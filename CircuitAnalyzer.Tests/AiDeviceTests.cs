using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Threading;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>Yapay zekânın çalıştığı yer: Otomatik / Ekran kartı / İşlemci / NPU.</summary>
[Collection(WpfUiCollection.Name)]
public class AiDeviceTests
{
    private static LlmStatusDto Status(bool npu = true, bool gpuRestart = false, string auto = AiDeviceIds.Npu,
                                       string? placement = null) => new()
    {
        Available = true,
        Models = new List<string> { "gemma4:e4b" },
        SelectedModel = "gemma4:e4b",
        AutoDevice = auto,
        Placement = placement,
        GpuNeedsRestart = gpuRestart,
        DeviceOptions = new List<LlmDeviceOptionDto>
        {
            new() { Id = "auto", Label = "Otomatik", Available = true, Note = "En hızlısını seçer." },
            new() { Id = "gpu", Label = "Ekran kartı", Available = true, Note = "Radeon 860M" },
            new() { Id = "cpu", Label = "İşlemci", Available = true, Note = "Her bilgisayarda çalışır." },
            new() { Id = "npu", Label = "NPU", Available = npu, Note = npu ? "FastFlowLM ile." : "Bu bilgisayarda uygun NPU yok." },
        },
    };

    private static void RunOnSta(Action action)
    {
        Exception? ex = null;
        var thread = new Thread(() =>
        {
            try { action(); }
            catch (Exception e) { ex = e; }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        if (ex != null) ExceptionDispatchInfo.Capture(ex).Throw();
    }

    private static void RunAsync(Func<Task> f)
    {
        var task = f();
        if (!task.IsCompleted)
        {
            var frame = new DispatcherFrame();
            task.ContinueWith(_ => frame.Continue = false);
            Dispatcher.PushFrame(frame);
        }
        task.GetAwaiter().GetResult();
    }

    /// <summary>Ayar dosyasını geçici bir yere alıp testi çalıştırır.</summary>
    private static void WithTempSettings(string? savedDevice, Action action)
    {
        string original = AppSettings.SettingsPath;
        string temp = Path.Combine(Path.GetTempPath(), $"ai-device-{Guid.NewGuid():N}.json");
        try
        {
            AppSettings.SettingsPath = temp;
            if (savedDevice != null) AppSettings.AiDevice = savedDevice;
            action();
        }
        finally
        {
            AppSettings.SettingsPath = original;
            if (File.Exists(temp)) File.Delete(temp);
        }
    }

    [Fact]
    public void Items_ShowAutoChoiceAndKeepUnavailableOptions()
    {
        var items = AiDevices.Items(Status(npu: false, auto: AiDeviceIds.Cpu));
        Assert.Equal(new[] { "auto", "gpu", "cpu", "npu" }, items.Select(i => i.Id));
        Assert.Equal("Otomatik (işlemci)", items[0].Display);
        Assert.False(items[3].Available);
        Assert.Contains("NPU yok", items[3].Note);
    }

    [Fact]
    public void Items_OldSolverWithoutOptions_OnlyAuto()
    {
        var items = AiDevices.Items(new LlmStatusDto { Available = true });
        Assert.Single(items);
        Assert.Equal(AiDeviceIds.Auto, items[0].Id);
    }

    [Fact]
    public void Pick_FallsBackToAutoWhenSavedChoiceIsUnavailable()
    {
        var items = AiDevices.Items(Status(npu: false));
        Assert.Equal(AiDeviceIds.Auto, AiDevices.Pick(items, AiDeviceIds.Npu).Id);
        Assert.Equal(AiDeviceIds.Cpu, AiDevices.Pick(items, AiDeviceIds.Cpu).Id);
        Assert.Equal(AiDeviceIds.Auto, AiDevices.Pick(items, null).Id);
    }

    [Fact]
    public void BusyTextAndPlacementFollowTheDevice()
    {
        Assert.Contains("NPU", AiDevices.BusyText(AiDevices.Effective(AiDeviceIds.Auto, Status())));
        Assert.Contains("işlemcide", AiDevices.BusyText(AiDeviceIds.Cpu));
        Assert.Contains("ekran kartında", AiDevices.BusyText(AiDeviceIds.Gpu));
        Assert.Null(AiDevices.PlacementLine(null));
        Assert.Equal("Şu an: ekran kartında", AiDevices.PlacementLine("ekran kartında"));
        Assert.Equal("NPU'da", AiDevices.PlacementFromAnswer(new LlmAnswerDto { Device = "npu" }));
        Assert.True(AiDevices.IsMismatch(AiDeviceIds.Gpu, "işlemcide"));
        Assert.False(AiDevices.IsMismatch(AiDeviceIds.Cpu, "işlemcide"));
    }

    [Fact]
    public void View_RestoresSavedChoiceAndSendsItWithTheQuestion()
    {
        RunOnSta(() => WithTempSettings(AiDeviceIds.Cpu, () =>
        {
            LlmAskRequestDto? sent = null;
            var view = new AssistantView
            {
                StatusProvider = _ => Task.FromResult<LlmStatusDto?>(Status(placement: "işlemcide")),
                Asker = (req, _) =>
                {
                    sent = req;
                    return Task.FromResult(new LlmAnswerDto { Answer = "V2 = 8 V", Device = "cpu", Placement = "işlemcide" });
                },
            };
            view.Configure(new AnalysisRequestDto { Netlist = "R1 1 0 100" }, false, Array.Empty<PracticeQuestionDto>());
            RunAsync(view.RefreshStatusAsync);

            Assert.Equal(AiDeviceIds.Cpu, view.SelectedDevice);
            Assert.Equal("Şu an: işlemcide", view.PlacementText);

            RunAsync(() => view.AskAsync("Soru?"));
            Assert.NotNull(sent);
            Assert.Equal(AiDeviceIds.Cpu, sent!.Device);
        }));
    }

    [Fact]
    public void View_ChoosingGpuOnIntegratedCard_AsksToRestartAndSavesChoice()
    {
        RunOnSta(() => WithTempSettings(null, () =>
        {
            bool restarted = false;
            var view = new AssistantView
            {
                StatusProvider = _ => Task.FromResult<LlmStatusDto?>(Status(gpuRestart: !restarted)),
                EnableGpu = _ => { restarted = true; return Task.FromResult(true); },
            };
            view.Configure(new AnalysisRequestDto { Netlist = "R1 1 0 100" }, false, Array.Empty<PracticeQuestionDto>());
            RunAsync(view.RefreshStatusAsync);
            Assert.Equal(AiDeviceIds.Auto, view.SelectedDevice);
            Assert.False(view.IsGpuRestartShown);

            var cmb = (System.Windows.Controls.ComboBox)view.FindName("CmbDevice");
            cmb.SelectedItem = ((IReadOnlyList<AiDeviceItem>)cmb.ItemsSource).First(i => i.Id == AiDeviceIds.Gpu);
            Assert.True(view.IsGpuRestartShown);
            Assert.Equal(AiDeviceIds.Gpu, AppSettings.AiDevice);

            // "Vazgeç": Otomatik'e döner, soru kapanır
            var cancel = (System.Windows.Controls.Button)view.FindName("BtnGpuCancel");
            cancel.RaiseEvent(new RoutedEventArgs(System.Windows.Controls.Primitives.ButtonBase.ClickEvent));
            Assert.Equal(AiDeviceIds.Auto, view.SelectedDevice);
            Assert.False(view.IsGpuRestartShown);
        }));
    }

    [Fact]
    public void View_UnavailableNpuCannotBeRestoredFromSettings()
    {
        RunOnSta(() => WithTempSettings(AiDeviceIds.Npu, () =>
        {
            var view = new AssistantView
            {
                StatusProvider = _ => Task.FromResult<LlmStatusDto?>(Status(npu: false, auto: AiDeviceIds.Cpu)),
            };
            view.Configure(new AnalysisRequestDto { Netlist = "R1 1 0 100" }, false, Array.Empty<PracticeQuestionDto>());
            RunAsync(view.RefreshStatusAsync);
            Assert.Equal(AiDeviceIds.Auto, view.SelectedDevice);
            Assert.Equal(AiDeviceIds.Npu, AppSettings.AiDevice);   // kayıt bozulmaz; NPU gelince geri seçilir
        }));
    }
}
