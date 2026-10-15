using System;
using System.Collections.Generic;
using System.Linq;
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
public class ExplanationViewTests : IClassFixture<BackendFixture>
{
    private readonly BackendFixture _fx;

    public ExplanationViewTests(BackendFixture fx)
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
    public async Task Dto_DcDivider_HasExpectedExplanationSectionsAndBlocks()
    {
        var resp = await _fx.Client.AnalyzeAsync(
            BuildRequest(TestCircuits.DcDivider(), AnalysisModes.Dc, type: AnalysisTypes.Nodal));

        Assert.NotNull(resp);
        Assert.NotNull(resp.Results);
        Assert.NotNull(resp.Results.Explanation);
        Assert.NotEmpty(resp.Results.Explanation);

        Assert.Equal("Devreyi Tanıyalım", resp.Results.Explanation[0].Title);

        bool hasExpectedResultBlock = resp.Results.Explanation
            .SelectMany(s => s.Blocks)
            .Any(b => b.Kind == "result" && b.Text == "V₂ = 12 mA / 1.5 mS = 8 V");

        Assert.True(hasExpectedResultBlock, "Explanation should contain result block with Text 'V₂ = 12 mA / 1.5 mS = 8 V'");
    }

    [Fact]
    public async Task Panel_ShowResults_SelectsExplanationView_AndSelectExplanationViewToggles()
    {
        var resp = await _fx.Client.AnalyzeAsync(
            BuildRequest(TestCircuits.DcDivider(), AnalysisModes.Dc, type: AnalysisTypes.Nodal));

        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();

            // After ShowResults, explanation view is selected by default
            panel.ShowResults(resp);
            Assert.True(panel.IsExplanationViewSelected);

            panel.Measure(new Size(400, 2000));
            panel.Arrange(new Rect(0, 0, 400, 2000));
            panel.UpdateLayout();

            var texts = GetAllTexts(panel);
            Assert.Contains(texts, t => t.Contains("V₂ = 12 mA / 1.5 mS = 8 V"));
            Assert.Contains(texts, t => t.Contains("Denklemlerin Çözümü"));

            // SelectExplanationView(false) -> tree contains "DÜĞÜM GERİLİMLERİ" and no longer the explanation title
            panel.SelectExplanationView(false);
            Assert.False(panel.IsExplanationViewSelected);

            panel.Measure(new Size(400, 2000));
            panel.Arrange(new Rect(0, 0, 400, 2000));
            panel.UpdateLayout();

            texts = GetAllTexts(panel);
            Assert.Contains(texts, t => t.Contains("Düğüm gerilimleri"));
            Assert.DoesNotContain(texts, t => t.Contains("Denklemlerin Çözümü"));

            // Choice persists across subsequent ShowResults calls in the same session
            panel.ShowResults(resp);
            Assert.False(panel.IsExplanationViewSelected);

            panel.Measure(new Size(400, 2000));
            panel.Arrange(new Rect(0, 0, 400, 2000));
            panel.UpdateLayout();

            texts = GetAllTexts(panel);
            Assert.Contains(texts, t => t.Contains("Düğüm gerilimleri"));
            Assert.DoesNotContain(texts, t => t.Contains("Denklemlerin Çözümü"));
        });
    }

    [Fact]
    public async Task Panel_EmptyExplanation_HidesToggleAndShowsSonuclar()
    {
        var resp = await _fx.Client.AnalyzeAsync(
            BuildRequest(TestCircuits.DcDivider(), AnalysisModes.Dc, type: AnalysisTypes.Nodal));

        var emptyResp = new AnalysisResponseDto
        {
            Status = resp.Status,
            Mode = resp.Mode,
            AnalysisType = resp.AnalysisType,
            Results = new AnalysisResultsDto
            {
                NodeVoltages = resp.Results.NodeVoltages,
                ElementCurrents = resp.Results.ElementCurrents,
                Power = resp.Results.Power,
                Explanation = new List<ExplanationSectionDto>()
            }
        };

        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.ShowResults(emptyResp);

            // Empty explanation hides toggle and shows Sonuçlar
            Assert.False(panel.IsExplanationViewSelected);

            panel.Measure(new Size(400, 2000));
            panel.Arrange(new Rect(0, 0, 400, 2000));
            panel.UpdateLayout();

            var texts = GetAllTexts(panel);
            Assert.Contains(texts, t => t.Contains("Düğüm gerilimleri"));
            Assert.DoesNotContain(texts, t => t.Contains("Anlatım"));
        });
    }

    [Fact]
    public async Task Panel_AcRc_RendersPhasorSymbol()
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
            Assert.Contains(texts, t => t.Contains("∠"));
        });
    }

    [Fact]
    public async Task Panel_MarkStale_ClearResults_ShowError_DoNotThrow_InEitherView()
    {
        var resp = await _fx.Client.AnalyzeAsync(
            BuildRequest(TestCircuits.DcDivider(), AnalysisModes.Dc, type: AnalysisTypes.Nodal));

        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();

            // 1. Explanation view active
            panel.ShowResults(resp);
            Assert.True(panel.IsExplanationViewSelected);

            panel.MarkStale();
            Assert.Equal(0.45, panel.ResultsScrollViewer.Opacity);
            Assert.Equal(Visibility.Visible, panel.BannerStale.Visibility);

            panel.ClearResults();
            Assert.Equal(1.0, panel.ResultsScrollViewer.Opacity);
            Assert.Equal(Visibility.Collapsed, panel.BannerStale.Visibility);
            Assert.Empty(panel.ResultsContainer.Children);

            panel.ShowError("Hata 1", "Açıklama görünümünde hata mesajı");
            Assert.Single(panel.ResultsContainer.Children);

            // 2. Results view active
            panel.ShowResults(resp);
            panel.SelectExplanationView(false);
            Assert.False(panel.IsExplanationViewSelected);

            panel.MarkStale();
            Assert.Equal(0.45, panel.ResultsScrollViewer.Opacity);
            Assert.Equal(Visibility.Visible, panel.BannerStale.Visibility);

            panel.ClearResults();
            Assert.Equal(1.0, panel.ResultsScrollViewer.Opacity);
            Assert.Equal(Visibility.Collapsed, panel.BannerStale.Visibility);
            Assert.Empty(panel.ResultsContainer.Children);

            panel.ShowError("Hata 2", "Sonuçlar görünümünde hata mesajı");
            Assert.Single(panel.ResultsContainer.Children);
        });
    }
}
