package campus.secondhand.service;

import campus.secondhand.common.ActorContext;
import campus.secondhand.common.AuditActions;
import campus.secondhand.common.BusinessException;
import campus.secondhand.common.PageResult;
import campus.secondhand.entity.Order;
import campus.secondhand.entity.OrderStatus;
import campus.secondhand.entity.Product;
import campus.secondhand.entity.ProductStatus;
import campus.secondhand.repository.OrderRepository;
import campus.secondhand.repository.ProductRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.OptimisticLockingFailureException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

/**
 * 订单领域服务。
 *
 * 核心修复：原实现在创建订单和支付时都不校验商品状态，
 * 导致同一件商品可以被无限次下单 —— 即"一物多卖"。
 * 现在的规则：
 *   1. 只有 ON_SALE 的商品可以下单；
 *   2. 下单成功即在同一事务内把商品标记为 SOLD 并写入 soldOrderId（乐观锁保护）；
 *   3. 取消未付款订单时释放商品回 ON_SALE；
 *   4. 支付时再次校验 soldOrderId 归属，防止并发绕过。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrderService {

    private final OrderRepository orderRepository;
    private final ProductRepository productRepository;
    private final AuditService auditService;

    /** 模拟支付密码（保持与原实现一致，仅用于 demo） */
    private static final String DEMO_PAY_PASSWORD = "123456";

    // ==================== 查询 ====================

    @Transactional(readOnly = true)
    public Order getByOrderNo(String orderNo) {
        Order order = orderRepository.findByOrderNo(orderNo);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        return order;
    }

    /** 按主键查询，不存在返回 null（供后台页面使用，避免抛异常打断渲染） */
    @Transactional(readOnly = true)
    public Order getById(Long id) {
        return id == null ? null : orderRepository.findById(id).orElse(null);
    }

    /** 买家或卖家均可查看 */
    @Transactional(readOnly = true)
    public Order getForParticipant(String orderNo, Long userId) {
        Order order = getByOrderNo(orderNo);
        if (!order.belongsToBuyer(userId) && !order.belongsToSeller(userId)) {
            throw BusinessException.forbidden("无权查看该订单");
        }
        return order;
    }

    @Transactional(readOnly = true)
    public List<Order> listBoughtBy(Long userId) {
        return orderRepository.findByUserIdOrderByCreateTimeDesc(userId);
    }

    @Transactional(readOnly = true)
    public List<Order> listSoldBy(Long sellerId) {
        return orderRepository.findBySellerIdOrderByCreateTimeDesc(sellerId);
    }

    @Transactional(readOnly = true)
    public List<Order> listAll() {
        return orderRepository.findAllByOrderByCreateTimeDesc();
    }

    /** 商品名映射，供列表页展示（避免模板里 N+1 查询） */
    @Transactional(readOnly = true)
    public java.util.Map<Long, Product> productMapFor(List<Order> orders) {
        List<Long> ids = orders.stream()
                .map(Order::getProductId)
                .filter(java.util.Objects::nonNull)
                .distinct()
                .toList();
        java.util.Map<Long, Product> map = new java.util.HashMap<>();
        productRepository.findAllById(ids).forEach(p -> map.put(p.getId(), p));
        return map;
    }

    /**
     * 按商品 ID 批量取订单，每个商品只保留**最新一笔**。
     *
     * 卖家视角的"我的订单"里，未售出的商品没有订单，
     * 已售出的商品有且有订单。用这个映射把两者拼起来。
     * 同一商品可能有多笔历史订单（取消后重下），取最新一笔即可。
     */
    @Transactional(readOnly = true)
    public java.util.Map<Long, Order> latestOrderByProduct(List<Long> productIds) {
        if (productIds == null || productIds.isEmpty()) {
            return java.util.Map.of();
        }
        java.util.Map<Long, Order> map = new java.util.HashMap<>();
        // 仓储已按创建时间降序返回，putIfAbsent 保住最新的一笔
        orderRepository.findByProductIdInOrderByCreateTimeDesc(productIds)
                .forEach(o -> {
                    if (o.getProductId() != null) {
                        map.putIfAbsent(o.getProductId(), o);
                    }
                });
        return map;
    }

    @Transactional(readOnly = true)
    public PageResult<Order> pageAll(int page, int size) {
        return PageResult.from(
                orderRepository.findAll(
                        org.springframework.data.domain.PageRequest.of(
                                Math.max(page, 0), Math.min(Math.max(size, 1), 100),
                                org.springframework.data.domain.Sort.by(
                                        org.springframework.data.domain.Sort.Direction.DESC, "createTime"))),
                o -> o);
    }

    // ==================== 写入 ====================

    /**
     * 创建订单。
     *
     * 关键点：下单即锁定商品。这样"锁定"这件事不依赖支付是否成功，
     * 避免买家下单后不付款导致商品被无限占用 —— 由取消逻辑释放。
     */
    @Transactional
    public Order create(CreateOrderCommand cmd, Long buyerId, String buyerName, ActorContext actor) {
        Product product = productRepository.findById(cmd.productId())
                .orElseThrow(() -> BusinessException.notFound("商品"));

        if (product.isOwnedBy(buyerId)) {
            throw BusinessException.badRequest("不能购买自己发布的商品");
        }
        if (!product.statusEnum().canBeOrdered()) {
            throw BusinessException.conflict(
                    "商品当前状态为「" + product.statusEnum().label() + "」，无法下单");
        }

        Order order = new Order();
        order.setOrderNo(UUID.randomUUID().toString().replace("-", ""));
        order.setUserId(buyerId);
        order.setSellerId(product.getSellerId());
        order.setProductId(product.getId());
        order.setPrice(product.getPrice());
        order.setStatus(OrderStatus.UNPAID.name());
        order.setDeliveryType(cmd.deliveryType());
        order.setAppointmentTime(cmd.appointmentTime());

        Order saved;
        try {
            saved = orderRepository.saveAndFlush(order);

            // 同一事务内锁定商品；若并发冲突，乐观锁会在此抛出
            product.markSold(saved.getId());
            productRepository.saveAndFlush(product);
        } catch (OptimisticLockingFailureException | IllegalStateException e) {
            log.warn("下单失败，商品已被抢占: productId={}, reason={}", cmd.productId(), e.getMessage());
            throw BusinessException.conflict("手慢了，该商品刚刚被其他同学下单");
        }

        audit(actor, AuditActions.ORDER_CREATE, "order", saved.getId(),
                "创建订单 orderNo=" + saved.getOrderNo() + " productId=" + product.getId()
                        + " price=" + saved.getPrice());
        audit(actor, AuditActions.PRODUCT_SOLD, "product", product.getId(),
                "商品已锁定至订单 " + saved.getOrderNo());
        return saved;
    }

    /**
     * 支付订单（模拟）。
     * 支付密码与原实现保持一致（123456），仅用于课程 demo。
     */
    @Transactional
    public Order pay(String orderNo, String payPassword, Long buyerId, ActorContext actor) {
        Order order = getByOrderNo(orderNo);
        if (!order.belongsToBuyer(buyerId)) {
            throw BusinessException.forbidden("只有买家可以支付该订单");
        }
        if (!order.statusEnum().isPayable()) {
            throw BusinessException.conflict("订单当前状态为「" + order.statusEnum().label() + "」，无法支付");
        }
        if (!DEMO_PAY_PASSWORD.equals(payPassword)) {
            throw BusinessException.badRequest("支付密码错误，请重试");
        }

        // 二次校验：商品必须仍锁定在本订单上
        Product product = productRepository.findById(order.getProductId()).orElse(null);
        if (product == null || product.getSoldOrderId() == null
                || !product.getSoldOrderId().equals(order.getId())) {
            throw BusinessException.conflict("商品锁定状态异常，无法完成支付，请联系管理员");
        }

        order.pay();
        Order saved = orderRepository.save(order);
        audit(actor, AuditActions.ORDER_PAY, "order", saved.getId(), "支付订单 orderNo=" + orderNo);
        return saved;
    }

    /**
     * 取消订单（买家）。
     * 未付款订单取消后释放商品，使其重新可售。
     */
    @Transactional
    public Order cancel(String orderNo, Long buyerId, String reason, ActorContext actor) {
        Order order = getByOrderNo(orderNo);
        if (!order.belongsToBuyer(buyerId)) {
            throw BusinessException.forbidden("只有买家可以取消该订单");
        }
        if (!order.statusEnum().canCancelWithoutRefund()) {
            throw BusinessException.conflict("订单当前状态为「" + order.statusEnum().label()
                    + "」，已支付订单需走退款流程");
        }

        order.cancel(reason);
        Order saved = orderRepository.save(order);

        releaseProduct(order, actor);
        audit(actor, AuditActions.ORDER_CANCEL, "order", saved.getId(),
                "取消订单 orderNo=" + orderNo + " reason=" + reason);
        return saved;
    }

    /** 卖家发货 */
    @Transactional
    public Order ship(String orderNo, Long sellerId, ActorContext actor) {
        Order order = getByOrderNo(orderNo);
        if (!order.belongsToSeller(sellerId)) {
            throw BusinessException.forbidden("只有卖家可以发货");
        }
        if (!order.statusEnum().canShip()) {
            throw BusinessException.conflict("只有已付款订单才能发货");
        }
        order.ship();
        Order saved = orderRepository.save(order);
        audit(actor, AuditActions.ORDER_SHIP, "order", saved.getId(), "发货 orderNo=" + orderNo);
        return saved;
    }

    // ==================== 内部工具 ====================

    /** 把商品从订单上释放回在售状态 */
    private void releaseProduct(Order order, ActorContext actor) {
        productRepository.findById(order.getProductId()).ifPresent(product -> {
            if (product.statusEnum() == ProductStatus.SOLD
                    && order.getId().equals(product.getSoldOrderId())) {
                product.releaseFromOrder(order.getId());
                productRepository.save(product);
                audit(actor, AuditActions.PRODUCT_RELIST, "product", product.getId(),
                        "订单取消，商品重新上架 orderNo=" + order.getOrderNo());
            }
        });
    }

    /**
     * 写审计。
     *
     * @param targetType 目标资源类型（order / product），由调用方显式指定，
     *                   避免"订单动作记到商品上"这类标签错误导致审计难以检索
     */
    private void audit(ActorContext actor, String action, String targetType, Long targetId, String detail) {
        if (actor == null) {
            actor = ActorContext.system();
        }
        auditService.record(actor.type(), actor.id(), actor.name(), action,
                targetType, targetId, detail, "SUCCESS", null, actor.conversationId());
    }
}
