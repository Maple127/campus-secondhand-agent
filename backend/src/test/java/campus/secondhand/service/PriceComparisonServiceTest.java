package campus.secondhand.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 比价分位数算法测试。
 *
 * 比价结论会直接展示给用户，并会被 LLM 转述，
 * 因此分位数计算的边界必须锁死 —— 一旦算错，agent 会自信地说出错误的价格建议。
 */
class PriceComparisonServiceTest {

    private static BigDecimal bd(String v) {
        return new BigDecimal(v);
    }

    @Test
    @DisplayName("单元素列表返回该元素")
    void singleElement() {
        assertEquals(bd("10.00"),
                PriceComparisonService.percentile(List.of(bd("10")), 0.5));
    }

    @Test
    @DisplayName("空列表返回 null 而不是抛异常")
    void emptyList() {
        assertNull(PriceComparisonService.percentile(List.of(), 0.5));
    }

    @Test
    @DisplayName("中位数：奇数个取中间值")
    void medianOddCount() {
        List<BigDecimal> prices = List.of(bd("10"), bd("20"), bd("30"));
        assertEquals(bd("20.00"), PriceComparisonService.percentile(prices, 0.50));
    }

    @Test
    @DisplayName("中位数：偶数个取中间两值平均")
    void medianEvenCount() {
        List<BigDecimal> prices = List.of(bd("10"), bd("20"), bd("30"), bd("40"));
        assertEquals(bd("25.00"), PriceComparisonService.percentile(prices, 0.50));
    }

    @Test
    @DisplayName("分位数：线性插值")
    void percentileInterpolation() {
        List<BigDecimal> prices = List.of(bd("10"), bd("20"), bd("30"), bd("40"));
        // pos = 0.25 * 3 = 0.75 -> 10 + (20-10)*0.75 = 17.5
        assertEquals(bd("17.50"), PriceComparisonService.percentile(prices, 0.25));
        // pos = 0.75 * 3 = 2.25 -> 30 + (40-30)*0.25 = 32.5
        assertEquals(bd("32.50"), PriceComparisonService.percentile(prices, 0.75));
    }

    @Test
    @DisplayName("最小/最大分位")
    void extremes() {
        List<BigDecimal> prices = List.of(bd("5"), bd("15"), bd("25"));
        assertEquals(bd("5.00"), PriceComparisonService.percentile(prices, 0.0));
        assertEquals(bd("25.00"), PriceComparisonService.percentile(prices, 1.0));
    }

    @Test
    @DisplayName("结果保留两位小数并四舍五入")
    void rounding() {
        List<BigDecimal> prices = List.of(bd("10"), bd("11"));
        // pos = 0.5 * 1 = 0.5 -> (10+11)/2 = 10.5
        assertEquals(bd("10.50"), PriceComparisonService.percentile(prices, 0.50));
    }

    @Test
    @DisplayName("相同价格不产生误差")
    void identicalPrices() {
        List<BigDecimal> prices = List.of(bd("20"), bd("20"), bd("20"), bd("20"));
        assertEquals(bd("20.00"), PriceComparisonService.percentile(prices, 0.25));
        assertEquals(bd("20.00"), PriceComparisonService.percentile(prices, 0.75));
    }
}
