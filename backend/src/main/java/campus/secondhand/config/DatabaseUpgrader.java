package campus.secondhand.config;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * 数据库幂等升级器。
 *
 * 为什么不用 Flyway：本项目用 {@code ddl-auto=update}，新增实体字段由 Hibernate 负责，
 * 但**索引、回填、数据修复**这类操作 Hibernate 不会做，必须自己保证幂等。
 *
 * 与原实现的差别：
 *  - 去掉了每次启动都执行的 migrateOldCategoryData()（它会把 category 字段反复
 *    改写成标准名，属于一次性迁移，已由 schema 脚本完成）；
 *  - 所有 DDL 都有 columnExists/indexExists 保护，可重复执行；
 *  - 新增 v0.2 的商品状态机与审计日志相关结构。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class DatabaseUpgrader implements ApplicationRunner {

    private final JdbcTemplate jdbcTemplate;

    @Override
    public void run(ApplicationArguments args) {
        // v0.1 遗留：分类关联字段
        upgradeProductCategoryColumns();
        ensureCategoryTable();

        // v0.2：商品状态机 / 售出锁定 / 比价字段
        upgradeProductStatusColumns();

        // v0.2：审计日志
        ensureAuditLogTable();

        // v0.2：历史脏数据修复
        repairLegacyData();
    }

    // ==================== v0.1 ====================

    private void upgradeProductCategoryColumns() {
        addColumnIfMissing("product", "category_id", "BIGINT COMMENT '分类ID'");
        addColumnIfMissing("product", "category_name", "VARCHAR(50) COMMENT '分类名称'");
        createIndexIfMissing("idx_product_category_id", "product", "category_id");
    }

    private void ensureCategoryTable() {
        jdbcTemplate.execute("CREATE TABLE IF NOT EXISTS category (" +
                "id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID'," +
                "name VARCHAR(50) NOT NULL UNIQUE COMMENT '分类名称'," +
                "description VARCHAR(255) COMMENT '分类描述'," +
                "create_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'" +
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
        insertCategoryIfNotExist(1, "图书教材", "教材、教辅、课外书等");
        insertCategoryIfNotExist(2, "数码电子", "手机、电脑、耳机、配件等");
        insertCategoryIfNotExist(3, "生活用品", "宿舍收纳、日用品、小家电等");
        insertCategoryIfNotExist(4, "体育器材", "运动装备、健身器材、出行工具等");
        insertCategoryIfNotExist(5, "服装鞋帽", "衣物、鞋帽、配饰等");
        insertCategoryIfNotExist(6, "其他", "无法归类的闲置物品");
    }

    // ==================== v0.2 ====================

    private void upgradeProductStatusColumns() {
        // 售出锁定的订单ID —— 修复"一物多卖"的核心字段
        addColumnIfMissing("product", "sold_order_id", "BIGINT COMMENT '售出锁定的订单ID'");
        // 乐观锁版本号：Hibernate @Version 需要该列存在且非空
        addColumnIfMissing("product", "version", "INT NOT NULL DEFAULT 0 COMMENT '乐观锁版本'");
        // 比价维度
        addColumnIfMissing("product", "condition_level", "VARCHAR(20) COMMENT '成色'");
        addColumnIfMissing("product", "original_price", "DECIMAL(10,2) COMMENT '原价'");
        addColumnIfMissing("product", "update_time", "DATETIME COMMENT '更新时间'");

        createIndexIfMissing("idx_product_status", "product", "status");
        createIndexIfMissing("idx_product_seller", "product", "seller_id");
        createIndexIfMissing("idx_product_sold_order", "product", "sold_order_id");

        // 订单表原本没有索引，列表查询会全表扫描
        createIndexIfMissing("idx_orders_buyer", "orders", "user_id");
        createIndexIfMissing("idx_orders_seller", "orders", "seller_id");
        createIndexIfMissing("idx_orders_product", "orders", "product_id");

        // 回填：update_time 为空则用 create_time 初始化；version 为空置 0
        jdbcTemplate.update("UPDATE product SET update_time = create_time " +
                "WHERE update_time IS NULL AND create_time IS NOT NULL");
        jdbcTemplate.update("UPDATE product SET version = 0 WHERE version IS NULL");
    }

    private void ensureAuditLogTable() {
        jdbcTemplate.execute("CREATE TABLE IF NOT EXISTS audit_log (" +
                "id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID'," +
                "actor_type VARCHAR(16) NOT NULL COMMENT 'USER/ADMIN/AGENT/SYSTEM'," +
                "actor_id BIGINT COMMENT '操作主体ID'," +
                "actor_name VARCHAR(255) COMMENT '操作主体名称'," +
                "action VARCHAR(64) NOT NULL COMMENT '动作，如 product.publish'," +
                "target_type VARCHAR(32) COMMENT '目标资源类型'," +
                "target_id BIGINT COMMENT '目标资源ID'," +
                "detail VARCHAR(2000) COMMENT '调用参数(JSON)'," +
                "result VARCHAR(16) NOT NULL DEFAULT 'SUCCESS' COMMENT 'SUCCESS/FAILURE'," +
                "error_message VARCHAR(500) COMMENT '失败原因'," +
                "conversation_id VARCHAR(64) COMMENT 'Agent 会话ID'," +
                "create_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '发生时间'," +
                "INDEX idx_audit_actor (actor_type, actor_id)," +
                "INDEX idx_audit_action (action)," +
                "INDEX idx_audit_target (target_type, target_id)," +
                "INDEX idx_audit_conversation (conversation_id)" +
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='操作审计日志'");
    }

    /**
     * 修复历史脏数据。
     *
     * 原实现允许多个订单指向同一商品，且商品状态不随成交变化。
     * 这里把"已存在 PAID/SHIPPED/COMPLETED 订单的商品"统一置为已售出(4)
     * 并锁定到最早的已付订单，避免升级后出现"商品在售但已有成交订单"的矛盾数据。
     */
    private void repairLegacyData() {
        if (!tableExists("orders")) {
            return;
        }
        int locked = jdbcTemplate.update(
                "UPDATE product p " +
                        "JOIN (SELECT product_id, MIN(id) AS oid FROM orders " +
                        "      WHERE status IN ('PAID','SHIPPED','COMPLETED') GROUP BY product_id) o " +
                        "  ON p.id = o.product_id " +
                        "SET p.status = 4, p.sold_order_id = o.oid " +
                        "WHERE p.sold_order_id IS NULL AND p.status = 1");
        if (locked > 0) {
            log.warn("数据修复：{} 件商品因存在已支付订单被标记为已售出", locked);
        }
    }

    // ==================== 工具方法 ====================

    private boolean columnExists(String table, String column) {
        if (!tableExists(table)) {
            return false;
        }
        String sql = "SELECT COUNT(*) FROM information_schema.COLUMNS " +
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND COLUMN_NAME = ?";
        Integer count = jdbcTemplate.queryForObject(sql, Integer.class, table, column);
        return count != null && count > 0;
    }

    private boolean indexExists(String table, String indexName) {
        if (!tableExists(table)) {
            return false;
        }
        String sql = "SELECT COUNT(*) FROM information_schema.STATISTICS " +
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND INDEX_NAME = ?";
        Integer count = jdbcTemplate.queryForObject(sql, Integer.class, table, indexName);
        return count != null && count > 0;
    }

    private void addColumnIfMissing(String table, String column, String definition) {
        if (!tableExists(table)) {
            return;
        }
        if (!columnExists(table, column)) {
            jdbcTemplate.execute("ALTER TABLE " + table + " ADD COLUMN " + column + " " + definition);
            log.info("新增列 {}.{}", table, column);
        }
    }

    private void createIndexIfMissing(String indexName, String table, String column) {
        if (!tableExists(table) || indexExists(table, indexName)) {
            return;
        }
        try {
            jdbcTemplate.execute("CREATE INDEX " + indexName + " ON " + table + "(" + column + ")");
            log.info("新增索引 {} on {}({})", indexName, table, column);
        } catch (Exception e) {
            log.warn("索引 {} 创建跳过：{}", indexName, e.getMessage());
        }
    }

    private boolean tableExists(String table) {
        Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM information_schema.TABLES " +
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ?",
                Integer.class, table);
        return count != null && count > 0;
    }

    private void insertCategoryIfNotExist(long id, String name, String desc) {
        jdbcTemplate.update(
                "INSERT IGNORE INTO category (id, name, description) VALUES (?, ?, ?)",
                id, name, desc
        );
    }
}
