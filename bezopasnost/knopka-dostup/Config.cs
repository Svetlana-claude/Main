using System.IO;
using System.Text.Json;

namespace KnopkaDostup;

/// <summary>
/// Настройки доступа. Хранятся в <c>%LOCALAPPDATA%\KnopkaDostup\config.json</c>, правятся из окна.
///
/// Здесь нет ничего, что раздавало бы доступ к ноуту кому-то, кроме вас: это параметры
/// исходящего соединения ноут → ваш сервер. Войти по туннелю всё равно можно только тем ключом,
/// который вы сами положите в sshd ноута (см. SETUP.md).
/// </summary>
public sealed class Config
{
    /// <summary>Адрес вашего сервера (куда ноут дозванивается), например <c>server.example.ru</c>.</summary>
    public string ServerHost { get; set; } = "";

    /// <summary>Порт SSH на сервере.</summary>
    public int ServerPort { get; set; } = 22;

    /// <summary>Учётка на сервере, под которой ноут устанавливает туннель.</summary>
    public string ServerUser { get; set; } = "";

    /// <summary>
    /// Порт на сервере (слушается только на 127.0.0.1 сервера), через который вы затем попадёте на ноут:
    /// на сервере <c>ssh -p &lt;этот порт&gt; &lt;вы&gt;@127.0.0.1</c>. Произвольный свободный, например 2222.
    /// </summary>
    public int ForwardPort { get; set; } = 2222;

    /// <summary>Закрытый ключ, которым ноут входит на сервер (его открытую часть вы кладёте в authorized_keys сервера).</summary>
    public string KeyPath { get; set; } = "";

    /// <summary>Файл known_hosts с ключом ВАШЕГО сервера — защита от подмены. Пусто — пин по первому подключению.</summary>
    public string KnownHostsPath { get; set; } = "";

    // --- Хранение -------------------------------------------------------------------------------

    public static string Dir =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "KnopkaDostup");

    public static string File => Path.Combine(Dir, "config.json");

    public static string LogFile => Path.Combine(Dir, "knopka.log");

    private static readonly JsonSerializerOptions JsonOpts = new() { WriteIndented = true };

    public static Config Load()
    {
        try
        {
            if (System.IO.File.Exists(File))
                return JsonSerializer.Deserialize<Config>(System.IO.File.ReadAllText(File)) ?? new Config();
        }
        catch { /* битый файл — начинаем с пустого */ }
        return new Config();
    }

    public void Save()
    {
        Directory.CreateDirectory(Dir);
        System.IO.File.WriteAllText(File, JsonSerializer.Serialize(this, JsonOpts));
    }

    /// <summary>Чего не хватает для запуска. Пусто — можно включать.</summary>
    public string? Validate()
    {
        if (string.IsNullOrWhiteSpace(ServerHost)) return "не задан адрес сервера";
        if (string.IsNullOrWhiteSpace(ServerUser)) return "не задана учётка на сервере";
        if (ServerPort is < 1 or > 65535) return "порт сервера вне диапазона";
        if (ForwardPort is < 1 or > 65535) return "порт туннеля вне диапазона";
        if (string.IsNullOrWhiteSpace(KeyPath)) return "не задан ключ";
        if (!System.IO.File.Exists(KeyPath)) return $"ключ не найден: {KeyPath}";
        return null;
    }
}
