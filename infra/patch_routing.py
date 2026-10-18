# -*- coding: utf-8 -*-
"""把显式路由接进 main.py 的两个聊天入口。

用 Python 做多行替换，避免 PowerShell here-string 的引号地雷。
"""

from pathlib import Path

p = Path(r"D:\Develop\AI\deepseek\test2\agent\app\main.py")
src = p.read_text(encoding="utf-8")

# ---------------------------------------------------------------- 1) 导入
if "from app.routing import" not in src:
    src = src.replace(
        "from app.metrics import METRICS",
        "from app.metrics import METRICS\n"
        "from app.routing import STRATEGY_FAST, STRATEGY_REFUSE, route",
        1,
    )

# ---------------------------------------------------------------- 2) 导入区排序交 ruff

# ------------------------------------------------------------ 3) chat 入口
OLD_CHAT = """    actor_token = _require_actor_token(x_actor_token)
    _guard_input(req.message)
    backend: BackendClient = app.state.backend
    runner: AgentRunner = app.state.runner

    text: list[str] = []
"""

NEW_CHAT = '''    actor_token = _require_actor_token(x_actor_token)
    _guard_input(req.message)
    backend: BackendClient = app.state.backend
    runner: AgentRunner = app.state.runner

    # ---- 显式路由：先由规则决定走哪条路，再执行 ----
    # 规则不调模型，所以这一步是零成本；判错了也有兜底（快路径答不了就退回 agent）。
    decision = route(req.message)
    if decision.strategy == STRATEGY_REFUSE:
        METRICS.route_refuse += 1
        raise HTTPException(
            status_code=400,
            detail="这个请求我处理不了，换个和二手交易相关的问题试试？",
        )
    if decision.strategy == STRATEGY_FAST:
        METRICS.route_fast += 1
        fast = await runner.quick_answer(
            req.message, actor_token=actor_token, backend=backend
        )
        if fast is not None:
            METRICS.route_fast_ok += 1
            _record_turn(runner)
            return {
                "reply": fast.text,
                "events": [
                    {"type": "token", "text": fast.text},
                    {"type": "done", "steps": 0},
                ],
                "toolCalls": ["search_products"],
                "usage": runner.last_usage,
                "strategy": decision.strategy,
                "routeReason": decision.reason,
            }
        # 快路径答不了（检索为空 / 抽不出关键词 / 生成失败）→ 退回 agent
        METRICS.route_fast_fallback += 1
    METRICS.route_agent += 1

    text: list[str] = []
'''

if OLD_CHAT not in src:
    raise SystemExit("chat 入口未匹配")
src = src.replace(OLD_CHAT, NEW_CHAT, 1)

# ------------------------------------------- 4) agent 正常返回体里加 strategy
OLD_RET = '''        "usage": runner.last_usage,
    }


def _guard_input'''
NEW_RET = '''        "usage": runner.last_usage,
        "strategy": decision.strategy,
        "routeReason": decision.reason,
    }


def _guard_input'''
if OLD_RET in src:
    src = src.replace(OLD_RET, NEW_RET, 1)
else:
    print("警告：未找到 agent 返回体锚点，strategy 字段可能没加上")

p.write_text(src, encoding="utf-8")
print("main.py 已更新")
