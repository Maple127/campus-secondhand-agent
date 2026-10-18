package campus.secondhand.entity;

import jakarta.persistence.*;
import lombok.Data;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Data
@Entity
@Table(
        name = "favorite",
        uniqueConstraints = @UniqueConstraint(columnNames = {"user_id", "product_id"})
)
public class Favorite {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 收藏者ID */
    @Column(name = "user_id", nullable = false)
    private Long userId;

    /** 被收藏的商品ID */
    @Column(name = "product_id", nullable = false)
    private Long productId;

    @CreationTimestamp
    @Column(updatable = false)
    private LocalDateTime createTime;
}
