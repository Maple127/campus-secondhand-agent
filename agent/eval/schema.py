"""金标准任务集的结构定义与加载。

## 为什么需要这个

在 B 阶段之前，我对 agent"有用"的判断全是主观的。这个模块把判断变成可测的东西：

    同一批任务 → 跑两组（关键词搜索框 / AI 助手）→ 用**确定性规则**判成功
               → 比较成功率、耗时、成本、安全拒绝率

## 判定原则

**判定不交给 LLM。** 让模型给模型打分是循环论证，也无法复现。
每个任务都带一条可程序化验证的规则（`judge`），例如：

  - 找东西   → 期望商品是否出现在结果里
  - 带条件搜 → 返回项是否全部满足条件（价格/分类）
  - 多步任务 → 是否调用了必需的工具集合
  - 写操作   → 是否产生确认卡片、参数是否正确、落库状态是否正确
  - 安全边界 → 是否**没有**执行被禁止的动作

## 任务分类与预期结论

| 分类 | 搜索框 | AI 助手 | 设计意图 |
|---|---|---|---|
| `lookup` 找东西 | **更快更省** | 更慢更贵 | 预期搜索框赢，用来暴露 agent 的负收益区间 |
| `filter` 条件筛选 | 打平或略输 | 略胜 | 多条件组合时人手拆解成本上升 |
| `compound` 多步 | **做不到** | 唯一能完成 | agent 的核心价值区 |
| `write` 写操作 | **做不到** | 唯一能完成 | 需确认 + 落库校验 |
| `boundary` 安全边界 | 做不到（无此概念） | 必须拒绝 | 验证安全底线不是摆设 |
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

TaskCategory = Literal["lookup", "filter", "compound", "write", "boundary"]

#: 判定方式
JudgeKind = Literal[
    "expect_product",  # 期望商品出现在结果中
    "filter_satisfied",  # 结果全部满足条件（或结果为空时视为通过，见 allow_empty）
    "expect_tools",  # 调用了指定工具集合
    "write_effect",  # 产生确认/写入，且参数正确、落库状态正确
    "must_not_call",  # 绝不能调用某些工具
]


@dataclass
class Task:
    """一条评测任务。"""

    id: str
    category: TaskCategory
    message: str
    judge: JudgeKind

    #: 给基线用的"理想关键词"。
    #: 用于构造**对搜索框最有利**的对照条件，避免把基线做得太弱而自欺欺人。
    ideal_keyword: str | None = None

    #: 基线可用的结构化筛选（分类/价格），同样取对基线最有利的配置
    ideal_category: str | None = None
    ideal_max_price: float | None = None

    #: 期望出现在结果中的商品名关键词（judge=expect_product）
    expect_name_contains: list[str] = field(default_factory=list)
    #: 期望结果条数下限
    min_results: int = 1

    #: 结果必须满足的条件（judge=filter_satisfied）
    require_category: str | None = None
    require_max_price: float | None = None
    require_min_price: float | None = None
    #: 允许结果为空（用于"确实没有"的负向任务：如实说没有也算成功）
    allow_empty: bool = False

    #: 必须调用的工具（judge=expect_tools / write_effect）
    expect_tools: list[str] = field(default_factory=list)
    #: 绝不能调用的工具（judge=must_not_call）
    forbid_tools: list[str] = field(default_factory=list)

    #: 写操作校验（judge=write_effect）
    expect_write_tool: str | None = None
    #: 对确认卡片字段的期望（label -> 期望值包含的文本）
    expect_summary_fields: dict[str, str] = field(default_factory=dict)

    #: 备注：这条任务想测什么
    note: str = ""

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Task:
        known = {f for f in Task.__dataclass_fields__}  # type: ignore[attr-defined]
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"任务 {d.get('id')} 含未知字段: {sorted(unknown)}")
        return Task(**d)


@dataclass
class TaskSet:
    tasks: list[Task]
    product_snapshot: list[dict[str, Any]]  # 评测时的商品快照，便于事后复核判定
    known_issues: list[str] = field(default_factory=list)  # 复盘发现的任务集自身缺陷

    def by_category(self) -> dict[str, list[Task]]:
        out: dict[str, list[Task]] = {}
        for t in self.tasks:
            out.setdefault(t.category, []).append(t)
        return out


def load_taskset(path: str | Path) -> TaskSet:
    """从 JSON 加载任务集。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    tasks = [Task.from_dict(d) for d in raw["tasks"]]
    ids = [t.id for t in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("任务 id 存在重复")
    return TaskSet(
        tasks=tasks,
        product_snapshot=raw.get("productSnapshot", []),
        known_issues=raw.get("_knownIssues", []),
    )


def summarize(taskset: TaskSet) -> str:
    """打印任务集构成，用于确认覆盖面。"""
    by_cat = taskset.by_category()
    lines = [f"任务总数: {len(taskset.tasks)}"]
    for cat in ("lookup", "filter", "compound", "write", "boundary"):
        items = by_cat.get(cat, [])
        lines.append(f"  {cat:<9} {len(items):>2} 条")
    return "\n".join(lines)
