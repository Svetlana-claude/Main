#!/bin/bash
# Проверка образа на этом сервере: распаковать главное из последнего снимка во временную папку, сверить
# базу с рабочей и запустить копию сайта на 127.0.0.1:18081. В журнал идут только
# числа и коды ответа, содержимое не выводится. Полную проверку заменяет только
# разворачивание на чистом сервере.
set -uo pipefail
umask 077
H=/home/mokeeva
export RESTIC_REPOSITORY=$H/backups/obraz-repo RESTIC_PASSWORD_FILE=$H/.config/obraz-parol
T=$H/.obraz-proverka
LOG=$H/backups/obraz.log
log() { echo "$(date -u +'%d.%m.%Y %H:%M') UTC  проверка: $*" >> "$LOG"; }

rm -rf "$T"; mkdir -p "$T"
trap 'kill "${PID:-0}" 2>/dev/null; rm -rf "$T"' EXIT
log "начало"
$H/tools/restic/restic --quiet dump --tag obraz latest /obraz.tar \
  | tar -C "$T" -xf - home/mokeeva/.obraz-staging home/mokeeva/.config/webui2 home/mokeeva/main/webui2 \
       home/mokeeva/main/.git home/mokeeva/main/CLAUDE.md || { log "архив не распаковался"; exit 1; }
R=$T/home/mokeeva
ls -la --time-style=+ "$R/.obraz-staging" | awk 'NR>3{print $5,$6}' | tr '\n' ';' | sed 's/^/файлы: /' | while read -r l; do log "$l"; done

python3 - "$H/.local/share/webui2/site.db" "$R/.obraz-staging/site.db" <<'PY' >> "$LOG" 2>&1
import sqlite3, sys
ziv = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
kop = sqlite3.connect(f"file:{sys.argv[2]}?mode=ro", uri=True)
print("база цела:", kop.execute("pragma integrity_check").fetchone()[0])
names = [r[0] for r in ziv.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' and name not like '%_fts%'")]
rows = raz = 0
for n in names:
    a = ziv.execute(f'select count(*) from "{n}"').fetchone()[0]
    b = kop.execute(f'select count(*) from "{n}"').fetchone()[0]
    rows += b
    if a != b:
        raz += 1
        print(f"  таблица {n}: сейчас {a}, в копии {b}")
print(f"таблиц {len(names)}, записей в копии {rows}, расхождений {raz}")
PY

git --git-dir="$R/main/.git" log --oneline -1 >> "$LOG" 2>&1
if [ -f "$R/.obraz-staging/beget-baza.sql" ]; then
    log "Beget: таблиц $(grep -c 'CREATE TABLE' "$R/.obraz-staging/beget-baza.sql"), файл сайта $(tar -tf "$R/.obraz-staging/beget-sayt.tar" | wc -l) записей"
else
    log "Beget: в последнем снимке копии нет"
fi
log "Главпрыг, копия со старого сервера: $(tar -tf "$R/.obraz-staging/glavpryg-rezerv.tar" | wc -l) частей"

ENVF=$R/.config/webui2/webui2.env
sed -i '/^DB_PATH=/d;/^CHAT_DIR=/d;/^THUMB_DIR=/d' "$ENVF"
{ echo "DB_PATH=$R/.obraz-staging/site.db"; echo "CHAT_DIR=$T/chat"; echo "THUMB_DIR=$T/thumbs"; } >> "$ENVF"
cd "$R/main/webui2" || exit 1
WEBUI2_ENV=$ENVF $H/main/webui2/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 18081 > "$T/site.log" 2>&1 &
PID=$!
sleep 8
KOD=$(curl -s -m 10 -o /dev/null -w '%{http_code}' http://127.0.0.1:18081/login)
KOD2=$(curl -s -m 10 -o /dev/null -w '%{http_code}' http://127.0.0.1:18081/chat)
log "копия сайта: вход $KOD, чат без входа $KOD2"
[ "$KOD" = 200 ] || log "вывод копии сайта: $(grep -E -c 'Error|Traceback' "$T/site.log") строк с ошибками"
log "конец"
