package campus.secondhand.api.web;

import campus.secondhand.entity.Product;
import campus.secondhand.entity.User;
import campus.secondhand.service.CategoryService;
import campus.secondhand.service.FavoriteService;
import campus.secondhand.service.FileStorageService;
import campus.secondhand.service.ProductPublishCommand;
import campus.secondhand.service.ProductService;
import jakarta.servlet.http.HttpSession;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

import java.math.BigDecimal;

/**
 * 商品页面控制器（Thymeleaf 视图）。
 *
 * 已改造为薄层：只负责参数绑定、登录校验、模板模型装配，
 * 全部业务规则下沉到 {@link ProductService}。
 */
@Controller
@RequiredArgsConstructor
public class ProductController {

    private final ProductService productService;
    private final FavoriteService favoriteService;
    private final CategoryService categoryService;
    private final FileStorageService fileStorageService;

    /** 商品发布页 */
    @GetMapping("/publish")
    public String publishPage(HttpSession session, Model model) {
        if (SessionActors.currentUser(session) == null) {
            return "redirect:/login";
        }
        model.addAttribute("loginUser", session.getAttribute("loginUser"));
        model.addAttribute("categories", categoryService.listAll());
        return "publish";
    }

    /** 处理商品上传（进入待审核） */
    @PostMapping("/publish")
    public String doPublish(
            @RequestParam String name,
            @RequestParam(required = false) String description,
            @RequestParam(required = false) BigDecimal price,
            @RequestParam(required = false) BigDecimal originalPrice,
            @RequestParam(required = false) String conditionLevel,
            @RequestParam(required = false) String location,
            @RequestParam(required = false) String category,
            @RequestParam(required = false) Long categoryId,
            @RequestParam(required = false) String productType,
            @RequestParam(value = "image", required = false) MultipartFile image,
            HttpSession session,
            RedirectAttributes redirectAttributes
    ) {
        User seller = SessionActors.currentUser(session);
        if (seller == null) {
            return "redirect:/login";
        }
        if (price == null || price.signum() <= 0) {
            redirectAttributes.addFlashAttribute("error", "请填写有效的商品价格");
            return "redirect:/publish";
        }

        String imagePath = fileStorageService.store(image);

        ProductPublishCommand cmd = ProductPublishCommand.builder()
                .name(name)
                .description(description)
                .price(price)
                .originalPrice(originalPrice)
                .conditionLevel(conditionLevel)
                .location(location)
                .categoryName(category)
                .categoryId(categoryId)
                .imagePath(imagePath)
                .productType(productType)
                .build();

        productService.publish(cmd, seller.getId(), seller.getUsername(), seller.getPhone(),
                SessionActors.user(session));

        // 发布成功不再用顶部横幅（太容易被忽略），改为回首页后弹一个确认窗口。
        // 文案在后端拼好，模板只负责显示，避免把字符串拼接逻辑写进模板。
        redirectAttributes.addFlashAttribute("publishSubmitted", true);
        redirectAttributes.addFlashAttribute("publishSubmittedName", name);
        redirectAttributes.addFlashAttribute("publishSubmittedMsg",
                "「" + name + "」已提交成功。\n"
                        + "商品会先进入「待审核」状态，管理员审核通过后才会出现在首页。");
        return "redirect:/home";
    }

    /** 商品详情页 */
    @GetMapping("/product/{id}")
    public String detail(@PathVariable Long id, HttpSession session, Model model) {
        Product product = productService.findByIdOrNull(id);
        if (product == null) {
            return "redirect:/home";
        }

        User current = SessionActors.currentUser(session);
        boolean owner = current != null && product.isOwnedBy(current.getId());
        // 只有「在售」的商品能下单。其余状态后端都会拒绝，
        // 所以按钮也不该显示 —— 让用户点了再看到报错是糟糕的交互。
        boolean canOrder = product.statusEnum() == campus.secondhand.entity.ProductStatus.ON_SALE;

        model.addAttribute("product", product);
        model.addAttribute("favorited", favoriteService.isFavorited(SessionActors.userId(session), id));
        model.addAttribute("loginUser", session.getAttribute("loginUser"));
        model.addAttribute("isOwner", owner);
        model.addAttribute("canOrder", canOrder);
        model.addAttribute("notOnSaleLabel", switch (product.statusEnum()) {
            case SOLD -> "已售出";
            case PENDING_APPROVAL -> "待审核";
            case DELISTED -> "已下架";
            case REJECTED -> "未通过审核";
            default -> "暂不可购买";
        });
        return "product";
    }

    /**
     * 「我的闲置」已并入「我的订单 → 出售」。
     *
     * 两个页面看的其实是同一批数据（我发布的商品），只是原来一个只看商品、
     * 一个只看订单，导致"待审核/出售中"的商品只能在一个地方看到。
     * 现在统一到 /order/list，这里保留跳转，避免书签和旧链接失效。
     */
    @GetMapping("/myItems")
    public String myItems(HttpSession session) {
        if (SessionActors.currentUser(session) == null) {
            return "redirect:/login";
        }
        return "redirect:/order/list";
    }

    /** 卖家下架自己的商品 */
    @PostMapping("/product/{id}/delist")
    public String delist(@PathVariable Long id, HttpSession session, RedirectAttributes ra) {
        User user = SessionActors.currentUser(session);
        if (user == null) {
            return "redirect:/login";
        }
        productService.delist(id, user.getId(), SessionActors.user(session));
        ra.addFlashAttribute("success", "商品已下架");
        return "redirect:/order/list";
    }

    /** 卖家重新提交审核 */
    @PostMapping("/product/{id}/relist")
    public String relist(@PathVariable Long id, HttpSession session, RedirectAttributes ra) {
        User user = SessionActors.currentUser(session);
        if (user == null) {
            return "redirect:/login";
        }
        productService.relist(id, user.getId(), SessionActors.user(session));
        ra.addFlashAttribute("success", "已重新提交审核");
        return "redirect:/order/list";
    }

    /** 保留旧路径别名，避免老模板链接失效 */
    @GetMapping("/my/items")
    public String myItemsAlias(HttpSession session) {
        return "redirect:/order/list";
    }
}
