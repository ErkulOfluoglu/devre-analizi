using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using CircuitAnalyzer.WPF;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Yerleştirme modu (araç kutusundan eleman → fareyi izleyen önizleme → tıkla bırak / Esc vazgeç),
/// boş yer bulma ve Analiz panelinin genişlik ayarı. Python arka ucu gerekmez.
/// </summary>
[Collection(WpfUiCollection.Name)]
public class PlacementTests
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

    private static void Click(Button button) => button.RaiseEvent(new RoutedEventArgs(ButtonBase.ClickEvent));

    /// <summary>Tuvaldeki yarı saydam, fareye şeffaf önizleme görselleri (yerleştirme bitince kalmamalı).</summary>
    private static int PreviewVisualCount(MainWindow win) =>
        win.CircuitCanvas.Children.Cast<UIElement>().Count(c => c.Opacity < 1 && !c.IsHitTestVisible);

    [Fact]
    public void FindFreePosition_NeverOverlapsExistingElements()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow();

            // Tercih edilen nokta etrafını yoğun biçimde doldur
            for (int i = 0; i < 12; i++)
                win.AddDependentSource((DependentSourceKind)(i % 4));
            var preferred = new Point(400, 300);

            foreach (var probe in new CircuitElement[]
                     {
                         new Resistor { Id = "R9" },
                         new GroundElement { Id = "GND9" },
                         new Resistor { Id = "R10", Rotation = 90 },
                     })
            {
                Point pos = win.FindFreePosition(probe, preferred);
                probe.Position = pos;
                Rect box = SelectionModel.GetElementBounds(probe);

                Assert.True(box.Left >= 0 && box.Top >= 0, $"{probe.Id} tuval dışına çıktı: {box}");
                foreach (var other in win.Elements)
                    Assert.False(box.IntersectsWith(SelectionModel.GetElementBounds(other)),
                        $"{probe.Id} {box} ile {other.Id} {SelectionModel.GetElementBounds(other)} kesişiyor");
            }

            // Boş tuvalde tercih edilen (ızgaraya oturmuş) konum aynen döner
            var empty = new MainWindow();
            Assert.Equal(new Point(400, 300), empty.FindFreePosition(new Resistor { Id = "R1" }, new Point(403, 297)));
        });
    }

    [Fact]
    public void AddDependentSource_Immediate_DoesNotLandOnExistingElements()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow();
            for (int i = 0; i < 8; i++)
                win.AddDependentSource(DependentSourceKind.Vcvs);

            var boxes = win.Elements.Select(SelectionModel.GetElementBounds).ToList();
            for (int i = 0; i < boxes.Count; i++)
                for (int j = i + 1; j < boxes.Count; j++)
                    Assert.False(boxes[i].IntersectsWith(boxes[j]), $"{win.Elements[i].Id} ve {win.Elements[j].Id} üst üste");
        });
    }

    [Fact]
    public void ToolboxClick_StartsPlacement_WithTranslucentPreview_AndAddsNothingYet()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow();
            Click(win.BtnAddResistor);

            Assert.True(win.IsPlacing);
            Assert.Empty(win.Elements);
            Assert.Equal("R1", win.PlacingElement!.Id);
            Assert.Equal(0.6, win.PlacementPreview!.Opacity, 3);
            Assert.False(win.PlacementPreview.IsHitTestVisible);
            Assert.Contains(win.PlacementPreview, win.CircuitCanvas.Children.Cast<UIElement>());
            Assert.Contains("R1 yerleştir", win.TxtStatus.Text);
            Assert.Contains("Esc", win.TxtStatus.Text);

            // Önizleme fareyi ızgaraya oturarak ve ortalanarak izler
            win.HandleCanvasMouseMove(new Point(413, 297));
            Assert.Equal(new Point(380, 280), win.PlacingElement.Position);
            Assert.Equal(380, Canvas.GetLeft(win.PlacementPreview));
            Assert.Equal(280, Canvas.GetTop(win.PlacementPreview));
        });
    }

    [Fact]
    public void Placement_Click_AddsExactlyOneElement_AtSnappedPoint_WithOneUndoStep()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow();
            Click(win.BtnAddResistor);
            win.HandleCanvasMouseMove(new Point(413, 297));
            win.HandleCanvasLeftButtonDown(new Point(413, 297));

            var r1 = Assert.Single(win.Elements);
            Assert.Equal("R1", r1.Id);
            Assert.Equal(new Point(380, 280), r1.Position);
            Assert.False(win.IsPlacing);
            Assert.Equal(0, PreviewVisualCount(win));
            Assert.Contains("R1 eklendi", win.TxtStatus.Text);

            // Tek geri-al adımı
            win.Undo();
            Assert.Empty(win.Elements);

            // Bırakıştan sonra tuvale tıklamak yeni eleman eklemez
            win.Redo();
            win.HandleCanvasLeftButtonDown(new Point(600, 400));
            Assert.Single(win.Elements);
        });
    }

    [Fact]
    public void Placement_Cancel_AddsNothing_AndDoesNotConsumeAnId()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow();
            Click(win.BtnAddResistor);
            win.HandleCanvasLeftButtonDown(new Point(200, 200)); // R1 yerleşti

            // Esc ile vazgeç
            Click(win.BtnAddResistor);
            Assert.Equal("R2", win.PlacingElement!.Id);
            Assert.True(win.HandleKeyDown(Key.Escape));
            Assert.False(win.IsPlacing);
            Assert.Single(win.Elements);
            Assert.Equal(0, PreviewVisualCount(win));

            // Yeni araç seçince öncekini iptal eder; Id'ler ardışık kalır
            Click(win.BtnAddResistor);
            Click(win.BtnAddCapacitor);
            Assert.Equal("C1", win.PlacingElement!.Id);
            Assert.Equal(1, PreviewVisualCount(win));
            Click(win.BtnAddResistor);
            Assert.Equal("R2", win.PlacingElement!.Id);
            Assert.Equal(1, PreviewVisualCount(win));
            win.HandleCanvasLeftButtonDown(new Point(400, 200));

            Assert.Equal(new[] { "R1", "R2" }, win.Elements.Select(e => e.Id).ToArray());
            Assert.Equal(0, PreviewVisualCount(win));
        });
    }

    [Fact]
    public void Placement_RotateKey_RotatesPreview_AndWireModeCancelsPlacement()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow();
            Click(win.BtnAddGround);
            Assert.True(win.HandleKeyDown(Key.R));
            Assert.Equal(90, win.PlacingElement!.Rotation);

            win.HandleCanvasLeftButtonDown(new Point(300, 300));
            Assert.Equal(90, Assert.Single(win.Elements).Rotation);

            Click(win.BtnAddProbe);
            Assert.True(win.IsPlacing);
            Click(win.BtnDrawWire);
            Assert.False(win.IsPlacing);
            Assert.Single(win.Elements);
        });
    }

    [Fact]
    public void Placement_StartsAtFreeSpot_WhenMouseIsNotOverCanvas()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow();
            win.AddDependentSource(DependentSourceKind.Vcvs); // görünür alanın ortasını işgal eder

            Click(win.BtnAddResistor);
            var preview = SelectionModel.GetElementBounds(win.PlacingElement!);
            Assert.False(preview.IntersectsWith(SelectionModel.GetElementBounds(win.Elements[0])));
        });
    }

    [Fact]
    public void AnalysisPanelWidth_RoundTripsThroughAppSettings_AndIsRestoredOnStartup()
    {
        string original = AppSettings.SettingsPath;
        string temp = Path.Combine(Path.GetTempPath(), $"settings_panel_{Guid.NewGuid():N}.json");
        try
        {
            AppSettings.SettingsPath = temp;

            Assert.Null(AppSettings.AnalysisPanelWidth);
            AppSettings.Theme = "Dark"; // başka ayarlar korunmalı
            AppSettings.AnalysisPanelWidth = 520;
            Assert.Equal(520, AppSettings.AnalysisPanelWidth);
            Assert.Equal("Dark", AppSettings.Theme);

            RunOnSta(() =>
            {
                var win = new MainWindow();
                Assert.Equal(520, win.AnalysisColumn.Width.Value);
                Assert.Equal(360, win.AnalysisColumn.MinWidth);
            });

            // Sınır dışı değer sınırlara çekilir; ayar yoksa varsayılan 460
            AppSettings.AnalysisPanelWidth = 5000;
            RunOnSta(() => Assert.Equal(900, new MainWindow().AnalysisColumn.Width.Value));
            AppSettings.AnalysisPanelWidth = 10;
            RunOnSta(() => Assert.Equal(360, new MainWindow().AnalysisColumn.Width.Value));
            AppSettings.AnalysisPanelWidth = null;
            Assert.Null(AppSettings.AnalysisPanelWidth);
            RunOnSta(() => Assert.Equal(460, new MainWindow().AnalysisColumn.Width.Value));
        }
        finally
        {
            AppSettings.SettingsPath = original;
            try { File.Delete(temp); } catch { }
        }
    }

    [Fact]
    public void AnalysisPanelMaxWidth_KeepsCanvasAtLeast400_WhenWindowAllows()
    {
        // 1248 px yerleşim: 1248 - 280 sabit sütun - 400 canvas = 568
        Assert.Equal(568, MainWindow.AnalysisPanelMaxWidthFor(1248));
        // Çok geniş pencere: 900'de durur
        Assert.Equal(900, MainWindow.AnalysisPanelMaxWidthFor(3000));
        // Çok dar pencere: panel en küçük genişliğine iner
        Assert.Equal(360, MainWindow.AnalysisPanelMaxWidthFor(900));
    }
}
