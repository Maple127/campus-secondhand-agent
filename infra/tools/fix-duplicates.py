# -*- coding: utf-8 -*-
"""把 17 组"重名且同价"的商品改成像是不同人挂的。

真实的二手市场里两个人卖同一本教材很正常，但**同价**就很假。
这里给较新的那条换个价、换个成色描述，让它读起来像另一个人的闲置。
"""

import subprocess
import os

MYSQL = r"D:\Develop\MySQL\MySQL Server 8.0\bin\mysql.exe"

# id -> (新价格, 新成色, 新描述, 名字后缀)
FIX = {
    80:  (880,  "8成新", "左边耳机有轻微使用痕迹，配件齐全", ""),
    88:  (420,  "9成新", "换了静音轴，这个闲置了", ""),
    94:  (105,  "8成新", "脚贴换过，滚轮有点涩", ""),
    114: (75,   "9成新", "用过两次，盒子还在", ""),
    126: (22,   "8成新", "书角有折痕，内页干净", ""),
    132: (8,    "7成新", "封面有点旧，不影响看", ""),
    137: (15,   "8成新", "有几页笔记，铅笔可擦", ""),
    142: (16,   "9成新", "翻过一遍，划了几行重点", ""),
    145: (38,   "8成新", "灯罩有点黄，亮度正常", ""),
    150: (25,   "8成新", "扇叶有灰，洗干净了", ""),
    154: (22,   "8成新", "洗过一次，无破损", ""),
    158: (30,   "7成新", "盖子有裂痕，不影响用", ""),
    162: (16,   "8成新", "用过几次，擦干净了", ""),
    177: (300,  "6成新", "刹车线新换的，车架有划痕", ""),
    178: (240,  "7成新", "折叠扣有点松，能骑", ""),
    183: (1600, "6成新", "电池衰减到35km，其他正常", ""),
    189: (520,  "7成新", "外壳有磕碰，骑行正常", ""),
}

lines = ["USE login_db;"]
for pid, (price, cond, desc, _suffix) in FIX.items():
    lines.append(
        f"UPDATE product SET price={price}, condition_level='{cond}', "
        f"description='{desc}' WHERE id={pid};"
    )
lines.append("SELECT COUNT(*) AS 仍有重名同价 FROM ("
             " SELECT name, price FROM product GROUP BY name, price HAVING COUNT(*)>1"
             ") t;")

sql = "\n".join(lines)
path = r"D:\Develop\AI\deepseek\test2\infra\_fixdup.sql"
with open(path, "w", encoding="utf-8") as f:
    f.write(sql)

env = dict(os.environ, MYSQL_PWD="123456")
r = subprocess.run(
    [MYSQL, "-h", "::1", "-uroot", "--default-character-set=utf8mb4"],
    stdin=open(path, "rb"), capture_output=True, env=env,
)
print(r.stdout.decode("utf-8", "replace"))
print(r.stderr.decode("utf-8", "replace")[:500])
