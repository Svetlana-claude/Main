using System.Windows;
using System.Windows.Media;
using Microsoft.Win32;

namespace KnopkaDostup;

/// <summary>Окно: правка настроек, одна кнопка «Открыть/Закрыть доступ», лампочка состояния и журнал.</summary>
public partial class MainWindow : Window
{
    private readonly TunnelClient _tunnel = new();
    private Config _cfg = Config.Load();

    public MainWindow()
    {
        InitializeComponent();
        FillFields();
        _tunnel.OnLog += AppendLog;
        _tunnel.OnStateChanged += () => Dispatcher.Invoke(RefreshState);
        RefreshState();
    }

    private void FillFields()
    {
        TbHost.Text = _cfg.ServerHost;
        TbPort.Text = _cfg.ServerPort.ToString();
        TbUser.Text = _cfg.ServerUser;
        TbFwd.Text = _cfg.ForwardPort.ToString();
        TbKey.Text = _cfg.KeyPath;
        TbKnown.Text = _cfg.KnownHostsPath;
    }

    /// <summary>Снять настройки из полей в конфиг. Возвращает текст ошибки разбора или null.</summary>
    private string? ReadFields()
    {
        if (!int.TryParse(TbPort.Text.Trim(), out var port)) return "порт сервера — не число";
        if (!int.TryParse(TbFwd.Text.Trim(), out var fwd)) return "порт туннеля — не число";
        _cfg.ServerHost = TbHost.Text.Trim();
        _cfg.ServerPort = port;
        _cfg.ServerUser = TbUser.Text.Trim();
        _cfg.ForwardPort = fwd;
        _cfg.KeyPath = TbKey.Text.Trim();
        _cfg.KnownHostsPath = TbKnown.Text.Trim();
        return null;
    }

    private void BtnToggle_Click(object sender, RoutedEventArgs e)
    {
        if (_tunnel.Enabled)
        {
            _tunnel.Disable();
            return;
        }

        var parse = ReadFields();
        if (parse != null) { MessageBox.Show(this, parse, "Проверьте настройки"); return; }

        var bad = _cfg.Validate();
        if (bad != null) { MessageBox.Show(this, bad, "Проверьте настройки"); return; }

        try { _cfg.Save(); }
        catch (Exception ex) { MessageBox.Show(this, "Не записаны настройки: " + ex.Message, "Ошибка"); return; }

        _tunnel.Enable(_cfg);
        RefreshState();
    }

    private void BtnKey_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new OpenFileDialog { Title = "Закрытый ключ для входа на сервер" };
        if (dlg.ShowDialog(this) == true) TbKey.Text = dlg.FileName;
    }

    private void BtnKnown_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new OpenFileDialog { Title = "known_hosts с ключом вашего сервера" };
        if (dlg.ShowDialog(this) == true) TbKnown.Text = dlg.FileName;
    }

    private void RefreshState()
    {
        var on = _tunnel.Enabled;
        BtnToggle.Content = on ? "Закрыть доступ" : "Открыть доступ";
        SetFieldsEnabled(!on);

        if (!on)
        {
            Lamp.Fill = new SolidColorBrush(Color.FromRgb(0xBB, 0xBB, 0xBB));
            TbStatus.Text = "Выключено";
        }
        else if (_tunnel.Connected)
        {
            Lamp.Fill = new SolidColorBrush(Color.FromRgb(0x2E, 0xA0, 0x43));
            TbStatus.Text = "Доступ открыт — заходите через сервер";
        }
        else
        {
            Lamp.Fill = new SolidColorBrush(Color.FromRgb(0xE0, 0xA0, 0x00));
            TbStatus.Text = _tunnel.LastError is { Length: > 0 } ? "Подключение… " + _tunnel.LastError : "Подключение…";
        }
    }

    private void SetFieldsEnabled(bool v)
    {
        TbHost.IsEnabled = TbPort.IsEnabled = TbUser.IsEnabled = TbFwd.IsEnabled =
            TbKey.IsEnabled = TbKnown.IsEnabled = BtnKey.IsEnabled = BtnKnown.IsEnabled = v;
    }

    private void AppendLog(string line) => Dispatcher.Invoke(() =>
    {
        TbLog.AppendText(line + Environment.NewLine);
        TbLog.ScrollToEnd();
    });

    protected override void OnClosed(EventArgs e)
    {
        _tunnel.Disable();   // закрыли окно — туннель гаснет, доступа не остаётся
        base.OnClosed(e);
    }
}
