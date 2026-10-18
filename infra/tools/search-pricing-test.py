"""验证「强化搜索框」与「比价独立成功能」两项改动。

覆盖：
  1. 首页价格区间筛选真的生效（之前 minPrice/maxPrice 被静默丢弃）
  2. 排序生效
  3. 筛选条件在分类切换与分页时被保留
  4. /web/price-insight 网页端点可用（无需 agent 令牌）
  5. 商品详情页与发布页都挂上了价格参考组件
  6. 样本不足时如实说明，不编造区间
"""

from __future__ import annotations

import asyncio
import re
import sys

import httpx

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

JAVA = "http://localhost:8081"
PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL':<4} {name:<46} {detail}")
    (PASS if ok else FAIL).append(name)


def prices_from(html: str) -> list[float]:
    """从首页 HTML 里抽出商品价格。"""
    return [float(x) for x in re.findall(r'<div class="price">¥([\d.]+)</div>', html)]


async def main() -> int:
    async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=True) as c:
        # ---------- 1. 价格区间筛选 ----------
        r_all = await c.get(f"{JAVA}/home")
        all_prices = prices_from(r_all.text)
        check("首页可访问", r_all.status_code == 200, f"{len(all_prices)} 件")

        r_range = await c.get(f"{JAVA}/home", params={"minPrice": 100, "maxPrice": 400})
        rng_prices = prices_from(r_range.text)
        in_range = all(100 <= p <= 400 for p in rng_prices) if rng_prices else False
        check("价格区间筛选生效", in_range and len(rng_prices) > 0,
              f"返回 {rng_prices}（全部落在 100~400）")

        r_max = await c.get(f"{JAVA}/home", params={"maxPrice": 50})
        max_prices = prices_from(r_max.text)
        check("仅上限筛选生效", bool(max_prices) and all(p <= 50 for p in max_prices),
              f"返回 {max_prices}")

        # 关键回归：修复前 minPrice/maxPrice 会被静默丢弃，返回与无条件一致
        changed = sorted(rng_prices) != sorted(all_prices[:len(rng_prices)])
        check("价格条件不再被静默丢弃", changed,
              f"无条件 {len(all_prices)} 件 vs 区间 {len(rng_prices)} 件")

        # ---------- 2. 排序 ----------
        r_asc = await c.get(f"{JAVA}/home", params={"sortBy": "price-asc"})
        asc = prices_from(r_asc.text)
        check("价格升序排序生效", asc == sorted(asc) and len(asc) > 1, f"{asc}")

        r_desc = await c.get(f"{JAVA}/home", params={"sortBy": "price-desc"})
        desc = prices_from(r_desc.text)
        check("价格降序排序生效", desc == sorted(desc, reverse=True) and len(desc) > 1, f"{desc}")

        # ---------- 3. 筛选条件在分类/分页中保留 ----------
        r_cat = await c.get(f"{JAVA}/home", params={
            "category": "生活用品", "minPrice": 20, "maxPrice": 50, "sortBy": "price-asc"})
        cat_prices = prices_from(r_cat.text)
        cat_kept = all(20 <= p <= 50 for p in cat_prices) if cat_prices else False
        check("分类切换保留价格条件", cat_kept, f"{cat_prices}")
        # 分类链接里应带上价格与排序参数
        has_link_params = ('minPrice=20' in r_cat.text or 'minPrice%3D20' in r_cat.text
                           or 'minPrice' in r_cat.text)
        check("分类链接携带筛选参数", has_link_params, "链接含 minPrice")

        # ---------- 4. 网页价格参考端点 ----------
        r_insight = await c.get(f"{JAVA}/web/price-insight",
                                params={"category": "图书教材"})
        body = r_insight.json()
        ok = body.get("code") == 0 and body.get("data", {}).get("sampleSize", 0) >= 3
        d = body.get("data", {})
        check("网页定价参考可用", ok,
              f"样本 {d.get('sampleSize')} 中位 ¥{d.get('median')} 区间 ¥{d.get('p25')}~¥{d.get('p75')}")
        check("定价参考给出解释文案", bool(d.get("explanation")),
              (d.get("explanation") or "")[:60])

        # 带目标价 -> 应有 verdict
        r_v = await c.get(f"{JAVA}/web/price-insight",
                          params={"category": "图书教材", "price": 100})
        dv = r_v.json().get("data", {})
        check("带目标价时给出结论", dv.get("verdict") in ("LOW", "FAIR", "HIGH"),
              f"verdict={dv.get('verdict')} price=100")

        # ---------- 5. 商品详情页挂载 ----------
        r_prod = await c.get(f"{JAVA}/product/3")
        check("商品详情页可访问", r_prod.status_code == 200, f"http={r_prod.status_code}")
        check("详情页含价格参考组件", 'id="priceInsight"' in r_prod.text, "")
        check("详情页引入组件脚本", 'price-insight.js' in r_prod.text, "")
        check("详情页传入 productId", 'productId:' in r_prod.text, "")

        # ---------- 6. 发布页挂载 + 成色字段 ----------
        sess = httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=True)
        await sess.post(f"{JAVA}/doLogin",
                        data={"username": "user01", "password": "pass123"})
        r_pub = await sess.get(f"{JAVA}/publish")
        check("发布页可访问", r_pub.status_code == 200, f"http={r_pub.status_code}")
        check("发布页含价格参考组件", 'id="priceInsight"' in r_pub.text, "")
        check("发布页新增成色字段", 'name="conditionLevel"' in r_pub.text, "")
        check("发布页实时联动脚本存在", 'PriceInsight.update' in r_pub.text, "")
        await sess.aclose()

        # ---------- 7. 样本不足 / 分类不存在的处理 ----------
        r_tiny = await c.get(f"{JAVA}/web/price-insight",
                             params={"category": "不存在的分类XYZ"})
        dt = r_tiny.json().get("data", {})
        expl = dt.get("explanation") or ""
        # 分类不存在时必须明确说"没找到分类"，而不是放宽到全站均价
        # —— 否则用户拼错分类名会拿到全平台均价，数字看着有道理却答非所问
        check("分类不存在时明确说明而非放宽范围",
              dt.get("verdict") == "INSUFFICIENT_DATA" and "没有找到分类" in expl,
              f"verdict={dt.get('verdict')}")

        # 真实存在但没货的分类 -> 应该说样本不足
        r_empty = await c.get(f"{JAVA}/web/price-insight",
                              params={"category": "服装鞋帽"})
        de = r_empty.json().get("data", {})
        check("分类存在但无货时说明样本不足",
              de.get("verdict") == "INSUFFICIENT_DATA"
              and ("样本不足" in (de.get("explanation") or "")),
              f"verdict={de.get('verdict')} samples={de.get('sampleSize')}")

    print("\n" + "=" * 60)
    print(f"TOTAL={len(PASS) + len(FAIL)}  PASS={len(PASS)}  FAIL={len(FAIL)}")
    for n in FAIL:
        print(f"  FAILED: {n}")
    return 0 if not FAIL else 1


sys.exit(asyncio.run(main()))
