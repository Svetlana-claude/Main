#!/usr/bin/env bash
# Отзыв клиента: пир убирается из конфига и тут же отключается от работающего сервера.
#
#   sudo ./remove-client.sh <имя>
#   sudo ./remove-client.sh --list      перечислить заведённых клиентов
#
# Конфиг клиента не удаляется, а переименовывается в <имя>.conf.revoked:
# по нему видно, кому и когда выдавали доступ.
set -euo pipefail

# Каталог переопределяется только ради проверок из tests/ — см. add-client.sh.
WG_DIR="${WG_DIR:-/etc/wireguard}"

info() { printf '==> %s\n' "$*"; }
die()  { printf 'Ошибка: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "нужны права root — запускайте через sudo"
[ -f "$WG_DIR/params" ] || die "сервер не настроен, сначала install-wireguard.sh"
# shellcheck disable=SC1091
. "$WG_DIR/params"

CONF="$WG_DIR/$WG_IFACE.conf"

if [ "${1:-}" = "--list" ]; then
    sed -n 's/^# client: //p' "$CONF" | sed 's/^/  /' || true
    exit 0
fi

NAME="${1:-}"
[ -n "$NAME" ] || die "не указано имя клиента (список: --list)"
MARKER="# client: $NAME"
grep -qxF "$MARKER" "$CONF" || die "клиента «$NAME» в конфиге нет (список: --list)"

cp "$CONF" "$CONF.bak"

# Блок пира — от строки-метки до ближайшей пустой строки или до конца файла.
awk -v marker="$MARKER" '
    skip { if ($0 ~ /^[[:space:]]*$/) skip = 0; next }
    $0 == marker { skip = 1; next }
    { print }
' "$CONF.bak" > "$CONF"
chmod 600 "$CONF"

# Отключаем прямо сейчас: syncconf убирает пиров, которых в конфиге не стало.
wg syncconf "$WG_IFACE" <(wg-quick strip "$WG_IFACE")

if [ -f "$WG_DIR/clients/$NAME.conf" ]; then
    mv "$WG_DIR/clients/$NAME.conf" "$WG_DIR/clients/$NAME.conf.revoked"
fi

info "Клиент «$NAME» отозван. Прежний конфиг сервера сохранён: $CONF.bak"
wg show "$WG_IFACE"
