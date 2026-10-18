/* ============================================================
   价格参考组件
   ------------------------------------------------------------
   数据来自 Java 后端的 /api/v1/products/price-suggestion
   （纯统计，不经过任何 LLM）。

   为什么做成客户端异步加载：
     统计查询比页面渲染慢，同步渲染会把整个详情页拖慢。
     异步加载 + 失败静默隐藏，既快又不会因为统计失败而报错。

   两种模式：
     · scope='product'  商品详情页：有目标价 → 给出"偏高/合理/偏低"判断
     · scope='publish'  发布表单：用户选分类、填价格 → 实时给定价建议
   ============================================================ */
(function (global) {
    'use strict';

    var el = {};
    var opts = { scope: 'publish', category: '', price: null, productId: null, compact: false };
    var lastQueryKey = '';
    var debounceTimer = null;

    // 网页端点：只依赖 HttpSession 登录态，与页面同源。
    // 不走 /api/v1/** —— 那里需要 agent 的服务令牌与能力令牌，浏览器不该持有。
    var API = '/web/price-insight';
    var COMPARE_API = '/web/products/';

    function $(id) { return document.getElementById(id); }

    function money(v) {
        if (v === null || v === undefined || v === '') return '—';
        return '¥' + Number(v).toFixed(2).replace(/\.00$/, '');
    }

    function verdictMeta(verdict) {
        switch (verdict) {
            case 'LOW':  return { cls: 'low',  text: '偏低' };
            case 'HIGH': return { cls: 'high', text: '偏高' };
            case 'FAIR': return { cls: 'fair', text: '合理' };
            default:     return { cls: 'na',   text: '' };
        }
    }

    function hide() {
        if (el.panel) el.panel.hidden = true;
    }

    function show() {
        if (el.panel) el.panel.hidden = false;
    }

    /** 渲染区间条：把 min/max 映射到 0~100% */
    function renderBar(min, max, p25, p75, median) {
        if (el.barRange) {
            var lo = 0, hi = 100;
            var span = max - min;
            if (span > 0) {
                lo = ((p25 - min) / span) * 100;
                hi = ((p75 - min) / span) * 100;
            }
            el.barRange.style.left = Math.max(0, lo) + '%';
            el.barRange.style.width = Math.max(2, hi - lo) + '%';
        }
        if (el.barMedian) {
            var span2 = max - min;
            var pos = span2 > 0 ? ((median - min) / span2) * 100 : 50;
            el.barMedian.style.left = Math.min(100, Math.max(0, pos)) + '%';
        }
        if (el.min) el.min.textContent = money(min);
        if (el.max) el.max.textContent = money(max);
        if (el.median) el.median.textContent = money(median);
    }

    function renderSamples(samples) {
        if (!el.samplesList) return;
        if (!samples || !samples.length) {
            el.samplesList.innerHTML = '';
            return;
        }
        var html = '<div style="margin-bottom:3px;">同类在售参考：</div>';
        samples.slice(0, 3).forEach(function (s) {
            html += '<div class="pi-sample"><span>' + escapeHtml(s.name) +
                    '</span><span>' + money(s.price) + '</span></div>';
        });
        el.samplesList.innerHTML = html;
    }

    function escapeHtml(s) {
        return String(s === null || s === undefined ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function render(data) {
        var meta = verdictMeta(data.verdict);

        if (el.verdict) {
            el.verdict.className = 'pi-verdict ' + meta.cls;
            el.verdict.textContent = meta.text;
            el.verdict.style.display = meta.text ? '' : 'none';
        }

        var insufficient = data.sampleSize < 3;
        if (insufficient) {
            // 样本太少：只说事实，不给区间，也不给判断
            if (el.barWrap) el.barWrap.style.display = 'none';
            if (el.facts) el.facts.style.display = 'none';
            if (el.explain) {
                el.explain.textContent = data.explanation ||
                    '同类商品样本太少，暂时给不出可靠的价格参考。';
            }
            if (el.samplesList) el.samplesList.innerHTML = '';
            show();
            return;
        }

        if (el.barWrap) el.barWrap.style.display = '';
        if (el.facts) el.facts.style.display = '';
        renderBar(Number(data.min), Number(data.max),
                  Number(data.p25), Number(data.p75), Number(data.median));

        if (el.range) el.range.textContent = money(data.p25) + ' ~ ' + money(data.p75);
        if (el.medianVal) el.medianVal.textContent = money(data.median);
        if (el.samples) el.samples.textContent = data.sampleSize + ' 件';
        if (el.explain) el.explain.textContent = data.explanation || '';
        renderSamples(data.samples);
        show();
    }

    function fetchData() {
        var url = opts.scope === 'product' && opts.productId
            ? (COMPARE_API + opts.productId + '/price-insight')
            : buildSuggestionUrl();

        var key = url;
        if (key === lastQueryKey) return;   // 参数没变就不重复请求
        lastQueryKey = key;

        fetch(url, { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (body) {
                if (!body || body.code !== 0 || !body.data) { hide(); return; }
                render(body.data);
            })
            .catch(function () {
                // 统计拿不到就不显示这块，绝不影响主流程
                hide();
            });
    }

    function buildSuggestionUrl() {
        var p = [];
        if (opts.category) p.push('category=' + encodeURIComponent(opts.category));
        // 品类词比分类细一档：给了它，参考区间会从"数码电子"收窄到"耳机"
        if (opts.type) p.push('type=' + encodeURIComponent(opts.type));
        if (opts.condition) p.push('condition=' + encodeURIComponent(opts.condition));
        if (opts.price !== null && opts.price !== undefined && opts.price !== '') {
            p.push('price=' + encodeURIComponent(opts.price));
        }
        return API + (p.length ? '?' + p.join('&') : '');
    }

    var PriceInsight = {
        /**
         * 初始化。
         * @param {Object} o
         *   scope:     'product' | 'publish'
         *   productId: scope=product 时必填
         *   category:  scope=publish 时的分类名
         *   price:     目标价（可选；不传则只报行情）
         *   compact:   是否使用紧凑样式（发布页）
         */
        init: function (o) {
            opts = Object.assign(opts, o || {});
            el = {
                panel: $('priceInsight'),
                verdict: $('piVerdict'),
                barWrap: document.querySelector('#priceInsight .pi-bar-wrap'),
                barRange: $('piBarRange'),
                barMedian: $('piBarMedian'),
                min: $('piMin'),
                max: $('piMax'),
                median: $('piMedian'),
                range: $('piRange'),
                medianVal: $('piMedianVal'),
                samples: $('piSamples'),
                facts: document.querySelector('#priceInsight .pi-facts'),
                explain: $('piExplain'),
                samplesList: $('piSamples-list')
            };
            if (el.panel && opts.compact) el.panel.classList.add('pi-compact');
            fetchData();
            return this;
        },

        /** 发布页：分类或价格变化时刷新（带防抖，避免每敲一个数字就请求） */
        update: function (o) {
            opts = Object.assign(opts, o || {});
            if (debounceTimer) clearTimeout(debounceTimer);
            debounceTimer = setTimeout(fetchData, 400);
            return this;
        },

        /** 仅当参数真的变化时才请求 */
        _reset: function () { lastQueryKey = ''; }
    };

    global.PriceInsight = PriceInsight;
})(window);
