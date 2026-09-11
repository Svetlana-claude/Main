#!/bin/bash
# Выпуск сертификата Let's Encrypt для веб-интерфейса.
#
# Запуск (ваш ручной шаг, нужен пароль):
#     sudo bash infra/tls-letsencrypt.sh пример.ru www.пример.ru you@example.com
#
# Имён можно передать несколько — сертификат покрывает только перечисленные,
# и www само в их число не входит. Почта опознаётся по собачке, порядок
# остальных доводов не важен; первое имя становится основным, по нему
# называется каталог с сертификатом.
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

WEBROOT=/var/www/certbot
EXPECT_IP=46.8.178.196

# Разбор доводов: с собачкой — почта, остальное — имена. В доменном имени
# собачки не бывает, так что спутать нельзя, и порядок доводов не важен.
DOMAINS=()
EMAIL=""
for arg in "$@"; do
    case "$arg" in
        *@*) EMAIL="$arg" ;;
        *)   DOMAINS+=("$arg") ;;
    esac
done

if [ ${#DOMAINS[@]} -eq 0 ]; then
    echo "Использование: sudo bash infra/tls-letsencrypt.sh <домен> [ещё домены] [почта]" >&2
    exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "нужен root: sudo bash infra/tls-letsencrypt.sh ${DOMAINS[*]}" >&2
    exit 1
fi

# Основное имя: по нему certbot называет каталог с сертификатом, на него потом
# смотрит nginx. Закрепляется явно (--cert-name ниже), иначе при добавлении имён
# certbot может завести соседний каталог вида «домен-0001», и пути разъедутся.
PRIMARY="${DOMAINS[0]}"

echo "=== 1. Куда указывают имена ==="
# Проверяем до выпуска: Let's Encrypt даёт 5 неудач на домен в час, и упереться
# в этот предел из-за неготовой DNS-записи обиднее, чем подождать её.
# Проверяются все имена: одно негодное срывает выпуск целиком, вместе с годными.
for d in "${DOMAINS[@]}"; do
    # «|| true» обязателен: getent возвращает ошибку, если имя не разрешилось,
    # а с set -e и pipefail это оборвало бы скрипт прямо здесь — молча, кодом 2,
    # так и не дойдя до понятного объяснения ниже.
    resolved=$(getent ahostsv4 "$d" | awk '{print $1}' | sort -u | tr '\n' ' ' || true)
    echo "  $d -> ${resolved:-нет}"
    if [ -z "$resolved" ]; then
        echo "ОШИБКА: $d не разрешается в адрес. Заведите A-запись на $EXPECT_IP" >&2
        echo "и подождите обновления DNS — обычно минуты, иногда до часа." >&2
        exit 1
    fi
    if ! grep -qw "$EXPECT_IP" <<<"$resolved"; then
        echo "ОШИБКА: $d указывает не на этот сервер ($EXPECT_IP)." >&2
        echo "Выпуск сорвётся: проверяющий пойдёт по A-записи и попадёт не сюда." >&2
        echo "Если зона на Cloudflare — проверьте, что проксирование выключено" >&2
        echo "(серое облако): с включённым отдаётся адрес Cloudflare, а не наш." >&2
        exit 1
    fi
done

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
# Каждое имя проверяется отдельно: проверяющий ходит по каждому из них.
for d in "${DOMAINS[@]}"; do
    probe="probe-$$-$(date +%s%N)"
    echo "$probe" > "$WEBROOT/.well-known/acme-challenge/$probe"
    code=$(curl -s -o /tmp/$probe.out -w '%{http_code}' --max-time 20 \
           "http://$d/.well-known/acme-challenge/$probe" || echo 000)
    got=$(cat /tmp/$probe.out 2>/dev/null || true)
    rm -f "$WEBROOT/.well-known/acme-challenge/$probe" "/tmp/$probe.out"
    if [ "$code" != "200" ] || [ "$got" != "$probe" ]; then
        echo "ОШИБКА: по имени $d путь проверки не отдаётся (код $code)." >&2
        echo "Ожидался 200 и содержимое файла. Проверьте, что в HTTP-блоке nginx есть" >&2
        echo "location ^~ /.well-known/acme-challenge/ и что конфиг разложен:" >&2
        echo "    sudo webui-deploy" >&2
        exit 1
    fi
    echo "  $d: 200, содержимое совпало"
done

echo "=== 5. Выпуск сертификата ==="
mail_args=(--register-unsafely-without-email)
[ -n "$EMAIL" ] && mail_args=(-m "$EMAIL")
# Почта нужна ради писем об истечении: они приходят, если автопродление молча
# сломалось. Без неё выпуск тоже пройдёт, но о неудачном продлении узнаете
# только по предупреждению в браузере.
d_args=()
for d in "${DOMAINS[@]}"; do d_args+=(-d "$d"); done
# --expand нужен на случай повторного запуска с добавленным именем: без него
# certbot в неинтерактивном режиме упрётся в «уже есть сертификат на часть имён»
# и ничего не сделает. --cert-name закрепляет каталог за основным именем.
certbot certonly --webroot -w "$WEBROOT" "${d_args[@]}" --cert-name "$PRIMARY" \
        --agree-tos --non-interactive --keep-until-expiring --expand "${mail_args[@]}"

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

live="/etc/letsencrypt/live/$PRIMARY"
echo
echo "=== Готово. Сертификат выпущен ==="
openssl x509 -in "$live/fullchain.pem" -noout -subject -issuer -enddate
# Перечень покрытых имён: по нему видно, что www попал в сертификат, а не забыт
openssl x509 -in "$live/fullchain.pem" -noout -ext subjectAltName

cat <<EOF

Осталось переключить nginx на эти пути. Правится в репозитории
(webui/deploy/nginx-webui.conf), в блоке listen 443:

    server_name         ${DOMAINS[*]};
    ssl_certificate     $live/fullchain.pem;
    ssl_certificate_key $live/privkey.pem;

и раскладывается беспарольно:

    sudo webui-deploy

Проверка после этого:

    curl -I https://$PRIMARY/Claude/    # без -k, то есть с проверкой подлинности

EOF
