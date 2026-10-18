"""写操作工具。

每个工具都遵循同一套结构：

    1. 归一化参数（生成幂等指纹用）
    2. 组装"给用户看的确认摘要"
    3. confirm_and_execute() 挂起等待确认 → 通过则执行
    4. 把结果转成模型能读懂的文本

两个必须注意的点：

  - **确认摘要**要用用户能自己核对的字段（商品名、价格、地点）。
    这张卡片是用户唯一的把关机会，缺字段等于让人盲签。
  - 所有后端调用都包在 `run_tool()` 里，它会把 `GraphInterrupt`
    原样上抛。写工具里**绝不能**直接写 `except Exception` ——
    那会把 interrupt 一起吞掉，导致图不挂起。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from app.hitl import confirm_and_execute
from app.tools import _dumps, _require_context, run_tool


def _ok(payload: Any) -> str:
    return _dumps(payload)


# ---------------------------------------------------------------------------
# 商品类
# ---------------------------------------------------------------------------


@tool
async def publish_product(
    name: str,
    price: float,
    description: str | None = None,
    category: str | None = None,
    condition: str | None = None,
    location: str | None = None,
) -> str:
    """帮用户发布一件闲置商品。

    这是**写操作**，执行前会请求用户确认。
    发布后商品进入**待审核**状态，需要管理员审核通过才会出现在首页，
    因此不要告诉用户"已经上架了"。

    Args:
        name: 商品标题，要具体，例如 "AirPods Pro 2代 95新"。
        price: 售价（元）。
        description: 详细描述，包括成色瑕疵、购买时间、配件是否齐全。
        category: 分类名称。不确定时先用 list_categories 查询。
        condition: 成色，例如 "全新"、"9成新"、"7成新"。
        location: 建议的交易地点，例如 "3号宿舍楼下"。
    """
    token, backend = _require_context()

    display_category = category or "其他"
    params = {
        "name": name.strip(),
        "price": price,
        "category": display_category,
        "condition": condition,
        "location": location,
    }

    summary = {
        "title": "确认发布商品？",
        "fields": [
            {"label": "标题", "value": name.strip()},
            {"label": "售价", "value": f"¥{price}"},
            {"label": "分类", "value": display_category},
            {"label": "成色", "value": condition or "未填写"},
            {"label": "交易地点", "value": location or "未填写"},
            {"label": "描述", "value": (description or "未填写")[:120]},
        ],
        "notice": "发布后商品将进入「待审核」状态，管理员审核通过后才会展示在首页。",
    }

    async def body() -> str:
        result = await confirm_and_execute(
            action="publish_product",
            params=params,
            summary=summary,
            run=lambda: backend.publish_product(
                token,
                {
                    "name": name.strip(),
                    "description": description,
                    "price": price,
                    "conditionLevel": condition,
                    "location": location,
                    "category": category,
                },
            ),
        )
        if result.get("rejected"):
            return _ok({"cancelled": True, "message": "用户取消了发布，未创建商品。"})
        return _ok(
            {
                "created": True,
                "productId": result.get("id"),
                "name": result.get("name"),
                "status": result.get("statusLabel"),
                "note": "已提交，等待管理员审核。审核通过后才会出现在首页。",
                "idempotentReplay": result.get("idempotentReplay", False),
            }
        )

    return await run_tool(body)


@tool
async def update_product(
    product_id: int,
    price: float | None = None,
    description: str | None = None,
    condition: str | None = None,
    location: str | None = None,
) -> str:
    """修改用户自己已发布的商品（改价、改描述等）。

    这是**写操作**，执行前会请求用户确认。
    只能改自己发布的商品；改别人的会被后端拒绝。

    Args:
        product_id: 商品 ID。
        price: 新的售价（元）。不改就不传。
        description: 新的描述。不改就不传。
        condition: 新的成色。不改就不传。
        location: 新的交易地点。不改就不传。
    """
    token, backend = _require_context()

    if price is None and description is None and condition is None and location is None:
        return _ok({"error": "没有提供任何要修改的字段。请告诉我改什么。"})

    async def body() -> str:
        # 取原商品：用于补全 PATCH 字段，并让确认卡片能显示"从多少改到多少"
        current = await backend.get_product(token, product_id)

        changes: dict[str, Any] = {}
        if price is not None:
            changes["price"] = price
        if description is not None:
            changes["description"] = description
        if condition is not None:
            changes["condition"] = condition
        if location is not None:
            changes["location"] = location

        summary = {
            "title": f"确认修改商品「{current.get('name')}」？",
            "fields": [
                {"label": "商品", "value": f"{current.get('name')}（productId {product_id}）"},
                {"label": "当前售价", "value": f"¥{current.get('price')}"},
                *[{"label": f"改为 {k}", "value": str(v)} for k, v in changes.items()],
            ],
            "notice": "修改后立即生效。",
        }

        async def run():
            payload = {
                "name": current.get("name"),
                "description": changes.get("description", current.get("description")),
                "price": changes.get("price", current.get("price")),
                "conditionLevel": changes.get("condition", current.get("conditionLevel")),
                "location": changes.get("location", current.get("location")),
                "category": current.get("category"),
            }
            return await backend.update_product(token, product_id, payload)

        result = await confirm_and_execute(
            action="update_product",
            params={"productId": product_id, **changes},
            summary=summary,
            run=run,
        )
        if result.get("rejected"):
            return _ok({"cancelled": True, "message": "用户取消了修改。"})
        return _ok(
            {
                "updated": True,
                "productId": result.get("id"),
                "price": result.get("price"),
                "status": result.get("statusLabel"),
                "idempotentReplay": result.get("idempotentReplay", False),
            }
        )

    return await run_tool(body)


@tool
async def delist_product(product_id: int) -> str:
    """下架用户自己的商品。

    这是**写操作**，执行前会请求用户确认。
    只有在售商品可以下架；已售出的商品不能下架（交易记录需保留）。

    Args:
        product_id: 要下架的商品 ID。
    """
    token, backend = _require_context()

    async def body() -> str:
        current = await backend.get_product(token, product_id)

        summary = {
            "title": "确认下架该商品？",
            "fields": [
                {"label": "商品", "value": current.get("name")},
                {"label": "售价", "value": f"¥{current.get('price')}"},
                {"label": "当前状态", "value": current.get("statusLabel")},
            ],
            "notice": "下架后商品不再出现在首页，之后可以重新发布。",
        }

        result = await confirm_and_execute(
            action="delist_product",
            params={"productId": product_id},
            summary=summary,
            run=lambda: backend.delist_product(token, product_id),
        )
        if result.get("rejected"):
            return _ok({"cancelled": True, "message": "用户取消了下架。"})
        return _ok(
            {
                "delisted": True,
                "productId": result.get("id"),
                "status": result.get("statusLabel"),
                "idempotentReplay": result.get("idempotentReplay", False),
            }
        )

    return await run_tool(body)


# ---------------------------------------------------------------------------
# 订单类
# ---------------------------------------------------------------------------


@tool
async def create_order(
    product_id: int,
    delivery_type: str = "PICKUP",
    appointment_time: str | None = None,
) -> str:
    """帮用户下单购买某个商品。

    这是**写操作**，执行前会请求用户确认。
    确认后商品会被立即锁定（其他同学无法再下单）。
    如果商品已被他人买走，会返回冲突提示。

    Args:
        product_id: 要购买的商品 ID。
        delivery_type: "PICKUP" 自取（默认）或 "DELIVERY" 配送。
        appointment_time: 预约交易时间，格式 2026-01-01T10:00。不传则默认 1 小时后。
    """
    token, backend = _require_context()

    async def body() -> str:
        product = await backend.get_product(token, product_id)
        if not product.get("available"):
            return _ok(
                {
                    "error": f"该商品当前状态为「{product.get('statusLabel')}」，无法下单。",
                    "productId": product_id,
                }
            )

        summary = {
            "title": "确认下单？",
            "fields": [
                {"label": "商品", "value": product.get("name")},
                {"label": "价格", "value": f"¥{product.get('price')}"},
                {"label": "交易地点", "value": product.get("location") or "未注明"},
                {"label": "交易方式", "value": "自取" if delivery_type == "PICKUP" else "配送"},
                {"label": "预约时间", "value": appointment_time or "默认 1 小时后"},
            ],
            "notice": "确认后商品将被锁定，其他同学无法再购买。支付需你本人在订单页完成。",
        }

        result = await confirm_and_execute(
            action="create_order",
            params={
                "productId": product_id,
                "deliveryType": delivery_type,
                "appointmentTime": appointment_time,
            },
            summary=summary,
            run=lambda: backend.create_order(token, product_id, delivery_type, appointment_time),
        )
        if result.get("rejected"):
            return _ok({"cancelled": True, "message": "用户取消了下单。"})
        return _ok(
            {
                "created": True,
                "orderNo": result.get("orderNo"),
                "productName": result.get("productName"),
                "price": result.get("price"),
                "status": result.get("statusLabel"),
                "note": "订单已创建，请到订单页由本人完成支付（我无法代为支付）。",
                "idempotentReplay": result.get("idempotentReplay", False),
            }
        )

    return await run_tool(body)


@tool
async def cancel_order(order_no: str, reason: str | None = None) -> str:
    """取消用户自己的未付款订单。

    这是**写操作**，执行前会请求用户确认。
    取消后商品会重新变为「在售」，其他同学可以下单。
    已付款订单不能直接取消（需要走退款流程）。

    Args:
        order_no: 订单号，来自 list_my_orders 返回的 orderNo。
        reason: 取消原因，可选。
    """
    token, backend = _require_context()

    async def body() -> str:
        order = await backend.get_order(token, order_no)

        summary = {
            "title": "确认取消订单？",
            "fields": [
                {"label": "订单号", "value": order_no},
                {"label": "商品", "value": order.get("productName")},
                {"label": "金额", "value": f"¥{order.get('price')}"},
                {"label": "当前状态", "value": order.get("statusLabel")},
            ],
            "notice": "取消后商品会重新上架，其他同学可以购买。",
        }

        result = await confirm_and_execute(
            action="cancel_order",
            params={"orderNo": order_no, "reason": reason},
            summary=summary,
            run=lambda: backend.cancel_order(token, order_no, reason),
        )
        if result.get("rejected"):
            return _ok({"cancelled": True, "message": "用户取消了该操作，订单未变动。"})
        return _ok(
            {
                "cancelled": True,
                "orderNo": result.get("orderNo"),
                "status": result.get("statusLabel"),
                "idempotentReplay": result.get("idempotentReplay", False),
            }
        )

    return await run_tool(body)


# ---------------------------------------------------------------------------
# 举报
# ---------------------------------------------------------------------------


@tool
async def submit_report(
    product_id: int,
    reason_type: str,
    description: str | None = None,
) -> str:
    """举报违规商品。

    这是**写操作**，执行前会请求用户确认。
    不能举报自己发布的商品；同一商品不能重复举报。

    Args:
        product_id: 被举报的商品 ID。
        reason_type: 举报类型，取值："虚假商品"、"违规物品"、"价格欺诈"、"其他违规"。
        description: 详细描述与证据说明。
    """
    token, backend = _require_context()

    allowed = {"虚假商品", "违规物品", "价格欺诈", "其他违规"}
    if reason_type not in allowed:
        return _ok(
            {
                "error": f"举报类型「{reason_type}」无效",
                "allowed": sorted(allowed),
            }
        )

    summary = {
        "title": "确认提交举报？",
        "fields": [
            {"label": "商品ID", "value": str(product_id)},
            {"label": "举报类型", "value": reason_type},
            {"label": "说明", "value": (description or "未填写")[:120]},
        ],
        "notice": "举报会提交给管理员核实，请确保内容真实。",
    }

    async def body() -> str:
        result = await confirm_and_execute(
            action="submit_report",
            params={
                "productId": product_id,
                "reasonType": reason_type,
                "description": description,
            },
            summary=summary,
            run=lambda: backend.submit_report(token, product_id, reason_type, description),
        )
        if result.get("rejected"):
            return _ok({"cancelled": True, "message": "用户取消了举报。"})
        return _ok(
            {
                "submitted": True,
                "reportId": result.get("id"),
                "message": result.get("message", "举报已提交"),
                "idempotentReplay": result.get("idempotentReplay", False),
            }
        )

    return await run_tool(body)


#: 需要人工确认的写工具
WRITE_TOOLS = [
    publish_product,
    update_product,
    delist_product,
    create_order,
    cancel_order,
    submit_report,
]
