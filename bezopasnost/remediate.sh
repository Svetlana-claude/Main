#!/bin/bash
# Слой 3: устранение угроз. Только белый список заведомо безопасных и обратимых
# действий, зашитый в код. Решения принимает этот скрипт, не ИИ — поэтому текст
# в логах не может спровоцировать выполнение чего-либо.
#
# ⚠️ Отличие от исходной инструкции: снимок НЕ принимается доводом, скрипт
# делает свежий сам. В инструкции путь к снимку приходит снаружи, а снимок
# лежит в каталоге, доступном на запись обычному пользователю, — то есть на
# вход root-скрипту попадают данные, которые можно подделать, и по ним он
# переносит файлы и гасит процессы. Лишний вызов collect.sh стоит секунд.
set -uo pipefail
export LC_ALL=C
BASE=${BASE:-/opt/secaudit}
. "$BASE/config.sh"

CUR=$(mktemp)
trap 'rm -f "$CUR"' EXIT
"$BASE/collect.sh" > "$CUR" 2>/dev/null

QUAR="$BASE/quarantine"
mkdir -p "$QUAR"
did=0
act() { did=1; echo "- $*"; }

# 1. Установка security-обновлений. Штатный механизм дистрибутива, откатываемо.
#
# ⚠️ Успех проверяется ДЕЛОМ — тем, что очередь сократилась, а не кодом возврата.
# Проверено 12.09.2026: `unattended-upgrade` отработал с кодом 0 и не поставил
# ни одного пакета из 193. Он берёт только источник `-security`, а на этой
# машине кандидаты всех этих пакетов лежат в `-updates` (машина не обновлялась
# с установки, и версия из `-updates` новее). В журнале — «kept back», в отчёте
# было бы «Установлены security-обновления (ожидало: 193)». Отчёт, который
# сообщает об устранении несделанного, опаснее отсутствия отчёта.
sec_cnt=$(grep -oP 'pending_security=\K\d+' "$CUR" | head -1)
if [ "${sec_cnt:-0}" -gt 0 ]; then
  unattended-upgrade -v >/tmp/uu.log 2>&1
  rc=$?
  after=$(apt-get -s upgrade 2>/dev/null | grep '^Inst' | grep -ci security)
  installed=$(( sec_cnt - after ))
  if [ "$rc" -ne 0 ]; then
    act "ОШИБКА: установка security-обновлений не удалась (код $rc), см. /tmp/uu.log"
  elif [ "$installed" -gt 0 ]; then
    act "Установлено security-обновлений: $installed из $sec_cnt, лог: /tmp/uu.log"
  else
    act "НЕ УСТРАНЕНО: ожидало $sec_cnt security-обновлений, установлено 0." \
        "Так бывает, когда кандидат лежит в -updates, а не в -security:" \
        "unattended-upgrade его не берёт. Нужен обычный apt-get upgrade руками."
  fi
fi

# 2. Карантин файлов с сигнатурами майнеров. Не удаляем — переносим, чтобы
#    осталось вещдоком и чтобы ложное срабатывание можно было отменить.
while read -r f; do
  [ -f "$f" ] || continue
  base=$(basename "$f")
  case "$base" in
    xmrig*|kdevtmpfsi*|kinsing*|minerd*|cpuminer*|sysrv*|dbused*)
      mv "$f" "$QUAR/$(date +%F_%H%M%S)_$base" 2>/dev/null && \
        act "В карантин помещён файл $f (сигнатура майнера)"
      ;;
  esac
done < <(awk '$0=="##MINER_IOC"{f=1;next} /^##/{f=0} f' "$CUR" | grep -E '^/(tmp|var/tmp|dev/shm)/')

# 3. Остановка процессов с известными именами майнеров.
#    pgrep -x, а не -f: поиск по полной строке находит сам себя.
for p in xmrig kdevtmpfsi kinsing minerd cpuminer sysrv dbused xmr-stak; do
  if pgrep -x "$p" >/dev/null 2>&1; then
    pids=$(pgrep -x "$p" | tr '\n' ' ')
    pkill -9 -x "$p" && act "Остановлен процесс $p (pid: $pids)"
  fi
done

# 4. Восстановление файрвола, если политика слетела.
#    Только если правила вообще когда-либо применялись: иначе на машине, где
#    файрвол ещё не настраивался, ночной аудит применил бы его сам — без
#    проверки доступа из второго окна, то есть ровно тем способом, которым
#    теряют сервер.
v4p=$(iptables -S INPUT 2>/dev/null | head -1)
if [ "$v4p" != "-P INPUT DROP" ] && [ -f "$BASE/backup/firewall-applied" ]; then
  "$BASE/apply-firewall.sh" >/dev/null 2>&1 && \
    act "Политика файрвола была не DROP — правила применены заново"
fi

# 5. Перезапуск fail2ban, если он лёг.
if systemctl list-unit-files fail2ban.service >/dev/null 2>&1 && \
   ! systemctl is-active --quiet fail2ban; then
  systemctl restart fail2ban && act "fail2ban не работал — перезапущен"
fi

[ $did -eq 0 ] && echo "Автоматических действий не потребовалось."
exit 0
