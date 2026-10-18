package campus.secondhand.service;

import campus.secondhand.common.AuditActions;
import campus.secondhand.common.BusinessException;
import campus.secondhand.entity.Admin;
import campus.secondhand.entity.ActorType;
import campus.secondhand.repository.AdminRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 管理员账号服务。
 *
 * 注意：与原实现一致，密码仍是明文比对。
 * 这里把登录与改密收敛到一处，后续替换 BCrypt 只需要改这个类。
 */
@Service
@RequiredArgsConstructor
public class AdminService {

    private final AdminRepository adminRepository;
    private final AuditService auditService;

    @Transactional
    public Admin authenticate(String username, String password) {
        Admin admin = adminRepository.findByUsernameAndPassword(username, password);
        if (admin == null) {
            throw BusinessException.unauthorized("用户名或密码错误");
        }
        auditService.record(ActorType.ADMIN, admin.getId(), admin.getUsername(),
                AuditActions.USER_LOGIN, "admin", admin.getId(), "管理员登录", "SUCCESS", null, null);
        return admin;
    }

    @Transactional
    public Admin changePassword(Long adminId, String oldPassword, String newPassword, String confirmPassword) {
        Admin admin = adminRepository.findById(adminId)
                .orElseThrow(() -> BusinessException.notFound("管理员"));

        if (!admin.getPassword().equals(oldPassword)) {
            throw BusinessException.badRequest("原密码错误");
        }
        if (!newPassword.equals(confirmPassword)) {
            throw BusinessException.badRequest("两次输入的密码不一致");
        }
        if (newPassword.length() < 4) {
            throw BusinessException.badRequest("新密码长度至少 4 位");
        }

        admin.setPassword(newPassword);
        return adminRepository.save(admin);
    }

    @Transactional(readOnly = true)
    public Admin getById(Long id) {
        return adminRepository.findById(id)
                .orElseThrow(() -> BusinessException.notFound("管理员"));
    }

    @Transactional(readOnly = true)
    public Admin findByUsername(String username) {
        return adminRepository.findByUsername(username);
    }

    @Transactional(readOnly = true)
    public long count() {
        return adminRepository.count();
    }
}
