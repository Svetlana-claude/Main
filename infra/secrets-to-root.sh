#!/bin/bash
# Перенос ключей приложения в файл с владельцем root.
#
# Что делает: кладёт значения из ~/.config/webui/webui.env в /etc/webui/webui.env
# (root:root, 600), ставит врезку в юнит с EnvironmentFile, перезапускает службу
# и убеждается, что она поднялась. Только после успешной проверки убирает копию
# пользователя — в /etc/webui/webui.env.bak, тоже под root. Ничего не удаляет.
#
# Зачем: пока файл с ключами доступен пользователю mokeeva, тема проекта с
# поднятым allow_bash читает его командой (`cat`), и запрет по пути не спасает —
# он действует на инструменты работы с файлами, но не на содержимое команд.
# Файл под root такой возможности не оставляет.
#
# Запускать с паролем, беспарольный sudo правку юнитов не покрывает:
#     sudo bash infra/secrets-to-root.sh
#
# Откат — в конце файла.
set -euo pipefail

SRC="${SRC:-/home/mokeeva/.config/webui/webui.env}"
DEST=/etc/webui/webui.env
DROPIN_DIR=/etc/systemd/system/webui.service.d
DROPIN="$DROPIN_DIR/secrets.conf"
SAMPLE=/home/mokeeva/main/webui/deploy/webui.service.d/secrets.conf
HEALTH=http://127.0.0.1:8000/healthz

if [ "$(id -u)" -ne 0 ]; then
    echo "Нужен root: sudo bash infra/secrets-to-root.sh" >&2
    exit 1
fi

if [ ! -f "$SRC" ] && [ ! -f "$DEST" ]; then
    echo "Не найден ни $SRC, ни $DEST — переносить нечего." >&2
    exit 1
fi

# 1. Файл под root. Копия, а не перенос: пользовательская убирается в самом
#    конце, когда служба уже доказала, что поднимается с новым источником.
if [ -f "$SRC" ]; then
    install -d -m 755 -o root -g root /etc/webui
    install -m 600 -o root -g root "$SRC" "$DEST"
    echo "→ $DEST создан (root:root, 600)"
else
    echo "→ $DEST уже на месте, файл пользователя отсутствует"
fi

# systemd читает EnvironmentFile как KEY=value. Строки с кавычками, пробелами
# вокруг «=» или продолжением он поймёт иначе, чем dotenv, — предупреждаем сразу.
if grep -qE '^[^#]*=[[:space:]]|[[:space:]]=|["'"'"'\\]' "$DEST"; then
    echo "ВНИМАНИЕ: в значениях есть кавычки, пробелы или обратный слеш." >&2
    echo "systemd разберёт такие строки не так, как dotenv. Проверьте вручную." >&2
fi

# 2. Врезка в юнит
install -d -m 755 -o root -g root "$DROPIN_DIR"
install -m 644 -o root -g root "$SAMPLE" "$DROPIN"
echo "→ врезка $DROPIN поставлена"
systemctl daemon-reload

# 3. Перезапуск и проверка делом: не «юнит active», а ответ приложения
systemctl restart webui
CODE=""
for _ in $(seq 1 30); do
    CODE="$(curl -s -o /dev/null -w '%{http_code}' "$HEALTH" || true)"
    [ "$CODE" = "200" ] && break
    sleep 1
done

if [ "$CODE" != "200" ]; then
    echo "ОТКАТ: приложение не ответило 200 на $HEALTH (получено «$CODE»)." >&2
    rm -f "$DROPIN"
    systemctl daemon-reload
    systemctl restart webui
    echo "Врезка снята, служба возвращена к прежнему состоянию." >&2
    echo "Файл $DEST оставлен на месте, копия пользователя не тронута." >&2
    exit 1
fi
echo "→ приложение ответило 200, ключи берутся из $DEST"

# 4. Теперь и только теперь убираем копию, доступную пользователю
if [ -f "$SRC" ]; then
    mv "$SRC" "$DEST.bak"
    chown root:root "$DEST.bak"
    chmod 600 "$DEST.bak"
    echo "→ копия пользователя убрана в $DEST.bak (root:root, 600)"
fi

echo
echo "Готово. Проверить, что пользователю ключи больше не видны:"
echo "    sudo -u mokeeva cat $DEST        # должно быть «Permission denied»"
echo
echo "Откат:"
echo "    sudo cp $DEST.bak /home/mokeeva/.config/webui/webui.env"
echo "    sudo chown mokeeva:mokeeva /home/mokeeva/.config/webui/webui.env"
echo "    sudo rm $DROPIN && sudo systemctl daemon-reload && sudo systemctl restart webui"
