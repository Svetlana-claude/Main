#!/bin/bash
# Образ сервера: один зашифрованный архив на случай потери аккаунта или сервера.
# Сайт, база с перепиской, проекты, история разговоров, настройки, ключи и копия
# боевого сайта Главпрыга с Beget. Запускается по расписанию (crontab mokeeva),
# разворачивается vosstanovit.sh. Закрытые базу и ключ сайта берёт с разрешения
# Светланы от 01.11.2026; содержимое никуда, кроме архива, не выводит.
#
# Пароль архива — ~/.config/obraz-parol (600), создаётся здесь при первом запуске;
# один раз кладётся в «Файлы проекта», Светлана записывает его и удаляет файл.
# Яндекс Диск подключается файлом ~/.config/yandex-disk.netrc: есть файл — архив
# частями уходит на Диск и с сервера убирается. Нет — лежит в «Файлах проекта».
set -uo pipefail
umask 077

H=/home/mokeeva
VYDACHA=$H/main/glavpryg-sayt/downloads
ARCH=$VYDACHA/obraz-sayta.tar.gpg
PAROL=$H/.config/obraz-parol
SITE_DB=$H/.local/share/webui2/site.db
STAGE=$H/.obraz-staging
LOG=$H/backups/obraz.log
OSHIBKA=$VYDACHA/OSHIBKA-OBRAZA.txt
YA_NETRC=$H/.config/yandex-disk.netrc
ZAPAS_MB=1024        # столько оставляем свободным на диске сервера

log() { echo "$(date -u +'%d.%m.%Y %H:%M') UTC  $*" >> "$LOG"; }
fail() {
    log "ОШИБКА: $*"
    rm -rf "$STAGE"
    echo "Образ не собран: $*. Подробности — $LOG" > "$OSHIBKA"
    exit 1
}

exec 9>"$H/backups/.obraz.lock"
flock -n 9 || exit 0
log "--- сборка ---"

if [ ! -s "$PAROL" ]; then
    openssl rand -hex 16 | sed -E 's/(.{4})/\1-/g; s/-$//' > "$PAROL"
    chmod 600 "$PAROL"
    { echo "Пароль архива obraz-sayta.tar.gpg. Запиши его на бумагу, потом удали этот файл."
      echo; cat "$PAROL"; } > "$VYDACHA/PAROL-OBRAZA-zapishi-i-udali.txt"
fi

rm -f "$ARCH"
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
( cd "$H/tools/beget" && .venv/bin/python vygruzit.py "$STAGE" ) >> "$LOG" 2>&1 \
    || fail "не выгружен сайт с Beget"
cp "$H/main/infra/obraz/vosstanovit.sh" "$H/main/infra/obraz/PAMYATKA.md" "$VYDACHA/"

SVOBODNO=$(df -m --output=avail "$VYDACHA" | tail -1 | tr -d ' ')
PREDEL=$(( SVOBODNO - ZAPAS_MB ))
[ "$PREDEL" -gt 500 ] || fail "на диске мало места: $SVOBODNO МБ"

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
    --exclude='home/mokeeva/main/glavpryg-sayt/downloads/obraz-sayta*' \
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
  | gpg --batch --yes --pinentry-mode loopback --passphrase-file "$PAROL" --symmetric \
        --cipher-algo AES256 --compress-algo zlib --compress-level 6 -o - \
  | head -c $(( PREDEL * 1024 * 1024 )) > "$ARCH"
KODY=("${PIPESTATUS[@]}")
RAZMER=$(stat -c %s "$ARCH")
rm -rf "$STAGE"
[ "$RAZMER" -lt $(( PREDEL * 1024 * 1024 )) ] || { rm -f "$ARCH"; fail "архив не поместился на диск ($PREDEL МБ)"; }
[ "${KODY[0]}" -le 1 ] && [ "${KODY[1]}" -eq 0 ] || { rm -f "$ARCH"; fail "сборка прервалась: ${KODY[*]}"; }

# Проверка: архив расшифровывается и в нём есть главное
SPISOK=$(gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$PAROL" -d "$ARCH" | tar -tf - ) \
    || { rm -f "$ARCH"; fail "архив не читается"; }
for nuzhno in home/mokeeva/.obraz-staging/site.db home/mokeeva/.obraz-staging/glavpryg-rezerv.tar \
              home/mokeeva/.obraz-staging/beget-baza.sql.gz home/mokeeva/.config/webui2/webui2.env \
              home/mokeeva/main/CLAUDE.md etc/nginx/nginx.conf; do
    grep -qx "$nuzhno" <<<"$SPISOK" || { rm -f "$ARCH"; fail "в архиве нет $nuzhno"; }
done
sha256sum "$ARCH" | cut -d' ' -f1 > "$VYDACHA/obraz-sayta.sha256"
rm -f "$OSHIBKA"
log "образ готов: $(( RAZMER / 1048576 )) МБ, записей $(wc -l <<<"$SPISOK")"

# Яндекс Диск: частями по 1 ГБ, чтобы обрыв не губил всю загрузку
if [ -s "$YA_NETRC" ]; then
    ya() { curl -sS --netrc-file "$YA_NETRC" --retry 5 --max-time 14400 "$@"; }
    ya -o /dev/null -X MKCOL https://webdav.yandex.ru/obraz-sayta/ || true
    cd "$VYDACHA" || fail "нет папки выдачи"
    split -b 1G -d "$ARCH" "$STAGE-chast-"
    for f in "$STAGE"-chast-*; do
        KOD=$(ya -o /dev/null -w '%{http_code}' -T "$f" "https://webdav.yandex.ru/obraz-sayta/$(basename "$f" | sed 's/.*chast-/chast-/')")
        case "$KOD" in 201|204) rm -f "$f" ;; *) rm -f "$STAGE"-chast-*; fail "Яндекс Диск: код $KOD" ;; esac
    done
    for f in obraz-sayta.sha256 vosstanovit.sh PAMYATKA.md; do ya -o /dev/null -T "$f" "https://webdav.yandex.ru/obraz-sayta/$f"; done
    log "образ на Яндекс Диске"
fi
