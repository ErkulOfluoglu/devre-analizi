using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// "Zener Aralığı" (ZENER_RANGE) analiz yöntemi arayüz, DTO, biçimlendirme, grafik ve yazdırma testleri.
/// </summary>
[Collection(WpfUiCollection.Name)]
public class ZenerRangeUiTests
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

    private static string SampleResponseJson(string maxToken) => $$"""
    {
      "status": "success",
      "mode": "DC",
      "analysis_type": "ZENER_RANGE",
      "results": {
        "zener_range": {
          "target_id": "RY",
          "kind": "LOAD",
          "symbol": "R_Y",
          "unit": "Ω",
          "min": 250.0,
          "max": {{maxToken}},
          "current_value": 300.0,
          "current_inside": true,
          "steps": [
            { "symbol": "I_Z,min", "value": 0.0, "unit": "A", "text": "Alt sınırda Zener akımı sıfır" },
            { "symbol": "R_Y,min", "value": 250.0, "unit": "Ω", "text": "Alt sınır yük direnci" }
          ],
          "checks": [
            { "x": 200.0, "state": "OFF", "v_y": 4.8, "i_z": 0.0, "verdict": "BELOW", "text": "Zener yalıtımda" },
            { "x": 300.0, "state": "ZENER", "v_y": 5.1, "i_z": 0.012, "verdict": "OK", "text": "Regülasyon sağlanıyor" },
            { "x": 500.0, "state": "ZENER", "v_y": 5.1, "i_z": 0.035, "verdict": "ABOVE", "text": "I_ZM aşıldı" }
          ],
          "curve": {
            "x": [150.0, 200.0, 250.0, 300.0, 400.0, 500.0],
            "v_y": [3.9, 4.8, 5.1, 5.1, 5.1, 5.1],
            "i_z": [0.0, 0.0, 0.0, 0.012, 0.03, 0.035]
          },
          "x_label": "R_Y (Ω)",
          "y_label": "V_Y (V)"
        }
      }
    }
    """;

    [Fact]
    public void AnalysisTypeFromText_ZenerRange_MatchesExactLiteralAcrossCultures()
    {
        var original = CultureInfo.CurrentCulture;
        try
        {
            foreach (var cultureName in new[] { "tr-TR", "en-US", "" })
            {
                CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo(cultureName);
                Assert.Equal(AnalysisTypes.ZenerRange, AnalysisPanel.AnalysisTypeFromText("Zener Aralığı"));
            }
        }
        finally
        {
            CultureInfo.CurrentCulture = original;
        }

        Assert.Equal("ZENER_RANGE", AnalysisTypes.ZenerRange);
        Assert.False(AnalysisPanel.UsesTerminals(AnalysisTypes.ZenerRange));
    }

    [Fact]
    public void ZenerRangeTargetIds_IncludesOnlyResistorsAndDcVoltageSources()
    {
        var elements = new CircuitElement[]
        {
            new VoltageSource { Id = "V1", Value = 12 },
            new Resistor { Id = "R1", Value = 100 },
            new Resistor { Id = "RY", Value = 300 },
            new Diode(DiodeModel.Zener) { Id = "D1", ZenerVoltage = 5.1 },
            new AcVoltageSource { Id = "VAC1", Amplitude = 10, Frequency = 50 },
            new CurrentSource { Id = "I1", Value = 0.01 },
            new AcCurrentSource { Id = "IAC1", Amplitude = 1, Frequency = 50 },
            new Inductor { Id = "L1", Value = 0.1 },
            new Capacitor { Id = "C1", Value = 1e-6 },
            new ImpedanceElement { Id = "Z1" },
            new GroundElement { Id = "GND1" },
            new TestProbe { Id = "VP1" },
            new JunctionElement { Id = "J1" },
            new Wattmeter { Id = "W1" },
        };

        var ids = AnalysisPanel.ZenerRangeTargetIds(elements);
        Assert.Equal(new[] { "V1", "R1", "RY" }, ids);
    }

    [Fact]
    public void ZenerRangeRow_VisibleOnlyForZenerRange_DefaultEmpty_AndStaysInSync()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAvailableZenerRangeTargets(new CircuitElement[]
            {
                new VoltageSource { Id = "V1", Value = 12 },
                new Resistor { Id = "R1", Value = 100 },
                new Resistor { Id = "RY", Value = 300 },
                new Diode(DiodeModel.Zener) { Id = "D1" },
                new AcVoltageSource { Id = "VAC1", Amplitude = 5, Frequency = 50 },
            });

            // Başka yöntemde satır gizli
            Assert.Equal(Visibility.Collapsed, panel.RowZenerRangeTarget.Visibility);
            Assert.Equal("Değişen eleman", panel.TxtZenerRangeTargetLabel.Text);

            // Zener Aralığı seçilince görünür; varsayılan seçim boş (API yükü seçer)
            panel.SetAnalysisType(AnalysisTypes.ZenerRange);
            Assert.Equal(Visibility.Visible, panel.RowZenerRangeTarget.Visibility);
            Assert.Equal(Visibility.Collapsed, panel.RowTerminals.Visibility);
            Assert.Equal(Visibility.Collapsed, panel.RowReciprocityTarget.Visibility);
            Assert.Null(panel.CmbZenerRangeTarget.SelectedItem);

            Assert.True(panel.TryGetOptions(out var optEmpty, out var err), err);
            Assert.Equal(AnalysisTypes.ZenerRange, optEmpty!.AnalysisType);
            Assert.Null(optEmpty.ZenerRangeTarget);

            // Eleman seçilince TryGetOptions bu kimliği taşır
            panel.CmbZenerRangeTarget.SelectedItem = "V1";
            Assert.True(panel.TryGetOptions(out var optV1, out err), err);
            Assert.Equal("V1", optV1!.ZenerRangeTarget);

            // Devre güncellenince seçili eleman hâlâ varsa korunur
            panel.SetAvailableZenerRangeTargets(new CircuitElement[]
            {
                new VoltageSource { Id = "V1", Value = 15 },
                new Resistor { Id = "R1", Value = 100 },
                new Resistor { Id = "RY", Value = 400 },
            });
            Assert.Equal("V1", panel.CmbZenerRangeTarget.SelectedItem);

            // Seçili eleman yeniden adlandırılınca veya silinince boş seçime döner
            panel.SetAvailableZenerRangeTargets(new CircuitElement[]
            {
                new VoltageSource { Id = "Vi", Value = 15 },
                new Resistor { Id = "R1", Value = 100 },
            });
            Assert.Null(panel.CmbZenerRangeTarget.SelectedItem);

            // Başka yönteme geçince satır tekrar gizlenir
            panel.SetAnalysisType(AnalysisTypes.Nodal);
            Assert.Equal(Visibility.Collapsed, panel.RowZenerRangeTarget.Visibility);
        });
    }

    [Fact]
    public void AnalysisSettings_ZenerRangeTarget_RoundTrip_AndOldFileWithoutIt()
    {
        RunOnSta(() =>
        {
            var elements = new CircuitElement[]
            {
                new VoltageSource { Id = "V1", Value = 12 },
                new Resistor { Id = "R1", Value = 100 },
                new Resistor { Id = "RY", Value = 300 },
            };

            var panel1 = new AnalysisPanel();
            panel1.SetAvailableZenerRangeTargets(elements);
            panel1.SetAnalysisType(AnalysisTypes.ZenerRange);
            panel1.CmbZenerRangeTarget.SelectedItem = "RY";

            var settings = panel1.GetAnalysisSettings();
            Assert.Equal(AnalysisTypes.ZenerRange, settings.Type);
            Assert.Equal("RY", settings.ZenerRangeTarget);

            var doc = new CircuitDocument { Analysis = settings };
            string json = doc.ToJson();
            Assert.Contains("\"zener_range_target\": \"RY\"", json);
            var loaded = CircuitDocument.FromJson(json);
            Assert.Equal("RY", loaded.Analysis!.ZenerRangeTarget);

            var panel2 = new AnalysisPanel();
            panel2.SetAvailableZenerRangeTargets(elements);
            panel2.RestoreAnalysisSettings(loaded.Analysis);
            Assert.Equal(AnalysisTypes.ZenerRange, panel2.GetAnalysisSettings().Type);
            Assert.Equal("RY", panel2.CmbZenerRangeTarget.SelectedItem);

            // Eski .devre dosyası (zener_range_target yok) sorunsuz açılır ve boş seçime düşer
            const string legacyJson = """
            {
              "format": "devre-analizi",
              "version": 1,
              "elements": [],
              "wires": [],
              "analysis": {
                "type": "ZENER_RANGE",
                "value_display": "RMS"
              }
            }
            """;
            var legacyDoc = CircuitDocument.FromJson(legacyJson);
            Assert.Null(legacyDoc.Analysis!.ZenerRangeTarget);

            var panel3 = new AnalysisPanel();
            panel3.SetAvailableZenerRangeTargets(elements);
            panel3.CmbZenerRangeTarget.SelectedItem = "V1";
            panel3.RestoreAnalysisSettings(legacyDoc.Analysis);
            Assert.Null(panel3.CmbZenerRangeTarget.SelectedItem);
        });
    }

    [Fact]
    public void AnalysisRequestDto_ZenerRangeTarget_SerializedWhenSet_OmittedWhenNull()
    {
        var req = new AnalysisRequestDto
        {
            Netlist = "V1 1 0 12\nR1 1 2 100\nRY 2 0 300\nD1 0 2 ZENER VZ=5.1 IZM=0.03",
            AnalysisType = AnalysisTypes.ZenerRange,
            ZenerRangeTarget = "RY",
        };
        string json = JsonSerializer.Serialize(req);
        Assert.Contains("\"zener_range_target\":\"RY\"", json.Replace(" ", ""));
        Assert.Contains("\"analysis_type\":\"ZENER_RANGE\"", json.Replace(" ", ""));

        var ask = LlmAskRequestDto.From(req, "Üst sınır neden 400 Ω?");
        Assert.Equal("RY", ask.ZenerRangeTarget);
        Assert.Contains("\"zener_range_target\":\"RY\"", JsonSerializer.Serialize(ask).Replace(" ", ""));

        var reqNull = new AnalysisRequestDto
        {
            AnalysisType = AnalysisTypes.ZenerRange,
            ZenerRangeTarget = null,
        };
        Assert.DoesNotContain("zener_range_target", JsonSerializer.Serialize(reqNull));
    }

    [Fact]
    public void ResponseDto_DeserializesSampleJson_FiniteAndInfiniteMax()
    {
        var finite = JsonSerializer.Deserialize<AnalysisResponseDto>(SampleResponseJson("400.0"));
        Assert.NotNull(finite);
        var zr = finite!.ZenerRangeResult;
        Assert.NotNull(zr);
        Assert.Equal("RY", zr!.TargetId);
        Assert.Equal("LOAD", zr.Kind);
        Assert.Equal("R_Y", zr.Symbol);
        Assert.Equal("Ω", zr.Unit);
        Assert.Equal(250.0, zr.Min);
        Assert.Equal(400.0, zr.Max);
        Assert.Equal(300.0, zr.CurrentValue);
        Assert.True(zr.CurrentInside);
        Assert.Equal(2, zr.Steps.Count);
        Assert.Equal(3, zr.Checks.Count);
        Assert.Equal("OK", zr.Checks[1].Verdict);
        Assert.NotNull(zr.Curve);
        Assert.Equal(6, zr.Curve!.X.Count);
        Assert.Equal("R_Y (Ω)", zr.XLabel);
        Assert.Equal("V_Y (V)", zr.YLabel);

        var openEnded = JsonSerializer.Deserialize<AnalysisResponseDto>(SampleResponseJson("null"));
        Assert.NotNull(openEnded?.ZenerRangeResult);
        Assert.Equal(250.0, openEnded!.ZenerRangeResult!.Min);
        Assert.Null(openEnded.ZenerRangeResult.Max);
    }

    [Fact]
    public void FormatZenerRange_AndCurrentStatus_HandleFiniteAndInfinite()
    {
        var finite = new ZenerRangeDto
        {
            TargetId = "RY",
            Symbol = "R_Y",
            Unit = "Ω",
            Min = 250.0,
            Max = 400.0,
            CurrentValue = 300.0,
            CurrentInside = true,
        };
        Assert.Equal("250 Ω ≤ R_Y ≤ 400 Ω", AnalysisPanel.FormatZenerRange(finite));
        Assert.Equal("Devredeki RY = 300 Ω aralığın içinde ✓", AnalysisPanel.FormatZenerCurrentStatus(finite));

        var infinite = new ZenerRangeDto
        {
            TargetId = "RY",
            Symbol = "R_Y",
            Unit = "Ω",
            Min = 250.0,
            Max = null,
            CurrentValue = 150.0,
            CurrentInside = false,
        };
        Assert.Equal("R_Y ≥ 250 Ω (üst sınır yok)", AnalysisPanel.FormatZenerRange(infinite));
        Assert.Equal("Devredeki RY = 150 Ω aralığın dışında", AnalysisPanel.FormatZenerCurrentStatus(infinite));

        var kilo = new ZenerRangeDto
        {
            TargetId = "RY",
            Symbol = "R_Y",
            Unit = "Ω",
            Min = 1500.0,
            Max = 4700.0,
        };
        Assert.Equal("1,5 kΩ ≤ R_Y ≤ 4,7 kΩ", AnalysisPanel.FormatZenerRange(kilo));
    }

    [Fact]
    public void FormatZenerVerdict_MapsOkBelowAboveToExpectedTextAndBrush()
    {
        var ok = AnalysisPanel.FormatZenerVerdict("OK");
        Assert.Contains("✓", ok.Text);
        Assert.Equal("Brush.Success", ok.BrushKey);

        var below = AnalysisPanel.FormatZenerVerdict("BELOW");
        Assert.Equal("Brush.Warning", below.BrushKey);

        var above = AnalysisPanel.FormatZenerVerdict("ABOVE");
        Assert.Equal("Brush.Warning", above.BrushKey);

        // Diyot durum metinleri yeniden kullanılıyor
        Assert.Equal("ters iletimde (V_Z)", AnalysisPanel.FormatDiodeState("ZENER"));
        Assert.Equal("yalıtımda", AnalysisPanel.FormatDiodeState("OFF"));
        Assert.Equal("iletimde", AnalysisPanel.FormatDiodeState("ON"));
    }

    [Fact]
    public void ZenerRangePlotView_AndResultsCard_AndPrintDocument_BuildWithoutThrowing()
    {
        var finiteResp = JsonSerializer.Deserialize<AnalysisResponseDto>(SampleResponseJson("400.0"))!;
        var openResp = JsonSerializer.Deserialize<AnalysisResponseDto>(SampleResponseJson("null"))!;

        RunOnSta(() =>
        {
            // Grafik bileşeni hem sonlu hem sonsuz üst sınırda hatasız kurulur
            var plotView = new ZenerRangePlotView();
            plotView.LoadData(finiteResp.ZenerRangeResult!);
            plotView.LoadData(openResp.ZenerRangeResult!);

            // Sonuçlar kartı Zener Aralığı bölümüyle hatasız oluşur
            var panel = new AnalysisPanel();
            panel.ShowResults(finiteResp);

            // Yazdırma belgesi aralık cümlesi, adımlar, sağlama tablosu ve grafiği içerir
            var figures = PrintContent.Figures(finiteResp);
            Assert.Contains(figures, f => f.Kind == PrintFigureKind.ZenerRangePlot);

            var doc = SolutionPrinter.BuildDocument(new PrintInput
            {
                Response = finiteResp,
                Method = "Zener Aralığı",
                Title = "Zener Regülatörü",
            });
            string allText = new TextRange(doc.ContentStart, doc.ContentEnd).Text;
            Assert.Contains("Zener Aralığı", allText);
            Assert.Contains("250 Ω", allText);
            Assert.Contains("400 Ω", allText);
            Assert.Contains("Sağlama", allText);
            Assert.Contains("ters iletimde", allText);
        });
    }

    // ═══════════════════════════════════════════════════════
    //  TERS PROBLEM (INVERSE) TESTLERİ
    // ═══════════════════════════════════════════════════════

    [Theory]
    [InlineData("", "", null, null)]
    [InlineData("   ", "  ", null, null)]
    [InlineData("120", "200", 120.0, 200.0)]
    [InlineData("120 V", "200 V", 120.0, 200.0)]
    [InlineData("1k", "4,7k", 1000.0, 4700.0)]
    [InlineData("1 kΩ", "4,7 kΩ", 1000.0, 4700.0)]
    [InlineData("0,5k", "2,5 kΩ", 500.0, 2500.0)]
    [InlineData("500 mV", "1,5 V", 0.5, 1.5)]
    public void TryParseZenerRangeGiven_AcceptsSiPrefixesDecimalCommaAndUnits(
        string minText, string maxText, double? expectedMin, double? expectedMax)
    {
        bool ok = AnalysisPanel.TryParseZenerRangeGiven(minText, maxText, out double? min, out double? max, out string? err);
        Assert.True(ok, err);
        Assert.Null(err);
        Assert.Equal(expectedMin, min);
        Assert.Equal(expectedMax, max);
    }

    [Theory]
    [InlineData("120", "")]
    [InlineData("", "200")]
    [InlineData("200", "200")]
    [InlineData("250", "120")]
    [InlineData("2k", "1,5 kΩ")]
    [InlineData("abc", "200")]
    [InlineData("120", "xyz")]
    public void TryParseZenerRangeGiven_RejectsOneEmptyOrMinGeMaxOrInvalid(string minText, string maxText)
    {
        bool ok = AnalysisPanel.TryParseZenerRangeGiven(minText, maxText, out double? min, out double? max, out string? err);
        Assert.False(ok);
        Assert.NotNull(err);
        Assert.Null(min);
        Assert.Null(max);
    }

    [Fact]
    public void ZenerRangeGivenRow_VisibleOnlyForZenerRange_ValidatesInline_AndClearsOnTargetChange()
    {
        RunOnSta(() =>
        {
            var elements = new CircuitElement[]
            {
                new VoltageSource { Id = "V1", Value = 150 },
                new Resistor { Id = "R1", Value = 100 },
                new Resistor { Id = "RY", Value = 300 },
            };

            var panel = new AnalysisPanel();
            panel.SetAvailableZenerRangeTargets(elements);

            // Başka yöntemde gizli
            Assert.Equal(Visibility.Collapsed, panel.RowZenerRangeGiven.Visibility);
            Assert.Equal("Değişim aralığı (isteğe bağlı)", panel.TxtZenerRangeGivenLabel.Text);
            Assert.Equal(
                "boş bırakılırsa aralık hesaplanır; doluysa diğer büyüklük bulunur",
                panel.TxtZenerRangeGivenHint.Text);

            // Zener Aralığı seçilince görünür
            panel.SetAnalysisType(AnalysisTypes.ZenerRange);
            Assert.Equal(Visibility.Visible, panel.RowZenerRangeGiven.Visibility);
            Assert.Equal(Visibility.Collapsed, panel.TxtZenerRangeGivenError.Visibility);

            // Tek kutu doluysa doğrulama başarısız olur ve satır içi hata görünür
            panel.CmbZenerRangeTarget.SelectedItem = "V1";
            panel.TxtZenerRangeGivenMin.Text = "120 V";
            panel.TxtZenerRangeGivenMax.Text = "";
            Assert.False(panel.TryGetOptions(out _, out string? err1));
            Assert.False(string.IsNullOrWhiteSpace(err1));
            Assert.Equal(Visibility.Visible, panel.TxtZenerRangeGivenError.Visibility);

            // min >= max ise doğrulama başarısız
            panel.TxtZenerRangeGivenMax.Text = "100 V";
            Assert.Equal(Visibility.Collapsed, panel.TxtZenerRangeGivenError.Visibility); // yazı değişince temizlenir
            Assert.False(panel.TryGetOptions(out _, out string? err2));
            Assert.False(string.IsNullOrWhiteSpace(err2));
            Assert.Equal(Visibility.Visible, panel.TxtZenerRangeGivenError.Visibility);

            // Geçerli aralık → SI temel biriminde SolveOptions'a yansır
            panel.TxtZenerRangeGivenMin.Text = "0,5k";
            panel.TxtZenerRangeGivenMax.Text = "1 kΩ";
            Assert.True(panel.TryGetOptions(out var opt, out string? err3), err3);
            Assert.Equal(500.0, opt!.ZenerRangeGivenMin);
            Assert.Equal(1000.0, opt.ZenerRangeGivenMax);
            Assert.Equal(Visibility.Collapsed, panel.TxtZenerRangeGivenError.Visibility);

            // Aynı hedef listede kaldığı sürece devre yenilenince aralık korunur
            panel.SetAvailableZenerRangeTargets(new CircuitElement[]
            {
                new VoltageSource { Id = "V1", Value = 160 },
                new Resistor { Id = "R1", Value = 100 },
                new Resistor { Id = "RY", Value = 400 },
            });
            Assert.Equal("V1", panel.CmbZenerRangeTarget.SelectedItem);
            Assert.Equal("0,5k", panel.TxtZenerRangeGivenMin.Text);
            Assert.Equal("1 kΩ", panel.TxtZenerRangeGivenMax.Text);

            // Başka elemana geçilince verilen aralık temizlenir
            panel.CmbZenerRangeTarget.SelectedItem = "RY";
            Assert.Equal("", panel.TxtZenerRangeGivenMin.Text);
            Assert.Equal("", panel.TxtZenerRangeGivenMax.Text);

            // Seçili eleman devreden silinince de temizlenir
            panel.TxtZenerRangeGivenMin.Text = "1k";
            panel.TxtZenerRangeGivenMax.Text = "2k";
            panel.SetAvailableZenerRangeTargets(new CircuitElement[]
            {
                new VoltageSource { Id = "V1", Value = 160 },
                new Resistor { Id = "R1", Value = 100 },
            });
            Assert.Null(panel.CmbZenerRangeTarget.SelectedItem);
            Assert.Equal("", panel.TxtZenerRangeGivenMin.Text);
            Assert.Equal("", panel.TxtZenerRangeGivenMax.Text);

            // Başka yönteme geçince satır tekrar gizlenir
            panel.SetAnalysisType(AnalysisTypes.Nodal);
            Assert.Equal(Visibility.Collapsed, panel.RowZenerRangeGiven.Visibility);
        });
    }

    [Fact]
    public void AnalysisSettings_ZenerRangeGiven_RoundTrip_AndOldFileWithoutIt()
    {
        RunOnSta(() =>
        {
            var elements = new CircuitElement[]
            {
                new VoltageSource { Id = "V1", Value = 150 },
                new Resistor { Id = "R1", Value = 100 },
                new Resistor { Id = "RY", Value = 300 },
            };

            var panel1 = new AnalysisPanel();
            panel1.SetAvailableZenerRangeTargets(elements);
            panel1.SetAnalysisType(AnalysisTypes.ZenerRange);
            panel1.CmbZenerRangeTarget.SelectedItem = "V1";
            panel1.TxtZenerRangeGivenMin.Text = "120 V";
            panel1.TxtZenerRangeGivenMax.Text = "200 V";

            var settings = panel1.GetAnalysisSettings();
            Assert.Equal("V1", settings.ZenerRangeTarget);
            Assert.Equal("120 V", settings.ZenerRangeGivenMin);
            Assert.Equal("200 V", settings.ZenerRangeGivenMax);

            var doc = new CircuitDocument { Analysis = settings };
            string json = doc.ToJson();
            Assert.Contains("\"zener_range_given_min\": \"120 V\"", json);
            Assert.Contains("\"zener_range_given_max\": \"200 V\"", json);

            var loaded = CircuitDocument.FromJson(json);
            var panel2 = new AnalysisPanel();
            panel2.SetAvailableZenerRangeTargets(elements);
            panel2.RestoreAnalysisSettings(loaded.Analysis);
            Assert.Equal("V1", panel2.CmbZenerRangeTarget.SelectedItem);
            Assert.Equal("120 V", panel2.TxtZenerRangeGivenMin.Text);
            Assert.Equal("200 V", panel2.TxtZenerRangeGivenMax.Text);

            // Eski dosya (zener_range_given_* yok) sorunsuz açılır ve kutuları temizler
            const string legacyJson = """
            {
              "format": "devre-analizi",
              "version": 1,
              "elements": [],
              "wires": [],
              "analysis": {
                "type": "ZENER_RANGE",
                "zener_range_target": "V1"
              }
            }
            """;
            var legacy = CircuitDocument.FromJson(legacyJson);
            Assert.Null(legacy.Analysis!.ZenerRangeGivenMin);
            Assert.Null(legacy.Analysis.ZenerRangeGivenMax);
            panel2.RestoreAnalysisSettings(legacy.Analysis);
            Assert.Equal("", panel2.TxtZenerRangeGivenMin.Text);
            Assert.Equal("", panel2.TxtZenerRangeGivenMax.Text);
        });
    }

    [Fact]
    public void AnalysisRequestDto_ZenerRangeGiven_SerializedWhenSet_OmittedWhenNull()
    {
        var req = new AnalysisRequestDto
        {
            Netlist = "V1 1 0 150\nR1 1 2 100\nRY 2 0 300\nD1 0 2 ZENER VZ=50 IZM=0.05",
            AnalysisType = AnalysisTypes.ZenerRange,
            ZenerRangeTarget = "V1",
            ZenerRangeGivenMin = 120.0,
            ZenerRangeGivenMax = 200.0,
        };
        string json = JsonSerializer.Serialize(req).Replace(" ", "");
        Assert.Contains("\"zener_range_given_min\":120", json);
        Assert.Contains("\"zener_range_given_max\":200", json);

        var ask = LlmAskRequestDto.From(req, "R_Y neden tek değer çıktı?");
        Assert.Equal(120.0, ask.ZenerRangeGivenMin);
        Assert.Equal(200.0, ask.ZenerRangeGivenMax);
        string askJson = JsonSerializer.Serialize(ask).Replace(" ", "");
        Assert.Contains("\"zener_range_given_min\":120", askJson);
        Assert.Contains("\"zener_range_given_max\":200", askJson);

        var reqNull = new AnalysisRequestDto { AnalysisType = AnalysisTypes.ZenerRange };
        string nullJson = JsonSerializer.Serialize(reqNull);
        Assert.DoesNotContain("zener_range_given_min", nullJson);
        Assert.DoesNotContain("zener_range_given_max", nullJson);
    }

    [Fact]
    public void ResponseDto_DeserializesInverseSamples_UniqueRangeInfeasible_AndGivenNullInRange()
    {
        const string uniqueJson = """
        {
          "status": "success",
          "mode": "DC",
          "analysis_type": "ZENER_RANGE",
          "results": {
            "zener_range": {
              "target_id": "V1",
              "answer_id": "RY",
              "kind": "LOAD_FROM_INPUT",
              "mode": "INVERSE",
              "unique": true,
              "feasible": true,
              "given": { "symbol": "V_İ", "unit": "V", "min": 120.0, "max": 200.0 },
              "symbol": "R_Y",
              "unit": "Ω",
              "min": 1000.0,
              "max": 1000.0,
              "plot_min": 120.0,
              "plot_max": 200.0,
              "current_value": 300.0,
              "current_inside": false,
              "steps": [],
              "checks": [
                { "x": 120.0, "state": "ZENER", "v_y": 50.0, "i_z": 0.01, "verdict": "OK", "text": "Alt sınır uygun" },
                { "x": 200.0, "state": "ZENER", "v_y": 50.0, "i_z": 0.05, "verdict": "OK", "text": "Üst sınır uygun" }
              ],
              "curve": { "x": [100.0, 120.0, 160.0, 200.0, 220.0], "v_y": [45.0, 50.0, 50.0, 50.0, 50.0], "i_z": [0.0, 0.01, 0.03, 0.05, 0.06] },
              "x_label": "V_İ (V)",
              "y_label": "V_Y (V)"
            }
          }
        }
        """;

        var uniqueResp = JsonSerializer.Deserialize<AnalysisResponseDto>(uniqueJson)!;
        var zr = uniqueResp.ZenerRangeResult!;
        Assert.Equal("INVERSE", zr.Mode);
        Assert.True(zr.IsInverse);
        Assert.True(zr.Unique);
        Assert.True(zr.Feasible);
        Assert.Equal("LOAD_FROM_INPUT", zr.Kind);
        Assert.Equal("RY", zr.AnswerId);
        Assert.NotNull(zr.Given);
        Assert.Equal("V_İ", zr.Given!.Symbol);
        Assert.Equal("V", zr.Given.Unit);
        Assert.Equal(120.0, zr.Given.Min);
        Assert.Equal(200.0, zr.Given.Max);
        Assert.Equal(120.0, zr.PlotMin);
        Assert.Equal(200.0, zr.PlotMax);

        const string rangeJson = """
        {
          "status": "success",
          "mode": "DC",
          "analysis_type": "ZENER_RANGE",
          "results": {
            "zener_range": {
              "target_id": "RY",
              "answer_id": "V1",
              "kind": "INPUT_FROM_LOAD",
              "mode": "INVERSE",
              "unique": false,
              "feasible": true,
              "given": { "symbol": "R_Y", "unit": "Ω", "min": 1000.0, "max": 2000.0 },
              "symbol": "V_İ",
              "unit": "V",
              "min": 15.0,
              "max": 25.0,
              "plot_min": 1000.0,
              "plot_max": 2000.0
            }
          }
        }
        """;
        var rangeZr = JsonSerializer.Deserialize<AnalysisResponseDto>(rangeJson)!.ZenerRangeResult!;
        Assert.True(rangeZr.IsInverse);
        Assert.False(rangeZr.Unique);
        Assert.True(rangeZr.Feasible);
        Assert.Equal("INPUT_FROM_LOAD", rangeZr.Kind);

        const string infeasibleJson = """
        {
          "status": "warning",
          "mode": "DC",
          "analysis_type": "ZENER_RANGE",
          "results": {
            "zener_range": {
              "target_id": "V1",
              "answer_id": "RY",
              "kind": "LOAD_FROM_INPUT",
              "mode": "INVERSE",
              "unique": false,
              "feasible": false,
              "given": { "symbol": "V_İ", "unit": "V", "min": 100.0, "max": 500.0 },
              "symbol": "R_Y",
              "unit": "Ω",
              "min": null,
              "max": null
            }
          }
        }
        """;
        var infeasibleZr = JsonSerializer.Deserialize<AnalysisResponseDto>(infeasibleJson)!.ZenerRangeResult!;
        Assert.True(infeasibleZr.IsInverse);
        Assert.False(infeasibleZr.Feasible);
        Assert.Null(infeasibleZr.Min);
        Assert.Null(infeasibleZr.Max);

        // İleri (RANGE) yanıtta given null, mode RANGE, feasible true
        var forwardZr = JsonSerializer.Deserialize<AnalysisResponseDto>(SampleResponseJson("400.0"))!.ZenerRangeResult!;
        Assert.False(forwardZr.IsInverse);
        Assert.True(forwardZr.Feasible);
        Assert.Null(forwardZr.Given);
    }

    [Fact]
    public void FormatZenerInverse_AllFourCases_AndCheckHeader()
    {
        var givenVi = new ZenerRangeGivenDto { Symbol = "V_İ", Unit = "V", Min = 120, Max = 200 };

        // 1. Tekil (unique) çözüm
        var unique = new ZenerRangeDto
        {
            Mode = "INVERSE",
            Unique = true,
            Feasible = true,
            Given = givenVi,
            TargetId = "V1",
            AnswerId = "RY",
            Symbol = "R_Y",
            Unit = "Ω",
            Min = 1000,
            Max = 1000,
            CurrentValue = 300,
            CurrentInside = false,
        };
        Assert.Equal("Verilen: 120 V ≤ V_İ ≤ 200 V", AnalysisPanel.FormatZenerGiven(unique));
        Assert.Equal("R_Y = 1 kΩ", AnalysisPanel.FormatZenerRange(unique));
        Assert.Equal("Devredeki RY = 300 Ω, bulunan değer 1 kΩ", AnalysisPanel.FormatZenerCurrentStatus(unique));
        Assert.Equal("V_İ", AnalysisPanel.ZenerCheckXSymbol(unique));
        Assert.Equal("V", AnalysisPanel.ZenerCheckXUnit(unique));

        // 2. Sonlu aralık çözümü
        var range = new ZenerRangeDto
        {
            Mode = "INVERSE",
            Unique = false,
            Feasible = true,
            Given = givenVi,
            TargetId = "V1",
            AnswerId = "RY",
            Symbol = "R_Y",
            Unit = "Ω",
            Min = 2000,
            Max = 3000,
            CurrentValue = 2500,
            CurrentInside = true,
        };
        Assert.Equal("2 kΩ ≤ R_Y ≤ 3 kΩ", AnalysisPanel.FormatZenerRange(range));
        Assert.Equal("Devredeki RY = 2,5 kΩ aralığın içinde ✓", AnalysisPanel.FormatZenerCurrentStatus(range));

        // 3. Üst sınırsız çözüm
        var openTop = new ZenerRangeDto
        {
            Mode = "INVERSE",
            Unique = false,
            Feasible = true,
            Given = givenVi,
            TargetId = "V1",
            AnswerId = "RY",
            Symbol = "R_Y",
            Unit = "Ω",
            Min = 2000,
            Max = null,
        };
        Assert.Equal("R_Y ≥ 2 kΩ (üst sınır yok)", AnalysisPanel.FormatZenerRange(openTop));

        // 4. Uygun değer yok (infeasible)
        var infeasible = new ZenerRangeDto
        {
            Mode = "INVERSE",
            Unique = false,
            Feasible = false,
            Given = givenVi,
            TargetId = "V1",
            AnswerId = "RY",
            Symbol = "R_Y",
            Unit = "Ω",
            CurrentValue = 300,
            CurrentInside = false,
        };
        Assert.Equal("Bu aralık için uygun değer yok", AnalysisPanel.FormatZenerRange(infeasible));
        Assert.Null(AnalysisPanel.FormatZenerCurrentStatus(infeasible));
    }

    [Fact]
    public void ZenerRangePlot_UsesPlotMinMax_XLabel_AndPrintsInverseCard()
    {
        var inverse = new ZenerRangeDto
        {
            Mode = "INVERSE",
            Unique = true,
            Feasible = true,
            Kind = "LOAD_FROM_INPUT",
            TargetId = "V1",
            AnswerId = "RY",
            Given = new ZenerRangeGivenDto { Symbol = "V_İ", Unit = "V", Min = 120, Max = 200 },
            Symbol = "R_Y",
            Unit = "Ω",
            Min = 1000,
            Max = 1000,
            PlotMin = 120,
            PlotMax = 200,
            CurrentValue = 300,
            CurrentInside = false,
            XLabel = "V_İ (V)",
            YLabel = "V_Y (V)",
            Checks = new List<ZenerRangeCheckDto>
            {
                new() { X = 120, State = "ZENER", VY = 50, IZ = 0.01, Verdict = "OK" },
                new() { X = 200, State = "ZENER", VY = 50, IZ = 0.05, Verdict = "OK" },
            },
            Curve = new ZenerRangeCurveDto
            {
                X = new List<double> { 100, 120, 160, 200, 220 },
                VY = new List<double> { 45, 50, 50, 50, 50 },
                IZ = new List<double> { 0, 0.01, 0.03, 0.05, 0.06 },
            },
        };

        // Grafik sınırları plot_min/plot_max'tan alınır (min/max = 1000 Ω değil)
        var (pMin, pMax) = ZenerRangePlotView.PlotBoundsFor(inverse);
        Assert.Equal(120.0, pMin);
        Assert.Equal(200.0, pMax);

        // X ekseni ölçeği verilen büyüklüğün (V) birimine göre seçilir (kΩ değil)
        var (scale, unit) = ZenerRangePlotView.XUnitFor(inverse);
        Assert.Equal(1.0, scale);
        Assert.Equal("V", unit);
        Assert.Contains("V", ZenerRangePlotView.FormatXLabel(inverse, scale, unit));

        // plot_min/plot_max yoksa eski yanıtlar gibi min/max'a düşer
        var legacy = new ZenerRangeDto { Min = 250, Max = 400 };
        var (lMin, lMax) = ZenerRangePlotView.PlotBoundsFor(legacy);
        Assert.Equal(250.0, lMin);
        Assert.Equal(400.0, lMax);

        // ScottPlot çiziminde kesikli dikey çizgiler ve gölgeli bant plot_min/plot_max konumundadır
        var plot = new ScottPlot.Plot();
        ZenerRangePlotView.BuildPlot(plot, inverse, scale, unit, 400, 200, _ => ScottPlot.Colors.Black);
        var vlines = plot.GetPlottables<ScottPlot.Plottables.VerticalLine>().Select(v => v.X).OrderBy(x => x).ToList();
        Assert.Equal(new[] { 120.0, 200.0 }, vlines);
        var hspan = Assert.Single(plot.GetPlottables<ScottPlot.Plottables.HorizontalSpan>());
        Assert.Equal(120.0, hspan.X1);
        Assert.Equal(200.0, hspan.X2);

        // Sağlama satırları verilen büyüklüğün birimiyle (V) biçimlenir
        var checkRows = PrintContent.ZenerRangeCheckRows(inverse);
        Assert.Equal("120 V", checkRows[0].X);
        Assert.Equal("200 V", checkRows[1].X);

        // Kart ve yazdırma belgesi Verilen + cevap satırlarını içerir
        var resp = new AnalysisResponseDto
        {
            Status = "success",
            Mode = "DC",
            AnalysisType = AnalysisTypes.ZenerRange,
            Results = new AnalysisResultsDto { ZenerRange = inverse },
        };
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.ShowResults(resp);

            var doc = SolutionPrinter.BuildDocument(new PrintInput
            {
                Response = resp,
                Method = "Zener Aralığı",
                Title = "Zener Ters Problem",
            });
            string allText = new TextRange(doc.ContentStart, doc.ContentEnd).Text;
            Assert.Contains("Verilen: 120 V", allText);
            Assert.Contains("1 kΩ", allText);
            Assert.Contains("Devredeki RY = 300 Ω, bulunan değer 1 kΩ", allText);
        });
    }
}
