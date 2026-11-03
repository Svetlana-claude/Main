#!/bin/bash
# Разворачивает образ на чистом Ubuntu 24.04. Запуск под root в папке, где лежат
# vosstanovit.sh, программа restic и папка hranilishche (так они лежат в хранилище
# Selectel, бакет klod-kopii-mokeeva, в obraz-sayta-repo/):
#   bash vosstanovit.sh                 — последний снимок
#   bash vosstanovit.sh <номер снимка>  — снимок за другой день; список снимков:
#                                         ./restic -r hranilishche snapshots
# Спросит пароль образа. PROVERKA=1 — стенд: только распаковка и окружение сайта,
# службы не ставятся и не запускаются.
set -euo pipefail
SNIMOK=${1:-latest}
H=/home/mokeeva
PROVERKA=${PROVERKA:-0}
export DEBIAN_FRONTEND=noninteractive
RESTIC=${RESTIC:-./restic}
export RESTIC_REPOSITORY=${RESTIC_REPOSITORY:-hranilishche}

[ "$(id -u)" = 0 ] || { echo "Нужен запуск под root"; exit 1; }
[ -x "$RESTIC" ] || chmod +x "$RESTIC"
[ -d "$RESTIC_REPOSITORY" ] || { echo "Нет папки $RESTIC_REPOSITORY рядом со скриптом"; exit 1; }
if [ -z "${RESTIC_PASSWORD_FILE:-}" ]; then
    read -rsp "Пароль образа: " RESTIC_PASSWORD; echo; export RESTIC_PASSWORD
fi
"$RESTIC" check || { echo "Хранилище повреждено: скачай папку заново"; exit 1; }

apt-get update -qq
apt-get install -y -qq tar python3 python3-venv python3-pip ca-certificates curl sudo git
id mokeeva >/dev/null 2>&1 || useradd -m -s /bin/bash mokeeva

razvernut() { "$RESTIC" dump --tag obraz "$SNIMOK" /obraz.tar | tar -C / -xpf - "$@"; }

echo "== Распаковка =="
razvernut
mkdir -p $H/.local/share/webui2
mv $H/.obraz-staging/site.db $H/.local/share/webui2/site.db
chown -R mokeeva:mokeeva $H
chmod 600 $H/.local/share/webui2/site.db

echo "== Сайт =="
sudo -u mokeeva python3 -m venv $H/main/webui2/.venv
sudo -u mokeeva $H/main/webui2/.venv/bin/pip install -q -r $H/main/webui2/requirements.txt

if [ "$PROVERKA" = 1 ]; then
    echo "== Стенд: службы не трогаю =="
    exit 0
fi

echo "== Службы =="
apt-get install -y -qq software-properties-common
add-apt-repository -y ppa:ondrej/php
apt-get update -qq
apt-get install -y -qq nginx mariadb-server postgresql-16 postfix dovecot-core dovecot-imapd \
    opendkim fail2ban certbot python3-certbot-nginx php8.4-fpm php8.4-cli php8.4-common \
    php8.4-bcmath php8.4-curl php8.4-gd php8.4-intl php8.4-mbstring php8.4-mysql php8.4-opcache \
    php8.4-readline php8.4-xml php8.4-zip
# Установка пакетов могла затереть настройки — возвращаем их из образа
razvernut etc/nginx etc/postfix etc/dovecot etc/opendkim etc/fail2ban etc/php/8.4/fpm/pool.d

echo "== Запуск =="
sudo -u mokeeva crontab $H/.obraz-staging/crontab.mokeeva
systemctl daemon-reload
systemctl enable --now webui2 nginx php8.4-fpm mariadb postfix dovecot opendkim fail2ban
systemctl restart nginx php8.4-fpm

echo "== Хранилище образа =="
# Ночные снимки продолжаются в том же хранилище и с тем же паролем
mkdir -p $H/backups $H/.config
cp -r "$RESTIC_REPOSITORY" $H/backups/obraz-repo
if [ -n "${RESTIC_PASSWORD:-}" ]; then
    printf '%s\n' "$RESTIC_PASSWORD" > $H/.config/obraz-parol
else
    cp "$RESTIC_PASSWORD_FILE" $H/.config/obraz-parol
fi
chmod 600 $H/.config/obraz-parol
chown -R mokeeva:mokeeva $H/backups $H/.config

echo "== Claude =="
curl -fsSL https://claude.ai/install.sh | sudo -u mokeeva bash || echo "Claude поставить не удалось, см. памятку"
echo
echo "Готово. Дальше — шаги из PAMYATKA.md: адрес сервера, вход в Claude, проверка сайта."
echo "Копия сайта Главпрыга с Beget (если была в снимке): $H/.obraz-staging/beget-baza.sql и beget-sayt.tar"
