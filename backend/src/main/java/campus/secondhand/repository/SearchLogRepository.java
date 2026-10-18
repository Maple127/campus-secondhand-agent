package campus.secondhand.repository;

import campus.secondhand.api.dto.KeywordStat;
import campus.secondhand.entity.SearchLog;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface SearchLogRepository extends JpaRepository<SearchLog, Long> {

    /**
     * 没有任何结果的关键词，按被搜次数降序。
     *
     * 这是最有价值的一张表：每一条都在说"有人想找这个，平台没有（或者我们的词表不认识它）"。
     */
    @Query("""
            SELECT new campus.secondhand.api.dto.KeywordStat(s.keyword, COUNT(s), MAX(s.createTime))
            FROM SearchLog s
            WHERE s.resultCount = 0
            GROUP BY s.keyword
            ORDER BY COUNT(s) DESC, MAX(s.createTime) DESC
            """)
    List<KeywordStat> zeroResultKeywords(Pageable pageable);

    /**
     * 按零结果原因分组的关键词。
     *
     * hint = TYPE_EMPTY → 词表认识但平台没货（运营问题）
     * hint = NO_TYPE    → 词表不认识（补别名就能修）
     *
     * 把这两种分开看，是因为处理方式完全不同：一个要补数据，一个要补货。
     */
    @Query("""
            SELECT new campus.secondhand.api.dto.KeywordStat(s.keyword, COUNT(s), MAX(s.createTime))
            FROM SearchLog s
            WHERE s.resultCount = 0 AND s.hint = :hint
            GROUP BY s.keyword
            ORDER BY COUNT(s) DESC, MAX(s.createTime) DESC
            """)
    List<KeywordStat> zeroResultByHint(@Param("hint") String hint, Pageable pageable);

    /** 命中了但很少（1~2 件），可能是供给不足，也可能是词表/分类没对上 */
    @Query("""
            SELECT new campus.secondhand.api.dto.KeywordStat(s.keyword, COUNT(s), MAX(s.createTime))
            FROM SearchLog s
            WHERE s.resultCount BETWEEN 1 AND 2
            GROUP BY s.keyword
            ORDER BY COUNT(s) DESC, MAX(s.createTime) DESC
            """)
    List<KeywordStat> lowResultKeywords(Pageable pageable);

    /** 被搜最多的关键词（不管结果多少） */
    @Query("""
            SELECT new campus.secondhand.api.dto.KeywordStat(s.keyword, COUNT(s), MAX(s.createTime))
            FROM SearchLog s
            GROUP BY s.keyword
            ORDER BY COUNT(s) DESC, MAX(s.createTime) DESC
            """)
    List<KeywordStat> topKeywords(Pageable pageable);

    List<SearchLog> findAllByOrderByCreateTimeDesc(Pageable pageable);

    long countByResultCount(int resultCount);
}
