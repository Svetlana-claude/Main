#!/usr/bin/env bash
# Установка и настройка WireGuard-сервера: пакеты, ключи, конфиг интерфейса,
# транзит пакетов, брандмауэр, автозапуск.
#
#   sudo ./install-wireguard.sh
#
# Повторный запуск безопасен: готовые ключи и конфиг не перезаписываются,
# уже заведённые клиенты не теряются.
#
# Настройки задаются переменными окружения (все необязательные):
#   WG_PORT=51820        порт UDP, на котором слушает сервер
#   WG_NET=10.8.0        сеть внутри туннеля, /24; сервер получает адрес .1
#   WG_DNS="1.1.1.1, 8.8.8.8"   DNS, который пропишется клиентам
#   WG_ENDPOINT=1.2.3.4  внешний адрес или имя сервера, если определился неверно
#   NET_IFACE=eth0       внешний сетевой интерфейс, если определился неверно
set -euo pipefail

WG_IFACE="${WG_IFACE:-wg0}"
WG_PORT="${WG_PORT:-51820}"
WG_NET="${WG_NET:-10.8.0}"
WG_DNS="${WG_DNS:-1.1.1.1, 8.8.8.8}"
WG_DIR=/etc/wireguard

info() { printf '==> %s\n' "$*"; }
die()  { printf 'Ошибка: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "нужны права root — запускайте через sudo"

# --- 1. Внешний интерфейс и внешний адрес -----------------------------------
NET_IFACE="${NET_IFACE:-$(ip -4 route show default | awk '{print $5; exit}')}"
[ -n "$NET_IFACE" ] || die "не определился внешний интерфейс — задайте NET_IFACE=..."

if [ -z "${WG_ENDPOINT:-}" ]; then
    # Сначала спрашиваем внешний адрес у стороннего сервиса: за NAT адрес
    # на интерфейсе может быть внутренним и в конфиг клиента не годится.
    WG_ENDPOINT="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
fi
if [ -z "${WG_ENDPOINT:-}" ]; then
    WG_ENDPOINT="$(ip -4 -o addr show dev "$NET_IFACE" | awk '{print $4}' | cut -d/ -f1 | head -n1)"
fi
[ -n "$WG_ENDPOINT" ] || die "не определился внешний адрес — задайте WG_ENDPOINT=..."

info "Внешний интерфейс: $NET_IFACE, адрес для клиентов: $WG_ENDPOINT:$WG_PORT/udp"

# --- 2. Пакеты --------------------------------------------------------------
if ! command -v wg >/dev/null 2>&1 || ! command -v qrencode >/dev/null 2>&1; then
    info "Ставлю пакеты: wireguard, qrencode"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y wireguard qrencode >/dev/null
else
    info "Пакеты уже стоят"
fi

# --- 3. Ключи сервера -------------------------------------------------------
umask 077
mkdir -p "$WG_DIR"
chmod 700 "$WG_DIR"
if [ ! -s "$WG_DIR/server.key" ]; then
    info "Создаю ключевую пару сервера"
    wg genkey > "$WG_DIR/server.key"
    wg pubkey < "$WG_DIR/server.key" > "$WG_DIR/server.pub"
else
    info "Ключи сервера уже есть — не трогаю"
fi
chmod 600 "$WG_DIR/server.key"

# --- 4. Общие параметры для скриптов управления клиентами -------------------
cat > "$WG_DIR/params" <<EOF
# Параметры установки. Читаются add-client.sh и remove-client.sh.
WG_IFACE=$WG_IFACE
WG_PORT=$WG_PORT
WG_NET=$WG_NET
WG_DNS="$WG_DNS"
WG_ENDPOINT=$WG_ENDPOINT
NET_IFACE=$NET_IFACE
EOF
chmod 600 "$WG_DIR/params"

# --- 5. Конфиг интерфейса ---------------------------------------------------
CONF="$WG_DIR/$WG_IFACE.conf"
if [ ! -f "$CONF" ]; then
    info "Пишу $CONF"
    cat > "$CONF" <<EOF
# Сервер WireGuard. Пиры добавляются скриптом add-client.sh — правьте файл через него.
[Interface]
Address = $WG_NET.1/24
ListenPort = $WG_PORT
PrivateKey = $(cat "$WG_DIR/server.key")

# Пропуск транзитных пакетов и подмена обратного адреса на внешний.
# Правила вставляются в НАЧАЛО цепочек (-I ... 1), а не дописываются в конец:
# при включённом ufw его собственный переход стоит первым и до дописанного
# в конец правила дело не дойдёт — туннель поднимется, а трафик не пойдёт.
PostUp = iptables -I FORWARD 1 -i %i -j ACCEPT; iptables -I FORWARD 1 -o %i -j ACCEPT; iptables -t nat -I POSTROUTING 1 -s $WG_NET.0/24 -o $NET_IFACE -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -s $WG_NET.0/24 -o $NET_IFACE -j MASQUERADE
EOF
    chmod 600 "$CONF"
else
    info "Конфиг $CONF уже есть — не перезаписываю (иначе пропали бы клиенты)"
fi

# --- 6. Транзит пакетов -----------------------------------------------------
cat > /etc/sysctl.d/99-wireguard.conf <<'EOF'
# Без этого сервер не пропускает пакеты клиентов в интернет.
net.ipv4.ip_forward = 1
EOF
sysctl -q --system

# --- 7. Брандмауэр ----------------------------------------------------------
# ufw здесь только дополняется и НИКОГДА не включается: включение с настройками
# по умолчанию отрезало бы SSH, а сервер удалённый — вернуться было бы некуда.
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | head -n1 | grep -q active; then
    info "ufw включён — открываю $WG_PORT/udp (и на всякий случай 22/tcp)"
    ufw allow 22/tcp >/dev/null
    ufw allow "$WG_PORT"/udp >/dev/null
else
    info "ufw выключен — открывать порт не нужно; сам ufw не включаю"
fi

# --- 8. Запуск --------------------------------------------------------------
systemctl enable "wg-quick@$WG_IFACE" >/dev/null 2>&1
if systemctl is-active --quiet "wg-quick@$WG_IFACE"; then
    info "Перечитываю настройки работающей службы"
    wg syncconf "$WG_IFACE" <(wg-quick strip "$WG_IFACE")
else
    info "Поднимаю службу wg-quick@$WG_IFACE"
    systemctl start "wg-quick@$WG_IFACE"
fi

systemctl is-active --quiet "wg-quick@$WG_IFACE" \
    || die "служба не поднялась, смотрите: journalctl -xeu wg-quick@$WG_IFACE"

# --- 9. Проверки на месте ---------------------------------------------------
[ "$(sysctl -n net.ipv4.ip_forward)" = "1" ] || die "транзит пакетов так и не включился"
ss -lnup | grep -q ":$WG_PORT " || die "порт $WG_PORT/udp никто не слушает"

echo
info "Готово. Сервер слушает $WG_ENDPOINT:$WG_PORT/udp, адрес в туннеле $WG_NET.1"
echo
echo "Дальше — завести клиента:"
# Запущенные из /usr/local/lib копии вызываются только через обёртку webui-vpn,
# показывать её служебный путь как команду бессмысленно.
case "$(readlink -f "$0")" in
    /usr/local/lib/webui-vpn/*) echo "    sudo webui-vpn add notebook" ;;
    *)                          echo "    sudo $(dirname "$(readlink -f "$0")")/add-client.sh notebook" ;;
esac
echo
wg show "$WG_IFACE"
