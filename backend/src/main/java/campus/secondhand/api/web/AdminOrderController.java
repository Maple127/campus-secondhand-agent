package campus.secondhand.api.web;

import campus.secondhand.entity.Admin;
import campus.secondhand.entity.Order;
import campus.secondhand.entity.Product;
import campus.secondhand.entity.User;
import campus.secondhand.service.OrderService;
import campus.secondhand.service.ProductService;
import campus.secondhand.service.UserService;
import jakarta.servlet.http.HttpSession;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 管理端订单查询。
 */
@Controller
@RequestMapping("/admin/orders")
@RequiredArgsConstructor
public class AdminOrderController {

    private final OrderService orderService;
    private final UserService userService;
    private final ProductService productService;

    private Admin currentAdmin(HttpSession session) {
        return SessionActors.currentAdmin(session);
    }

    @GetMapping
    public String listOrders(HttpSession session, Model model) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }

        List<Order> orders = orderService.listAll();

        Map<Long, String> userNameMap = new java.util.HashMap<>();
        userService.listAll().forEach(u -> userNameMap.put(u.getId(), u.getUsername()));

        // 模板使用 productNameMap[order.productId] 取商品名
        Map<Long, String> productNameMap = new java.util.HashMap<>();
        orderService.productMapFor(orders).forEach((id, p) -> productNameMap.put(id, p.getName()));

        model.addAttribute("admin", admin);
        model.addAttribute("orders", orders);
        model.addAttribute("userNameMap", userNameMap);
        model.addAttribute("productNameMap", productNameMap);
        return "admin/orders";
    }

    @GetMapping("/{id}")
    public String orderDetail(@PathVariable Long id, HttpSession session, Model model) {
        Admin admin = currentAdmin(session);
        if (admin == null) {
            return "redirect:/admin/login";
        }

        Order order = orderService.getById(id);
        if (order == null) {
            return "redirect:/admin/orders";
        }

        User buyer = order.getUserId() == null ? null : userService.findByIdOrNull(order.getUserId());
        User seller = order.getSellerId() == null ? null : userService.findByIdOrNull(order.getSellerId());
        Product product = productService.findByIdOrNull(order.getProductId());

        model.addAttribute("admin", admin);
        model.addAttribute("order", order);
        model.addAttribute("buyerName", buyer == null ? "" : buyer.getUsername());
        model.addAttribute("sellerName", seller == null ? "" : seller.getUsername());
        model.addAttribute("productName", product == null ? "" : product.getName());
        return "admin/orderDetail";
    }
}
