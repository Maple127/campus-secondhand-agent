"""验证确认事件能通过 SSE 流式接口送达前端。

浏览器用的是 /api/chat/stream（SSE），
前面的 e2e_hitl.py 用的是 /api/chat（非流式）。
两者走的是同一套事件翻译，但仍需分别验证 —— 流式路径涉及
事件分包，是最容易丢事件的地方。
"""

import asyncio
import contextlib
import json
import sys
import uuid

import httpx

for _s in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _s.reconfigure(encoding="utf-8", errors="replace")

JAVA = "http://localhost:8081"
AGENT = "http://127.0.0.1:8090"
SERVICE = "demo-agent-token-local"


async def main() -> int:
    async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
        await client.post(
            f"{JAVA}/doLogin",
            data={"username": "user03", "password": "pass123"},
            follow_redirects=False,
        )
        r = await client.post(
            f"{JAVA}/api/v1/agent/session",
            headers={"X-Service-Token": SERVICE},
            json={"conversationId": "sse-hitl"},
        )
        actor = r.json()["data"]["actorToken"]
        headers = {"X-Actor-Token": actor, "Accept": "text/event-stream"}

        conv = "sse-conf-" + uuid.uuid4().hex[:6]
        marker = "SSE-" + uuid.uuid4().hex[:6]

        print("=== 第一次请求：应收到 confirmation_required ===")
        payload = {
            "message": f"帮我发布一件闲置：标题「{marker} 台灯」，价格 45 元，分类 生活用品",
            "conversationId": conv,
        }

        events = []
        async with client.stream(
            "POST", f"{AGENT}/api/chat/stream", headers=headers, json=payload
        ) as resp:
            print(f"HTTP {resp.status_code} content-type={resp.headers.get('content-type')}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                evt = json.loads(line[5:].strip())
                events.append(evt)
                t = evt["type"]
                if t == "confirmation_required":
                    print(f"  [confirmation_required] action={evt['action']}")
                    for f in evt["summary"]["fields"]:
                        print(f"      {f['label']}: {f['value']}")
                elif t == "tool_start":
                    print(f"  [tool_start] {evt['name']} {evt.get('args')}")
                elif t == "done":
                    print(f"  [done] steps={evt.get('steps')}")
                elif t == "error":
                    print(f"  [error] {evt['message']}")

        [e["type"] for e in events]
        conf = next((e for e in events if e["type"] == "confirmation_required"), None)
        ok1 = conf is not None
        print(f"\n{'PASS' if ok1 else 'FAIL'}: SSE 收到确认事件")

        # 二次请求：调用 resume 流式接口完成确认
        print("\n=== 第二次请求：resume 并确认 ===")
        resumed = []
        async with client.stream(
            "POST",
            f"{AGENT}/api/chat/resume",
            headers=headers,
            json={"conversationId": conv, "approved": True, "action": "publish_product"},
        ) as resp:
            print(f"HTTP {resp.status_code}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                evt = json.loads(line[5:].strip())
                resumed.append(evt)
                if evt["type"] == "token":
                    pass
                elif evt["type"] == "tool_start":
                    print(f"  [tool_start] {evt['name']}")
                elif evt["type"] == "tool_end":
                    print(f"  [tool_end] {evt['name']} ok={evt['ok']}")
                elif evt["type"] == "done":
                    print(f"  [done] resumed={evt.get('resumed')}")

        text = "".join(e["text"] for e in resumed if e["type"] == "token")
        ok2 = "审核" in text or "已提交" in text
        print(f"\n{'PASS' if ok2 else 'FAIL'}: resume 得到执行结果")
        print("     回复:", text.replace("\n", " ")[:200])

        # 验证真的写库了
        r = await client.get(
            f"{JAVA}/api/v1/products/mine/list",
            headers={"X-Actor-Token": actor, "X-Service-Token": SERVICE},
        )
        mine = r.json().get("data") or []
        created = [p for p in mine if marker in (p.get("name") or "")]
        ok3 = len(created) == 1 and created[0]["status"] == "PENDING_APPROVAL"
        print(
            f"{'PASS' if ok3 else 'FAIL'}: 商品已创建且为待审核 "
            f"(count={len(created)}, status={created[0]['status'] if created else 'n/a'})"
        )

        # 清理
        if created:
            import subprocess

            subprocess.run(
                [
                    "mysql",
                    "-uroot",
                    "-p123456",
                    "login_db",
                    "-e",
                    f"DELETE FROM product WHERE id={created[0]['id']};",
                ],
                capture_output=True,
            )

        ok = ok1 and ok2 and ok3
        print(f"\n{'PASS' if ok else 'FAIL'}: SSE + resume 全链路")
        return 0 if ok else 1


sys.exit(asyncio.run(main()))
