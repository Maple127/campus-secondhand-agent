"""验证 SSE 流式接口：逐条打印事件，确认 token 是增量到达的。"""

import asyncio
import contextlib
import json
import sys
import time

import httpx

for s in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        s.reconfigure(encoding="utf-8", errors="replace")

JAVA = "http://localhost:8081"
AGENT = "http://127.0.0.1:8090"
SERVICE_TOKEN = "demo-agent-token-local"


async def main():
    async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
        await client.post(
            f"{JAVA}/doLogin",
            data={"username": "user01", "password": "pass123"},
            follow_redirects=False,
        )
        r = await client.post(
            f"{JAVA}/api/v1/agent/session",
            headers={"X-Service-Token": SERVICE_TOKEN},
            json={"conversationId": "sse-test"},
        )
        actor = r.json()["data"]["actorToken"]

        payload = {"message": "帮我搜一下数据结构这本书", "conversationId": "sse-test"}
        headers = {"X-Actor-Token": actor, "Accept": "text/event-stream"}

        print("=== SSE 事件流（逐条） ===")
        t0 = time.perf_counter()
        token_count = 0
        first_token_at = None
        event_types = []

        async with client.stream(
            "POST", f"{AGENT}/api/chat/stream", headers=headers, json=payload
        ) as resp:
            print(f"HTTP {resp.status_code}  content-type={resp.headers.get('content-type')}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                try:
                    evt = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                etype = evt.get("type")
                event_types.append(etype)
                if etype == "token":
                    token_count += 1
                    if first_token_at is None:
                        first_token_at = time.perf_counter() - t0
                    print(f"  [token] {evt['text']!r}")
                elif etype == "tool_start":
                    print(f"  [tool_start] {evt['name']} args={evt.get('args')}")
                elif etype == "tool_end":
                    print(f"  [tool_end] {evt['name']} ok={evt['ok']}")
                elif etype == "done":
                    print(f"  [done] steps={evt.get('steps')}")
                else:
                    print(f"  [{etype}] {evt}")

        total = time.perf_counter() - t0
        print("\n=== 统计 ===")
        print(f"token 事件数        : {token_count}")
        print(
            f"首 token 延迟       : {first_token_at:.2f}s"
            if first_token_at
            else "首 token 延迟: n/a"
        )
        print(f"总耗时              : {total:.2f}s")
        print(f"事件序列            : {event_types}")

        ok = token_count > 3 and "done" in event_types
        print(
            f"\n{'PASS' if ok else 'FAIL'}: SSE 增量输出{'正常' if ok else '异常'}"
            f"（token 数 > 3 且以 done 收尾）"
        )
        return 0 if ok else 1


sys.exit(asyncio.run(main()))
