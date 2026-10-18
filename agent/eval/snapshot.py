"""重建任务集的库存快照。

为什么需要：任务集的期望结果（例如"300~800 的运动器材有几件"）
是**依赖具体库存**的。库存一变，评测就不可复现。

用法：
    python -m eval.snapshot            # 打印当前快照
    python -m eval.snapshot --write    # 写回 gold_tasks.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

JAVA = "http://localhost:8081"
SERVICE = "demo-agent-token-local"
TASKS = ROOT / "eval" / "gold_tasks.json"


async def fetch_on_sale() -> list[dict]:
    async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
        await c.post(
            f"{JAVA}/doLogin",
            data={"username": "user01", "password": "pass123"},
            follow_redirects=False,
        )
        r = await c.post(
            f"{JAVA}/api/v1/agent/session",
            headers={"X-Service-Token": SERVICE},
            json={"conversationId": "snapshot"},
        )
        actor = r.json()["data"]["actorToken"]
        h = {"X-Actor-Token": actor, "X-Service-Token": SERVICE}

        items: list[dict] = []
        page = 0
        while True:
            r = await c.get(f"{JAVA}/api/v1/products", params={"size": 50, "page": page}, headers=h)
            data = r.json()["data"]
            chunk = data.get("items") or []
            items.extend(chunk)
            if not chunk or len(items) >= int(data.get("totalElements") or 0):
                break
            page += 1
    return sorted(items, key=lambda p: p["id"])


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="写回 gold_tasks.json")
    args = ap.parse_args()

    items = await fetch_on_sale()
    snapshot = [
        {"id": p["id"], "name": p["name"], "price": p["price"], "category": p["category"]}
        for p in items
    ]

    print(f"当前在售 {len(snapshot)} 件：")
    for p in snapshot:
        print(f"  {p['id']:>3} {p['name']:<24} ¥{p['price']:<8} {p['category']}")

    if args.write:
        raw = json.loads(TASKS.read_text(encoding="utf-8"))
        old = len(raw.get("productSnapshot", []))
        raw["productSnapshot"] = snapshot
        TASKS.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n已写回 {TASKS}（{old} -> {len(snapshot)} 条）")
        print("注意：若数量变化，部分任务的期望结果可能需要同步调整。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
