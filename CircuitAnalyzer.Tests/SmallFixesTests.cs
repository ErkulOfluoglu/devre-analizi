using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using CircuitAnalyzer.WPF;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>Küçük hata düzeltmeleri: kirli bayrağı, sürükleme sıfırlama, kes, imleç, ilk açılış boyutu, yazım düzeni.</summary>
[Collection(WpfUiCollection.Name)]
public class SmallFixesTests
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

    private static void WithTempSettings(Action action)
    {
        string original = AppSettings.SettingsPath;
        string temp = Path.Combine(Path.GetTempPath(), $"settings-{Guid.NewGuid():N}.json");
        try
        {
            AppSettings.SettingsPath = temp;
            action();
        }
        finally
        {
            AppSettings.SettingsPath = original;
            if (File.Exists(temp)) File.Delete(temp);
            if (File.Exists(temp + ".tmp")) File.Delete(temp + ".tmp");
        }
    }

    private static ExampleCircuit TwoResistors(out Resistor r1, out Resistor r2)
    {
        var circuit = new ExampleCircuit { Name = "SmallFixes" };
        r1 = circuit.Add(new Resistor { Value = 1000 }, "R1", 100, 100);
        r2 = circuit.Add(new Resistor { Value = 2000 }, "R2", 300, 100);
        circuit.Connect(r1.Pins[1], r2.Pins[0]);
        return circuit;
    }

    private static T GetField<T>(object target, string name)
    {
        var f = target.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic)
                ?? throw new InvalidOperationException(name);
        return (T)f.GetValue(target)!;
    }

    // ── 23: yazdırma iş adı ──

    [Fact]
    public void PrintJobName_IsAppNameAndDocument_NotTheHintText()
    {
        Assert.Equal("Devre Analizi – Devre1", MainWindow.PrintJobName("Devre1"));
        Assert.DoesNotContain("Print to PDF", MainWindow.PrintJobName("Adsız"));
    }

    // ── 26: hata kaydı ──

    [Fact]
    public void CrashLog_AppendsExceptionAndMessageNamesTheFile()
    {
        string original = CrashLog.LogPath;
        string temp = Path.Combine(Path.GetTempPath(), $"hata-{Guid.NewGuid():N}", "hata.log");
        try
        {
            CrashLog.LogPath = temp;
            Assert.True(CrashLog.Write(new InvalidOperationException("deneme-hatası"), "test"));
            Assert.True(CrashLog.Write(null, "ikinci"));
            string text = File.ReadAllText(temp);
            Assert.Contains("deneme-hatası", text);
            Assert.Contains("ikinci", text);
            Assert.Contains(temp, CrashLog.UserMessage());
            Assert.StartsWith("Beklenmeyen bir hata oldu. Çalışmanızı kaydetmenizi öneririz.", CrashLog.UserMessage());
        }
        finally
        {
            CrashLog.LogPath = original;
            try { Directory.Delete(Path.GetDirectoryName(temp)!, true); } catch (IOException) { }
        }
    }

    // ── 40: ekran testi son açılanlara dosya eklemez ──

    [Fact]
    public void OpenFile_SelfTest_DoesNotTouchRecentList_NormalOpenDoes()
    {
        RunOnSta(() => WithTempSettings(() =>
        {
            string file = Path.Combine(Path.GetTempPath(), $"sf-{Guid.NewGuid():N}.devre");
            try
            {
                var circuit = TwoResistors(out _, out _);
                CircuitDocument.FromCircuit(circuit.Elements, circuit.Wires).Save(file);

                var win = new MainWindow { ClipboardService = new InMemoryClipboardService() };
                Assert.True(win.OpenFile(file, isSelfTest: true));
                Assert.Empty(AppSettings.RecentFiles);

                Assert.True(win.OpenFile(file));
                Assert.Contains(file, AppSettings.RecentFiles);
            }
            finally
            {
                if (File.Exists(file)) File.Delete(file);
            }
        }));
    }

    // ── 42: kirli bayrağı kayda göre ──

    [Fact]
    public void Dirty_MeansDiffersFromSavedState_UndoBackToSavedClearsIt()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow { ClipboardService = new InMemoryClipboardService() };
            win.LoadExample(TwoResistors(out _, out var r2));
            Assert.False(win.IsDirty);

            win.Selection.Select(r2);
            win.RotateSelected();
            Assert.True(win.IsDirty);

            win.Undo();
            Assert.False(win.IsDirty);   // kayıtlı duruma dönüldü: "•" kalkar
            win.Redo();
            Assert.True(win.IsDirty);
        });
    }

    [Fact]
    public void CircuitChangedWithoutRealChange_StaysCleanAndAddsNoUndoStep()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow { ClipboardService = new InMemoryClipboardService() };
            win.LoadExample(TwoResistors(out _, out _));
            Assert.False(win.UndoHistory.CanUndo);

            // "Uygula" hiçbir şeyi değiştirmedi: aynı devre için OnCircuitChanged çağrılır
            typeof(MainWindow).GetMethod("OnCircuitChanged", BindingFlags.Instance | BindingFlags.NonPublic)!
                .Invoke(win, null);

            Assert.False(win.IsDirty);
            Assert.False(win.UndoHistory.CanUndo);
        });
    }

    // ── 44: sürükleme durumu sıfırlanır, geri al seçimi korur ──

    [Fact]
    public void ClearingTheCircuit_ResetsDragState()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow { ClipboardService = new InMemoryClipboardService() };
            win.LoadExample(TwoResistors(out var r1, out _));

            win.HandleElementLeftButtonDown(r1, new Point(140, 110));
            Assert.True(GetField<bool>(win, "_isDragging"));

            win.NewCircuit();   // ClearCircuit çağırır
            Assert.False(GetField<bool>(win, "_isDragging"));
            Assert.Null(GetField<object?>(win, "_draggedElement"));
            Assert.Null(GetField<object?>(win, "_draggedVisual"));
        });
    }

    [Fact]
    public void UndoAndRedo_KeepSelectionOfElementsThatStillExist()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow { ClipboardService = new InMemoryClipboardService() };
            win.LoadExample(TwoResistors(out _, out var r2));

            win.Selection.Select(r2);
            win.RotateSelected();
            win.Undo();

            var selected = Assert.Single(win.Selection.Elements);
            Assert.Equal("R2", selected.Id);
            Assert.Same(win.Elements.First(e => e.Id == "R2"), selected);

            win.Redo();
            Assert.Equal("R2", Assert.Single(win.Selection.Elements).Id);
        });
    }

    // ── 46: Space imleci pencere etkinliğini kaybedince kalkar ──

    [Fact]
    public void SpaceCursor_IsResetWhenWindowDeactivates()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow { ClipboardService = new InMemoryClipboardService() };
            win.ShowSpaceCursor();
            Assert.Equal(Cursors.Hand, Mouse.OverrideCursor);

            typeof(Window).GetMethod("OnDeactivated", BindingFlags.Instance | BindingFlags.NonPublic)!
                .Invoke(win, new object[] { EventArgs.Empty });

            Assert.Null(Mouse.OverrideCursor);
        });
    }

    // ── 47: yerel çözücüye proxy yok ──

    [Fact]
    public void ApiClientHandler_DoesNotUseSystemProxy()
    {
        Assert.False(AnalysisApiClient.CreateHandler().UseProxy);
    }

    // ── 49: ilk açılışta küçük ekrana sığdır ──

    [Fact]
    public void FitDefault_ShrinksToWorkAreaAndCenters()
    {
        // 1366×768 ekranda %125 ölçek: çalışma alanı 1093×582 birim
        var work = new Rect(0, 0, 1093, 582);
        var (bounds, minW, minH) = WindowPlacementRules.FitDefault(1280, 800, 900, 600, work);
        Assert.Equal(1093, bounds.Width);
        Assert.Equal(582, bounds.Height);
        Assert.Equal(0, bounds.Left);
        Assert.Equal(0, bounds.Top);
        Assert.Equal(900, minW);
        Assert.Equal(582, minH);   // en küçük yükseklik çalışma alanından büyük kalmaz
    }

    [Fact]
    public void FitDefault_LargeScreen_KeepsSizeAndCenters()
    {
        var work = new Rect(0, 0, 1920, 1040);
        var (bounds, _, minH) = WindowPlacementRules.FitDefault(1280, 800, 900, 600, work);
        Assert.Equal(1280, bounds.Width);
        Assert.Equal(800, bounds.Height);
        Assert.Equal(320, bounds.Left);
        Assert.Equal(120, bounds.Top);
        Assert.Equal(600, minH);
    }

    // ── 37: fazör yazısı satırda bölünmez (yalnız ekran) ──

    [Fact]
    public void PhasorText_JoinsNumberAngleAndUnit_OnlyForPhasors()
    {
        string shown = PhasorText.KeepTogether("21,94∠−36,87° A");
        Assert.Contains('⁠', shown);
        Assert.Contains(' ', shown);
        Assert.DoesNotContain(' ', shown);
        Assert.Equal("21,94∠−36,87° A", PhasorText.Strip(shown));

        // Fazör olmayan değere dokunulmaz
        Assert.Equal("8 V", PhasorText.KeepTogether("8 V"));
        Assert.Equal("", PhasorText.KeepTogether(null));
    }

    [Fact]
    public void ValueTiles_KeepPhasorTogether_AndStripRestoresPlainText()
    {
        RunOnSta(() =>
        {
            var m = typeof(AnalysisPanel).GetMethod("CreateValueTile", BindingFlags.Static | BindingFlags.NonPublic)!;
            var tile = (Border)m.Invoke(null, new object?[] { "I_R1", "21,94∠-36,87° A", null })!;
            var sp = (StackPanel)tile.Child;
            var value = (TextBlock)sp.Children[1];
            Assert.Contains('⁠', value.Text);
            Assert.Equal("21,94∠−36,87° A", PhasorText.Strip(value.Text));
        });
    }

    // ── 39: Rezonans Eğrisi başlığı bir kez; geçici durumda mod yazısı ──

    [Fact]
    public void ResonanceView_EnlargedHidesCardTitle_BecauseOverlayHasOne()
    {
        RunOnSta(() =>
        {
            var view = new ResonanceCurveView();
            Assert.Equal(Visibility.Visible, view.TxtHeaderTitle.Visibility);
            view.IsEnlarged = true;
            Assert.Equal(Visibility.Collapsed, view.TxtHeaderTitle.Visibility);
        });
    }

    [Theory]
    [InlineData(false, AnalysisTypes.Nodal, "DC analiz")]
    [InlineData(true, AnalysisTypes.Nodal, "AC (fazör) analiz")]
    [InlineData(false, AnalysisTypes.Transient, "Geçici durum")]
    [InlineData(true, AnalysisTypes.Transient, "Geçici durum")]
    public void ModeLabel_SaysTransientUnderTheTransientMethod(bool ac, string type, string expected)
    {
        Assert.Equal(expected, AnalysisPanel.ModeLabelText(ac, type));
    }

    [Fact]
    public void ModeLabel_FollowsMethodSelector()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetCircuitInfo(hasAcSource: false, needsFrequency: false);
            Assert.Equal("DC analiz", panel.TxtModeLabel.Text);

            panel.CmbAnalysisType.SelectedIndex = 7;   // Geçici Durum (Anahtar)
            Assert.Equal("Geçici durum", panel.TxtModeLabel.Text);

            panel.CmbAnalysisType.SelectedIndex = 0;
            Assert.Equal("DC analiz", panel.TxtModeLabel.Text);
        });
    }

    // ── 31: Etkin/Tepe başlığı "Gösterim" ──

    [Fact]
    public void ValueDisplayToggle_IsCaptionedGosterim_NotSonuclar()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            var captions = ((StackPanel)panel.RowValueDisplay).Children.OfType<TextBlock>().Select(t => t.Text).ToList();
            Assert.Contains("Gösterim", captions);
            Assert.DoesNotContain("Sonuçlar", captions);
        });
    }

    // ── 28: tanıtım turunda 1. ve 3. adım ──

    [Fact]
    public void Tour_StepsOneAndThree_DoNotCoverCircuitOrMethodBox()
    {
        var steps = TourSteps.Steps;
        Assert.Equal(TourSide.RightLow, steps[0].PreferredSides![0]);
        Assert.Equal(TourSide.Below, steps[2].PreferredSides![0]);

        // Pencere boyu sol şerit: kart sağında ama alt kısımda, devrenin durduğu üst-solda değil
        var rail = new Rect(0, 45, 72, 720);
        var spot = TourPlacement.Place(rail, 340, 224, 1266, 763, steps[0].PreferredSides);
        Assert.True(spot.X >= rail.Right);
        Assert.Equal(763 - 224 - TourPlacement.RightLowBottomMargin, spot.Y);
        Assert.True(spot.Y > 400, "kart devrenin bulunduğu üst kısımdan aşağıda olmalı");

        // Varsayılan sıra eskisi gibi: önce sağ
        var right = TourPlacement.Place(rail, 340, 200, 1280, 800);
        Assert.True(right.X >= rail.Right);
    }

    // ── 29: eleman kartı komşuyu örtmeyen yanı seçer ──

    [Fact]
    public void ElementCard_PicksTheSideThatOverlapsNeighboursLeast()
    {
        var target = new Rect(300, 300, 80, 40);
        var card = new Size(200, 150);
        var area = new Size(1000, 700);

        // Sağda komşu var: sol seçilir
        var neighbourRight = new Rect(400, 280, 100, 100);
        var p = ElementCardPlacement.Choose(target, card, area, new[] { neighbourRight }, 14);
        Assert.True(p.X + card.Width <= target.Left);

        // Komşu yoksa eski davranış: sağ
        var free = ElementCardPlacement.Choose(target, card, area, Array.Empty<Rect>(), 14);
        Assert.True(free.X >= target.Right);
    }
}
