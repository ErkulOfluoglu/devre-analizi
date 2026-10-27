using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using System.Windows.Shapes;
using CircuitAnalyzer.WPF.Models;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Bir bağımlı kaynağın kontrol ettiği elemanın üzerine çizilen işaretler:
    ///   * Gerilim kontrolü: pin 1 yanında "+", pin 2 yanında "−" ve küçük bir "V_X" etiketi.
    ///   * Akım kontrolü: eleman boyunca pin 1'den pin 2'ye küçük bir ok ve "I_X" etiketi.
    /// Kontrol ters çevrilmişse ("Yönü ters çevir") artı/eksi yer değiştirir, ok ters yöne bakar.
    ///
    /// İşaretler elemanın görselinin DIŞINDA, tuval koordinatlarında (dönmeden) çizilir; böylece
    /// yazılar eleman döndürülünce de okunaklı kalır. MainWindow, devre her değiştiğinde
    /// ya da eleman taşınırken bunları baştan üretir.
    /// </summary>
    public static class ControlMarkers
    {
        /// <summary>Eleman ekseninden ilk yazı satırına kadar boşluk (eleman kendi etiketlerini bunun içinde taşır).</summary>
        private const double Clearance = 27;

        /// <summary>Artı/eksi işaretlerinin pine göre (eksen boyunca içe, eksene dik) ofseti.</summary>
        private const double SignAlong = 9;
        private const double SignAcross = 11;

        private const double ArrowHalfLength = 14;

        /// <summary>
        /// Kontrol elemanı için işaret görsellerini üretir. Eleman iki uçlu değilse boş döner.
        /// otherSide: Aynı elemanın hem gerilimi hem akımı kontrol ediliyorsa ikincisini karşı yüze çizmek için.
        /// </summary>
        public static IReadOnlyList<UIElement> Create(CircuitElement control, bool voltage, bool reversed, bool otherSide = false)
        {
            var markers = new List<UIElement>();
            if (control.Pins.Count != 2)
                return markers;

            Point p1 = control.Pins[0].AbsolutePosition;
            Point p2 = control.Pins[1].AbsolutePosition;
            Vector axis = p2 - p1;
            if (axis.Length < 1e-6)
                return markers;
            axis.Normalize();

            // Yatay elemanda üst, dikey elemanda sol yüz: çözüm sonrası akım etiketleri yatayda
            // alta, dikeyde sağa; düğüm rozetleri de pinlerin sağına çizilir (ResultOverlay).
            // Elemanın dönüşüne göre seçilseydi 90°/180°'de işaretler bunların altında kalırdı.
            Vector across = Math.Abs(axis.X) >= Math.Abs(axis.Y) ? new Vector(0, -1) : new Vector(-1, 0);
            if (otherSide)
                across = -across;

            Point center = new Point((p1.X + p2.X) / 2, (p1.Y + p2.Y) / 2);
            string quantity = voltage ? "V" : "I";
            TextBlock name = CreateName(quantity, control.Id);
            Size nameSize = Measure(name);

            // Etiket satırının eksenden uzaklığı: dikey yerleşimde yazının yarı genişliği de hesaba katılır
            double rowDistance = Clearance + Math.Abs(across.X) * nameSize.Width / 2 + Math.Abs(across.Y) * nameSize.Height / 2;

            if (voltage)
            {
                Point plusAt = reversed ? p2 : p1;
                Point minusAt = reversed ? p1 : p2;
                Vector plusIn = reversed ? -axis : axis;   // pinden elemanın içine doğru
                Vector minusIn = -plusIn;

                markers.Add(CreateSign("+", plusAt + plusIn * SignAlong + across * SignAcross));
                markers.Add(CreateSign("−", minusAt + minusIn * SignAlong + across * SignAcross));
                PlaceCentered(name, nameSize, center + across * rowDistance);
                markers.Add(name);
            }
            else
            {
                Vector dir = reversed ? -axis : axis;
                Point rowCenter = center + across * rowDistance;
                Point from = rowCenter - dir * ArrowHalfLength;
                Point to = rowCenter + dir * ArrowHalfLength;
                markers.Add(CreateArrow(from, to));

                // "I_X" yazısı okun ucunun biraz ötesinde
                double alongExtent = Math.Abs(dir.X) * nameSize.Width / 2 + Math.Abs(dir.Y) * nameSize.Height / 2;
                PlaceCentered(name, nameSize, to + dir * (alongExtent + 4));
                markers.Add(name);
            }

            return markers;
        }

        private static Size Measure(TextBlock tb)
        {
            tb.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            return tb.DesiredSize;
        }

        private static void PlaceCentered(FrameworkElement element, Size size, Point center)
        {
            Canvas.SetLeft(element, center.X - size.Width / 2);
            Canvas.SetTop(element, center.Y - size.Height / 2);
        }

        private static TextBlock CreateSign(string text, Point center)
        {
            var tb = new TextBlock
            {
                Text = text,
                FontSize = 15,
                FontWeight = FontWeights.Bold,
                IsHitTestVisible = false
            };
            tb.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Probe");
            tb.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            PlaceCentered(tb, Measure(tb), center);
            return tb;
        }

        /// <summary>"V_R2" / "I_R2": harf + alt simge olarak kimlik.</summary>
        private static TextBlock CreateName(string quantity, string id)
        {
            var tb = new TextBlock
            {
                FontSize = 12,
                FontWeight = FontWeights.SemiBold,
                IsHitTestVisible = false
            };
            tb.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Probe");
            tb.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            tb.Inlines.Add(new Run(quantity));
            tb.Inlines.Add(new Run(id) { BaselineAlignment = BaselineAlignment.Subscript, FontSize = 9 });
            return tb;
        }

        private static Path CreateArrow(Point from, Point to)
        {
            Vector dir = to - from;
            dir.Normalize();
            Vector normal = new Vector(-dir.Y, dir.X);
            Point back = to - dir * 6;

            var geometry = new PathGeometry();
            var shaft = new PathFigure { StartPoint = from, IsClosed = false };
            shaft.Segments.Add(new LineSegment(to, true));
            geometry.Figures.Add(shaft);

            var head = new PathFigure { StartPoint = back + normal * 3.5, IsClosed = false };
            head.Segments.Add(new LineSegment(to, true));
            head.Segments.Add(new LineSegment(back - normal * 3.5, true));
            geometry.Figures.Add(head);

            var arrow = new Path
            {
                Data = geometry,
                StrokeThickness = 1.75,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round,
                StrokeLineJoin = PenLineJoin.Round,
                IsHitTestVisible = false
            };
            arrow.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Probe");
            return arrow;
        }
    }
}
