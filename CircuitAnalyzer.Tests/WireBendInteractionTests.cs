using System;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Input;
using CircuitAnalyzer.WPF;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Manuel tel köşesi çizim etkileşimi testleri: boş tuvale tıklayarak köşe ekleme,
/// Backspace ile son köşeyi geri alma, R ile canlı kol yönünü çevirme (seçili elemanı döndürmeden),
/// Esc ile iptal, tek/çift uçlu eleman taşımada köşe davranışı ve çözücü netlist eşdeğerliği.
/// </summary>
[Collection(WpfUiCollection.Name)]
public class WireBendInteractionTests
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

    [Fact]
    public void DrawWireWithTwoEmptyClicks_CreatesSingleWireWithExplicitCorners_AndSingleUndoRemovesIt()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow { ClipboardService = new InMemoryClipboardService() };
            var circuit = new ExampleCircuit { Name = "BendDraw" };
            // R1 @ (100,100): Pin1 = (180, 120)
            // R2 @ (360,180): Pin0 = (360, 200)
            var r1 = circuit.Add(new Resistor { Value = 100 }, "R1", 100, 100);
            var r2 = circuit.Add(new Resistor { Value = 200 }, "R2", 360, 180);
            win.LoadExample(circuit);
            Assert.Empty(win.Wires);
            Assert.False(win.IsDirty);

            win.StartPinWire(r1.Pins[1]);
            Assert.True(win.IsPinWiring);
            Assert.Equal(MainWindow.DrawingWireStatusText, win.TxtStatus.Text);

            // 1. boş tık: (240, 60) -> (180,120)'den L olduğu için örtük köşe (240,120) + (240,60) eklenmeli
            win.HandlePinWireClick(new Point(240, 60));
            Assert.True(win.IsPinWiring);

            // 2. boş tık: (320, 60) -> yatay kol, yalnızca (320, 60) eklenmeli
            win.HandlePinWireClick(new Point(320, 60));
            Assert.True(win.IsPinWiring);

            // Hedef pine tıkla: R2.Pin0 (360, 200)
            win.HandlePinWireClick(r2.Pins[0].AbsolutePosition);
            Assert.False(win.IsPinWiring);
            Assert.True(win.IsDirty);

            var wire = Assert.Single(win.Wires);
            Assert.Contains(new Point(240, 120), wire.Waypoints);
            Assert.Contains(new Point(240, 60), wire.Waypoints);
            Assert.Contains(new Point(320, 60), wire.Waypoints);
            Assert.Equal(new[] { new Point(240, 120), new Point(240, 60), new Point(320, 60) }, wire.Waypoints);

            // Tek geri-al (Undo) adımı teli tamamen kaldırmalı
            win.Undo();
            Assert.Empty(win.Wires);
        });
    }

    [Fact]
    public void Backspace_RemovesLastWaypointAndItsImplicitCorner_AndNoOpWhenEmpty()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow { ClipboardService = new InMemoryClipboardService() };
            var circuit = new ExampleCircuit { Name = "BendBackspace" };
            var r1 = circuit.Add(new Resistor { Value = 100 }, "R1", 100, 100); // Pin1 = (180, 120)
            var r2 = circuit.Add(new Resistor { Value = 200 }, "R2", 360, 180); // Pin0 = (360, 200)
            win.LoadExample(circuit);

            win.StartPinWire(r1.Pins[1]);

            // Köşe yokken Backspace hiçbir şey yapmamalı ve çizim sürmeli
            win.HandleKeyDown(Key.Back);
            Assert.True(win.IsPinWiring);

            // (240, 60) tıklaması örtük köşe (240,120) + (240,60) olarak 2 nokta ekler
            win.HandlePinWireClick(new Point(240, 60));
            // (320, 60) tıklaması 1 nokta ekler
            win.HandlePinWireClick(new Point(320, 60));

            // İlk Backspace -> (320, 60) kalkar, (240,120) ve (240,60) kalır
            win.HandleKeyDown(Key.Back);
            // İkinci Backspace -> (240,60) ve birlikte eklenen örtük köşesi (240,120) tek seferde kalkar
            win.HandleKeyDown(Key.Back);

            win.HandlePinWireClick(r2.Pins[0].AbsolutePosition);
            var wire = Assert.Single(win.Wires);
            Assert.Empty(wire.Waypoints);
        });
    }

    [Fact]
    public void KeyR_FlipsLiveLegAndStoredLastLegVerticalFirst_WithoutRotatingSelectedElement()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow { ClipboardService = new InMemoryClipboardService() };
            var circuit = new ExampleCircuit { Name = "BendFlipR" };
            var r1 = circuit.Add(new Resistor { Value = 100 }, "R1", 100, 100); // Pin1 = (180, 120)
            var r2 = circuit.Add(new Resistor { Value = 200 }, "R2", 320, 200); // Pin0 = (320, 220)
            win.LoadExample(circuit);

            // R1 seçiliyken tel çizimine başla; R tuşu R1'i döndürmemeli
            win.Selection.Select(r1);
            Assert.Equal(0, r1.Rotation);

            win.StartPinWire(r1.Pins[1]);
            win.HandleCanvasMouseMove(new Point(260, 60));

            // R tuşu canlı kolu dikey-önce'ye çevirir
            win.HandleKeyDown(Key.R);
            Assert.Equal(0, r1.Rotation);
            Assert.True(win.LiveLegVerticalFirst);

            // (260, 60) boş tıklaması dikey-önce örtük köşeyle (180, 60) -> (260, 60) kaydedilmeli
            win.HandlePinWireClick(new Point(260, 60));

            // Son ayak için tekrar R'ye bas -> false (yatay-önce) ve tekrar R'ye bas -> true (dikey-önce)
            win.HandleKeyDown(Key.R);
            Assert.False(win.LiveLegVerticalFirst);
            win.HandleKeyDown(Key.R);
            Assert.True(win.LiveLegVerticalFirst);
            Assert.Equal(0, r1.Rotation);

            win.HandlePinWireClick(r2.Pins[0].AbsolutePosition);

            var wire = Assert.Single(win.Wires);
            Assert.True(wire.LastLegVerticalFirst);
            Assert.Equal(new[] { new Point(180, 60), new Point(260, 60) }, wire.Waypoints);
            Assert.Equal(0, r1.Rotation);
        });
    }

    [Fact]
    public void Escape_WhileDrawingWithWaypoints_CancelsAndCreatesNoWire()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow { ClipboardService = new InMemoryClipboardService() };
            var circuit = new ExampleCircuit { Name = "BendEsc" };
            var r1 = circuit.Add(new Resistor { Value = 100 }, "R1", 100, 100);
            var r2 = circuit.Add(new Resistor { Value = 200 }, "R2", 320, 200);
            win.LoadExample(circuit);

            win.StartPinWire(r1.Pins[1]);
            win.HandlePinWireClick(new Point(240, 60));
            win.HandlePinWireClick(new Point(300, 60));
            Assert.True(win.IsPinWiring);

            win.HandleKeyDown(Key.Escape);

            Assert.False(win.IsPinWiring);
            Assert.Empty(win.Wires);
            Assert.False(win.IsDirty);
        });
    }

    [Fact]
    public void MovingOneEndElementKeepsWaypoints_MovingBothEndsTranslatesWaypoints()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow { ClipboardService = new InMemoryClipboardService() };
            var circuit = new ExampleCircuit { Name = "BendMove" };
            var r1 = circuit.Add(new Resistor { Value = 100 }, "R1", 100, 100); // Pin1 = (180, 120)
            var r2 = circuit.Add(new Resistor { Value = 200 }, "R2", 340, 180); // Pin0 = (340, 200)
            win.LoadExample(circuit);

            win.StartPinWire(r1.Pins[1]);
            win.HandlePinWireClick(new Point(240, 60));
            win.HandlePinWireClick(new Point(300, 60));
            win.HandlePinWireClick(r2.Pins[0].AbsolutePosition);

            var wire = Assert.Single(win.Wires);
            var initialWaypoints = wire.Waypoints.ToList();

            // 1) Yalnız R1'i (+20, +40) sürükle -> ara köşeler sabit kalmalı
            Point r1Grab = new(120, 110);
            win.HandleElementLeftButtonDown(r1, r1Grab);
            win.HandleCanvasMouseMove(new Point(140, 150));
            win.HandleCanvasLeftButtonUp(new Point(140, 150));

            Assert.Equal(new Point(120, 140), r1.Position);
            Assert.Equal(initialWaypoints, wire.Waypoints);

            // 2) Lastik bant (rubber-band) ile hem R1 hem R2'yi seçip (+40, +20) sürükle -> tüm köşeler (+40, +20) kaymalı
            win.HandleCanvasLeftButtonDown(new Point(40, 40));
            win.HandleCanvasMouseMove(new Point(500, 300));
            win.HandleCanvasLeftButtonUp(new Point(500, 300));
            Assert.Equal(2, win.Selection.Count);

            Point bothGrab = new(140, 150);
            win.HandleElementLeftButtonDown(r1, bothGrab);
            win.HandleCanvasMouseMove(new Point(180, 170));
            win.HandleCanvasLeftButtonUp(new Point(180, 170));

            var expectedTranslated = initialWaypoints
                .Select(p => new Point(p.X + 40, p.Y + 20))
                .ToList();
            Assert.Equal(expectedTranslated, wire.Waypoints);
        });
    }

    [Fact]
    public void NetlistBuilder_CircuitDrawnWithBends_ProducesIdenticalNetlistAsCircuitWithoutBends()
    {
        RunOnSta(() =>
        {
            ExampleCircuit MakeBase(out AcVoltageSource vac, out Resistor r1, out Inductor l1, out GroundElement gnd)
            {
                var c = new ExampleCircuit { Name = "BendNetlist" };
                vac = c.Add(new AcVoltageSource { Amplitude = 10, Frequency = 50 }, "VAC1", 80, 180, 90);
                r1 = c.Add(new Resistor { Value = 100 }, "R1", 180, 100);
                l1 = c.Add(new Inductor { Value = 0.1 }, "L1", 360, 100);
                gnd = c.Add(new GroundElement(), "GND1", 260, 280);
                c.Connect(r1.Pins[0], vac.Pins[0]);
                c.Connect(vac.Pins[1], gnd.Pins[0]);
                c.Connect(l1.Pins[1], gnd.Pins[0]);
                return c;
            }

            var straightCircuit = MakeBase(out _, out var r1A, out var l1A, out _);
            straightCircuit.Connect(r1A.Pins[1], l1A.Pins[0]);

            var bentCircuit = MakeBase(out _, out var r1B, out var l1B, out _);
            var win = new MainWindow { ClipboardService = new InMemoryClipboardService() };
            win.LoadExample(bentCircuit);

            win.StartPinWire(r1B.Pins[1]);
            win.HandlePinWireClick(new Point(280, 60));
            win.HandlePinWireClick(new Point(340, 60));
            win.HandleKeyDown(Key.R);
            win.HandlePinWireClick(l1B.Pins[0].AbsolutePosition);

            DateTime fixedTime = new(2026, 10, 26, 12, 0, 0);
            var nlStraight = NetlistBuilder.Build(straightCircuit.Elements, straightCircuit.Wires, fixedTime);
            var nlBent = NetlistBuilder.Build(win.Elements, win.Wires, fixedTime);

            Assert.Equal(nlStraight.NodeCount, nlBent.NodeCount);
            Assert.Equal(nlStraight.Text, nlBent.Text);
        });
    }
}
