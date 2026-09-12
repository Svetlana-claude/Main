#!/bin/bash
# Файрвол default-deny. Всё входящее, кроме перечисленного, отбрасывается.
# Применяется к IPv4 и IPv6.
#
# INPUT очищается целиком — это безопасно: цепочки Docker висят на FORWARD,
# в INPUT их нет. FORWARD и цепочки DOCKER* не трогаем.
#
# ⚠️ Отличия от исходной инструкции, оба обязательные:
#   1. открывается UDP (PUB_UDP). В инструкции его нет вовсе, и WireGuard
#      на 51820/udp был бы отрезан молча;
#   2. принимается трафик с доверенных интерфейсов (TRUSTED_IFACES). Клиент
#      VPN с полным туннелем ходит к серверу по 10.8.0.1, и это INPUT с wg0.
set -euo pipefail
BASE=${BASE:-/opt/secaudit}
. "$BASE/config.sh"

apply_v4() {
  iptables -F INPUT
  iptables -A INPUT -i lo -j ACCEPT
  for ifc in ${TRUSTED_IFACES:-}; do
    iptables -A INPUT -i "$ifc" -j ACCEPT
  done
  iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  iptables -A INPUT -m conntrack --ctstate INVALID -j DROP
  for ip in ${BLOCKED_V4:-}; do iptables -A INPUT -s "$ip" -j DROP; done
  iptables -A INPUT -p icmp --icmp-type echo-request -m limit --limit 5/sec --limit-burst 10 -j ACCEPT
  if [ "${SSH_AUTH_MODE:-key}" = "password" ] && [ -n "${ADMIN_NETS:-}" ]; then
    # Пароль подбираем — значит, подбирать должно быть неоткуда.
    for net in $ADMIN_NETS; do
      iptables -A INPUT -p tcp --dport "$SSH_PORT" -s "$net" -m conntrack --ctstate NEW -j ACCEPT
    done
    iptables -A INPUT -p tcp --dport "$SSH_PORT" -j DROP
  elif [ "${SSH_AUTH_MODE:-key}" = "password" ]; then
    # Адрес плавающий: ограничиваем темп — 4 новых соединения в минуту с адреса.
    # Порядок важен: --set до --update, иначе список никогда не наполнится.
    iptables -A INPUT -p tcp --dport "$SSH_PORT" -m conntrack --ctstate NEW -m recent --set --name SSHPROBE
    iptables -A INPUT -p tcp --dport "$SSH_PORT" -m conntrack --ctstate NEW -m recent --update --seconds 60 \
        --hitcount "${SSH_RATE_HITCOUNT:-10}" --name SSHPROBE -j DROP
    iptables -A INPUT -p tcp --dport "$SSH_PORT" -m conntrack --ctstate NEW -j ACCEPT
  else
    iptables -A INPUT -p tcp --dport "$SSH_PORT" -m conntrack --ctstate NEW -j ACCEPT
  fi
  iptables -A INPUT -p tcp -m multiport --dports "$PUB_TCP" -m conntrack --ctstate NEW -j ACCEPT
  [ -n "${PUB_UDP:-}" ] && iptables -A INPUT -p udp -m multiport --dports "$PUB_UDP" -j ACCEPT
  iptables -P INPUT DROP
}

apply_v6() {
  ip6tables -F INPUT
  ip6tables -A INPUT -i lo -j ACCEPT
  for ifc in ${TRUSTED_IFACES:-}; do
    ip6tables -A INPUT -i "$ifc" -j ACCEPT
  done
  ip6tables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  ip6tables -A INPUT -m conntrack --ctstate INVALID -j DROP
  # ICMPv6 нужен для работы IPv6 (NDP, PMTU) — вырезать нельзя, иначе сеть развалится.
  ip6tables -A INPUT -p ipv6-icmp -j ACCEPT
  ip6tables -A INPUT -s fe80::/10 -j ACCEPT
  ip6tables -A INPUT -p tcp --dport "$SSH_PORT" -m conntrack --ctstate NEW -j ACCEPT
  ip6tables -A INPUT -p tcp -m multiport --dports "$PUB_TCP" -m conntrack --ctstate NEW -j ACCEPT
  [ -n "${PUB_UDP:-}" ] && ip6tables -A INPUT -p udp -m multiport --dports "$PUB_UDP" -j ACCEPT
  ip6tables -P INPUT DROP
}

apply_v4
apply_v6
echo "Правила применены."
