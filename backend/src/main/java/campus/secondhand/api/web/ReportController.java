package campus.secondhand.api.web;

import campus.secondhand.common.BusinessException;
import campus.secondhand.entity.Admin;
import campus.secondhand.entity.Report;
import campus.secondhand.entity.User;
import campus.secondhand.service.ReportService;
import jakarta.servlet.http.HttpSession;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

import java.util.List;

/**
 * 举报控制器（学生端提交 + 管理端处理）。
 */
@Controller
@RequiredArgsConstructor
public class ReportController {

    private final ReportService reportService;

    // ==================== 学生端 ====================

    /** 提交举报 */
    @PostMapping("/report/submit")
    public String submitReport(@RequestParam Long productId,
                               @RequestParam String reasonType,
                               @RequestParam(required = false) String description,
                               HttpSession session,
                               RedirectAttributes redirectAttributes) {
        User user = SessionActors.currentUser(session);
        if (user == null) {
            return "redirect:/login";
        }
        try {
            reportService.submit(productId, reasonType, description,
                    user.getId(), user.getUsername(), SessionActors.user(session));
            // 举报提交后要有明确反馈：原来只塞了个 success，而商品页并不渲染它，
            // 用户点完"提交举报"什么反应都没有，会以为没提交成功。
            redirectAttributes.addFlashAttribute("reportSubmitted", true);
            redirectAttributes.addFlashAttribute("reportSubmittedMsg",
                    "感谢反馈，我们已收到你的举报。\n管理员会尽快核实处理，处理结果会出现在「我的 → 我的举报」。");
        } catch (BusinessException e) {
            redirectAttributes.addFlashAttribute("error", e.getMessage());
        }
        return "redirect:/product/" + productId;
    }

    /** 我的历史举报 */
    @GetMapping("/my/reports")
    public String myReports(HttpSession session, Model model) {
        User user = SessionActors.currentUser(session);
        if (user == null) {
            return "redirect:/login";
        }
        model.addAttribute("reports", reportService.listMine(user.getId()));
        model.addAttribute("title", "我的历史举报");
        return "myReports";
    }

    // ==================== 管理端 ====================

    @GetMapping("/admin/reports")
    public String adminReportList(@RequestParam(defaultValue = "-1") Integer status,
                                  HttpSession session, Model model) {
        Admin admin = SessionActors.currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        List<Report> reports = reportService.listAll(status);
        model.addAttribute("admin", admin);
        model.addAttribute("reports", reports);
        model.addAttribute("status", status);
        return "admin/reports";
    }

    /** 处理工单：1-核实违规并下架商品，2-驳回举报 */
    @PostMapping("/admin/report/{id}/handle")
    public String handleReport(@PathVariable Long id,
                               @RequestParam Integer status,
                               @RequestParam(required = false) String adminReply,
                               HttpSession session,
                               RedirectAttributes redirectAttributes) {
        Admin admin = SessionActors.currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }
        try {
            reportService.handle(id, status, adminReply, SessionActors.admin(session));
            redirectAttributes.addFlashAttribute("success", "工单处理成功！");
        } catch (BusinessException e) {
            redirectAttributes.addFlashAttribute("error", e.getMessage());
        }
        return "redirect:/admin/reports";
    }
}
