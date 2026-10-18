package campus.secondhand.api.web;

import campus.secondhand.common.BusinessException;
import campus.secondhand.entity.User;
import campus.secondhand.service.UserService;
import jakarta.servlet.http.HttpSession;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

/**
 * 个人中心：基本资料与收货地址。
 *
 * 订单列表统一由 {@link OrderController#myOrderList} 提供，
 * 原 MyController 里重复的一份订单列表实现已删除。
 */
@Controller
@RequiredArgsConstructor
public class MyController {

    private final UserService userService;

    /** 个人中心 */
    @GetMapping("/my")
    public String myPage(HttpSession session, Model model) {
        User sessionUser = SessionActors.currentUser(session);
        if (sessionUser == null) {
            return "redirect:/login";
        }
        User user = userService.getById(sessionUser.getId());
        model.addAttribute("user", user);
        return "my";
    }

    /** 编辑基本信息页 */
    @GetMapping("/edit-profile")
    public String editProfile(HttpSession session, Model model) {
        User user = SessionActors.currentUser(session);
        if (user == null) {
            return "redirect:/login";
        }
        model.addAttribute("user", user);
        return "edit-profile";
    }

    /** 保存基本信息 */
    @PostMapping("/update-profile")
    public String updateProfile(@RequestParam String school,
                                @RequestParam String grade,
                                @RequestParam String phone,
                                @RequestParam String shippingAddress,
                                HttpSession session,
                                RedirectAttributes redirectAttributes) {
        User user = SessionActors.currentUser(session);
        if (user == null) {
            return "redirect:/my";
        }
        try {
            User updated = userService.updateProfile(user.getId(), school, grade, phone,
                    shippingAddress, SessionActors.user(session));
            session.setAttribute("user", updated);
            redirectAttributes.addFlashAttribute("success", "基本信息更新成功");
        } catch (BusinessException e) {
            redirectAttributes.addFlashAttribute("error", e.getMessage());
        }
        return "redirect:/my";
    }

    /** 收货地址页 */
    @GetMapping("/address")
    public String addressPage(HttpSession session, Model model) {
        User sessionUser = SessionActors.currentUser(session);
        if (sessionUser == null) {
            return "redirect:/login";
        }
        model.addAttribute("user", userService.getById(sessionUser.getId()));
        return "address";
    }
}
