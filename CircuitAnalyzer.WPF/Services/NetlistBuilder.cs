using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Windows;
using CircuitAnalyzer.WPF.Models;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Netlist oluşturma sonucu.
    /// </summary>
    public sealed class NetlistResult
    {
        /// <summary>SPICE Netlist metni (Python API'ye gönderilir).</summary>
        public string Text { get; init; } = string.Empty;

        /// <summary>Her pinin düğüm numarası (GND ağı = 0).</summary>
        public Dictionary<Pin, int> NodeMap { get; init; } = new();

        /// <summary>Düğüm numarası → o düğüme bağlı pinler (etiket konumu için).</summary>
        public Dictionary<int, List<Pin>> NodePins { get; init; } = new();

        public bool HasGround { get; init; }

        public int NodeCount => NodePins.Count;

        /// <summary>Devrede AC kaynak var mı (analiz modu seçimi için).</summary>
        public bool HasAcSource { get; init; }

        /// <summary>Fazör modunda girilmiş AC kaynak var mı (frekans gerektirir).</summary>
        public bool HasPhasorSource { get; init; }
    }

    /// <summary>
    /// Canvas'taki elemanlardan ve tellerden SPICE Netlist üretir.
    ///
    /// Düğüm tespiti (Union-Find):
    ///   1. Aynı grid noktasına denk gelen pinler birleşir.
    ///   2. Tel ile bağlanan pinler birleşir.
    ///   3. GND elemanının bağlı olduğu ağ Node 0 olur, diğerleri 1'den başlar.
    ///
    /// Not: UI'dan bağımsızdır — test edilebilir ve hem "Netlist Oluştur"
    /// hem "Çöz" tarafından kullanılır.
    /// </summary>
    public static class NetlistBuilder
    {
        public static NetlistResult Build(
            IReadOnlyList<CircuitElement> elements,
            IReadOnlyList<Wire> wires,
            DateTime? timestamp = null)
        {
            var allPins = elements.SelectMany(el => el.Pins).ToList();

            // ═══ Union-Find ═══
            var parent = new Dictionary<Pin, Pin>();
            foreach (var pin in allPins)
                parent[pin] = pin;

            Pin Find(Pin p)
            {
                if (parent[p] != p)
                    parent[p] = Find(parent[p]);
                return parent[p];
            }

            void Union(Pin a, Pin b)
            {
                if (!parent.ContainsKey(a) || !parent.ContainsKey(b))
                    return; // Silinmiş elemana ait tel — yok say
                var rootA = Find(a);
                var rootB = Find(b);
                if (rootA != rootB)
                    parent[rootA] = rootB;
            }

            // Aynı grid noktasındaki pinler
            for (int i = 0; i < allPins.Count; i++)
            {
                for (int j = i + 1; j < allPins.Count; j++)
                {
                    Point posA = allPins[i].AbsolutePosition;
                    Point posB = allPins[j].AbsolutePosition;
                    if (Math.Abs(posA.X - posB.X) < 0.5 && Math.Abs(posA.Y - posB.Y) < 0.5)
                        Union(allPins[i], allPins[j]);
                }
            }

            // Tel ile bağlı pinler
            foreach (var wire in wires)
                Union(wire.StartPin, wire.EndPin);

            // ═══ Düğüm numaraları (GND = Node 0) ═══
            var gndRoots = new HashSet<Pin>(
                elements.OfType<GroundElement>()
                        .SelectMany(g => g.Pins)
                        .Select(Find));

            var nodeMap = new Dictionary<Pin, int>();
            var rootToNode = new Dictionary<Pin, int>();
            var nodePins = new Dictionary<int, List<Pin>>();
            int nextNodeId = 1;

            foreach (var pin in allPins)
            {
                var root = Find(pin);
                if (!rootToNode.TryGetValue(root, out int node))
                {
                    node = gndRoots.Contains(root) ? 0 : nextNodeId++;
                    rootToNode[root] = node;
                }
                nodeMap[pin] = node;
                if (!nodePins.TryGetValue(node, out var list))
                    nodePins[node] = list = new List<Pin>();
                list.Add(pin);
            }

            bool hasGround = elements.Any(el => el is GroundElement);
            var acSources = elements.OfType<AcVoltageSource>().ToList();
            var acCurrentSources = elements.OfType<AcCurrentSource>().ToList();

            // ═══ Netlist metni ═══
            var sb = new StringBuilder();
            sb.AppendLine("* Circuit Analyzer — Otomatik Netlist");
            sb.AppendLine($"* Tarih: {(timestamp ?? DateTime.Now):yyyy-MM-dd HH:mm}");
            sb.AppendLine($"* Eleman sayısı: {elements.Count}");
            sb.AppendLine($"* Tel sayısı: {wires.Count}");
            sb.AppendLine($"* Düğüm sayısı: {rootToNode.Count}");
            if (hasGround)
                sb.AppendLine("* Referans: Node 0 (GND)");
            sb.AppendLine("*");

            // Devre elemanları (GND ve Probe hariç, onlar ayrı yazdırılır)
            foreach (var element in elements)
            {
                if (element is GroundElement || element is TestProbe)
                    continue;
                sb.AppendLine(element.ToNetlistEntry(nodeMap));
            }

            // GND referansları
            foreach (var element in elements.OfType<GroundElement>())
                sb.AppendLine(element.ToNetlistEntry(nodeMap));

            // Düğüm çizim konumları (pinlerin ortalaması) — Python, çevre akımlarını
            // ekranda saat yönünde seçmek için kullanır; hesaplamayı etkilemez
            sb.AppendLine("*");
            foreach (var (node, pins) in nodePins.OrderBy(kv => kv.Key))
            {
                double x = pins.Average(p => p.AbsolutePosition.X);
                double y = pins.Average(p => p.AbsolutePosition.Y);
                sb.AppendLine(string.Create(CultureInfo.InvariantCulture,
                    $"* NODEPOS {node} {x:0.#} {y:0.#}"));
            }

            // Ölçüm probları (Python parser için)
            var probes = elements.OfType<TestProbe>().ToList();
            if (probes.Count > 0)
            {
                sb.AppendLine("*");
                sb.AppendLine("* ═══ Ölçüm Hedefleri ═══");
                foreach (var probe in probes)
                    sb.AppendLine(probe.ToNetlistEntry(nodeMap));
            }

            sb.AppendLine(".end");

            return new NetlistResult
            {
                Text = sb.ToString(),
                NodeMap = nodeMap,
                NodePins = nodePins,
                HasGround = hasGround,
                HasAcSource = acSources.Count > 0 || acCurrentSources.Count > 0,
                HasPhasorSource = acSources.Any(s => s.InputMode == AcInputMode.Phasor) || acCurrentSources.Any(s => s.InputMode == AcInputMode.Phasor),
            };
        }
    }
}
