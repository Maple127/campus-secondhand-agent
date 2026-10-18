package campus.secondhand.entity;

import jakarta.persistence.*;
import lombok.Data;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@Entity
@Table(name = "product", indexes = {
        @Index(name = "idx_product_status", columnList = "status"),
        @Index(name = "idx_product_seller", columnList = "seller_id"),
        @Index(name = "idx_product_sold_order", columnList = "sold_order_id"),
        // 搜索页的"分类 + 价格区间"筛选、以及比价取样，都走这组条件
        @Index(name = "idx_product_filter", columnList = "status,category_name,price"),
        // 品类词既用于搜索匹配，也用于比价取样
        @Index(name = "idx_product_type", columnList = "product_type")
})
public class Product {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 商品名称 */
    @Column(nullable = false)
    private String name;

    /** 商品描述 */
    @Column(length = 2000)
    private String description;

    /** 商品价格 */
    @Column(precision = 10, scale = 2)
    private BigDecimal price;

    /** 商品原价（可选，用于比价时展示折扣） */
    @Column(name = "original_price", precision = 10, scale = 2)
    private BigDecimal originalPrice;

    /** 成色，例如：全新 / 9成新 / 7成新。比价的核心维度之一 */
    @Column(name = "condition_level", length = 20)
    private String conditionLevel;

    /** 商品图片访问路径，例如 /uploads/xxx.jpg */
    private String image;

    /** 商品分类：教材、数码、出行、宿舍 */
    private String category;

    /** 交易地点 */
    private String location;

    /** 卖家ID */
    @Column(name = "seller_id")
    private Long sellerId;

    /** 卖家用户名 */
    private String sellerName;

    /** 分类ID */
    @Column(name = "category_id")
    private Long categoryId;

    /**
     * 品类词：比分类细一档的"这东西到底是什么"，例如「耳机」「充电宝」「平板」。
     *
     * 存在的理由只有一个：**让「耳机」能搜到《AirPods Pro 2代》**。
     * 分类太粗（数码电子把 iPad / 鼠标 / 耳机放在一起），
     * 而买家搜索时用的是具体品类词，标题里却常常没有那个词。
     *
     * 值取自 product_type.name（词表见 product_type 表）。
     * 允许为空：宁可让商品发出去、品类后补，也不要卡住发布。
     */
    @Column(name = "product_type", length = 32)
    private String productType;

    /** 分类名称 */
    private String categoryName;

    /** 卖家电话 */
    private String sellerPhone;

    /**
     * 审核/售卖状态，取值语义见 {@link ProductStatus}：
     * 0-待审核，1-在售，2-已拒绝，3-已下架，4-已售出。
     */
    @Column(nullable = false)
    private Integer status = ProductStatus.PENDING_APPROVAL.code();

    /** 拒绝原因 */
    private String rejectReason;

    /**
     * 售出时锁定的订单ID。
     * 配合 SOLD 状态使用，是修复"一物多卖"的关键字段：
     * 一旦写入，其他订单无法再对该商品下单。
     */
    @Column(name = "sold_order_id")
    private Long soldOrderId;

    /**
     * 乐观锁版本号。
     * 并发下单/审核时由 Hibernate 自动校验，冲突抛 OptimisticLockException，
     * 避免两个买家同时把同一件商品标记为已售。
     */
    @Version
    @Column(nullable = false)
    private Integer version = 0;

    @CreationTimestamp
    @Column(updatable = false)
    private LocalDateTime createTime;

    @UpdateTimestamp
    private LocalDateTime updateTime;

    // ==================== 领域行为：把状态机收敛在实体内部 ====================

    @Transient
    public ProductStatus statusEnum() {
        return ProductStatus.of(this.status);
    }

    public void applyStatus(ProductStatus next) {
        this.status = next.code();
    }

    /** 管理员审核通过 */
    public void approve() {
        requireState(statusEnum().canApprove(), "只有待审核商品可以审核通过");
        applyStatus(ProductStatus.ON_SALE);
        this.rejectReason = null;
    }

    /** 管理员审核拒绝 / 举报核实违规下架 */
    public void reject(String reason) {
        requireState(statusEnum().canReject(), "当前状态不允许拒绝：" + statusEnum().label());
        applyStatus(ProductStatus.REJECTED);
        this.rejectReason = reason;
    }

    /** 卖家主动下架 */
    public void delist() {
        requireState(statusEnum().canDelist(), "只有在售商品可以下架");
        applyStatus(ProductStatus.DELISTED);
    }

    /** 重新提交审核 */
    public void relist() {
        requireState(statusEnum().canRelist(), "当前状态不允许重新上架：" + statusEnum().label());
        applyStatus(ProductStatus.PENDING_APPROVAL);
        this.rejectReason = null;
    }

    /**
     * 标记售出并锁定订单。
     * 并发安全由 {@link #version} 乐观锁保证。
     */
    public void markSold(Long orderId) {
        requireState(statusEnum().canBeOrdered(),
                "商品当前不可下单（状态：" + statusEnum().label() + "）");
        requireState(this.soldOrderId == null, "商品已关联其他订单");
        applyStatus(ProductStatus.SOLD);
        this.soldOrderId = orderId;
    }

    /** 订单取消/退款后释放商品，使其重新可售 */
    public void releaseFromOrder(Long orderId) {
        requireState(this.soldOrderId != null && this.soldOrderId.equals(orderId),
                "订单与商品锁定关系不一致，拒绝释放");
        this.soldOrderId = null;
        applyStatus(ProductStatus.ON_SALE);
    }

    public boolean isOwnedBy(Long userId) {
        return userId != null && userId.equals(this.sellerId);
    }

    private static void requireState(boolean condition, String message) {
        if (!condition) {
            throw new IllegalStateException(message);
        }
    }
}
