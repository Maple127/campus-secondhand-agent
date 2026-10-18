package campus.secondhand.api.web;

import campus.secondhand.entity.ProductType;
import campus.secondhand.service.ProductTypeService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 发布页用的品类词接口（网页同源，不经过 agent 网关）。
 *
 * 两个用途：
 *   1. 分类选定后，给出这个分类下可选的品类词
 *   2. 标题输入过程中，猜一个最可能的品类并预选
 *
 * 猜错无所谓 —— 卖家面前是一个可以改的下拉框，不是一个自动提交的操作。
 */
@RestController
@RequiredArgsConstructor
public class ProductTypeController {

    private final ProductTypeService productTypeService;

    /** 某个分类下可选的品类词（不含别名，前端只需要名字） */
    @GetMapping("/web/product-types")
    public Map<String, Object> list(@RequestParam(required = false) String category) {
        List<ProductType> types = productTypeService.listByCategory(category);
        List<Map<String, Object>> items = types.stream()
                .map(t -> {
                    Map<String, Object> m = new HashMap<>();
                    m.put("name", t.getName());
                    return m;
                })
                .toList();

        Map<String, Object> body = new HashMap<>();
        body.put("code", 0);
        body.put("data", items);
        return body;
    }

    /**
     * 根据标题猜品类。
     *
     * 命中用"最长词优先"：标题里有「机械键盘」时不应该猜成「键盘」。
     */
    @GetMapping("/web/product-types/suggest")
    public Map<String, Object> suggest(@RequestParam(required = false) String title,
                                       @RequestParam(required = false) String category) {
        Map<String, Object> data = new HashMap<>();
        data.put("suggested", productTypeService.suggest(title, category).orElse(null));
        data.put("candidates", productTypeService.namesByCategory(category));

        Map<String, Object> body = new HashMap<>();
        body.put("code", 0);
        body.put("data", data);
        return body;
    }
}
