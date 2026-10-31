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

        /// <summary>Fazör modunda girilmiş AC kaynak var mı.</summary>
        public bool HasPhasorSource { get; init; }

        /// <summary>Fazör kaynakların frekansları (farklı değerler). Netlist satırı frekans taşımaz; istekle gider.</summary>
        public IReadOnlyList<double> PhasorFrequencies { get; init; } = Array.Empty<double>();
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
        /// <summary>
        /// Bağımlı kaynakların kontrol elemanlarını denetler. Çözmeden önce çağrılır: sorun varsa
        /// ilk sorunun Türkçe mesajını döndürür (arka uç çağrılmaz), yoksa null.
        /// </summary>
        public static string? ValidateDependentSources(IEnumerable<CircuitElement> elements)
        {
            var list = elements.ToList();
            foreach (var dep in list.OfType<DependentSource>())
            {
                string name = dep.Id;
                string control = (dep.ControlElementId ?? string.Empty).Trim();

                if (control.Length == 0)
                    return $"{name} için kontrol eden eleman seçilmemiş";

                if (string.Equals(control, dep.Id, StringComparison.OrdinalIgnoreCase))
                    return $"{name} kendi kendini kontrol edemez";

                var target = list.FirstOrDefault(e => string.Equals(e.Id, control, StringComparison.OrdinalIgnoreCase));
                if (target == null)
                    return $"{name}{GenitiveSuffix(name)} kontrol ettiği {control} devrede yok";

                if (!DependentSource.CanBeControl(target))
                    return $"{name}{GenitiveSuffix(name)} kontrol ettiği {control} iki uçlu bir devre elemanı değil";
            }

            // Aynı elemanın aynı büyüklüğü (V_R2 ya da I_R2) iki kaynakta ters yönlerde tanımlanamaz:
            // ekranda tek bir +/− (ya da ok) çizildiği için ikinci kaynağın etiketi yanıltıcı olurdu
            var conflict = list.OfType<DependentSource>()
                .GroupBy(d => (Control: (d.ControlElementId ?? string.Empty).Trim().ToUpperInvariant(), d.IsVoltageControlled))
                .FirstOrDefault(g => g.Select(d => d.ControlReversed).Distinct().Count() > 1);
            if (conflict != null)
            {
                var first = conflict.First();
                string quantity = $"{(first.IsVoltageControlled ? "V" : "I")}_{first.ControlElementId.Trim()}";
                return $"{string.Join(" ve ", conflict.Select(d => d.Id))} aynı {quantity} büyüklüğünü " +
                       "ters yönlerde kullanıyor; birinde “Yönü ters çevir” seçimini değiştirin";
            }
            return null;
        }

        /// <summary>
        /// Kimliğin ("E1", "G12") okunuşuna göre tamlayan eki: E1'in, E2'nin, E3'ün, G10'un …
        /// Kesme işaretiyle birlikte döner.
        /// </summary>
        internal static string GenitiveSuffix(string id)
        {
            if (string.IsNullOrEmpty(id) || !char.IsDigit(id[^1]))
                return "'in";

            int end = id.Length;
            int start = end;
            while (start > 0 && char.IsDigit(id[start - 1]))
                start--;
            if (!int.TryParse(id.AsSpan(start, end - start), out int number))
                return "'in";

            // Sayının okunuşunun son sesli harfine göre (bir→in, iki→nin, üç→ün, dört→ün, beş→in,
            // altı→nın, yedi→nin, sekiz→in, dokuz→un, sıfır→ın; 10 on→un, 20 yirmi→nin …)
            if (number >= 100 && number % 100 == 0) return "'ün";   // yüz
            int digit = number % 10;
            if (digit == 0)
            {
                return (number / 10 % 10) switch
                {
                    0 => "'ın",     // sıfır
                    1 => "'un",     // on
                    2 => "'nin",    // yirmi
                    3 => "'un",     // otuz
                    4 => "'ın",     // kırk
                    5 => "'nin",    // elli
                    6 => "'ın",     // altmış
                    7 => "'in",     // yetmiş
                    8 => "'in",     // seksen
                    _ => "'ın",     // doksan
                };
            }
            return digit switch
            {
                1 => "'in",
                2 => "'nin",
                3 => "'ün",
                4 => "'ün",
                5 => "'in",
                6 => "'nın",
                7 => "'nin",
                8 => "'in",
                _ => "'un",
            };
        }

        public static NetlistResult Build(
            IReadOnlyList<CircuitElement> elements,
            IReadOnlyList<Wire> wires,
            DateTime? timestamp = null)
        {
            // Bağlantı noktası (JunctionElement) pinlerini sona bırak ki düğüm numaralandırma
            // sırası doğrudan pin-pin bağlantılı devreyle birebir aynı kalsın.
            var allPins = elements
                .Where(el => el is not JunctionElement)
                .Concat(elements.Where(el => el is JunctionElement))
                .SelectMany(el => el.Pins)
                .ToList();

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
            var threePhaseSources = elements.OfType<ThreePhaseSource>().ToList();
            var wattmeters = elements.OfType<Wattmeter>().ToList();

            // ═══ Netlist metni ═══
            int componentCount = elements.Count(el => el is not JunctionElement);
            var sb = new StringBuilder();
            sb.AppendLine("* Circuit Analyzer — Otomatik Netlist");
            sb.AppendLine($"* Tarih: {(timestamp ?? DateTime.Now):yyyy-MM-dd HH:mm}");
            sb.AppendLine($"* Eleman sayısı: {componentCount}");
            sb.AppendLine($"* Tel sayısı: {wires.Count}");
            sb.AppendLine($"* Düğüm sayısı: {rootToNode.Count}");
            if (hasGround)
                sb.AppendLine("* Referans: Node 0 (GND)");
            sb.AppendLine("*");

            // Devre elemanları (GND, Probe ve bağlantı noktaları hariç)
            foreach (var element in elements)
            {
                if (element is GroundElement || element is TestProbe || element is JunctionElement)
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
                var posPins = pins.Where(p => p.Owner is not JunctionElement).ToList();
                if (posPins.Count == 0)
                    posPins = pins;
                double x = posPins.Average(p => p.AbsolutePosition.X);
                double y = posPins.Average(p => p.AbsolutePosition.Y);
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
                HasAcSource = acSources.Count > 0 || acCurrentSources.Count > 0 || threePhaseSources.Count > 0 || wattmeters.Count > 0,
                HasPhasorSource = acSources.Any(s => s.InputMode == AcInputMode.Phasor) || acCurrentSources.Any(s => s.InputMode == AcInputMode.Phasor),
                PhasorFrequencies = acSources.Where(s => s.InputMode == AcInputMode.Phasor).Select(s => s.Frequency)
                    .Concat(acCurrentSources.Where(s => s.InputMode == AcInputMode.Phasor).Select(s => s.Frequency))
                    .Distinct().ToList(),
            };
        }
    }
}
