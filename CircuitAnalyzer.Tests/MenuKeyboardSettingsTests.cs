using System;
using System.IO;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows.Input;
using System.Windows.Interop;
using CircuitAnalyzer.WPF;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Fable denetimi, 5. ve 8. tur: Esc'in gerçek tuş yolunda eleman listesini kapatması,
/// Etkin/Tepe varsayılanının dosya açınca değişmemesi, ayar dosyasının güvenli yazılması.
/// </summary>
[Collection(WpfUiCollection.Name)]
public class MenuKeyboardSettingsTests
{
    private static void RunOnSta(Action action)
    {
        Exception? ex = null;
        var thread = new Thread(() =>
        {
            try { action(); }
            catch (Exception e) { ex = e; }
            finally { System.Windows.Threading.Dispatcher.CurrentDispatcher.InvokeShutdown(); }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        if (ex != null) ExceptionDispatchInfo.Capture(ex).Throw();
    }

    private static void WithTempSettings(Action<string> action)
    {
        string original = AppSettings.SettingsPath;
        string temp = Path.Combine(Path.GetTempPath(), $"settings-{Guid.NewGuid():N}.json");
        try
        {
            AppSettings.SettingsPath = temp;
            action(temp);
        }
        finally
        {
            AppSettings.SettingsPath = original;
            if (File.Exists(temp)) File.Delete(temp);
            if (File.Exists(temp + ".tmp")) File.Delete(temp + ".tmp");
        }
    }

    [Fact]
    public void Escape_ThroughTheRealKeyHandler_ClosesTheDrawer()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow();
            win.RailMeasure.IsChecked = true;
            Assert.True(win.IsElementDrawerOpen);

            using var source = new HwndSource(new HwndSourceParameters("esc-test"));
            var args = new KeyEventArgs(Keyboard.PrimaryDevice, source, 0, Key.Escape)
            {
                RoutedEvent = Keyboard.PreviewKeyDownEvent,
            };
            win.RaiseEvent(args);

            Assert.True(args.Handled);
            Assert.False(win.IsElementDrawerOpen);
        });
    }

    [Fact]
    public void OpeningAPeakFile_DoesNotChangeTheDefault()
    {
        RunOnSta(() => WithTempSettings(_ =>
        {
            var panel = new AnalysisPanel();
            Assert.Equal("RMS", AppSettings.AcValueDisplay);

            // Dosyadan gelen ayar: ekranda tepe, ama varsayılan aynı kalır
            panel.RestoreAnalysisSettings(new CircuitDocument.AnalysisData { ValueDisplay = "PEAK" });
            Assert.Equal("PEAK", panel.ValueDisplay);
            Assert.Equal("RMS", AppSettings.AcValueDisplay);

            // Öğrencinin kendi seçimi varsayılan olur
            panel.SetValueDisplay("PEAK", notify: true);
            Assert.Equal("PEAK", AppSettings.AcValueDisplay);
        }));
    }

    [Fact]
    public void Settings_SameValueDoesNotRewriteTheFile()
    {
        WithTempSettings(path =>
        {
            AppSettings.AiDevice = "cpu";
            var old = new DateTime(2020, 1, 1, 0, 0, 0, DateTimeKind.Utc);
            File.SetLastWriteTimeUtc(path, old);

            AppSettings.AiDevice = "cpu";
            Assert.Equal(old, File.GetLastWriteTimeUtc(path));

            AppSettings.AiDevice = "gpu";
            Assert.NotEqual(old, File.GetLastWriteTimeUtc(path));
            Assert.False(File.Exists(path + ".tmp"));
        });
    }

    [Fact]
    public void Settings_LockedFileIsNotOverwrittenWithEmptySettings()
    {
        WithTempSettings(path =>
        {
            AppSettings.AiDevice = "cpu";
            AppSettings.AddRecentFile(@"C:\devre\odev.devre");
            string before = File.ReadAllText(path);

            using (new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
            {
                // Başka bir pencere o anda yazıyor: okunamayan dosyanın üstüne boş ayar yazılmamalı
                AppSettings.AiDevice = "gpu";
            }

            Assert.Equal(before, File.ReadAllText(path));
            Assert.Equal("cpu", AppSettings.AiDevice);
        });
    }
}
