#!/bin/bash
# Обновление сайта «Главпрыг» новой поставкой разработчика.
#
#     sudo bash glavpryg-sayt/deploy/obnovit.sh <каталог-с-новой-версией>
#
# Довод — каталог, в котором лежит корень приложения (artisan, composer.json,
# public/). Распакованный архив часто содержит одну вложенную папку: если
# корень найдётся в ней и она единственная, скрипт спустится туда сам.
#
# Порядок взят из «УСТАНОВКА.md» разработчика, §7: дамп → заглушка → файлы →
# миграции → сброс кэшей → снятие заглушки. К нему добавлено то, чего в
# инструкции нет, а без чего обновление на этой машине ломает сайт:
#
#   • .env и storage/ переносятся из прежней версии. В поставке .env нет вовсе,
#     а storage/ хранит загруженные из админки картинки — перезапись пустым
#     каталогом уносит их безвозвратно.
#   • Прежняя версия остаётся рядом в /var/www/glavpryg.staroe и не стирается:
#     это единственный путь назад, если новая поставка не заработает
#     (правило 1 — ничего не удаляем без спроса).
#   • Ссылка glavpryg-koren/glavpryg и storage:link создаются заново: обе
#     указывают внутрь подменённого каталога и подмену не переживают.
#   • Правила nginx и пул PHP-FPM раскладываются из репозитория: они часть
#     сайта, а не машины, и должны ехать вместе с ним.

set -euo pipefail

ETOT_KATALOG=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROEKT=$(dirname "$ETOT_KATALOG")
SAYT=/var/www/glavpryg
KOREN=/var/www/glavpryg-koren
SNIPPET=/etc/nginx/snippets/glavpryg.conf
PUL=/etc/php/8.4/fpm/pool.d/glavpryg.conf
KONFIG_DOMENA=/etc/nginx/sites-available/webui
SNIMOK=/var/backups/glavpryg

# ⚠️ Именно 8.4, а не системный php. «УСТАНОВКА.md» обещает 8.3, но
# vendor/composer/platform_check.php в поставке требует >= 8.4.0 и на 8.3
# приложение падает первой же строкой.
PHP=/usr/bin/php8.4

# Файлы сайта принадлежат человеку, а группа — www-data: nginx и PHP читают
# по группе, посторонним не видно ничего (каталоги 2750, файлы 0640).
# Раздавать дерево во владение www-data нельзя — тогда приложение получает
# право переписывать собственный код.
VLADELETS=${SUDO_USER:-mokeeva}

if [ "$(id -u)" -ne 0 ]; then
    echo "нужен root: sudo bash $0 $*" >&2
    exit 1
fi

# ⚠️ С 03.10.2026 сайт — git-репозиторий, и правки идут коммитами в нём, а не
# патчами поверх поставки. Этот скрипт подменяет каталог целиком: история и
# всё незакоммиченное уехали бы в glavpryg.staroe, а сайт собрался бы из
# архива плюс pravki/ — то есть без всего, что сделано после патча 04.
if [ -d "$SAYT/.git" ] && [ "${NAD_GIT:-}" != "da" ]; then
    echo "сайт ведётся в git ($SAYT/.git) — правки коммитятся там, поставкой не обновляется." >&2
    echo "Если новая поставка всё же пришла: влить её веткой в git, а не этим скриптом." >&2
    echo "Запустить вопреки этому: NAD_GIT=da sudo -E bash $0 <каталог>" >&2
    exit 1
fi

if [ $# -lt 1 ]; then
    echo "укажите каталог с новой версией: sudo bash $0 <каталог>" >&2
    exit 1
fi

ISTOCHNIK=$1
if [ ! -d "$ISTOCHNIK" ]; then
    echo "нет каталога: $ISTOCHNIK" >&2
    exit 1
fi
ISTOCHNIK=$(cd "$ISTOCHNIK" && pwd)

# Спускаемся во вложенную папку, только если она единственная и корень там:
# угадывать корень среди нескольких папок нельзя — выложится не то.
if [ ! -f "$ISTOCHNIK/artisan" ]; then
    vlozhennye=("$ISTOCHNIK"/*/)
    if [ ${#vlozhennye[@]} -eq 1 ] && [ -f "${vlozhennye[0]}artisan" ]; then
        ISTOCHNIK=${vlozhennye[0]%/}
        echo "корень приложения найден вложенным: $ISTOCHNIK"
    fi
fi

for obyazatelno in artisan composer.json public/index.php; do
    if [ ! -e "$ISTOCHNIK/$obyazatelno" ]; then
        echo "в $ISTOCHNIK нет $obyazatelno — это точно корень приложения?" >&2
        exit 1
    fi
done

# ⚠️ Поставка без vendor/ этим скриптом не ставится: composer на машине нет,
# а тянуть зависимости из сети на боевом сервере — отдельное решение.
if [ ! -d "$ISTOCHNIK/vendor" ]; then
    echo "в поставке нет vendor/ — зависимости надо поставить заранее:" >&2
    echo "    cd $ISTOCHNIK && composer install --no-dev --optimize-autoloader" >&2
    exit 1
fi

if [ ! -f "$SAYT/.env" ]; then
    echo "нет $SAYT/.env — сайт ещё не установлен, обновлять нечего." >&2
    echo "Первая установка идёт по glavpryg-sayt/README.md." >&2
    exit 1
fi

NOVOE="$SAYT.novoe"
STAROE="$SAYT.staroe"
METKA=$(date +%Y%m%d-%H%M%S)

kak_vladelec() { sudo -u "$VLADELETS" "$@"; }

# 0. Дамп базы до всего остального. Миграции новой версии могут переписать
#    таблицы так, что обратной дороги не будет, а откат файлов без отката
#    базы даёт старое приложение поверх новой схемы.
mkdir -p "$SNIMOK"
chmod 700 "$SNIMOK"
POLZOVATEL=$(grep -oP '^DB_USERNAME=\K.*' "$SAYT/.env")
BAZA=$(grep -oP '^DB_DATABASE=\K.*' "$SAYT/.env")
PAROL=$(grep -oP '^DB_PASSWORD=\K.*' "$SAYT/.env")
MYSQL_PWD="$PAROL" mysqldump -u "$POLZOVATEL" "$BAZA" | gzip > "$SNIMOK/baza-$METKA.sql.gz"
chmod 600 "$SNIMOK/baza-$METKA.sql.gz"
echo "дамп базы: $SNIMOK/baza-$METKA.sql.gz"

# 1. Заглушка. С этой минуты посетитель видит «сайт на обслуживании»,
#    а не полусобранное приложение. Признак заглушки лежит в storage/ и
#    переезжает в новую версию вместе с ним — снимет его шаг 5.
(cd "$SAYT" && kak_vladelec "$PHP" artisan down) || true

# 2. Новая версия собирается рядом и встаёт подменой каталога: сайт не должен
#    ни секунды отвечать из наполовину скопированного дерева.
rm -rf "$NOVOE"
cp -a "$ISTOCHNIK" "$NOVOE"

# Переносим то, что принадлежит машине, а не поставке
cp -a "$SAYT/.env" "$NOVOE/.env"
rm -rf "$NOVOE/storage"
cp -a "$SAYT/storage" "$NOVOE/storage"

# ⚠️ Наши правки в чужом коде. Подмена каталога уносит их без следа, поэтому
# они хранятся патчами в pravki/ и накладываются здесь, по порядку имён.
# Не лёг патч — останавливаемся до подмены каталога: сайт продолжает работать
# на прежней версии, и разбираться можно спокойно.
PRAVKI="$PROEKT/pravki"
if [ -d "$PRAVKI" ]; then
    for zaplata in "$PRAVKI"/*.patch; do
        [ -e "$zaplata" ] || break
        if ! (cd "$NOVOE" && patch -p1 --forward --dry-run < "$zaplata" >/dev/null 2>&1); then
            echo >&2
            echo "патч не ложится на новую поставку: $(basename "$zaplata")" >&2
            echo "Разработчик переписал то же место. Разобрать вручную:" >&2
            echo "    cd $NOVOE && patch -p1 < $zaplata" >&2
            echo "Сайт работает на прежней версии, ничего не подменено." >&2
            rm -rf "$NOVOE"
            exit 1
        fi
        (cd "$NOVOE" && patch -p1 --forward < "$zaplata" >/dev/null)
        echo "правка наложена: $(basename "$zaplata")"
    done
fi

chown -R "$VLADELETS":www-data "$NOVOE"
find "$NOVOE" -type d -exec chmod 2750 {} +
find "$NOVOE" -type f -exec chmod 0640 {} +
chmod 0640 "$NOVOE/.env"
chmod +x "$NOVOE/artisan"
# Приложению нужно писать только сюда — и больше никуда
chmod -R 2770 "$NOVOE/storage" "$NOVOE/bootstrap/cache"

# ⚠️ Прежнюю версию не стираем — она и есть путь назад. Позапрошлую убирают
#    руками после того, как новая отработала день.
rm -rf "$STAROE"
mv "$SAYT" "$STAROE"
mv "$NOVOE" "$SAYT"
echo "файлы: $ISTOCHNIK -> $SAYT (прежняя версия в $STAROE)"

# Ссылка на публичный корень: по ней nginx и находит сайт в подкаталоге
mkdir -p "$KOREN"
chmod 755 "$KOREN"
ln -sfn "$SAYT/public" "$KOREN/glavpryg"

# 3. База и кэши — порядок из инструкции разработчика. config:cache и
#    route:cache намеренно не трогаем: в инструкции их нет, а маршруты
#    Orchid кэширование переживают не всегда.
cd "$SAYT"
kak_vladelec "$PHP" artisan migrate --force
kak_vladelec "$PHP" artisan optimize:clear
kak_vladelec "$PHP" artisan view:cache
[ -L "$SAYT/public/storage" ] || kak_vladelec "$PHP" artisan storage:link

# 4. Правила nginx и пул PHP-FPM из репозитория
install -o root -g root -m 0644 "$ETOT_KATALOG/nginx-glavpryg.conf" "$SNIPPET"
install -o root -g root -m 0644 "$ETOT_KATALOG/php-fpm-glavpryg.conf" "$PUL"
echo "правила nginx: $SNIPPET; пул PHP-FPM: $PUL"

if ! grep -q 'snippets/glavpryg.conf' "$KONFIG_DOMENA"; then
    echo >&2
    echo "ОСТАЛСЯ ОДИН ШАГ: в $KONFIG_DOMENA нет строки подключения сниппета." >&2
    echo "    sudo cp $(dirname "$PROEKT")/webui/deploy/nginx-webui.conf $KONFIG_DOMENA" >&2
    echo "    sudo nginx -t && sudo systemctl reload nginx" >&2
    exit 2
fi

nginx -t
systemctl reload php8.4-fpm
systemctl reload nginx

# 5. Снимаем заглушку — сайт снова открыт
kak_vladelec "$PHP" artisan up

echo
echo "готово: https://mokeevasky.ru/glavpryg/"
echo "проверить: bash $PROEKT/tests/check-glavpryg.sh"
echo "откат:"
echo "    sudo mv $SAYT $SAYT.ne-poshlo && sudo mv $STAROE $SAYT"
echo "    zcat $SNIMOK/baza-$METKA.sql.gz | sudo mysql $BAZA"
echo "    sudo systemctl reload php8.4-fpm"
