package campus.secondhand.api.web;

import campus.secondhand.common.BusinessException;
import campus.secondhand.common.ProductQuery;
import campus.secondhand.entity.Product;
import campus.secondhand.entity.User;
import campus.secondhand.service.ProductService;
import campus.secondhand.service.SearchLogService;
import campus.secondhand.service.UserService;
import jakarta.servlet.http.HttpSession;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

import java.math.BigDecimal;
import java.util.List;

/**
 * 首页 + 登录注册控制器。
 *
 * 原类名 login_controller 不符合 Java 命名规范（且是小写开头），
 * 重命名为 HomeController；随机资料补齐逻辑已下沉到 UserService。
 */
@Controller
@RequiredArgsConstructor
public class HomeController {

    private final UserService userService;
    private final ProductService productService;
    private final SearchLogService searchLogService;

    /**
     * 首页：/ 和 /home 都能访问。
     * 支持 keyword / category / minPrice / maxPrice / sortBy / page 组合筛选。
     *
     * 价格区间筛选是在 B 阶段评测后补上的：评测显示"300 到 800 的运动器材"
     * 这类需求搜索框原本完全做不到（把整句当关键词），而它本该是搜索框的强项。
     */
    @GetMapping({"/", "/home"})
    public String home(@RequestParam(required = false) String keyword,
                       @RequestParam(required = false) String category,
                       @RequestParam(required = false) BigDecimal minPrice,
                       @RequestParam(required = false) BigDecimal maxPrice,
                       @RequestParam(required = false) String sortBy,
                       @RequestParam(defaultValue = "0") int page,
                       HttpSession session, Model model) {
        model.addAttribute("loginUser", session.getAttribute("loginUser"));

        // 下拉框用 "price-asc" / "price-desc" / "createTime" 这种组合值，
        // 这里拆成字段与方向，避免前端直接拼 SQL 语义
        String field = "createTime";
        String direction = "desc";
        if ("price-asc".equals(sortBy)) {
            field = "price";
            direction = "asc";
        } else if ("price-desc".equals(sortBy)) {
            field = "price";
            direction = "desc";
        }

        ProductQuery query = ProductQuery.of(keyword, category, page, 8)
                .withPriceRange(minPrice, maxPrice)
                .withSort(field, direction);

        Page<Product> productPage = productService.searchOnSale(query);

        // 零结果时把"死路"变成入口：告诉用户是缺货还是叫法不同，并给几件替代品
        String emptyHint = productPage.getTotalElements() == 0
                ? productService.emptyHint(query.getKeyword())
                : null;
        List<Product> suggestions = (emptyHint != null && page == 0)
                ? productService.suggestAlternatives(query.getKeyword(), query.getCategoryName(), 4)
                : List.of();
        model.addAttribute("emptyHint", emptyHint);
        model.addAttribute("suggestions", suggestions);

        // 只统计第一页：翻页会把同一个查询重复计数。
        // 关键词为空（直接打开首页）时 SearchLogService 内部会跳过。
        if (page == 0) {
            Object loginUser = session.getAttribute("loginUser");
            searchLogService.record(keyword, category, productPage.getTotalElements(),
                    "web", loginUser == null ? null : loginUser.toString(), emptyHint);
        }

        model.addAttribute("products", productPage.getContent());
        model.addAttribute("currentPage", productPage.getNumber());
        model.addAttribute("totalPages", productPage.getTotalPages());
        model.addAttribute("totalElements", productPage.getTotalElements());
        model.addAttribute("keyword", keyword);
        model.addAttribute("category", category);
        model.addAttribute("minPrice", minPrice);
        model.addAttribute("maxPrice", maxPrice);
        model.addAttribute("sortBy", sortBy);
        return "home";
    }

    /** 登录页 */
    @GetMapping("/login")
    public String loginPage() {
        return "login";
    }

    /** 处理登录 */
    @PostMapping("/doLogin")
    public String doLogin(@RequestParam String username,
                          @RequestParam String password,
                          HttpSession session,
                          RedirectAttributes redirectAttributes) {
        try {
            User user = userService.authenticate(username, password);
            session.setAttribute("loginUser", user.getUsername());
            session.setAttribute("user", user);
            return "redirect:/home";
        } catch (BusinessException e) {
            redirectAttributes.addFlashAttribute("error", e.getMessage());
            return "redirect:/login";
        }
    }

    /** 注册页 */
    @GetMapping("/register")
    public String registerPage(Model model) {
        model.addAttribute("user", new User());
        return "register";
    }

    /** 处理注册 */
    @PostMapping("/register")
    public String doRegister(@ModelAttribute User user, RedirectAttributes redirectAttributes) {
        try {
            userService.register(user.getUsername(), user.getPassword());
            redirectAttributes.addFlashAttribute("registerSuccess", "注册成功，请登录");
            return "redirect:/home";
        } catch (BusinessException e) {
            redirectAttributes.addFlashAttribute("error", e.getMessage());
            return "redirect:/register";
        }
    }

    /** 退出登录 */
    @GetMapping("/logout")
    public String logout(HttpSession session) {
        session.invalidate();
        return "redirect:/home";
    }
}
