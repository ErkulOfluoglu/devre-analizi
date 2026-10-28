using System;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

public class CurrentDisplayTests
{
    [Fact]
    public void Format_DcPassiveNegative_ReversesDirectionAndValuePositive()
    {
        var current = new ElementCurrentDto
        {
            Value = ResultValue.FromReal(-0.004),
            Unit = "A",
            Direction = "1→2"
        };

        var (value, direction) = CurrentDisplay.Format("R1", current);

        Assert.Equal("4 mA", value);
        Assert.Equal("2→1", direction);
    }

    [Fact]
    public void Format_DcPositive_Unchanged()
    {
        var current = new ElementCurrentDto
        {
            Value = ResultValue.FromReal(0.004),
            Unit = "A",
            Direction = "1→2"
        };

        var (value, direction) = CurrentDisplay.Format("R1", current);

        Assert.Equal("4 mA", value);
        Assert.Equal("1→2", direction);
    }

    [Fact]
    public void Format_DcSourceNegative_ReversesDirectionAndValuePositive()
    {
        var current = new ElementCurrentDto
        {
            Value = ResultValue.FromReal(-0.006),
            Unit = "A",
            Direction = "1→0"
        };

        var (value, direction) = CurrentDisplay.Format("V1", current);

        Assert.Equal("6 mA", value);
        Assert.Equal("0→1", direction);
    }

    [Fact]
    public void Format_DcZero_NotReversed()
    {
        var currentPassive = new ElementCurrentDto
        {
            Value = ResultValue.FromReal(0.0),
            Unit = "A",
            Direction = "1→2"
        };
        var (valPassive, dirPassive) = CurrentDisplay.Format("R1", currentPassive);
        Assert.Equal("0 A", valPassive);
        Assert.Equal("1→2", dirPassive);

        var currentSource = new ElementCurrentDto
        {
            Value = ResultValue.FromReal(0.0),
            Unit = "A",
            Direction = "1→0"
        };
        var (valSource, dirSource) = CurrentDisplay.Format("V1", currentSource);
        Assert.Equal("0 A", valSource);
        Assert.Equal("1→0", dirSource);
    }

    [Fact]
    public void Format_AcSource_ReversesDirectionAndNegatesPhasor()
    {
        var originalValue = new ResultValue
        {
            Real = -0.3163,
            Imaginary = -0.04436,
            IsComplex = true
        };
        var current = new ElementCurrentDto
        {
            Value = originalValue,
            Unit = "A",
            Direction = "1→0"
        };

        var (value, direction) = CurrentDisplay.Format("VAC1", current);

        Assert.Equal("0→1", direction);

        var negatedPhasor = new ResultValue
        {
            Real = -originalValue.Real,
            Imaginary = -originalValue.Imaginary,
            IsComplex = true
        };
        string expectedEngFormat = EngFormat.Format(negatedPhasor, "A");

        Assert.Equal(expectedEngFormat, value);
        Assert.Contains("319,4", value);
        Assert.Contains("mA", value);
    }

    [Fact]
    public void Format_AcPassive_KeepsDirectionAndPhasor()
    {
        var complexValue = new ResultValue
        {
            Real = -0.3163,
            Imaginary = -0.04436,
            IsComplex = true
        };
        var current = new ElementCurrentDto
        {
            Value = complexValue,
            Unit = "A",
            Direction = "1→2"
        };

        var (value, direction) = CurrentDisplay.Format("R1", current);

        Assert.Equal("1→2", direction);
        Assert.Equal(EngFormat.Format(complexValue, "A"), value);
    }

    [Theory]
    [InlineData("?")]
    [InlineData("")]
    [InlineData("no-arrow")]
    public void Format_MalformedDirection_NeverThrowsAndNotReversed(string malformedDirection)
    {
        var currentPassive = new ElementCurrentDto
        {
            Value = ResultValue.FromReal(-0.004),
            Unit = "A",
            Direction = malformedDirection
        };
        var (valP, dirP) = CurrentDisplay.Format("R1", currentPassive);
        Assert.Equal(malformedDirection, dirP);
        Assert.Equal("-4 mA", valP);

        var currentSource = new ElementCurrentDto
        {
            Value = ResultValue.FromReal(-0.006),
            Unit = "A",
            Direction = malformedDirection
        };
        var (valS, dirS) = CurrentDisplay.Format("V1", currentSource);
        Assert.Equal(malformedDirection, dirS);
        Assert.Equal("-6 mA", valS);

        var currentAcSource = new ElementCurrentDto
        {
            Value = new ResultValue { Real = -0.3163, Imaginary = -0.04436, IsComplex = true },
            Unit = "A",
            Direction = malformedDirection
        };
        var (valAc, dirAc) = CurrentDisplay.Format("VAC1", currentAcSource);
        Assert.Equal(malformedDirection, dirAc);
    }
}
