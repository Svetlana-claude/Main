<# :
@echo off
setlocal
set "KN_SELF=%~f0"
set "KN_MODE=%~1"
set "KN_USERPROFILE=%~2"
set "KN_ISADMIN=%~3"
powershell -NoProfile -ExecutionPolicy Bypass -Command "iex ([IO.File]::ReadAllText($env:KN_SELF, [Text.Encoding]::UTF8))"
exit /b %errorlevel%
#>

# Настройка ноута для «Кнопки доступа». Запуск — двойным щелчком.
# Первые строки — для cmd: он передаёт весь файл в PowerShell. Дальше — PowerShell.
#
# ================================================================================================
# Что делает (см. SETUP.md и back.md рядом):
#   часть администратора — ставит OpenSSH, запирает sshd ноута (только 127.0.0.1, только ключ),
#     кладёт ключ входа Светланы, закрывает входящий порт 22 в брандмауэре;
#   часть пользователя — проверяет ключ туннеля, пишет known_hosts сервера, заполняет настройки
#     «Кнопки доступа».
# Чего не делает: не меняет ключ туннеля, если он уже есть; не трогает сервер; ничего не
# скачивает, кроме компонентов Windows через её собственное обновление.
# ================================================================================================

$ErrorActionPreference = 'Stop'

# --- Постоянные данные ---------------------------------------------------------------------------

$ServerHost = '46.8.178.196'
$ServerPort = 22
$ServerUser = 'mokeeva'
$ForwardPort = 2222

# Ключ, которым Светлана входит на сервер, — им же она будет входить на ноут (открытая часть).
$VhodKey = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHJR4R62QUUhpAWhIXyPZbd4oTDkNXmGFXhJ5KtwCOT3 mokeeva-workstation-20260912'

# Ключ туннеля, уже прописанный на сервере (открытая часть) — с ним сверяем ключ на ноуте.
$TunnelKeyBody = 'AAAAC3NzaC1lZDI1NTE5AAAAIPyqrqakew3JnETrh4JIm2FercXnRhBzTIsODtvt7Ywi'

# Ключ сервера (SHA256:PqNpj3Z1Qa2IC0c1qvY0h8D1UmkgBIJUaBHYdRdyLd0) — защита от подмены сервера.
$ServerHostKey = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAID7oNjp6oozHhOF+yBoCT0VEQjV98FvZB/XS7hH+JGPY'

# --- Общее ---------------------------------------------------------------------------------------

$script:Ok = New-Object System.Collections.Generic.List[string]
$script:Bad = New-Object System.Collections.Generic.List[string]
function Good($t) { $script:Ok.Add($t); Write-Host "  [готово] $t" -ForegroundColor Green }
function Fail($t) { $script:Bad.Add($t); Write-Host "  [не вышло] $t" -ForegroundColor Red }

function Test-Admin {
    $p = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Состоит ли учётка в «Администраторах» (даже когда окно запущено без повышения прав).
function Test-InAdminGroup {
    (& whoami /groups /fo csv | Out-String) -match 'S-1-5-32-544'
}

# ================================================================================================
# Часть администратора
# ================================================================================================

function Invoke-AdminPart([string]$userProfile, [bool]$userIsAdmin) {
    Write-Host ''
    Write-Host 'Настройка входа на ноут (права администратора)' -ForegroundColor Cyan

    # 1. OpenSSH: клиент и сервер.
    foreach ($name in 'OpenSSH.Client', 'OpenSSH.Server') {
        try {
            $cap = Get-WindowsCapability -Online -Name "$name*" | Select-Object -First 1
            if (-not $cap) { Fail "$name — компонент не найден в этой Windows"; continue }
            if ($cap.State -ne 'Installed') {
                Write-Host "  ставлю $name, это может занять несколько минут..."
                Add-WindowsCapability -Online -Name $cap.Name | Out-Null
            }
            Good "$name стоит"
        } catch { Fail "$name не поставился: $($_.Exception.Message)" }
    }
    if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
        Fail 'служба входа на ноут не появилась — дальше настраивать нечего'
        return
    }

    # 2. Первый запуск создаёт sshd_config; затем запираем его.
    $cfg = Join-Path $env:ProgramData 'ssh\sshd_config'
    try {
        if (-not (Test-Path $cfg)) { Start-Service sshd; Start-Sleep 2 }
        $t = [IO.File]::ReadAllText($cfg)
        if (-not (Test-Path "$cfg.knopka-bak")) { Copy-Item $cfg "$cfg.knopka-bak" }
        $t = [regex]::Replace($t, '(?m)^\s*#?\s*ListenAddress.*\r?\n', '')
        $t = "ListenAddress 127.0.0.1`r`n" + $t
        $t = [regex]::Replace($t, '(?m)^\s*#?\s*PasswordAuthentication\s.*', 'PasswordAuthentication no')
        $t = [regex]::Replace($t, '(?m)^\s*#?\s*PubkeyAuthentication\s.*', 'PubkeyAuthentication yes')
        if ($t -notmatch '(?m)^PasswordAuthentication no') { $t = "PasswordAuthentication no`r`n" + $t }
        if ($t -notmatch '(?m)^PubkeyAuthentication yes') { $t = "PubkeyAuthentication yes`r`n" + $t }
        [IO.File]::WriteAllText($cfg, $t, [Text.Encoding]::ASCII)
        Good 'вход на ноут — только изнутри (127.0.0.1) и только по ключу, пароль выключен'
    } catch { Fail "не удалось поправить настройки входа: $($_.Exception.Message)" }

    # 3. Ключ входа.
    try {
        if ($userIsAdmin) {
            $ak = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
        } else {
            $dir = Join-Path $userProfile '.ssh'
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            $ak = Join-Path $dir 'authorized_keys'
        }
        $old = if (Test-Path $ak) { [IO.File]::ReadAllText($ak) } else { '' }
        $body = ($VhodKey -split ' ')[1]
        if ($old -notmatch [regex]::Escape($body)) {
            if ($old -and -not $old.EndsWith("`n")) { $old += "`r`n" }
            [IO.File]::WriteAllText($ak, $old + $VhodKey + "`r`n", [Text.Encoding]::ASCII)
        }
        if ($userIsAdmin) {
            # Без этих прав Windows молча игнорирует файл.
            & icacls $ak /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F' | Out-Null
        }
        Good "ключ входа положен ($ak)"
    } catch { Fail "не удалось положить ключ входа: $($_.Exception.Message)" }

    # 4. Брандмауэр: входящий 22 снаружи не нужен — только через туннель.
    try {
        Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue |
            Disable-NetFirewallRule
        Good 'входящий порт 22 в брандмауэре закрыт'
    } catch { Fail "брандмауэр не поправился: $($_.Exception.Message)" }

    # 5. Запуск. Сама включается при загрузке, иначе туннелю после перезагрузки не к чему вести.
    try {
        $sshd = Join-Path $env:windir 'System32\OpenSSH\sshd.exe'
        $check = & $sshd -t 2>&1
        if ($LASTEXITCODE -ne 0) { throw "ошибка в настройках: $check" }
        Set-Service sshd -StartupType Automatic
        Restart-Service sshd -Force
        Start-Sleep 2
        $listen = Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty LocalAddress -Unique
        if ((Get-Service sshd).Status -ne 'Running') { throw 'служба не запустилась' }
        if ($listen | Where-Object { $_ -ne '127.0.0.1' }) {
            Fail "порт 22 слушается не только изнутри: $($listen -join ', ')"
        } else {
            Good 'вход на ноут запущен и включается сам при загрузке'
        }
    } catch { Fail "вход на ноут не запустился: $($_.Exception.Message)" }
}

# ================================================================================================
# Часть пользователя
# ================================================================================================

function Invoke-UserPart {
    Write-Host ''
    Write-Host 'Настройка «Кнопки доступа» (твоя учётка)' -ForegroundColor Cyan
    $ssh = Join-Path $env:USERPROFILE '.ssh'
    New-Item -ItemType Directory -Force -Path $ssh | Out-Null

    # 1. Ключ туннеля: есть — сверяем с сервером, нет — создаём.
    $key = Join-Path $ssh 'knopka_tunnel'
    $script:NewTunnelPub = $null
    try {
        if (Test-Path $key) {
            $pub = if (Test-Path "$key.pub") { [IO.File]::ReadAllText("$key.pub") } else { '' }
            if ($pub -match [regex]::Escape($TunnelKeyBody)) {
                Good 'ключ туннеля на месте и совпадает с прописанным на сервере'
            } else {
                Fail 'ключ туннеля есть, но не тот, что на сервере. Его не трогал. Пришли Claude файл knopka_tunnel.pub из папки .ssh'
            }
        } else {
            $kg = Join-Path $env:windir 'System32\OpenSSH\ssh-keygen.exe'
            & $kg -q -t ed25519 -f $key -N '""' -C "knopka-tunnel-$env:COMPUTERNAME" | Out-Null
            $script:NewTunnelPub = [IO.File]::ReadAllText("$key.pub").Trim()
            try { Set-Clipboard -Value $script:NewTunnelPub } catch { }
            Fail 'ключа туннеля не было — создан новый. Сервер его ещё не знает: пришли Claude строку ниже (она уже скопирована)'
        }
    } catch { Fail "ключ туннеля: $($_.Exception.Message)" }

    # 2. Ключ сервера.
    $kh = Join-Path $ssh 'knopka_known_hosts'
    try {
        [IO.File]::WriteAllText($kh, "$ServerHost $ServerHostKey`r`n", [Text.Encoding]::ASCII)
        Good 'отпечаток сервера записан — к подставному серверу ноут не подключится'
    } catch { Fail "отпечаток сервера: $($_.Exception.Message)" }

    # 3. Настройки программы.
    try {
        if (Get-Process KnopkaDostup -ErrorAction SilentlyContinue) {
            throw 'программа сейчас открыта — закрой её и запусти настройку ещё раз'
        }
        $dir = Join-Path $env:LOCALAPPDATA 'KnopkaDostup'
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $conf = [ordered]@{
            ServerHost     = $ServerHost
            ServerPort     = $ServerPort
            ServerUser     = $ServerUser
            ForwardPort    = $ForwardPort
            KeyPath        = $key
            KnownHostsPath = $kh
        }
        $json = $conf | ConvertTo-Json
        [IO.File]::WriteAllText((Join-Path $dir 'config.json'), $json, (New-Object Text.UTF8Encoding $false))
        Good 'поля «Кнопки доступа» заполнены'
    } catch { Fail "настройки программы: $($_.Exception.Message)" }
}

# ================================================================================================
# Запуск
# ================================================================================================

$resultDir = Join-Path $(if ($env:KN_USERPROFILE) { $env:KN_USERPROFILE } else { $env:USERPROFILE }) 'AppData\Local\KnopkaDostup'
$resultFile = Join-Path $resultDir 'nastrojka-admin.txt'

if ($env:KN_MODE -eq 'admin') {
    # Окно администратора: настраивает и пишет итог для основного окна; всё, что видно на
    # экране, дублируется в журнал — на случай, если окно закроется само.
    New-Item -ItemType Directory -Force -Path $resultDir | Out-Null
    try { Start-Transcript -Path (Join-Path $resultDir 'nastrojka-admin.log') -Force | Out-Null } catch { }
    try {
        Invoke-AdminPart $env:KN_USERPROFILE ($env:KN_ISADMIN -eq '1')
    } catch {
        Fail "сбой: $($_.Exception.Message) (строка $($_.InvocationInfo.ScriptLineNumber))"
    }
    $lines = @($script:Ok | ForEach-Object { "OK`t$_" }) + @($script:Bad | ForEach-Object { "BAD`t$_" })
    [IO.File]::WriteAllLines($resultFile, [string[]]$lines, [Text.Encoding]::UTF8)
    try { Stop-Transcript | Out-Null } catch { }
    if ($script:Bad.Count) { Read-Host 'Есть ошибки (см. выше). Нажми Enter' | Out-Null }
} else {

Write-Host 'Настройка ноута для «Кнопки доступа»' -ForegroundColor Cyan
Write-Host 'Сейчас Windows спросит разрешение на изменения — ответь «Да».'
Remove-Item $resultFile -ErrorAction SilentlyContinue

$isAdminGroup = if (Test-InAdminGroup) { '1' } else { '0' }
# Окно администратора — сразу PowerShell, без повторного запуска cmd: так пути с пробелами и
# кавычки не ломаются. Данные передаются внутри закодированной команды.
function Q([string]$v) { "'" + $v.Replace("'", "''") + "'" }
$adminCmd = "`$env:KN_SELF=$(Q $env:KN_SELF); `$env:KN_MODE='admin'; " +
    "`$env:KN_USERPROFILE=$(Q $env:USERPROFILE); `$env:KN_ISADMIN='$isAdminGroup'; " +
    "iex ([IO.File]::ReadAllText(`$env:KN_SELF, [Text.Encoding]::UTF8))"
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($adminCmd))
try {
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded)
} catch {
    Fail 'разрешение администратора не дано — вход на ноут не настроен'
}

if (Test-Path $resultFile) {
    Write-Host ''
    Write-Host 'Настройка входа на ноут (права администратора)' -ForegroundColor Cyan
    foreach ($l in [IO.File]::ReadAllLines($resultFile, [Text.Encoding]::UTF8)) {
        $kind, $text = $l -split "`t", 2
        if ($kind -eq 'OK') { Good $text } else { Fail $text }
    }
} elseif (-not $script:Bad.Count) {
    Fail "окно администратора закрылось без итога — вход на ноут, скорее всего, не настроен. Журнал: $(Join-Path $resultDir 'nastrojka-admin.log')"
}

Invoke-UserPart

Write-Host ''
if ($script:Bad.Count) {
    Write-Host "Готово с ошибками: $($script:Bad.Count). Пришли Claude снимок этого окна." -ForegroundColor Yellow
    if ($script:NewTunnelPub) { Write-Host ''; Write-Host $script:NewTunnelPub }
} else {
    Write-Host 'Всё настроено. Открой «Кнопку доступа» и нажми «Открыть доступ».' -ForegroundColor Green
}
Write-Host ''
Read-Host 'Нажми Enter, чтобы закрыть окно' | Out-Null
}
