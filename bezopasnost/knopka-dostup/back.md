# Обратный туннель к ноуту — установка OpenSSH и настройка ключей

Пошаговая инструкция к «Кнопке доступа» (`bezopasnost/knopka-dostup/`). Здесь подробно
разобраны **установка OpenSSH** и **настройка двух ключей**. Остальное (known_hosts, запуск
программы, как заходить) — в `SETUP.md`.

## Главное: ключей два, роли разные

- **Ключ входа** — им *вы* заходите на ноут со своего устройства. Открытая часть кладётся
  **на ноут**.
- **Ключ туннеля** — им *ноут* заходит на *сервер*, чтобы поднять туннель. Открытая часть
  кладётся **на сервер**.

Это две разные пары, путать нельзя.

| Ключ | Создаётся на | Закрытая часть | Открытая часть | Роль |
|---|---|---|---|---|
| **входа** (`noutbuk_vhod`) | вашем устройстве | у вас | на ноуте (`authorized_keys`) | вы заходите на ноут |
| **туннеля** (`knopka_tunnel`) | ноуте | на ноуте | на сервере (`authorized_keys`) | ноут поднимает туннель к серверу |

---

## Часть A. Установить OpenSSH на ноуте

Открыть **PowerShell от имени администратора** (Пуск → ввести «PowerShell» → правой
кнопкой → «Запуск от имени администратора»).

**A.1. Проверить, что уже стоит:**

```powershell
Get-WindowsCapability -Online -Name OpenSSH*
```

В выводе у `OpenSSH.Client` и `OpenSSH.Server` смотрите поле `State`: `Installed` — стоит,
`NotPresent` — нет.

**A.2. Поставить то, чего нет:**

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
```

Клиент нужен для `ssh`/`ssh-keygen`, сервер (`sshd`) — чтобы на ноут можно было зайти.

---

## Часть B. Запереть sshd ноута (loopback + только по ключу)

Там же, в админском PowerShell. Выполнить блоком:

```powershell
Set-Service sshd -StartupType Manual     # не стартует сам при загрузке
Start-Service sshd                        # запустить сейчас
$cfg = 'C:\ProgramData\ssh\sshd_config'
$t = Get-Content $cfg -Raw
if ($t -notmatch '(?m)^ListenAddress 127\.0\.0\.1') { $t = "ListenAddress 127.0.0.1`r`n" + $t }
$t = $t -replace '(?m)^#?\s*PasswordAuthentication.*', 'PasswordAuthentication no'
$t = $t -replace '(?m)^#?\s*PubkeyAuthentication.*',   'PubkeyAuthentication yes'
Set-Content $cfg -Value $t -Encoding ascii
Restart-Service sshd
```

Что это даёт:

- `ListenAddress 127.0.0.1` — sshd ноута слушает **только локально**. Снаружи, напрямую из
  сети, к нему не подключиться — только через поднятый туннель.
- `PasswordAuthentication no` — вход по паролю выключен.
- `PubkeyAuthentication yes` — вход только по ключу.

---

## Часть C. Ключ ВХОДА (вы → ноут)

**C.1. Создать пару на устройстве, с которого будете заходить** (ваш рабочий комп/телефон с
SSH), а не на ноуте. Например на Linux/Mac:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/noutbuk_vhod -C "vhod-na-nout"
```

Получите `noutbuk_vhod` (закрытый, хранится у вас) и `noutbuk_vhod.pub` (открытый).
Содержимое открытой части посмотреть: `cat ~/.ssh/noutbuk_vhod.pub`.

**C.2. Открытую часть `noutbuk_vhod.pub` положить на ноут.** На ноуте, в админском
PowerShell. Если ваша учётка Windows — администратор:

```powershell
$ak = 'C:\ProgramData\ssh\administrators_authorized_keys'
Add-Content $ak -Value 'ssh-ed25519 AAAA...сюда содержимое noutbuk_vhod.pub...' -Encoding ascii
icacls $ak /inheritance:r /grant "*S-1-5-32-544:F" /grant "*S-1-5-18:F"
```

Если учётка **не** администратор — класть в `C:\Users\<вы>\.ssh\authorized_keys` (папку
`.ssh` при необходимости создать), `icacls` для этого файла не нужен.

> Строку `ssh-ed25519 AAAA...` берёте целиком из `noutbuk_vhod.pub`. `icacls` обязателен:
> Windows-sshd игнорирует `administrators_authorized_keys` с неправильными правами, и вход
> молча не сработает.

---

## Часть D. Ключ ТУННЕЛЯ (ноут → сервер)

**D.1. Создать пару на ноуте** (обычный PowerShell, без админа):

```powershell
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\knopka_tunnel -N '""'
type $env:USERPROFILE\.ssh\knopka_tunnel.pub
```

`knopka_tunnel` (закрытый) остаётся на ноуте — его путь потом впишете в программу. `type`
покажет открытую часть — скопируйте её.

**D.2. Открытую часть авторизовать на сервере.** На сервере, в вашей учётке, добавить её в
`~/.ssh/authorized_keys`, сузив права ключа только до проброса:

```bash
echo 'restrict,port-forwarding ssh-ed25519 AAAA...knopka_tunnel.pub...' >> ~/.ssh/authorized_keys
```

`restrict` снимает с ключа всё лишнее (шелл, агент, X11), `port-forwarding` оставляет только
туннель. Так даже этот ключ не даёт на сервере ничего, кроме проброса.

**D.3. Проверить на сервере**, что проброс разрешён (обычно да по умолчанию) — в
`/etc/ssh/sshd_config`:

```
AllowTcpForwarding yes
```

`GatewayPorts` **включать не надо** — проброс специально остаётся на loopback сервера.

---

## Дальше

Known_hosts, настройка и запуск программы, как заходить на ноут — в `SETUP.md`
(шаги 4–5 и раздел «Как заходить на ноут»).
