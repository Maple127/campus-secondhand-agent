package campus.secondhand.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import campus.secondhand.entity.Report;
import java.util.List;

@Repository
public interface ReportRepository extends JpaRepository<Report, Long> {

    // 学生端：查询个人历史举报记录，按时间降序
    List<Report> findByUserIdOrderByCreateTimeDesc(Long userId);

    // 管理端：按状态查询工单（0-待处理）
    List<Report> findByStatusOrderByCreateTimeDesc(Integer status);

    // 管理端：查询所有举报记录
    List<Report> findAllByOrderByCreateTimeDesc();

    // 检查用户是否对该商品提交过待处理的举报，防止重复恶意举报
    boolean existsByUserIdAndProductIdAndStatus(Long userId, Long productId, Integer status);
}