"""演示脚本：真实跑一遍 AI 助手，打印对话与确认流程。

用法（两个服务都在运行）：
    .venv\\Scripts\\python.exe scripts/demo_chat.py
"""

from __future__ import annotations

import asyncio
import contextlib
import sys

import httpx

for _s in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _s.reconfigure(encoding="utf-8", errors="replace")

JAVA = "http://localhost:8081"
AGENT = "http://127.0.0.1:8090"
SERVICE = "demo-agent-token-local"


async def main() -> None:
    # 每次运行用独立会话号：LangGraph 会按 conversationId 持久化多轮记忆，
    # 复用同一个 ID 会把上一次的对话（和商品 ID）带进这次，容易误解。
    import uuid

    run_id = uuid.uuid4().hex[:6]

    async with httpx.AsyncClient(timeout=180, trust_env=False) as c:
        # 1) 登录网页端（拿 session）
        r = await c.post(
            f"{JAVA}/doLogin",
            data={"username": "user01", "password": "pass123"},
            follow_redirects=False,
        )
        print(f"[1] 登录 user01 → HTTP {r.status_code}")

        # 2) 用 session 换 capability token
        r = await c.post(
            f"{JAVA}/api/v1/agent/session",
            headers={"X-Service-Token": SERVICE},
            json={"conversationId": "demo"},
        )
        body = r.json()
        if body.get("code") != 0:
            print("换令牌失败:", body)
            return
        actor = body["data"]["actorToken"]
        print(f"[2] 换取能力令牌 → {len(body['data']['scopes'])} 项权限")

        h = {"X-Actor-Token": actor}

        async def ask(msg: str, conv: str) -> dict:
            print(f"\n你：{msg}")
            r = await c.post(
                f"{AGENT}/api/chat", headers=h, json={"message": msg, "conversationId": conv}
            )
            d = r.json()
            tools = d.get("toolCalls") or []
            print(f"    （调用工具：{tools or '无'}）")
            print(f"助手：{d.get('reply', '')[:400]}")
            return d

        # 3) 只读问题
        await ask("500 以内的数码产品有哪些？", f"demo-search-{run_id}")
        await ask("数据结构这本书 18 元贵吗？", f"demo-compare-{run_id}")

        # 4) 写操作：会弹确认卡片
        print("\n" + "=" * 60)
        print("【写操作】下面会触发人工确认")
        print("=" * 60)
        conv = f"demo-publish-{run_id}"
        d = await ask(
            "帮我发布一件闲置：标题「演示台灯」，价格 45 元，分类 生活用品，成色 9成新", conv
        )
        conf = next(
            (e for e in (d.get("events") or []) if e.get("type") == "confirmation_required"), None
        )
        if conf:
            print("\n>>> 确认卡片内容：")
            print("   ", conf["summary"]["title"])
            for f in conf["summary"]["fields"]:
                print(f"    · {f['label']}：{f['value']}")
            print("    提示：", conf["summary"].get("notice", ""))
            print("\n>>> 模拟用户点『确认执行』…")
            r = await c.post(
                f"{AGENT}/api/chat/resume-sync",
                headers=h,
                json={"conversationId": conv, "approved": True, "action": conf["action"]},
            )
            print("    结果：", r.json().get("reply", "")[:200])
        else:
            print("（没有触发确认，回复：", d.get("reply", "")[:200], "）")


asyncio.run(main())
