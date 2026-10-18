package campus.secondhand;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertNotNull;

/**
 * 应用基础自检。
 *
 * 说明：这里刻意**不使用 {@code @SpringBootTest}**。
 * 完整上下文启动需要可用的 MySQL，会让单元测试套件依赖外部环境；
 * 端到端的启动验证由 `infra/smoke-test.ps1` 承担（真实起服务 + 真库）。
 * 当前测试套件保持"零外部依赖、秒级完成"，便于频繁执行与后续接入 CI。
 */
class CampusSecondhandApplicationTests {

    @Test
    @DisplayName("主类可被加载")
    void applicationClassLoads() {
        assertNotNull(CampusSecondhandApplication.class);
    }
}
