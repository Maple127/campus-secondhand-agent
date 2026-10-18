"""卖家侧实验：一次手动体检，不做任何代码改动。

要回答三个问题：
  1. 现有 agent（只有买家工具）拿到"帮我挂出去"会怎样？
  2. 如果给一个卖家侧 prompt + 我们已有的分类统计，产出质量够不够用？
  3. 价格建议靠不靠谱（这是闲鱼翻车的点）。

用法：.venv\\Scripts\\python.exe infra\\seller-side-test.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import sys

import httpx

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = "http://localhost:8081"
AGENT = "http://127.0.0.1:8090"
SERVICE = "demo-agent-token-local"
# 凭据路径不写死：优先环境变量，其次用户目录
CRED = Path(
    os.environ.get("DSH_CREDENTIALS")
    or (Path.home() / ".dsh" / "credentials.yaml")
)


def read_key() -> str:
    raw = open(CRED, encoding="utf-8").read()
    m = re.search(r'DEEPSEEK_API_KEY:\s*"?([^"\r\n]+)"?', raw)
    return m.group(1).strip() if m else ""


# 卖家真实能给的信息：一句话 + 成色 + 分类。没有标题、没有描述、没有价格。
ITEMS = [
    {
        "label": "台灯",
        "raw": "宿舍搬走清东西，一个用了半年的小台灯，9成新，还能用",
        "category": "生活用品",
        "condition": "9成新",
    },
    {
        "label": "键盘",
        "raw": "一把机械键盘，8成新，声音有点大想换个静音的所以出掉",
        "category": "数码电子",
        "condition": "8成新",
    },
]

SELLER_PROMPT = """你是一个校园二手平台的「发布助手」。卖家往往只说一句话，你要把它变成一条**能卖出去**的挂牌。

你只能基于卖家提供的信息和平台统计，**不要编造卖家没说过的规格**（型号、内存、轴体、尺寸等）。
无法确定的，就写"具体型号可私聊确认"。

平台给的价格统计（同分类样本）会一并给你。请据此给出定价建议，并明确说明依据。

输出严格用这个格式（不要多余的话）：

【标题】
（20 字以内，含关键卖点，不用"出售/低价"这类词）

【描述】
（3~5 行，写清楚：什么东西、什么成色、为什么卖、交易方式。让买家敢下单）

【定价】
建议价：¥___
可接受区间：¥___ ~ ¥___
理由：（一句话，引用平台统计）

【风险提示】
（一句话，指出卖家没提供但买家一定会问的信息）
"""


def extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


async def main() -> None:
    async with httpx.AsyncClient(timeout=60, trust_env=False, follow_redirects=False) as local:
        await local.post(f"{BASE}/doLogin",
                         data={"username": "user01", "password": "pass123"})
        tok = await local.post(f"{BASE}/api/v1/agent/session",
                               headers={"X-Service-Token": SERVICE},
                               json={"conversationId": "seller-test"})
        actor = tok.json()["data"]["actorToken"]

        # ---------- 1. 现有 agent 面对"帮我挂出去" ----------
        print("=" * 66)
        print("【实验 A】现有 agent（只有买家工具）")
        print("=" * 66)
        r = await local.post(f"{AGENT}/api/chat",
                             headers={"X-Actor-Token": actor},
                             json={"message": "帮我把这个挂出去：宿舍搬走清东西，一个用了半年的小台灯，9成新，还能用",
                                   "conversationId": "seller-a"})
        d = r.json()
        print("调用工具:", d.get("toolCalls") or "无")
        print("回复:", (d.get("reply") or "")[:600])

        # ---------- 2. 理想卖家侧 prompt ----------
        print()
        print("=" * 66)
        print("【实验 B】卖家侧 prompt + 平台统计")
        print("=" * 66)

        stats = {}
        for it in ITEMS:
            s = await local.get(f"{BASE}/web/price-insight",
                                params={"category": it["category"],
                                        "condition": it["condition"]})
            stats[it["label"]] = s.json()["data"]

        key = read_key()
        async with httpx.AsyncClient(timeout=120, trust_env=True) as llm:
            for it in ITEMS:
                st = stats[it["label"]]
                brief = (
                    f"卖家原话：{it['raw']}\n"
                    f"分类：{it['category']}　成色：{it['condition']}\n"
                    f"平台同分类统计：样本 {st['sampleSize']} 件，"
                    f"最低 ¥{st['min']}，中位价 ¥{st['median']}，最高 ¥{st['max']}，"
                    f"常见区间 ¥{st['p25']} ~ ¥{st['p75']}"
                )
                resp = await llm.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": "deepseek-chat",
                          "messages": [{"role": "system", "content": SELLER_PROMPT},
                                       {"role": "user", "content": brief}],
                          "temperature": 0.3},
                )
                out = resp.json()["choices"][0]["message"]["content"]
                print(f"\n----- {it['label']} -----")
                print(f"卖家原话：{it['raw']}")
                print(f"同分类统计：样本{st['sampleSize']}　中位¥{st['median']}　"
                      f"区间¥{st['p25']}~¥{st['p75']}")
                print()
                print(out.strip())


asyncio.run(main())
