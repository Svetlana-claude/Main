#!/bin/bash
# Сравнивает свежий снимок с утверждённым эталоном по критичным разделам.
# Работает без ИИ: появление новой учётки, порта, ключа или SUID-бинарника
# ловится текстовым сравнением, и обмануть его содержимым логов нельзя.
set -uo pipefail
export LC_ALL=C

BASE=${BASE:-/opt/secaudit}
[ -f "$BASE/config.sh" ] && . "$BASE/config.sh"

CUR="$1"; REF="$2"
CRITICAL="LISTEN USERS SUDO SSHKEYS SUID CRON SYSTEMD SSHCONF LOGIN_SRC"

section() { awk -v s="##$2" '$0==s{f=1;next} /^##/{f=0} f' "$1" | grep -v '^\s*$'; }

found=0
for s in $CRITICAL; do
  added=$(comm -13 <(section "$REF" "$s" | sort -u) <(section "$CUR" "$s" | sort -u))
  removed=$(comm -23 <(section "$REF" "$s" | sort -u) <(section "$CUR" "$s" | sort -u))
  if [ -n "$added" ] || [ -n "$removed" ]; then
    found=1
    echo "### Расхождение с эталоном: $s"
    [ -n "$added" ]   && echo "$added"   | sed 's/^/  ПОЯВИЛОСЬ: /'
    [ -n "$removed" ] && echo "$removed" | sed 's/^/  ПРОПАЛО:  /'
    echo
  fi
done

# Разделы, где тревожен сам факт непустого содержимого.
for s in MINER_IOC WORLDWRITABLE; do
  body=$(section "$CUR" "$s")
  if [ -n "$body" ]; then
    found=1
    echo "### Сработал индикатор: $s"
    echo "$body" | sed 's/^/  /'
    echo
  fi
done

# Пороговые проверки.
grep -q 'ТРЕБУЕТСЯ_ПЕРЕЗАГРУЗКА=да' "$CUR" && { found=1; echo "### Сервер ждёт перезагрузки после обновлений"; echo; }
grep -q 'ДОЛГАЯ_НАГРУЗКА' "$CUR" && { found=1; echo "### Процесс с длительной высокой загрузкой CPU"; grep 'ДОЛГАЯ_НАГРУЗКА' "$CUR" | sed 's/^/  /'; echo; }
sec_cnt=$(grep -oP 'pending_security=\K\d+' "$CUR" | head -1)
[ "${sec_cnt:-0}" -gt 0 ] && { found=1; echo "### Не установлено security-обновлений: $sec_cnt"; echo; }
v4p=$(grep -oP 'v4_policy=-P INPUT \K\w+' "$CUR" | head -1)
v6p=$(grep -oP 'v6_policy=-P INPUT \K\w+' "$CUR" | head -1)
[ "${v4p:-}" != "DROP" ] && { found=1; echo "### Политика IPv4-файрвола не DROP: ${v4p:-неизвестна}"; echo; }
[ "${v6p:-}" != "DROP" ] && { found=1; echo "### Политика IPv6-файрвола не DROP: ${v6p:-неизвестна}"; echo; }
grep -q 'fail2ban=active' "$CUR" || { found=1; echo "### fail2ban не работает"; echo; }

# Инварианты: то, что должно быть верно всегда. Проверяются отдельно от diff,
# иначе застарелая проблема прячется в эталоне и перестаёт быть заметной.
inv() { # описание, ожидаемое, фактическое
  if [ "$2" != "$3" ]; then found=1; echo "### Нарушен инвариант: $1"; echo "  ожидалось: $2, фактически: ${3:-не определено}"; echo; fi
}
inv "вход root по SSH запрещён" "permitrootlogin no"       "$(grep -m1 '^permitrootlogin' "$CUR")"
inv "пустые пароли запрещены"   "permitemptypasswords no"  "$(grep -m1 '^permitemptypasswords' "$CUR")"
inv "автообновления включены"   "APT::Periodic::Unattended-Upgrade\"1\"" "$(grep -oP 'auto_upgrades=\K.*' "$CUR" | head -1)"

if [ "${SSH_AUTH_MODE:-key}" = "password" ]; then
  # Парольный режим: инвариант «паролей нет» заменяется компенсирующими.
  # Удалять проверку, а не заменять, нельзя — это тихая эрозия: через полгода
  # никто не вспомнит, что её не стало.
  [ "$(grep -oP '^maxauthtries \K\d+' "$CUR" | head -1)" -gt 3 ] 2>/dev/null && \
    { found=1; echo "### MaxAuthTries больше 3 — при парольном входе это подарок подбору"; echo; }
  # Секция читается в переменную, а не подаётся в `grep -q` конвейером: `grep -q`
  # выходит по первому совпадению, писатель получает SIGPIPE, и `pipefail`
  # делает кодом конвейера 141 — проверка сообщила бы о находке там, где всё
  # в порядке. На этом же образце двое суток терялись выгрузки базы.
  passwd_body=$(section "$CUR" PASSWD)
  case "$passwd_body" in
    *allowusers=allow*) ;;
    *) found=1; echo "### Не задан AllowUsers/AllowGroups — подбирать можно любое имя"; echo ;;
  esac
  cnt=$(grep -oP 'failed_password_24h=\K\d+' "$CUR" | head -1)
  [ "${cnt:-0}" -gt "${BRUTE_THRESHOLD:-2000}" ] && \
    { found=1; echo "### Всплеск подбора пароля за сутки: $cnt (порог ${BRUTE_THRESHOLD:-2000})"; echo; }
  weak=$(section "$CUR" PASSWD | grep -E 'hash=\$(1|5)\$')
  [ -n "$weak" ] && { found=1; echo "### Пароль хранится слабым хэшем (MD5/SHA-256):"; echo "$weak" | sed 's/^/  /'; echo; }
else
  inv "пароли для SSH отключены" "passwordauthentication no" "$(grep -m1 '^passwordauthentication' "$CUR")"
fi

# Учётки с sudo без пароля — компрометация любой из них даёт root мгновенно.
nopw=$(section "$CUR" SUDO | grep -c 'NOPASSWD:ALL')
if [ "${nopw:-0}" -gt 0 ]; then
  found=1
  echo "### Учётных записей с sudo без пароля: $nopw"
  section "$CUR" SUDO | grep 'NOPASSWD:ALL' | sed 's/^/  /'
  echo
fi

echo "### Справочно: аккаунты с интерактивной оболочкой"
section "$CUR" USERS | grep 'shell=/bin/' | sed 's/^/  /'
echo

# Сверка слушающих сокетов с правилами файрвола. Ловит две ошибки:
# сервис смотрит наружу, но файрвол его режет (тихий обрыв клиентов), и
# наоборот — порт открыт правилом, а слушать на нём уже некому.
#
# ⚠️ Сокет наружу пишется тремя способами: 0.0.0.0, * и [::]. Фильтр по одному
# только 0.0.0.0 пропускает остальные МОЛЧА — на этой машине так выглядит порт
# 22 (`tcp *:22`). Отсюда образец ADDR_OUT, он же используется для UDP.
ADDR_OUT='(0\.0\.0\.0|\*|\[::\])'

expand() { # диапазоны вида 7000:7012 разворачиваем в отдельные порты
  while read -r r; do
    case "$r" in
      *:*) seq "${r%%:*}" "${r##*:}" ;;
      ?*)  echo "$r" ;;
    esac
  done
}

# ⚠️ Списки сортируются `sort -u`, а не `sort -un`. Для comm порядок обязан быть
# лексикографическим: при числовой сортировке он получает 22,80,443,51820,
# считает вход неупорядоченным и молча врёт результатом. Проверено — именно так
# первый прогон объявил закрытыми все порты подряд.

# Разрешённые правилами порты: отдельно по семейству и по протоколу.
fw_ports() { # $1 — v4|v6, $2 — tcp|udp
  {
    section "$CUR" FIREWALL | grep "^$1 " | grep -- "-p $2" | grep -oP -- '--dports \K[0-9,:]+' | tr ',' '\n' | expand
    section "$CUR" FIREWALL | grep "^$1 " | grep -- "-p $2" | grep -oP -- '--dport \K[0-9]+'
  } | sort -u
}

# Слушающие наружу порты по протоколу.
listen_ports() { # $1 — tcp|udp
  section "$CUR" LISTEN | grep -oP "^$1 $ADDR_OUT:\K[0-9]+" | sort -u
}

# Интерфейсы, принимаемые без разбора портов: порт за ними закрытым не считается.
iface_open=$(section "$CUR" FIREWALL | grep -oP -- '-i \K\S+' | sort -u | tr '\n' ' ')

# ⚠️ Сверять сокеты с правилами имеет смысл только при политике DROP. Пока
# политика ACCEPT (или файрвола нет вовсе), незакрытым правилом порт закрытым
# НЕ является — и проверка объявляла бы отрезанными все службы подряд. Отчёт,
# который каждую ночь кричит неправду, перестают читать целиком.
if [ "${v4p:-}" = "DROP" ] || [ "${v6p:-}" = "DROP" ]; then
  for proto in tcp udp; do
    for fam in v4 v6; do
      blocked=$(comm -23 <(listen_ports "$proto") <(fw_ports "$fam" "$proto"))
      [ -n "$blocked" ] || continue
      found=1
      echo "### Слушают наружу по $proto, но закрыты ${fam}-файрволом (проверь, не оборваны ли клиенты)"
      for p in $blocked; do
        echo "  порт $p: $(section "$CUR" LISTEN | grep -P "^$proto $ADDR_OUT:$p " | head -1)"
      done
      [ -n "$iface_open" ] && echo "  (без разбора портов приняты интерфейсы: $iface_open)"
      echo
    done
  done

  stale=$(comm -13 <(listen_ports tcp) <(fw_ports v4 tcp))
  if [ -n "$stale" ]; then
    echo "### Справочно: файрвол пропускает порты, на которых никто не слушает"
    echo "  $(echo $stale | tr '\n' ' ')"
    echo
  fi
else
  echo "### Справочно: сверка сокетов с правилами не проводилась — политика INPUT не DROP"
  echo
fi

[ $found -eq 0 ] && echo "Расхождений с эталоном нет."
exit 0
