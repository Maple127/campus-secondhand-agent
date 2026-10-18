package campus.secondhand.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import campus.secondhand.entity.Order;

import java.util.List;

@Repository
public interface OrderRepository extends JpaRepository<Order, Long> {

    // 查询当前用户所有订单，按创建时间降序
    // ⭐ 查询用户作为买家的订单（userId = 买家ID）
    List<Order> findByUserIdOrderByCreateTimeDesc(Long userId);


    List<Order> findBySellerIdOrderByCreateTimeDesc(Long sellerId);

    // ⭐ 查询用户作为买家或卖家的所有订单（合并查询）
    List<Order> findByUserIdOrSellerIdOrderByCreateTimeDesc(Long userId, Long sellerId);

    // 根据订单号查询
    Order findByOrderNo(String orderNo);

    // 统计买家待付款数量
    long countByUserIdAndStatus(Long userId, String status);

    // 统计卖家待付款数量
    long countBySellerIdAndStatus(Long sellerId, String status);

    // 管理员查看全局所有订单，按创建时间降序
    List<Order> findAllByOrderByCreateTimeDesc();

    /**
     * 按商品 ID 批量查订单（最新在前）。
     *
     * 用途：卖家视角的"我的订单"要同时展示**还没卖出去**的商品
     * （待审核 / 出售中），那些商品根本没有订单；
     * 只有已售出的商品才有订单。所以先取商品列表，再按商品批量补订单。
     * 批量查而不是逐条查，避免 N+1。
     */
    List<Order> findByProductIdInOrderByCreateTimeDesc(java.util.Collection<Long> productIds);
}
