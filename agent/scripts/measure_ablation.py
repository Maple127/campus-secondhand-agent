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
    # ---- 后 18 轮：拉长上下文，逼压缩触发 ----
    "对了，学校附近有没有卖台灯的店？",
    "网购的二手台灯一般能用多久？",
    "如果灯坏了能修吗？",
    "你之前说有几件台灯来着？",
    "最便宜的那件成色怎么样？",
    "宿舍能用大功率的台灯吗？",
    "我室友也想买一个，有推荐吗？",
    "他预算大概 80，有合适的吗？",
    "台灯一般多重？好搬吗？",
    "南门那边能自提吗？",
    "如果我不买了，会有什么影响吗？",
    "算了，还是先看看。",
    "那台 ¥45 的护眼台灯具体什么参数？",
    "它和 ¥38 那件差在哪？",
    "¥38 那件灯罩发黄是不是影响使用？",
    "你觉得我该买哪件？",
    "如果两件我都想要呢？",
    "最后再帮我确认一遍：我到底要买什么、预算多少、什么东西我说过不要。",
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


async def scenario_fault() -> dict:
    """故障注入：后端不可达时，agent 会怎么表现。

    跑之前要把 agent 的 BACKEND_BASE_URL 指向一个没人监听的端口，
    这样"请求必然失败"，可以观察重试与降级。
    """
    conv = f"abl-fault-{uuid.uuid4().hex[:6]}"
    async with httpx.AsyncClient(trust_env=False) as c:
        # ---------- 场景 A：只读工具失败 ----------
        # 注意：此时后端真的不可达，拿不到 actor token，
        # 所以直接构造一个假 token —— 反正请求会在传输层就失败。
        t0 = time.perf_counter()
        r = await c.post(
            f"{AGENT}/api/chat",
            headers={"X-Actor-Token": "fault-injection-token"},
            json={"message": "有什么 200 以内的耳机？", "conversationId": conv},
            timeout=180.0,
        )
        elapsed = int((time.perf_counter() - t0) * 1000)
        d = r.json() if r.status_code < 500 else {"reply": "", "error": str(r.status_code)}
        m = (await c.get(f"{AGENT}/api/metrics")).json()["counters"]

    reply = (d.get("reply") or "") if isinstance(d, dict) else ""
    return {
        "scenario": "fault",
        "http_status": r.status_code,
        "latency_ms": elapsed,
        "retries": m.get("retries", 0),
        "retry_exhausted": m.get("retry_exhausted", 0),
        # 关键判据：有没有给用户一句人话，而不是把异常抛出去
        "graceful": any(k in reply for k in ("暂时不可用", "稍后", "连接", "无法")),
        "reply": reply[:400],
    }


# ------------------------------------------------------------- 场景：lookup

#: 快路径与 agent 都能答的典型检索请求
LOOKUP_QUERIES = [
    "有没有耳机",
    "100 以内有什么耳机",
    "帮我看看台灯",
    "有卖键盘的吗",
    "300 以下的显示器",
    "自行车多少钱",
]


async def scenario_lookup() -> dict:
    """简单检索：快路径 vs agent 的延迟与 token 对比。"""
    rows: list[dict] = []
    async with httpx.AsyncClient(trust_env=False) as c:
        conv = f"abl-lookup-{uuid.uuid4().hex[:6]}"
        token = await issue_token(c, conv)
        for i, q in enumerate(LOOKUP_QUERIES, 1):
            d = await chat(c, token, q, f"{conv}-{i}")
            usage = d.get("usage") or {}
            rows.append(
                {
                    "query": q,
                    "strategy": d.get("strategy"),
                    "latency_ms": d["_latency_ms"],
                    "tokens_in": int(usage.get("input") or 0),
                    "tokens_out": int(usage.get("output") or 0),
                    "ok": bool(d.get("reply")),
                }
            )
            print(
                f"  {q:<18} {rows[-1]['strategy']:<6} "
                f"{rows[-1]['latency_ms']:>5}ms  in={rows[-1]['tokens_in']:>5}"
            )

    n = len(rows) or 1
    return {
        "scenario": "lookup",
        "runs": rows,
        "avg_latency_ms": round(sum(r["latency_ms"] for r in rows) / n, 1),
        "avg_tokens_in": round(sum(r["tokens_in"] for r in rows) / n, 1),
        "all_answered": all(r["ok"] for r in rows),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=["gate", "compress", "fault", "lookup"], required=True)
    ap.add_argument("--turns", type=int, default=12)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if args.scenario == "gate":
        result = await scenario_gate()
    elif args.scenario == "fault":
        result = await scenario_fault()
    elif args.scenario == "lookup":
        result = await scenario_lookup()
    else:
        result = await scenario_compress(args.turns)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    asyncio.run(main())
