#!/bin/bash
# Проверка отката файрвола `firewall-rollback.sh`.
#
# Запуск:  bash bezopasnost/tests/check-rollback.sh
#
# Поводом стал отказ 12.09.2026: откат вернул IPv4, а IPv6 оставил в DROP с
# новыми правилами — снимок «до» по IPv6 был пуст, и восстановление из пустого
# файла ничего не сделало. Откат, который откатывает не всё, хуже отсутствия
# отката: он создаёт уверенность, что всё вернулось.
#
# Настоящие iptables здесь не трогаются: вместо них в PATH лежат заглушки,
# которые записывают, что с ними сделали.
set -uo pipefail
export LC_ALL=C

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/firewall-rollback.sh"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

ok=0; bad=0
pass() { ok=$((ok+1));  echo "  норма  — $1"; }
fail() { bad=$((bad+1)); echo "  ПРОВАЛ — $1"; }

# Заглушки: пишут вызов в журнал. *-restore читает stdin, чтобы было видно,
# что ему подали.
mkdir -p "$WORK/bin"
for t in iptables ip6tables; do
  cat > "$WORK/bin/$t" <<EOF
#!/bin/bash
echo "$t \$*" >> "$WORK/calls"
EOF
  cat > "$WORK/bin/$t-restore" <<EOF
#!/bin/bash
echo "$t-restore <\$(wc -c | tr -d ' ') байт>" >> "$WORK/calls"
EOF
done
printf '#!/bin/bash\nexit 0\n' > "$WORK/bin/logger"
chmod +x "$WORK/bin/"*

run() { # подготовка: $1 — размер снимка v4, $2 — размер снимка v6 (0 = пустой, - = нет файла)
  rm -rf "$WORK/base" "$WORK/calls"; mkdir -p "$WORK/base/backup"; : > "$WORK/calls"
  for pair in "v4:$1" "v6:$2"; do
    fam=${pair%%:*}; size=${pair##*:}
    [ "$size" = "-" ] && continue
    head -c "$size" /dev/zero | tr '\0' 'x' > "$WORK/base/backup/rules.$fam.before-X"
    ln -s "rules.$fam.before-X" "$WORK/base/backup/rules.$fam.last"
  done
  BASE="$WORK/base" PATH="$WORK/bin:$PATH" bash "$SRC" >/dev/null 2>&1
}

echo "Случай 12.09.2026: снимок IPv4 есть, снимок IPv6 пуст:"
run 500 0
grep -q '^iptables-restore <500 байт>' "$WORK/calls" \
  && pass "IPv4 восстановлен из снимка" || fail "IPv4 не восстановлен из снимка"
grep -q '^ip6tables -P INPUT ACCEPT' "$WORK/calls" \
  && pass "IPv6 при пустом снимке: политика возвращена в ACCEPT" \
  || fail "IPv6 при пустом снимке остался как был — ровно дефект 12.09"
grep -q '^ip6tables -F INPUT' "$WORK/calls" \
  && pass "IPv6 при пустом снимке: цепочка INPUT очищена" \
  || fail "IPv6 при пустом снимке: новые правила остались"
grep -q '^ip6tables-restore' "$WORK/calls" \
  && fail "из пустого снимка IPv6 всё равно пытались восстанавливать" \
  || pass "из пустого снимка восстановление не вызывалось"

echo
echo "Порядок при открытии: сперва ACCEPT, потом очистка:"
# Наоборот — между двумя командами цепочка пуста при DROP, и режется всё,
# включая сессию, из которой откатываемся.
p=$(grep -n '^ip6tables -P INPUT ACCEPT' "$WORK/calls" | cut -d: -f1)
f=$(grep -n '^ip6tables -F INPUT' "$WORK/calls" | cut -d: -f1)
[ -n "$p" ] && [ -n "$f" ] && [ "$p" -lt "$f" ] \
  && pass "ACCEPT выставлен раньше очистки" || fail "очистка идёт раньше ACCEPT (строки $p и $f)"

echo
echo "Снимка нет вовсе (откат без предшествующего применения):"
run - -
grep -q '^iptables -P INPUT ACCEPT' "$WORK/calls" && grep -q '^ip6tables -P INPUT ACCEPT' "$WORK/calls" \
  && pass "оба семейства открыты" || fail "без снимков хотя бы одно семейство не открыто"

echo
echo "Оба снимка есть:"
run 300 200
grep -q '^iptables-restore <300 байт>' "$WORK/calls" && grep -q '^ip6tables-restore <200 байт>' "$WORK/calls" \
  && pass "оба восстановлены из своих снимков" || fail "восстановление из снимков не выполнено"
grep -q -- '-F INPUT' "$WORK/calls" \
  && fail "при годных снимках цепочки зачем-то очищались" || pass "лишней очистки нет"

echo
echo "Совпало: $ok, провалов: $bad."
[ "$bad" -eq 0 ]
