package campus.secondhand.api.rest;

import campus.secondhand.api.ApiResponse;
import campus.secondhand.common.BusinessException;
import campus.secondhand.entity.User;
import campus.secondhand.security.AgentAuthInterceptor;
import campus.secondhand.security.CapabilityToken;
import campus.secondhand.security.CapabilityTokenService;
import campus.secondhand.security.ServiceTokenValidator;
import campus.secondhand.service.UserService;
import jakarta.servlet.http.HttpSession;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

import java.time.Instant;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * Agent 会话入口：把浏览器登录态换成 capability token。
 *
 * 调用链路：
 *   前端（已登录） --POST /api/v1/agent/session--> Java
 *   Java 校验 HttpSession 中的用户 --> 签发 capability token --> 返回给前端
 *   前端把 token 交给 Python agent 服务；Python 调用 /api/v1/** 时透传。
 *
 * 此端点被排除在 {@link AgentAuthInterceptor} 之外（此时还没有 Actor-Token），
 * 因此在此处单独校验服务令牌 + 浏览器登录态。
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/agent")
@RequiredArgsConstructor
public class AgentSessionController {

    private final CapabilityTokenService capabilityTokenService;
    private final ServiceTokenValidator serviceTokenValidator;
    private final UserService userService;

    @Value("${app.agent.session-ttl-minutes:30}")
    private long sessionTtlMinutes;

    /**
     * 签发会话令牌。
     *
     * 身份来源是**浏览器 HttpSession**，不是请求体里的 userId ——
     * 这一点很关键：否则任何人都能通过伪造 userId 拿到别人的令牌。
     */
    @PostMapping("/session")
    public ApiResponse<Map<String, Object>> createSession(
            @RequestHeader(value = AgentAuthInterceptor.HEADER_SERVICE_TOKEN, required = false) String serviceToken,
            @RequestBody(required = false) SessionRequest req,
            HttpSession session) {

        serviceTokenValidator.validate(serviceToken);

        User user = (User) session.getAttribute("user");
        if (user == null) {
            throw BusinessException.unauthorized("请先登录后再使用 AI 助手");
        }

        // 每次都从库里取最新资料，避免 session 里的陈旧对象
        User fresh = userService.findByIdOrNull(user.getId());
        if (fresh == null) {
            session.invalidate();
            throw BusinessException.unauthorized("用户不存在，请重新登录");
        }

        String conversationId = (req != null && req.conversationId() != null && !req.conversationId().isBlank())
                ? req.conversationId()
                : UUID.randomUUID().toString();

        Set<String> requested = req == null ? null : req.scopes();
        CapabilityToken token = capabilityTokenService.issue(
                fresh.getId(), fresh.getUsername(), requested, conversationId);

        return ApiResponse.ok(Map.of(
                "actorToken", token.token(),
                "conversationId", conversationId,
                "expiresAt", token.expiresAt().toString(),
                "scopes", token.scopes(),
                "user", Map.of(
                        "id", fresh.getId(),
                        "username", fresh.getUsername())));
    }

    /** 撤销令牌（用户关闭 AI 助手时调用） */
    @DeleteMapping("/session")
    public ApiResponse<Map<String, Object>> revoke(
            @RequestHeader(value = AgentAuthInterceptor.HEADER_SERVICE_TOKEN, required = false) String serviceToken,
            @RequestHeader(value = AgentAuthInterceptor.HEADER_ACTOR_TOKEN, required = false) String actorToken) {
        serviceTokenValidator.validate(serviceToken);
        capabilityTokenService.revoke(actorToken);
        return ApiResponse.ok(Map.of("revoked", true, "at", Instant.now().toString()));
    }

    /** 查看当前令牌状态（便于前端展示剩余有效期） */
    @GetMapping("/session")
    public ApiResponse<Map<String, Object>> inspect(
            @RequestHeader(value = AgentAuthInterceptor.HEADER_SERVICE_TOKEN, required = false) String serviceToken,
            @RequestHeader(value = AgentAuthInterceptor.HEADER_ACTOR_TOKEN, required = false) String actorToken) {
        serviceTokenValidator.validate(serviceToken);
        CapabilityToken token = capabilityTokenService.resolve(actorToken);
        return ApiResponse.ok(Map.of(
                "conversationId", token.conversationId() == null ? "" : token.conversationId(),
                "expiresAt", token.expiresAt().toString(),
                "scopes", token.scopes(),
                "username", token.username()));
    }

    public record SessionRequest(String conversationId, Set<String> scopes) {
    }
}
