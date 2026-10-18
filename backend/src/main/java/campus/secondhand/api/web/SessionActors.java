package campus.secondhand.api.web;

import campus.secondhand.common.ActorContext;
import campus.secondhand.entity.Admin;
import campus.secondhand.entity.User;
import jakarta.servlet.http.HttpSession;

/**
 * 从 HttpSession 构造审计主体。
 *
 * 网页端所有 Controller 都通过这里取 ActorContext，
 * 保证审计日志里"谁做的"永远有值，不会出现 null actor。
 */
public final class SessionActors {

    private SessionActors() {
    }

    public static ActorContext user(HttpSession session) {
        User user = currentUser(session);
        if (user == null) {
            return ActorContext.system();
        }
        return ActorContext.ofUser(user.getId(), user.getUsername());
    }

    public static ActorContext admin(HttpSession session) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return ActorContext.system();
        }
        return ActorContext.ofAdmin(admin.getId(), admin.getUsername());
    }

    public static User currentUser(HttpSession session) {
        return session == null ? null : (User) session.getAttribute("user");
    }

    public static Admin currentAdmin(HttpSession session) {
        return session == null ? null : (Admin) session.getAttribute("admin");
    }

    /** 登录用户ID，未登录返回 null */
    public static Long userId(HttpSession session) {
        User user = currentUser(session);
        return user == null ? null : user.getId();
    }
}
