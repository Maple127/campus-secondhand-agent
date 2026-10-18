# 议价 Copilot：给建议

> 状态：**已完成并验证**。出价单（第二阶段）尚未开始。

## 一、定下来的三件事

用户拍板：只给建议 + 出价单 + 卖家设底价 + 两个入口都开，**不做自由聊天**。

不做聊天的理由写在这里，免得以后有人觉得"顺手加一下"：

| | 自由聊天 | 结构化出价 |
|---|---|---|
| 风险面 | 双方自由文本：注入、辱骂、引流、诈骗全在里面 | 只有数字和状态 |
| 成本 | 3~5 天 | 1~2 天 |
| 议价需要吗 | 不需要——`出价 ¥160 → 还价 ¥180 → 接受` 就是完整议价 |  |

而且我们**还没做 fencing**，先开私聊等于把最大的洞开在最挤的地方。

---

## 二、第一阶段做了什么

### 2.1 商品页的「💰 这个价值不值？」面板

默认**收起**，点开才请求——不是每个访客都想砍价，不该让所有人等一次请求。

展开后给出：

```
这个价贵不贵   明显偏贵，建议谈到合理区间
试探价 ¥342   目标价 ¥380   止损价 ¥650
依据           同类 7 件：便宜档 ¥90、中位 ¥380、贵档 ¥650。
               挂牌价 ¥680 已经超出同类贵档，建议谈到 ¥380 以内。
               同类还有 5 件更便宜的，这是你的筹码。
               这件挂了 105 天没出手，卖家可能愿意让。
[复制] 同学你好，「AirPods Pro 2代」还在吗？想收一个二手的。
       我看到同类还有 5 件比这个便宜一些，¥342 能出的话我今天就来拿…
```

### 2.2 定价规则（可解释，不神秘）

```
便宜档 p25 ── 中位 median ── 贵档 p75

挂牌价 ≤ 中位        → FAIR          劝你别砍，目标价 = 挂牌价
中位 < 挂牌价 ≤ p75  → SLIGHTLY_HIGH 目标价 = 中位价
挂牌价 > p75         → EXPENSIVE     目标价 = 中位价，止损价 = p75
样本 < 3 条          → UNKNOWN       **不给任何数字**
```

三个细节：

- **试探价 = 中位价 × 0.9，但不低于 p25，也不高于挂牌价**。太低会被卖家直接忽略，太高就没意义。
- **价格合理时明确劝你别砍。** 一个只会教你压价的助手会把平台成交率做低，卖家也会被骚扰跑掉。
- **"同类还有几件更便宜的"只用于解释和话术，不参与改价。** 让一个计数去影响建议价，结果就难以解释了——这条线宁可保守。

### 2.3 谁算、谁说

```
Java / NegotiationService   →  所有金额、判断、依据文本
Java / NegotiationController →  /web/products/{id}/negotiation-advice
Python / negotiation_advice →  只负责把数字翻译成人话
```

**关键：这个面板不依赖 AI 服务。** agent 挂了，商品页的议价建议照常工作。
判断价格不该依赖一个可能超时的大模型——这条线我们在 B2 就已经守过一次。

### 2.4 两个入口都开了

| 入口 | 形态 |
|---|---|
| 商品详情页 | 议价面板（面板本身有完整结论） |
| AI 助手 | 新增工具 `negotiation_advice`，可以问「这个 680 值吗」 |

商品页现在也能唤起 AI 抽屉了（之前只有首页有）。

---

## 三、实测

### 3.1 三种典型情况

| 商品 | 挂牌价 | 判断 | 试探 / 目标 / 止损 |
|---|---|---|---|
| AirPods Pro 2代 | 680 | **明显偏贵**（同类 7 件，p75=650） | 342 / 380 / 650 |
| 机械键盘 Cherry | 420 | 略高（同类 3 件，中位 380） | 342 / 380 / 680 |
| 罗技 G304 鼠标 | 105 | **合理**（中位 120） | 98 / 105 / 110 |

第三条是关键：挂牌价本来就合理时，面板会说"价格挺实在的，我今天就能来拿"，
而不是教用户去压一个已经合理的价。

### 3.2 AI 助手的回答

```
你：AirPods Pro 那个 680，值吗？能砍到多少

agent：（调用 negotiation_advice）
      - 开价 342 元
      - 目标价 380 元
      - 超过 650 元 就别要了
      可以直接发的话术：同学你好，「AirPods Pro 2代」还在吗？…
      另外提醒：这件没填成色，砍价前先问清楚电池健康度、有没有拆修、配件是否齐全。
```

最后那句提醒是模型自己加的——这正好是语言模型该干的事（判断该提醒什么），
而不是算价。

---

## 四、已知局限

1. **耳机这样的品类仍然太粗**。¥45 的有线耳机和 ¥1150 的索尼头戴都是"耳机"，
   四分位区间宽达 7 倍。面板会照实显示，但"合理区间"的意义有限。
   真正要修得把品类拆得更细，或者用型号聚类——目前不值得。
2. **样本 3~4 条时给的是 MEDIUM 置信**，文案会提示"参考有限"，但仍然给了数字。
   这是有意的取舍：不给建议等于没做这个功能，但必须让用户知道它不够准。
3. **没有考虑成色的实际差异**。同样是 AirPods，9成新和6成新应该差不少，
   现在只按品类统计。成色维度在 `PriceComparisonService` 里有，但议价没用上。

---

## 五、下一阶段：出价单

已经设计好但还没写代码：

```sql
-- 商品上加底价（卖家设定）
ALTER TABLE product ADD COLUMN min_acceptable_price DECIMAL(10,2) NULL;

-- 出价单
CREATE TABLE negotiation_offer (
  id, product_id, buyer_id, buyer_name,
  price,                 -- 买家出价
  status,                -- OFFERED / ACCEPTED / REJECTED / COUNTERED / EXPIRED / CANCELLED
  seller_reply_price,    -- 卖家还价
  create_time, update_time, expires_at
);
```

流程：

```
买家出价 ¥160
   ├─ < 卖家底价 → 系统自动拒绝（不暴露底价）
   └─ ≥ 底价
        ├─ 卖家接受 → 生成订单，成交价 = 谈定价
        ├─ 卖家还价 ¥180 → 买家接受/拒绝
        └─ 48h 未处理 → 过期
```

三个必须想清楚的点：

1. **订单价 = 谈定价**，不是挂牌价。`Order.price` 本来就是快照能装下，
   但"一物多卖"的守卫要重做一遍——两个买家可能同时在谈。
2. **不能暴露卖家底价**。低于底价时只说"卖家暂不接受这个价格"。
3. **卖家怎么看到出价**。没有通知系统，只能放在「我的订单 → 出售」里。

---

## 六、改了哪些文件（本阶段）

| 文件 | 改动 |
|---|---|
| `service/NegotiationAdvice.java` | 新增：建议的数据结构 |
| `service/NegotiationService.java` | 新增：三档价计算 + 依据 + 话术 |
| `api/web/NegotiationController.java` | 新增：`/web/products/{id}/negotiation-advice` |
| `api/rest/ProductRestController.java` | 新增 agent 用的同名接口 |
| `security/AgentAuthInterceptor.java` | 新端点的 scope 规则 |
| `repository/ProductRepository.java` | `countCheaper` + 比价样本按品类取样 |
| `service/ProductService.java` | `priceSamples` 增加品类参数 |
| `service/PriceComparisonService.java` | 取样阶梯加入品类（8.8 倍 → 1.4 倍） |
| `templates/fragments/negotiation-panel.html` | 新增：面板 |
| `static/js/negotiation.js` | 新增：懒加载 + 渲染 + 复制 |
| `static/css/negotiation.css` | 新增 |
| `templates/product.html` | 挂载面板 + AI 抽屉 |
| `agent/app/tools.py` | 新增工具 `negotiation_advice` |
| `agent/app/backend.py` | 新增客户端方法 |
| `src/test/.../NegotiationServiceTest.java` | 新增 6 条定价规则测试 |
