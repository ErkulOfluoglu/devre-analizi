using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Faz 1 + Faz 2 C# kapsamlı köşe durumu testleri:
/// - TurkishNumber.TryParse / TryParseSpice
/// - ElementEditorWindow.TryParseFieldValue
/// - ComplexValue.TryParse ve biçimlendirme gidiş-dönüş (BULGU-1 dahil)
/// - SwitchElement (NO/NC) ve SpdtSwitch netlist çıktısı ve döndürme pin konumları
/// - .devre (CircuitDocument) gidiş-dönüş (anahtarlar, bağımlı kaynaklar, ondalık nokta)
/// - TransientCurveCalculator.Evaluate
/// - NetlistBuilder (anahtarlı ve bağımlı kaynaklı devreler, Türkçe ek uyumu, doğrulama hataları)
/// </summary>
[Collection(WpfUiCollection.Name)]
public class Faz12Tests
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

    private static Dictionary<Pin, int> NodeMap(CircuitElement el, params int[] nodes)
    {
        var map = new Dictionary<Pin, int>();
        for (int i = 0; i < el.Pins.Count && i < nodes.Length; i++)
            map[el.Pins[i]] = nodes[i];
        return map;
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  1. TurkishNumber.TryParse / TryParseSpice ve TryParseFieldValue
    // ═══════════════════════════════════════════════════════════════════════

    [Theory]
    [InlineData("0", 0.0)]
    [InlineData("3,75", 3.75)]
    [InlineData("3.75", 3.75)]
    [InlineData("-12,5", -12.5)]
    [InlineData("  +4,7  ", 4.7)]
    [InlineData("1,5e-3", 0.0015)]
    [InlineData("2.5E+3", 2500.0)]
    public void TurkishNumber_TryParse_ValidInputs(string input, double expected)
    {
        Assert.True(TurkishNumber.TryParse(input, out double val));
        Assert.Equal(expected, val, precision: 9);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("1.000,5")]
    [InlineData("1,000.5")]
    [InlineData("3,,5")]
    [InlineData("3..5")]
    [InlineData("abc")]
    [InlineData("--5")]
    public void TurkishNumber_TryParse_InvalidInputs_ReturnsFalse(string input)
    {
        Assert.False(TurkishNumber.TryParse(input, out _));
    }

    [Theory]
    [InlineData("2,5k", 2500.0)]
    [InlineData("2,5K", 2500.0)]
    [InlineData("4,7 kΩ", 4700.0)]
    [InlineData("1,5M", 1_500_000.0)]
    [InlineData("1,5meg", 1_500_000.0)]
    [InlineData("1,5MEG", 1_500_000.0)]
    [InlineData("1,5m", 0.0015)]
    [InlineData("25 mH", 0.025)]
    [InlineData("4,7u", 4.7e-6)]
    [InlineData("4,7µ", 4.7e-6)]
    [InlineData("4,7µF", 4.7e-6)]
    [InlineData("10 µF", 10e-6)]
    [InlineData("100n", 100e-9)]
    [InlineData("22p", 22e-12)]
    [InlineData("10f", 10e-15)]
    [InlineData("2G", 2e9)]
    [InlineData("1T", 1e12)]
    [InlineData("-3,2mA", -0.0032)]
    public void TurkishNumber_TryParseSpice_ValidPrefixes(string input, double expected)
    {
        Assert.True(TurkishNumber.TryParseSpice(input, out double val));
        Assert.Equal(expected, val, precision: 12);
    }

    [Theory]
    // Kondansatör alanı (µF, unitScale = 1e6): düz sayı doğrudan µF (4,7), önekli sayı SI'dan µF'a (si * 1e6 = 4,7) çevrilir
    [InlineData("4,7", 1e6, 4.7)]
    [InlineData("4,7u", 1e6, 4.7)]
    [InlineData("4,7µF", 1e6, 4.7)]
    [InlineData("4700n", 1e6, 4.7)]
    [InlineData("0,0047m", 1e6, 4.7)]
    // Bobin alanı (mH, unitScale = 1e3): düz sayı doğrudan mH (25), önekli sayı SI'dan mH'ye (si * 1e3 = 25) çevrilir
    [InlineData("25", 1e3, 25.0)]
    [InlineData("25m", 1e3, 25.0)]
    [InlineData("25mH", 1e3, 25.0)]
    [InlineData("25000u", 1e3, 25.0)]
    // Direnç alanı (Ω, unitScale = 1.0)
    [InlineData("1,2k", 1.0, 1200.0)]
    [InlineData("2,5M", 1.0, 2_500_000.0)]
    [InlineData("500m", 1.0, 0.5)]
    public void ElementEditorWindow_TryParseFieldValue_ScalesCorrectly(
        string text, double unitScale, double expected)
    {
        Assert.True(CircuitAnalyzer.WPF.ElementEditorWindow.TryParseFieldValue(text, unitScale, out double val));
        Assert.Equal(expected, val, precision: 6);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  2. ComplexValue.TryParse ve Biçimlendirme Köşe Durumları
    // ═══════════════════════════════════════════════════════════════════════

    [Theory]
    [InlineData("3+j4", 3.0, 4.0)]
    [InlineData("3+j", 3.0, 1.0)]
    [InlineData("3-j", 3.0, -1.0)]
    [InlineData("3,5-j2,5", 3.5, -2.5)]
    [InlineData("-4,2+j1,8", -4.2, 1.8)]
    [InlineData("4+3j", 4.0, 3.0)]
    [InlineData("4,5-2,5j", 4.5, -2.5)]
    [InlineData("j12,5", 0.0, 12.5)]
    [InlineData("-j12,5", 0.0, -12.5)]
    [InlineData("12,5j", 0.0, 12.5)]
    [InlineData("-12,5j", 0.0, -12.5)]
    [InlineData("25,5", 25.5, 0.0)]
    [InlineData("-7,25", -7.25, 0.0)]
    public void ComplexValue_TryParse_RectangularInputs(string input, double expReal, double expImag)
    {
        Assert.True(ComplexValue.TryParse(input, out var cv));
        Assert.Equal(expReal, cv.Real, precision: 6);
        Assert.Equal(expImag, cv.Imaginary, precision: 6);
    }

    [Theory]
    // Analitik: 10∠60° → Real = 10·cos(60°) = 5, Imag = 10·sin(60°) = 5·√3 ≈ 8.660254
    [InlineData("10∠60", 5.0, 8.6602540378)]
    [InlineData("10∠-60°", 5.0, -8.6602540378)]
    [InlineData("10,0<-90", 0.0, -10.0)]
    [InlineData("5<36,86989765", 4.0, 3.0)]
    public void ComplexValue_TryParse_PolarInputs(string input, double expReal, double expImag)
    {
        Assert.True(ComplexValue.TryParse(input, out var cv));
        Assert.Equal(expReal, cv.Real, precision: 5);
        Assert.Equal(expImag, cv.Imaginary, precision: 5);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("abc")]
    [InlineData("10∠")]
    [InlineData("3++j4")]
    [InlineData("1.000,5+j2")]
    public void ComplexValue_TryParse_InvalidInputs_ReturnsFalse(string input)
    {
        Assert.False(ComplexValue.TryParse(input, out _));
    }

    [Fact]
    public void ComplexValue_ToRectangularString_NegativeImaginary_RoundTrip()
    {
        var original = ComplexValue.FromRectangular(50.0, -30.0);
        string formatted = original.ToRectangularString();
        Assert.True(ComplexValue.TryParse(formatted, out var parsed));
        Assert.Equal(50.0, parsed.Real, precision: 6);
        Assert.Equal(-30.0, parsed.Imaginary, precision: 6);
    }

    [Fact]
    public void ComplexValue_ToRectangularString_PureNegativeImaginary_RoundTrip()
    {
        var original = ComplexValue.FromRectangular(0.0, -30.0);
        string formatted = original.ToRectangularString();
        Assert.True(ComplexValue.TryParse(formatted, out var parsed));
        Assert.Equal(0.0, parsed.Real, precision: 6);
        Assert.Equal(-30.0, parsed.Imaginary, precision: 6);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  3. SwitchElement / SpdtSwitch Netlist, Pinler ve .devre Gidiş-Dönüş
    // ═══════════════════════════════════════════════════════════════════════

    [Fact]
    public void SwitchElement_And_SpdtSwitch_NetlistAndRotatedPins()
    {
        var swNo = new SwitchElement(SwitchMode.NormallyOpen) { Id = "S1" };
        var swNc = new SwitchElement(SwitchMode.NormallyClosed) { Id = "S2" };
        Assert.Equal("S1 1 2 NO", swNo.ToNetlistEntry(NodeMap(swNo, 1, 2)));
        Assert.Equal("S2 3 0 NC", swNc.ToNetlistEntry(NodeMap(swNc, 3, 0)));

        var spdt = new SpdtSwitch { Id = "S3", Position = new Point(100, 100), Rotation = 0 };
        Assert.Equal("S3 1 2 3 SPDT", spdt.ToNetlistEntry(NodeMap(spdt, 1, 2, 3)));
        Assert.Equal(3, spdt.Pins.Count);
        Assert.Equal(new Point(100, 120), spdt.Pins[0].AbsolutePosition);
        Assert.Equal(new Point(180, 100), spdt.Pins[1].AbsolutePosition);
        Assert.Equal(new Point(180, 140), spdt.Pins[2].AbsolutePosition);

        // 90°, 180° ve 270° döndürmede 3 pinin birbirinden farklı kalması
        foreach (double rot in new[] { 90.0, 180.0, 270.0 })
        {
            spdt.Rotation = rot;
            var pC = spdt.Pins[0].AbsolutePosition;
            var p1 = spdt.Pins[1].AbsolutePosition;
            var p2 = spdt.Pins[2].AbsolutePosition;
            Assert.NotEqual(pC, p1);
            Assert.NotEqual(pC, p2);
            Assert.NotEqual(p1, p2);
        }
    }

    [Fact]
    public void CircuitDocument_RoundTrip_PreservesSwitchesDependentSourcesAndInvariantDot()
    {
        RunOnSta(() =>
        {
            var c = new TestCircuits();
            var v1 = c.Add(new VoltageSource { Value = 12.5 }, "V1");
            var s1 = c.Add(new SwitchElement(SwitchMode.NormallyClosed) { Rotation = 90 }, "S1");
            var s2 = c.Add(new SpdtSwitch { Rotation = 180 }, "S2");
            var r1 = c.Add(new Resistor { Value = 1500.25 }, "R1");
            var c1 = c.Add(new Capacitor { Value = 4.7e-6 }, "C1");
            var dep = c.Add(new DependentSource(DependentSourceKind.Vccs)
            {
                ControlElementId = "R1",
                ControlReversed = true,
                Gain = 0.025
            }, "G1");
            var gnd = c.Add(new GroundElement(), "GND1");

            c.Wire(v1.Pins[0], s1.Pins[0]);
            c.Wire(s1.Pins[1], s2.Pins[0]);
            c.Wire(s2.Pins[1], r1.Pins[0]);
            c.Wire(s2.Pins[2], c1.Pins[0]);
            c.Wire(c1.Pins[1], dep.Pins[0]);
            c.Wire(dep.Pins[1], gnd.Pins[0]);
            c.Wire(r1.Pins[1], gnd.Pins[0]);
            c.Wire(v1.Pins[1], gnd.Pins[0]);

            var prevCulture = CultureInfo.CurrentCulture;
            try
            {
                CultureInfo.CurrentCulture = new CultureInfo("tr-TR");
                var doc = CircuitDocument.FromCircuit(c.Elements, c.Wires);
                string json = doc.ToJson();

                // JSON içinde ondalık ayırıcı nokta kalmalı
                Assert.Contains("12.5", json);
                Assert.Contains("1500.25", json);
                Assert.Contains("0.025", json);

                var loadedDoc = CircuitDocument.FromJson(json);
                var restored = loadedDoc.ToCircuit("RoundTrip");

                var rSw = Assert.Single(restored.Elements.OfType<SwitchElement>());
                Assert.Equal("S1", rSw.Id);
                Assert.Equal(SwitchMode.NormallyClosed, rSw.Mode);

                var rSpdt = Assert.Single(restored.Elements.OfType<SpdtSwitch>());
                Assert.Equal("S2", rSpdt.Id);
                Assert.Equal(180, rSpdt.Rotation);

                var rDep = Assert.Single(restored.Elements.OfType<DependentSource>());
                Assert.Equal(DependentSourceKind.Vccs, rDep.Kind);
                Assert.Equal("R1", rDep.ControlElementId);
                Assert.True(rDep.ControlReversed);
                Assert.Equal(0.025, rDep.Gain, precision: 9);

                var netOrig = NetlistBuilder.Build(c.Elements, c.Wires).Text;
                var netRestored = NetlistBuilder.Build(restored.Elements, restored.Wires).Text;
                Assert.Equal(netOrig, netRestored);
                Assert.Contains("G1 ", netRestored);
                Assert.Contains("V(-R1) 0.025", netRestored);
            }
            finally
            {
                CultureInfo.CurrentCulture = prevCulture;
            }
        });
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  4. TransientCurveCalculator.Evaluate Köşe Durumları
    // ═══════════════════════════════════════════════════════════════════════

    [Fact]
    public void TransientCurveCalculator_Evaluate_ChargingDischargingAndDiscontinuousJump()
    {
        // 1) Şarj (V_C: before=2 V, start=2 V, final=10 V, τ=0.01 s):
        //    t < 0 → 2 V; t = 0 → 2 V; t = τ → 10 + (2 - 10)·e⁻¹ ≈ 7.056964 V
        Assert.Equal(2.0, TransientCurveCalculator.Evaluate(2.0, 2.0, 10.0, 0.01, -0.005), precision: 9);
        Assert.Equal(2.0, TransientCurveCalculator.Evaluate(2.0, 2.0, 10.0, 0.01, 0.0), precision: 9);
        double expectedAtTau = 10.0 + (2.0 - 10.0) * Math.Exp(-1.0);
        Assert.Equal(expectedAtTau, TransientCurveCalculator.Evaluate(2.0, 2.0, 10.0, 0.01, 0.01), precision: 7);

        // 2) Süreksiz sıçrama (I_C: before=0 A, start=-0.012 A, final=0 A, τ=0.02 s):
        //    t < 0 → 0 A; t = 0⁺ → -0.012 A; t = 2τ → -0.012·e⁻²
        Assert.Equal(0.0, TransientCurveCalculator.Evaluate(0.0, -0.012, 0.0, 0.02, -1e-6), precision: 9);
        Assert.Equal(-0.012, TransientCurveCalculator.Evaluate(0.0, -0.012, 0.0, 0.02, 0.0), precision: 9);
        Assert.Equal(-0.012 * Math.Exp(-2.0), TransientCurveCalculator.Evaluate(0.0, -0.012, 0.0, 0.02, 0.04), precision: 9);

        // 3) τ <= 0 sınır durumu: t >= 0 için doğrudan Final dönmeli
        Assert.Equal(10.0, TransientCurveCalculator.Evaluate(2.0, 2.0, 10.0, 0.0, 0.0), precision: 9);
        Assert.Equal(10.0, TransientCurveCalculator.Evaluate(2.0, 2.0, 10.0, -1.0, 0.001), precision: 9);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  5. NetlistBuilder (Anahtarlar, Bağımlı Kaynak Doğrulaması, Türkçe Ekler)
    // ═══════════════════════════════════════════════════════════════════════

    [Theory]
    [InlineData("R1", "'in")]
    [InlineData("R2", "'nin")]
    [InlineData("R3", "'ün")]
    [InlineData("R4", "'ün")]
    [InlineData("R6", "'nın")]
    [InlineData("R9", "'un")]
    [InlineData("R10", "'un")]
    [InlineData("R20", "'nin")]
    [InlineData("R30", "'un")]
    [InlineData("R40", "'ın")]
    [InlineData("R50", "'nin")]
    [InlineData("R60", "'ın")]
    [InlineData("R70", "'in")]
    [InlineData("R80", "'in")]
    [InlineData("R90", "'ın")]
    [InlineData("R100", "'ün")]
    [InlineData("R0", "'ın")]
    public void NetlistBuilder_GenitiveSuffix_MatchesTurkishVowelHarmony(string id, string expected)
    {
        var dep = new DependentSource { Id = id, ControlElementId = "R99" };
        string? msg = NetlistBuilder.ValidateDependentSources(new CircuitElement[] { dep });
        Assert.Equal($"{id}{expected} kontrol ettiği R99 devrede yok", msg);
    }

    [Fact]
    public void NetlistBuilder_RejectsSwitchAsDependentControlElement_AndConflictingControlReversed()
    {
        // 1) Anahtar (SwitchElement ve SpdtSwitch) bağımlı kaynağın kontrol elemanı olamaz
        var swNo = new SwitchElement(SwitchMode.NormallyOpen) { Id = "S1" };
        var spdt = new SpdtSwitch { Id = "S2" };
        var depOnNo = new DependentSource(DependentSourceKind.Vcvs) { Id = "E1", ControlElementId = "S1", Gain = 2.0 };
        var depOnSpdt = new DependentSource(DependentSourceKind.Cccs) { Id = "F1", ControlElementId = "S2", Gain = 3.0 };

        string? msgNo = NetlistBuilder.ValidateDependentSources(new CircuitElement[] { swNo, depOnNo });
        Assert.NotNull(msgNo);
        Assert.Contains("S1", msgNo);

        string? msgSpdt = NetlistBuilder.ValidateDependentSources(new CircuitElement[] { spdt, depOnSpdt });
        Assert.NotNull(msgSpdt);
        Assert.Contains("S2", msgSpdt);

        // 2) Aynı kontrol elemanını iki bağımlı kaynak zıt yönlerle (ControlReversed) kontrol edemez
        var ra = new Resistor { Id = "R1", Value = 100 };
        var d1 = new DependentSource(DependentSourceKind.Vccs) { Id = "G1", ControlElementId = "R1", ControlReversed = false, Gain = 0.01 };
        var d2 = new DependentSource(DependentSourceKind.Vccs) { Id = "G2", ControlElementId = "R1", ControlReversed = true, Gain = 0.02 };

        string? msgConflict = NetlistBuilder.ValidateDependentSources(new CircuitElement[] { ra, d1, d2 });
        Assert.NotNull(msgConflict);
        Assert.Contains("V_R1", msgConflict);
        Assert.Contains("ters yönlerde", msgConflict);
    }
}
