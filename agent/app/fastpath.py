"""FAST 路径：一次结构化检索 + 一次模型调用。

## 它省掉了什么

走 agent 时，一次"100 以内有什么耳机"要经历：

    模型决定调哪个工具  →  工具执行  →  模型读结果写回答
    ↑ 一次完整 LLM 往返          ↑ 又一次

FAST 把第一步换成**规则解析**（纯函数，零成本），只剩第二步的模型调用。
所以省下的其实是「决定调什么工具」这一轮往返。

## 它不做什么（重要）

- **不做多步**：一次检索答不上来就返回 None，交回 agent
- **不处理空结果**：搜不到也返回 None —— 零结果的替代推荐那套逻辑在 agent 侧，
  在这里重写一遍等于两处维护
- **不碰写操作**：写操作有确认链路，只在 agent 里

一句话：**FAST 只负责"我知道要查什么，且查到了"这一种情况。**
其余全部退回 agent。宁可慢一点，也不要为了走快路径而答错。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.routing import extract_keyword, extract_price_range

logger = logging.getLogger(__name__)

#: 快路径最多返回几件。再多模型也说不清，用户也不会看。
_MAX_ITEMS = 5

_SYSTEM = """你是一个校园二手交易平台的助手。用户提了一个简单的检索需求，
系统已经替他查好了结果。你的任务：用两三句话把结果说清楚。

规则：
1. 只引用给到你的商品，不要新增、不要猜价格。
2. 每个提到的商品都带上 productId（写成 productId 123 的形式）。
3. 不要输出卖家的手机号。
4. 如果结果为空，直接说没找到，并建议换个说法。
5. 语气简洁友好，用中文。"""
_USER = """用户的问题：{message}

检索条件：关键词「{keyword}」{price_part}
共找到 {total} 件（下面最多列 {shown} 件）：
{items}
"""


@dataclass
class FastResult:
    text: str
    keyword: str
    total: int
    usage: dict[str, int]


def _format_items(items: list[dict[str, Any]]) -> str:
    lines = []
    for p in items[:_MAX_ITEMS]:
        lines.append(
            "- productId {id}｜{name}｜¥{price}｜{cond}｜{loc}".format(
                id=p.get("id"),
                name=p.get("name"),
                price=p.get("price"),
                cond=p.get("conditionLevel") or "未标成色",
                loc=p.get("location") or "未标地点",
            )
        )
    return "\n".join(lines) if lines else "（无）"


async def try_fast_answer(
    llm: Any,
    *,
    message: str,
    actor_token: str,
    backend: Any,
) -> FastResult | None:
    """尝试走快路径。答不了就返回 None（调用方退回 agent）。"""
    keyword = extract_keyword(message)
    if not keyword:
        return None

    min_price, max_price = extract_price_range(message)

    try:
        data = await backend.search_products(
            actor_token,
            query=keyword,
            min_price=min_price,
            max_price=max_price,
            size=_MAX_ITEMS,
        )
    except Exception:
        logger.info("快路径检索失败，退回 agent：keyword=%r", keyword, exc_info=True)
        return None

    items = list(data.get("items") or [])
    total = int(data.get("totalElements") or len(items))
    if not items:
        # 空结果交给 agent：零结果的替代推荐与话术都在那边
        return None

    price_part = ""
    if min_price is not None or max_price is not None:
        price_part = f"，价格 {min_price or '不限'}~{max_price or '不限'}"

    prompt = _USER.format(
        message=message,
        keyword=keyword,
        price_part=price_part,
        total=total,
        shown=min(len(items), _MAX_ITEMS),
        items=_format_items(items),
    )

    try:
        response = await llm.ainvoke(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ]
        )
    except Exception:
        logger.info("快路径生成失败，退回 agent", exc_info=True)
        return None

    text = getattr(response, "content", "")
    if not isinstance(text, str) or not text.strip():
        return None

    usage_meta = getattr(response, "usage_metadata", None) or {}
    usage = {
        "input": int(usage_meta.get("input_tokens") or 0),
        "output": int(usage_meta.get("output_tokens") or 0),
    }
    return FastResult(text=text.strip(), keyword=keyword, total=total, usage=usage)


__all__ = ["FastResult", "try_fast_answer"]
