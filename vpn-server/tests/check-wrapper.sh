#!/usr/bin/env bash
# Проверка root-обёртки infra/webui-vpn.sh — того рубежа, на котором отсекаются
# лишние доводы. Обёртка разрешена беспарольно, поэтому цена дыры в её разборе
# доводов — беспарольный root, и проверяется здесь именно разбор.
#
#   ./tests/check-wrapper.sh
#
# Ничего не устанавливает и не запускает: все случаи ниже отсекаются до того,
# как обёртка доберётся до рабочих скриптов. Root подделывается fakeroot.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Путь переопределяется только ради прогона на намеренно сломанной копии.
WRAPPER="${WEBUI_VPN_WRAPPER:-$(dirname "$(dirname "$HERE")")/infra/webui-vpn.sh}"
[ -f "$WRAPPER" ] || { echo "не найден webui-vpn.sh: $WRAPPER" >&2; exit 1; }

fail() { printf 'ПРОВАЛ: %s\n' "$*" >&2; exit 1; }
ok()   { printf '  ok: %s\n' "$*"; }

# Запуск обёртки под поддельным root. WEBUI_VPN_CHECK=1 велит ей показать
# разобранную команду вместо запуска: так проверка ничего не устанавливает и
# остаётся годной даже после того, как рабочая копия ляжет в /usr/local/lib.
run() {
    set +e
    OUT="$(fakeroot -- env WEBUI_VPN_CHECK=1 /bin/bash "$WRAPPER" "$@" 2>&1)"
    RC=$?
    set -e
}

# Довод обязан быть отвергнут разбором. Одного ненулевого кода мало: обёртка
# могла споткнуться и позже, уже пропустив негодный довод внутрь. Поэтому
# главное здесь — «ЗАПУСТИЛ БЫ» в выводе быть не должно.
refuse() {
    local what="$1"; shift
    run "$@"
    if printf '%s' "$OUT" | grep -q 'ЗАПУСТИЛ БЫ'; then
        fail "$what — довод прошёл разбор и дошёл до запуска: $OUT"
    fi
    [ "$RC" -ne 0 ] || fail "$what — принято, а должно быть отвергнуто (вывод: $OUT)"
    printf '%s' "$OUT" | grep -q 'ОТКАЗ' || fail "$what — отвергнуто без внятного отказа: $OUT"
    ok "$what отвергнуто"
}

# --- Неизвестные команды -----------------------------------------------------
refuse "неизвестная команда"            bash
refuse "команда с путём"                /bin/sh

# --- Имя клиента -------------------------------------------------------------
refuse "add без имени"                  add
refuse "имя с пробелом и «;»"           add 'phone; id'
refuse "имя с путём"                    add ../../etc/passwd
refuse "имя-флаг"                       add --help
refuse "имя длиннее 32 знаков"          add "$(printf 'a%.0s' $(seq 1 33))"
# shellcheck disable=SC2016  # одинарные кавычки здесь и нужны: подстановка передаётся буквально
refuse "имя с подстановкой"             add 'phone$(id)'

# --- Лишние и чужие ключи ----------------------------------------------------
refuse "произвольный --out"             add phone --out /tmp
refuse "лишний довод после --split"     add phone --split ещё
refuse "чужой ключ у add"               add phone --dns 8.8.8.8
refuse "два имени у remove"             remove phone notebook
refuse "довод у list"                   list лишнее
refuse "довод у peers"                  peers лишнее
refuse "довод у status"                 status лишнее

# --- Порт --------------------------------------------------------------------
refuse "порт не число"                  install --port abc
refuse "порт нулевой"                   install --port 0
refuse "порт за пределом"               install --port 70000
refuse "лишний довод у install"         install --port 51820 ещё
refuse "чужой ключ у install"           install -o 'APT::Update::Pre-Invoke=id'

# --- Годные доводы доходят до рабочих скриптов в неизменном виде -------------
LIB=/usr/local/lib/webui-vpn
OUT_DIR=/home/mokeeva/main/exchange/vpn
expect() {
    local want="$1"; shift
    run "$@"
    [ "$RC" -eq 0 ] || fail "«$*» отвергнуто, а должно было пройти: $OUT"
    [ "$OUT" = "ЗАПУСТИЛ БЫ: $want" ] \
        || fail "«$*» разобрано не так:
   ждали: ЗАПУСТИЛ БЫ: $want
   вышло: $OUT"
    ok "«$*» → $want"
}
expect "$LIB/add-client.sh phone --out $OUT_DIR"            add phone
expect "$LIB/add-client.sh phone --split --out $OUT_DIR"    add phone --split
expect "$LIB/remove-client.sh phone"                        remove phone
expect "$LIB/remove-client.sh --list"                       list
expect "$LIB/list-peers.sh "                                peers
expect "$LIB/install-wireguard.sh "                         install
expect "WG_PORT=443 $LIB/install-wireguard.sh "             install --port 443

# --- Без root обёртка не работает --------------------------------------------
set +e
OUT="$(/bin/bash "$WRAPPER" list 2>&1)"; RC=$?
set -e
[ "$RC" -ne 0 ] || fail "обёртка сработала без root"
printf '%s' "$OUT" | grep -q 'нужен root' || fail "без root нет внятного отказа: $OUT"
ok "без root обёртка отказывает"

echo "Все проверки пройдены."
