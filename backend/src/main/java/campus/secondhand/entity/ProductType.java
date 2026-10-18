package campus.secondhand.entity;

import jakarta.persistence.*;
import lombok.Data;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * 品类词（product_type）——比分类细一档的"这个东西到底是什么"。
 *
 * ## 为什么需要它
 *
 * 分类只有 6 个（图书教材 / 数码电子 / …），而买家搜索时用的是**具体品类词**：
 * 「耳机」「充电宝」「平板」。用户搜「耳机」时，《AirPods Pro 2代》的标题里
 * 根本没有"耳机"两个字，所以 `LIKE %耳机%` 命中 0 条 —— 这是评测里
 * lookup 失败的主因（L05 耳机）。
 *
 * 加一层品类词 + 别名，就把"词汇缺口"从**代码问题**变成**数据问题**：
 * 补一个别名是一行数据，不需要改检索逻辑，也不需要上向量检索。
 *
 * ## aliases 为什么用逗号分隔而不是 JSON
 *
 * 后台管理员编辑的是人，不是程序。`蓝牙耳机,airpods,苹果耳机` 比
 * `["蓝牙耳机","airpods"]` 更好改、更不容易写坏。解析只有一个 split。
 */
@Data
@Entity
@Table(name = "product_type", indexes = {
        @Index(name = "idx_ptype_category", columnList = "category_id"),
        @Index(name = "idx_ptype_name", columnList = "name")
})
public class ProductType {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 挂在哪个分类下（可为空，表示全局通用词） */
    @Column(name = "category_id")
    private Long categoryId;

    /** 品类词本身，例如「耳机」。商品上的 product_type 存的就是这个值 */
    @Column(nullable = false, unique = true, length = 32)
    private String name;

    /** 别名，逗号分隔：蓝牙耳机,airpods,苹果耳机 */
    @Column(columnDefinition = "TEXT")
    private String aliases;

    @Column(name = "sort_order")
    private Integer sortOrder = 0;

    @CreationTimestamp
    @Column(name = "create_time", updatable = false)
    private LocalDateTime createTime;

    /** 拆别名。中英文逗号都认，顺手去空白、去空项、转小写 */
    public List<String> aliasList() {
        List<String> out = new ArrayList<>();
        if (aliases == null || aliases.isBlank()) {
            return out;
        }
        for (String part : aliases.split("[,，]")) {
            String a = part.trim();
            if (!a.isEmpty()) {
                out.add(a);
            }
        }
        return out;
    }

    /** 品类词 + 别名，统一小写，供匹配用 */
    public List<String> allWordsLower() {
        List<String> out = new ArrayList<>();
        out.add(name.toLowerCase());
        for (String a : aliasList()) {
            out.add(a.toLowerCase());
        }
        return out;
    }
}
