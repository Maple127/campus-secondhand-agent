"""M4 端到端：写操作 + 人工确认（真后端 + 真 DeepSeek）。

验证的完整链路：
    用户说"帮我发布一件闲置" → 模型决定调用 publish_product
    → 工具 interrupt() 挂起 → SSE 产出 confirmation_required
    → 用户确认 → resume 接口恢复 → 真正写库 → 商品进入待审核

重点断言：
  - 挂起时**不能**已经写库（否则确认就是摆设）
  - 拒绝时**不能**写库
  - 同一确认重复提交，商品只能被创建一次（幂等）
  - 发布结果必须是待审核，不是直接上架
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
import uuid

import httpx

for _s in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _s.reconfigure(encoding="utf-8", errors="replace")

JAVA = "http://localhost:8081"
AGENT = "http://127.0.0.1:8090"
SERVICE_TOKEN = "demo-agent-token-local"

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL':<4} {name:<44} {detail}")
    (PASS if ok else FAIL).append(name)


async def main() -> int:
    async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
        # 登录并换取令牌
        await client.post(
            f"{JAVA}/doLogin",
            data={"username": "user01", "password": "pass123"},
            follow_redirects=False,
        )
        r = await client.post(
            f"{JAVA}/api/v1/agent/session",
            headers={"X-Service-Token": SERVICE_TOKEN},
            json={"conversationId": "m4"},
        )
        body = r.json()
        if body.get("code") != 0:
            check("capability token", False, str(body))
            return 1
        actor = body["data"]["actorToken"]
        check("capability token", True, f"scopes={len(body['data']['scopes'])}")

        # 调用后端 /api/v1/** 必须同时带服务令牌与能力令牌，缺任一都是 401
        h = {"X-Actor-Token": actor, "X-Service-Token": SERVICE_TOKEN}

        async def list_mine() -> list[dict]:
            """查询用户已发布的商品。

            capability token 有 TTL，长流程中可能过期；遇到 401 就重新换一次
            令牌再试，模拟前端刷新授权的行为。
            """
            nonlocal actor, h
            resp = await client.get(f"{JAVA}/api/v1/products/mine/list", headers=h)
            if resp.status_code == 401:
                again = await client.post(
                    f"{JAVA}/api/v1/agent/session",
                    headers={"X-Service-Token": SERVICE_TOKEN},
                    json={"conversationId": "m4-refresh"},
                )
                actor = again.json()["data"]["actorToken"]
                h = {"X-Actor-Token": actor, "X-Service-Token": SERVICE_TOKEN}
                resp = await client.get(f"{JAVA}/api/v1/products/mine/list", headers=h)
            if resp.status_code != 200:
                print(f"     [debug] mine/list http={resp.status_code} {resp.text[:200]}")
            return resp.json().get("data") or []

        # 记录测试前用户发布的商品数
        before_count = len(await list_mine())
        marker = "M4-" + uuid.uuid4().hex[:6]

        conv = "m4-publish-" + uuid.uuid4().hex[:6]

        # ---------- 1) 让模型发起发布 ----------
        print("\n--- 发起发布（应挂起等待确认）---")
        t0 = time.perf_counter()
        resp = await client.post(
            f"{AGENT}/api/chat",
            headers=h,
            json={
                "message": f"帮我发布一件闲置：标题「{marker} 测试台灯」，价格 45 元，"
                f"成色 9成新，分类 生活用品，交易地点 3号宿舍楼下",
                "conversationId": conv,
            },
        )
        data = resp.json()
        events = data.get("events", [])
        types = [e["type"] for e in events]
        conf = next((e for e in events if e["type"] == "confirmation_required"), None)
        elapsed = time.perf_counter() - t0

        check("confirmation event emitted", conf is not None, f"{elapsed:.1f}s")
        if conf is None:
            print("     事件序列:", types)
            print("     回复:", data.get("reply", "")[:300])
            return 1

        check(
            "confirmation action correct",
            conf.get("action") == "publish_product",
            f"action={conf.get('action')}",
        )
        labels = [f["label"] for f in conf["summary"]["fields"]]
        check(
            "summary is user-checkable", "标题" in labels and "售价" in labels, f"fields={labels}"
        )

        # 关键：此时不能已经写库
        during_count = len(await list_mine())
        check(
            "NOT written before confirmation",
            during_count == before_count,
            f"before={before_count} during={during_count}",
        )

        # ---------- 2) 拒绝路径 ----------
        print("\n--- 拒绝路径 ---")
        reject = await client.post(
            f"{AGENT}/api/chat/resume-sync",
            headers=h,
            json={
                "conversationId": conv,
                "approved": False,
                "action": "publish_product",
            },
        )
        reject_data = reject.json()
        reject_count = len(await list_mine())
        check("reject does not write", reject_count == before_count, f"count={reject_count}")
        check(
            "reject reply explains cancellation",
            "取消" in reject_data.get("reply", "") or "未" in reject_data.get("reply", ""),
            reject_data.get("reply", "")[:80].replace("\n", " "),
        )

        # ---------- 3) 同意路径 ----------
        print("\n--- 同意路径（重新发起并确认）---")
        conv2 = "m4-ok-" + uuid.uuid4().hex[:6]
        resp2 = await client.post(
            f"{AGENT}/api/chat",
            headers=h,
            json={
                "message": f"帮我发布一件闲置：标题「{marker}B 测试水杯」，价格 15 元，"
                f"分类 生活用品，交易地点 快递驿站",
                "conversationId": conv2,
            },
        )
        conf2 = next(
            (e for e in resp2.json().get("events", []) if e["type"] == "confirmation_required"),
            None,
        )
        check("second publish paused", conf2 is not None)
        if conf2 is None:
            print("     reply:", resp2.json().get("reply", "")[:300])
            return 1

        appro = await client.post(
            f"{AGENT}/api/chat/resume-sync",
            headers=h,
            json={
                "conversationId": conv2,
                "approved": True,
                "action": "publish_product",
            },
        )
        appro_data = appro.json()
        mine = await list_mine()
        created = [p for p in mine if marker in (p.get("name") or "")]

        # 诊断：失败时把关键信息打出来，避免"断言失败但看不出原因"
        if len(created) != 1:
            print(f"     [debug] marker={marker!r}")
            print(f"     [debug] mine count={len(mine)}")
            print(f"     [debug] names={[p.get('name') for p in mine]}")
            print(f"     [debug] resume reply={appro_data.get('reply', '')[:200]!r}")

        check("approve writes exactly one product", len(created) == 1, f"created={len(created)}")
        if created:
            st = created[0].get("status")
            check(
                "published product is PENDING_APPROVAL",
                st == "PENDING_APPROVAL",
                f"status={st}/{created[0].get('statusLabel')}",
            )
        check(
            "approve reply mentions review",
            "审核" in appro_data.get("reply", ""),
            appro_data.get("reply", "")[:100].replace("\n", " "),
        )

        # ---------- 4) 幂等：重复提交同一确认 ----------
        print("\n--- 幂等路径（重复提交同一确认）---")
        await client.post(
            f"{AGENT}/api/chat/resume-sync",
            headers=h,
            json={
                "conversationId": conv2,
                "approved": True,
                "action": "publish_product",
            },
        )
        dup_mine = await list_mine()
        dup_created = [p for p in dup_mine if marker in (p.get("name") or "")]
        check(
            "duplicate confirmation does not duplicate product",
            len(dup_created) == 1,
            f"count={len(dup_created)} (期望仍为 1)",
        )

        stats = await client.get(f"{AGENT}/api/idempotency/stats")
        print("     幂等账本:", stats.json())

        # ---------- 5) 无待确认时 resume 不报错 ----------
        pending = await client.get(f"{AGENT}/api/conversation/{conv2}/pending")
        check(
            "no pending after completion",
            pending.json().get("pendingConfirmation") is False,
            str(pending.json()),
        )

        # ---------- 6) 越权：agent 不得代付 ----------
        print("\n--- 支付边界 ---")
        pay = await client.post(
            f"{AGENT}/api/chat",
            headers=h,
            json={
                "message": "帮我支付订单，支付密码 123456",
                "conversationId": "m4-pay-" + uuid.uuid4().hex[:6],
            },
        )
        pay_events = pay.json().get("events", [])
        pay_conf = [e for e in pay_events if e["type"] == "confirmation_required"]
        check(
            "no pay tool offered to model",
            all(e.get("action") != "order_pay" for e in pay_conf),
            f"confirmations={[e.get('action') for e in pay_conf]}",
        )

    print("\n" + "=" * 56)
    print(f"M4 E2E TOTAL={len(PASS) + len(FAIL)}  PASS={len(PASS)}  FAIL={len(FAIL)}")
    for name in FAIL:
        print(f"  FAILED: {name}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
