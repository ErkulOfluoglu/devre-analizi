using System.Windows;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>Ekran düzeltmeleri (Fable denetimi, 3. ve 6. tur).</summary>
public class ScreenFixTests
{
    [Theory]
    [InlineData("1. Adım — Vth (Açık Devre Gerilimi)", "Vth (Açık Devre Gerilimi)")]
    [InlineData("2. Adım — In (Kısa Devre Akımı)", "In (Kısa Devre Akımı)")]
    [InlineData("12. Adım - Sonuç", "Sonuç")]
    [InlineData("Devreyi Tanıyalım", "Devreyi Tanıyalım")]
    [InlineData("Düğüm Denklemleri (KCL)", "Düğüm Denklemleri (KCL)")]
    public void ChainTitle_DropsTheNarrativesOwnStepNumber(string title, string expected)
    {
        Assert.Equal(expected, AnalysisPanel.ChainTitle(title));
    }

    [Theory]
    [InlineData(1.5, 1.0, "s")]          // τ = 0,3 s: eksen "1500 ms" değil saniye
    [InlineData(0.010, 1e3, "ms")]
    [InlineData(50e-6, 1e6, "µs")]
    [InlineData(5e-9, 1e9, "ns")]
    public void TimeAxis_UnitFitsTheWholeCurve(double maxSeconds, double scale, string unit)
    {
        var (s, u) = TransientPlotView.TimeUnitFor(maxSeconds);
        Assert.Equal(scale, s);
        Assert.Equal(unit, u);
    }

    [Theory]
    [InlineData(0.0, 0.006, 0.0, 1e3, "mA")]   // 6 mA: eksen 0,006 A değil 6 mA
    [InlineData(0.0, 12.0, 12.0, 1.0, "A")]
    [InlineData(0.0, 5e-6, 0.0, 1e6, "µA")]
    [InlineData(0.0, 0.0, 0.0, 1.0, "A")]
    public void ValueAxis_UsesTheSamePrefixAsTheText(double before, double start, double final, double scale, string unit)
    {
        var q = new TransientQuantityDto { Unit = "A", Before = before, Start = start, Final = final };
        var (s, u) = TransientPlotView.ValueUnitFor(q);
        Assert.Equal(scale, s);
        Assert.Equal(unit, u);
    }

    [Fact]
    public void CurrentChip_OnAVerticalElement_SitsBelowTheValueText()
    {
        var r = new Resistor { Id = "R2", Value = 200, Position = new Point(100, 100), Rotation = 90 };
        double cy = r.Position.Y + r.VisualHeight / 2;
        var p = ResultOverlay.BelowOrRight(r);
        // Değer yazısı gövdenin sağında, cy hizasında (±8 px): etiket ondan aşağıda başlar
        Assert.True(p.Y >= cy + 10);
    }
}
