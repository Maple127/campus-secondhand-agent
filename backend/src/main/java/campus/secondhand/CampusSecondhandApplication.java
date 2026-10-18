package campus.secondhand;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * 校园二手交易平台后端。
 *
 * 职责定位：**唯一业务真相源**。
 *  - Thymeleaf 页面（api/web）供人使用
 *  - REST 接口（api/rest）供 AI Agent 使用
 *  - 两者共用 service 层，规则不会漂移
 */
@SpringBootApplication
@EnableScheduling
public class CampusSecondhandApplication {

    public static void main(String[] args) {
        SpringApplication.run(CampusSecondhandApplication.class, args);
    }

}
