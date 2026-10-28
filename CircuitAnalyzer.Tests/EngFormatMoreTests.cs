using System.Text.Json;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.Tests;

public class EngFormatMoreTests
{
    [Theory]
    [InlineData(3, -4, "5∠-53,13° V")]
    [InlineData(-3, -4, "5∠-126,9° V")]
    [InlineData(-3, 4, "5∠126,9° V")]
    [InlineData(-10, 0, "10∠180° V")]
    [InlineData(0, -0.05, "50∠-90° mV")]
    public void EngFormat_NegativeComplex_FormatsPolarWithPrefix(double re, double im, string expected)
    {
        var v = ResultValue.FromComplex(new ComplexNumberDto { Real = re, Imaginary = im });
        Assert.Equal(expected, EngFormat.Format(v, "V"));
    }

    [Theory]
    [InlineData(1e9, "Hz", "1 GHz")]
    [InlineData(2.4e9, "Hz", "2,4 GHz")]
    [InlineData(100e9, "Ω", "100 GΩ")]
    [InlineData(-5e9, "W", "-5 GW")]
    public void EngFormat_GigaRange_FormatsCorrectly(double value, string unit, string expected)
    {
        Assert.Equal(expected, EngFormat.Format(value, unit));
    }

    [Fact]
    public void EngFormat_GigaRange_Complex_FormatsWithGigaPrefix()
    {
        var v = ResultValue.FromComplex(new ComplexNumberDto { Real = 3e9, Imaginary = 4e9 });
        Assert.Equal("5∠53,13° GV", EngFormat.Format(v, "V"));
    }

    [Theory]
    [InlineData(1e-12, "F", "1 pF")]
    [InlineData(22e-12, "F", "22 pF")]
    [InlineData(0.5e-12, "F", "0,5 pF")]
    [InlineData(-4.7e-12, "A", "-4,7 pA")]
    public void EngFormat_PicoRange_FormatsCorrectly(double value, string unit, string expected)
    {
        Assert.Equal(expected, EngFormat.Format(value, unit));
    }

    [Fact]
    public void EngFormat_PicoRange_Complex_FormatsWithPicoPrefix()
    {
        var v = ResultValue.FromComplex(new ComplexNumberDto { Real = 3e-12, Imaginary = 4e-12 });
        Assert.Equal("5∠53,13° pA", EngFormat.Format(v, "A"));
    }

    [Theory]
    [InlineData(double.NaN, "V", "— V")]
    [InlineData(double.PositiveInfinity, "A", "— A")]
    [InlineData(double.NegativeInfinity, "Ω", "— Ω")]
    public void EngFormat_NaNAndInfinity_ReturnsDashWithUnit(double value, string unit, string expected)
    {
        Assert.Equal(expected, EngFormat.Format(value, unit));
    }

    [Fact]
    public void EngFormat_ResultValue_NaNAndInfinity_ReturnsDashWithUnit()
    {
        var vNan = ResultValue.FromReal(double.NaN);
        Assert.Equal("— V", EngFormat.Format(vNan, "V"));

        var vInf = ResultValue.FromReal(double.PositiveInfinity);
        Assert.Equal("— A", EngFormat.Format(vInf, "A"));
    }

    [Fact]
    public void EngFormat_Zero_RealAndComplex()
    {
        Assert.Equal("0 V", EngFormat.Format(0.0, "V"));
        Assert.Equal("0 V", EngFormat.Format(ResultValue.FromReal(0.0), "V"));

        var cZero = ResultValue.FromComplex(new ComplexNumberDto { Real = 0, Imaginary = 0 });
        Assert.Equal("0 V", EngFormat.Format(cZero, "V"));
    }

    [Fact]
    public void ResultValue_JsonRoundTrip_RealValue()
    {
        var original = ResultValue.FromReal(42.5);
        string json = JsonSerializer.Serialize(original);
        var restored = JsonSerializer.Deserialize<ResultValue>(json);

        Assert.NotNull(restored);
        Assert.False(restored!.IsComplex);
        Assert.Equal(42.5, restored.Real);
        Assert.Equal(0, restored.Imaginary);
        Assert.Equal(42.5, restored.Magnitude);
    }

    [Fact]
    public void ResultValue_JsonRoundTrip_NegativeRealValue()
    {
        var original = ResultValue.FromReal(-0.048);
        string json = JsonSerializer.Serialize(original);
        var restored = JsonSerializer.Deserialize<ResultValue>(json);

        Assert.NotNull(restored);
        Assert.False(restored!.IsComplex);
        Assert.Equal(-0.048, restored.Real);
    }

    [Fact]
    public void ResultValue_JsonRoundTrip_ComplexValue()
    {
        var original = ResultValue.FromComplex(new ComplexNumberDto
        {
            Real = 3.5,
            Imaginary = -4.5,
            RectangularStr = "3.5-j4.5",
            PolarStr = "5.7∠-52.1°"
        });

        string json = JsonSerializer.Serialize(original);
        var restored = JsonSerializer.Deserialize<ResultValue>(json);

        Assert.NotNull(restored);
        Assert.True(restored!.IsComplex);
        Assert.Equal(3.5, restored.Real, 6);
        Assert.Equal(-4.5, restored.Imaginary, 6);
        Assert.Equal(original.Magnitude, restored.Magnitude, 4);
        Assert.Equal(original.PhaseDegrees, restored.PhaseDegrees, 2);
    }

    [Fact]
    public void NodeVoltageDto_JsonRoundTrip_ContainingComplexResultValue()
    {
        var dto = new NodeVoltageDto
        {
            Value = ResultValue.FromComplex(new ComplexNumberDto { Real = 1.25, Imaginary = -3.75 }),
            Unit = "V",
            Label = "Out"
        };

        string json = JsonSerializer.Serialize(dto);
        var restored = JsonSerializer.Deserialize<NodeVoltageDto>(json);

        Assert.NotNull(restored);
        Assert.Equal("V", restored!.Unit);
        Assert.Equal("Out", restored.Label);
        Assert.True(restored.Value.IsComplex);
        Assert.Equal(1.25, restored.Value.Real, 6);
        Assert.Equal(-3.75, restored.Value.Imaginary, 6);
    }
}
