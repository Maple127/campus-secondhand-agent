package campus.secondhand.security;

import campus.secondhand.common.ActorContext;
import campus.secondhand.entity.ActorType;

/**
 * 当前 REST 请求的操作主体上下文。
 *
 * 由 {@link AgentAuthInterceptor} 解析 capability token 后写入，
 * Controller/Service 通过 {@link #current()} 读取，无需层层传参。
 *
 * 用 ThreadLocal 是因为一次请求就是一个线程，且必须在 afterCompletion 中清理
 * （否则线程复用会导致身份串号）。
 */
public final class ActorContextHolder {

    private static final ThreadLocal<ActorContext> HOLDER = new ThreadLocal<>();

    private ActorContextHolder() {
    }

    public static void set(ActorContext context) {
        HOLDER.set(context);
    }

    public static ActorContext current() {
        ActorContext ctx = HOLDER.get();
        return ctx == null ? ActorContext.system() : ctx;
    }

    /** 当前请求是否由 agent 发起 */
    public static boolean isAgentRequest() {
        return current().type() == ActorType.AGENT;
    }

    public static void clear() {
        HOLDER.remove();
    }
}
