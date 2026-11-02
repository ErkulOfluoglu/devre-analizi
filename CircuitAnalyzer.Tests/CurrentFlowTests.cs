using System.Windows;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.Tests
{
    public class CurrentFlowTests
    {
        private static ElementCurrentDto Dc(double amps, string direction) =>
            new() { Value = ResultValue.FromReal(amps), Unit = "A", Direction = direction };

        /// <summary>V1 ve R1 seri: + ucundan R1'e 1 A çıkar, R1'den V1'in − ucuna döner.</summary>
        private static (List<CircuitElement> Els, List<Wire> Wires, Dictionary<Pin, int> Map, Wire Top, Wire Bottom, Resistor R1)
            SeriesLoop()
        {
            var v = new VoltageSource { Id = "V1", Position = new Point(0, 0) };
            var r = new Resistor { Id = "R1", Position = new Point(100, 0) };
            var top = new Wire(v.Pins[0], r.Pins[0]);
            var bottom = new Wire(r.Pins[1], v.Pins[1]);
            var map = new Dictionary<Pin, int> { [v.Pins[0]] = 1, [r.Pins[0]] = 1, [r.Pins[1]] = 0, [v.Pins[1]] = 0 };
            return (new List<CircuitElement> { v, r }, new List<Wire> { top, bottom }, map, top, bottom, r);
        }

        [Fact]
        public void SeriesLoop_WiresCarryTheCurrentInItsDirection()
        {
            var (els, wires, map, top, bottom, _) = SeriesLoop();
            var currents = new Dictionary<string, ElementCurrentDto>
            {
                ["V1"] = Dc(1, "0→1"),      // kaynağın içinde − uçtan + uca
                ["R1"] = Dc(1, "1→0"),
            };

            var flows = CurrentFlow.Compute(els, wires, map, currents);

            Assert.Equal(2, flows.Count);
            var t = flows.Single(f => f.Wire == top);
            var b = flows.Single(f => f.Wire == bottom);
            Assert.True(t.Forward);          // V1 + → R1
            Assert.True(b.Forward);          // R1 → V1 −
            Assert.Equal(1.0, t.Amps, 6);
            Assert.Equal(1.0, b.Amps, 6);
        }

        [Fact]
        public void NegativeCurrent_ReversesTheFlow()
        {
            var (els, wires, map, top, _, _) = SeriesLoop();
            var currents = new Dictionary<string, ElementCurrentDto>
            {
                ["V1"] = Dc(-1, "1→0"),
                ["R1"] = Dc(-1, "0→1"),
            };

            var flows = CurrentFlow.Compute(els, wires, map, currents);

            Assert.True(flows.Single(f => f.Wire == top).Forward);
        }

        [Fact]
        public void Junction_SplitsByKcl()
        {
            // V1 (2 A) ortak uçtan iki paralel dirence: R1 1,5 A, R2 0,5 A
            var v = new VoltageSource { Id = "V1", Position = new Point(0, 0) };
            var r1 = new Resistor { Id = "R1", Position = new Point(100, 0) };
            var r2 = new Resistor { Id = "R2", Position = new Point(100, 100) };
            var toR1 = new Wire(v.Pins[0], r1.Pins[0]);
            var r1ToR2 = new Wire(r1.Pins[0], r2.Pins[0]);
            var back1 = new Wire(r1.Pins[1], r2.Pins[1]);
            var back2 = new Wire(r2.Pins[1], v.Pins[1]);
            var map = new Dictionary<Pin, int>
            {
                [v.Pins[0]] = 1, [r1.Pins[0]] = 1, [r2.Pins[0]] = 1,
                [r1.Pins[1]] = 0, [r2.Pins[1]] = 0, [v.Pins[1]] = 0,
            };
            var currents = new Dictionary<string, ElementCurrentDto>
            {
                ["V1"] = Dc(2, "0→1"), ["R1"] = Dc(1.5, "1→0"), ["R2"] = Dc(0.5, "1→0"),
            };

            var flows = CurrentFlow.Compute(new CircuitElement[] { v, r1, r2 },
                new[] { toR1, r1ToR2, back1, back2 }, map, currents);

            Assert.Equal(2.0, flows.Single(f => f.Wire == toR1).Amps, 6);
            Assert.Equal(0.5, flows.Single(f => f.Wire == r1ToR2).Amps, 6);
            Assert.True(flows.Single(f => f.Wire == r1ToR2).Forward);
            Assert.Equal(1.5, flows.Single(f => f.Wire == back1).Amps, 6);
            Assert.Equal(2.0, flows.Single(f => f.Wire == back2).Amps, 6);
        }

        [Fact]
        public void WireLoop_GetsNoFlow()
        {
            // İki tel aynı iki ucu bağlıyor: dağılım belli değil, uydurma akım gösterilmez
            var (els, wires, map, top, bottom, r) = SeriesLoop();
            var extra = new Wire(els[0].Pins[0], r.Pins[0]);
            wires.Add(extra);
            var currents = new Dictionary<string, ElementCurrentDto>
            {
                ["V1"] = Dc(1, "0→1"), ["R1"] = Dc(1, "1→0"),
            };

            var flows = CurrentFlow.Compute(els, wires, map, currents);

            Assert.DoesNotContain(flows, f => f.Wire == top || f.Wire == extra);
            Assert.Contains(flows, f => f.Wire == bottom);
        }

        [Fact]
        public void ElementWithoutCurrent_BlocksItsNode()
        {
            var (els, wires, map, _, _, _) = SeriesLoop();
            var currents = new Dictionary<string, ElementCurrentDto> { ["V1"] = Dc(1, "0→1") };

            Assert.Empty(CurrentFlow.Compute(els, wires, map, currents));
        }

        [Fact]
        public void Branch_FollowsSeriesElementsAndStopsAtTheSplit()
        {
            // V1 → R1 → düğüm → (R2 ∥ R3) → V1: R2 seçilince yalnız onun teli
            var v = new VoltageSource { Id = "V1", Position = new Point(0, 0) };
            var r1 = new Resistor { Id = "R1", Position = new Point(100, 0) };
            var r2 = new Resistor { Id = "R2", Position = new Point(200, 0) };
            var r3 = new Resistor { Id = "R3", Position = new Point(200, 100) };
            var w1 = new Wire(v.Pins[0], r1.Pins[0]);
            var w2 = new Wire(r1.Pins[1], r2.Pins[0]);
            var w3 = new Wire(r2.Pins[0], r3.Pins[0]);
            var w4 = new Wire(r2.Pins[1], r3.Pins[1]);
            var w5 = new Wire(r3.Pins[1], v.Pins[1]);
            var map = new Dictionary<Pin, int>
            {
                [v.Pins[0]] = 1, [r1.Pins[0]] = 1, [r1.Pins[1]] = 2, [r2.Pins[0]] = 2, [r3.Pins[0]] = 2,
                [r2.Pins[1]] = 0, [r3.Pins[1]] = 0, [v.Pins[1]] = 0,
            };
            var currents = new Dictionary<string, ElementCurrentDto>
            {
                ["V1"] = Dc(3, "0→1"), ["R1"] = Dc(3, "1→2"), ["R2"] = Dc(2, "2→0"), ["R3"] = Dc(1, "2→0"),
            };
            var els = new CircuitElement[] { v, r1, r2, r3 };
            var flows = CurrentFlow.Compute(els, new[] { w1, w2, w3, w4, w5 }, map, currents);

            var ofR1 = CurrentFlow.BranchWires(r1, els, flows, map, currents);
            Assert.Contains(w1, ofR1);       // V1 ile aynı 3 A
            Assert.Contains(w2, ofR1);
            Assert.Contains(w5, ofR1);       // V1'in dönüş teli de 3 A
            Assert.DoesNotContain(w3, ofR1); // bölünen kollar değil

            var ofR3 = CurrentFlow.BranchWires(r3, els, flows, map, currents);
            Assert.Contains(w3, ofR3);       // R3'e giden 1 A
            Assert.DoesNotContain(w2, ofR3);
        }

        private static ElementCurrentDto Ac(double re, double im, string direction) =>
            new() { Value = new ResultValue { Real = re, Imaginary = im, IsComplex = true }, Unit = "A", Direction = direction };

        [Fact]
        public void Ac_JunctionAddsPhasors_NotMagnitudes()
        {
            // AC kaynaktan paralel R (1∠0° A) ve C (1∠90° A): ortak telde √2 A geçer, 2 A değil
            var v = new AcVoltageSource { Id = "VAC1", Position = new Point(0, 0) };
            var r1 = new Resistor { Id = "R1", Position = new Point(100, 0) };
            var c1 = new Capacitor { Id = "C1", Position = new Point(100, 100) };
            var trunk = new Wire(v.Pins[0], r1.Pins[0]);
            var toC = new Wire(r1.Pins[0], c1.Pins[0]);
            var back1 = new Wire(r1.Pins[1], c1.Pins[1]);
            var back2 = new Wire(c1.Pins[1], v.Pins[1]);
            var map = new Dictionary<Pin, int>
            {
                [v.Pins[0]] = 1, [r1.Pins[0]] = 1, [c1.Pins[0]] = 1,
                [r1.Pins[1]] = 0, [c1.Pins[1]] = 0, [v.Pins[1]] = 0,
            };
            var currents = new Dictionary<string, ElementCurrentDto>
            {
                // Gerilim kaynağının fazörü pasif yönde (+ uca giren) gelir; gösterimde ters çevrilir
                ["VAC1"] = Ac(-1, -1, "1→0"),
                ["R1"] = Ac(1, 0, "1→0"),
                ["C1"] = Ac(0, 1, "1→0"),
            };

            var flows = CurrentFlow.Compute(new CircuitElement[] { v, r1, c1 },
                new[] { trunk, toC, back1, back2 }, map, currents);

            Assert.Equal(Math.Sqrt(2), flows.Single(f => f.Wire == trunk).Amps, 6);
            var c = flows.Single(f => f.Wire == toC);
            Assert.Equal(1.0, c.Amps, 6);
            // R1'in ucundan C1'e giden akım C1'in fazörüdür: 0 + 1j
            Assert.Equal(0.0, c.Phasor.Real, 6);
            Assert.Equal(1.0, c.Phasor.Imaginary, 6);
            Assert.Equal(Math.Sqrt(2), flows.Single(f => f.Wire == back2).Amps, 6);
        }
    }
}
