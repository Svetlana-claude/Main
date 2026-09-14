#!/bin/bash
# Откат файрвола к правилам, сохранённым перед последним firewall-apply.
# Запускается таймером через 5 минут после применения, если применение не
# подтвердили, и руками — если нужно вернуть как было.
#
# ⚠️ Пустой снимок «до» — это НЕ «ничего не делать». Проверено 12.09.2026:
# до первого применения IPv6-правил не было вовсе, `ip6tables-save` выдал
# пустой файл, `ip6tables-restore` из пустого файла ничего не сделал — и
# после «отката» IPv4 вернулся к ACCEPT, а IPv6 остался в DROP с новыми
# правилами. Пустой снимок означает «правил не было»: политика ACCEPT и
# пустая цепочка INPUT. Это и восстанавливается.
set -uo pipefail
export LC_ALL=C
BASE=${BASE:-/opt/secaudit}
BACKUP="$BASE/backup"

restore() { # $1 — v4|v6
  local fam="$1" restore_cmd tables file
  case "$fam" in
    v4) restore_cmd=iptables-restore;  tables=iptables  ;;
    v6) restore_cmd=ip6tables-restore; tables=ip6tables ;;
  esac
  file="$BACKUP/rules.$fam.last"

  if [ -s "$file" ]; then
    if "$restore_cmd" < "$file"; then
      echo "$fam: восстановлено из $(readlink "$file" 2>/dev/null || echo "$file")"
      return 0
    fi
    echo "$fam: ОШИБКА восстановления из снимка — открываю INPUT целиком" >&2
  else
    echo "$fam: снимка «до» нет или он пуст — правил не было, открываю INPUT"
  fi

  # Возврат к состоянию «правил нет». Порядок важен: сперва политика ACCEPT,
  # потом очистка. Наоборот — между двумя командами цепочка пуста при DROP,
  # и в этот миг режется всё, включая сессию, из которой откатываемся.
  "$tables" -P INPUT ACCEPT
  "$tables" -F INPUT
}

rc=0
restore v4 || rc=1
restore v6 || rc=1
logger -t webui-sec "правила файрвола откачены (код $rc)" 2>/dev/null || true
exit "$rc"
