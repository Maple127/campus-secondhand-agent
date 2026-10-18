package campus.secondhand.service;

import java.math.BigDecimal;

/**
 * 议价建议：给买家看的"值不值 + 出多少 + 怎么说"。
 *
 * ## 为什么所有数字都在这里算
 *
 * 这个对象里的每一个金额都是 Java 算出来的，模型只负责把它们说成人话。
 * 我们被"模型编造价格区间"坑过一次之后，就一直守着这条线：
 * **有唯一正确答案的东西不交给语言模型。**
 *
 * @param productId      商品
 * @param askingPrice    卖家挂牌价
 * @param marketLow      同类 25 分位（便宜的那一档）
 * @param marketMedian   同类中位价
 * @param marketHigh     同类 75 分位（贵的那一档）
 * @param sampleSize     参与统计的同类样本数
 * @param confidence     HIGH / MEDIUM / LOW —— 样本量决定，用来决定文案有多确定
 * @param verdict        相对同类：偏贵 / 合理 / 便宜
 * @param suggestedOpen  试探价：第一次开口的价
 * @param suggestedTarget 目标价：谈到这个价就算合理
 * @param walkAway       止损价：超过这个就别买了
 * @param cheaperCount   同品类里还有几件比这更便宜（买家的谈判筹码）
 * @param daysListed     挂了几天（卖家急不急出）
 * @param reasoning      依据，一句话
 * @param script         可以直接发出去的话术
 */
public record NegotiationAdvice(
        Long productId,
        String productName,
        BigDecimal askingPrice,
        BigDecimal marketLow,
        BigDecimal marketMedian,
        BigDecimal marketHigh,
        int sampleSize,
        String confidence,
        String verdict,
        BigDecimal suggestedOpen,
        BigDecimal suggestedTarget,
        BigDecimal walkAway,
        int cheaperCount,
        long daysListed,
        String reasoning,
        String script
) {

    /** 样本量不足，给不出可靠建议 */
    public static NegotiationAdvice insufficient(Long id, String name, BigDecimal asking, String reason) {
        return new NegotiationAdvice(id, name, asking,
                null, null, null, 0, "LOW", "UNKNOWN",
                null, null, null, 0, 0, reason,
                "同类商品样本太少，暂时给不出可靠的出价建议。建议先看看商品详情和成色，或者多问卖家几个问题。");
    }
}
