package campus.secondhand.service;

import campus.secondhand.entity.ActorType;
import campus.secondhand.entity.AuditLog;
import campus.secondhand.repository.AuditLogRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * 审计服务。
 *
 * 用 REQUIRES_NEW 传播，保证即使外层业务事务回滚，
 * "有人尝试做过这件事（并失败了）"这条记录仍然留存。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AuditService {

    private final AuditLogRepository auditLogRepository;

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void record(ActorType actorType, Long actorId, String actorName,
                       String action, String targetType, Long targetId,
                       String detail, String result, String errorMessage,
                       String conversationId) {
        try {
            AuditLog entry = new AuditLog();
            entry.setActorType(actorType == null ? ActorType.SYSTEM : actorType);
            entry.setActorId(actorId);
            entry.setActorName(actorName);
            entry.setAction(action);
            entry.setTargetType(targetType);
            entry.setTargetId(targetId);
            entry.setDetail(truncate(detail, 2000));
            entry.setResult(result == null ? "SUCCESS" : result);
            entry.setErrorMessage(truncate(errorMessage, 500));
            entry.setConversationId(conversationId);
            auditLogRepository.save(entry);
        } catch (Exception e) {
            // 审计失败绝不能影响主业务，只记录告警
            log.warn("写入审计日志失败: action={}, target={}#{}", action, targetType, targetId, e);
        }
    }

    /** 成功记录（用户/管理员在网页端操作） */
    public void success(ActorType actorType, Long actorId, String actorName,
                        String action, String targetType, Long targetId, String detail) {
        record(actorType, actorId, actorName, action, targetType, targetId, detail, "SUCCESS", null, null);
    }

    /** 成功记录（由 agent 触发，带会话ID） */
    public void successByAgent(Long userId, String userName, String action,
                               String targetType, Long targetId, String detail, String conversationId) {
        record(ActorType.AGENT, userId, userName, action, targetType, targetId,
                detail, "SUCCESS", null, conversationId);
    }

    /** 失败记录 */
    public void failure(ActorType actorType, Long actorId, String actorName, String action,
                        String targetType, Long targetId, String detail, String errorMessage) {
        record(actorType, actorId, actorName, action, targetType, targetId,
                detail, "FAILURE", errorMessage, null);
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return null;
        }
        return s.length() <= max ? s : s.substring(0, max);
    }
}
