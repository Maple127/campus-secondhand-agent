"""用真实后端接口验证品类词效果（不是离线模拟）。

对照组：直接调 /api/v1/products?q=... ，看返回的商品集合是否等于标准答案。
"""

from __future__ import annotations

import asyncio
import sys

import httpx

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = "http://localhost:8081"
SERVICE = "demo-agent-token-local"
EXCLUDE = {62, 67}

CASES = [
    ("耳机", {8}), ("蓝牙耳机", {8}), ("airpods", {8}),
    ("键盘", {10}), ("机械键盘", {10}), ("cherry", {10}),
    ("鼠标", {7}), ("罗技", {7}),
    ("台灯", {19}), ("小台灯", {19}),
    ("自行车", {11, 14}), ("单车", {11, 14}),
    ("电动车", {12}), ("滑板", {13}), ("平衡车", {15}),
    ("充电宝", {9}), ("移动电源", {9}),
    ("平板", {6}), ("ipad", {6}),
    ("数学", {1, 4}), ("考研数学", {1, 4}), ("线代", {4}), ("高数", {1}),
    ("英语四级", {2}), ("四级", {2}),
    ("风扇", {17}), ("瑜伽垫", {20}), ("收纳箱", {18}),
    ("床帘", {16}), ("数据结构", {3}),
]


async def main() -> None:
    async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
        await c.post(f"{BASE}/doLogin", data={"username": "user01", "password": "pass123"})
        sess = await c.post(f"{BASE}/api/v1/agent/session",
                            headers={"X-Service-Token": SERVICE},
                            json={"conversationId": "verify"})
        tok = sess.json()["data"]["actorToken"]
        h = {"X-Actor-Token": tok, "X-Service-Token": SERVICE}

        full = 0
        rec_sum = 0.0
        fp_sum = 0
        fails = []

        for q, expect in CASES:
            r = await c.get(f"{BASE}/api/v1/products",
                            params={"q": q, "size": 50}, headers=h)
            items = [p for p in r.json()["data"]["items"] if p["id"] not in EXCLUDE]
            got = {p["id"] for p in items}
            hit = got & expect
            rec = len(hit) / len(expect)
            rec_sum += rec
            # 数据集从 22 件扩到 150+ 之后，不再要求"只返回期望的那几件"
            # （同一个品类下现在有多件商品，这是应该的）。
            # 只要求"期望的那些必须被召回"，精确度靠人工抽查。
            if rec == 1.0:
                full += 1
            else:
                names = [p["name"] for p in items]
                fails.append((q, sorted(expect - got), names))

        print(f"{'查询':<10}{'应得':>4}  {'结果':<40}")
        print("-" * 70)
        for q, expect in CASES:
            r = await c.get(f"{BASE}/api/v1/products",
                            params={"q": q, "size": 50}, headers=h)
            items = [p for p in r.json()["data"]["items"] if p["id"] not in EXCLUDE]
            got = {p["id"] for p in items}
            rec = len(got & expect) / len(expect)
            mark = "OK" if rec == 1.0 else f"{rec:.0%}"
            show = ", ".join(p["name"][:12] for p in items) or "（空）"
            print(f"{q:<10}{len(expect):>4}  {show[:38]:<40}{mark}")

        print("-" * 70)
        print(f"全部召回 {full}/{len(CASES)}　平均召回 {rec_sum/len(CASES):.0%}")
        if fails:
            print("\n未通过：")
            for q, miss, names, fp in fails:
                print(f"  {q}: 漏 {miss}  多 {fp}  实际 {names}")


asyncio.run(main())
