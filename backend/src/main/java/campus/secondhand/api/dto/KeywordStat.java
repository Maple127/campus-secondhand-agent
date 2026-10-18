package campus.secondhand.api.dto;

import java.time.LocalDateTime;

/**
 * 「某个关键词被搜了多少次」的聚合结果。
 *
 * 用 JPQL 构造表达式直接产出，避免把聚合逻辑写在模板里。
 * 字段顺序必须与 repository 里的 `new ...KeywordStat(...)` 一致。
 */
public record KeywordStat(String keyword, Long count, LocalDateTime lastTime) {
}
