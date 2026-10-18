package campus.secondhand.entity;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 订单状态机单元测试。
 */
class OrderStatusTest {

    private Order order(OrderStatus status) {
        Order o = new Order();
        o.setOrderNo("TEST-ORDER");
        o.setUserId(1L);
        o.setSellerId(2L);
        o.setProductId(3L);
        o.setStatus(status.name());
        return o;
    }

    @Test
    @DisplayName("只有待付款订单可支付，支付后记录 payTime")
    void payOnlyWhenUnpaid() {
        Order o = order(OrderStatus.UNPAID);
        o.pay();

        assertEquals(OrderStatus.PAID.name(), o.getStatus());
        assertNotNull(o.getPayTime());

        assertThrows(IllegalStateException.class, o::pay);
    }

    @Test
    @DisplayName("只有已付款订单可发货")
    void shipOnlyWhenPaid() {
        Order unpaid = order(OrderStatus.UNPAID);
        assertThrows(IllegalStateException.class, unpaid::ship);

        Order paid = order(OrderStatus.PAID);
        paid.ship();
        assertEquals(OrderStatus.SHIPPED.name(), paid.getStatus());
    }

    @Test
    @DisplayName("只有待付款订单可直接取消，已支付需走退款")
    void cancelOnlyWhenUnpaid() {
        Order unpaid = order(OrderStatus.UNPAID);
        unpaid.cancel("不想要了");
        assertEquals(OrderStatus.CANCELLED.name(), unpaid.getStatus());
        assertEquals("不想要了", unpaid.getCancelReason());

        Order paid = order(OrderStatus.PAID);
        IllegalStateException ex = assertThrows(IllegalStateException.class,
                () -> paid.cancel("后悔了"));
        assertTrue(ex.getMessage().contains("退款"));
    }

    @Test
    @DisplayName("状态字符串解析兼容大小写")
    void parseStatus() {
        assertEquals(OrderStatus.PAID, OrderStatus.of("paid"));
        assertEquals(OrderStatus.PAID, OrderStatus.of("PAID"));
        assertEquals(OrderStatus.UNPAID, OrderStatus.of(null));
        assertThrows(IllegalArgumentException.class, () -> OrderStatus.of("NOPE"));
    }

    @Test
    @DisplayName("买卖双方归属判断")
    void participation() {
        Order o = order(OrderStatus.UNPAID);
        assertTrue(o.belongsToBuyer(1L));
        assertFalse(o.belongsToBuyer(2L));
        assertTrue(o.belongsToSeller(2L));
        assertFalse(o.belongsToSeller(1L));
        assertFalse(o.belongsToBuyer(null));
    }
}
