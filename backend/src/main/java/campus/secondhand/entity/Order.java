package campus.secondhand.entity;

import jakarta.persistence.*;
import lombok.Data;
import org.hibernate.annotations.CreationTimestamp;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@Entity
@Table(name = "orders", indexes = {
        @Index(name = "idx_orders_buyer", columnList = "user_id"),
        @Index(name = "idx_orders_seller", columnList = "seller_id"),
        @Index(name = "idx_orders_product", columnList = "product_id")
})
public class Order {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(unique = true)
    private String orderNo; // 订单编号

    @Column(name = "user_id")
    private Long userId;    // 买家ID

    @Column(name = "seller_id")
    private Long sellerId;  // 卖家ID

    @Column(name = "product_id")
    private Long productId; // 商品ID

    private BigDecimal price; // 下单价格

    /**
     * 修复点：原实现缺少 @CreationTimestamp，
     * 依赖调用方手动 setCreateTime，一旦漏设该字段就是 null，
     * 导致 findByUserIdOrderByCreateTimeDesc 排序结果不稳定。
     */
    @CreationTimestamp
    @Column(updatable = false)
    private LocalDateTime createTime;

    private LocalDateTime payTime;

    // 交易方式 (PICKUP / DELIVERY)
    private String deliveryType;

    // 预约交易时间
    private LocalDateTime appointmentTime;

    /**
     * 订单状态，取值见 {@link OrderStatus}：
     * UNPAID / PAID / SHIPPED / COMPLETED / CANCELLED
     */
    private String status;

    /** 取消/关闭原因（可选，便于排查与 agent 解释） */
    private String cancelReason;

    // ==================== 领域行为 ====================

    @Transient
    public OrderStatus statusEnum() {
        return OrderStatus.of(this.status);
    }

    public void pay() {
        requireState(statusEnum().isPayable(), "订单当前不可支付：" + statusEnum().label());
        this.status = OrderStatus.PAID.name();
        this.payTime = LocalDateTime.now();
    }

    public void ship() {
        requireState(statusEnum().canShip(), "只有已付款订单才能发货");
        this.status = OrderStatus.SHIPPED.name();
    }

    public void cancel(String reason) {
        requireState(statusEnum().canCancelWithoutRefund(),
                "只有待付款订单可以直接取消，已支付订单需走退款流程");
        this.status = OrderStatus.CANCELLED.name();
        this.cancelReason = reason;
    }

    public boolean belongsToBuyer(Long uid) {
        return uid != null && uid.equals(this.userId);
    }

    public boolean belongsToSeller(Long uid) {
        return uid != null && uid.equals(this.sellerId);
    }

    private static void requireState(boolean condition, String message) {
        if (!condition) {
            throw new IllegalStateException(message);
        }
    }
}
