package campus.secondhand.config;

import campus.secondhand.common.ActorContext;
import campus.secondhand.entity.Admin;
import campus.secondhand.repository.AdminRepository;
import campus.secondhand.service.AuditService;
import campus.secondhand.service.CategoryService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

/**
 * 启动引导数据。
 *
 * 职责收窄为"保证管理员账号存在"：
 * 分类初始化已由 {@link DatabaseUpgrader} 用 INSERT IGNORE 幂等完成，
 * 这里不再重复创建，避免两处逻辑互相覆盖。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class DataInitializer implements CommandLineRunner {

    private final AdminRepository adminRepository;
    private final CategoryService categoryService;
    private final AuditService auditService;

    @Override
    public void run(String... args) {
        Admin admin = adminRepository.findByUsername("admin");
        if (admin == null) {
            admin = new Admin();
            admin.setUsername("admin");
            admin.setPassword("admin");
            adminRepository.save(admin);
            log.info("已创建默认管理员账号: admin/admin");
            auditService.success(campus.secondhand.entity.ActorType.SYSTEM, null, "bootstrap",
                    "admin.bootstrap", "admin", admin.getId(), "创建默认管理员");
        }

        // 兜底：若 category 表为空（例如手工删库后启动），补齐默认分类
        if (categoryService.listAll().isEmpty()) {
            log.warn("category 表为空，正在补齐默认分类");
            String[] defaults = {"图书教材", "数码电子", "生活用品", "体育器材", "服装鞋帽", "其他"};
            for (String name : defaults) {
                try {
                    categoryService.create(name, name + "（自动初始化）", ActorContext.system());
                } catch (Exception e) {
                    log.debug("分类 {} 已存在，跳过", name);
                }
            }
        }
    }
}
