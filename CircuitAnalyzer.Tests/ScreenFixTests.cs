using System;
using System.Collections.Generic;
using System.Linq;
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

    // ── Üç faz "Sonuçlar": iç adlar yerine faz adları ──

    [Theory]
    [InlineData("0", "GND", "0 (GND)")]
    [InlineData("4", "R fazı (Y1)", "V4 · R fazı (Y1)")]
    [InlineData("7", "N′ (Y1 yıldız noktası)", "V7 · N′ (Y1 yıldız noktası)")]
    [InlineData("3", null, "V3")]
    public void NodeTile_UsesThePhaseNameFromTheApi(string key, string? label, string expected)
    {
        Assert.Equal(expected, AnalysisPanel.NodeTileTitle(key, label));
    }

    private static ComplexNumberDto C(double mag, double deg) => new()
    {
        Real = mag * Math.Cos(deg * Math.PI / 180), Imaginary = mag * Math.Sin(deg * Math.PI / 180),
        Magnitude = mag, PhaseDegrees = deg
    };

    [Fact]
    public void ThreePhaseSections_StarStar_UseTheNarrativeNames()
    {
        var tp = new ThreePhaseResultDto
        {
            Source = "Y", Load = "Y", Wires = 3,
            PhaseVoltages = new() { ["R"] = C(219.4, 0), ["S"] = C(219.4, -120), ["T"] = C(219.4, 120) },
            LineVoltages = new() { ["RS"] = C(380, 30), ["ST"] = C(380, -90), ["TR"] = C(380, 150) },
            LineCurrents = new() { ["R"] = C(18.75, -33.7), ["S"] = C(18.75, -153.7), ["T"] = C(18.75, 86.3) },
            LoadVoltages = new() { ["R"] = C(202.8, 3.18), ["S"] = C(202.8, -116.8), ["T"] = C(202.8, 123.2) },
            LoadNeutralVoltage = C(0, 0),
        };
        var s = AnalysisPanel.ThreePhaseSections(tp);
        Assert.Equal(new[] { "Kaynağın faz gerilimleri", "Hat gerilimleri", "Hat akımları", "Yıldız yükün kol gerilimleri" },
                     s.Select(x => x.Header));
        var titles = s.SelectMany(x => x.Items.Select(i => i.Title)).ToList();
        Assert.Equal(new[] { "V_RN", "V_SN", "V_TN", "V_RS", "V_ST", "V_TR", "I_R", "I_S", "I_T",
                             "V_RN′", "V_SN′", "V_TN′", "V_N′N" }, titles);
        Assert.Equal("0 V", s[3].Items.Last().Value);                 // "0,02436 pV" değil
        Assert.Equal("380∠30° V", s[1].Items[0].Value);
    }

    [Fact]
    public void ThreePhaseSections_DeltaLoad_ShowsArmVoltagesAndPhaseCurrents()
    {
        var tp = new ThreePhaseResultDto
        {
            Source = "D", Load = "D", Wires = 3,
            LineVoltages = new() { ["RS"] = C(380, 30) },
            LineCurrents = new() { ["R"] = C(65.82, 0) },
            LoadVoltages = new() { ["RS"] = C(380, 30) },
            LoadPhaseCurrents = new() { ["RS"] = C(38, 30) },
        };
        var s = AnalysisPanel.ThreePhaseSections(tp);
        Assert.Equal(new[] { "Hat gerilimleri", "Hat akımları", "Üçgen yükün kol gerilimleri", "Üçgen yükün faz akımları" },
                     s.Select(x => x.Header));
        Assert.Equal("V_RS", s[2].Items[0].Title);
        Assert.Equal("I_RS", s[3].Items[0].Title);
    }

    // ── Grafikler: rozetler eksen sayılarıyla çakışmaz, işaret sayısı sınırlı ──

    [Theory]
    [InlineData(0, 6)]
    [InlineData(100, 3)]
    [InlineData(300, 4)]
    [InlineData(2000, 8)]
    public void TickBudget_IsReadable(double width, int expected)
    {
        Assert.Equal(expected, PlotLayout.TickBudget(width));
    }

    [Theory]
    [InlineData(-0.5, 5.0, 300)]      // geçici durum: −0,5τ … 5τ (τ = 1)
    [InlineData(-5, 50, 900)]
    [InlineData(-0.15, 1.5, 0)]       // genişlik bilinmiyor
    [InlineData(0.9, 1.1, 400)]       // rezonans: dar bant
    [InlineData(1234, 98765, 500)]
    public void NiceTicks_AreFewEvenAndInside(double min, double max, double width)
    {
        int budget = PlotLayout.TickBudget(width);
        var t = PlotLayout.NiceTicks(min, max, budget);
        Assert.InRange(t.Length, 2, budget);
        Assert.InRange(t.Length, 2, 8);                          // eskiden ~35 işaret
        Assert.All(t, x => Assert.InRange(x, min - 1e-9, max + 1e-9));
        double step = t[1] - t[0];
        for (int i = 2; i < t.Length; i++)
            Assert.Equal(step, t[i] - t[i - 1], 9);
        if (min < 0 && max > 0)
            Assert.Contains(0.0, t);
    }

    [Fact]
    public void Badges_ThatWouldTouch_GoToSeparateRows()
    {
        // f₁, f₀, f₂ yüksek Q'da birkaç piksel arayla
        double[] x = { 200, 212, 224 };
        double[] w = x.Select(_ => PlotLayout.BadgeWidthPx("f₀", 14)).ToArray();
        int[] rows = PlotLayout.BadgeRows(x, w);
        for (int i = 0; i < x.Length; i++)
            for (int j = i + 1; j < x.Length; j++)
                if (rows[i] == rows[j])
                    Assert.True(Math.Abs(x[i] - x[j]) >= (w[i] + w[j]) / 2 + 6);
        Assert.True(rows.Distinct().Count() > 1);
    }

    [Fact]
    public void TauBadges_FitOneRow_InTheBandAboveTheCurve()
    {
        // 300 px veri alanı, −0,5τ … 5τ: τ işaretleri ~55 px arayla
        double[] x = Enumerable.Range(1, 5).Select(k => (k + 0.5) / 5.5 * 300).ToArray();
        string[] txt = { "τ", "2τ", "3τ", "4τ", "5τ" };
        int[] rows = PlotLayout.BadgeRows(x, txt.Select(s => PlotLayout.BadgeWidthPx(s, 12)).ToArray());
        Assert.All(rows, r => Assert.Equal(0, r));
        var (axisMax, centers) = PlotLayout.TopBand(0, 12, rows.Max() + 1);
        Assert.All(centers, c => Assert.InRange(c, 12.0001, axisMax));   // eğrinin üstünde, eksen sayılarından uzak
    }

    [Theory]
    [InlineData(300, 12)]
    [InlineData(530, 12)]       // kâğıttaki genişlik
    [InlineData(900, 14)]
    [InlineData(160, 14)]       // çok dar kart
    public void Badges_AtTheEndsOfTheAxis_StayFullyInside(double w, double font)
    {
        // Geçici durum: −0,5τ … 5τ, 5τ tam sağ kenarda; rezonans rozetleri de iki uçta sınanır
        var cases = new[]
        {
            (Centers: Enumerable.Range(1, 5).Select(k => (k + 0.5) / 5.5 * w).ToArray(), Texts: new[] { "τ", "2τ", "3τ", "4τ", "5τ" }),
            (Centers: new[] { 0.0, w / 2, w }, Texts: new[] { "f₁", "f₀", "f₂" }),
        };
        foreach (var (natural, texts) in cases)
        {
            double[] widths = texts.Select(t => PlotLayout.BadgeWidthPx(t, font)).ToArray();
            double[] c = natural.Select((x, i) => PlotLayout.ClampBadgeCenterPx(x, widths[i], w)).ToArray();
            int[] rows = PlotLayout.BadgeRows(c, widths);
            for (int i = 0; i < c.Length; i++)
            {
                Assert.InRange(c[i] - widths[i] / 2, 0, w);
                Assert.InRange(c[i] + widths[i] / 2, 0, w);
                for (int j = i + 1; j < c.Length; j++)
                    if (rows[i] == rows[j])
                        Assert.True(Math.Abs(c[i] - c[j]) >= (widths[i] + widths[j]) / 2, $"{texts[i]} ile {texts[j]} üst üste");
            }
        }
        // İçerideki rozet yerinden oynamaz
        Assert.Equal(w / 2, PlotLayout.ClampBadgeCenterPx(w / 2, PlotLayout.BadgeWidthPx("f₀", font), w));
    }

    [Theory]
    [InlineData(135, 12, 1)]    // kâğıttaki geçici durum grafiği (230 − 95)
    [InlineData(205, 14, 1)]    // kâğıttaki rezonans eğrisi (300 − 95)
    [InlineData(205, 14, 3)]    // yüksek Q: f₁ f₀ f₂ üç satırda
    [InlineData(130, 14, 2)]    // ölçü bilinmiyor (varsayılan)
    [InlineData(400, 12, 1)]    // büyütülmüş pencere
    public void TopBand_BadgesFitBetweenTheCurveAndTheTopEdge(double h, double font, int rowCount)
    {
        double axisMin = -1.5, dataMax = 10.5;          // veri 0…10, altında ve üstünde pay
        double badgeH = PlotLayout.BadgeHeightPx(font);
        var (axisMax, centers) = PlotLayout.TopBandPx(axisMin, dataMax, rowCount, h, badgeH);
        Assert.Equal(rowCount, centers.Length);
        double Px(double y) => (axisMax - y) / (axisMax - axisMin) * h;   // üst kenardan piksel
        double curveTopPx = Px(dataMax);
        foreach (double c in centers)
        {
            double top = Px(c) - badgeH / 2, bottom = Px(c) + badgeH / 2;
            Assert.True(top >= 2, $"rozet üst kenara yapışık/taşıyor: {top:F1} px");
            Assert.True(bottom <= curveTopPx - 2, $"rozet eğriye biniyor: {bottom:F1} > {curveTopPx:F1}");
        }
        for (int r = 1; r < centers.Length; r++)
            Assert.True(Px(centers[r]) - Px(centers[r - 1]) >= badgeH, "satırlar üst üste");
    }

    [Theory]
    [InlineData(0.8, 1.2, 0.5, 2.0, true)]      // sağda boşluk çok
    [InlineData(4.0, 4.6, 0.5, 5.0, false)]     // f₂ sağ kenara yakın: solda
    [InlineData(0.95, 1.05, 0.5, 1.5, true)]    // simetrik: sağda
    public void HalfPowerLabel_GoesInsideThePlot_OnTheSideAwayFromTheCurve(double f1, double f2, double left, double right, bool expectRight)
    {
        bool onRight = PlotLayout.HalfPowerLabelOnRight(left, right, f1, f2);
        Assert.Equal(expectRight, onRight);

        double w = 530, labelW = PlotLayout.BadgeWidthPx("0,707·I_max", 12);
        var (bl, br) = PlotLayout.HalfPowerLabelBoxPx(onRight, labelW, w);
        Assert.True(bl >= 0 && br <= w, "etiket çizim alanının dışında (eksen sayılarının üstünde)");
        double f1Px = (f1 - left) / (right - left) * w, f2Px = (f2 - left) / (right - left) * w;
        Assert.True(br <= f1Px || bl >= f2Px, $"etiket eğrinin 0,707 üstündeki kısmına biniyor: [{bl:F0}, {br:F0}] / [{f1Px:F0}, {f2Px:F0}]");
    }

    // ── Güç üçgeni: kenarlarda değerler, kompanzasyon yazıları, çakışma yok ──

    public static IEnumerable<object?[]> TriangleCases() => new[]
    {
        new object?[] { 1000.0, 750.0, "lagging", null, 340.0, 180.0 },        // olağan
        new object?[] { 1000.0, 20.0, "lagging", null, 340.0, 180.0 },         // yassı (küçük φ)
        new object?[] { 30.0, 1000.0, "lagging", null, 340.0, 180.0 },         // dik (büyük φ)
        new object?[] { 1000.0, -750.0, "leading", null, 340.0, 180.0 },       // ileri
        new object?[] { 1000.0, 0.0, "unity", null, 340.0, 180.0 },            // birim
        new object?[] { 1000.0, 750.0, "lagging", 0.95, 340.0, 180.0 },       // kompanzasyon
        new object?[] { 14440.0, 10830.0, "lagging", 0.95, 280.0, 180.0 },   // dar tuval, kW
        new object?[] { 1000.0, 60.0, "lagging", 0.999, 340.0, 180.0 },        // yassı + kompanzasyon
        new object?[] { 50.0, 1000.0, "lagging", 0.9, 340.0, 180.0 },         // dik + kompanzasyon
    };

    [Theory]
    [MemberData(nameof(TriangleCases))]
    public void PowerTriangle_LabelsDoNotOverlapAndStayInside(double p, double q, string pf, double? target, double w, double h)
    {
        var r = PowerTriangleLayout.Layout(w, h, p, q, pf, target);
        var bounds = new Rect(0, 0, w, h);
        foreach (var l in r.Labels)
            Assert.True(bounds.Contains(l.Box), $"{l.Key} tuvalin dışında: {l.Box}");
        for (int i = 0; i < r.Labels.Count; i++)
            for (int j = i + 1; j < r.Labels.Count; j++)
                Assert.False(PowerTriangleLayout.Overlaps(r.Labels[i].Box, r.Labels[j].Box, 0),
                    $"{r.Labels[i].Key} ile {r.Labels[j].Key} üst üste");
    }

    [Fact]
    public void PowerTriangle_SidesCarryValuesWithUnits()
    {
        var r = PowerTriangleLayout.Layout(340, 180, 1000, 750, "lagging", null);
        Assert.Equal("P = 1 kW", r["P"]!.Text);
        Assert.Equal("Q = 750 VAR", r["Q"]!.Text);
        Assert.Equal("S = 1,25 kVA", r["S"]!.Text);
        Assert.Equal("φ = 36,87°", r["phi"]!.Text);
        Assert.Null(r["Q2"]);
    }

    [Fact]
    public void PowerTriangle_LeadingQ_UsesUnicodeMinus()
    {
        var r = PowerTriangleLayout.Layout(340, 180, 1000, -750, "leading", null);
        Assert.Equal("Q = −750 VAR", r["Q"]!.Text);
    }

    [Fact]
    public void PowerTriangle_CompensationLinesAreNamed()
    {
        // P = 1 kW, cos φ₁ = 0,8 → cos φ₂ = 0,95: Q′ = P·tan φ₂ = 328,7 VAR, S′ = P/cos φ₂ = 1,053 kVA
        var r = PowerTriangleLayout.Layout(340, 180, 1000, 750, "lagging", 0.95);
        Assert.Equal("φ₁ = 36,87°", r["phi"]!.Text);                  // anlatım: φ₁ önce, φ₂ hedef
        Assert.Equal("Q_C", r["Qc"]!.Text);
        Assert.Equal("Q′", r["Q2"]!.Text);
        Assert.Equal("S′", r["S2"]!.Text);
        Assert.Equal("φ₂", r["phi2"]!.Text);
        Assert.All(r.Labels.Where(l => l.Key is "Qc" or "Q2" or "S2" or "phi2"), l => Assert.True(l.IsCompensation));
        Assert.Equal("Kompanzasyondan sonra (kesikli): Q′ = 328,7 VAR, S′ = 1,053 kVA, φ₂ = 18,19° (cos φ₂ = 0,95)",
                     PowerTriangleLayout.CompensationCaption(1000, 0.95));
    }

    [Theory]
    [MemberData(nameof(TriangleCases))]
    public void PowerTriangle_ValueLabelsDoNotCrossTheSides_OnARoomyCanvas(double p, double q, string pf, double? target, double w, double h)
    {
        var r = PowerTriangleLayout.Layout(Math.Max(w, 340), h, p, q, pf, target);
        var sides = new List<(Point, Point)> { (r.P0, r.P1) };
        if (!r.IsUnity) { sides.Add((r.P1, r.P2)); sides.Add((r.P0, r.P2)); }
        foreach (var l in r.Labels.Where(l => l.Key is "P" or "Q" or "S"))
            Assert.DoesNotContain(sides, s => PowerTriangleLayout.Crosses(s.Item1, s.Item2, l.Box));
    }
}
