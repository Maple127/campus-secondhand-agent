package campus.secondhand.entity;
import jakarta.persistence.*;
import lombok.Data;
import jakarta.persistence.*;
import lombok.Data;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Data
@Entity
@Table(name = "users")
public class User {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(unique = true, nullable = false)
    private String username;

    @Column(nullable = false)
    private String password;

    /** 学校 */
    private String school;

    /** 年级 */
    private String grade;

    /** 手机号 */
    private String phone;

    /** 收货地址（只在地址页显示） */
    private String shippingAddress;

    private String creditStatus;   // 信用状态，例如 "正常"、"警告"、"封禁"

    // getter / setter
    public String getCreditStatus() { return creditStatus; }
    public void setCreditStatus(String creditStatus) { this.creditStatus = creditStatus; }

    @CreationTimestamp
    @Column(updatable = false)
    private LocalDateTime createTime;

}