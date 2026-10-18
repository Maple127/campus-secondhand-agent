package campus.secondhand.api.web;

import campus.secondhand.service.NegotiationAdvice;
import campus.secondhand.service.NegotiationService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;

/**
 * 网页端的议价接口。
 *
 * 目前只有"建议"（无状态）。出价单会在这里继续加。
 *
 * 注意：**这个接口不依赖 AI 服务**。所有金额都是后端算的，
 * agent 挂掉时商品页的议价面板照常工作 —— 这是刻意的：
 * 判断价格不该依赖一个可能超时的大模型。
 */
@RestController
@RequiredArgsConstructor
public class NegotiationController {

    private final NegotiationService negotiationService;

    /** 商品页：这件值不值、该出多少、怎么说 */
    @GetMapping("/web/products/{id}/negotiation-advice")
    public Map<String, Object> advice(@PathVariable Long id) {
        NegotiationAdvice a = negotiationService.adviceFor(id);

        Map<String, Object> data = new HashMap<>();
        data.put("productId", a.productId());
        data.put("productName", a.productName());
        data.put("askingPrice", a.askingPrice());
        data.put("marketLow", a.marketLow());
        data.put("marketMedian", a.marketMedian());
        data.put("marketHigh", a.marketHigh());
        data.put("sampleSize", a.sampleSize());
        data.put("confidence", a.confidence());
        data.put("verdict", a.verdict());
        data.put("suggestedOpen", a.suggestedOpen());
        data.put("suggestedTarget", a.suggestedTarget());
        data.put("walkAway", a.walkAway());
        data.put("cheaperCount", a.cheaperCount());
        data.put("daysListed", a.daysListed());
        data.put("reasoning", a.reasoning());
        data.put("script", a.script());

        Map<String, Object> body = new HashMap<>();
        body.put("code", 0);
        body.put("data", data);
        return body;
    }
}
