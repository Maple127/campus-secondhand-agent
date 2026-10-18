"""工具层测试。

用 FakeBackend 替代真实 HTTP，验证：
  1. 工具返回里必须带 productId（否则模型无法做后续调用）
  2. 隐私字段（卖家手机号）不能被带出去
  3. 后端错误变成文本而不是异常——模型才能读懂并如实告知用户
  4. 上下文未绑定时报错清晰（属于编程错误，应当尽早暴露）
"""

from __future__ import annotations

import json

import pytest

from app.backend import BackendError
from app.tools import (
    compare_price,
    get_product,
    list_categories,
    list_my_orders,
    search_products,
    tool_context,
)

CONV_TOKEN = "actor-token-abc"


class FakeBackend:
    """记录调用并返回预设结果。"""

    def __init__(self, **results):
        self.results = results
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        result = self.results.get(name)
        if isinstance(result, Exception):
            raise result
        return result

    async def search_products(self, token, **kwargs):
        return self._record("search_products", token, **kwargs)

    async def get_product(self, token, product_id):
        return self._record("get_product", token, product_id)

    async def compare_price(self, token, product_id, sample_limit=50):
        return self._record("compare_price", token, product_id)

    async def negotiation_advice(self, token, product_id):
        return self._record("negotiation_advice", token, product_id)

    async def list_categories(self, token):
        return self._record("list_categories", token)

    async def list_my_products(self, token):
        return self._record("list_my_products", token)

    async def list_my_orders(self, token, role="buyer"):
        return self._record("list_my_orders", token, role)


SAMPLE_PRODUCT = {
    "id": 6,
    "name": "iPad Air 4 64G WiFi版",
    "price": 2800.00,
    "category": "数码电子",
    "conditionLevel": "9成新",
    "location": "西区宿舍",
    "statusLabel": "在售",
    "available": True,
    "description": "使用一年，无划痕带笔带壳",
    "sellerPhone": "15012345678",  # 必须被过滤掉
    "sellerName": "user06",
}


async def test_search_returns_product_ids():
    """模型必须拿到 productId 才能继续查详情/比价。"""
    backend = FakeBackend(
        search_products={
            "items": [SAMPLE_PRODUCT],
            "totalElements": 1,
        }
    )
    with tool_context(CONV_TOKEN, backend):
        raw = await search_products.ainvoke({"query": "ipad"})

    payload = json.loads(raw)
    assert payload["found"] == 1
    assert payload["items"][0]["productId"] == 6
    assert payload["items"][0]["name"] == "iPad Air 4 64G WiFi版"


async def test_search_never_leaks_seller_phone():
    """隐私边界：联系方式不能进模型上下文。"""
    backend = FakeBackend(search_products={"items": [SAMPLE_PRODUCT], "totalElements": 1})
    with tool_context(CONV_TOKEN, backend):
        raw = await search_products.ainvoke({"query": "ipad"})

    assert "15012345678" not in raw
    assert "sellerPhone" not in raw


async def test_search_empty_result_gives_hint():
    """搜不到时要给模型可行动的建议，而不是空数组。"""
    backend = FakeBackend(search_products={"items": [], "totalElements": 0})
    with tool_context(CONV_TOKEN, backend):
        payload = json.loads(await search_products.ainvoke({"query": "不存在的商品"}))

    assert payload["found"] == 0
    assert "hint" in payload


async def test_search_passes_price_range():
    """价格区间要透传给后端。"""
    backend = FakeBackend(search_products={"items": [], "totalElements": 0})
    with tool_context(CONV_TOKEN, backend):
        await search_products.ainvoke({"query": "ipad", "max_price": 500, "min_price": 100})

    _, _args, kwargs = backend.calls[0]
    assert kwargs["max_price"] == 500
    assert kwargs["min_price"] == 100


async def test_search_size_is_clamped():
    """模型可能给出过大的 size，必须收口，避免一次拉爆。"""
    backend = FakeBackend(search_products={"items": [], "totalElements": 0})
    with tool_context(CONV_TOKEN, backend):
        await search_products.ainvoke({"query": "x", "size": 9999})

    _, _, kwargs = backend.calls[0]
    assert kwargs["size"] == 50


async def test_get_product_includes_description_but_not_phone():
    backend = FakeBackend(get_product=SAMPLE_PRODUCT)
    with tool_context(CONV_TOKEN, backend):
        payload = json.loads(await get_product.ainvoke({"product_id": 6}))

    assert payload["description"] == "使用一年，无划痕带笔带壳"
    assert "15012345678" not in json.dumps(payload)


async def test_compare_price_passes_backend_numbers_untouched():
    """比价数字必须原样透传，工具层不得再做计算。"""
    backend = FakeBackend(
        compare_price={
            "categoryName": "图书教材",
            "conditionLevel": "9成新",
            "sampleSize": 4,
            "min": 10.00,
            "p25": 13.75,
            "median": 16.50,
            "p75": 22.50,
            "max": 25.00,
            "suggestedLow": 13.75,
            "suggestedHigh": 22.50,
            "verdict": "HIGH",
            "explanation": "定价偏高",
            "samples": [{"productId": 1, "price": 25.00}],
        }
    )
    with tool_context(CONV_TOKEN, backend):
        payload = json.loads(await compare_price.ainvoke({"product_id": 3}))

    assert payload["median"] == 16.50
    assert payload["p25"] == 13.75
    assert payload["verdict"] == "HIGH"
    assert payload["sampleSize"] == 4


async def test_permission_error_becomes_text_not_exception():
    """403 不能让工具抛异常，否则整张图会挂掉；应变成可读文本。"""
    backend = FakeBackend(list_my_orders=BackendError(403, 403, "未授予 order:read 权限"))
    with tool_context(CONV_TOKEN, backend):
        raw = await list_my_orders.ainvoke({"role": "buyer"})

    assert "未授予 order:read 权限" in raw
    assert "请勿重试" in raw


async def test_conflict_error_is_readable():
    backend = FakeBackend(get_product=BackendError(409, 409, "商品已售出"))
    with tool_context(CONV_TOKEN, backend):
        raw = await get_product.ainvoke({"product_id": 1})

    assert "状态冲突" in raw
    assert "商品已售出" in raw


async def test_not_found_is_readable():
    backend = FakeBackend(get_product=BackendError(404, 404, "商品不存在"))
    with tool_context(CONV_TOKEN, backend):
        raw = await get_product.ainvoke({"product_id": 999})

    assert "商品不存在" in raw


async def test_categories_formatted():
    backend = FakeBackend(
        list_categories=[
            {"id": 1, "name": "图书教材", "description": "教材教辅"},
            {"id": 2, "name": "数码电子", "description": "手机电脑"},
        ]
    )
    with tool_context(CONV_TOKEN, backend):
        payload = json.loads(await list_categories.ainvoke({}))

    assert [c["name"] for c in payload] == ["图书教材", "数码电子"]


async def test_context_missing_raises_clear_error():
    """未绑定上下文属于编程错误，必须立刻暴露而不是静默失败。"""
    with pytest.raises(RuntimeError, match="工具上下文未初始化"):
        await search_products.ainvoke({"query": "x"})


async def test_actor_token_is_forwarded():
    """身份必须透传到后端，否则后端无法鉴权。"""
    backend = FakeBackend(search_products={"items": [], "totalElements": 0})
    with tool_context(CONV_TOKEN, backend):
        await search_products.ainvoke({"query": "x"})

    _, args, _ = backend.calls[0]
    assert args[0] == CONV_TOKEN


async def test_category_name_as_query_is_dropped():
    """模型把分类名当关键词传时必须忽略 query，否则必然搜空。

    真实故障：用户说「300 到 800 之间的运动器材」，模型传
    query="运动器材" + category="体育器材"。后端条件是
    `名称/描述/地点 LIKE %运动器材% AND category=体育器材`，
    而「捷安特山地自行车」的描述里当然不会写"运动器材"四个字
    —— 结果 0 条，用户被告知"没有运动器材在卖"，但实际有 2 件。
    """
    backend = FakeBackend(search_products={"items": [], "totalElements": 0})
    with tool_context(CONV_TOKEN, backend):
        await search_products.ainvoke({"query": "体育器材", "category": "体育器材"})

    _, _, kwargs = backend.calls[0]
    assert kwargs["query"] is None, "与分类同名的 query 应被丢弃"
    assert kwargs["category"] == "体育器材"


async def test_real_keyword_is_kept_alongside_category():
    """关键词确实可能出现在商品文案里时，应保留 query。"""
    backend = FakeBackend(search_products={"items": [], "totalElements": 0})
    with tool_context(CONV_TOKEN, backend):
        await search_products.ainvoke({"query": "键盘", "category": "数码电子"})

    _, _, kwargs = backend.calls[0]
    assert kwargs["query"] == "键盘"
    assert kwargs["category"] == "数码电子"


async def test_empty_result_hint_gives_actionable_next_step():
    """搜不到时要给出可行动的下一步，而不是笼统的"放宽条件"。

    契约在 B 阶段改过一次：早期提示会建议"改用 category 筛选看看"，
    但那等于鼓励模型继续发工具调用；现在明确收敛成
    "可以再换一次词，否则就如实说没有"。
    """
    backend = FakeBackend(search_products={"items": [], "totalElements": 0})
    with tool_context(CONV_TOKEN, backend):
        payload = json.loads(
            await search_products.ainvoke({"query": "运动器材", "category": "体育器材"})
        )

    assert payload["found"] == 0
    assert payload["retries_left"] == 1
    assert "换" in payload["hint"] and "如实" in payload["hint"]


# ---------------------------------------------------------------------------
# 空结果重试闸门
# ---------------------------------------------------------------------------


async def test_first_empty_search_allows_one_retry():
    """第一次搜空：告诉模型还剩 1 次机会，而不是无限重试。"""
    backend = FakeBackend(search_products={"items": [], "totalElements": 0})
    with tool_context(CONV_TOKEN, backend):
        payload = json.loads(await search_products.ainvoke({"query": "吉他"}))

    assert payload["found"] == 0
    assert payload["retries_left"] == 1
    assert "最多再换 1 种说法" in payload["hint"]


async def test_second_empty_search_says_stop():
    """第二次仍空：不再给重试机会，明确让模型停手。"""
    backend = FakeBackend(search_products={"items": [], "totalElements": 0})
    with tool_context(CONV_TOKEN, backend):
        await search_products.ainvoke({"query": "吉他"})
        payload = json.loads(await search_products.ainvoke({"query": "民谣吉他"}))

    assert payload["retries_left"] == 0
    assert "停止换词" in payload["hint"]


async def test_third_search_is_blocked_without_calling_backend():
    """第三次直接被拦下，不再打后端 —— 这是省 token 的关键。

    真实故障：搜「吉他」时模型连试 4 个同义词（吉他/吉他/民谣吉他/尤克里里），
    每次都一个后端请求 + 一轮模型往返，全部空手而归。
    """
    backend = FakeBackend(search_products={"items": [], "totalElements": 0})
    with tool_context(CONV_TOKEN, backend):
        await search_products.ainvoke({"query": "吉他"})
        await search_products.ainvoke({"query": "民谣吉他"})
        payload = json.loads(await search_products.ainvoke({"query": "尤克里里"}))

    assert payload["stop"] is True
    assert payload["already_tried"] == ["吉他", "民谣吉他"]
    assert len(backend.calls) == 2, "第三次不应该再请求后端"


async def test_success_resets_the_empty_streak():
    """中间有成功就清零：两段不相干的查询不该互相牵连。"""
    backend = FakeBackend(search_products={"items": [], "totalElements": 0})
    with tool_context(CONV_TOKEN, backend):
        await search_products.ainvoke({"query": "吉他"})
        # 换成有货的查询
        backend.results["search_products"] = {
            "items": [
                {
                    "id": 8,
                    "name": "AirPods Pro 2代",
                    "price": 680,
                    "category": "数码电子",
                    "conditionLevel": "8成新",
                    "location": "南门",
                    "statusLabel": "在售",
                    "available": True,
                }
            ],
            "totalElements": 1,
        }
        ok = json.loads(await search_products.ainvoke({"query": "耳机"}))
        assert ok["found"] == 1

        # 再搜空，应该重新从"还剩 1 次"开始
        backend.results["search_products"] = {"items": [], "totalElements": 0}
        payload = json.loads(await search_products.ainvoke({"query": "投影仪"}))

    assert payload["retries_left"] == 1


async def test_counter_resets_between_turns():
    """计数按轮次隔离：上一轮搜空不该影响下一轮。"""
    backend = FakeBackend(search_products={"items": [], "totalElements": 0})
    with tool_context(CONV_TOKEN, backend):
        await search_products.ainvoke({"query": "吉他"})
        await search_products.ainvoke({"query": "民谣吉他"})

    with tool_context(CONV_TOKEN, backend):
        payload = json.loads(await search_products.ainvoke({"query": "投影仪"}))

    assert payload["retries_left"] == 1, "新的一轮应该重新计数"
