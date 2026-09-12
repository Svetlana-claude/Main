#!/bin/bash
# Управление ночным аудитом безопасности — беспарольный шаг агента и панели.
#
#     sudo webui-sec collect              снимок состояния в stdout
#     sudo webui-sec remediate            устранение по белому списку
#     sudo webui-sec firewall-apply       применить правила файрвола
#     sudo webui-sec firewall-save        закрепить правила (после проверки!)
#     sudo webui-sec baseline-approve     принять снимок дня эталоном
#     sudo webui-sec quarantine-list      перечень изъятого
#     sudo webui-sec quarantine-restore ХЭШ   вернуть файл из карантина
#     sudo webui-sec quarantine-delete ХЭШ    удалить файл из карантина
#     sudo webui-sec status               состояние аудита одной сводкой
#
# Ставится в /usr/local/sbin/webui-sec владельцем root и БЕЗ права записи
# пользователю — иначе разрешение на обёртку означало бы разрешение запускать
# от root любой код: достаточно переписать файл. Отсюда следствие: правка
# этого файла в репозитории сама по себе ничего не меняет, новую версию ставите
# вы командой `sudo bash infra/install-root-helpers.sh`.
#
# ПОЧЕМУ В ДОВОДАХ НЕТ НИ ОДНОГО ПУТИ. Аудит по своей природе читает то, что
# контролирует атакующий: имена файлов в /tmp, строки логов. Прими обёртка путь
# доводом — и root-скрипт получал бы на вход данные, которые можно подделать.
# Поэтому снимок не передаётся, а снимается заново; карантин адресуется sha256
# содержимого, а не именем файла; эталон принимается только из снимка текущего
# дня, лежащего по жёстко заданному пути.
#
# ЧТО ЭТА ОБЁРТКА ВСЁ-ТАКИ ДАЁТ. `firewall-apply` правит iptables, `remediate`
# ставит обновления и гасит процессы — это по существу root-шаги, сужённые до
# одного дела каждый. Это осознанная плата за то, чтобы аудит работал ночью
# сам и чтобы панель могла показать его результат.

set -euo pipefail

LIB=/opt/secaudit                      # код: root:root, пользователю не писать
STATE=/var/lib/secaudit                # состояние: снимки и отчёты пользователя
QUAR=$LIB/quarantine
REF=$LIB/baseline/reference.txt

die() { echo "ОТКАЗ: $*" >&2; exit 1; }

usage() {
    # Строки подсказки берутся по образцу, а не по номерам: добавь команду —
    # и нумерация уехала бы, а подсказка молча потеряла бы последнюю строку.
    sed -n 's/^#     \(sudo webui-sec.*\)/    \1/p' "$0"
}

if [ "$(id -u)" -ne 0 ]; then
    echo "нужен root: sudo webui-sec <команда>" >&2
    exit 1
fi

# Запускаемый файл обязан принадлежать root и быть закрыт на запись прочим.
check_lib() {
    local script="$LIB/$1"
    [ -f "$script" ] || die "не установлен $script — выполните: sudo bash infra/install-root-helpers.sh"
    local st perm
    st="$(stat -c '%U %a' "$script")"
    [[ "$st" == "root "* ]] || die "$script принадлежит не root — запускать его от root нельзя"
    perm="${st##* }"
    if (( 8#$perm & 0022 )); then
        die "$script доступен на запись не только root — запускать его от root нельзя"
    fi
    echo "$script"
}

run_lib() {
    local script; script="$(check_lib "$1")"; shift
    # Ради проверок: показать разобранную команду и выйти, ничего не запуская.
    # На безопасность не влияет — исполнения здесь нет, а через sudo сюда не
    # попасть: env_reset вычищает окружение.
    if [ -n "${WEBUI_SEC_CHECK:-}" ]; then
        printf 'ЗАПУСТИЛ БЫ: %s %s\n' "$script" "$*"
        exit 0
    fi
    exec /bin/bash "$script" "$@"
}

# Довод-хэш: ровно 64 знака из [0-9a-f]. Ни пути, ни флага в него не спрятать.
check_hash() {
    [[ "$1" =~ ^[0-9a-f]{64}$ ]] || die "ожидался sha256 (64 знака 0-9a-f), получено «$1»"
}

# Файл карантина по хэшу содержимого. Имя файла в поиске не участвует:
# оно пришло от атакующего и доверия не заслуживает.
quar_by_hash() {
    local want="$1" f h
    for f in "$QUAR"/*; do
        [ -f "$f" ] || continue
        h="$(sha256sum "$f" | cut -d' ' -f1)"
        [ "$h" = "$want" ] && { echo "$f"; return 0; }
    done
    return 1
}

cmd="${1:-}"
[ $# -gt 0 ] && shift

case "$cmd" in
    collect)
        [ $# -eq 0 ] || die "collect доводов не принимает"
        run_lib collect.sh
        ;;
    remediate)
        [ $# -eq 0 ] || die "remediate доводов не принимает"
        run_lib remediate.sh
        ;;
    firewall-apply)
        [ $# -eq 0 ] || die "firewall-apply доводов не принимает"
        # Метка «файрвол применялся руками»: по ней remediate.sh решает, можно
        # ли восстанавливать правила ночью без человека. До первого применения
        # нельзя — ночной default-deny без проверки доступа отрезает сервер.
        install -o root -g root -m 644 -D /dev/null "$LIB/backup/firewall-applied"
        date -Is > "$LIB/backup/firewall-applied"
        run_lib apply-firewall.sh
        ;;
    firewall-save)
        [ $# -eq 0 ] || die "firewall-save доводов не принимает"
        command -v netfilter-persistent >/dev/null 2>&1 \
            || die "netfilter-persistent не установлен — правила закреплять нечем"
        exec netfilter-persistent save
        ;;
    baseline-approve)
        [ $# -eq 0 ] || die "baseline-approve доводов не принимает"
        # Эталоном становится снимок ТЕКУЩЕГО дня по жёстко заданному пути.
        # Произвольный файл сюда не подставить.
        snap="$STATE/snapshots/$(date +%F).txt"
        [ -s "$snap" ] || die "снимка за сегодня нет ($snap) — сперва прогоните аудит"
        install -o root -g root -m 755 -d "$LIB/baseline"
        # Прежний эталон не затирается молча: без него не разобрать, что именно
        # было принято, если приняли лишнее.
        [ -f "$REF" ] && cp -a "$REF" "$LIB/baseline/reference.$(date +%F_%H%M%S).bak"
        install -o root -g root -m 644 "$snap" "$REF"
        echo "Эталон принят из $snap"
        ;;
    quarantine-list)
        [ $# -eq 0 ] || die "quarantine-list доводов не принимает"
        [ -d "$QUAR" ] || exit 0
        # TSV: хэш, размер, время изъятия, имя, тип. Разбирать это панели, а
        # человеческий вид складывать там же — иначе формат зависит от языка.
        for f in "$QUAR"/*; do
            [ -f "$f" ] || continue
            printf '%s\t%s\t%s\t%s\t%s\n' \
                "$(sha256sum "$f" | cut -d' ' -f1)" \
                "$(stat -c '%s' "$f")" \
                "$(stat -c '%Y' "$f")" \
                "$(basename "$f")" \
                "$(file -b "$f" 2>/dev/null | tr '\t' ' ')"
        done
        ;;
    quarantine-restore)
        [ $# -eq 1 ] || die "нужен ровно один довод: webui-sec quarantine-restore ХЭШ"
        check_hash "$1"
        f="$(quar_by_hash "$1")" || die "в карантине нет файла с таким хэшем"
        # Исходный путь не восстанавливаем: имя в карантине — «ДАТА_ВРЕМЯ_имя»,
        # и откуда файл взят, из него не следует. Возвращаем в /tmp, дальше
        # разбирается человек.
        base="$(basename "$f")"
        dst="/tmp/${base#*_*_}"
        [ -e "$dst" ] && die "файл $dst уже существует — уберите его и повторите"
        mv "$f" "$dst"
        chmod 600 "$dst"
        echo "Возвращён: $dst (права 600, бит исполнения снят)"
        ;;
    quarantine-delete)
        [ $# -eq 1 ] || die "нужен ровно один довод: webui-sec quarantine-delete ХЭШ"
        check_hash "$1"
        f="$(quar_by_hash "$1")" || die "в карантине нет файла с таким хэшем"
        rm -f -- "$f"
        echo "Удалён из карантина: $(basename "$f")"
        ;;
    status)
        [ $# -eq 0 ] || die "status доводов не принимает"
        echo "baseline=$([ -f "$REF" ] && date -Is -r "$REF" || echo нет)"
        last=$(ls -1t "$STATE/reports"/rep_*.md 2>/dev/null | head -1)
        echo "last_report=${last:-нет}"
        [ -n "$last" ] && echo "last_report_at=$(date -Is -r "$last")"
        echo "fail2ban=$(systemctl is-active fail2ban 2>/dev/null)"
        echo "v4_policy=$(iptables -S INPUT 2>/dev/null | head -1)"
        echo "v6_policy=$(ip6tables -S INPUT 2>/dev/null | head -1)"
        echo "firewall_applied=$([ -f "$LIB/backup/firewall-applied" ] && cat "$LIB/backup/firewall-applied" || echo нет)"
        echo "quarantine=$(find "$QUAR" -maxdepth 1 -type f 2>/dev/null | wc -l)"
        ;;
    ""|-h|--help|help)
        usage
        exit 0
        ;;
    *)
        echo "ОТКАЗ: неизвестная команда «$cmd»." >&2
        usage >&2
        exit 1
        ;;
esac
