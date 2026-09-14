-- Схема базы веб-интерфейса. Применяется идемпотентно при старте приложения.

CREATE TABLE IF NOT EXISTS users (
    id              serial PRIMARY KEY,
    login           text NOT NULL UNIQUE,
    password_hash   text NOT NULL,
    must_change     boolean NOT NULL DEFAULT false,  -- требовать смену пароля
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_login_at   timestamptz
);

-- Серверные сессии: позволяют выйти на всех устройствах и увидеть активные входы
CREATE TABLE IF NOT EXISTS sessions (
    id          uuid PRIMARY KEY,
    user_id     integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    ip          text,
    user_agent  text
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);

-- Попытки входа: на них держится защита от перебора пароля
CREATE TABLE IF NOT EXISTS login_attempts (
    id      bigserial PRIMARY KEY,
    login   text NOT NULL,
    ip      text NOT NULL,
    ok      boolean NOT NULL,
    at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS login_attempts_ip_at_idx ON login_attempts(ip, at DESC);

-- Проекты
CREATE TABLE IF NOT EXISTS projects (
    id          serial PRIMARY KEY,
    name        text NOT NULL,
    slug        text NOT NULL UNIQUE,
    workdir     text NOT NULL,              -- рабочий каталог, куда пускается Claude
    created_at  timestamptz NOT NULL DEFAULT now(),
    archived    boolean NOT NULL DEFAULT false,
    -- Правка файлов в workdir разрешена всегда, запуск команд — только по флагу.
    -- Так у веб-интерфейса нет права выполнять произвольные команды по умолчанию.
    allow_bash  boolean NOT NULL DEFAULT false
);
ALTER TABLE projects ADD COLUMN IF NOT EXISTS allow_bash boolean NOT NULL DEFAULT false;

-- Диалоги. Один тип записи и для чатиков, и для тем внутри проекта:
-- kind='chat'  -> project_id IS NULL, инструменты выключены
-- kind='topic' -> project_id задан, инструменты доступны в workdir проекта
CREATE TABLE IF NOT EXISTS conversations (
    id                serial PRIMARY KEY,
    kind              text NOT NULL CHECK (kind IN ('chat', 'topic')),
    project_id        integer REFERENCES projects(id) ON DELETE CASCADE,
    title             text NOT NULL,
    claude_session_id text,                 -- для --resume, продолжения диалога
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT conversations_kind_project CHECK (
        (kind = 'chat'  AND project_id IS NULL) OR
        (kind = 'topic' AND project_id IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS conversations_kind_idx ON conversations(kind, updated_at DESC);
CREATE INDEX IF NOT EXISTS conversations_project_idx ON conversations(project_id);

-- Сообщения. Расход пишется по каждому ответу — из него собирается дашборд.
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
CREATE INDEX IF NOT EXISTS messages_conv_idx ON messages(conversation_id, id);
CREATE INDEX IF NOT EXISTS messages_created_idx ON messages(created_at DESC);
CREATE INDEX IF NOT EXISTS messages_tsv_idx ON messages USING gin(content_tsv);

-- Файлы проекта: обмен с заказчиком и разработчиком
CREATE TABLE IF NOT EXISTS files (
    id               bigserial PRIMARY KEY,
    project_id       integer NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    conversation_id  integer REFERENCES conversations(id) ON DELETE SET NULL,
    filename         text NOT NULL,
    stored_name      text NOT NULL,
    size_bytes       bigint NOT NULL,
    mime             text,
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS files_project_idx ON files(project_id, created_at DESC);

-- Настройки приложения: ключ-значение, чтобы не плодить таблиц
CREATE TABLE IF NOT EXISTS settings (
    key         text PRIMARY KEY,
    value       text NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- История метрик сервера для графика за сутки
CREATE TABLE IF NOT EXISTS metrics_history (
    at          timestamptz PRIMARY KEY DEFAULT now(),
    cpu_pct     real NOT NULL,
    mem_pct     real NOT NULL,
    disk_pct    real NOT NULL,
    load1       real NOT NULL
);
CREATE INDEX IF NOT EXISTS metrics_history_at_idx ON metrics_history(at DESC);

-- Второй фактор входа (TOTP), 14.09.2026. Секрет хранится в открытом виде
-- base32: зашифровать его нечем, чего не было бы рядом, — ключ лёг бы в тот же
-- файл настроек. Поэтому выгрузки базы, где он окажется, по-прежнему секрет.
-- totp_enabled поднимается только после ввода верного кода, до того секрет
-- «ожидает подтверждения» и на вход не влияет.
-- totp_last_step — номер последнего принятого 30-секундного отрезка: тот же
-- код второй раз не проходит.
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret    text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled   boolean NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_last_step bigint  NOT NULL DEFAULT 0;

-- Размер контекста сессии, 14.09.2026. Тема — одна сессия Claude Code, и каждый
-- шаг перечитывает её контекст целиком; по этим полям страница показывает, как
-- велик он сейчас и остыл ли кэш (живёт час). Пишется по каждому ответу и сжатию.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS context_tokens integer NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS context_at     timestamptz;
