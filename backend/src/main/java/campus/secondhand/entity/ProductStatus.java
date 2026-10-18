package campus.secondhand.entity;

import java.util.Set;

/**
 * 商品生命周期状态机。
 *
 * <pre>
 *   PENDING_APPROVAL ──approve──► ON_SALE ──createOrder+pay──► SOLD
 *          │                        │  ▲                        │
 *          │reject                  │  │ relist                 │cancelPaidOrder
 *          ▼                        ▼  │                        ▼
 *      REJECTED                 DELISTED ──────────────────► ON_SALE
 * </pre>
 *
 * 状态码与数据库历史值保持一致（0/1/2），新增 3/4 只做扩展，不需要数据迁移。
 */
public enum ProductStatus {

    /** 待审核：用户（或 agent 代填）提交后、管理员审核前 */
    PENDING_APPROVAL(0, "待审核"),

    /** 在售：审核通过，首页可见，可被下单 */
    ON_SALE(1, "在售"),

    /** 已拒绝：审核未通过（含举报核实违规下架） */
    REJECTED(2, "已拒绝"),

    /** 已下架：卖家主动下架 */
    DELISTED(3, "已下架"),

    /** 已售出：订单已支付，锁定不可再下单 —— 这是修复"一物多卖"的关键状态 */
    SOLD(4, "已售出");

    private final int code;
    private final String label;

    ProductStatus(int code, String label) {
        this.code = code;
        this.label = label;
    }

    public int code() {
        return code;
    }

    public String label() {
        return label;
    }

    public static ProductStatus of(Integer code) {
        if (code == null) {
            return PENDING_APPROVAL;
        }
        for (ProductStatus s : values()) {
            if (s.code == code) {
                return s;
            }
        }
        throw new IllegalArgumentException("未知的商品状态码: " + code);
    }

    /** 管理员审核通过：仅待审核状态可执行 */
    public boolean canApprove() {
        return this == PENDING_APPROVAL;
    }

    /** 管理员审核拒绝：待审核与在售都可以被驳回（后者用于举报核实违规） */
    public boolean canReject() {
        return this == PENDING_APPROVAL || this == ON_SALE;
    }

    /** 卖家主动下架：只有在售商品可以下架 */
    public boolean canDelist() {
        return this == ON_SALE;
    }

    /** 重新上架：已下架或已拒绝的商品可重新提交审核 */
    public boolean canRelist() {
        return this == DELISTED || this == REJECTED;
    }

    /** 是否可以被买家下单 —— 唯一入口，杜绝一物多卖 */
    public boolean canBeOrdered() {
        return this == ON_SALE;
    }

    /** 是否对普通用户（首页/搜索）可见 */
    public boolean isPubliclyVisible() {
        return this == ON_SALE || this == SOLD;
    }

    /** 合法迁移表，仅用于断言与文档化 */
    public Set<ProductStatus> allowedNext() {
        return switch (this) {
            case PENDING_APPROVAL -> Set.of(ON_SALE, REJECTED);
            case ON_SALE -> Set.of(SOLD, DELISTED, REJECTED);
            case REJECTED -> Set.of(PENDING_APPROVAL);
            case DELISTED -> Set.of(PENDING_APPROVAL);
            case SOLD -> Set.of(ON_SALE); // 仅退款/取消已支付订单时回退
        };
    }
}
