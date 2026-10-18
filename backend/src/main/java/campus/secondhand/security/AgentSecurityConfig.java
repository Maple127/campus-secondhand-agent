package campus.secondhand.security;

import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * 注册 agent REST 网关拦截器。
 *
 * 只作用于 /api/v1/**：
 *  - /api/v1/agent/session 需要放行 —— 它正是用来"用网页 session 换取 capability token"的，
 *    此时还没有 Actor-Token，但仍必须验证服务令牌（在 Controller 内单独处理）。
 */
@Configuration
@RequiredArgsConstructor
public class AgentSecurityConfig implements WebMvcConfigurer {

    private final AgentAuthInterceptor agentAuthInterceptor;

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(agentAuthInterceptor)
                .addPathPatterns("/api/v1/**")
                .excludePathPatterns("/api/v1/agent/session");
    }
}
