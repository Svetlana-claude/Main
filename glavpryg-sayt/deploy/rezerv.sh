#!/bin/bash
# Резервная копия сайта «Главпрыг» — всё, что нужно, чтобы поднять сайт заново.
#
# Запуск вручную:  bash glavpryg-sayt/deploy/rezerv.sh
# По расписанию:   ежедневно из crontab пользователя mokeeva (04:10)
#
# Один архив glavpryg-rezerv-<метка>.tar содержит:
#   baza.sql.gz     — база MariaDB `glavpryg` (заказы, сертификаты, настройки, тексты)
#   faily.tar.gz    — загруженное из админки: storage/app (фото, вложения)
#   kod.bundle      — git-репозиторий сайта со всей историей (шаблоны сертификатов, шрифты)
#   env             — /var/www/glavpryg/.env (ключ приложения, пароли — секрет!)
#   pochta.tar.gz   — ящик glavpryg@mokeevasky.ru, ключ DKIM, настройки Postfix/Dovecot
#   VOSSTANOVLENIE.txt — как развернуть
#
# Хранение: 14 копий в /home/mokeeva/backups/glavpryg/, последняя — ещё и в
# «Файлах проекта» (glavpryg-sayt/downloads/rezerv/), чтобы забрать её с сервера:
# копия на том же диске от отказа сервера не спасает.

set -uo pipefail

SAYT=/var/www/glavpryg
DEST=/home/mokeeva/backups/glavpryg
SHARE=/home/mokeeva/main/glavpryg-sayt/downloads/rezerv
KEEP=14
LOG="$DEST/rezerv.log"

STAMP=$(date +%Y%m%d-%H%M%S)
WORK=$(mktemp -d)
ARCH="$DEST/glavpryg-rezerv-$STAMP.tar"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$DEST" "$SHARE"
chmod 700 "$DEST"

log() { printf '%s  %s\n' "$(date '+%d.%m.%Y %H:%M:%S')" "$1" | tee -a "$LOG"; }
fail() { log "ОШИБКА: $1"; exit 1; }

log "--- начало резервной копии ---"

# ── База ──────────────────────────────────────────────────────────────
# --single-transaction: снимок без блокировки, сайт работает дальше.
sudo -n mysqldump --single-transaction --routines --triggers --default-character-set=utf8mb4 glavpryg \
    2>>"$LOG" | gzip -9 > "$WORK/baza.sql.gz"
[ "${PIPESTATUS[0]}" -eq 0 ] || fail "mysqldump не отработал"
gzip -t "$WORK/baza.sql.gz" || fail "архив базы повреждён"
# Архив читается один раз и без `grep -q`: см. SIGPIPE в infra/pg-backup.sh.
FOUND=$(gunzip -c "$WORK/baza.sql.gz" | grep -oE '^CREATE TABLE `[a-z_]+`|^-- Dump completed')
case "$FOUND" in *'Dump completed'*) ;; *) fail "выгрузка базы обрезана" ;; esac
for t in users settings certificate_orders certificates pages prices; do
    case "$FOUND" in *"CREATE TABLE \`$t\`"*) ;; *) fail "в выгрузке нет таблицы $t" ;; esac
done

# ── Загруженные файлы, код, настройки ─────────────────────────────────
tar -C "$SAYT/storage" -czf "$WORK/faily.tar.gz" app || fail "не собраны файлы storage/app"
git -C "$SAYT" bundle create "$WORK/kod.bundle" --all 2>>"$LOG" || fail "не собран git bundle"
git bundle verify "$WORK/kod.bundle" >/dev/null 2>>"$LOG" || fail "git bundle не проходит проверку"
cp "$SAYT/.env" "$WORK/env" || fail "нет .env"

# ── Почта ─────────────────────────────────────────────────────────────
sudo -n tar -C / -czf "$WORK/pochta.tar.gz" home/glavpryg/Maildir etc/opendkim etc/opendkim.conf \
    etc/postfix/main.cf etc/postfix/master.cf etc/dovecot/conf.d/99-mokeevasky.conf 2>>"$LOG" \
    || fail "не собрана почта"
sudo -n chown "$(id -u):$(id -g)" "$WORK/pochta.tar.gz"

cat > "$WORK/VOSSTANOVLENIE.txt" <<'EOF'
Восстановление сайта «Главпрыг» из резервной копии
=================================================
Подробно — glavpryg-sayt/README.md, раздел «Резервная копия» (репозиторий Main).

1. Код:     git clone kod.bundle /var/www/glavpryg
2. Настройки: cp env /var/www/glavpryg/.env
3. Пакеты:  cd /var/www/glavpryg && composer install --no-dev
4. База:    создать базу и пользователя glavpryg (пароль — DB_PASSWORD в env), затем
            gunzip -c baza.sql.gz | sudo mysql glavpryg
5. Файлы:   tar -C /var/www/glavpryg/storage -xzf faily.tar.gz
            php8.4 artisan storage:link
6. Сервер:  nginx и PHP-FPM — glavpryg-sayt/deploy/ (репозиторий Main)
7. Почта:   sudo tar -C / -xzf pochta.tar.gz, затем перезапустить postfix dovecot opendkim
EOF

tar -C "$WORK" -cf "$ARCH" baza.sql.gz faily.tar.gz kod.bundle env pochta.tar.gz VOSSTANOVLENIE.txt \
    || fail "не собран общий архив"
chmod 600 "$ARCH"
log "копия готова: $(basename "$ARCH"), $(du -h "$ARCH" | cut -f1)"

# ── Последняя копия — в «Файлы проекта», чтобы забрать её с сервера ───
rm -f "$SHARE"/glavpryg-rezerv-*.tar
cp -p "$ARCH" "$SHARE/" || fail "не скопирована в downloads"

# ── Уборка старых ─────────────────────────────────────────────────────
ls -1t "$DEST"/glavpryg-rezerv-*.tar 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
log "--- готово: копий $(ls -1 "$DEST"/glavpryg-rezerv-*.tar | wc -l), занято $(du -sh "$DEST" | cut -f1) ---"
