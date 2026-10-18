package campus.secondhand.security;

import java.time.Instant;
import java.util.Set;

/**
 * 用户能力令牌（Capability Token）。
 *
 * 这是 Java（业务真相源）与 Python（Agent）之间的身份桥梁：
 *  浏览器 session ──签发──► capability token ──透传──► Python ──携带──► Java /api/v1/**
 *
 * 与"直接把 session cookie 给 Python"相比，好处是：
 *  1. Python 拿不到 session，无法冒充网页端做任何事；
 *  2. token 只带显式列出的 scopes，越权在网关层被拒绝；
 *  3. 可设 TTL、可撤销、可审计。
 *
 * @param token          令牌字符串
 * @param userId         归属用户
 * @param username       用户名（用于审计展示）
 * @param scopes         授权范围
 * @param issuedAt       签发时间
 * @param expiresAt      过期时间
 * @param conversationId 绑定的 agent 会话（可为 null）
 */
public record CapabilityToken(
        String token,
        Long userId,
        String username,
        Set<String> scopes,
        Instant issuedAt,
        Instant expiresAt,
        String conversationId
) {

    public boolean isExpired() {
        return Instant.now().isAfter(expiresAt);
    }

    public boolean hasScope(String scope) {
        return scopes.contains(scope);
    }
}
