using System;
using System.Collections.Generic;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

[Collection(WpfUiCollection.Name)]
public class AnalysisPanelTests : IClassFixture<BackendFixture>
{
    private readonly BackendFixture _fx;

    public AnalysisPanelTests(BackendFixture fx)
    {
        _fx = fx;
    }

    private static void RunOnSta(Action action)
    {
        Exception? ex = null;
        var thread = new Thread(() =>
        {
            try
            {
                action();
            }
            catch (Exception e)
            {
                ex = e;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();

        if (ex != null)
        {
            ExceptionDispatchInfo.Capture(ex).Throw();
        }
    }

    private static List<string> GetAllTexts(DependencyObject root)
    {
        var list = new List<string>();
        var visited = new HashSet<DependencyObject>();

        void Collect(DependencyObject obj)
        {
            if (!visited.Add(obj)) return;

            if (obj is TextBlock tb && !string.IsNullOrEmpty(tb.Text))
                list.Add(tb.Text);
            else if (obj is TextBox txt && !string.IsNullOrEmpty(txt.Text))
                list.Add(txt.Text);
            else if (obj is Button btn && btn.Content is string bs)
                list.Add(bs);
            else if (obj is HeaderedContentControl hcc && hcc.Header is string hs)
                list.Add(hs);

            if (obj is Visual || obj is System.Windows.Media.Media3D.Visual3D)
            {
                int visualCount = VisualTreeHelper.GetChildrenCount(obj);
                for (int i = 0; i < visualCount; i++)
                {
                    Collect(VisualTreeHelper.GetChild(obj, i));
                }
            }

            foreach (var child in LogicalTreeHelper.GetChildren(obj))
            {
                if (child is DependencyObject dChild)
                {
                    Collect(dChild);
                }
            }
        }

        Collect(root);
        return list;
    }

    private static AnalysisRequestDto BuildRequest(
        TestCircuits c,
        string mode,
        double? frequency = null,
        string type = AnalysisTypes.Nodal,
        TerminalsDto? terminals = null) =>
        new()
        {
            Netlist = NetlistBuilder.Build(c.Elements, c.Wires).Text,
            Mode = mode,
            Frequency = frequency,
            AnalysisType = type,
            TheveninTerminals = terminals,
        };

    [Fact]
    public void TryGetOptions_NodalDefault_Succeeds()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            bool ok = panel.TryGetOptions(out var opt, out var err);

            Assert.True(ok);
            Assert.Null(err);
            Assert.NotNull(opt);
            Assert.Equal(AnalysisTypes.Nodal, opt!.AnalysisType);
            Assert.Null(opt.Frequency);
            Assert.Null(opt.TerminalPositive);
            Assert.Equal("0", opt.TerminalNegative);
        });
    }

    [Fact]
    public void TryGetOptions_Thevenin_WithoutPositiveTerminal_Fails()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAnalysisType(AnalysisTypes.Thevenin);

            bool ok = panel.TryGetOptions(out var opt, out var err);
            Assert.False(ok);
            Assert.Null(opt);
            Assert.NotNull(err);
            Assert.Contains("+ terminal", err!);
        });
    }

    [Fact]
    public void TryGetOptions_Thevenin_SameTerminals_Fails()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAnalysisType(AnalysisTypes.Thevenin);
            panel.SetAvailableNodes(new[] { 0, 1, 2 });
            panel.CmbTerminalPositive.SelectedItem = "1";
            panel.CmbTerminalNegative.SelectedItem = "1";

            bool ok = panel.TryGetOptions(out var opt, out var err);
            Assert.False(ok);
            Assert.Null(opt);
            Assert.NotNull(err);
            Assert.Contains("aynı olamaz", err!);
        });
    }

    [Theory]
    [InlineData("50", 50.0)]
    [InlineData("50.5", 50.5)]
    [InlineData("50,5", 50.5)]
    [InlineData("1k", 1000.0)]
    [InlineData("2.5k", 2500.0)]
    public void TryGetOptions_FrequencyParsing_ValidValues(string input, double expected)
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetCircuitInfo(hasAcSource: true, needsFrequency: false);
            panel.TxtFrequency.Text = input;

            bool ok = panel.TryGetOptions(out var opt, out var err);
            Assert.True(ok);
            Assert.Null(err);
            Assert.NotNull(opt);
            Assert.Equal(expected, opt!.Frequency);
        });
    }

    [Theory]
    [InlineData("-3", "Frekans pozitif bir sayı olmalı")]
    [InlineData("0", "Frekans pozitif bir sayı olmalı")]
    [InlineData("abc", null)]
    public void TryGetOptions_FrequencyParsing_InvalidValues(string input, string? expectedError)
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetCircuitInfo(hasAcSource: true, needsFrequency: false);
            panel.TxtFrequency.Text = input;

            bool ok = panel.TryGetOptions(out var opt, out var err);
            Assert.False(ok);
            Assert.Null(opt);
            Assert.NotNull(err);
            if (expectedError != null)
            {
                Assert.Equal(expectedError, err);
            }
        });
    }

    [Fact]
    public void TryGetOptions_NeedsFrequency_EmptyFails()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetCircuitInfo(hasAcSource: true, needsFrequency: true);
            panel.TxtFrequency.Text = "";

            bool ok = panel.TryGetOptions(out var opt, out var err);
            Assert.False(ok);
            Assert.Null(opt);
            Assert.NotNull(err);
        });
    }

    [Fact]
    public void TryGetOptions_DcCircuit_IgnoresFrequencyBox()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetCircuitInfo(hasAcSource: false, needsFrequency: false);
            panel.TxtFrequency.Text = "1k";

            bool ok = panel.TryGetOptions(out var opt, out var err);
            Assert.True(ok);
            Assert.Null(err);
            Assert.NotNull(opt);
            Assert.Null(opt!.Frequency);
        });
    }

    [Fact]
    public void SetAvailableNodes_KeepsValidSelection_AndDefaultsNegativeToZero()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAvailableNodes(new[] { 0, 1, 2, 3 });
            Assert.Equal("0", panel.CmbTerminalNegative.SelectedItem);

            panel.CmbTerminalPositive.SelectedItem = "2";
            panel.CmbTerminalNegative.SelectedItem = "1";

            // Girdi listesinde hâlâ varsa koru
            panel.SetAvailableNodes(new[] { 0, 1, 2 });
            Assert.Equal("2", panel.CmbTerminalPositive.SelectedItem);
            Assert.Equal("1", panel.CmbTerminalNegative.SelectedItem);

            // Pozitif kaldırıldıysa temizle, negatif 0'a dönsün
            panel.SetAvailableNodes(new[] { 0, 3 });
            Assert.Null(panel.CmbTerminalPositive.SelectedItem);
            Assert.Equal("0", panel.CmbTerminalNegative.SelectedItem);
        });
    }

    [Fact]
    public void SetAnalysisType_Thevenin_SelectsPositiveAndNegativeTerminals()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAvailableNodes(new[] { 0, 1, 2, 3 });
            panel.SetAnalysisType(AnalysisTypes.Thevenin, "3");

            bool ok = panel.TryGetOptions(out var opt, out var err);
            Assert.True(ok);
            Assert.Null(err);
            Assert.NotNull(opt);
            Assert.Equal(AnalysisTypes.Thevenin, opt!.AnalysisType);
            Assert.Equal("3", opt.TerminalPositive);
            Assert.Equal("0", opt.TerminalNegative);
        });
    }

    [Fact]
    public void SolveButton_StateTransitions_WithBackendAndBusy()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            // Başlangıçta Starting -> Buton pasif
            Assert.False(panel.BtnSolve.IsEnabled);

            panel.SetBackendStatus(BackendState.Ready, "Hazır");
            Assert.True(panel.BtnSolve.IsEnabled);

            panel.SetBusy(true);
            Assert.False(panel.BtnSolve.IsEnabled);
            Assert.Equal("Çözülüyor…", panel.TxtSolve.Text);

            panel.SetBusy(false);
            Assert.True(panel.BtnSolve.IsEnabled);
            Assert.Equal("Çöz", panel.TxtSolve.Text);

            panel.SetBackendStatus(BackendState.Failed, "Bağlantı kesildi");
            Assert.False(panel.BtnSolve.IsEnabled);
        });
    }

    [Fact]
    public void SolveRequested_EventFires_WhenReadyAndNotBusy()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            int calls = 0;
            panel.SolveRequested += (_, _) => calls++;

            // Ready olmadan çağrı event üretmez
            panel.RequestSolve();
            Assert.Equal(0, calls);

            panel.SetBackendStatus(BackendState.Ready, "Hazır");
            panel.RequestSolve();
            Assert.Equal(1, calls);

            panel.SetBusy(true);
            panel.RequestSolve();
            Assert.Equal(1, calls);
        });
    }

    [Fact]
    public void MarkStale_ClearResults_ShowError_DoNotThrow()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();

            panel.MarkStale();
            Assert.Equal(0.45, panel.ResultsScrollViewer.Opacity);
            Assert.Equal(Visibility.Visible, panel.BannerStale.Visibility);

            panel.ClearResults();
            Assert.Equal(1.0, panel.ResultsScrollViewer.Opacity);
            Assert.Equal(Visibility.Collapsed, panel.BannerStale.Visibility);
            Assert.Empty(panel.ResultsContainer.Children);

            panel.ShowError("Kritik Hata", "Python sunucusu yanıt vermedi");
            Assert.Single(panel.ResultsContainer.Children);

            panel.Measure(new Size(400, 1000));
            panel.Arrange(new Rect(0, 0, 400, 1000));
            panel.UpdateLayout();

            var texts = GetAllTexts(panel);
            Assert.Contains(texts, t => t.Contains("Kritik Hata"));
            Assert.Contains(texts, t => t.Contains("Python sunucusu yanıt vermedi"));
        });
    }

    [Fact]
    public async Task RealSolver_DcDivider_Nodal_RendersCorrectly()
    {
        var resp = await _fx.Client.AnalyzeAsync(
            BuildRequest(TestCircuits.DcDivider(), AnalysisModes.Dc, type: AnalysisTypes.Nodal));

        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.ShowResults(resp);

            panel.Measure(new Size(400, 2000));
            panel.Arrange(new Rect(0, 0, 400, 2000));
            panel.UpdateLayout();

            var texts = GetAllTexts(panel);
            Assert.Contains(texts, t => t.Contains("8 V"));
            Assert.Contains(texts, t => t.Contains("Çözüm başarılı"));
            Assert.Contains(texts, t => t.Contains("Düğüm gerilimleri"));
            Assert.Contains(texts, t => t.Contains("Eleman akımları"));
            Assert.Contains(texts, t => t.Contains("Güç analizi"));
        });
    }

    [Fact]
    public async Task RealSolver_AcRc_RendersCorrectly()
    {
        var resp = await _fx.Client.AnalyzeAsync(
            BuildRequest(TestCircuits.AcRcLowPass(), AnalysisModes.AcPhasor, frequency: 50));

        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.ShowResults(resp);

            panel.Measure(new Size(400, 2000));
            panel.Arrange(new Rect(0, 0, 400, 2000));
            panel.UpdateLayout();

            var texts = GetAllTexts(panel);
            Assert.Contains(texts, t => t.Contains("Çözüm başarılı"));
            Assert.Contains(texts, t => t.Contains("Düğüm gerilimleri"));
            Assert.Contains(texts, t => t.Contains("Güç analizi"));
        });
    }

    [Fact]
    public async Task RealSolver_DcDivider_Thevenin_RendersCorrectly()
    {
        var term = new TerminalsDto { NodePositive = "2", NodeNegative = "0" };
        var resp = await _fx.Client.AnalyzeAsync(
            BuildRequest(TestCircuits.DcDivider(), AnalysisModes.Dc, type: AnalysisTypes.Thevenin, terminals: term));

        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.ShowResults(resp);

            panel.Measure(new Size(400, 2000));
            panel.Arrange(new Rect(0, 0, 400, 2000));
            panel.UpdateLayout();

            var texts = GetAllTexts(panel);
            Assert.Contains(texts, t => t.Contains("Vth"));
            Assert.Contains(texts, t => t.Contains("Zth"));
            Assert.Contains(texts, t => t.Contains("Thevenin Eşdeğeri"));
        });
    }

    [Fact]
    public async Task RealSolver_DcDivider_Norton_RendersCorrectly()
    {
        var term = new TerminalsDto { NodePositive = "2", NodeNegative = "0" };
        var resp = await _fx.Client.AnalyzeAsync(
            BuildRequest(TestCircuits.DcDivider(), AnalysisModes.Dc, type: AnalysisTypes.Norton, terminals: term));

        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.ShowResults(resp);

            panel.Measure(new Size(400, 2000));
            panel.Arrange(new Rect(0, 0, 400, 2000));
            panel.UpdateLayout();

            var texts = GetAllTexts(panel);
            Assert.Contains(texts, t => t.Contains("In =") || t.Contains("In"));
            Assert.Contains(texts, t => t.Contains("Norton Eşdeğeri"));
        });
    }

    [Fact]
    public async Task RealSolver_WarningResponse_RendersMessage()
    {
        var resp = await _fx.Client.AnalyzeAsync(
            BuildRequest(TestCircuits.AcRcLowPass(), AnalysisModes.AcPhasor, frequency: null));

        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.ShowResults(resp);

            panel.Measure(new Size(400, 2000));
            panel.Arrange(new Rect(0, 0, 400, 2000));
            panel.UpdateLayout();

            var texts = GetAllTexts(panel);
            Assert.Contains(texts, t => t.Contains("Uyarılarla çözüldü") || t.Contains("frekans"));
        });
    }
}
