#!/bin/bash
# Проверка, что сайт «Главпрыг» действительно отдаётся по адресу, а не только
# лежит в каталоге. Запускается снаружи, обычным HTTP-запросом:
#
#     bash glavpryg-sayt/tests/check-glavpryg.sh [https://mokeevasky.ru]
#
# Это первый рубеж — быстрый и без браузера. Что он поймать не может (вёрстку,
# консоль, нажатия), ловят соседи: tests/snimki.py и tests/check-adminka.py.

set -uo pipefail

OSNOVA=${1:-https://mokeevasky.ru}
SAYT="$OSNOVA/glavpryg"

oshibki=0

skazat_horosho() { echo "  ок      — $1"; }
skazat_ploho()   { echo "  ОШИБКА  — $1"; oshibki=$((oshibki + 1)); }

kod()  { curl -sS -o /dev/null -w '%{http_code}' "$1"; }
kuda() { curl -sS -o /dev/null -w '%{redirect_url}' "$1"; }

echo "Проверка $SAYT"

# 1. Приложение отвечает, а не отдаётся исходником. Признак именно работающего
#    PHP — куки сессии: их ставит Laravel, а раздача файла nginx-ом не ставит
#    ничего. ⚠️ По разметке это не определить: csrf-токен есть не на каждой
#    странице сайта, на главной его нет вовсе — проверка на него краснела
#    там, где всё в порядке.
glavnaya=$(curl -sS "$SAYT/")
zagolovki_glavnoy=$(curl -sS -D - -o /dev/null "$SAYT/")
if [ -z "$glavnaya" ]; then
    skazat_ploho "главная пуста — приложение не ответило"
elif grep -qi 'set-cookie:.*glavpryg-session' <<<"$zagolovki_glavnoy"; then
    skazat_horosho "главную собрало приложение (ставит куку сессии)"
else
    skazat_ploho "нет куки сессии — PHP не отработал, отдан файл?"
fi
if grep -qi 'ГЛАВПРЫГ\|Главпрыг' <<<"$glavnaya"; then
    skazat_horosho "на главной есть название сайта"
else
    skazat_ploho "на главной нет названия сайта — отдана чужая страница"
fi

# 2. Внутренние страницы. Без try_files на index.php открывалась бы только
#    главная, а все адреса ниже давали бы 404 — случай нередкий и незаметный.
for put in services/tandem prices certificate certificate/order blog about \
           vr-trainer contacts admin/login; do
    k=$(kod "$SAYT/$put")
    if [ "$k" = "200" ]; then
        skazat_horosho "/$put — 200"
    else
        skazat_ploho "/$put отдал $k вместо 200"
    fi
done

# 3. Адрес без завершающего слеша уводит на адрес со слешем, иначе
#    относительные ссылки на странице поедут от корня домена.
k=$(kod "$OSNOVA/glavpryg")
if [ "$k" = "301" ]; then
    skazat_horosho "/glavpryg уводит на /glavpryg/ (301)"
else
    skazat_ploho "/glavpryg отдал $k вместо 301"
fi

# 4. Ссылки приложение собирает от подкаталога, а не от корня домена. Это
#    главная беда жизни в подкаталоге: Laravel берёт основу из APP_URL и
#    SCRIPT_NAME, и стоит им разъехаться — вход в админку уводит на
#    несуществующий /admin/login.
uvod=$(kuda "$SAYT/admin/main")
if [[ "$uvod" == *"/glavpryg/"* ]] || [ -z "$uvod" ]; then
    skazat_horosho "приложение собирает ссылки от /glavpryg/ (увод: ${uvod:-нет})"
else
    skazat_ploho "увод мимо подкаталога: $uvod"
fi

# 5. Два пути, отданные сайту от корня домена (см. deploy/nginx-glavpryg.conf).
#    Без них сайт открывается без картинок, а админка — без оформления.
for put in "/images/hero-bg.jpeg" "/vendor/orchid/css/orchid.css"; do
    k=$(kod "$OSNOVA$put")
    if [ "$k" = "200" ]; then
        skazat_horosho "$put — 200"
    else
        skazat_ploho "$put отдал $k — сайт останется без оформления"
    fi
done

# 6. Наружу не должно вылезать лишнее: .env с паролем базы, каталог исходников.
for put in "/glavpryg/.env" "/glavpryg/storage/logs/laravel.log"; do
    k=$(kod "$OSNOVA$put")
    if [ "$k" = "200" ]; then
        skazat_ploho "$put отдаётся наружу ($k) — закрыть немедленно"
    else
        skazat_horosho "$put наружу не отдаётся ($k)"
    fi
done

# 7. Несуществующая страница — 404 своей страницей, а не 500 и не 200
otvet=$(curl -sS -w '\n%{http_code}' "$SAYT/net-takoy-stranicy-12345")
k=${otvet##*$'\n'}
if [ "$k" = "404" ]; then
    skazat_horosho "несуществующая страница — 404"
else
    skazat_ploho "несуществующая страница отдала $k вместо 404"
fi

# 8. Заголовки безопасности на месте. Случай не праздный: add_header внутри
#    location отменяет наследование серверных заголовков, и потерять их можно
#    незаметно — интерфейс их сохранит, а сайт нет.
zagolovki=$(curl -sS -D - -o /dev/null "$SAYT/")
for z in "X-Content-Type-Options" "X-Frame-Options" "Referrer-Policy"; do
    if grep -qi "^$z:" <<<"$zagolovki"; then
        skazat_horosho "заголовок $z на месте"
    else
        skazat_ploho "нет заголовка $z"
    fi
done

# 9. HTTP уводится на HTTPS — пароли и вообще всё ходит только по TLS
bez_tls=${OSNOVA/https:/http:}
kuda_ushlo=$(kuda "$bez_tls/glavpryg/")
if [[ "$kuda_ushlo" == https://* ]]; then
    skazat_horosho "HTTP уводит на HTTPS ($kuda_ushlo)"
else
    skazat_ploho "HTTP не увёл на HTTPS (получено «$kuda_ushlo»)"
fi

# 10. Сайт не задел веб-интерфейс на том же домене
k=$(kod "$OSNOVA/Claude/login")
if [ "$k" = "200" ]; then
    skazat_horosho "/Claude/login по-прежнему отвечает 200"
else
    skazat_ploho "/Claude/login отдал $k — сайт задел интерфейс"
fi

# 11. Наша копия макета админки не отстала от Orchid. Без неё в подкаталоге
#     не работает ни одно поле загрузки файлов — а отстаёт она молча.
if /usr/bin/php8.4 "$(dirname "$0")/check-maket-orchid.php" > /dev/null; then
    skazat_horosho "копия макета админки совпадает с Orchid"
else
    skazat_ploho "копия макета админки разошлась с Orchid — tests/check-maket-orchid.php"
fi

echo
if [ "$oshibki" -eq 0 ]; then
    echo "Все проверки пройдены."
else
    echo "Провалено проверок: $oshibki"
fi
exit $(( oshibki > 0 ? 1 : 0 ))
