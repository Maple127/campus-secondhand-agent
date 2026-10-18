"""清理评测遗留状态：取消评测中创建的订单，释放被锁定的商品。

写操作评测会真实产生副作用（下单锁库存），这是"测真实行为"的代价。
跑完必须还原，否则下一次评测的库存基线与 gold_tasks.json 的快照就不一致了。
"""

import asyncio
import sys

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JAVA = "http://localhost:8081"
SERVICE = "demo-agent-token-local"


async def main():
    async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
        await c.post(
            f"{JAVA}/doLogin",
            data={"username": "user01", "password": "pass123"},
            follow_redirects=False,
        )
        r = await c.post(
            f"{JAVA}/api/v1/agent/session",
            headers={"X-Service-Token": SERVICE},
            json={"conversationId": "cleanup"},
        )
        actor = r.json()["data"]["actorToken"]
        h = {"X-Actor-Token": actor, "X-Service-Token": SERVICE}

        # 找出自己名下所有未付款订单并取消
        r = await c.get(f"{JAVA}/api/v1/orders", params={"role": "buyer"}, headers=h)
        orders = r.json().get("data") or []
        cancelled = 0
        for o in orders:
            if o.get("status") == "UNPAID":
                rr = await c.post(
                    f"{JAVA}/api/v1/orders/{o['orderNo']}/cancel",
                    headers=h,
                    json={"reason": "评测后清理"},
                )
                if rr.json().get("code") == 0:
                    cancelled += 1
                    print(f"已取消订单 {o['orderNo']} (productId={o.get('productId')})")
        print(f"共取消 {cancelled} 笔未付款订单")

        # 校验商品已释放
        r = await c.get(f"{JAVA}/api/v1/products", params={"size": 50}, headers=h)
        items = r.json()["data"]["items"]
        print(f"当前在售商品数: {len(items)}")


asyncio.run(main())
