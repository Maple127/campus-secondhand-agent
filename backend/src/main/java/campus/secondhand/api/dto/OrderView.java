package campus.secondhand.api.dto;

import campus.secondhand.entity.Order;
import campus.secondhand.entity.OrderStatus;
import campus.secondhand.entity.Product;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 订单对外视图。
 */
public record OrderView(
        Long id,
        String orderNo,
        Long productId,
        String productName,
        Long buyerId,
        Long sellerId,
        BigDecimal price,
        String status,
        String statusLabel,
        String deliveryType,
        LocalDateTime appointmentTime,
        LocalDateTime createTime,
        LocalDateTime payTime,
        String cancelReason
) {

    public static OrderView of(Order o, Product product) {
        OrderStatus st = o.statusEnum();
        return new OrderView(
                o.getId(),
                o.getOrderNo(),
                o.getProductId(),
                product == null ? null : product.getName(),
                o.getUserId(),
                o.getSellerId(),
                o.getPrice(),
                st.name(),
                st.label(),
                o.getDeliveryType(),
                o.getAppointmentTime(),
                o.getCreateTime(),
                o.getPayTime(),
                o.getCancelReason()
        );
    }
}
