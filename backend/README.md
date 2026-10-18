# 后端模块

Java 21 + Spring Boot 4.1 + Spring Data JPA + Thymeleaf + MySQL 8.0。

## 跑起来

```powershell
# 建库（MySQL 8.0，注意本项目连的是 IPv6 的 [::1]，不是 127.0.0.1）
mysql -h ::1 -uroot -p123456 < ..\infra\schema.sql
mysql -h ::1 -uroot -p123456 login_db < ..\infra\seed.sql

# 启动（默认 8081）
mvn spring-boot:run
# 或先打包再跑
mvn -DskipTests package
java -jar target/campus-backend-0.2.0-SNAPSHOT.jar
```

数据库连接、密码、agent 服务令牌都在 `src/main/resources/application.properties`，
均可用环境变量覆盖（`DB_URL` / `DB_PASSWORD` / `AGENT_SERVICE_TOKEN`）。

## 目录

```
src/main/java/campus/secondhand/
  ├─ api/web/      网页接口（Thymeleaf 页面）
  ├─ api/rest/     /api/v1（供 Python agent 调用，双层令牌鉴权）
  ├─ service/      业务真值：商品状态机、订单、比价、议价、品类词
  ├─ repository/   JPA 仓储
  ├─ entity/       实体与枚举（ProductStatus 里带合法迁移表）
  ├─ security/     令牌与 scope 拦截
  └─ config/       建表补丁、审计等横切
src/main/resources/
  ├─ templates/    34 个页面
  └─ static/       js / css（原生，无构建）
```

## 测试

```powershell
mvn test          # 50 个单元测试，Mockito 打桩，不需要数据库
```

端到端验证在仓库根目录的 `infra/smoke-test.ps1`（19 项断言，需要后端与 agent 都在跑）。
