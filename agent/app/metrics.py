"""进程内轻量指标。

## 为什么不用 Prometheus

这个项目是单实例 demo，引入指标服务器只会让依赖变重。
真正需要的是**回答几个具体问题**：

  · 一次对话花多少 token？
  · 压缩省了多少？
  · 重试触发了多少次、救回来多少？
  · 工具报错多少次？

所以这里只放计数器，用 `/api/metrics` 以 JSON 暴露，评测脚本直接读。

## 线程安全

CPython 下 asyncio 单线程，`+=` 之间没有 await，不会被打断。
如果将来多线程或多 worker 部署，这里必须换成外部存储 —— 届时的正确做法
不是加锁，而是换成 Redis/Prometheus，因为**多进程之间的计数天然不共享**。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Metrics:
    # ---- 对话与 token ----
    turns: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    llm_calls: int = 0

    # ---- 上下文压缩 ----
    compactions: int = 0
    """触发压缩的次数"""
    tokens_saved_by_compaction: int = 0
    """压缩前后的估算 token 差（估算值，不是计费值）"""
    compaction_failures: int = 0
    """压缩失败次数（失败时退化为不压缩，不阻断对话）"""

    # ---- 后端重试 ----
    retries: int = 0
    retry_success: int = 0
    retry_exhausted: int = 0

    # ---- 工具与闸门 ----
    tool_calls: int = 0
    tool_errors: int = 0
    empty_search_blocks: int = 0
    """被空结果闸门拦下的第 3 次搜索"""

    def record_turn(self, tokens_in: int, tokens_out: int) -> None:
        self.turns += 1
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out

    def record_compaction(self, saved: int) -> None:
        self.compactions += 1
        self.tokens_saved_by_compaction += max(0, saved)

    def snapshot(self) -> dict[str, int]:
        return asdict(self)

    def reset(self) -> None:
        for f in self.__dataclass_fields__:
            setattr(self, f, 0)


#: 全局单例。测试里用 reset() 隔离。
METRICS = Metrics()

__all__ = ["METRICS", "Metrics"]
