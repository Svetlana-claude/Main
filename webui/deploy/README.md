# Развёртывание

Копии рабочих конфигов. Правятся здесь, затем раскладываются по местам.
В `/etc` лежат рабочие экземпляры — они вне репозитория, поэтому и хранятся тут.

| Файл здесь | Место в системе |
|---|---|
| `nginx-webui.conf` | `/etc/nginx/sites-available/webui` (симлинк в `sites-enabled`) |
| `nginx-webui-proxy.conf` | `/etc/nginx/snippets/webui-proxy.conf` |
| `nginx-webui-limits.conf` | `/etc/nginx/conf.d/webui-limits.conf` |
| `webui.service` | `/etc/systemd/system/webui.service` |

Сертификат: `/etc/nginx/ssl/webui.{crt,key}` — самоподписанный, на IP 46.8.178.196,
действует до 12.12.2028. В репозиторий не попадает.

## Раскладка после правки

    sudo cp nginx-webui.conf /etc/nginx/sites-available/webui
    sudo cp nginx-webui-proxy.conf /etc/nginx/snippets/webui-proxy.conf
    sudo cp nginx-webui-limits.conf /etc/nginx/conf.d/webui-limits.conf
    sudo nginx -t && sudo systemctl reload nginx

    sudo cp webui.service /etc/systemd/system/webui.service
    sudo systemctl daemon-reload && sudo systemctl restart webui

## Первая установка с нуля

    sudo apt-get install -y postgresql nginx python3-venv python3-dev libpq-dev
    sudo -u postgres createuser webui --pwprompt
    sudo -u postgres createdb -O webui webui
    cd /home/mokeeva/main/webui
    python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
    install -d -m 700 ~/.config/webui
    install -m 600 .env.example ~/.config/webui/webui.env   # заполнить значения
    # схема применяется сама при первом запуске

Файл настроек лежит вне каталога проекта намеренно: `webui/` — рабочий каталог
темы в разделе «Проекты», а чтение файлов там разрешено всегда, и `.env` с
`SECRET_KEY` и паролем базы попал бы в ответ по первой же просьбе показать
настройки. Другой путь задаётся переменной `WEBUI_ENV`.
