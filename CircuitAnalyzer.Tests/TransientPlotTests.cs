using System;
using System.Collections.Generic;
using System.Text.Json;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

public class TransientPlotTests
{
    [Fact]
    public void TransientCurveCalculator_EvaluatesPointsAccurately()
    {
        double before = 0.0;
        double start = 0.0;
        double finalVal = 12.0;
        double tau = 0.002;

        // t < 0
        Assert.Equal(before, TransientCurveCalculator.Evaluate(before, start, finalVal, tau, -0.001));

        // t = 0
        Assert.Equal(start, TransientCurveCalculator.Evaluate(before, start, finalVal, tau, 0.0));

        // t = tau: 63.2% of the total change from start towards final
        double expectedAtTau = finalVal + (start - finalVal) * Math.Exp(-1.0);
        double actualAtTau = TransientCurveCalculator.Evaluate(before, start, finalVal, tau, tau);
        Assert.Equal(expectedAtTau, actualAtTau, 6);

        double totalChange = finalVal - start;
        double actualChange = actualAtTau - start;
        double changePercent = actualChange / totalChange;
        Assert.InRange(changePercent, 0.632, 0.633); // 63.2%

        // t = 5*tau
        double expectedAt5Tau = finalVal + (start - finalVal) * Math.Exp(-5.0);
        double actualAt5Tau = TransientCurveCalculator.Evaluate(before, start, finalVal, tau, 5 * tau);
        Assert.Equal(expectedAt5Tau, actualAt5Tau, 6);
    }

    [Fact]
    public void TransientDto_DeserializesCorrectly()
    {
        const string json = """
        {
          "element": "C1",
          "kind": "C",
          "tau": 0.002,
          "r_th": 2000.0,
          "quantities": [
            { "id": "V_C1", "label": "V_C1", "unit": "V", "before": 0.0, "start": 0.0, "final": 12.0 },
            { "id": "I_C1", "label": "I_C1", "unit": "A", "before": 0.0, "start": 0.006, "final": 0.0 }
          ]
        }
        """;

        var dto = JsonSerializer.Deserialize<TransientAnalysisDto>(json);
        Assert.NotNull(dto);
        Assert.Equal("C1", dto!.Element);
        Assert.Equal("C", dto.Kind);
        Assert.Equal(0.002, dto.Tau);
        Assert.Equal(2000.0, dto.Rth);
        Assert.Equal(2, dto.Quantities.Count);
        Assert.Equal("V_C1", dto.Quantities[0].Id);
        Assert.Equal(12.0, dto.Quantities[0].Final);
        Assert.Equal("I_C1", dto.Quantities[1].Id);
        Assert.Equal(0.006, dto.Quantities[1].Start);
    }

    [Fact]
    public void ScottPlot_ApisWorkAsExpected()
    {
        var plot = new ScottPlot.Plot();
        var scatter = plot.Add.Scatter(new double[] { 0, 1, 2 }, new double[] { 0, 5, 10 });
        scatter.LineWidth = 2;
        scatter.MarkerSize = 0;

        var vline = plot.Add.VerticalLine(1);
        vline.LinePattern = ScottPlot.LinePattern.Dashed;
        vline.Text = "τ";

        var hline = plot.Add.HorizontalLine(10);
        hline.LinePattern = ScottPlot.LinePattern.Dashed;

        var ch = plot.Add.Crosshair(1, 5);
        ch.IsVisible = true;

        plot.Axes.SetLimits(-1, 5, -2, 12);
        plot.XLabel("Zaman (s)");
        plot.YLabel("Gerilim (V)");
        plot.Title("V_C1");

        plot.RenderInMemory(400, 300);
        var pixel = new ScottPlot.Pixel(100, 100);
        var coords = plot.GetCoordinates(pixel);
        Assert.True(double.IsFinite(coords.X));
    }
}
