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
            => Route(start, null, end, lastLegVerticalFirst: false);

        /// <summary>
        /// Başlangıç noktası, ara köşe noktaları (waypoints) ve bitiş noktası arasındaki
        /// 90° dik açılı (orthogonal) tel rotasını döndürür.
        /// Eksen hizalı olmayan her ardışık nokta çifti L-parçası olarak çizilir:
        /// başlangıçtan veya ara köşeler arasından çıkan kollar önce yatay gider;
        /// son kol ise <paramref name="lastLegVerticalFirst"/> değerine göre yönlendirilir.
        /// </summary>
        public static IReadOnlyList<Point> Route(
            Point start,
            IReadOnlyList<Point>? waypoints,
            Point end,
            bool lastLegVerticalFirst = false)
        {
            if (waypoints == null || waypoints.Count == 0)
            {
                return RouteSingleLeg(start, end, lastLegVerticalFirst);
            }

            var controlPoints = new List<Point>(waypoints.Count + 2) { start };
            for (int i = 0; i < waypoints.Count; i++)
            {
                controlPoints.Add(waypoints[i]);
            }
            controlPoints.Add(end);

            var result = new List<Point>(controlPoints.Count * 2) { start };
            int lastLegIndex = controlPoints.Count - 2;

            for (int k = 0; k <= lastLegIndex; k++)
            {
                Point a = result[^1];
                Point b = controlPoints[k + 1];
                bool vf = (k == lastLegIndex) && lastLegVerticalFirst;

                double dx = Math.Abs(a.X - b.X);
                double dy = Math.Abs(a.Y - b.Y);

                if (dx <= CoordinateEpsilon && dy <= CoordinateEpsilon)
                    continue;

                if (dx > CoordinateEpsilon && dy > CoordinateEpsilon)
                {
                    Point mid = vf ? new Point(a.X, b.Y) : new Point(b.X, a.Y);
                    if (!PointsCoincide(result[^1], mid))
                        result.Add(mid);
                }

                if (!PointsCoincide(result[^1], b))
                    result.Add(b);
            }

            return result;
        }

        /// <summary>
        /// Verilen telin (Waypoints ve LastLegVerticalFirst dahil) tam rotasını döndürür.
        /// </summary>
        public static IReadOnlyList<Point> Route(Wire wire)
        {
            ArgumentNullException.ThrowIfNull(wire);
            return Route(
                wire.StartPin.AbsolutePosition,
                wire.Waypoints,
                wire.EndPin.AbsolutePosition,
                wire.LastLegVerticalFirst);
        }

        /// <summary>
        /// L-şekilli kolun yönünü seçer: tel uçtan dışarı doğru çıkıp karşı uca dışarıdan
        /// girecek biçimde "dıştan" dönsün, elemanın içinden geçmesin. Eşitlikte ya da düz
        /// kolda <paramref name="fallback"/> kalır.
        /// </summary>
        public static bool PreferVerticalFirst(Point start, Vector? startOutward, Point end, Vector? endOutward, bool fallback)
        {
            double dx = end.X - start.X;
            double dy = end.Y - start.Y;
            if (Math.Abs(dx) <= CoordinateEpsilon || Math.Abs(dy) <= CoordinateEpsilon)
                return fallback;

            var horizontal = new Vector(Math.Sign(dx), 0);
            var vertical = new Vector(0, Math.Sign(dy));

            int horizontalFirst = LegScore(horizontal, vertical, startOutward, endOutward);
            int verticalFirst = LegScore(vertical, horizontal, startOutward, endOutward);
            return verticalFirst == horizontalFirst ? fallback : verticalFirst > horizontalFirst;
        }

        private static int LegScore(Vector firstLeg, Vector lastLeg, Vector? startOutward, Vector? endOutward)
        {
            int score = 0;
            if (startOutward is { } s)
                score += firstLeg == s ? 1 : firstLeg == -s ? -1 : 0;
            if (endOutward is { } e)
                score += lastLeg == -e ? 1 : lastLeg == e ? -1 : 0;
            return score;
        }

        private static IReadOnlyList<Point> RouteSingleLeg(Point start, Point end, bool verticalFirst)
        {
            double dx = Math.Abs(start.X - end.X);
            double dy = Math.Abs(start.Y - end.Y);

            // Başlangıç ve bitiş aynı noktadaysa tek nokta (0 segment)
            if (dx <= CoordinateEpsilon && dy <= CoordinateEpsilon)
            {
                return new[] { start };
            }

            // Hem X hem Y farklıysa L-köşesi ekle
            if (dx > CoordinateEpsilon && dy > CoordinateEpsilon)
            {
                var mid = verticalFirst ? new Point(start.X, end.Y) : new Point(end.X, start.Y);
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
                var route = Route(wire);
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
        /// Çok segmentli tellerde isabet noktası örtük bir L-kolu üzerindeyse önce L-köşesi somutlaştırılır;
        /// önceki ara köşeler ilk tele, kalan ara köşeler ikinci tele aktarılır ve son kol yönleri
        /// iki telin birleşik rotası eski rotayla birebir aynı olacak biçimde seçilir.
        /// </summary>
        public static (Wire First, Wire Second) Split(Wire w, Pin junctionPin)
        {
            ArgumentNullException.ThrowIfNull(w);
            ArgumentNullException.ThrowIfNull(junctionPin);

            Point start = w.StartPin.AbsolutePosition;
            Point end = w.EndPin.AbsolutePosition;
            Point j = junctionPin.AbsolutePosition;
            var expectedRoute = Route(w);

            var controlPoints = new List<Point>((w.Waypoints?.Count ?? 0) + 2) { start };
            if (w.Waypoints != null)
            {
                controlPoints.AddRange(w.Waypoints);
            }
            controlPoints.Add(end);

            int legCount = controlPoints.Count - 1;
            int bestLeg = 0;
            double bestDist = double.PositiveInfinity;

            for (int k = 0; k < legCount; k++)
            {
                Point a = controlPoints[k];
                Point b = controlPoints[k + 1];
                bool vf = (k == legCount - 1) && w.LastLegVerticalFirst;
                bool isL = Math.Abs(a.X - b.X) > CoordinateEpsilon && Math.Abs(a.Y - b.Y) > CoordinateEpsilon;

                double legDist;
                if (isL)
                {
                    Point corner = vf ? new Point(a.X, b.Y) : new Point(b.X, a.Y);
                    var (d1, _) = ProjectAndSnapOnSegment(j, a, corner);
                    var (d2, _) = ProjectAndSnapOnSegment(j, corner, b);
                    legDist = Math.Min(d1, d2);
                }
                else
                {
                    var (d, _) = ProjectAndSnapOnSegment(j, a, b);
                    legDist = d;
                }

                if (legDist < bestDist)
                {
                    bestDist = legDist;
                    bestLeg = k;
                }
            }

            var w1Waypoints = new List<Point>();
            for (int i = 1; i <= bestLeg; i++)
            {
                w1Waypoints.Add(controlPoints[i]);
            }

            var w2Waypoints = new List<Point>();
            for (int i = bestLeg + 1; i < controlPoints.Count - 1; i++)
            {
                w2Waypoints.Add(controlPoints[i]);
            }

            Point legStart = controlPoints[bestLeg];
            Point legEnd = controlPoints[bestLeg + 1];
            bool hitLegVf = (bestLeg == legCount - 1) && w.LastLegVerticalFirst;
            bool hitLegIsL = Math.Abs(legStart.X - legEnd.X) > CoordinateEpsilon &&
                             Math.Abs(legStart.Y - legEnd.Y) > CoordinateEpsilon;

            if (hitLegIsL)
            {
                Point corner = hitLegVf ? new Point(legStart.X, legEnd.Y) : new Point(legEnd.X, legStart.Y);
                if (!PointsCoincide(j, corner))
                {
                    var (d1, _) = ProjectAndSnapOnSegment(j, legStart, corner);
                    var (d2, _) = ProjectAndSnapOnSegment(j, corner, legEnd);
                    if (d1 <= d2)
                    {
                        w2Waypoints.Insert(0, corner);
                    }
                    else
                    {
                        w1Waypoints.Add(corner);
                    }
                }
            }

            while (w1Waypoints.Count > 0 && (PointsCoincide(w1Waypoints[^1], j) || PointsCoincide(w1Waypoints[^1], start)))
                w1Waypoints.RemoveAt(w1Waypoints.Count - 1);
            while (w1Waypoints.Count > 0 && PointsCoincide(w1Waypoints[0], start))
                w1Waypoints.RemoveAt(0);

            while (w2Waypoints.Count > 0 && (PointsCoincide(w2Waypoints[0], j) || PointsCoincide(w2Waypoints[0], end)))
                w2Waypoints.RemoveAt(0);
            while (w2Waypoints.Count > 0 && PointsCoincide(w2Waypoints[^1], end))
                w2Waypoints.RemoveAt(w2Waypoints.Count - 1);

            bool defaultVf1 = false;
            bool defaultVf2 = (bestLeg < legCount - 1) ? w.LastLegVerticalFirst : false;

            (bool vf1, bool vf2)[] candidates =
            {
                (defaultVf1, defaultVf2),
                (false, w.LastLegVerticalFirst),
                (true, defaultVf2),
                (defaultVf1, !defaultVf2),
                (true, true),
            };

            bool chosenVf1 = defaultVf1;
            bool chosenVf2 = defaultVf2;

            foreach (var (c1, c2) in candidates)
            {
                var r1 = Route(start, w1Waypoints, j, c1);
                var r2 = Route(j, w2Waypoints, end, c2);
                if (CombinedRouteMatches(r1, r2, expectedRoute))
                {
                    chosenVf1 = c1;
                    chosenVf2 = c2;
                    break;
                }
            }

            var first = new Wire(w.StartPin, junctionPin, w1Waypoints, chosenVf1);
            var second = new Wire(junctionPin, w.EndPin, w2Waypoints, chosenVf2);
            return (first, second);
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

                        Wire? merged;
                        if (w2.EndPin.Owner == junction && w1.StartPin.Owner == junction)
                        {
                            merged = TryBuildMergedWire(junction, far2, w2, far1, w1)
                                  ?? TryBuildMergedWire(junction, far1, w1, far2, w2);
                        }
                        else
                        {
                            merged = TryBuildMergedWire(junction, far1, w1, far2, w2)
                                  ?? TryBuildMergedWire(junction, far2, w2, far1, w1);
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

        private static Wire? TryBuildMergedWire(
            JunctionElement junction,
            Pin pinA,
            Wire wireA,
            Pin pinB,
            Wire wireB)
        {
            Point jPos = junction.Pins[0].AbsolutePosition;

            var rawA = Route(wireA);
            IReadOnlyList<Point> routeA = wireA.StartPin == pinA ? rawA : rawA.Reverse().ToList();

            var rawB = Route(wireB);
            IReadOnlyList<Point> routeB = wireB.StartPin.Owner == junction ? rawB : rawB.Reverse().ToList();

            Point prevInRoute = routeA.Count >= 2 ? routeA[^2] : pinA.AbsolutePosition;
            Point nextInRoute = routeB.Count >= 2 ? routeB[1] : pinB.AbsolutePosition;

            // J noktasında 180° geri dönüş (hairpin) varsa birleştirme
            bool sameLineHoriz = Math.Abs(prevInRoute.Y - jPos.Y) <= CoordinateEpsilon &&
                                 Math.Abs(jPos.Y - nextInRoute.Y) <= CoordinateEpsilon;
            bool sameLineVert = Math.Abs(prevInRoute.X - jPos.X) <= CoordinateEpsilon &&
                                Math.Abs(jPos.X - nextInRoute.X) <= CoordinateEpsilon;
            bool collinearAtJ = AreCollinearInOrder(prevInRoute, jPos, nextInRoute);

            if ((sameLineHoriz || sameLineVert) && !collinearAtJ)
                return null;

            var aWaypoints = wireA.StartPin == pinA
                ? new List<Point>(wireA.Waypoints)
                : wireA.Waypoints.AsEnumerable().Reverse().ToList();

            // A-tarafı telde örtük bir L-köşesi varsa birleşik telde kaybolmaması için somutlaştır
            if (routeA.Count > aWaypoints.Count + 2)
            {
                aWaypoints = routeA.Skip(1).Take(routeA.Count - 2).ToList();
            }

            var bWaypoints = wireB.StartPin.Owner == junction
                ? new List<Point>(wireB.Waypoints)
                : wireB.Waypoints.AsEnumerable().Reverse().ToList();

            bool bForward = wireB.StartPin.Owner == junction;
            bool preferredVf = bForward ? wireB.LastLegVerticalFirst : !wireB.LastLegVerticalFirst;

            var candidateWps = new List<Point>(aWaypoints.Count + bWaypoints.Count + 1);
            candidateWps.AddRange(aWaypoints);
            if (!collinearAtJ &&
                !PointsCoincide(jPos, pinA.AbsolutePosition) &&
                !PointsCoincide(jPos, pinB.AbsolutePosition))
            {
                candidateWps.Add(jPos);
            }
            candidateWps.AddRange(bWaypoints);

            bool[] vfCandidates = { preferredVf, !preferredVf };
            foreach (bool vf in vfCandidates)
            {
                var candidateRoute = Route(pinA.AbsolutePosition, candidateWps, pinB.AbsolutePosition, vf);
                if (CombinedRouteMatches(routeA, routeB, candidateRoute))
                {
                    return new Wire(pinA, pinB, candidateWps, vf);
                }
            }

            // B-tarafı telde örtük L-köşesi varsa onu da somutlaştırarak dene
            if (routeB.Count > bWaypoints.Count + 2)
            {
                var bExplicit = routeB.Skip(1).Take(routeB.Count - 2).ToList();
                var explicitWps = new List<Point>(aWaypoints);
                if (!collinearAtJ &&
                    !PointsCoincide(jPos, pinA.AbsolutePosition) &&
                    !PointsCoincide(jPos, pinB.AbsolutePosition))
                {
                    explicitWps.Add(jPos);
                }
                explicitWps.AddRange(bExplicit);

                foreach (bool vf in vfCandidates)
                {
                    var candidateRoute = Route(pinA.AbsolutePosition, explicitWps, pinB.AbsolutePosition, vf);
                    if (CombinedRouteMatches(routeA, routeB, candidateRoute))
                    {
                        return new Wire(pinA, pinB, explicitWps, vf);
                    }
                }
            }

            return null;
        }

        private static bool AreCollinearInOrder(Point a, Point b, Point c)
        {
            bool sameHorizontal = Math.Abs(a.Y - b.Y) <= CoordinateEpsilon &&
                                  Math.Abs(b.Y - c.Y) <= CoordinateEpsilon &&
                                  ((a.X <= b.X + CoordinateEpsilon && b.X <= c.X + CoordinateEpsilon) ||
                                   (a.X >= b.X - CoordinateEpsilon && b.X >= c.X - CoordinateEpsilon));

            bool sameVertical = Math.Abs(a.X - b.X) <= CoordinateEpsilon &&
                                Math.Abs(b.X - c.X) <= CoordinateEpsilon &&
                                ((a.Y <= b.Y + CoordinateEpsilon && b.Y <= c.Y + CoordinateEpsilon) ||
                                 (a.Y >= b.Y - CoordinateEpsilon && b.Y >= c.Y - CoordinateEpsilon));

            return sameHorizontal || sameVertical;
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
