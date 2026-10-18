# 后端业务规则

> 这一篇只讲**业务真值**：状态怎么流转、审核怎么走、并发怎么防。界面操作步骤见 [使用指南](guide.md)。

## 一条原则

**所有业务判断都在 Java 里。** Agent 和网页只是两个调用方，都走同一套 Service：

```
网页 (Thymeleaf)  ─┐
                   ├─► ProductService / OrderService ─► MySQL
Agent (/api/v1)   ─┘
```

这不是洁癖。Agent 会出错、会超时、会被诱导，但这些错误**不该变成脏数据**。
把规则放在 Java 里，意味着 Python 侧无论怎么乱来，最坏结果也只是"这次没做成"。

---

## 一、商品状态机

5 个状态，`ProductStatus` 枚举，数据库存 `0~4` 与历史值兼容。

```
     PENDING_APPROVAL ──approve──► ON_SALE ──createOrder+pay──► SOLD
            │                       │  │                          │
            │reject                 │  │delist              取消已支付订单
            ▼                       ▼  ▼                          │
        REJECTED                 DELISTED ──relist──► ON_SALE ◄─────┘
            │                                   
            └──────────resubmit──► PENDING_APPROVAL
```

| 当前状态 | 允许迁移到 | 触发者 |
|---|---|---|
| `PENDING_APPROVAL` | `ON_SALE` / `REJECTED` | 管理员审核 |
| `ON_SALE` | `SOLD` / `DELISTED` / `REJECTED` | 买家下单 / 卖家下架 / 举报核实 |
| `REJECTED` | `PENDING_APPROVAL` | 卖家修改后重新提交 |
| `DELISTED` | `PENDING_APPROVAL` | 卖家重新上架（**要再审一次**） |
| `SOLD` | `ON_SALE` | 仅退款/取消已支付订单时回退 |

两条容易踩的规则：

1. **重新上架要重新审核**。`DELISTED → PENDING_APPROVAL` 而不是直接回 `ON_SALE`——
   下架期间商品可以被改得面目全非，直接放回在售等于绕过审核。
2. **`SOLD` 是锁**。它不是"卖完了"，而是"已被订单锁定"。只有订单取消/退款才退回 `ON_SALE`。

合法迁移表就在 `ProductStatus.allowedNext()` 里，**既是代码也是文档**——
单测直接对着它断言，不会出现"文档说能转、代码不让转"。

---

## 二、审核流

```
卖家提交  ──►  PENDING_APPROVAL  ──► 管理员在后台看到待审列表
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
                  通过               拒绝并填理由          删除
                    │                   │
                    ▼                   ▼
                 ON_SALE            REJECTED（卖家可改后重提）
```

关键点：

- **通过 = 一个状态迁移**，不是"标记一个字段"。所以审核历史天然可追溯。
- **拒绝必须填理由**，会展示给卖家。
- **举报核实后的下架走同一条路径**（`ON_SALE → REJECTED`），不另开一套逻辑。
- **Agent 发布也进这个流程**。模型不管多自信，都只能产出 `PENDING_APPROVAL`。

---

## 三、并发：一物多卖

二手商品是**唯一物品**——一件卖出去，其他订单必须失败。

做法是乐观锁 `@Version`：

```java
@Version
private Long version;
```

下单时比对版本号，并发下只有一个人成功，另一个拿到 `409 Conflict`，
前端提示"手慢了，这件已经被别人买走了"。

为什么不用悲观锁：二手交易是**读多写少**，一件商品可能被浏览上百次才成交一次。
给每次浏览加行锁会把数据库打死。

> 这是这个项目里修过的**最实质的正确性缺陷**：改造前两个用户可以同时下单同一件商品。

---

## 四、权限

双层令牌，详见 [Agent 接口约定](agent-api.md)：

| 令牌 | 证明什么 |
|---|---|
| `X-Service-Token` | 调用方是内部 agent 服务 |
| `X-Actor-Token` | 以哪个用户的身份操作（scope 交集，30 分钟过期） |

一个刻意的排除：**`order:pay` 永不授予 agent**。
付款是这个系统里唯一不可逆的金钱操作，它只走网页端的人工点击。

---

## 五、审计

写操作落 `audit_log`：谁、什么时候、对哪个对象、做了什么、结果如何。

用途不是"合规"，是**出问题时能回答"这条数据是谁改的"**——
Agent 参与后这一点尤其重要，因为"模型自己决定的"不是一个可接受的解释。

---

## 相关文档

- [Agent 接口约定](agent-api.md) — 令牌、scope、状态码
- [写操作与人工确认](agent-hitl.md) — 为什么 agent 的写操作要停一下
- [评测结论](evaluation-findings.md) — 哪些能力值得交给 agent
