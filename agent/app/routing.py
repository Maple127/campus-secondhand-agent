"""显式策略路由。

## 为什么要它

现在的分流是**隐式**的：模型自己决定调不调工具、调几次。这带来三个问题：

1. **不可观测**：事后没法回答"这次请求走了哪条路"
2. **不可控**：一句"有没有耳机"也可能触发多轮工具调用
3. **不可测**：想优化某条路径，却分不清哪次走了哪条

评测早就告诉我们：**纯检索场景用 agent 是负收益**（慢、贵、成功率只高一点）。
但那个结论一直只写在文档里，产品上没有任何机制去落实它。
显式路由就是把那个结论变成代码。

## 三条路，不是五条

参考实现（Adaptive-RAG）有 5 条：DIRECT/SINGLE/MULTI/AGENT/REFUSE。
它是知识库客服，有"多跳政策问题"这种真实场景。

我们没有：商品检索没有"多跳"的概念，只有一个查询词加若干筛选项。
硬套五条就是为架构而架构。所以只留三条：

    REFUSE  越权、注入、明显超范围
    FAST    一次结构化检索就能回答（"100 以内有什么耳机"）
    AGENT   需要多步、需要写操作、需要跨工具判断

## 规则是地板和天花板，模型在中间

这是从 `_research/Adaptive-rag-2/app/retrieval/adaptive.py` 学到的设计：
先算规则结论，再（可选地）让模型判断，但规则可以否决模型。

我们这一步**完全用规则**，不调模型：

- 路由本身调一次模型，就抵消了 FAST 省下的时间
- 规则是纯函数，可以脱网测（40+ 条用例，无需 API Key）
- 判错了有兜底：FAST 抽不出关键词或检索为空就退回 AGENT

将来若要接模型判断，接口已留好（`RouteDecision.source` 字段）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.guardrails import GuardrailError, detect_prompt_injection

STRATEGY_REFUSE = "REFUSE"
STRATEGY_FAST = "FAST"
STRATEGY_AGENT = "AGENT"


@dataclass(frozen=True)
class RouteDecision:
    """一次路由的结论。"""

    strategy: str
    """REFUSE / FAST / AGENT"""

    reason: str
    """为什么这么判。写进日志和响应，便于事后归因。"""

    source: str = "rule"
    """rule / model —— 目前只有 rule，留字段是为了将来接模型判断。"""


#: 写操作的强信号。命中就必须走 AGENT：这些动作需要人工确认，
#: 而确认链路只存在于 agent 的写工具里，FAST 路径没有。
_WRITE_CUES = (
    "发布",
    "挂出去",
    "上架",
    "下架",
    "删掉",
    "删除",
    "改价",
    "改成",
    "调价",
    "降价",
    "下单",
    "买下",
    "取消订单",
    "取消",
    "举报",
    "投诉",
)

#: 多步 / 条件推理的信号。出现就说明不是"一次检索"能解决的。
_MULTI_STEP_CUES = (
    "然后",
    "接着",
    "顺便",
    "再帮",
    "再找",
    "另外",
    "如果",
    "要是",
    "假如",
    "否则",
    "对比",
    "比较一下",
    "哪个更",
    "哪个好",
    "差别",
    "分别",
    "各自的",
)

#: 明显超出平台范围的话题。用正则而不是子串，因为中间常夹字
#: （"帮我写个 Python 程序"里「写」和「程序」不挨着）。
_OUT_OF_SCOPE_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"写(个|一个|段)?.{0,8}(程序|脚本|代码|函数)",
        r"(翻译|润色).{0,6}(文章|句子|段落)",
        r"写.{0,4}(作文|论文|报告)",
        r"(数学|物理|化学)(题|作业)",
        r"(股票|基金|彩票|币圈)",
        r"(天气|气温|下雨)",
    )
)

#: 价格上界："100 以内""200以下""不超过 300"
_MAX_PRICE_PATTERNS = (
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|块)?\s*(?:以内|以下|之内|封顶)"),
    re.compile(r"不超过\s*(\d+(?:\.\d+)?)"),
    re.compile(r"预算\s*(?:是|为|大概)?\s*(\d+(?:\.\d+)?)"),
    re.compile(r"低于\s*(\d+(?:\.\d+)?)"),
)

#: 价格下界："200 以上""高于 100"
_MIN_PRICE_PATTERNS = (
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|块)?\s*(?:以上|往上)"),
    re.compile(r"高于\s*(\d+(?:\.\d+)?)"),
    re.compile(r"至少\s*(\d+(?:\.\d+)?)"),
)

#: 检索时要剥掉的口语词。它们会把关键词污染成"想买个"这种没法匹配的东西。
#:
#: **不要**把单字量词（个/件/台/部/把/点）放进来：
#: 「台灯」会被拆成「灯」，「键盘」会被拆成「键」。单个汉字做停用词，
#: 收益极小，破坏复合词的概率极高。
_STOPWORDS = (
    "有没有",
    "看看有没有",
    "看看",
    "有卖",
    "有吗",
    "我想买",
    "我想",
    "想买",
    "想收",
    "想找",
    "帮我",
    "请问",
    "一下",
    "多少钱",
    "什么价",
    "价格",
    "二手",
    "闲置",
    "平台",
    "便宜",
    "推荐",
    "什么",
    "哪些",
    "哪几",
    "多少",
    "的",
    "了",
    "吗",
    "呢",
    "啊",
    "吧",
)

#: 关键词最短长度。2 是因为单字（"灯""键"）几乎必然误召回。
_MIN_KEYWORD_LEN = 2


def route(message: str) -> RouteDecision:
    """纯规则路由。不调模型，不碰网络。"""
    text = (message or "").strip()
    if not text:
        return RouteDecision(STRATEGY_REFUSE, "空输入")

    # ① 注入 / 越权优先 —— 这类请求不该进入任何业务路径
    try:
        detect_prompt_injection(text)
    except GuardrailError as exc:
        return RouteDecision(STRATEGY_REFUSE, f"护栏命中：{exc.code}")

    # ② 明显超出平台范围
    if any(p.search(text) for p in _OUT_OF_SCOPE_PATTERNS):
        return RouteDecision(STRATEGY_REFUSE, "超出平台范围")

    # ③ 写操作必须走 AGENT（需要人工确认链路）
    for cue in _WRITE_CUES:
        if cue in text:
            return RouteDecision(STRATEGY_AGENT, f"写操作信号：{cue}")

    # ④ 多步 / 条件推理
    for cue in _MULTI_STEP_CUES:
        if cue in text:
            return RouteDecision(STRATEGY_AGENT, f"多步信号：{cue}")

    # ⑤ 长输入通常包含多个诉求
    if len(text) > 60:
        return RouteDecision(STRATEGY_AGENT, "输入较长，可能包含多个诉求")

    # ⑥ 剩下的按"一次检索能不能答"来判
    if extract_keyword(text):
        return RouteDecision(STRATEGY_FAST, "单一检索请求")

    return RouteDecision(STRATEGY_AGENT, "无法抽取检索词")


def extract_keyword(message: str) -> str:
    """从口语化提问里抽出检索词。

    做法很土但可解释：先剥掉价格表达和口语词，剩下的当关键词。
    抽不出来就返回空串，调用方据此退回 AGENT —— 宁可慢，不能答错。
    """
    text = message or ""

    # 先去掉价格表达，避免"100"被当成关键词
    for pattern in _MAX_PRICE_PATTERNS + _MIN_PRICE_PATTERNS:
        text = pattern.sub(" ", text)
    text = re.sub(r"\d+\s*[-~到]\s*\d+", " ", text)

    # 长词优先，避免"看看有没有"被"看看"先切掉一半
    for word in sorted(_STOPWORDS, key=len, reverse=True):
        text = text.replace(word, " ")

    # 只保留中英文与数字
    text = re.sub(r"[^\u4e00-\u9fffa-zA-Z0-9]+", " ", text)
    parts = [p for p in text.split() if len(p) >= _MIN_KEYWORD_LEN]
    if not parts:
        return ""

    # 取最长片段；等长时取第一个（保持输入顺序的稳定行为）
    return max(parts, key=len)


def extract_price_range(message: str) -> tuple[float | None, float | None]:
    """抽出价格区间。抽不到就是 (None, None)，表示不限。"""
    text = message or ""

    # 先看有没有 "50-100" 这种区间写法
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-~到]\s*(\d+(?:\.\d+)?)", text)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return (min(a, b), max(a, b))

    lo = hi = None
    for pattern in _MAX_PRICE_PATTERNS:
        m = pattern.search(text)
        if m:
            hi = float(m.group(1))
            break
    for pattern in _MIN_PRICE_PATTERNS:
        m = pattern.search(text)
        if m:
            lo = float(m.group(1))
            break
    return lo, hi


__all__ = [
    "STRATEGY_AGENT",
    "STRATEGY_FAST",
    "STRATEGY_REFUSE",
    "RouteDecision",
    "extract_keyword",
    "extract_price_range",
    "route",
]
