package campus.secondhand.common;

/**
 * 审计动作常量。约定命名格式："资源.动作"。
 *
 * 集中定义是为了让审计查询、Agent 评测断言、文档三者引用同一份字符串，
 * 避免出现 "product.publish" 与 "PRODUCT_PUBLISH" 混用。
 */
public final class AuditActions {

    private AuditActions() {
    }

    // 商品
    public static final String PRODUCT_PUBLISH = "product.publish";
    public static final String PRODUCT_UPDATE = "product.update";
    public static final String PRODUCT_DELIST = "product.delist";
    public static final String PRODUCT_RELIST = "product.relist";
    public static final String PRODUCT_APPROVE = "product.approve";
    public static final String PRODUCT_REJECT = "product.reject";
    public static final String PRODUCT_DELETE = "product.delete";
    public static final String PRODUCT_SOLD = "product.sold";

    // 订单
    public static final String ORDER_CREATE = "order.create";
    public static final String ORDER_PAY = "order.pay";
    public static final String ORDER_CANCEL = "order.cancel";
    public static final String ORDER_SHIP = "order.ship";

    // 收藏
    public static final String FAVORITE_ADD = "favorite.add";
    public static final String FAVORITE_REMOVE = "favorite.remove";

    // 举报
    public static final String REPORT_SUBMIT = "report.submit";
    public static final String REPORT_HANDLE = "report.handle";

    // 用户
    public static final String USER_REGISTER = "user.register";
    public static final String USER_LOGIN = "user.login";
    public static final String USER_UPDATE_PROFILE = "user.updateProfile";

    // 分类
    public static final String CATEGORY_CREATE = "category.create";
    public static final String CATEGORY_UPDATE = "category.update";
    public static final String CATEGORY_DELETE = "category.delete";

    // Agent
    public static final String AGENT_SESSION_ISSUE = "agent.session.issue";
    public static final String AGENT_TOOL_CALL = "agent.tool.call";
}
