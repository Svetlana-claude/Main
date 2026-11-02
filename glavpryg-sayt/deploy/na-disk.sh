#!/bin/bash
# Всё по Главпрыгу — на Яндекс Диск Светланы, папка «Приложения → Claude Главпрыг» (каждую ночь,
# crontab mokeeva). Доступ — код ~/.config/yandex-app-token, он открывает только эту папку (yadisk.py):
#   kopii/      — зашифрованная копия сайта: боевой с Beget (база и файлы) и прежний с нашего
#                 сервера (копия rezerv.sh). 7 последних. Пароль — тот же, что у образа сервера.
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
[ -s "$H/.config/yandex-app-token" ] || fail "нет кода доступа к Яндекс Диску"
[ -s "$PAROL" ] || fail "нет пароля образа"

YD="python3 $H/main/glavpryg-sayt/deploy/yadisk.py"
yd() { $YD "$@" >> "$LOG" 2>&1; }

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
yd zalit "$WORK/$IMYA" "kopii/$IMYA" || fail "копия не загрузилась на Диск"
yd ostavit kopii 'glavpryg-kopiya-*' "$HRANIT"
log "копия на Диске: $IMYA, $(du -m "$WORK/$IMYA" | cut -f1) МБ, Beget: $BEGET"

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
