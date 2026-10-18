-- ============================================================
-- 品类词表（product_type）+ 现有商品回填
--
-- 背景：分类只有 6 个，而买家搜索用的是具体品类词。
-- 《AirPods Pro 2代》的标题里没有"耳机"两个字，所以搜「耳机」命中 0 条。
-- 加一层品类词 + 别名，把词汇缺口从"代码问题"变成"数据问题"。
--
-- 前置：先启动一次后端，让 Hibernate 建出 product_type 表与
--       product.product_type 列，再执行本脚本。
-- 幂等：全部 INSERT IGNORE / 覆盖式 UPDATE，可重复执行。
-- ============================================================

USE login_db;

-- ------------------------------------------------------------
-- 先修一个坑：create_time
--
-- Hibernate 建出来的列是 `datetime(6) NOT NULL`，**没有默认值**。
-- 用 SQL 直接 INSERT 而不写 create_time 时，MySQL 会写入零日期
-- '0000-00-00 00:00:00'；之后 JDBC 驱动读到它就抛
--   DataReadException: Zero date value prohibited
-- 表现是"接口 500"，而且日志里看不出跟品类词有关。
--
-- 所以这里给列加上默认值，任何插入路径都不会再写零日期。
-- ------------------------------------------------------------
ALTER TABLE product_type
    MODIFY create_time datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6);

-- ------------------------------------------------------------
-- 词表
--   aliases 用逗号分隔（中英文逗号都认），**要把短词也写进去**。
--   例：标签是「收纳箱」，但用户会搜「收纳」，所以"收纳"是别名。
-- ------------------------------------------------------------
INSERT IGNORE INTO product_type (category_id, name, aliases, sort_order) VALUES
-- 数码电子 (2)
(2,'耳机','蓝牙耳机,airpods,苹果耳机,有线耳机,耳麦,tws,pods',10),
(2,'键盘','机械键盘,cherry,红轴,轴体,无线键盘,静音键盘',20),
(2,'鼠标','罗技,无线鼠标,游戏鼠标,g304,鼠标',30),
(2,'充电宝','移动电源,充电,充电器,大容量电源',40),
(2,'平板','ipad,平板电脑,苹果平板,matepad,平板',50),
(2,'手机','iphone,手机,安卓机,华为,小米手机',60),
(2,'显示器','屏幕,monitor,显示屏,电竞屏',70),
(2,'相机','单反,微单,ccd,相机',80),

-- 生活用品 (3)
(3,'台灯','护眼灯,led灯,学习灯,小台灯,台灯',10),
(3,'风扇','小风扇,usb风扇,电风扇,桌面风扇,风扇',20),
(3,'床帘','遮光帘,窗帘,床帐,蚊帐,床帘',30),
(3,'收纳箱','收纳盒,整理箱,储物箱,收纳,箱子',40),
(3,'瑜伽垫','垫子,健身垫,运动垫,瑜伽',50),
(3,'水杯','保温杯,杯子,水壶',60),
(3,'衣架','晾衣架,挂衣架,衣架',70),

-- 体育器材 (4)
(4,'自行车','单车,山地车,捷安特,giant,折叠车,折叠自行车,公路车',10),
(4,'电动车','电瓶车,小牛,n1s,电动自行车,电车',20),
(4,'滑板','双翘,双翘板,skateboard,长板',30),
(4,'平衡车','体感车,小米平衡车,ninebot,九号,独轮车',40),
(4,'球拍','羽毛球拍,网球拍,乒乓球拍,球拍',50),
(4,'哑铃','哑铃,杠铃,健身器材',60),

-- 图书教材 (1)：书的"品类"其实是科目
(1,'数学','高数,高等数学,线代,线性代数,微积分,概率论,考研数学',10),
(1,'英语','四级,cet4,六级,雅思,考研英语,词汇书,单词书',20),
(1,'计算机','数据结构,c语言,编程,java,操作系统,计算机网络',30),
(1,'政治','马原,马克思,毛概,政治',40),

-- 服装鞋帽 (5)
(5,'外套','衣服,卫衣,夹克,外套',10),
(5,'鞋','球鞋,运动鞋,板鞋,鞋',20),
(5,'背包','双肩包,书包,背包',30);

-- ------------------------------------------------------------
-- 回填现有商品
-- 注意：真实上线后这一步由"发布时卖家确认 + 管理员审核"产生，
--       这里只是为了让我们现在的 22 件数据能立刻被搜到。
-- ------------------------------------------------------------
UPDATE product SET product_type='自行车' WHERE id IN (11,14);
UPDATE product SET product_type='电动车' WHERE id IN (12);
UPDATE product SET product_type='滑板'   WHERE id IN (13);
UPDATE product SET product_type='平衡车' WHERE id IN (15);

UPDATE product SET product_type='数学'   WHERE id IN (1,4);
UPDATE product SET product_type='英语'   WHERE id IN (2);
UPDATE product SET product_type='计算机' WHERE id IN (3);
UPDATE product SET product_type='政治'   WHERE id IN (5);

UPDATE product SET product_type='平板'   WHERE id IN (6);
UPDATE product SET product_type='鼠标'   WHERE id IN (7);
UPDATE product SET product_type='耳机'   WHERE id IN (8);
UPDATE product SET product_type='充电宝' WHERE id IN (9);
UPDATE product SET product_type='键盘'   WHERE id IN (10,67);

UPDATE product SET product_type='台灯'   WHERE id IN (19,62);
UPDATE product SET product_type='风扇'   WHERE id IN (17);
UPDATE product SET product_type='床帘'   WHERE id IN (16);
UPDATE product SET product_type='收纳箱' WHERE id IN (18);
UPDATE product SET product_type='瑜伽垫' WHERE id IN (20);

-- ------------------------------------------------------------
-- 校验
-- ------------------------------------------------------------
SELECT (SELECT COUNT(*) FROM product_type) AS 品类词数,
       (SELECT COUNT(*) FROM product WHERE product_type IS NOT NULL) AS 已打标商品,
       (SELECT COUNT(*) FROM product) AS 商品总数;
