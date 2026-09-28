/* Клиентская часть: автообновление дашборда, график, поток ответа в диалоге.
   Без сборщиков и фреймворков — плотная вёрстка в духе 1С в них не нуждается. */

'use strict';

function fmtNum(n) {
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

/* Крупные счёты токенов — в тысячах: «692 тыс.» читается, «692 118» — нет */
function fmtThousands(n) {
    return Math.max(1, Math.round(n / 1000)) + ' тыс.';
}

function setMeter(barId, value) {
    const bar = document.getElementById(barId);
    if (!bar) return;
    bar.style.width = Math.min(100, Math.max(0, value)) + '%';
    bar.classList.toggle('meter__fill--warn', value >= 75 && value < 90);
    bar.classList.toggle('meter__fill--err', value >= 90);
}

/* Время подписей — в поясе из настроек (data-tz на body). Сервер отдаёт
   моменты в UTC, а браузер без явного пояса показал бы их по часам той
   машины, где открыта страница. Пусто или пояс браузеру неизвестен —
   берётся пояс браузера, как было раньше. */
const TIME_OPTS = { hour: '2-digit', minute: '2-digit', second: '2-digit' };

function fmtDate(date, opts) {
    const tz = document.body ? document.body.dataset.tz : '';
    const o = Object.assign({}, opts || {});
    if (tz) o.timeZone = tz;
    try {
        return date.toLocaleString('ru-RU', o);
    } catch (err) {
        delete o.timeZone;              // RangeError: такого пояса браузер не знает
        return date.toLocaleString('ru-RU', o);
    }
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
        setText('stamp', 'обновлено ' + fmtDate(stamp, TIME_OPTS));
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
            fmtDate(new Date(points[0].at));
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
    let context = 0;               // размер контекста на последнем шаге
    let compacting = false;        // идёт сжатие: событий нет десятки секунд
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
        let text = (compacting ? '● сжимаю контекст ' : '● идёт ') + fmtElapsed(Date.now() - startedAt);
        if (steps) text += ' · шагов ' + steps;
        if (tokensOut()) text += ' · ↑ ' + fmtNum(tokensOut()) + ' токенов';
        if (context) text += ' · контекст ' + fmtThousands(context);
        say(text, 'live');
    }

    function addRow(name, target) {
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
        when.textContent = fmtDate(new Date(), TIME_OPTS);
        head.append(who, when);
        row.append(head);

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
    }

    return {
        start: function () {
            startedAt = Date.now();
            steps = 0;
            tokensDone = 0;
            tokensStep = 0;
            context = 0;
            compacting = false;
            const empty = log.querySelector('.empty');
            if (empty) empty.remove();
            live();
            if (ticker) clearInterval(ticker);
            ticker = setInterval(live, 1000);
        },

        step: function (name, input) {
            steps += 1;
            addRow(name, toolTarget(input));
            live();
        },

        /* Сжатие контекста — автоматическое у потолка или по кнопке */
        compact: function (event) {
            if (event.state === 'start') {
                compacting = true;
                addRow('Сжатие контекста', 'история заменяется сводкой');
            } else if (event.state === 'done') {
                compacting = false;
                context = event.post_tokens || 0;
                addRow(event.trigger === 'auto' ? 'Контекст сжат у потолка' : 'Контекст сжат',
                       'было ' + fmtThousands(event.pre_tokens || 0) +
                       ' → сводка ' + fmtThousands(event.post_tokens || 0));
            } else if (event.state === 'failed') {
                compacting = false;
                addRow('Сжатие не удалось', event.reason || '');
            }
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
            if (event.context_tokens) context = event.context_tokens;
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
            if (event.context_tokens || context) {
                parts.push('контекст ' + fmtThousands(event.context_tokens || context));
            }
            say(parts.join(' · '), 'done');
        },

        fail: function (message) {
            if (ticker) { clearInterval(ticker); ticker = null; }
            say('сбой · ' + message, 'err');
        },

        /* Итог с признаком ошибки — чаще всего исчерпанный лимит. Это не сбой и
           тем более не «готово»: работа стоит до обнуления окна, строка сервера
           уже говорит, до какого часа. */
        stop: function (message) {
            if (ticker) { clearInterval(ticker); ticker = null; }
            say(message, 'err');
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
    const compactBtn = document.getElementById('compact-btn');
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
        head.children[1].textContent = fmtDate(new Date(),
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
        if (compactBtn) compactBtn.disabled = locked;
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
                        } else if (event.type === 'compact') {
                            if (run) run.compact(event);
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
                            if (event.is_error) {
                                answer.wrap.className = 'msg msg--error';
                                if (run) run.stop(event.text || event.error_message || 'ответ оборван');
                                tellTopicState('work');
                            } else {
                                if (run) run.finish(event);
                                tellTopicState('done');
                            }
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

    // Сжатие идёт обычным запуском: за ним следим тем же ходом, что и за
    // ответом, итог приходит в ленту сообщением
    if (compactBtn && opts.compactUrl) {
        compactBtn.addEventListener('click', async function () {
            if (!confirm('Сжать контекст темы? История заменится сводкой: следующие шаги ' +
                         'станут дешевле, но подробности ранних сообщений модель забудет.')) return;
            lockInput(true);
            try {
                const res = await fetch(opts.compactUrl, { method: 'POST' });
                if (!res.ok) {
                    const payload = await res.json().catch(() => ({}));
                    throw new Error(payload.error || 'сервер ответил ' + res.status);
                }
            } catch (err) {
                const bad = addMessage('assistant', 'Claude', 'Не удалось сжать контекст: ' + err.message);
                bad.wrap.className = 'msg msg--error';
                lockInput(false);
                return;
            }
            follow(0, false);
        });
    }

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

/* ── Вкладки ──────────────────────────────────────────────────────── */

/* Вкладки по образцу WAI-ARIA: стрелки и Home/End переключают, Tab уходит
   в содержимое панели. Выбор помнится: загрузка файла перезагружает страницу,
   и без этого вкладка всякий раз сбрасывалась бы на первую. */
function initTabs(root, onShow) {
    const tabs = Array.from(root.querySelectorAll('[role="tab"]'));
    if (!tabs.length) return;
    const storeKey = 'tabs:' + (root.dataset.tabs || '');

    function select(tab, focus) {
        tabs.forEach(function (t) {
            const on = t === tab;
            t.setAttribute('aria-selected', on ? 'true' : 'false');
            t.tabIndex = on ? 0 : -1;      // в строку вкладок Tab попадает один раз
            const panel = document.getElementById(t.getAttribute('aria-controls'));
            if (panel) panel.hidden = !on;
        });
        if (focus) tab.focus();
        try { localStorage.setItem(storeKey, tab.id); } catch (err) { /* хранилище закрыто */ }
        if (onShow) onShow(tab.id);
    }

    tabs.forEach(function (tab, i) {
        tab.addEventListener('click', function () { select(tab, false); });
        tab.addEventListener('keydown', function (e) {
            let next = null;
            if (e.key === 'ArrowRight') next = tabs[(i + 1) % tabs.length];
            else if (e.key === 'ArrowLeft') next = tabs[(i - 1 + tabs.length) % tabs.length];
            else if (e.key === 'Home') next = tabs[0];
            else if (e.key === 'End') next = tabs[tabs.length - 1];
            if (!next) return;
            e.preventDefault();
            select(next, true);
        });
    });

    let saved = null;
    try { saved = localStorage.getItem(storeKey); } catch (err) { /* хранилище закрыто */ }
    select(tabs.find(function (t) { return t.id === saved; }) || tabs[0], false);
}

/* ── Файлы проекта ────────────────────────────────────────────────── */

/* Вкладка «Файлы проекта»: список папки выдачи со скачиванием. Список
   забирается при первом показе вкладки, а не при открытии страницы: на вкладку
   «Загрузка» ходят чаще, и тянуть обход каталога впустую незачем. */
function initProjectFiles(opts) {
    const tablist = document.querySelector('[data-tabs="project-files"]');
    const rows = document.getElementById('files-rows');
    if (!tablist || !rows) return;

    const note = document.getElementById('files-note');
    const count = document.getElementById('files-count');
    const filter = document.getElementById('files-filter');

    let files = [];        // последний полученный список
    let loaded = false;    // список уже забран
    let loading = false;   // запрос в пути — второй не шлём
    let truncatedNote = '';

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
            const li = document.createElement('li');

            // Имя файла приходит с диска, поэтому только textContent:
            // innerHTML тут означал бы разметку из имени файла.
            const link = document.createElement('a');
            link.href = opts.downloadUrl + '?path=' + encodeURIComponent(file.path);
            link.textContent = file.path;
            link.title = 'Скачать ' + file.path;
            link.setAttribute('download', '');

            const meta = document.createElement('div');
            meta.className = 'faint';
            meta.textContent = fmtBytes(file.size) + ' · ' +
                fmtDate(new Date(file.mtime),
                    { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });

            li.append(link, meta);
            rows.append(li);
        }

        rows.hidden = shown.length === 0;
        count.textContent = (needle
            ? shown.length + ' из ' + files.length
            : files.length + ' файл.') + truncatedNote;
        if (shown.length === 0) {
            say(files.length
                ? 'Под фильтр ничего не подошло'
                : 'Папка выдачи пуста. Сюда складывается то, что просили сделать или выложить.');
        } else {
            say('');
        }
    }

    async function load() {
        if (loading) return;
        loading = true;
        // Уже показанный список не гасим на время запроса: при обновлении
        // по окончании ответа он мигал бы надписью «Загрузка…»
        if (!loaded) say('Загрузка…');
        try {
            const res = await fetch(opts.listUrl, { cache: 'no-store' });
            const payload = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(payload.error || 'сервер ответил ' + res.status);
            files = payload.files || [];
            loaded = true;
            // Путь берём с сервера: он завёл папку и знает её настоящее место
            const dir = document.getElementById('files-dir');
            if (dir && payload.dir) dir.textContent = payload.dir;
            // Список обрезан по пределу — сказать об этом обязательно:
            // молча показанная часть выглядит как весь каталог.
            truncatedNote = payload.truncated ? ' (свежие ' + payload.limit + ')' : '';
            render();
        } catch (err) {
            files = [];
            rows.replaceChildren();
            rows.hidden = true;
            count.textContent = '';
            say('Не удалось получить список: ' + err.message);
        } finally {
            loading = false;
        }
    }

    initTabs(tablist, function (tabId) {
        if (tabId === 'tab-tree' && !loaded) load();
    });

    document.getElementById('files-reload').addEventListener('click', load);
    filter.addEventListener('input', function () { if (loaded) render(); });

    // Ответ закончился — в папке выдачи могло появиться сделанное.
    // Список обновляется, только если его уже смотрели.
    document.addEventListener('topic-state', function (e) {
        if (e.detail.state === 'done' && loaded) load();
    });
}

/* ── Панель VPN ───────────────────────────────────────────────────── */

function initVpnPanel(opts) {
    // Трафик и время последней связи обновляются сами: страницу для этого
    // перезагружать не нужно, а числа иначе устаревают молча.
    const rows = new Map();
    document.querySelectorAll('#vpn-peers tr[data-peer]').forEach(function (tr) {
        rows.set(tr.dataset.peer, tr);
    });

    const rxTotal = document.getElementById('vpn-rx-total');
    const txTotal = document.getElementById('vpn-tx-total');

    function put(tr, role, text) {
        const cell = tr.querySelector('[data-role="' + role + '"]');
        // Только textContent: значения приходят с сервера, но разметкой им быть незачем
        if (cell && text != null) cell.textContent = text;
    }

    async function tick() {
        try {
            const res = await fetch(opts.stateUrl, { cache: 'no-store' });
            if (!res.ok) return;          // не пускают — перерисовывать нечем
            const data = await res.json();
            if (!data.ok) return;

            if (rxTotal && data.rx_total_text) rxTotal.textContent = data.rx_total_text;
            if (txTotal && data.tx_total_text) txTotal.textContent = data.tx_total_text;

            (data.peers || []).forEach(function (peer) {
                const tr = rows.get(peer.name);
                if (!tr) return;          // клиента завели в другой вкладке — увидим при перезагрузке
                put(tr, 'seen', peer.seen_text);
                put(tr, 'rx', peer.rx_text);
                put(tr, 'tx', peer.tx_text);
                const dot = tr.querySelector('[data-role="dot"]');
                if (dot) {
                    dot.className = 'dot ' + (peer.online ? 'dot--done' : 'dot--empty');
                    dot.title = peer.online ? 'на связи' : 'связи нет';
                    dot.setAttribute('aria-label', dot.title);
                }
            });
        } catch (err) {
            /* связь моргнула — подтянется следующим опросом */
        }
    }

    setInterval(tick, Math.max(5, opts.intervalSec || 10) * 1000);
    tick();

    // Окно с QR-кодом. Картинка тянется по требованию: в ней закрытый ключ,
    // и держать её в разметке страницы для всех клиентов сразу незачем.
    const dialog = document.getElementById('vpn-qr-modal');
    if (!dialog) return;
    const img = document.getElementById('vpn-qr-img');
    const title = document.getElementById('vpn-qr-title');
    const closeBtn = document.getElementById('vpn-qr-close');

    document.querySelectorAll('[data-qr]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            img.src = btn.dataset.qrUrl;
            title.textContent = 'QR-код: ' + btn.dataset.qr;
            dialog.showModal();
        });
    });
    if (closeBtn) closeBtn.addEventListener('click', function () { dialog.close(); });
    dialog.addEventListener('close', function () { img.removeAttribute('src'); });
    dialog.addEventListener('click', function (e) {
        if (e.target === dialog) dialog.close();
    });
}

function initSecPanel(opts) {
    // Прогон аудита идёт минутами, поэтому страница сама следит за его концом:
    // иначе остаётся гадать, закончился он или завис.
    const verdict = document.getElementById('sec-verdict');
    const running = document.getElementById('sec-running');
    const quar = document.getElementById('sec-quar');
    const buttons = document.querySelectorAll('form[action$="/sec/run"] button');
    let wasRunning = false;

    async function tick() {
        try {
            const res = await fetch(opts.stateUrl, { cache: 'no-store' });
            if (!res.ok) return;          // не пускают — перерисовывать нечем
            const data = await res.json();
            if (!data.ok) return;

            // Только textContent: значения приходят с сервера, но разметкой им быть незачем
            if (verdict) {
                verdict.textContent = data.verdict;
                verdict.className = 'tag ' + (data.alarm ? 'tag--warn' : 'tag--ok');
            }
            if (quar) quar.textContent = String(data.quarantine);
            if (running) running.hidden = !data.running;
            buttons.forEach(function (b) { b.disabled = !!data.running; });

            // Прогон закончился — перезагружаем страницу: в списке появился
            // новый отчёт, а дорисовывать его по кусочкам незачем. Без ?ok=:
            // иначе после конца прогона снова висело бы «Прогон запущен».
            if (wasRunning && !data.running) location.replace(location.pathname);
            wasRunning = !!data.running;
        } catch (err) {
            /* связь моргнула — подтянется следующим опросом */
        }
    }

    setInterval(tick, Math.max(5, opts.intervalSec || 10) * 1000);
    tick();
}

/* ── Картинки: сетка превью и просмотрщик ─────────────────────────── */

/* Раздел устроен как файловый просмотрщик: слева дерево «проект → папка»,
   справа сетка превью, по нажатию — кадр во весь экран со стрелками,
   масштабом и лентой внизу.

   Список кадров строится один раз на весь каталог и дальше только
   отбирается и сортируется на месте: сотня превью — это сотня запросов
   за картинками, и гонять за ними ещё и разметку незачем. */

const PIC_SIZES = [120, 170, 240, 330];    /* ползунок «размер», px */
const PIC_ZOOM_MIN = 0.05;
const PIC_ZOOM_MAX = 8;
const PIC_ZOOM_STEP = 1.25;

function picRemember(key, value) {
    try { localStorage.setItem('pictures:' + key, value); } catch (err) { /* хранилище закрыто */ }
}

function picRecall(key, fallback) {
    try {
        const saved = localStorage.getItem('pictures:' + key);
        return saved === null ? fallback : saved;
    } catch (err) {
        return fallback;
    }
}

function initPictures(opts) {
    const tree = document.getElementById('pic-tree');
    const grid = document.getElementById('pic-grid');
    if (!tree || !grid) return;

    const title = document.getElementById('pic-title');
    const count = document.getElementById('pic-count');
    const where = document.getElementById('pic-where');
    const note = document.getElementById('pic-note');
    const search = document.getElementById('pic-search');
    const sortBox = document.getElementById('pic-sort');
    const sizeBox = document.getElementById('pic-size');

    let groups = [];          // каталог как пришёл с сервера
    let shown = [];           // что сейчас в сетке — по нему же ходит просмотрщик
    let pick = picRecall('pick', '');          // «ключ группы\tпапка», пусто — всё
    const folded = new Set((picRecall('folded', '') || '').split('\t').filter(Boolean));

    function say(text) {
        note.textContent = text || '';
        note.hidden = !text;
    }

    /* ── Отбор и порядок ──────────────────────────────────────────── */

    function everything() {
        const all = [];
        for (const group of groups) {
            for (const folder of group.folders) {
                for (const image of folder.images) all.push(image);
            }
        }
        return all;
    }

    function selected() {
        if (!pick) return { items: everything(), title: 'Все картинки', dir: '' };
        const [groupKey, folderPath] = pick.split('\t');
        const group = groups.find(g => g.key === groupKey);
        if (!group) return { items: everything(), title: 'Все картинки', dir: '' };
        if (folderPath === undefined || folderPath === null || folderPath === '*') {
            const items = [];
            group.folders.forEach(f => items.push(...f.images));
            return { items: items, title: group.name, dir: group.dir };
        }
        const folder = group.folders.find(f => f.path === folderPath);
        if (!folder) return { items: [], title: group.name, dir: group.dir };
        return {
            items: folder.images.slice(),
            title: group.name + ' · ' + folder.title,
            dir: folder.path && folder.path[0] !== ':' ? group.dir + '/' + folder.path : group.dir
        };
    }

    function ordered(items) {
        const how = sortBox.value;
        const list = items.slice();
        if (how === 'name') {
            list.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
        } else if (how === 'old') {
            list.sort((a, b) => a.mtime.localeCompare(b.mtime));
        } else if (how === 'big') {
            list.sort((a, b) => b.size - a.size);
        } else {
            list.sort((a, b) => b.mtime.localeCompare(a.mtime));
        }
        return list;
    }

    /* ── Дерево слева ─────────────────────────────────────────────── */

    function node(kind, label, badge, key, current) {
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'pic-node pic-node--' + kind + (current ? ' is-current' : '');
        const name = document.createElement('span');
        name.textContent = label;                  // имя с диска — только текстом
        const num = document.createElement('span');
        num.className = 'pic-node__count';
        num.textContent = badge;
        row.append(name, num);
        row.addEventListener('click', function () {
            pick = key;
            picRemember('pick', key);
            drawTree();
            draw();
            grid.scrollTop = 0;
        });
        return row;
    }

    function drawTree() {
        tree.replaceChildren();
        let total = 0;
        groups.forEach(g => { total += g.count; });
        tree.append(node('all', 'Все картинки', String(total), '', !pick));

        for (const group of groups) {
            const key = group.key + '\t*';
            const row = node('group', group.name, String(group.count), key, pick === key);

            // Треугольник свёртки — своей кнопкой внутри строки: у проекта
            // бывает десяток папок, и развёрнутыми все они прячут остальные
            const fold = document.createElement('button');
            fold.type = 'button';
            fold.className = 'pic-node__fold';
            fold.textContent = folded.has(group.key) ? '▸' : '▾';
            fold.title = folded.has(group.key) ? 'Развернуть' : 'Свернуть';
            fold.addEventListener('click', function (e) {
                e.stopPropagation();               // свёртка — не выбор папки
                if (folded.has(group.key)) folded.delete(group.key); else folded.add(group.key);
                picRemember('folded', Array.from(folded).join('\t'));
                drawTree();
            });
            row.prepend(fold);
            tree.append(row);

            if (folded.has(group.key)) continue;
            for (const folder of group.folders) {
                const fkey = group.key + '\t' + folder.path;
                tree.append(node('folder', folder.title, String(folder.count), fkey, pick === fkey));
            }
        }
    }

    /* ── Сетка ────────────────────────────────────────────────────── */

    function tile(image, withPath) {
        const cell = document.createElement('button');
        cell.type = 'button';
        cell.className = 'pic-tile';
        cell.title = image.name;

        const frame = document.createElement('div');
        frame.className = 'pic-tile__frame';
        const img = document.createElement('img');
        img.loading = 'lazy';                      // сотня кадров разом не грузится
        img.decoding = 'async';
        img.alt = image.name;
        img.src = opts.thumbUrl + '?src=' + encodeURIComponent(image.src);
        img.addEventListener('error', function () {
            // Битый файл или формат не по зубам: пустая плитка выглядела бы
            // как ещё не загруженная
            const stub = document.createElement('span');
            stub.className = 'faint';
            stub.textContent = 'превью нет';
            frame.replaceChildren(stub);
        });
        frame.append(img);

        if (withPath) {
            const place = document.createElement('div');
            place.className = 'pic-tile__where';
            place.textContent = picPlace(image.src);
            cell.append(frame, place);
        } else {
            cell.append(frame);
        }

        const name = document.createElement('div');
        name.className = 'pic-tile__name';
        name.textContent = image.name;

        const meta = document.createElement('div');
        meta.className = 'pic-tile__meta';
        meta.textContent = (image.w ? image.w + '×' + image.h + ' · ' : '') +
            fmtBytes(image.size) + ' · ' +
            fmtDate(new Date(image.mtime), { day: '2-digit', month: '2-digit', year: '2-digit' });

        cell.append(name, meta);
        cell.addEventListener('click', function () { open(shown.indexOf(image)); });
        return cell;
    }

    /* Где лежит кадр — «проект · папка». В общем списке без этого непонятно,
       откуда картинка. Считается один раз на каталог: перебором по всем
       папкам на каждую плитку сетка из тысячи кадров заметно тормозила бы. */
    const places = new Map();

    function mapPlaces() {
        places.clear();
        for (const group of groups) {
            for (const folder of group.folders) {
                const place = group.name + (folder.path ? ' · ' + folder.title : '');
                for (const image of folder.images) places.set(image.src, place);
            }
        }
    }

    function picPlace(src) {
        return places.get(src) || '';
    }

    function draw() {
        const chosen = selected();
        const needle = search.value.trim().toLowerCase();
        let items = chosen.items;
        if (needle) items = items.filter(i => i.name.toLowerCase().indexOf(needle) !== -1);
        shown = ordered(items);

        title.textContent = chosen.title;
        where.textContent = chosen.dir || '';
        count.textContent = needle
            ? shown.length + ' из ' + chosen.items.length
            : shown.length + ' шт.';

        const withPath = !pick || pick.endsWith('\t*');
        grid.replaceChildren();
        for (const image of shown) grid.append(tile(image, withPath));

        if (!shown.length) {
            const empty = document.createElement('div');
            empty.className = 'empty';
            empty.style.gridColumn = '1 / -1';
            empty.textContent = needle
                ? 'Под поиск ничего не подошло'
                : 'Картинок тут нет';
            grid.append(empty);
        }
    }

    /* ── Просмотрщик ──────────────────────────────────────────────── */

    const viewer = document.getElementById('pic-viewer');
    const stage = document.getElementById('v-stage');
    const canvas = document.getElementById('v-canvas');
    const big = document.getElementById('v-img');
    const strip = document.getElementById('v-strip');
    const vName = document.getElementById('v-name');
    const vWhere = document.getElementById('v-where');
    const vInfo = document.getElementById('v-info');
    const vZoom = document.getElementById('v-zoom');
    const vFit = document.getElementById('v-fit');
    const vDownload = document.getElementById('v-download');
    const prevBtn = document.getElementById('v-prev');
    const nextBtn = document.getElementById('v-next');

    let at = -1;            // место в `shown`
    let scale = 1;          // 0 — вписать в окно
    let fit = true;

    function zoomText() {
        if (fit) {
            const real = big.naturalWidth ? big.clientWidth / big.naturalWidth : 1;
            vZoom.textContent = Math.round(real * 100) + ' %';
        } else {
            vZoom.textContent = Math.round(scale * 100) + ' %';
        }
        vFit.textContent = fit ? '1:1' : 'Вписать';
        vFit.title = fit ? 'Показать 1:1 (1)' : 'Вписать в окно (0)';
    }

    function applyZoom() {
        if (fit) {
            // Вписать: размер отдан браузеру, полотно ровно в окно —
            // иначе `max-height` картинки считался бы от растущего полотна
            big.style.width = '';
            big.style.height = '';
            big.style.maxWidth = '100%';
            big.style.maxHeight = '100%';
            canvas.classList.remove('viewer__canvas--zoom');
            stage.classList.remove('viewer__stage--grab');
        } else {
            big.style.maxWidth = 'none';
            big.style.maxHeight = 'none';
            big.style.width = Math.round(big.naturalWidth * scale) + 'px';
            big.style.height = 'auto';
            canvas.classList.add('viewer__canvas--zoom');
            stage.classList.add('viewer__stage--grab');
        }
        zoomText();
    }

    function setScale(next, keepCentre) {
        const before = { x: stage.scrollLeft + stage.clientWidth / 2,
                         y: stage.scrollTop + stage.clientHeight / 2 };
        const was = fit ? (big.clientWidth / (big.naturalWidth || 1)) : scale;
        scale = Math.min(PIC_ZOOM_MAX, Math.max(PIC_ZOOM_MIN, next));
        fit = false;
        applyZoom();
        if (keepCentre && was) {
            // Середина кадра остаётся серединой: иначе после «+» смотришь
            // в левый верхний угол вместо того места, куда смотрела
            const k = scale / was;
            stage.scrollLeft = before.x * k - stage.clientWidth / 2;
            stage.scrollTop = before.y * k - stage.clientHeight / 2;
        }
    }

    function fitAll() {
        fit = true;
        applyZoom();
    }

    function drawStrip() {
        strip.replaceChildren();
        shown.forEach(function (image, i) {
            const thumb = document.createElement('img');
            thumb.loading = 'lazy';
            thumb.alt = image.name;
            thumb.title = image.name;
            thumb.src = opts.thumbUrl + '?src=' + encodeURIComponent(image.src);
            if (i === at) thumb.className = 'is-current';
            thumb.addEventListener('click', function () { go(i); });
            strip.append(thumb);
        });
    }

    function markStrip() {
        Array.from(strip.children).forEach(function (el, i) {
            el.classList.toggle('is-current', i === at);
            if (i === at) el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        });
    }

    /* Соседние кадры подгружаются заранее: со стрелкой в руке пауза на
       загрузку заметнее всего */
    function preload(i) {
        [i - 1, i + 1].forEach(function (j) {
            const image = shown[j];
            if (!image) return;
            const ghost = new Image();
            ghost.src = opts.viewUrl + '?src=' + encodeURIComponent(image.src);
        });
    }

    function go(i) {
        if (i < 0 || i >= shown.length) return;
        at = i;
        const image = shown[i];
        big.src = opts.viewUrl + '?src=' + encodeURIComponent(image.src);
        big.alt = image.name;
        vName.textContent = image.name;
        vWhere.textContent = picPlace(image.src);
        vInfo.textContent = (i + 1) + ' из ' + shown.length + ' · ' +
            (image.w ? image.w + '×' + image.h + ' · ' : '') + fmtBytes(image.size) + ' · ' +
            fmtDate(new Date(image.mtime), { day: '2-digit', month: '2-digit', year: 'numeric',
                                             hour: '2-digit', minute: '2-digit' });
        vDownload.href = opts.fileUrl + '?src=' + encodeURIComponent(image.src);
        prevBtn.disabled = i === 0;
        nextBtn.disabled = i === shown.length - 1;
        fitAll();
        markStrip();
        preload(i);
    }

    function open(i) {
        if (i < 0 || !shown.length) return;
        at = i;
        drawStrip();
        if (!viewer.open) viewer.showModal();
        go(i);
    }

    big.addEventListener('load', zoomText);

    prevBtn.addEventListener('click', function () { go(at - 1); });
    nextBtn.addEventListener('click', function () { go(at + 1); });
    document.getElementById('v-close').addEventListener('click', function () { viewer.close(); });
    document.getElementById('v-zoom-in').addEventListener('click', function () {
        setScale((fit ? big.clientWidth / (big.naturalWidth || 1) : scale) * PIC_ZOOM_STEP, true);
    });
    document.getElementById('v-zoom-out').addEventListener('click', function () {
        setScale((fit ? big.clientWidth / (big.naturalWidth || 1) : scale) / PIC_ZOOM_STEP, true);
    });
    vFit.addEventListener('click', function () { if (fit) setScale(1, false); else fitAll(); });

    document.getElementById('v-full').addEventListener('click', function () {
        if (document.fullscreenElement) document.exitFullscreen();
        else if (viewer.requestFullscreen) viewer.requestFullscreen();
    });

    /* Колесо: кадр вписан — листаем, как в ACDSee; увеличен — крутим полотно */
    stage.addEventListener('wheel', function (e) {
        if (e.ctrlKey) {
            e.preventDefault();
            setScale((fit ? big.clientWidth / (big.naturalWidth || 1) : scale) *
                (e.deltaY < 0 ? PIC_ZOOM_STEP : 1 / PIC_ZOOM_STEP), true);
            return;
        }
        if (fit) {
            e.preventDefault();
            go(at + (e.deltaY > 0 ? 1 : -1));
        }
    }, { passive: false });

    /* Перетаскивание увеличенного кадра */
    let drag = null;
    stage.addEventListener('pointerdown', function (e) {
        if (fit || e.button !== 0) return;
        drag = { x: e.clientX, y: e.clientY, left: stage.scrollLeft, top: stage.scrollTop };
        stage.setPointerCapture(e.pointerId);
        stage.classList.add('viewer__stage--grabbing');
    });
    stage.addEventListener('pointermove', function (e) {
        if (!drag) return;
        stage.scrollLeft = drag.left - (e.clientX - drag.x);
        stage.scrollTop = drag.top - (e.clientY - drag.y);
    });
    ['pointerup', 'pointercancel'].forEach(function (name) {
        stage.addEventListener(name, function () {
            drag = null;
            stage.classList.remove('viewer__stage--grabbing');
        });
    });

    /* Клавиши как в просмотрщике: стрелки листают, Esc закрывает (это делает
       сам <dialog>), 0 вписывает, 1 даёт 1:1, +/− меняют масштаб */
    viewer.addEventListener('keydown', function (e) {
        if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') {
            e.preventDefault(); go(at + 1);
        } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
            e.preventDefault(); go(at - 1);
        } else if (e.key === 'Home') {
            e.preventDefault(); go(0);
        } else if (e.key === 'End') {
            e.preventDefault(); go(shown.length - 1);
        } else if (e.key === '+' || e.key === '=') {
            e.preventDefault();
            setScale((fit ? big.clientWidth / (big.naturalWidth || 1) : scale) * PIC_ZOOM_STEP, true);
        } else if (e.key === '-') {
            e.preventDefault();
            setScale((fit ? big.clientWidth / (big.naturalWidth || 1) : scale) / PIC_ZOOM_STEP, true);
        } else if (e.key === '0') {
            e.preventDefault(); fitAll();
        } else if (e.key === '1') {
            e.preventDefault(); setScale(1, false);
        } else if (e.key === 'f' || e.key === 'F' || e.key === 'а' || e.key === 'А') {
            e.preventDefault();
            if (document.fullscreenElement) document.exitFullscreen();
            else if (viewer.requestFullscreen) viewer.requestFullscreen();
        }
    });

    viewer.addEventListener('close', function () {
        big.removeAttribute('src');      // крупный кадр в памяти держать незачем
        if (document.fullscreenElement) document.exitFullscreen();
    });

    /* ── Загрузка каталога ────────────────────────────────────────── */

    async function load() {
        say('');
        try {
            const res = await fetch(opts.listUrl, { cache: 'no-store' });
            const payload = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(payload.error || 'сервер ответил ' + res.status);
            groups = payload.groups || [];
            mapPlaces();
            if (payload.truncated) {
                say('Показаны первые ' + payload.limit + ' картинок — дальше список обрезан.');
            }
            drawTree();
            draw();
        } catch (err) {
            tree.replaceChildren();
            grid.replaceChildren();
            say('Не удалось получить список картинок: ' + err.message);
        }
    }

    /* ── Панель управления ────────────────────────────────────────── */

    function setSize(step) {
        const px = PIC_SIZES[Math.min(PIC_SIZES.length - 1, Math.max(0, Number(step)))];
        grid.style.setProperty('--thumb', px + 'px');
        picRemember('size', step);
    }

    sizeBox.value = picRecall('size', '1');
    setSize(sizeBox.value);
    sizeBox.addEventListener('input', function () { setSize(sizeBox.value); });

    sortBox.value = picRecall('sort', 'new');
    sortBox.addEventListener('change', function () {
        picRemember('sort', sortBox.value);
        draw();
    });

    search.addEventListener('input', draw);
    document.getElementById('pic-reload').addEventListener('click', load);

    load();
}
