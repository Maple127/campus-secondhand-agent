package campus.secondhand.api.rest;

import campus.secondhand.api.ApiResponse;
import campus.secondhand.api.dto.OrderView;
import campus.secondhand.common.BusinessException;
import campus.secondhand.entity.Order;
import campus.secondhand.entity.Product;
import campus.secondhand.security.ActorContextHolder;
import campus.secondhand.service.CreateOrderCommand;
import campus.secondhand.service.OrderService;
import campus.secondhand.service.ProductService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 订单 REST 接口（供 AI Agent 调用）。
 *
 * 明确的边界：**不提供支付接口**。
 * 支付需要用户本人在页面上输入支付密码，agent 无权代付。
 */
@RestController
@RequestMapping("/api/v1/orders")
@RequiredArgsConstructor
public class OrderRestController {

    private final OrderService orderService;
    private final ProductService productService;

    /** 我的订单（买入 / 卖出） */
    @GetMapping
    public ApiResponse<List<OrderView>> myOrders(@RequestParam(defaultValue = "buyer") String role) {
        var actor = ActorContextHolder.current();
        List<Order> orders = "seller".equalsIgnoreCase(role)
                ? orderService.listSoldBy(actor.id())
                : orderService.listBoughtBy(actor.id());
        return ApiResponse.ok(toViews(orders));
    }

    /** 订单详情（仅买卖双方可见） */
    @GetMapping("/{orderNo}")
    public ApiResponse<OrderView> detail(@PathVariable String orderNo) {
        var actor = ActorContextHolder.current();
        Order order = orderService.getForParticipant(orderNo, actor.id());
        return ApiResponse.ok(OrderView.of(order, productService.findByIdOrNull(order.getProductId())));
    }

    /**
     * 创建订单。
     *
     * 会锁定商品（status → 已售出），因此这是需要用户确认的写操作。
     */
    @PostMapping
    public ApiResponse<OrderView> create(@RequestBody CreateOrderRequest req) {
        var actor = ActorContextHolder.current();

        LocalDateTime appointment = null;
        if (req.appointmentTime() != null && !req.appointmentTime().isBlank()) {
            try {
                appointment = LocalDateTime.parse(req.appointmentTime());
            } catch (Exception e) {
                throw BusinessException.badRequest("预约时间格式应为 2026-01-01T10:00");
            }
        }

        Order order = orderService.create(
                CreateOrderCommand.of(req.productId(), req.deliveryType(), appointment),
                actor.id(), actor.name(), actor);

        return ApiResponse.ok(OrderView.of(order,
                productService.findByIdOrNull(order.getProductId())));
    }

    /** 取消订单（未付款） */
    @PostMapping("/{orderNo}/cancel")
    public ApiResponse<OrderView> cancel(@PathVariable String orderNo,
                                         @RequestBody(required = false) CancelRequest req) {
        var actor = ActorContextHolder.current();
        String reason = req == null ? null : req.reason();
        Order order = orderService.cancel(orderNo, actor.id(), reason, actor);
        return ApiResponse.ok(OrderView.of(order,
                productService.findByIdOrNull(order.getProductId())));
    }

    private List<OrderView> toViews(List<Order> orders) {
        var productMap = orderService.productMapFor(orders);
        return orders.stream()
                .map(o -> OrderView.of(o, productMap.get(o.getProductId())))
                .toList();
    }

    public record CreateOrderRequest(
            Long productId,
            String deliveryType,
            String appointmentTime
    ) {
    }

    public record CancelRequest(String reason) {
    }
}
