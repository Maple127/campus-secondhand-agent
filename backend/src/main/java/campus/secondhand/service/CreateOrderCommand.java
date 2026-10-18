package campus.secondhand.service;

import java.time.LocalDateTime;

/**
 * 创建订单的入参。
 *
 * @param productId       商品ID
 * @param deliveryType    PICKUP（自取）/ DELIVERY（配送），默认 PICKUP
 * @param appointmentTime 预约交易时间，可为空（默认 1 小时后）
 */
public record CreateOrderCommand(
        Long productId,
        String deliveryType,
        LocalDateTime appointmentTime
) {

    public static final String PICKUP = "PICKUP";
    public static final String DELIVERY = "DELIVERY";

    public CreateOrderCommand {
        if (productId == null) {
            throw new IllegalArgumentException("商品ID不能为空");
        }
        if (deliveryType == null || deliveryType.isBlank()) {
            deliveryType = PICKUP;
        }
        if (appointmentTime == null) {
            appointmentTime = LocalDateTime.now().plusHours(1);
        }
    }

    public static CreateOrderCommand of(Long productId, String deliveryType, LocalDateTime appointmentTime) {
        return new CreateOrderCommand(productId, deliveryType, appointmentTime);
    }
}
