#!/bin/bash
# Проверка разбора доводов обёрткой `infra/webui-sec.sh`.
#
# Запуск:  bash bezopasnost/tests/check-wrapper.sh
#
# Проверяется ровно то, ради чего обёртка существует: закрытый набор команд и
# невозможность подсунуть путь или флаг. Исполнения здесь нет — включён режим
# WEBUI_SEC_CHECK, при котором обёртка печатает разобранную команду и выходит.
#
# ⚠️ Работа идёт с ПРАВЛЕНОЙ копией: снята проверка «нужен root» и подменены
# каталоги, иначе стенд требовал бы root и трогал боевую установку. Правится
# только это — разбор доводов остаётся тем же, что в бою. Строки правки
# печатаются, чтобы было видно, что подменено (правило 13: убедиться, что
# результат дал код, а не оснастка).
set -uo pipefail
export LC_ALL=C

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/infra/webui-sec.sh"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/lib/baseline" "$WORK/lib/quarantine" "$WORK/lib/backup" "$WORK/state/snapshots"
# Поддельные «скрипты под root»: обёртка проверяет владельца и права, но в
# режиме WEBUI_SEC_CHECK до запуска не доходит.
for s in collect.sh remediate.sh apply-firewall.sh; do
  install -m 755 /dev/null "$WORK/lib/$s"
done

W="$WORK/webui-sec"
# Образцы намеренно не привязаны к концу строки: в исходнике у этих строк есть
# хвостовые комментарии, и якорь `$` молча не сработал бы — правка не легла бы,
# а стенд при этом отчитался бы о проверках. Ровно так и вышло на первом прогоне.
sed -e 's|^LIB=/opt/secaudit\b.*|LIB='"$WORK"'/lib|' \
    -e 's|^STATE=/var/lib/secaudit\b.*|STATE='"$WORK"'/state|' \
    -e 's|^if \[ "\$(id -u)" -ne 0 \]; then$|if false; then|' \
    "$SRC" > "$W"
chmod +x "$W"
echo "Подменено в копии:"
grep -nE "^(LIB|STATE)=|^if false; then" "$W" | sed 's/^/  /'
# Если подмена не легла, стенд бы работал с боевыми путями и отчитался о
# проверках, которых не было. Проверяем прямо.
grep -q "^LIB=$WORK/lib$" "$W" && grep -q "^STATE=$WORK/state$" "$W" \
  || { echo "ОСНАСТКА СЛОМАНА: подмена путей не легла, проверять нечего"; exit 2; }
echo

ok=0; bad=0
pass() { ok=$((ok+1));  echo "  норма  — $1"; }
fail() { bad=$((bad+1)); echo "  ПРОВАЛ — $1"; }

# Обёртка обязана ОТКАЗАТЬ: ненулевой код и слово ОТКАЗ в выводе.
deny() { # описание, доводы...
  local what="$1"; shift
  local out rc
  out=$(WEBUI_SEC_CHECK=1 bash "$W" "$@" 2>&1); rc=$?
  if [ "$rc" -ne 0 ] && echo "$out" | grep -q 'ОТКАЗ'; then pass "$what"
  else fail "$what (код $rc, вывод: ${out:0:70})"; fi
}

# Команда распознана: отказ, если он есть, говорит НЕ о неизвестной команде.
known() { # описание, доводы...
  local what="$1"; shift
  local out
  out=$(WEBUI_SEC_CHECK=1 bash "$W" "$@" 2>&1)
  if echo "$out" | grep -q 'неизвестная команда'; then
    fail "$what (команда не распознана)"
  else
    pass "$what"
  fi
}

# Отказ именно по названной причине.
deny_why() { # описание, причина, доводы...
  local what="$1" why="$2"; shift 2
  local out rc
  out=$(WEBUI_SEC_CHECK=1 bash "$W" "$@" 2>&1); rc=$?
  if [ "$rc" -ne 0 ] && echo "$out" | grep -qF "$why"; then pass "$what"
  else fail "$what (код $rc, вывод: ${out:0:70})"; fi
}

echo "Разрешённые команды распознаются:"
known "collect без доводов"        collect
known "remediate без доводов"      remediate

echo
echo "Запуск чужого скрипта от root не допускается:"
# Файлы в подменённом каталоге принадлежат не root — именно этим отличается
# «рабочая копия под root» от каталога, куда пишет пользователь. Разреши
# обёртка запуск такого файла, разрешение на неё было бы беспарольным root.
deny_why "collect: скрипт принадлежит не root"   "принадлежит не root" collect
deny_why "remediate: скрипт принадлежит не root" "принадлежит не root" remediate

echo
echo "Неизвестные команды:"
deny  "выдуманная команда"          нечто
deny  "команда с путём"             /bin/sh

# Пустая команда и --help печатают подсказку и выходят с нулём — так же, как у
# webui-vpn. Важно другое: ничего при этом не запускается.
for arg in "" --help; do
  out=$(WEBUI_SEC_CHECK=1 bash "$W" "$arg" 2>&1)
  if echo "$out" | grep -q 'ЗАПУСТИЛ БЫ'; then
    fail "«${arg:-пусто}» ничего не запускает"
  else
    pass "«${arg:-пусто}» печатает подсказку и ничего не запускает"
  fi
done

echo
echo "Лишние доводы (через них в инструкции приходил путь к снимку):"
# Тоже по причине: сними проверку доводов — и отказ всё равно придёт, только
# ниже по течению и по другому поводу. Стенд, спрашивающий «отказано ли»,
# такого не заметил бы.
deny_why "collect с путём"          "collect доводов не принимает"          collect /etc/passwd
deny_why "remediate с путём"        "remediate доводов не принимает"        remediate /tmp/поддельный-снимок.txt
deny_why "firewall-apply с доводом" "firewall-apply доводов не принимает"   firewall-apply --now
deny_why "baseline-approve с путём" "baseline-approve доводов не принимает" baseline-approve /tmp/чужой-эталон.txt
deny_why "status с доводом"         "status доводов не принимает"           status --verbose

echo
echo "Карантин адресуется хэшем — путь и флаг не подставить:"
# ⚠️ Отказ проверяется ПО ПРИЧИНЕ, а не по факту. Первая версия стенда
# спрашивала только «отказано ли», и ослабленная до `[ -n "$1" ]` проверка
# хэша прошла её насквозь: путь до хэша не дотягивал, но и файла с таким
# «хэшем» в карантине не находилось — отказ приходил, только не тот.
deny_why "путь вместо хэша"           "ожидался sha256" quarantine-restore ../../etc/shadow
deny_why "флаг вместо хэша"           "ожидался sha256" quarantine-delete --help
deny_why "короткий хэш"               "ожидался sha256" quarantine-restore abc123
deny_why "хэш с не-шестнадцатеричным" "ожидался sha256" quarantine-delete "$(printf 'z%.0s' {1..64})"
deny_why "хэш в верхнем регистре"     "ожидался sha256" quarantine-delete "$(printf 'A%.0s' {1..64})"
deny_why "два довода вместо одного"   "нужен ровно один довод" quarantine-restore "$(printf 'a%.0s' {1..64})" второй
deny_why "верный по виду, но чужой"   "нет файла с таким хэшем" quarantine-restore "$(printf 'a%.0s' {1..64})"

echo
echo "Приём эталона без снимка за сегодня:"
deny  "снимка нет — отказ, а не пустой эталон" baseline-approve

echo
echo "Совпало: $ok, провалов: $bad."
[ "$bad" -eq 0 ]
