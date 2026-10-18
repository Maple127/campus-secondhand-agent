package campus.secondhand.common;

import lombok.Getter;

import java.math.BigDecimal;

/**
 * 商品检索条件。
 *
 * 让网页端、REST 端和 Agent 工具共用同一套查询语义，
 * 避免"页面搜索"与"agent 搜索"两套逻辑漂移。
 */
@Getter
public class ProductQuery {

    /** 关键词，匹配名称/描述/地点 */
    private String keyword;

    /** 分类名称（精确匹配 categoryName） */
    private String categoryName;

    private BigDecimal minPrice;

    private BigDecimal maxPrice;

    /** 页码，从 0 开始 */
    private int page = 0;

    private int size = 8;

    /** 排序字段：createTime | price */
    private String sortBy = "createTime";

    /** 排序方向：desc | asc */
    private String direction = "desc";

    public static ProductQuery of(String keyword, String categoryName, int page, int size) {
        ProductQuery q = new ProductQuery();
        q.keyword = blankToNull(keyword);
        q.categoryName = blankToNull(categoryName);
        q.page = Math.max(page, 0);
        q.size = size <= 0 ? 8 : Math.min(size, 100);
        return q;
    }

    public ProductQuery withPriceRange(BigDecimal min, BigDecimal max) {
        this.minPrice = min;
        this.maxPrice = max;
        return this;
    }

    public ProductQuery withSort(String sortBy, String direction) {
        if (sortBy != null && !sortBy.isBlank()) {
            this.sortBy = sortBy;
        }
        if (direction != null && !direction.isBlank()) {
            this.direction = direction;
        }
        return this;
    }

    public ProductQuery withPage(int page, int size) {
        this.page = Math.max(page, 0);
        if (size > 0) {
            this.size = Math.min(size, 100);
        }
        return this;
    }

    private static String blankToNull(String s) {
        return (s == null || s.isBlank()) ? null : s.trim();
    }
}
