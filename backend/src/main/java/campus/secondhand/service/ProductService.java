package campus.secondhand.service;

import campus.secondhand.common.ActorContext;
import campus.secondhand.common.AuditActions;
import campus.secondhand.common.BusinessException;
import campus.secondhand.common.PageResult;
import campus.secondhand.common.ProductQuery;
import campus.secondhand.entity.Category;
import campus.secondhand.entity.Product;
import campus.secondhand.entity.ProductStatus;
import campus.secondhand.repository.CategoryRepository;
import campus.secondhand.repository.ProductRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 商品领域服务 —— 商品相关的唯一业务入口。
 *
 * 网页 Controller、REST Controller、Admin Controller 全部通过这里操作商品，
 * 状态机校验、分类归一化、审计都只在这一处发生。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductService {

    private final ProductRepository productRepository;
    private final CategoryRepository categoryRepository;
    private final AuditService auditService;
    private final ProductTypeService productTypeService;

    /**
     * 品类词扩展开关。默认开启。
     *
     * 加这个开关的唯一目的是**消融评测**：关掉它就能测出
     * "品类词到底贡献了多少召回"，而不是只能凭感觉说"有用"。
     * 线上没人会去关它。
     */
    @Value("${app.search.type-match-enabled:true}")
    private boolean typeMatchEnabled;

    /** `IN ()` 在 JPQL 里非法，没命中品类时用这个不可能匹配的值占位 */
    private static final List<String> NO_TYPE = List.of("__NO_TYPE__");

    // ==================== 查询 ====================

    /**
     * 组合检索。默认只返回在售商品（面向买家）。
     * 这是网页首页 / REST / Agent 搜索工具共用的入口。
     */
    @Transactional(readOnly = true)
    public PageResult<Product> search(ProductQuery query, ProductStatus status) {
        Pageable pageable = toPageable(query);
        Page<Product> page = productRepository.search(
                status.code(),
                query.getCategoryName(),
                query.getKeyword(),
                query.getMinPrice(),
                query.getMaxPrice(),
                typeNamesFor(query.getKeyword()),
                pageable);
        return PageResult.from(page, p -> p);
    }

    /**
     * 把用户输入里的"品类词"翻译成商品上的 product_type。
     *
     * 没命中就返回哨兵值 —— 检索会退回纯文本匹配，行为和改造前完全一致。
     * 也就是说：**词表覆盖不到的词，不会比以前更差。**
     */
    private List<String> typeNamesFor(String keyword) {
        if (!typeMatchEnabled) {
            // 消融评测用：关掉品类词扩展，观察"纯文本匹配"能召回多少。
            // 线上永远是 true，这个开关只通过配置临时关闭。
            return NO_TYPE;
        }
        List<String> matched = productTypeService.typesMatching(keyword);
        return matched.isEmpty() ? NO_TYPE : matched;
    }

    /** 兼容原首页签名：在售商品的关键词/分类分页查询 */
    @Transactional(readOnly = true)
    public Page<Product> searchOnSale(String keyword, String category, int page, int size) {
        return searchOnSale(ProductQuery.of(keyword, category, page, size));
    }

    /**
     * 首页检索：支持关键词 / 分类 / 价格区间 / 排序。
     *
     * 之前这里有个真实缺陷：原实现只把 keyword 与 category 传下去，
     * `minPrice` / `maxPrice` 被静默丢弃 —— 即"价格筛选"有入参但不生效。
     * 现在统一走 ProductQuery，参数不会再掉。
     */
    @Transactional(readOnly = true)
    public Page<Product> searchOnSale(ProductQuery query) {
        return productRepository.search(
                ProductStatus.ON_SALE.code(),
                query.getCategoryName(),
                query.getKeyword(),
                query.getMinPrice(),
                query.getMaxPrice(),
                typeNamesFor(query.getKeyword()),
                toPageable(query));
    }

    /**
     * 零结果时给用户看什么 —— 把"搜不到"从死路变成入口。
     *
     * 返回三种值：
     *   null       —— 不需要提示（有关键词且有结果，或者根本没搜关键词）
     *   TYPE_EMPTY —— 词表认识这个说法，但平台没有这类货 → "平台还没人挂「显示器」"
     *   NO_TYPE    —— 词表不认识这个说法 → "换个说法试试"
     *
     * 判断依据：只要品类词命中了，而结果仍然是 0，就说明该品类下确实没有在售商品
     * （因为检索条件里有 `productType IN (...)` 这一支）。
     */
    @Transactional(readOnly = true)
    public String emptyHint(String keyword) {
        if (keyword == null || keyword.isBlank()) {
            return null;
        }
        return productTypeService.typesMatching(keyword).isEmpty() ? "NO_TYPE" : "TYPE_EMPTY";
    }

    /**
     * 零结果时的替代推荐：优先推同类目，其次全站最新。
     *
     * 目的不是"凑数"，而是让用户在一次失败的搜索之后还能看到点东西，
     * 而不是面对一个空页面然后离开。
     */
    @Transactional(readOnly = true)
    public List<Product> suggestAlternatives(String keyword, String categoryName, int limit) {
        String target = categoryName;
        if (target == null || target.isBlank()) {
            target = productTypeService.categoryOfMatchedType(keyword).orElse(null);
        }
        Page<Product> page = searchOnSale(ProductQuery.of(null, target, 0, limit));
        if (page.getTotalElements() == 0 && target != null) {
            // 命中的分类也没货，退到全站
            page = searchOnSale(ProductQuery.of(null, null, 0, limit));
        }
        return page.getContent();
    }

    @Transactional(readOnly = true)
    public Product getById(Long id) {
        return productRepository.findById(id)
                .orElseThrow(() -> BusinessException.notFound("商品"));
    }

    @Transactional(readOnly = true)
    public Product getVisibleById(Long id) {
        Product p = getById(id);
        if (!p.statusEnum().isPubliclyVisible()) {
            throw BusinessException.notFound("商品");
        }
        return p;
    }

    /** Agent 向量召回后回主库复核：只保留仍然对公众可见的商品 */
    @Transactional(readOnly = true)
    public List<Product> filterVisible(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return List.of();
        }
        return productRepository.findVisibleByIdIn(ids,
                List.of(ProductStatus.ON_SALE.code(), ProductStatus.SOLD.code()));
    }

    @Transactional(readOnly = true)
    public List<Product> listBySeller(Long sellerId) {
        return productRepository.findBySellerIdOrderByCreateTimeDesc(sellerId);
    }

    @Transactional(readOnly = true)
    public List<Product> listByStatus(ProductStatus status) {
        return productRepository.findByStatusOrderByCreateTimeDesc(status.code());
    }

    @Transactional(readOnly = true)
    public List<Product> listByStatusAndKeyword(ProductStatus status, String keyword) {
        if (keyword == null || keyword.isBlank()) {
            return listByStatus(status);
        }
        return productRepository.findByStatusAndNameContainingIgnoreCaseOrderByCreateTimeDesc(
                status.code(), keyword.trim());
    }

    @Transactional(readOnly = true)
    public long countByStatus(ProductStatus status) {
        return productRepository.countByStatus(status.code());
    }

    /** 管理端：全部商品（不限状态） */
    @Transactional(readOnly = true)
    public List<Product> listAll() {
        return productRepository.findAllByOrderByCreateTimeDesc();
    }

    /** 管理端：全部商品 + 关键词过滤 */
    @Transactional(readOnly = true)
    public List<Product> searchAllForAdmin(String keyword) {
        if (keyword == null || keyword.isBlank()) {
            return listAll();
        }
        return productRepository
                .findByNameContainingIgnoreCaseOrDescriptionContainingIgnoreCaseOrLocationContainingIgnoreCaseOrderByCreateTimeDesc(
                        keyword.trim(), keyword.trim(), keyword.trim());
    }

    // ==================== 写入 ====================

    /**
     * 发布商品（网页表单 / Agent 代发布共用）。
     *
     * 无论来源如何，商品一律进入"待审核"，不绕过管理员审核。
     */
    @Transactional
    public Product publish(ProductPublishCommand cmd, Long sellerId, String sellerName,
                           String sellerPhone, ActorContext actor) {
        Product product = new Product();
        product.setName(cmd.name().trim());
        product.setDescription(cmd.description());
        product.setPrice(cmd.price());
        product.setOriginalPrice(cmd.originalPrice());
        product.setConditionLevel(cmd.conditionLevel());
        product.setLocation(cmd.location());
        product.setImage(cmd.imagePath());
        product.setSellerId(sellerId);
        product.setSellerName(sellerName);
        product.setSellerPhone(sellerPhone);
        product.applyStatus(ProductStatus.PENDING_APPROVAL);

        applyCategory(product, cmd.categoryId(), cmd.categoryName());

        // 品类词：卖家选了就用他的；没选就按标题猜一个；猜不出就留空。
        // 留空不影响上架 —— 卡住发布比少一个标签更糟。
        product.setProductType(productTypeService.resolveForPublish(
                cmd.productType(), cmd.name(), cmd.description(), product.getCategoryName()));

        Product saved = productRepository.save(product);

        audit(actor, AuditActions.PRODUCT_PUBLISH, saved.getId(),
                "发布商品 name=" + saved.getName() + " price=" + saved.getPrice());
        return saved;
    }

    /** 卖家修改自己的商品（修改后需重新审核吗？这里保持：仅在售→待审核的策略关闭，直接更新） */
    @Transactional
    public Product updateOwnProduct(Long productId, Long sellerId, ProductPublishCommand cmd, ActorContext actor) {
        Product product = getById(productId);
        requireOwner(product, sellerId);

        product.setName(cmd.name().trim());
        product.setDescription(cmd.description());
        product.setPrice(cmd.price());
        product.setOriginalPrice(cmd.originalPrice());
        product.setConditionLevel(cmd.conditionLevel());
        product.setLocation(cmd.location());
        if (cmd.imagePath() != null) {
            product.setImage(cmd.imagePath());
        }
        applyCategory(product, cmd.categoryId(), cmd.categoryName());
        product.setProductType(productTypeService.resolveForPublish(
                cmd.productType(), cmd.name(), cmd.description(), product.getCategoryName()));

        Product saved = productRepository.save(product);
        audit(actor, AuditActions.PRODUCT_UPDATE, saved.getId(), "修改商品 name=" + saved.getName());
        return saved;
    }

    /** 卖家主动下架 */
    @Transactional
    public Product delist(Long productId, Long sellerId, ActorContext actor) {
        Product product = getById(productId);
        requireOwner(product, sellerId);
        guardStateChange(product, ProductStatus.DELISTED, () -> product.delist());

        Product saved = productRepository.save(product);
        audit(actor, AuditActions.PRODUCT_DELIST, saved.getId(), "下架商品");
        return saved;
    }

    /** 重新提交审核 */
    @Transactional
    public Product relist(Long productId, Long sellerId, ActorContext actor) {
        Product product = getById(productId);
        requireOwner(product, sellerId);
        guardStateChange(product, ProductStatus.PENDING_APPROVAL, () -> product.relist());

        Product saved = productRepository.save(product);
        audit(actor, AuditActions.PRODUCT_RELIST, saved.getId(), "重新提交审核");
        return saved;
    }

    // ==================== 管理员审核 ====================

    @Transactional
    public Product approve(Long productId, ActorContext admin) {
        Product product = getById(productId);
        guardStateChange(product, ProductStatus.ON_SALE, () -> product.approve());

        Product saved = productRepository.save(product);
        audit(admin, AuditActions.PRODUCT_APPROVE, saved.getId(), "审核通过");
        return saved;
    }

    @Transactional
    public Product reject(Long productId, String reason, ActorContext admin) {
        Product product = getById(productId);
        guardStateChange(product, ProductStatus.REJECTED, () -> product.reject(reason));

        Product saved = productRepository.save(product);
        audit(admin, AuditActions.PRODUCT_REJECT, saved.getId(), "审核拒绝 reason=" + reason);
        return saved;
    }

    @Transactional
    public void delete(Long productId, ActorContext admin) {
        Product product = getById(productId);
        if (product.statusEnum() == ProductStatus.SOLD) {
            throw BusinessException.conflict("已售出的商品不可删除，请保留交易记录");
        }
        productRepository.delete(product);
        audit(admin, AuditActions.PRODUCT_DELETE, productId, "删除商品 name=" + product.getName());
    }

    // ==================== 内部工具 ====================

    /**
     * 分类归一化。
     *
     * 保留原实现的"模糊匹配"兼容策略（前端可能传短名/别名），
     * 但去掉原先重复执行两遍的 categoryId 处理代码。
     */
    private void applyCategory(Product product, Long categoryId, String categoryName) {
        if (categoryId != null) {
            categoryRepository.findById(categoryId).ifPresent(c -> {
                product.setCategoryId(c.getId());
                product.setCategoryName(c.getName());
                product.setCategory(c.getName());
            });
            return;
        }
        if (categoryName == null || categoryName.isBlank()) {
            return;
        }
        Category matched = resolveCategoryByName(categoryName.trim());
        if (matched != null) {
            product.setCategoryId(matched.getId());
            product.setCategoryName(matched.getName());
            product.setCategory(matched.getName());
        }
    }

    private Category resolveCategoryByName(String name) {
        Category exact = categoryRepository.findByName(name);
        if (exact != null) {
            return exact;
        }
        for (Category c : categoryRepository.findAll()) {
            if (c.getName().contains(name) || name.contains(c.getName())) {
                return c;
            }
        }
        return null;
    }

    private void requireOwner(Product product, Long sellerId) {
        if (!product.isOwnedBy(sellerId)) {
            throw BusinessException.forbidden("只能操作自己发布的商品");
        }
    }

    /**
     * 把实体内部抛出的 IllegalStateException 翻译成可对外展示的业务异常。
     * 状态机规则写在实体里，异常语义在这一层统一。
     */
    private void guardStateChange(Product product, ProductStatus expected, Runnable action) {
        if (!product.statusEnum().allowedNext().contains(expected)) {
            throw BusinessException.conflict(
                    "商品当前状态为「" + product.statusEnum().label() + "」，不允许变更为「" + expected.label() + "」");
        }
        try {
            action.run();
        } catch (IllegalStateException e) {
            throw BusinessException.conflict(e.getMessage());
        }
    }

    private Pageable toPageable(ProductQuery query) {
        Sort sort = "price".equalsIgnoreCase(query.getSortBy())
                ? Sort.by("asc".equalsIgnoreCase(query.getDirection()) ? Sort.Direction.ASC : Sort.Direction.DESC, "price")
                : Sort.by("asc".equalsIgnoreCase(query.getDirection()) ? Sort.Direction.ASC : Sort.Direction.DESC, "createTime");
        return PageRequest.of(query.getPage(), query.getSize(), sort);
    }

    private void audit(ActorContext actor, String action, Long targetId, String detail) {
        if (actor == null) {
            actor = ActorContext.system();
        }
        auditService.record(actor.type(), actor.id(), actor.name(), action,
                "product", targetId, detail, "SUCCESS", null, actor.conversationId());
    }

    /** 供内部/测试使用：直接按ID取（含不可见状态） */
    @Transactional(readOnly = true)
    public Product findByIdOrNull(Long id) {
        return id == null ? null : productRepository.findById(id).orElse(null);
    }

    /** 商品是否存在且属于该卖家 */
    @Transactional(readOnly = true)
    public boolean isOwnedBy(Long productId, Long sellerId) {
        Product p = findByIdOrNull(productId);
        return p != null && p.isOwnedBy(sellerId);
    }

    /** 价格样本，供比价服务使用 */
    @Transactional(readOnly = true)
    public List<Product> priceSamples(String categoryName, String conditionLevel, Long excludeId, int limit) {
        return priceSamples(null, categoryName, conditionLevel, excludeId, limit);
    }

    /**
     * 取价格样本。产品品类（耳机/笔记本）比分类（数码电子）细一档，
     * 优先按品类取样，品类样本不足时上层再退回分类。
     */
    @Transactional(readOnly = true)
    public List<Product> priceSamples(String productType, String categoryName,
                                      String conditionLevel, Long excludeId, int limit) {
        return productRepository.findPriceSamples(
                List.of(ProductStatus.ON_SALE.code(), ProductStatus.SOLD.code()),
                productType, categoryName, conditionLevel, excludeId,
                PageRequest.of(0, Math.max(1, Math.min(limit, 200))));
    }
}
