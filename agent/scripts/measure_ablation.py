"""消融评测的测量器（agent 侧）。

两个场景：

  gate      —— 空结果重试闸门值多少
  compress  —— 上下文压缩值多少（token 增长 + 约束保留）

用法：
    python scripts/measure_ablation.py --scenario gate
    python scripts/measure_ablation.py --scenario compress --turns 12

前置：后端 (8081) 与 agent (8090) 都在运行。
开关由**服务启动时的环境变量**控制，所以脚本本身只负责测量，
两次测量之间需要重启服务（见 infra/ablation-agent.ps1）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import contextlib

for _s in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

import httpx

BACKEND = "http://localhost:8081"
AGENT = "http://127.0.0.1:8090"
SERVICE_TOKEN = "demo-agent-token-local"


async def issue_token(c: httpx.AsyncClient, conv: str) -> str:
    await c.post(f"{BACKEND}/doLogin", data={"username": "user01", "password": "pass123"})
    r = await c.post(
        f"{BACKEND}/api/v1/agent/session",
        headers={"X-Service-Token": SERVICE_TOKEN},
        json={"conversationId": conv},
    )
    return r.json()["data"]["actorToken"]


async def chat(c: httpx.AsyncClient, token: str, message: str, conv: str) -> dict:
    t0 = time.perf_counter()
    r = await c.post(
        f"{AGENT}/api/chat",
        headers={"X-Actor-Token": token},
        json={"message": message, "conversationId": conv},
        timeout=180.0,
    )
    elapsed = int((time.perf_counter() - t0) * 1000)
    d = r.json()
    d["_latency_ms"] = elapsed
    return d


# ---------------------------------------------------------------- 场景：闸门


async def scenario_gate() -> dict:
    """一件平台上没有的东西，看模型会试几次。

    闸门开：第 3 次搜索被工具层直接拦下（不发请求给后端）。
    闸门关：模型可以一直换同义词试下去。
    """
    conv = f"abl-gate-{uuid.uuid4().hex[:6]}"
    async with httpx.AsyncClient(trust_env=False) as c:
        token = await issue_token(c, conv)
        # reset 计数器，确保只统计这一次
        with contextlib.suppress(Exception):
            await c.post(f"{AGENT}/api/metrics/reset")
        d = await chat(c, token, "平台上有二手投影仪卖吗？", conv)
        usage = d.get("usage") or {}
        m = (await c.get(f"{AGENT}/api/metrics")).json()["counters"]

    return {
        "scenario": "gate",
        "tool_calls": d.get("toolCalls") or [],
        "tool_call_count": len(d.get("toolCalls") or []),
        "tokens_in": int(usage.get("input") or 0),
        "tokens_out": int(usage.get("output") or 0),
        "latency_ms": d["_latency_ms"],
        "empty_search_blocks": m.get("empty_search_blocks", 0),
        "reply": (d.get("reply") or "")[:400],
    }


# ------------------------------------------------------------- 场景：压缩

#: 带有"必须被记住"的约束，后面要回头考它
CONSTRAINT_TURNS = [
    "我想买个能放宿舍的台灯，预算不超过 120，最好是能调光的。",
    "顺便看看有没有二手的收纳箱。",
    "收纳箱大概什么价位？",
    "台灯是不是有几件？分别多少钱？",
    "如果台灯超过 120 我就不要了，你帮我记着。",
    "再说说耳机，100 以内的有线耳机有吗？",
    "耳机先不买，我只是看看。",
    "回到台灯，你推荐哪个？",
    "台灯的颜色有什么选择吗？",
    "如果我今天下午去买，大概几点方便？",
    "再确认一下我的需求吧。",
    "好，那就这样。",
]

PROBE = "从头到尾回顾一下：我要买什么、预算是多少、我说过哪些东西不要？"


async def scenario_compress(turns: int) -> dict:
    """长对话：看 token 增长曲线，最后考一次"约束还记得吗"。"""
    conv = f"abl-comp-{uuid.uuid4().hex[:6]}"
    rows: list[dict] = []
    async with httpx.AsyncClient(trust_env=False) as c:
        token = await issue_token(c, conv)
        with contextlib.suppress(Exception):
            await c.post(f"{AGENT}/api/metrics/reset")

        for i, msg in enumerate(CONSTRAINT_TURNS[:turns], 1):
            d = await chat(c, token, msg, conv)
            usage = d.get("usage") or {}
            rows.append(
                {
                    "turn": i,
                    "tokens_in": int(usage.get("input") or 0),
                    "tokens_out": int(usage.get("output") or 0),
                    "latency_ms": d["_latency_ms"],
                }
            )
            print(f"  第 {i:2d} 轮  in={rows[-1]['tokens_in']:5d}  {rows[-1]['latency_ms']}ms")

        probe = await chat(c, token, PROBE, conv)
        m = (await c.get(f"{AGENT}/api/metrics")).json()["counters"]

    total_in = sum(r["tokens_in"] for r in rows)
    return {
        "scenario": "compress",
        "turns": len(rows),
        "tokens_in_total": total_in,
        "tokens_in_last3": sum(r["tokens_in"] for r in rows[-3:]),
        "compactions": m.get("compactions", 0),
        "tokens_saved_by_compaction": m.get("tokens_saved_by_compaction", 0),
        "rows": rows,
        "probe_reply": (probe.get("reply") or "")[:600],
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=["gate", "compress"], required=True)
    ap.add_argument("--turns", type=int, default=12)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if args.scenario == "gate":
        result = await scenario_gate()
    else:
        result = await scenario_compress(args.turns)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    asyncio.run(main())
