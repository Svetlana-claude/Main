#!/bin/bash
# Проверка восстановления из последней выгрузки.
#
# Запуск: bash infra/pg-restore-check.sh [файл.sql.gz]
#
# Смысл этого скрипта: непроверенная выгрузка — не резервная копия, а
# предположение о ней. Проверка разворачивает выгрузку в отдельную пустую базу
# и сверяет число строк по каждой таблице с рабочей. Проверочная база удаляется.
#
# Рабочая база не затрагивается ни на одном шаге.

set -uo pipefail

DB=webui
CHECK_DB=webui_restore_check
DEST=/home/mokeeva/backups
TABLES=(users sessions login_attempts projects conversations messages files settings metrics_history)

DUMP=${1:-$(ls -1t "$DEST"/${DB}-*.sql.gz 2>/dev/null | head -1)}

if [ -z "${DUMP:-}" ] || [ ! -f "$DUMP" ]; then
    echo "не найдена выгрузка для проверки в $DEST" >&2
    exit 1
fi

echo "Проверяемая выгрузка: $(basename "$DUMP") ($(du -h "$DUMP" | cut -f1))"

cleanup() {
    sudo -n -u postgres dropdb --if-exists "$CHECK_DB" 2>/dev/null
}
trap cleanup EXIT

# Если проверочная база осталась с прошлого раза — убираем
sudo -n -u postgres dropdb --if-exists "$CHECK_DB" 2>/dev/null

echo "Создаю пустую базу $CHECK_DB"
sudo -n -u postgres createdb "$CHECK_DB" || { echo "не удалось создать базу" >&2; exit 1; }

echo "Разворачиваю выгрузку"
ERRLOG=$(mktemp); trap 'rm -f "$ERRLOG"; cleanup' EXIT
if ! gunzip -c "$DUMP" | sudo -n -u postgres psql -q -v ON_ERROR_STOP=1 -d "$CHECK_DB" > /dev/null 2>"$ERRLOG"; then
    echo "ОШИБКА при восстановлении:" >&2
    tail -15 "$ERRLOG" >&2
    exit 1
fi
if [ -s "$ERRLOG" ]; then
    echo "Замечания при восстановлении:"
    sed 's/^/  /' "$ERRLOG" | head -10
fi

echo
printf '%-20s %10s %10s  %s\n' "Таблица" "рабочая" "копия" "итог"
printf '%s\n' "-------------------------------------------------------------"

FAILED=0
for table in "${TABLES[@]}"; do
    live=$(sudo -n -u postgres psql -tAc "SELECT count(*) FROM $table" -d "$DB" 2>/dev/null)
    restored=$(sudo -n -u postgres psql -tAc "SELECT count(*) FROM $table" -d "$CHECK_DB" 2>/dev/null)
    live=${live:-нет}
    restored=${restored:-нет}
    if [ "$live" = "$restored" ]; then
        verdict="совпало"
    else
        verdict="РАСХОЖДЕНИЕ"
        FAILED=$((FAILED + 1))
    fi
    printf '%-20s %10s %10s  %s\n' "$table" "$live" "$restored" "$verdict"
done

echo
# Схема тоже должна совпадать: одинаковое число строк при разной структуре
# ничего не доказывает
live_cols=$(sudo -n -u postgres psql -tAc \
    "SELECT count(*) FROM information_schema.columns WHERE table_schema='public'" -d "$DB")
rest_cols=$(sudo -n -u postgres psql -tAc \
    "SELECT count(*) FROM information_schema.columns WHERE table_schema='public'" -d "$CHECK_DB")
echo "Столбцов в схеме: рабочая $live_cols, копия $rest_cols"
[ "$live_cols" = "$rest_cols" ] || FAILED=$((FAILED + 1))

live_idx=$(sudo -n -u postgres psql -tAc \
    "SELECT count(*) FROM pg_indexes WHERE schemaname='public'" -d "$DB")
rest_idx=$(sudo -n -u postgres psql -tAc \
    "SELECT count(*) FROM pg_indexes WHERE schemaname='public'" -d "$CHECK_DB")
echo "Индексов: рабочая $live_idx, копия $rest_idx"
[ "$live_idx" = "$rest_idx" ] || FAILED=$((FAILED + 1))

echo
if [ "$FAILED" -eq 0 ]; then
    echo "ИТОГ: восстановление проверено, копия годная."
    exit 0
fi
echo "ИТОГ: расхождений $FAILED — копию нельзя считать годной." >&2
exit 1
