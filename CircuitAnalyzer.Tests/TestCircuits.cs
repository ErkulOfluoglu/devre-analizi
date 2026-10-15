using System.Windows;
using CircuitAnalyzer.WPF.Models;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Testler için programatik devre kurucu. Elemanlar birbirinden uzağa
/// yerleştirilir; bağlantılar yalnızca tellerle yapılır (pin çakışması yok).
/// </summary>
internal sealed class TestCircuits
{
    public List<CircuitElement> Elements { get; } = new();
    public List<Wire> Wires { get; } = new();

    private double _nextY = 0;

    public T Add<T>(T element, string id) where T : CircuitElement
    {
        element.Id = id;
        element.Position = new Point(1000, _nextY);
        _nextY += 200;
        Elements.Add(element);
        return element;
    }

    public void Wire(Pin a, Pin b) => Wires.Add(new Wire(a, b));

    /// <summary>V1=12V DC, R1=1k (1→2), R2=2k (2→0), GND, V probu düğüm 2'de.</summary>
    public static TestCircuits DcDivider(bool withProbe = true)
    {
        var c = new TestCircuits();
        var v1 = c.Add(new VoltageSource { Value = 12 }, "V1");
        var r1 = c.Add(new Resistor { Value = 1000 }, "R1");
        var r2 = c.Add(new Resistor { Value = 2000 }, "R2");
        var gnd = c.Add(new GroundElement(), "GND1");
        c.Wire(v1.Pins[0], r1.Pins[0]);
        c.Wire(r1.Pins[1], r2.Pins[0]);
        c.Wire(r2.Pins[1], gnd.Pins[0]);
        c.Wire(v1.Pins[1], gnd.Pins[0]);
        if (withProbe)
        {
            var probe = c.Add(new TestProbe { Type = ProbeType.Voltage }, "VP1");
            c.Wire(probe.Pins[0], r2.Pins[0]);
        }
        return c;
    }

    /// <summary>VAC1 = 10∠0° (fazör), R1=100Ω, C1=100µF, GND.</summary>
    public static TestCircuits AcRcLowPass()
    {
        var c = new TestCircuits();
        var vac = c.Add(new AcVoltageSource
        {
            Amplitude = 10, Phase = 0, Frequency = 50, InputMode = AcInputMode.Phasor,
        }, "VAC1");
        var r1 = c.Add(new Resistor { Value = 100 }, "R1");
        var c1 = c.Add(new Capacitor { Value = 100e-6 }, "C1");
        var gnd = c.Add(new GroundElement(), "GND1");
        c.Wire(vac.Pins[0], r1.Pins[0]);
        c.Wire(r1.Pins[1], c1.Pins[0]);
        c.Wire(c1.Pins[1], gnd.Pins[0]);
        c.Wire(vac.Pins[1], gnd.Pins[0]);
        return c;
    }
}
