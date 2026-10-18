package campus.secondhand.service;

import campus.secondhand.entity.Product;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * 比价服务（内部同类比价）。
 *
 * 设计原则：**所有数字都由后端算出来，LLM 只负责把它讲成人话。**
 * 这样即便模型产生幻觉，也编不出一个不存在的价格区间。
 *
 * 后续接入 Agent 时，"搜索比价"工具直接调用本服务，
 * 不需要 Python 侧再实现一套统计逻辑。
 */
@Service
@RequiredArgsConstructor
public class PriceComparisonService {

    /** 样本少于该数量时不给结论，避免用 1~2 条数据误导用户 */
    private static final int MIN_SAMPLES = 3;

    /** 建议区间取 P25~P75 */
    private static final int MAX_SAMPLES_RETURNED = 5;

    private final ProductService productService;
    private final CategoryService categoryService;

    /**
     * 对指定商品做同类比价。
     *
     * @param product 目标商品
     * @param limit   最多取多少条同类样本参与统计
     */
    @Transactional(readOnly = true)
    public PriceComparison compareFor(Product product, int limit) {
        if (product.getPrice() == null) {
            return insufficient(product, "该商品没有价格信息，无法比价");
        }
        String category = product.getCategoryName() != null
                ? product.getCategoryName() : product.getCategory();
        // 商品详情页允许放宽到"全部分类"：
        // 用户已经看到具体商品，给一个跨分类的粗略参考比什么都不给有用，
        // 且文案会明确标注"已放宽范围"。
        return compare(product.getProductType(), category, product.getConditionLevel(),
                product.getPrice(), product.getId(), limit, /* allowCategoryFallback */ true);
    }

    /**
     * 按分类给出价格参考（**不需要先有商品**）。
     *
     * 这个入口是给"发布时的定价建议"用的：用户还没发布，只有分类和成色，
     * 我们需要告诉他"这类东西大家一般卖多少"。
     *
     * @param category       分类名，可为 null（表示不限）
     * @param conditionLevel 成色，可为 null
     * @param targetPrice    用户当前填的价格，可为 null（表示只问行情、不评判）
     * @param limit          样本上限
     */
    @Transactional(readOnly = true)
    public PriceComparison suggestFor(String category, String conditionLevel,
                                      BigDecimal targetPrice, int limit) {
        return suggestFor(null, category, conditionLevel, targetPrice, limit);
    }

    /**
     * 带品类词的定价建议（发布页选了品类时用）。
     *
     * 品类比分类准得多：卖家给一件耳机定价，参考"数码电子"（含笔记本）
     * 毫无意义；参考"耳机"才有意义。
     *
     * @param productType 品类词，可为 null（退回按分类）
     */
    @Transactional(readOnly = true)
    public PriceComparison suggestFor(String productType, String category, String conditionLevel,
                                      BigDecimal targetPrice, int limit) {
        // 定价建议**不放宽到全部分类**：
        // 用户在给"图书教材"定价，却拿到"全平台均价"（含 1800 的电动车），
        // 这个数字看着有道理，实际会把人带偏。宁可说"样本不足"。
        return compare(productType, category, conditionLevel, targetPrice, null, limit,
                /* allowCategoryFallback */ false);
    }

    /**
     * 比价核心。
     *
     * 样本收窄策略：先"分类+成色"，不足 MIN_SAMPLES 就放宽为"仅分类"，
     * 再不足（且允许时）放宽为"全部分类" —— 每一档都记录实际用了哪一档，
     * 这样解释文案里能说清"参考范围有多窄"，避免用小样本给用户误导性结论。
     *
     * @param targetPrice          目标价格；为 null 时只输出行情、不给 verdict
     * @param excludeId            排除自身（按商品比价时传入）
     * @param allowCategoryFallback 分类样本不足时是否放宽到全部分类
     */
    private PriceComparison compare(String category, String conditionLevel,
                                    BigDecimal targetPrice, Long excludeId, int limit,
                                    boolean allowCategoryFallback) {
        return compare(null, category, conditionLevel, targetPrice, excludeId, limit,
                allowCategoryFallback);
    }

    /**
     * 比价核心（带品类词版本）。
     *
     * 取样阶梯，由细到粗：
     *   ① 同品类 + 成色
     *   ② 同品类
     *   ③ 同分类 + 成色
     *   ④ 同分类
     *   ⑤ 全平台（仅在允许时）
     *
     * 为什么必须让品类排在最前：一个分类里同时躺着 45 元的耳机和 4200 元的笔记本，
     * 按分类取样的四分位区间宽达 8.8 倍 —— 那个数字对定价毫无意义。
     */
    private PriceComparison compare(String productType, String category, String conditionLevel,
                                    BigDecimal targetPrice, Long excludeId, int limit,
                                    boolean allowCategoryFallback) {
        // 分类不存在时不要静默"放宽到全部分类"。
        // 否则用户把「数码电子」拼成「数码产品」，会拿到全站均价，
        // 而文案写着「参考全平台 N 件」——数字看着有道理，其实答非所问。
        if (category != null && !category.isBlank() && !categoryExists(category)) {
            return new PriceComparison(
                    category, conditionLevel, 0,
                    null, null, null, null, null, null, null,
                    PriceComparison.VERDICT_INSUFFICIENT,
                    "没有找到分类「" + category + "」，无法给出价格参考",
                    List.of());
        }

        List<Product> samples = productService.priceSamples(
                productType, category, conditionLevel, excludeId, limit);
        String usedCondition = conditionLevel;
        String usedCategory = category;
        String usedType = productType;

        // ① 品类+成色 → ② 品类
        if (samples.size() < MIN_SAMPLES && usedCondition != null) {
            samples = productService.priceSamples(productType, category, null, excludeId, limit);
            usedCondition = null;
        }
        // ③ 分类+成色
        if (samples.size() < MIN_SAMPLES && usedType != null) {
            samples = productService.priceSamples(null, category, conditionLevel, excludeId, limit);
            usedType = null;
            usedCondition = conditionLevel;
        }
        // ④ 分类
        if (samples.size() < MIN_SAMPLES && usedCondition != null) {
            samples = productService.priceSamples(null, category, null, excludeId, limit);
            usedCondition = null;
        }
        // ⑤ 全平台（仅在允许时）
        if (samples.size() < MIN_SAMPLES && category != null && allowCategoryFallback) {
            samples = productService.priceSamples(null, null, null, excludeId, limit);
            usedCategory = null;
            usedCondition = null;
        }

        List<BigDecimal> prices = samples.stream()
                .map(Product::getPrice)
                .filter(java.util.Objects::nonNull)
                .sorted()
                .toList();

        if (prices.size() < MIN_SAMPLES) {
            return new PriceComparison(
                    category, conditionLevel, prices.size(),
                    null, null, null, null, null, null, null,
                    PriceComparison.VERDICT_INSUFFICIENT,
                    "同类商品样本不足（仅 " + prices.size() + " 条），暂时无法给出可靠的价格参考",
                    List.of());
        }

        BigDecimal min = prices.get(0);
        BigDecimal max = prices.get(prices.size() - 1);
        BigDecimal p25 = percentile(prices, 0.25);
        BigDecimal median = percentile(prices, 0.50);
        BigDecimal p75 = percentile(prices, 0.75);

        // 没有目标价时只报行情，不给"偏高/偏低"的判断
        String verdict = null;
        String explanation;
        if (targetPrice == null) {
            explanation = buildRangeOnly(usedCategory, usedCondition, min, median, max, p25, p75,
                    prices.size());
        } else {
            if (targetPrice.compareTo(p25) < 0) {
                verdict = PriceComparison.VERDICT_LOW;
            } else if (targetPrice.compareTo(p75) > 0) {
                verdict = PriceComparison.VERDICT_HIGH;
            } else {
                verdict = PriceComparison.VERDICT_FAIR;
            }
            explanation = buildExplanation(targetPrice, verdict, min, median, max, p25, p75,
                    prices.size(), usedCategory);
        }

        List<PriceComparison.Sample> sampleViews = new ArrayList<>();
        samples.stream()
                .filter(p -> p.getPrice() != null)
                .sorted(Comparator.comparing(Product::getPrice))
                .limit(MAX_SAMPLES_RETURNED)
                .forEach(p -> sampleViews.add(new PriceComparison.Sample(
                        p.getId(), p.getName(), p.getPrice(), p.getConditionLevel(),
                        p.statusEnum().label())));

        return new PriceComparison(
                category, usedCondition, prices.size(),
                min, p25, median, p75, max,
                p25, p75,
                verdict, explanation, sampleViews);
    }

    /** 按商品ID比价 */
    @Transactional(readOnly = true)
    public PriceComparison compareForProduct(Long productId, int limit) {
        return compareFor(productService.getById(productId), limit);
    }

    /**
     * 分位数计算（线性插值法）。
     * 独立成包级可见的静态方法，便于单元测试直接覆盖边界。
     */
    static BigDecimal percentile(List<BigDecimal> sortedAsc, double q) {
        if (sortedAsc.isEmpty()) {
            return null;
        }
        if (sortedAsc.size() == 1) {
            return sortedAsc.get(0).setScale(2, RoundingMode.HALF_UP);
        }
        double pos = q * (sortedAsc.size() - 1);
        int lower = (int) Math.floor(pos);
        int upper = (int) Math.ceil(pos);
        if (lower == upper) {
            return sortedAsc.get(lower).setScale(2, RoundingMode.HALF_UP);
        }
        BigDecimal low = sortedAsc.get(lower);
        BigDecimal high = sortedAsc.get(upper);
        BigDecimal weight = BigDecimal.valueOf(pos - lower);
        return low.add(high.subtract(low).multiply(weight)).setScale(2, RoundingMode.HALF_UP);
    }

    /** 分类是否真实存在（用于区分"分类写错"和"分类里没货"） */
    private boolean categoryExists(String category) {
        return categoryService.listAll().stream()
                .anyMatch(c -> c.getName().equals(category));
    }

    private PriceComparison insufficient(Product product, String reason) {
        return new PriceComparison(
                product.getCategoryName() != null ? product.getCategoryName() : product.getCategory(),
                product.getConditionLevel(),
                0, null, null, null, null, null, null, null,
                PriceComparison.VERDICT_INSUFFICIENT, reason, List.of());
    }

    /**
     * 只报行情、不给"偏高/偏低"判断的文案（用户还没填价格时用）。
     *
     * 说明里必须点出参考范围是"同类"还是"全部分类" ——
     * 否则用户会以为"全站均价"就是"这类东西的均价"，产生误导。
     */
    private String buildRangeOnly(String category, String condition,
                                  BigDecimal min, BigDecimal median, BigDecimal max,
                                  BigDecimal p25, BigDecimal p75, int sampleSize) {
        String scope;
        if (category != null && condition != null) {
            scope = "同分类（" + category + "）且同为 " + condition + " 的 " + sampleSize + " 件";
        } else if (category != null) {
            scope = "「" + category + "」分类下的 " + sampleSize + " 件";
        } else {
            scope = "全平台 " + sampleSize + " 件在售/已售商品（该分类样本不足，已放宽范围）";
        }
        return "参考" + scope + "：最低 ¥" + min + "，中位价 ¥" + median + "，最高 ¥" + max
                + "。常见成交区间约 ¥" + p25 + " ~ ¥" + p75 + "。";
    }

    private String buildExplanation(BigDecimal target, String verdict, BigDecimal min, BigDecimal median,
                                    BigDecimal max, BigDecimal p25, BigDecimal p75, int sampleSize,
                                    String usedCategory) {
        // 参考范围必须如实说明。
        // 若已放宽到全部分类，却仍写"同类商品"，用户会以为是同类统计 ——
        // 这比数字不准更糟：数字看着有道理，其实答非所问。
        String scope = usedCategory != null
                ? "同类商品"
                : "全平台商品（该分类样本不足，已放宽范围）";

        String base = "参考 " + sampleSize + " 条" + scope + "：最低 ¥" + min + "，中位价 ¥" + median
                + "，最高 ¥" + max + "（合理区间 ¥" + p25 + " ~ ¥" + p75 + "）。";
        return switch (verdict) {
            case PriceComparison.VERDICT_LOW -> base
                    + "你的定价 ¥" + target + " 低于同类 25 分位，偏低，成交会很快但可能卖亏了。";
            case PriceComparison.VERDICT_HIGH -> base
                    + "你的定价 ¥" + target + " 高于同类 75 分位，偏高，建议下调到 ¥" + p75 + " 附近以提高成交率。";
            default -> base
                    + "你的定价 ¥" + target + " 落在合理区间内，属于正常市场价。";
        };
    }
}
