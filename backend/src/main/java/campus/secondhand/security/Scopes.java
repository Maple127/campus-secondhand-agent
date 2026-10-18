package campus.secondhand.security;

import java.util.Set;

/**
 * Agent 能力范围（Scope）定义。
 *
 * 设计要点：**Python 侧无权自行决定能做什么**。
 * 每个 scope 由 Java 在签发 token 时按用户身份赋予，
 * 网关在执行时逐请求校验。即使 agent 服务被攻破或被提示词注入，
 * 也无法越权调用未授权的工具。
 */
public final class Scopes {

    private Scopes() {
    }

    // ---- 读 ----
    public static final String PRODUCT_READ = "product:read";
    public static final String ORDER_READ = "order:read";
    public static final String FAVORITE_READ = "favorite:read";
    public static final String REPORT_READ = "report:read";
    public static final String PROFILE_READ = "profile:read";

    // ---- 写 ----
    public static final String PRODUCT_PUBLISH = "product:publish";
    public static final String PRODUCT_UPDATE = "product:update";
    public static final String PRODUCT_DELIST = "product:delist";
    public static final String ORDER_CREATE = "order:create";
    public static final String ORDER_CANCEL = "order:cancel";
    public static final String ORDER_PAY = "order:pay";
    public static final String FAVORITE_WRITE = "favorite:write";
    public static final String REPORT_SUBMIT = "report:submit";
    public static final String PROFILE_UPDATE = "profile:update";

    /**
     * 默认授予普通用户的 scope 集合。
     *
     * 注意这里**不包含** order:pay —— 支付是需要用户本人在页面上输入支付密码的动作，
     * 明确不允许 agent 代付。这是刻意的安全边界。
     */
    public static final Set<String> DEFAULT_USER_SCOPES = Set.of(
            PRODUCT_READ, ORDER_READ, FAVORITE_READ, REPORT_READ, PROFILE_READ,
            PRODUCT_PUBLISH, PRODUCT_UPDATE, PRODUCT_DELIST,
            ORDER_CREATE, ORDER_CANCEL,
            FAVORITE_WRITE, REPORT_SUBMIT, PROFILE_UPDATE
    );

    /** 需要用户二次确认的写操作（M5 的 HITL 机制会用到） */
    public static final Set<String> CONFIRMATION_REQUIRED = Set.of(
            PRODUCT_PUBLISH, PRODUCT_UPDATE, PRODUCT_DELIST,
            ORDER_CREATE, ORDER_CANCEL, REPORT_SUBMIT
    );

    public static boolean isKnown(String scope) {
        return ALL.contains(scope);
    }

    public static final Set<String> ALL = Set.of(
            PRODUCT_READ, ORDER_READ, FAVORITE_READ, REPORT_READ, PROFILE_READ,
            PRODUCT_PUBLISH, PRODUCT_UPDATE, PRODUCT_DELIST,
            ORDER_CREATE, ORDER_CANCEL, ORDER_PAY,
            FAVORITE_WRITE, REPORT_SUBMIT, PROFILE_UPDATE
    );
}
