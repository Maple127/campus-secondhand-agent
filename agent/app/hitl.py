"""人工确认（Human-in-the-Loop）机制。

## 为什么需要

Agent 可以读数据是安全的，但**写操作必须由人拍板**：
下单会锁定商品、发布会产生待审核内容、举报会影响他人。让模型自主执行这些动作，
一旦理解偏差就会造成真实的业务后果。

## 实现要点（踩过的坑）

用 LangGraph 的 `interrupt()` 在工具内部挂起图。但要注意官方文档的这句话：

> The graph resumes from the start of the node, **re-executing** all logic.

也就是说 —— **节点会被重新执行**。如果把"调用后端"写在 `interrupt()` 之前，
恢复时会再执行一遍，造成重复下单。因此这里的顺序是死的：

    1) 先 interrupt() 拿确认结果       ← 会被重复执行，但它是幂等的（只读）
    2) 确认通过后再执行副作用           ← 只会执行一次
    3) 副作用外面再套幂等账本           ← 双保险

第 3 层不是多余的：LangGraph 的恢复语义、用户双击确认、网络重试都可能造成重复触发，
幂等账本让"同一个确认动作"在系统层面永远只产生一次副作用。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from langgraph.types import interrupt

from app.idempotency import IdempotentExecutor

logger = logging.getLogger(__name__)

#: 幂等账本（请求级注入）
_executor: ContextVar[IdempotentExecutor | None] = ContextVar("idempotent_executor", default=None)


@contextmanager
def confirmation_context(executor: IdempotentExecutor) -> Iterator[None]:
    """在请求处理期间绑定幂等账本。"""
    handle = _executor.set(executor)
    try:
        yield
    finally:
        _executor.reset(handle)


def _require_executor() -> IdempotentExecutor:
    executor = _executor.get()
    if executor is None:
        raise RuntimeError("幂等账本未初始化：请在请求处理中使用 confirmation_context(...) 包裹")
    return executor


def _current_actor_token() -> str | None:
    """取当前请求的能力令牌，用作幂等作用域。

    延迟 import 以避免与 tools 模块循环依赖。
    """
    try:
        from app.tools import _actor_token

        return _actor_token.get()
    except Exception:  # noqa: BLE001
        return None


async def confirm_and_execute(
    *,
    action: str,
    params: dict[str, Any],
    summary: dict[str, Any],
    run,
    scope: str | None = None,
) -> dict[str, Any]:
    """请求用户确认，通过后执行动作（带幂等保护）。

    Args:
        action:  动作标识，如 "create_order"。
        params:  规范化后的参数，用于生成幂等指纹。
        summary: 给用户看的确认信息（前端渲染确认卡片）。
        run:     无参可等待函数，真正执行副作用。
        scope:   作用域，用于把幂等指纹绑定到具体用户。
                 不传时会自动取当前 actor token —— **绝不能省**，
                 否则不同用户的相同操作会互相干扰。

    Returns:
        执行结果 dict；被拒绝时返回 {"rejected": True, ...}。
    """
    executor = _require_executor()
    # 幂等指纹必须绑定用户身份：否则 A、B 两人用同样参数发同样的商品时，
    # B 的确认会被误判为 A 的重复请求而静默跳过。
    effective_scope = scope if scope is not None else _current_actor_token()
    fingerprint = IdempotentExecutor.fingerprint(action, params, effective_scope)

    # ---- 1) 挂起等待用户确认（此段会被重复执行，故必须无副作用）----
    decision = interrupt(
        {
            "type": "confirmation_required",
            "action": action,
            "fingerprint": fingerprint,
            "summary": summary,
            # 提示前端这是需要人工确认的动作，不要自动放行
            "message": "这是一个会改变数据的操作，需要你确认后才会执行。",
        }
    )

    if not _is_approved(decision):
        logger.info("用户拒绝执行: action=%s fingerprint=%s", action, fingerprint)
        return {
            "rejected": True,
            "action": action,
            "message": "用户取消了该操作，未执行。",
        }

    # ---- 2) 幂等账本：同一确认只允许产生一次副作用 ----
    outcome = await executor.run_once(fingerprint, run)

    result = outcome.get("result") or {}
    if not isinstance(result, dict):
        result = {"result": result}
    if outcome.get("duplicate"):
        result = dict(result)
        result["idempotentReplay"] = True
        result["message"] = "该操作之前已经执行过，本次未重复执行。"
    return result


def _is_approved(decision: Any) -> bool:
    """解析用户的确认结果。

    接受多种写法以兼容不同前端：
      True / "yes" / "approve" / {"approved": true}
    默认（无法识别）视为**拒绝** —— 安全默认。
    """
    if decision is None:
        return False
    if isinstance(decision, bool):
        return decision
    if isinstance(decision, str):
        return decision.strip().lower() in {
            "yes",
            "y",
            "true",
            "approve",
            "approved",
            "ok",
            "confirm",
        }
    if isinstance(decision, dict):
        for key in ("approved", "confirm", "approve", "ok"):
            if key in decision:
                return _is_approved(decision[key])
        if decision.get("action") in {"approve", "confirm", "yes"}:
            return True
        if decision.get("action") in {"reject", "cancel", "no"}:
            return False
    logger.warning("无法识别的确认结果，按拒绝处理: %r", decision)
    return False
