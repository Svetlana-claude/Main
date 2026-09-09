#!/bin/bash
# Раскладка конфигов nginx из репозитория с проверкой и перезагрузкой.
#
# Устанавливается в /usr/local/sbin/webui-deploy владельцем root и БЕЗ права
# записи пользователю. Иначе разрешение «sudo webui-deploy» означало бы
# разрешение запускать от root любой код: достаточно было бы переписать скрипт.
#
# Отсюда следствие: правка этого файла в репозитории сама по себе ничего не
# меняет — новую версию устанавливаете вы:
#     sudo install -o root -g root -m 0755 infra/webui-deploy.sh /usr/local/sbin/webui-deploy
#
# Юниты systemd намеренно НЕ раскладываются: юнит исполняется от root, значит
# его подмена равносильна root. Изменение юнита — ваш ручной шаг.

set -euo pipefail

SRC=/home/mokeeva/main/webui/deploy

# Пары «источник -> назначение». Список закрыт: произвольный путь не пройдёт.
declare -A FILES=(
    ["nginx-webui.conf"]="/etc/nginx/sites-available/webui"
    ["nginx-webui-proxy.conf"]="/etc/nginx/snippets/webui-proxy.conf"
    ["nginx-webui-limits.conf"]="/etc/nginx/conf.d/webui-limits.conf"
)

if [ "$(id -u)" -ne 0 ]; then
    echo "нужен root" >&2
    exit 1
fi

STAMP=$(date +%d%m%y-%H%M%S)
declare -a restore=()

echo "Раскладка конфигов nginx из $SRC"
for name in "${!FILES[@]}"; do
    src="$SRC/$name"
    dst="${FILES[$name]}"
    if [ ! -f "$src" ]; then
        echo "  пропуск: нет $src"
        continue
    fi
    if [ -f "$dst" ]; then
        cp -p "$dst" "$dst.bak-$STAMP"
        restore+=("$dst")
    fi
    install -o root -g root -m 0644 "$src" "$dst"
    echo "  $name -> $dst"
done

echo "Проверка конфигурации"
if ! nginx -t; then
    echo "ОШИБКА в конфигурации — откатываю" >&2
    for dst in "${restore[@]}"; do
        [ -f "$dst.bak-$STAMP" ] && mv "$dst.bak-$STAMP" "$dst"
    done
    nginx -t && systemctl reload nginx
    exit 1
fi

systemctl reload nginx
echo "nginx перезагружен. Резервные копии: *.bak-$STAMP"
