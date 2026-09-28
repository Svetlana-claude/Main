#!/bin/bash
# Выкладка сайта «Главпрыг»: файлы на место, правила nginx на место, перезагрузка.
#
#     sudo bash glavpryg-sayt/deploy/vylozhit.sh [каталог-с-сайтом]
#
# Без довода берётся glavpryg-sayt/public. Довод нужен, когда исходники
# распакованы в другое место или у сайта есть сборка: указывается каталог,
# в котором лежит index.html.
#
# Почему сайт не отдаётся прямо из репозитория: домашний каталог закрыт для
# www-data, и nginx до файлов просто не дошёл бы. А открывать его нельзя —
# рядом лежат рабочие каталоги проектов. Поэтому сайт копируется в
# /var/www/glavpryg под root с правами «всем читать, никому не писать»:
# ни пользователь, ни приложение, ни агент в отданный наружу каталог не пишут.

set -euo pipefail

ETOT_KATALOG=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROEKT=$(dirname "$ETOT_KATALOG")
ISTOCHNIK=${1:-$PROEKT/public}
NAZNACHENIE=/var/www/glavpryg
SNIPPET=/etc/nginx/snippets/glavpryg.conf
KONFIG_DOMENA=/etc/nginx/sites-available/webui

if [ "$(id -u)" -ne 0 ]; then
    echo "нужен root: sudo bash $0 $*" >&2
    exit 1
fi

if [ ! -d "$ISTOCHNIK" ]; then
    echo "нет каталога с сайтом: $ISTOCHNIK" >&2
    exit 1
fi
ISTOCHNIK=$(cd "$ISTOCHNIK" && pwd)

# Архив часто распаковывается одной вложенной папкой. Спускаемся в неё, но
# только если она единственная и index.html лежит именно там: угадывать корень
# сайта среди нескольких папок нельзя — выложится не то.
if [ ! -f "$ISTOCHNIK/index.html" ]; then
    vlozhennye=("$ISTOCHNIK"/*/)
    if [ ${#vlozhennye[@]} -eq 1 ] && [ -f "${vlozhennye[0]}index.html" ]; then
        ISTOCHNIK=${vlozhennye[0]%/}
        echo "корень сайта найден вложенным: $ISTOCHNIK"
    fi
fi

if [ ! -f "$ISTOCHNIK/index.html" ]; then
    echo "в $ISTOCHNIK нет index.html — это точно корень сайта?" >&2
    echo "укажите каталог доводом: sudo bash $0 <каталог>" >&2
    exit 1
fi

# 1. Файлы сайта. Собираем рядом и подменяем переименованием: полусобранный
#    каталог не должен ни секунды отвечать посетителю.
NOVOE="$NAZNACHENIE.novoe"
STAROE="$NAZNACHENIE.staroe"
rm -rf "$NOVOE" "$STAROE"
mkdir -p "$(dirname "$NAZNACHENIE")"
cp -a "$ISTOCHNIK" "$NOVOE"
chown -R root:root "$NOVOE"
find "$NOVOE" -type d -exec chmod 755 {} +
find "$NOVOE" -type f -exec chmod 644 {} +

if [ -d "$NAZNACHENIE" ]; then
    mv "$NAZNACHENIE" "$STAROE"
fi
mv "$NOVOE" "$NAZNACHENIE"
rm -rf "$STAROE"
echo "файлы сайта: $ISTOCHNIK -> $NAZNACHENIE"

# 2. Правила nginx
install -o root -g root -m 0644 "$ETOT_KATALOG/nginx-glavpryg.conf" "$SNIPPET"
echo "правила nginx: $SNIPPET"

# 3. Врезка в server-блок домена. Правим не живой файл, а репозиторий: живой
#    раскладывает webui-deploy, и правка руками потерялась бы при следующей
#    выкладке интерфейса.
if ! grep -q 'snippets/glavpryg.conf' "$KONFIG_DOMENA"; then
    echo >&2
    echo "ОСТАЛСЯ ОДИН ШАГ: в $KONFIG_DOMENA нет строки подключения." >&2
    echo "Она уже есть в репозитории, разложить конфиг домена:" >&2
    echo "    sudo cp $PROEKT/../webui/deploy/nginx-webui.conf $KONFIG_DOMENA" >&2
    echo "    sudo nginx -t && sudo systemctl reload nginx" >&2
    echo >&2
    echo "Файлы сайта и правила уже на месте — после этого шага адрес заработает." >&2
    exit 2
fi

nginx -t
systemctl reload nginx
echo "готово: https://mokeevasky.ru/glavpryg/"
