package campus.secondhand.security;

import campus.secondhand.common.ActorContext;
import campus.secondhand.common.BusinessException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Agent REST 网关拦截器。
 *
 * 对 /api/v1/** 的每一个请求执行三重校验：
 *   1. 服务令牌（X-Service-Token）—— 确认调用方是内部 agent 服务
 *   2. 用户能力令牌（X-Actor-Token）—— 确认"以谁的身份"
 *   3. 该端点要求的 scope —— 确认"有没有权限做这件事"
 *
 * 校验通过后把身份写入 {@link ActorContextHolder}，
 * 并强制标记为 AGENT 类型，使审计日志能区分"人点的"和"agent 做的"。
 */
@Component
@RequiredArgsConstructor
public class AgentAuthInterceptor implements HandlerInterceptor {

    public static final String HEADER_SERVICE_TOKEN = "X-Service-Token";
    public static final String HEADER_ACTOR_TOKEN = "X-Actor-Token";
    public static final String ATTR_ACTOR_TOKEN = "campus.actorToken";

    private final ServiceTokenValidator serviceTokenValidator;
    private final CapabilityTokenService capabilityTokenService;

    /**
     * 端点 → 所需 scope 的映射。
     * 用 "METHOD /path" 作为 key，路径用 Ant 风格通配。
     */
    private static final Map<String, String> SCOPE_RULES = new LinkedHashMap<>();

    static {
        // 商品
        SCOPE_RULES.put("GET /api/v1/products", Scopes.PRODUCT_READ);
        // 显式登记定价参考：requiredScope 先精确匹配再通配匹配，
        // 所以它本就不会被 /api/v1/products/* 吞掉，但显式登记更清晰也更稳妥。
        SCOPE_RULES.put("GET /api/v1/products/price-suggestion", Scopes.PRODUCT_READ);
        SCOPE_RULES.put("GET /api/v1/products/mine/list", Scopes.PRODUCT_READ);
        SCOPE_RULES.put("GET /api/v1/products/*", Scopes.PRODUCT_READ);
        SCOPE_RULES.put("POST /api/v1/products", Scopes.PRODUCT_PUBLISH);
        SCOPE_RULES.put("PATCH /api/v1/products/*", Scopes.PRODUCT_UPDATE);
        SCOPE_RULES.put("POST /api/v1/products/*/delist", Scopes.PRODUCT_DELIST);
        SCOPE_RULES.put("GET /api/v1/products/*/price-comparison", Scopes.PRODUCT_READ);
        SCOPE_RULES.put("GET /api/v1/products/*/negotiation-advice", Scopes.PRODUCT_READ);
        // 订单
        SCOPE_RULES.put("GET /api/v1/orders", Scopes.ORDER_READ);
        SCOPE_RULES.put("GET /api/v1/orders/*", Scopes.ORDER_READ);
        SCOPE_RULES.put("POST /api/v1/orders", Scopes.ORDER_CREATE);
        SCOPE_RULES.put("POST /api/v1/orders/*/cancel", Scopes.ORDER_CANCEL);
        // 收藏
        SCOPE_RULES.put("GET /api/v1/favorites", Scopes.FAVORITE_READ);
        SCOPE_RULES.put("POST /api/v1/favorites/*", Scopes.FAVORITE_WRITE);
        // 举报
        SCOPE_RULES.put("GET /api/v1/reports/mine", Scopes.REPORT_READ);
        SCOPE_RULES.put("POST /api/v1/reports", Scopes.REPORT_SUBMIT);
        // 个人资料
        SCOPE_RULES.put("GET /api/v1/me", Scopes.PROFILE_READ);
        SCOPE_RULES.put("PATCH /api/v1/me", Scopes.PROFILE_UPDATE);
        // 元数据（无需额外 scope，仅需身份）
        SCOPE_RULES.put("GET /api/v1/meta/categories", Scopes.PRODUCT_READ);
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        String serviceToken = request.getHeader(HEADER_SERVICE_TOKEN);
        serviceTokenValidator.validate(serviceToken);

        String actorToken = request.getHeader(HEADER_ACTOR_TOKEN);
        CapabilityToken token = capabilityTokenService.resolve(actorToken);

        String required = requiredScope(request.getMethod(), request.getRequestURI());
        if (required != null && !token.hasScope(required)) {
            throw BusinessException.forbidden(
                    "当前会话未被授予 " + required + " 权限（此操作不在 AI 助手允许范围内）");
        }

        request.setAttribute(ATTR_ACTOR_TOKEN, token);
        ActorContextHolder.set(ActorContext.ofAgent(token.userId(), token.username(), token.conversationId()));
        return true;
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response,
                               Object handler, Exception ex) {
        // 必须清理，否则线程池复用会造成身份串号
        ActorContextHolder.clear();
    }

    /**
     * 解析端点所需 scope。未登记的端点返回 null（只校验身份，不再要求额外 scope）。
     * 匹配规则：先精确匹配，再按通配符匹配。
     */
    static String requiredScope(String method, String uri) {
        String key = method.toUpperCase() + " " + normalize(uri);
        String exact = SCOPE_RULES.get(key);
        if (exact != null) {
            return exact;
        }
        for (Map.Entry<String, String> e : SCOPE_RULES.entrySet()) {
            if (matches(e.getKey(), key)) {
                return e.getValue();
            }
        }
        return null;
    }

    /** 去掉 contextPath 之外的多余部分，保留以 /api 开头的路径 */
    private static String normalize(String uri) {
        int idx = uri.indexOf("/api/");
        return idx >= 0 ? uri.substring(idx) : uri;
    }

    /** 把 "GET /api/v1/products/*" 这样的模式与真实请求比对 */
    private static boolean matches(String pattern, String actual) {
        String[] p = pattern.split(" ");
        String[] a = actual.split(" ");
        if (p.length != 2 || a.length != 2 || !p[0].equalsIgnoreCase(a[0])) {
            return false;
        }
        String[] ps = p[1].split("/");
        String[] as = a[1].split("/");
        if (ps.length != as.length) {
            return false;
        }
        for (int i = 0; i < ps.length; i++) {
            if (ps[i].equals("*")) {
                continue;
            }
            if (!ps[i].equals(as[i])) {
                return false;
            }
        }
        return true;
    }
}
