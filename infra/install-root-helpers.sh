#!/bin/bash
# Установка root-обёрток из репозитория в /usr/local/sbin.
#
# Запуск (ваш ручной шаг, нужен пароль):
#     sudo bash infra/install-root-helpers.sh
#
# Обёртка — это скрипт, который агенту разрешено запускать от root беспарольно
# (см. infra/sudo-allowed.list). Поэтому она обязана принадлежать root и быть
# закрытой пользователю на запись: будь она доступна на запись, разрешение на
# неё означало бы разрешение исполнять от root любой код — достаточно переписать
# файл. Из этого же следует, что правка обёртки в репозитории сама по себе
# ничего не меняет: чтобы новая версия заработала, её ставите вы этой командой.
#
# Список закрыт: произвольный путь сюда не подставить.

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Пары «файл в репозитории -> имя команды в /usr/local/sbin»
declare -A HELPERS=(
    ["webui-deploy.sh"]="webui-deploy"
    ["webui-apt-install.sh"]="webui-apt-install"
    ["tls-letsencrypt.sh"]="webui-tls-issue"
)

if [ "$(id -u)" -ne 0 ]; then
    echo "нужен root: sudo bash $0" >&2
    exit 1
fi

for name in "${!HELPERS[@]}"; do
    src="$SRC/$name"
    dst="/usr/local/sbin/${HELPERS[$name]}"
    if [ ! -f "$src" ]; then
        echo "  пропуск: нет $src"
        continue
    fi
    if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
        echo "  $dst — без изменений"
        continue
    fi
    install -o root -g root -m 0755 "$src" "$dst"
    echo "  $name -> $dst"
done

echo
echo "Проверка прав (должно быть root:root и без w у прочих):"
ls -l /usr/local/sbin/webui-* 2>/dev/null

cat <<'EOF'

Дальше — применить список разрешённых команд, если он менялся:

    sudo bash infra/apply-sudo.sh

EOF
