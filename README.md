# 校园二手交易平台 · AI Agent 化升级

把传统「校园二手网站」升级为**可以用自然语言驱动**的智能交易平台：
用户说一句话，AI 助手就能帮 ta 发布商品、搜索比价、跟进订单。

> 当前进度：**M1 后端加固 · M2 Agent 接口层 · M3 只读工具+SSE · M4 写操作+人工确认 · B 价值评测 · B2 搜索与比价强化 · B3 品类词，全部完成**。

## 🚀 第一次用？从这里开始

**零基础使用教程：[docs/使用指南.md](docs/使用指南.md)**

只需两条命令：

```powershell
cd D:\Develop\AI\deepseek\test2
powershell -File infra\start-all.ps1     # 启动网站 + AI 助手
powershell -File infra\stop-all.ps1      # 停止
```

然后浏览器打开 **<http://localhost:8081>**，用 `user01 / pass123` 登录。

三个要看的地址：

| 地址 | 是什么 |
|---|---|
| <http://localhost:8081> | 网站（前端页面） |
| <http://127.0.0.1:8090/playground> | AI 助手调试台（能看到工具调用） |
| <http://127.0.0.1:8090/docs> | AI 接口文档 |

> ⚠️ 本机有两个 MySQL（8.0.41 在 IPv6、WAMP 的 5.5.24 在 IPv4），
> 项目已固定连 `[::1]` 指向 8.0.41。详见 [使用指南 · 常见问题](docs/使用指南.md#八常见问题)。

## ✅ B2：按评测结论落地的两项改动

评测给出的行动顺序是「先修检索、再把不需要 LLM 的能力从 agent 里拿出来」。已完成：

| 改动 | 内容 | 效果 |
|---|---|---|
| **强化搜索框** | 价格区间筛选 + 排序 + 条件保留 | 「300 到 800 的运动器材」这类需求回到搜索框：**11ms、零成本** |
| **比价独立成功能** | 商品详情页「价格参考」+ 发布页「定价建议」 | 不需要再走 6.7 秒、¥0.015 的 agent |

过程中修掉一个**真实缺陷**：`HomeController` 收了 `minPrice`/`maxPrice`，
但 `searchOnSale` 内部把它们写死成 `null` —— 价格筛选**有入参、不生效、无报错**。

详见 [B2 改动记录](docs/b2-search-and-pricing.md)。

## ✅ B3：品类词——用标签解决「搜不到」

评测里有一条稳定失败的任务：**搜「耳机」找不到《AirPods Pro 2代》**（标题里没这两个字）。

原来计划上向量检索，后来改了：*"AirPods 是耳机"是一个事实，不是语义相似度*。
加一层**品类词 + 别名**，把词汇缺口从代码问题变成数据问题——补一个别名只是一行 SQL。

| | 改造前 | 改造后 |
|---|---|---|
| 30 个真实查询的完全命中 | 19/30 | **28/30** |
| 平均召回 | 70% | **100%** |
| Agent 搜「耳机」 | 2~3 次工具调用（试错） | **1 次，2.0s** |

三个关键决策：**单层标签**、**只做单向匹配**（双向会误召回，实测 28/28 vs 27/28）、
**词表没覆盖时退回原行为**（只会变好，不会变差）。

并且加了**搜索日志**（`/admin/search-log`）：记录搜了什么、命中几件，
按「词表不认识」和「平台没货」分栏——前者补别名，后者补供给。

零结果页面也不再是一堵墙：告诉用户是缺货还是叫法不同，并给 4 件替代推荐。
Agent 侧限制了重试次数（最多换 1 次说法），实测搜索次数 4 → 2。

详见 [品类词说明](docs/product-type-tags.md)。

## 🧪 消融评测与面试自检

- [消融评测](docs/ablation.md)：五个单变量实验——品类词 +33.3pt、压缩 −35.2%、闸门 +25 token、重试 −5.0s、路由 −48.6% 延迟
- [Agent 面试自检表](docs/agent-interview-map.md)：39 个会被追问的问题 → 答案 → 证据 → 空白（27/6/6）
- [注入防护](docs/injection-defense.md)：入口检测 + 内容围栏，22 条测试
- [显式策略路由](docs/explicit-routing.md)：REFUSE/FAST/AGENT 三路，响应带 strategy，兜底退回 agent

## 💰 议价 Copilot（第一阶段）

商品页新增「这个价值不值？」面板：给三档价（试探/目标/止损）、依据、和一段可以直接发的话术。

关键取舍：**所有金额由 Java 算，模型只负责措辞**；价格合理时明确劝你别砍；
面板**不依赖 AI 服务**（agent 挂了照常工作）。AI 助手也有同名工具，可以直接问「这个 680 值吗」。

详见 [议价 Copilot](docs/negotiation-copilot.md)。

## ⚠️ 评测结论（必读）

我用 30 条金标准任务做了对照实验（关键词搜索框 vs AI 助手），
**结论是分场景的，不是"agent 全面更好"**。下表为 B2 改动后的最新复测：

| 场景 | 搜索框（理想） | AI 助手 | 该用谁 |
|---|---|---|---|
| 找东西 | 88% / **10 ms** / ¥0 | 100% / 7344 ms / ¥0.020 | **仍是搜索框** |
| 条件筛选 | 71% | **100%** | 打平（搜索框补了价格筛选） |
| 多步任务 | 33% | **100%** | **只有 agent 能做** |
| 写操作 | 20% | 80% | **只有 agent 能做** |
| 安全边界 | 100% | 100% | 打平 |
| **总** | 63% | **97%** (29/30) | — |

**四条要记住的结论：**

1. **纯检索仍然别用 agent** —— 找东西这一档 agent 现在 100% vs 搜索框 88%，
   但多出的 12 个百分点要付 **717 倍延迟 + 每次 ¥0.02**。
   在"找一件具体东西"这种高频低价值动作上不划算，用户宁愿多试个关键词。
2. **agent 的价值在那 37%「搜索框做不到」的任务上** —— 多步编排（+67pp）与写操作（+60pp）。
   搜索框不是做得差，是**根本没有这个能力**。
3. **真正的瓶颈是检索，不是编排** —— 后端是 `LIKE %关键词%`。
   找东西能到 100% 靠的是"模型换词多试几次"这个补丁，成本也因此上升。
   **上语义检索能用一个请求替掉这几次试错。**
4. **放宽用户的硬条件比说"没有"更糟** —— 这是复测中踩到的：
   加了"搜不到就换词重试"后，模型把「50 块以下的自行车」回答成「捷安特 ¥350」。
   最终按条件分支：**可以为找东西而换词，不可以为凑结果而放宽硬条件。**

完整数据与推理过程见 [评测结论](docs/eval-findings.md)（含 4 个被修正的测量错误，
其中 2 个会得出完全相反的结论）。

---

## 1. 为什么需要先改造后端

原项目是一个典型的 Thymeleaf + JPA 单体应用，功能完整，但**没有 REST 接口、业务逻辑全部写在 Controller 里**。
Agent 要复用业务能力就只能靠 HTTP 反向调用，若不先做分层，agent 侧必然出现「第二套业务逻辑」，
最终导致网页端与 agent 行为不一致（例如网页禁止购买已售出商品，agent 却能下单）。

因此升级顺序是：**先让后端成为可被安全调用的业务真相源，再让 AI 长在上面。**

---

## 2. 目录结构

```
test2/
├── backend/              Spring Boot 4.1 后端（唯一业务真相源）
│   ├── src/main/java/campus/secondhand/
│   │   ├── api/web/      Thymeleaf 页面控制器（薄层）
│   │   ├── api/rest/     /api/v1/** REST 接口（供 Agent 调用）
│   │   ├── api/dto/      对外视图对象（与实体解耦）
│   │   ├── service/      领域服务（业务规则唯一入口）
│   │   ├── entity/       实体 + 状态机枚举
│   │   ├── repository/   数据访问
│   │   ├── security/     服务令牌 / capability token / 网关拦截器
│   │   ├── common/       统一响应、业务异常、审计动作
│   │   └── config/       数据库幂等升级、初始化
│   └── src/main/resources/
│       ├── templates/    Thymeleaf 页面（27 个）
│       └── application.properties
├── agent/                Python Agent 服务（FastAPI + LangChain v1 + LangGraph）
│   ├── app/
│   │   ├── backend.py    Java API 客户端（双层令牌透传 + 错误翻译）
│   │   ├── tools.py      只读工具（搜索/详情/比价/分类/我的商品/我的订单）
│   │   ├── write_tools.py 写工具（发布/改价/下架/下单/取消/举报）
│   │   ├── hitl.py       人工确认机制（interrupt + 确认结果解析）
│   │   ├── idempotency.py 幂等账本（防止确认被重复执行）
│   │   ├── graph.py      LangGraph 组装 + SSE 事件流
│   │   ├── prompt.py     系统提示词（幻觉抑制 / 注入防护 / 能力边界）
│   │   ├── config.py     配置（密钥只从环境变量读）
│   │   └── main.py       FastAPI 入口
│   ├── data/             运行时状态（checkpointer + 幂等账本，已 gitignore）
│   ├── tests/            39 个单元测试（Fake 模型，无需 API Key）
│   ├── eval/             价值评测：金标准任务集 + 程序化判定 + 报告
│   │   ├── gold_tasks.json  30 条任务（含 _knownIssues 诚实披露）
│   │   ├── judge.py         程序化判定（不交给 LLM 自评）
│   │   ├── evaluator.py     执行器（耗时/token/成本/落库校验）
│   │   ├── report.py        报告生成
│   │   ├── snapshot.py      库存基线校验/更新
│   │   ├── cleanup.py       清理写操作副作用
│   │   └── results/         report.md + report.json
│   └── scripts/          启动脚本、真实端到端测试
├── docs/                 设计文档与实现说明
├── infra/                数据库脚本、冒烟测试脚本
└── uploads/              商品图片存储目录
```

---

## 3. 快速开始

### 3.1 前置条件

| 组件 | 版本 | 本机验证 |
|---|---|---|
| JDK | 21+ | OpenJDK 24.0.1 |
| Maven | 3.9+ | 3.9.1 |
| MySQL | 8.0+ | 8.0.41 |

> ⚠️ **JDK 23+ 必读**：JDK 23 起 javac 不再为 classpath 上的注解处理器自动开启处理，
> 会导致 Lombok 静默失效（症状：`找不到 getter/setter`）。
> 本项目已在 `pom.xml` 中显式声明 `<proc>full</proc>` 与 `annotationProcessorPaths`，
> 请勿删除，否则项目无法编译。

### 3.2 初始化数据库

```bash
mysql -uroot -p < infra/schema.sql    # 表结构（9 张表）
mysql -uroot -p < infra/seed.sql      # 基础数据（分类/学校/管理员，幂等）
mysql -uroot -p < infra/schema-legacy.sql   # 可选：商品与用户演示数据
```

应用启动时 `DatabaseUpgrader` 会自动补齐索引、新增列并修复历史脏数据，可重复执行。

### 3.3 启动

```bash
# 1) Java 后端（业务真相源）
cd backend
mvn spring-boot:run          # http://localhost:8081

# 2) Agent 服务（AI 助手）
cd agent
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env       # 填入 DEEPSEEK_API_KEY
powershell -File scripts/run-agent.ps1   # http://127.0.0.1:8090
```

访问 <http://localhost:8081>，登录后点左下角「🤖 AI 助手」。

默认账号：普通用户 `user01 / pass123`，管理员 `admin / admin`。

> AI 助手调试台（不依赖 Java 页面）：<http://127.0.0.1:8090/playground>
> 接口文档：<http://127.0.0.1:8090/docs>

### 3.4 测试

```powershell
# Java 侧：19 项端到端断言（三层鉴权、一物多卖拦截、agent 发布进审核…）
powershell -File infra/smoke-test.ps1

# Agent 侧：39 个单元测试（Fake 模型，无需 API Key，10 秒完成）
cd agent; .venv\Scripts\python.exe -m pytest tests/

# Agent 侧真实端到端（需后端 8081 + agent 8090 都在运行，会真实调用 DeepSeek）
cd agent
.venv\Scripts\python.exe scripts/e2e_real.py      # 13 项：只读能力
.venv\Scripts\python.exe scripts/e2e_hitl.py      # 14 项：写操作 + 人工确认 + 幂等
.venv\Scripts\python.exe scripts/e2e_sse_hitl.py  #  4 项：SSE 链路下的确认流程
```

### 3.5 价值评测（B 阶段）

```powershell
cd agent
# 1) 校验库存基线与任务集快照一致（不一致会中止，避免结果不可复现）
.venv\Scripts\python.exe -m eval.snapshot

# 2) 跑评测（30 条任务 × 3 组对照，约 4 分钟，花费约 ¥0.5）
.venv\Scripts\python.exe -m eval.run_eval

# 3) 清理写操作副作用（下单会锁库存）
.venv\Scripts\python.exe -m eval.cleanup
```

结果写到 `agent/eval/results/report.md` 与 `report.json`。
常用参数：`--only L01,C01`、`--conditions agent`、`--no-writes`。

---

## 4. 本次升级做了什么

### 4.1 修复的正确性缺陷

| # | 问题 | 影响 | 修复方式 |
|---|---|---|---|
| 1 | **项目根本无法编译** | Lombok 未生效，所有实体没有 getter/setter | POM 显式 `<proc>full</proc>` |
| 2 | **一物多卖** | 下单/支付都不校验商品状态，同一商品可被无限次下单 | 引入 `ProductStatus` 状态机 + `sold_order_id` + `@Version` 乐观锁，下单即锁定、取消即释放 |
| 3 | 商品无「已售出」状态 | 成交后商品仍显示在首页 | 新增状态码 `4 = SOLD` |
| 4 | `Order.createTime` 无 `@CreationTimestamp` | 依赖调用方手动赋值，漏设则为 null，排序不稳定 | 补注解 |
| 5 | 管理员可直接 `setStatus(1/2)` | 可把已售出商品「审核通过」 | 审核走 `ProductService` 状态机校验 |
| 6 | 密码明文比对 | 安全债 | 保留（demo），但登录/改密入口已收敛到 `UserService`/`AdminService` 单点，便于替换 BCrypt |
| 7 | 分类删除无约束 | 可删掉仍有商品的分类 | 有商品时拒绝删除 |
| 8 | `ProductController` 中 `categoryId` 处理重复两遍 | 冗余代码 | 抽为 `ProductService.applyCategory()` |
| 9 | `MyController` 与 `OrderController` 各有一份订单列表逻辑 | 双份实现容易漂移 | 统一到 `OrderService` |
| 10 | 订单列表在模板里逐条查商品（N+1） | 性能 | `productMapFor()` 批量取回 |

### 4.2 架构改造

- **抽取 Service 层**：`ProductService` / `OrderService` / `FavoriteService` / `ReportService` /
  `CategoryService` / `UserService` / `AdminService` / `AuditService` / `PriceComparisonService` / `FileStorageService`。
  Controller 全部变成薄层，网页端与 REST 端共用同一套规则。
- **状态机收敛到实体**：`Product.approve()/reject()/delist()/markSold()/releaseFromOrder()`，
  非法迁移在实体内部就被拒绝，Service 负责翻译成可读的业务异常。
- **审计日志**：`audit_log` 表记录每次写操作的 `actor_type / actor_id / action / target / result / conversation_id`。
  这是 agent 化的安全基础设施——任何一条由 AI 创建的商品都能追溯到「谁、经由哪次会话」。
- **数据库迁移幂等化**：`DatabaseUpgrader` 全部加存在性判断，并修复「商品在售但已有成交订单」的历史矛盾数据。

### 4.3 Agent 接口层（M2）

**双层令牌鉴权**，让 Python 无法越权：

```
浏览器(HttpSession) ──POST /api/v1/agent/session──► Java 签发 capability token
        │
        └─► 前端把 token 交给 Python Agent
                     │
                     └─► Python 调用 /api/v1/**
                          带 X-Service-Token（证明是内部服务）
                          带 X-Actor-Token（证明以谁的身份）
                                │
                                ▼
                     网关校验：服务令牌 + 用户令牌 + endpoint 所需 scope
```

关键设计：

- **服务令牌**：`X-Service-Token`，挡住外部直接调用内部接口。
- **能力令牌**：`X-Actor-Token`，只携带明确授予的 scopes，TTL 30 分钟。
- **越权双重防护**：Python 请求的 scope 会与 `DEFAULT_USER_SCOPES` 取交集，无法自行提权；
  网关再按 endpoint 校验所需 scope。
- **支付明确排除**：`order:pay` 不在默认 scope 中——支付需要用户在页面上输入支付密码，**不允许 agent 代付**。
- **身份不可伪造**：`/api/v1/agent/session` 的身份来源是浏览器 HttpSession，而不是请求体里的 userId。

### 4.4 REST 接口一览

| 方法 | 路径 | 所需 scope | 说明 |
|---|---|---|---|
| POST | `/api/v1/agent/session` | 服务令牌 | 用网页登录态换取能力令牌 |
| GET | `/api/v1/products` | `product:read` | 检索（关键词/分类/价格区间/排序），仅返回在售 |
| GET | `/api/v1/products/{id}` | `product:read` | 详情 |
| GET | `/api/v1/products/{id}/price-comparison` | `product:read` | **内部同类比价**（分位数统计） |
| POST | `/api/v1/products` | `product:publish` | 发布（**进入待审核**） |
| PATCH | `/api/v1/products/{id}` | `product:update` | 修改自己的商品 |
| POST | `/api/v1/products/{id}/delist` | `product:delist` | 下架 |
| GET | `/api/v1/products/mine/list` | `product:read` | 我发布的 |
| GET | `/api/v1/orders` | `order:read` | 我的订单（role=buyer/seller） |
| GET | `/api/v1/orders/{orderNo}` | `order:read` | 订单详情 |
| POST | `/api/v1/orders` | `order:create` | 下单（会锁定商品） |
| POST | `/api/v1/orders/{orderNo}/cancel` | `order:cancel` | 取消（释放商品） |
| GET/POST | `/api/v1/favorites`、`/favorites/{id}` | `favorite:read/write` | 收藏 |
| GET/POST | `/api/v1/reports/mine`、`/reports` | `report:read/submit` | 举报 |
| GET/PATCH | `/api/v1/me` | `profile:read/update` | 个人资料 |
| GET | `/api/v1/meta/categories` | `product:read` | 分类列表 |

统一响应体：`{ "code": 0, "message": "ok", "data": ... }`；错误时 HTTP 状态码与 `code` 同步。

**比价由后端计算**：`p25 / median / p75 / 建议区间 / 结论`全部来自 `PriceComparisonService`，
LLM 只负责转述，从根上杜绝「模型编造一个价格区间」。

---

## 5. 已验证的行为

| 验证项 | 结果 |
|---|---|
| 原有 27 个 Thymeleaf 页面全部可访问 | ✅ 200 |
| 首页关键词 / 分类 / 价格区间筛选 | ✅ 正常 |
| 第二人下单已被售出的商品 | ✅ 409 且订单数保持 1 |
| 下单后商品锁定为「已售出」 | ✅ `status=4, sold_order_id` 写入，`version` +1 |
| 取消订单后商品自动回到「在售」 | ✅ |
| 缺少/伪造服务令牌 | ✅ 401 |
| 缺少/伪造能力令牌 | ✅ 401 |
| 只读令牌尝试发布商品 | ✅ 403 |
| 请求越权 scope（如 `order:pay`） | ✅ 被交集过滤，不予授予 |
| 未登录请求 agent 会话 | ✅ 401 |
| agent 发布商品 | ✅ 直接进入 `PENDING_APPROVAL`，不绕过审核 |
| 网页端重复下单 | ✅ 友好提示并重定向，非 500 |
| 审计日志可追溯 agent 操作 | ✅ `actor_type=AGENT` + conversation_id |

### 5.1 Agent 侧（真实 DeepSeek 端到端）

| 验证项 | 结果 |
|---|---|
| 自然语言搜索（"有没有便宜点的 iPad"） | ✅ 正确调用 `search_products` |
| 价格条件理解（"500 以内的数码产品"） | ✅ 映射为 `maxPrice=500` |
| 同类比价 | ✅ 数字全部来自后端，无编造 |
| 多轮记忆（"刚才那个多少钱"） | ✅ 正确回忆上一轮结果 |
| **拒绝代付**（用户给出支付密码） | ✅ 无 `order:pay` 权限，并提醒用户改密码 |
| **隐私保护** | ✅ 回复中无卖家手机号 |
| **幻觉抑制**（查不存在的商品） | ✅ 如实说没找到，不编造商品 |
| SSE 增量输出 | ✅ 61 个 token 事件，首 token 1.0s |
| Agent 单元测试 | ✅ 39/39 通过（10s，无需 API Key） |
| Agent 只读端到端 | ✅ 13/13 通过 |

### 5.2 Agent 写操作与人工确认（M4）

| 验证项 | 结果 |
|---|---|
| 写操作弹出确认卡片 | ✅ 卡片含标题/售价/分类/成色/地点/描述 |
| **确认前不写库** | ✅ 挂起期间商品数不变 |
| 用户取消 → 不执行 | ✅ 商品数不变 |
| 用户确认 → 执行一次 | ✅ 商品创建且为 `PENDING_APPROVAL` |
| **重复确认不重复执行** | ✅ 幂等账本拦截，商品数仍为 1 |
| **不同用户相同操作不误判** | ✅ 指纹绑定用户身份 |
| 确认状态跨重启存活 | ✅ SQLite checkpointer |
| SSE 链路下的确认流程 | ✅ 事件不丢包 |
| 写操作端到端 | ✅ 14/14 通过 |

详细实现说明见 [M4 HITL 实现说明](docs/m4-hitl.md)。

### 5.3 价值评测（B 阶段，30 条任务 × 3 组对照）

| 验证项 | 结果 |
|---|---|
| 判定是否独立于 LLM | ✅ 全部程序化规则，无自评 |
| 库存基线校验 | ✅ 不一致时中止，避免不可复现的结果 |
| 写操作落库校验 | ✅ 确认卡片字段 + 实际落库状态双重校验 |
| 评测副作用清理 | ✅ 取消订单释放商品，任务集数据未被污染 |
| 报告与逐条数据一致性 | ✅ 统计一律从逐条结果现算 |

评测暴露并修正了 4 个测量错误，其中 2 个会得出**完全相反**的结论
（详见 [评测结论](docs/eval-findings.md)）。

---

## 6. 下一步

评测给出了一条明确的行动顺序 —— **先修检索，再加能力**。
前两项已完成（见开头 B2 章节），剩余：

1. ~~**强化搜索框**~~ ✅ 已完成
2. ~~**把比价从 agent 里拿出来**~~ ✅ 已完成
3. **ChromaDB 语义检索**（评测指出的真实瓶颈）
   搜「耳机」找不到《AirPods Pro 2代》。召回后仍须回主库复核状态。
   **优先级高于再加 agent 工具** —— 否则是在查不准的底座上加功能。
4. **站内消息 + Copilot 起草**
   需先在后端建 `chat_thread` / `chat_message` 表。
5. **补评测的严谨性**：多次运行取均值与方差；增加多轮对话任务；
   并重跑一次评测，验证 B2 是否真的把「条件筛选」一档拉平。
6. **确认超时与清理**：长期挂起的确认需要回收。

## 7. 相关文档

- [评测结论](docs/eval-findings.md) — **建议先读这个**：agent 在哪些场景赢/输，以及为什么
- [设计文档](docs/系统设计文档.md) — 原有管理端流程与测试用例
- [Agent 接口约定](docs/agent-api.md) — Python 侧对接说明
- [Agent 实现说明](docs/agent-implementation.md) — 工具设计、SSE 协议、踩坑与修复
- [M4 HITL 实现说明](docs/m4-hitl.md) — 人工确认机制、幂等账本、踩坑与修复
- [B2 改动记录](docs/b2-search-and-pricing.md) — 搜索强化与比价独立成功能
- [M1/M2 改造记录](docs/m1-m2-changelog.md) — 后端加固的完整变更

## 8. 已知限制

**产品层面**
- 交易沟通（站内消息）尚未实现
- 检索是关键词匹配，无语义能力（评测已证明这是主要短板）
- 价格筛选是精确数值比较，不支持"100 左右"这类模糊语义
- 排序只支持发布时间与价格，无热度/距离
- 比价样本含"已售出"商品，成交价与挂牌价混用可能拉低中位数
- 收藏功能后端有权限但 agent 侧未开放为工具

**工程层面**
- 密码仍为明文存储与比对（原项目如此），未引入 Spring Security
- 支付为模拟实现，密码硬编码 `123456`
- capability token 存于进程内 Map，多实例部署需替换为 Redis
- 确认卡片无超时机制，长期挂起的确认会占用存储
- 幂等指纹以 capability token 作作用域，token 换新后同一未完成确认会得到新指纹
- 前端直连 agent 端口（跨源），生产应改为由 Java 反向代理 `/agent/**`
- agent 单次约 7000 输入 token（12 个工具 schema 每轮都传），有优化空间
- `/web/**` 价格参考端点未加频率限制，实际部署需补

**评测层面**
- 30 条任务偏少，单分类 4~8 条，一个任务就是 12~25 个百分点
- 单次运行，未多次取均值（已观察到运行间方差：同一配置见过 87% / 83% / 97%）
- 任务分布是人为设定的，结论对分布敏感
- 判定规则只认第一次搜索入参，对"换词兜底"不友好
- 有对被测系统过拟合的风险：B2 的两处 agent 修复是看着失败用例做的
  （但都写成了通用规则并补了单元测试，非针对单条任务特判）
