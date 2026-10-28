using System.Text.Json;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.Tests;

public class ApiModelsTests
{
    [Fact]
    public void ResultValue_ReadsPlainNumber()
    {
        var nv = JsonSerializer.Deserialize<NodeVoltageDto>("""{"value": 8.0, "unit": "V"}""")!;
        Assert.False(nv.Value.IsComplex);
        Assert.Equal(8.0, nv.Value.Real);
    }

    [Fact]
    public void ResultValue_ReadsComplexObject()
    {
        const string json = """
            {"value": {"real": 0.92, "imaginary": -2.89, "magnitude": 3.033,
                       "phase_degrees": -72.34, "rectangular_str": "0.92−j2.89",
                       "polar_str": "3.033∠-72.34°"}, "unit": "V"}
            """;
        var nv = JsonSerializer.Deserialize<NodeVoltageDto>(json)!;
        Assert.True(nv.Value.IsComplex);
        Assert.Equal(-2.89, nv.Value.Imaginary);
        Assert.Equal("3.033∠-72.34°", nv.Value.PolarStr);
        Assert.InRange(nv.Value.PhaseDegrees, -72.4, -72.2);
    }

    [Fact]
    public void ResultValue_RejectsUnexpectedToken()
    {
        Assert.Throws<JsonException>(() =>
            JsonSerializer.Deserialize<NodeVoltageDto>("""{"value": "abc"}"""));
    }

    [Theory]
    [InlineData(0.004, "A", "4 mA")]
    [InlineData(8.0, "V", "8 V")]
    [InlineData(2000.0 / 3, "Ω", "666,7 Ω")]
    [InlineData(4700.0, "Ω", "4,7 kΩ")]
    [InlineData(1e-6, "F", "1 µF")]
    [InlineData(-0.048, "W", "-48 mW")]
    [InlineData(0.0, "V", "0 V")]
    [InlineData(0.99996, "A", "1 A")]
    public void EngFormat_Real(double value, string unit, string expected)
    {
        Assert.Equal(expected, EngFormat.Format(value, unit));
    }

    [Fact]
    public void EngFormat_ComplexUsesPolarWithPrefixAtEnd()
    {
        var v = ResultValue.FromComplex(new ComplexNumberDto { Real = 0.0316292, Imaginary = 0.0044364 });
        Assert.Equal("31,94∠7,984° mA", EngFormat.Format(v, "A"));
    }

    [Fact]
    public void ExtractErrorDetail_HandlesFastApiShapes()
    {
        Assert.Equal("Netlist hatası",
            AnalysisApiClient.ExtractErrorDetail("""{"detail": "Netlist hatası"}""", 400));
        string msg422 = AnalysisApiClient.ExtractErrorDetail(
            """{"detail": [{"loc": ["body", "mode"], "msg": "Input should be 'DC'"}]}""", 422);
        Assert.Contains("Input should be 'DC'", msg422);
        Assert.Contains("HTTP 500", AnalysisApiClient.ExtractErrorDetail("Internal Server Error", 500));
    }
}
