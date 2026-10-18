package campus.secondhand.service;

import campus.secondhand.entity.Product;
import campus.secondhand.repository.ProductRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 议价建议的定价逻辑测试。
 *
 * 这块特别值得测：给用户的三档价是**具体金额**，算错了用户会照着去砍价，
 * 而且很难事后发现。规则只有四条，但边界很容易写错：
 *   · 挂牌价 ≤ 中位价 → 劝你别砍
 *   · 挂牌价在 (中位价, p75] → 有谈的空间
 *   · 挂牌价 > p75 → 明显偏贵
 *   · 样本不足 → 不给数字
 */
class NegotiationServiceTest {

    private ProductService productService;
    private PriceComparisonService priceComparisonService;
    private ProductRepository productRepository;
    private NegotiationService service;

    @BeforeEach
    void setUp() {
        productService = mock(ProductService.class);
        priceComparisonService = mock(PriceComparisonService.class);
        productRepository = mock(ProductRepository.class);
        service = new NegotiationService(productRepository, productService, priceComparisonService);
    }

    private static BigDecimal bd(String v) {
        return new BigDecimal(v);
    }

    private static Product product(long id, String name, String price, String type) {
        Product p = new Product();
        p.setId(id);
        p.setName(name);
        p.setPrice(price == null ? null : bd(price));
        p.setProductType(type);
        p.setLocation("南门");
        p.setCreateTime(LocalDateTime.now().minusDays(30));
        return p;
    }

    /** 构造一个比价结果：p25 / median / p75 由调用方决定 */
    private static PriceComparison cmp(String p25, String median, String p75, int samples) {
        return new PriceComparison(
                "数码电子", "9成新", samples,
                bd("45"), bd(p25), bd(median), bd(p75), bd("1150"),
                bd(p25), bd(p75), "FAIR", "x", List.of());
    }

    // =====================================================================

    @Test
    @DisplayName("挂牌价不高于中位价时，劝用户别砍")
    void fairPriceDiscouragesHaggling() {
        Product p = product(1, "罗技G304", "105", "鼠标");
        when(productService.getVisibleById(1L)).thenReturn(p);
        when(priceComparisonService.compareFor(any(), anyInt()))
                .thenReturn(cmp("95", "120", "180", 5));
        when(productRepository.countCheaper(anyInt(), any(), any(), anyLong())).thenReturn(2L);

        NegotiationAdvice a = service.adviceFor(1L);

        assertEquals("FAIR", a.verdict());
        // 目标价就是挂牌价 —— 不要让人去砍一个本来合理的价
        assertEquals(0, a.suggestedTarget().compareTo(bd("105")));
        assertTrue(a.script().contains("实在"), "话术应该肯定这个价格：" + a.script());
        assertFalse(a.script().contains("比这个便宜一些"), "合理价位不该拿便宜货去压价");
    }

    @Test
    @DisplayName("挂牌价高于 p75 时判偏贵，目标价取中位价")
    void expensiveAboveP75() {
        Product p = product(2, "AirPods Pro 2代", "680", "耳机");
        when(productService.getVisibleById(2L)).thenReturn(p);
        when(priceComparisonService.compareFor(any(), anyInt()))
                .thenReturn(cmp("90", "380", "650", 7));
        when(productRepository.countCheaper(anyInt(), any(), any(), anyLong())).thenReturn(5L);

        NegotiationAdvice a = service.adviceFor(2L);

        assertEquals("EXPENSIVE", a.verdict());
        assertEquals(0, a.suggestedTarget().compareTo(bd("380")), "目标价应是中位价");
        assertEquals(0, a.walkAway().compareTo(bd("650")), "止损价应是 p75");
        // 试探价 = 中位价 × 0.9，且不低于 p25
        assertEquals(0, a.suggestedOpen().compareTo(bd("342")));
        assertTrue(a.suggestedOpen().compareTo(a.suggestedTarget()) <= 0);
        assertTrue(a.reasoning().contains("5 件更便宜"), a.reasoning());
    }

    @Test
    @DisplayName("挂牌价在 (中位价, p75] 之间时判略高")
    void slightlyHighBetweenMedianAndP75() {
        Product p = product(3, "机械键盘", "420", "键盘");
        when(productService.getVisibleById(3L)).thenReturn(p);
        when(priceComparisonService.compareFor(any(), anyInt()))
                .thenReturn(cmp("255", "380", "680", 6));
        when(productRepository.countCheaper(anyInt(), any(), any(), anyLong())).thenReturn(5L);

        NegotiationAdvice a = service.adviceFor(3L);

        assertEquals("SLIGHTLY_HIGH", a.verdict());
        assertEquals(0, a.suggestedTarget().compareTo(bd("380")));
        assertEquals(0, a.walkAway().compareTo(bd("680")));
    }

    @Test
    @DisplayName("样本不足时不给任何金额")
    void insufficientSamplesReturnsNoNumbers() {
        Product p = product(4, "冷门相机", "1500", "相机");
        when(productService.getVisibleById(4L)).thenReturn(p);
        when(priceComparisonService.compareFor(any(), anyInt()))
                .thenReturn(cmp("900", "1200", "1600", 2));

        NegotiationAdvice a = service.adviceFor(4L);

        assertEquals("UNKNOWN", a.verdict());
        assertNull(a.suggestedOpen(), "样本不足时绝不能编一个数字");
        assertNull(a.suggestedTarget());
        assertNull(a.walkAway());
        assertFalse(a.reasoning().isBlank());
    }

    @Test
    @DisplayName("试探价必须落在 [p25, 挂牌价] 之间")
    void openPriceIsClamped() {
        Product p = product(5, "廉价耳机", "100", "耳机");
        when(productService.getVisibleById(5L)).thenReturn(p);
        // 中位价远高于挂牌价 → 按规则会算出一个比挂牌价还高的试探价
        when(priceComparisonService.compareFor(any(), anyInt()))
                .thenReturn(cmp("90", "380", "650", 6));
        when(productRepository.countCheaper(anyInt(), any(), any(), anyLong())).thenReturn(0L);

        NegotiationAdvice a = service.adviceFor(5L);

        // 挂牌价 100 ≤ 中位价 380 → FAIR，试探价不该超过挂牌价
        assertEquals("FAIR", a.verdict());
        assertTrue(a.suggestedOpen().compareTo(a.askingPrice()) <= 0,
                "试探价 " + a.suggestedOpen() + " 不应高于挂牌价 " + a.askingPrice());
    }

    @Test
    @DisplayName("没有价格的商品给出明确原因而不是零")
    void noPriceGivesReason() {
        Product p = product(6, "面议商品", null, "其他");
        when(productService.getVisibleById(6L)).thenReturn(p);

        NegotiationAdvice a = service.adviceFor(6L);

        assertEquals("UNKNOWN", a.verdict());
        assertTrue(a.reasoning().contains("没有标价"), a.reasoning());
    }
}
