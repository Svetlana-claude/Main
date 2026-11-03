#!/bin/bash
# Всё по Главпрыгу вне сервера, каждую ночь (crontab mokeeva):
#   копия сайта — в хранилище Selectel S3 (с 03.11.2026 вместо Диска), бакет klod-kopii-mokeeva,
#                 папка glavpryg-kopii/: зашифрованная копия — боевой с Beget (база и файлы)
#                 и прежний с нашего сервера (копия rezerv.sh). 7 последних. Пароль — тот же,
#                 что у образа сервера. Ключ — ~/.config/selectel-s3.json.
# Остальное — на Яндекс Диск Светланы, папка «Приложения → Claude Главпрыг». Доступ — код
# ~/.config/yandex-app-token, он открывает только эту папку (yadisk.py):
#   materialy/  — папка проекта glavpryg-sayt и материалы из exchange, без файлов с паролями.
#   istoriya/   — задачи и команды по Главпрыгу (tools/istoriya-proektov.py).
#   PAMYATKA.md — как восстановить сайт из копии.
# Журнал — ~/backups/glavpryg/na-disk.log.
set -uo pipefail
umask 077

H=/home/mokeeva
HRANIT=7
PAROL=$H/.config/obraz-parol
WORK=$H/.glavpryg-na-disk
LOG=$H/backups/glavpryg/na-disk.log
METKA=$(date -u +%Y%m%d-%H%M)

log() { echo "$(date -u +'%d.%m.%Y %H:%M') UTC  $*" >> "$LOG"; }
fail() { log "ОШИБКА: $*"; rm -rf "$WORK"; exit 1; }

exec 9>"$H/backups/glavpryg/.na-disk.lock"
flock -n 9 || exit 0
log "--- начало ---"
[ -s "$PAROL" ] || fail "нет пароля образа"

YD="python3 $H/main/glavpryg-sayt/deploy/yadisk.py"
yd() { $YD "$@" >> "$LOG" 2>&1; }
# Без кода Диска материалы не выгружаются, а копия сайта уходит всё равно
DISK=da; [ -s "$H/.config/yandex-app-token" ] || { DISK=net; log "ВНИМАНИЕ: нет кода доступа к Яндекс Диску — только копия сайта"; }

rm -rf "$WORK"; mkdir -p "$WORK/kopiya"

# ── Копия сайта ─────────────────────────────────────────────────────────────
BEGET=net
( cd "$H/tools/beget" && timeout 1800 .venv/bin/python vygruzit.py "$WORK/kopiya" ) >> "$LOG" 2>&1 \
    && BEGET=da || { rm -f "$WORK"/kopiya/beget-*; log "ВНИМАНИЕ: Beget не ответил, в копии только прежний сайт"; }
STARY=$(ls -t $H/backups/glavpryg/glavpryg-rezerv-*.tar 2>/dev/null | head -1)
[ -n "$STARY" ] && cp "$STARY" "$WORK/kopiya/stary-server-$(basename "$STARY")"
ls "$WORK"/kopiya/* >/dev/null 2>&1 || fail "нечего копировать: нет ни Beget, ни копии со старого сервера"
IMYA="glavpryg-kopiya-$METKA$([ $BEGET = net ] && echo -bez-beget).tar.gpg"
tar -C "$WORK/kopiya" -cf - . \
  | gpg --batch --yes --pinentry-mode loopback --passphrase-file "$PAROL" --symmetric \
        --cipher-algo AES256 -o "$WORK/$IMYA" || fail "копия не зашифрована"
gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$PAROL" -d "$WORK/$IMYA" | tar -tf - > /dev/null \
    || fail "зашифрованная копия не читается"
[ -s "$H/.config/selectel-s3.json" ] || fail "нет ключа Selectel"
source "$H/main/infra/obraz/s3-env.sh"
"$H/tools/restic/rclone" copyto "$WORK/$IMYA" ":s3:$S3_BAKET/glavpryg-kopii/$IMYA" --retries 5 >> "$LOG" 2>&1 \
    || fail "копия не загрузилась в Selectel"
"$H/tools/restic/.venv/bin/python" "$H/main/infra/obraz/s3-chistka.py" ostavit glavpryg-kopii/ "$HRANIT" >> "$LOG" 2>&1
"$H/tools/restic/rclone" copyto "$H/main/glavpryg-sayt/deploy/PAMYATKA-DISK.md" ":s3:$S3_BAKET/glavpryg-kopii/PAMYATKA.md" >> "$LOG" 2>&1
log "копия в Selectel: $IMYA, $(du -m "$WORK/$IMYA" | cut -f1) МБ, Beget: $BEGET"

[ $DISK = net ] && { rm -rf "$WORK"; log "--- готово ---"; exit 0; }

# ── Материалы ───────────────────────────────────────────────────────────────
# Файлы с паролями и доступами на Диск не идут
ISKL=('.git/*' '*/.git/*' '*node_modules/*' '*.venv/*' '*__pycache__/*' 'downloads/rezerv/*'
      'downloads/PAROL*' 'downloads/perenos*' 'downloads/dostup*' 'downloads/yandex-kod*'
      'downloads/OSHIBKA*' 'downloads/obraz-*' 'downloads/Снимок экрана*')
yd sinhr "$H/main/glavpryg-sayt" materialy/glavpryg-sayt --iskl "${ISKL[@]}" || log "ВНИМАНИЕ: материалы проекта загрузились не полностью"
for d in glavpryg-arhiv glavpryg-foto glavpryg-foto-gotovoe; do
    [ -d "$H/main/exchange/$d" ] && { yd sinhr "$H/main/exchange/$d" "materialy/exchange/$d" \
        || log "ВНИМАНИЕ: exchange/$d загрузилась не полностью"; }
done

# ── История и памятка ───────────────────────────────────────────────────────
python3 "$H/main/tools/istoriya-proektov.py" "$WORK/istoriya" >> "$LOG" 2>&1 \
    && yd zalit "$WORK/istoriya/проекты/glavpryg-sayt.md" istoriya/glavpryg-sayt.md \
    || log "ВНИМАНИЕ: история не обновлена"
yd zalit "$H/main/glavpryg-sayt/deploy/PAMYATKA-DISK.md" PAMYATKA.md || log "ВНИМАНИЕ: памятка не загрузилась"

rm -rf "$WORK"
log "--- готово ---"
