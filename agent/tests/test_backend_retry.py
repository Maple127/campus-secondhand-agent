"""重试与降级的测试。

这里的测试不碰真实网络，用 `httpx.MockTransport` 按脚本返回响应。
重点验证的是**哪些错误该重试、哪些绝对不该**：

  · 5xx / 超时 / 连接失败 → 重试（服务端暂时性故障）
  · 4xx → 不重试（商品已售出、没权限，重试一万次也一样）

第二条比第一条重要：重试一个业务错误只会让用户多等两秒，
而且如果是写操作，还可能被执行两次。
"""

from __future__ import annotations

import httpx
import pytest

from app.backend import BackendClient, BackendError
from app.metrics import METRICS

SERVICE_TOKEN = "test-service-token"


@pytest.fixture(autouse=True)
def _reset_metrics():
    METRICS.reset()
    yield
    METRICS.reset()


def make_client(handler, max_retries: int = 2) -> BackendClient:
    return BackendClient(
        base_url="http://backend.test",
        service_token=SERVICE_TOKEN,
        transport=httpx.MockTransport(handler),
        max_retries=max_retries,
        retry_base_delay=0.0,
    )


def ok(data):
    return httpx.Response(200, json={"code": 0, "message": "ok", "data": data})


async def test_retries_on_503_then_succeeds():
    """503 是暂时性故障，重试应该成功，并记账。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="busy")
        return ok({"items": [], "totalElements": 0})

    client = make_client(handler)
    try:
        data = await client.search_products("t")
    finally:
        await client.aclose()

    assert data["totalElements"] == 0
    assert calls["n"] == 2, "应该只重试一次就成功"
    assert METRICS.retries == 1
    assert METRICS.retry_success == 1
    assert METRICS.retry_exhausted == 0


async def test_does_not_retry_on_400():
    """业务错误（400）不重试 —— 重试不会改变结论。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"code": 40001, "message": "商品已售出"})

    client = make_client(handler)
    try:
        with pytest.raises(BackendError) as ei:
            await client.get_product("t", 1)
    finally:
        await client.aclose()

    assert calls["n"] == 1, "4xx 不应该触发重试"
    assert ei.value.status == 400
    assert "已售出" in ei.value.message
    assert METRICS.retries == 0


async def test_does_not_retry_on_403():
    """权限错误不重试：模型只能换说法，不能换结果。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403, json={"code": 40300, "message": "超出权限范围"})

    client = make_client(handler)
    try:
        with pytest.raises(BackendError) as ei:
            await client.get_product("t", 1)
    finally:
        await client.aclose()

    assert calls["n"] == 1
    assert ei.value.is_permission_error


async def test_exhausts_retries_and_reports_504():
    """持续 503：重试到上限后放弃，并把计数记在 retry_exhausted。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="down")

    client = make_client(handler, max_retries=2)
    try:
        with pytest.raises(BackendError) as ei:
            await client.get_product("t", 1)
    finally:
        await client.aclose()

    assert calls["n"] == 3, "1 次原始 + 2 次重试"
    assert ei.value.status == 503
    assert METRICS.retry_exhausted == 1
    assert METRICS.retry_success == 0


async def test_connection_error_retried_then_504():
    """连接不上：重试后归为 504，且不会抛原始 httpx 异常给上层。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("refused", request=request)

    client = make_client(handler, max_retries=1)
    try:
        with pytest.raises(BackendError) as ei:
            await client.get_product("t", 1)
    finally:
        await client.aclose()

    assert calls["n"] == 2
    assert ei.value.status == 504
    assert "暂时不可用" in ei.value.message


async def test_business_code_error_not_retried():
    """HTTP 200 但 code != 0：这是业务结论，不是故障，不重试。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"code": 40901, "message": "库存不足"})

    client = make_client(handler)
    try:
        with pytest.raises(BackendError) as ei:
            await client.get_product("t", 1)
    finally:
        await client.aclose()

    assert calls["n"] == 1
    assert ei.value.code == 40901
    assert METRICS.retries == 0
