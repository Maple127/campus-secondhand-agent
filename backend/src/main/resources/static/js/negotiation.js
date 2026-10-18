/* ============================================================
   议价面板
   ------------------------------------------------------------
   数据来自 Java 后端 /web/products/{id}/negotiation-advice。
   所有金额都是后端算的，前端只负责显示 ——
   这样即使 AI 服务挂了，议价建议照常可用。
   ============================================================ */
(function (global) {
    'use strict';

    var loaded = false;
    var open = false;
    var el = {};

    var VERDICT = {
        FAIR:           { cls: 'fair',      text: '价格合理，没必要砍' },
        SLIGHTLY_HIGH:  { cls: 'high',      text: '略高于同类中位价，有谈的空间' },
        EXPENSIVE:      { cls: 'expensive', text: '明显偏贵，建议谈到合理区间' },
        UNKNOWN:        { cls: 'unknown',   text: '同类样本太少，给不出可靠建议' }
    };

    function $(id) { return document.getElementById(id); }

    function money(v) {
        if (v === null || v === undefined || v === '') return '—';
        return '¥' + Number(v).toFixed(0);
    }

    function render(d) {
        var v = VERDICT[d.verdict] || VERDICT.UNKNOWN;

        el.verdict.className = 'nego-verdict ' + v.cls;
        el.verdict.textContent = v.text;

        var enough = d.verdict !== 'UNKNOWN' && d.suggestedOpen !== null;
        el.prices.style.display = enough ? '' : 'none';

        if (enough) {
            el.open.textContent = money(d.suggestedOpen);
            el.target.textContent = money(d.suggestedTarget);
            el.walk.textContent = money(d.walkAway);
        }

        el.reason.textContent = d.reasoning || '';
        el.script.textContent = d.script || '';

        var tips = [];
        if (d.confidence !== 'HIGH') {
            tips.push('同品类样本只有 ' + d.sampleSize + ' 条，这个建议的参考价值有限。');
        }
        if (d.cheaperCount > 0) {
            tips.push('同品类有 ' + d.cheaperCount + ' 件更便宜，谈不下来可以看看别的。');
        }
        if (d.daysListed >= 14) {
            tips.push('这件已经挂了 ' + d.daysListed + ' 天。');
        }
        el.tip.textContent = tips.join(' ');

        el.hint.textContent = v.text;
    }

    function load(productId) {
        if (loaded) return;
        loaded = true;

        el.hint.textContent = '正在算…';
        fetch('/web/products/' + productId + '/negotiation-advice',
              { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (b) {
                if (!b || b.code !== 0 || !b.data) { hide(); return; }
                render(b.data);
            })
            .catch(function () { hide(); });
    }

    function hide() {
        if (el.panel) el.panel.hidden = true;
    }

    function toggle() {
        if (!el.body) return;
        open = !open;
        el.body.hidden = !open;
        if (open) load(el.panel.dataset.productId);
    }

    var NegotiationPanel = {
        init: function (productId) {
            el.panel = $('negoPanel');
            if (!el.panel) return this;
            el.panel.hidden = false;
            el.panel.dataset.productId = productId;

            el.toggle = $('negoToggle');
            el.body = $('negoBody');
            el.hint = $('negoHint');
            el.verdict = $('negoVerdict');
            el.prices = $('negoPrices');
            el.open = $('negoOpen');
            el.target = $('negoTarget');
            el.walk = $('negoWalk');
            el.reason = $('negoReason');
            el.script = $('negoScript');
            el.tip = $('negoTip');
            el.copy = $('negoCopy');

            el.toggle.addEventListener('click', toggle);

            el.copy.addEventListener('click', function () {
                var text = el.script.textContent || '';
                if (!text) return;
                var done = function () {
                    el.copy.textContent = '已复制';
                    setTimeout(function () { el.copy.textContent = '复制'; }, 1500);
                };
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(text).then(done).catch(function () {});
                } else {
                    // 老浏览器兜底
                    var ta = document.createElement('textarea');
                    ta.value = text;
                    document.body.appendChild(ta);
                    ta.select();
                    try { document.execCommand('copy'); done(); } catch (e) {}
                    document.body.removeChild(ta);
                }
            });

            return this;
        }
    };

    global.NegotiationPanel = NegotiationPanel;
})(window);
