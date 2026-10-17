using System.Diagnostics;
using System.IO;
using System.Text;

namespace KnopkaDostup;

/// <summary>
/// Обратный туннель ноут → ваш сервер. Запускает встроенный <c>ssh.exe</c> с ключом <c>-R</c>:
/// порт на 127.0.0.1 СЕРВЕРА пробрасывается на локальный sshd ноута (127.0.0.1:22). Держит
/// соединение, пока включено, и переподключается при обрыве.
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
        }
        KillSsh();
        Connected = false;
        Log("Выключено: доступа к ноуту по туннелю больше нет");
        OnStateChanged?.Invoke();
    }

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

            try { _ssh = Process.Start(psi); }
            catch (Exception e)
            {
                LastError = e.Message;
                Log("Не удалось запустить ssh (стоит ли клиент OpenSSH?): " + e.Message);
                OnStateChanged?.Invoke();
                break;
            }
            if (_ssh == null) break;

            _ssh.ErrorDataReceived += (_, e) =>
            {
                if (!string.IsNullOrWhiteSpace(e.Data)) { LastError = e.Data; Log("ssh: " + e.Data); }
            };
            _ssh.BeginErrorReadLine();

            // С ExitOnForwardFailure ssh быстро выходит, если проброс не поднялся. Жив через 3 с — считаем, что встал.
            if (_ssh.WaitForExit(3000))
            {
                if (!_enabled) return;
                Log($"Соединение не поднялось (код {_ssh.ExitCode}), повтор через 15 с");
                OnStateChanged?.Invoke();
                Sleep(15);
                continue;
            }
            Connected = true;
            LastError = null;
            Log("Соединён — можно заходить на ноут через сервер, пока кнопка включена");
            OnStateChanged?.Invoke();

            _ssh.WaitForExit();
            Connected = false;
            if (!_enabled) return;
            Log("Соединение оборвалось, переподключение через 15 с");
            OnStateChanged?.Invoke();
            Sleep(15);
        }
    }

    /// <summary>Аргументы ssh. Только проброс (-N -R), без удалённой команды.</summary>
    private static IEnumerable<string> BuildArgs(Config c)
    {
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
