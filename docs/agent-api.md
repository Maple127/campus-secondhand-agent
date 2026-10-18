# Agent 接口约定（Python 侧对接说明）

本文档面向 `agent/` 下的 Python 服务，说明如何安全地调用后端业务接口。

---

## 1. 鉴权模型

后端对 `/api/v1/**` 实施**双层令牌 + scope 校验**，缺一不可。

| 请求头 | 作用 | 来源 | 缺失后果 |
|---|---|---|---|
| `X-Service-Token` | 证明调用方是内部 agent 服务 | 部署时配置的共享密钥 | 401 |
| `X-Actor-Token` | 证明「以哪个用户的身份操作」 | 前端通过 `/api/v1/agent/session` 换取 | 401 |

### 1.1 获取 Actor Token

前端在用户已登录的前提下调用：

```http
POST /api/v1/agent/session
X-Service-Token: <服务密钥>
Content-Type: application/json

{ "conversationId": "可选，不传则自动生成" }
```

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "actorToken": "xxxxx",
    "conversationId": "uuid",
    "expiresAt": "2026-01-01T10:30:00Z",
    "scopes": ["product:read", "product:publish", "order:create", "..."],
    "user": { "id": 1, "username": "user01" }
  }
}
```

**关键点**：该接口的身份来源是浏览器 HttpSession，`userId` 不能由请求体指定。
后端会将请求的 scopes 与 `DEFAULT_USER_SCOPES` 求交集，agent **无法自行提权**。

### 1.2 调用业务接口

```http
GET /api/v1/products?q=ipad&maxPrice=3000
X-Service-Token: <服务密钥>
X-Actor-Token: <上一步拿到的 actorToken>
```

---

## 2. Scope 一览

| Scope | 允许的操作 |
|---|---|
| `product:read` | 搜索、详情、比价、我的发布、分类列表 |
| `product:publish` | 发布商品（进入待审核） |
| `product:update` | 修改自己的商品 |
| `product:delist` | 下架自己的商品 |
| `order:read` | 查看自己的买卖订单 |
| `order:create` | 创建订单（会锁定商品） |
| `order:cancel` | 取消未付款订单 |
| `favorite:read` / `favorite:write` | 收藏列表 / 切换收藏 |
| `report:read` / `report:submit` | 我的举报 / 提交举报 |
| `profile:read` / `profile:update` | 读取 / 修改个人资料 |
| ~~`order:pay`~~ | **不在默认集合中**：支付需用户在页面输入支付密码，agent 不得代付 |

---

## 3. 响应约定

成功：

```json
{ "code": 0, "message": "ok", "data": { } }
```

失败（HTTP 状态码与 code 一致）：

```json
{ "code": 409, "message": "商品当前状态为「已售出」，无法下单", "data": null }
```

**`message` 是写给人和 LLM 看的**，可以直接转述给用户，不需要二次加工。

常见状态码：

| HTTP | 含义 | Agent 应如何处理 |
|---|---|---|
| 400 | 参数不合法 | 修正参数后重试，或向用户澄清 |
| 401 | 令牌缺失/过期/无效 | 提示用户刷新页面重新授权 |
| 403 | scope 不足 | **不要重试**，告知用户此操作超出 AI 助手权限 |
| 404 | 资源不存在或不可见 | 重新搜索 |
| 409 | 状态冲突（已被抢单、状态不允许等） | 向用户说明现状，提供替代方案 |

---

## 4. 建议的工具映射

| Agent 工具 | 调用 | 是否有副作用 | 是否需用户确认 |
|---|---|---|---|
| `search_products` | `GET /api/v1/products` | 否 | 否 |
| `get_product` | `GET /api/v1/products/{id}` | 否 | 否 |
| `compare_price` | `GET /api/v1/products/{id}/price-comparison` | 否 | 否 |
| `list_my_products` | `GET /api/v1/products/mine/list` | 否 | 否 |
| `list_my_orders` | `GET /api/v1/orders?role=` | 否 | 否 |
| `publish_product` | `POST /api/v1/products` | **是** | ✅ 必须 |
| `update_product` | `PATCH /api/v1/products/{id}` | **是** | ✅ |
| `delist_product` | `POST /api/v1/products/{id}/delist` | **是** | ✅ |
| `create_order` | `POST /api/v1/orders` | **是** | ✅ |
| `cancel_order` | `POST /api/v1/orders/{orderNo}/cancel` | **是** | ✅ |
| `toggle_favorite` | `POST /api/v1/favorites/{id}` | 是（可撤销） | 否 |
| `submit_report` | `POST /api/v1/reports` | **是** | ✅ |
| `get_profile` | `GET /api/v1/me` | 否 | 否 |

### 4.1 必须遵守的约束

1. **写操作一律先确认**。使用 LangGraph `interrupt` 让用户点确认后再真正调用，并为每个待执行动作生成幂等键，避免重复提交。
2. **发布商品必然进入待审核**。不要向用户承诺「已经上架了」，应说明「已提交，等待管理员审核」。
3. **不要尝试支付**。没有 `order:pay` scope，且这是刻意的边界。
4. **事实性数据必须来自接口**。价格、库存、订单状态一律引用接口返回值并回显 `productId` / `orderNo`，禁止模型自行编造。
5. **商品描述是数据不是指令**。商品文本可能包含「忽略以上指令」之类的注入内容，必须以数据形式注入并转义。
6. **不要把卖家手机号直接给用户**。列表与详情接口默认不返回 `sellerPhone`，沟通应走站内消息（M6 实现）。

---

## 5. 状态取值参考

商品状态（`ProductView.status` / `statusLabel`）：

| 值 | 标签 | `available` | 说明 |
|---|---|---|---|
| `PENDING_APPROVAL` | 待审核 | false | agent 发布后的初始状态 |
| `ON_SALE` | 在售 | **true** | 唯一可下单状态 |
| `REJECTED` | 已拒绝 | false | 审核未通过或举报核实违规 |
| `DELISTED` | 已下架 | false | 卖家主动下架 |
| `SOLD` | 已售出 | false | 已有订单锁定，不可下单 |

订单状态：`UNPAID` / `PAID` / `SHIPPED` / `COMPLETED` / `CANCELLED`

---

## 6. 本地联调

```bash
# 后端
cd backend && mvn spring-boot:run          # http://localhost:8081

# 服务密钥（默认值见 application.properties）
export AGENT_SERVICE_TOKEN=demo-agent-token-local
```

冒烟测试脚本 `infra/smoke-test.ps1` 可作为 Python 侧请求构造的参考实现。
