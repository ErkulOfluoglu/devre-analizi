using System.Windows;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.Tests;

public class NetlistBuilderTests
{
    private static List<string> ElementLines(NetlistResult r) =>
        r.Text.Split('\n').Select(l => l.TrimEnd('\r')).Where(l => l.Length > 0).ToList();

    [Fact]
    public void DcDivider_ProducesExpectedNetlist()
    {
        var c = TestCircuits.DcDivider();
        var r = NetlistBuilder.Build(c.Elements, c.Wires);
        var lines = ElementLines(r);

        Assert.Contains("V1 1 0 DC 12", lines);
        Assert.Contains("R1 1 2 1000", lines);
        Assert.Contains("R2 2 0 2000", lines);
        Assert.Contains("* GND1 — Referans toprak (Node 0)", lines);
        Assert.Contains("* PROBE VP1 V(2)", lines);
        Assert.Equal(".end", lines[^1]);
        Assert.True(r.HasGround);
        Assert.Equal(3, r.NodeCount);           // 0, 1, 2
        Assert.False(r.HasAcSource);
    }

    [Fact]
    public void NodePins_GroupsPinsByNode()
    {
        var c = TestCircuits.DcDivider(withProbe: false);
        var r = NetlistBuilder.Build(c.Elements, c.Wires);

        var r1 = c.Elements.Single(e => e.Id == "R1");
        var r2 = c.Elements.Single(e => e.Id == "R2");
        Assert.Contains(r1.Pins[1], r.NodePins[2]);
        Assert.Contains(r2.Pins[0], r.NodePins[2]);
        Assert.Equal(r.NodeMap[r1.Pins[1]], r.NodeMap[r2.Pins[0]]);
        Assert.All(r.NodePins[0], p => Assert.Equal(0, r.NodeMap[p]));
    }

    [Fact]
    public void PinsOnSameGridPoint_AreConnectedWithoutWire()
    {
        var r1 = new Resistor { Id = "R1", Value = 1, Position = new Point(0, 0) };
        // R1'in sağ pini (80,20) ile R2'nin sol pini (80,20) çakışır
        var r2 = new Resistor { Id = "R2", Value = 2, Position = new Point(80, 0) };
        var r = NetlistBuilder.Build(new List<CircuitElement> { r1, r2 }, new List<Wire>());

        Assert.Equal(r.NodeMap[r1.Pins[1]], r.NodeMap[r2.Pins[0]]);
        Assert.Equal(3, r.NodeCount);
        Assert.False(r.HasGround);
    }

    [Fact]
    public void WireToDeletedElement_IsIgnored()
    {
        var c = TestCircuits.DcDivider(withProbe: false);
        var orphan = new Resistor { Id = "RX", Position = new Point(5000, 5000) };
        c.Wires.Add(new Wire(orphan.Pins[0], c.Elements[0].Pins[0]));

        var r = NetlistBuilder.Build(c.Elements, c.Wires);   // istisna fırlatmamalı
        Assert.DoesNotContain("RX", r.Text);
    }

    [Fact]
    public void AcPhasorSource_SetsFlags()
    {
        var c = TestCircuits.AcRcLowPass();
        var r = NetlistBuilder.Build(c.Elements, c.Wires);
        Assert.True(r.HasAcSource);
        Assert.True(r.HasPhasorSource);
        Assert.Contains("VAC1 1 0 AC_PHASOR(10, 0)", ElementLines(r));
        Assert.Contains("C1 2 0 100u", ElementLines(r));
    }

    [Fact]
    public void NoGround_StartsNodesAtOne()
    {
        var c = TestCircuits.DcDivider(withProbe: false);
        c.Elements.RemoveAll(e => e is GroundElement);
        c.Wires.RemoveAll(w => w.EndPin.Owner is GroundElement);
        var r = NetlistBuilder.Build(c.Elements, c.Wires);
        Assert.False(r.HasGround);
        Assert.DoesNotContain(0, r.NodeMap.Values);
    }
}
