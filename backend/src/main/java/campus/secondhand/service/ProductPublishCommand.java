package campus.secondhand.service;

import java.math.BigDecimal;

/**
 * 发布商品的入参。
 *
 * 网页表单与 Agent 工具都转换成这个对象后调用 ProductService，
 * 保证两条入口的校验规则完全一致（这是避免逻辑漂移的关键）。
 *
 * @param name           商品名称（必填）
 * @param description    描述
 * @param price          价格（必填，> 0）
 * @param originalPrice  原价（可选）
 * @param conditionLevel 成色（可选，如"9成新"）
 * @param location       交易地点
 * @param categoryName   分类名称（可选，服务层做模糊归一化）
 * @param categoryId     分类ID（优先级高于 categoryName）
 * @param imagePath      已保存的图片路径（由 FileStorageService 产出）
 * @param productType    品类词（可选，如"耳机""充电宝"）。为空时服务层会按标题猜一个
 */
public record ProductPublishCommand(
        String name,
        String description,
        BigDecimal price,
        BigDecimal originalPrice,
        String conditionLevel,
        String location,
        String categoryName,
        Long categoryId,
        String imagePath,
        String productType
) {

    public ProductPublishCommand {
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("商品名称不能为空");
        }
        if (price == null || price.signum() <= 0) {
            throw new IllegalArgumentException("商品价格必须大于 0");
        }
    }

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {
        private String name;
        private String description;
        private BigDecimal price;
        private BigDecimal originalPrice;
        private String conditionLevel;
        private String location;
        private String categoryName;
        private Long categoryId;
        private String imagePath;
        private String productType;

        public Builder name(String v) { this.name = v; return this; }
        public Builder description(String v) { this.description = v; return this; }
        public Builder price(BigDecimal v) { this.price = v; return this; }
        public Builder originalPrice(BigDecimal v) { this.originalPrice = v; return this; }
        public Builder conditionLevel(String v) { this.conditionLevel = v; return this; }
        public Builder location(String v) { this.location = v; return this; }
        public Builder categoryName(String v) { this.categoryName = v; return this; }
        public Builder categoryId(Long v) { this.categoryId = v; return this; }
        public Builder imagePath(String v) { this.imagePath = v; return this; }
        public Builder productType(String v) { this.productType = v; return this; }

        public ProductPublishCommand build() {
            return new ProductPublishCommand(name, description, price, originalPrice,
                    conditionLevel, location, categoryName, categoryId, imagePath, productType);
        }
    }
}
