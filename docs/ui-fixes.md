# 界面问题修复记录（8 项）

反馈来源：用户实测。全部已修复并在 `infra/ui-fix-verify.py` 里逐条断言（29 项，全通过）。

---

## 1. AI 助手按钮与发布「＋」的位置

**第一轮**：原本 `#agentFab { bottom: 96px }`，而发布按钮是
`right:20px / bottom:80px / 直径 56px`（占 80~136px），两者正好叠在一起。
先改成 `bottom: 148px` 叠到 `+` 上方。

**第二轮（按你的要求）**：改为**左下角**，彻底不再和右下角的 `+` 抢位置。

```css
#agentFab {
    left: 22px;
    right: auto;
    bottom: 80px;   /* 底部导航固定占 0~50px，抬到它上面 */
}
```

抽屉也一起从左下弹出（`.agent-panel { left: 22px }`）——
按钮在左下、面板却从右下弹出会让人找不到对应关系。

移动端：按钮 `left:14px / bottom:76px`，面板左右各 8px（近全屏）。

---

## 2. 发布后「上传成功，待审核」不明显

**原因**：只是一条浅绿色顶部横幅，首页内容多、用户提交完就往下滚，很容易没看到。

**修复**：改成**模态弹窗**，必须点「确认」才能继续：

- 新增可复用片段 `templates/fragments/feedback-modal.html`
- 后端 `ProductController.doPublish` 改为 flash `publishSubmitted` + 文案
- 首页渲染弹窗，文案带商品名：「『xxx』已提交成功。商品会先进入「待审核」状态…」

---

## 3. user01 能买 user01 发布的商品

**表面看是 UI 问题，实际是数据 bug。**

商品页显示"卖家 user01"，但数据库里 `seller_id` 与 `seller_name` 对不上：

```
id=1  高等数学   seller_id=2   seller_name=user01   ← 名字是 user01，id 却是 user02
```

原始种子数据整体错位了一位。所以 `isOwnedBy(当前用户id)` 返回 false，
按钮照常显示，后端也不拦（买家 1 ≠ 卖家 2），**真的能下单成功**。

**修复两部分**：

1. **数据**：按用户名回填 `seller_id`，20 行全部对齐（现 0 行不一致）
   ```sql
   UPDATE product p JOIN users u ON u.username = p.seller_name
   SET p.seller_id = u.id WHERE p.seller_id <> u.id;
   ```
2. **UI**：`ProductController.detail` 增加 `isOwner`，商品页据此渲染
   - 自己的商品 → 灰色禁用按钮「自己的商品」（而不是让用户点了才被拒）
   - 别人的商品 → 正常「立即下单」

---

## 4. 支付成功后没有返回首页；「我的订单」是死链

**两个问题**：

- `paySuccess.html` 只有「查看订单」「我的订单」两个按钮，没有回首页
- 那个「我的订单」写的是 `href="/list"`，**后端根本没有 `/list` 路由**
  （真正的是 `/order/list`），点进去 404

**修复**：三个出口

```
[查看这一单] [全部订单 → /order/list] [返回首页 → /home]
```

---

## 5. 「我的闲置」与「我的订单」重合，合并成两个 Tab

**原因**：两个页面看的是同一批数据，但各自只看到一半：

- 「我的闲置」= 我发布的商品（能看到待审核/出售中）
- 「我的订单」= 我参与的订单（看不到还没卖出去的商品）

**修复**：合并到 `/order/list`，两个 Tab，**默认「出售」**：

| Tab | 内容 | 状态标签 |
|---|---|---|
| 📤 出售（默认） | 我发布的全部商品 + 各自最新订单 | 待审核 / 出售中 / 已出售待交易 / 出售成功（+审核未通过、已下架、订单已取消） |
| 📥 购买 | 我下的全部订单 | 待支付 / 已支付待交易 / 购买成功 / 已取消 |

实现要点：

- 新增 `SellItemView`，把"商品状态 + 订单状态"合成一个阶段标签，
  **在 Java 里算，不散落在模板的 th:if 里**
- 出售栏列的是**商品**而非订单 —— 因为待审核/出售中根本没有订单
- 顺带把下架/重新提交审核也搬进来（原来只在「我的闲置」有）
- `ProductController.delist/relist` 的跳转目标改为 `/order/list`
- `/myItems` 保留为跳转到 `/order/list`，旧书签不失效
- 个人中心去掉「我的闲置」入口

---

## 6. 底部栏「收藏」改成「订单」

- `home.html` 底部：`⭐ 收藏` → `📋 订单`（跳 `/order/list`）
- 收藏改动是低频操作，移到「我的 → 我的收藏」，没有丢失入口
- 同时把 `📦 闲置` 改名为 `📦 发布`（它实际跳的就是发布页）

顺带修了个人中心两个死链：`/list` → `/order/list`，`/settings`（无此路由）→ `/edit-profile`。

---

## 7. 举报后没有反馈

**原因**：`ReportController` 提交后塞的是 flash `success`，
而**商品页根本不渲染 `success`** —— 用户点完"提交举报"页面毫无变化。

**修复**：改用统一的反馈弹窗（同问题 2），文案：

> 感谢反馈，我们已收到你的举报。
> 管理员会尽快核实处理，处理结果会出现在「我的 → 我的举报」。

---

## 8. 管理端缺少「返回控制台」

**原因**：只有「举报工单」页有 `⬅️ 返回控制台`，其它页面只有右上角一个「首页」文字链接。

**修复**：新增 `templates/admin/_backbar.html`，`position: sticky` 顶部条
（sticky 而不是 fixed，避免遮住内容），插入到 10 个子页面：

商品管理 / 商品详情 / 分类管理 / 新增分类 / 编辑分类 / 用户管理 /
用户商品 / 订单管理 / 订单详情 / 修改密码

### 8.1 举报工单页统一成主流风格

原本这一页是早期写法：`<strong>🚩 全局举报工单处理</strong>` 加几个彩色文字链接，
和别的模块完全不同。现在整页重写，与「商品审核管理」保持一致：

| 项 | 原来 | 现在 |
|---|---|---|
| 顶部 | 只有一行 `.nav` | 黑色抬头 `.header`（`校园二手交易平台 - 管理后台` + 欢迎/首页/退出登录） |
| 返回 | `.nav` 里一个蓝字链接 | 统一的 `_backbar` 吸顶条 |
| 标题 | `<strong>🚩 全局举报工单处理</strong>` | `<h2>举报工单处理</h2>` |
| 筛选 | 4 个彩色文字链接 | `.status-tabs` 胶囊 Tab（当前项高亮） |
| 提示 | 无 | `success` / `error` 提示条 |
| 表格 | 细边框 | 圆角白卡 + 阴影，与管理端其它表格一致 |

功能未变：提交处理意见、核实下架、驳回、批注展示都保留并回归验证过。

---

## 验证

```
infra/ui-fix-verify.py      29/29 通过（8 个问题逐条断言）
infra/smoke-test.ps1        19/19 通过
后端单元测试                 44/44 通过
Agent 单元测试               42/42 通过
```

验证脚本里有两点值得注意（都是踩过的坑）：

- **断言前要剥掉 HTML 注释**：源码注释里会自然写着被移除的功能名
  （"原来这里是收藏"），直接搜字符串会误判成功能残留
- **CSS 断言前要剥掉 CSS 注释**：同一个原因

## 附：新增/修改文件

| 文件 | 改动 |
|---|---|
| `templates/fragments/feedback-modal.html` | 新增：通用反馈弹窗 |
| `templates/admin/_backbar.html` | 新增：管理端返回条 |
| `api/web/SellItemView.java` | 新增：出售栏的阶段标签映射 |
| `api/web/OrderController.java` | 出售视角数据（商品+订单） |
| `api/web/ProductController.java` | isOwner、跳转目标、发布弹窗 flash |
| `api/web/ReportController.java` | 举报弹窗 flash |
| `service/OrderService.java` | `latestOrderByProduct` 批量取订单 |
| `repository/OrderRepository.java` | `findByProductIdIn...` |
| `templates/Order.html` | Tab 重写 |
| `templates/product.html` | 自己的商品禁用下单、举报弹窗 |
| `templates/home.html` | 发布弹窗、底部栏 |
| `templates/my.html` | 去闲置入口、修死链 |
| `templates/paySuccess.html` | 三个出口按钮 |
| `static/css/agent-widget.css` | AI 按钮位置上移 |
