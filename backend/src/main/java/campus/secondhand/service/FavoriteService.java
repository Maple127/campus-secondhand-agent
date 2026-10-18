package campus.secondhand.service;

import campus.secondhand.common.ActorContext;
import campus.secondhand.common.AuditActions;
import campus.secondhand.common.BusinessException;
import campus.secondhand.entity.Favorite;
import campus.secondhand.entity.Product;
import campus.secondhand.repository.FavoriteRepository;
import campus.secondhand.repository.ProductRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 收藏领域服务。
 */
@Service
@RequiredArgsConstructor
public class FavoriteService {

    private final FavoriteRepository favoriteRepository;
    private final ProductRepository productRepository;
    private final AuditService auditService;

    /** 收藏/取消收藏，返回 true 表示收藏成功 */
    @Transactional
    public boolean toggle(Long userId, Long productId, ActorContext actor) {
        Product product = productRepository.findById(productId)
                .orElseThrow(() -> BusinessException.notFound("商品"));

        var existing = favoriteRepository.findByUserIdAndProductId(userId, productId);
        if (existing.isPresent()) {
            favoriteRepository.delete(existing.get());
            audit(actor, AuditActions.FAVORITE_REMOVE, productId, "取消收藏 " + product.getName());
            return false;
        }
        Favorite favorite = new Favorite();
        favorite.setUserId(userId);
        favorite.setProductId(productId);
        favoriteRepository.save(favorite);
        audit(actor, AuditActions.FAVORITE_ADD, productId, "收藏 " + product.getName());
        return true;
    }

    /** 我的收藏商品列表（保持收藏时间倒序） */
    @Transactional(readOnly = true)
    public List<Product> listProducts(Long userId) {
        List<Long> productIds = favoriteRepository.findByUserIdOrderByCreateTimeDesc(userId)
                .stream()
                .map(Favorite::getProductId)
                .toList();
        if (productIds.isEmpty()) {
            return List.of();
        }
        // 按收藏顺序返回
        List<Product> found = productRepository.findAllById(productIds);
        return productIds.stream()
                .map(id -> found.stream().filter(p -> p.getId().equals(id)).findFirst().orElse(null))
                .filter(java.util.Objects::nonNull)
                .toList();
    }

    @Transactional(readOnly = true)
    public boolean isFavorited(Long userId, Long productId) {
        return userId != null && favoriteRepository.existsByUserIdAndProductId(userId, productId);
    }

    private void audit(ActorContext actor, String action, Long productId, String detail) {
        if (actor == null) {
            actor = ActorContext.system();
        }
        auditService.record(actor.type(), actor.id(), actor.name(), action,
                "product", productId, detail, "SUCCESS", null, actor.conversationId());
    }
}
