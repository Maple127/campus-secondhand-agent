package campus.secondhand.api.rest;

import campus.secondhand.api.ApiResponse;
import campus.secondhand.api.dto.ProductView;
import campus.secondhand.api.dto.UserProfileView;
import campus.secondhand.security.ActorContextHolder;
import campus.secondhand.service.CategoryService;
import campus.secondhand.service.FavoriteService;
import campus.secondhand.service.ReportService;
import campus.secondhand.service.UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 个人中心、收藏、举报、元数据等辅助接口。
 */
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class UserRestController {

    private final UserService userService;
    private final FavoriteService favoriteService;
    private final ReportService reportService;
    private final CategoryService categoryService;

    // ==================== 个人资料 ====================

    @GetMapping("/me")
    public ApiResponse<UserProfileView> me() {
        var actor = ActorContextHolder.current();
        return ApiResponse.ok(UserProfileView.of(userService.getById(actor.id())));
    }

    @PatchMapping("/me")
    public ApiResponse<UserProfileView> updateMe(@RequestBody ProfileRequest req) {
        var actor = ActorContextHolder.current();
        return ApiResponse.ok(UserProfileView.of(userService.updateProfile(
                actor.id(), req.school(), req.grade(), req.phone(), req.shippingAddress(), actor)));
    }

    // ==================== 收藏 ====================

    @GetMapping("/favorites")
    public ApiResponse<List<ProductView>> favorites() {
        var actor = ActorContextHolder.current();
        return ApiResponse.ok(favoriteService.listProducts(actor.id()).stream()
                .map(ProductView::of).toList());
    }

    /** 切换收藏状态，返回 true=已收藏 */
    @PostMapping("/favorites/{productId}")
    public ApiResponse<Map<String, Object>> toggleFavorite(@PathVariable Long productId) {
        var actor = ActorContextHolder.current();
        boolean favorited = favoriteService.toggle(actor.id(), productId, actor);
        return ApiResponse.ok(Map.of("productId", productId, "favorited", favorited));
    }

    // ==================== 举报 ====================

    @GetMapping("/reports/mine")
    public ApiResponse<List<Map<String, Object>>> myReports() {
        var actor = ActorContextHolder.current();
        return ApiResponse.ok(reportService.listMine(actor.id()).stream()
                .map(r -> Map.<String, Object>of(
                        "id", r.getId(),
                        "productId", r.getProductId(),
                        "productName", r.getProductName() == null ? "" : r.getProductName(),
                        "reasonType", r.getReasonType(),
                        "status", r.getStatus(),
                        "createTime", String.valueOf(r.getCreateTime())))
                .toList());
    }

    @PostMapping("/reports")
    public ApiResponse<Map<String, Object>> submitReport(@RequestBody ReportRequest req) {
        var actor = ActorContextHolder.current();
        var report = reportService.submit(req.productId(), req.reasonType(), req.description(),
                actor.id(), actor.name(), actor);
        return ApiResponse.ok(Map.of(
                "id", report.getId(),
                "status", report.getStatus(),
                "message", "举报已提交，等待管理员核实"));
    }

    // ==================== 元数据 ====================

    /** 分类列表，供 agent 在发布商品时选择合适的分类 */
    @GetMapping("/meta/categories")
    public ApiResponse<List<Map<String, Object>>> categories() {
        return ApiResponse.ok(categoryService.listAll().stream()
                .map(c -> Map.<String, Object>of(
                        "id", c.getId(),
                        "name", c.getName(),
                        "description", c.getDescription() == null ? "" : c.getDescription()))
                .toList());
    }

    public record ProfileRequest(String school, String grade, String phone, String shippingAddress) {
    }

    public record ReportRequest(Long productId, String reasonType, String description) {
    }
}
