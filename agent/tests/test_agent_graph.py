"""Agent 图测试：用 Fake 模型驱动整张图，不打真实 LLM。

这样做的价值：
  - 不需要 API Key、不花钱、毫秒级完成，可进 CI
  - 能精确验证「事件协议」是否稳定（前端依赖它）
  - 能验证工具确实被调用、参数确实传对了
"""

from __future__ import annotations

import json

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.config import Settings
from app.graph import AgentRunner
from app.idempotency import IdempotentExecutor


class RecordingBackend:
    """记录调用的假后端。"""

    def __init__(self, search_result=None, compare_result=None, error=None):
        self.search_result = search_result or {"items": [], "totalElements": 0}
        self.compare_result = compare_result
        self.error = error
        self.calls = []

    async def search_products(self, token, **kwargs):
        self.calls.append(("search_products", kwargs))
        if self.error:
            raise self.error
        return self.search_result

    async def get_product(self, token, product_id):
        self.calls.append(("get_product", {"product_id": product_id}))
        return {"id": product_id, "name": "x", "price": 1, "available": True, "statusLabel": "在售"}

    async def compare_price(self, token, product_id, sample_limit=50):
        self.calls.append(("compare_price", {"product_id": product_id}))
        return self.compare_result or {}

    async def list_categories(self, token):
        self.calls.append(("list_categories", {}))
        return [{"id": 1, "name": "数码电子", "description": ""}]

    async def list_my_products(self, token):
        self.calls.append(("list_my_products", {}))
        return []

    async def list_my_orders(self, token, role="buyer"):
        self.calls.append(("list_my_orders", {"role": role}))
        return []


class ScriptedModel(FakeMessagesListChatModel):
    """脚本化的假模型。

    FakeMessagesListChatModel 没有实现 bind_tools，而 LangChain v1 的 agent
    在构建图时会调用 model.bind_tools(...)，因此必须补上：
    返回自身即可（假模型已经是脚本化的，无需真的绑定工具）。
    """

    def bind_tools(self, tools, **kwargs):
        return self


def make_settings(**overrides) -> Settings:
    base = {
        "DEEPSEEK_API_KEY": "sk-fake-for-test",
        "AGENT_SERVICE_TOKEN": "test-token",
        "MAX_AGENT_STEPS": 6,
    }
    base.update(overrides)
    return Settings(**base)


def make_executor(tmp_path) -> IdempotentExecutor:
    """每个测试用独立的幂等账本，避免相互影响。"""
    return IdempotentExecutor(tmp_path / "ledger.db")


def make_runner(messages: list[AIMessage], tmp_path=None) -> AgentRunner:
    """用脚本化的假模型构建 runner：按顺序返回给定的 AIMessage。"""
    import tempfile
    from pathlib import Path

    base = Path(tmp_path) if tmp_path is not None else Path(tempfile.mkdtemp())
    return AgentRunner(
        make_settings(),
        InMemorySaver(),
        model=ScriptedModel(responses=messages),
        executor=IdempotentExecutor(base / "ledger.db"),
    )


async def collect(runner, backend, message="测试", conv="conv-test"):
    events = []
    async for ev in runner.stream(
        message, conversation_id=conv, actor_token="actor-token", backend=backend
    ):
        events.append(ev)
    return events


async def test_plain_answer_without_tools():
    """模型直接回答时，事件流应只有 token + done。"""
    runner = make_runner([AIMessage(content="你好，我是校园二手助手。")])
    events = await collect(runner, RecordingBackend())

    types = [e["type"] for e in events]
    assert "done" in types
    assert "error" not in types
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "校园二手助手" in text


async def test_tool_call_flow_emits_start_and_end():
    """工具调用应产生 tool_start / tool_end 事件，供前端展示进度。"""
    tool_call = AIMessage(
        content="",
        tool_calls=[{"name": "search_products", "args": {"query": "ipad"}, "id": "call_1"}],
    )
    final = AIMessage(content="找到 0 件商品。")
    runner = make_runner([tool_call, final])
    backend = RecordingBackend()

    events = await collect(runner, backend, message="有没有 ipad")

    starts = [e for e in events if e["type"] == "tool_start"]
    ends = [e for e in events if e["type"] == "tool_end"]

    assert len(starts) == 1
    assert starts[0]["name"] == "search_products"
    assert starts[0]["args"] == {"query": "ipad"}
    assert len(ends) == 1
    assert ends[0]["name"] == "search_products"
    assert ends[0]["ok"] is True

    # 工具真的被调用了，且参数传对了
    assert backend.calls[0][0] == "search_products"
    assert backend.calls[0][1]["query"] == "ipad"


async def test_tool_error_does_not_break_stream():
    """后端报错时，图不能崩，仍要产出最终回答。"""
    tool_call = AIMessage(
        content="",
        tool_calls=[{"name": "search_products", "args": {"query": "x"}, "id": "c1"}],
    )
    final = AIMessage(content="查询失败，请稍后重试。")
    runner = make_runner([tool_call, final])

    from app.backend import BackendError

    backend = RecordingBackend(error=BackendError(500, 500, "后端炸了"))
    events = await collect(runner, backend)

    assert "error" not in [e["type"] for e in events]
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "请稍后重试" in text


async def test_done_event_reports_tool_step_count():
    """done 事件要带步数，便于观测 agent 是否陷入循环。"""
    tool_call = AIMessage(
        content="",
        tool_calls=[{"name": "list_categories", "args": {}, "id": "c1"}],
    )
    final = AIMessage(content="分类有：数码电子。")
    runner = make_runner([tool_call, final])

    events = await collect(runner, RecordingBackend())
    done = next(e for e in events if e["type"] == "done")
    assert done["steps"] == 1


async def test_history_is_persisted_per_conversation():
    """多轮记忆按 conversationId 隔离，且能读回历史。"""
    runner = make_runner(
        [
            AIMessage(content="第一轮回答。"),
            AIMessage(content="第二轮回答。"),
        ]
    )

    await collect(runner, RecordingBackend(), message="第一轮", conv="conv-A")
    await collect(runner, RecordingBackend(), message="第二轮", conv="conv-A")

    history = await runner.history("conv-A")
    contents = [m["content"] for m in history]
    assert "第一轮" in contents
    assert "第一轮回答。" in contents

    # 另一个会话不应看到 conv-A 的内容
    other = await runner.history("conv-B")
    assert other == []


async def test_events_are_json_serializable():
    """事件最终要 json.dumps 进 SSE，必须可序列化。"""
    tool_call = AIMessage(
        content="",
        tool_calls=[{"name": "list_categories", "args": {}, "id": "c1"}],
    )
    runner = make_runner([tool_call, AIMessage(content="完成")])
    events = await collect(runner, RecordingBackend())

    for ev in events:
        json.dumps(ev, ensure_ascii=False)  # 不抛异常即通过


async def test_history_isolated_between_tokens_same_conversation():
    """同一会话内不同请求共享历史（这是多轮对话的基础）。"""
    runner = make_runner(
        [
            AIMessage(content="记住了，你叫小明。"),
            AIMessage(content="你叫小明。"),
        ]
    )
    backend = RecordingBackend()

    await collect(runner, backend, message="我叫小明", conv="conv-M")
    await collect(runner, backend, message="我叫什么", conv="conv-M")

    history = await runner.history("conv-M")
    user_msgs = [m["content"] for m in history if m["role"] == "user"]
    assert user_msgs == ["我叫小明", "我叫什么"]


@pytest.mark.parametrize("failing_message", ["rate limit 429", "connection error"])
async def test_llm_failure_yields_error_event(failing_message, tmp_path):
    """模型层异常要变成 error 事件，而不是让 SSE 静默中断。"""

    class BoomModel(ScriptedModel):
        def bind_tools(self, tools, **kwargs):
            return self

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            raise RuntimeError(failing_message)

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise RuntimeError(failing_message)

    runner = AgentRunner(
        make_settings(),
        InMemorySaver(),
        model=BoomModel(responses=[AIMessage(content="x")]),
        executor=make_executor(tmp_path),
    )
    events = await collect(runner, RecordingBackend())

    types = [e["type"] for e in events]
    assert "error" in types
