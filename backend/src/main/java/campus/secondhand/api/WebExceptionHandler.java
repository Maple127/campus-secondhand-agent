package campus.secondhand.api;

import campus.secondhand.common.BusinessException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

/**
 * 网页端（Thymeleaf）统一异常处理。
 *
 * 作用：把 Service 层抛出的 {@link BusinessException}（状态机冲突、越权、不存在）
 * 转换成带提示语的**友好重定向**，而不是 Tomcat 的 500 白页。
 *
 * 与 {@code ApiExceptionHandler} 分工明确：
 *  - 本类：返回 HTML 视图 / 重定向
 *  - ApiExceptionHandler：返回 JSON 错误体
 * 两者都只在"控制器方法本身未捕获"时生效，已有 try/catch 的地方行为不变。
 */
@Slf4j
@ControllerAdvice(basePackages = "campus.secondhand.api.web")
public class WebExceptionHandler {

    @ExceptionHandler(BusinessException.class)
    public String handleBusiness(BusinessException e,
                                 RedirectAttributes redirectAttributes,
                                 Model model) {
        log.info("业务异常被拦截: {} - {}", e.getCode(), e.getMessage());
        redirectAttributes.addFlashAttribute("error", e.getMessage());
        // 回到来源页（Referer 由 RedirectView 处理成本次请求的上一步需自行判断，
        // 这里统一回首页，避免开放重定向风险）
        return "redirect:/home";
    }

    @ExceptionHandler(IllegalStateException.class)
    public String handleIllegalState(IllegalStateException e, RedirectAttributes redirectAttributes) {
        log.warn("状态机冲突: {}", e.getMessage());
        redirectAttributes.addFlashAttribute("error", e.getMessage());
        return "redirect:/home";
    }

    @ExceptionHandler(Exception.class)
    public String handleOther(Exception e, Model model) {
        log.error("网页请求发生未预期异常", e);
        model.addAttribute("errorMessage", "系统开小差了，请稍后重试");
        return "errorPage";
    }
}
