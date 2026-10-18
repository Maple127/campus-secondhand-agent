"""后端客户端测试：用的是 httpx.MockTransport，不依赖真实后端。

重点验证两件事：
  1. 双层令牌确实被放到请求头上（漏了就是 401）
  2. 后端错误被正确翻译，并且**权限类错误明确要求模型不要重试**
"""

from __future__ import annotations

import httpx
import pytest

from app.backend import (
    ACTOR_TOKEN_HEADER,
    SERVICE_TOKEN_HEADER,
    BackendClient,
    BackendError,
)

SERVICE_TOKEN = "test-service-token"


def make_client(handler) -> BackendClient:
    return BackendClient(
        base_url="http://backend.test",
        service_token=SERVICE_TOKEN,
        transport=httpx.MockTransport(handler),
    )


def ok(data):
    return httpx.Response(200, json={"code": 0, "message": "ok", "data": data})


async def test_sends_both_tokens():
    """双层令牌必须同时出现在请求头。"""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        return ok({"items": [], "totalElements": 0})

    client = make_client(handler)
    try:
        await client.search_products("actor-123", query="ipad")
    finally:
        await client.aclose()

    assert captured[SERVICE_TOKEN_HEADER.lower()] == SERVICE_TOKEN
    assert captured[ACTOR_TOKEN_HEADER.lower()] == "actor-123"


async def test_query_params_mapped_and_none_dropped():
    """查询参数名要与后端一致，且 None 不能被传成 "None"。"""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return ok({"items": [], "totalElements": 0})

    client = make_client(handler)
    try:
        await client.search_products(
            "t", query="ipad", category=None, min_price=100, max_price=3000, size=5
        )
    finally:
        await client.aclose()

    params = seen["params"]
    assert params["q"] == "ipad"
    assert params["minPrice"] == "100"
    assert params["maxPrice"] == "3000"
    assert params["size"] == "5"
    assert "category" not in params, "值为 None 的参数不应出现在请求里"


async def test_unwraps_data_envelope():
    """统一响应体 {code,message,data} 要自动解包。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return ok({"id": 7, "name": "iPad"})

    client = make_client(handler)
    try:
        data = await client.get_product("t", 7)
    finally:
        await client.aclose()

    assert data["id"] == 7
    assert data["name"] == "iPad"


async def test_business_error_code_in_body_raises():
    """HTTP 200 但 code != 0 也属于业务失败。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 409, "message": "已被抢单", "data": None})

    client = make_client(handler)
    try:
        with pytest.raises(BackendError) as ei:
            await client.compare_price("t", 1)
    finally:
        await client.aclose()

    assert ei.value.code == 409
    assert "抢单" in ei.value.message


@pytest.mark.parametrize("status", [401, 403])
async def test_permission_errors_flagged_and_message_says_no_retry(status):
    """权限类错误必须被标记，并且给模型的文本要明确说不要重试。"""
    body = {"code": status, "message": "当前会话未被授予 order:pay 权限", "data": None}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    client = make_client(handler)
    try:
        with pytest.raises(BackendError) as ei:
            await client.list_my_orders("t")
    finally:
        await client.aclose()

    err = ei.value
    assert err.is_permission_error is True
    text = err.to_tool_message()
    assert "请勿重试" in text, "必须显式阻止模型反复重试越权请求"


async def test_conflict_is_flagged():
    """409 应被识别为状态冲突。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"code": 409, "message": "商品已售出", "data": None})

    client = make_client(handler)
    try:
        with pytest.raises(BackendError) as ei:
            await client.get_product("t", 1)
    finally:
        await client.aclose()

    assert ei.value.is_conflict is True
    assert "状态冲突" in ei.value.to_tool_message()


async def test_timeout_becomes_backend_error():
    """超时不能抛原始 httpx 异常给上层。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("too slow", request=request)

    client = make_client(handler)
    try:
        with pytest.raises(BackendError) as ei:
            await client.get_product("t", 1)
    finally:
        await client.aclose()

    assert ei.value.status == 504
    assert "超时" in ei.value.message


async def test_connection_error_becomes_backend_error():
    """连接失败同样要被包装。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = make_client(handler)
    try:
        with pytest.raises(BackendError) as ei:
            await client.get_product("t", 1)
    finally:
        await client.aclose()

    assert ei.value.status == 502
    assert "无法连接后端服务" in ei.value.message


async def test_non_json_error_body_is_tolerated():
    """后端返回 HTML 错误页时不能因为解析失败而崩溃。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="<html>500</html>")

    client = make_client(handler)
    try:
        with pytest.raises(BackendError) as ei:
            await client.get_product("t", 1)
    finally:
        await client.aclose()

    assert ei.value.status == 500
