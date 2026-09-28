#!/bin/bash
# Проверка, что сайт «Главпрыг» действительно отдаётся по адресу, а не только
# лежит в каталоге. Запускается снаружи, обычным HTTP-запросом:
#
#     bash glavpryg-sayt/tests/check-glavpryg.sh [https://mokeevasky.ru]
#
# До выкладки она обязана падать (первый же случай даёт 404) — этим и проверяется
# сама проверка, правило 12. После выкладки все случаи должны проходить.

set -uo pipefail

OSNOVA=${1:-https://mokeevasky.ru}
ETOT_KATALOG=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ISTOCHNIK=$(dirname "$ETOT_KATALOG")/public

oshibki=0

skazat_horosho() { echo "  ок      — $1"; }
skazat_ploho()   { echo "  ОШИБКА  — $1"; oshibki=$((oshibki + 1)); }

kod() { curl -sS -o /dev/null -w '%{http_code}' "$1"; }
kuda() { curl -sS -o /dev/null -w '%{redirect_url}' "$1"; }

echo "Проверка $OSNOVA/glavpryg"

# 1. Главная страница отдаётся и совпадает с исходником байт в байт.
#    Сравнение по хэшу, а не по строке из вёрстки: когда заглушку сменит
#    настоящий сайт, проверка продолжит работать без правок.
if [ -f "$ISTOCHNIK/index.html" ]; then
    svoy=$(sha256sum < "$ISTOCHNIK/index.html" | cut -d' ' -f1)
    otdano=$(curl -sS "$OSNOVA/glavpryg/" | sha256sum | cut -d' ' -f1)
    if [ "$svoy" = "$otdano" ]; then
        skazat_horosho "главная отдаётся и совпадает с public/index.html"
    else
        skazat_ploho "главная не совпадает с public/index.html (выкладка не проходила?)"
    fi
else
    skazat_ploho "нет исходника $ISTOCHNIK/index.html — не с чем сверять"
fi

# 2. Адрес без завершающего слеша уводит на адрес со слешем, иначе
#    относительные ссылки на странице поедут от корня домена.
k=$(kod "$OSNOVA/glavpryg")
if [ "$k" = "301" ]; then
    skazat_horosho "/glavpryg уводит на /glavpryg/ (301)"
else
    skazat_ploho "/glavpryg отдал $k вместо 301"
fi

# 3. Несуществующая страница внутри сайта — 404 своей страницей, а не 404 домена
otvet=$(curl -sS -w '\n%{http_code}' "$OSNOVA/glavpryg/net-takoy-stranicy-12345")
k=${otvet##*$'\n'}
telo=${otvet%$'\n'*}
if [ "$k" = "404" ]; then
    skazat_horosho "несуществующая страница — 404"
else
    skazat_ploho "несуществующая страница отдала $k вместо 404"
fi
if [ -f "$ISTOCHNIK/404.html" ] && ! grep -q 'Главпрыг' <<<"$telo"; then
    skazat_ploho "404 отдана не страницей сайта (error_page не сработал)"
fi

# 4. Заголовки безопасности на месте. Случай не праздный: add_header внутри
#    location отменяет наследование серверных заголовков, и потерять их можно
#    незаметно — интерфейс их сохранит, а сайт нет.
zagolovki=$(curl -sS -D - -o /dev/null "$OSNOVA/glavpryg/")
for z in "X-Content-Type-Options" "X-Frame-Options" "Referrer-Policy"; do
    if grep -qi "^$z:" <<<"$zagolovki"; then
        skazat_horosho "заголовок $z на месте"
    else
        skazat_ploho "нет заголовка $z"
    fi
done

# 5. HTTP уводится на HTTPS — пароли и вообще всё ходит только по TLS
bez_tls=${OSNOVA/https:/http:}
kuda_ushlo=$(kuda "$bez_tls/glavpryg/")
if [[ "$kuda_ushlo" == https://* ]]; then
    skazat_horosho "HTTP уводит на HTTPS ($kuda_ushlo)"
else
    skazat_ploho "HTTP не увёл на HTTPS (получено «$kuda_ushlo»)"
fi

# 6. Выкладка сайта не задела веб-интерфейс на том же домене
k=$(kod "$OSNOVA/Claude/login")
if [ "$k" = "200" ]; then
    skazat_horosho "/Claude/login по-прежнему отвечает 200"
else
    skazat_ploho "/Claude/login отдал $k — выкладка задела интерфейс"
fi

echo
if [ "$oshibki" -eq 0 ]; then
    echo "Все проверки пройдены."
else
    echo "Провалено проверок: $oshibki"
fi
exit $(( oshibki > 0 ? 1 : 0 ))
