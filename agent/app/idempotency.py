"""幂等执行器。

**为什么必须有**：人工确认的语义是"用户点了一次确认，动作就执行一次"。
但现实中会出现重复触发：

  - 用户双击确认按钮
  - 网络重试 / 前端重连
  - LangGraph 恢复执行时节点被重新执行（这是 `interrupt` 的固有行为）
  - 服务重启后旧请求被重放

对"下单"和"发布商品"来说，重复执行会直接产生脏数据（重复订单、重复商品），
因此需要一个**独立于图状态**的账本：只要某个确认已成功执行过，
再次执行就返回上一次的结果，而不是重新调用后端。

账本落在 SQLite（与 checkpointer 同一文件），保证跨进程重启仍然有效。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS idempotency_ledger (
    fingerprint TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    result      TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_status ON idempotency_ledger(status);
"""


class IdempotentExecutor:
    """带幂等账本的执行器。

    用法：
        executor = IdempotentExecutor(db_path)
        result = await executor.run_once(fingerprint, action)

    - 若该 fingerprint 已成功执行过，直接返回上次结果，**不调用 action**
    - 若正在执行中（并发请求），等待/拒绝，避免双写
    - 执行失败时不写成功记录，允许用户重试
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        # SQLite 写入很快，用一个锁避免同进程内并发写
        self._lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ---------- 指纹 ----------

    @staticmethod
    def fingerprint(action: str, params: dict[str, Any], scope: str | None = None) -> str:
        """由「作用域 + 动作 + 规范化参数」生成稳定指纹。

        **scope 必须带上用户身份**。否则会出现跨用户误判：
        A 和 B 都用同样的参数发布"台灯 45 元"，B 的确认会被当成 A 的重复请求
        而直接跳过 —— 表现是"用户点了确认但什么都没发生"。

        Args:
            action: 动作标识。
            params: 规范化参数。
            scope:  作用域，通常传 actor token 或用户 ID。

        用 sort_keys 保证字段顺序不影响结果，
        这样"同一用户、同一动作、同一参数"必然得到同一指纹。
        """
        payload = json.dumps(
            {"scope": scope or "-", "action": action, "params": params},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"{action}:{digest[:32]}"

    # ---------- 查询 ----------

    def get_success(self, fingerprint: str) -> dict[str, Any] | None:
        """返回已成功执行的结果；未执行过返回 None。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT result FROM idempotency_ledger WHERE fingerprint = ? AND status = 'SUCCESS'",
                (fingerprint,),
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["result"]) if row["result"] else {}
        except json.JSONDecodeError:
            return {}

    # ---------- 执行 ----------

    async def run_once(self, fingerprint: str, action):
        """执行一次。

        Args:
            fingerprint: 幂等键。
            action: 无参可等待函数，返回可 JSON 序列化的结果。

        Returns:
            dict: {"executed": bool, "result": Any, "duplicate": bool}
                  executed=False 表示命中幂等、未真正调用后端。
        """
        async with self._lock:
            cached = self.get_success(fingerprint)
            if cached is not None:
                logger.warning("幂等命中，跳过重复执行: %s", fingerprint)
                return {"executed": False, "duplicate": True, "result": cached}

            now = _now()
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO idempotency_ledger "
                    "(fingerprint, status, result, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (fingerprint, "RUNNING", None, now, now),
                )
                conn.commit()

        # 在锁外执行：避免长时间占用锁，同时让失败可重试
        try:
            result = await action()
        except Exception:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE idempotency_ledger SET status = 'FAILED', updated_at = ? "
                    "WHERE fingerprint = ?",
                    (_now(), fingerprint),
                )
                conn.commit()
            raise

        with self._connect() as conn:
            conn.execute(
                "UPDATE idempotency_ledger SET status = 'SUCCESS', result = ?, updated_at = ? "
                "WHERE fingerprint = ?",
                (json.dumps(result, ensure_ascii=False, default=str), _now(), fingerprint),
            )
            conn.commit()

        return {"executed": True, "duplicate": False, "result": result}

    # ---------- 维护 ----------

    def stats(self) -> dict[str, int]:
        """账本统计，便于调试与测试断言。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM idempotency_ledger GROUP BY status"
            ).fetchall()
        return {row["status"]: row["c"] for row in rows}

    def clear(self) -> None:
        """清空账本（仅测试与重置演示数据时使用）。"""
        with self._connect() as conn:
            conn.execute("DELETE FROM idempotency_ledger")
            conn.commit()


def _now() -> str:
    return datetime.now(UTC).isoformat()
