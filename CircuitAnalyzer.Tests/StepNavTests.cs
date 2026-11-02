using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Okuma panelinin adım geçişi: anlatımın her bölümü bir adımdır; Önceki / Sonraki
/// bölüm başına kaydırır, etiket okunan bölümü gösterir. Çözüm sayfalara bölünmez.
/// Python arka ucu gerekmez (cevap elle kurulur).
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

    // Gerçek anlatımlar gibi: ilk bölümler uzun, son bölümler kısa (en altta birkaçı birlikte görünür)
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

    [Fact]
    public void NextAndPrevious_MoveBetweenSections_AndLabelFollows()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.ShowResults(Response(5));
            Layout(panel);

            Assert.Equal(5, panel.StepSections.Count);
            Assert.Equal(Visibility.Visible, panel.StepNavBar.Visibility);
            Assert.Equal(0, panel.CurrentStepIndex);
            Assert.StartsWith("Adım 1 / 5 · Bölüm 1", panel.TxtStepLabel.Text);
            Assert.True(panel.BtnNextStep.IsEnabled);

            panel.GoToStep(+1);
            Assert.Equal(1, panel.CurrentStepIndex);
            Assert.StartsWith("Adım 2 / 5 · Bölüm 2", panel.TxtStepLabel.Text);

            panel.GoToStep(+1);
            Assert.Equal(2, panel.CurrentStepIndex);

            panel.GoToStep(-1);
            Assert.Equal(1, panel.CurrentStepIndex);

            // Bütün bölümler görünür kalır (sayfalara bölünmez)
            Assert.All(panel.StepSections, s => Assert.Equal(Visibility.Visible, s.Visibility));
        });
    }

    [Fact]
    public void Previous_WorksFromTheEnd_WhereLastSectionsShareTheScreen()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.ShowResults(Response(5));
            Layout(panel);

            // Sonraki ile sona kadar git: en alttayken son bölümler birlikte görünür
            for (int i = 0; i < 6; i++)
                panel.GoToStep(+1);
            Assert.Equal(4, panel.CurrentStepIndex);
            Assert.False(panel.BtnNextStep.IsEnabled);

            // Önceki her basışta bir adım geri gider, sayfa kıpırdamasa bile
            for (int expected = 3; expected >= 0; expected--)
            {
                Assert.True(panel.BtnPrevStep.IsEnabled);
                panel.GoToStep(-1);
                Assert.Equal(expected, panel.CurrentStepIndex);
                Assert.StartsWith($"Adım {expected + 1} / 5", panel.TxtStepLabel.Text);
                // Seçilen adımın başlığı vurgulanır, diğerleri değil
                var headings = panel.StepSections.Select(sec => (TextBlock)((StackPanel)sec).Children[0]).ToList();
                for (int i = 0; i < headings.Count; i++)
                    Assert.Equal(i == expected, headings[i].ReadLocalValue(TextBlock.ForegroundProperty) != DependencyProperty.UnsetValue);
            }
        });
    }

    [Fact]
    public void Previous_WorksAfterScrollingToTheEndByHand()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.ShowResults(Response(5));
            Layout(panel);

            panel.ResultsScrollViewer.ScrollToEnd();
            panel.UpdateLayout();
            int atEnd = panel.CurrentStepIndex;
            Assert.Equal(4, atEnd);

            panel.GoToStep(-1);
            Assert.Equal(3, panel.CurrentStepIndex);
            panel.GoToStep(-1);
            Assert.Equal(2, panel.CurrentStepIndex);
        });
    }

    [Fact]
    public void ResultsView_AndSingleSection_HideStepNav()
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
}
