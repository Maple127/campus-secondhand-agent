"""LangGraph Agent 组装与事件流。

为什么用 LangGraph（而不是裸 LangChain）：
  1. 需要 checkpointer 做**多轮会话记忆**（thread_id = 会话ID）
  2. 下一阶段写操作需要 `interrupt` 做**人工确认**（Human-in-the-Loop）
  3. 需要按节点流式输出，才能把「正在调用工具」实时推给前端

事件协议（SSE data 字段）：
  {"type":"token",   "text": "..."}                    模型输出的增量文本
  {"type":"tool_start","name":"search_products","args":{...}}
  {"type":"tool_end",  "name":"search_products","ok":true,"preview":"..."}
  {"type":"done",    "steps": 3}
  {"type":"error",   "message": "..."}
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from pathlib import Path
from typing import Any, Literal, cast

import httpx
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, RemoveMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.types import Command
from pydantic import SecretStr

from app import tools as tools_module
from app import write_tools
from app.backend import BackendClient
from app.config import Settings
from app.hitl import confirmation_context
from app.idempotency import IdempotentExecutor
from app.memory import Compressor
from app.metrics import METRICS
from app.prompt import build_system_prompt

logger = logging.getLogger(__name__)

#: 工具返回内容在事件里只放预览，避免把大段 JSON 推到前端
_TOOL_PREVIEW_LIMIT = 600

#: 需要的流式模式。写成带字面量类型的元组，是为了匹配 LangGraph 的 astream 重载
#: （直接传 list[str] 会被 mypy 判为不匹配，但运行时完全没问题）
# 必须是 list 而不是 tuple —— 传 tuple 时 LangGraph 会静默什么都不返回
# （它内部按 list 判断）。Literal 标注只是为了让 mypy 匹配 astream 的重载。
_STREAM_MODES: list[Literal["messages", "updates", "values"]] = [
    "messages",
    "updates",
    "values",
]


def build_llm(settings: Settings) -> ChatOpenAI:
    """构建 DeepSeek 对话模型。

    DeepSeek 提供 OpenAI 兼容接口，因此用 ChatOpenAI 指定 base_url 接入。
    显式传入 httpx 客户端，把 trust_env 变成可配置项：
    国内访问 api.deepseek.com 通常需要系统代理，而无代理环境则需要关掉。
    """
    return ChatOpenAI(
        model=settings.deepseek_model,
        # LangChain 1.x 要求 SecretStr，直接传 str 会在 mypy 里报类型错误；
        # 这里显式包一层，避免密钥被意外打进日志/异常信息
        api_key=SecretStr(settings.require_llm_key()),
        base_url=settings.deepseek_base_url,
        temperature=settings.llm_temperature,
        timeout=60.0,
        max_retries=2,
        http_async_client=httpx.AsyncClient(
            trust_env=settings.llm_trust_env,
            timeout=httpx.Timeout(60.0),
        ),
    )


class AgentRunner:
    """封装 agent 的构建与流式执行。

    单例持有 graph 与 checkpointer，会话历史按 thread_id 隔离。

    checkpointer 由外部注入：
      - 生产：AsyncSqliteSaver（持久化，人工确认状态可跨请求与重启存活）
      - 测试：InMemorySaver（无需落盘）
    之所以不在内部 new，是因为 AsyncSqliteSaver 需要 async context manager，
    其生命周期必须与应用 lifespan 对齐。
    """

    def __init__(
        self,
        settings: Settings,
        checkpointer: BaseCheckpointSaver,
        model: Any | None = None,
        executor: IdempotentExecutor | None = None,
    ) -> None:
        """初始化。

        Args:
            settings: 应用配置。
            checkpointer: 状态持久化实现。
            model: 可选的模型实例。仅用于测试注入 FakeModel，
                   生产路径传 None 由 build_llm() 构建 DeepSeek 模型 ——
                   这样测试无需真实 API Key 即可跑通整张图。
            executor: 幂等账本。为 None 时按需在内存目录创建（仅测试会这样）。
        """
        self._settings = settings
        self._checkpointer = checkpointer
        self._executor = executor or IdempotentExecutor(
            Path(settings.checkpoint_db_path).with_name("idempotency-test.db")
        )
        # 最近一次 stream/resume 的 token 用量。
        # 从流式 chunk 的 usage_metadata 累加 —— 评测需要它来算单次成本。
        self._last_usage: dict[str, int] = {"input": 0, "output": 0}
        # 模型只构建一次：压缩器和主图共用同一个实例。
        # 共用的代价是压缩本身也计入 token 成本（这一点在消融评测里会体现）。
        llm = model if model is not None else build_llm(settings)
        # FAST 路径也用它：快路径要一次模型调用来组织语言
        self._llm = llm
        # 上下文压缩器。关闭时不压缩（消融评测用这个开关做对照）。
        self._compressor: Compressor | None = (
            Compressor(
                llm,
                budget=settings.context_token_budget,
                keep_recent=settings.compress_keep_recent,
            )
            if settings.enable_compression
            else None
        )
        self._graph = create_agent(
            model=llm,
            # 只读工具 + 写工具：写工具内部会 interrupt() 等用户确认
            tools=[*tools_module.READ_ONLY_TOOLS, *write_tools.WRITE_TOOLS],
            system_prompt=build_system_prompt(),
            checkpointer=self._checkpointer,
        )

    @property
    def graph(self):
        return self._graph

    @property
    def executor(self) -> IdempotentExecutor:
        return self._executor

    @property
    def last_usage(self) -> dict[str, int]:
        """最近一轮对话的 token 用量（input / output）。"""
        return dict(self._last_usage)

    async def stream(
        self,
        message: str,
        *,
        conversation_id: str,
        actor_token: str,
        backend: BackendClient,
        user_name: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """执行一轮对话并产出事件流。

        并发安全：ContextVar 在 tool_context / confirmation_context 中绑定，
        各请求互不干扰；conversation_id 作为 thread_id 让会话彼此隔离。
        """
        config = self._config(conversation_id)

        steps = 0
        self._reset_usage()
        # 压缩必须发生在"本轮消息进入状态"之前：
        # 此时 checkpoint 里全是历史，可以安全地整段替换。
        await self._maybe_compress(config, conversation_id)
        try:
            with (
                tools_module.tool_context(actor_token, backend),
                confirmation_context(self._executor),
            ):
                async with aclosing(
                    # astream 运行时返回 async generator（有 aclose），
                    # 但类型标注只写了 AsyncIterator，这里补一个 cast
                    cast(
                        "AsyncGenerator[Any, None]",
                        self._graph.astream(
                            {"messages": [{"role": "user", "content": message}]},
                            config=config,
                            # values 用于捕获 __interrupt__（人工确认请求）
                            stream_mode=_STREAM_MODES,
                        ),
                    )
                ) as stream:
                    async for chunk in stream:
                        async for event in self._translate(chunk):
                            if event["type"] == "tool_start":
                                steps += 1
                            yield event
        except Exception as exc:
            logger.exception("agent 执行失败: %s", exc)
            yield {"type": "error", "message": _friendly_error(exc)}
            return

        yield {"type": "done", "steps": steps}

    async def resume(
        self,
        decision: dict[str, Any],
        *,
        conversation_id: str,
        actor_token: str,
        backend: BackendClient,
    ) -> AsyncIterator[dict[str, Any]]:
        """用户对确认卡片作出决定后，恢复被挂起的图。

        Args:
            decision: 例如 {"approved": True} 或 {"approved": False}。
        """
        config = self._config(conversation_id)
        steps = 0
        self._reset_usage()
        try:
            with (
                tools_module.tool_context(actor_token, backend),
                confirmation_context(self._executor),
            ):
                async with aclosing(
                    # 同上：astream 实际是 async generator
                    cast(
                        "AsyncGenerator[Any, None]",
                        self._graph.astream(
                            Command(resume=decision),
                            config=config,
                            stream_mode=_STREAM_MODES,
                        ),
                    )
                ) as stream:
                    async for chunk in stream:
                        async for event in self._translate(chunk):
                            if event["type"] == "tool_start":
                                steps += 1
                            yield event
        except Exception as exc:
            logger.exception("agent 恢复执行失败: %s", exc)
            yield {"type": "error", "message": _friendly_error(exc)}
            return

        yield {"type": "done", "steps": steps, "resumed": True}

    def _reset_usage(self) -> None:
        self._last_usage = {"input": 0, "output": 0}

    def _record_usage(self, message: Any) -> None:
        """累加 token 用量。

        真实模型（DeepSeek）会在消息上带 usage_metadata；
        假模型没有，此时保持 0 —— 评测时会体现为"成本为 0"，
        这是符合实际的，不应伪造。
        """
        usage = getattr(message, "usage_metadata", None)
        if not isinstance(usage, dict):
            return
        self._last_usage["input"] += int(usage.get("input_tokens") or 0)
        self._last_usage["output"] += int(usage.get("output_tokens") or 0)

    def _config(self, conversation_id: str) -> RunnableConfig:
        return {
            "configurable": {"thread_id": conversation_id},
            # 写操作要经过确认节点，步数上限需要比只读场景宽松
            "recursion_limit": max(self._settings.max_agent_steps * 3, 15),
        }

    async def has_pending_confirmation(self, conversation_id: str) -> bool:
        """会话是否正等待用户确认（前端刷新后据此恢复确认卡片）。"""
        state = await self._graph.aget_state(self._config(conversation_id))
        return bool(state.next)

    async def quick_answer(
        self,
        message: str,
        *,
        actor_token: str,
        backend: BackendClient,
    ) -> Any:
        """FAST 路径：一次检索 + 一次模型调用。

        返回 None 表示"这条路答不了"，调用方应退回 agent。
        """
        from app.fastpath import try_fast_answer

        result = await try_fast_answer(
            self._llm,
            message=message,
            actor_token=actor_token,
            backend=backend,
        )
        if result is not None:
            self._last_usage = dict(result.usage)
        return result

    async def _maybe_compress(self, config: RunnableConfig, conversation_id: str) -> None:
        """超出 token 预算时，把早期历史压成一条摘要。

        三条保护：

        1. **有挂起的人工确认时不动历史** —— interrupt 的载荷引用了具体的
           工具调用和消息，改写消息列表会让恢复时对不上。
        2. **压缩失败不阻断对话** —— 牺牲一次压缩，换这一轮照常回答。
        3. **整段替换而不是逐条删除** —— 摘要必须排在近期消息之前，
           靠 REMOVE_ALL_MESSAGES + 重新追加保证顺序。
        """
        if self._compressor is None:
            return
        try:
            state = await self._graph.aget_state(config)
            if state.next:
                # 等待用户确认中，跳过
                return
            messages = list((state.values or {}).get("messages") or [])
            plan = await self._compressor.plan(messages)
            if plan is None:
                return
            await self._graph.aupdate_state(
                config,
                {
                    "messages": [
                        RemoveMessage(id=REMOVE_ALL_MESSAGES),
                        plan.summary,
                        *plan.keep,
                    ]
                },
            )
            METRICS.record_compaction(plan.saved_tokens)
            logger.info("会话 %s 已压缩历史，保留近期 %d 条", conversation_id, len(plan.keep))
        except Exception:
            METRICS.compaction_failures += 1
            logger.warning("上下文压缩失败，本轮按原样继续", exc_info=True)

    async def _translate(self, chunk: Any) -> AsyncIterator[dict[str, Any]]:
        """把 LangGraph 的 stream_mode=["messages","updates"] 输出翻译成前端事件。"""
        # 多模式流返回 (mode, data) 二元组
        if not (isinstance(chunk, tuple) and len(chunk) == 2):
            return
        mode, data = chunk

        if mode == "messages":
            # data = (message_chunk, metadata)
            if not (isinstance(data, tuple) and len(data) == 2):
                return
            msg_chunk, _metadata = data
            # 真实模型流式输出 AIMessageChunk；
            # 但非流式的模型实现（含测试用的假模型）会直接给完整 AIMessage，
            # 两种都要兼容，否则会出现「用户问了但一个字都没返回」。
            if isinstance(msg_chunk, (AIMessageChunk, AIMessage)):
                # 先记 token 用量（评测算成本用），再判断是否有正文
                self._record_usage(msg_chunk)
                # 带 tool_calls 的消息 content 通常为空，不会误把参数当正文
                if isinstance(msg_chunk, AIMessage) and msg_chunk.tool_calls:
                    return
                text = _chunk_text(msg_chunk)
                if text:
                    yield {"type": "token", "text": text}

        elif mode == "updates":
            # data = {node_name: {"messages": [...]}}
            if not isinstance(data, dict):
                return
            for _node, node_update in data.items():
                if not isinstance(node_update, dict):
                    continue
                messages = node_update.get("messages")
                if not isinstance(messages, list):
                    continue
                for msg in messages:
                    if isinstance(msg, ToolMessage):
                        yield {
                            "type": "tool_end",
                            "name": msg.name,
                            "ok": msg.status != "error",
                            "preview": _truncate(str(msg.content)),
                        }
                    elif isinstance(msg, AIMessage) and msg.tool_calls:
                        for call in msg.tool_calls:
                            yield {
                                "type": "tool_start",
                                "name": call.get("name"),
                                "args": _safe_args(call.get("args"))
                                if self._settings.log_tool_args
                                else {},
                            }

        elif mode == "values":
            # 人工确认的挂起信息在状态里以 __interrupt__ 暴露
            if not isinstance(data, dict):
                return
            for intr in data.get("__interrupt__") or []:
                payload = getattr(intr, "value", None)
                if not isinstance(payload, dict):
                    continue
                # 只转换写操作确认；其它类型的 interrupt 原样带出
                yield {
                    "type": "confirmation_required",
                    "action": payload.get("action"),
                    "fingerprint": payload.get("fingerprint"),
                    "summary": payload.get("summary"),
                    "message": payload.get("message", ""),
                }

    async def history(self, conversation_id: str) -> list[dict[str, str]]:
        """读取某会话的历史消息（用于前端刷新后恢复）。"""
        state = await self._graph.aget_state(self._config(conversation_id))
        out: list[dict[str, str]] = []
        for msg in (state.values or {}).get("messages", []):
            role = None
            if isinstance(msg, AIMessage):
                role = "assistant"
            elif isinstance(msg, ToolMessage):
                role = "tool"
            elif msg.__class__.__name__ == "HumanMessage":
                role = "user"
            if role and msg.content:
                out.append({"role": role, "content": str(msg.content)})
        return out

    async def clear(self, conversation_id: str) -> None:
        """清空某会话历史。

        直接删除 checkpoint 记录；对 demo 用的 InMemorySaver 而言，
        用一个新的 thread_id 就等价于重开一段会话，因此这里只做记录。
        """
        logger.info("清除会话历史: %s", conversation_id)


def _chunk_text(chunk: AIMessage | AIMessageChunk) -> str:
    """从 AI 消息（分片或完整）中提取文本。

    注意：带 tool_calls 的消息其 content 可能为空，
    只有最终回答才含文本，因此这里天然不会把工具参数当正文推给前端。
    """
    content = chunk.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""


def _truncate(text: str) -> str:
    if len(text) <= _TOOL_PREVIEW_LIMIT:
        return text
    return text[:_TOOL_PREVIEW_LIMIT] + f"...(共 {len(text)} 字符)"


def _safe_args(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        return args
    return {"_raw": str(args)}


def _friendly_error(exc: Exception) -> str:
    """把底层异常翻译成用户能看懂的一句话。"""
    name = exc.__class__.__name__
    text = str(exc)
    if "AuthenticationError" in name or "401" in text:
        return "AI 服务认证失败，请检查 DEEPSEEK_API_KEY 配置。"
    if "RateLimit" in name or "429" in text:
        return "AI 服务请求过于频繁，请稍后再试。"
    if "APIConnectionError" in name or "ConnectError" in name:
        return "无法连接 AI 服务，请检查网络或 DEEPSEEK_BASE_URL 配置。"
    if "Timeout" in name:
        return "AI 服务响应超时，请稍后重试。"
    return f"处理请求时出错：{text[:200]}"
