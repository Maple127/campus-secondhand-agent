# Agent 服务（AI 助手核心）

把自然语言指令转成对后端业务接口的调用：用户说一句话 → 理解意图 → 调用工具 → 自然语言回应。

**技术栈**：Python 3.11 · FastAPI · LangChain v1 · LangGraph · DeepSeek

> 状态：**M4 已完成** —— 6 个只读工具 + 6 个写工具，SSE 流式对话，
> 写操作经 LangGraph `interrupt` 人工确认 + 幂等账本保护，确认状态持久化到 SQLite。

---

## 快速开始

```bash
cd agent

# 1) 建虚拟环境（必须 3.11/3.12；3.13+ 部分依赖 wheel 尚不完整）
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2) 配置
copy .env.example .env
#    填入 DEEPSEEK_API_KEY
#    AGENT_SERVICE_TOKEN 必须与后端 application.properties 的 app.agent.service-token 一致

# 3) 启动（需先启动 Java 后端）
powershell -File scripts/run-agent.ps1
```

| 地址 | 用途 |
|---|---|
| <http://127.0.0.1:8090/playground> | 独立调试台，不依赖 Java 页面 |
| <http://127.0.0.1:8090/docs> | 自动生成的 API 文档 |
| <http://127.0.0.1:8090/health> | 健康检查（含后端连通性） |

接入到 Java 页面后，登录 <http://localhost:8081> 点右下角「🤖 AI 助手」即可。

---

## 目录结构

```
agent/
├── app/
│   ├── config.py            配置（密钥只从环境变量/.env 读）
│   ├── backend.py           Java API 客户端：双层令牌透传 + 错误翻译
│   ├── tools.py             工具层（6 个只读工具，ContextVar 传身份）
│   ├── prompt.py            系统提示词（幻觉抑制/注入防护/能力边界）
│   ├── graph.py             LangGraph 组装 + SSE 事件协议
│   ├── main.py              FastAPI 入口
│   └── static/playground.html
├── tests/                   39 个单元测试（Fake 模型，无需 API Key）
├── scripts/
│   ├── run-agent.ps1        启动脚本
│   ├── e2e_real.py          只读能力端到端（13 项）
│   ├── e2e_sse.py           SSE 流式验证
│   ├── e2e_hitl.py          写操作 + 人工确认 + 幂等（14 项）
│   └── e2e_sse_hitl.py      SSE 链路下的确认流程（4 项）
└── requirements.txt
```

---

## 当前工具

**只读（6 个，直接执行）**

| 工具 | 用途 |
|---|---|
| `search_products` | 关键词 / 分类 / 价格区间搜索（仅返回在售商品） |
| `get_product` | 商品详情 |
| `compare_price` | 同类比价（分位数统计由后端计算） |
| `list_categories` | 分类列表 |
| `list_my_products` | 我发布的商品 |
| `list_my_orders` | 我的订单 |

**写（6 个，需用户确认后才执行）**

| 工具 | 用途 |
|---|---|
| `publish_product` | 发布闲置（进待审核） |
| `update_product` | 改价 / 改描述 |
| `delist_product` | 下架 |
| `create_order` | 下单（会锁定商品） |
| `cancel_order` | 取消未付款订单 |
| `submit_report` | 举报违规商品 |

写操作走 `app/hitl.py` 的 `confirm_and_execute()`：先 `interrupt()` 挂起并推确认卡片，
用户点确认后才执行，且外面套了幂等账本防止重复执行。

---

## 测试

```bash
# 单元测试：不碰网络与真实模型，10 秒完成，可进 CI
.venv\Scripts\python.exe -m pytest tests/

# 真实端到端：需后端(8081) + agent(8090) 都在运行
.venv\Scripts\python.exe scripts/e2e_real.py       # 只读能力
.venv\Scripts\python.exe scripts/e2e_hitl.py       # 写操作 + 确认 + 幂等
.venv\Scripts\python.exe scripts/e2e_sse_hitl.py   # SSE 链路确认
.venv\Scripts\python.exe scripts/e2e_sse.py        # SSE 增量输出
```

单元测试用 `ScriptedModel`（继承 `FakeMessagesListChatModel` 并补上 `bind_tools`）驱动整张图，
因此不需要 API Key 也能验证事件协议、工具调用、多轮记忆与人工确认全流程。

---

## SSE 事件协议

`POST /api/chat/stream`，请求头 `X-Actor-Token`，请求体 `{message, conversationId}`。

每个 SSE 事件的 `data` 为 JSON：

```json
{"type":"token","text":"你"}
{"type":"tool_start","name":"search_products","args":{"query":"键盘"}}
{"type":"tool_end","name":"search_products","ok":true,"preview":"..."}
{"type":"confirmation_required","action":"publish_product","fingerprint":"...","summary":{"title":"...","fields":[...],"notice":"..."}}
{"type":"done","steps":1}
{"type":"error","message":"..."}
```

前端累加 `token.text` 即为最终回答；
收到 `confirmation_required` 时渲染确认卡片，用户点击后调用
`POST /api/chat/resume`（同样返回 SSE）继续执行。

---

## 设计要点

### 身份流转

```
浏览器(Java session) → POST /api/v1/agent/session → capability token
                     → X-Actor-Token 给 agent
                     → agent 带 X-Service-Token + X-Actor-Token 调 /api/v1/**
```

Agent 不签发令牌、不接触密码。令牌只存前端内存变量，刷新即失效。

### 四条安全红线

1. **业务规则不在 Python 侧**：所有状态校验、权限判断、事务都在 Java。
   Python 不直连数据库、不写 SQL，因此网页端与 agent 行为不可能漂移。
2. **隐私在数据层剥离**：工具返回里根本没有 `sellerPhone` 字段，
   而不是靠提示词"请不要说手机号"——提示词可能被绕过，数据不在上下文里则无从泄露。
3. **权限类错误不重试**：403/401 会转成明确写着"请勿重试"的文本交给模型。
4. **写操作必须人工确认 + 幂等保护**：`interrupt()` 挂起等用户拍板，
   幂等账本保证同一确认只产生一次副作用（幂等指纹绑定用户身份）。

### 两个容易踩的实现坑

| 坑 | 现象 | 处理 |
|---|---|---|
| `except Exception` 吞掉 `GraphInterrupt` | 图不挂起、工具像没执行一样返回文本、**无任何报错** | 统一用 `run_tool()`，控制流异常原样上抛 |
| 提示词没说清"确认由系统负责" | 模型用文字问"确认无误我就提交"然后停住，确认卡片永不出现 | 在提示词里写清机制并给出正反例 |

### 已知环境坑

| 坑 | 现象 | 处理 |
|---|---|---|
| JDK 23+ Lombok 失效 | 后端找不到 getter/setter | 属后端问题，见 `backend/pom.xml` 的 `<proc>full</proc>` |
| Windows 系统代理 | agent 调 localhost 后端返回 502 | `BACKEND_TRUST_ENV=false`（LLM 请求相反，默认走代理） |
| 控制台 GBK 编码 | 模型回复含 emoji 时脚本崩溃 | 脚本内 `sys.stdout.reconfigure(encoding="utf-8")` |
| Python 3.13 wheel 不全 | 依赖装不上 | 用 Python 3.11 |
| `X-Service-Token` 漏传 | 后端返回 401「服务令牌无效」 | 调 `/api/v1/**` 必须同时带服务令牌与能力令牌 |

---

## 下一阶段

1. 站内消息 + Copilot 起草（需后端先建 `chat_*` 表）
2. ChromaDB 语义检索（召回后须回主库复核状态）
3. 黄金指令集评测（含幂等命中率、越权拒绝率）
4. 确认超时与清理

详见 [../docs/m4-hitl.md](../docs/m4-hitl.md)。
