using System.Windows;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.Tests;

public class NetlistTopologyTests
{
    private static List<string> ElementLines(NetlistResult r) =>
        r.Text.Split('\n')
            .Select(l => l.TrimEnd('\r'))
            .Where(l => l.Length > 0 && !l.StartsWith("*") && l != ".end")
            .ToList();

    [Fact]
    public void Resistor_Rotated90Degrees_ConnectsToOtherElementPinWithoutWire()
    {
        // R1: 80x40 piksel, merkez (40, 20).
        // 90° döndürmede:
        //   Pin 1 (rel 0, 20) -> mutlak (Position.X + 40, Position.Y - 20)
        //   Pin 2 (rel 80, 20) -> mutlak (Position.X + 40, Position.Y + 60)
        var r1 = new Resistor
        {
            Id = "R1",
            Value = 100,
            Position = new Point(0, 0),
            Rotation = 90
        };

        // Pin 2 mutlak konumu: (40, 60)
        Assert.Equal(40, r1.Pins[1].AbsolutePosition.X, 2);
        Assert.Equal(60, r1.Pins[1].AbsolutePosition.Y, 2);

        // R2'yi (40, 40) konumuna 0° dönüşle yerleştiriyoruz.
        // R2'nin Pin 1'i (rel 0, 20) -> mutlak (40 + 0, 40 + 20) = (40, 60).
        var r2 = new Resistor
        {
            Id = "R2",
            Value = 200,
            Position = new Point(40, 40),
            Rotation = 0
        };
        Assert.Equal(40, r2.Pins[0].AbsolutePosition.X, 2);
        Assert.Equal(60, r2.Pins[0].AbsolutePosition.Y, 2);

        var r = NetlistBuilder.Build(new List<CircuitElement> { r1, r2 }, new List<Wire>());

        // Tel olmadan çakışan pinler aynı düğüme atanmalı
        Assert.Equal(r.NodeMap[r1.Pins[1]], r.NodeMap[r2.Pins[0]]);
        Assert.Equal(3, r.NodeCount); // r1.Pins[0], ortak düğüm, r2.Pins[1]
    }

    [Fact]
    public void Resistor_Rotated180Degrees_PinCoordinatesAndConnection()
    {
        // 180° rotasyonda pinler yer değiştirir:
        //   Pin 1 (rel 0, 20) -> (80, 20)
        //   Pin 2 (rel 80, 20) -> (0, 20)
        var r1 = new Resistor
        {
            Id = "R1",
            Position = new Point(0, 0),
            Rotation = 180
        };
        Assert.Equal(80, r1.Pins[0].AbsolutePosition.X, 2);
        Assert.Equal(20, r1.Pins[0].AbsolutePosition.Y, 2);
        Assert.Equal(0, r1.Pins[1].AbsolutePosition.X, 2);
        Assert.Equal(20, r1.Pins[1].AbsolutePosition.Y, 2);

        // R2 (80, 0) konumunda 0°: Pin 1 = (80, 20)
        var r2 = new Resistor
        {
            Id = "R2",
            Position = new Point(80, 0),
            Rotation = 0
        };

        var result = NetlistBuilder.Build(new List<CircuitElement> { r1, r2 }, new List<Wire>());
        Assert.Equal(result.NodeMap[r1.Pins[0]], result.NodeMap[r2.Pins[0]]);
    }

    [Fact]
    public void Resistor_Rotated270Degrees_PinCoordinatesAndConnection()
    {
        // 270° rotasyonda:
        //   Pin 1 (rel 0, 20) -> (40, 60)
        //   Pin 2 (rel 80, 20) -> (40, -20)
        var r1 = new Resistor
        {
            Id = "R1",
            Position = new Point(0, 0),
            Rotation = 270
        };
        Assert.Equal(40, r1.Pins[0].AbsolutePosition.X, 2);
        Assert.Equal(60, r1.Pins[0].AbsolutePosition.Y, 2);

        var r2 = new Resistor
        {
            Id = "R2",
            Position = new Point(40, 40),
            Rotation = 0
        };

        var result = NetlistBuilder.Build(new List<CircuitElement> { r1, r2 }, new List<Wire>());
        Assert.Equal(result.NodeMap[r1.Pins[0]], result.NodeMap[r2.Pins[0]]);
    }

    [Fact]
    public void TwoGroundElements_OnSeparateNets_BothMapToNodeZero()
    {
        // Net 1: R1 pini GND1'e bağlı
        var r1 = new Resistor { Id = "R1", Position = new Point(100, 100) };
        var gnd1 = new GroundElement { Id = "GND1", Position = new Point(100, 300) };
        var wire1 = new Wire(r1.Pins[0], gnd1.Pins[0]);

        // Net 2: R2 pini GND2'ye bağlı (Net 1 ile hiçbir elektriksel bağı yok)
        var r2 = new Resistor { Id = "R2", Position = new Point(500, 100) };
        var gnd2 = new GroundElement { Id = "GND2", Position = new Point(500, 300) };
        var wire2 = new Wire(r2.Pins[1], gnd2.Pins[0]);

        var elements = new List<CircuitElement> { r1, gnd1, r2, gnd2 };
        var wires = new List<Wire> { wire1, wire2 };

        var r = NetlistBuilder.Build(elements, wires);

        Assert.True(r.HasGround);
        Assert.Equal(0, r.NodeMap[r1.Pins[0]]);
        Assert.Equal(0, r.NodeMap[gnd1.Pins[0]]);
        Assert.Equal(0, r.NodeMap[r2.Pins[1]]);
        Assert.Equal(0, r.NodeMap[gnd2.Pins[0]]);

        // Düğüm 0 havuzunda her iki ağın pinleri yer alır
        Assert.Contains(r1.Pins[0], r.NodePins[0]);
        Assert.Contains(gnd1.Pins[0], r.NodePins[0]);
        Assert.Contains(r2.Pins[1], r.NodePins[0]);
        Assert.Contains(gnd2.Pins[0], r.NodePins[0]);
    }

    [Fact]
    public void FixedTimestamp_ProducesIdenticalNetlistText()
    {
        var c = TestCircuits.DcDivider();
        var ts = new DateTime(2026, 4, 15, 12, 34, 56);

        var r1 = NetlistBuilder.Build(c.Elements, c.Wires, timestamp: ts);
        var r2 = NetlistBuilder.Build(c.Elements, c.Wires, timestamp: ts);

        Assert.Equal(r1.Text, r2.Text);
        Assert.Contains("* Tarih: 2026-04-15 12:34", r1.Text);
    }

    [Fact]
    public void ProbePin_WiredToNode_DoesNotCreateExtraElementLine()
    {
        var c = TestCircuits.DcDivider(withProbe: true);
        var r = NetlistBuilder.Build(c.Elements, c.Wires);

        var elements = ElementLines(r);

        // Sadece V1, R1, R2 eleman satırları olmalı; prob satırı elemanlar arasında yer almaz
        Assert.Equal(3, elements.Count);
        Assert.Contains(elements, l => l.StartsWith("V1 "));
        Assert.Contains(elements, l => l.StartsWith("R1 "));
        Assert.Contains(elements, l => l.StartsWith("R2 "));
        Assert.DoesNotContain(elements, l => l.StartsWith("VP1 "));

        // Prob yalnızca * PROBE yorum satırı olarak yer almalı
        Assert.Contains("* PROBE VP1 V(2)", r.Text);
    }

    /// <summary>
    /// Belgelenen Davranış:
    /// NetlistBuilder tüm elemanların pinlerini Union-Find kümesine kaydeder.
    /// Devreye hiçbir telle veya çakışmayla bağlı olmayan bir voltaj probu
    /// kendi başına bir kök (root) oluşturur ve boşta kalan prob için benzersiz
    /// bir düğüm numarası üretilir (örn. Node 3).
    /// </summary>
    [Fact]
    public void UnconnectedVoltageProbe_YieldsItsOwnNodeNumber()
    {
        var r1 = new Resistor { Id = "R1", Position = new Point(100, 100) };
        var probe = new TestProbe { Id = "VP1", Type = ProbeType.Voltage, Position = new Point(500, 500) };

        var r = NetlistBuilder.Build(new List<CircuitElement> { r1, probe }, new List<Wire>());

        // R1'in pinleri 1 ve 2 düğümlerini alır
        int nodeR1A = r.NodeMap[r1.Pins[0]];
        int nodeR1B = r.NodeMap[r1.Pins[1]];

        // Bağlantısız prob pini de bir düğüm numarası alır
        Assert.True(r.NodeMap.ContainsKey(probe.Pins[0]));
        int probeNode = r.NodeMap[probe.Pins[0]];

        Assert.NotEqual(nodeR1A, probeNode);
        Assert.NotEqual(nodeR1B, probeNode);
        Assert.True(probeNode > 0);

        // Netlist çıktısında bu düğüm numarasıyla prob direktifi yer alır
        Assert.Contains($"* PROBE VP1 V({probeNode})", r.Text);
        Assert.Single(r.NodePins[probeNode]);
        Assert.Same(probe.Pins[0], r.NodePins[probeNode][0]);
    }

    [Fact]
    public void RedundantWire_BetweenAlreadyConnectedPins_DoesNotChangeNodeCount()
    {
        var r1 = new Resistor { Id = "R1", Position = new Point(0, 0) };
        var r2 = new Resistor { Id = "R2", Position = new Point(80, 0) };

        // Pinler zaten çakışık (80, 20)
        var wire = new Wire(r1.Pins[1], r2.Pins[0]);
        var r = NetlistBuilder.Build(new List<CircuitElement> { r1, r2 }, new List<Wire> { wire });

        Assert.Equal(r.NodeMap[r1.Pins[1]], r.NodeMap[r2.Pins[0]]);
        Assert.Equal(3, r.NodeCount);
    }

    [Fact]
    public void ThreeResistorsInSeries_GridAbutment_CreatesFourSequentialNodes()
    {
        var r1 = new Resistor { Id = "R1", Position = new Point(0, 0) };
        var r2 = new Resistor { Id = "R2", Position = new Point(80, 0) };
        var r3 = new Resistor { Id = "R3", Position = new Point(160, 0) };

        var r = NetlistBuilder.Build(new List<CircuitElement> { r1, r2, r3 }, new List<Wire>());

        Assert.Equal(4, r.NodeCount);
        Assert.Equal(r.NodeMap[r1.Pins[1]], r.NodeMap[r2.Pins[0]]);
        Assert.Equal(r.NodeMap[r2.Pins[1]], r.NodeMap[r3.Pins[0]]);
    }
}
