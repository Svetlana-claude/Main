# `webclaude.md` — развёртывание веб-интерфейса к Claude Code с нуля

Документ для ИИ-агента. По нему на **пустом сервере** поднимается такой же пульт
к Claude Code, как в образце: вход по паролю и коду из приложения, дашборд,
чатики, проекты с темами, VPN, ночной аудит безопасности, настройки.
**Переносится устройство, а не данные:** база заводится пустой, темы, чатики,
расход и история метрик не переносятся, выгрузки базы образца не
восстанавливаются.

Образец: `https://mokeevasky.ru/Claude`, репозиторий `main/`, приложение в `webui/`.
Состояние описано на 15.09.2026.

Как читать:

* **Часть А** — что строится и почему так. Прочитать целиком до первой команды:
  большая часть решений принята после поломки, и без объяснений их легко
  «упростить» обратно.
* **Часть Б** — пошаговое развёртывание. Этапы идут строго по порядку, каждый
  заканчивается проверкой делом. Не прошла проверка — дальше не идти.
* **Часть В** — правила работы, проверки, грабли одним списком.

---

## 0. Прежде чем начать: что спросить у человека

Агент не угадывает эти значения, а спрашивает. В документе они записаны
заглушками.

| Заглушка | Что это | В образце |
|---|---|---|
| `<ПОЛЬЗОВАТЕЛЬ>` | учётка Linux, от которой работают служба и `claude` | `mokeeva` |
| `<ДОМЕН>` | имя сервера, A-запись должна указывать на `<IP>` | `mokeevasky.ru` |
| `<IP>` | внешний адрес сервера | — |
| `<ПОЧТА>` | почта для писем Let's Encrypt об истечении сертификата | — |
| `<ЛОГИН>` | логин входа в панель | `Svetlana` |
| `<ИМЯ>` | как подписывать реплики человека в ленте | `Светлана` |
| `<РЕПОЗИТОРИЙ>` | откуда брать код (git) | `git@github.com:…/Main.git` |
| `<ПОЯС>` | часовой пояс по умолчанию | `Europe/Moscow` |

**Шаги, которые делает только человек** (агент их готовит, объясняет и ждёт):

1. создание учётки и первый вход по SSH с паролем от хостера;
2. генерация SSH-ключа **на своём компьютере** и передача открытой части;
3. авторизация Claude Code по подписке (открыть ссылку в браузере, вставить код);
4. проверка входа по ключу из **второго** окна перед выключением пароля;
5. подключение второго фактора — сканирование QR-кода телефоном;
6. подтверждение файрвола после проверки доступа из второго окна.

Никогда не выводить в ответ и не класть в документы значения `SECRET_KEY`,
пароля базы, закрытых ключей WireGuard, секретов TOTP и паролей. В примерах —
только заглушки.

---

# Часть А. Что строится

## 1. Главное решение

Пульт к Claude Code через браузер: замена терминала для повседневной работы.

**Приложение не обращается к Messages API и не реализует инструменты заново.**
Оно запускает тот же `claude`, что работает в терминале, в неинтерактивном
режиме (`-p --output-format stream-json`) и разбирает поток JSON. Следствия:

* аутентификация — по подписке, API-ключ не нужен и не хранится;
* `CLAUDE.md`, скиллы и память подхватываются сами;
* лимиты — лимиты подписки (окна на 5 часов и неделю), а не деньги.

**Чатики и темы проектов работают на одном движке**, разница только в правах.
Одна таблица `conversations`, один драйвер, одна раскладка диалога — поиск,
экспорт и расход общие.

**Root приложению не выдаётся.** Всё, что требует root (VPN, файрвол, аудит),
делается через обёртки `webui-*` в `/usr/local/sbin` — root-владелец, закрытый
набор команд, доводы проверяются по образцу.

## 2. Разделы интерфейса

| Раздел | Адрес | Что делает |
|---|---|---|
| Дашборд | `/` | ресурсы сервера, график за сутки, расход токенов: окна 5 ч и неделя, сегодня, по разделам |
| Чатики | `/chats` | разговоры без инструментов |
| Проекты | `/projects` | темы с правкой файлов в каталоге проекта, «Ход работы», вкладки «Загрузка» / «Файлы проекта», сжатие контекста |
| VPN | `/vpn` | состояние WireGuard, клиенты, QR, выдача `.conf`, отзыв, трафик |
| Безопасность | `/sec` | сводка аудита, итог прогона, ручной прогон, эталон, отчёты |
| Настройки | `/settings` | модель, потолок контекста, пределы окон, тема, пояс, файлы сопровождения, перезапуск, второй фактор, сессии |
| Журнал | `/journal` | все сообщения подряд |
| Поиск | `/search` | полнотекстовый поиск по сообщениям |

## 3. Стек

| Слой | Выбор |
|---|---|
| ОС | Ubuntu 24.04 LTS |
| Веб-сервер | nginx 1.24: обратный прокси, TLS Let's Encrypt, ограничение частоты входа |
| Приложение | Python 3.12 + FastAPI 0.115, uvicorn под systemd |
| БД | PostgreSQL 16 |
| Шаблоны | Jinja2, серверная отрисовка |
| Клиент | ванильный JS без сборки, свой CSS на токенах (дизайн в духе 1С) |
| Движок | Claude Code CLI (`~/.local/bin/claude`) |
| VPN | WireGuard (`wg-quick@wg0`), `qrencode` |
| Защита | iptables default-deny + `netfilter-persistent`, fail2ban, unattended-upgrades |

`webui/requirements.txt`:

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
jinja2==3.1.5
python-multipart==0.0.20
psycopg[binary,pool]==3.2.3
argon2-cffi==23.1.0
itsdangerous==2.2.0
psutil==6.1.1
python-dotenv==1.0.1
markdown==3.7
```

**Чего сознательно нет:** Node.js и сборщиков, Docker, Redis, ORM, очереди задач,
pytest. При 2–4 ГБ RAM накладные расходы не окупаются; фоновая работа живёт
в задачах asyncio, запросов немного и голый SQL читается лучше. TOTP сделан
своей реализацией на `hmac` (RFC 6238) — зависимость ради 40 строк не нужна.

## 4. Структура

### Репозиторий

```
main/
├── CLAUDE.md              правила работы (раздел 22)
├── architect.md           архитектура
├── result.md              текущий ход работ
├── current_questions.md   открытые вопросы
├── tech_debt.md           технический долг
├── log.md                 журнал задач
├── .gitignore
├── exchange/              НЕ версионируется: обмен, бэкапы, конфиги VPN-клиентов
├── infra/                 уровень машины: sudo, обёртки, бэкапы, TLS, ключи
├── bezopasnost/           ночной аудит безопасности и файрвол
├── vpn-server/            установка WireGuard, выдача и отзыв клиентов
└── webui/                 веб-интерфейс
```

Каталог каждого проекта — это `projects.workdir`. У каждого есть папка
`downloads/` — её показывает вкладка «Файлы проекта» (раздел 12).

### `webui/`

```
webui/
├── app/
│   ├── main.py             точка входа, lifespan, фоновая уборка раз в час
│   ├── config.py           настройки из файла вне каталога проекта
│   ├── db.py               пул psycopg, применение схемы, засев
│   ├── security.py         argon2id, подписанные cookie, стойкость пароля
│   ├── deps.py             текущий пользователь, отрисовка, IP за прокси
│   ├── timefmt.py          часовой пояс: показ UTC в поясе из настроек
│   ├── schema.sql          схема, применяется идемпотентно при старте
│   ├── routers/            auth, totp, dashboard, chats, projects, vpn,
│   │                       security, settings, claude_login
│   ├── services/
│   │   ├── claude_driver.py драйвер Claude Code, потолок контекста, сжатие
│   │   ├── runs.py          фоновые запуски и SSE
│   │   ├── transcripts.py   расход по стенограммам ~/.claude/projects
│   │   ├── usage.py         окна тарифного плана
│   │   ├── restart.py       отложенный перезапуск
│   │   ├── metrics.py       метрики сервера
│   │   ├── totp.py          коды второго фактора, QR через qrencode
│   │   ├── claude_auth.py   вход Claude: состояние, `claude auth login` в псевдотерминале
│   │   ├── vpn.py           вызов обёртки webui-vpn и разбор вывода
│   │   └── security.py      состояние аудита, отчёты, ручной прогон
│   ├── templates/          base, login, login_totp, password, dashboard, chats,
│   │                       projects, vpn, security, security_report, settings,
│   │                       settings_totp, settings_claude, journal, search, time-macros
│   └── static/css/app.css, static/js/app.js
├── deploy/                 копии конфигов nginx и systemd
├── tests/                  пробники check_*.py, запускаются вручную
├── manual/                 сборка «Руководства пользователя.docx»: make_shots.py
│                           (снимки на вымышленном стенде), build_manual.py (текст)
├── requirements.txt
├── .env.example            образец состава настроек, без значений
├── webclaude.md            этот документ
├── Руководство пользователя.docx  собирается из manual/, вне версий
├── downloads/              папка выдачи проекта, вне версий
├── .venv/, uploads/        вне версий
```

Около 8 000 строк. Крупнейшие файлы: `static/js/app.js` (~1 000),
`routers/projects.py` (~800), `static/css/app.css` (~600),
`services/claude_driver.py` (~450).

Руководство пользователя собирается на сервере по желанию, после этапа 16: нужны Playwright с Chromium и `python-docx` в отдельном окружении (не в `.venv` приложения), права на `sudo -u postgres` для временной базы стенда. Скрипт снимков поднимает свой экземпляр приложения на вымышленных данных и заглушках движка, VPN и аудита — рабочую базу и настоящие ключи не трогает. Готовый docx копируется в `downloads/` командой `cp`.

### `infra/`

| Файл | Назначение |
|---|---|
| `sudo-allowed.list` | источник истины по беспарольному sudo |
| `apply-sudo.sh` | собирает `/etc/sudoers.d/010-<ПОЛЬЗОВАТЕЛЬ>`, проверяет `visudo -c` до установки |
| `install-root-helpers.sh` | ставит обёртки в `/usr/local/sbin`, скрипты VPN в `/usr/local/lib/webui-vpn`, аудит в `/opt/secaudit` |
| `webui-deploy.sh` | раскладка трёх конфигов nginx с `nginx -t` и откатом |
| `webui-apt-install.sh` | установка пакетов: принимает **только имена** |
| `tls-letsencrypt.sh` | выпуск сертификата (webroot), смена почты `--email` |
| `webui-vpn.sh` | `install`, `add`, `remove`, `list`, `peers`, `status` для WireGuard |
| `webui-sec.sh` | сбор фактов, устранение, файрвол, эталон, ужесточение SSH/fail2ban/обновлений, карантин |
| `secrets-to-root.sh` | перенос ключей приложения в `/etc/webui/webui.env` под root |
| `switch-to-keys.sh` | вход только по ключам и полный беспарольный sudo — одной командой с проверками |
| `pg-backup.sh`, `pg-restore-check.sh` | выгрузка базы и проверка восстановления |
| `crontab.mokeeva` | копия расписания cron пользователя |
| `tests/check-backup-verify.sh` | проверка проверки выгрузки |

### `.gitignore`

```
exchange/
*.exe
*.dll
dist/
build/
node_modules/
*.log
.env
.env.local
.DS_Store
Thumbs.db
desktop.ini
.vscode/
.idea/
webui/.venv/
webui/.env
webui/uploads/
__pycache__/
*.pyc
downloads/
webui/manual/shots/
webui/*.docx
```

## 5. Адреса

nginx срезает префикс (`proxy_pass` со слешем), приложение запущено с
`--root-path /Claude`. Маршруты пишутся без префикса, ссылки строятся через
`url_for`. **Исключение:** ссылки меню в `base.html` на разделы, добавленные
позже, собираются вручную — `{{ root_path }}/vpn`: `url_for` на маршрут, которого
ещё нет в работающем Python (раздел 20), роняет **каждую** страницу.

| Маршрут | Назначение |
|---|---|
| `GET/POST /login`, `POST /login/totp` | вход в два шага |
| `GET/POST /password`, `POST /logout` | обязательная смена пароля, выход |
| `GET /` , `/api/metrics`, `/api/metrics/history` | дашборд и данные автообновления |
| `/chats`, `/chats/new`, `/chats/{id}/rename`, `/delete`, `/send`, `/stream` | чатики |
| `/projects`, `/projects/new`, `/projects/{id}/bash` | проекты, переключатель запуска команд |
| `/projects/{id}/topics/new`, `/projects/topics/{id}/delete` | темы |
| `/projects/topics/{id}/send`, `/stream`, `/compact` | отправка, события, сжатие контекста |
| `/projects/{id}/topics/state` | кружки состояния тем (опрос) |
| `/projects/{id}/tree`, `/projects/{id}/tree/file?path=` | «Файлы проекта»: список `downloads/` и скачивание |
| `/projects/{id}/upload`, `/projects/files/{id}`, `/delete` | «Загрузка»: файлообмен |
| `/vpn`, `/vpn/state`, `/vpn/add`, `/vpn/remove`, `/vpn/qr/{name}`, `/vpn/conf/{name}` | VPN |
| `/sec`, `/sec/state`, `/sec/run`, `/sec/baseline`, `/sec/reports/{date}`, `/raw` | безопасность |
| `/settings`, `/settings/save`, `/settings/file`, `/settings/sessions/{id}/close` | настройки |
| `/settings/restart`, `/settings/restart/state` | перезапуск и его состояние |
| `/settings/totp`, `/start`, `/enable`, `/cancel`, `/disable` | второй фактор |
| `/settings/claude`, `/start`, `/code`, `/cancel`, `/check` | вход Claude: срок, повторный вход, проверка |
| `/export/{id}`, `/journal`, `/search`, `/healthz` | выгрузка, журнал, поиск, живость |

## 6. База

Девять таблиц. Схема применяется при каждом старте; миграций нет, новый
столбец пишется как `ALTER TABLE … ADD COLUMN IF NOT EXISTS`. Засев при старте:
пользователь `config.INITIAL_LOGIN` с паролем `config.INITIAL_PASSWORD` и
`must_change = true`, настройки по умолчанию `ON CONFLICT DO NOTHING`.

| Таблица | Назначение |
|---|---|
| `users` | логин, argon2id, `must_change`, `totp_secret`, `totp_enabled`, `totp_last_step` |
| `sessions` | серверные сессии (uuid), IP, браузер, срок |
| `login_attempts` | защита от перебора |
| `projects` | имя, `slug`, `workdir`, `allow_bash`, `archived` |
| `conversations` | чатики и темы, `claude_session_id`, `context_tokens`, `context_at` |
| `messages` | роль `user`/`assistant`/`error`, расход, `content_tsv` (GIN, `russian`) |
| `files` | файлообмен по проектам (вкладка «Загрузка») |
| `settings` | ключ-значение |
| `metrics_history` | история метрик для графика |

Полный текст — `webui/app/schema.sql`. Ключевые места:

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id                serial PRIMARY KEY,
    kind              text NOT NULL CHECK (kind IN ('chat', 'topic')),
    project_id        integer REFERENCES projects(id) ON DELETE CASCADE,
    title             text NOT NULL,
    claude_session_id text,                 -- для --resume
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT conversations_kind_project CHECK (
        (kind = 'chat'  AND project_id IS NULL) OR
        (kind = 'topic' AND project_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS messages (
    id               bigserial PRIMARY KEY,
    conversation_id  integer NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             text NOT NULL CHECK (role IN ('user', 'assistant', 'error')),
    content          text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    model            text,
    input_tokens     integer NOT NULL DEFAULT 0,
    output_tokens    integer NOT NULL DEFAULT 0,
    cache_read       integer NOT NULL DEFAULT 0,
    cache_write      integer NOT NULL DEFAULT 0,
    cost_usd         numeric(12, 6) NOT NULL DEFAULT 0,
    duration_ms      integer NOT NULL DEFAULT 0,
    num_turns        integer NOT NULL DEFAULT 0,
    content_tsv      tsvector GENERATED ALWAYS AS (to_tsvector('russian', content)) STORED
);
CREATE INDEX IF NOT EXISTS messages_tsv_idx ON messages USING gin(content_tsv);

-- второй фактор
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret    text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled   boolean NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_last_step bigint  NOT NULL DEFAULT 0;
-- размер контекста темы
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS context_tokens integer NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS context_at     timestamptz;
```

Поиск — `websearch_to_tsquery('russian', …)`, `ts_headline`, `ts_rank`.
Пул `min_size=1, max_size=8`, `row_factory=dict_row`. **Всё время хранится
в UTC** (`timestamptz`), пояс влияет только на показ (раздел 14).

Настройки по умолчанию (`config.DEFAULT_SETTINGS`):

| Ключ | Значение | Смысл |
|---|---|---|
| `refresh_seconds` | 10 | автообновление дашборда |
| `model` | `opus` | псевдоним модели для `--model` |
| `theme` | `light` | `light` / `dark` / `system` |
| `metrics_keep_hours` | 48 | сколько хранить историю метрик |
| `timezone` | `Europe/Moscow` | пояс показа |
| `compact_window` | 250000 | потолок контекста; 0 — не задавать |
| `limit_5h_tokens`, `limit_week_tokens` | 0 | пределы окон; 0 — без меры остатка |

## 7. Драйвер движка

### Командная строка

```python
argv = [CLAUDE_BIN, "-p", prompt, "--output-format", "stream-json",
        "--include-partial-messages", "--verbose", "--model", model]
if session_id:
    argv += ["--resume", session_id]
if with_tools:                                   # тема проекта
    allowed = ["Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch"]
    denied = list(SECRET_DENY)
    if allow_bash:
        allowed.append("Bash")
    else:
        denied += ["Bash", "BashOutput", "KillShell"]
    argv += ["--disallowed-tools", *denied, "--allowed-tools", *allowed,
             "--permission-mode", "acceptEdits", "--add-dir", str(workdir)]
else:                                            # чатик
    argv += ["--disallowed-tools", *CHAT_DISALLOWED, *SECRET_DENY]
argv += ["--permission-prompts", "none"]         # нажимать кнопки некому

SECRET_DENY = [f"{t}(//{ENV_DIR_без_ведущего_слеша}/**)" for t in ("Read", "Write", "Edit")]
```

Процесс запускается с `cwd=workdir`, с окружением `_child_env(window)`:
из `os.environ` вычищаются `config.SCRUB_ENV_KEYS` и унаследованная
`CLAUDE_CODE_AUTO_COMPACT_WINDOW`, затем она ставится из настройки.

### Граблей в драйвере пять

1. **`--allowed-tools` не запрещает остальное**, только авто-одобряет
   перечисленное. Запрет — только `--disallowed-tools`, и сразу всё семейство
   `Bash`, `BashOutput`, `KillShell`.
2. **`--add-dir` — рабочая область, но не граница.** `Read` из
   `--allowed-tools` читает любой путь. Нужен явный запрет по пути.
3. **В правиле по пути двойной слеш**: `Read(//home/...)`. С одним слешем
   правило молча не действует.
4. **`StreamReader.readline()` падает на строках длиннее 64 КиБ**, а движок
   кладёт в одну строку JSON файл целиком. Нужен свой построчный разбор
   с потолком 64 МБ; тайм-аут — на кусок (время молчания), а не на строку.
5. **В `modelUsage` есть вспомогательная модель** (haiku). Основная — та, что
   выдала больше всего токенов на выход, а не первый ключ.

### События

Драйвер — асинхронный генератор словарей:

| Событие | Откуда | Зачем |
|---|---|---|
| `init` | `system/init` | `session_id` для `--resume` |
| `delta` | `content_block_delta` | кусок текста в ленту |
| `usage` | `message_start` / `message_delta` | живой расход; `context_tokens` — только у основного агента (`parent_tool_use_id` пуст) |
| `tool` | `assistant` → `tool_use` | строка в «Ходе работы» |
| `compact` | `system/status` (начало), `compact_boundary` (итог), отказ | `phase` start/done/failed, `pre_tokens`, `post_tokens`, `trigger` auto/manual |
| `text` | `assistant` → `text` | готовый текст шага |
| `result` | `result` | итог: расход, стоимость, длительность, шаги, контекст — **единственное место записи ответа в базу** |
| `error` | сбой, тайм-аут, `result` с `is_error` | строка роли `error` |

Размер контекста шага — `input_tokens + cache_read_input_tokens +
cache_creation_input_tokens` из `message_start` основного агента.

**Исчерпанный лимит подписки** приходит обычным `result` с `is_error: true` и
текстом вида «You've hit your limit · resets 9:50am (UTC)». Он пишется ролью
`error`, кружок темы остаётся красным «есть незавершённое», а время сброса
переводится в пояс из настроек (`local_limit` в шаблонах).

Предел ответа — `RUN_TIMEOUT_SEC = 1800`; столько же держит nginx.
Заголовок диалога — отдельный вызов на `haiku` по первой реплике, уходит
в браузер событием `title`.

## 8. Фоновые запуски

Работа не должна обрываться при уходе со страницы.

* `POST …/send` пишет вопрос в базу, заводит фоновую задачу и **сразу** отвечает
  `{"ok": true}`; повтор при идущем ответе — 409 **до** записи вопроса;
* события копятся в списке объекта `Run`, ожидание — `asyncio.Condition`;
  ключ запусков темы один на всё — `RUN_KIND = "topic"` (иначе кружок не видит
  запуск сжатия);
* `GET …/stream?start=N` — только читатель: кадры SSE `data: {json}\n\n` с позиции
  `N`, в конце `{"type": "done"}`; при обрыве браузер переподключается с той же
  позиции;
* при **открытии** страницы поток запрашивается с `active=1` — иначе прошлый
  ответ проигрался бы поверх уже показанного из базы; нечего отдавать — `idle`;
* законченный запуск держится 30 минут; предохранитель — 20 000 событий, дальше
  явная отметка об обрыве показа;
* nginx: `proxy_buffering off` и заголовок `X-Accel-Buffering: no`.

Список, а не очередь: очередь читается один раз, вернувшийся браузер получил бы
обрывок.

## 9. Проекты и права

* Правка файлов в `workdir` разрешена всегда (`acceptEdits`), запуск команд —
  только при `projects.allow_bash` (флажок «разрешить запуск команд» в панели
  проекта).
* Каталог нового проекта — транслитерация имени в `slug`; при совпадении
  добавляется суффикс. Вместе с каталогом сразу заводится `downloads/`.
* **Если каталог уже есть** (например `webui/`), проект заводится записью в
  таблице, а не формой — иначе «Веб-интерфейс» даст `veb-interfeys/`.
* Интерфейс удобно завести проектом в самом себе (`workdir = <репо>/webui`,
  `allow_bash = true`) — тогда его дорабатывают из браузера.

### Кружок состояния темы

У каждой темы в левом списке — кружок, цвет подкреплён подсказкой и
`aria-label`:

| Состояние | Когда |
|---|---|
| `work` — «есть незавершённое» | идёт запуск; или последняя запись — вопрос либо ошибка (в том числе исчерпанный лимит, оборванный перезапуском ответ) |
| `done` — «всё выполнено» | последняя запись — ответ |
| `empty` — «сообщений нет» | тема пустая (не зелёная: в ней ничего не делали) |

Страница опрашивает `/projects/{id}/topics/state` и перекрашивает кружки.

### Правая колонка проекта

Сверху — вкладки **«Загрузка»** (файлы в таблице `files`, до 64 МБ, `uploads/`)
и **«Файлы проекта»** (содержимое `downloads/` проекта, раздел 12). Снизу —
**«Ход работы»** со своей прокруткой: строки инструментов, сжатия, таймер,
счётчик шагов, живой расход, размер контекста; после завершения — время,
стоимость, итог. В простое показывает размер контекста темы и предупреждает,
что **кэш остыл** (контекст ≥ 100 тыс. и простой больше часа — следующий шаг
заново запишет весь контекст по цене записи).

## 10. Потолок контекста и сжатие

Тема живёт одной сессией через `--resume`, каждый шаг агента перечитывает её
целиком. У модели окно 1 млн — автосжатие у края не наступает никогда, тема
дорастает до 700 тыс. и каждый шаг стоит дорого.

* Драйвер передаёт `claude` переменную `CLAUDE_CODE_AUTO_COMPACT_WINDOW` из
  настройки `compact_window`: по умолчанию 250 000, границы 100 000–1 000 000
  (меньшее CLI молча игнорирует — значение поднимается до 100 000),
  0 — переменная не задаётся.
* После каждого ответа и сжатия `conversations.context_tokens` и `context_at`
  обновляются.
* Кнопка **«Сжать контекст»** (есть у темы с сессией) — подтверждение, затем
  `claude -p /compact --resume <id>` фоновым запуском того же вида; итог —
  сообщение в ленте «контекст сжат: было → стало» со стоимостью.
* Причины отказа переводятся словами (`too_few_groups` → «сжимать пока нечего»).

## 11. Секреты, вход, сессии, второй фактор

### Секреты

`SECRET_KEY` и пароль базы — **вне** каталога проекта: сперва
`~/.config/webui/webui.env` (600), затем переносятся в `/etc/webui/webui.env`
(root, 600) и подключаются врезкой `EnvironmentFile=`. Путь переопределяется
`WEBUI_ENV`. В репозитории — только `.env.example`:

```
DATABASE_URL=postgresql://webui:ПАРОЛЬ@127.0.0.1:5432/webui
SECRET_KEY=случайные_64_hex_символа
CLAUDE_BIN=/home/<ПОЛЬЗОВАТЕЛЬ>/.local/bin/claude
REPO_ROOT=/home/<ПОЛЬЗОВАТЕЛЬ>/main
ROOT_PATH=/Claude
```

Нужны три вещи разом: файл вне каталога проекта; запрет по пути с двойным слешем;
вычистка окружения перед запуском `claude` по **явному** списку
`config.SCRUB_ENV_KEYS` (иначе после переноса под root файла нет и список
окажется пустым). При `allow_bash` запрет по пути обходится `cat` — поэтому файл
и уезжает под root.

**Остаточный риск, назвать вслух:** приложение и `claude` работают от одного
пользователя. Тема с `allow_bash` — это командная строка этого пользователя,
а при полном беспарольном sudo — и root (раздел 16).

### Вход

* argon2id (`time_cost=3, memory_cost=65536, parallelism=2`);
* серверные сессии: uuid в подписанной cookie `webui_session` (`itsdangerous`),
  30 дней; в настройках видны и закрываются;
* первый вход по `INITIAL_LOGIN` / `INITIAL_PASSWORD`, **смена обязательна**;
  стойкость: не короче 8, не первоначальный, не одни цифры, не из ходовых;
* перебор: 10 неудач за 15 минут с адреса (`login_attempts`) плюс `limit_req`
  nginx на `/Claude/login` — 12 в минуту, всплеск 5;
* IP — из `X-Forwarded-For`, перед приложением nginx.

### Второй фактор (TOTP)

* RFC 6238: SHA1, 6 цифр, шаг 30 с, окно ±1 шаг; реализация в `services/totp.py`.
* Вход в два шага: верный пароль при `totp_enabled` не создаёт сессию, а выдаёт
  подписанный **пропуск на 5 минут** (`PENDING_MAX_AGE = 300`) и форму кода.
* Повтор кода закрыт: `totp_last_step` обновляется условием
  `WHERE totp_last_step < шаг`, тот же код второй раз не проходит.
* Подключение: «Настройки» → «Второй фактор входа» → «Подключить» → QR (SVG
  через `/usr/bin/qrencode`) и строка секрета → код из приложения → «Включить».
  До ввода верного кода секрет «ожидает подтверждения» и на вход не влияет.
* Отключение — паролем и текущим кодом.
* Потерян телефон — из SSH:
  `sudo -u postgres psql webui -c "UPDATE users SET totp_enabled=false, totp_secret=NULL, totp_last_step=0 WHERE login='<ЛОГИН>'"`.
* Имя в приложении-аутентификаторе — `totp.ISSUER` (заменить под свой домен).
* Секрет лежит в базе открыто (шифровать нечем, чего не было бы рядом) —
  выгрузки базы остаются секретом.

## 12. Папка выдачи `downloads/`

Файлы, которые человек просит сделать или выложить, кладутся в
`<workdir>/downloads/`. Вкладка «Файлы проекта» показывает **только эту папку**,
не весь проект.

* `_downloads_dir(workdir)` создаёт папку при обращении и при создании проекта;
* дерево строится с пропуском `.git`, `.venv`, `node_modules`, `__pycache__`,
  `dist`, `build` и прочего; закрыты `.env*`, `*.key`, `*.pem`, `*.pyc`;
  не больше 2 000 файлов и 12 уровней;
* путь для скачивания разрешается внутри папки (`_resolve_in_dir`): `..`,
  симлинк наружу и сама папка — отказ;
* `downloads/` не версионируется: оригинал живёт в каталоге проекта, в
  `downloads/` — копия, которая обновляется **только командой `cp`**
  (правило 15, раздел 22).

## 13. VPN

WireGuard, сеть `10.8.0.0/24`, сервер `10.8.0.1`, порт `51820/udp`,
`wg-quick@wg0`, транзит и MASQUERADE. Комплект — `vpn-server/`
(`install-wireguard.sh`, `add-client.sh`, `remove-client.sh`, `list-peers.sh`).

Приложение в `/etc/wireguard` не ходит и `wg` не вызывает: только
`sudo -n webui-vpn install [--port N]|add ИМЯ [--split]|remove ИМЯ|list|peers|status`.
QR-код приложение рисует само (`qrencode -t SVG`) из конфига клиента. Обёртка
запускает копии скриптов из `/usr/local/lib/webui-vpn` (root), а не из
репозитория — иначе правка файла в репозитории давала бы root.

Имя клиента — `^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$`, проверяется и в приложении,
и в обёртке (ведущий дефис стал бы флагом). Конфиги с закрытым ключом —
`exchange/vpn/ИМЯ.conf` (вне версий, 600).

Страница: «Сервер» (интерфейс, порт, адрес, клиентов), «Новый клиент» (имя,
флажок «только сеть туннеля» — `--split`, без него через сервер идёт весь
трафик устройства), «Клиенты» (адрес, кружок «на связи» по последнему
рукопожатию, трафик, QR, скачать `.conf`, «Отозвать»), опрос `/vpn/state`.

## 14. Часовой пояс

* Хранится UTC; показ — `timefmt.fmt(value, pattern, tz)`, в шаблонах макрос
  `time.when(...)` из `time-macros.html`, в `<body data-tz="…">` — для JS.
* «Сегодня» на дашборде — от полуночи в поясе:
  `date_trunc('day', now() AT TIME ZONE tz) AT TIME ZONE tz`.
* Время сброса лимита из текста Claude Code («resets 9:50am (UTC)») переводится
  в пояс (`local_limit`).
* Выбор в «Настройках»: список `timefmt.zone_choices()` со смещением.

## 15. Ночной аудит безопасности

Код — `bezopasnost/`: `config.sh` (единственный файл под сервер), `collect.sh`
(слой 1, сбор фактов, root), `diff.sh` (слой 2, сверка с эталоном),
`remediate.sh` (слой 3, устранение по белому списку, root), `apply-firewall.sh`,
`firewall-rollback.sh`, `audit.sh` (связка и отчёт), `CONTEXT.md`.

**Раскладка: код отдельно, состояние отдельно.**

| Путь | Владелец | Что |
|---|---|---|
| `/opt/secaudit/*.sh`, `config.sh` | root:root | рабочая копия кода |
| `/opt/secaudit/baseline/` | root:root | эталон |
| `/opt/secaudit/quarantine/` | root:root 700 | изъятое, адресуется sha256 |
| `/var/lib/secaudit/` | `<ПОЛЬЗОВАТЕЛЬ>` 700 | снимки, отчёты `reports/rep_ГГГГ-ММ-ДД.md`, `audit.log` |

Каталог, доступный пользователю на запись, плюс разрешение запускать оттуда
от root — это root. Поэтому правка `bezopasnost/` действует только после
`sudo bash infra/install-root-helpers.sh`.

**Обёртка `webui-sec` не принимает путей**: снимок снимается заново, карантин —
по sha256, эталон — из снимка текущего дня по жёсткому пути. Аудит читает то,
что контролирует атакующий.

`config.sh` образца:

```bash
ADMIN_USER=<ПОЛЬЗОВАТЕЛЬ>
SSH_PORT=22
SSH_AUTH_MODE=key          # password до перехода на ключи
PUB_TCP="80,443"
PUB_UDP="51820"            # без этого первый же файрвол молча отрежет WireGuard
TRUSTED_IFACES="wg0"
TRUSTED_IPS="127.0.0.1/8 ::1 10.8.0.0/24"
SERVICES="ssh nginx postgresql fail2ban webui wg-quick@wg0"
ANALYZER=""                # разбор моделью выключен; если включать — без инструментов, данные на stdin
RETENTION_DAYS=90
```

**Файрвол** default-deny для v4 и v6: входящие 22, 80, 443/tcp, 51820/udp,
всё с `wg0`, loopback, установленные соединения. Применяется **временно**:
`firewall-apply` ставит самооткат через 5 минут (`systemd-run
--unit=webui-sec-rollback --on-active=300`); после проверки входа из второго
окна — `firewall-confirm`, затем `firewall-save` (`netfilter-persistent`).
Ночной прогон не включает файрвол, пока его не применили руками хотя бы раз.

**fail2ban** с джейлами `sshd` и `recidive` (`harden-fail2ban`),
**автообновления** безопасности (`harden-updates`).

**Страница `/sec`:** «Состояние» (установлен ли аудит, эталон, последний отчёт,
молчание дольше 26 часов — отдельным предупреждением, fail2ban, политики
файрвола, карантин, находки), итог последнего прогона по `audit.log`,
«Прогнать сейчас» — «Прогнать с устранением» (`REMEDIATE=1`), «Прогнать без
вмешательства» (`REMEDIATE=0`), «Принять эталон» (только после разбора
расхождений); «Отчёты» — список с числом находок, чтение и сырой текст.
Дата в адресе отчёта сверяется с `^\d{4}-\d{2}-\d{2}$` **до** обращения к диску.
Прогон — поток приложения с тайм-аутом 30 минут; перезапуск службы ждёт его
окончания (раздел 17).

## 16. Доступ к серверу: SSH и sudo

Итоговое состояние образца:

* **SSH только по ключам**: `/etc/ssh/sshd_config.d/10-hardening.conf` —
  `PermitRootLogin no`, `MaxAuthTries 3`, `LoginGraceTime 20`, `LogLevel VERBOSE`,
  `AllowUsers <ПОЛЬЗОВАТЕЛЬ>`, `PasswordAuthentication no`,
  `KbdInteractiveAuthentication no`. Имя начинается с `10-`: OpenSSH берёт
  **первое** встреченное значение, и `50-cloud-init.conf` перебил бы `99-`.
* **Беспарольный sudo на всё** (`ALL` в разделе root `sudo-allowed.list`) и
  шесть команд от postgres (`psql`, `createdb`, `createuser`, `dropdb`,
  `pg_dump`, `pg_dumpall`).
* Обёртки `webui-*` — root:root 0755 в `/usr/local/sbin`: при полном sudo они
  удобство и защита от ошибки, при суженном — граница.

**Порядок нельзя переставлять:** сперва ключ в `authorized_keys`, проверка
входа по ключу, выключение пароля, проверка `sshd -T` и **настоящей попыткой
входа паролем** (ожидается отказ `(publickey)`), и только потом полный
беспарольный sudo. Беспарольный sudo при парольном SSH — один шаг от подбора
пароля до root. Всё это делает `infra/switch-to-keys.sh` с остановкой на
первом провале.

**Более строгий вариант** — вместо `ALL` перечень команд (в образце был до
14.09: `git show 3b1830a:infra/sudo-allowed.list`). В нём сознательно нет правки
юнитов, `apt-get install` с произвольными доводами, `tee`/`cp`/`sed`/`chmod` с
произвольными путями, интерпретаторов, `visudo`: любая из них равна root.
Выбор — за человеком; агент называет цену обоих вариантов.

## 17. Перезапуск из интерфейса

`claude` запущен приложением и входит в контрольную группу `webui.service`:
остановка службы гасит и его, а ответ пишется в базу по завершении.

Кнопка «Перезапустить» **ставит перезапуск в очередь**: ждёт, пока
`restart._busy()` (идущие ответы драйвера + идущий прогон аудита) обнулится,
предел 30 минут. Браузер опрашивает `/settings/restart/state`, ловит момент,
когда приложение перестало отвечать, и обновляет страницу, когда `/healthz`
снова отвечает. Команда — дословно `/usr/bin/sudo -n /usr/bin/systemctl restart webui`.

⚠️ Агент, работающий из темы, **сам себя перезапустить не может** тем же
способом: его процесс в той же группе. Перезапуск ставится через кнопку или
отложенно (`systemd-run --on-active=…`), и результат проверяется после.

## 18. Учёт расхода

* Остаток по подписке **программно недоступен** (Admin/Analytics API личным
  подпискам не выдаются). Пределы окон задаются в настройках и подбираются
  наблюдением.
* Ограничивают окна 5 часов и неделя, а не деньги; `total_cost_usd` —
  справочный пересчёт по тарифам API.
* Окна считаются по стенограммам `~/.claude/projects/*/*.jsonl` (учитывают и
  терминал), база — запасной источник; источник подписан на странице.
* ⚠️ Один ответ разложен на несколько строк с **одним и тем же** `usage` —
  сводить по `requestId + message.id` (построчное сложение завышает вдвое).
* Файлы дочитываются по смещению, последняя незаконченная строка пропускается.
* Окно скользящее: начало — самый ранний ответ в пределах длины окна.
* Метрики — psutil и `/proc`, совпадают с `free`, `df`, `uptime`;
  `cpu_percent(interval=None)`; скорость сети считается самостоятельно.

## 19. Дизайн-система

Плотные таблицы, командные панели, тёплая серо-бежевая гамма, жёлто-оранжевый
акцент, без скруглений и теней. Всё на токенах; тёмная тема переопределяет
только их.

```css
:root {
    --bg: #f2f1ee;  --bg-sunken: #e7e5e0;  --panel: #ffffff;  --panel-alt: #faf9f7;
    --cmdbar: linear-gradient(#f7f6f3, #eceae4);  --cmdbar-flat: #f1efea;
    --line: #c9c6bf;  --line-soft: #dedbd4;  --line-strong: #a8a49b;
    --ink: #23211d;  --ink-soft: #5f5b53;  --ink-faint: #8b867c;  --ink-invert: #fff;
    --accent: #e8b000;  --accent-deep: #b98a00;  --accent-wash: #fdf4d0;
    --link: #1f5c9e;  --link-hover: #14406e;
    --ok: #2f7d32;  --warn: #b26a00;  --err: #b3261e;
    --row-hover: #f5f2e6;  --row-select: #fdf3cd;
    --gap: 8px;  --radius: 2px;
    --font: "Segoe UI", "PT Sans", Tahoma, sans-serif;
    --fs: 13px;  --fs-sm: 12px;  --row-h: 26px;
}
```

* Тема: `:root[data-theme="light|dark"]`, системная — `@media
  (prefers-color-scheme: dark)` с `:root:not([data-theme="light"])`.
* Раскладка: титульная строка, панель разделов (Дашборд, Чатики, Проекты, VPN,
  Безопасность, Настройки | Журнал, Поиск), `main`. Окно диалога занимает высоту
  окна, лента прокручивается внутри, поле ввода внизу, Ctrl+Enter — отправить.
* Прокрутка липнет к низу, только если пользователь внизу (запас 60 px).
* Элементы: `panel`, `cmdbar`, `btn`/`btn--primary`/`btn--danger`/`btn--plain`,
  `table`, `tag`, `dot dot--work|done|empty`, `tabs`/`tabpanel`, `note`, `field`.
* Доступность: семантические теги, фокус с клавиатуры, цвет не единственный
  признак; широкие блоки скроллятся в своём контейнере.
* Тексты интерфейса и комментарии — на русском.

## 20. Разрыв при выкладке

Шаблоны Jinja2 перечитываются сразу, Python — только после перезапуска службы.
Между правкой и перезапуском новый шаблон работает со старым кодом. Поэтому:

* в шаблонах новые переменные проверяются `is defined`;
* ссылки на новые маршруты в `base.html` собираются вручную, не `url_for`;
* после выкладки Python — перезапуск (раздел 17) и проверка страницы нажатием.

---

# Часть Б. Развёртывание по шагам

Команды даны от `<ПОЛЬЗОВАТЕЛЬ>` в его домашнем каталоге, если не сказано иное.
До этапа 12 `sudo` спрашивает пароль — эти шаги выполняет человек или агент
в сессии, где человек ввёл пароль. Каждый этап заканчивается **проверкой** —
не прошла, дальше не идти.

## Этап 1. Сервер и учётка

```bash
# от root, первый вход от хостера
adduser <ПОЛЬЗОВАТЕЛЬ>
usermod -aG sudo <ПОЛЬЗОВАТЕЛЬ>
timedatectl set-timezone UTC            # система в UTC, пояс показа — в настройках
apt-get update && apt-get -y upgrade
```

**Проверка:** `ssh <ПОЛЬЗОВАТЕЛЬ>@<IP>` входит, `sudo -v` принимает пароль.

## Этап 2. SSH-ключ (пароль пока не выключать)

На **своём компьютере** человека:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/<ПОЛЬЗОВАТЕЛЬ>-ssh-key -C "<ПОЛЬЗОВАТЕЛЬ>@<ДОМЕН>"
ssh-copy-id -i ~/.ssh/<ПОЛЬЗОВАТЕЛЬ>-ssh-key.pub <ПОЛЬЗОВАТЕЛЬ>@<IP>
```

Windows без `ssh-copy-id`: содержимое `.pub` дописать на сервере одной строкой
в `~/.ssh/authorized_keys`, права `700` на `~/.ssh`, `600` на файл.

**Проверка:** из второго окна `ssh -i ~/.ssh/<ПОЛЬЗОВАТЕЛЬ>-ssh-key <ПОЛЬЗОВАТЕЛЬ>@<IP>`
входит **без** вопроса пароля.

## Этап 3. Пакеты

```bash
sudo apt-get install -y git curl postgresql nginx python3-venv python3-dev libpq-dev \
    certbot qrencode wireguard iptables-persistent fail2ban unattended-upgrades
```

`iptables-persistent` спросит, сохранять ли текущие правила, — ответить «нет»:
правила ставятся на этапе 14.

**Проверка:** `psql --version` (16), `nginx -v`, `python3 --version` (3.12),
`qrencode -V`, `wg --version`.

## Этап 4. Claude Code

```bash
curl -fsSL https://claude.ai/install.sh | bash      # ставит ~/.local/bin/claude
~/.local/bin/claude                                  # интерактивно: вход по подписке
```

Человек выбирает вход по подписке, открывает ссылку в своём браузере, вставляет
код. Затем выход из `claude`.

**Проверка:**

```bash
~/.local/bin/claude -p "ответь одним словом: работает" --output-format stream-json --verbose | tail -1
```

Последняя строка — `{"type":"result",…,"is_error":false,…}`, никаких вопросов.
Если спрашивает — интерфейс повиснет: нажимать кнопки некому.

## Этап 5. Код

```bash
git clone <РЕПОЗИТОРИЙ> ~/main
cd ~/main
mkdir -p exchange webui/downloads
```

**Под новый сервер заменить** (`grep -rn "mokeeva\|mokeevasky\|46\.8\.178\|Светлана\|Svetlana"`):

| Где | Что |
|---|---|
| `webui/app/config.py` | `INITIAL_LOGIN` → `<ЛОГИН>`; значения по умолчанию путей |
| `webui/app/services/totp.py` | `ISSUER` → «Рабочее место `<ДОМЕН>`» |
| `webui/app/templates/{projects,chats,search}.html` | подпись реплик → `<ИМЯ>` |
| `webui/app/templates/login_totp.html`, `routers/settings.py` | упоминания пользователя |
| `webui/deploy/webui.service` | `User`, `Group`, пути, `HOME` |
| `webui/deploy/nginx-webui.conf` | `server_name`, пути сертификата, www-имя |
| `infra/*.sh`, `infra/sudo-allowed.list`, `infra/crontab.mokeeva` | пользователь, пути; `EXPECT_IP` в `tls-letsencrypt.sh` → `<IP>` |
| `bezopasnost/config.sh` | `ADMIN_USER`, `SSH_AUTH_MODE=password` (до этапа 12) |

Правила работы — `CLAUDE.md` (раздел 22). `result.md`, `log.md`,
`current_questions.md`, `tech_debt.md` начать заново, пустыми разделами:
история образца не переносится.

**Проверка:** `grep` выше ничего не находит вне документации.

## Этап 6. База

```bash
DBPASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
sudo -u postgres psql -c "CREATE ROLE webui LOGIN PASSWORD '$DBPASS'"
sudo -u postgres createdb -O webui webui
```

Пароль сразу уходит в файл настроек (этап 7), в историю и ответы не выводится.

**Проверка:** `PGPASSWORD=… psql -h 127.0.0.1 -U webui webui -c 'select 1'`.

## Этап 7. Приложение

```bash
cd ~/main/webui
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
install -d -m 700 ~/.config/webui
umask 077
cat > ~/.config/webui/webui.env <<EOF
DATABASE_URL=postgresql://webui:$DBPASS@127.0.0.1:5432/webui
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
CLAUDE_BIN=$HOME/.local/bin/claude
REPO_ROOT=$HOME/main
ROOT_PATH=/Claude
EOF
chmod 600 ~/.config/webui/webui.env
unset DBPASS
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --root-path /Claude &
sleep 3; curl -s http://127.0.0.1:8000/healthz; kill %1
```

Схема и засев применяются при старте.

**Проверка:** `/healthz` отвечает `ok`; в базе девять таблиц и пользователь
`<ЛОГИН>` с `must_change = true`.

## Этап 8. systemd

```bash
sudo cp ~/main/webui/deploy/webui.service /etc/systemd/system/webui.service
sudo systemctl daemon-reload && sudo systemctl enable --now webui
```

Юнит (`deploy/webui.service`): `User`/`Group` = `<ПОЛЬЗОВАТЕЛЬ>`,
`WorkingDirectory=…/main/webui`, `Environment=PATH=…/webui/.venv/bin:…/.local/bin:/usr/local/bin:/usr/bin:/bin`,
`Environment=HOME=/home/<ПОЛЬЗОВАТЕЛЬ>` (**обязательно**: без него `claude`
не найдёт учётные данные), `ExecStart=… uvicorn app.main:app --host 127.0.0.1
--port 8000 --root-path /Claude --proxy-headers --forwarded-allow-ips 127.0.0.1`,
`Restart=on-failure`.

**Проверка:** `systemctl is-active webui` → `active`,
`curl -s http://127.0.0.1:8000/healthz` → `ok`.

## Этап 9. nginx и TLS

DNS: A-записи `<ДОМЕН>` и `www.<ДОМЕН>` → `<IP>` (пустая A-запись даёт
молчаливый отказ выпуска).

```bash
sudo install -d /var/www/certbot
sudo cp ~/main/webui/deploy/nginx-webui-proxy.conf  /etc/nginx/snippets/webui-proxy.conf
sudo cp ~/main/webui/deploy/nginx-webui-limits.conf /etc/nginx/conf.d/webui-limits.conf
```

Сертификата ещё нет, поэтому сперва временный конфиг только с HTTP-блоком
из `deploy/nginx-webui.conf` (ACME-location и редирект), затем:

```bash
sudo bash ~/main/infra/tls-letsencrypt.sh <ДОМЕН> www.<ДОМЕН> <ПОЧТА>
sudo cp ~/main/webui/deploy/nginx-webui.conf /etc/nginx/sites-available/webui
sudo ln -sf /etc/nginx/sites-available/webui /etc/nginx/sites-enabled/webui
sudo rm -f /etc/nginx/sites-enabled/default      # с согласия человека
sudo nginx -t && sudo systemctl reload nginx
```

Суть конфига: HTTP → HTTPS кроме `location ^~ /.well-known/acme-challenge/`;
`location = /Claude/login` с `limit_req zone=login burst=5 nodelay`;
`location /Claude/` → `proxy_pass http://127.0.0.1:8000/` с `proxy_buffering off`,
`proxy_cache off`, `proxy_read_timeout 1800s`, `proxy_send_timeout 1800s`;
`client_max_body_size 70m`; заголовки `X-Content-Type-Options nosniff`,
`X-Frame-Options SAMEORIGIN`, `Referrer-Policy same-origin`; `www` — отдельным
`server` с `return 301` на основное имя (cookie привязана к имени). Зона:
`limit_req_zone $binary_remote_addr zone=login:1m rate=12r/m;`.
Продление — `certbot.timer`.

**Проверка:** в браузере `https://<ДОМЕН>/Claude/healthz` → `ok`, замок без
предупреждений; `http://` уводит на `https://`; `https://www.<ДОМЕН>/Claude/`
уводит на основное имя.

## Этап 10. Первый вход

1. `https://<ДОМЕН>/Claude/` → вход `<ЛОГИН>` / `INITIAL_PASSWORD`.
2. Обязательная смена пароля.
3. «Настройки»: часовой пояс `<ПОЯС>`, модель, потолок контекста 250 000.
4. «Настройки» → «Второй фактор входа» → «Подключить», человек сканирует QR,
   вводит код → «Включить».
5. Выход и вход заново: пароль → код.

**Проверка:** неверный код не пускает, тот же верный код второй раз не проходит,
10 неверных паролей подряд упираются в отказ.

## Этап 11. Проект «Веб-интерфейс»

```bash
sudo -u postgres psql webui -c "INSERT INTO projects (name, slug, workdir, allow_bash)
    VALUES ('Веб-интерфейс', 'webui', '/home/<ПОЛЬЗОВАТЕЛЬ>/main/webui', true)"
```

Прочие проекты — формой «Новый проект».

**Проверка** (нажатием, в теме): при снятом флажке «разрешить запуск команд»
просьба выполнить `ls` **не** выполняется; просьба прочитать
`~/.config/webui/webui.env` **отказана**; файл, созданный в `downloads/`, виден
во вкладке «Файлы проекта» и скачивается; уход на другой раздел посреди ответа
и возврат — ответ дописан.

## Этап 12. Обёртки, SSH только по ключам, беспарольный sudo

```bash
cd ~/main
sudo bash infra/install-root-helpers.sh     # webui-* в /usr/local/sbin, VPN-скрипты, /opt/secaudit
sed -i 's/^SSH_AUTH_MODE=.*/SSH_AUTH_MODE=key/' bezopasnost/config.sh
sudo bash infra/switch-to-keys.sh
```

`switch-to-keys.sh` по шагам: ставит обёртки и аудит заново → проверяет
`authorized_keys` → `webui-sec harden-ssh` → `sshd -T` показывает
`passwordauthentication no` и настоящая попытка входа паролем получает
`Permission denied (publickey)` → `apply-sudo.sh` (с `visudo -c`) →
`sudo -l` показывает `NOPASSWD: ALL`. Первый провал — остановка, sudo не выдаётся.

⚠️ Текущую сессию **не закрывать**, пока человек не вошёл по ключу из второго
окна. Откат SSH: `sudo rm /etc/ssh/sshd_config.d/10-hardening.conf && sudo systemctl reload ssh`.
Если доступ всё-таки потерян — консоль хостера (VNC/KVM).

Затем ключи приложения под root:

```bash
sudo bash infra/secrets-to-root.sh
```

Скрипт кладёт копию в `/etc/webui/webui.env` (root, 600), ставит врезку
`deploy/webui.service.d/secrets.conf`, перезапускает службу, проверяет `/healthz`
и только тогда уводит пользовательскую копию в `/etc/webui/webui.env.bak`.
Нет 200 — сам откатывает.

**Проверка:** `sudo -n true` без пароля; `ssh -o PubkeyAuthentication=no
<ПОЛЬЗОВАТЕЛЬ>@<ДОМЕН>` → `Permission denied (publickey)`;
`ls ~/.config/webui/webui.env` → нет файла; `/healthz` → `ok`;
кнопка «Перезапустить» в настройках отрабатывает, страница возвращается.

## Этап 13. VPN

```bash
sudo WG_ENDPOINT=<ДОМЕН> bash ~/main/vpn-server/install-wireguard.sh
```

`WG_ENDPOINT` именем — чтобы смена адреса не ломала конфиги клиентов. Без него
адрес определяется сам (`sudo webui-vpn install` делает то же, но окружение
через sudo не передаёт). У хостера должен быть открыт `51820/udp`.

Клиенты — на странице `/vpn` («Новый клиент», по одному на устройство).

**Проверка:** `sudo webui-vpn status` — интерфейс поднят, порт слушается;
`cat /proc/sys/net/ipv4/ip_forward` → `1`; на клиенте после подключения
`curl ifconfig.me` показывает `<IP>`, а `https://10.8.0.1/Claude/` открывается;
на `/vpn` кружок клиента зелёный.

VPN ставится **до** файрвола и аудита: в `config.sh` служба `wg-quick@wg0`
уже перечислена, и без неё первый отчёт покажет упавшую службу.

## Этап 14. Файрвол, fail2ban, автообновления, аудит

Порядок: **сперва доступ, потом замок.**

```bash
sudo webui-sec harden-updates
sudo webui-sec harden-fail2ban
sudo webui-sec firewall-apply               # правила на 5 минут, потом самооткат
```

Человек из **второго** окна проверяет: SSH по ключу входит, панель открывается.
Только после этого:

```bash
sudo webui-sec firewall-confirm             # снять самооткат
sudo webui-sec firewall-save                # закрепить через netfilter-persistent
REMEDIATE=0 bash /opt/secaudit/audit.sh     # первый прогон без вмешательства
```

Разобрать отчёт на `/sec`; когда расхождения объяснены — «Принять эталон»
(`webui-sec baseline-approve`).

**Проверка:** `sudo webui-sec status` — fail2ban active, политики DROP,
эталон принят; `bash bezopasnost/tests/check-diff.sh` — все OK; `/sec` без
предупреждения о молчании.

## Этап 15. Резервные копии и расписание

```bash
install -d -m 700 ~/backups ~/main/exchange/backups
crontab ~/main/infra/crontab.mokeeva        # после замены пользователя и путей
bash ~/main/infra/pg-backup.sh
bash ~/main/infra/pg-restore-check.sh
```

Расписание: выгрузка 03:17 ежедневно (текстовый SQL + gzip, роли отдельно,
14 копий в `~/backups`, 3 в `exchange/backups` для забора по SFTP), проверка
восстановления по воскресеньям в 04:05, аудит в 00:00. Выгрузка содержит хеш
пароля, секрет TOTP и всю переписку — это секрет. Копии на том же диске от
его отказа не спасают — забирать наружу.

**Проверка:** в `~/backups` свежий `webui-*.sql.gz`, в `backup.log` строка об
успешной проверке; `restore-check.log` — восстановление прошло; `bash
infra/tests/check-backup-verify.sh` — OK.

## Этап 16. Итоговая приёмка

Пройти каждый пункт нажатием в браузере (headless Chromium через Playwright
в отдельном окружении `exchange/pwenv`, если человека рядом нет):

- [ ] вход: пароль → код; выход; закрытие сессии в «Активных сессиях»;
- [ ] дашборд: плитки обновляются, график рисуется, окна расхода с источником;
- [ ] чатик: ответ приходит потоком, заголовок меняется, экспорт скачивается;
- [ ] тема: «Ход работы» показывает инструменты, контекст; кружок меняет цвет;
      «Сжать контекст» даёт итог в ленте;
- [ ] вкладки «Загрузка» и «Файлы проекта» работают;
- [ ] VPN: заведён и отозван пробный клиент, QR показывается;
- [ ] Безопасность: «Прогнать без вмешательства» даёт итог и отчёт;
- [ ] Настройки: пояс меняет время на страницах, тема оформления переключается,
      файл сопровождения сохраняется, перезапуск возвращает страницу;
- [ ] поиск находит слово из чатика, журнал показывает сообщения;
- [ ] консоль браузера без ошибок на каждой странице;
- [ ] `ss -tlnp`: наружу слушают только 22, 80, 443 (8000 и 5432 — на 127.0.0.1).

Итог записать в `result.md` нового сервера.

---

# Часть В. Правила, проверки, грабли

## 21. Порядок сборки с нуля (если код писать, а не клонировать)

1. Каркас: venv, FastAPI, `healthz`, systemd, nginx с префиксом и TLS.
2. База и вход: схема, пул, засев, argon2id, серверные сессии, смена пароля,
   ограничение частоты.
3. Дизайн-система: `base.html`, токены, меню, тёмная тема, часовой пояс.
4. Драйвер и чатики: разбор потока, расход, `--resume`, заголовок.
5. Проекты: каталоги, `downloads/`, темы, `allow_bash`, запреты, кружки,
   вкладки правой колонки. Проверка: команда без флага не выполняется, файл
   настроек не читается.
6. Фоновые запуски: задача приложения, SSE с позиции, переподключение.
7. Дашборд и расход: метрики, окна по стенограммам, поиск, журнал, экспорт.
8. Потолок контекста, сжатие, исчерпанный лимит.
9. Перезапуск из интерфейса, ключи под root.
10. Второй фактор.
11. VPN: комплект, обёртка, страница.
12. Аудит: скрипты, обёртка, файрвол с самооткатом, страница.
13. SSH по ключам и sudo, бэкапы, cron.

## 22. Правила работы (переносятся в `CLAUDE.md`)

### Нельзя

1. **Не удалять файлы** без явной просьбы. Кажется лишним — спросить.
2. **Не добавлять в Git бинарники и артефакты сборки** — `.exe`, `.dll`,
   `dist/`, `build/`, `node_modules/`.

### Рабочий процесс

1. В начале сессии прочитать `result.md`; при необходимости `log.md` и план.
2. Текущий ход работ и документирование — в `result.md`. `CLAUDE.md` компактный.
3. Новое правило — только с подтверждения.
4. Технический долг — в `tech_debt.md` с подтверждения, «что не так → чем
   грозит → как закрывается»; закрытый переносится в «Закрыто» с датой и хэшем.
5. До и после изменений проект в рабочем состоянии.
6. Git: небольшие логичные коммиты; по завершении — коммит и пуш без
   подтверждения, отчёт хэшем.
7. Задание выполнять целиком, без промежуточных вопросов.
8. `log.md`: задача вверх списка **до** работы (дата, название, «в работе»,
   суть); по завершении — статус, хэши, «Ход».
9. Проверять интерфейс на сервере, а не только сборкой; нужные инструменты
   ставить самостоятельно.
10. `exchange/` не версионируется; в корне только файлы сопровождения.
11. Открытые вопросы — в `current_questions.md`, только незакрытые.
12. Новую проверку сперва прогнать на дефекте, который она ловит.
13. Упавшая проверка сперва проверяется сама. `pgrep -f` находит сам себя —
    гасить по PID, проверять делом.
14. Правка обработчика кнопки проверяется нажатием кнопки.
15. Сделанное по проекту — в каталог проекта, копия — в `<проект>/downloads/`.
    ⚠️ Копия обновляется **только `cp`**; саму копию не читать и не писать
    инструментами Read/Write/Edit — иначе сессия подкладывает её в контекст
    при каждом изменении.

### Стандарты

Комментарии и тексты интерфейса — на русском. PascalCase — классы и компоненты,
camelCase — локальные переменные и функции, kebab-case — CSS-классы и имена
файлов. Семантическая вёрстка, адаптивность, доступность, широкие блоки
скроллятся внутри контейнера.

## 23. Проверки

`pytest` нет. Пробники — `webui/tests/check_*.py`, запуск
`.venv/bin/python tests/<файл>.py`; браузерные поднимают второй экземпляр
приложения на свободном порту с подставным `claude`, временной сессией
(запись в `sessions` + `security.sign_session_id`) и жмут кнопки в Chromium из
`exchange/pwenv`. Рабочую службу не трогают.

| Пробник | Что ловит |
|---|---|
| `check_long_line` | строка JSON длиннее 64 КиБ |
| `check_runs_detach` | запуск переживает обрыв соединения |
| `check_transcripts_usage`, `check_usage_windows`, `check_usage_events` | двойной счёт, окна, разбор расхода |
| `check_topic_state`, `check_limit_state`, `check_limit_time` | кружки, исчерпанный лимит, время сброса |
| `check_compact_context`, `check_compact_ui` | потолок контекста, сжатие, «кэш остыл» |
| `check_project_tree` | «Файлы проекта»: только `downloads/`, выход за папку |
| `check_timezone` | показ в поясе, «сегодня» |
| `check_totp` | коды, окно, повтор, вход в два шага |
| `check_vpn_panel`, `check_sec_panel`, `check_sec_run_result` | страницы VPN и безопасности на заглушках обёрток (`WEBUI_VPN_CMD`, `WEBUI_SEC_CMD`) |

Скриптовые: `bezopasnost/tests/check-diff.sh`, `check-rollback.sh`,
`check-wrapper.sh`; `vpn-server/tests/check-clients.sh`, `check-wrapper.sh`;
`infra/tests/check-backup-verify.sh`.

Минимум перед сдачей: страница открывается, консоль чистая, вёрстка не поехала,
`/healthz` → `ok`, правленая кнопка нажата.

## 24. Грабли одним списком

* `--allowed-tools` авто-одобряет, но не запрещает; запрет — `--disallowed-tools`,
  всё семейство `Bash`/`BashOutput`/`KillShell`.
* Правило по пути — с двойным слешем, иначе молча не действует.
* `--add-dir` — рабочая область, не граница.
* При `allow_bash` запрет по пути обходится `cat` — ключи под root.
* `readline()` падает на строках длиннее 64 КиБ.
* `StreamingResponse` с работой внутри умирает вместе с вкладкой.
* В `modelUsage` есть вспомогательная модель.
* В стенограммах `usage` повторён по строкам ответа — сводить по
  `requestId + message.id`.
* Остаток подписки программно недоступен.
* `proxy_buffering off` и `X-Accel-Buffering: no` — иначе поток приходит разом.
* `HOME` в юните обязателен.
* Перезапуск службы гасит группу вместе с `claude` и прогоном аудита — ставить
  в очередь.
* `www` и основное имя — разные cookie: редирект.
* `pgrep -f` находит сам себя.
* Форма проекта транслитерирует имя: для существующего каталога — запись в таблице.
* Без `CLAUDE_CODE_AUTO_COMPACT_WINDOW` тема дорастает до 700 тыс.; ниже
  100 000 CLI значение игнорирует.
* Через час простоя кэш остывает: первый шаг пишет весь контекст заново
  (при 600 тыс. — $6–7).
* Исчерпанный лимит — это `result` с `is_error`, не «готово».
* Ключ запусков темы один (`topic`) — иначе кружок не видит сжатие.
* Шаблоны подхватываются сразу, Python — после перезапуска: `is defined`,
  ручные ссылки в меню.
* Файл в `sshd_config.d` называть `10-…`: OpenSSH берёт первое значение.
* Беспарольный sudo — только после выключения пароля SSH и проверки входа
  настоящей попыткой.
* Файрвол без `PUB_UDP=51820` молча отрезает WireGuard; без `wg0` в доверенных —
  панель по туннелю.
* Файрвол — только с самооткатом и проверкой из второго окна.
* Обёртка, разрешённая в sudo, должна быть root-владельца без записи
  пользователю; скрипты она берёт из root-копии, не из репозитория.
* Аудит в каталоге, доступном пользователю на запись, — это root.
* Дату отчёта сверять с образцом до обращения к диску (`../../`).
* Пустой снимок аудита — ошибка, а не «всё спокойно»; молчание больше 26 часов —
  предупреждение.
* `grep -q` в конвейере с `gunzip` под `pipefail` убивает источник — проверка
  выгрузки врёт (выгрузки терялись двое суток).
* `pg_dump -Fc` восстанавливается только `pg_restore` — текстовый SQL
  разворачивается `psql`.
* Копию в `downloads/` правят только `cp`.
