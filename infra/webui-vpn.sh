#!/bin/bash
# Управление VPN-сервером WireGuard — беспарольный шаг агента.
#
#     sudo webui-vpn install [--port ЧИСЛО]   поставить и поднять сервер
#     sudo webui-vpn add ИМЯ [--split]        завести клиента
#     sudo webui-vpn remove ИМЯ               отозвать клиента
#     sudo webui-vpn list                     перечислить клиентов
#     sudo webui-vpn status                   состояние интерфейса
#
# Ставится в /usr/local/sbin/webui-vpn владельцем root и БЕЗ права записи
# пользователю — иначе разрешение на обёртку означало бы разрешение запускать
# от root любой код: достаточно переписать файл. Отсюда же следствие: правка
# этого файла в репозитории сама по себе ничего не меняет, новую версию ставите
# вы командой `sudo bash infra/install-root-helpers.sh`.
#
# ПОЧЕМУ ОБЁРТКА НЕ ЗАПУСКАЕТ СКРИПТЫ ИЗ ~/main/vpn-server. Тот каталог доступен
# на запись пользователю и агенту. Запусти обёртка код оттуда — строка в
# sudo-allowed.list была бы просто беспарольным root: агент переписал бы
# add-client.sh и получил исполнение чего угодно. Поэтому install-root-helpers.sh
# кладёт рядом root-овую копию в /usr/local/lib/webui-vpn, и работа идёт с ней,
# а обёртка перед запуском проверяет владельца и права этой копии.
#
# ЧТО ЭТА ОБЁРТКА ВСЁ-ТАКИ ДАЁТ АГЕНТУ. Установка пишет в /etc, правит sysctl и
# iptables — то есть по существу это root-шаг, сужённый до одного дела. Кроме
# того, `add` выкладывает конфиг клиента с закрытым ключом в exchange/vpn, а
# значит тот, кто получит доступ к учётной записи mokeeva, получит и доступ к
# самому VPN. Это осознанная плата за то, чтобы агент мог заводить и отзывать
# клиентов без вашего участия.

set -euo pipefail

LIB=/usr/local/lib/webui-vpn
OUT_DIR=/home/mokeeva/main/exchange/vpn   # задан жёстко: произвольный путь
                                          # означал бы запись файла от root куда угодно
WG=/usr/bin/wg

die() { echo "ОТКАЗ: $*" >&2; exit 1; }

usage() {
    sed -n '3,9p' "$0" | sed 's/^# \{0,1\}//'
}

if [ "$(id -u)" -ne 0 ]; then
    echo "нужен root: sudo webui-vpn <команда>" >&2
    exit 1
fi

# Имя клиента: латиница, цифры, дефис и подчёркивание, первым знаком — буква
# или цифра. Начало важно отдельно: разреши образец ведущий дефис — и «--help»
# или любой другой флаг прошёл бы проверку как имя и уехал бы в рабочий скрипт
# отдельным доводом.
check_name() {
    [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$ ]] \
        || die "«$1» не годится в имя клиента: латиница, цифры, дефис и подчёркивание, первым знаком буква или цифра, до 32 знаков"
}

# Запускаемый файл обязан принадлежать root и быть закрыт на запись прочим.
run_lib() {
    local script="$LIB/$1"; shift
    # Ради проверок из vpn-server/tests: показать разобранную команду и выйти,
    # ничего не запуская. На безопасность не влияет — исполнения здесь нет, а
    # через sudo сюда и не попасть: env_reset вычищает окружение.
    if [ -n "${WEBUI_VPN_CHECK:-}" ]; then
        printf 'ЗАПУСТИЛ БЫ: %s%s %s\n' "${WG_PORT:+WG_PORT=$WG_PORT }" "$script" "$*"
        exit 0
    fi
    [ -f "$script" ] || die "не установлен $script — выполните: sudo bash infra/install-root-helpers.sh"
    local st perm
    st="$(stat -c '%U %a' "$script")"
    [[ "$st" == "root "* ]] || die "$script принадлежит не root — запускать его от root нельзя"
    perm="${st##* }"
    if (( 8#$perm & 0022 )); then
        die "$script доступен на запись не только root — запускать его от root нельзя"
    fi
    exec /bin/bash "$script" "$@"
}

cmd="${1:-}"
[ $# -gt 0 ] && shift

case "$cmd" in
    install)
        if [ $# -gt 0 ]; then
            if [ "$1" != "--port" ] || [ $# -ne 2 ]; then
                die "install принимает только «--port ЧИСЛО»"
            fi
            if ! [[ "$2" =~ ^[0-9]{1,5}$ ]] || [ "$2" -lt 1 ] || [ "$2" -gt 65535 ]; then
                die "порт должен быть числом от 1 до 65535"
            fi
            export WG_PORT="$2"   # установщик читает порт из окружения
        fi
        run_lib install-wireguard.sh
        ;;
    add)
        [ $# -ge 1 ] || die "нужно имя клиента: webui-vpn add ИМЯ [--split]"
        check_name "$1"
        name="$1"; shift
        split=()
        if [ $# -gt 0 ]; then
            if [ "$1" != "--split" ] || [ $# -ne 1 ]; then
                die "у add допустим только ключ --split"
            fi
            split=(--split)
        fi
        run_lib add-client.sh "$name" "${split[@]}" --out "$OUT_DIR"
        ;;
    remove)
        [ $# -eq 1 ] || die "нужно ровно одно имя: webui-vpn remove ИМЯ"
        check_name "$1"
        run_lib remove-client.sh "$1"
        ;;
    list)
        [ $# -eq 0 ] || die "list доводов не принимает"
        run_lib remove-client.sh --list
        ;;
    status)
        [ $# -eq 0 ] || die "status доводов не принимает"
        exec "$WG" show
        ;;
    ""|-h|--help|help)
        usage
        exit 0
        ;;
    *)
        echo "ОТКАЗ: неизвестная команда «$cmd»." >&2
        usage >&2
        exit 1
        ;;
esac
