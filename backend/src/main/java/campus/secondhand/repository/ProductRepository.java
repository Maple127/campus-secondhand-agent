package campus.secondhand.repository;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import campus.secondhand.entity.Product;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.math.BigDecimal;
import java.util.List;

@Repository
public interface ProductRepository extends JpaRepository<Product, Long> {

    /** 全部商品，按发布时间倒序 */
    List<Product> findAllByOrderByCreateTimeDesc();

    /** 全部商品（分页） */
    Page<Product> findAllByOrderByCreateTimeDesc(Pageable pageable);

    /** 关键词搜索：名称 / 描述 / 地点 任意命中 */
    List<Product> findByNameContainingIgnoreCaseOrDescriptionContainingIgnoreCaseOrLocationContainingIgnoreCaseOrderByCreateTimeDesc(
            String name, String description, String location);

    /** 关键词搜索（分页） */
    Page<Product> findByNameContainingIgnoreCaseOrDescriptionContainingIgnoreCaseOrLocationContainingIgnoreCaseOrderByCreateTimeDesc(
            String name, String description, String location, Pageable pageable);

    /** 我发布的商品 */
    List<Product> findBySellerIdOrderByCreateTimeDesc(Long sellerId);

    /** 按审核状态查询 */
    List<Product> findByStatusOrderByCreateTimeDesc(Integer status);

    /** 按分类查询 */
    List<Product> findByCategoryIdOrderByCreateTimeDesc(Long categoryId);

    /** 按分类查询（分页） */
    Page<Product> findByCategoryOrderByCreateTimeDesc(String category, Pageable pageable);

    /** 按分类 + 关键词搜索 */
    List<Product> findByCategoryAndNameContainingIgnoreCaseOrCategoryAndDescriptionContainingIgnoreCaseOrCategoryAndLocationContainingIgnoreCaseOrderByCreateTimeDesc(
            String category1, String name, String category2, String description, String category3, String location);

    /** 按分类 + 关键词搜索（分页） */
    Page<Product> findByCategoryAndNameContainingIgnoreCaseOrCategoryAndDescriptionContainingIgnoreCaseOrCategoryAndLocationContainingIgnoreCaseOrderByCreateTimeDesc(
            String category1, String name, String category2, String description, String category3, String location, Pageable pageable);

    /** 按状态和关键词查询 */
    List<Product> findByStatusAndNameContainingIgnoreCaseOrderByCreateTimeDesc(Integer status, String keyword);

    /** 统计各状态商品数量 */
    long countByStatus(Integer status);

    // 按状态和分类名分页（categoryName 精确匹配）
    Page<Product> findByStatusAndCategoryNameOrderByCreateTimeDesc(int status, String categoryName, Pageable pageable);

    // 按状态+分类名+关键词模糊搜索（用 @Query 避免超长方法名）
    @Query("SELECT p FROM Product p WHERE p.status = :status AND p.categoryName = :categoryName " +
            "AND (p.name LIKE %:keyword% OR p.description LIKE %:keyword% OR p.location LIKE %:keyword%) " +
            "ORDER BY p.createTime DESC")
    Page<Product> findByStatusAndCategoryNameAndKeywordApproved(@Param("status") int status,
                                                                 @Param("categoryName") String categoryName,
                                                                 @Param("keyword") String keyword,
                                                                 Pageable pageable);

    // 按状态+关键词模糊搜索，三个字段（名称、描述、地点）同时匹配
    @Query("SELECT p FROM Product p WHERE p.status = :status AND " +
            "(p.name LIKE %:keyword% OR p.description LIKE %:keyword% OR p.location LIKE %:keyword%) " +
            "ORDER BY p.createTime DESC")
    Page<Product> findByStatusAndKeyword(@Param("status") int status,
                                         @Param("keyword") String keyword,
                                         Pageable pageable);

    // 分页查询：按状态过滤，时间倒序
    Page<Product> findByStatusOrderByCreateTimeDesc(int status, Pageable pageable);

    // ==================== Agent / REST 层需要的能力 ====================

    /**
     * 多条件组合检索：在售状态 + 可选分类 + 可选关键词 + 可选价格区间 + 品类词。
     *
     * ## 品类词为什么与关键词是 OR
     *
     * 用户搜「耳机」时，《AirPods Pro 2代》的名称/描述里都没有"耳机"两个字，
     * 只有 product_type 是「耳机」。所以品类命中必须能独立成立，不能被文本条件卡住。
     *
     * ## ORDER BY 里的 CASE
     *
     * 品类精确命中排在文本命中之前 —— 搜「键盘」时标了「键盘」的商品
     * 应该比"描述里顺带提到键盘"的商品更靠前。
     *
     * ## typeNames 为什么不能为空
     *
     * JPQL 的 `IN ()` 是非法语法。调用方在"没有命中任何品类"时传入
     * 一个不会匹配的哨兵值（见 ProductService），保证这条 SQL 始终合法。
     */
    @Query("""
            SELECT p FROM Product p
            WHERE p.status = :status
              AND (:categoryName IS NULL OR p.categoryName = :categoryName)
              AND (:minPrice IS NULL OR p.price >= :minPrice)
              AND (:maxPrice IS NULL OR p.price <= :maxPrice)
              AND (:keyword IS NULL
                   OR p.productType IN (:typeNames)
                   OR LOWER(p.name) LIKE LOWER(CONCAT('%', :keyword, '%'))
                   OR LOWER(p.description) LIKE LOWER(CONCAT('%', :keyword, '%'))
                   OR LOWER(p.location) LIKE LOWER(CONCAT('%', :keyword, '%')))
            ORDER BY CASE WHEN p.productType IN (:typeNames) THEN 0 ELSE 1 END,
                     p.createTime DESC
            """)
    Page<Product> search(@Param("status") int status,
                         @Param("categoryName") String categoryName,
                         @Param("keyword") String keyword,
                         @Param("minPrice") BigDecimal minPrice,
                         @Param("maxPrice") BigDecimal maxPrice,
                         @Param("typeNames") List<String> typeNames,
                         Pageable pageable);

    /** 查询一批ID中仍然对公众可见的商品（Agent 拿到向量召回结果后必须回主库复核） */
    @Query("SELECT p FROM Product p WHERE p.id IN :ids AND p.status IN :statuses")
    List<Product> findVisibleByIdIn(@Param("ids") List<Long> ids, @Param("statuses") List<Integer> statuses);

    /**
     * 同类商品价格样本，用于比价。
     *
     * `productType` 是比 `categoryName` 更细的一档：
     * 「数码电子」里同时躺着 45 元的耳机和 4200 元的笔记本，
     * 按分类取样得到的区间宽达 8.8 倍，对定价毫无参考价值；
     * 按品类（耳机 / 笔记本）取样才能给出真正可用的锚点。
     */
    @Query("""
            SELECT p FROM Product p
            WHERE p.status IN :statuses
              AND p.price IS NOT NULL
              AND (:productType IS NULL OR p.productType = :productType)
              AND (:categoryName IS NULL OR p.categoryName = :categoryName)
              AND (:conditionLevel IS NULL OR p.conditionLevel = :conditionLevel)
              AND (:excludeId IS NULL OR p.id <> :excludeId)
            """)
    List<Product> findPriceSamples(@Param("statuses") List<Integer> statuses,
                                   @Param("productType") String productType,
                                   @Param("categoryName") String categoryName,
                                   @Param("conditionLevel") String conditionLevel,
                                   @Param("excludeId") Long excludeId,
                                   Pageable pageable);
    /**
     * 同品类里比给定价格更便宜的在售商品数。
     *
     * 用途：议价时告诉买家"还有更便宜的"——这是谈判筹码，
     * 但我们只用它来解释和措辞，不拿它去改建议价（那样结果就难以解释了）。
     */
    @Query("""
            SELECT COUNT(p) FROM Product p
            WHERE p.status = :status
              AND p.productType = :productType
              AND p.price IS NOT NULL
              AND p.price < :price
              AND p.id <> :excludeId
            """)
    long countCheaper(@Param("status") int status,
                      @Param("productType") String productType,
                      @Param("price") BigDecimal price,
                      @Param("excludeId") Long excludeId);
}