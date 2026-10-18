package campus.secondhand.service;

import campus.secondhand.entity.Product;
import campus.secondhand.entity.ProductStatus;
import campus.secondhand.repository.ProductRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;

/**
 * 议价建议：把比价统计翻译成"我该出多少"。
 *
 * ## 核心原则
 *
 * **所有金额在这里算完，模型只负责措辞。** 这个项目的
 * {@code PriceComparisonService} 已经踩过"让模型说价格"的坑，
 * 所以议价也守着同一条线。
 *
 * ## 定价逻辑（可解释，不神秘）
 *
 * 市场区间用同类样本的四分位：
 *   便宜档 p25 ── 中位 median ── 贵档 p75
 *
 * - 挂牌价 ≤ 中位价   → 已经是合理价位，**劝你别砍**（砍价也有成本）
 * - 挂牌价 > 中位价   → 目标价 = 中位价；试探价 = 中位价再往下 10%，但不低于 p25
 * - 挂牌价 > p75      → 明显偏贵，止损价就是 p75：谈不下来就换一家
 *
 * "同品类还有几件更便宜的"只用于**解释**和**话术**，不直接改价格 ——
 * 让一个计数去影响建议价，会让结果变得难以解释。这条线宁可保守。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class NegotiationService {

    private final ProductRepository productRepository;
    private final ProductService productService;
    private final PriceComparisonService priceComparisonService;

    /** 低于这个样本量，只给结论不给精确价位 */
    private static final int CONFIDENT_SAMPLES = 5;
    private static final int MIN_SAMPLES = 3;

    @Transactional(readOnly = true)
    public NegotiationAdvice adviceFor(Long productId) {
        Product product = productService.getVisibleById(productId);
        BigDecimal asking = product.getPrice();
        if (asking == null) {
            return NegotiationAdvice.insufficient(productId, product.getName(), null,
                    "这件商品没有标价");
        }

        PriceComparison cmp = priceComparisonService.compareFor(product, 50);
        if (cmp.sampleSize() < MIN_SAMPLES || cmp.p25() == null || cmp.p75() == null) {
            return NegotiationAdvice.insufficient(productId, product.getName(), asking,
                    "同类样本只有 " + cmp.sampleSize() + " 条，不够可靠");
        }

        BigDecimal low = cmp.p25();
        BigDecimal mid = cmp.median();
        BigDecimal high = cmp.p75();

        int cheaper = countCheaper(product);
        long days = daysListed(product);

        String confidence = cmp.sampleSize() >= CONFIDENT_SAMPLES ? "HIGH"
                : cmp.sampleSize() >= MIN_SAMPLES ? "MEDIUM" : "LOW";

        // ---- 挂牌价相对同类的位置 ----
        String verdict;
        BigDecimal open;
        BigDecimal target;
        BigDecimal walkAway;

        if (asking.compareTo(mid) <= 0) {
            // 已经不比中位价贵了：别为了几十块折腾
            verdict = "FAIR";
            target = asking;
            open = max(low, scale(asking, "0.93"));
            walkAway = min(high, scale(asking, "1.05"));
        } else {
            // 比中位价贵：按"谈到中位价"来算
            verdict = asking.compareTo(high) > 0 ? "EXPENSIVE" : "SLIGHTLY_HIGH";
            target = mid;
            open = max(low, scale(mid, "0.90"));
            walkAway = high;
        }

        // 出价不能高于挂牌价（没意义），也不能低于 p25（会被直接忽略）
        open = min(open, asking);
        target = min(target, asking);
        if (open.compareTo(target) > 0) {
            open = target;
        }

        String reasoning = buildReasoning(verdict, asking, low, mid, high,
                cmp.sampleSize(), cheaper, days);
        String script = buildScript(product, asking, target, open, verdict, cheaper, days);

        return new NegotiationAdvice(
                productId, product.getName(), asking,
                low, mid, high, cmp.sampleSize(), confidence,
                verdict, open, target, walkAway,
                cheaper, days, reasoning, script);
    }

    // ------------------------------------------------------------------

    /** 同品类里比它便宜的还有几件 —— 买家的谈判筹码 */
    private int countCheaper(Product product) {
        String type = product.getProductType();
        if (type == null || type.isBlank() || product.getPrice() == null) {
            return 0;
        }
        return (int) productRepository.countCheaper(
                ProductStatus.ON_SALE.code(), type, product.getPrice(), product.getId());
    }

    private long daysListed(Product product) {
        LocalDateTime created = product.getCreateTime();
        if (created == null) {
            return 0;
        }
        return Math.max(0, ChronoUnit.DAYS.between(created, LocalDateTime.now()));
    }

    private String buildReasoning(String verdict, BigDecimal asking,
                                  BigDecimal low, BigDecimal mid, BigDecimal high,
                                  int samples, int cheaper, long days) {
        StringBuilder sb = new StringBuilder();
        sb.append("同类 ").append(samples).append(" 件：便宜档 ¥").append(fmt(low))
                .append("、中位 ¥").append(fmt(mid)).append("、贵档 ¥").append(fmt(high)).append("。");

        switch (verdict) {
            case "FAIR" -> sb.append("它的挂牌价 ¥").append(fmt(asking))
                    .append(" 已经不比中位价贵，属于正常价位。");
            case "SLIGHTLY_HIGH" -> sb.append("挂牌价 ¥").append(fmt(asking))
                    .append(" 高于中位价，有谈的空间。");
            default -> sb.append("挂牌价 ¥").append(fmt(asking))
                    .append(" 已经超出同类贵档，建议谈到 ¥").append(fmt(mid)).append(" 以内。");
        }

        if (cheaper > 0) {
            sb.append(" 同类还有 ").append(cheaper).append(" 件更便宜的，这是你的筹码。");
        }
        if (days >= 14) {
            sb.append(" 这件挂了 ").append(days).append(" 天没出手，卖家可能愿意让。");
        } else if (days <= 2) {
            sb.append(" 刚挂出来 ").append(days).append(" 天，卖家一般不太肯降。");
        }
        return sb.toString();
    }

    private String buildScript(Product product, BigDecimal asking, BigDecimal target,
                               BigDecimal open, String verdict, int cheaper, long days) {
        String name = product.getName();
        if ("FAIR".equals(verdict)) {
            return "同学你好，「" + name + "」还在吗？我看价格挺实在的，"
                    + "如果方便的话我今天就能来拿，可以约在" + where(product) + "。";
        }

        StringBuilder sb = new StringBuilder();
        sb.append("同学你好，「").append(name).append("」还在吗？想收一个二手的。");
        if (cheaper > 0) {
            sb.append("我看到同类还有 ").append(cheaper).append(" 件比这个便宜一些，");
        }
        sb.append("¥").append(fmt(open)).append(" 能出的话我今天就来拿，")
                .append("可以约在").append(where(product)).append("。");
        return sb.toString();
    }

    private String where(Product product) {
        String loc = product.getLocation();
        return (loc == null || loc.isBlank()) ? "校内方便的地方" : loc;
    }

    private static BigDecimal scale(BigDecimal v, String factor) {
        return v.multiply(new BigDecimal(factor)).setScale(0, RoundingMode.HALF_UP);
    }

    private static BigDecimal max(BigDecimal a, BigDecimal b) {
        return a.compareTo(b) >= 0 ? a : b;
    }

    private static BigDecimal min(BigDecimal a, BigDecimal b) {
        return a.compareTo(b) <= 0 ? a : b;
    }

    private static String fmt(BigDecimal v) {
        return v.setScale(0, RoundingMode.HALF_UP).toPlainString();
    }
}
