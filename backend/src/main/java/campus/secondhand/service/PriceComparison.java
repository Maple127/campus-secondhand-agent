package campus.secondhand.service;

import java.math.BigDecimal;
import java.util.List;

/**
 * 比价结果。
 *
 * @param categoryName       参照的分类
 * @param conditionLevel     参照的成色（可能为 null，表示未按成色收窄）
 * @param sampleSize         参与统计的同类商品数量
 * @param min                最低价
 * @param p25                25 分位
 * @param median             中位数
 * @param p75                75 分位
 * @param max                最高价
 * @param suggestedLow       建议定价区间下界
 * @param suggestedHigh      建议定价区间上界
 * @param verdict            结论：LOW / FAIR / HIGH / INSUFFICIENT_DATA
 * @param explanation        面向用户/Agent 的自然语言解释（由后端生成，不交给 LLM 编造）
 * @param samples            参照样本（最多 5 条，用于展示）
 */
public record PriceComparison(
        String categoryName,
        String conditionLevel,
        int sampleSize,
        BigDecimal min,
        BigDecimal p25,
        BigDecimal median,
        BigDecimal p75,
        BigDecimal max,
        BigDecimal suggestedLow,
        BigDecimal suggestedHigh,
        String verdict,
        String explanation,
        List<Sample> samples
) {

    /**
     * 单个参照样本。
     */
    public record Sample(Long productId, String name, BigDecimal price, String conditionLevel, String statusLabel) {
    }

    public static final String VERDICT_INSUFFICIENT = "INSUFFICIENT_DATA";
    public static final String VERDICT_LOW = "LOW";
    public static final String VERDICT_FAIR = "FAIR";
    public static final String VERDICT_HIGH = "HIGH";
}
