package campus.secondhand.service;

import campus.secondhand.entity.Category;
import campus.secondhand.entity.ProductType;
import campus.secondhand.repository.CategoryRepository;
import campus.secondhand.repository.ProductTypeRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;

/**
 * 品类词服务：把「用户说的词」翻译成「商品上的品类」。
 *
 * ## 匹配规则（这是本模块的核心决策）
 *
 * **只做单向包含：标签词出现在查询里，才算命中。**
 *
 * 试过双向包含（"查询含标签" 或 "标签含查询"），会误召回：
 * 查询「自行车」时，「电动自行车」这个别名包含"自行车"，于是把
 * 《小牛电动车N1S》也带了出来。20 件商品的实测里，双向是 27/28 且 1 个误召回，
 * 单向是 28/28 且零误召回。
 *
 * 单向的代价是"用户输入比标签短"时会漏（搜「收纳」但标签是「收纳箱」）。
 * 解法不是放宽规则，而是**把短词写进别名**——每加一个词只是一行数据。
 *
 * 原则：**宁可漏，不可错。** 漏了用户换词还能找到；错了会直接失去信任。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductTypeService {

    private final ProductTypeRepository productTypeRepository;
    private final CategoryRepository categoryRepository;

    /** 词表很小且极少变，缓存 60 秒即可；管理员改完最多一分钟生效 */
    private volatile List<ProductType> cache;
    private volatile long cacheAt;

    @Transactional(readOnly = true)
    public List<ProductType> all() {
        long now = System.currentTimeMillis();
        List<ProductType> c = cache;
        if (c != null && now - cacheAt < 60_000L) {
            return c;
        }
        List<ProductType> fresh = productTypeRepository.findAllByOrderBySortOrderAscIdAsc();
        cache = fresh;
        cacheAt = now;
        return fresh;
    }

    /** 改动词表后调用，让下一次读取重新加载 */
    public void evictCache() {
        cache = null;
        cacheAt = 0L;
    }

    /**
     * 查询串能命中哪些品类词。
     *
     * @return 品类名列表（可能为空）。空表示"这串词里没有已知品类"，检索会退回纯文本匹配。
     */
    @Transactional(readOnly = true)
    public List<String> typesMatching(String query) {
        if (query == null || query.isBlank()) {
            return List.of();
        }
        String q = query.toLowerCase();
        List<String> hit = new ArrayList<>();
        for (ProductType t : all()) {
            for (String word : t.allWordsLower()) {
                if (!word.isEmpty() && q.contains(word)) {
                    hit.add(t.getName());
                    break;
                }
            }
        }
        return hit;
    }

    /**
     * 发布时的品类预选：从标题/描述里猜一个最可能的品类。
     *
     * 命中取**最长**的那个词——因为长词更具体：
     * 「机械键盘」比「键盘」更准，「airpods pro」比「耳」相关。
     *
     * 注意这是"猜"，前端必须让卖家能改。它只是把"从 50 个词里找"
     * 换成"看一眼、点确认"。
     */
    @Transactional(readOnly = true)
    public Optional<String> suggest(String text, String categoryName) {
        if (text == null || text.isBlank()) {
            return Optional.empty();
        }
        String t = text.toLowerCase();
        Long categoryId = resolveCategoryId(categoryName);

        String best = null;
        int bestScore = 0;
        for (ProductType type : all()) {
            // 分类下没有归属的词（categoryId 为空）视为全局通用
            if (categoryId != null && type.getCategoryId() != null
                    && !type.getCategoryId().equals(categoryId)) {
                continue;
            }
            for (String word : type.allWordsLower()) {
                if (!word.isEmpty() && t.contains(word) && word.length() > bestScore) {
                    best = type.getName();
                    bestScore = word.length();
                }
            }
        }
        return Optional.ofNullable(best);
    }

    /**
     * 查询串命中的品类词所归属的分类名。
     *
     * 用途：搜「显示器」但平台没货时，可以顺势推荐"数码电子里还有什么"。
     * 命不中品类词就返回空，调用方自己决定要不要退到全站推荐。
     */
    @Transactional(readOnly = true)
    public Optional<String> categoryOfMatchedType(String query) {
        if (query == null || query.isBlank()) {
            return Optional.empty();
        }
        List<String> hit = typesMatching(query);
        if (hit.isEmpty()) {
            return Optional.empty();
        }
        for (ProductType t : all()) {
            if (t.getName().equals(hit.get(0)) && t.getCategoryId() != null) {
                return categoryRepository.findAllByOrderByNameAsc().stream()
                        .filter(c -> c.getId().equals(t.getCategoryId()))
                        .map(Category::getName)
                        .findFirst();
            }
        }
        return Optional.empty();
    }

    /** 某个分类下的品类词，供发布页下拉 */
    @Transactional(readOnly = true)
    public List<ProductType> listByCategory(String categoryName) {
        Long categoryId = resolveCategoryId(categoryName);
        if (categoryId == null) {
            return all();
        }
        List<ProductType> out = new ArrayList<>();
        for (ProductType t : all()) {
            if (t.getCategoryId() == null || t.getCategoryId().equals(categoryId)) {
                out.add(t);
            }
        }
        return out;
    }

    /**
     * 商品落库前把品类词规范化：
     * - 传了就用传的（校验存在）
     * - 没传就按标题猜一个
     * - 都失败就留空（不阻断发布，和闲鱼"必填但可跳过"的取舍一致：
     *   我们优先保证能发出去，品类留给管理员补）
     */
    @Transactional(readOnly = true)
    public String resolveForPublish(String requested, String name, String description,
                                    String categoryName) {
        if (requested != null && !requested.isBlank()) {
            String trimmed = requested.trim();
            if (productTypeRepository.existsByName(trimmed)) {
                return trimmed;
            }
            log.debug("忽略未知品类词: {}", trimmed);
        }
        String text = ((name == null ? "" : name) + " " + (description == null ? "" : description)).trim();
        List<String> matched = typesMatching(text);
        if (!matched.isEmpty()) {
            return matched.get(0);
        }
        return suggest(text, categoryName).orElse(null);
    }

    /** 按词表热度无法得知，这里给一个稳定的排序：分类内按 sortOrder */
    @Transactional(readOnly = true)
    public List<String> namesByCategory(String categoryName) {
        List<ProductType> list = new ArrayList<>(listByCategory(categoryName));
        list.sort(Comparator.comparing(t -> t.getSortOrder() == null ? 0 : t.getSortOrder()));
        return list.stream().map(ProductType::getName).toList();
    }

    private Long resolveCategoryId(String categoryName) {
        if (categoryName == null || categoryName.isBlank()) {
            return null;
        }
        Category c = categoryRepository.findByName(categoryName);
        return c == null ? null : c.getId();
    }
}
