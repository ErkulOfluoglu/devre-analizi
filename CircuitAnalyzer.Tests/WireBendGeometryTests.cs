using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using CircuitAnalyzer.WPF.Helpers;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Manuel tel köşeleri (Waypoints + LastLegVerticalFirst) geometri, bölme/birleştirme,
/// belge kaydetme/yükleme ve pano kopyala/yapıştır birim testleri.
/// </summary>
public class WireBendGeometryTests
{
    private static void AssertAllSegmentsAxisAligned(IReadOnlyList<Point> poly)
    {
        Assert.True(poly.Count >= 2);
        for (int i = 0; i < poly.Count - 1; i++)
        {
            Point a = poly[i];
            Point b = poly[i + 1];
            bool horizontal = Math.Abs(a.Y - b.Y) < 1e-6;
            bool vertical = Math.Abs(a.X - b.X) < 1e-6;
            Assert.True(horizontal || vertical, $"Segment {i} ({a} -> {b}) eksene paralel değil.");
        }
    }

    /// <summary>
    /// Bir poligondaki doğrusal (collinear) ara noktaları sadeleştirerek kanonik köşe listesini döndürür.
    /// İki rotanın geometrik olarak birebir aynı doğru parçalarından oluştuğunu doğrulamak için kullanılır.
    /// </summary>
    private static List<Point> NormalizePolyline(IEnumerable<Point> points)
    {
        var result = new List<Point>();
        foreach (var pt in points)
        {
            if (result.Count > 0 && (result[^1] - pt).Length < 1e-6)
                continue;

            if (result.Count >= 2)
            {
                Point prev2 = result[^2];
                Point prev1 = result[^1];
                bool sameX = Math.Abs(prev2.X - prev1.X) < 1e-6 && Math.Abs(prev1.X - pt.X) < 1e-6;
                bool sameY = Math.Abs(prev2.Y - prev1.Y) < 1e-6 && Math.Abs(prev1.Y - pt.Y) < 1e-6;
                if (sameX || sameY)
                {
                    result[^1] = pt;
                    continue;
                }
            }

            result.Add(pt);
        }
        return result;
    }

    [Fact]
    public void Route_NoWaypoints_MatchesLegacyHorizontalFirstAndFlipsWithLastLegVerticalFirst()
    {
        Point start = new(100, 120);
        Point end = new(260, 240);

        var legacy = WireGeometry.Route(start, end);
        var noWpDefault = WireGeometry.Route(start, Array.Empty<Point>(), end, lastLegVerticalFirst: false);
        var noWpNull = WireGeometry.Route(start, null, end, lastLegVerticalFirst: false);
        var noWpVertical = WireGeometry.Route(start, Array.Empty<Point>(), end, lastLegVerticalFirst: true);

        Assert.Equal(legacy, noWpDefault);
        Assert.Equal(legacy, noWpNull);
        Assert.Equal(new[] { start, new Point(260, 120), end }, noWpDefault);
        Assert.Equal(new[] { start, new Point(100, 240), end }, noWpVertical);

        AssertAllSegmentsAxisAligned(noWpDefault);
        AssertAllSegmentsAxisAligned(noWpVertical);
    }

    [Fact]
    public void Route_WithWaypoints_AllSegmentsAxisAligned_AndLastLegVerticalFirstFlipsOnlyFinalCorner()
    {
        Point start = new(100, 100);
        var waypoints = new List<Point>
        {
            new(180, 100),
            new(180, 60),
            new(320, 140), // Önceki noktayla çapraz -> yatay-önce ara L köşesi (320, 60) üretmeli
        };
        Point end = new(420, 220); // Son ayak çapraz

        var routeHorizLast = WireGeometry.Route(start, waypoints, end, lastLegVerticalFirst: false);
        var routeVertLast = WireGeometry.Route(start, waypoints, end, lastLegVerticalFirst: true);

        AssertAllSegmentsAxisAligned(routeHorizLast);
        AssertAllSegmentsAxisAligned(routeVertLast);

        // İlk bacaklar her iki durumda da aynı olmalı; yalnızca son köşe (420,140) <-> (320,220) değişmeli
        Assert.Equal(
            new[]
            {
                new Point(100, 100),
                new Point(180, 100),
                new Point(180, 60),
                new Point(320, 60),
                new Point(320, 140),
                new Point(420, 140),
                new Point(420, 220),
            },
            routeHorizLast);

        Assert.Equal(
            new[]
            {
                new Point(100, 100),
                new Point(180, 100),
                new Point(180, 60),
                new Point(320, 60),
                new Point(320, 140),
                new Point(320, 220),
                new Point(420, 220),
            },
            routeVertLast);
    }

    [Fact]
    public void HitTestWire_DetectsPointsOnEverySegmentIncludingImplicitCorners()
    {
        var r1 = new Resistor { Id = "R1", Position = new Point(100, 100) }; // Pin1 = (180, 120)
        var r2 = new Resistor { Id = "R2", Position = new Point(400, 220) }; // Pin0 = (400, 240)

        // (180,120) -> wp1(240,60) [örtük köşe (240,120)] -> wp2(340,60) -> end(400,240) [dikey-önce örtük köşe (340,240)]
        var wire = new Wire(
            r1.Pins[1],
            r2.Pins[0],
            new[] { new Point(240, 60), new Point(340, 60) },
            lastLegVerticalFirst: true);

        var poly = WireGeometry.Route(wire);
        Assert.Equal(
            new[]
            {
                new Point(180, 120),
                new Point(240, 120),
                new Point(240, 60),
                new Point(340, 60),
                new Point(340, 240),
                new Point(400, 240),
            },
            poly);

        var wires = new[] { wire };

        // Her doğru parçasının orta noktası ve örtük köşeler yakalanmalı
        for (int i = 0; i < poly.Count - 1; i++)
        {
            Point mid = new((poly[i].X + poly[i + 1].X) / 2.0, (poly[i].Y + poly[i + 1].Y) / 2.0);
            var hit = WireGeometry.HitTestWire(wires, mid, tolerance: 6.0);
            Assert.NotNull(hit);
            Assert.Same(wire, hit!.Value.wire);
        }

        // Örtük köşelerin tam üstü (pinlerden uzakta)
        Assert.NotNull(WireGeometry.HitTestWire(wires, new Point(240, 120), tolerance: 6.0));
        Assert.NotNull(WireGeometry.HitTestWire(wires, new Point(340, 240), tolerance: 6.0));

        // SelectionModel.HitTest de her iki ucu seçim kutusunda olan çok segmentli teli seçmeli
        var inBox = SelectionModel.HitTest(
            new Rect(new Point(80, 40), new Point(500, 280)),
            new CircuitElement[] { r1, r2 },
            wires);
        Assert.Single(inBox.Wires);
        Assert.Same(wire, inBox.Wires[0]);
    }

    [Fact]
    public void Split_And_CleanupJunctions_PreserveExactRouteAcrossRandomMultiSegmentWires()
    {
        var rng = new Random(20261026);

        for (int trial = 0; trial < 30; trial++)
        {
            Point startPos = new(rng.Next(2, 8) * 20, rng.Next(2, 8) * 20);
            Point endPos = new(rng.Next(18, 26) * 20, rng.Next(14, 22) * 20);

            var rStart = new Resistor { Id = "R1", Position = new Point(startPos.X - 80, startPos.Y - 20) };
            var rEnd = new Resistor { Id = "R2", Position = new Point(endPos.X, endPos.Y - 20) };

            int wpCount = rng.Next(1, 5);
            var waypoints = new List<Point>();
            Point prev = rStart.Pins[1].AbsolutePosition;
            for (int k = 0; k < wpCount; k++)
            {
                Point next = new(rng.Next(4, 24) * 20, rng.Next(3, 20) * 20);
                if ((next - prev).Length < 40)
                    next = new Point(prev.X + 60, prev.Y + 40);
                waypoints.Add(next);
                prev = next;
            }

            bool lastVert = rng.Next(2) == 1;
            var originalWire = new Wire(rStart.Pins[1], rEnd.Pins[0], waypoints, lastVert);
            var originalPoly = WireGeometry.Route(originalWire);
            var normalizedOriginal = NormalizePolyline(originalPoly);

            // Poligonun her segmenti üzerinde bir iç nokta seçip Split ve ardından CleanupJunctions testi yap
            for (int seg = 0; seg < originalPoly.Count - 1; seg++)
            {
                Point a = originalPoly[seg];
                Point b = originalPoly[seg + 1];
                if ((b - a).Length < 40)
                    continue;

                Point splitPt = GridHelper.Snap(new Point((a.X + b.X) / 2.0, (a.Y + b.Y) / 2.0));
                if ((splitPt - a).Length < 1e-6 || (splitPt - b).Length < 1e-6)
                    continue;

                // Kendi kendine kesişen (self-intersecting) rastgele tellerde splitPt daha önceki bir segmente de
                // denk gelebilir; Split ilk eşleşen segmentten böldüğü için test noktasının ilk kez bu segmentte
                // geçtiğinden emin olalım.
                int firstHitSeg = -1;
                for (int check = 0; check < originalPoly.Count - 1; check++)
                {
                    Point ca = originalPoly[check];
                    Point cb = originalPoly[check + 1];
                    bool onSeg =
                        splitPt.X >= Math.Min(ca.X, cb.X) - 1e-4 &&
                        splitPt.X <= Math.Max(ca.X, cb.X) + 1e-4 &&
                        splitPt.Y >= Math.Min(ca.Y, cb.Y) - 1e-4 &&
                        splitPt.Y <= Math.Max(ca.Y, cb.Y) + 1e-4 &&
                        (Math.Abs(ca.X - cb.X) < 1e-4 || Math.Abs(ca.Y - cb.Y) < 1e-4);
                    if (onSeg)
                    {
                        firstHitSeg = check;
                        break;
                    }
                }
                if (firstHitSeg != seg)
                    continue;

                var j = new JunctionElement { Id = "J1", Position = splitPt };
                var (w1, w2) = WireGeometry.Split(originalWire, j.Pins[0]);

                var route1 = WireGeometry.Route(w1);
                var route2 = WireGeometry.Route(w2);
                AssertAllSegmentsAxisAligned(route1);
                AssertAllSegmentsAxisAligned(route2);

                var combined = NormalizePolyline(route1.Concat(route2.Skip(1)));
                Assert.Equal(normalizedOriginal, combined);

                // Şimdi yalnızca bu 2 tel varken CleanupJunctions çağrıldığında J1 kalkmalı ve rota korunmalı
                var elements = new List<CircuitElement> { rStart, rEnd, j };
                var wires = new List<Wire> { w1, w2 };
                WireGeometry.CleanupJunctions(elements, wires);

                Assert.DoesNotContain(j, elements);
                var merged = Assert.Single(wires);
                var mergedRoute = NormalizePolyline(WireGeometry.Route(merged));
                Assert.Equal(normalizedOriginal, mergedRoute);
            }
        }
    }

    [Fact]
    public void CircuitDocument_RoundTripPreservesPointsAndVerticalFirst_AndOldFormatLoadsUnchanged()
    {
        var r1 = new Resistor { Id = "R1", Value = 100, Position = new Point(100, 100) };
        var r2 = new Resistor { Id = "R2", Value = 200, Position = new Point(360, 200) };
        var bentWire = new Wire(
            r1.Pins[1],
            r2.Pins[0],
            new[] { new Point(220, 120), new Point(220, 60), new Point(320, 60) },
            lastLegVerticalFirst: true);

        var doc = CircuitDocument.FromCircuit(new CircuitElement[] { r1, r2 }, new[] { bentWire });
        string json = doc.ToJson();

        Assert.Contains("\"points\"", json);
        Assert.Contains("\"vertical_first\": true", json);

        var restored = CircuitDocument.FromJson(json).ToCircuit("Restored");
        var rw = Assert.Single(restored.Wires);
        Assert.Equal(bentWire.Waypoints, rw.Waypoints);
        Assert.True(rw.LastLegVerticalFirst);
        Assert.Equal(WireGeometry.Route(bentWire), WireGeometry.Route(rw));

        // Eski format JSON (points ve vertical_first alanları yok) sorunsuz yüklenmeli
        const string oldJson = """
        {
          "version": 1,
          "elements": [
            { "id": "R1", "type": "R", "x": 100, "y": 100, "rotation": 0, "value": 100 },
            { "id": "R2", "type": "R", "x": 360, "y": 200, "rotation": 0, "value": 200 }
          ],
          "wires": [
            { "from": "R1", "from_pin": 1, "to": "R2", "to_pin": 0 }
          ]
        }
        """;

        var oldLoaded = CircuitDocument.FromJson(oldJson).ToCircuit("Old");
        var oldWire = Assert.Single(oldLoaded.Wires);
        Assert.Empty(oldWire.Waypoints);
        Assert.False(oldWire.LastLegVerticalFirst);
        Assert.Equal(
            WireGeometry.Route(oldWire.StartPin.AbsolutePosition, oldWire.EndPin.AbsolutePosition),
            WireGeometry.Route(oldWire));
    }

    [Fact]
    public void CircuitClipboard_CopyAndPaste_ShiftsAndSnapsWaypointsAndPreservesLastLegOrientation()
    {
        var r1 = new Resistor { Id = "R1", Value = 100, Position = new Point(100, 100) };
        var r2 = new Resistor { Id = "R2", Value = 200, Position = new Point(300, 180) };
        var wire = new Wire(
            r1.Pins[1],
            r2.Pins[0],
            new[] { new Point(200, 120), new Point(200, 60), new Point(280, 60) },
            lastLegVerticalFirst: true);

        string payload = CircuitClipboard.Copy(new CircuitElement[] { r1, r2 }, new[] { wire });
        var pasted = CircuitClipboard.Paste(payload, new[] { "R1", "R2" }, new Point(40, 60));

        var pastedWire = Assert.Single(pasted.Wires);
        Assert.True(pastedWire.LastLegVerticalFirst);
        Assert.Equal(
            new[] { new Point(240, 180), new Point(240, 120), new Point(320, 120) },
            pastedWire.Waypoints);
    }
}
