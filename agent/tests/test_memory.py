"""上下文压缩测试。

最需要盯住的两件事：

  1. **不能把当前轮压缩掉** —— 用户这一轮刚问的话必须在，否则模型在自问自答
  2. **摘要要保住约束** —— 提示词里必须显式要求提取预算/排除条件，
     否则"只删旧消息"会把约束一起删掉（这是最常见的坑）
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.memory import Compressor, estimate_tokens, total_tokens


class FakeLLM:
    """记录调用参数，返回固定摘要。"""

    def __init__(self, reply: str = "用户想买便宜耳机；预算 300 以内；已排除二手。") -> None:
        self.reply = reply
        self.prompts: list[str] = []

    async def ainvoke(self, prompt: str):
        self.prompts.append(prompt)

        class _R:
            content = self.reply

        return _R()


class BrokenLLM:
    async def ainvoke(self, prompt: str):
        raise RuntimeError("模型挂了")


def make_history(
    turns: int, filler: str = "这里是一段比较长的历史消息内容用来撑大 token 数。"
) -> list:
    msgs: list = [SystemMessage(content="你是校园二手交易助手")]
    for i in range(turns):
        msgs.append(HumanMessage(content=f"第{i}轮问题 " + filler * 3))
        msgs.append(AIMessage(content=f"第{i}轮回答 " + filler * 3))
        msgs.append(ToolMessage(content=f"第{i}轮工具结果 " + filler * 2, tool_call_id=f"c{i}"))
    return msgs


# ---------------------------------------------------------------------------


def test_estimate_tokens_prefers_cjk():
    """中文按字算，英文按 4 字符算 —— 量级要对。"""
    zh = estimate_tokens("这是一个中文句子")
    en = estimate_tokens("this is an english sentence")
    assert zh >= 7
    assert en < zh, "同样长度下英文的 token 应该少于中文"


def test_should_compress_respects_budget():
    small = make_history(1)
    big = make_history(6)
    c = Compressor(FakeLLM(), budget=1000, keep_recent=4, min_compress_messages=8)

    assert total_tokens(big) > 1000
    # 同一个压缩器：大历史触发，小历史不触发
    assert c.should_compress(big)
    assert not c.should_compress(small)


def test_split_never_cuts_current_turn():
    """当前轮（最后一条用户消息）及其之后的工具/回答都必须保留。"""
    msgs = make_history(5)
    msgs.append(HumanMessage(content="我刚问的这句话必须保留"))
    c = Compressor(FakeLLM(), budget=100, keep_recent=2, min_compress_messages=4)

    old, keep = c.split(msgs)

    assert old, "应该切出可压缩的早期历史"
    assert keep[-1].content == "我刚问的这句话必须保留"
    assert all("我刚问的这句话" not in str(m.content) for m in old)


async def test_plan_produces_summary_and_saves_tokens():
    llm = FakeLLM()
    msgs = make_history(8)
    c = Compressor(llm, budget=1000, keep_recent=4, min_compress_messages=8)

    plan = await c.plan(msgs)

    assert plan is not None
    assert isinstance(plan.summary, SystemMessage)
    assert "摘要" in plan.summary.content
    assert plan.saved_tokens > 0
    assert len(plan.keep) <= 4 or plan.keep[-1].type == "human"
    assert len(llm.prompts) == 1


async def test_summary_prompt_asks_to_preserve_constraints():
    """这是防"删掉约束"的关键：提示词必须点名要保留约束。"""
    llm = FakeLLM()
    c = Compressor(llm, budget=1000, keep_recent=4, min_compress_messages=8)
    await c.plan(make_history(8))

    prompt = llm.prompts[0]
    assert "约束" in prompt
    assert "预算" in prompt
    assert "排除" in prompt
    assert "还没完成" in prompt


async def test_compression_failure_returns_none_instead_of_raising():
    """模型挂了不能拖垮对话，只是这一轮不压缩。"""
    c = Compressor(BrokenLLM(), budget=500, keep_recent=4, min_compress_messages=8)
    plan = await c.plan(make_history(8))
    assert plan is None


async def test_short_history_untouched():
    c = Compressor(FakeLLM(), budget=6000, keep_recent=6, min_compress_messages=8)
    assert await c.plan(make_history(1)) is None
