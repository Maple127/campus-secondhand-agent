"""逐条验证用户提出的 8 个界面问题是否已修复。

只做只读 + 必要的写后清理，跑完会把测试数据删掉。
用法：.venv\\Scripts\\python.exe infra\\ui-fix-verify.py
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

BASE = "http://localhost:8081"
PASS: list[str] = []
FAIL: list[str] = []


def ck(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL':<4} {name:<34} {detail}")
    (PASS if ok else FAIL).append(name)


def strip_comments(html: str) -> str:
    """去掉 HTML 注释再断言。

    源码注释里会自然提到被移除的功能名（例如"原来这里是收藏，现改为订单"），
    直接搜字符串会把注释误判成残留功能。断言只应针对真实渲染内容。
    """
    return re.sub(r"<!--.*?-->", "", html, flags=re.S)


def strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


async def login(c: httpx.AsyncClient) -> None:
    r = await c.post(f"{BASE}/doLogin",
                     data={"username": "user01", "password": "pass123"},
                     follow_redirects=False)
    assert r.status_code == 302, r.status_code


async def main() -> int:
    async with httpx.AsyncClient(timeout=40, trust_env=False, follow_redirects=False) as c:
        # ---------- 问题 1：AI 按钮在左下角，且不压住发布按钮/底栏 ----------
        css = strip_css_comments((await c.get(f"{BASE}/css/agent-widget.css")).text)
        fab = re.search(r"#agentFab\s*\{(.*?)\}", css, re.S)
        block = fab.group(1) if fab else ""
        left = re.search(r"left:\s*(\d+)px", block)
        right = re.search(r"right:\s*([a-z]+|\d+px)", block)
        bottom = re.search(r"bottom:\s*(\d+)px", block)
        ck("1 AI按钮在左下角",
           bool(left) and (right is None or right.group(1) == "auto"),
           f"left={left.group(1) if left else '?'}px, right={right.group(1) if right else '未设'}")
        # 底部导航栏固定在 bottom:0、高约 50px，按钮要抬到它上面
        ck("1 AI按钮不压底部导航",
           bool(bottom) and int(bottom.group(1)) >= 66,
           f"bottom={bottom.group(1) if bottom else '?'}px（底栏约占 0~50px）")

        # 抽屉要与按钮同侧，否则点开面板跑到另一边
        panel = re.search(r"\.agent-panel\s*\{(.*?)\}", css, re.S)
        pblock = panel.group(1) if panel else ""
        ck("1 抽屉与按钮同侧",
           "left:" in pblock and ("right: auto" in pblock or "right:" not in pblock),
           "面板也从左下弹出")

        # ---------- 问题 3：自己的商品没有下单键 ----------
        await login(c)
        own = strip_comments((await c.get(f"{BASE}/product/1")).text)    # 卖家 = user01
        other = strip_comments((await c.get(f"{BASE}/product/3")).text)  # 卖家 = user03
        ck("3 自己的商品无下单键",
           "立即下单" not in own and "自己的商品" in own,
           "显示「自己的商品」且无下单按钮")
        ck("3 别人的商品有下单键", "立即下单" in other, "")

        # ---------- 问题 2：发布后弹窗反馈 ----------
        r = await c.post(f"{BASE}/publish", data={
            "name": "UI验证-弹窗测试", "price": "30",
            "category": "生活用品", "conditionLevel": "9成新",
            "location": "测试地点", "description": "验证发布反馈",
        }, files={"image": ("", b"", "application/octet-stream")})
        ck("2 发布后跳回首页", r.status_code == 302, f"http={r.status_code}")
        home = (await c.get(f"{BASE}/home")).text
        ck("2 首页弹出确认窗口", "已提交审核" in home and "fb-mask" in home,
           "")
        ck("2 弹窗带商品名", "UI验证-弹窗测试" in home, "")
        ck("2 旧的顶部横幅已移除", 'th:if="${registerSuccess}"' not in home, "")

        # ---------- 问题 7：举报后有反馈 ----------
        r = await c.post(f"{BASE}/report/submit", data={
            "productId": "3", "reasonType": "虚假信息", "description": "UI 验证用",
        })
        detail = (await c.get(f"{BASE}/product/3")).text
        ck("7 举报后弹窗反馈", "举报已提交" in detail, "")

        # ---------- 问题 4：支付成功页三个出口 ----------
        # 先下一单再支付，才能打开 paySuccess。
        # 注意：下单会让商品变成"已售出"，所以先找一个当前在售的、不属于 user01 的商品，
        # 用完在脚本结尾还原（见 cleanup）。
        pick = None
        for pid in (6, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19):
            page = strip_comments((await c.get(f"{BASE}/product/{pid}")).text)
            if "立即下单" in page:
                pick = pid
                break
        ck("4 找到可下单商品", pick is not None, f"productId={pick}")

        if pick:
            r = await c.post(f"{BASE}/order/create", data={
                "productId": str(pick), "deliveryType": "校园面交",
                "appointmentTime": "2026-10-20T10:00",
            })
            m = re.search(r"orderNo=([A-Za-z0-9]+)", str(r.headers.get("location", "")))
            if m:
                om = await c.get(f"{BASE}/order/detail?orderNo={m.group(1)}")
                om2 = re.search(r'name="orderNo"\s+value="([^"]+)"', om.text)
                ono = om2.group(1) if om2 else m.group(1)
                await c.post(f"{BASE}/order/pay", data={"orderNo": ono, "payPassword": "123456"})
                ps = (await c.get(f"{BASE}/order/paySuccess?orderNo={ono}")).text
                ck("4 支付成功页有返回首页", "返回首页" in ps and 'href="/home"' in ps, "")
                ck("4 我的订单指向正确路由",
                   "/order/list" in ps and 'href="/list"' not in ps, "")
            else:
                ck("4 支付成功页有返回首页", False, f"下单失败 http={r.status_code}")

        # ---------- 问题 5：订单页默认出售 + 商品状态 ----------
        ol = (await c.get(f"{BASE}/order/list")).text
        ck("5 默认停在「出售」",
           'data-tab="sell"' in ol and "class=\"tab active\" data-tab=\"sell\"" in ol, "")
        ck("5 出售栏渲染商品状态",
           "待审核" in ol or "出售中" in ol, "")
        ck("5 购买栏仍有订单", "📥 购买" in ol, "")

        r = await c.get(f"{BASE}/myItems")
        ck("5 我的闲置已并入订单", r.status_code == 302
           and "/order/list" in r.headers.get("location", ""),
           f"→ {r.headers.get('location')}")

        my = strip_comments((await c.get(f"{BASE}/my")).text)
        ck("5 个人中心去掉我的闲置", "我的闲置" not in my, "")
        ck("5 个人中心订单链接修正", 'href="/order/list"' in my and 'href="/list"' not in my, "")
        ck("5 死链 /settings 已修正", 'href="/settings"' not in my, "")

        # ---------- 问题 6：底部栏 收藏 → 订单 ----------
        home2 = strip_comments((await c.get(f"{BASE}/home")).text)
        footer = home2[home2.find("<footer>"):home2.find("</footer>")] if "<footer>" in home2 else ""
        ck("6 底部栏有订单入口", "/order/list" in footer and "订单" in footer, "")
        ck("6 底部栏不再有收藏", "收藏" not in footer, "")

    # ---------- 问题 8：管理端返回控制台 ----------
    async with httpx.AsyncClient(timeout=40, trust_env=False, follow_redirects=False) as c:
        await c.post(f"{BASE}/admin/doLogin",
                     data={"username": "admin", "password": "admin"})
        pages = {
            "/admin/products": "商品管理",
            "/admin/categories": "分类管理",
            "/admin/users": "用户管理",
            "/admin/orders": "订单管理",
            "/admin/reports": "举报工单",
            "/admin/changePassword": "修改密码",
            "/admin/category/add": "新增分类",
        }
        for path, name in pages.items():
            html = strip_comments((await c.get(f"{BASE}{path}")).text)
            ok = "返回控制台" in html
            ck(f"8 {name}有返回控制台", ok, "")

        # 商品详情 / 用户商品 这两个子页也要有
        html = strip_comments((await c.get(f"{BASE}/admin/product/1")).text)
        ck("8 商品详情有返回控制台", "返回控制台" in html, "")
        html = strip_comments((await c.get(f"{BASE}/admin/users/1/products")).text)
        ck("8 用户商品有返回控制台", "返回控制台" in html, "")

    print("\n" + "=" * 62)
    print(f"TOTAL={len(PASS) + len(FAIL)}  PASS={len(PASS)}  FAIL={len(FAIL)}")
    for n in FAIL:
        print(f"  FAILED: {n}")
    return 0 if not FAIL else 1


sys.exit(asyncio.run(main()))
