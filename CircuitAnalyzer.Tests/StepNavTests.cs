using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Okuma panelinin adım zinciri: anlatımın her bölümü numaralı bir adımdır, aynı anda bir adım
/// açıktır, Önceki / Sonraki zinciri ilerletir, "Tümünü aç" hepsini açar. Kapalı adımda tek
/// satırlık özet görünür. Python arka ucu gerekmez (cevap elle kurulur).
/// </summary>
[Collection(WpfUiCollection.Name)]
public class StepNavTests
{
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
            finally
            {
                System.Windows.Threading.Dispatcher.CurrentDispatcher.InvokeShutdown();
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();

        if (ex != null)
            ExceptionDispatchInfo.Capture(ex).Throw();
    }

    // Gerçek anlatımlar gibi: ilk bölümler uzun, son bölümler kısa
    private static AnalysisResponseDto Response(int sections) => new()
    {
        Status = "success",
        Results = new AnalysisResultsDto
        {
            Explanation = Enumerable.Range(1, sections).Select(i => new ExplanationSectionDto
            {
                Title = $"Bölüm {i}",
                Blocks = Enumerable.Range(1, i <= sections - 3 ? 6 : 1).Select(j => new ExplanationBlockDto
                {
                    Kind = "text",
                    Text = $"Bölüm {i}, paragraf {j}: düğüm gerilimleri ve akımlar üzerine uzunca bir açıklama metni."
                }).ToList()
            }).ToList()
        }
    };

    private static void Layout(AnalysisPanel panel)
    {
        panel.Measure(new Size(420, 600));
        panel.Arrange(new Rect(0, 0, 420, 600));
        panel.UpdateLayout();
    }

    private static int[] OpenSteps(AnalysisPanel panel) =>
        Enumerable.Range(0, panel.StepSections.Count).Where(panel.IsStepOpen).ToArray();

    [Fact]
    public void FirstStepOpens_AndNextPreviousWalkTheWholeChain()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.ShowResults(Response(5));
            Layout(panel);

            Assert.Equal(5, panel.StepSections.Count);
            Assert.Equal(Visibility.Visible, panel.StepNavBar.Visibility);
            Assert.Equal(0, panel.CurrentStepIndex);
            Assert.Equal(new[] { 0 }, OpenSteps(panel));
            Assert.StartsWith("Adım 1 / 5 · Bölüm 1", panel.TxtStepLabel.Text);
            Assert.False(panel.BtnPrevStep.IsEnabled);

            for (int expected = 1; expected <= 4; expected++)
            {
                panel.GoToStep(+1);
                Assert.Equal(expected, panel.CurrentStepIndex);
                Assert.Equal(new[] { expected }, OpenSteps(panel));
            }
            Assert.False(panel.BtnNextStep.IsEnabled);

            // Sondan başa: en altta kısa adımlar birlikte görünse de her basış bir adım geri gider
            for (int expected = 3; expected >= 0; expected--)
            {
                Assert.True(panel.BtnPrevStep.IsEnabled);
                panel.GoToStep(-1);
                Assert.Equal(expected, panel.CurrentStepIndex);
                Assert.Equal(new[] { expected }, OpenSteps(panel));
                Assert.StartsWith($"Adım {expected + 1} / 5", panel.TxtStepLabel.Text);
            }
        });
    }

    [Fact]
    public void ClickingOpenStep_ClosesIt_AndNextStartsFromTheTop()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.ShowResults(Response(4));
            Layout(panel);

            panel.OnStepHeaderClicked(2);
            Assert.Equal(2, panel.CurrentStepIndex);
            Assert.Equal(new[] { 2 }, OpenSteps(panel));

            panel.OnStepHeaderClicked(2);
            Assert.Equal(-1, panel.CurrentStepIndex);
            Assert.Empty(OpenSteps(panel));
            Assert.Equal("4 adım", panel.TxtStepLabel.Text);

            panel.GoToStep(+1);
            Assert.Equal(0, panel.CurrentStepIndex);
        });
    }

    [Fact]
    public void OpenAll_ShowsEveryStep_AndNavigationStillMovesTheMarker()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.ShowResults(Response(4));
            Layout(panel);

            panel.SetAllStepsOpen(true);
            Assert.True(panel.AllStepsOpen);
            Assert.Equal(new[] { 0, 1, 2, 3 }, OpenSteps(panel));

            panel.GoToStep(+1);
            Assert.Equal(1, panel.CurrentStepIndex);
            Assert.Equal(new[] { 0, 1, 2, 3 }, OpenSteps(panel));

            panel.SetAllStepsOpen(false);
            Assert.Equal(new[] { 1 }, OpenSteps(panel));
        });
    }

    [Fact]
    public void ResultsView_SingleSection_AndClear_HideStepNav()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.ShowResults(Response(4));
            Layout(panel);
            Assert.Equal(Visibility.Visible, panel.StepNavBar.Visibility);

            panel.SelectExplanationView(false);
            Assert.Empty(panel.StepSections);
            Assert.Equal(Visibility.Collapsed, panel.StepNavBar.Visibility);

            panel.SelectExplanationView(true);
            panel.ShowResults(Response(1));
            Layout(panel);
            Assert.Equal(Visibility.Collapsed, panel.StepNavBar.Visibility);

            panel.ClearResults();
            Assert.Equal(Visibility.Collapsed, panel.StepNavBar.Visibility);
        });
    }

    private static ExplanationSectionDto Section(params (string Kind, string Text)[] blocks) => new()
    {
        Title = "Adım",
        Blocks = blocks.Select(b => new ExplanationBlockDto { Kind = b.Kind, Text = b.Text }).ToList()
    };

    [Fact]
    public void Summary_PrefersResults_ThenChecks_ThenEquations_ThenFirstSentence()
    {
        Assert.Equal("V₂ = 8,685 V · V₃ = 5,474 V", AnalysisPanel.SummarizeStep(Section(
            ("text", "Cramer kuralıyla çözelim:"),
            ("math", "Δ = 197,7"),
            ("result", "V₂ = Δ₁/Δ = 1717 / 197,7 = 8,685 V"),
            ("result", "V₃ = Δ₂/Δ = 1082 / 197,7 = 5,474 V"))));

        Assert.Equal("Güç dengesi ✓", AnalysisPanel.SummarizeStep(Section(
            ("math", "P_R1 = I²·R = 109,9 mW"),
            ("check", "Güç dengesi: verilen 753,8 mW = harcanan 753,8 mW ✓"))));

        Assert.Equal("3 kontrol tuttu ✓", AnalysisPanel.SummarizeStep(Section(
            ("check", "Düğüm 1: ... ✓"), ("check", "Düğüm 2: ... ✓"), ("check", "Düğüm 3: ... ✓"))));

        Assert.Equal("2 bilinmeyen için 2 denklem", AnalysisPanel.SummarizeStep(Section(
            ("text", "Kirchhoff Akım Yasası."),
            ("math", "Düğüm 2: (V₂ − V₁)/R1 + V₂/R3 = 0"),
            ("math", "⇒ (V₂ − 12)/100 + V₂/330 = 0"),
            ("math", "Düğüm 3: (V₃ − V₁)/R2 + V₃/R4 = 0"))));

        Assert.Equal("I_R1 = 33,15 mA · I_R2 = 29,66 mA · …", AnalysisPanel.SummarizeStep(Section(
            ("math", "I_R1 = (V₁ − V₂)/R1 = 33,15 mA  (Düğüm 1 → Düğüm 2)"),
            ("math", "I_R2 = (V₁ − V₃)/R2 = 29,66 mA  (Düğüm 1 → Düğüm 3)"),
            ("math", "I_R3 = V₂/R3 = 26,32 mA"))));

        Assert.Equal("Kaynaklar: V1 = 12 V (DC).", AnalysisPanel.SummarizeStep(Section(
            ("text", "Kaynaklar: V1 = 12 V (DC)."), ("text", "İkinci cümle."))));
    }
}
