"""FastAPI 应用入口。

提供的接口：
  GET  /health                              健康检查（含后端连通性）
  GET  /playground                          内置调试页面（浏览器直接对话）
  POST /api/chat/stream                     SSE 流式对话（推荐）
  POST /api/chat/resume                     SSE 恢复（用户确认写操作后）
  POST /api/chat                            一次性返回（脚本/测试用）
  POST /api/chat/resume-sync                一次性恢复（脚本/测试用）
  GET  /api/conversation/{id}               读取会话历史
  GET  /api/conversation/{id}/pending       是否有待确认动作
  GET  /api/idempotency/stats               幂等账本统计

身份怎么来：actor_token 由前端从 **Java 后端** 的 /api/v1/agent/session 换取，
本服务不签发令牌、也拿不到用户密码。见 docs/agent-api.md。
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.backend import BackendClient, BackendError
from app.config import get_settings
from app.graph import AgentRunner
from app.metrics import METRICS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("agent")

_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时创建长生命周期对象，关闭时释放连接池。"""
    logger.info(
        "Agent 服务启动：backend=%s model=%s db=%s",
        _settings.backend_base_url,
        _settings.deepseek_model,
        _settings.checkpoint_db_path,
    )

    backend = BackendClient(
        base_url=_settings.backend_base_url,
        service_token=_settings.require_service_token(),
        timeout=_settings.backend_timeout,
        trust_env=_settings.backend_trust_env,
    )
    app.state.backend = backend

    # 持久化 checkpointer：人工确认是"挂起 → 等待用户 → 恢复"的跨请求流程，
    # 状态必须跨重启存活，否则用户刷新页面或服务重启后就再也无法完成该操作。
    # AsyncSqliteSaver 是 async context manager，生命周期必须与 lifespan 对齐。
    db_path = Path(_settings.checkpoint_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from app.idempotency import IdempotentExecutor

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        executor = IdempotentExecutor(db_path)
        app.state.runner = AgentRunner(_settings, checkpointer, executor=executor)
        app.state.executor = executor
        try:
            yield
        finally:
            await backend.aclose()
            logger.info("Agent 服务已停止")


app = FastAPI(
    title="Campus Secondhand Agent",
    description="校园二手交易平台的 AI 助手：自然语言搜索、比价、发布与沟通",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS：Thymeleaf 页面在 8081，本服务在 8090，浏览器直连属于跨源请求。
# demo 阶段按配置白名单放行；生产应改为同源反向代理（由网关转发 /agent/**）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins_list(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Actor-Token", "X-Service-Token"],
)


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="用户自然语言输入")
    conversationId: str = Field(
        ..., min_length=1, max_length=64, description="会话ID，用于多轮记忆"
    )
    userName: str | None = Field(default=None, description="可选的用户名，用于提示词个性化")


class ResumeRequest(BaseModel):
    conversationId: str = Field(..., min_length=1, max_length=64, description="会话ID")
    approved: bool = Field(..., description="用户是否同意执行该写操作")
    action: str | None = Field(default=None, description="被确认的动作名，仅用于日志与前端回显")


def _require_actor_token(actor_token: str | None) -> str:
    if not actor_token:
        raise HTTPException(
            status_code=401,
            detail=(
                "缺少 X-Actor-Token。请先登录网页端，再调用 Java 后端的 "
                "POST /api/v1/agent/session 获取能力令牌。"
            ),
        )
    return actor_token


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    """健康检查：同时探测 Java 后端是否可达。"""
    backend: BackendClient = app.state.backend
    backend_ok = False
    detail = ""
    try:
        # 用一个只读端点探测；无 actor token 时预期返回 401，
        # 能收到 401 恰恰说明服务令牌被接受、后端是活的。
        await backend.list_categories(actor_token="probe")
        backend_ok = True
        detail = "ok"
    except BackendError as exc:
        if exc.status == 401:
            backend_ok = True
            detail = "reachable (actor token required)"
        else:
            detail = f"HTTP {exc.status}: {exc.message}"
    except Exception as exc:  # noqa: BLE001
        detail = f"unreachable: {exc}"

    return {
        "status": "ok",
        "backend": {"url": _settings.backend_base_url, "ok": backend_ok, "detail": detail},
        "model": _settings.deepseek_model,
    }


@app.post("/api/chat/stream")
async def chat_stream(
    req: ChatRequest,
    x_actor_token: str | None = Header(default=None, alias="X-Actor-Token"),
):
    """SSE 流式对话。

    事件类型见 app/graph.py 顶部说明。
    """
    actor_token = _require_actor_token(x_actor_token)
    backend: BackendClient = app.state.backend
    runner: AgentRunner = app.state.runner

    async def event_generator():
        try:
            async for event in runner.stream(
                req.message,
                conversation_id=req.conversationId,
                actor_token=actor_token,
                backend=backend,
                user_name=req.userName,
            ):
                yield {"data": json.dumps(event, ensure_ascii=False)}
        except Exception as exc:
            logger.exception("SSE 流异常")
            yield {
                "data": json.dumps(
                    {"type": "error", "message": f"服务异常：{exc}"}, ensure_ascii=False
                )
            }

    return EventSourceResponse(event_generator())


@app.post("/api/chat")
async def chat(
    req: ChatRequest,
    x_actor_token: str | None = Header(default=None, alias="X-Actor-Token"),
) -> dict:
    """非流式对话，便于脚本与自动化测试调用。"""
    actor_token = _require_actor_token(x_actor_token)
    backend: BackendClient = app.state.backend
    runner: AgentRunner = app.state.runner

    text: list[str] = []
    events: list[dict] = []
    async for event in runner.stream(
        req.message,
        conversation_id=req.conversationId,
        actor_token=actor_token,
        backend=backend,
        user_name=req.userName,
    ):
        events.append(event)
        if event["type"] == "token":
            text.append(event["text"])

    _record_turn(runner)
    return {
        "reply": "".join(text),
        "events": events,
        "toolCalls": [e["name"] for e in events if e["type"] == "tool_start"],
        # token 用量：评测据此计算单次成本
        "usage": runner.last_usage,
    }


def _record_turn(runner: Any) -> None:
    """每轮对话后累计指标（token / 轮次）。"""
    usage = runner.last_usage
    METRICS.record_turn(int(usage.get("input") or 0), int(usage.get("output") or 0))


@app.get("/api/metrics")
async def metrics() -> dict[str, Any]:
    """进程内指标快照。

    用途：消融评测直接读它，回答"重试触发了几次""压缩省了多少"这类问题，
    不必去解析日志。
    """
    return {"counters": METRICS.snapshot()}


@app.post("/api/metrics/reset")
async def metrics_reset() -> dict[str, bool]:
    METRICS.reset()
    return {"ok": True}


@app.post("/api/chat/resume")
async def chat_resume(
    req: ResumeRequest,
    x_actor_token: str | None = Header(default=None, alias="X-Actor-Token"),
):
    """用户对确认卡片作出决定后，恢复被挂起的图（SSE）。

    这是 HITL 的关键一步：写操作在 `interrupt()` 处暂停，
    用户点「确认执行」或「取消」后调用本接口，图从断点继续。
    """
    actor_token = _require_actor_token(x_actor_token)
    backend: BackendClient = app.state.backend
    runner: AgentRunner = app.state.runner

    decision = {"approved": bool(req.approved), "action": req.action or ""}

    async def event_generator():
        try:
            async for event in runner.resume(
                decision,
                conversation_id=req.conversationId,
                actor_token=actor_token,
                backend=backend,
            ):
                yield {"data": json.dumps(event, ensure_ascii=False)}
        except Exception as exc:
            logger.exception("SSE 恢复流异常")
            yield {
                "data": json.dumps(
                    {"type": "error", "message": f"服务异常：{exc}"}, ensure_ascii=False
                )
            }

    return EventSourceResponse(event_generator())


@app.post("/api/chat/resume-sync")
async def chat_resume_sync(
    req: ResumeRequest,
    x_actor_token: str | None = Header(default=None, alias="X-Actor-Token"),
) -> dict:
    """非流式恢复，便于脚本与自动化测试调用。"""
    actor_token = _require_actor_token(x_actor_token)
    backend: BackendClient = app.state.backend
    runner: AgentRunner = app.state.runner

    decision = {"approved": bool(req.approved), "action": req.action or ""}
    text: list[str] = []
    events: list[dict] = []
    async for event in runner.resume(
        decision,
        conversation_id=req.conversationId,
        actor_token=actor_token,
        backend=backend,
    ):
        events.append(event)
        if event["type"] == "token":
            text.append(event["text"])

    return {
        "reply": "".join(text),
        "events": events,
        "toolCalls": [e["name"] for e in events if e["type"] == "tool_start"],
        "confirmation": next((e for e in events if e["type"] == "confirmation_required"), None),
        "usage": runner.last_usage,
    }


@app.get("/api/conversation/{conversation_id}/pending")
async def pending_confirmation(conversation_id: str) -> dict:
    """查询会话是否有等待确认的动作（前端刷新后据此恢复确认卡片）。"""
    runner: AgentRunner = app.state.runner
    pending = await runner.has_pending_confirmation(conversation_id)
    return {"conversationId": conversation_id, "pendingConfirmation": pending}


@app.get("/api/conversation/{conversation_id}")
async def conversation_history(conversation_id: str) -> dict:
    """读取会话历史（前端刷新后恢复对话用）。"""
    runner: AgentRunner = app.state.runner
    return {"conversationId": conversation_id, "messages": await runner.history(conversation_id)}


@app.get("/api/idempotency/stats")
async def idempotency_stats() -> dict:
    """幂等账本统计（调试与测试断言用）。"""
    executor = app.state.executor
    return {"ledger": executor.stats()}


@app.get("/playground", response_class=HTMLResponse)
async def playground() -> HTMLResponse:
    """内置调试页面：在浏览器里直接和助手对话。"""
    html_path = Path(__file__).parent / "static" / "playground.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))
