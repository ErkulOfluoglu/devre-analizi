using System.Globalization;
using CircuitAnalyzer.WPF.Models;

namespace CircuitAnalyzer.Tests;

public class NetlistFormatTests
{
    private static Dictionary<Pin, int> NodeMap(CircuitElement el, int n1 = 1, int n2 = 2)
    {
        var map = new Dictionary<Pin, int>();
        if (el.Pins.Count > 0) map[el.Pins[0]] = n1;
        if (el.Pins.Count > 1) map[el.Pins[1]] = n2;
        return map;
    }

    [Theory]
    [InlineData(4700, "R1 1 2 4700")]
    [InlineData(1e6, "R1 1 2 1000000")]
    [InlineData(0, "R1 1 2 0")]
    [InlineData(220.5, "R1 1 2 220.5")]
    public void Resistor_FormatsNetlistEntry(double value, string expected)
    {
        var r = new Resistor { Id = "R1", Value = value };
        var line = r.ToNetlistEntry(NodeMap(r));
        Assert.Equal(expected, line);
    }

    [Theory]
    [InlineData(100e-6, "C1 1 2 100u")]
    [InlineData(4.7e-9, "C1 1 2 4.7n")]
    [InlineData(1e-3, "C1 1 2 1m")]
    [InlineData(22e-12, "C1 1 2 22p")]
    [InlineData(2.2, "C1 1 2 2.2")]
    [InlineData(12000e-6, "C1 1 2 12m")]
    public void Capacitor_FormatsSpiceUnits(double value, string expected)
    {
        var c = new Capacitor { Id = "C1", Value = value };
        var line = c.ToNetlistEntry(NodeMap(c));
        Assert.Equal(expected, line);
    }

    [Theory]
    [InlineData(0.1, "L1 1 2 100m")]
    [InlineData(1.5, "L1 1 2 1.5")]
    [InlineData(2.2e-6, "L1 1 2 2.2u")]
    [InlineData(4.7e-9, "L1 1 2 4.7n")]
    [InlineData(1e-3, "L1 1 2 1m")]
    public void Inductor_FormatsSpiceUnits(double value, string expected)
    {
        var l = new Inductor { Id = "L1", Value = value };
        var line = l.ToNetlistEntry(NodeMap(l));
        Assert.Equal(expected, line);
    }

    [Fact]
    public void ImpedanceElement_RectangularMode_ProducesComplexEntry()
    {
        var zPos = new ImpedanceElement
        {
            Id = "Z1",
            InputMode = ImpedanceInputMode.Rectangular,
            Impedance = ComplexValue.FromRectangular(50, 30)
        };
        Assert.Equal("Z1 1 2 COMPLEX(50, 30)", zPos.ToNetlistEntry(NodeMap(zPos)));

        var zNeg = new ImpedanceElement
        {
            Id = "Z2",
            InputMode = ImpedanceInputMode.Rectangular,
            Impedance = ComplexValue.FromRectangular(50, -30)
        };
        Assert.Equal("Z2 1 2 COMPLEX(50, -30)", zNeg.ToNetlistEntry(NodeMap(zNeg)));
    }

    [Fact]
    public void ImpedanceElement_PolarMode_ProducesPolarEntry()
    {
        var z = new ImpedanceElement
        {
            Id = "Z1",
            InputMode = ImpedanceInputMode.Polar,
            Impedance = ComplexValue.FromPolar(58.31, 30.96)
        };
        Assert.Equal("Z1 1 2 POLAR(58.31, 30.96)", z.ToNetlistEntry(NodeMap(z)));
    }

    [Theory]
    [InlineData(12, "V1 1 2 DC 12")]
    [InlineData(-5, "V1 1 2 DC -5")]
    [InlineData(0, "V1 1 2 DC 0")]
    public void VoltageSource_FormatsNetlistEntry(double value, string expected)
    {
        var v = new VoltageSource { Id = "V1", Value = value };
        var line = v.ToNetlistEntry(NodeMap(v));
        Assert.Equal(expected, line);
    }

    [Fact]
    public void AcVoltageSource_PhysicalMode_ProducesSineEntry()
    {
        var vac = new AcVoltageSource
        {
            Id = "VAC1",
            InputMode = AcInputMode.Physical,
            Amplitude = 10,
            Frequency = 50,
            Phase = 30
        };
        Assert.Equal("VAC1 1 2 SINE(0 10 50 0 0 30)", vac.ToNetlistEntry(NodeMap(vac)));
    }

    [Fact]
    public void AcVoltageSource_PhasorMode_ProducesAcPhasorEntry()
    {
        var vac = new AcVoltageSource
        {
            Id = "VAC1",
            InputMode = AcInputMode.Phasor,
            Amplitude = 12,
            Phase = 45
        };
        Assert.Equal("VAC1 1 2 AC_PHASOR(12, 45)", vac.ToNetlistEntry(NodeMap(vac)));
    }

    [Fact]
    public void TestProbe_Voltage_Connected_ProducesProbeDirective()
    {
        var probe = new TestProbe { Id = "VP1", Type = ProbeType.Voltage };
        var map = new Dictionary<Pin, int> { [probe.Pins[0]] = 2 };
        Assert.Equal("* PROBE VP1 V(2)", probe.ToNetlistEntry(map));
    }

    [Fact]
    public void TestProbe_Current_WithTarget_ProducesTargetDirective()
    {
        var probe = new TestProbe
        {
            Id = "IP1",
            Type = ProbeType.Current,
            TargetElementId = "R1"
        };
        var map = new Dictionary<Pin, int>();
        Assert.Equal("* PROBE IP1 I(R1)", probe.ToNetlistEntry(map));
    }

    [Fact]
    public void TestProbe_Current_WithoutTarget_ProducesQuestionMarkDirective()
    {
        var probe = new TestProbe
        {
            Id = "IP1",
            Type = ProbeType.Current,
            TargetElementId = ""
        };
        var map = new Dictionary<Pin, int>();
        Assert.Equal("* PROBE IP1 I(?)", probe.ToNetlistEntry(map));
    }

    [Fact]
    public void GroundElement_ProducesCommentLine()
    {
        var gnd = new GroundElement { Id = "GND1" };
        var map = new Dictionary<Pin, int> { [gnd.Pins[0]] = 0 };
        Assert.Equal("* GND1 — Referans toprak (Node 0)", gnd.ToNetlistEntry(map));
    }

    [Fact]
    public void InvariantCulture_PreservesDotDecimalUnderTurkishCulture()
    {
        var prevCulture = Thread.CurrentThread.CurrentCulture;
        try
        {
            Thread.CurrentThread.CurrentCulture = new CultureInfo("tr-TR");

            var r = new Resistor { Id = "R1", Value = 4700 };
            Assert.Equal("R1 1 2 4700", r.ToNetlistEntry(NodeMap(r)));

            var c = new Capacitor { Id = "C1", Value = 4.7e-9 };
            Assert.Equal("C1 1 2 4.7n", c.ToNetlistEntry(NodeMap(c)));

            var c2 = new Capacitor { Id = "C2", Value = 2.2 };
            Assert.Equal("C2 1 2 2.2", c2.ToNetlistEntry(NodeMap(c2)));

            var l = new Inductor { Id = "L1", Value = 2.2e-6 };
            Assert.Equal("L1 1 2 2.2u", l.ToNetlistEntry(NodeMap(l)));

            var v = new VoltageSource { Id = "V1", Value = 3.3 };
            Assert.Equal("V1 1 2 DC 3.3", v.ToNetlistEntry(NodeMap(v)));

            var vac = new AcVoltageSource
            {
                Id = "VAC1",
                InputMode = AcInputMode.Physical,
                Amplitude = 10.5,
                Frequency = 50.25,
                Phase = 30.5
            };
            Assert.Equal("VAC1 1 2 SINE(0 10.5 50.25 0 0 30.5)", vac.ToNetlistEntry(NodeMap(vac)));

            var z = new ImpedanceElement
            {
                Id = "Z1",
                InputMode = ImpedanceInputMode.Rectangular,
                Impedance = ComplexValue.FromRectangular(50.5, -30.5)
            };
            Assert.Equal("Z1 1 2 COMPLEX(50.5, -30.5)", z.ToNetlistEntry(NodeMap(z)));
        }
        finally
        {
            Thread.CurrentThread.CurrentCulture = prevCulture;
        }
    }
}
