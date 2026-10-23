using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using CircuitAnalyzer.WPF.Helpers;
using CircuitAnalyzer.WPF.Models;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Tel yönlendirme (L-biçimi), tel yakalama (hit-test), tel bölme (split)
    /// ve bağlantı noktası temizleme (cleanup) işlemlerini barındıran saf geometri/topoloji sınıfı.
    /// WPF görsel nesnelerine bağımlı değildir; birim testlerde doğrudan çalıştırılabilir.
    /// </summary>
    public static class WireGeometry
    {
        private const double CoordinateEpsilon = 0.5;

        /// <summary>
        /// İki nokta arasındaki L-şekilli (önce yatay, sonra dikey) tel rotasını döndürür.
        /// Dejenere (sıfır uzunluklu) segmentler atlanır.
        /// </summary>
        public static IReadOnlyList<Point> Route(Point start, Point end)
        {
            double dx = Math.Abs(start.X - end.X);
            double dy = Math.Abs(start.Y - end.Y);

            // Başlangıç ve bitiş aynı noktadaysa tek nokta (0 segment)
            if (dx <= CoordinateEpsilon && dy <= CoordinateEpsilon)
            {
                return new[] { start };
            }

            // Hem X hem Y farklıysa L-köşesi ekle: önce yatay, sonra dikey
            if (dx > CoordinateEpsilon && dy > CoordinateEpsilon)
            {
                var mid = new Point(end.X, start.Y);
                return new[] { start, mid, end };
            }

            // Yalnızca yatay veya yalnızca dikey düz çizgi
            return new[] { start, end };
        }

        /// <summary>
        /// Verilen noktanın `tolerance` mesafesinden geçen en yakın teli ve o telin
        /// segmenti üzerinde ızgaraya yuvarlanmış (snapped) izdüşüm noktasını bulur.
        /// Yakalanan nokta telin uç pinlerinden biriyle çakışıyorsa null döner.
        /// </summary>
        public static (Wire wire, Point snapped)? HitTestWire(
            IEnumerable<Wire> wires,
            Point p,
            double tolerance)
        {
            if (wires == null || tolerance < 0)
                return null;

            Wire? bestWire = null;
            Point bestSnapped = default;
            double bestDist = double.PositiveInfinity;

            foreach (var wire in wires)
            {
                if (wire?.StartPin == null || wire.EndPin == null)
                    continue;

                Point start = wire.StartPin.AbsolutePosition;
                Point end = wire.EndPin.AbsolutePosition;
                var route = Route(start, end);
                if (route.Count < 2)
                    continue;

                double wireBestDist = double.PositiveInfinity;
                Point wireBestSnapped = default;
                bool wireHit = false;

                for (int i = 0; i < route.Count - 1; i++)
                {
                    Point a = route[i];
                    Point b = route[i + 1];

                    var (dist, snapped) = ProjectAndSnapOnSegment(p, a, b);
                    if (dist <= tolerance && dist < wireBestDist)
                    {
                        wireBestDist = dist;
                        wireBestSnapped = snapped;
                        wireHit = true;
                    }
                }

                if (wireHit && wireBestDist < bestDist)
                {
                    // Yakalanan nokta telin başlangıç veya bitiş piniyle çakışıyorsa pin mantığı devralır
                    if (PointsCoincide(wireBestSnapped, start) || PointsCoincide(wireBestSnapped, end))
                        continue;

                    bestDist = wireBestDist;
                    bestWire = wire;
                    bestSnapped = wireBestSnapped;
                }
            }

            if (bestWire == null)
                return null;

            return (bestWire, bestSnapped);
        }

        /// <summary>
        /// Bir teli verilen `j` noktasında yeni bir bağlantı noktası (JunctionElement) ile
        /// iki tele böler: (w.StartPin → J, J → w.EndPin).
        /// </summary>
        public static (Wire First, Wire Second) Split(Wire w, Point j)
        {
            ArgumentNullException.ThrowIfNull(w);
            var junction = new JunctionElement { Position = j };
            return Split(w, junction.Pins[0]);
        }

        /// <summary>
        /// Bir teli verilen `junction` elemanı üzerinden iki tele böler: (w.StartPin → J, J → w.EndPin).
        /// </summary>
        public static (Wire First, Wire Second) Split(Wire w, JunctionElement junction)
        {
            ArgumentNullException.ThrowIfNull(w);
            ArgumentNullException.ThrowIfNull(junction);
            return Split(w, junction.Pins[0]);
        }

        /// <summary>
        /// Bir teli verilen `junctionPin` üzerinden iki tele böler: (w.StartPin → junctionPin, junctionPin → w.EndPin).
        /// </summary>
        public static (Wire First, Wire Second) Split(Wire w, Pin junctionPin)
        {
            ArgumentNullException.ThrowIfNull(w);
            ArgumentNullException.ThrowIfNull(junctionPin);
            return (new Wire(w.StartPin, junctionPin), new Wire(junctionPin, w.EndPin));
        }

        /// <summary>
        /// İki ardışık tel rotasının (ilk rota + ikinci rota) birleşiminin, doğrusal ara noktalar
        /// sadeleştirildiğinde verilen referans rotayla birebir aynı yolu izleyip izlemediğini denetler.
        /// </summary>
        public static bool CombinedRouteMatches(
            IReadOnlyList<Point> firstRoute,
            IReadOnlyList<Point> secondRoute,
            IReadOnlyList<Point> expectedRoute)
        {
            var combined = CombineAndSimplify(firstRoute, secondRoute);
            var expected = SimplifyRoute(expectedRoute);

            if (combined.Count != expected.Count)
                return false;

            for (int i = 0; i < combined.Count; i++)
            {
                if (!PointsCoincide(combined[i], expected[i]))
                    return false;
            }
            return true;
        }

        /// <summary>
        /// İki ardışık rotayı uç uca ekler ve aynı doğrultudaki ara noktaları sadeleştirir.
        /// </summary>
        public static IReadOnlyList<Point> CombineAndSimplify(
            IReadOnlyList<Point> firstRoute,
            IReadOnlyList<Point> secondRoute)
        {
            var pts = new List<Point>(firstRoute.Count + secondRoute.Count);
            pts.AddRange(firstRoute);
            pts.AddRange(secondRoute);
            return SimplifyRoute(pts);
        }

        /// <summary>
        /// Bir rota üzerindeki ardışık çakışık noktaları ve aynı yöndeki doğrusal ara noktaları kaldırır.
        /// </summary>
        public static IReadOnlyList<Point> SimplifyRoute(IReadOnlyList<Point> route)
        {
            if (route == null || route.Count == 0)
                return Array.Empty<Point>();

            var result = new List<Point> { route[0] };
            for (int i = 1; i < route.Count; i++)
            {
                if (!PointsCoincide(route[i], result[^1]))
                {
                    result.Add(route[i]);
                }
            }

            int idx = 1;
            while (idx < result.Count - 1)
            {
                Point a = result[idx - 1];
                Point b = result[idx];
                Point c = result[idx + 1];

                bool sameHorizontal = Math.Abs(a.Y - b.Y) <= CoordinateEpsilon &&
                                      Math.Abs(b.Y - c.Y) <= CoordinateEpsilon &&
                                      ((a.X <= b.X + CoordinateEpsilon && b.X <= c.X + CoordinateEpsilon) ||
                                       (a.X >= b.X - CoordinateEpsilon && b.X >= c.X - CoordinateEpsilon));

                bool sameVertical = Math.Abs(a.X - b.X) <= CoordinateEpsilon &&
                                    Math.Abs(b.X - c.X) <= CoordinateEpsilon &&
                                    ((a.Y <= b.Y + CoordinateEpsilon && b.Y <= c.Y + CoordinateEpsilon) ||
                                     (a.Y >= b.Y - CoordinateEpsilon && b.Y >= c.Y - CoordinateEpsilon));

                if (sameHorizontal || sameVertical)
                {
                    result.RemoveAt(idx);
                }
                else
                {
                    idx++;
                }
            }

            return result;
        }

        /// <summary>
        /// Verilen `p` noktasının `route` üzerindeki herhangi bir segmentin üzerinde olup olmadığını denetler.
        /// </summary>
        public static bool IsPointOnRoute(Point p, IReadOnlyList<Point> route, double tolerance = CoordinateEpsilon)
        {
            if (route == null || route.Count == 0)
                return false;

            if (route.Count == 1)
                return PointsCoincide(p, route[0], tolerance);

            for (int i = 0; i < route.Count - 1; i++)
            {
                Point a = route[i];
                Point b = route[i + 1];
                double minX = Math.Min(a.X, b.X) - tolerance;
                double maxX = Math.Max(a.X, b.X) + tolerance;
                double minY = Math.Min(a.Y, b.Y) - tolerance;
                double maxY = Math.Max(a.Y, b.Y) + tolerance;

                if (Math.Abs(a.Y - b.Y) <= CoordinateEpsilon)
                {
                    if (Math.Abs(p.Y - a.Y) <= tolerance && p.X >= minX && p.X <= maxX)
                        return true;
                }
                else if (Math.Abs(a.X - b.X) <= CoordinateEpsilon)
                {
                    if (Math.Abs(p.X - a.X) <= tolerance && p.Y >= minY && p.Y <= maxY)
                        return true;
                }
            }

            return false;
        }

        /// <summary>
        /// Tel silme işlemlerinden sonra bağlantı noktalarını (JunctionElement) temizler:
        /// - 0 veya 1 teli kalan bağlantı noktaları kaldırılır (1 teli varsa o boşta kalan tel de silinir).
        /// - Tam 2 teli kalan bağlantı noktası, konumu yeni A→B L-rotası üzerindeyse tek bir A→B
        ///   teliyle birleştirilir ve bağlantı noktası kaldırılır; aksi halde korunur (görünmez).
        /// </summary>
        public static (List<JunctionElement> RemovedJunctions, List<Wire> RemovedWires, List<Wire> AddedWires)
            CleanupJunctions(IList<CircuitElement> elements, IList<Wire> wires)
        {
            ArgumentNullException.ThrowIfNull(elements);
            ArgumentNullException.ThrowIfNull(wires);

            var removedJunctions = new List<JunctionElement>();
            var removedWires = new List<Wire>();
            var addedWires = new List<Wire>();

            void RemoveWireTrack(Wire w)
            {
                wires.Remove(w);
                if (!addedWires.Remove(w))
                {
                    removedWires.Add(w);
                }
            }

            bool changed = true;
            while (changed)
            {
                changed = false;
                var junctions = elements.OfType<JunctionElement>().ToList();

                foreach (var junction in junctions)
                {
                    var attached = wires
                        .Where(w => w.StartPin.Owner == junction || w.EndPin.Owner == junction)
                        .ToList();

                    if (attached.Count == 0)
                    {
                        elements.Remove(junction);
                        removedJunctions.Add(junction);
                        changed = true;
                        break;
                    }

                    if (attached.Count == 1)
                    {
                        RemoveWireTrack(attached[0]);
                        elements.Remove(junction);
                        removedJunctions.Add(junction);
                        changed = true;
                        break;
                    }

                    if (attached.Count == 2)
                    {
                        var w1 = attached[0];
                        var w2 = attached[1];

                        Pin far1 = w1.StartPin.Owner == junction ? w1.EndPin : w1.StartPin;
                        Pin far2 = w2.StartPin.Owner == junction ? w2.EndPin : w2.StartPin;

                        if (far1 == far2 || far1.Owner == junction || far2.Owner == junction)
                            continue;

                        // Orijinal yönü tercih et: w1 J'de bitiyor ve w2 J'den başlıyorsa far1 -> far2
                        Pin candidateA = far1;
                        Pin candidateB = far2;
                        if (w2.EndPin.Owner == junction && w1.StartPin.Owner == junction)
                        {
                            candidateA = far2;
                            candidateB = far1;
                        }

                        Point jPos = junction.Pins[0].AbsolutePosition;
                        var routeAB = Route(candidateA.AbsolutePosition, candidateB.AbsolutePosition);
                        var routeBA = Route(candidateB.AbsolutePosition, candidateA.AbsolutePosition);

                        Wire? merged = null;
                        if (IsPointOnRoute(jPos, routeAB))
                        {
                            merged = new Wire(candidateA, candidateB);
                        }
                        else if (IsPointOnRoute(jPos, routeBA))
                        {
                            merged = new Wire(candidateB, candidateA);
                        }

                        if (merged != null)
                        {
                            RemoveWireTrack(w1);
                            RemoveWireTrack(w2);
                            elements.Remove(junction);
                            removedJunctions.Add(junction);

                            wires.Add(merged);
                            addedWires.Add(merged);
                            changed = true;
                            break;
                        }
                    }
                }
            }

            // Kalan bağlantı noktalarının tel sayılarını güncelle
            foreach (var j in elements.OfType<JunctionElement>())
            {
                j.AttachedWireCount = wires.Count(w => w.StartPin.Owner == j || w.EndPin.Owner == j);
            }

            return (removedJunctions, removedWires, addedWires);
        }

        private static (double dist, Point snapped) ProjectAndSnapOnSegment(Point p, Point a, Point b)
        {
            bool isHorizontal = Math.Abs(a.Y - b.Y) <= Math.Abs(a.X - b.X);
            if (isHorizontal)
            {
                double minX = Math.Min(a.X, b.X);
                double maxX = Math.Max(a.X, b.X);
                double segY = a.Y;

                double projX = Math.Clamp(p.X, minX, maxX);
                double dx = p.X - projX;
                double dy = p.Y - segY;
                double dist = Math.Sqrt(dx * dx + dy * dy);

                double snappedX = Math.Clamp(GridHelper.Snap(projX), minX, maxX);
                return (dist, new Point(snappedX, segY));
            }
            else
            {
                double minY = Math.Min(a.Y, b.Y);
                double maxY = Math.Max(a.Y, b.Y);
                double segX = a.X;

                double projY = Math.Clamp(p.Y, minY, maxY);
                double dx = p.X - segX;
                double dy = p.Y - projY;
                double dist = Math.Sqrt(dx * dx + dy * dy);

                double snappedY = Math.Clamp(GridHelper.Snap(projY), minY, maxY);
                return (dist, new Point(segX, snappedY));
            }
        }

        public static bool PointsCoincide(Point a, Point b, double tolerance = CoordinateEpsilon)
        {
            return Math.Abs(a.X - b.X) <= tolerance && Math.Abs(a.Y - b.Y) <= tolerance;
        }
    }
}
