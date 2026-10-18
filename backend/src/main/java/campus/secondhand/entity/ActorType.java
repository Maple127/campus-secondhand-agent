package campus.secondhand.entity;

/**
 * 审计日志的操作主体类型。
 *
 * 引入 AGENT 是本项目升级的关键：所有由自然语言 agent 触发的写操作，
 * 都必须能追溯到"是哪个用户、通过哪次会话"发起的。
 */
public enum ActorType {

    /** 普通用户通过网页表单操作 */
    USER,

    /** 管理员通过后台操作 */
    ADMIN,

    /** 由 AI Agent 代用户执行 */
    AGENT,

    /** 系统自身（定时任务、数据迁移等） */
    SYSTEM
}
