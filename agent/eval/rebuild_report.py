"""从已保存的 report.json 重新渲染报告（不重跑评测）。

用途：调整报告格式、补充任务集自身缺陷说明时，不需要再花几块钱和几分钟重跑。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from eval.evaluator import ConditionReport, TaskResult
from eval.report import render_markdown
from eval.schema import load_taskset


def rebuild(report_json: str | Path, out: str | Path, tasks_path: str | Path) -> None:
    raw = json.loads(Path(report_json).read_text(encoding="utf-8"))
    reports: dict[str, ConditionReport] = {}
    for cond, d in raw.items():
        r = ConditionReport(condition=cond)
        r.total = d["total"]
        r.passed = d["passed"]
        r.by_category = d["byCategory"]
        r.latency_ms_avg = d["latencyMsAvg"]
        r.latency_ms_p50 = d["latencyMsP50"]
        r.latency_ms_max = d["latencyMsMax"]
        r.tokens_in_total = d["tokensIn"]
        r.tokens_out_total = d["tokensOut"]
        r.cost_cny_total = d["costCny"]
        r.safety_pass = d["safety"]["pass"]
        r.safety_total = d["safety"]["total"]
        r.results = [TaskResult(**x) for x in d["results"]]
        reports[cond] = r

    ts = load_taskset(tasks_path)
    md = render_markdown(
        reports,
        task_count=len(ts.tasks),
        model="deepseek-chat",
        known_issues=ts.known_issues,
    )
    Path(out).write_text(md, encoding="utf-8")
    print(f"已重渲染: {out}")


if __name__ == "__main__":
    d = ROOT / "eval" / "results"
    rebuild(d / "report.json", d / "report.md", ROOT / "eval" / "gold_tasks.json")
