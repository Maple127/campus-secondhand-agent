# -*- coding: utf-8 -*-
"""把显式路由接进 SSE 流式入口。

http 入口和流式入口必须走同一套路由，否则网页端和 API 的行为会不一致。
"""

from pathlib import Path

p = Path(r"D:\Develop\AI\deepseek\test2\agent\app\main.py")
src = p.read_text(encoding="utf-8")

OLD = """    async def event_generator():
        try:
            async for event in runner.stream(
                req.message,
                conversation_id=req.conversationId,
                actor_token=actor_token,
                backend=backend,
                user_name=req.userName,
            ):
                yield {"data": json.dumps(event, ensure_ascii=False)}
"""

NEW = '''    decision = route(req.message)

    async def event_generator():
        # REFUSE 和 FAST 都不进入图：前者直接拒绝，后者只做一次检索 + 一次生成。
        if decision.strategy == STRATEGY_REFUSE:
            METRICS.route_refuse += 1
            yield {
                "data": json.dumps(
                    {
                        "type": "error",
                        "message": "这个请求我处理不了，换个和二手交易相关的问题试试？",
                        "strategy": decision.strategy,
                    },
                    ensure_ascii=False,
                )
            }
            return

        if decision.strategy == STRATEGY_FAST:
            METRICS.route_fast += 1
            fast = await runner.quick_answer(
                req.message, actor_token=actor_token, backend=backend
            )
            if fast is not None:
                METRICS.route_fast_ok += 1
                _record_turn(runner)
                yield {
                    "data": json.dumps(
                        {"type": "token", "text": fast.text}, ensure_ascii=False
                    )
                }
                yield {
                    "data": json.dumps(
                        {"type": "done", "steps": 0, "strategy": decision.strategy},
                        ensure_ascii=False,
                    )
                }
                return
            METRICS.route_fast_fallback += 1

        METRICS.route_agent += 1
        try:
            async for event in runner.stream(
                req.message,
                conversation_id=req.conversationId,
                actor_token=actor_token,
                backend=backend,
                user_name=req.userName,
            ):
                event["strategy"] = decision.strategy
                yield {"data": json.dumps(event, ensure_ascii=False)}
'''

if OLD not in src:
    raise SystemExit("SSE 入口未匹配")
src = src.replace(OLD, NEW, 1)
p.write_text(src, encoding="utf-8")
print("SSE 入口已接线")
