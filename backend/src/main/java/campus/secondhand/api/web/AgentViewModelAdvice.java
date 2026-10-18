package campus.secondhand.api.web;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.bind.annotation.ModelAttribute;

/**
 * 向所有 Thymeleaf 视图注入 AI 助手所需的配置。
 *
 * 为什么不写死在模板里：agent 服务地址与内部服务令牌属于部署配置，
 * 集中从 application.properties 读取，改环境不用改模板。
 *
 * 注意：这里下发的 service-token 是**前端用来向后端换取 capability token** 的。
 * demo 阶段可接受；生产应改为由 Java 反向代理 /agent/**，
 * 前端完全不接触服务令牌。
 */
@ControllerAdvice(basePackages = "campus.secondhand.api.web")
public class AgentViewModelAdvice {

    private final String agentUrl;
    private final String agentServiceToken;

    public AgentViewModelAdvice(
            @Value("${app.agent.public-url:http://127.0.0.1:8090}") String agentUrl,
            @Value("${app.agent.service-token:}") String agentServiceToken) {
        this.agentUrl = agentUrl;
        this.agentServiceToken = agentServiceToken;
    }

    @ModelAttribute("agentUrl")
    public String agentUrl() {
        return agentUrl;
    }

    @ModelAttribute("agentServiceToken")
    public String agentServiceToken() {
        return agentServiceToken;
    }
}
