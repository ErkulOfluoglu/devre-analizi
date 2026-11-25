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
}
