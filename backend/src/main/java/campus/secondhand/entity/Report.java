package campus.secondhand.entity;

import jakarta.persistence.*;
import lombok.Data;
import org.hibernate.annotations.CreationTimestamp;
import java.time.LocalDateTime;

@Data
@Entity
@Table(name = "report")
public class Report {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long userId;        // 举报人ID
    private String username;    // 举报人用户名

    @Column(nullable = false)
    private Long productId;     // 被举报的商品ID
    private String productName; // 商品名称
    private Long sellerId;      // 卖家ID

    /**
     * 举报类型：虚假商品、违规物品、价格欺诈、其他
     */
    @Column(nullable = false)
    private String reasonType;

    /**
     * 详细描述/证据说明
     */
    @Column(length = 1000)
    private String description;

    /**
     * 状态：0-待处理，1-已核实下架，2-驳回举报
     */
    @Column(nullable = false)
    private Integer status = 0;

    private String adminReply;  // 管理员处理批复（可选）

    @CreationTimestamp
    @Column(updatable = false)
    private LocalDateTime createTime;
}