using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Numerics;
using CircuitAnalyzer.WPF.Models;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Bir teldeki akım: Forward ise StartPin → EndPin yönünde, Amps büyüklüğü.
    /// Phasor, StartPin → EndPin yönündeki akımdır (DC'de sanal kısmı sıfır, AC'de fazör).
    /// </summary>
    public sealed record WireFlow(Wire Wire, bool Forward, double Amps, Complex Phasor = default);

    /// <summary>
    /// Elemanların akımlarından her telin akımını KCL ile bulur. Bir düğümün telleri ağaç
    /// oluşturur: yapraktan köke doğru toplanan akım teli geçen akımdır. AC'de akımlar fazör
    /// olarak (karmaşık sayı) toplanır; genlikleri düz toplamak yanlış olurdu. Tek çözümü olmayan
    /// (halka oluşturan) ya da akımı bilinmeyen elemana bağlı düğümdeki tellere akım atanmaz.
    /// </summary>
    public static class CurrentFlow
    {
        public static List<WireFlow> Compute(
            IEnumerable<CircuitElement> elements,
            IEnumerable<Wire> wires,
            IReadOnlyDictionary<Pin, int> nodeMap,
            IReadOnlyDictionary<string, ElementCurrentDto> currents)
        {
            var injected = new Dictionary<Pin, Complex>();
            var blockedNodes = new HashSet<int>();
            var ground = new HashSet<Pin>();

            foreach (var element in elements)
            {
                if (element is GroundElement)
                {
                    foreach (var pin in element.Pins) ground.Add(pin);
                    continue;
                }
                if (element is TestProbe or JunctionElement)
                    continue;

                if (!TryPhasor(element, nodeMap, currents, out var from, out var to, out Complex amps))
                {
                    foreach (var pin in element.Pins)
                        if (nodeMap.TryGetValue(pin, out int node)) blockedNodes.Add(node);
                    continue;
                }
                injected[from] = injected.GetValueOrDefault(from) - amps;
                injected[to] = injected.GetValueOrDefault(to) + amps;
            }

            var byPin = new Dictionary<Pin, List<Wire>>();
            foreach (var wire in wires)
            {
                if (!nodeMap.TryGetValue(wire.StartPin, out int node) || blockedNodes.Contains(node))
                    continue;
                foreach (var pin in new[] { wire.StartPin, wire.EndPin })
                {
                    if (!byPin.TryGetValue(pin, out var list))
                        byPin[pin] = list = new List<Wire>();
                    list.Add(wire);
                }
            }

            var flows = new List<WireFlow>();
            var visited = new HashSet<Pin>();
            foreach (var start in byPin.Keys.OrderBy(p => ground.Contains(p) ? 0 : 1))
            {
                if (!visited.Add(start))
                    continue;
                var (order, parentWire, isTree) = Walk(start, byPin, visited);
                if (!isTree)
                    continue;

                // Sıranın sondan başına: her düğüm ucu kendi alt ağacının toplamını ebeveyne iletir
                var sum = order.ToDictionary(p => p, p => injected.GetValueOrDefault(p));
                for (int i = order.Count - 1; i > 0; i--)
                {
                    var pin = order[i];
                    var wire = parentWire[pin];
                    var parent = wire.StartPin == pin ? wire.EndPin : wire.StartPin;
                    Complex current = sum[pin]; // pin'den ebeveyne doğru
                    sum[parent] += current;
                    if (current.Magnitude > 1e-12)
                    {
                        Complex alongWire = wire.StartPin == pin ? current : -current;
                        bool forward = alongWire.Real > 0 || (alongWire.Real == 0 && alongWire.Imaginary > 0);
                        flows.Add(new WireFlow(wire, forward, current.Magnitude, alongWire));
                    }
                }
            }

            double max = flows.Count > 0 ? flows.Max(f => f.Amps) : 0;
            return flows.Where(f => f.Amps > max * 1e-6).ToList();
        }

        /// <summary>İki uçlu elemanın akımı: fromPin ucundan girip toPin ucundan çıkar.</summary>
        public static bool TryBranch(
            CircuitElement element,
            IReadOnlyDictionary<Pin, int> nodeMap,
            IReadOnlyDictionary<string, ElementCurrentDto> currents,
            out Pin from, out Pin to, out double amps)
        {
            bool ok = TryPhasor(element, nodeMap, currents, out from, out to, out Complex phasor);
            amps = ok ? phasor.Magnitude : 0;
            return ok;
        }

        /// <summary>İki uçlu elemanın akımı fazör olarak (fromPin → toPin yönünde); DC'de pozitif gerçel.</summary>
        public static bool TryPhasor(
            CircuitElement element,
            IReadOnlyDictionary<Pin, int> nodeMap,
            IReadOnlyDictionary<string, ElementCurrentDto> currents,
            out Pin from, out Pin to, out Complex phasor)
        {
            from = to = null!;
            phasor = Complex.Zero;
            if (element.Pins.Count != 2 || !currents.TryGetValue(element.Id, out var dto))
                return false;

            var (value, direction) = CurrentDisplay.Normalize(element.Id, dto);
            string[] ends = direction.Split('→');
            if (ends.Length != 2
                || !int.TryParse(ends[0], NumberStyles.Integer, CultureInfo.InvariantCulture, out int a)
                || !int.TryParse(ends[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out int b)
                || a == b)
                return false;

            Pin? fromPin = element.Pins.FirstOrDefault(p => nodeMap.TryGetValue(p, out int n) && n == a);
            Pin? toPin = element.Pins.FirstOrDefault(p => nodeMap.TryGetValue(p, out int n) && n == b);
            if (fromPin == null || toPin == null)
                return false;

            from = fromPin;
            to = toPin;
            phasor = value.IsComplex ? new Complex(value.Real, value.Imaginary) : new Complex(Math.Abs(value.Real), 0);
            return true;
        }

        private static (List<Pin> Order, Dictionary<Pin, Wire> ParentWire, bool IsTree) Walk(
            Pin start, Dictionary<Pin, List<Wire>> byPin, HashSet<Pin> visited)
        {
            var order = new List<Pin> { start };
            var parentWire = new Dictionary<Pin, Wire>();
            var seenWires = new HashSet<Wire>();
            bool isTree = true;
            for (int i = 0; i < order.Count; i++)
            {
                foreach (var wire in byPin[order[i]])
                {
                    if (!seenWires.Add(wire))
                        continue;
                    var next = wire.StartPin == order[i] ? wire.EndPin : wire.StartPin;
                    if (!visited.Add(next))
                    {
                        isTree = false;
                        continue;
                    }
                    parentWire[next] = wire;
                    order.Add(next);
                }
            }
            return (order, parentWire, isTree);
        }

        /// <summary>
        /// Seçili elemanın kolu: aynı akımı taşıyan teller ve iki uçlu elemanlar boyunca yürür,
        /// akım bölündüğü düğümde durur.
        /// </summary>
        public static HashSet<Wire> BranchWires(
            CircuitElement selected,
            IEnumerable<CircuitElement> elements,
            IReadOnlyList<WireFlow> flows,
            IReadOnlyDictionary<Pin, int> nodeMap,
            IReadOnlyDictionary<string, ElementCurrentDto> currents)
        {
            var branch = new HashSet<Wire>();
            if (!TryBranch(selected, nodeMap, currents, out _, out _, out double amps) || amps <= 0)
                return branch;

            bool Same(double other) => Math.Abs(other - amps) <= amps * 0.01;

            var flowAt = new Dictionary<Pin, List<WireFlow>>();
            foreach (var flow in flows)
            {
                foreach (var pin in new[] { flow.Wire.StartPin, flow.Wire.EndPin })
                {
                    if (!flowAt.TryGetValue(pin, out var list))
                        flowAt[pin] = list = new List<WireFlow>();
                    list.Add(flow);
                }
            }

            var owners = new Dictionary<Pin, CircuitElement>();
            foreach (var element in elements)
                foreach (var pin in element.Pins)
                    owners[pin] = element;

            var seen = new HashSet<Pin>();
            var stack = new Stack<Pin>(selected.Pins);
            while (stack.Count > 0)
            {
                var pin = stack.Pop();
                if (!seen.Add(pin))
                    continue;

                if (flowAt.TryGetValue(pin, out var here))
                {
                    foreach (var flow in here.Where(f => Same(f.Amps)))
                    {
                        branch.Add(flow.Wire);
                        stack.Push(flow.Wire.StartPin == pin ? flow.Wire.EndPin : flow.Wire.StartPin);
                    }
                }

                // Aynı akımı taşıyan iki uçlu elemanın öteki ucuna geç (seri kol)
                if (owners.TryGetValue(pin, out var owner) && owner != selected
                    && TryBranch(owner, nodeMap, currents, out _, out _, out double other) && Same(other))
                {
                    foreach (var otherPin in owner.Pins)
                        stack.Push(otherPin);
                }
            }
            return branch;
        }
    }
}
