#!/bin/bash
# Управление ночным аудитом безопасности — беспарольный шаг агента и панели.
#
#     sudo webui-sec collect              снимок состояния в stdout
#     sudo webui-sec remediate            устранение по белому списку
#     sudo webui-sec firewall-apply       применить правила файрвола на 5 минут
#     sudo webui-sec firewall-confirm     отменить самооткат после проверки
#     sudo webui-sec firewall-save        закрепить правила (после проверки!)
#     sudo webui-sec baseline-approve     принять снимок дня эталоном
#     sudo webui-sec harden-updates       включить автообновления
#     sudo webui-sec harden-fail2ban      настроить fail2ban из config.sh
#     sudo webui-sec harden-ssh           ужесточить вход по SSH
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
        script="$(check_lib apply-firewall.sh)"
        rollback="$(check_lib firewall-rollback.sh)"
        install -o root -g root -m 700 -d "$LIB/backup"

        # Правила «до» сохраняются ВСЕГДА и до применения: это единственный
        # способ вернуться, если новые отрежут доступ.
        stamp=$(date +%F_%H%M%S)
        iptables-save  > "$LIB/backup/rules.v4.before-$stamp"
        ip6tables-save > "$LIB/backup/rules.v6.before-$stamp"
        ln -sf "rules.v4.before-$stamp" "$LIB/backup/rules.v4.last"
        ln -sf "rules.v6.before-$stamp" "$LIB/backup/rules.v6.last"

        # ⚠️ Самооткат. Ошибка в правилах — это потеря доступа к удалённой
        # машине, и «проверьте из второго окна» помогает только если есть чем
        # вернуть. Поэтому применение временное: через 5 минут правила
        # возвращаются сами, если не подтвердить их командой firewall-confirm.
        #
        # Таймер ставится ДО применения, а не после: упади apply-firewall.sh на
        # середине — с политикой DROP и половиной правил, — и откатывать было бы
        # нечем. Откат вынесен в отдельный скрипт: прежняя строка в одну команду
        # не умела пустой снимок и оставила IPv6 в DROP (12.09.2026).
        rm -f "$LIB/backup/firewall-applied"
        systemctl stop webui-sec-rollback.timer 2>/dev/null || true
        systemctl reset-failed webui-sec-rollback.service 2>/dev/null || true
        systemd-run --quiet --unit=webui-sec-rollback --on-active=300 /bin/bash "$rollback"

        /bin/bash "$script"
        echo
        echo "⚠️ Правила применены ВРЕМЕННО. Через 5 минут они откатятся сами."
        echo "   Проверьте ИЗ ВТОРОГО ОКНА, не закрывая это: вход по SSH, сайт,"
        echo "   подключение VPN с телефона. Если всё живо — подтвердите:"
        echo "       sudo webui-sec firewall-confirm"
        echo "   Ничего не делать тоже безопасно: через 5 минут вернётся как было."
        ;;
    firewall-confirm)
        [ $# -eq 0 ] || die "firewall-confirm доводов не принимает"
        systemctl stop webui-sec-rollback.timer 2>/dev/null || true
        systemctl reset-failed webui-sec-rollback.service 2>/dev/null || true
        # Метка «файрвол применялся руками и проверен»: по ней remediate.sh
        # решает, можно ли восстанавливать правила ночью без человека. До
        # первого подтверждения нельзя — ночной default-deny без проверки
        # доступа отрезает сервер.
        date -Is > "$LIB/backup/firewall-applied"
        chmod 644 "$LIB/backup/firewall-applied"
        echo "Откат отменён. Правила остаются до перезагрузки."
        echo "Чтобы они пережили перезагрузку: sudo webui-sec firewall-save"
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
    harden-updates)
        [ $# -eq 0 ] || die "harden-updates доводов не принимает"
        # Содержимое задано здесь целиком и доводами не управляется. Сама по
        # себе установленная служба unattended-upgrades ничего не значит:
        # проверено 12.09.2026 — при нулях в этом файле она не ставила годами.
        install -o root -g root -m 644 /dev/stdin /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
CONF
        echo "Автообновления включены. Проверка делом:"
        grep '' /etc/apt/apt.conf.d/20auto-upgrades
        ;;
    harden-fail2ban)
        [ $# -eq 0 ] || die "harden-fail2ban доводов не принимает"
        [ -f "$LIB/config.sh" ] || die "не установлен $LIB/config.sh"
        # shellcheck source=/dev/null
        . "$LIB/config.sh"
        command -v fail2ban-client >/dev/null 2>&1 || die "fail2ban не установлен"
        # Значения берутся из root-овой config.sh, не из доводов.
        install -o root -g root -m 644 /dev/stdin /etc/fail2ban/jail.local <<CONF
# Сгенерирован webui-sec harden-fail2ban из /opt/secaudit/config.sh.
# Правится там, а не здесь: этот файл перезапишется.
[DEFAULT]
backend  = systemd
bantime  = 24h
findtime = 30m
maxretry = 5
ignoreip = ${TRUSTED_IPS}

[sshd]
enabled  = true
mode     = aggressive
port     = ${SSH_PORT}
maxretry = 3
bantime  = 7d

# Тех, кого уже банили, банит надолго. При парольном входе это главная мера
# после ограничения темпа: подбор растягивается настолько, что теряет смысл.
[recidive]
enabled  = true
bantime  = 30d
findtime = 1d
maxretry = 3
CONF
        systemctl restart fail2ban
        sleep 2
        # Проверка делом, а не «служба active»: перезапустившийся fail2ban
        # с битым правилом поднимается, но джейла не заводит.
        fail2ban-client status sshd >/dev/null 2>&1 \
            || die "fail2ban поднялся, но джейл sshd не заведён — смотрите journalctl -u fail2ban"
        echo "fail2ban настроен. Джейлы:"
        fail2ban-client status | sed 's/^/  /'
        ;;
    harden-ssh)
        [ $# -eq 0 ] || die "harden-ssh доводов не принимает"
        [ -f "$LIB/config.sh" ] || die "не установлен $LIB/config.sh"
        # shellcheck source=/dev/null
        . "$LIB/config.sh"
        id "$ADMIN_USER" >/dev/null 2>&1 \
            || die "учётки «$ADMIN_USER» из config.sh нет — AllowUsers отрезал бы доступ"

        # Режим входа. В key пароль выключается — и тогда без годного ключа в
        # authorized_keys на машину не войти никому. Проверяем это ДО записи:
        # замок без ключа ставится одной командой, а снимается только через
        # консоль хостера.
        auth_lines=""
        if [ "${SSH_AUTH_MODE:-password}" = "key" ]; then
            home=$(getent passwd "$ADMIN_USER" | cut -d: -f6)
            keys="$home/.ssh/authorized_keys"
            [ -s "$keys" ] || die "в $keys нет ключей — выключить пароль значит закрыть вход совсем"
            ssh-keygen -lf "$keys" >/dev/null 2>&1 \
                || die "$keys не разбирается как список ключей — пароль не выключаю"
            auth_lines="PasswordAuthentication no
KbdInteractiveAuthentication no"
        fi

        # ⚠️ Имя файла начинается с 10-, а не 99-: OpenSSH берёт ПЕРВОЕ
        # встреченное значение, и 50-cloud-init.conf перебил бы более поздний
        # файл. Инструкция описывает этот случай как уже стоивший кому-то
        # времени: reload проходил без ошибок, файл выглядел правильно,
        # а настройка не действовала.
        DST=/etc/ssh/sshd_config.d/10-hardening.conf
        BAK="$LIB/backup/10-hardening.conf.before-$(date +%F_%H%M%S)"
        [ -f "$DST" ] && cp -a "$DST" "$BAK"

        # Пароль выключается только в режиме key (SSH_AUTH_MODE в config.sh).
        # В режиме password остаются компенсирующие меры.
        install -o root -g root -m 644 /dev/stdin "$DST" <<CONF
# Сгенерирован webui-sec harden-ssh из /opt/secaudit/config.sh.
# Имя с 10- намеренно: OpenSSH берёт первое встреченное значение.
# Режим входа: ${SSH_AUTH_MODE:-password}
PermitRootLogin no
MaxAuthTries 3
LoginGraceTime 20
LogLevel VERBOSE
AllowUsers ${ADMIN_USER}
${auth_lines}
CONF
        if ! sshd -t 2>/tmp/sshd-test.log; then
            rm -f "$DST"
            [ -f "$BAK" ] && cp -a "$BAK" "$DST"
            die "sshd отверг настройки, вернул как было: $(cat /tmp/sshd-test.log)"
        fi
        systemctl reload ssh
        # Проверка делом: что ДЕЙСТВУЕТ, а не что написано в файле.
        echo "Действующие настройки входа:"
        sshd -T | grep -E '^(port|permitrootlogin|passwordauthentication|kbdinteractiveauthentication|maxauthtries|allowusers)' | sed 's/^/  /'
        if [ "${SSH_AUTH_MODE:-password}" = "key" ]; then
            sshd -T | grep -qx 'passwordauthentication no' \
                || die "в файле пароль выключен, а sshd -T его не видит — что-то перебивает настройку"
        fi
        echo
        echo "⚠️ НЕ ЗАКРЫВАЙТЕ текущую сессию, пока не проверите вход из второго окна."
        echo "   Откат: sudo rm $DST && sudo systemctl reload ssh"
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
        # ⚠️ `|| true` обязателен. Пока отчётов нет, `ls` отдаёт 2, `head` — 0,
        # а `pipefail` делает кодом конвейера 2, и `set -e` гасит обёртку после
        # первой же строки. Проверено нажатием: сводка обрывалась на baseline.
        last=$(ls -1t "$STATE/reports"/rep_*.md 2>/dev/null | head -1 || true)
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
