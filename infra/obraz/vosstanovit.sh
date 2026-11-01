#!/bin/bash
# Разворачивает образ на чистом Ubuntu 24.04. Запуск под root:
#   bash vosstanovit.sh            (в папке с частями obraz-chast-*)
#   bash vosstanovit.sh obraz-sayta.tar.gpg
# Спросит пароль архива. PROVERKA=1 — стенд: только распаковка и окружение сайта,
# службы не ставятся и не запускаются.
set -euo pipefail
ARCH=${1:-obraz-sayta.tar.gpg}
if [ ! -f "$ARCH" ]; then
    ls obraz-chast-* >/dev/null 2>&1 || { echo "Нет частей obraz-chast-* в этой папке"; exit 1; }
    sha256sum -c obraz-chasti.sha256 || { echo "Часть повреждена: скачай её заново"; exit 1; }
    cat obraz-chast-* > "$ARCH"
fi
H=/home/mokeeva
PROVERKA=${PROVERKA:-0}
export DEBIAN_FRONTEND=noninteractive

[ "$(id -u)" = 0 ] || { echo "Нужен запуск под root"; exit 1; }
apt-get update -qq
apt-get install -y -qq gnupg tar python3 python3-venv python3-pip ca-certificates curl sudo git
id mokeeva >/dev/null 2>&1 || useradd -m -s /bin/bash mokeeva

rasshifrovat() {
    gpg --quiet --pinentry-mode loopback ${OBRAZ_PAROL_FILE:+--batch --passphrase-file "$OBRAZ_PAROL_FILE"} -d "$ARCH"
}

echo "== Распаковка =="
rasshifrovat | tar -C / -xpf -
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
rasshifrovat | tar -C / -xpf - etc/nginx etc/postfix etc/dovecot etc/opendkim etc/fail2ban etc/php/8.4/fpm/pool.d

echo "== Запуск =="
sudo -u mokeeva crontab $H/.obraz-staging/crontab.mokeeva
systemctl daemon-reload
systemctl enable --now webui2 nginx php8.4-fpm mariadb postfix dovecot opendkim fail2ban
systemctl restart nginx php8.4-fpm

echo "== Claude =="
curl -fsSL https://claude.ai/install.sh | sudo -u mokeeva bash || echo "Claude поставить не удалось, см. памятку"
echo
echo "Готово. Дальше — шаги из PAMYATKA.md: адрес сервера, вход в Claude, проверка сайта."
echo "Копия сайта Главпрыга с Beget: $H/.obraz-staging/beget-baza.sql.gz и beget-sayt.tgz"
