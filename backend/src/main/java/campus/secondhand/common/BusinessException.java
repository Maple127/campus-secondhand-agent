package campus.secondhand.common;

/**
 * 业务异常：表示可预期的领域规则冲突（库存已售、越权、状态不允许等）。
 *
 * 与"系统异常"区分开：前者返回 4xx 且消息可直接展示给用户或 agent，
 * 后者返回 5xx 并记录堆栈。
 */
public class BusinessException extends RuntimeException {

    private final int status;
    private final String code;

    public BusinessException(String message) {
        this(409, "BUSINESS_ERROR", message);
    }

    public BusinessException(int status, String code, String message) {
        super(message);
        this.status = status;
        this.code = code;
    }

    public int getStatus() {
        return status;
    }

    public String getCode() {
        return code;
    }

    // ---------- 常用快捷构造 ----------

    public static BusinessException notFound(String what) {
        return new BusinessException(404, "NOT_FOUND", what + "不存在");
    }

    public static BusinessException badRequest(String message) {
        return new BusinessException(400, "BAD_REQUEST", message);
    }

    public static BusinessException forbidden(String message) {
        return new BusinessException(403, "FORBIDDEN", message);
    }

    public static BusinessException conflict(String message) {
        return new BusinessException(409, "CONFLICT", message);
    }

    public static BusinessException unauthorized(String message) {
        return new BusinessException(401, "UNAUTHORIZED", message);
    }
}
