package campus.secondhand.api.web;

import campus.secondhand.service.PriceComparison;
import campus.secondhand.service.PriceComparisonService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.Map;

/**
 * 供网页（Thymeleaf）调用的价格参考接口。
 *
 * ## 为什么不复用 /api/v1/products/price-suggestion
 *
 * `/api/v1/**` 走的是 agent 网关：必须同时带 `X-Service-Token` 与 `X-Actor-Token`。
 * 浏览器里的登录态是 HttpSession cookie，**拿不到也不应该拿**那两个令牌。
 * 硬让网页去调 /api/v1 只会把服务令牌下发到前端，那是安全倒退。
 *
 * 因此这里开一组独立的网页端点：只依赖 HttpSession 登录态，
 * 与页面同源，不需要任何特殊令牌。业务逻辑仍复用同一个 Service。
 *
 * ## 顺带说明：这块能力原本只存在于 agent 里
 *
 * 评测（docs/eval-findings.md）指出：比价是**纯统计**，不需要 LLM，
 * 却只挂在最慢的 agent 入口后面。现在它同时是网页上的独立功能。
 */
@RestController
@RequiredArgsConstructor
public class PriceInsightController {

    private final PriceComparisonService priceComparisonService;

    /**
     * 商品详情页：对已有商品比价。
     */
    @GetMapping("/web/products/{id}/price-insight")
    public Map<String, Object> forProduct(@PathVariable Long id,
                                          @RequestParam(defaultValue = "50") int sampleLimit) {
        return toView(priceComparisonService.compareForProduct(id, sampleLimit));
    }

    /**
     * 发布页：按分类 + 品类 + 成色给定价参考（不需要先有商品）。
     *
     * type 是品类词（耳机/笔记本）。传了它，参考范围会从"数码电子"这种大杂烩
     * 收窄到"耳机"，区间宽度能从 8.8 倍降到 1.x 倍 —— 这才有参考价值。
     */
    @GetMapping("/web/price-insight")
    public Map<String, Object> suggest(@RequestParam(required = false) String category,
                                       @RequestParam(required = false) String condition,
                                       @RequestParam(required = false) String type,
                                       @RequestParam(required = false) BigDecimal price,
                                       @RequestParam(defaultValue = "50") int sampleLimit) {
        return toView(priceComparisonService.suggestFor(type, category, condition, price, sampleLimit));
    }

    /**
     * 转成与 /api/v1 一致的响应结构，前端组件可以复用同一套渲染逻辑。
     */
    private Map<String, Object> toView(PriceComparison c) {
        Map<String, Object> data = new HashMap<>();
        data.put("categoryName", c.categoryName());
        data.put("conditionLevel", c.conditionLevel());
        data.put("sampleSize", c.sampleSize());
        data.put("min", c.min());
        data.put("p25", c.p25());
        data.put("median", c.median());
        data.put("p75", c.p75());
        data.put("max", c.max());
        data.put("suggestedLow", c.suggestedLow());
        data.put("suggestedHigh", c.suggestedHigh());
        data.put("verdict", c.verdict());
        data.put("explanation", c.explanation());
        data.put("samples", c.samples());

        Map<String, Object> body = new HashMap<>();
        body.put("code", 0);
        body.put("message", "ok");
        body.put("data", data);
        return body;
    }
}
