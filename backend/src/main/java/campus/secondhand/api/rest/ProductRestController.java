package campus.secondhand.api.rest;

import campus.secondhand.api.ApiResponse;
import campus.secondhand.api.dto.ProductView;
import campus.secondhand.common.BusinessException;
import campus.secondhand.common.PageResult;
import campus.secondhand.common.ProductQuery;
import campus.secondhand.entity.Product;
import campus.secondhand.security.ActorContextHolder;
import campus.secondhand.service.PriceComparison;
import campus.secondhand.service.PriceComparisonService;
import campus.secondhand.service.ProductPublishCommand;
import campus.secondhand.service.NegotiationService;
import campus.secondhand.service.ProductService;
import campus.secondhand.service.SearchLogService;
import jakarta.validation.constraints.NotBlank;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;
import java.util.List;

/**
 * 鍟嗗搧 REST 鎺ュ彛锛堜緵 AI Agent 璋冪敤锛夈€? *
 * 璁捐绾﹀畾锛? *  - 鎵€鏈夊啓鎿嶄綔鏈€缁堥兘钀藉埌 ProductService锛屼笌缃戦〉绔叡鐢ㄥ悓涓€濂楃姸鎬佹満
 *  - 鍙戝竷鍟嗗搧涓€寰嬭繘鍏?寰呭鏍?锛宎gent 鏃犳硶缁曡繃绠＄悊鍛? *  - 杩斿洖浣撶粺涓€涓?{@link ApiResponse}
 */
@RestController
@RequestMapping("/api/v1/products")
@RequiredArgsConstructor
public class ProductRestController {

    private final ProductService productService;
    private final PriceComparisonService priceComparisonService;
    private final SearchLogService searchLogService;
    private final NegotiationService negotiationService;

    /**
     * 鍟嗗搧妫€绱€?     *
     * 杩欐槸 agent "鎼滅储鍟嗗搧"宸ュ叿鐨勫悗绔€傛敮鎸佸叧閿瘝 / 鍒嗙被 / 浠锋牸鍖洪棿 / 鎺掑簭锛?     * 骞朵笖**鍙繑鍥炲湪鍞晢鍝?*锛岄伩鍏?agent 鎶婂凡鍞嚭銆佸緟瀹℃牳鐨勫晢鍝佹帹鑽愮粰鐢ㄦ埛銆?     */
    @GetMapping
    public ApiResponse<PageResult<ProductView>> search(
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String category,
            @RequestParam(required = false) BigDecimal minPrice,
            @RequestParam(required = false) BigDecimal maxPrice,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "10") int size,
            @RequestParam(defaultValue = "createTime") String sortBy,
            @RequestParam(defaultValue = "desc") String direction) {

        ProductQuery query = ProductQuery.of(q, category, page, size)
                .withPriceRange(minPrice, maxPrice)
                .withSort(sortBy, direction);

        PageResult<ProductView> result = productService
                .search(query, campus.secondhand.entity.ProductStatus.ON_SALE)
                .map(ProductView::of);

        // 记录到搜索日志：agent 的搜索同样算"有人想找这个"。
        // 只统计第一页，翻页会把同一个查询重复计数。
        if (page == 0) {
            String actorName = null;
            try {
                var ctx = ActorContextHolder.current();
                actorName = ctx == null ? null : ctx.name();
            } catch (Exception ignored) {
                // 取不到身份不影响统计
            }
            searchLogService.record(q, category, result.getTotalElements(), "agent", actorName,
                    result.getTotalElements() == 0 ? productService.emptyHint(q) : null);
        }
        return ApiResponse.ok(result);
    }

    /** 鍟嗗搧璇︽儏 */
    @GetMapping("/{id}")
    public ApiResponse<ProductView> detail(@PathVariable Long id) {
        return ApiResponse.ok(ProductView.of(productService.getVisibleById(id)));
    }

    /**
     * 鍐呴儴鍚岀被姣斾环銆?     *
     * 杩斿洖鐨勭粺璁℃暟瀛楀叏閮ㄧ敱鍚庣璁＄畻锛孡LM 鍙礋璐ｈ浆杩帮紝
     * 浠庢牴涓婇伩鍏?妯″瀷缂栭€犱竴涓环鏍煎尯闂?鐨勯棶棰樸€?     */
    @GetMapping("/{id}/price-comparison")
    public ApiResponse<PriceComparison> priceComparison(@PathVariable Long id,
                                                        @RequestParam(defaultValue = "50") int sampleLimit) {
        return ApiResponse.ok(priceComparisonService.compareForProduct(id, sampleLimit));
    }

    /**
     * 议价建议（agent 工具 `negotiation_advice` 的后端）。
     *
     * 和网页端 /web/products/{id}/negotiation-advice 共用同一个 Service ——
     * 保证"网页上看到的三档价"和"AI 告诉你该出多少"永远一致。
     */
    @GetMapping("/{id}/negotiation-advice")
    public ApiResponse<campus.secondhand.service.NegotiationAdvice> negotiationAdvice(
            @PathVariable Long id) {
        return ApiResponse.ok(negotiationService.adviceFor(id));
    }

    /**
     * 鍙戝竷鍓嶇殑瀹氫环鍙傝€冿紙**涓嶉渶瑕佸厛鏈夊晢鍝?*锛夈€?     *
     * 鎶婃瘮浠蜂粠 agent 閲?鎷垮嚭鏉?涔嬪悗鐨勭涓€绫讳娇鐢ㄨ€咃細
     * 缃戦〉鍙戝竷琛ㄥ崟鍦ㄧ敤鎴烽€夊畬鍒嗙被銆佸～浜嗕环鏍煎悗鐩存帴璋冨畠锛屽疄鏃剁粰鍑鸿鎯呫€?     * 妯″瀷涓嶅啀鏄繀缁忎箣璺€?     */
    @GetMapping("/price-suggestion")
    public ApiResponse<PriceComparison> priceSuggestion(
            @RequestParam(required = false) String category,
            @RequestParam(required = false) String condition,
            @RequestParam(required = false) String type,
            @RequestParam(required = false) BigDecimal price,
            @RequestParam(defaultValue = "50") int sampleLimit) {
        return ApiResponse.ok(
                priceComparisonService.suggestFor(type, category, condition, price, sampleLimit));
    }

    /**
     * 鍙戝竷鍟嗗搧锛坅gent 浠ｇ敤鎴峰彂甯冿級銆?     *
     * 娉ㄦ剰锛氫骇鍑虹殑鍟嗗搧 status = 寰呭鏍革紝涓嶄細鐩存帴涓婃灦銆?     */
    @PostMapping
    public ApiResponse<ProductView> publish(@RequestBody PublishRequest req) {
        var actor = ActorContextHolder.current();

        ProductPublishCommand cmd;
        try {
            cmd = ProductPublishCommand.builder()
                    .name(req.name())
                    .description(req.description())
                    .price(req.price())
                    .originalPrice(req.originalPrice())
                    .conditionLevel(req.conditionLevel())
                    .location(req.location())
                    .categoryName(req.category())
                    .categoryId(req.categoryId())
                    .imagePath(req.imagePath())
                        .productType(req.productType())
                    .build();
        } catch (IllegalArgumentException e) {
            throw BusinessException.badRequest(e.getMessage());
        }

        Product saved = productService.publish(cmd, actor.id(), actor.name(), null, actor);
        return ApiResponse.ok(ProductView.of(saved));
    }

    /** 淇敼鑷繁鐨勫晢鍝?*/
    @PatchMapping("/{id}")
    public ApiResponse<ProductView> update(@PathVariable Long id, @RequestBody PublishRequest req) {
        var actor = ActorContextHolder.current();
        ProductPublishCommand cmd;
        try {
            cmd = ProductPublishCommand.builder()
                    .name(req.name())
                    .description(req.description())
                    .price(req.price())
                    .originalPrice(req.originalPrice())
                    .conditionLevel(req.conditionLevel())
                    .location(req.location())
                    .categoryName(req.category())
                    .categoryId(req.categoryId())
                    .imagePath(req.imagePath())
                        .productType(req.productType())
                    .build();
        } catch (IllegalArgumentException e) {
            throw BusinessException.badRequest(e.getMessage());
        }
        return ApiResponse.ok(ProductView.of(
                productService.updateOwnProduct(id, actor.id(), cmd, actor)));
    }

    /** 涓嬫灦鑷繁鐨勫晢鍝?*/
    @PostMapping("/{id}/delist")
    public ApiResponse<ProductView> delist(@PathVariable Long id) {
        var actor = ActorContextHolder.current();
        return ApiResponse.ok(ProductView.of(productService.delist(id, actor.id(), actor)));
    }

    /** 鎴戝彂甯冪殑鍟嗗搧 */
    @GetMapping("/mine/list")
    public ApiResponse<List<ProductView>> mine() {
        var actor = ActorContextHolder.current();
        return ApiResponse.ok(productService.listBySeller(actor.id()).stream()
                .map(ProductView::of).toList());
    }

    // ==================== 璇锋眰浣?====================

    /**
     * 鍙戝竷/淇敼璇锋眰浣撱€?     * name 涓?price 鐢ㄦ敞瑙ｅ仛鍩虹鏍￠獙锛屼笟鍔℃牎楠屼粛鍦?Service 鍐呫€?     */
    public record PublishRequest(
            @NotBlank(message = "鍟嗗搧鍚嶇О涓嶈兘涓虹┖") String name,
            String description,
            BigDecimal price,
            BigDecimal originalPrice,
            String conditionLevel,
            String location,
            String category,
            Long categoryId,
            String imagePath,
            /** 鍝佺被璇嶏紙濡?鑰虫満"锛夈€侫gent 涓嶄紶涔熷彲浠ワ細鏈嶅姟灞備細鎸夋爣棰樼寽锛岀寽涓嶅嚭灏辩暀绌?*/
            String productType
    ) {
    }
}
