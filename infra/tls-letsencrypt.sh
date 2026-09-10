#!/bin/bash
# Выпуск сертификата Let's Encrypt для веб-интерфейса.
#
# Запуск (ваш ручной шаг, нужен пароль):
#     sudo bash infra/tls-letsencrypt.sh пример.ru you@example.com
#
# Почему не входит в беспарольный sudo: скрипт ставит пакет и пишет в /etc —
# и то и другое равносильно полному root, см. infra/sudo-allowed.list.
#
# Способ подтверждения владения — webroot, а не плагин --nginx. Плагин правит
# /etc/nginx/sites-available/webui сам, а этот файл раскладывается из репозитория
# (webui/deploy/nginx-webui.conf) и при следующей раскладке правки плагина
# затёрлись бы. Здесь nginx не трогается вовсе: certbot кладёт файл в webroot,
# отдаёт его уже настроенный location в HTTP-блоке.
#
# Скрипт только выпускает сертификат. Переключение nginx на выпущенные пути —
# отдельный шаг в репозитории, см. вывод в конце.

set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"
WEBROOT=/var/www/certbot
EXPECT_IP=46.8.178.196

if [ -z "$DOMAIN" ]; then
    echo "Использование: sudo bash infra/tls-letsencrypt.sh <домен> [почта]" >&2
    exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "нужен root: sudo bash infra/tls-letsencrypt.sh $DOMAIN" >&2
    exit 1
fi

echo "=== 1. Куда указывает $DOMAIN ==="
# Проверяем до выпуска: Let's Encrypt даёт 5 неудач на домен в час, и упереться
# в этот предел из-за неготовой DNS-записи обиднее, чем подождать её.
resolved=$(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u | tr '\n' ' ')
echo "  A-запись: ${resolved:-нет}"
if [ -z "$resolved" ]; then
    echo "ОШИБКА: домен не разрешается в адрес. Заведите A-запись на $EXPECT_IP" >&2
    echo "и подождите обновления DNS — обычно минуты, иногда до часа." >&2
    exit 1
fi
if ! grep -qw "$EXPECT_IP" <<<"$resolved"; then
    echo "ОШИБКА: домен указывает не на этот сервер ($EXPECT_IP)." >&2
    echo "Выпуск сорвётся: проверяющий пойдёт по A-записи и попадёт не сюда." >&2
    exit 1
fi

echo "=== 2. Certbot ==="
if command -v certbot >/dev/null; then
    echo "  уже установлен: $(certbot --version 2>&1)"
else
    echo "  ставлю пакет certbot"
    apt-get update
    apt-get install -y certbot
fi

echo "=== 3. Каталог для проверки владения ==="
mkdir -p "$WEBROOT/.well-known/acme-challenge"
chown -R root:root "$WEBROOT"
chmod -R 755 "$WEBROOT"
echo "  $WEBROOT"

echo "=== 4. Проверка, что путь проверки отдаётся по HTTP ==="
# Тот же путь, которым пойдёт проверяющий. Если здесь редирект на HTTPS или 404 —
# выпуск сорвётся, и лучше узнать это сейчас, не потратив попытку.
probe="probe-$$-$(date +%s)"
echo "$probe" > "$WEBROOT/.well-known/acme-challenge/$probe"
code=$(curl -s -o /tmp/$probe.out -w '%{http_code}' --max-time 20 \
       "http://$DOMAIN/.well-known/acme-challenge/$probe" || echo 000)
got=$(cat /tmp/$probe.out 2>/dev/null || true)
rm -f "$WEBROOT/.well-known/acme-challenge/$probe" "/tmp/$probe.out"
if [ "$code" != "200" ] || [ "$got" != "$probe" ]; then
    echo "ОШИБКА: путь проверки не отдаётся (код $code)." >&2
    echo "Ожидался 200 и содержимое файла. Проверьте, что в HTTP-блоке nginx есть" >&2
    echo "location ^~ /.well-known/acme-challenge/ и что конфиг разложен:" >&2
    echo "    sudo webui-deploy" >&2
    exit 1
fi
echo "  200, содержимое совпало"

echo "=== 5. Выпуск сертификата ==="
mail_args=(--register-unsafely-without-email)
[ -n "$EMAIL" ] && mail_args=(-m "$EMAIL")
# Почта нужна ради писем об истечении: они приходят, если автопродление молча
# сломалось. Без неё выпуск тоже пройдёт, но о неудачном продлении узнаете
# только по предупреждению в браузере.
certbot certonly --webroot -w "$WEBROOT" -d "$DOMAIN" \
        --agree-tos --non-interactive --keep-until-expiring "${mail_args[@]}"

echo "=== 6. Перезагрузка nginx после продления ==="
# Продлением занимается таймер certbot.timer, поставленный пакетом. Он обновляет
# файлы сертификата, но nginx держит прежние в памяти — без перезагрузки сайт
# продолжит отдавать просроченный. Hook выполняется только когда сертификат
# действительно обновился.
hook=/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
mkdir -p "$(dirname "$hook")"
cat > "$hook" <<'EOF'
#!/bin/bash
# Перезагрузка nginx после успешного продления сертификата.
systemctl reload nginx
EOF
chmod 755 "$hook"
echo "  $hook"
systemctl enable --now certbot.timer 2>/dev/null || true
systemctl list-timers certbot.timer --no-pager 2>/dev/null | head -3

live="/etc/letsencrypt/live/$DOMAIN"
echo
echo "=== Готово. Сертификат выпущен ==="
openssl x509 -in "$live/fullchain.pem" -noout -subject -issuer -enddate

cat <<EOF

Осталось переключить nginx на эти пути. Правится в репозитории
(webui/deploy/nginx-webui.conf), в блоке listen 443:

    server_name         $DOMAIN;
    ssl_certificate     $live/fullchain.pem;
    ssl_certificate_key $live/privkey.pem;

и раскладывается беспарольно:

    sudo webui-deploy

Проверка после этого:

    curl -I https://$DOMAIN/Claude/    # без -k, то есть с проверкой подлинности

EOF
