package campus.secondhand.api.web;

import campus.secondhand.entity.User;
import campus.secondhand.service.FavoriteService;
import jakarta.servlet.http.HttpSession;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;

/**
 * 收藏页面控制器。
 */
@Controller
@RequiredArgsConstructor
public class FavoriteController {

    private final FavoriteService favoriteService;

    /** 收藏 / 取消收藏（已收藏则取消） */
    @PostMapping("/favorite/{productId}")
    public String toggle(@PathVariable Long productId, HttpSession session) {
        User user = SessionActors.currentUser(session);
        if (user == null) {
            return "redirect:/login";
        }
        favoriteService.toggle(user.getId(), productId, SessionActors.user(session));
        return "redirect:/product/" + productId;
    }

    /** 我的收藏列表 */
    @GetMapping("/favorites")
    public String list(HttpSession session, Model model) {
        User user = SessionActors.currentUser(session);
        if (user == null) {
            return "redirect:/login";
        }
        model.addAttribute("products", favoriteService.listProducts(user.getId()));
        model.addAttribute("title", "我的收藏");
        model.addAttribute("loginUser", session.getAttribute("loginUser"));
        return "favorites";
    }
}
