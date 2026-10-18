package campus.secondhand.service;

import campus.secondhand.common.ActorContext;
import campus.secondhand.common.AuditActions;
import campus.secondhand.common.BusinessException;
import campus.secondhand.entity.Product;
import campus.secondhand.entity.ProductStatus;
import campus.secondhand.entity.Report;
import campus.secondhand.repository.ProductRepository;
import campus.secondhand.repository.ReportRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 举报领域服务。
 *
 * 管理员"核实违规"时会连带下架商品 —— 原实现直接 setStatus(2)，
 * 现在走 ProductService 的状态机，保证规则一致。
 */
@Service
@RequiredArgsConstructor
public class ReportService {

    /** 举报状态：0-待处理，1-已核实下架，2-驳回 */
    public static final int PENDING = 0;
    public static final int VERIFIED = 1;
    public static final int DISMISSED = 2;

    private final ReportRepository reportRepository;
    private final ProductRepository productRepository;
    private final AuditService auditService;

    @Transactional
    public Report submit(Long productId, String reasonType, String description,
                         Long userId, String username, ActorContext actor) {
        Product product = productRepository.findById(productId)
                .orElseThrow(() -> BusinessException.notFound("商品"));

        if (product.isOwnedBy(userId)) {
            throw BusinessException.badRequest("无法举报自己发布的闲置商品");
        }
        if (reportRepository.existsByUserIdAndProductIdAndStatus(userId, productId, PENDING)) {
            throw BusinessException.conflict("您已对该商品提交过举报，请耐心等待管理员处理");
        }

        Report report = new Report();
        report.setUserId(userId);
        report.setUsername(username);
        report.setProductId(productId);
        report.setProductName(product.getName());
        report.setSellerId(product.getSellerId());
        report.setReasonType(reasonType);
        report.setDescription(description);
        report.setStatus(PENDING);

        Report saved = reportRepository.save(report);
        audit(actor, AuditActions.REPORT_SUBMIT, saved.getId(),
                "举报商品 " + product.getName() + " 类型=" + reasonType);
        return saved;
    }

    @Transactional(readOnly = true)
    public List<Report> listMine(Long userId) {
        return reportRepository.findByUserIdOrderByCreateTimeDesc(userId);
    }

    @Transactional(readOnly = true)
    public List<Report> listAll(Integer status) {
        if (status != null && status >= 0) {
            return reportRepository.findByStatusOrderByCreateTimeDesc(status);
        }
        return reportRepository.findAllByOrderByCreateTimeDesc();
    }

    /** 管理员处理工单；status=VERIFIED 时连带下架商品 */
    @Transactional
    public Report handle(Long reportId, int status, String adminReply, ActorContext admin) {
        if (status != VERIFIED && status != DISMISSED) {
            throw BusinessException.badRequest("处理结果只能是 1（核实下架）或 2（驳回）");
        }
        Report report = reportRepository.findById(reportId)
                .orElseThrow(() -> BusinessException.notFound("举报工单"));

        report.setStatus(status);
        report.setAdminReply(adminReply);
        Report saved = reportRepository.save(report);

        if (status == VERIFIED) {
            productRepository.findById(report.getProductId()).ifPresent(p -> {
                if (p.statusEnum().canReject()) {
                    p.reject("被用户举报违规核实：" + report.getReasonType());
                    productRepository.save(p);
                }
            });
        }
        audit(admin, AuditActions.REPORT_HANDLE, reportId,
                "处理举报 status=" + status);
        return saved;
    }

    @Transactional(readOnly = true)
    public long countPending() {
        return reportRepository.findByStatusOrderByCreateTimeDesc(PENDING).size();
    }

    @Transactional(readOnly = true)
    public long countVisibleProducts() {
        return productRepository.countByStatus(ProductStatus.ON_SALE.code());
    }

    private void audit(ActorContext actor, String action, Long targetId, String detail) {
        if (actor == null) {
            actor = ActorContext.system();
        }
        auditService.record(actor.type(), actor.id(), actor.name(), action,
                "report", targetId, detail, "SUCCESS", null, actor.conversationId());
    }
}
