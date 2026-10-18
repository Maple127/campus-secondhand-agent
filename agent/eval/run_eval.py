"""Agent 价值评测 CLI。

用法：
    # 全量评测（agent + 两档基线）
    python -m eval.run_eval

    # 只跑 agent
    python -m eval.run_eval --conditions agent

    # 只跑若干任务（调试用）
    python -m eval.run_eval --only L01,C01,W01

    # 不执行写操作（快速跑只读部分）
    python -m eval.run_eval --no-writes

前置条件：Java 后端(8081) 与 agent 服务(8090) 均已启动。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
from pathlib import Path

# 允许以 `python eval/run_eval.py` 或 `python -m eval.run_eval` 两种方式运行
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Windows 控制台默认 GBK，打印 emoji/中文会崩；重配失败也无所谓
for _s in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from eval.evaluator import Evaluator
from eval.report import write_outputs
from eval.schema import load_taskset, summarize

DEFAULT_TASKS = Path(__file__).parent / "gold_tasks.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Agent 价值评测")
    p.add_argument("--tasks", default=str(DEFAULT_TASKS), help="任务集 JSON 路径")
    p.add_argument(
        "--conditions",
        default="agent,baseline_ideal,baseline_naive",
        help="要跑的对照组，逗号分隔",
    )
    p.add_argument("--only", default="", help="只跑指定任务 id，逗号分隔")
    p.add_argument("--no-writes", action="store_true", help="跳过写操作落库校验")
    p.add_argument("--agent-url", default="http://127.0.0.1:8090")
    p.add_argument("--backend-url", default="http://localhost:8081")
    p.add_argument("--service-token", default="demo-agent-token-local")
    p.add_argument("--user", default="user01")
    p.add_argument("--password", default="pass123")
    p.add_argument("--model", default="deepseek-chat")
    p.add_argument("--price-in", type=float, default=2.0, help="输入 token 单价(元/百万)")
    p.add_argument("--price-out", type=float, default=8.0, help="输出 token 单价(元/百万)")
    p.add_argument("--outdir", default=str(ROOT / "eval" / "results"))
    p.add_argument("--force", action="store_true", help="库存与快照不一致时仍继续评测")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args()


async def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    taskset = load_taskset(args.tasks)
    print("=" * 62)
    print(summarize(taskset))
    print("=" * 62)

    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    only = [t.strip() for t in args.only.split(",") if t.strip()] or None

    ev = Evaluator(
        agent_url=args.agent_url,
        backend_url=args.backend_url,
        service_token=args.service_token,
        actor_token="",
        java_user=args.user,
        java_password=args.password,
        price_in=args.price_in,
        price_out=args.price_out,
    )
    # 先登录换令牌
    await ev.login_and_issue_token()

    # 检查服务可用性，避免跑一半才发现没启动
    import httpx

    async with httpx.AsyncClient(timeout=15, trust_env=False) as c:
        try:
            h = (await c.get(f"{args.agent_url}/health")).json()
        except Exception as exc:  # noqa: BLE001
            print(f"[FATAL] agent 服务不可用: {exc}")
            print("        请先运行: powershell -File agent/scripts/run-agent.ps1")
            return 2
        if not h.get("backend", {}).get("ok"):
            print(f"[FATAL] agent 无法连到后端: {h.get('backend')}")
            return 2
        print(f"服务就绪: model={h.get('model')} backend={h.get('backend', {}).get('url')}")

    # 预热：建立长连接 + 后端连接池初始化。
    # 不预热的话第一条任务的延迟会包含握手开销，而各对照组的"第一次调用"
    # 落在不同任务上，直接污染对比结论。
    await ev.warmup()

    # 校验库存基线与任务集快照一致。
    # 期望结果是依赖具体库存的，若库里有上次测试残留（或商品被锁成已售出），
    # 评测就不可复现、也无法归因。不一致时明确告警而不是默默跑出一个脏结果。
    problems = await ev.check_snapshot(taskset)
    if problems:
        print()
        print("!" * 62)
        print("警告：当前库存与任务集快照不一致，评测结果不可复现")
        for p in problems:
            print(f"  - {p}")
        print("建议：先执行 python -m eval.cleanup，或重建任务集快照")
        print("!" * 62)
        print()
        if not args.force:
            print("已中止。确认要继续请加 --force")
            await ev.aclose()
            return 3

    reports = await ev.evaluate(taskset, conditions, only=only, with_writes=not args.no_writes)
    await ev.aclose()

    md_path, json_path = write_outputs(
        reports, args.outdir, task_count=len(only or taskset.tasks), model=args.model
    )

    print()
    print("=" * 62)
    for cond, r in reports.items():
        print(
            f"{cond:<17} 成功率 {r.success_rate:>5.0%} "
            f"({r.passed}/{r.total})  平均 {r.latency_ms_avg:>7.0f}ms  "
            f"¥{r.cost_cny_total:.4f}"
        )
    print("=" * 62)
    print(f"报告: {md_path}")
    print(f"原始: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
