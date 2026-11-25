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
using CircuitAnalyzer.WPF;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// "Dalga Şekli" (WAVEFORM) analiz yöntemi, Kare/Üçgen kaynak düzenleyici, belge/pano,
/// DTO, biçimlendirme, grafik, yazdırma ve yarım dalga doğrultucu örneği testleri.
/// </summary>
[Collection(WpfUiCollection.Name)]
public class WaveformUiTests
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

    private static string SampleSineResponseJson(bool underResults = true)
    {
        const string payload = """
        {
          "source_id": "VAC1",
          "shape": "SINE",
          "frequency": 50.0,
          "period": 0.02,
          "output_id": "R1",
          "output_label": "v_O (R1)",
          "t": [0.0, 0.005, 0.01, 0.015, 0.02],
          "v_in": [0.0, 10.0, 0.0, -10.0, 0.0],
          "v_out": [0.0, 9.3, 0.0, 0.0, 0.0],
          "diodes": [
            {
              "id": "D1",
              "intervals": [
                { "t_start": 0.0, "t_end": 0.01, "state": "ON" },
                { "t_start": 0.01, "t_end": 0.02, "state": "OFF" }
              ]
            }
          ],
          "v_out_max": 9.3,
          "v_out_min": 0.0,
          "v_dc_numeric": 2.841,
          "book_formula": {
            "name": "Yarım dalga doğrultucu",
            "text": "V_DC = 0,318·(V_m − V_T) = 0,318·(10 − 0,7) = 2,957 V",
            "value": 2.957
          },
          "conduction_angle_deg": 4.01,
          "levels": null
        }
        """;

        return underResults
            ? $$"""
            {
              "status": "success",
              "mode": "AC_PHASOR",
              "analysis_type": "WAVEFORM",
              "results": {
                "waveform": {{payload}}
              }
            }
            """
            : $$"""
            {
              "status": "success",
              "mode": "AC_PHASOR",
              "analysis_type": "WAVEFORM",
              "waveform": {{payload}}
            }
            """;
    }

    private static string SampleSquareResponseJson() => """
    {
      "status": "success",
      "mode": "AC_PHASOR",
      "analysis_type": "WAVEFORM",
      "results": {
        "waveform": {
          "source_id": "VAC1",
          "shape": "SQUARE",
          "frequency": 1000.0,
          "period": 0.001,
          "output_id": "R1",
          "output_label": "v_O (R1)",
          "t": [0.0, 0.0005, 0.0005, 0.001],
          "v_in": [10.0, 10.0, -15.0, -15.0],
          "v_out": [9.3, 9.3, 0.0, 0.0],
          "diodes": [
            {
              "id": "D1",
              "intervals": [
                { "t_start": 0.0, "t_end": 0.0005, "state": "ON" },
                { "t_start": 0.0005, "t_end": 0.001, "state": "OFF" }
              ]
            }
          ],
          "v_out_max": 9.3,
          "v_out_min": 0.0,
          "v_dc_numeric": 4.65,
          "book_formula": null,
          "conduction_angle_deg": null,
          "levels": [
            { "v_in": 10.0, "v_out": 9.3, "states": { "D1": "ON" } },
            { "v_in": -15.0, "v_out": 0.0, "states": { "D1": "OFF" } }
          ]
        }
      }
    }
    """;

    [Fact]
    public void SourceEditor_SquareAndTriangle_RoundTripNetlistWithNegativeAndDecimals()
    {
        RunOnSta(() =>
        {
            var src = new AcVoltageSource { Id = "V1", Amplitude = 10, Frequency = 50, Phase = 0 };
            var nodeMap = new Dictionary<Pin, int> { [src.Pins[0]] = 1, [src.Pins[1]] = 0 };

            // Kare dalga: negatif V2 ve ondalıklı V1 + 1 kHz frekans
            var editorSq = new ElementEditorWindow(src);
            Assert.NotNull(editorSq.WaveformCombo);
            Assert.Equal(0, editorSq.WaveformCombo!.SelectedIndex);
            editorSq.WaveformCombo.SelectedIndex = 1; // Kare

            Assert.Equal(3, editorSq.ValueBoxes.Count);
            Assert.Equal("1000", editorSq.ValueBoxes[2].Text); // Sinüs 50 Hz'den geçince 1 kHz varsayılanı

            editorSq.ValueBoxes[0].Text = "12,5";
            editorSq.ValueBoxes[1].Text = "-15,25";
            editorSq.ValueBoxes[2].Text = "1000";
            Assert.True(editorSq.TryApplyForTest());

            Assert.Equal(AcWaveform.Square, src.Waveform);
            Assert.Equal(12.5, src.SquareV1, 6);
            Assert.Equal(-15.25, src.SquareV2, 6);
            Assert.Equal(1000.0, src.Frequency, 6);
            Assert.Equal("V1 1 0 SQUARE(12.5 -15.25 1000)", src.ToNetlistEntry(nodeMap));
            Assert.Equal("Kare 12,5/−15,2 V, 1 kHz", src.FormatValue());
            Assert.NotNull(src.CreateVisual());

            // Üçgen dalga: tepe değeri ve frekans
            var editorTri = new ElementEditorWindow(src);
            Assert.Equal(1, editorTri.WaveformCombo!.SelectedIndex);
            editorTri.WaveformCombo.SelectedIndex = 2; // Üçgen

            Assert.Equal(2, editorTri.ValueBoxes.Count);
            editorTri.ValueBoxes[0].Text = "7,5";
            editorTri.ValueBoxes[1].Text = "2500";
            Assert.True(editorTri.TryApplyForTest());

            Assert.Equal(AcWaveform.Triangle, src.Waveform);
            Assert.Equal(7.5, src.Amplitude, 6);
            Assert.Equal(2500.0, src.Frequency, 6);
            Assert.Equal("V1 1 0 TRIANGLE(7.5 2500)", src.ToNetlistEntry(nodeMap));
            Assert.Equal("Üçgen 7,5 V, 2,5 kHz", src.FormatValue());
            Assert.NotNull(src.CreateVisual());
        });
    }

    [Fact]
    public void DocumentAndClipboard_WaveformSources_RoundTrip_AndLegacyLoadsAsSine()
    {
        var sq = new AcVoltageSource
        {
            Id = "VAC1",
            Waveform = AcWaveform.Square,
            SquareV1 = 10,
            SquareV2 = -15,
            Frequency = 1000,
        };
        var tri = new AcVoltageSource
        {
            Id = "VAC2",
            Waveform = AcWaveform.Triangle,
            Amplitude = 8.5,
            Frequency = 500,
        };

        var doc = CircuitDocument.FromCircuit(new CircuitElement[] { sq, tri }, Array.Empty<Wire>());
        string json = doc.ToJson();
        Assert.Contains("\"waveform\": \"SQUARE\"", json);
        Assert.Contains("\"v1\": 10", json);
        Assert.Contains("\"v2\": -15", json);
        Assert.Contains("\"waveform\": \"TRIANGLE\"", json);
        Assert.Contains("\"vp\": 8.5", json);

        var loaded = CircuitDocument.FromJson(json).ToCircuit("Test");
        var loadedSq = loaded.Elements.OfType<AcVoltageSource>().Single(e => e.Id == "VAC1");
        Assert.Equal(AcWaveform.Square, loadedSq.Waveform);
        Assert.Equal(10, loadedSq.SquareV1, 6);
        Assert.Equal(-15, loadedSq.SquareV2, 6);
        Assert.Equal(1000, loadedSq.Frequency, 6);

        var loadedTri = loaded.Elements.OfType<AcVoltageSource>().Single(e => e.Id == "VAC2");
        Assert.Equal(AcWaveform.Triangle, loadedTri.Waveform);
        Assert.Equal(8.5, loadedTri.Amplitude, 6);
        Assert.Equal(500, loadedTri.Frequency, 6);

        // Eski dosya (waveform alanı yok) → Sinüs olarak yüklenir
        const string legacyJson = """
        {
          "format": "devre-analizi",
          "version": 1,
          "elements": [
            { "type": "VAC", "id": "VAC1", "x": 100, "y": 100, "rotation": 0, "amplitude": 10, "frequency": 50, "phase": 0 }
          ],
          "wires": []
        }
        """;
        var legacyCircuit = CircuitDocument.FromJson(legacyJson).ToCircuit("Legacy");
        var legacyVac = legacyCircuit.Elements.OfType<AcVoltageSource>().Single();
        Assert.Equal(AcWaveform.Sine, legacyVac.Waveform);
        Assert.Equal(10, legacyVac.Amplitude, 6);
        Assert.Equal(50, legacyVac.Frequency, 6);

        // Pano (Clipboard) kopyala/yapıştır dalga biçimini korur
        var clip = new InMemoryClipboardService();
        CircuitClipboard.CopyToClipboard(clip, new CircuitElement[] { sq, tri });
        var pasted = CircuitClipboard.PasteFromClipboard(clip, new[] { "VAC1", "VAC2" }, new Point(40, 40));
        Assert.Equal(2, pasted.Elements.Count);
        var pastedSq = Assert.IsType<AcVoltageSource>(pasted.Elements[0]);
        Assert.Equal(AcWaveform.Square, pastedSq.Waveform);
        Assert.Equal(10, pastedSq.SquareV1, 6);
        Assert.Equal(-15, pastedSq.SquareV2, 6);
        var pastedTri = Assert.IsType<AcVoltageSource>(pasted.Elements[1]);
        Assert.Equal(AcWaveform.Triangle, pastedTri.Waveform);
        Assert.Equal(8.5, pastedTri.Amplitude, 6);
    }

    [Fact]
    public void MethodCombo_WaveformIsAppendedAfterZenerRange_AndMatchesAcrossCultures()
    {
        var original = CultureInfo.CurrentCulture;
        try
        {
            foreach (var cultureName in new[] { "tr-TR", "en-US", "" })
            {
                CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo(cultureName);
                Assert.Equal(AnalysisTypes.Waveform, AnalysisPanel.AnalysisTypeFromText("Dalga Şekli"));
            }
        }
        finally
        {
            CultureInfo.CurrentCulture = original;
        }

        Assert.Equal("WAVEFORM", AnalysisTypes.Waveform);
        Assert.False(AnalysisPanel.UsesTerminals(AnalysisTypes.Waveform));

        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            var labels = panel.MethodLabels;
            int zenerIdx = labels.ToList().IndexOf("Zener Aralığı");
            int waveIdx = labels.ToList().IndexOf("Dalga Şekli");
            Assert.True(zenerIdx >= 0);
            Assert.Equal(zenerIdx + 1, waveIdx);
        });
    }

    [Fact]
    public void WaveformOutputRow_VisibleOnlyForWaveform_ListsOnlyResistors_AndStaysInSync()
    {
        var elements = new CircuitElement[]
        {
            new AcVoltageSource { Id = "VAC1", Amplitude = 10, Frequency = 50 },
            new Diode(DiodeModel.Si) { Id = "D1" },
            new Resistor { Id = "R1", Value = 1000 },
            new Resistor { Id = "R2", Value = 2000 },
            new VoltageSource { Id = "V1", Value = 5 },
            new Capacitor { Id = "C1", Value = 1e-6 },
            new GroundElement { Id = "GND1" },
        };
        Assert.Equal(new[] { "R1", "R2" }, AnalysisPanel.WaveformOutputIds(elements));

        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAvailableWaveformOutputs(elements);

            Assert.Equal(Visibility.Collapsed, panel.RowWaveformOutput.Visibility);
            Assert.Equal("Çıkış elemanı", panel.TxtWaveformOutputLabel.Text);

            panel.SetAnalysisType(AnalysisTypes.Waveform);
            Assert.Equal(Visibility.Visible, panel.RowWaveformOutput.Visibility);
            Assert.Equal(Visibility.Collapsed, panel.RowZenerRangeTarget.Visibility);
            Assert.Null(panel.CmbWaveformOutput.SelectedItem);

            Assert.True(panel.TryGetOptions(out var optEmpty, out var err), err);
            Assert.Equal(AnalysisTypes.Waveform, optEmpty!.AnalysisType);
            Assert.Null(optEmpty.WaveformOutput);

            panel.CmbWaveformOutput.SelectedItem = "R2";
            Assert.True(panel.TryGetOptions(out var optR2, out err), err);
            Assert.Equal("R2", optR2!.WaveformOutput);

            // Belge gidiş-dönüşü (waveform_output)
            var settings = panel.GetAnalysisSettings();
            Assert.Equal("R2", settings.WaveformOutput);
            var docJson = new CircuitDocument { Analysis = settings }.ToJson();
            Assert.Contains("\"waveform_output\": \"R2\"", docJson);
            var loaded = CircuitDocument.FromJson(docJson);
            Assert.Equal("R2", loaded.Analysis!.WaveformOutput);

            var panel2 = new AnalysisPanel();
            panel2.SetAvailableWaveformOutputs(elements);
            panel2.RestoreAnalysisSettings(loaded.Analysis);
            Assert.Equal(AnalysisTypes.Waveform, panel2.GetAnalysisSettings().Type);
            Assert.Equal("R2", panel2.CmbWaveformOutput.SelectedItem);

            // Eleman yeniden adlandırılınca / silinince boş seçime döner
            panel.SetAvailableWaveformOutputs(new CircuitElement[]
            {
                new Resistor { Id = "R1", Value = 1000 },
                new Resistor { Id = "RY", Value = 2000 },
            });
            Assert.Null(panel.CmbWaveformOutput.SelectedItem);

            // Başka yönteme geçince gizlenir
            panel.SetAnalysisType(AnalysisTypes.Nodal);
            Assert.Equal(Visibility.Collapsed, panel.RowWaveformOutput.Visibility);
        });
    }

    [Fact]
    public void AnalysisRequestDto_WaveformOutput_SerializedWhenSet_OmittedWhenNull()
    {
        var req = new AnalysisRequestDto
        {
            Netlist = "VAC1 1 0 SINE(0 10 50 0 0 0)\nD1 1 2 SI\nR1 2 0 1000",
            AnalysisType = AnalysisTypes.Waveform,
            WaveformOutput = "R1",
        };
        string json = JsonSerializer.Serialize(req).Replace(" ", "");
        Assert.Contains("\"analysis_type\":\"WAVEFORM\"", json);
        Assert.Contains("\"waveform_output\":\"R1\"", json);

        var ask = LlmAskRequestDto.From(req, "Ortalama değer neden 2,841 V?");
        Assert.Equal("R1", ask.WaveformOutput);
        Assert.Contains("\"waveform_output\":\"R1\"", JsonSerializer.Serialize(ask).Replace(" ", ""));

        var reqNull = new AnalysisRequestDto { AnalysisType = AnalysisTypes.Waveform, WaveformOutput = null };
        Assert.DoesNotContain("waveform_output", JsonSerializer.Serialize(reqNull));
    }

    [Fact]
    public void ResponseDto_DeserializesSineWithBookFormula_AndSquareWithLevels_BothLocations()
    {
        var underResults = JsonSerializer.Deserialize<AnalysisResponseDto>(SampleSineResponseJson(underResults: true))!;
        var wf = underResults.WaveformResult;
        Assert.NotNull(wf);
        Assert.Equal("VAC1", wf!.SourceId);
        Assert.Equal("SINE", wf.Shape);
        Assert.Equal(50.0, wf.Frequency, 6);
        Assert.Equal(0.02, wf.Period, 6);
        Assert.Equal("R1", wf.OutputId);
        Assert.Equal(5, wf.T.Count);
        Assert.Equal(9.3, wf.VOutMax, 6);
        Assert.Equal(0.0, wf.VOutMin, 6);
        Assert.Equal(2.841, wf.VDcNumeric, 6);
        Assert.NotNull(wf.BookFormula);
        Assert.Equal("Yarım dalga doğrultucu", wf.BookFormula!.Name);
        Assert.Equal(2.957, wf.BookFormula.Value, 6);
        Assert.Equal(4.01, wf.ConductionAngleDeg!.Value, 6);
        Assert.Single(wf.Diodes);
        Assert.Equal(2, wf.Diodes[0].Intervals.Count);

        var topLevel = JsonSerializer.Deserialize<AnalysisResponseDto>(SampleSineResponseJson(underResults: false))!;
        Assert.NotNull(topLevel.WaveformResult);
        Assert.Equal(9.3, topLevel.WaveformResult!.VOutMax, 6);

        var sqResp = JsonSerializer.Deserialize<AnalysisResponseDto>(SampleSquareResponseJson())!;
        var sq = sqResp.WaveformResult;
        Assert.NotNull(sq);
        Assert.Equal("SQUARE", sq!.Shape);
        Assert.Null(sq.BookFormula);
        Assert.Null(sq.ConductionAngleDeg);
        Assert.NotNull(sq.Levels);
        Assert.Equal(2, sq.Levels!.Count);
        Assert.Equal(10.0, sq.Levels[0].VIn, 6);
        Assert.Equal(9.3, sq.Levels[0].VOut, 6);
        Assert.Equal("ON", sq.Levels[0].States["D1"]);
        Assert.Equal(-15.0, sq.Levels[1].VIn, 6);
        Assert.Equal("OFF", sq.Levels[1].States["D1"]);
    }

    [Fact]
    public void FormattingHelpers_FormatExtremaDcBookAngleAndIntervalsWithTurkishComma()
    {
        var sine = JsonSerializer.Deserialize<AnalysisResponseDto>(SampleSineResponseJson())!.WaveformResult!;
        Assert.Equal("V_O,max = 9,3 V · V_O,min = 0 V", AnalysisPanel.FormatWaveformExtrema(sine));
        Assert.Equal("Ortalama (DC) değer: 2,841 V (sayısal)", AnalysisPanel.FormatWaveformDcNumeric(sine));
        Assert.Equal(
            "Kitap formülü (Yarım dalga doğrultucu): V_DC = 0,318·(V_m − V_T) = 0,318·(10 − 0,7) = 2,957 V",
            AnalysisPanel.FormatWaveformBookFormula(sine.BookFormula));
        Assert.Equal("İletim θ = 4,01° den başlar", AnalysisPanel.FormatWaveformConductionAngle(sine.ConductionAngleDeg));

        var (scale50, unit50) = WaveformPlotView.TimeUnitFor(sine);
        Assert.Equal("ms", unit50);
        Assert.Equal(1000.0, scale50);
        Assert.Equal("0–10 ms iletimde · 10–20 ms yalıtımda",
            AnalysisPanel.FormatWaveformDiodeIntervals(sine.Diodes[0], scale50, unit50));

        var sq = JsonSerializer.Deserialize<AnalysisResponseDto>(SampleSquareResponseJson())!.WaveformResult!;
        var (scale1k, unit1k) = WaveformPlotView.TimeUnitFor(sq);
        Assert.Equal("ms", unit1k);
        Assert.Equal("0–0,5 ms iletimde · 0,5–1 ms yalıtımda",
            AnalysisPanel.FormatWaveformDiodeIntervals(sq.Diodes[0], scale1k, unit1k));
        Assert.Equal("D1: iletimde", AnalysisPanel.FormatWaveformLevelStates(sq.Levels![0].States));
    }

    [Fact]
    public void WaveformPlotView_ResultsCard_AndPrintDocument_BuildWithoutThrowing()
    {
        var sineResp = JsonSerializer.Deserialize<AnalysisResponseDto>(SampleSineResponseJson())!;
        var sqResp = JsonSerializer.Deserialize<AnalysisResponseDto>(SampleSquareResponseJson())!;

        RunOnSta(() =>
        {
            var plotView = new WaveformPlotView();
            plotView.LoadData(sineResp.WaveformResult!);
            plotView.LoadData(sqResp.WaveformResult!);

            var panel = new AnalysisPanel();
            panel.ShowResults(sineResp);
            panel.ShowResults(sqResp);

            var figures = PrintContent.Figures(sineResp);
            Assert.Contains(figures, f => f.Kind == PrintFigureKind.WaveformPlot);

            var docSine = SolutionPrinter.BuildDocument(new PrintInput
            {
                Response = sineResp,
                Method = "Dalga Şekli",
                Title = "Yarım Dalga Doğrultucu",
            });
            string textSine = new TextRange(docSine.ContentStart, docSine.ContentEnd).Text;
            Assert.Contains("Dalga Şekli", textSine);
            Assert.Contains("9,3 V", textSine);
            Assert.Contains("2,841 V", textSine);
            Assert.Contains("Yarım dalga doğrultucu", textSine);
            Assert.Contains("4,01°", textSine);
            Assert.Contains("0–10 ms iletimde", textSine);

            var docSq = SolutionPrinter.BuildDocument(new PrintInput
            {
                Response = sqResp,
                Method = "Dalga Şekli",
                Title = "Kare Dalga",
            });
            string textSq = new TextRange(docSq.ContentStart, docSq.ContentEnd).Text;
            Assert.Contains("Seviyeler", textSq);
            Assert.Contains("−15 V", textSq);
            Assert.Contains("0–0,5 ms iletimde", textSq);
        });
    }

    [Fact]
    public void ExampleCircuit_AcHalfWaveRectifierSi_ExistsAndHasValidNetlist()
    {
        Assert.Contains((Func<ExampleCircuit>)ExampleCircuits.AcHalfWaveRectifierSi, ExampleCircuits.All);

        var c = ExampleCircuits.AcHalfWaveRectifierSi();
        Assert.Equal("Doğrultucu: Yarım Dalga (Si)", c.Name);
        Assert.Equal(AnalysisTypes.Waveform, c.SuggestedAnalysisType);
        Assert.Equal("R1", c.SuggestedWaveformOutput);

        var netlist = NetlistBuilder.Build(c.Elements, c.Wires);
        Assert.True(netlist.HasGround);
        Assert.True(netlist.HasAcSource);

        var src = c.Elements.OfType<AcVoltageSource>().Single();
        Assert.Equal(AcWaveform.Sine, src.Waveform);
        Assert.Equal(10.0, src.Amplitude, 6);
        Assert.Equal(50.0, src.Frequency, 6);
        Assert.Equal(AcValueKind.Peak, src.ValueKind);

        var d1 = c.Elements.OfType<Diode>().Single();
        Assert.Equal(DiodeModel.Si, d1.Model);

        var r1 = c.Elements.OfType<Resistor>().Single();
        Assert.Equal("R1", r1.Id);
        Assert.Equal(1000.0, r1.Value, 6);

        Assert.Contains("SINE(0 10 50 0 0 0)", netlist.Text);
        Assert.Contains("SI", netlist.Text);
        Assert.Contains("R1 ", netlist.Text);
    }

    private static string SampleClamperResponseJson(string? rcNote = null, bool includeStaleRectifierFields = false)
    {
        string rcJson = rcNote == null ? "null" : JsonSerializer.Serialize(rcNote);
        string bookJson = includeStaleRectifierFields
            ? """{ "name": "Sahte", "text": "V_DC = 1 V", "value": 1.0 }"""
            : "null";
        string angleJson = includeStaleRectifierFields ? "12.5" : "null";

        return $$"""
        {
          "status": "success",
          "mode": "AC_PHASOR",
          "analysis_type": "WAVEFORM",
          "results": {
            "node_voltages": {
              "1": { "value": -15.0, "unit": "V" },
              "2": { "value": -0.7, "unit": "V" }
            },
            "element_currents": {
              "R1": { "value": -0.00007, "unit": "A", "direction": "2→0" },
              "D1": { "value": 0.00007, "unit": "A", "direction": "0→2" }
            },
            "diodes": [
              { "id": "D1", "model": "SI", "v_t": 0.7, "state": "ON", "v_ak": 0.7, "i": 0.00007 }
            ],
            "waveform": {
              "source_id": "VAC1",
              "shape": "SQUARE",
              "frequency": 250.0,
              "period": 0.004,
              "output_id": "R1",
              "output_label": "v_O (R1)",
              "t": [0.0, 0.002, 0.002, 0.004],
              "v_in": [10.0, 10.0, -15.0, -15.0],
              "v_out": [24.3, 24.3, -0.7, -0.7],
              "diodes": [
                {
                  "id": "D1",
                  "intervals": [
                    { "t_start": 0.0, "t_end": 0.002, "state": "OFF" },
                    { "t_start": 0.002, "t_end": 0.004, "state": "ON" }
                  ]
                }
              ],
              "v_out_max": 24.3,
              "v_out_min": -0.7,
              "v_dc_numeric": 11.8,
              "book_formula": {{bookJson}},
              "conduction_angle_deg": {{angleJson}},
              "levels": [
                { "v_in": 10.0, "v_out": 24.3, "states": { "D1": "OFF" } },
                { "v_in": -15.0, "v_out": -0.7, "states": { "D1": "ON" } }
              ],
              "clamper": {
                "v_c": -14.3,
                "v_c_plus_side": "OUTPUT",
                "v_k": -0.7,
                "pinned": "BOTTOM",
                "shift": "UP",
                "input_swing": 25.0,
                "output_swing": 25.0,
                "checks": [
                  { "name": "Salınım", "ok": true, "text": "25 V = 25 V (korundu)" },
                  { "name": "Zaman sabiti", "ok": false, "text": "τ = 0.5 ms, T/2 = 2 ms" },
                  { "name": "DC kaynak", "ok": null, "text": "Kolda ek DC kaynak yok" }
                ],
                "tau": 0.1,
                "period": 0.004,
                "rc_note": {{rcJson}}
              }
            }
          }
        }
        """;
    }

    private static List<string> CollectRenderedTexts(DependencyObject root)
    {
        var texts = new List<string>();
        var visited = new HashSet<DependencyObject>();

        static string InlineText(Inline inline) => inline switch
        {
            Run r => r.Text,
            Span s => string.Concat(s.Inlines.Select(InlineText)),
            LineBreak => "\n",
            _ => "",
        };

        void Visit(DependencyObject obj)
        {
            if (!visited.Add(obj)) return;

            if (obj is TextBlock tb)
            {
                string t = tb.Inlines.Count > 0
                    ? string.Concat(tb.Inlines.Select(InlineText))
                    : tb.Text;
                if (!string.IsNullOrEmpty(t))
                    texts.Add(t);
            }

            if (obj is Border b && b.Child != null)
                Visit(b.Child);
            if (obj is Panel p)
            {
                foreach (UIElement child in p.Children)
                    Visit(child);
            }
            if (obj is ContentControl cc && cc.Content is DependencyObject cdo)
                Visit(cdo);
        }

        Visit(root);
        return texts;
    }

    [Fact]
    public void ResponseDto_DeserializesClamper_WithChecksTrueFalseNull_AndRcNoteNullOrPresent()
    {
        var respNullNote = JsonSerializer.Deserialize<AnalysisResponseDto>(SampleClamperResponseJson(rcNote: null))!;
        var wf = respNullNote.WaveformResult;
        Assert.NotNull(wf);
        Assert.NotNull(wf!.Clamper);

        var c = wf.Clamper!;
        Assert.Equal(-14.3, c.VC, 6);
        Assert.Equal("OUTPUT", c.VCPlusSide);
        Assert.Equal(-0.7, c.VK, 6);
        Assert.Equal("BOTTOM", c.Pinned);
        Assert.Equal("UP", c.Shift);
        Assert.Equal(25.0, c.InputSwing, 6);
        Assert.Equal(25.0, c.OutputSwing, 6);
        Assert.Equal(0.1, c.Tau, 6);
        Assert.Equal(0.004, c.Period, 6);
        Assert.Null(c.RcNote);

        Assert.Equal(3, c.Checks.Count);
        Assert.Equal("Salınım", c.Checks[0].Name);
        Assert.True(c.Checks[0].Ok);
        Assert.Equal("Zaman sabiti", c.Checks[1].Name);
        Assert.False(c.Checks[1].Ok);
        Assert.Equal("DC kaynak", c.Checks[2].Name);
        Assert.Null(c.Checks[2].Ok);

        var respWithNote = JsonSerializer.Deserialize<AnalysisResponseDto>(
            SampleClamperResponseJson(rcNote: "RC zaman sabiti 5τ ≥ T/2 koşulunu tam sağlamıyor (τ = 0.5 ms)."))!;
        Assert.Equal("RC zaman sabiti 5τ ≥ T/2 koşulunu tam sağlamıyor (τ = 0.5 ms).", respWithNote.WaveformResult!.Clamper!.RcNote);
    }

    [Fact]
    public void ClamperFormattingHelpers_FormatSideShiftSwingVerdictsAndDecimalComma()
    {
        var downInput = new WaveformClamperDto
        {
            VC = 10.0,
            VCPlusSide = "INPUT",
            VK = 0.7,
            Pinned = "TOP",
            Shift = "DOWN",
            InputSwing = 25.0,
            OutputSwing = 25.0,
        };
        Assert.Equal("V_C = 10 V (+ ucu giriş tarafında)", AnalysisPanel.FormatWaveformClamperVC(downInput));
        Assert.Equal("Diyot iletimdeyken V_O = 0,7 V", AnalysisPanel.FormatWaveformClamperConductingVO(downInput));
        Assert.Equal("Çıkış, girişin 10 V aşağı kaymış hâlidir", AnalysisPanel.FormatWaveformClamperShift(downInput));
        Assert.Equal("Salınım: Giriş 25 V · Çıkış 25 V", AnalysisPanel.FormatWaveformClamperSwing(downInput));

        var upOutput = new WaveformClamperDto
        {
            VC = -14.3,
            VCPlusSide = "OUTPUT",
            VK = -0.7,
            Pinned = "BOTTOM",
            Shift = "UP",
            InputSwing = 25.5,
            OutputSwing = 25.5,
        };
        Assert.Equal("V_C = 14,3 V (+ ucu çıkış tarafında)", AnalysisPanel.FormatWaveformClamperVC(upOutput));
        Assert.Equal("Diyot iletimdeyken V_O = −0,7 V", AnalysisPanel.FormatWaveformClamperConductingVO(upOutput));
        Assert.Equal("Çıkış, girişin 14,3 V yukarı kaymış hâlidir", AnalysisPanel.FormatWaveformClamperShift(upOutput));
        Assert.Equal("Salınım: Giriş 25,5 V · Çıkış 25,5 V", AnalysisPanel.FormatWaveformClamperSwing(upOutput));

        Assert.Equal(("Uygun ✓", "Brush.Success"), AnalysisPanel.FormatWaveformClamperCheckVerdict(true));
        Assert.Equal(("Uymuyor ✗", "Brush.Error"), AnalysisPanel.FormatWaveformClamperCheckVerdict(false));
        Assert.Equal(("Uygulanmaz", "Brush.Text.Secondary"), AnalysisPanel.FormatWaveformClamperCheckVerdict(null));

        Assert.Null(AnalysisPanel.FormatWaveformClamperRcNote(null));
        Assert.Null(AnalysisPanel.FormatWaveformClamperRcNote("   "));
        Assert.Equal("τ = 0,5 ms < T/2", AnalysisPanel.FormatWaveformClamperRcNote("ℹ τ = 0.5 ms < T/2"));
    }

    [Fact]
    public void ClamperResultsCard_ShowsKenetlemeBlock_AndHidesBookFormulaAndConductionAngle()
    {
        var resp = JsonSerializer.Deserialize<AnalysisResponseDto>(
            SampleClamperResponseJson(rcNote: "τ = 0.5 ms küçük olduğu için boşalma görülebilir.", includeStaleRectifierFields: true))!;

        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.ShowResults(resp);
            panel.SelectExplanationView(false);

            var texts = CollectRenderedTexts(panel.ResultsCard);
            string joined = string.Join("\n", texts);

            Assert.Contains("Kenetleme", joined);
            Assert.Contains("VC = 14,3 V (+ ucu çıkış tarafında)", joined);
            Assert.Contains("Diyot iletimdeyken VO = −0,7 V", joined);
            Assert.Contains("Çıkış, girişin 14,3 V yukarı kaymış hâlidir", joined);
            Assert.Contains("Salınım: Giriş 25 V · Çıkış 25 V", joined);
            Assert.Contains("Uygun ✓", joined);
            Assert.Contains("Uymuyor ✗", joined);
            Assert.Contains("Uygulanmaz", joined);
            Assert.Contains("τ = 0,5 ms küçük olduğu için boşalma görülebilir.", joined);

            // Kenetleyicide kitap formülü ve iletim açısı satırları gösterilmemeli
            Assert.DoesNotContain("Kitap formülü", joined);
            Assert.DoesNotContain("İletim θ", joined);
        });
    }

    [Fact]
    public void PrintContentAndSolutionPrinter_IncludeKenetlemeBlock_AndHideBookFormulaAndAngle()
    {
        var resp = JsonSerializer.Deserialize<AnalysisResponseDto>(
            SampleClamperResponseJson(rcNote: "τ = 0.5 ms < T/2", includeStaleRectifierFields: true))!;
        var wf = resp.WaveformResult!;

        var summary = PrintContent.WaveformClamperSummaryLines(wf);
        Assert.Equal(4, summary.Count);
        Assert.Equal("V_C = 14,3 V (+ ucu çıkış tarafında)", summary[0]);
        Assert.Equal("Diyot iletimdeyken V_O = −0,7 V", summary[1]);
        Assert.Equal("Çıkış, girişin 14,3 V yukarı kaymış hâlidir", summary[2]);
        Assert.Equal("Salınım: Giriş 25 V · Çıkış 25 V", summary[3]);

        var checkRows = PrintContent.WaveformClamperCheckRows(wf);
        Assert.Equal(3, checkRows.Count);
        Assert.Equal(("Salınım", "Uygun ✓", "Brush.Success", "25 V = 25 V (korundu)"), checkRows[0]);
        Assert.Equal(("Zaman sabiti", "Uymuyor ✗", "Brush.Error", "τ = 0,5 ms, T/2 = 2 ms"), checkRows[1]);
        Assert.Equal(("DC kaynak", "Uygulanmaz", "Brush.Text.Secondary", "Kolda ek DC kaynak yok"), checkRows[2]);
        Assert.Equal("τ = 0,5 ms < T/2", PrintContent.WaveformClamperRcNote(wf));

        RunOnSta(() =>
        {
            var doc = SolutionPrinter.BuildDocument(new PrintInput
            {
                Response = resp,
                Method = "Dalga Şekli",
                Title = "Kenetleyici: Si Diyot (kare dalga)",
            });
            string text = new TextRange(doc.ContentStart, doc.ContentEnd).Text;

            Assert.Contains("Kenetleme", text);
            Assert.Contains("14,3 V (+ ucu çıkış tarafında)", text);
            Assert.Contains("Diyot iletimdeyken", text);
            Assert.Contains("−0,7 V", text);
            Assert.Contains("Çıkış, girişin 14,3 V yukarı kaymış hâlidir", text);
            Assert.Contains("Salınım: Giriş 25 V · Çıkış 25 V", text);
            Assert.Contains("Uygun ✓", text);
            Assert.Contains("Uymuyor ✗", text);
            Assert.Contains("Uygulanmaz", text);
            Assert.Contains("τ = 0,5 ms < T/2", text);
            Assert.DoesNotContain("Kitap formülü", text);
            Assert.DoesNotContain("İletim θ", text);
        });
    }

    [Fact]
    public void ClamperCircuit_AllowsWaveformMethod_ListsOnlyResistors_AndSerializesRequest()
    {
        var c = ExampleCircuits.AcClamperSiSquare();
        var netlist = NetlistBuilder.Build(c.Elements, c.Wires);

        Assert.True(netlist.HasGround);
        Assert.True(netlist.HasAcSource);
        Assert.Empty(netlist.PhasorFrequencies);

        // Çıkış elemanı listesi kapasitör veya diyot değil yalnızca dirençleri içerir
        Assert.Equal(new[] { "R1" }, AnalysisPanel.WaveformOutputIds(c.Elements));

        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetCircuitInfo(netlist.HasAcSource, needsFrequency: false);
            panel.SetAvailableWaveformOutputs(c.Elements);
            panel.SetAnalysisType(AnalysisTypes.Waveform);
            panel.SetWaveformOutput("R1");

            Assert.Equal(Visibility.Visible, panel.RowWaveformOutput.Visibility);
            Assert.Equal(Visibility.Collapsed, panel.RowValueDisplay.Visibility);
            Assert.True(panel.TryGetOptions(out var options, out var err), err);
            Assert.Equal(AnalysisTypes.Waveform, options!.AnalysisType);
            Assert.Equal("R1", options.WaveformOutput);

            var req = new AnalysisRequestDto
            {
                Netlist = netlist.Text,
                Mode = netlist.HasAcSource ? AnalysisModes.AcPhasor : AnalysisModes.Dc,
                AnalysisType = options.AnalysisType,
                WaveformOutput = options.WaveformOutput,
            };
            string json = JsonSerializer.Serialize(req).Replace(" ", "");
            Assert.Contains("\"analysis_type\":\"WAVEFORM\"", json);
            Assert.Contains("\"waveform_output\":\"R1\"", json);
        });
    }

    [Fact]
    public void ResultOverlay_ClamperCircuit_RendersCapacitorVoltageAndDiodeStateWithoutCrashing()
    {
        var c = ExampleCircuits.AcClamperSiSquare();
        var netlist = NetlistBuilder.Build(c.Elements, c.Wires);
        var resp = JsonSerializer.Deserialize<AnalysisResponseDto>(SampleClamperResponseJson())!;

        RunOnSta(() =>
        {
            foreach (var w in c.Wires)
                w.CreateOrUpdateVisual();

            var canvas = new Canvas();
            var overlay = new ResultOverlay(canvas);
            overlay.ShowResults(netlist, c.Elements, c.Wires, resp);

            var texts = CollectRenderedTexts(canvas);
            string joined = string.Join("\n", texts);

            Assert.Contains("VC = 14,3 V", joined);
            Assert.Contains("iletimde", joined);
        });
    }

    [Fact]
    public void ExampleCircuit_AcClamperSiSquare_IsLastAndHasExpectedNetlistTopology()
    {
        Assert.Equal((Func<ExampleCircuit>)ExampleCircuits.AcClamperSiSquare, ExampleCircuits.All[^1]);

        var c = ExampleCircuits.AcClamperSiSquare();
        Assert.Equal("Kenetleyici: Si Diyot (kare dalga)", c.Name);
        Assert.Equal(AnalysisTypes.Waveform, c.SuggestedAnalysisType);
        Assert.Equal("R1", c.SuggestedWaveformOutput);

        var netlist = NetlistBuilder.Build(c.Elements, c.Wires);
        Assert.True(netlist.HasGround);
        Assert.True(netlist.HasAcSource);

        var src = c.Elements.OfType<AcVoltageSource>().Single();
        Assert.Equal(AcWaveform.Square, src.Waveform);
        Assert.Equal(10.0, src.SquareV1, 6);
        Assert.Equal(-15.0, src.SquareV2, 6);
        Assert.Equal(250.0, src.Frequency, 6);

        var cap = c.Elements.OfType<Capacitor>().Single();
        Assert.Equal(10e-6, cap.Value, 12);

        var diode = c.Elements.OfType<Diode>().Single();
        Assert.Equal(DiodeModel.Si, diode.Model);

        var res = c.Elements.OfType<Resistor>().Single();
        Assert.Equal("R1", res.Id);
        Assert.Equal(10_000.0, res.Value, 6);

        // Düğüm yerleşimi: kaynak sıcak uç → C1 → çıkış düğümü; D1 anot GND'de, katot çıkışta; R1 çıkış → GND
        int hotNode = netlist.NodeMap[src.Pins[0]];
        int gndNode = netlist.NodeMap[src.Pins[1]];
        int outNode = netlist.NodeMap[cap.Pins[1]];
        Assert.Equal(0, gndNode);
        Assert.NotEqual(0, hotNode);
        Assert.NotEqual(0, outNode);
        Assert.NotEqual(hotNode, outNode);

        Assert.Equal(hotNode, netlist.NodeMap[cap.Pins[0]]);
        Assert.Equal(0, netlist.NodeMap[diode.Pins[0]]);        // Anot GND'de
        Assert.Equal(outNode, netlist.NodeMap[diode.Pins[1]]);  // Katot çıkış düğümünde
        Assert.Equal(outNode, netlist.NodeMap[res.Pins[0]]);
        Assert.Equal(0, netlist.NodeMap[res.Pins[1]]);

        Assert.Contains($"VAC1 {hotNode} 0 SQUARE(10 -15 250)", netlist.Text);
        Assert.Contains($"C1 {hotNode} {outNode} 10u", netlist.Text);
        Assert.Contains($"D1 0 {outNode} SI", netlist.Text);
        Assert.Contains($"R1 {outNode} 0 ", netlist.Text);
    }
}
