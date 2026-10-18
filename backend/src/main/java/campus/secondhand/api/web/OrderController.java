package campus.secondhand.api.web;

import campus.secondhand.common.BusinessException;
import campus.secondhand.entity.Order;
import campus.secondhand.entity.Product;
import campus.secondhand.entity.User;
import campus.secondhand.service.CreateOrderCommand;
import campus.secondhand.service.OrderService;
import campus.secondhand.service.ProductService;
import jakarta.servlet.http.HttpSession;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 订单页面控制器。
 *
 * 修复要点：原实现创建订单时不校验商品状态、支付时也不校验，
 * 导致同一商品可被反复下单（一物多卖）。现在全部由 OrderService 的状态机把关。
 */
@Controller
@RequestMapping("/order")
@RequiredArgsConstructor
public class OrderController {

    private final OrderService orderService;
    private final ProductService productService;

    /** 1. 确认订单页 */
    @GetMapping("/confirm")
    public String confirmOrder(@RequestParam Long productId, HttpSession session, Model model) {
        User buyer = SessionActors.currentUser(session);
        if (buyer == null) {
            return "redirect:/login";
        }
        Product product = productService.findByIdOrNull(productId);
        if (product == null) {
            return "redirect:/home";
        }
        if (!product.statusEnum().canBeOrdered()) {
            return "redirect:/product/" + productId;
        }
        model.addAttribute("product", product);
        return "confirmOrder";
    }

    /** 2. 创建订单 */
    @PostMapping("/create")
    public String createOrder(@RequestParam Long productId,
                              @RequestParam(required = false) String deliveryType,
                              @RequestParam(required = false) String appointmentTime,
                              HttpSession session) {
        User buyer = SessionActors.currentUser(session);
        if (buyer == null) {
            return "redirect:/login";
        }

        LocalDateTime appointment = null;
        if (appointmentTime != null && !appointmentTime.isBlank()) {
            // datetime-local 提交格式为 yyyy-MM-ddTHH:mm
            String normalized = appointmentTime.length() > 16
                    ? appointmentTime.substring(0, 16)
                    : appointmentTime;
            appointment = LocalDateTime.parse(normalized);
        }

        Order order = orderService.create(
                CreateOrderCommand.of(productId, deliveryType, appointment),
                buyer.getId(), buyer.getUsername(), SessionActors.user(session));

        return "redirect:/order/detail?orderNo=" + order.getOrderNo();
    }

    /** 3. 订单详情（买卖双方均可看） */
    @GetMapping("/detail")
    public String orderDetail(@RequestParam String orderNo, HttpSession session, Model model) {
        User user = SessionActors.currentUser(session);
        if (user == null) {
            return "redirect:/login";
        }
        Order order = orderService.getForParticipant(orderNo, user.getId());
        Product product = productService.findByIdOrNull(order.getProductId());

        model.addAttribute("order", order);
        model.addAttribute("product", product);
        return "orderDetail";
    }

    /** 4. 模拟支付 */
    @PostMapping("/pay")
    public String payOrder(@RequestParam String orderNo,
                           @RequestParam(required = false) String payPassword,
                           HttpSession session, Model model) {
        User user = SessionActors.currentUser(session);
        if (user == null) {
            return "redirect:/login";
        }

        // 未提交密码 → 展示支付密码输入页
        if (payPassword == null || payPassword.isBlank()) {
            model.addAttribute("order", orderService.getForParticipant(orderNo, user.getId()));
            return "payConfirm";
        }

        try {
            orderService.pay(orderNo, payPassword, user.getId(), SessionActors.user(session));
        } catch (BusinessException e) {
            model.addAttribute("order", orderService.getForParticipant(orderNo, user.getId()));
            model.addAttribute("error", "❌ " + e.getMessage());
            return "payConfirm";
        }
        return "redirect:/order/paySuccess?orderNo=" + orderNo;
    }

    /** 支付成功页 */
    @GetMapping("/paySuccess")
    public String paySuccess(@RequestParam String orderNo, HttpSession session, Model model) {
        User user = SessionActors.currentUser(session);
        if (user == null) {
            return "redirect:/login";
        }
        model.addAttribute("order", orderService.getForParticipant(orderNo, user.getId()));
        return "paySuccess";
    }

    /** 5. 取消订单（买家） */
    @PostMapping("/cancel")
    @ResponseBody
    public String cancelOrder(@RequestParam String orderNo,
                              @RequestParam(required = false) String reason,
                              HttpSession session) {
        User user = SessionActors.currentUser(session);
        if (user == null) {
            return "请先登录";
        }
        try {
            orderService.cancel(orderNo, user.getId(), reason, SessionActors.user(session));
            return "success";
        } catch (BusinessException e) {
            return e.getMessage();
        }
    }

    /**
     * 6. 我的订单（出售 / 购买两个 Tab）
     *
     * ## 为什么"出售"这一栏要看商品而不是订单
     *
     * 卖家真正关心的是「我这件东西现在怎么样了」，而一件商品的状态
     * 比订单状态更全：待审核、出售中这两种状态**根本没有订单**。
     * 只看订单表的话，刚发布的商品在"我的订单"里是不存在的 ——
     * 这正是原来"我的闲置"和"我的订单"要分成两个页面的原因。
     *
     * 现在合并成一个页面：出售 = 我发布的全部商品（附带订单，若有），
     * 购买 = 我下的订单。默认展示出售。
     */
    @GetMapping("/list")
    public String myOrderList(HttpSession session, Model model) {
        User user = SessionActors.currentUser(session);
        if (user == null) {
            return "redirect:/login";
        }

        List<Order> buyOrders = orderService.listBoughtBy(user.getId());
        List<Order> sellOrders = orderService.listSoldBy(user.getId());

        // 合并去重，并一次性取回商品信息（原实现在模板里逐条查询，存在 N+1）
        java.util.Set<Order> merged = new java.util.LinkedHashSet<>();
        merged.addAll(buyOrders);
        merged.addAll(sellOrders);
        Map<Long, Product> productMap = orderService.productMapFor(new java.util.ArrayList<>(merged));

        // ===== 出售视角：我的全部商品 + 各自最新订单 =====
        List<Product> myProducts = productService.listBySeller(user.getId());
        Map<Long, Order> orderByProduct = orderService.latestOrderByProduct(
                myProducts.stream().map(Product::getId).toList());

        List<SellItemView> sellItems = new java.util.ArrayList<>();
        for (Product p : myProducts) {
            sellItems.add(SellItemView.of(p, orderByProduct.get(p.getId())));
        }

        long buyUnpaidCount = buyOrders.stream().filter(o -> "UNPAID".equals(o.getStatus())).count();
        long sellUnpaidCount = sellOrders.stream().filter(o -> "UNPAID".equals(o.getStatus())).count();
        // 卖家真正需要动手的：买家已付款但自己还没发货
        long sellNeedActionCount = sellItems.stream().filter(SellItemView::needsShip).count();

        model.addAttribute("sellItems", sellItems);
        model.addAttribute("sellNeedActionCount", sellNeedActionCount);
        model.addAttribute("orderList", new java.util.ArrayList<>(merged));
        model.addAttribute("buyOrders", buyOrders);
        model.addAttribute("sellOrders", sellOrders);
        model.addAttribute("buyUnpaidCount", buyUnpaidCount);
        model.addAttribute("sellUnpaidCount", sellUnpaidCount);
        model.addAttribute("productMap", productMap);
        return "Order";
    }

    /** 7. 确认发货（卖家） */
    @PostMapping("/ship")
    @ResponseBody
    public String shipOrder(@RequestParam String orderNo, HttpSession session) {
        User user = SessionActors.currentUser(session);
        if (user == null) {
            return "请先登录";
        }
        try {
            orderService.ship(orderNo, user.getId(), SessionActors.user(session));
            return "success";
        } catch (BusinessException e) {
            return e.getMessage();
        }
    }
}
