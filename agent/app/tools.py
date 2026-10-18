"""Agent 工具层。

设计原则：
  1. **不含业务规则**：所有校验在后端。工具只负责把模型意图翻译成 API 调用。
  2. **返回结构化文本**：模型需要 productId 才能做后续调用，因此结果里必须带 id。
  3. **错误变成可读文本**：工具不抛异常给模型，而是返回「发生了什么 + 该不该重试」。
  4. **身份用 ContextVar 传递**：工具函数由模型按名字调用，无法额外传 token，
     因此每次请求开始时绑定当前用户的能力令牌。

本期实现只读工具（搜索 / 详情 / 比价 / 分类）。
写操作（发布、下单）将在下一阶段配合人工确认（LangGraph interrupt）加入。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import tool
from langgraph.errors import GraphBubbleUp

from app.backend import BackendClient, BackendError
from app.config import get_settings
from app.guardrails import fence_untrusted
from app.metrics import METRICS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 请求级上下文：当前用户的能力令牌 + 后端客户端
# ---------------------------------------------------------------------------

_actor_token: ContextVar[str | None] = ContextVar("actor_token", default=None)
_backend: ContextVar[BackendClient | None] = ContextVar("backend_client", default=None)


@dataclass
class TurnSearchState:
    """单轮对话里的搜索计数，用来阻止"换词换到天荒地老"。

    实测：让 agent 搜一个平台上根本没有的东西（「吉他」），它连试了
    4 个词（吉他 / 吉他 / 民谣吉他 / 尤克里里），每次都打后端、都空手而归。
    对一个**缺货**的查询，第一次没有结果就已经说明问题了 ——
    后面的重试除了烧 token 没有任何意义。

    但重试不能一刀切禁掉：用户的说法可能真的和商品标题对不上
    （「耳机」→《AirPods Pro 2代》）。所以规则是：
      · 允许换 1 次说法（总共 2 次空结果）
      · 第 3 次直接拦下，不再请求后端
    """

    calls: int = 0
    empty_streak: int = 0
    empty_keywords: list[str] = field(default_factory=list)

    def reset_streak(self) -> None:
        self.empty_streak = 0


# 每轮请求创建一次（tool_context 内），请求结束自动丢弃
_turn_state: ContextVar[TurnSearchState | None] = ContextVar("turn_state", default=None)

# 连续空搜索达到这个次数后，不再放行新的搜索
MAX_EMPTY_SEARCHES = 2


@contextmanager
def tool_context(actor_token: str, backend: BackendClient) -> Iterator[None]:
    """在请求处理期间绑定身份与客户端。

    使用 ContextVar 而非全局变量：并发请求之间互不干扰。
    """
    token_handle = _actor_token.set(actor_token)
    backend_handle = _backend.set(backend)
    state_handle = _turn_state.set(TurnSearchState())
    try:
        yield
    finally:
        _actor_token.reset(token_handle)
        _backend.reset(backend_handle)
        _turn_state.reset(state_handle)


def _require_context() -> tuple[str, BackendClient]:
    token = _actor_token.get()
    backend = _backend.get()
    if not token or backend is None:
        # 这只会在编程错误时发生（忘记包 tool_context），不是用户错误
        raise RuntimeError("工具上下文未初始化：请在请求处理中使用 tool_context(...) 包裹")
    return token, backend


# ---------------------------------------------------------------------------
# 结果格式化
# ---------------------------------------------------------------------------


def _dumps(payload: Any) -> str:
    """紧凑 JSON，减少 token 消耗；ensure_ascii=False 保留中文可读性。"""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _handle_error(exc: Exception) -> str:
    """把后端错误转成给模型看的文本。

    注意：这里**必须留下日志**。此前该函数静默吞掉了内部异常，
    表现为"工具什么都没做、模型却收到一段含糊文本"，排查成本极高。
    """
    if isinstance(exc, BackendError):
        return exc.to_tool_message()
    # 非后端错误属于代码缺陷（如上下文未初始化），必须记录完整堆栈
    logger.exception("工具执行发生内部错误: %s", type(exc).__name__)
    return f"工具执行失败（{type(exc).__name__}）：{exc}"


#: 必须原样向上抛出的"控制流"异常 —— 它们不是错误
_PASSTHROUGH_EXCEPTIONS = (
    GraphBubbleUp,  # interrupt / 子图冒泡（GraphInterrupt 的基类）
)


async def run_tool(action):
    """统一的工具执行包装。

    **这里有个很容易踩的坑**：写工具通过 `interrupt()` 挂起图，
    而 `interrupt()` 是**抛异常**实现的（GraphInterrupt）。

    如果工具内部写 `except Exception` 去兜底错误处理，
    这个异常会被一起吞掉 —— 表现为"图不挂起、工具像没执行一样返回一段文本"，
    而且极难排查。

    因此所有工具的错误处理都必须走这个包装：
    控制流异常原样上抛，业务异常转成给模型看的文本。
    """
    try:
        return await action()
    except _PASSTHROUGH_EXCEPTIONS:
        raise
    except Exception as exc:  # noqa: BLE001
        return _handle_error(exc)


def _product_brief(p: dict[str, Any]) -> dict[str, Any]:
    """裁剪商品字段：只保留模型决策所需的信息。

    刻意不包含卖家手机号 —— 隐私边界，沟通应走站内消息。
    """
    return {
        "productId": p.get("id"),
        "name": p.get("name"),
        "price": p.get("price"),
        "category": p.get("category"),
        # 品类词：让模型知道「这是耳机」而不只是「数码电子」。
        # 用户搜「耳机」命中 AirPods 时，模型能解释为什么是它。
        "productType": p.get("productType"),
        "condition": p.get("conditionLevel"),
        "location": p.get("location"),
        "status": p.get("statusLabel"),
        "available": p.get("available"),
    }


# ---------------------------------------------------------------------------
# 只读工具
# ---------------------------------------------------------------------------


@tool
async def search_products(
    query: str | None = None,
    category: str | None = None,
    max_price: float | None = None,
    min_price: float | None = None,
    size: int = 10,
) -> str:
    """搜索校园二手商品。用于用户想「找东西」「看看有什么」「有没有便宜的 XX」。

    只会返回**在售**商品，已售出/待审核/已下架的商品不会出现。

    【重要】query 与 category 的用法完全不同，不要混：

    - 想说「要哪一类」→ 用 `category`（精确分类筛选）
    - 想说「名字/描述里有某个词」→ 用 `query`（模糊匹配名称、描述、地点）
    - **不要把分类名当 query 传**。`query="运动器材"` 会去找名称/描述里
      真含"运动器材"四个字的商品，结果必然是 0 条 —— 因为越野自行车不会
      在描述里写"运动器材"。只要用 `category="体育器材"` 就够了。
    - 两者可以同时用，但仅当关键词确实会出现在商品文案里时
      （例如 category="数码电子" + query="键盘"）。

    Args:
        query: 关键词，模糊匹配商品名称 / 描述 / 交易地点。
               传**具体名词**（品牌、型号、品类名），例如 "iPad"、"机械键盘"、"高等数学"。
               **不要传分类名**。
        category: 分类名称，需使用 list_categories 返回的准确名称，例如 "数码电子"。
                  这是"筛选某一类"的正确方式。
        max_price: 价格上限（元）。用户说"500 以内"就传 500。
        min_price: 价格下限（元）。用户说"300 到 800"就传 min_price=300, max_price=800。
        size: 返回条数，默认 10，最多 50。
    """
    token, backend = _require_context()

    # ---- 本轮重试闸门：连续空搜索达到上限后，不再请求后端 ----
    # 目的不是限制能力，而是避免"缺货的查询被反复重试"这种纯浪费：
    # 实测搜「吉他」时模型会连试 4 个同义词，每次一个后端请求 + 一轮模型往返。
    # 开关 ENABLE_EMPTY_SEARCH_GATE 供消融评测关闭它，测这个闸门到底值多少。
    state = _turn_state.get()
    _settings = get_settings()
    gate_on = _settings.enable_empty_search_gate
    threshold = max(1, _settings.max_empty_searches)
    if gate_on and state is not None and state.empty_streak >= threshold:
        METRICS.empty_search_blocks += 1
        logger.info(
            "search_products: 本轮已有 %d 次空结果，拒绝继续搜索 query=%r",
            state.empty_streak,
            query,
        )
        return _dumps(
            {
                "found": 0,
                "stop": True,
                "already_tried": state.empty_keywords,
                "hint": (
                    f"本轮已经连续 {state.empty_streak} 次搜索没有结果"
                    f"（试过：{'、'.join(state.empty_keywords)}）。"
                    "**不要再换词搜索了** —— 再换也是浪费。"
                    "请直接告诉用户：平台上暂时没有这件商品。"
                    "可以建议他换个类目看看，或者自己发布一件求购/闲置。"
                ),
            }
        )

    # 防御：模型很容易把分类名塞进 query（"300-800 的运动器材" 这种表述尤其容易），
    # 而后端是 名称/描述/地点 LIKE %query% AND category = :category，
    # 于是变成"名称里必须有『运动器材』四个字" —— 必然 0 条。
    # 这里检测到 query 就是分类名时直接丢弃，避免模型因为措辞而搜空。
    effective_query = query
    if query and category and query.strip() == category.strip():
        logger.info("search_products: query 与 category 相同(%r)，已忽略 query 仅按分类筛选", query)
        effective_query = None

    if state is not None:
        state.calls += 1

    try:
        data = await backend.search_products(
            token,
            query=effective_query,
            category=category,
            min_price=min_price,
            max_price=max_price,
            size=max(1, min(size, 50)),
        )
    except Exception as exc:  # noqa: BLE001 - 统一转成给模型的文本
        return _handle_error(exc)

    items = [_product_brief(p) for p in data.get("items", [])]

    # 有结果就把"连续空"清零：两段不相干的查询之间不互相牵连
    if items and state is not None:
        state.reset_streak()

    if not items:
        # "没结果"有两种完全不同的原因，必须区别对待 ——
        # 这一点是评测逼出来的教训：给了笼统的"换词重试"提示后，
        # 搜索类任务成功率上升，但**条件筛选类反而下降** ——
        # 模型为了让结果非空，把用户给的价格上限也一起放宽了，
        # 于是"50 块以下的自行车"被回答成"捷安特 ¥350"。
        # 放宽条件去凑结果，比直接说"没有"更糟。
        has_price = min_price is not None or max_price is not None

        # 记账：这次空手而归
        remaining = 0
        if state is not None:
            state.empty_streak += 1
            state.empty_keywords.append(str(effective_query or category or "?"))
            remaining = max(0, MAX_EMPTY_SEARCHES - state.empty_streak)

        if has_price:
            hint = (
                "没有匹配结果。**价格/分类条件是用户的硬性要求，不许放宽**。"
                "可以换关键词再试（换成同义词或更具体的词），"
                "但绝不要为了凑出结果而扩大价格区间或忽略分类。"
                "如果换词后仍为空，就如实告诉用户这个价位/分类下暂时没有，"
                "并可以建议他调整预算。"
            )
        elif remaining <= 0:
            hint = (
                "没有匹配结果，而且这已经是本轮最后一次尝试。"
                "**停止换词，直接回答用户**：平台上暂时没有这件商品。"
                "可以建议他换个类目看看，或者自己发布一件闲置。"
            )
        else:
            hint = (
                "没有匹配结果。**最多再换 1 种说法试一次** —— "
                "搜索是关键词匹配、没有同义词能力，用户的说法常与商品标题对不上"
                "（用户说「耳机」，商品叫「AirPods Pro 2代」）。"
                "换法：换成更口语的同义词，或拆掉宽泛词只留核心名词。"
                "如果这一次还是空，就**如实告诉用户暂时没有**，不要再试了。"
            )
        return _dumps(
            {
                "found": 0,
                "hint": hint,
                # 让模型看得见自己还剩几次机会，比只在提示词里写规则更有效
                "retries_left": remaining,
            }
        )
    return _dumps(
        {
            "found": len(items),
            "total": data.get("totalElements"),
            "items": items,
        }
    )


@tool
async def negotiation_advice(product_id: int) -> str:
    """给出"这件值不值、该出多少钱、怎么说"的议价建议。

    当用户问「这个贵不贵」「能砍到多少」「帮我砍价」「要不要买」时使用。

    **所有金额都是后端算出来的，你只负责转述和措辞，绝对不要自己算或改。**
    返回里同时带了一段现成话术（script），可以直接给用户用。

    Args:
        product_id: 商品 ID，来自 search_products 返回的 productId。
    """
    token, backend = _require_context()
    try:
        data = await backend.negotiation_advice(token, product_id)
    except Exception as exc:  # noqa: BLE001
        return _handle_error(exc)

    if data.get("verdict") == "UNKNOWN" or data.get("suggestedTarget") is None:
        return _dumps(
            {
                "productId": product_id,
                "productName": data.get("productName"),
                "verdict": "UNKNOWN",
                "reasoning": data.get("reasoning"),
                "hint": "同类样本太少，给不出可靠价位。如实告诉用户这一点，"
                "不要编一个数字；可以建议他看看商品成色和详情。",
            }
        )

    return _dumps(
        {
            "productId": product_id,
            "productName": data.get("productName"),
            "askingPrice": data.get("askingPrice"),
            "marketLow": data.get("marketLow"),
            "marketMedian": data.get("marketMedian"),
            "marketHigh": data.get("marketHigh"),
            "sampleSize": data.get("sampleSize"),
            "confidence": data.get("confidence"),
            "verdict": data.get("verdict"),
            "suggestedOpen": data.get("suggestedOpen"),
            "suggestedTarget": data.get("suggestedTarget"),
            "walkAway": data.get("walkAway"),
            "cheaperCount": data.get("cheaperCount"),
            "daysListed": data.get("daysListed"),
            "reasoning": data.get("reasoning"),
            "script": data.get("script"),
            "hint": "把 verdict 翻译成人话（合理/偏高/偏贵），给出三档价，"
            "再附上 script 作为可直接发送的话术。"
            "verdict 是 FAIR 时要明确劝用户不必砍价。",
        }
    )


@tool
async def get_product(product_id: int) -> str:
    """查看某个商品的详细信息（含完整描述）。

    当用户想了解某个具体商品的细节、或者你已经有 productId 需要确认状态时使用。

    Args:
        product_id: 商品 ID，来自 search_products 返回的 productId。
    """
    token, backend = _require_context()
    try:
        p = await backend.get_product(token, product_id)
    except Exception as exc:  # noqa: BLE001
        return _handle_error(exc)

    detail = _product_brief(p)
    # 描述是卖家可控的：围栏 + 标记，模型看到边界就不会把它当指令
    detail["description"] = fence_untrusted(p.get("description"))
    detail["_untrusted_fields"] = ["name", "description"]
    detail["originalPrice"] = p.get("originalPrice")
    detail["createdAt"] = p.get("createTime")
    return _dumps(detail)


@tool
async def compare_price(product_id: int) -> str:
    """对某个商品做同类比价，判断定价是否合理。

    用户问「这个贵吗」「值不值」「多少钱合适」时使用。

    返回的 median / p25 / p75 / suggestedLow / suggestedHigh 全部由后端统计得出。
    **必须原样引用这些数字，不要自行估算或编造价格区间。**

    Args:
        product_id: 商品 ID。
    """
    token, backend = _require_context()
    try:
        c = await backend.compare_price(token, product_id)
    except Exception as exc:  # noqa: BLE001
        return _handle_error(exc)

    return _dumps(
        {
            "productId": product_id,
            "category": c.get("categoryName"),
            "condition": c.get("conditionLevel"),
            "sampleSize": c.get("sampleSize"),
            "min": c.get("min"),
            "p25": c.get("p25"),
            "median": c.get("median"),
            "p75": c.get("p75"),
            "max": c.get("max"),
            "suggestedLow": c.get("suggestedLow"),
            "suggestedHigh": c.get("suggestedHigh"),
            "verdict": c.get("verdict"),
            "explanation": c.get("explanation"),
            "samples": c.get("samples"),
        }
    )


@tool
async def list_categories() -> str:
    """列出平台所有商品分类。

    在需要按分类筛选、或准备发布商品需要选分类时先调用它，
    以获得**准确的分类名称**（传错分类名会导致筛选不到结果）。
    """
    token, backend = _require_context()
    try:
        cats = await backend.list_categories(token)
    except Exception as exc:  # noqa: BLE001
        return _handle_error(exc)
    return _dumps([{"name": c.get("name"), "description": c.get("description")} for c in cats])


@tool
async def list_my_products() -> str:
    """查看当前用户自己发布的商品（含待审核、已下架、已售出）。

    用户问「我挂的东西」「我发的闲置卖出去没」时使用。
    """
    token, backend = _require_context()
    try:
        products = await backend.list_my_products(token)
    except Exception as exc:  # noqa: BLE001
        return _handle_error(exc)

    return _dumps(
        [
            {
                "productId": p.get("id"),
                "name": p.get("name"),
                "price": p.get("price"),
                "status": p.get("statusLabel"),
                "rejectReason": p.get("rejectReason"),
            }
            for p in products
        ]
    )


@tool
async def list_my_orders(role: str = "buyer") -> str:
    """查看当前用户的订单。

    用户问「我买的东西」「我的订单」「有人买我的东西吗」时使用。

    Args:
        role: "buyer" 查看我买的，"seller" 查看我卖出的。
    """
    token, backend = _require_context()
    try:
        orders = await backend.list_my_orders(token, role=role)
    except Exception as exc:  # noqa: BLE001
        return _handle_error(exc)

    return _dumps(
        [
            {
                "orderNo": o.get("orderNo"),
                "productName": o.get("productName"),
                "price": o.get("price"),
                "status": o.get("statusLabel"),
                "createdAt": o.get("createTime"),
            }
            for o in orders
        ]
    )


#: 本期向模型开放的工具集合（全部只读）
READ_ONLY_TOOLS = [
    search_products,
    get_product,
    compare_price,
    negotiation_advice,
    list_categories,
    list_my_products,
    list_my_orders,
]
