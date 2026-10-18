package campus.secondhand.service;

import campus.secondhand.common.ActorContext;
import campus.secondhand.common.AuditActions;
import campus.secondhand.common.BusinessException;
import campus.secondhand.entity.User;
import campus.secondhand.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Random;

/**
 * 用户领域服务。
 *
 * 原实现把"随机学校/年级/手机号补全"的逻辑写在 login_controller 里，
 * 现在收敛到这里，网页登录与 API 登录共用。
 *
 * ⚠️ 已知安全债：密码仍为明文比对（与原实现一致）。
 * 本 demo 不引入 Spring Security，但把比对入口收敛到 authenticate() 一处，
 * 便于后续替换为 BCrypt。
 */
@Service
@RequiredArgsConstructor
public class UserService {

    private final UserRepository userRepository;
    private final JdbcTemplate jdbcTemplate;
    private final AuditService auditService;

    private final Random random = new Random();

    @Transactional
    public User authenticate(String username, String password) {
        User user = userRepository.findByUsernameAndPassword(username, password);
        if (user == null) {
            throw BusinessException.unauthorized("用户名或密码错误");
        }
        fillDemoProfileIfMissing(user);
        userRepository.save(user);
        auditService.record(campus.secondhand.entity.ActorType.USER, user.getId(), user.getUsername(),
                AuditActions.USER_LOGIN, "user", user.getId(), "登录成功", "SUCCESS", null, null);
        return user;
    }

    @Transactional
    public User register(String username, String password) {
        if (userRepository.existsByUsername(username)) {
            throw BusinessException.conflict("用户名已存在");
        }
        User user = new User();
        user.setUsername(username);
        user.setPassword(password);
        User saved = userRepository.save(user);
        auditService.record(campus.secondhand.entity.ActorType.USER, saved.getId(), saved.getUsername(),
                AuditActions.USER_REGISTER, "user", saved.getId(), "注册成功", "SUCCESS", null, null);
        return saved;
    }

    @Transactional
    public User updateProfile(Long userId, String school, String grade, String phone,
                              String shippingAddress, ActorContext actor) {
        User user = getById(userId);
        user.setSchool(school);
        user.setGrade(grade);
        user.setPhone(phone);
        user.setShippingAddress(shippingAddress);
        User saved = userRepository.save(user);
        audit(actor, AuditActions.USER_UPDATE_PROFILE, userId, "更新个人资料");
        return saved;
    }

    @Transactional(readOnly = true)
    public User getById(Long id) {
        return userRepository.findById(id)
                .orElseThrow(() -> BusinessException.notFound("用户"));
    }

    /** 按主键查询，不存在返回 null（供后台页面使用） */
    @Transactional(readOnly = true)
    public User findByIdOrNull(Long id) {
        return id == null ? null : userRepository.findById(id).orElse(null);
    }

    @Transactional(readOnly = true)
    public List<User> listAll() {
        return userRepository.findAll();
    }

    /** demo 数据补齐：首次登录时为缺少资料的用户随机生成学校/年级/手机号/收货地址 */
    private void fillDemoProfileIfMissing(User user) {
        if (user.getSchool() == null) {
            List<String> schools = jdbcTemplate.queryForList("SELECT name FROM school", String.class);
            if (!schools.isEmpty()) {
                user.setSchool(schools.get(random.nextInt(schools.size())));
            }
        }
        if (user.getGrade() == null) {
            String[] grades = {"大一", "大二", "大三", "大四", "研一", "研二"};
            user.setGrade(grades[random.nextInt(grades.length)]);
        }
        if (user.getPhone() == null) {
            user.setPhone(randomPhone());
        }
        if (user.getShippingAddress() == null) {
            List<String> addresses = jdbcTemplate.queryForList(
                    "SELECT CONCAT(name,' - ',address) FROM school", String.class);
            if (!addresses.isEmpty()) {
                user.setShippingAddress(addresses.get(random.nextInt(addresses.size())));
            }
        }
    }

    private String randomPhone() {
        String[] prefixes = {
                "130", "131", "132", "133", "134", "135", "136", "137",
                "150", "151", "152", "153", "155", "156", "157", "158",
                "170", "171", "172", "173", "175", "176", "177",
                "180", "181", "182", "183", "184", "185", "186", "187", "188"
        };
        StringBuilder sb = new StringBuilder(prefixes[random.nextInt(prefixes.length)]);
        for (int i = 0; i < 8; i++) {
            sb.append(random.nextInt(10));
        }
        return sb.toString();
    }

    private void audit(ActorContext actor, String action, Long targetId, String detail) {
        if (actor == null) {
            actor = ActorContext.system();
        }
        auditService.record(actor.type(), actor.id(), actor.name(), action,
                "user", targetId, detail, "SUCCESS", null, actor.conversationId());
    }
}
