using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using CircuitAnalyzer.WPF.Models;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>Eleman bırakıldığında veya taşındığında kurulan otomatik bağlantı türü.</summary>
    public enum DropConnectionKind
    {
        /// <summary>Serbest uç mevcut bir telin ortasına T-bağlantı noktası (JunctionElement) ile bağlandı.</summary>
        WireSplit,

        /// <summary>İki uçlu eleman aynı düz tel parçasına seri eklendi; aradaki tel çıkarıldı.</summary>
        SeriesInsert,

        /// <summary>Serbest uç başka bir elemanın (veya bağlantı noktasının) ucuna sıfır uzunluklu telle bağlandı.</summary>
        PinToPin,
    }

    /// <summary>Tek bir otomatik bağlantı işleminin özeti.</summary>
    public sealed record DropConnectionEvent(
        CircuitElement Element,
        DropConnectionKind Kind,
        Point Point,
        JunctionElement? CreatedJunction = null,
        CircuitElement? TargetElement = null);

    /// <summary>
    /// <see cref="WireDropConnector.Connect(IList{CircuitElement}, IList{Wire}, IEnumerable{CircuitElement}, double)"/>
    /// çağrısının net değişiklik listesi (eklenen bağlantı noktaları, kaldırılan/eklenen teller ve olaylar).
    /// </summary>
    public sealed class WireDropResult
    {
        public List<JunctionElement> AddedJunctions { get; } = new();
        public List<Wire> RemovedWires { get; } = new();
        public List<Wire> AddedWires { get; } = new();
        public List<DropConnectionEvent> Connections { get; } = new();

        public bool AnyConnected => Connections.Count > 0;
        public bool HasSeriesInsert => Connections.Any(c => c.Kind == DropConnectionKind.SeriesInsert);
    }

    /// <summary>
    /// Eleman yerleştirildiğinde, taşındığında, döndürüldüğünde veya yapıştırıldığında
    /// serbest uçlarını üstüne düştüğü tellere / uçlara otomatik bağlayan saf topoloji yardımcısı.
    /// WPF görsel nesnelerine bağımlı değildir; birim testlerde doğrudan çalıştırılabilir.
    /// </summary>
    public static class WireDropConnector
    {
        /// <summary>Tel çizimindeki yakalama eşiği ile aynı varsayılan tolerans (tuval birimi).</summary>
        public const double DefaultWireTolerance = 6.0;

        private const double CoordinateEpsilon = 0.5;

        /// <summary>
        /// Bağlantı noktaları ve akım probları (pin yerine hedef kimliği kullanır) otomatik bağlanmaz.
        /// GND ve gerilim probu normal uç gibi bağlanır.
        /// </summary>
        public static bool IsEligibleElement(CircuitElement? element) =>
            element != null &&
            element is not JunctionElement &&
            element is not TestProbe { Type: ProbeType.Current };

        /// <summary>Tek bir eleman için otomatik tel/uç bağlantısı uygular.</summary>
        public static WireDropResult Connect(
            IList<CircuitElement> elements,
            IList<Wire> wires,
            CircuitElement movedElement,
            double wireTolerance = DefaultWireTolerance)
        {
            ArgumentNullException.ThrowIfNull(movedElement);
            return Connect(elements, wires, new[] { movedElement }, wireTolerance);
        }

        /// <summary>Verilen elemanlar için otomatik tel/uç bağlantısı uygular; listeleri yerinde günceller.</summary>
        public static WireDropResult Connect(
            IList<CircuitElement> elements,
            IList<Wire> wires,
            IEnumerable<CircuitElement> movedElements,
            double wireTolerance = DefaultWireTolerance)
        {
            ArgumentNullException.ThrowIfNull(elements);
            ArgumentNullException.ThrowIfNull(wires);
            ArgumentNullException.ThrowIfNull(movedElements);

            var result = new WireDropResult();
            double effectiveTolerance = Math.Clamp(wireTolerance, CoordinateEpsilon, DefaultWireTolerance);

            foreach (var element in movedElements)
            {
                if (!IsEligibleElement(element))
                    continue;

                ConnectSingleElement(elements, wires, element, effectiveTolerance, result);
            }

            if (result.AnyConnected)
            {
                RefreshJunctionCounts(elements, wires);
            }

            return result;
        }

        /// <summary>
        /// Sürükleme veya yerleştirme önizlemesi sırasında elemanın bırakıldığında bağlanacağı noktaları hesaplar.
        /// Devreyi değiştirmez.
        /// </summary>
        public static List<Point> FindPreviewPoints(
            IReadOnlyList<CircuitElement> elements,
            IReadOnlyList<Wire> wires,
            IEnumerable<CircuitElement> candidateElements,
            double wireTolerance = DefaultWireTolerance)
        {
            var points = new List<Point>();
            if (elements == null || wires == null || candidateElements == null)
                return points;

            double effectiveTolerance = Math.Clamp(wireTolerance, CoordinateEpsilon, DefaultWireTolerance);

            foreach (var element in candidateElements)
            {
                if (!IsEligibleElement(element))
                    continue;

                if (TryFindSeriesCandidate(wires, element, out _, out _, out _))
                {
                    AddDistinctPoint(points, element.Pins[0].AbsolutePosition);
                    AddDistinctPoint(points, element.Pins[1].AbsolutePosition);
                    continue;
                }

                var candidateWires = wires
                    .Where(w => w?.StartPin != null && w.EndPin != null &&
                                w.StartPin.Owner != element && w.EndPin.Owner != element)
                    .ToList();

                foreach (var pin in element.Pins)
                {
                    if (IsPinConnected(wires, pin))
                        continue;

                    Point pinPos = pin.AbsolutePosition;
                    var wireHit = WireGeometry.HitTestWire(candidateWires, pinPos, effectiveTolerance);
                    if (wireHit is var (_, snapped) && WireGeometry.PointsCoincide(pinPos, snapped, CoordinateEpsilon))
                    {
                        AddDistinctPoint(points, snapped);
                        continue;
                    }

                    if (FindCoincidentPin(elements, element, pinPos) != null)
                    {
                        AddDistinctPoint(points, pinPos);
                    }
                }
            }

            return points;
        }

        /// <summary>Bağlantı sonucuna göre durum çubuğu için kısa Türkçe ileti üretir; bağlantı yoksa null.</summary>
        public static string? FormatStatusMessage(WireDropResult? result)
        {
            if (result == null || !result.AnyConnected)
                return null;

            var distinctElements = result.Connections
                .Select(c => c.Element)
                .Distinct()
                .ToList();

            if (distinctElements.Count == 1)
            {
                var el = distinctElements[0];
                var events = result.Connections.Where(c => ReferenceEquals(c.Element, el)).ToList();

                if (events.Any(e => e.Kind == DropConnectionKind.SeriesInsert))
                    return $"{el.Id} tele seri eklendi";

                if (events.Any(e => e.Kind == DropConnectionKind.WireSplit || e.TargetElement is JunctionElement))
                    return $"{el.Id} tele bağlandı";

                var pinEvent = events.FirstOrDefault(e => e.Kind == DropConnectionKind.PinToPin && e.TargetElement != null);
                if (pinEvent != null && events.Count == 1)
                    return $"{el.Id} {pinEvent.TargetElement!.Id} ucuna bağlandı";

                return $"{el.Id} tele bağlandı";
            }

            string subject = distinctElements.Count <= 3
                ? string.Join(", ", distinctElements.Select(e => e.Id))
                : $"{distinctElements.Count} eleman";

            bool allSeries = result.Connections.All(c => c.Kind == DropConnectionKind.SeriesInsert);
            return allSeries
                ? $"{subject} tele seri eklendi"
                : $"{subject} tele bağlandı";
        }

        private static void ConnectSingleElement(
            IList<CircuitElement> elements,
            IList<Wire> wires,
            CircuitElement element,
            double wireTolerance,
            WireDropResult result)
        {
            // İki uçlu elemanın iki ucu da aynı düz tel parçasına oturduysa seri ekle (aradaki tel çıkarılır)
            if (TryFindSeriesCandidate(wires, element, out Wire? seriesWire, out Pin? nearPin, out Pin? farPin))
            {
                var (firstPart, rest) = WireGeometry.Split(seriesWire!, nearPin!);
                var (_, secondPart) = WireGeometry.Split(rest, farPin!);

                ReplaceWire(wires, result, seriesWire!, firstPart, secondPart);

                Point mid = new(
                    (nearPin!.AbsolutePosition.X + farPin!.AbsolutePosition.X) / 2.0,
                    (nearPin.AbsolutePosition.Y + farPin.AbsolutePosition.Y) / 2.0);
                result.Connections.Add(new DropConnectionEvent(element, DropConnectionKind.SeriesInsert, mid));
                return;
            }

            foreach (var pin in element.Pins)
            {
                if (IsPinConnected(wires, pin))
                    continue;

                Point pinPos = pin.AbsolutePosition;

                // Elemanın kendi tellerini dışla — kendi teline kısa devre yapmasın
                var candidateWires = wires
                    .Where(w => w?.StartPin != null && w.EndPin != null &&
                                w.StartPin.Owner != element && w.EndPin.Owner != element)
                    .ToList();

                // 1) Tel ortasına iniş: HitTestWire uç pinleri zaten atlar; yalnız ızgarada tel üstündeki uç bağlanır
                var wireHit = WireGeometry.HitTestWire(candidateWires, pinPos, wireTolerance);
                if (wireHit is var (hitWire, snapped) && WireGeometry.PointsCoincide(pinPos, snapped, CoordinateEpsilon))
                {
                    int nextJunctionNum = CircuitClipboard.GetMaxNumberForPrefix(elements.Select(e => e.Id), "J") + 1;
                    var junction = new JunctionElement
                    {
                        Id = $"J{nextJunctionNum}",
                        Position = snapped,
                    };
                    elements.Add(junction);
                    result.AddedJunctions.Add(junction);

                    var (first, second) = WireGeometry.Split(hitWire, junction);
                    var branch = new Wire(pin, junction.Pins[0]);

                    ReplaceWire(wires, result, hitWire, first, second, branch);
                    result.Connections.Add(new DropConnectionEvent(
                        element, DropConnectionKind.WireSplit, snapped, CreatedJunction: junction));
                    continue;
                }

                // 2) Başka bir elemanın (serbest veya tel ucu) pinine ya da mevcut bağlantı noktasına tam iniş
                Pin? targetPin = FindCoincidentPin(elements, element, pinPos);
                if (targetPin != null && !HasWireBetween(wires, pin, targetPin))
                {
                    var zeroWire = new Wire(pin, targetPin);
                    wires.Add(zeroWire);
                    result.AddedWires.Add(zeroWire);
                    result.Connections.Add(new DropConnectionEvent(
                        element, DropConnectionKind.PinToPin, pinPos, TargetElement: targetPin.Owner));
                }
            }
        }

        private static bool TryFindSeriesCandidate(
            IEnumerable<Wire> wires,
            CircuitElement element,
            out Wire? matchedWire,
            out Pin? nearPin,
            out Pin? farPin)
        {
            matchedWire = null;
            nearPin = null;
            farPin = null;

            if (element.Pins.Count != 2)
                return false;

            Pin p0 = element.Pins[0];
            Pin p1 = element.Pins[1];
            if (IsPinConnected(wires, p0) || IsPinConnected(wires, p1))
                return false;

            Point pos0 = p0.AbsolutePosition;
            Point pos1 = p1.AbsolutePosition;
            if (WireGeometry.PointsCoincide(pos0, pos1, CoordinateEpsilon))
                return false;

            foreach (var wire in wires)
            {
                if (wire?.StartPin == null || wire.EndPin == null)
                    continue;
                if (wire.StartPin.Owner == element || wire.EndPin.Owner == element)
                    continue;

                var route = WireGeometry.Route(wire);
                if (route.Count < 2)
                    continue;

                for (int i = 0; i < route.Count - 1; i++)
                {
                    Point a = route[i];
                    Point b = route[i + 1];
                    if (WireGeometry.PointsCoincide(a, b, CoordinateEpsilon))
                        continue;

                    if (IsPointOnAxisAlignedSegment(pos0, a, b) && IsPointOnAxisAlignedSegment(pos1, a, b))
                    {
                        double d0 = DistanceAlongSegment(a, pos0);
                        double d1 = DistanceAlongSegment(a, pos1);

                        matchedWire = wire;
                        if (d0 <= d1)
                        {
                            nearPin = p0;
                            farPin = p1;
                        }
                        else
                        {
                            nearPin = p1;
                            farPin = p0;
                        }
                        return true;
                    }
                }
            }

            return false;
        }

        private static bool IsPointOnAxisAlignedSegment(Point p, Point a, Point b)
        {
            bool horizontal = Math.Abs(a.Y - b.Y) <= CoordinateEpsilon;
            bool vertical = Math.Abs(a.X - b.X) <= CoordinateEpsilon;

            if (horizontal)
            {
                double minX = Math.Min(a.X, b.X) - CoordinateEpsilon;
                double maxX = Math.Max(a.X, b.X) + CoordinateEpsilon;
                return Math.Abs(p.Y - a.Y) <= CoordinateEpsilon && p.X >= minX && p.X <= maxX;
            }

            if (vertical)
            {
                double minY = Math.Min(a.Y, b.Y) - CoordinateEpsilon;
                double maxY = Math.Max(a.Y, b.Y) + CoordinateEpsilon;
                return Math.Abs(p.X - a.X) <= CoordinateEpsilon && p.Y >= minY && p.Y <= maxY;
            }

            return false;
        }

        private static double DistanceAlongSegment(Point segStart, Point p)
            => Math.Abs(p.X - segStart.X) + Math.Abs(p.Y - segStart.Y);

        private static bool IsPinConnected(IEnumerable<Wire> wires, Pin pin)
            => wires.Any(w => w != null && (w.StartPin == pin || w.EndPin == pin));

        private static bool HasWireBetween(IEnumerable<Wire> wires, Pin a, Pin b)
            => wires.Any(w => w != null &&
                              ((w.StartPin == a && w.EndPin == b) ||
                               (w.StartPin == b && w.EndPin == a)));

        private static Pin? FindCoincidentPin(
            IEnumerable<CircuitElement> elements,
            CircuitElement movingElement,
            Point pinPos)
        {
            Pin? fallback = null;

            foreach (var other in elements)
            {
                if (other == null || ReferenceEquals(other, movingElement))
                    continue;
                if (other is TestProbe { Type: ProbeType.Current })
                    continue;

                foreach (var otherPin in other.Pins)
                {
                    if (!WireGeometry.PointsCoincide(otherPin.AbsolutePosition, pinPos, CoordinateEpsilon))
                        continue;

                    // Aynı noktada zaten bir bağlantı noktası (J) varsa doğrudan ona bağlan: yeni J üretme
                    if (other is JunctionElement)
                        return otherPin;

                    fallback ??= otherPin;
                }
            }

            return fallback;
        }

        private static void ReplaceWire(IList<Wire> wires, WireDropResult result, Wire oldWire, params Wire[] newWires)
        {
            int idx = wires.IndexOf(oldWire);
            if (idx >= 0)
            {
                wires.RemoveAt(idx);
                for (int i = 0; i < newWires.Length; i++)
                {
                    wires.Insert(idx + i, newWires[i]);
                }
            }
            else
            {
                foreach (var nw in newWires)
                {
                    wires.Add(nw);
                }
            }

            if (!result.AddedWires.Remove(oldWire))
            {
                result.RemovedWires.Add(oldWire);
            }

            foreach (var nw in newWires)
            {
                result.AddedWires.Add(nw);
            }
        }

        private static void RefreshJunctionCounts(IEnumerable<CircuitElement> elements, IEnumerable<Wire> wires)
        {
            foreach (var j in elements.OfType<JunctionElement>())
            {
                var pin = j.Pins[0];
                j.AttachedWireCount = wires.Count(w => w.StartPin == pin || w.EndPin == pin);
            }
        }

        private static void AddDistinctPoint(List<Point> points, Point p)
        {
            if (!points.Any(existing => WireGeometry.PointsCoincide(existing, p, CoordinateEpsilon)))
            {
                points.Add(p);
            }
        }
    }
}
