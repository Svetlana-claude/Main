-- Таблицы бота. Применяются идемпотентно при старте, поверх схемы webui:
-- общие `users`, `projects`, `conversations`, `messages`, `files` уже есть, бот
-- их не дублирует — он к ним присоединяется.

-- Кто может писать боту. Запись появляется при первом обращении (в том числе
-- чужом), но `allowed` поднимается только из списка TELEGRAM_ALLOWED: так в
-- журнале видно, кто стучался, и доступ при этом не раздаётся.
CREATE TABLE IF NOT EXISTS tg_users (
    tg_id       bigint PRIMARY KEY,
    username    text,
    first_name  text,
    allowed     boolean NOT NULL DEFAULT false,
    user_id     integer REFERENCES users(id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz NOT NULL DEFAULT now(),
    -- Сколько раз обратился и когда последний раз получил отказ: по этим полям
    -- видно перебор, если id бота кто-то узнает
    requests    bigint NOT NULL DEFAULT 0,
    denied_at   timestamptz
);

-- К какому диалогу привязан чат Телеграма сейчас и в каком он режиме.
-- Диалог — обычная запись `conversations`, та же, что у веб-интерфейса: разговор,
-- начатый в Телеграме, виден в браузере и продолжается там.
CREATE TABLE IF NOT EXISTS tg_binding (
    chat_id         bigint PRIMARY KEY,
    conversation_id integer REFERENCES conversations(id) ON DELETE SET NULL,
    -- 'srazu' — делать сразу; 'plan' — сперва показать замысел и спросить кнопкой
    mode            text NOT NULL DEFAULT 'srazu' CHECK (mode IN ('srazu', 'plan')),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Задачи. Отдельная таблица, а не сообщение в диалоге: у задачи есть состояние,
-- которое меняется кнопками, и его надо видеть списком — «что утверждено»,
-- «что в работе», «что я отклонила и почему».
CREATE TABLE IF NOT EXISTS tasks (
    id              serial PRIMARY KEY,
    project_id      integer REFERENCES projects(id) ON DELETE SET NULL,
    conversation_id integer REFERENCES conversations(id) ON DELETE SET NULL,
    title           text NOT NULL,
    body            text NOT NULL,              -- постановка, как её дал человек
    plan            text NOT NULL DEFAULT '',   -- замысел, составленный движком
    status          text NOT NULL DEFAULT 'waiting'
                    CHECK (status IN ('waiting', 'approved', 'rejected',
                                      'running', 'done', 'failed')),
    note            text NOT NULL DEFAULT '',   -- чем дополнили при отправке на переделку
    result_text     text NOT NULL DEFAULT '',
    created_by      bigint,                     -- tg_id постановщика
    chat_id         bigint,                     -- куда отвечать по итогу
    message_id      bigint,                     -- сообщение с кнопками
    created_at      timestamptz NOT NULL DEFAULT now(),
    decided_at      timestamptz,
    done_at         timestamptz
);
CREATE INDEX IF NOT EXISTS tasks_status_idx  ON tasks(status, created_at DESC);
CREATE INDEX IF NOT EXISTS tasks_project_idx ON tasks(project_id, created_at DESC);

-- Смещение очереди обновлений. Нужно, чтобы перезапуск службы не переигрывал
-- заново последние сообщения: Телеграм держит необработанное сутки и отдаёт его
-- снова, пока не подтвердишь смещением.
CREATE TABLE IF NOT EXISTS tg_offset (
    id      integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    value   bigint NOT NULL DEFAULT 0
);
INSERT INTO tg_offset (id, value) VALUES (1, 0) ON CONFLICT (id) DO NOTHING;
