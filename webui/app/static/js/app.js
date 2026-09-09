/* Клиентская часть: автообновление дашборда, график, поток ответа в диалоге.
   Без сборщиков и фреймворков — плотная вёрстка в духе 1С в них не нуждается. */

'use strict';

function fmtNum(n) {
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

function setMeter(barId, value) {
    const bar = document.getElementById(barId);
    if (!bar) return;
    bar.style.width = Math.min(100, Math.max(0, value)) + '%';
    bar.classList.toggle('meter__fill--warn', value >= 75 && value < 90);
    bar.classList.toggle('meter__fill--err', value >= 90);
}

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

/* ── Дашборд ──────────────────────────────────────────────────────── */

function initDashboard(opts) {
    let timer = null;
    const auto = document.getElementById('auto');

    function paint(data) {
        const m = data.metrics;
        setText('cpu-val', m.cpu.percent);
        setMeter('cpu-bar', m.cpu.percent);
        setText('mem-val', m.memory.percent);
        setMeter('mem-bar', m.memory.percent);
        setText('mem-sub', m.memory.used_h + ' из ' + m.memory.total_h);
        setText('disk-val', m.disk.percent);
        setMeter('disk-bar', m.disk.percent);
        setText('disk-sub', m.disk.used_h + ' из ' + m.disk.total_h + ', свободно ' + m.disk.free_h);
        setText('load-val', m.load.one);
        setText('load-sub', m.load.five + ' / ' + m.load.fifteen + ' — на ядро ' + m.load.per_core);
        setText('net-sub', 'всего ↓ ' + m.net.rx_total_h + ' · ↑ ' + m.net.tx_total_h);
        setText('up-val', m.uptime.human);
        setText('proc-sub', 'процессов: ' + m.processes);

        const net = document.getElementById('net-val');
        if (net) net.innerHTML = '↓ ' + m.net.rx_rate_h + '<br>↑ ' + m.net.tx_rate_h;

        const u = data.usage;
        setText('u-today-cost', '$' + u.today.cost.toFixed(4));
        setText('u-today-req', u.today.requests);
        setText('u-today-in', fmtNum(u.today.input_tokens));
        setText('u-today-out', fmtNum(u.today.output_tokens));
        setText('u-today-cr', fmtNum(u.today.cache_read));
        setText('u-today-cw', fmtNum(u.today.cache_write));
        setText('u-month-cost', '$' + u.month.cost.toFixed(2));
        if (u.month.limit) {
            setText('u-month-share', u.month.share);
            setMeter('u-month-bar', u.month.share);
        }

        const stamp = new Date();
        setText('stamp', 'обновлено ' + stamp.toLocaleTimeString('ru-RU'));
    }

    async function tick() {
        try {
            const res = await fetch(opts.metricsUrl, { headers: { 'Accept': 'application/json' } });
            if (res.status === 401) { location.reload(); return; }
            paint(await res.json());
        } catch (e) {
            setText('stamp', 'нет связи с сервером');
        }
    }

    function schedule() {
        if (timer) clearInterval(timer);
        if (auto && auto.checked) timer = setInterval(tick, opts.intervalSec * 1000);
    }

    if (auto) auto.addEventListener('change', schedule);
    schedule();
    tick();
    drawHistory(opts.historyUrl);
}

/* График истории: рисуем сами на canvas, чтобы не тянуть библиотеку */
async function drawHistory(url) {
    const canvas = document.getElementById('chart');
    if (!canvas) return;
    const note = document.getElementById('chart-note');

    let points = [];
    try {
        const res = await fetch(url + '?hours=24');
        points = (await res.json()).points || [];
    } catch (e) {
        if (note) note.textContent = 'историю загрузить не удалось';
        return;
    }

    if (points.length < 2) {
        if (note) note.textContent = 'история копится — точки появятся по мере автообновления';
        return;
    }
    if (note) {
        note.textContent = 'точек: ' + points.length + ', с ' +
            new Date(points[0].at).toLocaleString('ru-RU');
    }

    const css = getComputedStyle(document.documentElement);
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 1200;
    const h = 130;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    const pad = { l: 30, r: 6, t: 6, b: 16 };
    const iw = w - pad.l - pad.r;
    const ih = h - pad.t - pad.b;

    // Сетка и подписи по оси значений
    ctx.strokeStyle = css.getPropertyValue('--line-soft').trim() || '#ddd';
    ctx.fillStyle = css.getPropertyValue('--ink-faint').trim() || '#888';
    ctx.font = '10px sans-serif';
    ctx.lineWidth = 1;
    [0, 25, 50, 75, 100].forEach(function (v) {
        const y = pad.t + ih - (v / 100) * ih;
        ctx.beginPath();
        ctx.moveTo(pad.l, y + 0.5);
        ctx.lineTo(w - pad.r, y + 0.5);
        ctx.stroke();
        ctx.fillText(v + '%', 4, y + 3);
    });

    function series(key, color) {
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        points.forEach(function (p, i) {
            const x = pad.l + (i / (points.length - 1)) * iw;
            const y = pad.t + ih - (Math.min(100, p[key]) / 100) * ih;
            i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
        });
        ctx.stroke();
    }

    series('cpu', css.getPropertyValue('--link').trim() || '#1f5c9e');
    series('mem', css.getPropertyValue('--accent-deep').trim() || '#b98a00');
}

/* ── Диалог ───────────────────────────────────────────────────────── */

function initConversation(opts) {
    const form = document.getElementById('send-form');
    const input = document.getElementById('text');
    const button = document.getElementById('send-btn');
    const scroll = document.getElementById('scroll');
    if (!form || !input || !scroll) return;

    const atBottom = () => scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 60;
    const toBottom = () => { scroll.scrollTop = scroll.scrollHeight; };
    toBottom();

    function addMessage(role, who, text) {
        const empty = scroll.querySelector('.empty');
        if (empty) empty.remove();
        const wrap = document.createElement('div');
        wrap.className = 'msg msg--' + role;
        const head = document.createElement('div');
        head.className = 'msg__head';
        head.innerHTML = '<span class="msg__who"></span><span></span>';
        head.children[0].textContent = who;
        head.children[1].textContent = new Date().toLocaleString('ru-RU',
            { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
        const body = document.createElement('div');
        body.className = 'msg__body';
        body.textContent = text;
        wrap.append(head, body);
        scroll.append(wrap);
        toBottom();
        return { wrap: wrap, body: body };
    }

    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            form.requestSubmit();
        }
    });

    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        const text = input.value.trim();
        if (!text) return;

        input.value = '';
        input.disabled = true;
        button.disabled = true;
        button.textContent = 'Отправлено…';

        addMessage('user', opts.who, text);
        const answer = addMessage('assistant', 'Claude', '');
        answer.body.innerHTML = '<span class="typing">думает</span>';
        let collected = '';

        try {
            const res = await fetch(form.dataset.url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams({ text: text })
            });
            if (!res.ok || !res.body) throw new Error('сервер ответил ' + res.status);

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const chunk = await reader.read();
                if (chunk.done) break;
                buffer += decoder.decode(chunk.value, { stream: true });

                let cut;
                while ((cut = buffer.indexOf('\n\n')) !== -1) {
                    const frame = buffer.slice(0, cut);
                    buffer = buffer.slice(cut + 2);
                    if (!frame.startsWith('data: ')) continue;

                    let event;
                    try { event = JSON.parse(frame.slice(6)); } catch (_) { continue; }
                    const stick = atBottom();

                    if (event.type === 'delta') {
                        collected += event.text;
                        answer.body.textContent = collected;
                    } else if (event.type === 'text' && !collected) {
                        collected = event.text;
                        answer.body.textContent = collected;
                    } else if (event.type === 'tool' && opts.showTools) {
                        const line = document.createElement('div');
                        line.className = 'toolline';
                        line.textContent = 'инструмент: ' + event.name;
                        answer.wrap.insertBefore(line, answer.body);
                    } else if (event.type === 'result') {
                        if (event.text) {
                            collected = event.text;
                            answer.body.textContent = collected;
                        }
                        const meta = document.createElement('div');
                        meta.className = 'msg__meta';
                        meta.textContent = (event.model || '—') +
                            ' · $' + Number(event.cost_usd || 0).toFixed(4) +
                            ' · ' + (event.input_tokens || 0) + '→' + (event.output_tokens || 0) + ' токенов' +
                            ' · ' + ((event.duration_ms || 0) / 1000).toFixed(1) + ' с';
                        answer.wrap.append(meta);
                    } else if (event.type === 'error') {
                        answer.wrap.className = 'msg msg--error';
                        answer.body.textContent = event.message;
                    } else if (event.type === 'title') {
                        document.title = event.title;
                        const active = document.querySelector('.sidebar__item--active');
                        if (active) active.childNodes[0].textContent = event.title + ' ';
                    }

                    if (stick) toBottom();
                }
            }

            if (!collected && answer.body.querySelector('.typing')) {
                answer.body.textContent = '(пустой ответ)';
            }
        } catch (err) {
            answer.wrap.className = 'msg msg--error';
            answer.body.textContent = 'Не удалось получить ответ: ' + err.message;
        } finally {
            input.disabled = false;
            button.disabled = false;
            button.textContent = 'Отправить';
            input.focus();
        }
    });
}
