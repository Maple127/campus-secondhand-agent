package campus.secondhand.api.web;

import campus.secondhand.common.BusinessException;
import campus.secondhand.entity.Admin;
import campus.secondhand.entity.Category;
import campus.secondhand.entity.Product;
import campus.secondhand.entity.ProductStatus;
import campus.secondhand.service.AdminService;
import campus.secondhand.service.CategoryService;
import campus.secondhand.service.ProductService;
import campus.secondhand.service.ReportService;
import campus.secondhand.service.SearchLogService;
import jakarta.servlet.http.HttpSession;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

import java.util.List;

/**
 * 管理员后台控制器。
 *
 * 审核动作全部走 ProductService 的状态机：
 * 原实现直接 setStatus(1)/setStatus(2)，无法阻止"把已售出商品重新审核通过"这类非法迁移。
 */
@Controller
@RequestMapping("/admin")
@RequiredArgsConstructor
public class AdminController {

    private final AdminService adminService;
    private final ProductService productService;
    private final CategoryService categoryService;
    private final ReportService reportService;
    private final SearchLogService searchLogService;

    private Admin currentAdmin(HttpSession session) {
        return SessionActors.currentAdmin(session);
    }

    // ==================== 登录 ====================

    @GetMapping("/login")
    public String loginPage() {
        return "admin/login";
    }

    @PostMapping("/doLogin")
    public String doLogin(@RequestParam String username,
                          @RequestParam String password,
                          HttpSession session,
                          RedirectAttributes redirectAttributes) {
        try {
            Admin admin = adminService.authenticate(username, password);
            session.setAttribute("admin", admin);
            return "redirect:/admin/dashboard";
        } catch (BusinessException e) {
            redirectAttributes.addFlashAttribute("error", e.getMessage());
            return "redirect:/admin/login";
        }
    }

    @GetMapping("/logout")
    public String logout(HttpSession session) {
        session.invalidate();
        return "redirect:/admin/login";
    }

    // ==================== 仪表盘 ====================

    @GetMapping("/dashboard")
    public String dashboard(HttpSession session, Model model) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }

        model.addAttribute("admin", admin);
        model.addAttribute("pendingCount", productService.countByStatus(ProductStatus.PENDING_APPROVAL));
        model.addAttribute("approvedCount", productService.countByStatus(ProductStatus.ON_SALE));
        model.addAttribute("rejectedCount", productService.countByStatus(ProductStatus.REJECTED));
        // 新增统计：已售出与待处理举报，为后续 agent 运营看板预留
        model.addAttribute("soldCount", productService.countByStatus(ProductStatus.SOLD));
        model.addAttribute("pendingReportCount", reportService.countPending());
        model.addAttribute("zeroSearchCount", searchLogService.zeroResultTotal());
        return "admin/dashboard";
    }

    // ==================== 搜索日志 ====================

    /**
     * 搜索日志：看看大家在搜什么、我们缺什么。
     *
     * 这是词表的采购清单：
     *   「无结果」榜 = 词表缺词，或平台真的没货
     *   「少结果」榜 = 有货但少，供给问题
     */
    @GetMapping("/search-log")
    public String searchLog(HttpSession session, Model model) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        model.addAttribute("admin", admin);
        model.addAttribute("zeroResults", searchLogService.zeroResultKeywords(30));
        model.addAttribute("noTypeKeywords",
                searchLogService.zeroResultByHint(SearchLogService.HINT_NO_TYPE, 30));
        model.addAttribute("typeEmptyKeywords",
                searchLogService.zeroResultByHint(SearchLogService.HINT_TYPE_EMPTY, 30));
        model.addAttribute("lowResults", searchLogService.lowResultKeywords(20));
        model.addAttribute("topKeywords", searchLogService.topKeywords(20));
        model.addAttribute("recent", searchLogService.recent(30));
        model.addAttribute("zeroTotal", searchLogService.zeroResultTotal());
        return "admin/searchLog";
    }

    // ==================== 改密 ====================

    @GetMapping("/changePassword")
    public String changePasswordPage(HttpSession session, Model model) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        model.addAttribute("admin", admin);
        return "admin/changePassword";
    }

    @PostMapping("/changePassword")
    public String doChangePassword(@RequestParam String oldPassword,
                                   @RequestParam String newPassword,
                                   @RequestParam String confirmPassword,
                                   HttpSession session,
                                   RedirectAttributes redirectAttributes) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        try {
            Admin updated = adminService.changePassword(admin.getId(), oldPassword, newPassword, confirmPassword);
            session.setAttribute("admin", updated);
            redirectAttributes.addFlashAttribute("success", "密码修改成功");
            return "redirect:/admin/dashboard";
        } catch (BusinessException e) {
            redirectAttributes.addFlashAttribute("error", e.getMessage());
            return "redirect:/admin/changePassword";
        }
    }

    // ==================== 商品审核 ====================

    @GetMapping("/products")
    public String productList(@RequestParam(defaultValue = "0") Integer status,
                              @RequestParam(required = false) String keyword,
                              HttpSession session,
                              Model model) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }

        List<Product> products;
        if (status != null && status == -1) {
            // -1 表示全部：为后台增加"查看全部商品"能力
            products = keyword != null && !keyword.isBlank()
                    ? productService.searchAllForAdmin(keyword)
                    : productService.listAll();
        } else {
            products = productService.listByStatusAndKeyword(ProductStatus.of(status), keyword);
        }

        model.addAttribute("admin", admin);
        model.addAttribute("products", products);
        model.addAttribute("status", status);
        model.addAttribute("keyword", keyword);
        return "admin/products";
    }

    @GetMapping("/product/{id}")
    public String productDetail(@PathVariable Long id, HttpSession session, Model model) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        Product product = productService.findByIdOrNull(id);
        if (product == null) {
            return "redirect:/admin/products";
        }
        model.addAttribute("admin", admin);
        model.addAttribute("product", product);
        return "admin/productDetail";
    }

    @GetMapping("/product/{id}/approve")
    public String approveProduct(@PathVariable Long id, HttpSession session, RedirectAttributes ra) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        try {
            productService.approve(id, SessionActors.admin(session));
            ra.addFlashAttribute("success", "审核通过");
        } catch (BusinessException e) {
            ra.addFlashAttribute("error", e.getMessage());
        }
        return "redirect:/admin/products";
    }

    @PostMapping("/product/{id}/reject")
    public String rejectProduct(@PathVariable Long id,
                                @RequestParam String rejectReason,
                                HttpSession session, RedirectAttributes ra) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        try {
            productService.reject(id, rejectReason, SessionActors.admin(session));
            ra.addFlashAttribute("success", "已拒绝该商品");
        } catch (BusinessException e) {
            ra.addFlashAttribute("error", e.getMessage());
        }
        return "redirect:/admin/products";
    }

    @GetMapping("/product/{id}/delete")
    public String deleteProduct(@PathVariable Long id, HttpSession session, RedirectAttributes ra) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        try {
            productService.delete(id, SessionActors.admin(session));
            ra.addFlashAttribute("success", "商品已删除");
        } catch (BusinessException e) {
            ra.addFlashAttribute("error", e.getMessage());
        }
        return "redirect:/admin/products";
    }

    // ==================== 分类管理 ====================

    @GetMapping("/categories")
    public String categoryList(HttpSession session, Model model) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        model.addAttribute("admin", admin);
        model.addAttribute("categories", categoryService.listAll());
        return "admin/categories";
    }

    @GetMapping("/category/add")
    public String addCategoryPage(HttpSession session, Model model) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        model.addAttribute("admin", admin);
        model.addAttribute("category", new Category());
        return "admin/addCategory";
    }

    @PostMapping("/category/add")
    public String doAddCategory(@RequestParam String name,
                                @RequestParam(required = false) String description,
                                HttpSession session, RedirectAttributes ra) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        try {
            categoryService.create(name, description, SessionActors.admin(session));
            ra.addFlashAttribute("success", "分类添加成功");
            return "redirect:/admin/categories";
        } catch (BusinessException e) {
            ra.addFlashAttribute("error", e.getMessage());
            return "redirect:/admin/category/add";
        }
    }

    @GetMapping("/category/{id}/edit")
    public String editCategoryPage(@PathVariable Long id, HttpSession session, Model model) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        model.addAttribute("admin", admin);
        model.addAttribute("category", categoryService.getById(id));
        return "admin/editCategory";
    }

    @PostMapping("/category/{id}/edit")
    public String doEditCategory(@PathVariable Long id,
                                 @RequestParam String name,
                                 @RequestParam(required = false) String description,
                                 HttpSession session, RedirectAttributes ra) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        try {
            categoryService.update(id, name, description, SessionActors.admin(session));
            ra.addFlashAttribute("success", "分类更新成功");
            return "redirect:/admin/categories";
        } catch (BusinessException e) {
            ra.addFlashAttribute("error", e.getMessage());
            return "redirect:/admin/category/" + id + "/edit";
        }
    }

    @GetMapping("/category/{id}/delete")
    public String deleteCategory(@PathVariable Long id, HttpSession session, RedirectAttributes ra) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        try {
            categoryService.delete(id, SessionActors.admin(session));
            ra.addFlashAttribute("success", "分类已删除");
        } catch (BusinessException e) {
            ra.addFlashAttribute("error", e.getMessage());
        }
        return "redirect:/admin/categories";
    }
}
