-- ============================================================
-- 校园二手交易 数据库初始化脚本
-- ============================================================
CREATE DATABASE IF NOT EXISTS login_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;
USE login_db;

-- ------------------------------------------------------------
-- 用户表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    username VARCHAR(50) NOT NULL UNIQUE COMMENT '用户名',
    password VARCHAR(255) NOT NULL COMMENT '密码',
    school VARCHAR(100) COMMENT '学校',
    grade VARCHAR(20) COMMENT '年级',
    phone VARCHAR(20) COMMENT '手机号',
    shipping_address VARCHAR(255) COMMENT '收货地址',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
) ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_unicode_ci;

INSERT INTO users (username, password, school, grade, phone, shipping_address) VALUES
('user01', 'pass123', '清华大学', '大三', '13000000001', '北京市海淀区清华大学'),
('user02', 'pass123', '北京大学', '大二', '13100000002', '北京市海淀区北京大学'),
('user03', 'pass123', '浙江大学', '大四', '13200000003', '杭州市浙大路38号'),
('user04', 'pass123', '复旦大学', '研一', '13300000004', '上海市杨浦区邯郸路220号'),
('user05', 'pass123', '南京大学', '大一', '13400000005', '南京市鼓楼区汉口路22号'),
('user06', 'pass123', '武汉大学', '大三', '13500000006', '武汉市武昌区珞珈山路16号'),
('user07', 'pass123', '中山大学', '大二', '13600000007', '广州市海珠区新港西路135号'),
('user08', 'pass123', '四川大学', '大四', '13700000008', '成都市武侯区科华北路62号'),
('user09', 'pass123', '西安交通大学', '研二', '13800000009', '西安市碑林区咸宁西路28号'),
('user10', 'pass123', '哈尔滨工业大学', '大一', '13900000010', '哈尔滨市南岗区西大直街92号'),
('alice', 'alice123', '厦门大学', '大三', '15000000011', '厦门市思明区思明南路422号'),
('bob', 'bob123', '南开大学', '大二', '15100000012', '天津市南开区卫津路94号'),
('carol', 'carol123', '同济大学', '大四', '15200000013', '上海市杨浦区四平路1239号'),
('david', 'david123', '华中科技大学', '研一', '15300000014', '武汉市洪山区珞喻路1037号'),
('emma', 'emma123', '东南大学', '大一', '15500000015', '南京市玄武区四牌楼2号'),
('frank', 'frank123', '天津大学', '大三', '15600000016', '天津市南开区卫津路92号'),
('grace', 'grace123', '山东大学', '大二', '15700000017', '济南市历城区山大南路27号'),
('henry', 'henry123', '吉林大学', '大四', '15800000018', '长春市朝阳区前进大街2699号'),
('iris', 'iris123', '大连理工', '研二', '15900000019', '大连市甘井子区凌工路2号'),
('jack', 'jack123', '中南大学', '大一', '17000000020', '长沙市岳麓区麓山南路932号');

-- ------------------------------------------------------------
-- 学校表（登录时随机分配学校 / 收货地址使用）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS school (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    name VARCHAR(100) NOT NULL COMMENT '学校名称',
    address VARCHAR(255) COMMENT '学校地址'
) ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_unicode_ci;

INSERT INTO school (name, address) VALUES
('清华大学', '北京市海淀区双清路30号'),
('北京大学', '北京市海淀区颐和园路5号'),
('复旦大学', '上海市杨浦区邯郸路220号'),
('上海交通大学', '上海市闵行区东川路800号'),
('浙江大学', '浙江省杭州市西湖区余杭塘路866号'),
('南京大学', '江苏省南京市栖霞区仙林大道163号'),
('武汉大学', '湖北省武汉市武昌区八一路299号'),
('中山大学', '广东省广州市海珠区新港西路135号'),
('四川大学', '四川省成都市武侯区一环路南一段24号'),
('西安交通大学', '陕西省西安市碑林区咸宁西路28号');

-- ------------------------------------------------------------
-- 商品表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    name VARCHAR(255) NOT NULL COMMENT '商品名称',
    description VARCHAR(2000) COMMENT '商品描述',
    price DECIMAL(10,2) COMMENT '价格',
    image VARCHAR(255) COMMENT '图片访问路径',
    category VARCHAR(50) COMMENT '分类：教材、数码、出行、宿舍',
    location VARCHAR(255) COMMENT '交易地点',
    seller_id BIGINT COMMENT '卖家ID',
    seller_name VARCHAR(255) COMMENT '卖家用户名',
    seller_phone VARCHAR(20) COMMENT '卖家电话',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '发布时间'
) ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 种子商品数据（4个分类各5个，共20个）
-- ------------------------------------------------------------
INSERT INTO product (name, description, price, category, location, seller_id, seller_name, seller_phone) VALUES
-- 📚 教材类
('高等数学第七版上下册', '同济大学出版，9成新无笔记', 25.00, '教材', '3号宿舍楼下', 2, 'user01', '13012345678'),
('大学英语四级词汇书', '背完一遍，有少量标注', 10.00, '教材', '图书馆一楼', 3, 'user02', '13112345678'),
('数据结构C语言版', '严蔚敏版，考研用书，品相好', 18.00, '教材', '计算机学院门口', 4, 'user03', '13212345678'),
('线性代数辅导讲义', '李永乐考研辅导讲义，有笔记', 15.00, '教材', '东区食堂', 5, 'user04', '13312345678'),
('马克思主义基本原理概论', '全新未拆封，多买了一本', 20.00, '教材', '快递驿站', 6, 'user05', '13412345678'),
-- 💻 数码类
('iPad Air 4 64G WiFi版', '使用一年，无划痕带笔带壳', 2800.00, '数码', '西区宿舍', 7, 'user06', '15012345678'),
('罗技G304无线鼠标', '轻度使用半年，手感很好', 120.00, '数码', '快递驿站', 8, 'user07', '15112345678'),
('AirPods Pro 2代', '换了安卓手机用不上了', 680.00, '数码', '南门星巴克', 9, 'user08', '15212345678'),
('小米移动电源20000mAh', '全新未拆，朋友送的用不上', 89.00, '数码', '东区超市门口', 10, 'user09', '15312345678'),
('机械键盘 Cherry红轴', '毕业清宿舍，正品行货', 200.00, '数码', '北门菜鸟驿站', 11, 'user10', '15412345678'),
-- 🚲 出行类
('捷安特山地自行车', '骑了两年，变速正常刹车灵', 350.00, '出行', '车棚北侧', 12, 'alice', '17012345678'),
('小牛电动车N1S', '续航50km，带充电器头盔', 1800.00, '出行', '东门电动车停车场', 13, 'bob', '17112345678'),
('滑板 双翘板入门款', '玩了几次不想玩了', 80.00, '出行', '操场旁', 14, 'carol', '17212345678'),
('折叠自行车20寸', '适合校园通勤，折叠后可放宿舍', 280.00, '出行', '1号宿舍楼下', 15, 'david', '17312345678'),
('平衡车小米九号', '电池健康95%，速度正常', 600.00, '出行', '体育馆入口', 16, 'emma', '17412345678'),
-- 🛏️ 宿舍类
('宿舍床帘遮光款', '1.2m宽，用了一学期挺新', 25.00, '宿舍', '6号宿舍楼', 17, 'frank', '18012345678'),
('桌面小风扇USB充电', '三挡风力，续航8小时', 30.00, '宿舍', '快递驿站', 18, 'grace', '18112345678'),
('收纳箱三件套', '塑料材质可叠放，搬宿舍利器', 35.00, '宿舍', '西区超市旁', 19, 'henry', '18212345678'),
('护眼台灯LED', '三色温可调，带USB充电口', 45.00, '宿舍', '2号宿舍楼下', 20, 'iris', '18312345678'),
('瑜伽垫加厚15mm', '宿舍健身用，清洗干净', 20.00, '宿舍', '快递驿站', 21, 'jack', '18412345678');

-- ------------------------------------------------------------
-- 收藏表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS favorite (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    user_id BIGINT NOT NULL COMMENT '收藏者ID',
    product_id BIGINT NOT NULL COMMENT '商品ID',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '收藏时间',
    UNIQUE KEY uq_user_product (user_id, product_id)
) ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 举报表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS report (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    user_id BIGINT NOT NULL COMMENT '举报人ID',
    username VARCHAR(50) COMMENT '举报人用户名',
    product_id BIGINT NOT NULL COMMENT '被举报的商品ID',
    product_name VARCHAR(255) COMMENT '商品名称',
    seller_id BIGINT COMMENT '卖家ID',
    reason_type VARCHAR(50) NOT NULL COMMENT '举报类型：虚假商品、违规物品、价格欺诈、其他',
    description VARCHAR(1000) COMMENT '详细描述/证据说明',
    status INT NOT NULL DEFAULT 0 COMMENT '状态：0-待处理，1-已核实下架，2-驳回举报',
    admin_reply VARCHAR(255) COMMENT '管理员处理批复',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
) ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 举报模块 - 种子测试数据（覆盖 0-待处理、1-已核实、2-已驳回 三种状态）
-- ------------------------------------------------------------
INSERT INTO report (user_id, username, product_id, product_name, seller_id, reason_type, description, status, admin_reply, create_time) VALUES
-- 1. 待处理状态 (黄标) - 举报数码假货
(3, 'user02', 8, 'AirPods Pro 2代', 9, '虚假商品', '面交时发现是华强北山寨高仿耳机，弹窗动画极度卡顿，降噪功能是假的，严重与正品描述不符！', 0, NULL, '2026-06-28 10:15:00'),

-- 2. 待处理状态 (黄标) - 举报教材价格欺诈
(12, 'alice', 1, '高等数学第七版上下册', 2, '价格欺诈', '商品页面标价25元，加微信私聊时对方非要卖50元，不给就拒绝交易，存在严重的恶意低价引流和价格欺诈行为！', 0, NULL, '2026-06-29 14:30:00'),

-- 3. 已核实下架状态 (绿标) - 违规诈骗导流
(13, 'bob', 6, 'iPad Air 4 64G WiFi版', 7, '违规物品', '卖家在聊聊中频繁发送第三方外部链接，诱导不在平台上交易，并要求先交200元定金，怀疑是网络诈骗。', 1, '👨‍💼 管理员批复：经过官方客服核实，该用户确实存在违规导流和外部诈骗倾向，相关闲置商品已强制执行下架处理！', '2026-06-25 16:20:00'),

-- 4. 已驳回状态 (红标) - 主观恶意/误报
(14, 'carol', 12, '小牛电动车N1S', 13, '其他违规', '我觉得他卖1800元太贵了，全新车现在打折也就卖2500，他这个骑了几年还卖这么贵，不合理。', 2, '👨‍💼 管理员批复：二手交易商品的定价属于卖家个人自主行为，平台不干涉市场合理自由定价，且未发现其他违规行为，本举报予以驳回。', '2026-06-26 09:45:00');

