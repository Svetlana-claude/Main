#!/bin/bash
# Ночной аудит безопасности. Запускается из crontab непривилегированной учётки.
#
# Порядок: собрать факты -> сравнить с эталоном -> устранить из белого списка ->
# отдать результат на разбор -> собрать отчёт.
#
# Сбор фактов и устранение идут от root через обёртку webui-sec: сам audit.sh
# работает от пользователя и root не получает. Анализатор запускается БЕЗ
# ЕДИНОГО ИНСТРУМЕНТА и получает данные на stdin — он не может ничего
# выполнить, прочитать или записать, только вернуть текст. Это принципиально:
# аудит по своей природе читает то, что контролирует атакующий (логи, имена
# процессов), и агент с sudo на таких данных был бы готовым бэкдором.
set -uo pipefail
export LC_ALL=C
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$HOME/.local/bin

BASE=${BASE:-/opt/secaudit}
. "$BASE/config.sh"

# Чем вызывается обёртка. Переопределяется проверками из tests/: подставив
# заглушку, стенд гоняет разбор на поддельном снимке и не трогает систему.
SEC_CMD=${SEC_CMD:-"sudo -n webui-sec"}

DATE=$(date +%F)
SNAP=$STATE/snapshots/$DATE.txt
REF=$BASE/baseline/reference.txt
REPORT=$STATE/reports/rep_$DATE.md
LOG=$STATE/audit.log

mkdir -p "$STATE/snapshots" "$STATE/reports"

log() { echo "[$(date -Is)] $*" >> "$LOG"; }
log "=== запуск аудита ==="

# 1. Сбор фактов.
#    ⚠️ Молчащий отказ sudo даёт пустой снимок, а отчёт по нему выглядит
#    спокойным. Поэтому пустой снимок — это ошибка, а не «всё чисто».
if ! $SEC_CMD collect > "$SNAP" 2>>"$LOG" || [ ! -s "$SNAP" ]; then
  log "ОШИБКА: сбор фактов не выполнен — снимок пуст"
  echo "СБОР ФАКТОВ НЕ ВЫПОЛНЕН. Отчёт недостоверен, см. $LOG" >> "$SNAP"
fi

# 2. Сравнение с эталоном.
ALERTS=$(mktemp)
if [ -f "$REF" ]; then
  "$BASE/diff.sh" "$SNAP" "$REF" > "$ALERTS" 2>>"$LOG"
else
  echo "Эталон отсутствует — сравнивать не с чем. Примите его: sudo webui-sec baseline-approve" > "$ALERTS"
fi

# 3. Устранение из белого списка. REMEDIATE=0 — только отчёт, ничего не менять.
ACTIONS=$(mktemp)
if [ "${REMEDIATE:-1}" = "1" ]; then
  $SEC_CMD remediate > "$ACTIONS" 2>>"$LOG"
else
  echo "Автоустранение отключено (REMEDIATE=0) — отчёт составлен без изменений." > "$ACTIONS"
fi

# 4. Повторный снимок, если что-то чинили: отчёт должен отражать итог, а не исход.
if ! grep -q 'Автоматических действий не потребовалось' "$ACTIONS"; then
  $SEC_CMD collect > "$SNAP.after" 2>>"$LOG" && [ -s "$SNAP.after" ] && mv "$SNAP.after" "$SNAP"
  rm -f "$SNAP.after"
  if [ -f "$REF" ]; then
    "$BASE/diff.sh" "$SNAP" "$REF" > "$ALERTS.after" 2>>"$LOG" && mv "$ALERTS.after" "$ALERTS"
  fi
fi

# 5. Разбор. Инструменты отключены полностью. Без ANALYZER шаг пропускается.
ANALYSIS=$(mktemp)
if [ -n "${ANALYZER:-}" ]; then
  {
    [ -f "$BASE/CONTEXT.md" ] && { cat "$BASE/CONTEXT.md"; echo; echo "---"; echo; }
    echo "Расхождения с эталоном:"; echo; cat "$ALERTS"
    echo; echo "Выполненные автоматически действия:"; echo; cat "$ACTIONS"
    echo; echo "Снимок состояния:"; echo; cat "$SNAP"
  } | timeout "$ANALYZER_TIMEOUT" $ANALYZER > "$ANALYSIS" 2>>"$LOG"
fi

if [ ! -s "$ANALYSIS" ]; then
  echo "## Оценка"                                                     >  "$ANALYSIS"
  echo "Разбор не выполнялся или не дал ответа (см. $LOG). Ниже — данные без разбора." >> "$ANALYSIS"
fi

# 6. Сборка отчёта.
{
  echo "# Отчёт безопасности — $DATE"
  echo
  echo "Сервер: $(hostname). Аудит выполнен $(date '+%d.%m.%Y в %H:%M %Z')."
  echo
  cat "$ANALYSIS"
  echo
  echo "## Устранено автоматически"; echo
  cat "$ACTIONS"
  echo
  echo "## Расхождения с эталоном (машинная проверка)"; echo
  echo '```'; cat "$ALERTS"; echo '```'
  echo
  echo "<details><summary>Полный снимок состояния</summary>"; echo
  echo '```'; cat "$SNAP"; echo '```'
  echo
  echo "</details>"
} > "$REPORT"

rm -f "$ALERTS" "$ACTIONS" "$ANALYSIS"

# Снимки старше срока хранения не нужны — отчёты остаются.
find "$STATE/snapshots" -name '*.txt' -mtime +"$RETENTION_DAYS" -delete 2>/dev/null

log "готово: $REPORT"
echo "$REPORT"
