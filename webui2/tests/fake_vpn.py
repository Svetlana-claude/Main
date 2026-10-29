"""Подставная обёртка VPN: устройства — в файле FAKE_VPN_DB, настоящий VPN не трогается."""
import json
import os
import re
import sys

db_path = os.environ["FAKE_VPN_DB"]
devices = json.load(open(db_path)) if os.path.exists(db_path) else {}
cmd, args = sys.argv[1], sys.argv[2:]


def save() -> None:
    json.dump(devices, open(db_path, "w"))


def conf(name: str) -> str:
    return f"[Interface]\nPrivateKey = fake-secret-{name}\nAddress = {devices[name]['ip']}/32\n"


if cmd == "peers":
    for name, d in devices.items():
        print(f"{name}\t{d['ip']}/32\tkey\t{d['rx']}\t{d['tx']}\t{d['shake']}\t")
elif cmd in ("add", "config", "remove"):
    name = args[0]
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$", name):
        sys.exit("плохое имя")
    if cmd == "add":
        if name in devices:
            sys.exit(f"клиент «{name}» уже заведён")
        devices[name] = {"ip": f"10.8.0.{len(devices) + 2}", "rx": 0, "tx": 0, "shake": 0}
        save()
    elif name not in devices:
        sys.exit(f"файла для «{name}» нет")
    if cmd == "remove":
        del devices[name]
        save()
    else:
        print(conf(name), end="")
else:
    sys.exit("неизвестная команда")
