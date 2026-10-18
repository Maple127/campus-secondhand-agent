"""调用 Java 后端的 HTTP 客户端。

职责边界（重要）：
  本模块**不包含任何业务规则**。所有状态校验、权限判断、事务都由 Java 后端负责。
  这里只做三件事：拼请求、透传身份、把后端错误翻译成 Python 异常。

鉴权采用双层令牌，见 docs/agent-api.md：
  - X-Service-Token：证明调用方是内部 agent 服务
  - X-Actor-Token ：证明「以哪个用户的身份」操作
"""

from __future__ import annotations

from typing import Any

import httpx

SERVICE_TOKEN_HEADER = "X-Service-Token"
ACTOR_TOKEN_HEADER = "X-Actor-Token"


class BackendError(Exception):
    """后端返回的业务错误。

    后端返回的 message 是「写给人和 LLM 看的」，
    因此可以直接交给模型转述给用户，不需要二次加工。
    """

    def __init__(self, status: int, code: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    @property
    def is_permission_error(self) -> bool:
        """权限类错误：agent 不应重试，只能告知用户超出范围。"""
        return self.status in (401, 403)

    @property
    def is_conflict(self) -> bool:
        """状态冲突（如商品已被他人下单）。"""
        return self.status == 409

    def to_tool_message(self) -> str:
        """转成给 LLM 看的工具返回文本。

        刻意把「不要重试」写进文本：模型看到 403 时常见错误是换个参数反复试，
        而这里要它直接放弃并解释原因。
        """
        if self.is_permission_error:
            return (
                f"操作被拒绝（HTTP {self.status}）：{self.message}\n"
                "这是权限或登录状态问题，请勿重试，直接如实告知用户。"
            )
        if self.is_conflict:
            return f"操作发生状态冲突：{self.message}"
        return f"操作失败（HTTP {self.status}）：{self.message}"


class BackendClient:
    """后端 API 客户端。

    生命周期与 FastAPI 应用一致（单例），内部复用连接池。
    用户身份通过方法参数传入，而不是存在客户端实例上 ——
    避免并发请求之间身份串号。
    """

    def __init__(
        self,
        base_url: str,
        service_token: str,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
        trust_env: bool = False,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout),
            transport=transport,
            # trust_env=False 很关键：Windows 下 Python 会从注册表读到系统代理，
            # 导致对 localhost 后端的请求被送去代理并返回 502。
            trust_env=trust_env,
            headers={"Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---------- 内部请求封装 ----------

    def _headers(self, actor_token: str) -> dict[str, str]:
        return {
            SERVICE_TOKEN_HEADER: self._service_token,
            ACTOR_TOKEN_HEADER: actor_token,
        }

    async def _request(
        self,
        method: str,
        path: str,
        actor_token: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        # 去掉值为 None 的查询参数，避免把 "None" 当字符串传给后端
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}

        try:
            resp = await self._client.request(
                method,
                path,
                headers=self._headers(actor_token),
                params=clean_params or None,
                json=json,
            )
        except httpx.TimeoutException as exc:
            raise BackendError(504, 504, "后端服务响应超时，请稍后重试") from exc
        except httpx.HTTPError as exc:
            raise BackendError(502, 502, f"无法连接后端服务：{exc}") from exc

        if resp.status_code >= 400:
            raise self._to_error(resp)

        payload = resp.json()
        # 后端统一响应体 {code, message, data}
        if isinstance(payload, dict) and payload.get("code", 0) != 0:
            raise BackendError(
                resp.status_code, payload.get("code", -1), payload.get("message", "未知错误")
            )
        return payload.get("data") if isinstance(payload, dict) else payload

    @staticmethod
    def _to_error(resp: httpx.Response) -> BackendError:
        try:
            body = resp.json()
            return BackendError(
                status=resp.status_code,
                code=body.get("code", resp.status_code),
                message=body.get("message") or resp.text[:200],
            )
        except Exception:  # noqa: BLE001 - 响应体不是 JSON 时的兜底，任何解析异常都要退化成状态码
            return BackendError(resp.status_code, resp.status_code, resp.text[:200])

    # ---------- 只读接口（本期实现）----------

    async def search_products(
        self,
        actor_token: str,
        *,
        query: str | None = None,
        category: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        page: int = 0,
        size: int = 10,
        sort_by: str = "createTime",
        direction: str = "desc",
    ) -> dict[str, Any]:
        """商品检索。后端只返回在售商品。"""
        return await self._request(
            "GET",
            "/api/v1/products",
            actor_token,
            params={
                "q": query,
                "category": category,
                "minPrice": min_price,
                "maxPrice": max_price,
                "page": page,
                "size": size,
                "sortBy": sort_by,
                "direction": direction,
            },
        )

    async def get_product(self, actor_token: str, product_id: int) -> dict[str, Any]:
        """商品详情。不可见商品后端会返回 404。"""
        return await self._request("GET", f"/api/v1/products/{product_id}", actor_token)

    async def compare_price(
        self, actor_token: str, product_id: int, sample_limit: int = 50
    ) -> dict[str, Any]:
        """内部同类比价。统计数字全部由后端计算，模型只负责转述。"""
        return await self._request(
            "GET",
            f"/api/v1/products/{product_id}/price-comparison",
            actor_token,
            params={"sampleLimit": sample_limit},
        )

    async def negotiation_advice(self, actor_token: str, product_id: int) -> dict[str, Any]:
        """议价建议。三档价与依据全部由后端计算，模型只负责转述。"""
        return await self._request(
            "GET",
            f"/api/v1/products/{product_id}/negotiation-advice",
            actor_token,
        )

    async def list_categories(self, actor_token: str) -> list[dict[str, Any]]:
        """分类列表，供模型在筛选/发布时使用准确分类名。"""
        return await self._request("GET", "/api/v1/meta/categories", actor_token)

    async def get_me(self, actor_token: str) -> dict[str, Any]:
        """当前用户资料。"""
        return await self._request("GET", "/api/v1/me", actor_token)

    async def list_my_products(self, actor_token: str) -> list[dict[str, Any]]:
        """我发布的商品。"""
        return await self._request("GET", "/api/v1/products/mine/list", actor_token)

    async def list_my_orders(self, actor_token: str, role: str = "buyer") -> list[dict[str, Any]]:
        """我的订单。role=buyer|seller"""
        return await self._request("GET", "/api/v1/orders", actor_token, params={"role": role})

    async def get_order(self, actor_token: str, order_no: str) -> dict[str, Any]:
        """订单详情（仅买卖双方可见）。"""
        return await self._request("GET", f"/api/v1/orders/{order_no}", actor_token)

    # ---------- 写接口（由 agent 在用户确认后调用）----------
    #
    # 这些方法带副作用，因此**只允许**已通过人工确认的写工具调用。
    # 业务校验（状态机、越权、审核）全部在后端完成，这里不做任何判断。

    async def publish_product(self, actor_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        """发布商品。后端会置为待审核状态。"""
        return await self._request("POST", "/api/v1/products", actor_token, json=payload)

    async def update_product(
        self, actor_token: str, product_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """修改自己的商品。"""
        return await self._request(
            "PATCH", f"/api/v1/products/{product_id}", actor_token, json=payload
        )

    async def delist_product(self, actor_token: str, product_id: int) -> dict[str, Any]:
        """下架自己的商品。"""
        return await self._request("POST", f"/api/v1/products/{product_id}/delist", actor_token)

    async def create_order(
        self,
        actor_token: str,
        product_id: int,
        delivery_type: str = "PICKUP",
        appointment_time: str | None = None,
    ) -> dict[str, Any]:
        """创建订单。后端在同一事务内锁定商品，因此可能返回 409。"""
        return await self._request(
            "POST",
            "/api/v1/orders",
            actor_token,
            json={
                "productId": product_id,
                "deliveryType": delivery_type,
                "appointmentTime": appointment_time,
            },
        )

    async def cancel_order(
        self, actor_token: str, order_no: str, reason: str | None = None
    ) -> dict[str, Any]:
        """取消未付款订单。"""
        return await self._request(
            "POST",
            f"/api/v1/orders/{order_no}/cancel",
            actor_token,
            json={"reason": reason},
        )

    async def submit_report(
        self,
        actor_token: str,
        product_id: int,
        reason_type: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        """提交举报。"""
        return await self._request(
            "POST",
            "/api/v1/reports",
            actor_token,
            json={
                "productId": product_id,
                "reasonType": reason_type,
                "description": description,
            },
        )
