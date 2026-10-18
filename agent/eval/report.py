"""评测报告输出。

产出两个东西：
  1. 控制台/markdown 表格 —— 给人看的结论
  2. JSON 原始结果 —— 给机器复核，保证结论可追溯

报告的核心是**按任务分类拆开看**，而不是只报一个总成功率。
因为"agent 总成功率 70%"这种数字没有信息量：
它在 lookup 上可能远输搜索框，在 compound 上可能完胜，混在一起就看不出来了。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from eval.evaluator import ConditionReport

CATEGORY_LABEL = {
    "lookup": "找东西",
    "filter": "条件筛选",
    "compound": "多步任务",
    "write": "写操作",
    "boundary": "安全边界",
}

#: 结论以"理想关键词"基线为准（对搜索框最有利的条件）
PRIMARY_BASELINE = "baseline_ideal"


def _category_stats(report: ConditionReport | None) -> dict[str, dict[str, int]]:
    """按分类统计通过数。

    **必须从逐条结果现算，不能直接读 report.by_category。**
    原因：by_category 是评测过程中增量累加的，如果中途有任务被跳过或
    结果被重新加载（例如从 JSON 重建报告），它会与 results 不一致 ——
    我确实踩过这个坑：报告里 filter 显示 57%，而逐条数据算出来是 100%。
    报告的内部不一致比数字不好看更严重，因为它会让读者不再信任所有数字。
    """
    out: dict[str, dict[str, int]] = {}
    if report is None:
        return out
    for r in report.results:
        c = out.setdefault(r.category, {"total": 0, "passed": 0})
        c["total"] += 1
        if r.success:
            c["passed"] += 1
    return out


def render_markdown(
    reports: dict[str, ConditionReport],
    *,
    task_count: int,
    model: str,
    known_issues: list[str] | None = None,
    price_note: str = "DeepSeek 定价（输入 ¥2 / 输出 ¥8 每百万 token）",
) -> str:
    agent = reports.get("agent")
    base_ideal = reports.get(PRIMARY_BASELINE)
    base_naive = reports.get("baseline_naive")

    L: list[str] = []
    L.append("# Agent 价值评测报告")
    L.append("")
    L.append(f"- 任务数：**{task_count}**")
    L.append(f"- 被测模型：`{model}`")
    L.append(f"- 成本口径：{price_note}")
    L.append(f"- 主对照：**{PRIMARY_BASELINE}**（人工拆解的理想关键词，对搜索框最有利）")
    L.append("")
    L.append("> 判定全部由程序化规则完成，未使用 LLM 自评。")
    L.append("")

    # ---------- 总览 ----------
    L.append("## 一、总览")
    L.append("")
    L.append("| 指标 | 关键词搜索框（理想） | AI 助手 |")
    L.append("|---|---|---|")
    if base_ideal and agent:
        L.append(
            f"| 任务成功率 | {base_ideal.success_rate:.0%} "
            f"({base_ideal.passed}/{base_ideal.total}) | "
            f"**{agent.success_rate:.0%}** ({agent.passed}/{agent.total}) |"
        )
        L.append(
            f"| 平均耗时 | {base_ideal.latency_ms_avg:.0f} ms | "
            f"**{agent.latency_ms_avg:.0f} ms**（{_ratio(agent.latency_ms_avg, base_ideal.latency_ms_avg)}） |"
        )
        L.append(
            f"| P50 耗时 | {base_ideal.latency_ms_p50:.0f} ms | {agent.latency_ms_p50:.0f} ms |"
        )
        L.append(f"| 最大耗时 | {base_ideal.latency_ms_max} ms | {agent.latency_ms_max} ms |")
        L.append(
            f"| 总 token | 0 | {agent.tokens_in_total:,} in / {agent.tokens_out_total:,} out |"
        )
        L.append(f"| 总成本 | ¥0 | **¥{agent.cost_cny_total:.4f}** |")
        L.append(f"| 单次成本 | ¥0 | ¥{agent.cost_per_task:.6f} |")
        L.append(f"| 安全边界通过 | — | {agent.safety_pass}/{agent.safety_total} |")
    L.append("")

    # ---------- 分类对比 ----------
    L.append("## 二、分类对比（关键）")
    L.append("")
    L.append("总成功率会把强弱项抵消掉，必须拆开看。")
    L.append("")
    L.append("| 任务类型 | 条数 | 搜索框（理想） | AI 助手 | 差值 | 谁更合适 |")
    L.append("|---|---|---|---|---|---|")
    order = ["lookup", "filter", "compound", "write", "boundary"]
    bi_cats = _category_stats(base_ideal)
    ag_cats = _category_stats(agent)
    cats = [c for c in order if c in bi_cats or c in ag_cats]
    for cat in cats:
        bi = bi_cats.get(cat)
        ag = ag_cats.get(cat)
        n = (ag or bi or {}).get("total", 0)
        bi_rate = (bi["passed"] / bi["total"]) if bi and bi["total"] else 0.0
        ag_rate = (ag["passed"] / ag["total"]) if ag and ag["total"] else 0.0
        diff = ag_rate - bi_rate
        if diff > 0.001:
            win = "**AI 助手**"
        elif diff < -0.001:
            win = "搜索框"
        else:
            win = "打平"
        L.append(
            f"| {CATEGORY_LABEL.get(cat, cat)} | {n} | "
            f"{bi_rate:.0%} | {ag_rate:.0%} | "
            f"{diff:+.0%} | {win} |"
        )
    if base_naive:
        L.append("")
        L.append(
            f"> 另附 `baseline_naive`（用户原话直接当关键词）总成功率："
            f"{base_naive.success_rate:.0%} —— 这一档对基线不公平，仅作参考，"
            f"结论以上表为准。"
        )
    L.append("")

    # ---------- 逐条明细 ----------
    L.append("## 三、逐条结果")
    L.append("")
    if agent:
        L.append("| 任务 | 类型 | 输入 | 搜索框 | AI 助手 | 用时 | 成本 | 判定说明 |")
        L.append("|---|---|---|---|---|---|---|---|")
        base_by_id = {r.task_id: r for r in (base_ideal.results if base_ideal else [])}
        for r in agent.results:
            b = base_by_id.get(r.task_id)
            bmark = _mark(b.success) if b else "—"
            L.append(
                f"| {r.task_id} | {CATEGORY_LABEL.get(r.category, r.category)} | "
                f"{_short(r.message)} | {bmark} | {_mark(r.success)} | "
                f"{r.latency_ms} ms | ¥{r.cost_cny:.5f} | {_short(r.reason, 46)} |"
            )
    L.append("")

    # ---------- 结论 ----------
    L.append("## 四、结论")
    L.append("")
    L.extend(_conclusions(agent, base_ideal))
    L.append("")

    # ---------- 任务集自身缺陷（诚实披露） ----------
    if known_issues:
        L.append("## 五、任务集自身的已知缺陷")
        L.append("")
        L.append(
            "下列失败**不是 agent 的问题**，而是评测设计的问题。"
            "保留原样不调参，是为了避免把评测变成「调到好看为止」。"
        )
        L.append("")
        for line in known_issues:
            if line.startswith("_"):
                continue
            if line.startswith("    "):
                L.append(f"  {line.strip()}")
            else:
                L.append(f"- {line}")
        L.append("")
    return "\n".join(L)


def _conclusions(agent, base_ideal) -> list[str]:
    """根据数据自动生成结论，而不是写死一段话。"""
    if not agent or not base_ideal:
        return ["数据不足，无法得出结论。"]

    out: list[str] = []
    # 同样从逐条结果现算，避免与明细表不一致
    ag = _category_stats(agent)
    bi = _category_stats(base_ideal)

    def rate(d: dict, cat: str) -> float | None:
        v = d.get(cat)
        return (v["passed"] / v["total"]) if v and v["total"] else None

    lookup_a, lookup_b = rate(ag, "lookup"), rate(bi, "lookup")
    comp_a, comp_b = rate(ag, "compound"), rate(bi, "compound")
    write_a = rate(ag, "write")

    if lookup_a is not None and lookup_b is not None:
        if lookup_a < lookup_b:
            out.append(
                f"- **找东西场景：搜索框更好**（成功率 {lookup_b:.0%} vs {lookup_a:.0%}），"
                f"且 agent 平均多花 {agent.latency_ms_avg / max(base_ideal.latency_ms_avg, 1):.0f}× 时间、"
                f"每次 ¥{agent.cost_per_task:.5f}。这是 agent 的负收益区间，"
                f"**不应该用它做纯检索**。"
            )
        else:
            out.append(f"- 找东西场景 agent 未落后（{lookup_a:.0%} vs {lookup_b:.0%}）。")

    if comp_a is not None and comp_b is not None:
        if comp_a > comp_b:
            out.append(
                f"- **多步任务：搜索框做不到**（{comp_b:.0%} vs agent {comp_a:.0%}）。"
                f"这是 agent 唯一不可替代的价值区间。"
            )
        else:
            out.append(f"- 多步任务上 agent 未体现优势（{comp_a:.0%} vs {comp_b:.0%}），需要排查。")

    if write_a is not None:
        out.append(f"- 写操作成功率 {write_a:.0%}（搜索框无此能力），且全部经过人工确认。")

    if agent.safety_total:
        out.append(f"- 安全边界 {agent.safety_pass}/{agent.safety_total} 通过。")

    # 综合判断
    (bi.get("lookup") or {}).get("total", 0)
    comp_n = sum((bi.get(c) or {}).get("total", 0) for c in ("compound", "write"))
    total = agent.total or 1
    hard_share = comp_n / total
    out.append("")
    out.append(
        f"- **结构性判断**：无法被搜索框替代的任务占比约 **{hard_share:.0%}**"
        f"（多步 + 写操作 {comp_n} 条 / 共 {total} 条）。"
    )
    if hard_share < 0.3:
        out.append(
            "  - 低于 30% 意味着：如果真实用户需求分布与这里接近，"
            "agent 主要是在为少数场景支付普遍性的延迟与成本。"
        )
    else:
        out.append(
            "  - 超过 30% 意味着：agent 覆盖了足够比例的「搜索框做不到」的需求，价值站得住。"
        )
    return out


def _mark(ok: bool | None) -> str:
    if ok is None:
        return "—"
    return "✅" if ok else "❌"


def _short(text: str, limit: int = 30) -> str:
    t = (text or "").replace("\n", " ").replace("|", "\\|")
    return t if len(t) <= limit else t[:limit] + "…"


def _ratio(a: float, b: float) -> str:
    if b <= 0:
        return "n/a"
    return f"{a / b:.1f}×"


def write_outputs(
    reports: dict[str, ConditionReport],
    outdir: str | Path,
    *,
    task_count: int,
    model: str,
) -> tuple[Path, Path]:
    """写出 markdown 报告与 JSON 原始结果。"""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    md = render_markdown(reports, task_count=task_count, model=model)
    md_path = outdir / "report.md"
    md_path.write_text(md, encoding="utf-8")

    raw = {
        cond: {
            "condition": r.condition,
            "total": r.total,
            "passed": r.passed,
            "successRate": round(r.success_rate, 4),
            "byCategory": r.by_category,
            "latencyMsAvg": round(r.latency_ms_avg, 1),
            "latencyMsP50": round(r.latency_ms_p50, 1),
            "latencyMsMax": r.latency_ms_max,
            "tokensIn": r.tokens_in_total,
            "tokensOut": r.tokens_out_total,
            "costCny": round(r.cost_cny_total, 6),
            "safety": {"pass": r.safety_pass, "total": r.safety_total},
            "results": [asdict(x) for x in r.results],
        }
        for cond, r in reports.items()
    }
    json_path = outdir / "report.json"
    json_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, json_path
