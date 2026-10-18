package campus.secondhand.entity;

/**
 * 订单状态机。
 *
 * <pre>
 *   UNPAID ──pay──► PAID ──ship──► SHIPPED ──confirm──► COMPLETED
 *      │              │
 *      │cancel        │cancel(退款)
 *      ▼              ▼
 *   CANCELLED     CANCELLED
 * </pre>
 *
 * 数据库中以字符串存储，与原实现保持一致（原 Order.status 就是 String）。
 */
public enum OrderStatus {

    UNPAID("待付款"),
    PAID("已付款"),
    SHIPPED("已发货"),
    COMPLETED("已完成"),
    CANCELLED("已取消");

    private final String label;

    OrderStatus(String label) {
        this.label = label;
    }

    public String label() {
        return label;
    }

    public static OrderStatus of(String value) {
        if (value == null || value.isBlank()) {
            return UNPAID;
        }
        for (OrderStatus s : values()) {
            if (s.name().equalsIgnoreCase(value)) {
                return s;
            }
        }
        throw new IllegalArgumentException("未知的订单状态: " + value);
    }

    /** 仅买家、且订单未支付时可直接取消（不涉及退款） */
    public boolean canCancelWithoutRefund() {
        return this == UNPAID;
    }

    /** 只有已付款订单可发货 */
    public boolean canShip() {
        return this == PAID;
    }

    public boolean isPayable() {
        return this == UNPAID;
    }
}
