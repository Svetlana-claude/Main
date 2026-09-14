#!/bin/bash
# Переход на вход только по ключам и полный беспарольный доступ агента.
# Последний ручной шаг с паролем (решение от 14.09.2026).
#
# Запуск:
#     sudo bash infra/switch-to-keys.sh
#
# ⚠️ НЕ ЗАКРЫВАЙТЕ сессию, из которой запускаете, пока не проверите вход по
# ключу из второго окна. Уже открытое соединение выключение пароля не рвёт.
#
# Порядок жёсткий, и каждый шаг проверяется ДЕЛОМ, прежде чем идти дальше:
#
#   1. разложить свежие обёртки и скрипты аудита;
#   2. убедиться, что в authorized_keys есть ключ — иначе замок без ключа;
#   3. выключить пароль (webui-sec harden-ssh в режиме key);
#   4. убедиться по `sshd -T` и настоящей попыткой входа, что пароль выключен;
#   5. ТОЛЬКО ПОСЛЕ ЭТОГО выдать беспарольный sudo на всё.
#
# Почему 5 строго после 4. Беспарольный sudo при парольном входе по SSH —
# один шаг от подбора пароля до root (§11 инструкции по аудиту). Выдай доступ
# раньше, упади шаг 3 — и машина осталась бы именно в этом состоянии.

set -euo pipefail

ADMIN_USER=mokeeva
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

step() { echo; echo "== $* =="; }
die()  { echo; echo "ОСТАНОВЛЕНО: $*" >&2; echo "Беспарольный доступ НЕ выдан." >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || { echo "нужен root: sudo bash $0" >&2; exit 1; }

step "1. Обёртки и скрипты аудита"
bash "$REPO/infra/install-root-helpers.sh"
grep -qx 'SSH_AUTH_MODE=key' /opt/secaudit/config.sh \
    || die "в установленной config.sh режим не key — установка не легла"

step "2. Ключи в authorized_keys"
KEYS="$(getent passwd "$ADMIN_USER" | cut -d: -f6)/.ssh/authorized_keys"
[ -s "$KEYS" ] || die "$KEYS пуст — выключать пароль нельзя"
ssh-keygen -lf "$KEYS" | sed 's/^/  /'

step "3. Выключаю вход по паролю"
/usr/local/sbin/webui-sec harden-ssh

step "4. Проверка делом"
sshd -T | grep -qx 'passwordauthentication no' \
    || die "sshd -T показывает, что пароль всё ещё включён"
echo "  sshd -T: passwordauthentication no"

# Настоящая попытка входа паролем. Сервер обязан предложить только publickey:
# «Permission denied (publickey)» без «password» в скобках.
answer=$(ssh -o BatchMode=yes -o PubkeyAuthentication=no -o PreferredAuthentications=password \
             -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 \
             "$ADMIN_USER@127.0.0.1" true 2>&1 | tail -1 || true)
echo "  попытка входа паролем: $answer"
case "$answer" in
    *"(publickey)"*) ;;
    *password*) die "сервер всё ещё предлагает вход по паролю" ;;
    *) die "не удалось проверить вход: $answer" ;;
esac

step "5. Беспарольный доступ агента"
bash "$REPO/infra/apply-sudo.sh"
sudo -l -U "$ADMIN_USER" | grep -q 'NOPASSWD: ALL' \
    || die "правило установлено, но sudo -l его не показывает"
echo "  sudo -l: NOPASSWD: ALL для $ADMIN_USER"

cat <<EOF

Готово. Вход на сервер — только по ключу, агент работает без пароля.

СЕЙЧАС, не закрывая это окно, откройте второе и войдите по ключу:

    ssh -i ~/.ssh/mokeeva-ssh-key $ADMIN_USER@mokeevasky.ru

Если вход не удался — в этом окне верните пароль:

    sudo rm /etc/ssh/sshd_config.d/10-hardening.conf && sudo systemctl reload ssh

EOF
