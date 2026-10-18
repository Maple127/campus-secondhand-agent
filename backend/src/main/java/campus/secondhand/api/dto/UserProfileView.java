package campus.secondhand.api.dto;

import campus.secondhand.entity.User;

/**
 * 个人资料对外视图（不含密码）。
 */
public record UserProfileView(
        Long id,
        String username,
        String school,
        String grade,
        String phone,
        String shippingAddress,
        String creditStatus
) {

    public static UserProfileView of(User u) {
        return new UserProfileView(
                u.getId(),
                u.getUsername(),
                u.getSchool(),
                u.getGrade(),
                u.getPhone(),
                u.getShippingAddress(),
                u.getCreditStatus()
        );
    }
}
