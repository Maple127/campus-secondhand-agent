package campus.secondhand.security;

import campus.secondhand.common.AuditActions;
import campus.secondhand.common.BusinessException;
import campus.secondhand.entity.ActorType;
import campus.secondhand.service.AuditService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.security.SecureRandom;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 能力令牌服务。
 *
 * 存储说明：当前用进程内 ConcurrentHashMap，足够 demo 使用。
 * 多实例部署时应换成 Redis —— 接口已按"可替换存储"设计（issue/resolve/revoke）。
 */
@Slf4j
@Service
public class CapabilityTokenService {

    private final AuditService auditService;

    /** 令牌默认有效期 */
    private final Duration ttl;

    private final Map<String, CapabilityToken> store = new ConcurrentHashMap<>();
    private final SecureRandom random = new SecureRandom();

    public CapabilityTokenService(AuditService auditService,
                                  @Value("${app.agent.token-ttl-minutes:30}") long ttlMinutes) {
        this.auditService = auditService;
        this.ttl = Duration.ofMinutes(ttlMinutes);
    }

    /**
     * 为用户签发令牌。
     *
     * @param requestedScopes 期望的 scope；为 null 时使用默认用户 scope。
     *                        始终与 DEFAULT_USER_SCOPES 取交集，防止调用方自行提权。
     */
    public CapabilityToken issue(Long userId, String username, Set<String> requestedScopes,
                                 String conversationId) {
        Set<String> granted = (requestedScopes == null || requestedScopes.isEmpty())
                ? Scopes.DEFAULT_USER_SCOPES
                : requestedScopes.stream()
                        .filter(Scopes.DEFAULT_USER_SCOPES::contains)
                        .collect(java.util.stream.Collectors.toUnmodifiableSet());

        Instant now = Instant.now();
        CapabilityToken token = new CapabilityToken(
                newTokenString(), userId, username, granted, now, now.plus(ttl), conversationId);
        store.put(token.token(), token);

        auditService.record(ActorType.AGENT, userId, username, AuditActions.AGENT_SESSION_ISSUE,
                "user", userId, "签发 agent 能力令牌 scopes=" + granted, "SUCCESS", null, conversationId);

        log.info("签发 capability token: user={}({}), scopes={}, ttl={}min",
                username, userId, granted, ttl.toMinutes());
        return token;
    }

    /** 校验并解析令牌；失效则抛 401 */
    public CapabilityToken resolve(String tokenString) {
        if (tokenString == null || tokenString.isBlank()) {
            throw BusinessException.unauthorized("缺少 agent 会话令牌");
        }
        CapabilityToken token = store.get(tokenString);
        if (token == null) {
            throw BusinessException.unauthorized("agent 会话令牌无效或已失效，请刷新页面重试");
        }
        if (token.isExpired()) {
            store.remove(tokenString);
            throw BusinessException.unauthorized("agent 会话令牌已过期，请刷新页面重试");
        }
        return token;
    }

    /** 校验令牌是否具备指定 scope */
    public CapabilityToken requireScope(String tokenString, String scope) {
        CapabilityToken token = resolve(tokenString);
        if (!token.hasScope(scope)) {
            throw BusinessException.forbidden("当前会话未被授予 " + scope + " 权限");
        }
        return token;
    }

    public void revoke(String tokenString) {
        if (tokenString != null) {
            store.remove(tokenString);
        }
    }

    /** 主动清理过期令牌，避免内存无界增长 */
    @Scheduled(fixedDelay = 300_000L)
    public void purgeExpired() {
        int before = store.size();
        store.entrySet().removeIf(e -> e.getValue().isExpired());
        int removed = before - store.size();
        if (removed > 0) {
            log.debug("清理过期 capability token: {} 个", removed);
        }
    }

    /** 仅用于测试/诊断 */
    public int activeTokenCount() {
        return store.size();
    }

    public Optional<CapabilityToken> peek(String tokenString) {
        return Optional.ofNullable(store.get(tokenString));
    }

    private String newTokenString() {
        byte[] bytes = new byte[24];
        random.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
}
