using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Runtime.ExceptionServices;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

[Collection(WpfUiCollection.Name)]
public class CurrentSourceTests : IClassFixture<BackendFixture>
{
    private readonly BackendFixture _fx;

    public CurrentSourceTests(BackendFixture fx) => _fx = fx;

    private static Dictionary<Pin, int> NodeMap(CircuitElement el, int n1 = 1, int n2 = 2)
    {
        var map = new Dictionary<Pin, int>();
        if (el.Pins.Count > 0) map[el.Pins[0]] = n1;
        if (el.Pins.Count > 1) map[el.Pins[1]] = n2;
        return map;
    }

    private static void RunOnSta(Action action)
    {
        Exception? error = null;
        var thread = new Thread(() =>
        {
            try
            {
                action();
            }
            catch (Exception ex)
            {
                error = ex;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        if (error != null)
            ExceptionDispatchInfo.Capture(error).Throw();
    }

    [Fact]
    public void CurrentSource_ToNetlistEntry_DcFormat()
    {
        var cs = new CurrentSource { Id = "I1", Value = 0.002 };
        string entry = cs.ToNetlistEntry(NodeMap(cs, 1, 2));
        Assert.Equal("I1 1 2 DC 0.002", entry);
    }

    [Fact]
    public void AcCurrentSource_ToNetlistEntry_PhysicalFormat()
    {
        var ac = new AcCurrentSource
        {
            Id = "IAC1",
            InputMode = AcInputMode.Physical,
            Amplitude = 0.01,
            Frequency = 50,
            Phase = 30
        };
        string entry = ac.ToNetlistEntry(NodeMap(ac, 1, 2));
        Assert.Equal("IAC1 1 2 SINE(0 0.01 50 0 0 30)", entry);
    }

    [Fact]
    public void AcCurrentSource_ToNetlistEntry_PhasorFormat()
    {
        var ac = new AcCurrentSource
        {
            Id = "IAC1",
            InputMode = AcInputMode.Phasor,
            Amplitude = 0.015,
            Phase = 45
        };
        string entry = ac.ToNetlistEntry(NodeMap(ac, 1, 2));
        Assert.Equal("IAC1 1 2 AC_PHASOR(0.015, 45)", entry);
    }

    [Fact]
    public void ToNetlistEntry_UnderTurkishCulture_PreservesDotDecimal()
    {
        var prevCulture = Thread.CurrentThread.CurrentCulture;
        try
        {
            Thread.CurrentThread.CurrentCulture = new CultureInfo("tr-TR");

            var cs = new CurrentSource { Id = "I1", Value = 0.002 };
            Assert.Equal("I1 1 2 DC 0.002", cs.ToNetlistEntry(NodeMap(cs, 1, 2)));

            var acPhys = new AcCurrentSource
            {
                Id = "IAC1",
                InputMode = AcInputMode.Physical,
                Amplitude = 0.0125,
                Frequency = 50.5,
                Phase = 30.25
            };
            Assert.Equal("IAC1 1 2 SINE(0 0.0125 50.5 0 0 30.25)", acPhys.ToNetlistEntry(NodeMap(acPhys, 1, 2)));

            var acPhasor = new AcCurrentSource
            {
                Id = "IAC2",
                InputMode = AcInputMode.Phasor,
                Amplitude = 0.025,
                Phase = 45.75
            };
            Assert.Equal("IAC2 1 2 AC_PHASOR(0.025, 45.75)", acPhasor.ToNetlistEntry(NodeMap(acPhasor, 1, 2)));
        }
        finally
        {
            Thread.CurrentThread.CurrentCulture = prevCulture;
        }
    }

    [Fact]
    public void Rotation_Rotated90Degrees_HasPins40PxAboveAndBelowCenter()
    {
        var cs = new CurrentSource
        {
            Position = new Point(100, 100),
            Rotation = 90
        };

        // Merkez: (100 + 40, 100 + 20) = (140, 120)
        // 90° dönüşte Pins[0] (0, 20) merkeze göre (-40, 0) iken (0, -40) olur -> Y = 120 - 40 = 80
        // Pins[1] (80, 20) merkeze göre (+40, 0) iken (0, +40) olur -> Y = 120 + 40 = 160
        Point p0 = cs.Pins[0].AbsolutePosition;
        Point p1 = cs.Pins[1].AbsolutePosition;

        Assert.Equal(140.0, p0.X, 4);
        Assert.Equal(80.0, p0.Y, 4);

        Assert.Equal(140.0, p1.X, 4);
        Assert.Equal(160.0, p1.Y, 4);
    }

    [Fact]
    public void NetlistBuilder_Flags_WithAcCurrentSource()
    {
        var gnd = new GroundElement();

        // 1. Fiziksel mod: HasAcSource = true, HasPhasorSource = false
        var physAc = new AcCurrentSource { InputMode = AcInputMode.Physical };
        var resPhys = NetlistBuilder.Build(new CircuitElement[] { physAc, gnd }, Array.Empty<Wire>());
        Assert.True(resPhys.HasAcSource);
        Assert.False(resPhys.HasPhasorSource);

        // 2. Fazör mod: HasAcSource = true, HasPhasorSource = true
        var phasorAc = new AcCurrentSource { InputMode = AcInputMode.Phasor };
        var resPhasor = NetlistBuilder.Build(new CircuitElement[] { phasorAc, gnd }, Array.Empty<Wire>());
        Assert.True(resPhasor.HasAcSource);
        Assert.True(resPhasor.HasPhasorSource);

        // 3. DC kaynak: her iki bayrak da false
        var dc = new CurrentSource();
        var resDc = NetlistBuilder.Build(new CircuitElement[] { dc, gnd }, Array.Empty<Wire>());
        Assert.False(resDc.HasAcSource);
        Assert.False(resDc.HasPhasorSource);
    }

    private static string BuildTinyGroundedNetlist(CircuitElement element)
    {
        var gnd = new GroundElement { Id = "GND1", Position = new Point(0, 200) };
        element.Position = new Point(0, 0);
        var wire = new Wire(element.Pins[1], gnd.Pins[0]);
        var result = NetlistBuilder.Build(new List<CircuitElement> { element, gnd }, new List<Wire> { wire });
        return result.Text;
    }

    private async Task AssertParseOnlyAsync(
        CircuitElement element,
        string expectedId,
        string expectedType,
        double expectedValue,
        bool isAc = false,
        double? frequency = null)
    {
        string netlist = BuildTinyGroundedNetlist(element);

        var payload = new
        {
            netlist,
            mode = isAc ? AnalysisModes.AcPhasor : AnalysisModes.Dc,
            frequency = isAc ? (frequency ?? 50.0) : (double?)null
        };

        using var http = new HttpClient();
        var jsonContent = new StringContent(
            JsonSerializer.Serialize(payload),
            Encoding.UTF8,
            "application/json");

        var response = await http.PostAsync(
            new Uri(_fx.Client.BaseAddress, "/parse-only"),
            jsonContent);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        string body = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(body);
        var root = doc.RootElement;

        var warnings = root.GetProperty("warnings").EnumerateArray().ToList();
        Assert.Empty(warnings);

        var elements = root.GetProperty("elements").EnumerateArray().ToList();
        var parsedElem = Assert.Single(elements);

        Assert.Equal(expectedId, parsedElem.GetProperty("id").GetString());
        Assert.Equal(expectedType, parsedElem.GetProperty("type").GetString());

        double parsedVal = parsedElem.GetProperty("value").GetDouble();
        double relDiff = Math.Abs(parsedVal - expectedValue) / Math.Abs(expectedValue);
        Assert.True(relDiff <= 0.001,
            $"Eleman {expectedId} için beklenen: {expectedValue}, ayrıştırılan: {parsedVal}, bağıl fark: {relDiff:P3}");
    }

    [Fact]
    public Task ParseOnly_DcCurrentSource() =>
        AssertParseOnlyAsync(new CurrentSource { Id = "I1", Value = 0.002 }, "I1", "I_DC", 0.002);

    [Fact]
    public Task ParseOnly_AcCurrentSource_Sine()
    {
        var ac = new AcCurrentSource
        {
            Id = "IAC1",
            InputMode = AcInputMode.Physical,
            Amplitude = 0.01,
            Frequency = 50,
            Phase = 30
        };
        return AssertParseOnlyAsync(ac, "IAC1", "I_AC_SINE", 0.01, isAc: true, frequency: 50);
    }

    [Fact]
    public Task ParseOnly_AcCurrentSource_Phasor()
    {
        var ac = new AcCurrentSource
        {
            Id = "IAC1",
            InputMode = AcInputMode.Phasor,
            Amplitude = 0.015,
            Phase = 45
        };
        return AssertParseOnlyAsync(ac, "IAC1", "I_AC_PHASOR", 0.015, isAc: true, frequency: 50);
    }

    [Fact]
    public async Task EndToEnd_DcCurrentSource_DividerWithCurrentInjection()
    {
        // V1 = 10 V DC, R1 = 1k (V1+ → node a), R2 = 1k (node a → GND),
        // CurrentSource 2 mA with Pins[0] on GND and Pins[1] on node a (injects into node a)
        // → AnalyzeAsync DC → V(node a) = 6 V, I(I1) = +2 mA with direction "0→<a>",
        // CurrentDisplay shows "2 mA" and that direction
        var c = new TestCircuits();
        var v1 = c.Add(new VoltageSource { Value = 10 }, "V1");
        var r1 = c.Add(new Resistor { Value = 1000 }, "R1");
        var r2 = c.Add(new Resistor { Value = 1000 }, "R2");
        var i1 = c.Add(new CurrentSource { Value = 0.002 }, "I1");
        var gnd = c.Add(new GroundElement(), "GND1");

        // V1(+) -> R1 pin 0
        c.Wire(v1.Pins[0], r1.Pins[0]);
        // Node a: R1 pin 1, R2 pin 0, I1 pin 1
        c.Wire(r1.Pins[1], r2.Pins[0]);
        c.Wire(r2.Pins[0], i1.Pins[1]);
        // GND: V1(-), R2 pin 1, I1 pin 0, GND
        c.Wire(v1.Pins[1], gnd.Pins[0]);
        c.Wire(r2.Pins[1], gnd.Pins[0]);
        c.Wire(i1.Pins[0], gnd.Pins[0]);

        var netlistResult = NetlistBuilder.Build(c.Elements, c.Wires);
        int nodeA = netlistResult.NodeMap[r1.Pins[1]];
        int nodeGnd = netlistResult.NodeMap[gnd.Pins[0]];
        Assert.Equal(0, nodeGnd);

        var request = new AnalysisRequestDto
        {
            Netlist = netlistResult.Text,
            Mode = AnalysisModes.Dc,
            AnalysisType = AnalysisTypes.Nodal
        };

        var resp = await _fx.Client.AnalyzeAsync(request);
        Assert.Equal("success", resp.Status);

        // V(node a) = 6 V
        Assert.Equal(6.0, resp.Results.NodeVoltages[nodeA.ToString()].Value.Real, 4);

        // I(I1) = +2 mA with direction "0→<a>"
        var i1Current = resp.Results.ElementCurrents["I1"];
        Assert.Equal(0.002, i1Current.Value.Real, 4);
        string expectedDirection = $"{nodeGnd}→{nodeA}";
        Assert.Equal(expectedDirection, i1Current.Direction);

        // CurrentDisplay shows "2 mA" and that direction
        var (displayVal, displayDir) = CurrentDisplay.Format("I1", i1Current);
        Assert.Equal("2 mA", displayVal);
        Assert.Equal(expectedDirection, displayDir);
    }

    [Fact]
    public async Task EndToEnd_PureCurrentSource_ProducesOneVolt()
    {
        // a pure current-source circuit (I1 into node a, R 1k to GND) gives V(a) = +1 V for 1 mA.
        var c = new TestCircuits();
        var i1 = c.Add(new CurrentSource { Value = 0.001 }, "I1");
        var r1 = c.Add(new Resistor { Value = 1000 }, "R1");
        var gnd = c.Add(new GroundElement(), "GND1");

        // I1 Pins[0] on GND, Pins[1] on node a
        c.Wire(i1.Pins[0], gnd.Pins[0]);
        c.Wire(i1.Pins[1], r1.Pins[0]);
        // R1 pin 1 to GND
        c.Wire(r1.Pins[1], gnd.Pins[0]);

        var netlistResult = NetlistBuilder.Build(c.Elements, c.Wires);
        int nodeA = netlistResult.NodeMap[r1.Pins[0]];

        var request = new AnalysisRequestDto
        {
            Netlist = netlistResult.Text,
            Mode = AnalysisModes.Dc,
            AnalysisType = AnalysisTypes.Nodal
        };

        var resp = await _fx.Client.AnalyzeAsync(request);
        Assert.Equal("success", resp.Status);
        Assert.Equal(1.0, resp.Results.NodeVoltages[nodeA.ToString()].Value.Real, 4);
    }

    [Fact]
    public void CreateVisual_OnStaThread_DoesNotThrow()
    {
        RunOnSta(() =>
        {
            var cs = new CurrentSource { Id = "I1", Value = 0.002 };
            var visualCs = cs.CreateVisual();
            Assert.NotNull(visualCs);

            var acPhys = new AcCurrentSource
            {
                Id = "IAC1",
                InputMode = AcInputMode.Physical,
                Amplitude = 0.01,
                Frequency = 50,
                Phase = 30
            };
            var visualAcPhys = acPhys.CreateVisual();
            Assert.NotNull(visualAcPhys);

            var acPhasor = new AcCurrentSource
            {
                Id = "IAC2",
                InputMode = AcInputMode.Phasor,
                Amplitude = 0.01,
                Phase = 0
            };
            var visualAcPhasor = acPhasor.CreateVisual();
            Assert.NotNull(visualAcPhasor);
        });
    }
}
