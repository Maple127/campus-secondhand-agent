# M1 + M2 改造记录

**阶段**：后端加固（M1）+ Agent 接口层（M2）
**范围**：`backend/`、`infra/`、`docs/`
**状态**：已完成并通过验证

---

## 一、起点：项目当时无法编译

改造前的**第一件事**不是加功能，而是发现项目根本编译不过：

```
[ERROR] 找不到符号: 方法 setUsername(java.lang.String)
[ERROR]   位置: 类型为 campus.secondhand.entity.Admin 的变量 admin
```

全部实体类的 getter/setter 都"不存在"。根因：

> **JDK 23 起，javac 不再为 classpath 上的注解处理器默认开启处理。**

Lombok 因此在编译时完全没有运行，而症状表现得像是"Lombok 坏了"。
原项目用 `java.version=21` 但实际运行时 JDK 为 24，编译目标与运行环境不一致掩盖了这个问题。

**修复**：在 `pom.xml` 显式声明

```xml
<configuration>
    <proc>full</proc>
    <annotationProcessorPaths>
        <path>
            <groupId>org.projectlombok</groupId>
            <artifactId>lombok</artifactId>
            <version>${lombok.version}</version>
        </path>
    </annotationProcessorPaths>
</configuration>
```

同时补上 `project.build.sourceEncoding=UTF-8`（源码含中文，不声明会随平台默认编码漂移）。
这两项请勿删除，否则项目无法编译。

---

## 二、正确性缺陷修复

| # | 缺陷 | 影响面 | 修复 |
|---|---|---|---|
| 1 | **一物多卖** | 数据可信性 | 新增 `ProductStatus` 状态机 + `product.sold_order_id` + `@Version` 乐观锁；下单即锁定商品，取消即释放 |
| 2 | 商品缺少「已售出」状态 | 首页展示错误 | 状态码扩展 `4 = SOLD`（与历史值 0/1/2 兼容，无需数据迁移） |
| 3 | `Order.createTime` 缺 `@CreationTimestamp` | 列表排序不稳定 | 补注解 |
| 4 | 管理员直接 `setStatus(1/2)` | 可把已售出商品"审核通过" | 审核收敛到 `ProductService` 走状态机校验 |
| 5 | 分类删除无约束 | 可删掉仍有商品的分类 | 有商品时拒绝删除 |
| 6 | 重复代码：`categoryId` 处理执行两遍 | 可维护性 | 抽为 `ProductService.applyCategory()` |
| 7 | 重复实现：`MyController` 与 `OrderController` 各有一份订单列表 | 规则漂移风险 | 统一到 `OrderService` |
| 8 | N+1 查询：模板里逐条查商品 | 性能 | `OrderService.productMapFor()` 批量取回 |
| 9 | 每次启动都执行一次性数据迁移 | 启动副作用 | 改为幂等升级，一次性迁移移出启动流程 |
| 10 | 网页端状态冲突返回 500 白页 | 用户体验 | 新增 `WebExceptionHandler` + `errorPage.html`，改为友好提示 |
| 11 | 比价分位数在单元素时返回 scale=0 | 输出不一致（`¥10` vs `¥10.50`） | 统一 `setScale(2)`（由单元测试发现） |

---

## 三、架构改造

### 3.1 分层

```
Controller（薄层：参数绑定 / 登录校验 / 模板装配）
        ↓
Service（业务规则唯一入口，网页端与 REST 端共用）
        ↓
Repository / Entity（状态机收敛在实体内部）
```

新增服务：`ProductService`、`OrderService`、`FavoriteService`、`ReportService`、
`CategoryService`、`UserService`、`AdminService`、`AuditService`、
`PriceComparisonService`、`FileStorageService`。

**关键收益**：Agent 复用业务能力时不再需要复制逻辑，从根本上防止
"网页禁止买已售出商品、agent 却能下单"这类漂移。

### 3.2 审计日志（Agent 化的安全基础设施）

`audit_log` 表记录每个写操作：

| 字段 | 说明 |
|---|---|
| `actor_type` | `USER` / `ADMIN` / **`AGENT`** / `SYSTEM` |
| `actor_id`, `actor_name` | 谁 |
| `action` | 做了什么（`product.publish` 等，集中定义于 `AuditActions`） |
| `target_type`, `target_id` | 对什么做的 |
| `detail` | 参数摘要 |
| `result`, `error_message` | 成功/失败及原因 |
| `conversation_id` | **哪次 agent 会话** |

审计写入使用 `REQUIRES_NEW` 传播：即使业务事务回滚，"有人尝试做过这件事并失败"仍然留痕。

### 3.3 双层令牌鉴权（M2 核心）

```
浏览器(HttpSession)
   │  POST /api/v1/agent/session   ← 身份来源于 session，不接受请求体传入 userId
   ▼
capability token（显式 scopes + 30min TTL）
   │  交给 Python Agent
   ▼
Python ──► /api/v1/**   X-Service-Token（是内部服务）+ X-Actor-Token（以谁的身份）
                              │
                              ▼
                   网关校验：服务令牌 + 用户令牌 + endpoint 所需 scope
```

设计要点：

- **scope 求交集**：请求的 scopes 与 `DEFAULT_USER_SCOPES` 取交集，**agent 无法自行提权**
- **`order:pay` 明确不在默认 scope 中**：支付需用户本人在页面输入支付密码，agent 不得代付
- **恒定时间比较**服务令牌，避免时序侧信道
- **`ThreadLocal` 身份在 `afterCompletion` 清理**，防止线程复用导致身份串号

---

## 四、新增文件清单

**领域与状态机**
`entity/ProductStatus.java`、`entity/OrderStatus.java`、`entity/ActorType.java`、`entity/AuditLog.java`

**公共**
`common/BusinessException.java`、`common/ActorContext.java`、`common/AuditActions.java`、
`common/ProductQuery.java`、`common/PageResult.java`

**服务层**
`service/ProductService.java`、`OrderService.java`、`FavoriteService.java`、`ReportService.java`、
`CategoryService.java`、`UserService.java`、`AdminService.java`、`AuditService.java`、
`PriceComparisonService.java`、`PriceComparison.java`、`FileStorageService.java`、
`ProductPublishCommand.java`、`CreateOrderCommand.java`

**REST / 安全**
`api/ApiResponse.java`、`api/ApiExceptionHandler.java`、`api/WebExceptionHandler.java`
`api/dto/ProductView.java`、`OrderView.java`、`UserProfileView.java`
`api/rest/ProductRestController.java`、`OrderRestController.java`、`UserRestController.java`、`AgentSessionController.java`
`security/Scopes.java`、`CapabilityToken.java`、`CapabilityTokenService.java`、
`ServiceTokenValidator.java`、`AgentAuthInterceptor.java`、`AgentSecurityConfig.java`、`ActorContextHolder.java`
`api/web/SessionActors.java`

**测试**
`ProductStatusTest`(14)、`OrderStatusTest`(5)、`PriceComparisonServiceTest`(8)、`AgentAuthInterceptorScopeTest`(10)

**基础设施**
`infra/schema.sql`（权威表结构）、`infra/seed.sql`（幂等种子）、`infra/smoke-test.ps1`（端到端验证）

---

## 五、验证结果

### 5.1 单元测试

```
Tests run: 38, Failures: 0, Errors: 0, Skipped: 0
BUILD SUCCESS
```

零外部依赖、秒级完成，可直接接入 CI。

### 5.2 端到端冒烟测试（真实起服务 + 真实 MySQL）

```
TOTAL=19  PASS=19  FAIL=0
```

覆盖：能力令牌签发、三层鉴权（服务令牌/用户令牌/scope）、每类越权拒绝、
一物多卖拦截（HTTP 409 且订单数保持 1）、商品锁定与释放、
agent 发布进入待审核、scope 提权被过滤、未登录会话请求被拒。

### 5.3 原有功能回归

27 个 Thymeleaf 页面 + 新增 `errorPage.html` 全部可访问；
首页关键词/分类/价格区间筛选正常；订单、收藏、举报、管理端审核流程正常。

---

## 六、已知限制（未处理，非遗漏）

| 限制 | 说明 |
|---|---|
| 密码明文存储与比对 | 沿用原实现。已将入口收敛到 `UserService.authenticate()` / `AdminService`，替换 BCrypt 只需改单点 |
| 支付为模拟实现 | 密码硬编码 `123456`，仅用于课程 demo |
| capability token 存于进程内 `ConcurrentHashMap` | 多实例部署需换 Redis；接口已按可替换存储设计 |
| 比价仅为平台内部同类比价 | 未接入外部行情。外部比价涉及爬取合规风险，建议只用官方 API |
| 交易沟通（站内消息）未实现 | 数据模型尚未建立，属 M6 范围 |
| 商品编辑不触发重新审核 | 当前直接更新；若要求严格，可在 `ProductService.updateOwnProduct()` 中改为回到待审核 |

---

## 七、下一步

接口契约已就绪（见 [`agent-api.md`](agent-api.md)），Python Agent 可独立开发，不需改动 Java。

建议顺序：

1. `httpx` 客户端 + 3 个只读工具（搜索 / 详情 / 比价）
2. 会话与 SSE 流式输出
3. 写操作 + LangGraph `interrupt` 人工确认 + 幂等键
4. ChromaDB 索引同步（需后端新增 outbox 表）
5. 站内消息 + Copilot 起草
6. 黄金指令集评测

详见 [`../agent/README.md`](../agent/README.md)。
