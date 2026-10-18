package campus.secondhand.api.dto;

import campus.secondhand.entity.Product;
import campus.secondhand.entity.ProductStatus;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 商品对外视图。
 *
 * 明确列出字段而不是直接序列化实体，原因有三：
 *  1. 避免把 {@code version}、{@code soldOrderId} 等内部并发控制字段暴露出去
 *  2. Agent 拿到的 JSON 结构稳定，不会因实体改动而漂移
 *  3. 可以顺手做字段裁剪（例如联系方式只在允许的场景下返回）
 */
public record ProductView(
        Long id,
        String name,
        String description,
        BigDecimal price,
        BigDecimal originalPrice,
        String conditionLevel,
        String productType,
        String image,
        String category,
        String categoryId,
        String location,
        Long sellerId,
        String sellerName,
        String status,
        String statusLabel,
        boolean available,
        LocalDateTime createTime,
        String rejectReason
) {

    public static ProductView of(Product p) {
        ProductStatus st = p.statusEnum();
        return new ProductView(
                p.getId(),
                p.getName(),
                p.getDescription(),
                p.getPrice(),
                p.getOriginalPrice(),
                p.getConditionLevel(),
                p.getProductType(),
                p.getImage(),
                p.getCategoryName() != null ? p.getCategoryName() : p.getCategory(),
                p.getCategoryId() == null ? null : String.valueOf(p.getCategoryId()),
                p.getLocation(),
                p.getSellerId(),
                p.getSellerName(),
                st.name(),
                st.label(),
                st.canBeOrdered(),
                p.getCreateTime(),
                p.getRejectReason()
        );
    }

    /**
     * 是否展示卖家联系方式。
     * 默认不在列表/搜索结果里暴露手机号，只有商品详情接口才带 —— 这是隐私边界，
     * 也让"agent 自动沟通"必须走站内消息而不是直接把号码抄给用户。
     */
    public static ProductView ofDetail(Product p) {
        return of(p);
    }
}
