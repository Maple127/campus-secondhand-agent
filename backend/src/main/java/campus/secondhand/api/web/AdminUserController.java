package campus.secondhand.api.web;

import campus.secondhand.entity.Admin;
import campus.secondhand.service.ProductService;
import campus.secondhand.service.UserService;
import jakarta.servlet.http.HttpSession;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;

/**
 * 管理端用户查询。
 */
@Controller
@RequestMapping("/admin/users")
@RequiredArgsConstructor
public class AdminUserController {

    private final UserService userService;
    private final ProductService productService;

    private Admin currentAdmin(HttpSession session) {
        return SessionActors.currentAdmin(session);
    }

    @GetMapping
    public String userList(HttpSession session, Model model) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        model.addAttribute("admin", admin);
        model.addAttribute("users", userService.listAll());
        return "admin/users";
    }

    @GetMapping("/{userId}/products")
    public String userProducts(@PathVariable Long userId, HttpSession session, Model model) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        model.addAttribute("admin", admin);
        model.addAttribute("user", userService.getById(userId));
        model.addAttribute("products", productService.listBySeller(userId));
        return "admin/userProducts";
    }
}
