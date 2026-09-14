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
    ["webui-vpn.sh"]="webui-vpn"
    ["webui-sec.sh"]="webui-sec"
)

# Обёртка webui-vpn запускает не сами скрипты из vpn-server/ — тот каталог
# доступен на запись пользователю и агенту, и запуск оттуда от root означал бы
# беспарольный root целиком, — а их root-овую копию. Список закрыт.
VPN_SRC="$(dirname "$SRC")/vpn-server"
VPN_LIB=/usr/local/lib/webui-vpn
VPN_SCRIPTS=(install-wireguard.sh add-client.sh remove-client.sh list-peers.sh)

# То же и для аудита: код под root в /opt/secaudit, состояние под пользователем
# в /var/lib/secaudit. Разнесены намеренно — каталог, доступный пользователю на
# запись, плюс разрешение запускать оттуда collect.sh от root равносильны
# беспарольному root целиком.
SEC_SRC="$(dirname "$SRC")/bezopasnost"
SEC_LIB=/opt/secaudit
SEC_STATE=/var/lib/secaudit
SEC_SCRIPTS=(collect.sh diff.sh remediate.sh apply-firewall.sh firewall-rollback.sh audit.sh)
SEC_DATA=(config.sh CONTEXT.md)

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

install -o root -g root -m 0755 -d "$VPN_LIB"
for name in "${VPN_SCRIPTS[@]}"; do
    src="$VPN_SRC/$name"
    dst="$VPN_LIB/$name"
    if [ ! -f "$src" ]; then
        echo "  пропуск: нет $src"
        continue
    fi
    if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
        echo "  $dst — без изменений"
        continue
    fi
    install -o root -g root -m 0755 "$src" "$dst"
    echo "  vpn-server/$name -> $dst"
done

if [ -d "$SEC_SRC" ]; then
    install -o root -g root -m 755 -d "$SEC_LIB" "$SEC_LIB/baseline" "$SEC_LIB/backup"
    # Карантин закрыт наглухо: там лежит изъятое, в том числе исполняемое.
    install -o root -g root -m 700 -d "$SEC_LIB/quarantine"
    # Состояние — пользователю: audit.sh работает от него и root не получает.
    install -o "$SUDO_USER" -g "$SUDO_USER" -m 700 -d \
        "$SEC_STATE" "$SEC_STATE/snapshots" "$SEC_STATE/reports" 2>/dev/null \
        || echo "  ВНИМАНИЕ: не удалось завести $SEC_STATE для пользователя — задайте владельца вручную"

    for name in "${SEC_SCRIPTS[@]}"; do
        src="$SEC_SRC/$name"; dst="$SEC_LIB/$name"
        [ -f "$src" ] || { echo "  пропуск: нет $src"; continue; }
        if [ -f "$dst" ] && cmp -s "$src" "$dst"; then echo "  $dst — без изменений"; continue; fi
        install -o root -g root -m 755 "$src" "$dst"
        echo "  bezopasnost/$name -> $dst"
    done
    for name in "${SEC_DATA[@]}"; do
        src="$SEC_SRC/$name"; dst="$SEC_LIB/$name"
        [ -f "$src" ] || { echo "  пропуск: нет $src"; continue; }
        if [ -f "$dst" ] && cmp -s "$src" "$dst"; then echo "  $dst — без изменений"; continue; fi
        install -o root -g root -m 644 "$src" "$dst"
        echo "  bezopasnost/$name -> $dst"
    done
fi

echo
echo "Проверка прав (должно быть root:root и без w у прочих):"
ls -l /usr/local/sbin/webui-* 2>/dev/null
ls -l "$VPN_LIB" 2>/dev/null
ls -ld "$SEC_LIB" "$SEC_LIB/quarantine" "$SEC_STATE" 2>/dev/null

cat <<'EOF'

Дальше — применить список разрешённых команд, если он менялся:

    sudo bash infra/apply-sudo.sh

EOF
