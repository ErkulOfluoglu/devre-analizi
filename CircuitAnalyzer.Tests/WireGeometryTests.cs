using System;
using System.Collections.Generic;
using System.Windows;
using CircuitAnalyzer.WPF.Helpers;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests
{
    /// <summary>
    /// WireGeometry saf geometri ve topoloji sınıfının birim testleri:
    /// L-yönlendirme (Route), tel yakalama ve eksen boyunca ızgaraya oturtma (HitTestWire)
    /// ve tel bölme (Split) işlemlerinin doğrulanması.
    /// </summary>
    public class WireGeometryTests
    {
        private static Pin MakePinAt(double x, double y, string ownerId = "R1", int pinId = 0)
        {
            _ = pinId;
            var j = new JunctionElement { Id = ownerId, Position = new Point(x, y) };
            return j.Pins[0];
        }

        private static Wire MakeWire(double x1, double y1, double x2, double y2)
        {
            return new Wire(MakePinAt(x1, y1, "A", 0), MakePinAt(x2, y2, "B", 0));
        }

        [Fact]
        public void Route_HorizontalFirstL_ReturnsThreePointsWithCornerAtEndXStartY()
        {
            var start = new Point(100, 120);
            var end = new Point(260, 240);

            var route = WireGeometry.Route(start, end);

            Assert.Equal(3, route.Count);
            Assert.Equal(start, route[0]);
            Assert.Equal(new Point(260, 120), route[1]);
            Assert.Equal(end, route[2]);
        }

        [Fact]
        public void Route_StraightHorizontalAndVertical_SkipsDegenerateCorner()
        {
            var horiz = WireGeometry.Route(new Point(100, 120), new Point(300, 120));
            Assert.Equal(2, horiz.Count);
            Assert.Equal(new Point(100, 120), horiz[0]);
            Assert.Equal(new Point(300, 120), horiz[1]);

            var vert = WireGeometry.Route(new Point(140, 80), new Point(140, 260));
            Assert.Equal(2, vert.Count);
            Assert.Equal(new Point(140, 80), vert[0]);
            Assert.Equal(new Point(140, 260), vert[1]);
        }

        [Fact]
        public void Route_ZeroLength_ReturnsSinglePoint()
        {
            var p = new Point(200, 160);
            var route = WireGeometry.Route(p, p);

            Assert.Single(route);
            Assert.Equal(p, route[0]);
        }

        [Fact]
        public void HitTestWire_HorizontalSegment_SnapsXToGridAndKeepsExactY()
        {
            // Y = 125 (grid dışı dikey koordinat bile korunmalı), X: 100 → 300
            var w = MakeWire(100, 125, 300, 125);

            var hit = WireGeometry.HitTestWire(new[] { w }, new Point(187, 128), tolerance: 6.0);

            Assert.NotNull(hit);
            Assert.Same(w, hit!.Value.wire);
            Assert.Equal(new Point(180, 125), hit.Value.snapped);
        }

        [Fact]
        public void HitTestWire_VerticalSegment_SnapsYToGridAndKeepsExactX()
        {
            var w = MakeWire(140, 100, 260, 280);
            // L-rotası: (140,100) → (260,100) → (260,280); dikey kol X = 260 üzerinde
            var hit = WireGeometry.HitTestWire(new[] { w }, new Point(264, 193), tolerance: 6.0);

            Assert.NotNull(hit);
            Assert.Same(w, hit!.Value.wire);
            Assert.Equal(new Point(260, 200), hit.Value.snapped);
        }

        [Fact]
        public void HitTestWire_ToleranceBoundary_InsideHitsAndOutsideReturnsNull()
        {
            var w = MakeWire(100, 120, 300, 120);

            // Tam sınırda (dist = 6.0) yakalar
            var onBoundary = WireGeometry.HitTestWire(new[] { w }, new Point(200, 126), tolerance: 6.0);
            Assert.NotNull(onBoundary);
            Assert.Equal(new Point(200, 120), onBoundary!.Value.snapped);

            // Sınırın dışında (dist = 6.1) null döner
            var outside = WireGeometry.HitTestWire(new[] { w }, new Point(200, 126.1), tolerance: 6.0);
            Assert.Null(outside);
        }

        [Fact]
        public void HitTestWire_AtPinEnds_ReturnsNullSoPinLogicHandlesIt()
        {
            var w = MakeWire(100, 120, 260, 240);

            // Başlangıç pinine yuvarlanan nokta → null
            Assert.Null(WireGeometry.HitTestWire(new[] { w }, new Point(104, 121), tolerance: 6.0));

            // Bitiş pinine yuvarlanan nokta → null
            Assert.Null(WireGeometry.HitTestWire(new[] { w }, new Point(259, 236), tolerance: 6.0));

            // Köşe noktası (260, 120) pin ucu değildir → yakalanmalı
            var cornerHit = WireGeometry.HitTestWire(new[] { w }, new Point(258, 121), tolerance: 6.0);
            Assert.NotNull(cornerHit);
            Assert.Equal(new Point(260, 120), cornerHit!.Value.snapped);
        }

        [Fact]
        public void Split_PointOnEitherSegmentOfL_PreservesExactRouteAcrossRandomGridPoints()
        {
            var rng = new Random(42);
            int testedPoints = 0;

            for (int trial = 0; trial < 30; trial++)
            {
                double x1 = rng.Next(2, 15) * GridHelper.GridSize;
                double y1 = rng.Next(2, 15) * GridHelper.GridSize;
                double x2 = rng.Next(18, 32) * GridHelper.GridSize;
                double y2 = rng.Next(18, 32) * GridHelper.GridSize;

                var w = MakeWire(x1, y1, x2, y2);
                var originalRoute = WireGeometry.Route(w.StartPin.AbsolutePosition, w.EndPin.AbsolutePosition);

                // Yatay kol üzerindeki tüm iç ızgara noktaları ve köşe noktası
                for (double gx = x1 + GridHelper.GridSize; gx <= x2; gx += GridHelper.GridSize)
                {
                    var j = new Point(gx, y1);
                    var (first, second) = WireGeometry.Split(w, j);
                    var rFirst = WireGeometry.Route(first.StartPin.AbsolutePosition, first.EndPin.AbsolutePosition);
                    var rSecond = WireGeometry.Route(second.StartPin.AbsolutePosition, second.EndPin.AbsolutePosition);
                    Assert.True(WireGeometry.CombinedRouteMatches(rFirst, rSecond, originalRoute));
                    testedPoints++;
                }

                // Dikey kol üzerindeki tüm iç ızgara noktaları
                for (double gy = y1 + GridHelper.GridSize; gy < y2; gy += GridHelper.GridSize)
                {
                    var j = new Point(x2, gy);
                    var (first, second) = WireGeometry.Split(w, j);
                    var rFirst = WireGeometry.Route(first.StartPin.AbsolutePosition, first.EndPin.AbsolutePosition);
                    var rSecond = WireGeometry.Route(second.StartPin.AbsolutePosition, second.EndPin.AbsolutePosition);
                    Assert.True(WireGeometry.CombinedRouteMatches(rFirst, rSecond, originalRoute));
                    testedPoints++;
                }
            }

            Assert.True(testedPoints > 200);
        }
    }
}
