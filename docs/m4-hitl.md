# M4 实现说明：写操作 + 人工确认（HITL）

**阶段**：M4
**状态**：已完成并通过真实端到端验证
**范围**：`agent/`（后端接口在 M2 已就绪，本轮零改动）

---

## 一、为什么写操作必须人工确认

Agent 读数据是安全的，但写操作会改变真实业务状态：

| 动作 | 后果 |
|---|---|
| 下单 | 商品被锁定，其他同学买不到 |
| 发布商品 | 产生待审核内容 |
| 下架 | 自己的商品从首页消失 |
| 举报 | 影响他人账号 |

让模型自主执行这些动作，一旦理解偏差就造成真实后果。
所以设计原则是：**模型负责理解与准备，人负责拍板。**

---

## 二、机制：LangGraph interrupt + 幂等账本

### 2.1 执行时序

```
用户: "帮我发布一件闲置：台灯 45 元"
   │
   ▼ 模型决定调用 publish_product
工具内部 confirm_and_execute()
   │
   ├─ 1) interrupt({type, action, fingerprint, summary})   ← 图在此挂起
   │      SSE 产出 confirmation_required，前端渲染确认卡片
   │
   │   …… 用户点「确认执行」……
   │
   ├─ 2) resume → 校验幂等账本（是否已执行过？）
   │
   └─ 3) 执行后端调用 → 商品入库 status=PENDING_APPROVAL
```

### 2.2 三个关键实现约束

**① `interrupt()` 是抛异常实现的，且恢复时节点会重新执行**

官方文档原文：

> The graph resumes from the start of the node, **re-executing** all logic.

因此代码顺序是死的：

```python
decision = interrupt(...)      # 第一步：会被重复执行，但它是幂等的（只读）
if not approved: return        # 第二步：判断
await executor.run_once(...)   # 第三步：副作用只执行一次
```

**② `except Exception` 会吞掉 `GraphInterrupt`**

这是本轮踩的最深的坑。写工具最初写成：

```python
try:
    result = await confirm_and_execute(...)
except Exception as exc:        # ← 灾难
    return _handle_error(exc)
```

而 `interrupt()` 正是通过抛 `GraphInterrupt` 来挂起的，于是被这个 `except` 一起吃掉了。
表现极具迷惑性：**图不挂起、工具像没执行一样返回一段文本、没有任何报错**。

修复：抽出统一的 `run_tool()` 包装，控制流异常原样上抛。

```python
_PASSTHROUGH_EXCEPTIONS = (GraphBubbleUp,)   # GraphInterrupt 的基类

async def run_tool(action):
    try:
        return await action()
    except _PASSTHROUGH_EXCEPTIONS:
        raise                                 # 控制流，不是错误
    except Exception as exc:
        return _handle_error(exc)             # 业务错误转文本
```

同时给 `_handle_error` 加了日志 —— 此前它静默吞掉内部异常，
导致"断言失败但看不出原因"，排查成本极高。

**③ 幂等账本独立于图状态**

LangGraph 的恢复语义、用户双击确认、网络重试都可能造成重复触发。
账本落在 SQLite，键是 `action + 规范化参数的 SHA256`：

```
publish_product:78101968acea9fd01465bb5ab1ca3519 → SUCCESS
```

已成功执行过的指纹直接返回上次结果，**不再调用后端**。
这样"同一个确认动作"在系统层面永远只产生一次副作用。

### 2.3 为什么确认状态必须持久化

人工确认是「挂起 → 等待用户 → 恢复」的**跨请求**流程。
如果 checkpointer 只在内存：

- 用户刷新页面 → 确认丢失，操作永远无法完成
- 服务重启 → 同上

因此本轮把 `InMemorySaver` 换成了 `AsyncSqliteSaver`（`agent/data/agent_state.db`）。
测试 `test_state_survives_runner_restart` 用「同一 DB 文件 + 新建 runner」模拟重启，
验证挂起状态仍然可查、仍可继续完成。

---

## 三、新增的写工具

| 工具 | 动作 | 确认卡片关键字段 |
|---|---|---|
| `publish_product` | 发布闲置 | 标题 / 售价 / 分类 / 成色 / 地点 / 描述 |
| `update_product` | 改价改描述 | 商品 / **当前售价** / 改为… |
| `delist_product` | 下架 | 商品 / 售价 / 当前状态 |
| `create_order` | 下单 | 商品 / 价格 / 地点 / 方式 / 预约时间 |
| `cancel_order` | 取消订单 | 订单号 / 商品 / 金额 / 当前状态 |
| `submit_report` | 举报 | 商品ID / 类型 / 说明 |

确认卡片刻意放**用户能自己核对**的字段。
这张卡片是用户唯一的把关机会，缺字段等于让人盲签。

订单类工具还会**先查一次商品/订单**，把真实名称和价格填进卡片 ——
而不是只显示 `productId`。

---

## 四、SSE 协议扩展

新增一个事件类型：

```json
{
  "type": "confirmation_required",
  "action": "publish_product",
  "fingerprint": "publish_product:78101968...",
  "summary": {
    "title": "确认发布商品？",
    "fields": [{"label": "标题", "value": "..."}, ...],
    "notice": "发布后商品将进入「待审核」状态…"
  },
  "message": "这是一个会改变数据的操作，需要你确认后才会执行。"
}
```

前端渲染成黄色确认卡片，「确认执行」/「取消」两个按钮，
点击后调用 `POST /api/chat/resume`（SSE）。

新增接口：

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/chat/resume` | 用户决定后恢复执行（SSE） |
| POST | `/api/chat/resume-sync` | 非流式恢复（脚本/测试用） |
| GET | `/api/conversation/{id}/pending` | 是否有待确认动作 |
| GET | `/api/idempotency/stats` | 幂等账本统计 |

---

## 五、本轮修复的两个真实问题

### 问题 1：模型用文字征求确认，导致确认卡片永不出现

**现象**：用户说"帮我发布一件闲置"，模型回复：

> 发布前请你确认一下信息：标题 X、价格 Y…确认无误的话我就提交发布。

然后**停住了**。它把"人工确认"误解成"我要在文字里问一句"，
根本没调用工具，HITL 机制完全没被触发。用户永远等不到确认卡片。

**根因**：提示词没说明确认机制由系统负责。

**修复**：在提示词里明确写清机制，并给出正反例：

```
写操作直接调用工具，不要用文字征求确认。
确认环节由系统负责：你调用工具时系统会自动暂停并弹出确认卡片。

反面例子（错误做法）：
> 确认无误的话我就提交发布。
这样用户永远等不到确认卡片，操作根本无法完成。

正确做法：直接调用 publish_product(...)，让系统弹确认卡片。
```

同时把"你没有支付工具、不要尝试支付"也写进能力边界。

### 问题 2（测试侧）：能力令牌与服务令牌缺一不可

E2E 断言连续两次失败，显示 `mine count=0`，但数据库里商品明明存在。
加诊断后发现 `mine/list http=401`，响应是「**服务令牌无效**」——
**我的测试脚本忘了带 `X-Service-Token`**。

生产代码一直是对的（`test_backend_client.py` 里有专门的断言覆盖双层令牌）。
这次是测试脚手架自身的缺陷，也顺便给测试加了 401 自动换令牌的重试逻辑。

> 教训：断言失败时先打印原始响应，而不是猜。
> 这两个失败我一开始怀疑是时序问题，加了 `[debug] http=401` 才一眼定位。

---

## 六、验证结果

### 6.1 单元测试：39 通过

| 文件 | 数量 | 覆盖 |
|---|---|---|
| `test_backend_client.py` | 11 | 双层令牌、参数映射、错误翻译 |
| `test_tools.py` | 13 | 只读工具、隐私过滤、错误转文本 |
| `test_agent_graph.py` | 8 | 事件协议、多轮记忆、错误不中断 |
| `test_hitl.py` | **7** | **人工确认全流程（本轮新增）** |

`test_hitl.py` 的 7 项断言：

1. 写工具调用时挂起并产出 `confirmation_required`
2. **确认前绝不写库**（否则确认就是摆设）
3. 拒绝时不执行
4. 同意时执行一次
5. **重复同意同一确认，商品只创建一次**（幂等核心）
6. **不同用户的相同操作不会被误判为重复**（指纹绑定用户）
7. 用同一 DB + 新建 runner 模拟重启，挂起状态仍可恢复

### 6.2 真实端到端：14 通过（真后端 + 真 DeepSeek）

```
PASS capability token
PASS confirmation event emitted            1.6s
PASS confirmation action correct
PASS summary is user-checkable
PASS NOT written before confirmation       before=0 during=0
PASS reject does not write
PASS reject reply explains cancellation
PASS approve writes exactly one product    created=1
PASS published product is PENDING_APPROVAL status=PENDING_APPROVAL/待审核
PASS approve reply mentions review
PASS duplicate confirmation does not duplicate product  count=1
PASS no pending after completion
PASS no pay tool offered to model

M4 E2E TOTAL=14  PASS=14  FAIL=0
```

其中最关键的一条是 `duplicate confirmation does not duplicate product`：
重复提交同一确认后，商品数量仍然为 1。

### 6.3 SSE 链路验证

前端用的是 SSE 而非非流式接口，因此单独验证：

```
[confirmation_required] action=publish_product
    标题: SSE-29e3bc 台灯
    售价: ¥45.0
    分类: 生活用品
[resume] → [tool_end] publish_product ok=True
        → 已提交发布，商品 ID 29，当前状态：待审核
PASS: 商品已创建且为待审核 (count=1, status=PENDING_APPROVAL)
```

### 6.4 回归验证（M3 与 Java 侧未被破坏）

- M3 只读 E2E：13/13
- Java 冒烟测试：19/19
- Agent 单元测试：39/39

---

## 七、前端交互

`agent-widget.js` 新增 `showConfirmation()`：

- 渲染黄色确认卡片（标题 + 字段表 + 提示 + 两个按钮）
- 点击后**立即禁用按钮**，避免双击产生两次 resume
- 追加「✓ 已确认 / ✕ 已取消」状态戳，卡片保留可回溯
- 走 `/api/chat/resume` 流式接口，复用同一套 `readStream()` 事件处理

样式加在 `agent-widget.css` 的 `.agent-confirm*` 命名空间下，不影响既有页面。

---

## 八、已知限制

| 限制 | 说明 |
|---|---|
| 同一会话同时只有一个待确认动作 | 模型串行调用工具，暂不需要队列 |
| 确认卡片无超时 | 挂起的确认会一直保留，长期不用会占用存储 |
| 无操作撤销 | 确认执行后只能通过反向操作补救（如取消订单） |
| SQLite 单文件 | 多实例部署需换 Postgres/Redis checkpointer |
| 指纹用 capability token 作作用域 | token 过期换新后，同一个"未完成"的确认会得到不同指纹。因为确认卡片本身短时有效，实际影响很小；若要更严谨应改用 `userId` |

> ✅ 已修复：**幂等指纹绑定用户**。
> 早先指纹只由 `action + params` 决定，A、B 两人用同样参数发布同样商品时，
> B 的确认会被当成 A 的重复请求而静默跳过（表现："点了确认但什么都没发生"）。
> 现在 `IdempotentExecutor.fingerprint()` 接受 `scope` 参数，
> `confirm_and_execute()` 自动取当前 actor token 作为作用域，
> 并有 `test_fingerprint_is_scoped_to_user` 专门覆盖这个场景。

---

## 九、下一阶段建议

M4 完成后，剩余工作按价值排序：

1. **站内消息 + Copilot 起草**（需先在后端建 `chat_thread` / `chat_message` 表）
2. **ChromaDB 语义检索**（召回后须回主库复核状态）
3. **黄金指令集评测**（任务成功率 / 工具选择准确率 / 越权拒绝率 / 幂等命中率）
4. **确认超时与队列**（清理长期挂起的确认）
5. **指纹作用域改用 userId**（见上表最后一行）
