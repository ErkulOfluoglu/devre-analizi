using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

public class ExampleCircuitsTests : IClassFixture<BackendFixture>
{
    private readonly BackendFixture _fx;

    public ExampleCircuitsTests(BackendFixture fx)
    {
        _fx = fx;
    }

    public static IEnumerable<object[]> AllFactories =>
        ExampleCircuits.All.Select(f => new object[] { f });

    [Theory]
    [MemberData(nameof(AllFactories))]
    public void Factory_ReturnsFreshInstances_AndValidStructure(Func<ExampleCircuit> factory)
    {
        var c1 = factory();
        var c2 = factory();

        // Fresh element / wire objects and no shared Pin instances
        Assert.NotSame(c1, c2);

        var pins1 = c1.Elements.SelectMany(e => e.Pins).ToHashSet();
        foreach (var pin in c2.Elements.SelectMany(e => e.Pins))
        {
            Assert.DoesNotContain(pin, pins1);
        }

        var wires1 = c1.Wires.ToHashSet();
        foreach (var wire in c2.Wires)
        {
            Assert.DoesNotContain(wire, wires1);
        }

        // All element IDs unique
        var ids = c1.Elements.Select(e => e.Id).ToList();
        Assert.Equal(ids.Count, ids.Distinct(StringComparer.OrdinalIgnoreCase).Count());

        // NetlistBuilder.Build(...).HasGround is true
        var netlist = NetlistBuilder.Build(c1.Elements, c1.Wires);
        Assert.True(netlist.HasGround, $"Devrede GND bulunmalı: {c1.Name}");

        // No node has exactly one pin except intentional ones:
        // Every passive/source pin is wired: check every non-probe, non-ground pin's node has >= 2 pins
        foreach (var element in c1.Elements)
        {
            if (element is TestProbe or GroundElement)
                continue;

            foreach (var pin in element.Pins)
            {
                int node = netlist.NodeMap[pin];
                int count = netlist.NodePins[node].Count;
                Assert.True(count >= 2,
                    $"{c1.Name}: Eleman {element.Id} pini {pin.Id} düğüm {node}'da ama sadece {count} pin bağlı.");
            }
        }

        // Suggested analysis type is one of AnalysisTypes constants
        var validAnalysisTypes = new[] { AnalysisTypes.Nodal, AnalysisTypes.Thevenin, AnalysisTypes.Norton, AnalysisTypes.Mesh, AnalysisTypes.Superposition };
        Assert.Contains(c1.SuggestedAnalysisType, validAnalysisTypes);
    }

    private static AnalysisRequestDto BuildSolverRequest(ExampleCircuit c, NetlistResult netlist) =>
        new()
        {
            Netlist = netlist.Text,
            Mode = netlist.HasAcSource ? AnalysisModes.AcPhasor : AnalysisModes.Dc,
            Frequency = null,
            AnalysisType = c.SuggestedAnalysisType,
            TheveninTerminals = c.SuggestedTerminal != null
                ? new TerminalsDto { NodePositive = c.SuggestedTerminal, NodeNegative = "0" }
                : null
        };

    [Fact]
    public async Task Solve_DcVoltageDivider_MatchesTextbookAnswers()
    {
        var c = ExampleCircuits.DcVoltageDivider();
        var netlist = NetlistBuilder.Build(c.Elements, c.Wires);
        var resp = await _fx.Client.AnalyzeAsync(BuildSolverRequest(c, netlist));

        Assert.Equal("success", resp.Status);

        // V(node of R1–R2 junction) = 8 V
        var r1 = c.Elements.First(e => e.Id == "R1");
        int junctionNode = netlist.NodeMap[r1.Pins[1]];
        Assert.Equal(8.0, resp.Results.NodeVoltages[junctionNode.ToString()].Value.Real, 4);

        // I(R1) = 4 mA
        Assert.Equal(0.004, resp.Results.ElementCurrents["R1"].Value.Real, 6);

        // probe VP1 = 8 V
        var vp1 = resp.Results.ProbeResults.First(p => p.ProbeId == "VP1");
        Assert.Equal(8.0, vp1.Value.Real, 4);
    }

    [Fact]
    public async Task Solve_DcLadderThevenin_MatchesTextbookAnswers()
    {
        var c = ExampleCircuits.DcLadderThevenin();
        var netlist = NetlistBuilder.Build(c.Elements, c.Wires);

        // Thevenin at node "3" (terminal at R4 top node / R3 pin 1)
        var r4 = c.Elements.First(e => e.Id == "R4");
        int node3 = netlist.NodeMap[r4.Pins[0]];
        Assert.Equal("3", node3.ToString());

        var resp = await _fx.Client.AnalyzeAsync(BuildSolverRequest(c, netlist));

        Assert.Equal("success", resp.Status);
        Assert.NotNull(resp.Results.Thevenin);

        // Vth = 3 V, Zth = 625 Ω
        Assert.Equal(3.0, resp.Results.Thevenin!.Vth.Real, 4);
        Assert.Equal(625.0, resp.Results.Thevenin.Zth.Real, 4);
    }

    [Fact]
    public async Task Solve_AcRcLowPass_MatchesTextbookAnswers()
    {
        var c = ExampleCircuits.AcRcLowPass();
        var netlist = NetlistBuilder.Build(c.Elements, c.Wires);
        var resp = await _fx.Client.AnalyzeAsync(BuildSolverRequest(c, netlist));

        // status "success", Warnings contains "kaynak frekansı kullanıldı"
        Assert.Equal("success", resp.Status);
        Assert.Contains(resp.Warnings, w => w.Contains("kaynak frekansı kullanıldı"));

        // |V(C1 top node)| = 3.0331 V, phase −72.34° (±0.05°)
        var c1 = c.Elements.First(e => e.Id == "C1");
        int c1TopNode = netlist.NodeMap[c1.Pins[0]];
        var vC1 = resp.Results.NodeVoltages[c1TopNode.ToString()].Value;

        Assert.Equal(3.0331, vC1.Magnitude, 3);
        Assert.InRange(vC1.PhaseDegrees, -72.34 - 0.05, -72.34 + 0.05);
    }

    [Fact]
    public async Task Solve_AcRlSeries_MatchesTextbookAnswers()
    {
        var c = ExampleCircuits.AcRlSeries();
        var netlist = NetlistBuilder.Build(c.Elements, c.Wires);
        var resp = await _fx.Client.AnalyzeAsync(BuildSolverRequest(c, netlist));

        Assert.Equal("success", resp.Status);

        // |I(R1)| = 0.3194 A
        var iR1 = resp.Results.ElementCurrents["R1"].Value;
        Assert.Equal(0.3194, iR1.Magnitude, 3);

        // circuit power factor ≈ 0.7985 "geri"
        Assert.NotNull(resp.Results.Power);
        Assert.NotNull(resp.Results.Power!.PowerFactor);
        Assert.Equal(0.7985, resp.Results.Power.PowerFactor.Value, 3);
        Assert.Equal("geri", resp.Results.Power.PowerFactorType);

        // |V(L1 top node)| = 12.04 V
        var l1 = c.Elements.First(e => e.Id == "L1");
        int l1TopNode = netlist.NodeMap[l1.Pins[0]];
        var vL1 = resp.Results.NodeVoltages[l1TopNode.ToString()].Value;
        Assert.Equal(12.04, vL1.Magnitude, 2);
    }
}
