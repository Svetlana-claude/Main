#!/bin/bash
# Проверка сверки `diff.sh` на поддельных снимках.
#
# Запуск:  bash bezopasnost/tests/check-diff.sh
#
# Каждый случай — это дефект, который проверка обязана ловить. Все три взяты не
# из головы: первый и второй найдены на прогоне, третий — изъян исходной
# инструкции, из-за которого VPN был бы отрезан молча.
set -uo pipefail
export LC_ALL=C

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

cp "$SRC"/config.sh "$SRC"/diff.sh "$WORK/"
mkdir -p "$WORK/baseline"

ok=0; bad=0
# Отступ не выравнивается пробелами: под LC_ALL=C длина строки считается в
# байтах, и кириллица разъезжает. Признак идёт первым — так он и читается.
pass() { ok=$((ok+1));  echo "  норма  — $1"; }
fail() { bad=$((bad+1)); echo "  ПРОВАЛ — $1"; }

check()   { if echo "$2" | grep -qF "$3"; then pass "$1"; else fail "$1"; fi; }
check_no() { if echo "$2" | grep -qF "$3"; then fail "$1"; else pass "$1"; fi; }

run_diff() { BASE="$WORK" bash "$WORK/diff.sh" "$1" "$2" 2>&1; }

# --- Случай 1: файрвол default-deny открыл только TCP, WireGuard на UDP ------
# Ровно та ловушка, о которой предупреждает §10 инструкции: сокеты слушают,
# фильтр их не пропускает, и никто этого не замечает.
cat > "$WORK/udp.txt" <<'EOF'
##LISTEN
tcp *:22 ((sshd))
tcp 0.0.0.0:80 ((nginx))
tcp 0.0.0.0:443 ((nginx))
udp 0.0.0.0:51820
##FIREWALL
v4_policy=-P INPUT DROP
v6_policy=-P INPUT DROP
v4 -A INPUT -p tcp -m tcp --dport 22 -m conntrack --ctstate NEW -j ACCEPT
v4 -A INPUT -p tcp -m multiport --dports 80,443 -m conntrack --ctstate NEW -j ACCEPT
v6 -A INPUT -p tcp -m tcp --dport 22 -m conntrack --ctstate NEW -j ACCEPT
v6 -A INPUT -p tcp -m multiport --dports 80,443 -m conntrack --ctstate NEW -j ACCEPT
fail2ban=active
EOF
cp "$WORK/udp.txt" "$WORK/udp-ref.txt"
out=$(run_diff "$WORK/udp.txt" "$WORK/udp-ref.txt")
check    "UDP-порт, не открытый файрволом, найден"            "$out" "по udp, но закрыты v4-файрволом"
check    "то же по IPv6"                                      "$out" "по udp, но закрыты v6-файрволом"
check    "в находке указан именно 51820"                      "$out" "порт 51820"
# Дуалстековый сокет `*:22` — вторая половина той же ловушки: фильтр по одному
# только 0.0.0.0 его не видит, и порт 22 попал бы в «закрытые» по ошибке.
check_no "порт 22 записан как «*:22» и закрытым не считается" "$out" "порт 22:"
check_no "порт 80 закрытым не считается"                      "$out" "порт 80:"

# --- Случай 2: политика не DROP — сверять сокеты с правилами нельзя ----------
# До установки файрвола незакрытый правилом порт закрытым не является. Прежняя
# версия объявляла отрезанными все службы разом, и отчёт превращался в крик.
cat > "$WORK/accept.txt" <<'EOF'
##LISTEN
tcp *:22 ((sshd))
udp 0.0.0.0:51820
##FIREWALL
v4_policy=
v6_policy=
fail2ban=active
EOF
cp "$WORK/accept.txt" "$WORK/accept-ref.txt"
out=$(run_diff "$WORK/accept.txt" "$WORK/accept-ref.txt")
check_no "при политике ACCEPT порты отрезанными не объявляются" "$out" "но закрыты"
check    "и об этом сказано прямо"                             "$out" "политика INPUT не DROP"

# --- Случай 3: порядок сортировки для comm ----------------------------------
# `sort -un` даёт 22,80,443,51820 — числовой порядок. comm ждёт
# лексикографического, на числовом он ругается и врёт результатом.
cat > "$WORK/sort.txt" <<'EOF'
##LISTEN
tcp 0.0.0.0:22 ((sshd))
tcp 0.0.0.0:80 ((nginx))
tcp 0.0.0.0:443 ((nginx))
tcp 0.0.0.0:51820 ((x))
##FIREWALL
v4_policy=-P INPUT DROP
v6_policy=-P INPUT DROP
v4 -A INPUT -p tcp -m multiport --dports 22,80,443,51820 -m conntrack --ctstate NEW -j ACCEPT
v6 -A INPUT -p tcp -m multiport --dports 22,80,443,51820 -m conntrack --ctstate NEW -j ACCEPT
fail2ban=active
EOF
cp "$WORK/sort.txt" "$WORK/sort-ref.txt"
out=$(run_diff "$WORK/sort.txt" "$WORK/sort-ref.txt")
check_no "все порты открыты — жалоб быть не должно" "$out" "но закрыты"
check_no "comm не ругается на порядок"              "$out" "not in sorted order"

# --- Случай 4: расхождение с эталоном ---------------------------------------
# Базовое: в снимке появилась учётка, которой нет в эталоне.
cat > "$WORK/base-ref.txt" <<'EOF'
##USERS
mokeeva uid=1000 shell=/bin/bash
##FIREWALL
v4_policy=-P INPUT DROP
v6_policy=-P INPUT DROP
fail2ban=active
EOF
cat > "$WORK/base-cur.txt" <<'EOF'
##USERS
mokeeva uid=1000 shell=/bin/bash
audit-probe uid=1001 shell=/bin/bash
##FIREWALL
v4_policy=-P INPUT DROP
v6_policy=-P INPUT DROP
fail2ban=active
EOF
out=$(run_diff "$WORK/base-cur.txt" "$WORK/base-ref.txt")
check "новая учётка попала в ПОЯВИЛОСЬ" "$out" "ПОЯВИЛОСЬ: audit-probe"

echo
echo "Совпало: $ok, провалов: $bad."
[ "$bad" -eq 0 ]
