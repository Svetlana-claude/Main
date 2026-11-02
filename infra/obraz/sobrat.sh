#!/bin/bash
# Образ сервера на случай потери аккаунта или сервера: сайт, база с перепиской,
# проекты, история разговоров, настройки, ключи и копия боевого сайта Главпрыга
# с Beget. Запускается по расписанию (crontab mokeeva), разворачивается
# vosstanovit.sh. Закрытые базу и ключ сайта берёт с разрешения Светланы от
# 01.11.2026; содержимое никуда, кроме хранилища образа, не выводит.
#
# С 02.11.2026 образ — не один архив, а хранилище «только изменения»
# (~/backups/obraz-repo, программа ~/tools/restic/restic): каждую ночь туда
# добавляется снимок obraz.tar, а повторяющиеся куски хранятся один раз. Новый
# снимок не трогает прежние, так что сбой ночи не оставляет без копии. Хранятся
# снимки за 14 дней и по одному на месяц за год.
#
# Пароль хранилища — ~/.config/obraz-parol (600), тот же, что был у архива;
# создаётся здесь при первом запуске и один раз кладётся в «Файлы проекта»,
# Светлана записывает его и удаляет файл.
# Яндекс Диск подключается файлом ~/.config/yandex-disk.netrc: есть файл —
# хранилище и всё для восстановления повторяются в папке obraz-sayta-repo/.
set -uo pipefail
umask 077

H=/home/mokeeva
VYDACHA=$H/main/glavpryg-sayt/downloads
PAROL=$H/.config/obraz-parol
SITE_DB=$H/.local/share/webui2/site.db
STAGE=$H/.obraz-staging
LOG=$H/backups/obraz.log
OSHIBKA=$VYDACHA/OSHIBKA-OBRAZA.txt
YA_NETRC=$H/.config/yandex-disk.netrc
BIN=$H/tools/restic
export RESTIC_REPOSITORY=$H/backups/obraz-repo RESTIC_PASSWORD_FILE=$PAROL
ZAPAS_MB=1024        # столько оставляем свободным на диске сервера

log() { echo "$(date -u +'%d.%m.%Y %H:%M') UTC  $*" >> "$LOG"; }
fail() {
    log "ОШИБКА: $*"
    rm -rf "$STAGE"
    echo "Образ не собран: $*. Прежние снимки целы. Подробности — $LOG" > "$OSHIBKA"
    exit 1
}
r() { "$BIN/restic" --quiet "$@"; }

exec 9>"$H/backups/.obraz.lock"
flock -n 9 || exit 0
log "--- сборка ---"

if [ ! -s "$PAROL" ]; then
    openssl rand -hex 16 | sed -E 's/(.{4})/\1-/g; s/-$//' > "$PAROL"
    chmod 600 "$PAROL"
    { echo "Пароль образа сайта. Запиши его на бумагу, потом удали этот файл."
      echo; cat "$PAROL"; } > "$VYDACHA/PAROL-OBRAZA-zapishi-i-udali.txt"
fi
[ -f "$RESTIC_REPOSITORY/config" ] || r init >> "$LOG" 2>&1 || fail "хранилище образа не создано"

SVOBODNO=$(df -m --output=avail "$H/backups" | tail -1 | tr -d ' ')
[ "$SVOBODNO" -gt "$ZAPAS_MB" ] || fail "на диске мало места: $SVOBODNO МБ"

rm -rf "$STAGE"; mkdir -p "$STAGE"
python3 - "$SITE_DB" "$STAGE/site.db" <<'PY' || fail "не снята копия базы сайта"
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
assert dst.execute("pragma integrity_check").fetchone()[0] == "ok"
PY
crontab -l > "$STAGE/crontab.mokeeva"
cp "$(ls -t $H/backups/glavpryg/glavpryg-rezerv-*.tar | head -1)" "$STAGE/glavpryg-rezerv.tar" \
    || fail "нет резервной копии Главпрыга"
cp "$(ls -t $H/backups/webui-*.sql.gz | head -1)" "$STAGE/webui.sql.gz"
sudo -n -u postgres pg_dumpall --roles-only > "$STAGE/roles.sql" 2>/dev/null

# Beget: три попытки с паузой 10 минут — короткий обрыв связи не оставляет без копии
# (BEGET_POPYTOK задаёт число попыток при ручном запуске).
# Не вышло — образ собирается без свежей копии Главпрыга с хостинга.
BEGET=0 POPYTOK=${BEGET_POPYTOK:-3}
for popytka in $(seq "$POPYTOK"); do
    ( cd "$H/tools/beget" && timeout 1800 .venv/bin/python vygruzit.py "$STAGE" ) >> "$LOG" 2>&1 \
        && { BEGET=1; break; }
    rm -f "$STAGE"/beget-*
    log "Beget: попытка $popytka не удалась"
    [ "$popytka" = "$POPYTOK" ] || sleep 600
done
if [ "$BEGET" = 1 ]; then
    # Без сжатия: сжатый файл каждую ночь меняется целиком, и повторы не находятся
    gunzip "$STAGE/beget-baza.sql.gz" && gunzip -c "$STAGE/beget-sayt.tgz" > "$STAGE/beget-sayt.tar" \
        && rm -f "$STAGE/beget-sayt.tgz" || fail "копия Beget не распаковалась"
else
    log "ВНИМАНИЕ: сайт с Beget не выгружен, в этом снимке его нет"
fi

# tar идёт под root (ключи сайтов и почты), в хранилище — потоком, без файла на диске
sudo -n tar -C / --warning=no-file-changed --warning=no-file-removed --ignore-failed-read -cf - \
    --exclude='.venv' --exclude='node_modules' --exclude='__pycache__' \
    --exclude='home/mokeeva/main/exchange/aivid' --exclude='home/mokeeva/main/exchange/rife' \
    --exclude='home/mokeeva/main/exchange/nncflib' --exclude='home/mokeeva/main/exchange/pwenv' \
    --exclude='home/mokeeva/main/exchange/sdlib' --exclude='home/mokeeva/main/exchange/esrgan' \
    --exclude='home/mokeeva/main/exchange/chromelibs' --exclude='home/mokeeva/main/exchange/backups' \
    --exclude='home/mokeeva/main/exchange/aevit/fon' \
    --exclude='home/mokeeva/main/webui/uploads' --exclude='home/mokeeva/main/webui/downloads' \
    --exclude='home/mokeeva/main/glavpryg-sayt/downloads/glavpryg-kod.bundle' \
    --exclude='home/mokeeva/main/glavpryg-sayt/downloads/rezerv' \
    --exclude='home/mokeeva/main/glavpryg-sayt/downloads/obraz-*' \
    --exclude='home/mokeeva/main/glavpryg-sayt/downloads/PAROL-OBRAZA*' \
    --exclude='home/mokeeva/.config/obraz-parol' \
    --exclude='home/mokeeva/.claude/.credentials.json' \
    --exclude='home/mokeeva/.local/share/webui2/site.db*' \
    --exclude='home/mokeeva/.local/share/webui2/backup' \
    home/mokeeva/main home/mokeeva/projects home/mokeeva/tools home/mokeeva/.ssh \
    home/mokeeva/.claude home/mokeeva/.config/webui2 home/mokeeva/.config/webui \
    home/mokeeva/.config/tgbot home/mokeeva/.config/glavpryg-admin.pass \
    home/mokeeva/.config/glavpryg-db.pass home/mokeeva/.config/glavpryg-mail.pass \
    home/mokeeva/.config/glavpryg-rezerv.adresa home/mokeeva/.config/glavpryg-beget.json \
    home/mokeeva/.local/share/webui2 home/mokeeva/.obraz-staging \
    etc/nginx etc/letsencrypt etc/opendkim etc/postfix etc/dovecot etc/fail2ban etc/amnezia \
    etc/wireguard etc/php/8.4/fpm/pool.d etc/systemd/system/webui2.service etc/sudoers.d \
    usr/local/sbin usr/local/lib/webui-vpn opt/secaudit var/lib/secaudit var/mail 2>>"$LOG" \
  | r backup --stdin --stdin-filename obraz.tar --tag obraz --json 2>>"$LOG" > "$STAGE/itog.json"
KODY=("${PIPESTATUS[@]}")
[ "${KODY[0]}" -le 1 ] && [ "${KODY[1]}" -eq 0 ] || fail "сборка прервалась: ${KODY[*]}"
DOBAVLENO=$(python3 -c "import json,sys
for l in open(sys.argv[1]):
    d=json.loads(l)
    if d.get('message_type')=='summary': print(d['data_added']//1048576, d['total_bytes_processed']//1048576)" "$STAGE/itog.json")
rm -rf "$STAGE"

# Проверка: в свежем снимке есть главное
SPISOK=$(r dump latest --tag obraz /obraz.tar | tar -tf - ) || fail "снимок не читается"
for nuzhno in home/mokeeva/.obraz-staging/site.db home/mokeeva/.obraz-staging/glavpryg-rezerv.tar \
              home/mokeeva/.config/webui2/webui2.env \
              home/mokeeva/main/CLAUDE.md etc/nginx/nginx.conf; do
    grep -qx "$nuzhno" <<<"$SPISOK" || fail "в снимке нет $nuzhno"
done
read -r NOVOE VSEGO <<<"$DOBAVLENO"
log "снимок готов: образ $VSEGO МБ, нового в хранилище $NOVOE МБ, записей $(wc -l <<<"$SPISOK")"

r forget --keep-daily 14 --keep-monthly 12 --prune >> "$LOG" 2>&1 \
    || log "ВНИМАНИЕ: старые снимки не убраны"
r check >> "$LOG" 2>&1 || fail "хранилище повреждено"
log "хранилище: $(du -sm "$RESTIC_REPOSITORY" | cut -f1) МБ, снимков $(r snapshots --json | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')"
rm -f "$OSHIBKA"
cp "$H/main/infra/obraz/PAMYATKA.md" "$VYDACHA/"

# Яндекс Диск: хранилище и всё для восстановления. Ошибка Диска не губит копию на сервере
if [ -s "$YA_NETRC" ]; then
    read -r YA_USER YA_PASS < <(awk '{for(i=1;i<NF;i++){if($i=="login")u=$(i+1);if($i=="password")p=$(i+1)}} END{print u, p}' "$YA_NETRC")
    export RCLONE_WEBDAV_URL=https://webdav.yandex.ru RCLONE_WEBDAV_VENDOR=other \
           RCLONE_WEBDAV_USER=$YA_USER RCLONE_WEBDAV_PASS=$("$BIN/rclone" obscure "$YA_PASS")
    unset YA_PASS
    if "$BIN/rclone" sync "$RESTIC_REPOSITORY" :webdav:obraz-sayta-repo/hranilishche --retries 5 >> "$LOG" 2>&1 \
       && "$BIN/rclone" copy "$H/main/infra/obraz" :webdav:obraz-sayta-repo --include '{vosstanovit.sh,PAMYATKA.md}' >> "$LOG" 2>&1 \
       && "$BIN/rclone" copyto "$BIN/restic" :webdav:obraz-sayta-repo/restic >> "$LOG" 2>&1; then
        log "образ на Яндекс Диске"
    else
        log "ВНИМАНИЕ: Яндекс Диск не принял образ"
        echo "Образ на сервере готов, но на Яндекс Диск не ушёл. Подробности — $LOG" > "$OSHIBKA"
    fi
fi
