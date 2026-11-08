#!/bin/bash
# Перезапуск сайта v2, когда допишутся ответы Claude, запущенные из самого сайта.
#
# Зачем: Claude из вкладки «Проекты» работает внутри службы сайта, и перезапуск
# оборвал бы его ответ вместе с работой. Поэтому Claude не перезапускает сайт
# сам, а ставит этот скрипт в crontab раз в минуту (cron живёт вне службы):
#
#   * * * * * /bin/bash /home/mokeeva/main/webui2/tools/perezapusk-posle-otveta.sh  # perezapusk-webui2
#
# Каждую минуту скрипт смотрит, остались ли в службе процессы claude. Нет —
# перезапускает сайт, ждёт, проверяет, что он поднялся и страница входа
# отвечает, пишет итог в журнал и убирает свою строку из crontab.
set -u
LOG=/home/mokeeva/backups/perezapusk-webui2.log
MARK='# perezapusk-webui2'
CG=/sys/fs/cgroup/system.slice/webui2.service/cgroup.procs
now() { TZ=Europe/Moscow date '+%d.%m.%Y %H:%M по Москве'; }
unschedule() { crontab -l 2>/dev/null | grep -vF "$MARK" | crontab -; }

# Идёт ответ — ждём следующей минуты
for pid in $(cat "$CG" 2>/dev/null); do
  [ "$(cat /proc/$pid/comm 2>/dev/null)" = claude ] && exit 0
done

before=$(systemctl show webui2.service -p ExecMainPID --value)
if ! sudo -n /usr/local/sbin/webui2-power restart-site; then
  echo "$(now) перезапуск не удался: нет права на команду" >> "$LOG"; unschedule; exit 1
fi
for _ in $(seq 1 60); do
  sleep 2
  pid=$(systemctl show webui2.service -p ExecMainPID --value)
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8002/login)
  if [ "$pid" != "$before" ] && [ "$pid" != 0 ] && [ "$code" = 200 ]; then
    echo "$(now) сайт перезапущен и отвечает" >> "$LOG"; unschedule; exit 0
  fi
done
echo "$(now) ОШИБКА: после перезапуска сайт не отвечает (код $code)" >> "$LOG"
unschedule
exit 1
