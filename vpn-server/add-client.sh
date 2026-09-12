#!/usr/bin/env bash
# Добавление клиента (пира) к серверу WireGuard.
#
#   sudo ./add-client.sh <имя> [--out КАТАЛОГ] [--split]
#
#   <имя>           латиница, цифры, дефис и подчёркивание: ноутбук → notebook
#   --out КАТАЛОГ   положить копию конфига ещё и сюда (чтобы забрать по SFTP),
#                   права 600 и владелец — тот, кто вызвал sudo
#   --split         пустить через туннель только сеть самого туннеля,
#                   а не весь трафик (раздельная маршрутизация)
#
# Конфиг клиента печатается в виде QR-кода — для телефона этого достаточно,
# файл никуда переносить не нужно.
set -euo pipefail

# Каталог переопределяется только ради проверок из tests/ — в работе он всегда
# /etc/wireguard, потому что туда же смотрят wg-quick и служба.
WG_DIR="${WG_DIR:-/etc/wireguard}"

info() { printf '==> %s\n' "$*"; }
die()  { printf 'Ошибка: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "нужны права root — запускайте через sudo"
[ -f "$WG_DIR/params" ] || die "сервер не настроен, сначала install-wireguard.sh"
# shellcheck disable=SC1091
. "$WG_DIR/params"

NAME=""
OUT_DIR=""
SPLIT=0
while [ $# -gt 0 ]; do
    case "$1" in
        --out)   OUT_DIR="${2:-}"; [ -n "$OUT_DIR" ] || die "--out без каталога"; shift 2 ;;
        --split) SPLIT=1; shift ;;
        -*)      die "неизвестный ключ: $1" ;;
        *)       [ -z "$NAME" ] || die "имя уже задано: $NAME"; NAME="$1"; shift ;;
    esac
done

[ -n "$NAME" ] || die "не указано имя клиента"
printf '%s' "$NAME" | grep -qE '^[A-Za-z0-9_-]{1,32}$' \
    || die "имя может состоять только из латиницы, цифр, дефиса и подчёркивания (до 32 знаков)"

CONF="$WG_DIR/$WG_IFACE.conf"
MARKER="# client: $NAME"
grep -qxF "$MARKER" "$CONF" && die "клиент «$NAME» уже заведён"

# --- Свободный адрес в туннеле ---------------------------------------------
# Сервер занимает .1, клиенты идут с .2; берём первый незанятый.
used="$(sed -n "s|^AllowedIPs *= *${WG_NET//./\\.}\.\([0-9]\+\)/32.*|\1|p" "$CONF")"
octet=""
for n in $(seq 2 254); do
    printf '%s\n' "$used" | grep -qx "$n" || { octet="$n"; break; }
done
[ -n "$octet" ] || die "свободных адресов в сети $WG_NET.0/24 не осталось"
CLIENT_IP="$WG_NET.$octet"

# --- Ключи ------------------------------------------------------------------
umask 077
client_key="$(wg genkey)"
client_pub="$(printf '%s' "$client_key" | wg pubkey)"
psk="$(wg genpsk)"   # общий секрет поверх ключей: запас прочности на будущее

# --- Пир на сервере ---------------------------------------------------------
cat >> "$CONF" <<EOF

$MARKER
[Peer]
PublicKey = $client_pub
PresharedKey = $psk
AllowedIPs = $CLIENT_IP/32
EOF

# Применяем без перезапуска службы: syncconf не рвёт сессии остальных клиентов.
wg syncconf "$WG_IFACE" <(wg-quick strip "$WG_IFACE")

# --- Конфиг клиента ---------------------------------------------------------
if [ "$SPLIT" -eq 1 ]; then
    allowed="$WG_NET.0/24"
else
    allowed="0.0.0.0/0"
fi

mkdir -p "$WG_DIR/clients"
chmod 700 "$WG_DIR/clients"
CLIENT_CONF="$WG_DIR/clients/$NAME.conf"
cat > "$CLIENT_CONF" <<EOF
# Клиент «$NAME», заведён $(date '+%d.%m.%Y')
[Interface]
PrivateKey = $client_key
Address = $CLIENT_IP/32
DNS = $WG_DNS

[Peer]
PublicKey = $(cat "$WG_DIR/server.pub")
PresharedKey = $psk
Endpoint = $WG_ENDPOINT:$WG_PORT
AllowedIPs = $allowed
# Держим проход через NAT открытым, иначе сервер не достучится первым.
PersistentKeepalive = 25
EOF
chmod 600 "$CLIENT_CONF"

if [ -n "$OUT_DIR" ]; then
    mkdir -p "$OUT_DIR"
    cp "$CLIENT_CONF" "$OUT_DIR/$NAME.conf"
    chmod 600 "$OUT_DIR/$NAME.conf"
    if [ -n "${SUDO_USER:-}" ]; then
        chown "$SUDO_USER" "$OUT_DIR/$NAME.conf"
        chown "$SUDO_USER" "$OUT_DIR" 2>/dev/null || true
    fi
    info "Копия для переноса: $OUT_DIR/$NAME.conf (в файле закрытый ключ — не выкладывать в git)"
fi

info "Клиент «$NAME» заведён, адрес в туннеле $CLIENT_IP"
info "Файл на сервере: $CLIENT_CONF"
echo
echo "QR-код для телефона (приложение WireGuard → «+» → сканировать):"
echo
qrencode -t ansiutf8 < "$CLIENT_CONF"
