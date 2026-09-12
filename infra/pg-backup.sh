#!/bin/bash
# Резервное копирование базы webui.
#
# Запуск вручную:  bash infra/pg-backup.sh
# По расписанию:   из crontab пользователя mokeeva, см. infra/README.md
#
# Формат выгрузки — текстовый SQL с gzip, а не -Fc. Причина не в эстетике:
# восстановление custom-формата требует pg_restore, которого нет в разрешённых
# командах sudo, а текстовую выгрузку разворачивает psql — он разрешён.
# То есть восстановиться можно, не расширяя прав.
#
# Роли выгружаются отдельно: pg_dump их не включает, а без роли webui
# восстановленная база останется без владельца объектов.

set -uo pipefail

DB=webui
DEST=/home/mokeeva/backups
SHARE=/home/mokeeva/main/exchange/backups   # копия для забора по SFTP
KEEP=14                                      # сколько выгрузок держать
KEEP_SHARE=3                                 # сколько держать в exchange
MIN_BYTES=2048                               # выгрузка меньше — заведомо битая
LOG="$DEST/backup.log"

STAMP=$(date +%Y%m%d-%H%M%S)
DUMP="$DEST/${DB}-${STAMP}.sql.gz"
ROLES="$DEST/roles-${STAMP}.sql"

mkdir -p "$DEST" "$SHARE"
chmod 700 "$DEST" "$SHARE"

log() { printf '%s  %s\n' "$(date '+%d.%m.%Y %H:%M:%S')" "$1" | tee -a "$LOG"; }
fail() { log "ОШИБКА: $1"; exit 1; }

log "--- начало выгрузки $DB ---"

# ── Выгрузка ──────────────────────────────────────────────────────────
if ! sudo -n -u postgres pg_dump --no-owner --no-privileges "$DB" 2>>"$LOG" | gzip -9 > "$DUMP"; then
    rm -f "$DUMP"
    fail "pg_dump не отработал"
fi
# PIPESTATUS проверяем отдельно: gzip мог вернуть 0 при упавшем pg_dump
if [ "${PIPESTATUS[0]:-0}" -ne 0 ]; then
    rm -f "$DUMP"
    fail "pg_dump вернул ненулевой код"
fi

if ! sudo -n -u postgres pg_dumpall --roles-only > "$ROLES" 2>>"$LOG"; then
    log "предупреждение: роли выгрузить не удалось"
    rm -f "$ROLES"
fi

chmod 600 "$DUMP" 2>/dev/null
[ -f "$ROLES" ] && chmod 600 "$ROLES"

# ── Проверка выгрузки ─────────────────────────────────────────────────
# Молча созданный битый или пустой файл хуже отсутствия копии: создаёт
# уверенность, которой нет. Поэтому проверяем сразу и удаляем негодное.
SIZE=$(stat -c%s "$DUMP")
[ "$SIZE" -lt "$MIN_BYTES" ] && { rm -f "$DUMP"; fail "выгрузка подозрительно мала: $SIZE Б"; }

gzip -t "$DUMP" 2>>"$LOG" || { rm -f "$DUMP"; fail "архив повреждён"; }

# ⚠️ Архив читается ОДИН раз, и `grep -q` в связке с `gunzip` не используется.
# Причина не теоретическая, она стоила нам двух суток копий (11–12.09.2026):
# `grep -q` выходит по первому совпадению и закрывает канал, `gunzip` получает
# SIGPIPE и завершается с кодом 141, а `set -o pipefail` в начале файла делает
# кодом всего конвейера именно 141. Проверка объявляла таблицу отсутствующей,
# хотя та была на месте, — и следующей строкой УДАЛЯЛА годную выгрузку.
# Пока база была маленькой, `gunzip` успевал дочитать до конца и отказа не
# было; ошибка проявилась ровно тогда, когда данных стало больше.
FOUND=$(gunzip -c "$DUMP" | grep -oE '^CREATE TABLE public\.[a-z_]+|PostgreSQL database dump complete')

case "$FOUND" in
    *'PostgreSQL database dump complete'*) ;;
    *) rm -f "$DUMP"; fail "в выгрузке нет отметки о завершении — она обрезана" ;;
esac

MISSING=""
for table in users sessions projects conversations messages files settings; do
    case "$FOUND" in
        *"CREATE TABLE public.$table"*) ;;
        *) MISSING="$MISSING $table" ;;
    esac
done
[ -n "$MISSING" ] && { rm -f "$DUMP"; fail "в выгрузке нет таблиц:$MISSING"; }

log "выгрузка готова: $(basename "$DUMP"), $(numfmt --to=iec "$SIZE" 2>/dev/null || echo "$SIZE Б")"

# ── Копия для забора по SFTP ──────────────────────────────────────────
# Тот же диск, поэтому от отказа диска не спасает. Смысл в другом:
# файл видно в exchange и его можно забрать FAR-ом на свою машину.
cp -p "$DUMP" "$SHARE/" && chmod 600 "$SHARE/$(basename "$DUMP")"
[ -f "$ROLES" ] && cp -p "$ROLES" "$SHARE/" && chmod 600 "$SHARE/$(basename "$ROLES")"
log "копия положена в exchange/backups для забора по SFTP"

# ── Уборка старых ─────────────────────────────────────────────────────
prune() {
    local dir="$1" pattern="$2" keep="$3" removed=0
    while IFS= read -r old; do
        rm -f "$old" && removed=$((removed + 1))
    done < <(ls -1t "$dir"/$pattern 2>/dev/null | tail -n +$((keep + 1)))
    [ "$removed" -gt 0 ] && log "удалено старых ($dir, $pattern): $removed"
    return 0
}
prune "$DEST"  "${DB}-*.sql.gz" "$KEEP"
prune "$DEST"  "roles-*.sql"    "$KEEP"
prune "$SHARE" "${DB}-*.sql.gz" "$KEEP_SHARE"
prune "$SHARE" "roles-*.sql"    "$KEEP_SHARE"

COUNT=$(ls -1 "$DEST"/${DB}-*.sql.gz 2>/dev/null | wc -l)
log "--- готово: выгрузок в хранилище $COUNT, занято $(du -sh "$DEST" | cut -f1) ---"
