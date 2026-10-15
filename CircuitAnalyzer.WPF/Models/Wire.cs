using System;
using System.Windows;
using System.Windows.Media;
using System.Windows.Shapes;

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
    /// Tel, L-şeklinde (orthogonal) çizilir:
    /// 
    ///   Pin1 ━━━━━━━━━━┓
    ///                  ┃
    ///                  ┗━━━━━━ Pin2
    /// 
    /// Önce yatay (horizontal), sonra dikey (vertical) gider.
    /// Eğer iki pin aynı Y'deyse → düz yatay çizgi.
    /// Eğer iki pin aynı X'teyse → düz dikey çizgi.
    /// </summary>
    public class Wire
    {
        /// <summary>Telin başladığı pin</summary>
        public Pin StartPin { get; set; }

        /// <summary>Telin bittiği pin</summary>
        public Pin EndPin { get; set; }

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

            // L-şekli kırılma noktası: önce yatay git, sonra dikey dön
            var mid = new Point(end.X, start.Y);

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
            Visual.Points.Add(start);

            // Sadece hem X hem Y farklıysa kırılma noktası ekle
            // Aksi halde düz çizgi yeterli
            bool needsMidpoint = Math.Abs(start.X - end.X) > 0.5 &&
                                 Math.Abs(start.Y - end.Y) > 0.5;
            if (needsMidpoint)
                Visual.Points.Add(mid);

            Visual.Points.Add(end);

            return Visual;
        }

        /// <summary>
        /// Tel çizimi sırasında gösterilen önizleme çizgisini oluşturur.
        /// Kesik çizgi (dashed) ve yarı saydam stilindedir.
        /// </summary>
        public static Polyline CreatePreviewLine(Point start, Point end)
        {
            var mid = new Point(end.X, start.Y);

            var preview = new Polyline
            {
                StrokeThickness = 2,
                StrokeDashArray = new DoubleCollection { 4, 3 },
                StrokeLineJoin = PenLineJoin.Round,
                IsHitTestVisible = false
            };
            preview.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.WirePreview");

            preview.Points.Add(start);

            bool needsMidpoint = Math.Abs(start.X - end.X) > 0.5 &&
                                 Math.Abs(start.Y - end.Y) > 0.5;
            if (needsMidpoint)
                preview.Points.Add(mid);

            preview.Points.Add(end);

            return preview;
        }
    }
}
