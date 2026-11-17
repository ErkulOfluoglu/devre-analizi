using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using System.Windows.Shapes;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Yazdırılan / PDF'e kaydedilen çözüm: yöntem adı, tablo hücreleri ekrandaki gibi,
/// geçici durum tablolarının notu, grafikler ve güç üçgeni.
/// </summary>
[Collection(WpfUiCollection.Name)]
public class PrintOutputTests
{
    private static void RunOnSta(Action action)
    {
        Exception? ex = null;
        var thread = new Thread(() =>
        {
            try { action(); }
            catch (Exception e) { ex = e; }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        if (ex != null) ExceptionDispatchInfo.Capture(ex).Throw();
    }

    // ── 1. Yöntem adı: yöntem seçicisindeki yazı, iç ad değil ──

    public static IEnumerable<object[]> AllAnalysisTypes() =>
        typeof(AnalysisTypes).GetFields(BindingFlags.Public | BindingFlags.Static)
            .Where(f => f.IsLiteral)
            .Select(f => new object[] { (string)f.GetRawConstantValue()! });

    [Theory]
    [MemberData(nameof(AllAnalysisTypes))]
    public void MethodDisplayName_EveryAnalysisType_IsTheSelectorLabel(string analysisType)
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            string name = panel.MethodDisplayName(analysisType);

            Assert.Contains(name, panel.MethodLabels);
            Assert.Equal(analysisType, AnalysisPanel.AnalysisTypeFromText(name));
            Assert.DoesNotContain("_", name);
            Assert.NotEqual(analysisType, name);
        });
    }

    [Theory]
    [InlineData(AnalysisTypes.ThreePhase, "Üç Faz")]
    [InlineData(AnalysisTypes.Transient, "Geçici Durum (Anahtar)")]
    [InlineData(AnalysisTypes.Power, "Güç ve Güç Katsayısı")]
    [InlineData(AnalysisTypes.Nodal, "Düğüm Gerilimleri")]
    public void MethodLabelFor_FindsTheLabelThatMapsBack(string analysisType, string expected)
    {
        var labels = new[]
        {
            "Düğüm Gerilimleri", "Thevenin Eşdeğeri", "Geçici Durum (Anahtar)",
            "Güç ve Güç Katsayısı", "Rezonans", "Üç Faz"
        };
        Assert.Equal(expected, AnalysisPanel.MethodLabelFor(labels, analysisType));
    }

    [Fact]
    public void MethodLabelFor_UnknownOrMissing_IsNull()
    {
        Assert.Null(AnalysisPanel.MethodLabelFor(new[] { "Rezonans" }, AnalysisTypes.Mesh));
        Assert.Null(AnalysisPanel.MethodLabelFor(new[] { "Rezonans" }, null));
    }

    // ── 2. Tablo hücreleri: önekli birim, Unicode eksi, ekrandaki adlar ──

    [Theory]
    [InlineData("1∠-90° A", "1∠−90° A")]
    [InlineData("-4 mA", "−4 mA")]
    [InlineData("1,556∠-45° A", "1,556∠−45° A")]
    [InlineData("1→0", "1→0")]
    [InlineData("12 V", "12 V")]
    public void UnicodeMinus_ReplacesTheSignOfNumbersOnly(string input, string expected)
    {
        Assert.Equal(expected, PrintContent.UnicodeMinus(input));
    }

    [Fact]
    public void PowerRow_UsesEngineeringPrefixesLikeTheScreen()
    {
        var el = new ElementPowerDto
        {
            ElementId = "Z1", Role = "load",
            ActivePower = 9873.504, ReactivePower = -7405.128, ApparentPower = 12341.88,
            PowerFactor = 0.8, PowerFactorType = "ileri"
        };
        var row = PrintContent.PowerRow("Z1", el);
        Assert.Equal(new[] { "Z1", "9,874 kW", "−7,405 kVAR", "12,34 kVA", "0,800 ileri", "Yük" }, row);
        Assert.Equal("242 W", PrintContent.PowerRow("R1", new ElementPowerDto { ActivePower = 242.008, Role = "source" })[1]);
        Assert.Equal("Kaynak", PrintContent.PowerRow("V1", new ElementPowerDto { Role = "source" })[5]);
    }

    [Fact]
    public void NodeRows_CarryThePhaseNamesAndScreenOrder()
    {
        var nodes = new Dictionary<string, NodeVoltageDto>
        {
            ["10"] = new() { Value = ResultValue.FromReal(1), Unit = "V" },
            ["4"] = new() { Value = new ResultValue { Real = 0, Imaginary = -219.4, IsComplex = true }, Unit = "V", Label = "R fazı (Y1)" },
            ["0"] = new() { Value = ResultValue.FromReal(0), Unit = "V", Label = "GND" },
        };
        var rows = PrintContent.NodeRows(nodes);
        Assert.Equal(new[] { "0 (GND)", "V4 · R fazı (Y1)", "V10" }, rows.Select(r => r.Name));
        Assert.Equal("219,4∠−90° V", rows[1].Value);
    }

    [Fact]
    public void CurrentRows_UseTheScreenNameAndRealDirection()
    {
        var currents = new Dictionary<string, ElementCurrentDto>
        {
            ["R1"] = new() { Value = ResultValue.FromReal(-0.004), Unit = "A", Direction = "1→0" },
        };
        var row = Assert.Single(PrintContent.CurrentRows(currents));
        Assert.Equal(("I_R1", "4 mA", "0→1"), row);
    }

    // ── 3. Geçici durum: tablolar t → ∞ değerleri ──

    [Fact]
    public void ResultsTablesNote_OnlyForTransient()
    {
        Assert.Null(PrintContent.ResultsTablesNote(NodalResponse()));
        string? note = PrintContent.ResultsTablesNote(TransientResponse());
        Assert.NotNull(note);
        Assert.Contains("t → ∞ (yeni kararlı hâl)", note);
        Assert.Contains("grafiğindedir", note);

        var noPlot = TransientResponse();
        noPlot.Transient!.Quantities.Clear();
        Assert.DoesNotContain("grafiğindedir", PrintContent.ResultsTablesNote(noPlot));
    }

    // ── 4. Şekiller: hangileri, nereye ──

    [Fact]
    public void Figures_FollowTheScreenCards()
    {
        Assert.Empty(PrintContent.Figures(NodalResponse()));
        Assert.Equal(new[] { PrintFigureKind.TransientPlot }, PrintContent.Figures(TransientResponse()).Select(f => f.Kind));
        Assert.Equal(new[] { PrintFigureKind.PowerTriangle }, PrintContent.Figures(PowerResponse()).Select(f => f.Kind));
        Assert.Equal(new[] { PrintFigureKind.ResonanceCurve },
            PrintContent.Figures(new AnalysisResponseDto { Resonance = new ResonanceDto { F0 = 1000, Q = 5, Bw = 200 } }).Select(f => f.Kind));
        Assert.Equal(new[] { PrintFigureKind.PowerTriangle },
            PrintContent.Figures(new AnalysisResponseDto { ThreePhase = new ThreePhaseResultDto { P = 1000, Q = 500, S = 1118, Pf = 0.894, PfType = "lagging" } })
                .Select(f => f.Kind));

        // Büyüklüğü olmayan geçici durumda grafik de açıklaması da yok
        var empty = TransientResponse();
        empty.Transient!.Quantities.Clear();
        Assert.Empty(PrintContent.Figures(empty));
    }

    [Fact]
    public void FigureCaptions_AreTurkishWithValues()
    {
        var power = PrintContent.Figures(PowerResponse()).Single();
        Assert.StartsWith("Güç üçgeni:", power.Caption);
        Assert.Contains("P = 1 kW", power.Caption);
        Assert.Contains("cos φ = 0,8 geri", power.Caption);

        var leading = PrintContent.PowerTriangleCaption(new PowerSummaryDto { P = 1000, Q = -750, S = 1250, Pf = 0.8, PfType = "leading" });
        Assert.Contains("Q = −750 VAR", leading);
        Assert.DoesNotContain("-", leading);

        var tr = PrintContent.Figures(TransientResponse()).Single();
        Assert.StartsWith("Zaman grafiği:", tr.Caption);
        Assert.Contains("τ = 2 ms", tr.Caption);
    }

    [Theory]
    [InlineData("TransientPlot", new[] { "Devreyi Tanıyalım", "Zamana Bağlı İfade", "Sonuç" }, 1)]
    [InlineData("ResonanceCurve", new[] { "Rezonans Frekansı", "Bant Genişliği", "Kontrol" }, 1)]
    [InlineData("PowerTriangle", new[] { "Güç Hesabı", "Güç Üçgeni", "Kompanzasyon" }, 1)]
    [InlineData("PowerTriangle", new[] { "Faz ve Hat Büyüklükleri", "Güç", "Kontrol" }, 1)]
    [InlineData("TransientPlot", new[] { "Geçici Durum (Anahtar)" }, -1)]
    [InlineData("PowerTriangle", new string[0], -1)]
    public void AnchorSection_PutsTheFigureAfterItsTopic(string kind, string[] titles, int expected)
    {
        Assert.Equal(expected, PrintContent.AnchorSection(titles, Enum.Parse<PrintFigureKind>(kind)));
    }

    [Theory]
    [MemberData(nameof(ScreenFixTests.TriangleCases), MemberType = typeof(ScreenFixTests))]
    public void PowerTriangle_AtPrintSize_LabelsStayInsideAndApart(double p, double q, string pf, double? target, double w, double h)
    {
        _ = (w, h);   // ekran ölçüsü; burada kâğıttaki ölçü sınanır
        double pw = SolutionPrinter.FigureWidth, ph = SolutionPrinter.TriangleHeight;
        var r = PowerTriangleLayout.Layout(pw, ph, p, q, pf, target);
        var bounds = new Rect(0, 0, pw, ph);
        foreach (var l in r.Labels)
            Assert.True(bounds.Contains(l.Box), $"{l.Key} tuvalin dışında: {l.Box}");
        for (int i = 0; i < r.Labels.Count; i++)
            for (int j = i + 1; j < r.Labels.Count; j++)
                Assert.False(PowerTriangleLayout.Overlaps(r.Labels[i].Box, r.Labels[j].Box, 0),
                    $"{r.Labels[i].Key} ile {r.Labels[j].Key} üst üste");
    }

    // ── Belgenin kendisi (STA, pencere ve yazdırma iletişim kutusu yok) ──

    private static List<Border> FigureFrames(FlowDocument doc) =>
        doc.Blocks.OfType<BlockUIContainer>()
            .Select(b => b.Child).OfType<Border>()
            .Where(b => b.Tag is PrintFigureKind)
            .ToList();

    private static string FrameCaption(Border frame) =>
        ((StackPanel)frame.Child).Children.OfType<TextBlock>().Single() is { } tb
            ? new TextRange(tb.ContentStart, tb.ContentEnd).Text
            : "";

    private static int IndexOfBlock(FlowDocument doc, Func<Block, bool> match)
    {
        int i = 0;
        foreach (var b in doc.Blocks)
        {
            if (match(b)) return i;
            i++;
        }
        return -1;
    }

    private static bool IsParagraphWithText(Block b, string text) =>
        b is Paragraph p && new TextRange(p.ContentStart, p.ContentEnd).Text.Trim() == text;

    [Fact]
    public void BuildDocument_Power_HasTheTriangleAfterItsSection_InLightColors()
    {
        RunOnSta(() =>
        {
            var doc = SolutionPrinter.BuildDocument(new PrintInput { Response = PowerResponse(), Method = "Güç ve Güç Katsayısı" });

            var frame = Assert.Single(FigureFrames(doc));
            Assert.Equal(PrintFigureKind.PowerTriangle, frame.Tag);
            Assert.StartsWith("Güç üçgeni:", FrameCaption(frame));

            // Vektör çizim, ekrandaki yerleşimle; renkler açık temadan (#0071E3)
            var canvas = ((StackPanel)frame.Child).Children.OfType<Canvas>().Single();
            Assert.True(canvas.Width <= 642.5);
            var stroke = canvas.Children.OfType<Line>().First().Stroke as SolidColorBrush;
            Assert.Equal(Color.FromRgb(0x00, 0x71, 0xE3), stroke!.Color);
            Assert.Contains(canvas.Children.OfType<TextBlock>(), t => new TextRange(t.ContentStart, t.ContentEnd).Text.StartsWith("P = 1 kW"));

            // "Güç Üçgeni" bölümünün ardında, "Kompanzasyon"dan ve "Sonuçlar"dan önce
            int section = IndexOfBlock(doc, b => IsParagraphWithText(b, "Güç Üçgeni"));
            int figure = IndexOfBlock(doc, b => b is BlockUIContainer { Child: Border { Tag: PrintFigureKind } });
            int next = IndexOfBlock(doc, b => IsParagraphWithText(b, "Kompanzasyon"));
            int results = IndexOfBlock(doc, b => IsParagraphWithText(b, "Sonuçlar"));
            Assert.True(section >= 0 && section < figure && figure < next && next < results,
                $"bölüm {section}, şekil {figure}, sonraki {next}, sonuçlar {results}");

            // Güç tablosu önekli birimle
            string text = new TextRange(doc.ContentStart, doc.ContentEnd).Text;
            Assert.Contains("1 kW", text);
            Assert.DoesNotContain("1000 W", text);
            Assert.DoesNotContain(doc.Blocks, b => b.Tag as string == SolutionPrinter.ResultsNoteTag);
        });
    }

    [Fact]
    public void BuildDocument_Transient_HasThePlotAndTheTablesNote()
    {
        RunOnSta(() =>
        {
            var doc = SolutionPrinter.BuildDocument(new PrintInput { Response = TransientResponse(), Method = "Geçici Durum (Anahtar)" });

            var frame = Assert.Single(FigureFrames(doc));
            Assert.Equal(PrintFigureKind.TransientPlot, frame.Tag);
            Assert.StartsWith("Zaman grafiği:", FrameCaption(frame));

            // İki büyüklük, ekran dışında üretilmiş keskin görüntüler (sayfa genişliğine sığar)
            var images = ((StackPanel)((StackPanel)frame.Child).Children[0]).Children.OfType<Image>().ToList();
            Assert.Equal(2, images.Count);
            Assert.All(images, img =>
            {
                Assert.True(img.Width <= 642.5);
                var bmp = Assert.IsAssignableFrom<System.Windows.Media.Imaging.BitmapSource>(img.Source);
                Assert.True(bmp.PixelWidth >= img.Width * 2.5, $"çözünürlük düşük: {bmp.PixelWidth} px");
            });

            // Grafik "Zamana Bağlı İfade"nin ardında; not "Sonuçlar"ın altında, tablolardan önce
            int section = IndexOfBlock(doc, b => IsParagraphWithText(b, "Zamana Bağlı İfade"));
            int figure = IndexOfBlock(doc, b => b is BlockUIContainer { Child: Border { Tag: PrintFigureKind } });
            int results = IndexOfBlock(doc, b => IsParagraphWithText(b, "Sonuçlar"));
            int note = IndexOfBlock(doc, b => b.Tag as string == SolutionPrinter.ResultsNoteTag);
            int firstTable = IndexOfBlock(doc, b => b is Table);
            Assert.True(section >= 0 && section < figure && figure < results && results < note && note < firstTable,
                $"bölüm {section}, şekil {figure}, sonuçlar {results}, not {note}, tablo {firstTable}");

            string text = new TextRange(doc.ContentStart, doc.ContentEnd).Text;
            Assert.Contains("t → ∞ (yeni kararlı hâl)", text);
        });
    }

    [Fact]
    public void BuildDocument_NodalOrPractice_HasNoFigureAndNoNote()
    {
        RunOnSta(() =>
        {
            var nodal = SolutionPrinter.BuildDocument(new PrintInput { Response = NodalResponse(), Method = "Düğüm Gerilimleri" });
            Assert.Empty(FigureFrames(nodal));
            Assert.DoesNotContain(nodal.Blocks, b => b.Tag as string == SolutionPrinter.ResultsNoteTag);
            string text = new TextRange(nodal.ContentStart, nodal.ContentEnd).Text;
            Assert.Contains("Yöntem: Düğüm Gerilimleri", text);

            // Alıştırma yaprağında grafik cevabı gösterir: basılmaz
            var practice = SolutionPrinter.BuildDocument(new PrintInput
            {
                Response = TransientResponse(),
                IsPracticeMode = true,
                PracticeQuestions = new List<PracticeQuestionDto>()
            });
            Assert.Empty(FigureFrames(practice));
        });
    }

    // ── Elle kurulmuş yanıtlar (arka uç gerekmez) ──

    private static ExplanationSectionDto Section(string title) => new()
    {
        Title = title,
        Blocks = new List<ExplanationBlockDto> { new() { Kind = "text", Text = title + " açıklaması" } }
    };

    private static AnalysisResponseDto NodalResponse() => new()
    {
        Status = "success",
        Results = new AnalysisResultsDto
        {
            NodeVoltages = new() { ["1"] = new NodeVoltageDto { Value = ResultValue.FromReal(8), Unit = "V" } },
            Explanation = new() { Section("Devreyi Tanıyalım"), Section("Düğüm Denklemleri (KCL)") }
        }
    };

    private static AnalysisResponseDto PowerResponse() => new()
    {
        Status = "success",
        PowerSummary = new PowerSummaryDto { P = 1000, Q = 750, S = 1250, Pf = 0.8, PfType = "lagging" },
        Results = new AnalysisResultsDto
        {
            NodeVoltages = new() { ["1"] = new NodeVoltageDto { Value = new ResultValue { Real = 100, Imaginary = -10, IsComplex = true }, Unit = "V" } },
            Power = new PowerAnalysisDto
            {
                Elements = new()
                {
                    ["Z1"] = new ElementPowerDto { ElementId = "Z1", Role = "load", ActivePower = 1000, ReactivePower = 750, ApparentPower = 1250, PowerFactor = 0.8, PowerFactorType = "geri" }
                }
            },
            Explanation = new() { Section("Güç Hesabı"), Section("Güç Üçgeni"), Section("Kompanzasyon"), Section("Sonuç") }
        }
    };

    private static AnalysisResponseDto TransientResponse() => new()
    {
        Status = "success",
        Transient = new TransientAnalysisDto
        {
            Element = "C1", Kind = "RC", Tau = 0.002, Rth = 1000,
            Quantities = new()
            {
                new TransientQuantityDto { Id = "v", Label = "v_C1", Unit = "V", Before = 0, Start = 0, Final = 10 },
                new TransientQuantityDto { Id = "i", Label = "i_C1", Unit = "A", Before = 0, Start = 0.01, Final = 0 },
            }
        },
        Results = new AnalysisResultsDto
        {
            NodeVoltages = new() { ["1"] = new NodeVoltageDto { Value = ResultValue.FromReal(10), Unit = "V" } },
            ElementCurrents = new() { ["C1"] = new ElementCurrentDto { Value = ResultValue.FromReal(0), Unit = "A", Direction = "1→0" } },
            Explanation = new() { Section("Devreyi Tanıyalım"), Section("Zamana Bağlı İfade"), Section("Sonuç") }
        }
    };
}
