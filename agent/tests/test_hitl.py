"""HITL（人工确认）流程验证。

这是 M4 的核心机制，必须验证四件事：
  1. 写工具被调用时会挂起，并产出 confirmation_required 事件
  2. 用户**拒绝**时不执行副作用
  3. 用户**同意**时执行一次副作用
  4. **重复同意同一个确认不会重复执行**（幂等）

第 4 条最关键：LangGraph 的 interrupt 恢复时会重新执行节点，
如果没有幂等账本，用户双击确认就会产生两件商品。
"""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.config import Settings
from app.graph import AgentRunner
from app.idempotency import IdempotentExecutor


class WriteRecordingBackend:
    """记录写调用的假后端。"""

    def __init__(self):
        self.published: list[dict] = []
        self.orders: list[dict] = []
        self.delisted: list[int] = []
        self.cancelled: list[str] = []
        self.list_categories_calls = 0

    async def list_categories(self, token):
        self.list_categories_calls += 1
        return [{"id": 2, "name": "数码电子", "description": ""}]

    async def search_products(self, token, **kwargs):
        return {"items": [], "totalElements": 0}

    async def get_product(self, token, product_id):
        return {
            "id": product_id,
            "name": "测试商品",
            "price": 100.0,
            "available": True,
            "statusLabel": "在售",
            "location": "宿舍楼下",
            "category": "数码电子",
            "conditionLevel": "9成新",
        }

    async def compare_price(self, token, product_id, sample_limit=50):
        return {}

    async def list_my_products(self, token):
        return []

    async def list_my_orders(self, token, role="buyer"):
        return []

    async def get_order(self, token, order_no):
        return {
            "orderNo": order_no,
            "productName": "测试商品",
            "price": 100.0,
            "statusLabel": "待付款",
        }

    # ---- 写操作 ----
    async def publish_product(self, token, payload):
        self.published.append(payload)
        return {"id": 100 + len(self.published), "name": payload["name"], "statusLabel": "待审核"}

    async def update_product(self, token, product_id, payload):
        return {"id": product_id, "price": payload.get("price"), "statusLabel": "在售"}

    async def delist_product(self, token, product_id):
        self.delisted.append(product_id)
        return {"id": product_id, "statusLabel": "已下架"}

    async def create_order(self, token, product_id, delivery_type="PICKUP", appointment_time=None):
        self.orders.append({"productId": product_id})
        return {
            "orderNo": "ORDER-1",
            "productName": "测试商品",
            "price": 100.0,
            "statusLabel": "待付款",
        }

    async def cancel_order(self, token, order_no, reason=None):
        self.cancelled.append(order_no)
        return {"orderNo": order_no, "statusLabel": "已取消"}

    async def submit_report(self, token, product_id, reason_type, description=None):
        return {"id": 1, "message": "已提交"}


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def make_settings(tmp_path) -> Settings:
    return Settings(
        DEEPSEEK_API_KEY="sk-fake",
        AGENT_SERVICE_TOKEN="t",
        CHECKPOINT_DB_PATH=str(tmp_path / "state.db"),
    )


def publish_call(name="测试商品", price=100.0) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "publish_product",
                "args": {"name": name, "price": price, "category": "数码电子"},
                "id": "call_pub_1",
            }
        ],
    )


def final_answer(text="好的，已处理。") -> AIMessage:
    return AIMessage(content=text)


async def run_stream(runner, backend, message, conv):
    events = []
    async for ev in runner.stream(
        message, conversation_id=conv, actor_token="tok", backend=backend
    ):
        events.append(ev)
    return events


async def run_resume(runner, backend, approved, conv):
    events = []
    async for ev in runner.resume(
        {"approved": approved}, conversation_id=conv, actor_token="tok", backend=backend
    ):
        events.append(ev)
    return events


# ===========================================================================


async def test_write_tool_emits_confirmation_and_pauses(tmp_path):
    """写工具被调用时必须挂起并产出确认事件。"""
    backend = WriteRecordingBackend()
    runner = AgentRunner(
        make_settings(tmp_path),
        InMemorySaver(),
        model=ScriptedModel(responses=[publish_call(), final_answer()]),
        executor=IdempotentExecutor(tmp_path / "ledger.db"),
    )

    events = await run_stream(runner, backend, "帮我发布一件闲置", "c1")
    types = [e["type"] for e in events]

    assert "confirmation_required" in types, f"未产出确认事件: {types}"

    conf = next(e for e in events if e["type"] == "confirmation_required")
    assert conf["action"] == "publish_product"
    assert conf["fingerprint"]
    assert conf["summary"]["title"]
    assert any(f["label"] == "标题" for f in conf["summary"]["fields"])

    # 关键：还没确认，绝不能已经执行
    assert backend.published == [], "确认前就执行了副作用！"
    # 图确实挂起了
    assert await runner.has_pending_confirmation("c1") is True


async def test_reject_does_not_execute(tmp_path):
    """用户拒绝时不得执行副作用。"""
    backend = WriteRecordingBackend()
    runner = AgentRunner(
        make_settings(tmp_path),
        InMemorySaver(),
        model=ScriptedModel(responses=[publish_call(), final_answer("好的，已取消。")]),
        executor=IdempotentExecutor(tmp_path / "ledger.db"),
    )

    await run_stream(runner, backend, "发布", "c-reject")
    await run_resume(runner, backend, approved=False, conv="c-reject")

    assert backend.published == [], "用户拒绝了却仍然执行了！"
    assert await runner.has_pending_confirmation("c-reject") is False


async def test_approve_executes_once(tmp_path):
    """用户同意时执行一次副作用。"""
    backend = WriteRecordingBackend()
    runner = AgentRunner(
        make_settings(tmp_path),
        InMemorySaver(),
        model=ScriptedModel(responses=[publish_call(), final_answer("已提交审核。")]),
        executor=IdempotentExecutor(tmp_path / "ledger.db"),
    )

    await run_stream(runner, backend, "发布", "c-ok")
    events = await run_resume(runner, backend, approved=True, conv="c-ok")

    assert len(backend.published) == 1
    assert backend.published[0]["name"] == "测试商品"
    assert "error" not in [e["type"] for e in events]


async def test_double_approve_is_idempotent(tmp_path):
    """重复同意同一个确认，副作用只能发生一次。

    这是最关键的断言：interrupt 恢复会重跑节点，
    若没有幂等账本，用户双击确认就会创建两件商品。
    """
    backend = WriteRecordingBackend()
    runner = AgentRunner(
        make_settings(tmp_path),
        InMemorySaver(),
        model=ScriptedModel(responses=[publish_call(), final_answer("已提交审核。")]),
        executor=IdempotentExecutor(tmp_path / "ledger.db"),
    )

    await run_stream(runner, backend, "发布", "c-dup")
    await run_resume(runner, backend, approved=True, conv="c-dup")

    # 第一次确认后的指纹
    ledger = runner.executor
    assert len(backend.published) == 1

    # 直接对同一指纹再次调用执行器，模拟重复触发
    fp = next(iter([k for k in _fingerprints(ledger)]), None)
    assert fp is not None, "账本里没有记录"

    async def action():
        return await backend.publish_product("tok", {"name": "测试商品", "price": 100.0})

    outcome = await ledger.run_once(fp, action)
    assert outcome["duplicate"] is True, "重复执行没有被幂等拦截"
    assert outcome["executed"] is False
    assert len(backend.published) == 1, f"副作用被执行了多次: {len(backend.published)}"


def _fingerprints(executor) -> list[str]:
    import sqlite3

    with sqlite3.connect(executor._db_path) as conn:
        rows = conn.execute("SELECT fingerprint FROM idempotency_ledger").fetchall()
    return [r[0] for r in rows]


async def test_confirmation_summary_is_user_checkable(tmp_path):
    """确认卡片必须包含用户能自己核对的字段。

    这张卡片是用户唯一的把关机会，缺字段等于让人盲签。
    """
    backend = WriteRecordingBackend()
    runner = AgentRunner(
        make_settings(tmp_path),
        InMemorySaver(),
        model=ScriptedModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "create_order",
                            "args": {"product_id": 7},
                            "id": "call_order_1",
                        }
                    ],
                ),
                final_answer(),
            ]
        ),
        executor=IdempotentExecutor(tmp_path / "ledger.db"),
    )

    events = await run_stream(runner, backend, "帮我买这个", "c-order")
    conf = next(e for e in events if e["type"] == "confirmation_required")

    labels = [f["label"] for f in conf["summary"]["fields"]]
    assert "商品" in labels
    assert "价格" in labels
    assert conf["summary"]["notice"]

    # 未确认前不能下单
    assert backend.orders == []


async def test_fingerprint_is_scoped_to_user(tmp_path):
    """幂等指纹必须绑定用户，否则会跨用户误判。

    场景：A 和 B 用完全相同的参数发布同款商品。
    如果指纹不含用户身份，B 的确认会被当成 A 的重复请求而静默跳过，
    表现为"B 点了确认但什么都没发生" —— 这是个很容易漏掉的正确性缺陷。
    """
    executor = IdempotentExecutor(tmp_path / "ledger.db")

    fp_a = IdempotentExecutor.fingerprint(
        "publish_product", {"name": "台灯", "price": 45}, "token-A"
    )
    fp_b = IdempotentExecutor.fingerprint(
        "publish_product", {"name": "台灯", "price": 45}, "token-B"
    )
    fp_a2 = IdempotentExecutor.fingerprint(
        "publish_product", {"name": "台灯", "price": 45}, "token-A"
    )

    assert fp_a != fp_b, "不同用户相同参数必须得到不同指纹"
    assert fp_a == fp_a2, "同一用户相同参数必须稳定（幂等的基础）"

    # 未带 scope 时与显式 "-" 等价，且不与任何真实用户冲突
    fp_none = IdempotentExecutor.fingerprint("publish_product", {"name": "台灯", "price": 45}, None)
    assert fp_none not in (fp_a, fp_b)

    # 端到端：A 执行过之后，B 的相同操作仍应被真正执行
    calls: list[str] = []

    async def action_a():
        calls.append("A")
        return {"id": 1}

    async def action_b():
        calls.append("B")
        return {"id": 2}

    await executor.run_once(fp_a, action_a)
    outcome_b = await executor.run_once(fp_b, action_b)

    assert outcome_b["executed"] is True, "B 的操作被误判为重复"
    assert calls == ["A", "B"]

    # 而 A 自己重复提交仍然命中幂等
    outcome_a2 = await executor.run_once(fp_a, action_a)
    assert outcome_a2["duplicate"] is True
    assert calls == ["A", "B"], "A 的重复提交不应再次执行"


async def test_state_survives_runner_restart(tmp_path):
    """确认状态必须落在持久化存储里。

    这里用「同一个数据库文件 + 新建 checkpointer / runner」模拟服务重启：
    挂起状态应当仍然可查，否则用户刷新或重启后就无法完成确认。
    """
    db = tmp_path / "state.db"
    ledger = tmp_path / "ledger.db"

    backend = WriteRecordingBackend()
    settings = Settings(
        DEEPSEEK_API_KEY="sk-fake", AGENT_SERVICE_TOKEN="t", CHECKPOINT_DB_PATH=str(db)
    )

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(str(db)) as cp1:
        runner1 = AgentRunner(
            settings,
            cp1,
            model=ScriptedModel(responses=[publish_call(), final_answer()]),
            executor=IdempotentExecutor(ledger),
        )
        await run_stream(runner1, backend, "发布", "c-persist")
        assert await runner1.has_pending_confirmation("c-persist") is True

    # 模拟重启：新的 checkpointer 实例，同一个 DB 文件
    async with AsyncSqliteSaver.from_conn_string(str(db)) as cp2:
        runner2 = AgentRunner(
            settings,
            cp2,
            model=ScriptedModel(responses=[final_answer("已提交审核。")]),
            executor=IdempotentExecutor(ledger),
        )
        assert await runner2.has_pending_confirmation("c-persist") is True, "重启后挂起的确认丢失了"

        # 并且可以继续完成
        await run_resume(runner2, backend, approved=True, conv="c-persist")
        assert len(backend.published) == 1
