#!/bin/bash
# Проверка того, как `pg-backup.sh` проверяет свою выгрузку.
#
# Запуск:  bash infra/tests/check-backup-verify.sh
#
# Поводом стал отказ 11–12.09.2026: годные выгрузки объявлялись негодными и
# УДАЛЯЛИСЬ. Причина — `gunzip -c ФАЙЛ | grep -q ОБРАЗЕЦ` при `set -o pipefail`:
# `grep -q` выходит по первому совпадению, `gunzip` получает SIGPIPE и отдаёт
# 141, и это становится кодом всего конвейера. Пока база была маленькой,
# `gunzip` успевал дочитать — ошибка ждала роста данных.
#
# Стенд работает на поддельных выгрузках и к настоящей базе не обращается.
set -uo pipefail
export LC_ALL=C

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

ok=0; bad=0
pass() { ok=$((ok+1));  echo "  норма  — $1"; }
fail() { bad=$((bad+1)); echo "  ПРОВАЛ — $1"; }

TABLES="users sessions projects conversations messages files settings"

# Поддельная выгрузка: девять таблиц и отметка о завершении. Размер задаётся
# доводом — на маленьком файле ошибка не воспроизводится, нужен крупный.
make_dump() { # $1 — файл, $2 — сколько строк «данных» подсыпать
  {
    echo "-- PostgreSQL database dump"
    for t in $TABLES login_attempts metrics_history; do
      echo "CREATE TABLE public.$t ("
      echo "    id integer NOT NULL"
      echo ");"
    done
    seq 1 "$2" | sed 's/^/-- строка данных /'
    echo "-- PostgreSQL database dump complete"
  } | gzip -9 > "$1"
}

# Проверка ровно в том виде, в каком она в pg-backup.sh сейчас.
verify_now() { # $1 — файл; печатает список недостающих
  local dump="$1" found missing=""
  found=$(gunzip -c "$dump" | grep -oE '^CREATE TABLE public\.[a-z_]+|PostgreSQL database dump complete')
  case "$found" in
    *'PostgreSQL database dump complete'*) ;;
    *) echo "ОБРЕЗАНА"; return ;;
  esac
  for t in $TABLES; do
    case "$found" in
      *"CREATE TABLE public.$t"*) ;;
      *) missing="$missing $t" ;;
    esac
  done
  echo "$missing"
}

# Прежняя проверка — дословно, для сравнения.
verify_before() { # $1 — файл
  local dump="$1" missing=""
  for t in $TABLES; do
    gunzip -c "$dump" | grep -q "CREATE TABLE public.$t" || missing="$missing $t"
  done
  echo "$missing"
}

echo "Крупная годная выгрузка (та, на которой всё и сломалось):"
make_dump "$WORK/big.sql.gz" 20000
res=$(verify_now "$WORK/big.sql.gz")
[ -z "$res" ] && pass "нынешняя проверка не находит недостающих" \
               || fail "нынешняя проверка объявила недостающими:$res"

# Тот же файл прежней проверкой. Если она НЕ ошиблась — стенд бесполезен:
# значит воспроизвести дефект не удалось, и зелёный результат выше ничего
# не доказывает (правило 12).
res=$(verify_before "$WORK/big.sql.gz")
[ -n "$res" ] && pass "прежняя проверка на том же файле ошибается:$res" \
              || fail "прежняя проверка НЕ ошиблась — дефект не воспроизведён, стенд ничего не доказывает"

echo
echo "Мелкая выгрузка — на ней дефект не проявлялся, поэтому и жил незамеченным:"
make_dump "$WORK/small.sql.gz" 5
res=$(verify_now "$WORK/small.sql.gz")
[ -z "$res" ] && pass "нынешняя проверка чиста" || fail "нынешняя проверка ошиблась:$res"

echo
echo "Выгрузка действительно без таблицы — обязана быть поймана:"
gunzip -c "$WORK/big.sql.gz" | grep -v 'CREATE TABLE public.messages' | gzip -9 > "$WORK/nomsg.sql.gz"
res=$(verify_now "$WORK/nomsg.sql.gz")
[[ "$res" == *messages* ]] && pass "отсутствие messages найдено" \
                           || fail "отсутствие messages НЕ найдено (получено: «$res»)"

echo
echo "Обрезанная выгрузка — обязана быть поймана:"
gunzip -c "$WORK/big.sql.gz" | head -100 | gzip -9 > "$WORK/cut.sql.gz"
res=$(verify_now "$WORK/cut.sql.gz")
[ "$res" = "ОБРЕЗАНА" ] && pass "отсутствие отметки о завершении найдено" \
                        || fail "обрезанная выгрузка принята за годную"

echo
echo "Совпало: $ok, провалов: $bad."
[ "$bad" -eq 0 ]
