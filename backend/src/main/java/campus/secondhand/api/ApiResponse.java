package campus.secondhand.api;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * REST 统一响应体。
 *
 * 约定：
 *  - code = 0 表示成功，非 0 表示业务错误码
 *  - HTTP 状态码同时被设置，便于 agent / 前端两层都能判断
 *
 * @param code    业务码，0=成功
 * @param message 人类可读消息（会直接展示给用户或交给 LLM 解释）
 * @param data    业务数据
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ApiResponse<T>(int code, String message, T data) {

    public static <T> ApiResponse<T> ok(T data) {
        return new ApiResponse<>(0, "ok", data);
    }

    public static ApiResponse<Void> ok() {
        return new ApiResponse<>(0, "ok", null);
    }

    public static <T> ApiResponse<T> error(int code, String message) {
        return new ApiResponse<>(code, message, null);
    }
}
