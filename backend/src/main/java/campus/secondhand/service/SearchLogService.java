package campus.secondhand.service;

import campus.secondhand.api.dto.KeywordStat;
import campus.secondhand.entity.SearchLog;
import campus.secondhand.repository.SearchLogRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 搜索日志服务。
 *
 * ## 一个刻意的设计：写日志失败不能影响搜索
 *
 * 用户来是为了找东西，不是为了让我们统计。日志写失败（DB 抖动、字段超长）
 * 必须被吞掉并且只留一条 warn，绝不能把 500 抛给用户。
 *
 * 用 {@link Propagation#REQUIRES_NEW}：主流程是只读事务（@Transactional(readOnly=true)），
 * 如果复用同一个事务，MySQL 会把这次写入当成只读事务的一部分而报错。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class SearchLogService {

    private static final int MAX_KEYWORD_LEN = 100;
    private static final int MAX_ACTOR_LEN = 64;

    private final SearchLogRepository searchLogRepository;

    /**
     * 记录一次搜索。
     *
     * @param keyword     用户输入的关键词；为空（打开首页）时不记录
     * @param category    分类筛选
     * @param resultCount 命中数量
     * @param source      web / agent
     * @param actor       用户名或 agent 身份名，可为空
     */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void record(String keyword, String category, long resultCount,
                       String source, String actor) {
        record(keyword, category, resultCount, source, actor, null);
    }

    /**
     * 记录一次搜索（带零结果原因）。
     *
     * @param hint 零结果原因：TYPE_EMPTY / NO_TYPE；有结果时传 null
     */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void record(String keyword, String category, long resultCount,
                       String source, String actor, String hint) {
        if (keyword == null || keyword.isBlank()) {
            return;   // 浏览不是搜索
        }
        try {
            SearchLog entry = new SearchLog();
            entry.setKeyword(truncate(keyword.trim(), MAX_KEYWORD_LEN));
            entry.setCategory(truncate(category, 50));
            entry.setResultCount((int) Math.min(resultCount, Integer.MAX_VALUE));
            entry.setSource(truncate(source, 16));
            entry.setActor(truncate(actor, MAX_ACTOR_LEN));
            entry.setHint(truncate(hint, 16));
            searchLogRepository.save(entry);
        } catch (Exception e) {
            // 统计失败不影响用户搜索 —— 这是刻意的取舍
            log.warn("搜索日志写入失败（已忽略）: keyword={} err={}", keyword, e.toString());
        }
    }

    // ==================== 管理端读取 ====================

    @Transactional(readOnly = true)
    public List<KeywordStat> zeroResultKeywords(int limit) {
        return searchLogRepository.zeroResultKeywords(PageRequest.of(0, limit));
    }

    /**
     * 零结果关键词，按原因分组。
     * hint 取 {@link #HINT_NO_TYPE} 或 {@link #HINT_TYPE_EMPTY}。
     */
    @Transactional(readOnly = true)
    public List<KeywordStat> zeroResultByHint(String hint, int limit) {
        return searchLogRepository.zeroResultByHint(hint, PageRequest.of(0, limit));
    }

    /** 词表不认识这个说法 —— 补个别名就能修 */
    public static final String HINT_NO_TYPE = "NO_TYPE";

    /** 词表认识，但平台没有这类货 —— 供给问题 */
    public static final String HINT_TYPE_EMPTY = "TYPE_EMPTY";

    @Transactional(readOnly = true)
    public List<KeywordStat> lowResultKeywords(int limit) {
        return searchLogRepository.lowResultKeywords(PageRequest.of(0, limit));
    }

    @Transactional(readOnly = true)
    public List<KeywordStat> topKeywords(int limit) {
        return searchLogRepository.topKeywords(PageRequest.of(0, limit));
    }

    @Transactional(readOnly = true)
    public List<SearchLog> recent(int limit) {
        return searchLogRepository.findAllByOrderByCreateTimeDesc(PageRequest.of(0, limit));
    }

    @Transactional(readOnly = true)
    public long zeroResultTotal() {
        return searchLogRepository.countByResultCount(0);
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return null;
        }
        String t = s.trim();
        return t.length() <= max ? t : t.substring(0, max);
    }
}
