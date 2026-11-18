using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using CircuitAnalyzer.WPF;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Program davranışı denetimi: tek kopya, pencere yerini hatırlama, çözücü hatası ve yeniden
/// deneme, büyük AC devre uyarısı, kurulum sorusu ve tanıtım metinleri.
/// Ayar dosyasına ve WPF'e dokunan testler (WpfUiCollection içinde, sırayla).
/// </summary>
[Collection(WpfUiCollection.Name)]
public class AppBehaviourTests
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

    private static string FindRepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir != null && !File.Exists(Path.Combine(dir.FullName, "CircuitAnalyzer.sln")))
            dir = dir.Parent;
        return dir?.FullName ?? throw new InvalidOperationException("CircuitAnalyzer.sln bulunamadı");
    }

    // ═══════════════════════════════════════════════════════
    //  2. PENCERE YERİ
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void Placement_RoundTripsThroughSettings_AndSkipsUnchangedWrites()
    {
        WithTempSettings(path =>
        {
            Assert.Null(AppSettings.MainWindowPlacement);

            AppSettings.MainWindowPlacement = new SavedWindowPlacement(100.4, 50, 1300, 820, Maximized: true);
            var read = AppSettings.MainWindowPlacement;
            Assert.Equal(new SavedWindowPlacement(100, 50, 1300, 820, true), read);

            // Aynı değer (yuvarlanınca aynı) yeniden yazılmaz
            var before = File.GetLastWriteTimeUtc(path);
            File.SetLastWriteTimeUtc(path, before.AddMinutes(-5));
            var stamp = File.GetLastWriteTimeUtc(path);
            AppSettings.MainWindowPlacement = new SavedWindowPlacement(100.2, 50, 1300, 820, true);
            Assert.Equal(stamp, File.GetLastWriteTimeUtc(path));

            // Başka ayarlar silinmez
            AppSettings.OnboardingCompleted = true;
            AppSettings.MainWindowPlacement = new SavedWindowPlacement(10, 10, 1000, 700, false);
            Assert.True(AppSettings.OnboardingCompleted);
        });
    }

    [Fact]
    public void Placement_BrokenOrNonNumberValues_ReadAsNull()
    {
        WithTempSettings(path =>
        {
            File.WriteAllText(path, "{\"MainWindowPlacement\": {\"Left\": \"abc\", \"Top\": 1}}");
            Assert.Null(AppSettings.MainWindowPlacement);

            AppSettings.MainWindowPlacement = new SavedWindowPlacement(double.NaN, 0, 100, 100, false);
            Assert.Null(AppSettings.MainWindowPlacement);
        });
    }

    [Fact]
    public void Placement_WindowsBuiltByTests_DoNotReadTheSettings()
    {
        // Testlerde App yok: pencere kullanıcının (burada geçici) kayıtlı yerine gitmemeli
        RunOnSta(() => WithTempSettings(_ =>
        {
            AppSettings.MainWindowPlacement = new SavedWindowPlacement(5, 5, 1500, 900, true);
            var win = new MainWindow();
            Assert.Equal(1280, win.Width);
            Assert.Equal(800, win.Height);
            Assert.Equal(WindowState.Normal, win.WindowState);
        }));
    }

    // ═══════════════════════════════════════════════════════
    //  3. ÇÖZÜCÜ HATASI: Yeniden dene düğmesi
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void ShowError_WithAction_AddsRetryButtonThatRunsOnce()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            int calls = 0;
            panel.ShowError("Çözücü kapandı", "metin", BackendMessages.RetryText, () => calls++);

            var button = panel.ErrorActionButton;
            Assert.NotNull(button);
            Assert.Equal("Yeniden dene", button!.Content);

            button.RaiseEvent(new RoutedEventArgs(ButtonBase.ClickEvent));
            Assert.Equal(1, calls);
            Assert.False(button.IsEnabled);   // ikinci tık ikinci bir başlatma yapmasın

            // Düz hata kartında düğme yok
            panel.ShowError("Devre çözülemedi", "metin");
            Assert.Null(panel.ErrorActionButton);
        });
    }

    // ═══════════════════════════════════════════════════════
    //  5. KURULUM / 6. TANITIM METİNLERİ
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void Installer_IsPerUser_WithoutTheAllUsersQuestion()
    {
        string iss = File.ReadAllText(Path.Combine(FindRepoRoot(), "installer", "DevreAnalizi.iss"));
        Assert.Contains("PrivilegesRequired=lowest", iss);
        Assert.DoesNotContain("PrivilegesRequiredOverridesAllowed=dialog", iss);

        string readme = File.ReadAllText(Path.Combine(FindRepoRoot(), "README.md"));
        Assert.Contains("yönetici izni istemez", readme);
    }

    [Fact]
    public void TourAndOnboarding_DoNotDescribeDragFromPalette()
    {
        foreach (var step in TourSteps.Steps)
            Assert.DoesNotContain("sürük", step.Body, StringComparison.OrdinalIgnoreCase);

        string xaml = File.ReadAllText(Path.Combine(FindRepoRoot(), "CircuitAnalyzer.WPF", "Views", "OnboardingView.xaml"));
        Assert.DoesNotContain("sürükleyip yerleştirin", xaml);

        // Elemanlar adımı gerçek akışı anlatır: listeden seç, tuvale tıklayıp bırak
        string first = TourSteps.Steps[0].Body;
        Assert.Contains("tıklayıp bırakın", first);
    }
}

/// <summary>Saf karar fonksiyonları ve WPF gerektirmeyen davranış testleri.</summary>
public class AppBehaviourPureTests
{
    // ═══════════════════════════════════════════════════════
    //  1. TEK KOPYA
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void FindFileArgument_PicksTheFirstCircuitFile()
    {
        Func<string, bool> exists = p => p == "var-olan.txt";
        Assert.Equal("a.devre", StartupArgs.FindFileArgument(new[] { "--theme", "dark", "a.devre" }, exists));
        Assert.Equal("var-olan.txt", StartupArgs.FindFileArgument(new[] { "var-olan.txt", "b.devre" }, exists));
        Assert.Null(StartupArgs.FindFileArgument(new[] { "--software-render" }, exists));
        Assert.Null(StartupArgs.FindFileArgument(Array.Empty<string>(), exists));
        Assert.Null(StartupArgs.FindFileArgument(new[] { "--x.devre", " " }, exists));
    }

    [Fact]
    public void SelfTestModes_DoNotTakePartInSingleInstance()
    {
        // App.OnStartup tek kopya düzenini HasAnySelfTest true iken hiç kurmaz
        Assert.True(MainWindow.HasAnySelfTest(new[] { "--selftest", "0", "x.png" }));
        Assert.True(MainWindow.HasAnySelfTest(new[] { "--tour-shot", "1", "x.png" }));
        Assert.False(MainWindow.HasAnySelfTest(new[] { "devre.devre" }));
    }

    [Fact]
    public void ForwardedFile_WaitsWhileAnythingModalIsOpen()
    {
        Assert.False(MainWindow.ShouldDeferForwardedFile(false, false, false, false, windowEnabled: true));
        Assert.True(MainWindow.ShouldDeferForwardedFile(openingAlready: true, false, false, false, true));
        Assert.True(MainWindow.ShouldDeferForwardedFile(false, questionOpen: true, false, false, true));   // kaydet sorusu
        Assert.True(MainWindow.ShouldDeferForwardedFile(false, false, cardOpen: true, false, true));       // tanıtım, Hakkında
        Assert.True(MainWindow.ShouldDeferForwardedFile(false, false, false, ownedWindowOpen: true, true)); // eleman düzenleyici
        Assert.True(MainWindow.ShouldDeferForwardedFile(false, false, false, false, windowEnabled: false)); // Aç/Kaydet penceresi
    }

    [Fact]
    public void Message_RoundTripsAndRejectsForeignData()
    {
        string full = Path.Combine(Path.GetTempPath(), "Ödev 1.devre");
        Assert.True(SingleInstance.TryDecodeMessage(SingleInstance.EncodeMessage(full), out var path));
        Assert.Equal(full, path);

        Assert.True(SingleInstance.TryDecodeMessage(SingleInstance.EncodeMessage(null), out path));
        Assert.Null(path);

        Assert.False(SingleInstance.TryDecodeMessage("merhaba\nC:\\a.devre", out _));
        Assert.False(SingleInstance.TryDecodeMessage(null, out _));
        // Göreli yol gönderenin klasörüne göredir: kabul edilmez
        Assert.False(SingleInstance.TryDecodeMessage(SingleInstance.EncodeMessage("a.devre"), out _));
        Assert.False(SingleInstance.TryDecodeMessage(SingleInstance.MessageHeader + "\nC:\\a\nC:\\b", out _));
    }

    [Fact]
    public void Names_AreScopedToUserAndSession()
    {
        string a = SingleInstance.BaseNameFor("S-1-5-21-1-2-3-1001", 1);
        string b = SingleInstance.BaseNameFor("S-1-5-21-1-2-3-1002", 1);
        string c = SingleInstance.BaseNameFor("S-1-5-21-1-2-3-1001", 2);
        Assert.NotEqual(a, b);
        Assert.NotEqual(a, c);
        Assert.StartsWith(@"Local\", SingleInstance.MutexNameFor(a));
        Assert.DoesNotContain('\\', SingleInstance.PipeNameFor(SingleInstance.BaseNameFor(@"a\b", 1)));
    }

    private static string TestBaseName() => "DevreAnaliziTest-" + Guid.NewGuid().ToString("N");

    /// <summary>
    /// Mutex iş parçacığına bağlıdır (aynı iş parçacığı onu yeniden alabilir): ikinci kopyayı
    /// her zaman ayrı, yeni bir iş parçacığında taklit et.
    /// </summary>
    private static Task<T> OnNewThread<T>(Func<T> func)
    {
        var tcs = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
        var t = new Thread(() =>
        {
            try { tcs.SetResult(func()); }
            catch (Exception ex) { tcs.SetException(ex); }
        }) { IsBackground = true };
        t.Start();
        return tcs.Task;
    }

    [Fact]
    public async Task SecondLaunch_ForwardsTheFileToTheFirst()
    {
        string name = TestBaseName();
        var (primary, forwarded) = SingleInstance.Acquire(name, null, TimeSpan.FromSeconds(2));
        Assert.NotNull(primary);
        Assert.False(forwarded);
        try
        {
            var received = new TaskCompletionSource<string?>(TaskCreationOptions.RunContinuationsAsynchronously);
            primary!.StartListening(p => received.TrySetResult(p));

            string file = Path.Combine(Path.GetTempPath(), "ikinci.devre");
            var second = await OnNewThread(() => SingleInstance.Acquire(name, file, TimeSpan.FromSeconds(5)));
            Assert.Null(second.Primary);
            Assert.True(second.Forwarded);

            var done = await Task.WhenAny(received.Task, Task.Delay(5000));
            Assert.Same(received.Task, done);
            Assert.Equal(file, await received.Task);
        }
        finally
        {
            primary!.Dispose();
        }
    }

    [Fact]
    public async Task SecondLaunch_WhileFirstIsStillStarting_WaitsForItsPipe()
    {
        string name = TestBaseName();
        var (primary, _) = SingleInstance.Acquire(name, null, TimeSpan.FromSeconds(2));
        Assert.NotNull(primary);
        try
        {
            var received = new TaskCompletionSource<string?>(TaskCreationOptions.RunContinuationsAsynchronously);
            // İkinci kopya, ilk kopya kanalı açmadan önce başlıyor
            var secondTask = OnNewThread(() => SingleInstance.Acquire(name, null, TimeSpan.FromSeconds(6)));
            await Task.Delay(800);
            primary!.StartListening(p => received.TrySetResult(p));

            var second = await secondTask;
            Assert.True(second.Forwarded);
            var done = await Task.WhenAny(received.Task, Task.Delay(5000));
            Assert.Same(received.Task, done);
            Assert.Null(await received.Task);   // dosyasız açılış: yalnız öne gel
        }
        finally
        {
            primary!.Dispose();
        }
    }

    [Fact]
    public void AbandonedMutex_FromACrashedInstance_IsTakenOver()
    {
        string name = TestBaseName();
        Mutex? leaked = null;
        // Mutex'i alıp bırakmadan biten iş parçacığı = çöken kopya
        var crashed = new Thread(() => { leaked = new Mutex(true, SingleInstance.MutexNameFor(name), out _); });
        crashed.Start();
        crashed.Join();
        try
        {
            var (primary, forwarded) = SingleInstance.Acquire(name, null, TimeSpan.FromSeconds(2));
            Assert.NotNull(primary);
            Assert.False(forwarded);
            primary!.Dispose();
        }
        finally
        {
            leaked?.Dispose();
        }
    }

    [Fact]
    public void FirstInstanceThatNeverAnswers_DoesNotBlockForever()
    {
        string name = TestBaseName();
        Mutex? held = null;
        var holderReady = new ManualResetEventSlim();
        var release = new ManualResetEventSlim();
        var holder = new Thread(() =>
        {
            held = new Mutex(true, SingleInstance.MutexNameFor(name), out _);
            holderReady.Set();
            release.Wait();
            held.ReleaseMutex();
            held.Dispose();
        });
        holder.Start();
        holderReady.Wait();
        try
        {
            var sw = Stopwatch.StartNew();
            var (primary, forwarded) = SingleInstance.Acquire(name, null, TimeSpan.FromSeconds(1.5));
            Assert.Null(primary);
            Assert.False(forwarded);   // normal açılır (tek kopya düzeni olmadan)
            Assert.True(sw.Elapsed < TimeSpan.FromSeconds(6));
        }
        finally
        {
            release.Set();
            holder.Join();
        }
    }

    // ═══════════════════════════════════════════════════════
    //  2. PENCERE YERİ: ekrana sığdırma
    // ═══════════════════════════════════════════════════════

    private static readonly IReadOnlyList<Rect> OneScreen = new[] { new Rect(0, 0, 1920, 1040) };
    private static readonly IReadOnlyList<Rect> TwoScreens = new[] { new Rect(0, 0, 1920, 1040), new Rect(1920, 0, 1280, 984) };

    [Fact]
    public void Fit_KeepsAUsableRectangleAsIs()
    {
        Assert.Equal(new Rect(100, 80, 1280, 800), WindowPlacementRules.Fit(100, 80, 1280, 800, OneScreen, 960, 600));
        Assert.Equal(new Rect(2000, 50, 1000, 700), WindowPlacementRules.Fit(2000, 50, 1000, 700, TwoScreens, 960, 600));
    }

    [Theory]
    [InlineData(double.NaN, 0, 1280, 800)]
    [InlineData(0, double.PositiveInfinity, 1280, 800)]
    [InlineData(0, 0, 0, 800)]
    [InlineData(0, 0, 1280, -5)]
    [InlineData(5000, 100, 1280, 800)]      // ikinci monitör çıkarıldı
    [InlineData(-3000, -2000, 1280, 800)]   // tamamen ekran dışında
    [InlineData(100, 1100, 1280, 800)]      // başlık çubuğu ekranın altında
    [InlineData(1850, 100, 1280, 800)]      // başlığın yalnız 70 px'i görünüyor
    public void Fit_RejectsUnusableRectangles(double left, double top, double width, double height)
    {
        Assert.Null(WindowPlacementRules.Fit(left, top, width, height, OneScreen, 960, 600));
    }

    [Fact]
    public void Fit_PartlyOffScreen_IsMovedInside()
    {
        var r = WindowPlacementRules.Fit(1200, -20, 1280, 800, OneScreen, 960, 600);
        Assert.Equal(new Rect(640, 0, 1280, 800), r);
    }

    [Fact]
    public void Fit_LargerThanTheScreen_IsShrunk()
    {
        // Çözünürlük düştü: 2560x1400'lük pencere 1366x728'lik ekrana
        var small = new[] { new Rect(0, 0, 1366, 728) };
        var r = WindowPlacementRules.Fit(0, 0, 2560, 1400, small, 960, 600);
        Assert.Equal(new Rect(0, 0, 1366, 728), r);
    }

    [Fact]
    public void Fit_SmallerThanMinimum_IsGrown_AndNoScreensMeansDefault()
    {
        Assert.Equal(new Rect(10, 10, 960, 600), WindowPlacementRules.Fit(10, 10, 300, 200, OneScreen, 960, 600));
        Assert.Null(WindowPlacementRules.Fit(10, 10, 1280, 800, Array.Empty<Rect>(), 960, 600));
    }

    // ═══════════════════════════════════════════════════════
    //  3. ÇÖZÜCÜ HATA METİNLERİ
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void BackendMessages_MentionPythonOnlyInADeveloperRun()
    {
        foreach (BackendFailure failure in Enum.GetValues<BackendFailure>())
        {
            var (title, text) = BackendMessages.Describe(failure, developerRun: false,
                detail: "Çözücü çıktısı: Traceback ... ModuleNotFoundError");
            Assert.False(string.IsNullOrWhiteSpace(title));
            Assert.DoesNotContain("Python", text, StringComparison.OrdinalIgnoreCase);
            Assert.DoesNotContain("PATH", text);
            Assert.DoesNotContain("Traceback", text);        // ayrıntı yalnız geliştiriciye
            Assert.DoesNotContain(".exe", text);
            Assert.DoesNotContain("backend", text, StringComparison.OrdinalIgnoreCase);
        }

        var (_, dev) = BackendMessages.Describe(BackendFailure.CouldNotStart, developerRun: true, detail: "Sistem dosyayı bulamıyor");
        Assert.Contains("Python kurulu", dev);
        Assert.Contains("Sistem dosyayı bulamıyor", dev);
    }

    [Fact]
    public void BackendMessages_DistinguishTheCases()
    {
        var titles = new[] { BackendFailure.Missing, BackendFailure.NotReady, BackendFailure.Stopped, BackendFailure.Timeout }
            .Select(f => BackendMessages.Describe(f, developerRun: false).Title)
            .ToList();
        Assert.Equal(titles.Count, titles.Distinct().Count());
        Assert.Contains("yeniden kur", BackendMessages.Describe(BackendFailure.Missing, false).Text);
        Assert.Contains("kapandı", BackendMessages.Describe(BackendFailure.Stopped, false).Text);
    }

    // ═══════════════════════════════════════════════════════
    //  4. BÜYÜK AC DEVRE UYARISI
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void LargeCircuitWarning_OnlyForBigAcCircuits()
    {
        int n = LargeCircuitCheck.LargeAcElementCount;
        Assert.Equal(85, n);
        Assert.True(LargeCircuitCheck.ShouldWarn(n, AnalysisModes.AcPhasor));
        Assert.True(LargeCircuitCheck.ShouldWarn(200, AnalysisModes.AcPhasor));
        Assert.False(LargeCircuitCheck.ShouldWarn(n - 1, AnalysisModes.AcPhasor));
        Assert.False(LargeCircuitCheck.ShouldWarn(500, AnalysisModes.Dc));   // DC etkilenmez

        Assert.Contains("iki dakika", LargeCircuitCheck.WarningText(90));
        Assert.Contains("90", LargeCircuitCheck.WarningText(90));
        Assert.Contains("1:05", LargeCircuitCheck.BusyText(TimeSpan.FromSeconds(65)));
    }
}

/// <summary>Gerçek çözücüyle: yeniden başlatma iki süreç bırakmaz, kapanan çözücü hemen fark edilir.</summary>
[Collection(RealProcessCollection.Name)]
public class BackendRestartTests
{
    [Fact]
    public async Task Restart_ReplacesTheProcess_AndAStoppedSolverIsNoticedAtOnce()
    {
        using var manager = new BackendManager();
        await manager.StartAsync();
        int firstPid = manager.ProcessId!.Value;
        Assert.True(manager.IsAlive);

        // Aynı anda iki "Yeniden dene": tek başlatma
        var a = manager.StartAsync();
        var b = manager.StartAsync();
        Assert.Same(a, b);
        var client = await a;
        int secondPid = manager.ProcessId!.Value;
        Assert.NotEqual(firstPid, secondPid);
        Assert.True(ProcessHasExited(firstPid), "eski çözücü hâlâ çalışıyor");
        Assert.NotNull(await client.TryGetHealthAsync());

        // Çözücü dışarıdan kapanırsa: belirteç hemen iptal, IsAlive false
        var token = manager.StoppedToken;
        Process.GetProcessById(secondPid).Kill(entireProcessTree: true);
        var sw = Stopwatch.StartNew();
        while (!token.IsCancellationRequested && sw.Elapsed < TimeSpan.FromSeconds(10))
            await Task.Delay(50);
        Assert.True(token.IsCancellationRequested);
        Assert.False(manager.IsAlive);
        Assert.True(sw.Elapsed < TimeSpan.FromSeconds(10));
    }

    private static bool ProcessHasExited(int pid)
    {
        try
        {
            using var p = Process.GetProcessById(pid);
            return p.WaitForExit(5000);
        }
        catch (ArgumentException)
        {
            return true;   // artık yok
        }
    }
}
