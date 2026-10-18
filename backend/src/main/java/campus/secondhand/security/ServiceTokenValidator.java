package campus.secondhand.security;

import campus.secondhand.common.BusinessException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * 服务令牌校验。
 *
 * Python agent 服务调用 Java REST 接口时，必须在 {@code X-Service-Token} 头里带上共享密钥。
 * 这挡住的是"外部直接调用 /api/v1/**"——即使拿到某个用户的 capability token，
 * 没有服务密钥也无法从公网调用内部接口。
 *
 * demo 实现为静态共享密钥（配置项 app.agent.service-token）。
 * 生产环境应替换为 mTLS 或短期服务凭证。
 */
@Slf4j
@Component
public class ServiceTokenValidator {

    private final String expected;

    public ServiceTokenValidator(@Value("${app.agent.service-token:}") String expected) {
        this.expected = expected;
        if (expected == null || expected.isBlank()) {
            log.warn("""
                    未配置 app.agent.service-token，/api/v1/** 的 agent 入口将在校验时全部拒绝。
                    请在 application.properties 或环境变量 AGENT_SERVICE_TOKEN 中配置。""");
        }
    }

    public void validate(String provided) {
        if (expected == null || expected.isBlank()) {
            throw BusinessException.unauthorized("服务端未配置 agent 服务令牌，接口不可用");
        }
        if (provided == null || !constantTimeEquals(provided, expected)) {
            throw BusinessException.unauthorized("服务令牌无效");
        }
    }

    /** 恒定时间比较，避免通过响应时间侧信道猜测密钥 */
    private static boolean constantTimeEquals(String a, String b) {
        if (a.length() != b.length()) {
            return false;
        }
        int result = 0;
        for (int i = 0; i < a.length(); i++) {
            result |= a.charAt(i) ^ b.charAt(i);
        }
        return result == 0;
    }
}
