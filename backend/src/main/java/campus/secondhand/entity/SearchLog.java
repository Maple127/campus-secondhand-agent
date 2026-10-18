package campus.secondhand.entity;

import jakarta.persistence.*;
import lombok.Data;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

/**
 * 搜索日志：记录买家到底搜了什么、搜到了几件。
 *
 * ## 为什么值得为它建一张表
 *
 * 品类词表是我们手写的 28 个词，覆盖了现在这 22 件商品。
 * 但真实用户会怎么叫这些东西，我们猜不全 ——
 * 「收纳箱」还是「整理箱」？「充电宝」还是「移动电源」？
 *
 * 与其继续猜，不如记录。**搜索日志就是词表的采购清单**：
 * 某天发现「显示器」被搜了 12 次、每次 0 结果，那要么补词，要么补货。
 *
 * ## 只记有关键词的搜索
 *
 * 打开首页（没有关键词）不记：那是浏览，不是搜索，记下来只会淹没真正的信号。
 *
 * ## result_count 的两个用途
 *
 * = 0  → 词表缺词，或者平台缺货（两种情况处理方式不同，所以两种都值得看）
 * 很小 → 有货但少，可能是供给问题，也可能是分类/品类没对上
 */
@Data
@Entity
@Table(name = "search_log", indexes = {
        @Index(name = "idx_slog_keyword", columnList = "keyword"),
        @Index(name = "idx_slog_result", columnList = "result_count"),
        @Index(name = "idx_slog_time", columnList = "create_time")
})
public class SearchLog {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 用户输入的原始关键词（已去空白、截断到 100 字） */
    @Column(length = 100)
    private String keyword;

    /** 搜索时选中的分类，可为空 */
    @Column(length = 50)
    private String category;

    /** 这次搜索命中了几件（0 是我们最关心的） */
    @Column(name = "result_count", nullable = false)
    private Integer resultCount;

    /** 来源：web（网页搜索框）| agent（AI 助手代搜） */
    @Column(length = 16)
    private String source;

    /**
     * 零结果的原因分类，用来区分"缺货"和"缺词"：
     *
     *   TYPE_EMPTY —— 词表认识这个说法（比如「显示器」），但平台没有这类货 → 运营问题
     *   NO_TYPE    —— 词表不认识这个说法 → 补别名，一行 SQL 就能修
     *
     * 有结果时为 null。
     */
    @Column(length = 16)
    private String hint;

    /** 谁搜的：登录用户名，或 agent 的身份名。便于判断是不是同一个人的重复搜索 */
    @Column(length = 64)
    private String actor;

    /**
     * 建表时带默认值，避免"用 SQL 直接插入没写时间"→ 零日期 → JDBC 读取报错。
     * 这个坑在 product_type 表上已经踩过一次。
     */
    @CreationTimestamp
    @Column(name = "create_time", updatable = false,
            columnDefinition = "datetime(6) default current_timestamp(6)")
    private LocalDateTime createTime;
}
