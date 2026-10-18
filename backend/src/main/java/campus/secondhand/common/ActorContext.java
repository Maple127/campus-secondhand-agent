package campus.secondhand.common;

import campus.secondhand.entity.ActorType;

/**
 * 当前请求的操作主体。
 *
 * 网页端由 Controller 从 HttpSession 构造，
 * API 端由 capability token 解析后构造。
 * 这样 Service 层无需关心身份来源，也能统一写审计。
 */
public record ActorContext(
        ActorType type,
        Long id,
        String name,
        String conversationId
) {

    public static ActorContext ofUser(Long id, String name) {
        return new ActorContext(ActorType.USER, id, name, null);
    }

    public static ActorContext ofAdmin(Long id, String name) {
        return new ActorContext(ActorType.ADMIN, id, name, null);
    }

    public static ActorContext ofAgent(Long userId, String name, String conversationId) {
        return new ActorContext(ActorType.AGENT, userId, name, conversationId);
    }

    public static ActorContext system() {
        return new ActorContext(ActorType.SYSTEM, null, "system", null);
    }

    public boolean isAgent() {
        return type == ActorType.AGENT;
    }
}
