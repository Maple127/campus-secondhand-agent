package campus.secondhand.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import campus.secondhand.entity.AuditLog;

import java.util.List;

@Repository
public interface AuditLogRepository extends JpaRepository<AuditLog, Long> {

    List<AuditLog> findTop100ByOrderByCreateTimeDesc();

    List<AuditLog> findByTargetTypeAndTargetIdOrderByCreateTimeDesc(String targetType, Long targetId);

    List<AuditLog> findByConversationIdOrderByCreateTimeAsc(String conversationId);
}
