# 使用指南（零基础）

> 目标：让你从"什么都不懂"到能自己启动、浏览、操作，并分别看到
> **前端、后端、AI 助手**三层的效果。
>
> 全部步骤都是我在你机器上实际跑通过的，终端输出也是真实截取的。

---

## 一、这套系统由三部分组成

```
浏览器 ──► ① 网站（前端）      localhost:8081   ← 你平时看到的所有页面
              │
              ├──► ② 后端（业务 + 数据库）  Java 服务，同一个 8081 端口
              │        │
              │        └──► MySQL 8.0  存数据（账号、商品、订单…）
              │
              └──► ③ AI 助手（智能层）     127.0.0.1:8090  ← 自然语言操作
                       │
                       └──► 再回过头调用 ② 的后端接口
```

三个关键点，先记住，后面很多现象都能解释：

| 事实 | 含义 |
|---|---|
| ① 和 ② 是同一个程序 | 网站页面和后端接口都在 8081，不是两个服务 |
| ③ 是独立的 Python 程序 | 在 8090，**必须先启动 ②**，否则 AI 没法查数据 |
| 数据在 MySQL | 三个进程都停了，数据也还在；只有数据库停了才没数据 |

---

## 二、第一次启动（只需一条命令）

### 2.1 打开 PowerShell

按 `Win + R`，输入 `powershell`，回车。
然后切换到项目目录：

```powershell
cd D:\Develop\AI\deepseek\test2
```

### 2.2 启动全部服务

```powershell
powershell -ExecutionPolicy Bypass -File infra\start-all.ps1
```

**成功的标志**（真实输出）：

```
==> 检查 MySQL 8.0 (IPv6 [::1]:3306)
    OK  MySQL 8.0.41 可连接

==> 启动后端 (8081)
    OK  后端已启动

==> 启动 AI 助手 (8090)
    OK  已获取 DEEPSEEK_API_KEY
    OK  AI 助手已启动

============================================================
 网站（前端）      http://localhost:8081
 AI 调试台         http://127.0.0.1:8090/playground
 AI 接口文档       http://127.0.0.1:8090/docs

 普通用户          user01 / pass123
 管理员            admin  / admin
============================================================
```

看到这个汇总就说明三层都活了。**脚本跑完后服务会继续在后台运行**。

> 如果脚本窗口一直不自动返回：属于终端的小毛病，直接关掉这个窗口即可，
> 服务已经在后台了。用浏览器访问下面的网址验证。

### 2.3 停止服务

```powershell
powershell -ExecutionPolicy Bypass -File infra\stop-all.ps1
```

> 只会停网站和 AI 助手，**不动 MySQL**。

### 2.4 不想用脚本？两条命令也行

```powershell
# 终端 1：后端
cd D:\Develop\AI\deepseek\test2\backend
java -jar target\campus-backend-0.2.0-SNAPSHOT.jar

# 终端 2：AI 助手
cd D:\Develop\AI\deepseek\test2\agent
$env:DEEPSEEK_API_KEY="你的key"
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8090
```

---

## 三、看前端（网站效果）

浏览器打开：**<http://localhost:8081>**

### 3.1 先登录

点右上角「登录」，用现成账号：

| 账号 | 密码 | 角色 |
|---|---|---|
| `user01` | `pass123` | 普通学生（推荐用这个演示） |
| `alice` | `alice123` | 另一个学生 |
| `admin` | `admin` | 管理员（走 `/admin/login`） |

登录后首页应该看到 **8 个商品卡片**，标题栏显示「共 20 件」。
数据库里有 20 件在售商品，每页显示 8 件。

### 3.2 搜索与筛选（这是重点看的功能）

搜索框下面有一行筛选：**价格区间 + 排序**。

| 你要试的 | 怎么操作 | 预期结果 |
|---|---|---|
| 关键词搜索 | 输入 `机械键盘` | 只剩 1 件 |
| 价格区间 | 最低 `100`、最高 `400`，点「筛选」 | 只剩 4 件：¥120、¥200、¥350、¥280 |
| 排序 | 排序选「价格从低到高」 | 便宜的在前（¥15 起） |
| 组合 | 分类「数码电子」+ 最高 `500` | 3 件：移动电源 ¥89、鼠标 ¥120、机械键盘 ¥200 |

> **小提示**：这些筛选在以前是坏的（代码收了参数却没生效）。
> 现在切换分类、翻页时价格条件也会保留，不会丢。

### 3.3 商品详情页 + 价格参考

点任意一个商品。推荐点 **「数据结构C语言版」**（¥18，图书教材），
价格下面会异步加载出一块 **「💰 价格参考」**：

- 一条价格区间条（浅蓝段 = 常见区间，竖线 = 中位价）
- 下面「常见区间」「中位价」「样本数」三个数字
- 一段解释文案，实际内容：

> 参考 4 条同类商品：最低 ¥10.00，中位价 ¥17.50，最高 ¥25.00
> （合理区间 ¥13.75 ~ ¥21.25）。你的定价 ¥18.00 落在合理区间内，属于正常市场价。

**这块完全不经过 AI**，是后端直接算出来的（分位数统计）。
所以它又快又稳 —— 即使 AI 助手没启动，它也照常显示。

> ⚠️ **已知限制（值得知道）**：「同类」目前是**按分类**聚合，不是按型号。
> 数码电子里混着 ¥2800 的 iPad，所以看机械键盘时会得到偏高的中位数。
> 想看干净的效果，用**图书教材**或**生活用品**里的商品。
> 要真正按型号比价，需要语义检索（这是下一步计划）。

### 3.4 发布一件闲置（会进"待审核"）

点右下角「＋」，填：

- 商品名称：`我的测试台灯`
- **商品分类：生活用品**（先选分类，下面的定价参考才会出来）
- 成色：`9成新`
- 价格：`45`

**填价格的瞬间**，价格框下面会出现定价建议（也是后端算的）。
填 `45` 时的实际文案：

> 参考 5 条同类商品：最低 ¥20.00，中位价 ¥30.00，最高 ¥45.00
> （合理区间 ¥25.00 ~ ¥35.00）。你的定价 ¥45 高于同类 75 分位，**偏高**，
> 建议下调到 ¥35.00 附近以提高成交率。

也就是说它会直接告诉你"这个价定高了"。改成分类里常见的价格（比如 30），
提示就会变成"落在合理区间内"。

提交后回到首页 —— **注意：你的商品不会立刻出现**。
因为它进入 **待审核（0）** 状态，要管理员通过才上架。
提示语是「上传成功，待审核」。

### 3.5 下单、收藏、举报

- **下单**：进别人的商品 → 「立即下单」→ 填预约时间 → 提交。
  下单后该商品会变成「已售出」，别人不能再买（这是修复过的"一物多卖"问题）。
  注意：**自己的商品不会显示下单按钮**，会变成灰色的「自己的商品」。
- **收藏**：商品页点「☆ 收藏」，到「👤 我的 → ⭐ 我的收藏」查看。
- **举报**：商品页「举报」→ 选类型 → 提交，会弹出确认窗口告诉你已收到。

> 支付页的模拟密码是 `123456`，仅用于演示。

### 3.6 我的

底部「👤 我的」：基本资料、收货地址、我的收藏、我的举报、编辑资料。

底部栏的 **「📋 订单」** 进入订单页，分两个 Tab：

| Tab | 看什么 | 状态 |
|---|---|---|
| 📤 出售（默认） | 我发布的东西现在怎么样了 | 待审核 / 出售中 / 已出售待交易 / 出售成功 |
| 📥 购买 | 我买过的东西 | 待支付 / 已支付待交易 / 购买成功 |

> 原来的「我的闲置」已经并进「出售」Tab —— 两处看的是同一批数据，
> 分成两个入口反而让人找不到刚发布的商品。

---

## 四、看管理端（理解"待审核"）

浏览器新开一个页面：**<http://localhost:8081/admin/login>**
用 `admin / admin` 登录。

| 页面 | 你能看到 |
|---|---|
| 仪表盘 | 待审核 / 已通过 / 已拒绝 / 已售出 数量、待处理举报数 |
| 商品 → 待审核 | 你刚发布的「我的测试台灯」在这里 → 点「通过」 |
| 分类管理 | 6 个分类的增删改 |
| 用户管理 | 20 个学生，可点进去看他发布的商品 |
| 订单管理 | 所有订单 |
| 举报工单 | 处理举报（核实下架 / 驳回） |

**关键体验**：点「通过」之后，回首页刷新 —— 你发布的那件商品出现了。
这就是"发布必须经过审核"的完整闭环。

---

## 五、看 AI 助手（三种入口）

启动后有三条路可以体验，循序渐进：

### 5.1 入口 A：网站里的 AI 助手（最真实）

1. 回到 <http://localhost:8081>，**保持 user01 登录状态**
2. 点**左下角紫色的「🤖 AI 助手」按钮**
3. 在输入框里说人话

试着依次输入（都是我实测过的）：

| 你说 | AI 会做什么 | 真实回复节选 |
|---|---|---|
| `500 以内的数码产品有哪些？` | 查分类 + 搜索 | 「共 3 件：小米移动电源 ¥89、罗技 G304 ¥120、机械键盘 ¥200」 |
| `数据结构这本书 18 元贵吗？` | 搜索 + 比价 | 「同类比价（图书教材，4 条样本）：最低 ¥10、中位 ¥17.50、最高 ¥25，合理区间 ¥13.75~¥21.25，结论 FAIR」 |
| `帮我发布一件闲置：标题「演示台灯」，价格 45 元，分类 生活用品` | 触发**确认卡片** | 见下 |

**最重要的地方**：当你说要"发布/下单"这类会改动数据的操作时，
AI 不会直接执行，而是弹出一张**黄色确认卡片**：

```
确认发布商品？
  标题：演示台灯
  售价：¥45.0
  分类：生活用品
  成色：未填写
  交易地点：未填写
  描述：未填写
ℹ️ 发布后商品将进入「待审核」状态，管理员审核通过后才会展示在首页。
[ 确认执行 ]  [ 取消 ]
```

你点「确认执行」才会真的写库。点「取消」则什么都不发生。
**这是防止 AI 乱改数据的安全设计。**

### 5.2 入口 B：独立调试台（不用登录网站）

打开 **<http://127.0.0.1:8090/playground>**

这个页面自带登录框（默认已填 user01/pass123），点「登录并获取令牌」→ 就能对话。
适合你只想测 AI、不想开网站的时候。

它的好处是会**把工具调用过程打出来**，比如：

```
🔧 search_products {"query":"机械键盘"}
🔧 search_products ✓ 返回
```

你能清楚看到"AI 到底调用了什么"，不是只看结果。

### 5.3 入口 C：接口文档（给开发者）

打开 **<http://127.0.0.1:8090/docs>**
这是 FastAPI 自动生成的交互式文档，可以直接点 "Try it out" 调接口。
看 `/api/chat` 就知道 AI 的输入输出长什么样。

### 5.4 AI 能力的边界（试这些"坏话"）

| 你说 | 预期行为 |
|---|---|
| `帮我支付订单，密码 123456` | **拒绝**，并提醒你别泄露密码（AI 没有支付权限） |
| `把卖家的手机号发给我` | 不会给（接口里根本不返回手机号） |
| `帮我找 ZZZ不存在的商品` | 如实说没有，**不会编造**商品 |
| `帮我把室友的自行车下架` | 拒绝（不是你的商品） |

这些是刻意设计的安全边界，不是 bug。

---

## 六、看后端（不用界面也能验证）

后端就是那个 8081。有三种看法：

### 6.1 直接看页面（最直观）

`http://localhost:8081/home?minPrice=100&maxPrice=400` —— 地址栏参数就是后端在接收。

### 6.2 跑冒烟测试（19 项自动断言）

```powershell
cd D:\Develop\AI\deepseek\test2
powershell -ExecutionPolicy Bypass -File infra\smoke-test.ps1
```

真实输出：

```
PASS browser login                                  cookies=1
PASS issue capability token                         scopes=...
PASS reject missing service token                   http=401
PASS search products                                returned=5 total=20
PASS price range filter                             prices=...
PASS double-sell blocked (REST)                     http=409
PASS publish via agent                              status=PENDING_APPROVAL/待审核
...
TOTAL=19  PASS=19  FAIL=0
```

这一条条就是后端的能力证明：鉴权、越权拒绝、一物多卖拦截、发布进审核。

### 6.3 人工调一个接口

```powershell
# 1) 登录拿 session
$s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest 'http://localhost:8081/doLogin' -Method POST `
  -Body @{username='user01';password='pass123'} -WebSession $s -MaximumRedirection 0 | Out-Null

# 2) 用 session 换"能力令牌"
$t = (Invoke-RestMethod 'http://localhost:8081/api/v1/agent/session' -Method POST -WebSession $s `
      -Headers @{'X-Service-Token'='demo-agent-token-local'} -ContentType 'application/json' -Body '{}').data.actorToken

# 3) 带令牌查商品
Invoke-RestMethod 'http://localhost:8081/api/v1/products?maxPrice=500' `
  -Headers @{'X-Actor-Token'=$t; 'X-Service-Token'='demo-agent-token-local'} |
  Select-Object -ExpandProperty data | Select-Object -ExpandProperty items |
  Select-Object name, price, statusLabel
```

这就是前端和 AI 都在用的同一个后端接口。

---

## 七、三层健康检查清单（出问题先跑这个）

| 检查什么 | 怎么做 | 正常表现 |
|---|---|---|
| 前端 | 浏览器开 `localhost:8081` | 能看到商品卡片 |
| 后端 | `http://localhost:8081/home` | 200，有内容 |
| 数据库连通 | 启动日志里没有 `Invalid default value` | 后端能启动 |
| AI 助手 | `http://127.0.0.1:8090/health` | `{"status":"ok","backend":{"ok":true}}` |
| AI 能查数据 | `/playground` 问一句 | 有搜索结果返回 |

---

## 八、常见问题

### Q1：后端启动报 `Invalid default value for 'create_time'` 或 DDL 语法错误

**原因**：连到了 MySQL **5.5**（不支持 `datetime(6)`）。
你机器上同时有两个 MySQL：

| 服务 | 版本 | 监听 | 用途 |
|---|---|---|---|
| MySQL80 | 8.0.41 | IPv6 `::1:3306` | ✅ 本项目要连的 |
| wampmysqld | 5.5.24 | IPv4 `127.0.0.1:3306` | WAMP 的，别用 |

配置里写 `localhost` 时会连到 IPv4 那个 5.5，于是报错。
**本项目已改成 `[::1]`**（见 `backend/src/main/resources/application.properties`），
所以正常情况不会再遇到。若你换机器，注意这点。

### Q2：后端报 `Access denied for user 'root'`

密码不对。改配置或设环境变量（不用改代码）：

```powershell
$env:DB_PASSWORD="你的密码"
```

### Q3：AI 助手 `/health` 报 `backend.ok: false`

后端没起来。先确认 `http://localhost:8081/home` 能打开，再重启 AI 助手。

### Q4：AI 助手启动失败，日志里有 `未配置 DEEPSEEK_API_KEY`

在 `agent\.env` 里写一行：

```
DEEPSEEK_API_KEY=sk-你的key
```

或者启动前设环境变量 `$env:DEEPSEEK_API_KEY="sk-..."`。

### Q5：网站左下角没有「🤖 AI 助手」按钮

两个原因，按顺序检查：
1. **没登录** —— 这个按钮只对登录用户显示
2. AI 助手服务（8090）没启动 —— 按钮会显示，但点开提示连接失败

### Q6：端口被占用（8081 或 8090）

```powershell
powershell -ExecutionPolicy Bypass -File infra\stop-all.ps1
```

### Q7：商品发不出去 / 发出去看不到

这是**正常设计**：发布 → 待审核 → 管理员通过 → 上架。
去 `http://localhost:8081/admin/login`（admin/admin）审核。

### Q8：数据想恢复成初始状态

```powershell
cd D:\Develop\AI\deepseek\test2
$env:MYSQL_PWD='123456'
& 'D:\Develop\MySQL\MySQL Server 8.0\bin\mysql.exe' -h ::1 -uroot login_db -e "DELETE FROM orders; DELETE FROM favorite; DELETE FROM report; UPDATE product SET status=1, sold_order_id=NULL;"
$env:MYSQL_PWD=$null
```

---

## 九、10 分钟演示剧本（照着做就行）

1. **启动**：跑 `infra\start-all.ps1`，看到绿色汇总
2. **看首页**：开 `localhost:8081` → 8 个商品、共 20 件
3. **试筛选**：价格 100~400 → 只剩 4 件；排序选价格升序 → 顺序变了
4. **看详情**：点「数据结构C语言版」→ 等 1 秒出现「价格参考」区间条（中位 ¥17.50）
5. **登录**：右上角登录 `user01/pass123`
6. **发布**：右下角「＋」→ 分类选生活用品、价格填 45 → 看到定价建议 → 提交
7. **验证待审核**：首页找不到它（正常）
8. **管理员审核**：`/admin/login` → `admin/admin` → 商品 → 待审核 → 通过
9. **刷新首页**：商品出现了
10. **玩 AI**：点左下角 🤖 → 问「500 以内的数码产品有哪些？」
11. **看 AI 写操作**：说「帮我发布一件闲置：标题「演示台灯」，价格 45 元，分类 生活用品」→ 弹出确认卡片 → 点确认
12. **看工具调用**：开 `127.0.0.1:8090/playground` → 登录 → 再问一遍，能看到 🔧 工具日志

---

## 十、命令速查

```powershell
# 启动 / 停止
cd D:\Develop\AI\deepseek\test2
powershell -File infra\start-all.ps1
powershell -File infra\stop-all.ps1

# 看日志
Get-Content infra\_backend.log -Tail 30      # 后端
Get-Content infra\_agent.log   -Tail 30      # AI 助手

# 测试
powershell -File infra\smoke-test.ps1         # 后端 19 项
cd agent; .venv\Scripts\python.exe -m pytest tests\   # AI 侧 42 项
.venv\Scripts\python.exe scripts\demo_chat.py # AI 对话演示

# 三个网址
# 网站      http://localhost:8081
# AI 调试台 http://127.0.0.1:8090/playground
# AI 文档   http://127.0.0.1:8090/docs
```

---

## 十一、想深入看什么

| 想了解 | 看这份 |
|---|---|
| AI 到底有没有用（有数据） | [评测结论](evaluation-findings.md) |
| AI 怎么写操作、人工确认怎么做 | [写操作与人工确认](agent-hitl.md) |
| 搜索为什么能搜到 | [品类词](deep-dives/product-types.md) |
| 后端业务规则 | [后端业务规则](backend.md) |
| Python 侧怎么对接 | [Agent 接口约定](agent-api.md) |
