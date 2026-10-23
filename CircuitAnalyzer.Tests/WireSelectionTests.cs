using System;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using CircuitAnalyzer.WPF;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Tekil tel seçimi, tel vurgusu, tel silme, T-bağlantı birleştirme, telden sürükleyerek
/// yeni tel başlatma ve yalnız tel seçiliyken kopyala/kes davranışlarının testleri.
/// </summary>
[Collection(WpfUiCollection.Name)]
public class WireSelectionTests
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
        {
            ExceptionDispatchInfo.Capture(ex).Throw();
        }
    }

    private static ExampleCircuit CreateTwoResistorCircuit(out Resistor r1, out Resistor r2, out Wire wire)
    {
        var circuit = new ExampleCircuit { Name = "WireSelTest" };
        // R1 @ (100,100): Pin0=(100,120), Pin1=(180,120)
        // R2 @ (300,100): Pin0=(300,120), Pin1=(380,120)
        r1 = circuit.Add(new Resistor { Value = 1000 }, "R1", 100, 100);
        r2 = circuit.Add(new Resistor { Value = 2000 }, "R2", 300, 100);
        circuit.Connect(r1.Pins[1], r2.Pins[0]);
        wire = circuit.Wires[0];
        return circuit;
    }

    [Fact]
    public void ClickOnWireMiddle_SelectsOnlyThatWireWithAccentAndThickness3_ClickEmptyCanvasDeselects()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow
            {
                ClipboardService = new InMemoryClipboardService()
            };
            var circuit = CreateTwoResistorCircuit(out _, out _, out _);
            win.LoadExample(circuit);

            var wire = Assert.Single(win.Wires);
            Assert.NotNull(wire.Visual);

            var accentBrush = (Brush)win.FindResource("Brush.Accent");
            var normalWireBrush = (Brush)win.FindResource("Brush.Circuit.Wire");

            // Başlangıçta tel seçili değil ve normal tel fırçası + kalınlık 2
            Assert.False(win.Selection.HasSelection);
            Assert.Equal(2, wire.Visual!.StrokeThickness);
            Assert.Equal(normalWireBrush.ToString(), wire.Visual.Stroke?.ToString());

            // Telin üzerine gelindiğinde (hover) el imleci ve durum çubuğu metni güncellenmeli
            Point midPoint = new(240, 120);
            win.HandleCanvasMouseMove(midPoint);
            Assert.Equal(Cursors.Hand, win.CircuitCanvas.Cursor);
            Assert.Equal("Tıkla: teli seç · Sürükle: buradan yeni tel", win.TxtStatus.Text);

            // Telin ortasına tek tık (bas + 4px eşiğini aşmadan bırak) → yalnız o tel seçilmeli
            win.HandleCanvasLeftButtonDown(midPoint);
            win.HandleCanvasLeftButtonUp(midPoint);

            Assert.Equal(0, win.Selection.Count);
            Assert.Single(win.Selection.Wires);
            Assert.Same(wire, win.Selection.Wires[0]);
            Assert.Equal(3, wire.Visual.StrokeThickness);
            Assert.Equal(accentBrush.ToString(), wire.Visual.Stroke?.ToString());

            // Boş tuvale tıklama → seçimi temizlemeli ve normal tel görünümünü geri yüklemeli
            Point emptyPoint = new(50, 50);
            win.HandleCanvasLeftButtonDown(emptyPoint);
            win.HandleCanvasLeftButtonUp(emptyPoint);

            Assert.False(win.Selection.HasSelection);
            Assert.Empty(win.Selection.Wires);
            Assert.Equal(2, wire.Visual.StrokeThickness);
            Assert.Equal(normalWireBrush.ToString(), wire.Visual.Stroke?.ToString());
        });
    }

    [Fact]
    public void DeleteSelectedWire_RemovesOnlyWireKeepsElements_SingleUndoRestoresEndpoints()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow
            {
                ClipboardService = new InMemoryClipboardService()
            };
            var circuit = CreateTwoResistorCircuit(out _, out _, out _);
            win.LoadExample(circuit);

            Point midPoint = new(240, 120);
            win.HandleCanvasLeftButtonDown(midPoint);
            win.HandleCanvasLeftButtonUp(midPoint);
            Assert.Single(win.Selection.Wires);

            win.DeleteSelected();

            Assert.Empty(win.Wires);
            Assert.Equal(2, win.Elements.Count);
            Assert.Contains(win.Elements, e => e.Id == "R1");
            Assert.Contains(win.Elements, e => e.Id == "R2");
            Assert.Equal("Tel silindi", win.TxtStatus.Text);

            // Tek geri-al (Undo) adımı teli aynı uçlarla geri getirmeli
            win.Undo();

            Assert.Equal(2, win.Elements.Count);
            var restoredWire = Assert.Single(win.Wires);
            Assert.Equal("R1", restoredWire.StartPin.Owner?.Id);
            Assert.Equal("2", restoredWire.StartPin.Id);
            Assert.Equal("R2", restoredWire.EndPin.Owner?.Id);
            Assert.Equal("1", restoredWire.EndPin.Id);
        });
    }

    [Fact]
    public void DeleteBranchWireOfTJunction_RemovesJunctionAndMergesWires_SingleUndoRestoresAll()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow
            {
                ClipboardService = new InMemoryClipboardService()
            };

            var baseCircuit = new ExampleCircuit { Name = "TJunctionDeleteTest" };
            var r1 = baseCircuit.Add(new Resistor { Value = 100 }, "R1", 200, 100);
            var l1 = baseCircuit.Add(new Inductor { Value = 0.1 }, "L1", 400, 100);
            var c2 = baseCircuit.Add(new Capacitor { Value = 10e-6 }, "C2", 300, 200, 90);
            baseCircuit.Connect(r1.Pins[1], l1.Pins[0]);

            var expectedOriginalRoute = WireGeometry.Route(r1.Pins[1].AbsolutePosition, l1.Pins[0].AbsolutePosition);

            win.LoadExample(baseCircuit);

            // C2'nin üst ucundan (340, 180) R1–L1 telinin ortasına (340, 120) T-bağlantısı oluştur
            win.StartPinWire(c2.Pins[0]);
            win.HandlePinWireClick(new Point(340, 120));

            Assert.Single(win.Elements.OfType<JunctionElement>());
            Assert.Equal(3, win.Wires.Count);

            // C2 dal telinin ortasına (340, 150) tıklayarak seç ve sil
            Point branchMid = new(340, 150);
            win.HandleCanvasLeftButtonDown(branchMid);
            win.HandleCanvasLeftButtonUp(branchMid);

            var selectedBranch = Assert.Single(win.Selection.Wires);
            Assert.True(selectedBranch.StartPin.Owner?.Id == "C2" || selectedBranch.EndPin.Owner?.Id == "C2");

            win.DeleteSelected();

            // J1 kalkmalı ve kalan iki tel orijinal rotayla tek telde birleşmeli
            Assert.Empty(win.Elements.OfType<JunctionElement>());
            var mergedWire = Assert.Single(win.Wires);
            var mergedRoute = WireGeometry.Route(mergedWire.StartPin.AbsolutePosition, mergedWire.EndPin.AbsolutePosition);
            Assert.Equal(expectedOriginalRoute, mergedRoute);

            // Tek geri-al (Undo) adımı J1'i ve 3 teli geri yüklemeli
            win.Undo();

            var restoredJ = Assert.Single(win.Elements.OfType<JunctionElement>());
            Assert.Equal(new Point(340, 120), restoredJ.Position);
            Assert.Equal(3, restoredJ.AttachedWireCount);
            Assert.Equal(3, win.Wires.Count);
        });
    }

    [Fact]
    public void PressAndDragFromWire_StartsPinWiringFromNewJunction_EscapeCancelsAndRestoresCircuit()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow
            {
                ClipboardService = new InMemoryClipboardService()
            };
            var circuit = CreateTwoResistorCircuit(out _, out _, out _);
            win.LoadExample(circuit);

            Assert.Single(win.Wires);
            Assert.Empty(win.Elements.OfType<JunctionElement>());
            Assert.False(win.IsPinWiring);

            // Telin ortasına (240, 120) bas ve 4px eşiğinin ötesine (240, 140) sürükle
            Point pressPoint = new(240, 120);
            Point dragPoint = new(240, 140);
            win.HandleCanvasLeftButtonDown(pressPoint);
            win.HandleCanvasMouseMove(dragPoint);

            Assert.True(win.IsPinWiring);
            Assert.Single(win.Elements.OfType<JunctionElement>());
            Assert.Equal(2, win.Wires.Count);

            // Esc ile iptal edildiğinde devre değişmeden kalmalı (tek tel, bağlantı noktası yok)
            win.CancelPinWire();

            Assert.False(win.IsPinWiring);
            Assert.Empty(win.Elements.OfType<JunctionElement>());
            var remainingWire = Assert.Single(win.Wires);
            Assert.Equal("R1", remainingWire.StartPin.Owner?.Id);
            Assert.Equal("R2", remainingWire.EndPin.Owner?.Id);
        });
    }

    [Fact]
    public void CtrlClickTogglesWire_AndRubberBandElementPlusWire_DeleteRemovesBothInOneUndoStep()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow
            {
                ClipboardService = new InMemoryClipboardService()
            };

            var circuit = new ExampleCircuit { Name = "MultiWireElemTest" };
            var r1 = circuit.Add(new Resistor { Value = 1000 }, "R1", 100, 100);
            var r2 = circuit.Add(new Resistor { Value = 2000 }, "R2", 300, 100);
            var r3 = circuit.Add(new Resistor { Value = 3000 }, "R3", 500, 100);
            circuit.Connect(r1.Pins[1], r2.Pins[0]); // w1: (180,120) -> (300,120)
            circuit.Connect(r2.Pins[1], r3.Pins[0]); // w2: (380,120) -> (500,120)
            win.LoadExample(circuit);

            Point w1Mid = new(240, 120);
            Point w2Mid = new(440, 120);

            // w1'e normal tık → seçilir
            win.HandleCanvasLeftButtonDown(w1Mid);
            win.HandleCanvasLeftButtonUp(w1Mid);
            Assert.Single(win.Selection.Wires);

            // w2'ye Ctrl+tık → seçime eklenir (2 tel)
            win.HandleCanvasLeftButtonDown(w2Mid, ModifierKeys.Control);
            win.HandleCanvasLeftButtonUp(w2Mid, ModifierKeys.Control);
            Assert.Equal(2, win.Selection.Wires.Count);

            // w1'e tekrar Ctrl+tık → seçimden çıkarılır (1 tel kalır)
            win.HandleCanvasLeftButtonDown(w1Mid, ModifierKeys.Control);
            win.HandleCanvasLeftButtonUp(w1Mid, ModifierKeys.Control);
            Assert.Single(win.Selection.Wires);
            Assert.Same(win.Wires[1], win.Selection.Wires[0]);

            // Çerçeve (rubber-band) seçimi: (80,80) → (310,160) R1, R2 ve w1'i kapsar; R3 ve w2 dışarıda
            Point rbStart = new(80, 80);
            Point rbEnd = new(310, 160);
            win.HandleCanvasLeftButtonDown(rbStart);
            win.HandleCanvasMouseMove(rbEnd);
            win.HandleCanvasLeftButtonUp(rbEnd);

            Assert.Equal(2, win.Selection.Count);
            Assert.Single(win.Selection.Wires);

            // Delete: seçili elemanları ve teli tek geri-al adımında siler
            win.DeleteSelected();
            Assert.Single(win.Elements);
            Assert.Equal("R3", win.Elements[0].Id);
            Assert.Empty(win.Wires);

            // Tek Undo ile hem silinen elemanlar hem teller geri yüklenmeli
            win.Undo();
            Assert.Equal(3, win.Elements.Count);
            Assert.Equal(2, win.Wires.Count);
        });
    }

    [Fact]
    public void SelectionWithOnlyWires_CtrlCDoesNotThrowAndLeavesClipboardUnchanged_CtrlXDeletesWires()
    {
        RunOnSta(() =>
        {
            var clipboard = new InMemoryClipboardService();
            var win = new MainWindow
            {
                ClipboardService = clipboard
            };

            var circuit = CreateTwoResistorCircuit(out var r1, out _, out _);
            win.LoadExample(circuit);

            // Önce panoya R1'i kopyalayalım ki panoda mevcut bir veri bulunsun
            win.Selection.Select(r1);
            Assert.True(win.CopySelected());
            string? initialClipboardPayload = clipboard.GetCircuitData();
            Assert.NotNull(initialClipboardPayload);

            // Şimdi yalnız teli seçelim
            Point midPoint = new(240, 120);
            win.HandleCanvasLeftButtonDown(midPoint);
            win.HandleCanvasLeftButtonUp(midPoint);
            Assert.Equal(0, win.Selection.Count);
            Assert.Single(win.Selection.Wires);

            // Ctrl+C (CopySelected): hata fırlatmamalı ve panoyu değiştirmemeli
            var copyEx = Record.Exception(() => Assert.False(win.CopySelected()));
            Assert.Null(copyEx);
            Assert.Equal(initialClipboardPayload, clipboard.GetCircuitData());

            // Ctrl+X (CutSelected): panoyu değiştirmeden seçili teli silmeli
            Assert.True(win.CutSelected());
            Assert.Empty(win.Wires);
            Assert.Equal(2, win.Elements.Count);
            Assert.Equal(initialClipboardPayload, clipboard.GetCircuitData());

            // Sağ-tık bağlam menüsü doğrulaması: Undo ile teli geri getirip sağ-tık menüsünü kontrol et
            win.Undo();
            Assert.Single(win.Wires);
            var menu = win.HandleCanvasRightButtonDown(midPoint);
            Assert.NotNull(menu);
            var headers = menu!.Items.OfType<MenuItem>().Select(m => m.Header?.ToString()).ToList();
            Assert.Contains("Teli sil (Delete)", headers);
            Assert.Contains("Buradan tel çiz", headers);
        });
    }
}
