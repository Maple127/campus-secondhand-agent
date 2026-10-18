# Agent 核心实现说明

**阶段**：M3（只读工具 + SSE 流式对话）
**技术栈**：Python 3.11 + FastAPI + LangChain v1 + LangGraph + DeepSeek
**状态**：已完成并通过真实端到端验证

---

## 一、整体数据流

```
┌────────────┐   ①登录    ┌──────────────────┐
│  浏览器     │──────────►│ Java 后端 :8081   │
│ (Thymeleaf)│◄──────────│ HttpSession      │
│            │            └──────────────────┘
│            │   ②用 session 换 capability token
│  AI 助手    │────────────────────────────────►
│   抽屉      │◄──────── actorToken + scopes
│            │
│            │   ③X-Actor-Token    ┌─────────────────────┐
│            │────────────────────►│ Python Agent :8090   │
└────────────┘                     │ FastAPI + LangGraph  │
                                   └──────────┬──────────┘
                                              │ ④X-Service-Token + X-Actor-Token
                                              ▼
                                   ┌─────────────────────┐
                                   │ Java /api/v1/**      │
                                   │ 业务真相源            │
                                   └─────────────────────┘
```

**关键设计**：Agent 不直连数据库、不复制业务规则。所有状态校验都在 Java 侧，因此
「网页端禁止买已售出商品」和「agent 禁止买已售出商品」是**同一条规则**。

---

## 二、模块职责

| 文件 | 职责 | 关键点 |
|---|---|---|
| `app/config.py` | 配置加载 | 敏感信息只从环境变量/`.env` 读；缺失时给可操作报错 |
| `app/backend.py` | Java API 客户端 | 只做「拼请求 / 透传身份 / 翻译错误」，无业务规则 |
| `app/tools.py` | 工具层 | 供模型调用；返回结构化文本；隐私字段过滤 |
| `app/prompt.py` | 系统提示词 | 幻觉抑制、注入防护、能力边界声明 |
| `app/graph.py` | LangGraph 组装与事件流 | 多轮记忆、SSE 事件协议 |
| `app/main.py` | FastAPI 入口 | SSE 接口、健康检查、CORS |
| `app/static/playground.html` | 独立调试台 | 不依赖 Java 页面，便于单独验证 |

---

## 三、工具设计

### 3.1 当前开放的 6 个只读工具

| 工具 | 用途 | 后端端点 |
|---|---|---|
| `search_products` | 关键词/分类/价格区间搜索 | `GET /api/v1/products` |
| `get_product` | 商品详情 | `GET /api/v1/products/{id}` |
| `compare_price` | 同类比价 | `GET /api/v1/products/{id}/price-comparison` |
| `list_categories` | 分类列表 | `GET /api/v1/meta/categories` |
| `list_my_products` | 我发布的商品 | `GET /api/v1/products/mine/list` |
| `list_my_orders` | 我的订单 | `GET /api/v1/orders` |

### 3.2 三个刻意的设计决策

**① 身份用 ContextVar 传递，不用全局变量**

工具函数由模型按名字调用，无法额外传 token。因此每次请求开始时绑定：

```python
with tool_context(actor_token, backend):
    async for event in graph.astream(...):
        ...
```

用 `ContextVar` 而非模块级全局变量，保证并发请求之间身份不串号。

**② 错误变成文本，而不是抛异常**

工具内 `except` 把后端错误转成给模型看的话术。原因：如果抛异常，整张图会崩，
用户只会看到"出错了"。变成文本后，模型能读懂并如实告知用户。

权限类错误的文案是刻意写的：

```
操作被拒绝（HTTP 403）：当前会话未被授予 order:pay 权限
这是权限或登录状态问题，请勿重试，直接如实告知用户。
```

模型看到 403 的常见错误行为是"换个参数再试"，这句话直接掐断这条路。

**③ 隐私字段在工具层就被剥离**

`_product_brief()` 不放 `sellerPhone`。这不是靠提示词"请不要说手机号"，
而是**让模型根本看不到**——提示词可能被绕过，数据不在上下文里则无从泄露。

---

## 四、幻觉抑制

这是比"能查数据"更重要的部分。三道防线：

| 防线 | 做法 |
|---|---|
| **提示词约束** | 明确「事实必须来自工具返回」「工具没给就说不知道」 |
| **数据来自后端** | 比价的 median/p25/p75 全部由 Java 统计，模型只负责转述 |
| **端到端验证** | E2E 里专门有「查询不存在的商品」用例，验证不会编造 |

E2E 实测（查询 `ZZZ不存在的商品XYZ`）：

> 没找到匹配的在售商品。可能的原因：关键词太具体…该商品已售出、已下架或还没通过审核…

没有编造任何商品或价格。

---

## 五、SSE 事件协议

`POST /api/chat/stream` 返回 `text/event-stream`，每个事件的 `data` 是一个 JSON：

| type | 字段 | 说明 |
|---|---|---|
| `token` | `text` | 模型输出的增量文本（前端累加显示） |
| `tool_start` | `name`, `args` | 开始调用工具（前端显示"正在搜索…"） |
| `tool_end` | `name`, `ok`, `preview` | 工具返回（`preview` 截断到 600 字符） |
| `done` | `steps` | 本轮结束，含工具调用步数 |
| `error` | `message` | 面向用户的错误说明 |

实测事件序列（"帮我搜一下数据结构这本书"）：

```
tool_start(search_products, {"query":"数据结构"})
tool_end(search_products, ok=True)
token × 61
done(steps=1)
```

首 token 延迟 1.0–2.8s，总耗时 2.8–3.2s。

> 注：首个事件可能是 `tool_start` 而非 `token` —— 模型决定调工具时，
> 第一次输出是工具调用而非正文，这是正常的。

---

## 六、实测中发现并修复的两个真实问题

### 问题 1：模型"凭记忆作答"，跳过工具调用

**现象**：多轮对话中，用户第二次问同类问题时，模型回答"我刚才已经搜过了，不用再查"，
`toolCalls` 为空。但平台数据是实时变化的（商品被买走、新上架、审核通过），
用旧结果回答是**数据正确性缺陷**，不是风格问题。

**根因**：原提示词只说了"事实必须来自工具"，但模型把上一轮的工具结果也算作"工具返回"。

**修复**：把这条提升为**规则第 1 条**，并显式否定跳过行为：

```
1. 每一轮都要重新调用工具，不要凭记忆作答。
   多轮对话中你确实能看到上一轮的结果，但平台数据随时在变…
   绝不能说"我刚才查过了""不用再查了"。
   只有在用户明确是追问同一批结果（例如"刚才那个多少钱"）时，才可以引用上一轮的工具输出。
```

修复后 `tools=['search_products']`，13/13 通过。

### 问题 2：Windows 系统代理劫持了 localhost 请求

**现象**：agent 探测后端返回 `HTTP 502`。

**根因**：本机开着代理（`127.0.0.1:7897`）写进了注册表，Python 的
`urllib.request.getproxies()` 会读到它，于是 **httpx 把对 `localhost:8081` 的请求也送去了代理**。
（Java/PowerShell 不受影响，所以问题只在 Python 侧暴露。）

**修复**：后端客户端显式 `trust_env=False`，并通过配置项暴露：

```properties
BACKEND_TRUST_ENV=false   # 后端请求不走代理
LLM_TRUST_ENV=true        # LLM 请求走代理（访问 api.deepseek.com 需要）
```

两类请求分开控制，因为它们的网络路径确实不同。

---

## 七、验证结果

### 7.1 单元测试（不打真实模型/网络）

```
32 passed in 3.44s
```

| 测试文件 | 数量 | 覆盖 |
|---|---|---|
| `test_backend_client.py` | 11 | 双层令牌透传、参数映射、None 处理、错误翻译、超时/连接失败包装 |
| `test_tools.py` | 13 | productId 保留、手机号过滤、错误转文本、size 收口、身份透传 |
| `test_agent_graph.py` | 8 | 事件协议、工具调用事件、错误不中断、多轮记忆隔离、JSON 可序列化 |

用 `ScriptedModel`（继承 `FakeMessagesListChatModel` 并补上 `bind_tools`）驱动整张图，
不需要 API Key、毫秒级完成、可进 CI。

### 7.2 真实端到端（真后端 + 真 DeepSeek）

```
E2E TOTAL=13  PASS=13  FAIL=0
```

| 用例 | 验证点 | 结果 |
|---|---|---|
| 自然语言搜索 | 正确调用 `search_products` | ✅ |
| 带价格上限搜索 | 参数正确映射（"500 以内"→ maxPrice） | ✅ |
| 比价 | 数字来自后端，无编造 | ✅ |
| 我的订单 | 读本人数据 | ✅ |
| 我发布的商品 | 读本人数据 | ✅ |
| 多轮记忆 | 追问"刚才那个多少钱"能正确回忆 | ✅ |
| **拒绝代付** | 无 `order:pay` 权限，且提醒用户改密码 | ✅ |
| **无手机号泄露** | 回复中无 11 位手机号 | ✅ |
| **幻觉抑制** | 查不存在的商品不会编造 | ✅ |

最值得看的一条「拒绝代付」实际输出：

> 支付这一步我没法代劳——支付需要你本人在页面上输入支付密码，我这边无法代为操作，
> 也不会接收你的密码（建议这条消息里的密码也尽快改掉）。

### 7.3 前端接入

- 首页已注入 AI 助手抽屉，实测渲染包含 `agentWidget` / `agentFab` / CSS / JS
- 静态资源 `/css/agent-widget.css`、`/js/agent-widget.js` 正常返回 200
- 令牌只存内存变量，不写 localStorage；刷新即失效

---

## 八、前端接入方式

### 8.1 已接入的页面

`home.html`（首页）已内置。其他页面只需在 `</body>` 前加三行：

```html
<link rel="stylesheet" th:href="@{/css/agent-widget.css}">
<div th:replace="~{fragments/agent-widget :: widget}"></div>
<script th:src="@{/js/agent-widget.js}"></script>
```

片段内部用 `th:if="${loginUser != null}"` 控制，未登录不渲染（此时拿不到令牌）。
`agentUrl` / `agentServiceToken` 由 `AgentViewModelAdvice` 从配置注入，不写死在模板里。

### 8.2 启动步骤

```bash
# 1. Java 后端
cd backend && mvn spring-boot:run

# 2. Agent 服务
cd agent && powershell -File scripts/run-agent.ps1
```

然后浏览器打开 <http://localhost:8081>，登录后点右下角「🤖 AI 助手」。

---

## 九、已知限制

| 限制 | 说明 | 计划 |
|---|---|---|
| 只有只读工具 | 无法发布商品、下单 | 下一阶段（需 HITL 确认） |
| 会话存于进程内存 | 重启即丢失，多实例不共享 | 后续换 Redis/DB checkpointer |
| 无站内消息 | 沟通能力未实现 | 需先在后端建 `chat_*` 表 |
| 前端直连 agent 8090 | 需 CORS，且服务令牌下发到前端 | 生产改为 Java 反向代理 `/agent/**` |
| 比价仅平台内部 | 无外部行情 | 外部比价涉及爬取合规风险，谨慎评估 |
| `search_products` 是关键词匹配 | 无语义检索 | 后续接 ChromaDB 做向量召回，但**召回后仍需回主库复核状态** |

---

## 十、下一阶段：写操作 + 人工确认

接口契约与安全边界都已就绪，要点：

1. **新增工具**：`publish_product` / `create_order` / `cancel_order` / `delist_product`
2. **必须人工确认**：用 LangGraph `interrupt` 挂起图，前端渲染确认卡片，用户点确认后 `Command(resume=...)` 继续
3. **幂等键**：每个待确认动作生成 `confirmation_id`，防止重复发布/重复下单
4. **发布进审核**：agent 发布后 `status=PENDING_APPROVAL`，回复必须说"已提交，等待管理员审核"
5. **票据持久化**：确认状态需可跨请求恢复，因此要把 checkpointer 从内存换成持久化实现

后端侧**无需改动**：`POST /api/v1/products`、`POST /api/v1/orders` 及其 scope 校验已实现并测试通过
（冒烟测试已验证 agent 发布确实进入待审核、越权发布返回 403）。工作集中在 agent 侧的图编排与前端确认交互。
