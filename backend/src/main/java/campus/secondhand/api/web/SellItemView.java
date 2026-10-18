package campus.secondhand.api.web;

import campus.secondhand.entity.Order;
import campus.secondhand.entity.Product;
import campus.secondhand.entity.ProductStatus;

/**
 * 「我的订单 → 出售」里的一行：一件商品 + 它对应的订单（可能为 null）。
 *
 * 把"商品状态 + 订单状态"合成一个对人友好的阶段标签，放在 Java 里算，
 * 而不是散落在模板的 th:if 里 —— 这样状态映射只有一处，改起来不会漏。
 *
 * 卖家看到的四个阶段：
 *   待审核 / 出售中 / 已出售待交易 / 出售成功
 */
public record SellItemView(Product product, Order order, String stage, String stageClass, boolean needsShip) {

    public static SellItemView of(Product product, Order order) {
        ProductStatus ps = product.statusEnum();

        // 未进入交易的商品：状态完全由商品自身决定
        if (ps == ProductStatus.PENDING_APPROVAL) {
            return new SellItemView(product, null, "待审核", "pending", false);
        }
        if (ps == ProductStatus.REJECTED) {
            return new SellItemView(product, null, "审核未通过", "cancelled", false);
        }
        if (ps == ProductStatus.DELISTED) {
            return new SellItemView(product, null, "已下架", "cancelled", false);
        }
        if (ps == ProductStatus.ON_SALE) {
            return new SellItemView(product, null, "出售中", "onsale", false);
        }

        // 已售出：再看订单走到哪一步
        if (order == null) {
            // 数据异常兜底：商品标记已售但查不到订单
            return new SellItemView(product, null, "已出售待交易", "unpaid", false);
        }
        String os = order.getStatus();
        if ("UNPAID".equals(os)) {
            return new SellItemView(product, order, "已出售待交易", "unpaid", false);
        }
        if ("PAID".equals(os)) {
            // 买家已付款但卖家还没发货 —— 这是卖家最需要行动的一步
            return new SellItemView(product, order, "已出售待交易", "paid", true);
        }
        if ("SHIPPED".equals(os) || "COMPLETED".equals(os)) {
            return new SellItemView(product, order, "出售成功", "shipped", false);
        }
        if ("CANCELLED".equals(os)) {
            return new SellItemView(product, order, "订单已取消", "cancelled", false);
        }
        return new SellItemView(product, order, "已出售待交易", "unpaid", false);
    }

    /**
     * 购买侧的阶段标签。
     *   待支付 / 已支付待交易 / 购买成功 / 已取消
     */
    public static String buyStage(String orderStatus) {
        if (orderStatus == null) {
            return "未知";
        }
        return switch (orderStatus) {
            case "UNPAID" -> "待支付";
            case "PAID" -> "已支付待交易";
            case "SHIPPED" -> "已支付待交易";   // 已发货，在途
            case "COMPLETED" -> "购买成功";
            case "CANCELLED" -> "已取消";
            default -> "未知";
        };
    }

    /** 购买侧标签对应的样式类 */
    public static String buyStageClass(String orderStatus) {
        if (orderStatus == null) {
            return "unpaid";
        }
        return switch (orderStatus) {
            case "UNPAID" -> "unpaid";
            case "PAID", "SHIPPED" -> "paid";
            case "COMPLETED" -> "shipped";
            default -> "cancelled";
        };
    }
}
