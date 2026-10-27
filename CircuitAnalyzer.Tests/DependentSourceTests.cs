using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using System.Windows.Shapes;
using CircuitAnalyzer.WPF;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Bağımlı (kontrollü) kaynaklar: netlist satırı, dosya biçimi, pano, doğrulama,
/// kontrol işaretleri ve düzenleyici. Python arka ucu gerekmez.
/// </summary>
[Collection(WpfUiCollection.Name)]
public class DependentSourceTests
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

    private static Dictionary<Pin, int> NodeMap(CircuitElement el, int n1, int n2)
        => new() { [el.Pins[0]] = n1, [el.Pins[1]] = n2 };

    /// <summary>R1–R2–GND bölücüsü ve R2'yi kontrol eden E1 (bir de R3 yükü); E1 yüklü tuval örneği.</summary>
    private static ExampleCircuit ControlledCircuit(bool withControlTarget = true)
    {
        var c = new ExampleCircuit { Name = "Bağımlı", Description = "" };
        var v1 = c.Add(new VoltageSource { Value = 10 }, "V1", 60, 200, 90);
        var r1 = c.Add(new Resistor { Value = 100 }, "R1", 120, 160);
        var r2 = c.Add(new Resistor { Value = 200 }, "R2", 160, 200, 90);
        var gnd = c.Add(new GroundElement(), "GND1", 180, 300);
        c.Connect(v1.Pins[0], r1.Pins[0]);
        c.Connect(gnd.Pins[0], r2.Pins[1]);
        c.Connect(v1.Pins[1], r2.Pins[1]);

        var e1 = c.Add(new DependentSource(DependentSourceKind.Vcvs)
        {
            Gain = 3,
            ControlElementId = withControlTarget ? "R2" : "R9",
        }, "E1", 420, 160);
        var r3 = c.Add(new Resistor { Value = 1000 }, "R3", 520, 200, 90);
        var gnd2 = c.Add(new GroundElement(), "GND2", 470, 300);
        c.Connect(e1.Pins[1], r3.Pins[0]);
        c.Connect(gnd2.Pins[0], e1.Pins[0]);
        c.Connect(gnd2.Pins[0], r3.Pins[1]);
        return c;
    }

    // ═══════════════════════════════════════════════════════
    //  NETLIST
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void Netlist_AllFourKinds_FollowTheContractSyntax()
    {
        var e = new DependentSource(DependentSourceKind.Vcvs) { Id = "E1", Gain = 3, ControlElementId = "R2" };
        var g = new DependentSource(DependentSourceKind.Vccs) { Id = "G1", Gain = 0.5, ControlElementId = "R1" };
        var h = new DependentSource(DependentSourceKind.Ccvs) { Id = "H1", Gain = 2000, ControlElementId = "R3" };
        var f = new DependentSource(DependentSourceKind.Cccs) { Id = "F1", Gain = 50, ControlElementId = "R1", ControlReversed = true };

        Assert.Equal("E1 3 0 V(R2) 3", e.ToNetlistEntry(NodeMap(e, 3, 0)));
        Assert.Equal("G1 1 2 V(R1) 0.5", g.ToNetlistEntry(NodeMap(g, 1, 2)));
        Assert.Equal("H1 4 5 I(R3) 2000", h.ToNetlistEntry(NodeMap(h, 4, 5)));
        Assert.Equal("F1 0 4 I(-R1) 50", f.ToNetlistEntry(NodeMap(f, 0, 4)));
    }

    [Fact]
    public void Netlist_ReversedVoltageControl_AndNegativeGain()
    {
        var e = new DependentSource(DependentSourceKind.Vcvs)
        {
            Id = "E2", Gain = -2.5, ControlElementId = "R2", ControlReversed = true
        };
        Assert.Equal("E2 1 0 V(-R2) -2.5", e.ToNetlistEntry(NodeMap(e, 1, 0)));
    }

    [Fact]
    public void Netlist_GainUsesInvariantDot_EvenUnderTurkishCulture()
    {
        var old = Thread.CurrentThread.CurrentCulture;
        try
        {
            Thread.CurrentThread.CurrentCulture = new System.Globalization.CultureInfo("tr-TR");
            var g = new DependentSource(DependentSourceKind.Vccs) { Id = "G1", Gain = 0.002, ControlElementId = "R1" };
            Assert.Equal("G1 1 2 V(R1) 0.002", g.ToNetlistEntry(NodeMap(g, 1, 2)));
        }
        finally
        {
            Thread.CurrentThread.CurrentCulture = old;
        }
    }

    [Fact]
    public void Netlist_RotatedSource_StillUsesPin1AsPositive_ContractExample()
    {
        var c = new TestCircuits();
        var v1 = c.Add(new VoltageSource { Value = 10 }, "V1");
        var r1 = c.Add(new Resistor { Value = 2 }, "R1");
        var r2 = c.Add(new Resistor { Value = 4 }, "R2");
        var e1 = c.Add(new DependentSource(DependentSourceKind.Vcvs) { Gain = 3, ControlElementId = "R2" }, "E1");
        e1.Rotation = 90;
        var r3 = c.Add(new Resistor { Value = 6 }, "R3");
        var gnd = c.Add(new GroundElement(), "GND1");

        c.Wire(v1.Pins[0], r1.Pins[0]);
        c.Wire(r1.Pins[1], r2.Pins[0]);
        c.Wire(r2.Pins[1], gnd.Pins[0]);
        c.Wire(v1.Pins[1], gnd.Pins[0]);
        c.Wire(e1.Pins[0], r3.Pins[0]);   // E1 n+ -> düğüm 3
        c.Wire(e1.Pins[1], gnd.Pins[0]);  // E1 n- -> toprak
        c.Wire(r3.Pins[1], gnd.Pins[0]);

        var result = NetlistBuilder.Build(c.Elements, c.Wires);
        var lines = result.Text.Split('\n').Select(l => l.TrimEnd('\r')).ToList();

        Assert.Contains("E1 3 0 V(R2) 3", lines);
        Assert.Contains("R2 2 0 4", lines);
        Assert.False(result.HasAcSource);
    }

    // ═══════════════════════════════════════════════════════
    //  KAYDET / AÇ
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void Document_RoundTrip_KeepsKindGainControlAndReversed()
    {
        var r1 = new Resistor { Id = "R1", Position = new Point(100, 100), Value = 100 };
        var kinds = new[]
        {
            new DependentSource(DependentSourceKind.Vcvs) { Id = "E1", Gain = 3, ControlElementId = "R1" },
            new DependentSource(DependentSourceKind.Vccs) { Id = "G1", Gain = 0.5, ControlElementId = "R1", ControlReversed = true },
            new DependentSource(DependentSourceKind.Ccvs) { Id = "H1", Gain = -2000, ControlElementId = "R1" },
            new DependentSource(DependentSourceKind.Cccs) { Id = "F1", Gain = 50, ControlElementId = "", Rotation = 270 },
        };
        double y = 200;
        foreach (var k in kinds)
        {
            k.Position = new Point(200, y);
            y += 100;
        }

        var elements = new List<CircuitElement> { r1 };
        elements.AddRange(kinds);
        var json = CircuitDocument.FromCircuit(elements, Array.Empty<Wire>()).ToJson();

        var restored = CircuitDocument.FromJson(json).ToCircuit("Test").Elements.OfType<DependentSource>().ToList();
        Assert.Equal(4, restored.Count);

        for (int i = 0; i < kinds.Length; i++)
        {
            Assert.Equal(kinds[i].Id, restored[i].Id);
            Assert.Equal(kinds[i].Kind, restored[i].Kind);
            Assert.Equal(kinds[i].Gain, restored[i].Gain);
            Assert.Equal(kinds[i].ControlElementId, restored[i].ControlElementId);
            Assert.Equal(kinds[i].ControlReversed, restored[i].ControlReversed);
            Assert.Equal(kinds[i].Position, restored[i].Position);
            Assert.Equal(kinds[i].Rotation, restored[i].Rotation);
        }
    }

    [Fact]
    public void Document_OldFileWithoutDependentSources_LoadsUnchanged_AndAddsNoNewFields()
    {
        var oldJson = """
        {
          "format": "devre-analizi",
          "version": 1,
          "elements": [
            { "type": "V", "id": "V1", "x": 60, "y": 200, "rotation": 90, "value": 10 },
            { "type": "R", "id": "R1", "x": 120, "y": 160, "rotation": 0, "value": 100 },
            { "type": "GND", "id": "GND1", "x": 180, "y": 300, "rotation": 0 }
          ],
          "wires": []
        }
        """;

        var circuit = CircuitDocument.FromJson(oldJson).ToCircuit("Eski");
        Assert.Equal(3, circuit.Elements.Count);
        Assert.DoesNotContain(circuit.Elements, e => e is DependentSource);

        // Kaydedince bağımlı kaynağa özgü alanlar eklenmez
        string saved = CircuitDocument.FromCircuit(circuit.Elements, circuit.Wires).ToJson();
        Assert.DoesNotContain("\"kind\"", saved);
        Assert.DoesNotContain("\"gain\"", saved);
        Assert.DoesNotContain("\"control", saved);
    }

    [Fact]
    public void Document_DependentRecordWithMissingFields_FallsBackToDefaults()
    {
        var json = """
        {
          "format": "devre-analizi",
          "version": 1,
          "elements": [
            { "type": "DEP", "id": "E1", "x": 100, "y": 100, "rotation": 0 },
            { "type": "DEP", "id": "H1", "x": 100, "y": 200, "rotation": 0, "kind": "Ccvs", "gain": 4 },
            { "type": "DEP", "id": "G1", "x": 100, "y": 300, "rotation": 0, "kind": "Bilinmeyen" }
          ],
          "wires": []
        }
        """;

        var deps = CircuitDocument.FromJson(json).ToCircuit("Eksik").Elements.OfType<DependentSource>().ToList();

        Assert.Equal(DependentSourceKind.Vcvs, deps[0].Kind);
        Assert.Equal(1, deps[0].Gain);
        Assert.Equal("", deps[0].ControlElementId);
        Assert.False(deps[0].ControlReversed);

        Assert.Equal(DependentSourceKind.Ccvs, deps[1].Kind);
        Assert.Equal(4, deps[1].Gain);

        Assert.Equal(DependentSourceKind.Vcvs, deps[2].Kind); // tanınmayan tür -> varsayılan
    }

    // ═══════════════════════════════════════════════════════
    //  PANO
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void Clipboard_ControlPastedInSameBatch_IsRemappedToNewId()
    {
        var r2 = new Resistor { Id = "R2", Position = new Point(100, 100), Value = 200 };
        var e1 = new DependentSource(DependentSourceKind.Vcvs)
        {
            Id = "E1", Position = new Point(300, 100), Gain = 3, ControlElementId = "R2", ControlReversed = true
        };

        string payload = CircuitClipboard.Copy(new CircuitElement[] { r2, e1 });
        var pasted = CircuitClipboard.Paste(payload, new[] { "R1", "R2", "E1" }, new Point(40, 40));

        var newR = pasted.Elements.OfType<Resistor>().Single();
        var newE = pasted.Elements.OfType<DependentSource>().Single();
        Assert.Equal("R3", newR.Id);
        Assert.Equal("E2", newE.Id);
        Assert.Equal("R3", newE.ControlElementId);
        Assert.True(newE.ControlReversed);
        Assert.Equal(3, newE.Gain);
    }

    [Fact]
    public void Clipboard_ControlNotInBatch_KeepsPointingAtOriginal()
    {
        var e1 = new DependentSource(DependentSourceKind.Cccs)
        {
            Id = "F1", Position = new Point(300, 100), Gain = 50, ControlElementId = "R2"
        };

        string payload = CircuitClipboard.Copy(new CircuitElement[] { e1 });
        var pasted = CircuitClipboard.Paste(payload, new[] { "R1", "R2", "F1" }, new Point(40, 40));

        var copy = Assert.IsType<DependentSource>(Assert.Single(pasted.Elements));
        Assert.Equal("F2", copy.Id);
        Assert.Equal("R2", copy.ControlElementId);
    }

    [Fact]
    public void Clipboard_PrefixesAreRenumberedPerKind()
    {
        var sources = new[]
        {
            new DependentSource(DependentSourceKind.Vcvs) { Id = "E1", Position = new Point(0, 0) },
            new DependentSource(DependentSourceKind.Vccs) { Id = "G1", Position = new Point(0, 100) },
            new DependentSource(DependentSourceKind.Ccvs) { Id = "H1", Position = new Point(0, 200) },
            new DependentSource(DependentSourceKind.Cccs) { Id = "F1", Position = new Point(0, 300) },
        };

        string payload = CircuitClipboard.Copy(sources);
        var pasted = CircuitClipboard.Paste(payload, new[] { "E1", "G1", "H1", "F1", "GND1", "VAC1" }, new Point(20, 20));

        Assert.Equal(new[] { "E2", "G2", "H2", "F2" }, pasted.Elements.Select(e => e.Id).ToArray());
        Assert.Equal(new[]
        {
            DependentSourceKind.Vcvs, DependentSourceKind.Vccs, DependentSourceKind.Ccvs, DependentSourceKind.Cccs
        }, pasted.Elements.Cast<DependentSource>().Select(d => d.Kind).ToArray());
    }

    // ═══════════════════════════════════════════════════════
    //  DOĞRULAMA
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void Validation_NoControlSelected_ReportsTurkishMessage()
    {
        var e1 = new DependentSource(DependentSourceKind.Vcvs) { Id = "E1" };
        Assert.Equal("E1 için kontrol eden eleman seçilmemiş",
            NetlistBuilder.ValidateDependentSources(new CircuitElement[] { e1 }));
    }

    [Fact]
    public void Validation_ControlMissingFromCircuit_ReportsTurkishMessage()
    {
        var r1 = new Resistor { Id = "R1" };
        var e1 = new DependentSource(DependentSourceKind.Vcvs) { Id = "E1", ControlElementId = "R2" };
        Assert.Equal("E1'in kontrol ettiği R2 devrede yok",
            NetlistBuilder.ValidateDependentSources(new CircuitElement[] { r1, e1 }));

        // Tamlayan eki kimliğin okunuşuna uyar (iki -> nin, üç -> ün, altı -> nın, dokuz -> un)
        foreach (var (id, suffix) in new[] { ("E2", "'nin"), ("G3", "'ün"), ("H6", "'nın"), ("F9", "'un"), ("E10", "'un") })
        {
            var dep = new DependentSource { Id = id, ControlElementId = "R9" };
            Assert.Equal($"{id}{suffix} kontrol ettiği R9 devrede yok",
                NetlistBuilder.ValidateDependentSources(new CircuitElement[] { dep }));
        }
    }

    [Fact]
    public void Validation_SelfControlGroundAndProbe_AreRejected_ValidControlPasses()
    {
        var gnd = new GroundElement { Id = "GND1" };
        var probe = new TestProbe { Id = "VP1" };
        var r1 = new Resistor { Id = "R1" };

        var self = new DependentSource { Id = "E1", ControlElementId = "E1" };
        Assert.Contains("kendi kendini", NetlistBuilder.ValidateDependentSources(new CircuitElement[] { self })!);

        var onGround = new DependentSource { Id = "E1", ControlElementId = "GND1" };
        Assert.NotNull(NetlistBuilder.ValidateDependentSources(new CircuitElement[] { gnd, onGround }));

        var onProbe = new DependentSource { Id = "E1", ControlElementId = "VP1" };
        Assert.NotNull(NetlistBuilder.ValidateDependentSources(new CircuitElement[] { probe, onProbe }));

        // Başka bir bağımlı kaynak da kontrol elemanı olabilir (sözleşme)
        var chain1 = new DependentSource(DependentSourceKind.Vcvs) { Id = "E1", ControlElementId = "R1" };
        var chain2 = new DependentSource(DependentSourceKind.Ccvs) { Id = "H1", ControlElementId = "E1" };
        Assert.Null(NetlistBuilder.ValidateDependentSources(new CircuitElement[] { r1, chain1, chain2 }));
    }

    [Fact]
    public void Validation_SameQuantityInOppositeDirections_IsRejected()
    {
        var r2 = new Resistor { Id = "R2" };
        var e1 = new DependentSource(DependentSourceKind.Vcvs) { Id = "E1", ControlElementId = "R2" };
        var g1 = new DependentSource(DependentSourceKind.Vccs) { Id = "G1", ControlElementId = "R2", ControlReversed = true };
        var message = NetlistBuilder.ValidateDependentSources(new CircuitElement[] { r2, e1, g1 });
        Assert.Equal("E1 ve G1 aynı V_R2 büyüklüğünü ters yönlerde kullanıyor; birinde “Yönü ters çevir” seçimini değiştirin",
            message);

        // Aynı yön ya da farklı büyüklük (V_R2 ile I_R2) sorun değildir
        g1.ControlReversed = false;
        var h1 = new DependentSource(DependentSourceKind.Ccvs) { Id = "H1", ControlElementId = "R2", ControlReversed = true };
        Assert.Null(NetlistBuilder.ValidateDependentSources(new CircuitElement[] { r2, e1, g1, h1 }));
    }

    [Fact]
    public void MainWindow_Validation_ShowsDialogAndBlocksSolve_WhenControlIsMissing()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow();

            // Geçerli devre: uyarı yok
            win.LoadExample(ControlledCircuit(withControlTarget: true));
            Assert.True(win.ValidateDependentSources());
            Assert.False(win.DialogOverlay.IsOpen);

            // Kontrol edilen eleman devrede yok
            win.LoadExample(ControlledCircuit(withControlTarget: false));
            Assert.False(win.ValidateDependentSources());
            Assert.True(win.DialogOverlay.IsOpen);
            var body = Assert.IsType<TextBlock>(win.DialogOverlay.Body);
            Assert.Contains("E1'in kontrol ettiği R9 devrede yok", body.Text);
            win.DialogOverlay.Close(animate: false);

            // Kontrol hiç seçilmemiş
            var e1 = win.Elements.OfType<DependentSource>().Single();
            e1.ControlElementId = "";
            Assert.False(win.ValidateDependentSources());
            Assert.Contains("E1 için kontrol eden eleman seçilmemiş", ((TextBlock)win.DialogOverlay.Body!).Text);
        });
    }

    // ═══════════════════════════════════════════════════════
    //  ARAÇ KUTUSU / SAYAÇLAR / GERİ AL
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void MainWindow_AddDependentSources_NumbersPerKind_AndSurvivesReload()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow();

            var e1 = win.AddDependentSource(DependentSourceKind.Vcvs);
            var e2 = win.AddDependentSource(DependentSourceKind.Vcvs);
            var g1 = win.AddDependentSource(DependentSourceKind.Vccs);
            var h1 = win.AddDependentSource(DependentSourceKind.Ccvs);
            var f1 = win.AddDependentSource(DependentSourceKind.Cccs);

            Assert.Equal(new[] { "E1", "E2", "G1", "H1", "F1" }, new[] { e1.Id, e2.Id, g1.Id, h1.Id, f1.Id });
            Assert.True(win.UndoHistory.CanUndo);

            // Geri al: son eklenen kalkar, sayaç yeniden senkronlanır
            win.Undo();
            Assert.DoesNotContain(win.Elements, e => e.Id == "F1");
            var again = win.AddDependentSource(DependentSourceKind.Cccs);
            Assert.Equal("F1", again.Id);
        });
    }

    [Fact]
    public void MainWindow_ControlMarkers_FollowTheControlledElement_ThroughDeleteRotateAndUndo()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow();
            win.LoadExample(ControlledCircuit());

            // R2'yi kontrol eden gerilim: "+", "−" ve "V_R2" etiketi
            Assert.Equal(3, win.ControlMarkerVisuals.Count);
            Assert.All(win.ControlMarkerVisuals, m => Assert.True(win.CircuitCanvas.Children.Contains(m)));

            // Döndürmede işaretler yeniden kurulur (aynı sayıda, yeni nesneler)
            var before = win.ControlMarkerVisuals.ToList();
            var r2 = win.Elements.First(e => e.Id == "R2");
            win.Selection.Select(new[] { r2 }, Array.Empty<Wire>());
            win.RotateSelected();
            Assert.Equal(3, win.ControlMarkerVisuals.Count);
            Assert.DoesNotContain(win.ControlMarkerVisuals, m => before.Contains(m));
            Assert.All(before, m => Assert.False(win.CircuitCanvas.Children.Contains(m)));

            // Kontrol edilen eleman silinince işaret kalmaz
            win.Selection.Select(new[] { r2 }, Array.Empty<Wire>());
            win.DeleteSelected();
            Assert.Empty(win.ControlMarkerVisuals);

            // Geri al -> işaretler geri gelir
            win.Undo();
            Assert.Equal(3, win.ControlMarkerVisuals.Count);

            // Kontrol elemanı belirtilmeyen bağımlı kaynak işaret çizmez
            win.Elements.OfType<DependentSource>().Single().ControlElementId = "";
            win.LoadExample(ControlledCircuit(withControlTarget: false));
            Assert.Empty(win.ControlMarkerVisuals);
        });
    }

    [Fact]
    public void MainWindow_DuplicateBoth_RemapsControl_DuplicateSourceAlone_KeepsOriginal()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow { ClipboardService = new InMemoryClipboardService() };
            win.LoadExample(ControlledCircuit());

            // Yalnızca E1'i çoğalt -> kopya R2'yi göstermeye devam eder
            win.Selection.Select(new[] { win.Elements.First(e => e.Id == "E1") }, Array.Empty<Wire>());
            Assert.True(win.DuplicateSelected());
            var e2 = win.Elements.OfType<DependentSource>().Single(d => d.Id == "E2");
            Assert.Equal("R2", e2.ControlElementId);

            // R2 ve E1 birlikte çoğaltılırsa yeni kopya yeni R'yi gösterir
            win.Selection.Select(
                win.Elements.Where(e => e.Id is "R2" or "E1"),
                Array.Empty<Wire>());
            Assert.True(win.DuplicateSelected());
            var e3 = win.Elements.OfType<DependentSource>().Single(d => d.Id == "E3");
            var newR = win.Elements.OfType<Resistor>().Single(r => r.Id == e3.ControlElementId);
            Assert.NotEqual("R2", newR.Id);

            // Kopya için de işaret çizilir: R2 (E1, E2) + yeni R (E3)
            Assert.Equal(6, win.ControlMarkerVisuals.Count);
        });
    }

    // ═══════════════════════════════════════════════════════
    //  GÖRSEL: ETİKET, SEMBOL, KONTROL İŞARETLERİ
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void Label_ShowsGainAndControl_WithTurkishComma_NoMinusWhenReversed()
    {
        var a = new DependentSource(DependentSourceKind.Vcvs) { Gain = 3, ControlElementId = "R2" };
        var b = new DependentSource(DependentSourceKind.Cccs) { Gain = 0.5, ControlElementId = "R2" };
        var c = new DependentSource(DependentSourceKind.Ccvs) { Gain = -1.5, ControlElementId = "R1", ControlReversed = true };
        var d = new DependentSource(DependentSourceKind.Vccs) { Gain = 2 };

        Assert.Equal("3·V_R2", a.LabelText);
        Assert.Equal("0,5·I_R2", b.LabelText);
        // Ters kontrolde eksi yazılmaz: R1 üzerindeki ok ters çizilir, I_R1 ona göre tanımlıdır
        Assert.Equal("−1,5·I_R1", c.LabelText);
        Assert.Equal("2·V_?", d.LabelText);
    }

    [Fact]
    public void Visual_IsDiamond80x40_WithSubscriptControlLabel()
    {
        RunOnSta(() =>
        {
            foreach (DependentSourceKind kind in Enum.GetValues<DependentSourceKind>())
            {
                var src = new DependentSource(kind) { Gain = 3, ControlElementId = "R2", ControlReversed = true };
                var canvas = Assert.IsType<Canvas>(src.CreateVisual());

                Assert.Equal(80, canvas.Width);
                Assert.Equal(40, canvas.Height);
                Assert.Equal(80, src.VisualWidth);
                Assert.Equal(2, src.Pins.Count);

                var diamond = canvas.Children.OfType<Polygon>().Single();
                Assert.Equal(4, diamond.Points.Count);

                var label = canvas.Children.OfType<TextBlock>().First(t => t.Inlines.Count == 3);
                var runs = label.Inlines.OfType<Run>().ToList();
                // Ters kontrolde de eksi yok: yön, kontrol elemanındaki işaretlerle gösterilir
                Assert.Equal(src.ControlLetter, runs[1].Text);
                Assert.Equal("R2", runs[2].Text);
                Assert.Equal(BaselineAlignment.Subscript, runs[2].BaselineAlignment);
            }
        });
    }

    [Fact]
    public void ControlMarkers_Voltage_PutPlusNearPin1AndMinusNearPin2_SwappedWhenReversed()
    {
        RunOnSta(() =>
        {
            var r = new Resistor { Id = "R2", Position = new Point(200, 200) }; // pinler (200,220) ve (280,220)

            var normal = ControlMarkers.Create(r, voltage: true, reversed: false);
            Assert.Equal(3, normal.Count);
            var plus = (TextBlock)normal[0];
            var minus = (TextBlock)normal[1];
            Assert.Equal("+", plus.Text);
            Assert.Equal("−", minus.Text);
            Assert.True(Canvas.GetLeft(plus) < Canvas.GetLeft(minus));
            Assert.True(Canvas.GetLeft(plus) < 240 && Canvas.GetLeft(minus) > 240);

            var reversed = ControlMarkers.Create(r, voltage: true, reversed: true);
            var plusR = (TextBlock)reversed[0];
            var minusR = (TextBlock)reversed[1];
            Assert.True(Canvas.GetLeft(plusR) > Canvas.GetLeft(minusR));

            var name = (TextBlock)normal[2];
            Assert.Equal("V", ((Run)name.Inlines.First()).Text);
            Assert.Equal("R2", ((Run)name.Inlines.Last()).Text);
            Assert.Equal(BaselineAlignment.Subscript, ((Run)name.Inlines.Last()).BaselineAlignment);
        });
    }

    [Fact]
    public void ControlMarkers_Current_DrawArrowFromPin1ToPin2_ReversedPointsBack()
    {
        RunOnSta(() =>
        {
            var r = new Resistor { Id = "R1", Position = new Point(100, 100) };

            static (Point Start, Point End) Shaft(UIElement arrow)
            {
                var geometry = (PathGeometry)((Path)arrow).Data;
                var figure = geometry.Figures[0];
                return (figure.StartPoint, ((LineSegment)figure.Segments[0]).Point);
            }

            var normal = ControlMarkers.Create(r, voltage: false, reversed: false);
            Assert.Equal(2, normal.Count);
            var (s1, e1) = Shaft(normal[0]);
            Assert.True(e1.X > s1.X);
            Assert.Equal(s1.Y, e1.Y, 6);

            var reversed = ControlMarkers.Create(r, voltage: false, reversed: true);
            var (s2, e2) = Shaft(reversed[0]);
            Assert.True(e2.X < s2.X);

            // Eleman 90° döndürülünce ok da dikey olur: pin 1 üstte, pin 2 altta -> ok aşağı bakar
            r.Rotation = 90;
            var vertical = ControlMarkers.Create(r, voltage: false, reversed: false);
            var (s3, e3) = Shaft(vertical[0]);
            Assert.True(e3.Y > s3.Y);
            Assert.Equal(s3.X, e3.X, 6);
        });
    }

    // ═══════════════════════════════════════════════════════
    //  DÜZENLEYİCİ
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void Editor_ControlList_HasOnlyOtherTwoTerminalElements()
    {
        var r1 = new Resistor { Id = "R1" };
        var r2 = new Resistor { Id = "R2" };
        var e1 = new DependentSource(DependentSourceKind.Vcvs) { Id = "E1", ControlElementId = "R2", Gain = 4 };
        var h1 = new DependentSource(DependentSourceKind.Ccvs) { Id = "H1" };
        var gnd = new GroundElement { Id = "GND1" };
        var probe = new TestProbe { Id = "VP1" };
        var junction = new JunctionElement { Id = "J1" };

        var choices = ElementEditorWindow.BuildControlChoices(
            e1, new CircuitElement[] { r1, r2, e1, h1, gnd, probe, junction });

        // Kendisi, GND, prob ve bağlantı noktası listede yok; başka bağımlı kaynak var
        Assert.Equal(new[] { "(seçilmedi)", "R1", "R2", "H1" }, choices.Labels);
        Assert.Equal(new[] { "", "R1", "R2", "H1" }, choices.Ids);
        Assert.Equal("R2", choices.Ids[choices.SelectedIndex]);

        // Hiç seçilmemişse "(seçilmedi)" işaretli gelir
        h1.ControlElementId = "";
        Assert.Equal(0, ElementEditorWindow.BuildControlChoices(h1, new CircuitElement[] { r1, h1 }).SelectedIndex);
    }

    [Fact]
    public void Editor_StaleControlId_IsShownAsMissing()
    {
        var r1 = new Resistor { Id = "R1" };
        var f1 = new DependentSource(DependentSourceKind.Cccs) { Id = "F1", ControlElementId = "R7" };

        var choices = ElementEditorWindow.BuildControlChoices(f1, new CircuitElement[] { r1, f1 });

        Assert.Equal("R7 (devrede yok)", choices.Labels[choices.SelectedIndex]);
        Assert.Equal("R7", choices.Ids[choices.SelectedIndex]);
    }

    [Fact]
    public void GainUnits_AndNames_MatchTheContract()
    {
        Assert.Equal("V/V", DependentSource.GainUnitOf(DependentSourceKind.Vcvs));
        Assert.Equal("A/V (S)", DependentSource.GainUnitOf(DependentSourceKind.Vccs));
        Assert.Equal("V/A (Ω)", DependentSource.GainUnitOf(DependentSourceKind.Ccvs));
        Assert.Equal("A/A", DependentSource.GainUnitOf(DependentSourceKind.Cccs));

        Assert.Equal("Gerilim Kontrollü Akım Kaynağı (GKAK)", DependentSource.NameOf(DependentSourceKind.Vccs));
        Assert.Equal("Akım Kontrollü Gerilim Kaynağı (AKGK)", DependentSource.NameOf(DependentSourceKind.Ccvs));
        Assert.Equal("Akım Kontrollü Akım Kaynağı (AKAK)", DependentSource.NameOf(DependentSourceKind.Cccs));
    }

}
