using System;
using System.Linq;
using System.Text.RegularExpressions;
using CircuitAnalyzer.WPF;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Fable denetiminde bulunan çökme ve veri kaybı durumları: sonlu olmayan sayılar,
/// "10 F" birimi, aynı eleman adı, düzenleme penceresinde İptal ve bozuk dosya.
/// </summary>
public class DataSafetyTests
{
    [Theory]
    [InlineData("NaN")]
    [InlineData("Infinity")]
    [InlineData("-Infinity")]
    [InlineData("1e999")]
    [InlineData("∞")]
    public void TurkishNumber_RejectsNonFiniteValues(string text)
    {
        Assert.False(TurkishNumber.TryParse(text, out _));
        Assert.False(TurkishNumber.TryParseSpice(text, out _));
        Assert.False(ElementEditorWindow.TryParseFieldValue(text, 1e6, out _));
    }

    [Theory]
    [InlineData("10 F", 10)]
    [InlineData("10F", 10)]
    [InlineData("2,2 farad", 2.2)]
    [InlineData("10 fF", 10e-15)]
    [InlineData("30°", 30)]
    [InlineData("-45°", -45)]
    [InlineData("47 mF", 0.047)]
    [InlineData("100µF", 100e-6)]
    public void TurkishNumber_ReadsUnitsAsUnits(string text, double expected)
    {
        Assert.True(TurkishNumber.TryParseSpice(text, out double val));
        Assert.Equal(expected, val, Math.Abs(expected) * 1e-12 + 1e-30);
    }

    [Fact]
    public void CapacitorField_TenFarad_IsNotFemto()
    {
        // Kondansatör alanı µF biriminde: "10 F" = 10 farad = 1e7 µF
        Assert.True(ElementEditorWindow.TryParseFieldValue("10 F", 1e6, out double val));
        Assert.Equal(1e7, val, 1e-3);
    }

    [Theory]
    [InlineData("NaN")]
    [InlineData("1e999")]
    [InlineData("10∠1e999")]
    [InlineData("1e999+j5")]
    [InlineData("5+j1e999")]
    public void ComplexValue_RejectsNonFiniteValues(string text)
    {
        Assert.False(ComplexValue.TryParse(text, out _));
    }

    [Fact]
    public void ComplexValue_StillReadsNormalValues()
    {
        Assert.True(ComplexValue.TryParse("10∠30°", out var cv));
        Assert.Equal(10, cv.Magnitude, 1e-9);
        Assert.True(ComplexValue.TryParse("50+j30", out cv));
        Assert.Equal(30, cv.Imaginary, 1e-9);
    }

    [Fact]
    public void ComplexValue_EditorFormat_KeepsAllDigits()
    {
        var z = ComplexValue.FromRectangular(12345.678, -0.5);
        Assert.True(ComplexValue.TryParse(z.ToRectangularString("G10"), out var back));
        Assert.Equal(12345.678, back.Real, 1e-9);
        Assert.Equal(-0.5, back.Imaginary, 1e-9);
        // Görüntü biçimi değişmedi
        Assert.Equal("1,235E+04−j0,5", z.ToRectangularString());
    }

    // ── Eleman adı ──

    private static readonly CircuitElement[] Circuit =
    {
        new Resistor { Id = "R1" },
        new SwitchElement(SwitchMode.NormallyOpen) { Id = "S1" },
        new SwitchElement(SwitchMode.NormallyOpen) { Id = "S2" },
    };

    [Theory]
    [InlineData("S1")]          // değişmedi
    [InlineData("")]            // boş: eski ad kalır
    [InlineData("S3")]
    [InlineData("s_ana")]
    public void ElementName_AcceptsValidNames(string text)
    {
        Assert.Null(ElementEditorWindow.CheckElementName(text, "S1", Circuit[1], Circuit));
    }

    [Theory]
    [InlineData("R1", "kullanılıyor")]   // başka bir elemanın adı (ilk harf de yanlış)
    [InlineData("S2", "kullanılıyor")]
    [InlineData("s2", "kullanılıyor")]   // büyük/küçük harf farkı aynı ad sayılır
    [InlineData("A1", "harfiyle başlamalı")]
    [InlineData("Sş", "harfiyle başlamalı")]
    [InlineData("S 1", "harfiyle başlamalı")]
    [InlineData("S12345678901234567", "harfiyle başlamalı")]
    public void ElementName_RejectsDuplicatesAndBadNames(string text, string expectedPart)
    {
        string? error = ElementEditorWindow.CheckElementName(text, "S1", Circuit[1], Circuit);
        Assert.NotNull(error);
        if (expectedPart == "kullanılıyor" && !text.StartsWith("S", StringComparison.OrdinalIgnoreCase))
            Assert.Contains("harfiyle başlamalı", error);
        else
            Assert.Contains(expectedPart, error);
    }

    // ── Düzenleme penceresi: İptal'de geri yükleme ──

    [Fact]
    public void EditorState_RestoresModesAndValues()
    {
        var ac = new AcVoltageSource
        {
            Id = "VAC1", Amplitude = 10, Frequency = 50, Phase = 30,
            InputMode = AcInputMode.Physical, ValueKind = AcValueKind.Peak,
        };
        var state = ElementEditorWindow.CaptureState(ac);

        // Pencerede mod değişti ve hatalı bir Uygula'dan önce genlik yazıldı
        ac.InputMode = AcInputMode.Phasor;
        ac.ValueKind = AcValueKind.Rms;
        ac.Amplitude = 230;
        ac.Frequency = 0;

        ElementEditorWindow.RestoreState(ac, state);

        Assert.Equal(AcInputMode.Physical, ac.InputMode);
        Assert.Equal(AcValueKind.Peak, ac.ValueKind);
        Assert.Equal(10, ac.Amplitude);
        Assert.Equal(50, ac.Frequency);
        Assert.Equal(30, ac.Phase);
        Assert.Equal("VAC1", ac.Id);
    }

    [Fact]
    public void EditorState_RestoresProbeTypeAndId()
    {
        var probe = new TestProbe { Id = "VP1", Type = ProbeType.Voltage };
        var state = ElementEditorWindow.CaptureState(probe);
        probe.Type = ProbeType.Current;
        probe.Id = "IP1";
        probe.TargetElementId = "R1";

        ElementEditorWindow.RestoreState(probe, state);

        Assert.Equal("VP1", probe.Id);
        Assert.Equal(ProbeType.Voltage, probe.Type);
        Assert.Equal(string.Empty, probe.TargetElementId);
    }

    // ── Pano: akım ölçerin adı ──

    [Fact]
    public void Clipboard_CurrentProbeKeepsIpPrefix()
    {
        Assert.Equal("IP", CircuitClipboard.GetPrefixForElement(new TestProbe { Type = ProbeType.Current }));
        Assert.Equal("VP", CircuitClipboard.GetPrefixForElement(new TestProbe { Type = ProbeType.Voltage }));
    }

    // ── Bozuk dosya ──

    [Fact]
    public void CorruptFile_InfinitePosition_IsRejectedBeforeLoading()
    {
        var r1 = new Resistor { Id = "R1", Value = 100 };
        string json = CircuitDocument.Snapshot(new CircuitElement[] { r1 }, Array.Empty<Wire>());
        string broken = Regex.Replace(json, "\"x\":[^,}]+", "\"x\":1e999");
        Assert.NotEqual(json, broken);

        Assert.Throws<CircuitFileException>(() => CircuitDocument.FromJson(broken).ToCircuit("bozuk"));
    }
}
