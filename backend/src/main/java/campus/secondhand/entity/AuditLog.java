package campus.secondhand.entity;

import jakarta.persistence.*;
import lombok.Data;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

/**
 * 审计日志：记录每一次改变系统状态的操作。
 *
 * 这是 agent 化改造的安全基础设施 —— 当一条商品由自然语言指令创建时，
 * 必须能回答：谁发起、经由哪次 agent 会话、调用了哪个工具、参数是什么、结果如何。
 */
@Data
@Entity
@Table(name = "audit_log", indexes = {
        @Index(name = "idx_audit_actor", columnList = "actor_type,actor_id"),
        @Index(name = "idx_audit_action", columnList = "action"),
        @Index(name = "idx_audit_target", columnList = "target_type,target_id")
})
public class AuditLog {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 操作主体类型：USER / ADMIN / AGENT / SYSTEM */
    @Enumerated(EnumType.STRING)
    @Column(name = "actor_type", nullable = false, length = 16)
    private ActorType actorType;

    /** 操作主体ID（admin 与 user 是两张表，因此 ID 需配合 actorType 解读） */
    @Column(name = "actor_id")
    private Long actorId;

    /** 操作主体名称（冗余存储，避免事后因改名或删号丢失线索） */
    private String actorName;

    /** 动作标识，约定为 "资源.动作"，例如 product.publish / order.pay */
    @Column(nullable = false, length = 64)
    private String action;

    /** 目标资源类型，例如 product / order / report / user */
    @Column(name = "target_type", length = 32)
    private String targetType;

    @Column(name = "target_id")
    private Long targetId;

    /** 调用参数（JSON 字符串，已脱敏） */
    @Column(length = 2000)
    private String detail;

    /** 执行结果：SUCCESS / FAILURE */
    @Column(nullable = false, length = 16)
    private String result = "SUCCESS";

    /** 失败原因（result=FAILURE 时填写） */
    @Column(length = 500)
    private String errorMessage;

    /** Agent 会话ID；非 agent 触发时为 null */
    @Column(name = "conversation_id", length = 64)
    private String conversationId;

    @CreationTimestamp
    @Column(updatable = false)
    private LocalDateTime createTime;
}
