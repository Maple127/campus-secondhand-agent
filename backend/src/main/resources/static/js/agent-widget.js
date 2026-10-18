/* ============================================================
   AI 助手前端逻辑
   ------------------------------------------------------------
   身份流转（关键）：
     1. 用户已登录网页端（Java 8081），浏览器持有 HttpSession cookie
     2. 前端向 Java POST /api/v1/agent/session 换取 capability token
     3. 前端把 token 放在 X-Actor-Token 头里调用 Python agent (8090)
     4. Python 再用双层令牌调用 Java 的 /api/v1/**

   安全性：
     - token 只保存在内存变量中，不落 localStorage，刷新即失效
     - 前端拿不到也不传递用户密码；换 token 用的还是 cookie 登录态
   ============================================================ */
(function () {
    'use strict';

    var root = document.getElementById('agentWidget');
    if (!root) return;

    var AGENT_URL = (root.dataset.agentUrl || 'http://127.0.0.1:8090').replace(/\/$/, '');
    var SERVICE_TOKEN = root.dataset.serviceToken || 'demo-agent-token-local';

    var fab = document.getElementById('agentFab');
    var panel = document.getElementById('agentPanel');
    var logEl = document.getElementById('agentLog');
    var inputEl = document.getElementById('agentInput');
    var sendBtn = document.getElementById('agentSend');
    var statusEl = document.getElementById('agentStatus');

    var actorToken = null;
    var conversationId = 'conv-' + Math.random().toString(36).slice(2, 10);
    var busy = false;
    // 当前等待用户确认的动作（同一时刻最多一个）
    var pendingConfirmation = null;

    // ---------- 工具函数 ----------
    function scrollDown() {
        logEl.scrollTop = logEl.scrollHeight;
    }

    function clearHint() {
        var hint = logEl.querySelector('.agent-hint');
        if (hint) hint.remove();
    }

    function addMessage(role, text) {
        clearHint();
        var div = document.createElement('div');
        div.className = 'agent-msg ' + role;
        div.textContent = text;
        logEl.appendChild(div);
        scrollDown();
        return div;
    }

    function addTool(name, args) {
        clearHint();
        var div = document.createElement('div');
        div.className = 'agent-tool';
        div.textContent = '🔧 ' + name;
        if (args && Object.keys(args).length) {
            var span = document.createElement('span');
            span.className = 'args';
            span.textContent = JSON.stringify(args);
            div.appendChild(span);
        }
        logEl.appendChild(div);
        scrollDown();
        return div;
    }

    function setStatus(text, ok) {
        statusEl.textContent = text;
        statusEl.style.color = ok === false ? '#fecaca' : '';
    }

    // ---------- 换取 capability token ----------
    function ensureToken() {
        if (actorToken) return Promise.resolve(actorToken);

        setStatus('正在获取授权…');
        return fetch('/api/v1/agent/session', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Service-Token': SERVICE_TOKEN
            },
            body: JSON.stringify({ conversationId: conversationId }),
            credentials: 'same-origin'   // 带上 HttpSession cookie
        })
            .then(function (r) { return r.json(); })
            .then(function (body) {
                if (body.code !== 0 || !body.data || !body.data.actorToken) {
                    throw new Error(body.message || '授权失败，请重新登录');
                }
                actorToken = body.data.actorToken;
                conversationId = body.data.conversationId || conversationId;
                setStatus('已连接（' + body.data.scopes.length + ' 项权限）', true);
                return actorToken;
            })
            .catch(function (e) {
                setStatus('连接失败', false);
                throw e;
            });
    }

    // ---------- 发送并处理 SSE ----------
    function send() {
        var text = inputEl.value.trim();
        if (!text || busy) return;

        busy = true;
        sendBtn.disabled = true;
        inputEl.value = '';
        inputEl.style.height = 'auto';

        addMessage('user', text);
        var bubble = addMessage('assistant', '');
        bubble.classList.add('agent-caret');

        ensureToken()
            .then(function (token) {
                return fetch(AGENT_URL + '/api/chat/stream', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Actor-Token': token
                    },
                    body: JSON.stringify({ message: text, conversationId: conversationId })
                });
            })
            .then(function (resp) {
                if (resp.status === 401) {
                    // 令牌过期：清掉后让用户重试一次即可
                    actorToken = null;
                    throw new Error('授权已过期，请再发一次');
                }
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                return readStream(resp, bubble);
            })
            .catch(function (e) {
                bubble.classList.remove('agent-caret');
                if (!bubble.textContent) {
                    bubble.className = 'agent-msg error';
                    bubble.textContent = '⚠️ ' + e.message;
                }
                setStatus('出错', false);
            })
            .finally(function () {
                bubble.classList.remove('agent-caret');
                if (!bubble.textContent) bubble.textContent = '（没有返回内容）';
                busy = false;
                sendBtn.disabled = false;
                inputEl.focus();
            });
    }

    function readStream(resp, bubble) {
        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        function pump() {
            return reader.read().then(function (res) {
                if (res.done) return;
                buffer += decoder.decode(res.value, { stream: true });

                // SSE 事件以空行分隔
                var chunks = buffer.split('\n\n');
                buffer = chunks.pop();

                chunks.forEach(function (chunk) {
                    var line = chunk.split('\n').filter(function (l) {
                        return l.indexOf('data:') === 0;
                    })[0];
                    if (!line) return;

                    var evt;
                    try { evt = JSON.parse(line.slice(5).trim()); } catch (e) { return; }

                    if (evt.type === 'token') {
                        bubble.textContent += evt.text;
                        scrollDown();
                    } else if (evt.type === 'tool_start') {
                        addTool(evt.name, evt.args);
                    } else if (evt.type === 'tool_end') {
                        var box = addTool(evt.name + (evt.ok ? ' ✓' : ' ✗'));
                        box.classList.add('done');
                    } else if (evt.type === 'confirmation_required') {
                        showConfirmation(evt);
                    } else if (evt.type === 'error') {
                        bubble.classList.remove('agent-caret');
                        bubble.className = 'agent-msg error';
                        bubble.textContent = '⚠️ ' + evt.message;
                        setStatus('出错', false);
                    }
                });
                return pump();
            });
        }
        return pump();
    }

    // ---------- 人工确认卡片 ----------
    //
    // 写操作（发布/下单/下架…）会在后端 interrupt 挂起，前端据此渲染一张卡片。
    // 这是用户唯一的把关机会，因此字段必须完整可核对。
    function showConfirmation(evt) {
        clearHint();
        pendingConfirmation = evt;

        var card = document.createElement('div');
        card.className = 'agent-confirm';
        card.dataset.action = evt.action || '';

        var title = document.createElement('div');
        title.className = 'agent-confirm-title';
        title.textContent = (evt.summary && evt.summary.title) || '确认执行该操作？';
        card.appendChild(title);

        var fields = (evt.summary && evt.summary.fields) || [];
        if (fields.length) {
            var dl = document.createElement('div');
            dl.className = 'agent-confirm-fields';
            fields.forEach(function (f) {
                var row = document.createElement('div');
                row.className = 'agent-confirm-row';
                var k = document.createElement('span');
                k.className = 'k';
                k.textContent = f.label;
                var v = document.createElement('span');
                v.className = 'v';
                v.textContent = f.value;
                row.appendChild(k);
                row.appendChild(v);
                dl.appendChild(row);
            });
            card.appendChild(dl);
        }

        if (evt.summary && evt.summary.notice) {
            var notice = document.createElement('div');
            notice.className = 'agent-confirm-notice';
            notice.textContent = 'ℹ️ ' + evt.summary.notice;
            card.appendChild(notice);
        }

        var actions = document.createElement('div');
        actions.className = 'agent-confirm-actions';

        var okBtn = document.createElement('button');
        okBtn.className = 'ok';
        okBtn.textContent = '确认执行';
        var noBtn = document.createElement('button');
        noBtn.className = 'no';
        noBtn.textContent = '取消';

        okBtn.addEventListener('click', function () { decide(true, card, actions); });
        noBtn.addEventListener('click', function () { decide(false, card, actions); });

        actions.appendChild(okBtn);
        actions.appendChild(noBtn);
        card.appendChild(actions);

        logEl.appendChild(card);
        scrollDown();
        setStatus('等待你确认');
    }

    function decide(approved, card, actions) {
        if (busy || !pendingConfirmation) return;

        // 立即禁用按钮，避免用户双击产生两次 resume
        Array.prototype.forEach.call(actions.querySelectorAll('button'), function (b) {
            b.disabled = true;
        });

        var stamp = document.createElement('div');
        stamp.className = 'agent-confirm-stamp ' + (approved ? 'ok' : 'no');
        stamp.textContent = approved ? '✓ 已确认' : '✕ 已取消';
        card.appendChild(stamp);

        var banner = addMessage('system', approved ? '正在执行…' : '已取消该操作');
        pendingConfirmation = null;

        busy = true;
        sendBtn.disabled = true;
        var bubble = addMessage('assistant', '');
        bubble.classList.add('agent-caret');

        ensureToken()
            .then(function (token) {
                return fetch(AGENT_URL + '/api/chat/resume', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Actor-Token': token
                    },
                    body: JSON.stringify({
                        conversationId: conversationId,
                        approved: approved,
                        action: (card.dataset.action || '')
                    })
                });
            })
            .then(function (resp) {
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                return readStream(resp, bubble);
            })
            .catch(function (e) {
                bubble.classList.remove('agent-caret');
                bubble.className = 'agent-msg error';
                bubble.textContent = '⚠️ 执行失败：' + e.message;
            })
            .finally(function () {
                bubble.classList.remove('agent-caret');
                if (!bubble.textContent) bubble.textContent = '（没有返回内容）';
                if (banner && banner.parentNode) banner.remove();
                busy = false;
                sendBtn.disabled = false;
                setStatus('已连接', true);
                inputEl.focus();
            });
    }

    // ---------- 交互绑定 ----------
    function openPanel() {
        panel.classList.add('open');
        panel.setAttribute('aria-hidden', 'false');
        fab.classList.add('hidden');
        inputEl.focus();
        // 打开时才去换令牌，避免每次页面加载都打扰后端
        ensureToken().catch(function () { /* 状态已提示 */ });
    }

    function closePanel() {
        panel.classList.remove('open');
        panel.setAttribute('aria-hidden', 'true');
        fab.classList.remove('hidden');
    }

    fab.addEventListener('click', openPanel);
    document.getElementById('agentClose').addEventListener('click', closePanel);

    document.getElementById('agentReset').addEventListener('click', function () {
        conversationId = 'conv-' + Math.random().toString(36).slice(2, 10);
        actorToken = null;
        logEl.innerHTML = '<div class="agent-hint">已开启新会话，之前的上下文已清空。</div>';
        ensureToken().catch(function () { });
    });

    sendBtn.addEventListener('click', send);

    inputEl.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    });

    // 输入框自适应高度
    inputEl.addEventListener('input', function () {
        inputEl.style.height = 'auto';
        inputEl.style.height = Math.min(inputEl.scrollHeight, 96) + 'px';
    });
})();
