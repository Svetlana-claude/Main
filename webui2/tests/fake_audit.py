"""Подставная ночная проверка: пишет снимок и отчёт за сегодня в FAKE_SEC_STATE
(как audit.sh). После «approve» расхождений нет. Есть <каталог>/fail — ошибка.
С доводом approve — подставной «webui-sec baseline-approve»."""
import os
import sys
import time
from pathlib import Path

state = Path(os.environ["FAKE_SEC_STATE"])
today = time.strftime("%Y-%m-%d")
if (state / "fail").exists():
    print("sudo: нужен пароль")
    sys.exit(1)
if sys.argv[1:] == ["approve"]:
    if not (state / "snapshots" / f"{today}.txt").exists():
        sys.exit("снимка за сегодня нет")
    (state / "approved").write_text(today)
    sys.exit(0)
(state / "snapshots").mkdir(parents=True, exist_ok=True)
(state / "reports").mkdir(parents=True, exist_ok=True)
with open(state / "runs.log", "a") as fh:
    fh.write(f"REMEDIATE={os.environ.get('REMEDIATE', '')}\n")
(state / "snapshots" / f"{today}.txt").write_text(
    "# Снимок\n\n##LISTEN\ntcp 0.0.0.0:22 (\"sshd\")\ntcp 0.0.0.0:443 (\"nginx\")\n"
    "tcp 127.0.0.1:8002 (\"uvicorn\")\ntcp 0.0.0.0:4444 (\"nc\")\nudp 0.0.0.0:51820 \n\n"
    "##FIREWALL\nv4_policy=-P INPUT DROP\nv6_policy=-P INPUT DROP\nfail2ban=active\nCurrently banned:\t7\n\n"
    "##USERS\nmokeeva uid=1000 shell=/bin/bash\nglavpryg uid=1001 shell=/usr/sbin/nologin\n\n"
    "##SSHKEYS\nmokeeva: SHA256:abc (ED25519)\n\n##SSHCONF\nport 22\npermitrootlogin no\npasswordauthentication no\n\n"
    "##AUTHFAIL\nfailed_password_24h=3\n-- успешные входы за сутки:\n     5 for mokeeva from 10.1.2.3\n\n"
    "##UPDATES\npending_total=12\npending_security=0\nтребуется_перезагрузка=нет\n")
if (state / "approved").exists():
    diff = "Расхождений с эталоном нет.\n"
else:
    diff = ("### Расхождение с эталоном: LISTEN\n  ПОЯВИЛОСЬ: tcp 0.0.0.0:4444 (\"nc\")\n\n"
            "### Расхождение с эталоном: USERS\n  ПРОПАЛО:  guest uid=1002 shell=/bin/bash\n\n"
            "### Справочно: аккаунты с интерактивной оболочкой\n  mokeeva uid=1000 shell=/bin/bash\n\n")
(state / "reports" / f"rep_{today}.md").write_text(
    f"# Отчёт безопасности — {today}\n\nСервер: test. Аудит выполнен 01.01.2026 в 00:00 UTC.\n\n"
    "## Оценка\nРазбор не выполнялся.\n\n## Устранено автоматически\n\nАвтоматических действий не потребовалось.\n\n"
    f"## Расхождения с эталоном (машинная проверка)\n\n```\n{diff}```\n\n"
    "<details><summary>Полный снимок состояния</summary>\n\n```\n##LISTEN\ntcp 0.0.0.0:22 <b>\n```\n\n</details>\n")
