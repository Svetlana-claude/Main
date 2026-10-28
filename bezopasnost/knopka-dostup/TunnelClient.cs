using System.Diagnostics;
using System.IO;
using System.Text;

namespace KnopkaDostup;

/// <summary>
/// Обратный туннель ноут → ваш сервер. Запускает встроенный <c>ssh.exe</c> с ключом <c>-R</c>:
/// порт на 127.0.0.1 СЕРВЕРА пробрасывается на локальный sshd ноута (127.0.0.1:22). Держит
/// соединение, пока включено, и переподключается при обрыве. ssh.exe лежит в «задании» Windows
/// (<see cref="JobObject"/>) и гаснет вместе с программой, как бы она ни закрылась.
///
/// Чего здесь намеренно НЕТ (в отличие от примера BackTunnel) и не будет:
///   • не кладёт ничьих ключей в sshd ноута — вход решает только то, что вы сами туда положили;
///   • не принимает и не исполняет команды из сети;
///   • не обновляет себя по сети;
///   • не заводит службу и не прописывается в автозапуск — доступ живёт ровно пока открыто окно
///     и нажата кнопка. Закрыли — туннеля нет.
/// Проброс слушает только на 127.0.0.1 сервера, поэтому дойти до него можно, лишь уже войдя
/// на сервер под вашей учёткой.
/// </summary>
public sealed class TunnelClient
{
    private readonly object _lock = new();
    private Process? _ssh;
    private Thread? _loop;
    private volatile bool _enabled;
    private Config? _cfg;

    public bool Enabled => _enabled;
    public bool Connected { get; private set; }
    public string? LastError { get; private set; }

    public event Action<string>? OnLog;
    public event Action? OnStateChanged;

    /// <summary>Встроенный клиент OpenSSH Windows.</summary>
    public static string SshExe =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "OpenSSH", "ssh.exe");

    // --- Включение / выключение -----------------------------------------------------------------

    public void Enable(Config cfg)
    {
        lock (_lock)
        {
            if (_enabled) return;
            _cfg = cfg;
            _enabled = true;
            LastError = null;
            _loop = new Thread(Loop) { IsBackground = true, Name = "knopka-tunnel" };
            _loop.Start();
            Log($"Включено: туннель на {cfg.ServerUser}@{cfg.ServerHost}:{cfg.ServerPort}, " +
                $"на сервере порт {cfg.ForwardPort} → ноут 127.0.0.1:22");
        }
    }

    public void Disable()
    {
        lock (_lock)
        {
            if (!_enabled) return;
            _enabled = false;
            KillSsh();
        }
        Connected = false;
        Log("Выключено: доступа к ноуту по туннелю больше нет");
        OnStateChanged?.Invoke();
    }

    /// <summary>Сколько ждать подтверждения проброса от сервера, прежде чем начать заново.</summary>
    private const int ConfirmTimeoutSec = 30;

    private void Loop()
    {
        while (_enabled)
        {
            var psi = new ProcessStartInfo(SshExe)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardError = true,
                RedirectStandardOutput = true,
            };
            foreach (var a in BuildArgs(_cfg!)) psi.ArgumentList.Add(a);

            Process? ssh;
            var confirmed = new ManualResetEventSlim(false);
            lock (_lock)
            {
                // Под замком: «Закрыть доступ» не может проскочить между проверкой и запуском
                // и оставить ssh, о котором никто не знает.
                if (!_enabled) return;
                try { ssh = Process.Start(psi); }
                catch (Exception e)
                {
                    LastError = e.Message;
                    Log("Не удалось запустить ssh (стоит ли клиент OpenSSH?): " + e.Message);
                    OnStateChanged?.Invoke();
                    break;
                }
                if (ssh == null) break;
                if (!JobObject.Add(ssh))
                    Log("Внимание: ssh не привязан к программе — при сбое программы туннель может остаться");
                _ssh = ssh;
            }

            ssh.ErrorDataReceived += (_, e) =>
            {
                if (string.IsNullOrWhiteSpace(e.Data)) return;
                // ssh -v: подробности не пишем, кроме подтверждения сервера, что проброс поднят.
                if (e.Data.StartsWith("debug", StringComparison.Ordinal))
                {
                    if (e.Data.Contains("remote forward success")) confirmed.Set();
                    return;
                }
                if (e.Data.StartsWith("OpenSSH_", StringComparison.Ordinal) ||
                    e.Data.StartsWith("Authenticated to", StringComparison.Ordinal)) return;   // не ошибки
                LastError = e.Data;
                Log("ssh: " + e.Data);
            };
            ssh.BeginErrorReadLine();

            // Зелёный — только когда сервер подтвердил проброс, а не «ssh пока не упал».
            var exited = new ManualResetEventSlim(false);
            ssh.EnableRaisingEvents = true;
            ssh.Exited += (_, _) => exited.Set();
            if (ssh.HasExited) exited.Set();
            var which = WaitHandle.WaitAny(new[] { confirmed.WaitHandle, exited.WaitHandle },
                                           TimeSpan.FromSeconds(ConfirmTimeoutSec));
            if (!_enabled) return;

            if (which == 0)
            {
                Connected = true;
                LastError = null;
                Log("Соединён — сервер подтвердил туннель, можно заходить на ноут, пока кнопка включена");
                OnStateChanged?.Invoke();
                exited.Wait();
                Connected = false;
                if (!_enabled) return;
                Log("Соединение оборвалось, переподключение через 15 с");
            }
            else if (which == WaitHandle.WaitTimeout)
            {
                KillSsh();
                LastError = "сервер не отвечает";
                Log($"Сервер не подтвердил туннель за {ConfirmTimeoutSec} с — связь не доходит " +
                    "(включён VPN или защита сети на ноуте?). Повтор через 15 с");
            }
            else
            {
                Log($"Соединение не поднялось (код {ssh.ExitCode}), повтор через 15 с");
            }
            OnStateChanged?.Invoke();
            Sleep(15);
        }
    }

    /// <summary>Аргументы ssh. Только проброс (-N -R), без удалённой команды.</summary>
    private static IEnumerable<string> BuildArgs(Config c)
    {
        yield return "-v";                              // подробный вывод: по нему видно, что сервер принял проброс
        yield return "-N";                              // не выполнять команд на сервере — только проброс
        yield return "-T";                              // без псевдотерминала
        yield return "-i"; yield return c.KeyPath;
        yield return "-p"; yield return c.ServerPort.ToString();
        yield return "-R";                              // обратный проброс на loopback сервера
        yield return $"127.0.0.1:{c.ForwardPort}:127.0.0.1:22";
        yield return "-o"; yield return "ExitOnForwardFailure=yes";
        yield return "-o"; yield return "ServerAliveInterval=30";
        yield return "-o"; yield return "ServerAliveCountMax=3";
        yield return "-o"; yield return "IdentitiesOnly=yes";
        if (!string.IsNullOrWhiteSpace(c.KnownHostsPath))
        {
            // Сервер пришпилен к known_hosts — подмену сервера ssh отвергнет.
            yield return "-o"; yield return "StrictHostKeyChecking=yes";
            yield return "-o"; yield return $"UserKnownHostsFile=\"{c.KnownHostsPath}\"";
        }
        else
        {
            yield return "-o"; yield return "StrictHostKeyChecking=accept-new";
        }
        yield return $"{c.ServerUser}@{c.ServerHost}";
    }

    private void Sleep(int seconds)
    {
        for (var i = 0; i < seconds * 10 && _enabled; i++) Thread.Sleep(100);
    }

    private void KillSsh()
    {
        try { if (_ssh is { HasExited: false }) _ssh.Kill(true); } catch { }
    }

    // --- Журнал ---------------------------------------------------------------------------------

    private void Log(string text)
    {
        var line = $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {text}";
        try
        {
            Directory.CreateDirectory(Config.Dir);
            File.AppendAllText(Config.LogFile, line + Environment.NewLine, Encoding.UTF8);
        }
        catch { /* журнал не должен ронять работу */ }
        OnLog?.Invoke(line);
    }
}
