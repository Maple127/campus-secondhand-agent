package campus.secondhand.service;

import campus.secondhand.common.ActorContext;
import campus.secondhand.common.AuditActions;
import campus.secondhand.common.BusinessException;
import campus.secondhand.entity.Category;
import campus.secondhand.repository.CategoryRepository;
import campus.secondhand.repository.ProductRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 分类领域服务（管理员维护）。
 */
@Service
@RequiredArgsConstructor
public class CategoryService {

    private final CategoryRepository categoryRepository;
    private final ProductRepository productRepository;
    private final AuditService auditService;

    @Transactional(readOnly = true)
    public List<Category> listAll() {
        return categoryRepository.findAllByOrderByNameAsc();
    }

    @Transactional(readOnly = true)
    public Category getById(Long id) {
        return categoryRepository.findById(id)
                .orElseThrow(() -> BusinessException.notFound("分类"));
    }

    @Transactional
    public Category create(String name, String description, ActorContext admin) {
        if (categoryRepository.existsByName(name)) {
            throw BusinessException.conflict("分类名称已存在：" + name);
        }
        Category category = new Category();
        category.setName(name);
        category.setDescription(description);
        Category saved = categoryRepository.save(category);
        audit(admin, AuditActions.CATEGORY_CREATE, saved.getId(), "新增分类 " + name);
        return saved;
    }

    @Transactional
    public Category update(Long id, String name, String description, ActorContext admin) {
        Category category = getById(id);

        // 名称冲突检查：允许改成自己原来的名字
        Category existing = categoryRepository.findByName(name);
        if (existing != null && !existing.getId().equals(id)) {
            throw BusinessException.conflict("分类名称已存在：" + name);
        }

        category.setName(name);
        category.setDescription(description);
        Category saved = categoryRepository.save(category);
        audit(admin, AuditActions.CATEGORY_UPDATE, saved.getId(), "修改分类 " + name);
        return saved;
    }

    @Transactional
    public void delete(Long id, ActorContext admin) {
        Category category = getById(id);
        long inUse = productRepository.findByCategoryIdOrderByCreateTimeDesc(id).size();
        if (inUse > 0) {
            throw BusinessException.conflict("该分类下还有 " + inUse + " 件商品，无法删除");
        }
        categoryRepository.delete(category);
        audit(admin, AuditActions.CATEGORY_DELETE, id, "删除分类 " + category.getName());
    }

    private void audit(ActorContext actor, String action, Long targetId, String detail) {
        if (actor == null) {
            actor = ActorContext.system();
        }
        auditService.record(actor.type(), actor.id(), actor.name(), action,
                "category", targetId, detail, "SUCCESS", null, actor.conversationId());
    }
}
