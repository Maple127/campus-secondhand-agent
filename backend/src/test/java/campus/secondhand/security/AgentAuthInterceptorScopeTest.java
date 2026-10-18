package campus.secondhand.security;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 网关端点 → scope 映射测试。
 *
 * 这是安全边界的可执行规格：改错一个映射就等于开了越权口子，
 * 因此必须由测试而非人工检查来保证。
 */
class AgentAuthInterceptorScopeTest {

    @Test
    @DisplayName("商品读接口需要 product:read")
    void productRead() {
        assertEquals(Scopes.PRODUCT_READ,
                AgentAuthInterceptor.requiredScope("GET", "/api/v1/products"));
        assertEquals(Scopes.PRODUCT_READ,
                AgentAuthInterceptor.requiredScope("GET", "/api/v1/products/12"));
    }

    @Test
    @DisplayName("发布商品需要 product:publish")
    void productPublish() {
        assertEquals(Scopes.PRODUCT_PUBLISH,
                AgentAuthInterceptor.requiredScope("POST", "/api/v1/products"));
    }

    @Test
    @DisplayName("下架商品匹配通配路径")
    void productDelist() {
        assertEquals(Scopes.PRODUCT_DELIST,
                AgentAuthInterceptor.requiredScope("POST", "/api/v1/products/42/delist"));
    }

    @Test
    @DisplayName("下单需要 order:create，取消需要 order:cancel")
    void orderScopes() {
        assertEquals(Scopes.ORDER_CREATE,
                AgentAuthInterceptor.requiredScope("POST", "/api/v1/orders"));
        assertEquals(Scopes.ORDER_CANCEL,
                AgentAuthInterceptor.requiredScope("POST", "/api/v1/orders/ABC123/cancel"));
        assertEquals(Scopes.ORDER_READ,
                AgentAuthInterceptor.requiredScope("GET", "/api/v1/orders"));
    }

    @Test
    @DisplayName("带 contextPath 的 URI 也能正确归一化")
    void normalizesContextPath() {
        assertEquals(Scopes.PRODUCT_READ,
                AgentAuthInterceptor.requiredScope("GET", "/app/api/v1/products"));
    }

    @Test
    @DisplayName("方法不匹配时不套用规则")
    void methodMustMatch() {
        // GET /api/v1/orders/* 是 order:read；POST 到同一路径不应命中该规则
        assertNotEquals(Scopes.ORDER_READ,
                AgentAuthInterceptor.requiredScope("POST", "/api/v1/orders/XYZ"));
    }

    @Test
    @DisplayName("比价接口属于 product:read")
    void priceComparison() {
        assertEquals(Scopes.PRODUCT_READ,
                AgentAuthInterceptor.requiredScope("GET", "/api/v1/products/7/price-comparison"));
    }

    @Test
    @DisplayName("未登记端点返回 null（仅校验身份）")
    void unregisteredEndpoint() {
        assertNull(AgentAuthInterceptor.requiredScope("GET", "/api/v1/unknown/thing"));
    }

    @Test
    @DisplayName("order:pay 不在默认用户 scope 中 —— agent 不得代付")
    void payNotGrantedByDefault() {
        assertFalse(Scopes.DEFAULT_USER_SCOPES.contains(Scopes.ORDER_PAY));
        assertTrue(Scopes.ALL.contains(Scopes.ORDER_PAY));
    }

    @Test
    @DisplayName("默认 scope 覆盖用户自助所需的全部能力")
    void defaultsCoverUserSelfService() {
        assertTrue(Scopes.DEFAULT_USER_SCOPES.containsAll(java.util.Set.of(
                Scopes.PRODUCT_READ, Scopes.PRODUCT_PUBLISH, Scopes.PRODUCT_UPDATE,
                Scopes.PRODUCT_DELIST, Scopes.ORDER_READ, Scopes.ORDER_CREATE,
                Scopes.ORDER_CANCEL, Scopes.FAVORITE_READ, Scopes.FAVORITE_WRITE,
                Scopes.REPORT_READ, Scopes.REPORT_SUBMIT,
                Scopes.PROFILE_READ, Scopes.PROFILE_UPDATE)));
    }
}
