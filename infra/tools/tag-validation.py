"""品类标签验证：不改代码，纯离线对比两套匹配。

对照：
  A) 现状：LIKE %q% 打在 名称/描述/地点 上（复刻 ProductRepository.search 的行为）
  B) 标签：product_type + aliases 命中，再并上 A 作为兜底

判分：拿"我应该返回哪些商品"当标准答案，算召回与误召回。
测试商品（62 测试小台灯 / 67 测试键盘）已排除，避免污染。
"""

from __future__ import annotations

import asyncio
import sys

import httpx

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = "http://localhost:8081"
SERVICE = "demo-agent-token-local"

# ---------- 打标结果（相当于卖家确认过的 product_type） ----------
TYPE = {
    11: ("自行车", ["单车", "山地车", "捷安特", "giant", "折叠车"]),
    12: ("电动车", ["电瓶车", "小牛", "n1s", "电动自行车"]),
    13: ("滑板", ["双翘", "skateboard", "双翘板"]),
    14: ("自行车", ["单车", "折叠车", "折叠自行车"]),
    15: ("平衡车", ["体感车", "小米平衡车", "ninebot", "九号"]),
    1: ("数学", ["高数", "高等数学", "微积分"]),
    2: ("英语", ["四级", "cet4", "词汇书", "英语四级"]),
    3: ("计算机", ["数据结构", "c语言", "编程书"]),
    4: ("数学", ["线代", "线性代数"]),
    5: ("政治", ["马原", "马克思"]),
    6: ("平板", ["ipad", "平板电脑", "苹果平板"]),
    7: ("鼠标", ["罗技", "g304", "无线鼠标", "游戏鼠标"]),
    8: ("耳机", ["airpods", "蓝牙耳机", "苹果耳机", "pods", "tws"]),
    9: ("充电宝", ["移动电源", "充电器", "电源"]),
    10: ("键盘", ["机械键盘", "cherry", "红轴", "樱桃"]),
    16: ("床帘", ["遮光帘", "窗帘", "床帐"]),
    17: ("风扇", ["小风扇", "usb风扇", "电风扇", "桌面风扇"]),
    18: ("收纳箱", ["收纳盒", "整理箱", "储物箱"]),
    19: ("台灯", ["护眼灯", "led灯", "学习灯"]),
    20: ("瑜伽垫", ["垫子", "健身垫", "运动垫"]),
}

EXCLUDE = {62, 67}  # 测试数据

# ---------- 查询与标准答案（模拟"已经想好要买什么"的买家） ----------
CASES = [
    ("耳机",          {8}),
    ("蓝牙耳机",       {8}),
    ("airpods",       {8}),
    ("键盘",          {10}),
    ("机械键盘",       {10}),
    ("cherry",        {10}),
    ("鼠标",          {7}),
    ("罗技",          {7}),
    ("台灯",          {19}),
    ("自行车",        {11, 14}),
    ("单车",          {11, 14}),
    ("电动车",        {12}),
    ("滑板",          {13}),
    ("平衡车",        {15}),
    ("充电宝",        {9}),
    ("移动电源",       {9}),
    ("平板",          {6}),
    ("ipad",          {6}),
    ("数学",          {1, 4}),
    ("考研数学",       {1, 4}),
    ("英语四级",       {2}),
    ("风扇",          {17}),
    ("瑜伽垫",        {20}),
    ("收纳箱",        {18}),
    ("收纳",          {18}),   # 比标签短：靠别名兜
    ("床帘",          {16}),
    ("线代",          {4}),    # 简称：靠别名兜
    ("高数",          {1}),    # 简称：靠别名兜
]


def like_hit(q: str, p: dict) -> bool:
    """复刻后端：name / description / location 三列 LIKE %q%"""
    q = q.lower()
    blob = " ".join(str(p.get(k) or "") for k in ("name", "description", "location")).lower()
    return q in blob


def tag_hit(q: str, p: dict, two_way: bool = True) -> bool:
    """
    two_way=True：双向包含（查询里有标签词，或查询是标签词的一部分）
    two_way=False：只允许「查询里含标签词」——更保守，不会把「电动自行车」算成「自行车」
    """
    entry = TYPE.get(p["id"])
    if not entry:
        return False
    name, aliases = entry
    qn = q.lower().strip()
    for word in [name, *aliases]:
        w = word.lower()
        if w in qn:
            return True
        if two_way and len(qn) >= 2 and qn in w:
            return True
    return False


async def main() -> None:
    async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
        await c.post(f"{BASE}/doLogin", data={"username": "user01", "password": "pass123"})
        tok = (await c.post(f"{BASE}/api/v1/agent/session",
                            headers={"X-Service-Token": SERVICE},
                            json={"conversationId": "tagtest"})).json()["data"]["actorToken"]
        r = await c.get(f"{BASE}/api/v1/products",
                        params={"size": 50},
                        headers={"X-Actor-Token": tok, "X-Service-Token": SERVICE})
        items = [p for p in r.json()["data"]["items"] if p["id"] not in EXCLUDE]

    print(f"参与评测的商品：{len(items)} 件\n")

    rows = []
    res = {k: {"full": 0, "rec": 0.0, "fp": 0} for k in ("A", "B1", "B2")}

    for q, expect in CASES:
        a = {p["id"] for p in items if like_hit(q, p)}
        # B1 = 标签(双向) ∪ LIKE；B2 = 标签(单向) ∪ LIKE
        b1 = {p["id"] for p in items if tag_hit(q, p, True) or like_hit(q, p)}
        b2 = {p["id"] for p in items if tag_hit(q, p, False) or like_hit(q, p)}

        out = {"A": a, "B1": b1, "B2": b2}
        for k, got in out.items():
            r = len(got & expect) / len(expect)
            fp = len(got - expect)
            res[k]["rec"] += r
            res[k]["fp"] += fp
            if r == 1.0 and fp == 0:
                res[k]["full"] += 1

        ra, rb2 = res["A"]["rec"], res["B2"]["rec"]
        rows.append((q, len(expect), a & expect, a - expect, False))

    # 逐条只打印现状失败 / 两个标签版本有差异的
    print(f"{'查询':<10}{'应得':>4}  {'LIKE':>6}  {'标签双向':>8}  {'标签单向':>8}")
    print("-" * 58)
    for q, expect in CASES:
        a = {p["id"] for p in items if like_hit(q, p)}
        b1 = {p["id"] for p in items if tag_hit(q, p, True) or like_hit(q, p)}
        b2 = {p["id"] for p in items if tag_hit(q, p, False) or like_hit(q, p)}

        def fmt(got):
            miss = len(expect - got)
            fp = len(got - expect)
            s = "100%" if miss == 0 else f"{len(got & expect)}/{len(expect)}"
            if fp:
                s += f" 误{fp}"
            return s

        line = f"{q:<10}{len(expect):>4}  {fmt(a):>6}  {fmt(b1):>8}  {fmt(b2):>8}"
        if a != expect or b1 != b2:
            line += "  <<"
        print(line)

    print("-" * 58)
    for k, label in (("A", "现状 LIKE"), ("B1", "标签 双向"), ("B2", "标签 单向")):
        r = res[k]
        print(f"{label:<12} 完全命中 {r['full']}/{len(CASES)}　"
              f"平均召回 {r['rec']/len(CASES):>5.0%}　误召回 {r['fp']}")


asyncio.run(main())
