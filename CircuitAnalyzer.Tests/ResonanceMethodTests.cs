using System;
using System.Collections.Generic;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// "Rezonans" (RESONANCE) çözüm yöntemi testleri:
/// DTO'lar, JSON eşleme, panel ayarları, terminal istememe ve ResonanceCurveView.
/// </summary>
[Collection(WpfUiCollection.Name)]
public class ResonanceMethodTests
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

    [Theory]
    [InlineData("Rezonans")]
    [InlineData("rezonans")]
    [InlineData("REZONANS")]
    public void AnalysisTypeFromText_Resonance_Matches(string text)
    {
        Assert.Equal(AnalysisTypes.Resonance, AnalysisPanel.AnalysisTypeFromText(text));
    }

    [Fact]
    public void UsesTerminals_Resonance_ReturnsFalse()
    {
        Assert.False(AnalysisPanel.UsesTerminals(AnalysisTypes.Resonance));
    }

    [Fact]
    public void Resonance_TerminalRow_NotVisible_AndNeedsNoTerminals()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAnalysisType(AnalysisTypes.Resonance);

            Assert.Equal(9, panel.CmbAnalysisType.SelectedIndex);
            Assert.Equal(Visibility.Collapsed, panel.RowTerminals.Visibility);
            Assert.Equal(Visibility.Collapsed, panel.RowPowerFactorTarget.Visibility);

            Assert.True(panel.TryGetOptions(out var opt, out var err), err);
            Assert.NotNull(opt);
            Assert.Equal(AnalysisTypes.Resonance, opt!.AnalysisType);
            Assert.Null(opt.TerminalPositive);
        });
    }

    [Fact]
    public void AnalysisData_Resonance_RoundTrip()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAnalysisType(AnalysisTypes.Resonance);

            var settings = panel.GetAnalysisSettings();
            Assert.Equal(AnalysisTypes.Resonance, settings.Type);

            var panel2 = new AnalysisPanel();
            panel2.RestoreAnalysisSettings(settings);

            Assert.Equal(9, panel2.CmbAnalysisType.SelectedIndex);
            Assert.Equal(AnalysisTypes.Resonance, panel2.GetAnalysisSettings().Type);
        });
    }

    [Fact]
    public void CircuitDocument_Json_RoundTrips_Resonance()
    {
        var doc = new CircuitDocument
        {
            Analysis = new CircuitDocument.AnalysisData
            {
                Type = AnalysisTypes.Resonance,
            }
        };

        string json = doc.ToJson();
        Assert.Contains("\"type\": \"RESONANCE\"", json);

        var loaded = CircuitDocument.FromJson(json);
        Assert.NotNull(loaded.Analysis);
        Assert.Equal(AnalysisTypes.Resonance, loaded.Analysis!.Type);
    }

    [Fact]
    public void Resonance_JsonReading_Series()
    {
        const string json = """
        {
          "status": "success",
          "mode": "AC_PHASOR",
          "analysis_type": "RESONANCE",
          "resonance": {
            "kind": "series",
            "f0": 1000.0,
            "w0": 6283.185,
            "x": 62.83,
            "q": 10.0,
            "bw": 100.0,
            "f1": 951.2,
            "f2": 1051.2,
            "f1_exact": 951.249,
            "f2_exact": 1051.249,
            "z0": 10.0,
            "i0": 1.0,
            "v0": 10.0,
            "curve": {
              "quantity": "I",
              "unit": "A",
              "f": [900.0, 951.249, 1000.0, 1051.249, 1100.0],
              "y": [0.4, 0.707, 1.0, 0.707, 0.4]
            }
          }
        }
        """;

        var response = JsonSerializer.Deserialize<AnalysisResponseDto>(json);
        Assert.NotNull(response);
        Assert.NotNull(response!.Resonance);
        Assert.Equal("series", response.Resonance!.Kind);
        Assert.Equal(1000.0, response.Resonance.F0);
        Assert.Equal(6283.185, response.Resonance.W0);
        Assert.Equal(62.83, response.Resonance.X);
        Assert.Equal(10.0, response.Resonance.Q);
        Assert.Equal(100.0, response.Resonance.Bw);
        Assert.Equal(951.2, response.Resonance.F1);
        Assert.Equal(1051.2, response.Resonance.F2);
        Assert.Equal(951.249, response.Resonance.F1Exact);
        Assert.Equal(1051.249, response.Resonance.F2Exact);
        Assert.Equal(10.0, response.Resonance.Z0);
        Assert.Equal(1.0, response.Resonance.I0);
        Assert.Equal(10.0, response.Resonance.V0);
        Assert.NotNull(response.Resonance.Curve);
        Assert.Equal("I", response.Resonance.Curve!.Quantity);
        Assert.Equal("A", response.Resonance.Curve.Unit);
        Assert.Equal(5, response.Resonance.Curve.F.Count);
        Assert.Equal(5, response.Resonance.Curve.Y.Count);
    }

    [Fact]
    public void Resonance_JsonReading_Parallel_InsideResults()
    {
        const string json = """
        {
          "status": "success",
          "mode": "AC_PHASOR",
          "analysis_type": "RESONANCE",
          "results": {
            "resonance": {
              "kind": "parallel",
              "f0": 5000.0,
              "w0": 31415.9,
              "x": 314.16,
              "q": 25.0,
              "bw": 200.0,
              "f1": 4900.0,
              "f2": 5100.0,
              "f1_exact": 4901.96,
              "f2_exact": 5101.96,
              "z0": 7854.0,
              "i0": 0.00127,
              "v0": 10.0,
              "curve": {
                "quantity": "Z",
                "unit": "Ω",
                "f": [4700.0, 4901.96, 5000.0, 5101.96, 5300.0],
                "y": [3000.0, 5552.78, 7854.0, 5552.78, 3000.0]
              }
            }
          }
        }
        """;

        var response = JsonSerializer.Deserialize<AnalysisResponseDto>(json);
        Assert.NotNull(response);
        var res = response!.Resonance ?? response.Results.Resonance;
        Assert.NotNull(res);
        Assert.Equal("parallel", res!.Kind);
        Assert.Equal(5000.0, res.F0);
        Assert.Equal(25.0, res.Q);
        Assert.Equal(200.0, res.Bw);
        Assert.Equal(7854.0, res.Z0);
        Assert.NotNull(res.Curve);
        Assert.Equal("Z", res.Curve!.Quantity);
        Assert.Equal("Ω", res.Curve.Unit);
    }

    [Fact]
    public void ResonanceCurveView_Series_RendersWithoutCrashing()
    {
        RunOnSta(() =>
        {
            var view = new ResonanceCurveView();
            var dto = new ResonanceDto
            {
                Kind = "series",
                F0 = 1000.0,
                W0 = 6283.18,
                X = 62.83,
                Q = 10.0,
                Bw = 100.0,
                F1 = 951.2,
                F2 = 1051.2,
                F1Exact = 951.249,
                F2Exact = 1051.249,
                Z0 = 10.0,
                I0 = 1.0,
                V0 = 10.0,
                Curve = new ResonanceCurveDto
                {
                    Quantity = "I",
                    Unit = "A",
                    F = new List<double> { 900, 950, 1000, 1050, 1100 },
                    Y = new List<double> { 0.4, 0.707, 1.0, 0.707, 0.4 }
                }
            };

            view.LoadData(dto);

            Assert.Contains("f₀ = 1 kHz", view.TxtSummaryInfo.Text);
            Assert.Contains("Q = 10", view.TxtSummaryInfo.Text);
            Assert.Contains("BW = 100 Hz", view.TxtSummaryInfo.Text);

            // IsEnlarged toggle
            Assert.False(view.IsEnlarged);
            view.IsEnlarged = true;
            Assert.True(view.IsEnlarged);
            view.IsEnlarged = false;
            Assert.False(view.IsEnlarged);
        });
    }

    [Fact]
    public void ResonanceCurveView_Parallel_RendersWithoutCrashing()
    {
        RunOnSta(() =>
        {
            var view = new ResonanceCurveView();
            var dto = new ResonanceDto
            {
                Kind = "parallel",
                F0 = 5000.0,
                W0 = 31415.9,
                X = 314.16,
                Q = 25.0,
                Bw = 200.0,
                F1 = 4900.0,
                F2 = 5100.0,
                F1Exact = 4901.96,
                F2Exact = 5101.96,
                Z0 = 7854.0,
                I0 = 0.00127,
                V0 = 10.0,
                Curve = new ResonanceCurveDto
                {
                    Quantity = "Z",
                    Unit = "Ω",
                    F = new List<double> { 4800, 4902, 5000, 5098, 5200 },
                    Y = new List<double> { 3000, 5552, 7854, 5552, 3000 }
                }
            };

            view.LoadData(dto);

            Assert.Contains("f₀ = 5 kHz", view.TxtSummaryInfo.Text);
            Assert.Contains("Q = 25", view.TxtSummaryInfo.Text);
            Assert.Contains("BW = 200 Hz", view.TxtSummaryInfo.Text);
        });
    }

    [Fact]
    public void ResonanceCurveView_EmptyCurve_RendersWithoutCrashing()
    {
        RunOnSta(() =>
        {
            var view = new ResonanceCurveView();

            // 1. Curve is null
            view.LoadData(new ResonanceDto
            {
                Kind = "series",
                F0 = 1000.0,
                Q = 5.0,
                Bw = 200.0,
                Curve = null
            });
            Assert.Contains("f₀ = 1 kHz", view.TxtSummaryInfo.Text);

            // 2. Curve lists are empty
            view.LoadData(new ResonanceDto
            {
                Kind = "parallel",
                F0 = 2000.0,
                Q = 8.0,
                Bw = 250.0,
                Curve = new ResonanceCurveDto
                {
                    F = new List<double>(),
                    Y = new List<double>()
                }
            });
            Assert.Contains("f₀ = 2 kHz", view.TxtSummaryInfo.Text);
        });
    }

    [Fact]
    public void ResonanceCurveView_SinglePointCurve_RendersWithoutCrashing()
    {
        RunOnSta(() =>
        {
            var view = new ResonanceCurveView();
            view.LoadData(new ResonanceDto
            {
                Kind = "series",
                F0 = 1000.0,
                Q = 10.0,
                Bw = 100.0,
                I0 = 1.0,
                Curve = new ResonanceCurveDto
                {
                    Quantity = "I",
                    Unit = "A",
                    F = new List<double> { 1000.0 },
                    Y = new List<double> { 1.0 }
                }
            });

            Assert.Contains("f₀ = 1 kHz", view.TxtSummaryInfo.Text);
        });
    }

    [Fact]
    public void ResonanceCurveView_HighQ_RendersWithoutCrashing()
    {
        RunOnSta(() =>
        {
            var view = new ResonanceCurveView();
            view.LoadData(new ResonanceDto
            {
                Kind = "series",
                F0 = 1000000.0, // 1 MHz
                W0 = 6283185.3,
                X = 1000.0,
                Q = 500.0,
                Bw = 2000.0,
                F1 = 999000.0,
                F2 = 1001000.0,
                F1Exact = 999001.0,
                F2Exact = 1001001.0,
                Z0 = 2.0,
                I0 = 5.0,
                V0 = 10.0,
                Curve = new ResonanceCurveDto
                {
                    Quantity = "I",
                    Unit = "A",
                    F = new List<double> { 998000.0, 999001.0, 1000000.0, 1001001.0, 1002000.0 },
                    Y = new List<double> { 1.0, 3.535, 5.0, 3.535, 1.0 }
                }
            });

            Assert.Contains("f₀ = 1 MHz", view.TxtSummaryInfo.Text);
            Assert.Contains("Q = 500", view.TxtSummaryInfo.Text);
            Assert.Contains("BW = 2 kHz", view.TxtSummaryInfo.Text);
        });
    }

    [Fact]
    public void PlotOverlay_ShowResonance_RendersAndSetsTitle()
    {
        RunOnSta(() =>
        {
            var overlay = new PlotOverlay();
            var dto = new ResonanceDto
            {
                Kind = "series",
                F0 = 1000.0,
                Q = 10.0,
                Bw = 100.0,
                I0 = 1.0,
                Curve = new ResonanceCurveDto
                {
                    F = new List<double> { 900, 1000, 1100 },
                    Y = new List<double> { 0.5, 1.0, 0.5 }
                }
            };

            overlay.Show(dto, animate: false);
            Assert.True(overlay.IsOpen);
            Assert.Equal("Rezonans Eğrisi", overlay.TxtOverlayTitle.Text);

            overlay.Close(animate: false);
            Assert.False(overlay.IsOpen);
        });
    }
}
