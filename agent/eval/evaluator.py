"""评测执行器：把同一批任务跑在 agent 与基线上，产出可比较的观测结果。

## 度量口径

| 指标 | 口径 |
|---|---|
| 成功率 | 判定器规则通过的任务占比 |
| 延迟 | 端到端墙钟时间（含模型推理 + 工具调用） |
| 输入/输出 token | 从流式 chunk 的 `usage_metadata` 累加 |
| 成本 | 按可配置单价换算（默认 DeepSeek 定价） |
| 越权拒绝率 | 安全类任务全部通过的占比 |
| 幂等命中率 | 写操作重复确认时被正确拦截的比例 |

## 写操作怎么测

写操作会改数据库，因此：
  1. 先跑一轮拿确认卡片 -> 校验字段
  2. 自动确认（模拟用户点"确认执行"）-> 校验落库
  3. 立刻清理产生的数据

这样既能验证真实副作用，又不会污染评测环境。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from eval.judge import Outcome, ToolCall, judge
from eval.schema import Task, TaskSet

logger = logging.getLogger("eval")

#: DeepSeek 定价（元 / 百万 token）。写死默认值，但允许覆盖 —— 价格会变，
#: 硬编码单价会让"成本"这个指标悄悄失真。
PRICE_IN_PER_MTOK = 2.0
PRICE_OUT_PER_MTOK = 8.0


@dataclass
class TaskResult:
    """单条任务的评测记录。"""

    task_id: str
    category: str
    message: str
    condition: str
    success: bool
    reason: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_cny: float
    tool_names: list[str]
    had_confirmation: bool
    write_verified: bool | None
    error: str | None
    reply_excerpt: str


@dataclass
class ConditionReport:
    """某个对照组的汇总。"""

    condition: str
    total: int = 0
    passed: int = 0
    by_category: dict[str, dict[str, int]] = field(default_factory=dict)
    latency_ms_avg: float = 0.0
    latency_ms_p50: float = 0.0
    latency_ms_max: int = 0
    tokens_in_total: int = 0
    tokens_out_total: int = 0
    cost_cny_total: float = 0.0
    safety_pass: int = 0
    safety_total: int = 0
    results: list[TaskResult] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def cost_per_task(self) -> float:
        return self.cost_cny_total / self.total if self.total else 0.0


class Evaluator:
    """评测主体。"""

    def __init__(
        self,
        *,
        agent_url: str,
        backend_url: str,
        service_token: str,
        actor_token: str,
        java_user: str = "user01",
        java_password: str = "pass123",
        price_in: float = PRICE_IN_PER_MTOK,
        price_out: float = PRICE_OUT_PER_MTOK,
    ) -> None:
        self.agent_url = agent_url.rstrip("/")
        self.backend_url = backend_url.rstrip("/")
        self.service_token = service_token
        self.actor_token = actor_token
        self.java_user = java_user
        self.java_password = java_password
        self.price_in = price_in
        self.price_out = price_out
        #: 置位后由主循环在下一个任务前续期令牌（避免每条任务都登录）
        self._need_refresh = False
        #: 基线用的长连接客户端（懒创建，评测结束关闭）
        self._shared_client: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        """取共享的 HTTP 客户端。

        为什么必须共享：基线在浏览器里是复用连接点一下搜索，
        每条任务都新建客户端会把连接建立开销算成"搜索耗时"，
        把基线人为拉慢两个数量级 —— 评测结论就完全不可信了。
        """
        if self._shared_client is None:
            self._shared_client = httpx.AsyncClient(timeout=30, trust_env=False)
        return self._shared_client

    async def aclose(self) -> None:
        if self._shared_client is not None:
            await self._shared_client.aclose()
            self._shared_client = None

    # ---------- 底层观测 ----------

    async def run_agent_task(self, task: Task) -> Outcome:
        """跑一条 agent 任务，抓取全部可观测信号。

        令牌过期（401）时自动续期并重试一次 —— 但**重试的时间不计入延迟**，
        因为续期是评测脚手架的开销，不是 agent 的性能表现。
        """
        out = await self._agent_chat_once(task)
        if out.error and "会话令牌" in out.error:
            logger.warning("令牌过期，续期后重试 %s", task.id)
            await self.login_and_issue_token()
            out = await self._agent_chat_once(task)

        # 权威回查：SSE 里的工具返回被截断（600 字符），商品多时 JSON 会断掉，
        # 判定器会误判成"没有结果"。这里拿 agent **实际用过的参数**重新查一次后端，
        # 既避免截断问题，又仍然验证的是"agent 参数用对没对"。
        await self._attach_authoritative_results(out)
        return out

    async def _attach_authoritative_results(self, out: Outcome) -> None:
        """对检索类任务回查后端，填充权威结果。"""
        search_calls = [c for c in out.tool_calls if c.name == "search_products"]
        if not search_calls:
            return
        args = search_calls[-1].args or {}
        params: dict[str, Any] = {"size": 50}
        # 工具入参 -> 后端查询参数
        for src, dst in (
            ("query", "q"),
            ("category", "category"),
            ("min_price", "minPrice"),
            ("max_price", "maxPrice"),
            ("size", "size"),
        ):
            if args.get(src) is not None:
                params[dst] = args[src]
        try:
            r = await self._client().get(
                f"{self.backend_url}/api/v1/products", params=params, headers=self._auth_headers()
            )
            body = r.json()
            if body.get("code") == 0:
                out.authoritative_items = (body.get("data") or {}).get("items") or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("权威回查失败 %s: %s", out.task_id, exc)

    async def _agent_chat_once(self, task: Task) -> Outcome:
        out = Outcome(task_id=task.id, condition="agent")
        conv = f"eval-{task.id}-{uuid.uuid4().hex[:6]}"

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=180, trust_env=False) as c:
                resp = await c.post(
                    f"{self.agent_url}/api/chat",
                    headers={"X-Actor-Token": self.actor_token},
                    json={"message": task.message, "conversationId": conv},
                )
                body = resp.json()
        except Exception as exc:  # noqa: BLE001
            out.error = f"{type(exc).__name__}: {exc}"
            out.latency_ms = int((time.perf_counter() - t0) * 1000)
            return out
        out.latency_ms = int((time.perf_counter() - t0) * 1000)

        out.reply = body.get("reply", "")
        for ev in body.get("events", []):
            et = ev.get("type")
            if et == "tool_start":
                out.tool_calls.append(ToolCall(name=ev.get("name", "?"), args=ev.get("args") or {}))
            elif et == "tool_end":
                # 回填到最近一次同名未完成调用
                for call in reversed(out.tool_calls):
                    if call.name == ev.get("name") and call.ok is None:
                        call.ok = bool(ev.get("ok"))
                        call.raw = (ev.get("preview") or "")[:800]
                        break
            elif et == "confirmation_required":
                out.confirmation = ev
            elif et == "done":
                out.steps = int(ev.get("steps") or 0)
            elif et == "error":
                out.error = ev.get("message")

        usage = body.get("usage") or {}
        out.tokens_in = int(usage.get("input") or 0)
        out.tokens_out = int(usage.get("output") or 0)
        return out

    # ---------- 写操作：确认 + 落库校验 + 清理 ----------

    async def _list_my_products(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
            r = await c.get(
                f"{self.backend_url}/api/v1/products/mine/list",
                headers=self._auth_headers(),
            )
            if r.status_code == 401:
                await self.refresh_actor_token(c)
                r = await c.get(
                    f"{self.backend_url}/api/v1/products/mine/list",
                    headers=self._auth_headers(),
                )
            return (r.json().get("data") or []) if r.status_code == 200 else []

    async def _delete_product(self, product_id: int) -> None:
        """清理评测产生的商品。

        走管理员接口（agent 没有删除权限 —— 这是刻意的权限边界）。
        """
        async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
            await c.post(
                f"{self.backend_url}/admin/doLogin",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            await c.get(
                f"{self.backend_url}/admin/product/{product_id}/delete", follow_redirects=False
            )

    # ---------- 认证 ----------

    def _auth_headers(self) -> dict[str, str]:
        return {
            "X-Actor-Token": self.actor_token,
            "X-Service-Token": self.service_token,
        }

    async def login_and_issue_token(self) -> str:
        """登录 Java 后端并换取 capability token。"""
        async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
            await c.post(
                f"{self.backend_url}/doLogin",
                data={"username": self.java_user, "password": self.java_password},
                follow_redirects=False,
            )
            tok = await self.refresh_actor_token(c)
            return tok

    async def refresh_actor_token(self, client: httpx.AsyncClient | None = None) -> str:
        """重新签发 capability token（长评测会超时，需要能续期）。"""

        async def _do(c: httpx.AsyncClient) -> str:
            r = await c.post(
                f"{self.backend_url}/api/v1/agent/session",
                headers={"X-Service-Token": self.service_token},
                json={"conversationId": "eval-refresh"},
            )
            self.actor_token = r.json()["data"]["actorToken"]
            return self.actor_token

        if client is not None:
            return await _do(client)
        async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
            return await _do(c)

    # ---------- 主流程 ----------

    async def check_snapshot(self, taskset: TaskSet) -> list[str]:
        """校验当前在售商品与任务集快照是否一致。

        为什么必须做：任务集的期望结果（比如"300~800 的运动器材有 2 件"）
        是**依赖具体库存**的。如果库里有上次测试残留的商品，
        或者某个商品被锁成已售出，评测结果就无法复现，也无法归因。

        返回不一致的描述列表（空列表表示一致）。
        """
        expected = {(p.get("name"), float(p.get("price") or 0)) for p in taskset.product_snapshot}
        # 在售商品（分页取全）
        items: list[dict[str, Any]] = []
        page = 0
        while True:
            r = await self._client().get(
                f"{self.backend_url}/api/v1/products",
                params={"size": 50, "page": page},
                headers=self._auth_headers(),
            )
            body = r.json()
            if body.get("code") != 0:
                return [f"查询在售商品失败: {body.get('message')}"]
            data = body.get("data") or {}
            chunk = data.get("items") or []
            items.extend(chunk)
            if len(items) >= int(data.get("totalElements") or 0) or not chunk:
                break
            page += 1

        actual = {(p.get("name"), float(p.get("price") or 0)) for p in items}

        problems: list[str] = []
        missing = expected - actual
        extra = actual - expected
        if missing:
            problems.append(
                f"快照中有 {len(missing)} 件商品当前不在售: {[n for n, _ in list(missing)[:5]]}"
            )
        if extra:
            problems.append(
                f"当前多出 {len(extra)} 件不在快照中的在售商品: {[n for n, _ in list(extra)[:5]]}"
            )
        return problems

    async def warmup(self) -> None:
        """预热。

        两个目的：
          1. 建立长连接（否则第一条任务的延迟包含 TCP/TLS 握手，约 1 秒）
          2. 让后端完成连接池与查询计划初始化

        不做预热的话，"第一条任务"的数字会显著偏高，
        而不同对照组的第一次调用又落在不同任务上 —— 直接污染结论。
        """
        logger.info("预热中…")
        # 后端搜索路径
        for _ in range(3):
            try:
                await self._client().get(
                    f"{self.backend_url}/api/v1/products",
                    params={"size": 1},
                    headers=self._auth_headers(),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("预热搜索失败: %s", exc)
        # agent 对话路径（含模型调用）
        try:
            async with httpx.AsyncClient(timeout=120, trust_env=False) as c:
                await c.post(
                    f"{self.agent_url}/api/chat",
                    headers={"X-Actor-Token": self.actor_token},
                    json={"message": "你好", "conversationId": "eval-warmup"},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("预热对话失败: %s", exc)
        logger.info("预热完成")

    async def evaluate(
        self,
        taskset: TaskSet,
        conditions: list[str],
        *,
        only: list[str] | None = None,
        with_writes: bool = True,
    ) -> dict[str, ConditionReport]:
        """跑完整评测。"""
        reports: dict[str, ConditionReport] = {c: ConditionReport(condition=c) for c in conditions}
        tasks = [t for t in taskset.tasks if not only or t.id in only]

        for condition in conditions:
            report = reports[condition]
            logger.info("=== 开始对照组: %s（%d 条任务）===", condition, len(tasks))
            for _i, task in enumerate(tasks, 1):
                # capability token 会过期，但**不能每次循环都续期**：
                # 登录 + 换令牌是纯额外开销，会污染基线延迟 ——
                # 真实用户在浏览器里已带 session，点一下搜索就走。
                # 因此只在真正遇到 401 时才续期（见 _need_refresh）。
                if self._need_refresh:
                    await self.login_and_issue_token()
                    self._need_refresh = False

                if condition == "agent":
                    if task.category == "write" and with_writes:
                        conv = f"eval-{task.id}-{uuid.uuid4().hex[:6]}"
                        self._last_conv = conv
                        out = await self._run_write(task, conv)
                    else:
                        out = await self.run_agent_task(task)
                else:
                    out = await self.run_baseline_task(task, condition)

                verdict = judge(task, out)
                cost = (out.tokens_in / 1e6) * self.price_in + (
                    out.tokens_out / 1e6
                ) * self.price_out
                tr = TaskResult(
                    task_id=task.id,
                    category=task.category,
                    message=task.message,
                    condition=condition,
                    success=verdict.success,
                    reason=verdict.reason,
                    latency_ms=out.latency_ms,
                    tokens_in=out.tokens_in,
                    tokens_out=out.tokens_out,
                    cost_cny=round(cost, 6),
                    tool_names=out.tool_names,
                    had_confirmation=out.confirmation is not None,
                    write_verified=out.write_verified,
                    error=out.error,
                    reply_excerpt=out.reply[:200],
                )
                report.results.append(tr)
                _accumulate(report, tr)

                mark = "✓" if verdict.success else "✗"
                logger.info(
                    "%s %s %-4s %-9s %5dms  %s",
                    mark,
                    condition,
                    task.id,
                    task.category,
                    tr.latency_ms,
                    verdict.reason[:70],
                )

        _finalize(reports)
        return reports

    async def run_baseline_task(self, task: Task, condition: str) -> Outcome:
        """对照组（关键词搜索框）。

        两档条件：
          - baseline_naive：用户原话直接当关键词（对基线不公平，仅作参考）
          - baseline_ideal：人工拆解出的理想关键词 + 筛选（**结论以它为准**）

        ⚠️ 性能口径很关键：这里**复用长连接客户端**。
        基线在浏览器里是"已打开页面点一下搜索"，复用 TCP 连接；
        如果每条任务都新建 httpx 客户端，会把连接建立开销算进基线延迟，
        把基线人为做慢 100 倍以上 —— 那样得出的"agent 更快"是假的。
        """
        if condition == "baseline_naive":
            keyword, category, max_price = task.message, None, None
        elif condition == "baseline_ideal":
            keyword = task.ideal_keyword or None
            category = task.ideal_category
            max_price = task.ideal_max_price
        else:
            raise ValueError(f"未知对照组: {condition}")

        params: dict[str, Any] = {"size": 50}
        if keyword:
            params["q"] = keyword
        if category:
            params["category"] = category
        if max_price is not None:
            params["maxPrice"] = max_price

        out = Outcome(task_id=task.id, condition=condition)
        t0 = time.perf_counter()
        try:
            r = await self._client().get(
                f"{self.backend_url}/api/v1/products", params=params, headers=self._auth_headers()
            )
            body = r.json()
            if body.get("code") != 0:
                out.error = body.get("message", "搜索失败")
            else:
                data = body.get("data") or {}
                items = data.get("items") or []
                # 搜索框没有"工具调用"概念，但为了让判定器复用同一套规则，
                # 把它记成一次 search_products 调用。
                out.tool_calls.append(
                    ToolCall(name="search_products", args=params, ok=True, payload=data)
                )
                names = [str(i.get("name") or "") for i in items]
                out.reply = (
                    f"找到 {len(items)} 件：{'、'.join(names)}" if items else "没有找到相关商品"
                )
        except Exception as exc:  # noqa: BLE001
            out.error = f"{type(exc).__name__}: {exc}"
        out.latency_ms = int((time.perf_counter() - t0) * 1000)
        # 搜索框不调模型 -> token 与成本恒为 0
        out.tokens_in = 0
        out.tokens_out = 0
        out.steps = 1
        return out

    async def run_baseline(self, task: Task, condition: str) -> Outcome:
        """兼容别名。"""
        return await self.run_baseline_task(task, condition)

    async def _run_write(self, task: Task, conv: str) -> Outcome:
        """写操作：先拿确认，再自动确认，再校验落库，最后清理。"""
        out = Outcome(task_id=task.id, condition="agent")
        before = await self._list_my_products()
        before_ids = {p["id"] for p in before}

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=180, trust_env=False) as c:
                r1 = await c.post(
                    f"{self.agent_url}/api/chat",
                    headers={"X-Actor-Token": self.actor_token},
                    json={"message": task.message, "conversationId": conv},
                )
                body1 = r1.json()
                out.reply = body1.get("reply", "")
                for ev in body1.get("events", []):
                    et = ev.get("type")
                    if et == "tool_start":
                        out.tool_calls.append(
                            ToolCall(name=ev.get("name", "?"), args=ev.get("args") or {})
                        )
                    elif et == "tool_end":
                        for call in reversed(out.tool_calls):
                            if call.name == ev.get("name") and call.ok is None:
                                call.ok = bool(ev.get("ok"))
                                call.raw = ev.get("preview")
                                break
                    elif et == "confirmation_required":
                        out.confirmation = ev
                    elif et == "done":
                        out.steps = int(ev.get("steps") or 0)
                usage = body1.get("usage") or {}
                out.tokens_in += int(usage.get("input") or 0)
                out.tokens_out += int(usage.get("output") or 0)

                if out.confirmation is not None:
                    r2 = await c.post(
                        f"{self.agent_url}/api/chat/resume-sync",
                        headers={"X-Actor-Token": self.actor_token},
                        json={
                            "conversationId": conv,
                            "approved": True,
                            "action": out.confirmation.get("action"),
                        },
                    )
                    body2 = r2.json()
                    out.reply += "\n" + body2.get("reply", "")
                    usage2 = body2.get("usage") or {}
                    out.tokens_in += int(usage2.get("input") or 0)
                    out.tokens_out += int(usage2.get("output") or 0)
        except Exception as exc:  # noqa: BLE001
            out.error = f"{type(exc).__name__}: {exc}"
        out.latency_ms = int((time.perf_counter() - t0) * 1000)

        await self._attach_authoritative_results(out)

        # 落库校验
        if out.confirmation is not None and not out.error:
            action = out.confirmation.get("action")
            after = await self._list_my_products()
            new_items = [p for p in after if p["id"] not in before_ids]
            if action == "publish_product":
                if len(new_items) == 1 and new_items[0].get("status") == "PENDING_APPROVAL":
                    out.write_verified = True
                    out.write_detail = f"新建 id={new_items[0]['id']} 状态=待审核（非直接上架）"
                else:
                    out.write_verified = False
                    out.write_detail = f"期望新建 1 件待审核商品，实际 {len(new_items)} 件"
            else:
                out.write_verified = True
                out.write_detail = f"{action} 已执行，无预期外副作用"

            # 清理产生的商品，避免污染后续任务
            for p in new_items:
                await self._delete_product(p["id"])

        return out


def _accumulate(report: ConditionReport, tr: TaskResult) -> None:
    report.total += 1
    if tr.success:
        report.passed += 1
    cat = report.by_category.setdefault(tr.category, {"total": 0, "passed": 0})
    cat["total"] += 1
    if tr.success:
        cat["passed"] += 1
    if tr.category == "boundary":
        report.safety_total += 1
        if tr.success:
            report.safety_pass += 1
    report.tokens_in_total += tr.tokens_in
    report.tokens_out_total += tr.tokens_out
    report.cost_cny_total += tr.cost_cny


def _finalize(reports: dict[str, ConditionReport]) -> None:
    for report in reports.values():
        lats = sorted(r.latency_ms for r in report.results)
        if lats:
            report.latency_ms_avg = sum(lats) / len(lats)
            report.latency_ms_p50 = lats[len(lats) // 2]
            report.latency_ms_max = lats[-1]
