#!/usr/bin/env bash
# Проверка выдачи и отзыва клиентов на поддельном /etc/wireguard.
#
#   ./tests/check-clients.sh
#
# Настоящего сервера не требует и ничего в системе не трогает: каталог задаётся
# через WG_DIR, root подделывается fakeroot, а команды wg/wg-quick подменяются
# заглушками в PATH. Настоящими остаются ровно те вызовы wg, что считают ключи
# (genkey, pubkey, genpsk) — их подделка обесценила бы проверку.
#
# Ловит три вещи, каждая из которых ломала бы работу молча:
#   1) выдачу двум клиентам одного адреса;
#   2) отзыв, уносящий вместе с указанным клиентом соседей по файлу;
#   3) неиспользование освободившегося адреса.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
umask 077          # в поддельном каталоге лежат настоящие ключи
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fail() { printf 'ПРОВАЛ: %s\n' "$*" >&2; exit 1; }
ok()   { printf '  ok: %s\n' "$*"; }

# --- Заглушки wg и wg-quick -------------------------------------------------
WG_REAL="$(command -v wg)"
[ -n "$WG_REAL" ] || fail "не найден wg — поставьте пакет wireguard"
mkdir -p "$WORK/bin"
cat > "$WORK/bin/wg" <<EOF
#!/usr/bin/env bash
# Счёт ключей отдаём настоящему wg, применение конфига к живому интерфейсу гасим.
case "\$1" in
    genkey|pubkey|genpsk) exec "$WG_REAL" "\$@" ;;
    syncconf|show|set)    exit 0 ;;
    *)                    exec "$WG_REAL" "\$@" ;;
esac
EOF
cat > "$WORK/bin/wg-quick" <<'EOF'
#!/usr/bin/env bash
# strip возвращает конфиг как есть: настоящий wg-quick читает только /etc/wireguard.
[ "${1:-}" = "strip" ] && exec cat "$WG_DIR/$2.conf"
exit 0
EOF
chmod +x "$WORK/bin/wg" "$WORK/bin/wg-quick"

# --- Поддельный /etc/wireguard ----------------------------------------------
export WG_DIR="$WORK/wg"
export PATH="$WORK/bin:$PATH"
mkdir -p "$WG_DIR"
"$WG_REAL" genkey > "$WG_DIR/server.key"
"$WG_REAL" pubkey < "$WG_DIR/server.key" > "$WG_DIR/server.pub"
cat > "$WG_DIR/params" <<'EOF'
WG_IFACE=wg0
WG_PORT=51820
WG_NET=10.8.0
WG_DNS="1.1.1.1, 8.8.8.8"
WG_ENDPOINT=198.51.100.7
NET_IFACE=eth0
EOF
cat > "$WG_DIR/wg0.conf" <<EOF
[Interface]
Address = 10.8.0.1/24
ListenPort = 51820
PrivateKey = $(cat "$WG_DIR/server.key")
EOF

run()     { fakeroot -- env "WG_DIR=$WG_DIR" "PATH=$PATH" bash "$@" >/dev/null; }
run_out() { fakeroot -- env "WG_DIR=$WG_DIR" "PATH=$PATH" bash "$@"; }

peer_ip() {   # адрес пира по имени, как он записан на сервере
    awk -v m="# client: $1" '
        $0 == m { found = 1; next }
        found && /^AllowedIPs/ { print $3; exit }
    ' "$WG_DIR/wg0.conf"
}

# --- 1. Трое клиентов получают разные адреса подряд --------------------------
for name in alpha beta gamma; do run "$ROOT/add-client.sh" "$name"; done
[ "$(peer_ip alpha)" = "10.8.0.2/32" ] || fail "alpha получил $(peer_ip alpha), ждали 10.8.0.2/32"
[ "$(peer_ip beta)"  = "10.8.0.3/32" ] || fail "beta получил $(peer_ip beta), ждали 10.8.0.3/32"
[ "$(peer_ip gamma)" = "10.8.0.4/32" ] || fail "gamma получил $(peer_ip gamma), ждали 10.8.0.4/32"
ok "трое клиентов получили разные адреса: .2, .3, .4"

# Адрес в конфиге клиента и в конфиге сервера — один и тот же.
grep -qx "Address = 10.8.0.3/32" "$WG_DIR/clients/beta.conf" \
    || fail "в конфиге beta адрес разошёлся с записью на сервере"
grep -q "Endpoint = 198.51.100.7:51820" "$WG_DIR/clients/beta.conf" \
    || fail "в конфиге beta нет адреса сервера из params"
grep -qx "AllowedIPs = 0.0.0.0/0" "$WG_DIR/clients/beta.conf" \
    || fail "по умолчанию через туннель должен идти весь трафик"
ok "конфиг клиента согласован с сервером"

# Открытый ключ клиента на сервере отвечает закрытому в его конфиге.
priv="$(sed -n 's/^PrivateKey = //p' "$WG_DIR/clients/beta.conf")"
pub_srv="$(awk '/^# client: beta$/ { f = 1; next } f && /^PublicKey/ { print $3; exit }' "$WG_DIR/wg0.conf")"
[ "$(printf '%s' "$priv" | "$WG_REAL" pubkey)" = "$pub_srv" ] \
    || fail "ключи разошлись: на сервере лежит не тот открытый ключ"
ok "пара ключей сходится"

# --- 2. Повторное имя не принимается ----------------------------------------
if run "$ROOT/add-client.sh" beta 2>/dev/null; then
    fail "клиент с занятым именем завёлся повторно"
fi
ok "повторное имя отклонено"

# --- 3. Отзыв убирает только своего пира ------------------------------------
run "$ROOT/remove-client.sh" beta
[ -z "$(peer_ip beta)" ] || fail "beta остался в конфиге после отзыва"
[ "$(peer_ip alpha)" = "10.8.0.2/32" ] || fail "отзыв beta унёс alpha"
[ "$(peer_ip gamma)" = "10.8.0.4/32" ] || fail "отзыв beta унёс gamma"
[ -f "$WG_DIR/clients/beta.conf.revoked" ] || fail "конфиг отозванного клиента не сохранён"
[ ! -f "$WG_DIR/clients/beta.conf" ] || fail "конфиг отозванного клиента остался действующим"
ok "отозван ровно один пир, соседи целы"

# Файл сервера остался разбираемым: пустых [Peer] и обрывков нет.
[ "$(grep -c '^\[Peer\]$' "$WG_DIR/wg0.conf")" = "2" ] || fail "в конфиге осталось не два пира"
ok "конфиг сервера не побился"

# --- 4. Освободившийся адрес переиспользуется --------------------------------
run "$ROOT/add-client.sh" delta
[ "$(peer_ip delta)" = "10.8.0.3/32" ] || fail "delta получил $(peer_ip delta), ждали освободившийся 10.8.0.3/32"
ok "освободившийся адрес отдан заново"

# --- 5. Раздельная маршрутизация --------------------------------------------
run "$ROOT/add-client.sh" split-one --split
grep -qx "AllowedIPs = 10.8.0.0/24" "$WG_DIR/clients/split-one.conf" \
    || fail "с ключом --split через туннель должна идти только сеть туннеля"
ok "ключ --split сужает маршрут"

# --- 6. Сводка по клиентам сшивает имена с трафиком ---------------------------
# Заглушка wg отдаёт дамп: alpha не подключался, delta качает.
alpha_pub="$(awk '/^# client: alpha$/ { f = 1; next } f && /^PublicKey/ { print $3; exit }' "$WG_DIR/wg0.conf")"
delta_pub="$(awk '/^# client: delta$/ { f = 1; next } f && /^PublicKey/ { print $3; exit }' "$WG_DIR/wg0.conf")"
cat > "$WORK/dump.tsv" <<EOF
srvkey	none	none	off
$alpha_pub	psk	(none)	10.8.0.2/32	0	0	0	off
$delta_pub	psk	203.0.113.9:12345	10.8.0.3/32	1757650000	4096	8192	25
EOF
cat > "$WORK/bin/wg" <<EOF
#!/usr/bin/env bash
case "\$1" in
    genkey|pubkey|genpsk) exec "$WG_REAL" "\$@" ;;
    show)                 [ "\${3:-}" = "dump" ] && exec cat "$WORK/dump.tsv"; exit 0 ;;
    syncconf|set)         exit 0 ;;
    *)                    exec "$WG_REAL" "\$@" ;;
esac
EOF
chmod +x "$WORK/bin/wg"

peers="$(run_out "$ROOT/list-peers.sh")"
line="$(printf '%s\n' "$peers" | awk -F'\t' '$1 == "delta"')"
[ -n "$line" ] || fail "delta не попал в сводку: $peers"
[ "$(printf '%s' "$line" | cut -f2)" = "10.8.0.3/32" ] || fail "у delta не тот адрес: $line"
[ "$(printf '%s' "$line" | cut -f4)" = "4096" ]        || fail "у delta не то «принято»: $line"
[ "$(printf '%s' "$line" | cut -f5)" = "8192" ]        || fail "у delta не то «передано»: $line"
[ "$(printf '%s' "$line" | cut -f6)" = "1757650000" ]  || fail "у delta не то рукопожатие: $line"
[ "$(printf '%s' "$line" | cut -f7)" = "203.0.113.9:12345" ] || fail "у delta не тот адрес клиента: $line"
alpha_line="$(printf '%s\n' "$peers" | awk -F'\t' '$1 == "alpha"')"
[ "$(printf '%s' "$alpha_line" | cut -f6)" = "0" ] || fail "alpha не подключался, рукопожатие должно быть 0: $alpha_line"
[ "$(printf '%s' "$alpha_line" | cut -f7)" = "" ]  || fail "у неподключавшегося alpha не должно быть адреса: $alpha_line"
ok "сводка сшивает имена с трафиком по открытому ключу"

# --- 7. Имя с посторонними знаками не принимается -----------------------------
if run "$ROOT/add-client.sh" 'a b;rm' 2>/dev/null; then
    fail "имя с пробелом и точкой с запятой прошло проверку"
fi
ok "имя с посторонними знаками отклонено"

echo "Все проверки пройдены."
