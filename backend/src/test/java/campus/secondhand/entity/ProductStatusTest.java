package campus.secondhand.entity;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 商品状态机单元测试。
 *
 * 这些断言锁定的是本次升级最关键的正确性保证：
 * 「一物多卖」在领域层就不可能发生。
 */
class ProductStatusTest {

    private Product product(ProductStatus status, Long sellerId) {
        Product p = new Product();
        p.setName("测试商品");
        p.setPrice(new BigDecimal("10.00"));
        p.setSellerId(sellerId);
        p.applyStatus(status);
        return p;
    }

    @Test
    @DisplayName("只有在售商品可以被下单")
    void onlyOnSaleCanBeOrdered() {
        assertTrue(product(ProductStatus.ON_SALE, 1L).statusEnum().canBeOrdered());
        assertFalse(product(ProductStatus.PENDING_APPROVAL, 1L).statusEnum().canBeOrdered());
        assertFalse(product(ProductStatus.REJECTED, 1L).statusEnum().canBeOrdered());
        assertFalse(product(ProductStatus.DELISTED, 1L).statusEnum().canBeOrdered());
        assertFalse(product(ProductStatus.SOLD, 1L).statusEnum().canBeOrdered());
    }

    @Test
    @DisplayName("markSold 会写入 sold_order_id 并切换到已售出")
    void markSoldLocksOrder() {
        Product p = product(ProductStatus.ON_SALE, 1L);
        p.markSold(99L);

        assertEquals(ProductStatus.SOLD.code(), p.getStatus());
        assertEquals(99L, p.getSoldOrderId());
    }

    @Test
    @DisplayName("已售出商品再次下单会被拒绝 —— 一物多卖的核心防护")
    void cannotSellTwice() {
        Product p = product(ProductStatus.ON_SALE, 1L);
        p.markSold(99L);

        IllegalStateException ex = assertThrows(IllegalStateException.class, () -> p.markSold(100L));
        assertTrue(ex.getMessage().contains("不可下单"));
        // 原有锁定关系不能被覆盖
        assertEquals(99L, p.getSoldOrderId());
    }

    @Test
    @DisplayName("未在售商品不能直接标记售出")
    void pendingProductCannotBeSold() {
        Product p = product(ProductStatus.PENDING_APPROVAL, 1L);
        assertThrows(IllegalStateException.class, () -> p.markSold(1L));
        assertNull(p.getSoldOrderId());
    }

    @Test
    @DisplayName("取消订单后商品可被释放回在售")
    void releaseFromOrderReturnsToOnSale() {
        Product p = product(ProductStatus.ON_SALE, 1L);
        p.markSold(7L);
        p.releaseFromOrder(7L);

        assertEquals(ProductStatus.ON_SALE.code(), p.getStatus());
        assertNull(p.getSoldOrderId());
        assertTrue(p.statusEnum().canBeOrdered());
    }

    @Test
    @DisplayName("释放时必须匹配订单，避免误释放他人锁定的商品")
    void releaseRequiresMatchingOrder() {
        Product p = product(ProductStatus.ON_SALE, 1L);
        p.markSold(7L);

        assertThrows(IllegalStateException.class, () -> p.releaseFromOrder(8L));
        assertEquals(7L, p.getSoldOrderId());
    }

    @Test
    @DisplayName("审核通过只能在待审核状态执行")
    void approveOnlyFromPending() {
        Product pending = product(ProductStatus.PENDING_APPROVAL, 1L);
        pending.approve();
        assertEquals(ProductStatus.ON_SALE.code(), pending.getStatus());

        Product sold = product(ProductStatus.SOLD, 1L);
        assertThrows(IllegalStateException.class, sold::approve);
    }

    @Test
    @DisplayName("已售出商品不能被审核拒绝，防止成交记录被改写")
    void cannotRejectSoldProduct() {
        Product sold = product(ProductStatus.SOLD, 1L);
        assertThrows(IllegalStateException.class, () -> sold.reject("理由"));
    }

    @Test
    @DisplayName("审核拒绝可作用于待审核与在售（后者用于举报核实违规）")
    void rejectFromPendingOrOnSale() {
        Product pending = product(ProductStatus.PENDING_APPROVAL, 1L);
        pending.reject("信息不实");
        assertEquals(ProductStatus.REJECTED.code(), pending.getStatus());
        assertEquals("信息不实", pending.getRejectReason());

        Product onSale = product(ProductStatus.ON_SALE, 1L);
        onSale.reject("举报核实违规");
        assertEquals(ProductStatus.REJECTED.code(), onSale.getStatus());
    }

    @Test
    @DisplayName("下架与重新上架的迁移规则")
    void delistAndRelistRules() {
        Product p = product(ProductStatus.ON_SALE, 1L);
        p.delist();
        assertEquals(ProductStatus.DELISTED.code(), p.getStatus());

        p.relist();
        assertEquals(ProductStatus.PENDING_APPROVAL.code(), p.getStatus());

        // 待审核状态不允许下架
        assertThrows(IllegalStateException.class, p::delist);
    }

    @Test
    @DisplayName("只有在售与已售出对公众可见")
    void visibilityRules() {
        assertTrue(ProductStatus.ON_SALE.isPubliclyVisible());
        assertTrue(ProductStatus.SOLD.isPubliclyVisible());
        assertFalse(ProductStatus.PENDING_APPROVAL.isPubliclyVisible());
        assertFalse(ProductStatus.REJECTED.isPubliclyVisible());
        assertFalse(ProductStatus.DELISTED.isPubliclyVisible());
    }

    @Test
    @DisplayName("状态码与数据库历史值兼容")
    void statusCodesStayCompatible() {
        assertEquals(0, ProductStatus.PENDING_APPROVAL.code());
        assertEquals(1, ProductStatus.ON_SALE.code());
        assertEquals(2, ProductStatus.REJECTED.code());
        assertEquals(3, ProductStatus.DELISTED.code());
        assertEquals(4, ProductStatus.SOLD.code());

        assertEquals(ProductStatus.ON_SALE, ProductStatus.of(1));
        assertEquals(ProductStatus.SOLD, ProductStatus.of(4));
    }

    @Test
    @DisplayName("未知状态码抛出明确异常")
    void unknownCodeRejected() {
        assertThrows(IllegalArgumentException.class, () -> ProductStatus.of(99));
    }

    @Test
    @DisplayName("归属判断")
    void ownershipCheck() {
        Product p = product(ProductStatus.ON_SALE, 5L);
        assertTrue(p.isOwnedBy(5L));
        assertFalse(p.isOwnedBy(6L));
        assertFalse(p.isOwnedBy(null));
    }
}
