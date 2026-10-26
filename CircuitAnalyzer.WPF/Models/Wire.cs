using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Media;
using System.Windows.Shapes;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>
    /// İki pin arasındaki elektriksel bağlantıyı (tel/kablo) temsil eder.
    /// 
    /// Tel, devre elemanı (CircuitElement) DEĞİLDİR:
    ///   - SPICE Netlist'te tel satırı bulunmaz (ideal tel, R ≈ 0)
    ///   - Tel yalnızca iki pinin aynı düğümde (node) olduğunu belirtir
    ///   - Bu yüzden CircuitElement'ten miras almaz — ayrı bir sınıftır
    /// 
    /// Yönlendirme (Routing):
    /// Tel, 90° dik açılı (orthogonal) parçalarla çizilir. Ara köşe noktaları
    /// (Waypoints) yoksa L-şeklinde, varsa ara köşelerden geçerek yönlendirilir.
    /// </summary>
    public class Wire
    {
        /// <summary>Telin başladığı pin</summary>
        public Pin StartPin { get; set; }

        /// <summary>Telin bittiği pin</summary>
        public Pin EndPin { get; set; }

        /// <summary>
        /// Telin ızgaraya oturtulmuş ara köşe noktaları (tuval koordinatları, boş olabilir).
        /// </summary>
        public List<Point> Waypoints { get; set; } = new();

        /// <summary>
        /// Son kolun (EndPin'e giden parçanın) yönü:
        /// false (varsayılan) = önce yatay sonra dikey; true = önce dikey sonra yatay.
        /// </summary>
        public bool LastLegVerticalFirst { get; set; }

        /// <summary>
        /// Polyline görsel nesnesi — Canvas üzerinde güncelleme için referans tutulur.
        /// Eleman sürüklendiğinde bu referans üzerinden noktalar güncellenir.
        /// </summary>
        public Polyline? Visual { get; set; }

        public Wire(Pin startPin, Pin endPin)
        {
            StartPin = startPin;
            EndPin = endPin;
        }

        public Wire(Pin startPin, Pin endPin, IEnumerable<Point>? waypoints, bool lastLegVerticalFirst = false)
        {
            StartPin = startPin;
            EndPin = endPin;
            if (waypoints != null)
            {
                Waypoints.AddRange(waypoints);
            }
            LastLegVerticalFirst = lastLegVerticalFirst;
        }

        /// <summary>
        /// Telin görselini (Polyline) oluşturur veya günceller.
        /// 
        /// Neden CreateOrUpdate?
        /// - İlk çağrıda Polyline oluşturulur ve Canvas'a eklenmek üzere döner.
        /// - Eleman sürüklendiğinde aynı Polyline'ın Points koleksiyonu güncellenir.
        ///   Böylece Canvas'tan kaldırıp yeniden eklemeye gerek kalmaz.
        /// </summary>
        public Polyline CreateOrUpdateVisual()
        {
            var start = StartPin.AbsolutePosition;
            var end = EndPin.AbsolutePosition;

            if (Visual == null)
            {
                Visual = new Polyline
                {
                    StrokeThickness = 2,
                    StrokeLineJoin = PenLineJoin.Round,
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round,
                    IsHitTestVisible = false // Fare olaylarını engellemez
                };
                Visual.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Wire");
            }

            Visual.Points.Clear();
            var route = WireGeometry.Route(start, Waypoints, end, LastLegVerticalFirst);
            foreach (var pt in route)
                Visual.Points.Add(pt);
            if (Visual.Points.Count == 1)
                Visual.Points.Add(end);

            return Visual;
        }

        /// <summary>
        /// Tel çizimi sırasında gösterilen önizleme çizgisini oluşturur.
        /// Kesik çizgi (dashed) ve yarı saydam stilindedir.
        /// </summary>
        public static Polyline CreatePreviewLine(Point start, Point end)
            => CreatePreviewLine(start, null, end, false);

        /// <summary>
        /// Ara köşe noktaları ve son kol yönü ile tel önizleme çizgisini oluşturur.
        /// </summary>
        public static Polyline CreatePreviewLine(
            Point start,
            IReadOnlyList<Point>? waypoints,
            Point end,
            bool lastLegVerticalFirst = false)
        {
            var preview = new Polyline
            {
                StrokeThickness = 2,
                StrokeDashArray = new DoubleCollection { 4, 3 },
                StrokeLineJoin = PenLineJoin.Round,
                IsHitTestVisible = false
            };
            preview.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.WirePreview");

            var route = WireGeometry.Route(start, waypoints, end, lastLegVerticalFirst);
            foreach (var pt in route)
                preview.Points.Add(pt);
            if (preview.Points.Count == 1)
                preview.Points.Add(end);

            return preview;
        }
    }
}
