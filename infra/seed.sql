-- ============================================================
-- 校园二手交易平台 - 基础种子数据（幂等）
-- 生成方式: mysqldump --no-create-info --complete-insert login_db category school admin
-- 说明: 使用 INSERT IGNORE，可重复执行，不会因主键冲突报错
-- 商品/用户演示数据见 infra/schema-legacy.sql
-- ============================================================
USE login_db;

INSERT IGNORE INTO `category` (`id`, `create_time`, `description`, `name`) VALUES (1,'2026-07-04 17:32:32.539373',NULL,'图书教材');
INSERT IGNORE INTO `category` (`id`, `create_time`, `description`, `name`) VALUES (2,'2026-07-04 17:32:32.547266',NULL,'数码电子');
INSERT IGNORE INTO `category` (`id`, `create_time`, `description`, `name`) VALUES (3,'2026-07-04 17:32:32.557594',NULL,'生活用品');
INSERT IGNORE INTO `category` (`id`, `create_time`, `description`, `name`) VALUES (4,'2026-07-04 17:32:32.565198',NULL,'体育器材');
INSERT IGNORE INTO `category` (`id`, `create_time`, `description`, `name`) VALUES (5,'2026-07-04 17:32:32.578505',NULL,'服装鞋帽');
INSERT IGNORE INTO `category` (`id`, `create_time`, `description`, `name`) VALUES (6,'2026-07-04 17:32:32.594429',NULL,'其他');
INSERT IGNORE INTO `school` (`id`, `name`, `address`) VALUES (1,'清华大学','北京市海淀区双清路30号');
INSERT IGNORE INTO `school` (`id`, `name`, `address`) VALUES (2,'北京大学','北京市海淀区颐和园路5号');
INSERT IGNORE INTO `school` (`id`, `name`, `address`) VALUES (3,'复旦大学','上海市杨浦区邯郸路220号');
INSERT IGNORE INTO `school` (`id`, `name`, `address`) VALUES (4,'上海交通大学','上海市闵行区东川路800号');
INSERT IGNORE INTO `school` (`id`, `name`, `address`) VALUES (5,'浙江大学','浙江省杭州市西湖区余杭塘路866号');
INSERT IGNORE INTO `school` (`id`, `name`, `address`) VALUES (6,'南京大学','江苏省南京市栖霞区仙林大道163号');
INSERT IGNORE INTO `school` (`id`, `name`, `address`) VALUES (7,'武汉大学','湖北省武汉市武昌区八一路299号');
INSERT IGNORE INTO `school` (`id`, `name`, `address`) VALUES (8,'中山大学','广东省广州市海珠区新港西路135号');
INSERT IGNORE INTO `school` (`id`, `name`, `address`) VALUES (9,'四川大学','四川省成都市武侯区一环路南一段24号');
INSERT IGNORE INTO `school` (`id`, `name`, `address`) VALUES (10,'西安交通大学','陕西省西安市碑林区咸宁西路28号');
INSERT IGNORE INTO `admin` (`id`, `create_time`, `password`, `username`) VALUES (1,'2026-07-04 17:32:32.506952','admin','admin');
