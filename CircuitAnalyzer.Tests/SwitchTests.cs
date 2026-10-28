using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows;
using System.Windows.Input;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Faz 2 Anahtar elemanları (tek konumlu NO/NC, iki konumlu SPDT) ve
/// geçici durum (Transient) netlist, kayıt, pano ve arayüz testleri.
/// </summary>
[Collection(WpfUiCollection.Name)]
public class SwitchTests
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

    private static void PumpDispatcher(Func<bool> condition, int timeoutMs = 2000)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        while (!condition() && sw.ElapsedMilliseconds < timeoutMs)
        {
            var frame = new System.Windows.Threading.DispatcherFrame();
            System.Windows.Threading.Dispatcher.CurrentDispatcher.BeginInvoke(
                System.Windows.Threading.DispatcherPriority.Background,
                new Action(() => frame.Continue = false));
            System.Windows.Threading.Dispatcher.PushFrame(frame);
            Thread.Sleep(10);
        }
    }

    private static Dictionary<Pin, int> NodeMap(CircuitElement el, params int[] nodes)
    {
        var map = new Dictionary<Pin, int>();
        for (int i = 0; i < el.Pins.Count && i < nodes.Length; i++)
        {
            map[el.Pins[i]] = nodes[i];
        }
        return map;
    }

    // ═══════════════════════════════════════════════════════
    //  1. NETLIST SATIRLARI (NO / NC / SPDT / DÖNDÜRME / BAĞLANTI)
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void SwitchElement_ToNetlistEntry_NormallyOpen_FollowsContract()
    {
        var sw = new SwitchElement(SwitchMode.NormallyOpen) { Id = "S1" };
        var entry = sw.ToNetlistEntry(NodeMap(sw, 1, 2));
        Assert.Equal("S1 1 2 NO", entry);
    }

    [Fact]
    public void SwitchElement_ToNetlistEntry_NormallyClosed_FollowsContract()
    {
        var sw = new SwitchElement(SwitchMode.NormallyClosed) { Id = "S2" };
        var entry = sw.ToNetlistEntry(NodeMap(sw, 3, 0));
        Assert.Equal("S2 3 0 NC", entry);
    }

    [Fact]
    public void SpdtSwitch_ToNetlistEntry_FollowsContract()
    {
        var spdt = new SpdtSwitch { Id = "S1" };
        var entry = spdt.ToNetlistEntry(NodeMap(spdt, 1, 2, 3));
        Assert.Equal("S1 1 2 3 SPDT", entry);
    }

    [Fact]
    public void NetlistBuilder_Build_CircuitWithNoSwitch_EmitsCorrectLine()
    {
        var c = new TestCircuits();
        var v1 = c.Add(new VoltageSource { Value = 12 }, "V1");
        var r1 = c.Add(new Resistor { Value = 1000 }, "R1");
        var s1 = c.Add(new SwitchElement(SwitchMode.NormallyOpen), "S1");
        var c1 = c.Add(new Capacitor { Value = 10e-6 }, "C1");
        var gnd = c.Add(new GroundElement(), "GND1");

        // V1(+) -> S1 pin 0, S1 pin 1 -> R1 pin 0, R1 pin 1 -> C1 pin 0, C1 pin 1 -> GND, V1(-) -> GND
        c.Wire(v1.Pins[0], s1.Pins[0]);
        c.Wire(s1.Pins[1], r1.Pins[0]);
        c.Wire(r1.Pins[1], c1.Pins[0]);
        c.Wire(c1.Pins[1], gnd.Pins[0]);
        c.Wire(v1.Pins[1], gnd.Pins[0]);

        var result = NetlistBuilder.Build(c.Elements, c.Wires);
        var lines = result.Text.Split('\n').Select(l => l.TrimEnd('\r')).ToList();

        Assert.Contains(lines, l => l.StartsWith("S1 ") && l.EndsWith(" NO"));
    }

    [Fact]
    public void NetlistBuilder_Build_CircuitWithNcSwitch_EmitsCorrectLine()
    {
        var c = new TestCircuits();
        var v1 = c.Add(new VoltageSource { Value = 12 }, "V1");
        var s1 = c.Add(new SwitchElement(SwitchMode.NormallyClosed), "S1");
        var r1 = c.Add(new Resistor { Value = 500 }, "R1");
        var gnd = c.Add(new GroundElement(), "GND1");

        c.Wire(v1.Pins[0], s1.Pins[0]);
        c.Wire(s1.Pins[1], r1.Pins[0]);
        c.Wire(r1.Pins[1], gnd.Pins[0]);
        c.Wire(v1.Pins[1], gnd.Pins[0]);

        var result = NetlistBuilder.Build(c.Elements, c.Wires);
        var lines = result.Text.Split('\n').Select(l => l.TrimEnd('\r')).ToList();

        Assert.Contains(lines, l => l.StartsWith("S1 ") && l.EndsWith(" NC"));
    }

    [Fact]
    public void NetlistBuilder_Build_CircuitWithSpdtSwitch_EmitsCorrectLine()
    {
        var c = new TestCircuits();
        var v1 = c.Add(new VoltageSource { Value = 10 }, "V1");
        var v2 = c.Add(new VoltageSource { Value = 5 }, "V2");
        var spdt = c.Add(new SpdtSwitch(), "S1");
        var r1 = c.Add(new Resistor { Value = 100 }, "R1");
        var gnd = c.Add(new GroundElement(), "GND1");

        // Pin 0 (c) -> R1 pin 0
        // Pin 1 (a) -> V1 pin 0
        // Pin 2 (b) -> V2 pin 0
        c.Wire(spdt.Pins[0], r1.Pins[0]);
        c.Wire(spdt.Pins[1], v1.Pins[0]);
        c.Wire(spdt.Pins[2], v2.Pins[0]);
        c.Wire(r1.Pins[1], gnd.Pins[0]);
        c.Wire(v1.Pins[1], gnd.Pins[0]);
        c.Wire(v2.Pins[1], gnd.Pins[0]);

        var result = NetlistBuilder.Build(c.Elements, c.Wires);
        var lines = result.Text.Split('\n').Select(l => l.TrimEnd('\r')).ToList();

        var spdtLine = lines.FirstOrDefault(l => l.StartsWith("S1 "));
        Assert.NotNull(spdtLine);
        Assert.EndsWith(" SPDT", spdtLine);

        // Satır formatı: S1 <düğüm_c> <düğüm_a> <düğüm_b> SPDT
        var tokens = spdtLine.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        Assert.Equal(5, tokens.Length);
        Assert.Equal("S1", tokens[0]);
        Assert.Equal("SPDT", tokens[4]);
    }

    [Fact]
    public void NetlistBuilder_RotatedSwitches_KeepCorrectNodeConnectivity()
    {
        var c = new TestCircuits();
        var v1 = c.Add(new VoltageSource { Value = 24 }, "V1");
        var s1 = c.Add(new SwitchElement(SwitchMode.NormallyOpen) { Rotation = 90 }, "S1");
        var r1 = c.Add(new Resistor { Value = 1000 }, "R1");
        var gnd = c.Add(new GroundElement(), "GND1");

        c.Wire(v1.Pins[0], s1.Pins[0]);
        c.Wire(s1.Pins[1], r1.Pins[0]);
        c.Wire(r1.Pins[1], gnd.Pins[0]);
        c.Wire(v1.Pins[1], gnd.Pins[0]);

        var result = NetlistBuilder.Build(c.Elements, c.Wires);
        var lines = result.Text.Split('\n').Select(l => l.TrimEnd('\r')).ToList();

        Assert.Contains(lines, l => l.StartsWith("S1 ") && l.EndsWith(" NO"));
    }

    // ═══════════════════════════════════════════════════════
    //  2. DOSYA KAYDETME / YÜKLEME (ROUND TRIP)
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void CircuitDocument_RoundTrip_WithNoNcAndSpdtSwitches()
    {
        RunOnSta(() =>
        {
            var c = new TestCircuits();
            var v1 = c.Add(new VoltageSource { Value = 12 }, "V1");
            var s1 = c.Add(new SwitchElement(SwitchMode.NormallyOpen) { Rotation = 90 }, "S1");
            var s2 = c.Add(new SwitchElement(SwitchMode.NormallyClosed), "S2");
            var s3 = c.Add(new SpdtSwitch { Rotation = 180 }, "S3");
            var r1 = c.Add(new Resistor { Value = 220 }, "R1");
            var gnd = c.Add(new GroundElement(), "GND1");

            c.Wire(v1.Pins[0], s1.Pins[0]);
            c.Wire(s1.Pins[1], s2.Pins[0]);
            c.Wire(s2.Pins[1], s3.Pins[0]);
            c.Wire(s3.Pins[1], r1.Pins[0]);
            c.Wire(r1.Pins[1], gnd.Pins[0]);
            c.Wire(v1.Pins[1], gnd.Pins[0]);

            var originalNetlist = NetlistBuilder.Build(c.Elements, c.Wires).Text;

            var doc = CircuitDocument.FromCircuit(c.Elements, c.Wires);
            string json = doc.ToJson();

            var loadedDoc = CircuitDocument.FromJson(json);
            var restoredCircuit = loadedDoc.ToCircuit("Test");

            Assert.Equal(c.Elements.Count, restoredCircuit.Elements.Count);
            Assert.Equal(c.Wires.Count, restoredCircuit.Wires.Count);

            var loadedS1 = restoredCircuit.Elements.OfType<SwitchElement>().FirstOrDefault(e => e.Id == "S1");
            Assert.NotNull(loadedS1);
            Assert.Equal(SwitchMode.NormallyOpen, loadedS1.Mode);
            Assert.Equal(90, loadedS1.Rotation);

            var loadedS2 = restoredCircuit.Elements.OfType<SwitchElement>().FirstOrDefault(e => e.Id == "S2");
            Assert.NotNull(loadedS2);
            Assert.Equal(SwitchMode.NormallyClosed, loadedS2.Mode);

            var loadedS3 = restoredCircuit.Elements.OfType<SpdtSwitch>().FirstOrDefault(e => e.Id == "S3");
            Assert.NotNull(loadedS3);
            Assert.Equal(180, loadedS3.Rotation);
            Assert.Equal(3, loadedS3.Pins.Count);

            var restoredNetlist = NetlistBuilder.Build(restoredCircuit.Elements, restoredCircuit.Wires).Text;
            Assert.Equal(originalNetlist, restoredNetlist);
        });
    }

    // ═══════════════════════════════════════════════════════
    //  3. PANO KOPYALA / YAPIŞTIR (CIRCUIT CLIPBOARD)
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void CircuitClipboard_CopyPaste_Switches_RenumbersCorrectly()
    {
        var s1 = new SwitchElement(SwitchMode.NormallyOpen) { Id = "S1", Position = new Point(100, 100) };
        var s2 = new SpdtSwitch { Id = "S2", Position = new Point(200, 100) };
        var r1 = new Resistor { Id = "R1", Position = new Point(300, 100) };
        var wire = new Wire(s1.Pins[1], s2.Pins[0]);

        string payload = CircuitClipboard.Copy(new CircuitElement[] { s1, s2, r1 }, new[] { wire });

        var existingIds = new[] { "S1", "S2", "R1" };
        var pasted = CircuitClipboard.Paste(payload, existingIds, new Point(40, 40));

        Assert.Equal(3, pasted.Elements.Count);
        Assert.Single(pasted.Wires);

        var pastedIds = pasted.Elements.Select(e => e.Id).ToList();
        Assert.Contains("S3", pastedIds);
        Assert.Contains("S4", pastedIds);
        Assert.Contains("R2", pastedIds);

        var pastedWire = pasted.Wires[0];
        Assert.Equal("S3", pastedWire.StartPin.Owner?.Id);
        Assert.Equal("S4", pastedWire.EndPin.Owner?.Id);
    }

    // ═══════════════════════════════════════════════════════
    //  4. PENCERE İÇİ OVERLAY (BÜYÜT / ESC İLE KAPATMA)
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void PlotOverlay_Show_OpensInWindowWithoutCreatingNewWindow_AndEscCloses()
    {
        RunOnSta(() =>
        {
            var hostWindow = new Window
            {
                Width = 800,
                Height = 600,
                WindowStartupLocation = WindowStartupLocation.Manual,
                Left = -20000,
                Top = -20000,
                ShowActivated = false
            };

            var overlay = new PlotOverlay();
            hostWindow.Content = overlay;
            hostWindow.Show();

            // Overlay'in ayrı bir Window türevi OLMADIĞINI doğrula (pencere içi katmandır)
            Assert.False((object)overlay is Window);
            Assert.True(overlay is FrameworkElement);

            int? initialWindowCount = Application.Current?.Windows.Count;

            var testData = new TransientAnalysisDto
            {
                Element = "C1",
                Kind = "C",
                Tau = 0.001,
                Rth = 1000,
                Quantities = new List<TransientQuantityDto>
                {
                    new() { Id = "V_C1", Label = "V_C1", Unit = "V", Before = 0, Start = 0, Final = 10 },
                    new() { Id = "I_C1", Label = "I_C1", Unit = "A", Before = 0, Start = 0.01, Final = 0 }
                }
            };

            // 1. Overlay aç
            overlay.Show(testData, animate: false);
            Assert.True(overlay.IsOpen);

            // Ayrı bir pencere açılmadığını doğrula
            if (initialWindowCount.HasValue && Application.Current != null)
            {
                Assert.Equal(initialWindowCount.Value, Application.Current.Windows.Count);
            }

            // 2. Esc tuşunu simüle et
            var source = PresentationSource.FromVisual(overlay);
            Assert.NotNull(source);

            var escArgs = new KeyEventArgs(Keyboard.PrimaryDevice, source, 0, Key.Escape)
            {
                RoutedEvent = UIElement.PreviewKeyDownEvent
            };
            overlay.RaiseEvent(escArgs);
            PumpDispatcher(() => !overlay.IsOpen);

            Assert.False(overlay.IsOpen);
            Assert.True(escArgs.Handled);

            hostWindow.Close();
        });
    }
}
