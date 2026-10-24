#!/usr/bin/env bash
# Сервер AmneziaWG рядом с прежним WireGuard и выдача клиентов для него.
#
#   sudo bash install-amneziawg.sh [имя ...]      по умолчанию — phone
#
# AmneziaWG — тот же WireGuard, но с маскировкой: мусорные пакеты перед
# рукопожатием, сдвиг размеров и свои заголовки. Оператор, который узнаёт и
# режет обычный WireGuard, такой трафик не опознаёт. Прежний wg0 не трогается:
# у него своя сеть, свой порт и свои клиенты.
#
# Повторный запуск безопасен: готовые ключи, параметры маскировки и клиенты
# не перезаписываются; для уже заведённого клиента просто заново печатается
# его QR-код.
#
# Настройки задаются переменными окружения (все необязательные):
#   AWG_PORT=443         порт UDP; 443 режут реже всего, nginx занимает 443 по TCP
#   AWG_NET=10.9.0       сеть внутри туннеля, /24; у wg0 — 10.8.0
#   AWG_DNS="1.1.1.1, 8.8.8.8"
#   AWG_MTU=1280         MTU клиента: мобильные сети большие пакеты теряют
#   AWG_ENDPOINT=1.2.3.4 внешний адрес, если определился неверно
#   NET_IFACE=eth0       внешний интерфейс, если определился неверно
set -euo pipefail

AWG_IFACE=awg0
AWG_DIR=/etc/amnezia/amneziawg

info() { printf '==> %s\n' "$*"; }
die()  { printf 'Ошибка: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "нужны права root — запускайте через sudo"

# Куда положить конфиги и QR-коды для переноса: exchange/vpn рядом с репозиторием.
OUT_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)/exchange/vpn"

# --- 1. Пакеты --------------------------------------------------------------
if ! command -v awg >/dev/null 2>&1; then
    info "Ставлю AmneziaWG из PPA amnezia (модуль ядра собирается DKMS, это пара минут)"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y software-properties-common "linux-headers-$(uname -r)" qrencode >/dev/null
    add-apt-repository -y ppa:amnezia/ppa >/dev/null
    apt-get update -qq
    apt-get install -y amneziawg amneziawg-tools >/dev/null
else
    info "AmneziaWG уже стоит"
fi
modprobe amneziawg 2>/dev/null \
    || die "модуль ядра amneziawg не загрузился, смотрите: dkms status"

# --- 2. Параметры установки -------------------------------------------------
umask 077
mkdir -p "$AWG_DIR"
chmod 700 "$AWG_DIR"

if [ -f "$AWG_DIR/params" ]; then
    info "Параметры уже есть — беру их ($AWG_DIR/params)"
    # shellcheck disable=SC1091
    . "$AWG_DIR/params"
else
    AWG_PORT="${AWG_PORT:-443}"
    AWG_NET="${AWG_NET:-10.9.0}"
    AWG_DNS="${AWG_DNS:-1.1.1.1, 8.8.8.8}"
    AWG_MTU="${AWG_MTU:-1280}"

    NET_IFACE="${NET_IFACE:-$(ip -4 route show default | awk '{print $5; exit}')}"
    [ -n "$NET_IFACE" ] || die "не определился внешний интерфейс — задайте NET_IFACE=..."
    if [ -z "${AWG_ENDPOINT:-}" ]; then
        AWG_ENDPOINT="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
    fi
    if [ -z "${AWG_ENDPOINT:-}" ]; then
        AWG_ENDPOINT="$(ip -4 -o addr show dev "$NET_IFACE" | awk '{print $4}' | cut -d/ -f1 | head -n1)"
    fi
    [ -n "$AWG_ENDPOINT" ] || die "не определился внешний адрес — задайте AWG_ENDPOINT=..."

    # Порт должен быть свободен по UDP: занятый кем-то ещё сервер не поднимет.
    listening=$(ss -lnu)
    case "$listening" in
        *":$AWG_PORT "*) die "порт $AWG_PORT/udp уже занят — задайте другой: AWG_PORT=51821" ;;
    esac

    # Маскировка. Те же числа обязаны стоять у каждого клиента, поэтому они
    # выбираются один раз и хранятся в params. S1 + 56 не должно равняться S2,
    # иначе пакеты рукопожатия двух видов совпадут по длине; H1–H4 различны и
    # больше 4 — значения 1–4 у обычного WireGuard.
    JC=$(shuf -i 3-6 -n 1)
    JMIN=40
    JMAX=70
    while :; do
        S1=$(shuf -i 15-150 -n 1)
        S2=$(shuf -i 15-150 -n 1)
        [ $((S1 + 56)) -ne "$S2" ] && break
    done
    read -r H1 H2 H3 H4 <<<"$(shuf -i 5-2147483647 -n 4 | tr '\n' ' ')"

    cat > "$AWG_DIR/params" <<EOF
# Параметры установки AmneziaWG. Читаются install-amneziawg.sh при повторном запуске.
AWG_PORT=$AWG_PORT
AWG_NET=$AWG_NET
AWG_DNS="$AWG_DNS"
AWG_MTU=$AWG_MTU
AWG_ENDPOINT=$AWG_ENDPOINT
NET_IFACE=$NET_IFACE
JC=$JC
JMIN=$JMIN
JMAX=$JMAX
S1=$S1
S2=$S2
H1=$H1
H2=$H2
H3=$H3
H4=$H4
EOF
    chmod 600 "$AWG_DIR/params"
fi

info "Внешний интерфейс: $NET_IFACE, адрес для клиентов: $AWG_ENDPOINT:$AWG_PORT/udp"

OBFS="Jc = $JC
Jmin = $JMIN
Jmax = $JMAX
S1 = $S1
S2 = $S2
H1 = $H1
H2 = $H2
H3 = $H3
H4 = $H4"

# --- 3. Ключи и конфиг сервера ----------------------------------------------
if [ ! -s "$AWG_DIR/server.key" ]; then
    info "Создаю ключевую пару сервера"
    awg genkey > "$AWG_DIR/server.key"
    awg pubkey < "$AWG_DIR/server.key" > "$AWG_DIR/server.pub"
fi
chmod 600 "$AWG_DIR/server.key"

CONF="$AWG_DIR/$AWG_IFACE.conf"
if [ ! -f "$CONF" ]; then
    info "Пишу $CONF"
    cat > "$CONF" <<EOF
# Сервер AmneziaWG. Клиенты добавляются install-amneziawg.sh <имя>.
[Interface]
Address = $AWG_NET.1/24
ListenPort = $AWG_PORT
PrivateKey = $(cat "$AWG_DIR/server.key")
$OBFS

# Правила — в начало цепочек, как у wg0: при включённом ufw дописанное в конец
# не сработает (см. install-wireguard.sh).
PostUp = iptables -I FORWARD 1 -i %i -j ACCEPT; iptables -I FORWARD 1 -o %i -j ACCEPT; iptables -t nat -I POSTROUTING 1 -s $AWG_NET.0/24 -o $NET_IFACE -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -s $AWG_NET.0/24 -o $NET_IFACE -j MASQUERADE
EOF
    chmod 600 "$CONF"
else
    info "Конфиг $CONF уже есть — не перезаписываю"
fi

# --- 4. Транзит и брандмауэр ------------------------------------------------
cat > /etc/sysctl.d/99-amneziawg.conf <<'EOF'
# Без этого сервер не пропускает пакеты клиентов в интернет.
net.ipv4.ip_forward = 1
EOF
sysctl -q --system

# ufw только дополняется и никогда не включается — иначе отрезало бы SSH.
ufw_state=$(ufw status 2>/dev/null | head -n1 || true)
if command -v ufw >/dev/null 2>&1 && [[ "$ufw_state" == *active* ]]; then
    info "ufw включён — открываю $AWG_PORT/udp"
    ufw allow "$AWG_PORT"/udp >/dev/null
fi

# --- 5. Запуск --------------------------------------------------------------
systemctl enable "awg-quick@$AWG_IFACE" >/dev/null 2>&1
if ! systemctl is-active --quiet "awg-quick@$AWG_IFACE"; then
    info "Поднимаю службу awg-quick@$AWG_IFACE"
    systemctl start "awg-quick@$AWG_IFACE"
fi
systemctl is-active --quiet "awg-quick@$AWG_IFACE" \
    || die "служба не поднялась, смотрите: journalctl -xeu awg-quick@$AWG_IFACE"

listening=$(ss -lnu)
case "$listening" in
    *":$AWG_PORT "*) ;;
    *) die "порт $AWG_PORT/udp никто не слушает" ;;
esac

# --- 6. Клиенты -------------------------------------------------------------
add_client() {
    local name="$1" marker used octet n key pub psk ip client_conf
    printf '%s' "$name" | grep -qE '^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$' \
        || die "имя «$name»: латиница, цифры, дефис, подчёркивание, до 15 знаков"

    client_conf="$AWG_DIR/clients/$name.conf"
    marker="# client: $name"
    if ! grep -qxF "$marker" "$CONF"; then
        used="$(sed -n "s|^AllowedIPs *= *${AWG_NET//./\\.}\.\([0-9]\+\)/32.*|\1|p" "$CONF")"
        octet=""
        for n in $(seq 2 254); do
            printf '%s\n' "$used" | grep -qx "$n" || { octet="$n"; break; }
        done
        [ -n "$octet" ] || die "свободных адресов в сети $AWG_NET.0/24 не осталось"
        ip="$AWG_NET.$octet"

        key="$(awg genkey)"
        pub="$(printf '%s' "$key" | awg pubkey)"
        psk="$(awg genpsk)"

        cat >> "$CONF" <<EOF

$marker
[Peer]
PublicKey = $pub
PresharedKey = $psk
AllowedIPs = $ip/32
EOF
        # syncconf не рвёт сессии остальных клиентов.
        awg syncconf "$AWG_IFACE" <(awg-quick strip "$AWG_IFACE")

        mkdir -p "$AWG_DIR/clients"
        chmod 700 "$AWG_DIR/clients"
        cat > "$client_conf" <<EOF
# Клиент AmneziaWG «$name», заведён $(date '+%d.%m.%Y')
[Interface]
PrivateKey = $key
Address = $ip/32
DNS = $AWG_DNS
MTU = $AWG_MTU
$OBFS

[Peer]
PublicKey = $(cat "$AWG_DIR/server.pub")
PresharedKey = $psk
Endpoint = $AWG_ENDPOINT:$AWG_PORT
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
EOF
        chmod 600 "$client_conf"
        info "Клиент «$name» заведён, адрес в туннеле $ip"
    else
        info "Клиент «$name» уже есть — печатаю его QR-код заново"
    fi

    mkdir -p "$OUT_DIR"
    cp "$client_conf" "$OUT_DIR/awg-$name.conf"
    qrencode -o "$OUT_DIR/awg-$name.png" -s 8 < "$client_conf"
    chmod 600 "$OUT_DIR/awg-$name.conf" "$OUT_DIR/awg-$name.png"
    [ -z "${SUDO_USER:-}" ] || chown "$SUDO_USER" "$OUT_DIR/awg-$name.conf" "$OUT_DIR/awg-$name.png"

    echo
    echo "QR-код «$name» — приложение AmneziaWG → «+» → «Создать из QR-кода»:"
    echo
    qrencode -t ansiutf8 < "$client_conf"
    echo "Копии: $OUT_DIR/awg-$name.conf и awg-$name.png (в них закрытый ключ — не в git)"
}

[ $# -gt 0 ] || set -- phone
for name in "$@"; do
    add_client "$name"
done

echo
info "Готово. AmneziaWG слушает $AWG_ENDPOINT:$AWG_PORT/udp, прежний WireGuard работает как раньше."
awg show "$AWG_IFACE" | grep -vi 'private key'
