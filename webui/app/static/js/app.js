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
        setText('u-today-req', u.today.requests);
        setText('u-today-in', fmtNum(u.today.input_tokens));
        setText('u-today-out', fmtNum(u.today.output_tokens));
        setText('u-today-cr', fmtNum(u.today.cache_read));
        setText('u-today-cw', fmtNum(u.today.cache_write));

        // Окна тарифного плана. Мера и остаток обновляются только когда предел
        // задан: иначе на странице их просто нет, и писать некуда.
        [['u-w5', u.window_5h], ['u-week', u.window_week]].forEach(function (pair) {
            const id = pair[0], w = pair[1];
            setText(id + '-tokens', fmtNum(w.tokens));
            setText(id + '-req', w.requests);
            setText(id + '-in', fmtNum(w.input_tokens));
            setText(id + '-out', fmtNum(w.output_tokens));
            setText(id + '-cr', fmtNum(w.cache_read));
            setText(id + '-resets', w.idle ? 'запросов не было' : 'обнулится через ' + w.resets_in);
            if (w.limit) {
                setText(id + '-share', w.share);
                setText(id + '-left', fmtNum(w.left));
                setMeter(id + '-bar', w.share);
            }
        });

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

/* ── Ход работы ───────────────────────────────────────────────────── */

/* Продолжительность в виде 1:23 или 1:02:03 — секунды в таймере нужны всегда,
   иначе непонятно, идёт процесс или замер. */
function fmtElapsed(ms) {
    const total = Math.max(0, Math.round(ms / 1000));
    const s = String(total % 60).padStart(2, '0');
    const m = Math.floor(total / 60) % 60;
    const h = Math.floor(total / 3600);
    return h ? h + ':' + String(m).padStart(2, '0') + ':' + s : m + ':' + s;
}

/* Из аргументов инструмента вытаскиваем то единственное, что стоит показать
   в узкой колонке: команду, путь, образец поиска. */
function toolTarget(input) {
    if (!input || typeof input !== 'object') return '';
    const key = ['command', 'file_path', 'pattern', 'url', 'query', 'path', 'description']
        .find(function (k) { return typeof input[k] === 'string' && input[k]; });
    return key ? input[key] : '';
}

/* Панель промежуточных действий. Команды и инструменты идут сюда, а не в ленту
   сообщений — там остаётся только разговор. Панели может не быть (чатики):
   тогда возвращаем null, и вызывающая сторона просто ничего не показывает. */
function createRunPanel() {
    const log = document.getElementById('run-log');
    const stat = document.getElementById('run-stat');
    if (!log || !stat) return null;

    const MAX_ROWS = 200;          // хвост важнее начала: старое вытесняем
    let startedAt = 0;
    let steps = 0;
    let tokensDone = 0;            // выход завершённых шагов
    let tokensStep = 0;            // выход текущего шага, значение накопительное
    let ticker = null;

    const atBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    const toBottom = () => { log.scrollTop = log.scrollHeight; };

    function say(text, mod) {
        stat.textContent = text;
        stat.className = 'runstat' + (mod ? ' runstat--' + mod : '');
    }

    function tokensOut() {
        return tokensDone + tokensStep;
    }

    function live() {
        let text = '● идёт ' + fmtElapsed(Date.now() - startedAt);
        if (steps) text += ' · шагов ' + steps;
        if (tokensOut()) text += ' · ↑ ' + fmtNum(tokensOut()) + ' токенов';
        say(text, 'live');
    }

    return {
        start: function () {
            startedAt = Date.now();
            steps = 0;
            tokensDone = 0;
            tokensStep = 0;
            const empty = log.querySelector('.empty');
            if (empty) empty.remove();
            live();
            if (ticker) clearInterval(ticker);
            ticker = setInterval(live, 1000);
        },

        step: function (name, input) {
            steps += 1;
            const stick = atBottom();
            const row = document.createElement('div');
            row.className = 'runrow';

            const head = document.createElement('div');
            head.className = 'runrow__head';
            const who = document.createElement('span');
            who.className = 'runrow__name';
            who.textContent = name;
            const when = document.createElement('span');
            when.className = 'runrow__time';
            when.textContent = new Date().toLocaleTimeString('ru-RU');
            head.append(who, when);
            row.append(head);

            const target = toolTarget(input);
            if (target) {
                const what = document.createElement('div');
                what.className = 'runrow__what';
                what.textContent = target;
                what.title = target;          // в колонке помещается не всё
                row.append(what);
            }

            log.append(row);
            while (log.children.length > MAX_ROWS) log.removeChild(log.firstChild);
            if (stick) toBottom();
            live();
        },

        /* Расход приходит по ходу ответа: в пределах шага значение накопительное,
           на новом шаге счёт начинается заново — потому и две переменные. */
        usage: function (event) {
            if (event.new_message) {
                tokensDone += tokensStep;
                tokensStep = 0;
            }
            if (typeof event.output_tokens === 'number') {
                tokensStep = event.output_tokens;
            }
            live();
        },

        finish: function (event) {
            if (ticker) { clearInterval(ticker); ticker = null; }
            const parts = ['готово за ' + fmtElapsed(event.duration_ms || (Date.now() - startedAt))];
            if (steps) parts.push('шагов ' + steps);
            if (event.cost_usd) parts.push('$' + Number(event.cost_usd).toFixed(4));
            if (event.input_tokens || event.output_tokens) {
                parts.push(fmtNum(event.input_tokens || 0) + '→' +
                           fmtNum(event.output_tokens || 0) + ' токенов');
            }
            say(parts.join(' · '), 'done');
        },

        fail: function (message) {
            if (ticker) { clearInterval(ticker); ticker = null; }
            say('сбой · ' + message, 'err');
        },

        clear: function () {
            log.textContent = '';
            const empty = document.createElement('div');
            empty.className = 'empty';
            empty.textContent = 'Здесь появятся команды и обращения к файлам';
            log.append(empty);
        },
    };
}

/* ── Кружки состояния тем ─────────────────────────────────────────── */

const TOPIC_STATE_TITLE = {
    work: 'есть незавершённое',
    done: 'всё выполнено',
    empty: 'сообщений нет',
};

/* Перечень тем: кружок у каждой темы. Состояние берётся с сервера опросом —
   ответ в соседней теме идёт фоном, и её кружок должен позеленеть сам,
   без перезагрузки страницы. */
function initTopicDots(opts) {
    const dots = new Map();
    document.querySelectorAll('[data-topic-dot]').forEach(function (el) {
        dots.set(String(el.dataset.topicDot), el);
    });
    if (!dots.size) return;

    function paint(id, state, title) {
        const el = dots.get(String(id));
        if (!el || !TOPIC_STATE_TITLE[state]) return;
        el.className = 'dot dot--' + state;
        el.title = title || TOPIC_STATE_TITLE[state];
        el.setAttribute('aria-label', el.title);
    }

    async function tick() {
        try {
            const res = await fetch(opts.stateUrl, { cache: 'no-store' });
            if (!res.ok) return;              // не пускают — перерисовывать нечем
            const data = await res.json();
            const topics = data.topics || {};
            Object.keys(topics).forEach(function (id) {
                paint(id, topics[id].state, topics[id].title);
            });
        } catch (err) {
            /* связь моргнула — состояние подтянется следующим опросом */
        }
    }

    document.addEventListener('topic-state', function (e) {
        paint(e.detail.topicId, e.detail.state);
    });

    setInterval(tick, Math.max(5, opts.intervalSec || 10) * 1000);
    tick();
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

    const run = createRunPanel();
    const clearBtn = document.getElementById('run-clear');
    if (run && clearBtn) clearBtn.addEventListener('click', run.clear);

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

    // Показ ответа отвязан от отправки. Работа идёт в приложении и о браузере
    // не знает, страница только читает события с нужной позиции. Поэтому один
    // и тот же ход годится и для только что заданного вопроса, и для возврата
    // на страницу, где ответ уже идёт.
    let following = false;

    /* Кружок открытой темы перекрашивается сразу: здесь о начале и конце ответа
       известно раньше, чем о нём скажет опрос перечня тем. */
    function tellTopicState(state) {
        if (!opts.topicId) return;
        document.dispatchEvent(new CustomEvent('topic-state', {
            detail: { topicId: opts.topicId, state: state },
        }));
    }

    function lockInput(locked) {
        input.disabled = locked;
        button.disabled = locked;
        button.textContent = locked ? 'Отправлено…' : 'Отправить';
        if (!locked) input.focus();
    }

    async function follow(from, onlyActive) {
        if (following) return;
        following = true;

        let answer = null;
        let collected = '';
        let waitTicker = null;
        let index = from;
        let finished = false;
        let attempt = 0;
        const startedAt = Date.now();

        // Пузырь ответа заводится не сразу: при открытии страницы может
        // оказаться, что отвечать нечего, и пустой пузырь был бы враньём.
        function ensureAnswer() {
            if (answer) return;
            answer = addMessage('assistant', 'Claude', '');
            answer.body.innerHTML = '<span class="typing">думает</span>';
            waitTicker = setInterval(function () {
                const typing = answer.body.querySelector('.typing');
                if (typing) typing.textContent = 'думает ' + fmtElapsed(Date.now() - startedAt);
            }, 1000);
            if (run) run.start();
            lockInput(true);
            tellTopicState('work');
        }

        try {
            while (!finished && attempt < 120) {
                attempt += 1;
                let res;
                try {
                    res = await fetch(opts.streamUrl + '?start=' + index +
                                      (onlyActive ? '&active=1' : ''), { cache: 'no-store' });
                } catch (netErr) {
                    // Сеть моргнула — работа в приложении идёт своим ходом,
                    // поэтому просто подключаемся заново с той же позиции
                    await new Promise(r => setTimeout(r, 1000));
                    continue;
                }
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

                        if (event.type === 'idle') { finished = true; break; }
                        if (event.type === 'done') { finished = true; break; }

                        // Позиция запоминается до разбора: по ней подключаемся
                        // заново, не пересчитывая уже показанное
                        index += 1;
                        const stick = atBottom();
                        ensureAnswer();

                        if (event.type === 'delta') {
                            collected += event.text;
                            answer.body.textContent = collected;
                        } else if (event.type === 'text' && !collected) {
                            collected = event.text;
                            answer.body.textContent = collected;
                        } else if (event.type === 'tool' && opts.showTools) {
                            // Промежуточные действия — в свою панель; лента остаётся
                            // разговором. Панели нет — показываем строкой, как раньше.
                            if (run) {
                                run.step(event.name, event.input);
                            } else {
                                const line = document.createElement('div');
                                line.className = 'toolline';
                                line.textContent = 'инструмент: ' + event.name;
                                answer.wrap.insertBefore(line, answer.body);
                            }
                        } else if (event.type === 'usage') {
                            if (run) run.usage(event);
                        } else if (event.type === 'result') {
                            if (event.text) {
                                collected = event.text;
                                answer.body.textContent = collected;
                            }
                            const meta = document.createElement('div');
                            meta.className = 'msg__meta';
                            meta.textContent = (event.model || '—') +
                                ' · ' + (event.input_tokens || 0) + '→' + (event.output_tokens || 0) + ' токенов' +
                                ' · ' + ((event.duration_ms || 0) / 1000).toFixed(1) + ' с';
                            answer.wrap.append(meta);
                            if (run) run.finish(event);
                            tellTopicState('done');
                        } else if (event.type === 'error') {
                            answer.wrap.className = 'msg msg--error';
                            answer.body.textContent = event.message;
                            if (run) run.fail(event.message);
                            tellTopicState('work');     // оборванное — незакрытое
                        } else if (event.type === 'title') {
                            document.title = event.title;
                            const active = document.querySelector('.sidebar__item--active');
                            if (active) active.childNodes[0].textContent = event.title + ' ';
                        }

                        if (stick) toBottom();
                    }
                    if (finished) break;
                }
            }

            if (answer && !collected && answer.body.querySelector('.typing')) {
                answer.body.textContent = '(пустой ответ)';
            }
        } catch (err) {
            if (answer) {
                answer.wrap.className = 'msg msg--error';
                answer.body.textContent = 'Не удалось получить ответ: ' + err.message;
            }
            if (run) run.fail(err.message);
        } finally {
            following = false;
            clearInterval(waitTicker);
            if (answer) lockInput(false);
        }
    }

    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        const text = input.value.trim();
        if (!text) return;

        input.value = '';
        lockInput(true);
        addMessage('user', opts.who, text);

        try {
            const res = await fetch(form.dataset.url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams({ text: text })
            });
            if (!res.ok) {
                const payload = await res.json().catch(() => ({}));
                throw new Error(payload.error || 'сервер ответил ' + res.status);
            }
        } catch (err) {
            const bad = addMessage('assistant', 'Claude', 'Не удалось отправить: ' + err.message);
            bad.wrap.className = 'msg msg--error';
            lockInput(false);
            return;
        }

        follow(0, false);
    });

    // Ответ мог начаться до того, как эту страницу открыли: например, её
    // покинули посреди работы и вернулись. Тогда подхватываем с начала —
    // в базе его ещё нет, он сохраняется только по завершении.
    follow(0, true);
}

/* ── Перезапуск приложения ────────────────────────────────────────── */

function initRestart(opts) {
    const btn = document.getElementById('restart-btn');
    const label = document.getElementById('restart-state');
    if (!btn || !label) return;

    // Служба уже остановилась — дальше ждём не состояние, а её возвращение:
    // отвечать на запрос о состоянии некому, приложение и есть перезапускаемое
    let wentDown = false;

    function say(text) {
        label.textContent = text;
    }

    function later() {
        setTimeout(poll, 2000);
    }

    async function poll() {
        if (wentDown) {
            try {
                const res = await fetch(opts.healthUrl, { cache: 'no-store' });
                if (res.ok) {
                    say('Приложение поднялось, обновляю страницу');
                    location.reload();
                    return;
                }
            } catch (err) {
                /* ещё не поднялось — ждём дальше */
            }
            later();
            return;
        }

        try {
            const res = await fetch(opts.stateUrl, { cache: 'no-store' });
            if (!res.ok) throw new Error('нет ответа');
            const state = await res.json();
            if (state.pending) {
                say(state.waiting_for > 0
                    ? 'Ждём завершения ответов, осталось: ' + state.waiting_for
                    : 'Служба уходит на перезапуск');
                later();
            } else {
                btn.disabled = false;
                say(state.error ? 'Перезапуск не состоялся: ' + state.error : 'Служба работает');
            }
        } catch (err) {
            wentDown = true;
            say('Служба перезапускается');
            later();
        }
    }

    btn.addEventListener('click', async function () {
        if (!confirm('Перезапустить приложение? Оно будет недоступно несколько секунд.')) return;
        btn.disabled = true;
        say('Перезапуск запланирован');
        try {
            const res = await fetch(opts.requestUrl, { method: 'POST' });
            if (!res.ok) throw new Error('отказ');
        } catch (err) {
            btn.disabled = false;
            say('Не удалось запросить перезапуск');
            return;
        }
        poll();
    });

    if (opts.pending) {
        btn.disabled = true;
        poll();
    }
}

/* ── Папка выдачи проекта ─────────────────────────────────────────── */

function fmtBytes(n) {
    const units = ['Б', 'КБ', 'МБ', 'ГБ'];
    let value = n, unit = 0;
    while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
    return (unit === 0 ? value : value.toFixed(1)) + ' ' + units[unit];
}

function initProjectFiles(opts) {
    const dialog = document.getElementById('files-dialog');
    const openBtn = document.getElementById('files-open');
    if (!dialog || !openBtn) return;

    const rows = document.getElementById('files-rows');
    const table = document.getElementById('files-table');
    const note = document.getElementById('files-note');
    const count = document.getElementById('files-count');
    const filter = document.getElementById('files-filter');

    let files = [];       // последний полученный список
    let loaded = false;   // список уже забран — повторно при открытии не тянем

    function say(text) {
        note.textContent = text;
        note.hidden = !text;
    }

    function render() {
        const needle = filter.value.trim().toLowerCase();
        const shown = needle
            ? files.filter(f => f.path.toLowerCase().indexOf(needle) !== -1)
            : files;

        rows.replaceChildren();
        for (const file of shown) {
            const tr = document.createElement('tr');

            // Имя файла приходит с диска, поэтому только textContent:
            // innerHTML тут означал бы разметку из имени файла.
            const name = document.createElement('td');
            name.className = 'mono';
            name.textContent = file.path;
            name.title = file.path;

            const size = document.createElement('td');
            size.className = 'num';
            size.textContent = fmtBytes(file.size);

            const when = document.createElement('td');
            when.textContent = new Date(file.mtime).toLocaleString('ru-RU',
                { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });

            const act = document.createElement('td');
            const link = document.createElement('a');
            link.href = opts.downloadUrl + '?path=' + encodeURIComponent(file.path);
            link.textContent = 'скачать';
            link.setAttribute('download', '');
            act.append(link);

            tr.append(name, size, when, act);
            rows.append(tr);
        }

        table.hidden = shown.length === 0;
        count.textContent = needle
            ? shown.length + ' из ' + files.length
            : files.length + ' файл.';
        if (shown.length === 0) {
            say(files.length
                ? 'Под фильтр ничего не подошло'
                : 'Папка выдачи пуста. Сюда складывается то, что просили сделать или выложить.');
        } else {
            say('');
        }
    }

    async function load() {
        table.hidden = true;
        rows.replaceChildren();
        count.textContent = '';
        say('Загрузка…');
        try {
            const res = await fetch(opts.listUrl, { cache: 'no-store' });
            const payload = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(payload.error || 'сервер ответил ' + res.status);
            files = payload.files || [];
            loaded = true;
            // Путь берём с сервера: он завёл папку и знает её настоящее место
            const dir = document.getElementById('files-dir');
            if (dir && payload.dir) dir.textContent = payload.dir;
            render();
            // Список обрезан по пределу — сказать об этом обязательно:
            // молча показанная часть выглядит как весь каталог.
            if (payload.truncated) {
                count.textContent += ' (показаны свежие ' + payload.limit + ')';
            }
        } catch (err) {
            files = [];
            say('Не удалось получить список: ' + err.message);
        }
    }

    openBtn.addEventListener('click', function () {
        dialog.showModal();
        if (!loaded) load();
    });
    document.getElementById('files-close').addEventListener('click', () => dialog.close());
    document.getElementById('files-reload').addEventListener('click', load);
    filter.addEventListener('input', function () { if (loaded) render(); });

    // Щелчок мимо окошка закрывает его: само окно занимает не весь экран,
    // и промах по нему — обычное дело.
    dialog.addEventListener('click', function (e) {
        if (e.target === dialog) dialog.close();
    });
}
