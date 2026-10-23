using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using CircuitAnalyzer.WPF;
using CircuitAnalyzer.WPF.Helpers;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// CircuitClipboard ve MainWindow düzenleyici (çoklu seçim, pano, uca tıklayarak tel çizme, geri al) testleri.
/// </summary>
[Collection(WpfUiCollection.Name)]
public class CircuitClipboardTests
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
    public void Copy_KeepsOnlyInternalWires()
    {
        var r1 = new Resistor { Id = "R1", Position = new Point(100, 100), Value = 1000 };
        var r2 = new Resistor { Id = "R2", Position = new Point(220, 100), Value = 2000 };
        var r3 = new Resistor { Id = "R3", Position = new Point(340, 100), Value = 3000 };

        var internalWire = new Wire(r1.Pins[1], r2.Pins[0]);
        var externalWire = new Wire(r2.Pins[1], r3.Pins[0]);

        // Yalnızca R1 ve R2 kopyalanıyor; R2-R3 arasındaki tel dışarıda kalmalı
        string payload = CircuitClipboard.Copy(new CircuitElement[] { r1, r2 }, new[] { internalWire, externalWire });
        var pasted = CircuitClipboard.Paste(payload, Array.Empty<string>(), new Point(40, 40));

        Assert.Equal(2, pasted.Elements.Count);
        Assert.Single(pasted.Wires);
        Assert.Equal("R1", pasted.Wires[0].StartPin.Owner?.Id);
        Assert.Equal("R2", pasted.Wires[0].EndPin.Owner?.Id);
    }

    [Fact]
    public void Paste_RenumbersIds_VacAndVNotConfused_GndNumbered()
    {
        var r1 = new Resistor { Id = "R1", Position = new Point(100, 100) };
        var r2 = new Resistor { Id = "R2", Position = new Point(200, 100) };
        var v1 = new VoltageSource { Id = "V1", Position = new Point(100, 200) };
        var vac1 = new AcVoltageSource { Id = "VAC1", Position = new Point(200, 200) };
        var i1 = new CurrentSource { Id = "I1", Position = new Point(300, 200) };
        var iac1 = new AcCurrentSource { Id = "IAC1", Position = new Point(400, 200) };
        var gnd1 = new GroundElement { Id = "GND1", Position = new Point(100, 300) };

        string payload = CircuitClipboard.Copy(
            new CircuitElement[] { r1, r2, v1, vac1, i1, iac1, gnd1 },
            Array.Empty<Wire>());

        // Mevcut devrede R1, R2, V1, VAC5, I2, IAC4, GND1 var
        var existingIds = new[] { "R1", "R2", "V1", "VAC5", "I2", "IAC4", "GND1" };
        var pasted = CircuitClipboard.Paste(payload, existingIds, new Point(40, 40));

        var ids = pasted.Elements.Select(e => e.Id).ToList();
        Assert.Contains("R3", ids);
        Assert.Contains("R4", ids);
        // V1 mevcutken VAC5 yüzünden V6 olmamalı -> V2 olmalı
        Assert.Contains("V2", ids);
        Assert.Contains("VAC6", ids);
        // I2 mevcutken IAC4 yüzünden I5 olmamalı -> I3 olmalı
        Assert.Contains("I3", ids);
        Assert.Contains("IAC5", ids);
        Assert.Contains("GND2", ids);
    }

    [Fact]
    public void Paste_PositionsShiftedAndSnappedToGrid()
    {
        var r1 = new Resistor { Id = "R1", Position = new Point(100, 120) };
        string payload = CircuitClipboard.Copy(new[] { r1 }, Array.Empty<Wire>());

        // Izgaraya tam oturmayan bir ofset (33, 47) -> (133, 167) -> Snap(20) ile (140, 160) olmalı
        var pasted = CircuitClipboard.Paste(payload, new[] { "R1" }, new Point(33, 47));
        Assert.Single(pasted.Elements);
        Assert.Equal(GridHelper.Snap(133), pasted.Elements[0].Position.X);
        Assert.Equal(GridHelper.Snap(167), pasted.Elements[0].Position.Y);
    }

    [Fact]
    public void Paste_ProbeTargetRemappedWhenCopied_KeptOtherwise()
    {
        var r1 = new Resistor { Id = "R1", Position = new Point(100, 100) };
        var probeCopiedTarget = new TestProbe
        {
            Id = "VP1",
            Position = new Point(140, 100),
            Type = ProbeType.Voltage,
            TargetElementId = "R1"
        };
        var probeExternalTarget = new TestProbe
        {
            Id = "VP2",
            Position = new Point(180, 100),
            Type = ProbeType.Current,
            TargetElementId = "R2"
        };

        string payload = CircuitClipboard.Copy(
            new CircuitElement[] { r1, probeCopiedTarget, probeExternalTarget },
            Array.Empty<Wire>());

        var existingIds = new[] { "R1", "R2", "VP1", "VP2" };
        var pasted = CircuitClipboard.Paste(payload, existingIds, new Point(40, 40));

        var newR = pasted.Elements.OfType<Resistor>().Single();
        Assert.Equal("R3", newR.Id);

        var probes = pasted.Elements.OfType<TestProbe>().ToList();
        Assert.Equal(2, probes.Count);

        var remappedProbe = probes.Single(p => p.Type == ProbeType.Voltage);
        var keptProbe = probes.Single(p => p.Type == ProbeType.Current);

        Assert.Equal("VP3", remappedProbe.Id);
        Assert.Equal("R3", remappedProbe.TargetElementId);

        Assert.Equal("VP4", keptProbe.Id);
        Assert.Equal("R2", keptProbe.TargetElementId);
    }

    [Fact]
    public void Paste_TwoConsecutivePastesNeverCollide()
    {
        var r1 = new Resistor { Id = "R1", Position = new Point(100, 100) };
        var r2 = new Resistor { Id = "R2", Position = new Point(200, 100) };
        var w = new Wire(r1.Pins[1], r2.Pins[0]);

        string payload = CircuitClipboard.Copy(new CircuitElement[] { r1, r2 }, new[] { w });
        var allIds = new HashSet<string>(StringComparer.Ordinal) { "R1", "R2" };

        var firstPaste = CircuitClipboard.Paste(payload, allIds, new Point(40, 40));
        foreach (var el in firstPaste.Elements)
        {
            Assert.True(allIds.Add(el.Id), $"İlk yapıştırmada çakışan ID: {el.Id}");
        }

        var secondPaste = CircuitClipboard.Paste(payload, allIds, new Point(80, 80));
        foreach (var el in secondPaste.Elements)
        {
            Assert.True(allIds.Add(el.Id), $"İkinci yapıştırmada çakışan ID: {el.Id}");
        }

        Assert.Equal(new[] { "R3", "R4" }, firstPaste.Elements.Select(e => e.Id).ToArray());
        Assert.Equal(new[] { "R5", "R6" }, secondPaste.Elements.Select(e => e.Id).ToArray());
    }

    [Fact]
    public void RoundTrip_AllElementTypes_PreservesProperties()
    {
        var elements = new CircuitElement[]
        {
            new Resistor { Id = "R1", Position = new Point(40, 40), Value = 4700, Rotation = 90 },
            new Capacitor { Id = "C1", Position = new Point(120, 40), Value = 22e-6, Rotation = 180 },
            new Inductor { Id = "L1", Position = new Point(200, 40), Value = 15e-3, Rotation = 270 },
            new ImpedanceElement { Id = "Z1", Position = new Point(280, 40), Impedance = ComplexValue.FromRectangular(10, 5), Rotation = 90 },
            new VoltageSource { Id = "V1", Position = new Point(40, 140), Value = 24, Rotation = 90 },
            new AcVoltageSource { Id = "VAC1", Position = new Point(120, 140), Amplitude = 120, Phase = 30, Frequency = 60, Rotation = 180 },
            new CurrentSource { Id = "I1", Position = new Point(200, 140), Value = 0.25, Rotation = 270 },
            new AcCurrentSource { Id = "IAC1", Position = new Point(280, 140), Amplitude = 2.5, Phase = -45, Rotation = 90 },
            new GroundElement { Id = "GND1", Position = new Point(40, 240), Rotation = 90 },
            new TestProbe { Id = "VP1", Position = new Point(120, 240), Type = ProbeType.Voltage, TargetElementId = "R1", Rotation = 90 },
        };

        string payload = CircuitClipboard.Copy(elements, Array.Empty<Wire>());
        var pasted = CircuitClipboard.Paste(payload, elements.Select(e => e.Id), new Point(20, 20));

        Assert.Equal(elements.Length, pasted.Elements.Count);

        var r = pasted.Elements.OfType<Resistor>().Single();
        Assert.Equal("R2", r.Id);
        Assert.Equal(4700, r.Value);
        Assert.Equal(90, r.Rotation);

        var c = pasted.Elements.OfType<Capacitor>().Single();
        Assert.Equal("C2", c.Id);
        Assert.Equal(22e-6, c.Value, 10);
        Assert.Equal(180, c.Rotation);

        var l = pasted.Elements.OfType<Inductor>().Single();
        Assert.Equal("L2", l.Id);
        Assert.Equal(15e-3, l.Value, 10);
        Assert.Equal(270, l.Rotation);

        var z = pasted.Elements.OfType<ImpedanceElement>().Single();
        Assert.Equal("Z2", z.Id);
        Assert.Equal(10, z.Impedance.Real);
        Assert.Equal(5, z.Impedance.Imaginary);
        Assert.Equal(90, z.Rotation);

        var v = pasted.Elements.OfType<VoltageSource>().Single();
        Assert.Equal("V2", v.Id);
        Assert.Equal(24, v.Value);
        Assert.Equal(90, v.Rotation);

        var vac = pasted.Elements.OfType<AcVoltageSource>().Single();
        Assert.Equal("VAC2", vac.Id);
        Assert.Equal(120, vac.Amplitude);
        Assert.Equal(30, vac.Phase);
        Assert.Equal(60, vac.Frequency);
        Assert.Equal(180, vac.Rotation);

        var i = pasted.Elements.OfType<CurrentSource>().Single();
        Assert.Equal("I2", i.Id);
        Assert.Equal(0.25, i.Value);
        Assert.Equal(270, i.Rotation);

        var iac = pasted.Elements.OfType<AcCurrentSource>().Single();
        Assert.Equal("IAC2", iac.Id);
        Assert.Equal(2.5, iac.Amplitude);
        Assert.Equal(-45, iac.Phase);
        Assert.Equal(90, iac.Rotation);

        var gnd = pasted.Elements.OfType<GroundElement>().Single();
        Assert.Equal("GND2", gnd.Id);
        Assert.Equal(90, gnd.Rotation);

        var vp = pasted.Elements.OfType<TestProbe>().Single();
        Assert.Equal("VP2", vp.Id);
        Assert.Equal(ProbeType.Voltage, vp.Type);
        Assert.Equal("R2", vp.TargetElementId);
        Assert.Equal(90, vp.Rotation);
    }

    [Fact]
    public void InMemoryClipboardWrapper_And_EmptyOrForeignClipboard_NoOp()
    {
        var clipboard = new InMemoryClipboardService();
        Assert.False(clipboard.ContainsCircuit());

        var emptyResult = CircuitClipboard.PasteFromClipboard(clipboard, Array.Empty<string>(), new Point(20, 20));
        Assert.Empty(emptyResult.Elements);

        // Yabancı metin varsa devre olarak kabul edilmemeli
        clipboard.SetData(CircuitClipboard.FormatName, "not a valid json circuit");
        clipboard.PlainText = "merhaba dünya";
        Assert.False(clipboard.ContainsCircuit());
        var foreignResult = CircuitClipboard.PasteFromClipboard(clipboard, Array.Empty<string>(), new Point(20, 20));
        Assert.Empty(foreignResult.Elements);

        // Geçerli devre kopyalandığında hem özel format hem düz metin yazılmalı
        var r1 = new Resistor { Id = "R1", Position = new Point(60, 60), Value = 330 };
        CircuitClipboard.CopyToClipboard(clipboard, new[] { r1 }, Array.Empty<Wire>());
        Assert.True(clipboard.ContainsCircuit());
        Assert.NotNull(clipboard.GetData(CircuitClipboard.FormatName));
        Assert.NotNull(clipboard.PlainText);

        var pasted = CircuitClipboard.PasteFromClipboard(clipboard, new[] { "R1" }, new Point(40, 40));
        Assert.Single(pasted.Elements);
        Assert.Equal("R2", pasted.Elements[0].Id);
    }

    [Fact]
    public void MainWindow_Duplicate_CopyPaste_Rotate_Delete_PinWire_SingleUndoStepEach()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow
            {
                ClipboardService = new InMemoryClipboardService()
            };

            // Örnek 0 yükle: V1, R1, R2, GND1 (4 eleman, 4 tel)
            win.LoadExample(ExampleCircuits.All[0]());
            int initialElements = win.Elements.Count;
            int initialWires = win.Wires.Count;
            Assert.False(win.IsDirty);
            Assert.False(win.UndoHistory.CanUndo);

            // 1) Tümünü seç + Çoğalt (Ctrl+D) -> sistem/bellek panosuna dokunmadan çoğaltmalı, tek geri-al adımı olmalı
            win.SelectAllElements();
            Assert.Equal(initialElements, win.Selection.Count);
            Assert.True(win.DuplicateSelected());
            Assert.False(win.ClipboardService.ContainsCircuit());
            Assert.Equal(initialElements * 2, win.Elements.Count);
            Assert.Equal(initialWires * 2, win.Wires.Count);
            Assert.True(win.IsDirty);
            Assert.True(win.UndoHistory.CanUndo);

            var idsAfterDup = win.Elements.Select(e => e.Id).ToHashSet();
            Assert.Contains("R3", idsAfterDup);
            Assert.Contains("R4", idsAfterDup);
            Assert.Contains("V2", idsAfterDup);
            Assert.Contains("GND2", idsAfterDup);

            // Tek Undo ile çoğaltma geri alınmalı
            win.Undo();
            Assert.Equal(initialElements, win.Elements.Count);
            Assert.Equal(initialWires, win.Wires.Count);

            // 2) Kopyala + Yapıştır (Ctrl+C / Ctrl+V) -> panoyu kullanmalı ve kademeli (cascade) ofset uygulamalı
            win.SelectAllElements();
            Assert.True(win.CopySelected());
            Assert.True(win.ClipboardService.ContainsCircuit());
            Assert.True(win.PasteFromClipboard());
            Assert.Equal(initialElements * 2, win.Elements.Count);

            // 3) Seçili grubu döndür (R) -> tek Undo adımı
            var r3 = win.Elements.First(e => e.Id == "R3");
            double rotBefore = r3.Rotation;
            win.RotateSelected();
            Assert.Equal((rotBefore + 90) % 360, win.Elements.First(e => e.Id == "R3").Rotation);
            win.Undo();
            Assert.Equal(rotBefore, win.Elements.First(e => e.Id == "R3").Rotation);

            // 4) Kes (Ctrl+X) -> tek Undo adımı
            win.Selection.Select(win.Elements.Where(e => e.Id is "R3" or "R4"), Array.Empty<Wire>());
            Assert.True(win.CutSelected());
            Assert.DoesNotContain(win.Elements, e => e.Id == "R3");
            win.Undo();
            Assert.Contains(win.Elements, e => e.Id == "R3");

            // 5) Normal modda uca tıklayarak tel çizme -> tamamlandığında normal moda dönmeli ve tek Undo adımı olmalı
            int wiresBeforePinWire = win.Wires.Count;
            var startPin = win.Elements.First(e => e.Id == "R1").Pins[0];
            var endPin = win.Elements.First(e => e.Id == "R3").Pins[0];
            win.StartPinWire(startPin);
            Assert.True(win.IsPinWiring);
            win.HandlePinWireClick(endPin.AbsolutePosition);
            Assert.False(win.IsPinWiring);
            Assert.Equal(wiresBeforePinWire + 1, win.Wires.Count);

            win.Undo();
            Assert.Equal(wiresBeforePinWire, win.Wires.Count);
        });
    }
}
