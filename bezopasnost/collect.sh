#!/bin/bash
# Слой 1: сбор фактов о состоянии сервера. Без ИИ, без принятия решений.
# Единственный шаг, которому нужен root. Только читает, ничего не меняет.
# Вывод — плоский текст с секциями ##SECTION.
set -uo pipefail
export LC_ALL=C

sec() { echo; echo "##$1"; }

echo "# Снимок состояния $(date -Is) на $(hostname)"

sec HOST
uptime
echo "kernel=$(uname -r)"
df -h / /var 2>/dev/null | tail -n +2

sec LISTEN
# Порты, открытые наружу, — главный индикатор появления нового сервиса.
# PID и fd вырезаем: после каждого перезапуска службы они меняются и засоряют
# сравнение с эталоном десятками ложных расхождений. Личность сокета задают
# адрес, порт и имя процесса — их и сверяем.
ss -tulpnH 2>/dev/null | awk '{print $1, $5, $7}' | \
  sed -E 's/,(fd|pid)=[0-9]+//g; s/users:\(//; s/\)$//' | sort

sec FIREWALL
echo "v4_policy=$(iptables -S INPUT 2>/dev/null | head -1)"
echo "v6_policy=$(ip6tables -S INPUT 2>/dev/null | head -1)"
# Оба набора: без v6-правил сверка портов проверяла бы половину картины,
# а сокеты с привязкой "*" дуалстековые.
iptables  -S INPUT 2>/dev/null | grep -v '^-P' | grep -v 'f2b' | sed 's/^/v4 /'
ip6tables -S INPUT 2>/dev/null | grep -v '^-P' | grep -v 'f2b' | sed 's/^/v6 /'
echo "fail2ban=$(systemctl is-active fail2ban 2>/dev/null)"
fail2ban-client status sshd 2>/dev/null | grep -E 'Currently banned|Total banned' | sed 's/[[:space:]|`-]*//'

sec USERS
# Любая новая учётка с шеллом — повод для тревоги.
awk -F: '$3>=1000 && $3<65534 {print $1" uid="$3" shell="$7}' /etc/passwd | sort
echo "-- с пустым паролем:"
awk -F: '$2=="" {print $1}' /etc/shadow 2>/dev/null
echo "-- uid=0 кроме root:"
awk -F: '$3==0 && $1!="root" {print $1}' /etc/passwd

sec PASSWD
# Алгоритм хэша и возраст пароля. В парольном режиме это и есть прочность
# входа: $1$ — MD5, $5$ — SHA-256, $6$ — SHA-512, $y$ — yescrypt.
awk -F: '$2 ~ /^\$/ {split($2,a,"$"); print $1" hash=$"a[2]"$"}' /etc/shadow 2>/dev/null | sort
for u in root $(awk -F: '$3>=1000 && $3<65534 {print $1}' /etc/passwd); do
  echo "$u last_change=$(chage -l "$u" 2>/dev/null | awk -F': ' '/Last password change/{print $2}')"
done
echo "allowusers=$(sshd -T 2>/dev/null | grep -E '^(allowusers|allowgroups)' | tr '\n' ' ')"

sec SUDO
# Типовой след взлома — свой файл в sudoers.d с NOPASSWD:ALL.
for f in /etc/sudoers.d/*; do
  [ -f "$f" ] || continue
  case "$f" in *README) continue;; esac
  echo "$(basename "$f"): $(grep -hv '^#' "$f" | grep -v '^\s*$' | tr '\n' ';')"
done

sec SSHKEYS
# Отпечатки, а не сами ключи: подменённый ключ видно по смене отпечатка.
for h in /root /home/*; do
  u=$(basename "$h")
  f="$h/.ssh/authorized_keys"
  [ -f "$f" ] || continue
  while read -r line; do
    [ -n "$line" ] || continue
    fp=$(echo "$line" | ssh-keygen -lf - 2>/dev/null | awk '{print $2" "$4}')
    echo "$u: ${fp:-НЕРАЗОБРАННАЯ_СТРОКА}"
  done < "$f"
done

sec SSHCONF
sshd -T 2>/dev/null | grep -E '^(port|permitrootlogin|passwordauthentication|pubkeyauthentication|permitemptypasswords|maxauthtries)'

sec CRON
for u in $(cut -d: -f1 /etc/passwd); do
  out=$(crontab -u "$u" -l 2>/dev/null | grep -v '^#' | grep -v '^\s*$')
  [ -n "$out" ] && echo "$u: $out"
done
echo "-- /etc/cron.d:"
ls /etc/cron.d/ 2>/dev/null | sort
echo "-- /etc/cron.*/:"
ls /etc/cron.hourly /etc/cron.daily /etc/cron.weekly /etc/cron.monthly 2>/dev/null | sort -u

sec SYSTEMD
systemctl list-unit-files --state=enabled --no-pager --no-legend 2>/dev/null | awk '{print $1}' | sort
echo "-- юниты вне пакетов (частое место закрепления):"
find /etc/systemd/system -maxdepth 1 \( -name '*.service' -o -name '*.timer' \) 2>/dev/null | sort

sec SUID
# Новый SUID-бинарник = почти наверняка повышение привилегий.
find / -xdev -perm -4000 -type f 2>/dev/null | sort

sec PROCS
# Майнер выдаёт себя длительной высокой загрузкой CPU.
ps -eo user,pcpu,pmem,etimes,comm --sort=-pcpu --no-headers 2>/dev/null | head -15 | \
  awk '$2>20 && $4>600 {print "ДОЛГАЯ_НАГРУЗКА: "$0; next} {print $0}'

sec MINER_IOC
# Признаки майнеров: имена процессов, порты стратум-пулов, скрытые каталоги.
ps -eo comm= 2>/dev/null | grep -iE 'xmrig|kdevtmpfsi|kinsing|minerd|cpuminer|cryptonight|sysrv|dbused|xmr-stak' | sort -u
ss -tnH state established 2>/dev/null | \
  awk '{split($4,a,":"); p=a[length(a)]; if (p==3333||p==4444||p==5555||p==7777||p==14444||p==45700||p==9999) print "ПОДОЗРИТЕЛЬНЫЙ_ПОРТ: "$0}'
find /tmp /var/tmp /dev/shm -maxdepth 2 -type f -perm -u+x 2>/dev/null | head -20
find /tmp /var/tmp /dev/shm -maxdepth 2 -name '.*' -type d 2>/dev/null | \
  grep -vE '/\.(X11-unix|XIM-unix|ICE-unix|font-unix|Test-unix)$' | head -10

sec AUTHFAIL
# Объём брутфорса: резкий рост может означать смену тактики атакующего.
cnt=$(journalctl -u ssh --since "24 hours ago" --no-pager 2>/dev/null | grep -c 'Failed password')
echo "failed_password_24h=$cnt"
echo "-- успешные входы за сутки:"
journalctl -u ssh --since "24 hours ago" --no-pager 2>/dev/null | grep 'Accepted' | \
  grep -oE 'for [a-z_][a-z0-9_-]* from [0-9a-f.:]+' | sort | uniq -c | sort -rn | head -10

sec LOGIN_SRC
# Адреса, с которых вход УДАЛСЯ. Сверяется с эталоном, поэтому вход с нового
# адреса становится строкой ПОЯВИЛОСЬ. В парольном режиме это главный сигнал:
# подбор виден не по неудачам (их всегда тысячи), а по первой удаче.
#
# Пишем сеть /24, а не адрес: домашний провайдер меняет последний октет, и
# сверка по адресу давала бы «новый адрес» на каждый свой вход. Выход за
# пределы сети при этом виден по-прежнему.
journalctl -u ssh --since "24 hours ago" --no-pager 2>/dev/null | grep 'Accepted' | \
  grep -oP 'from \K[0-9a-f.:]+' | \
  awk -F. 'NF==4 {print $1"."$2"."$3".0/24"; next} {print}' | sort -u

sec UPDATES
apt-get -s upgrade 2>/dev/null | grep -c '^Inst' | sed 's/^/pending_total=/'
apt-get -s upgrade 2>/dev/null | grep '^Inst' | grep -ci security | sed 's/^/pending_security=/'
echo "auto_upgrades=$(grep -h 'Unattended-Upgrade' /etc/apt/apt.conf.d/20auto-upgrades 2>/dev/null | tr -d ' ;')"
[ -f /var/run/reboot-required ] && echo "ТРЕБУЕТСЯ_ПЕРЕЗАГРУЗКА=да" || echo "требуется_перезагрузка=нет"

sec DOCKER
docker ps --format '{{.Names}} image={{.Image}} status={{.Status}}' 2>/dev/null | sort
docker ps -q 2>/dev/null | while read -r c; do
  docker inspect -f '{{.Name}} netmode={{.HostConfig.NetworkMode}} privileged={{.HostConfig.Privileged}}' "$c" 2>/dev/null
done | sort

sec ETC_CHANGED
# Изменения в /etc за сутки — если вы их не делали, это чужие руки.
find /etc -xdev -type f -mtime -1 2>/dev/null | grep -vE '/etc/(mtab|adjtime|resolv.conf|ld.so.cache)' | sort | head -30

sec WORLDWRITABLE
find /etc /usr/local/bin /usr/local/sbin -xdev -type f -perm -0002 2>/dev/null | head
