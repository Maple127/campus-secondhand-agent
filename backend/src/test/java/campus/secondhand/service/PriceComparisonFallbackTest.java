package campus.secondhand.service;

import campus.secondhand.entity.Category;
import campus.secondhand.entity.Product;
import campus.secondhand.repository.CategoryRepository;
import campus.secondhand.repository.ProductRepository;
import campus.secondhand.repository.ProductTypeRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.data.domain.Pageable;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 价格参考的**样本收窄与降级策略**测试。
 *
 * 这块逻辑容易写错且后果隐性：一旦降级策略不对，用户会拿到
 * "看着有道理、其实答非所问"的数字。比如给「图书教材」定价时
 * 参考到全平台的均价（含 1800 的电动车），比没有参考更糟。
 */
class PriceComparisonFallbackTest {

    private ProductRepository productRepository;
    private CategoryRepository categoryRepository;
    private PriceComparisonService service;

    @BeforeEach
    void setUp() {
        productRepository = mock(ProductRepository.class);
        categoryRepository = mock(CategoryRepository.class);

        // 品类词表在本测试里为空：比价逻辑不依赖它，但 ProductService 需要这个依赖
        ProductTypeRepository productTypeRepository = mock(ProductTypeRepository.class);
        when(productTypeRepository.findAllByOrderBySortOrderAscIdAsc()).thenReturn(List.of());
        ProductTypeService productTypeService =
                new ProductTypeService(productTypeRepository, categoryRepository);

        ProductService productService = new ProductService(
                productRepository, categoryRepository, mock(AuditService.class), productTypeService);
        CategoryService categoryService = new CategoryService(
                categoryRepository, productRepository, mock(AuditService.class));
        service = new PriceComparisonService(productService, categoryService);
    }

    private static Product product(long id, String name, String category, String price) {
        Product p = new Product();
        p.setId(id);
        p.setName(name);
        p.setCategoryName(category);
        p.setCategory(category);
        p.setPrice(new BigDecimal(price));
        return p;
    }

    private void categoryExists(String name) {
        Category c = new Category();
        c.setName(name);
        when(categoryRepository.findAllByOrderByNameAsc()).thenReturn(List.of(c));
    }

    private void samplesReturned(List<Product> samples) {
        when(productRepository.findPriceSamples(anyList(), any(), any(), any(), any(), any(Pageable.class)))
                .thenReturn(samples);
    }

    // =====================================================================

    @Test
    @DisplayName("分类不存在时应明确说没找到，而不是放宽到全部分类")
    void unknownCategoryDoesNotFallBack() {
        when(categoryRepository.findAllByOrderByNameAsc()).thenReturn(List.of());

        PriceComparison r = service.suggestFor("数码产品", null, null, 50);

        assertEquals(PriceComparison.VERDICT_INSUFFICIENT, r.verdict());
        assertTrue(r.explanation().contains("没有找到分类"), r.explanation());
        assertEquals(0, r.sampleSize());
    }

    @Test
    @DisplayName("定价建议在分类无货时不放宽范围，宁可说样本不足")
    void suggestDoesNotWidenAcrossCategories() {
        categoryExists("服装鞋帽");
        // 该分类下没有任何样本
        when(productRepository.findPriceSamples(anyList(), any(), eq("服装鞋帽"), any(), any(), any(Pageable.class)))
                .thenReturn(List.of());
        // 全平台有 19 件（含高价的电动车等），若能放宽就会被误用
        when(productRepository.findPriceSamples(anyList(), any(), isNull(), isNull(), isNull(), any(Pageable.class)))
                .thenReturn(List.of(
                        product(1, "小牛电动车N1S", "体育器材", "1800"),
                        product(2, "AirPods Pro 2代", "数码电子", "680"),
                        product(3, "机械键盘", "数码电子", "200")));

        PriceComparison r = service.suggestFor("服装鞋帽", null, new BigDecimal("30"), 50);

        assertEquals(PriceComparison.VERDICT_INSUFFICIENT, r.verdict(),
                "不该给出跨分类的假参考");
        assertTrue(r.explanation().contains("样本不足"), r.explanation());
        assertNull(r.median(), "样本不足时不能返回中位价，否则前端会显示误导数字");
    }

    @Test
    @DisplayName("商品详情页允许放宽范围，但要标明已放宽")
    void productComparisonMayWidenAndSaysSo() {
        categoryExists("图书教材");
        when(productRepository.findPriceSamples(anyList(), any(), eq("图书教材"), any(), any(), any(Pageable.class)))
                .thenReturn(List.of());
        when(productRepository.findPriceSamples(anyList(), any(), isNull(), isNull(), any(), any(Pageable.class)))
                .thenReturn(List.of(
                        product(1, "数据结构", "图书教材", "18"),
                        product(2, "线性代数", "图书教材", "15"),
                        product(3, "机械键盘", "数码电子", "200"),
                        product(4, "小风扇", "生活用品", "30")));

        Product target = product(99, "高等数学", "图书教材", "25");
        PriceComparison r = service.compareFor(target, 50);

        assertEquals(4, r.sampleSize());
        assertNotNull(r.median());
        assertTrue(r.explanation().contains("放宽"),
                "放宽了范围就必须说明，否则用户会以为是同类统计：" + r.explanation());
    }

    @Test
    @DisplayName("同分类样本充足时按分类统计，并给出合理/偏高/偏低判断")
    void enoughSamplesGivesVerdict() {
        categoryExists("图书教材");
        samplesReturned(List.of(
                product(1, "a", "图书教材", "10"),
                product(2, "b", "图书教材", "16"),
                product(3, "c", "图书教材", "20"),
                product(4, "d", "图书教材", "30")));

        // 100 明显高于 p75，应判 HIGH
        PriceComparison high = service.suggestFor("图书教材", null, new BigDecimal("100"), 50);
        assertEquals(PriceComparison.VERDICT_HIGH, high.verdict());
        assertEquals(4, high.sampleSize());

        // 18 落在 p25~p75 内，应判 FAIR
        PriceComparison fair = service.suggestFor("图书教材", null, new BigDecimal("18"), 50);
        assertEquals(PriceComparison.VERDICT_FAIR, fair.verdict());
    }

    @Test
    @DisplayName("不传目标价时只报行情，不给高低判断")
    void noTargetPriceMeansNoVerdict() {
        categoryExists("图书教材");
        samplesReturned(List.of(
                product(1, "a", "图书教材", "10"),
                product(2, "b", "图书教材", "16"),
                product(3, "c", "图书教材", "20")));

        PriceComparison r = service.suggestFor("图书教材", null, null, 50);

        assertNull(r.verdict(), "没有目标价就不该判高低");
        assertNotNull(r.median());
        assertTrue(r.explanation().contains("参考"));
    }

    @Test
    @DisplayName("成色样本不足时自动降级为仅按分类统计")
    void fallsBackFromConditionToCategory() {
        categoryExists("数码电子");
        // 指定成色时无样本，去掉成色后有 3 条
        when(productRepository.findPriceSamples(anyList(), any(), eq("数码电子"), eq("全新"), any(), any(Pageable.class)))
                .thenReturn(List.of());
        when(productRepository.findPriceSamples(anyList(), any(), eq("数码电子"), isNull(), any(), any(Pageable.class)))
                .thenReturn(List.of(
                        product(1, "a", "数码电子", "100"),
                        product(2, "b", "数码电子", "200"),
                        product(3, "c", "数码电子", "300")));

        PriceComparison r = service.suggestFor("数码电子", "全新", new BigDecimal("200"), 50);

        assertEquals(3, r.sampleSize());
        assertNull(r.conditionLevel(), "降级后不应再声称按成色统计");
        assertEquals(PriceComparison.VERDICT_FAIR, r.verdict());
    }
}
