package campus.secondhand.common;

import lombok.Getter;

import java.util.List;
import java.util.function.Function;

/**
 * 统一分页返回结构，供 REST / Agent 工具使用。
 */
@Getter
public class PageResult<T> {

    private final List<T> items;
    private final int page;
    private final int size;
    private final long totalElements;
    private final int totalPages;

    public PageResult(List<T> items, int page, int size, long totalElements, int totalPages) {
        this.items = items;
        this.page = page;
        this.size = size;
        this.totalElements = totalElements;
        this.totalPages = totalPages;
    }

    public static <E, T> PageResult<T> from(org.springframework.data.domain.Page<E> page, Function<E, T> mapper) {
        return new PageResult<>(
                page.getContent().stream().map(mapper).toList(),
                page.getNumber(),
                page.getSize(),
                page.getTotalElements(),
                page.getTotalPages()
        );
    }

    /** 把元素类型从 T 转换成 R，保留分页元信息 */
    public <R> PageResult<R> map(Function<T, R> mapper) {
        return new PageResult<>(
                items.stream().map(mapper).toList(),
                page, size, totalElements, totalPages);
    }
}
