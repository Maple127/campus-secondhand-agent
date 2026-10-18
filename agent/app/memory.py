"""上下文压缩。

## 为什么需要它

LangGraph 的 checkpointer 会保存**整个会话历史**，每一轮都把全部历史发给模型。
对话一长，两件事同时发生：token 成本线性上涨，模型开始"忘记"早期约束
（预算、排除条件、还没做完的事）。

## 压缩策略

按 **token 预算**触发，不按轮数。轮数没有普适值——一句 "嗯" 和一段长描述
占的上下文差十倍。

触发后：

    早期历史 ──摘要──► 一条 SystemMessage
    最近 N 条  ──────► 原样保留
    当前轮     ──────► **永远不动**（正在处理的那条消息不能被摘要）

## 一个容易踩的坑

"把最早的消息删掉"看起来等价，实际不是。如果最早那几条里写着
「预算不超过 300」「别给我推二手的」——删掉之后模型就不知道这些约束了，
后面每一句回答都可能是错的。

所以摘要提示词里**显式要求提取约束**，而不是让模型自由发挥写一段总结。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数。

    DeepSeek 的中文分词大致是 1 个汉字 ≈ 1 个 token，英文约 4 字符 ≈ 1 个 token。
    这里不追求精确（精确要真跑 tokenizer，代价大且版本相关），
    只求"量级对、方向对"——压缩阈值是个工程参数，不是计费依据。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return cjk + other // 4 + 1


def message_tokens(message: BaseMessage) -> int:
    content = message.content
    if isinstance(content, str):
        text = content
    else:
        try:
            text = json.dumps(content, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(content)
    # +4 是角色标记和格式开销的经验值
    return estimate_tokens(text) + 4


def total_tokens(messages: list[BaseMessage]) -> int:
    return sum(message_tokens(m) for m in messages)


@dataclass
class CompressionPlan:
    """压缩方案。由调用方负责写入 checkpoint（这里不碰图）。"""

    summary: SystemMessage
    keep: list[BaseMessage]
    saved_tokens: int


class Compressor:
    """把早期历史压成一条摘要。

    设计上**不直接改 state**：`plan()` 只产出方案，
    写回 checkpoint 由 AgentRunner 做。这样压缩逻辑可以脱离 LangGraph 单测。
    """

    def __init__(
        self,
        llm: Any,
        *,
        budget: int = 6000,
        keep_recent: int = 6,
        min_compress_messages: int = 8,
        max_summary_chars: int = 400,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._keep_recent = max(2, keep_recent)
        self._min_compress_messages = max(self._keep_recent + 2, min_compress_messages)
        self._max_summary_chars = max_summary_chars

    # ------------------------------------------------------------------

    def should_compress(self, messages: list[BaseMessage]) -> bool:
        return (
            len(messages) >= self._min_compress_messages and total_tokens(messages) > self._budget
        )

    def split(self, messages: list[BaseMessage]) -> tuple[list[BaseMessage], list[BaseMessage]]:
        """切出「可压缩的早期历史」和「必须原样保留的近期消息」。

        两个不得越过的边界：
          1. 最近 keep_recent 条不动
          2. **当前轮**不动 —— 从最后一条 HumanMessage 开始往后全部保留，
             否则正在处理的那条用户消息会被摘要掉，模型就问了个空气
        """
        last_human = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].type == "human":
                last_human = i
                break

        keep_from = max(len(messages) - self._keep_recent, last_human)
        keep_from = max(0, keep_from)
        return messages[:keep_from], messages[keep_from:]

    async def plan(self, messages: list[BaseMessage]) -> CompressionPlan | None:
        if not self.should_compress(messages):
            return None

        old, keep = self.split(messages)
        if len(old) < 2:
            return None

        summary_text = await self._summarize(old)
        if not summary_text:
            return None

        before = total_tokens(messages)
        after = estimate_tokens(summary_text) + total_tokens(keep) + 4
        saved = max(0, before - after)

        logger.info(
            "[压缩] %d 条历史 → 1 条摘要（%d 字），保留近期 %d 条，估算省 %d token",
            len(old),
            len(summary_text),
            len(keep),
            saved,
        )

        summary = SystemMessage(
            content=(
                "以下是本次对话的早期历史摘要（原始消息已压缩，细节可能缺失；"
                "如果摘要与最近对话冲突，以最近对话为准）：\n\n" + summary_text
            )
        )
        return CompressionPlan(summary=summary, keep=keep, saved_tokens=saved)

    async def _summarize(self, old: list[BaseMessage]) -> str:
        transcript = "\n".join(
            f"[{m.type}] {m.content if isinstance(m.content, str) else json.dumps(m.content, ensure_ascii=False)}"
            for m in old
        )
        prompt = (
            "把下面这段多轮对话压缩成摘要，用于后续对话的上下文。\n"
            f"要求不超过 {self._max_summary_chars} 字，并且**必须保留**以下三类信息：\n"
            "1. 用户的目标，以及已经明确过的约束（预算上限、必须满足的条件、明确排除的选项）\n"
            "2. 已经完成的操作和结果（尤其是发布、下单、下架这类写操作）\n"
            "3. 还没完成、用户仍在等待的事\n"
            "可以丢弃：工具返回的原始数据、重复寒暄、中间推理过程。\n\n"
            "对话记录：\n" + transcript
        )
        try:
            result = await self._llm.ainvoke(prompt)
        except Exception:
            logger.warning("[压缩] 摘要生成失败，本轮不压缩", exc_info=True)
            return ""
        content = getattr(result, "content", "")
        return content if isinstance(content, str) else str(content)
