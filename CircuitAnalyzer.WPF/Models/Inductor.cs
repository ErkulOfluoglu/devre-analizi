using System;
using System.Collections.Generic;
using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>
    /// Bobin / İndüktör (Inductor) devre elemanı.
    /// IEC 60617 standardına uygun kavisli yay (coil) sembolü.
    /// 
    /// Görsel yapısı (80×40 piksel, yatay konumda):
    /// 
    ///   Pin1                                        Pin2
    ///    ●━━━━╭─╮╭─╮╭─╮╭─╮━━━━●
    ///   (0,20)                            (80,20)
    ///         ← 4 kavis (arc) →
    ///
    ///    ←16px→←── 48px coil ──→←16px→
    ///
    /// Fiziksel Bilgi (Öğrenci İçin):
    ///   Bobin, manyetik alanda enerji depolayan elemandır.
    ///   İndüktans birimi: Henry (H) — pratikte mH, µH kullanılır.
    ///   
    ///   AC devrelerde empedansı:
    ///     Z_L = jωL  =  j·2πfL
    ///   
    ///   Örnek: L = 100mH, f = 50Hz →
    ///     Z_L = j·2π·50·0.1 ≈ j31.42 Ω
    ///     (İndüktif reaktans: X_L = 31.42 Ω, gerilim akımın 90° önünde)
    ///   
    ///   Kapasitör ile karşılaştırma:
    ///     Z_C = 1/(jωC) → frekans ↑ ise Z_C ↓  (kısa devre etkisi)
    ///     Z_L = jωL     → frekans ↑ ise Z_L ↑  (açık devre etkisi)
    ///
    /// SPICE Netlist formatı:
    ///   L1 düğüm1 düğüm2 değer
    ///   Örnek: L1 2 3 5m  →  5mH bobin, düğüm 2 ile 3 arası
    /// </summary>
    public class Inductor : CircuitElement
    {
        // Görsel boyutlar (piksel)
        private const double TotalWidth = 80;
        private const double TotalHeight = 40;
        private const double LeadLength = 16;     // Her taraftaki bağlantı teli
        private const double CoilWidth = 48;      // Kavis bölgesinin toplam genişliği
        private const int CoilCount = 4;          // Kavis sayısı
        private const double ArcWidth = CoilWidth / CoilCount; // Her kavisin genişliği: 12px

        public Inductor()
        {
            Unit = "H";
            Value = 100e-3; // Varsayılan: 100mH

            Pins.Add(new Pin
            {
                Id = "1",
                RelativePosition = new Point(0, TotalHeight / 2),
                Owner = this
            });
            Pins.Add(new Pin
            {
                Id = "2",
                RelativePosition = new Point(TotalWidth, TotalHeight / 2),
                Owner = this
            });
        }

        /// <summary>
        /// IEC bobin sembolünü çizer: 4 adet yarım daire (arc) yan yana.
        /// Her arc, merkez çizgisinin üstüne doğru bir kavis oluşturur.
        /// Renk: Turuncu/amber — kapasitörün (cyan) tamamlayıcı rengi.
        /// 
        /// Çizim tekniği:
        ///   WPF PathGeometry ile ArcSegment kullanılır.
        ///   Her ArcSegment bir yarım daire çizer:
        ///   
        ///     ╭──╮        Size = (ArcWidth/2, ArcHeight)
        ///     │  │        SweepDirection = Counterclockwise
        ///   start end     IsLargeArc = false
        /// </summary>
        public override UIElement CreateVisual()
        {
            var container = new Canvas
            {
                Width = TotalWidth,
                Height = TotalHeight
            };

            double centerY = TotalHeight / 2; // 20
            double coilStartX = LeadLength;    // 16
            double arcHeight = 10; // Kavisin yukarı doğru yüksekliği

            // ── Gövde dolgusu (ızgara alttan görünmesin) ──
            var body = new Rectangle
            {
                Width = CoilWidth,
                Height = arcHeight + 2,
            };
            body.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            Canvas.SetLeft(body, coilStartX);
            Canvas.SetTop(body, centerY - arcHeight);

            // ── Sol bağlantı teli ──
            var leftLead = new Line
            {
                X1 = 0, Y1 = centerY,
                X2 = coilStartX, Y2 = centerY,
                StrokeThickness = 2
            };
            leftLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Sağ bağlantı teli ──
            var rightLead = new Line
            {
                X1 = coilStartX + CoilWidth, Y1 = centerY,
                X2 = TotalWidth, Y2 = centerY,
                StrokeThickness = 2
            };
            rightLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Kavisler (Coils) — 4 yarım daire ──
            // PathFigure ile tek bir sürekli yol (path) oluşturuyoruz.
            // Her ArcSegment bir yarım daire çizer.

            var pathFigure = new PathFigure
            {
                StartPoint = new Point(coilStartX, centerY),
                IsClosed = false
            };

            for (int i = 0; i < CoilCount; i++)
            {
                double arcEndX = coilStartX + (i + 1) * ArcWidth;

                // Her yarım daire: mevcut noktadan arcEndX'e kadar,
                // yukarı doğru kavisli bir yay çizer.
                pathFigure.Segments.Add(new ArcSegment
                {
                    Point = new Point(arcEndX, centerY),
                    Size = new Size(ArcWidth / 2, arcHeight),
                    SweepDirection = SweepDirection.Counterclockwise,
                    IsLargeArc = false,
                    IsStroked = true
                });
            }

            var pathGeometry = new PathGeometry();
            pathGeometry.Figures.Add(pathFigure);

            var coilPath = new Path
            {
                Data = pathGeometry,
                StrokeThickness = 2,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round,
                StrokeLineJoin = PenLineJoin.Round,
                Fill = Brushes.Transparent
            };
            coilPath.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Değer etiketi (ör: "100mH") ──
            var label = new TextBlock
            {
                Text = FormatDisplayValue(),
                FontSize = 12,
                TextAlignment = TextAlignment.Center
            };
            label.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.LabelSecondary");
            label.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            label.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(label, (TotalWidth - label.DesiredSize.Width) / 2);
            Canvas.SetTop(label, centerY - arcHeight - label.DesiredSize.Height - 4);

            // ── ID etiketi (ör: "L1") ──
            var idLabel = new TextBlock
            {
                Text = Id,
                FontSize = 12
            };
            idLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Label");
            idLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            idLabel.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(idLabel, (TotalWidth - idLabel.DesiredSize.Width) / 2);
            Canvas.SetTop(idLabel, centerY + 4);

            container.Children.Add(body);
            container.Children.Add(leftLead);
            container.Children.Add(rightLead);
            container.Children.Add(coilPath);
            container.Children.Add(label);
            container.Children.Add(idLabel);

            AddPinIndicators(container);

            return container;
        }

        /// <summary>
        /// SPICE Netlist satırı üretir.
        /// Format: L_id düğüm1 düğüm2 değer
        /// 
        /// SPICE değer gösterimi SI ön ekleri kullanır:
        ///   u = micro (10⁻⁶), m = milli (10⁻³)
        /// 
        /// Örnek: "L1 2 3 100m" → L1, düğüm 2-3, 100mH
        /// </summary>
        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int node1 = nodeMap[Pins[0]];
            int node2 = nodeMap[Pins[1]];
            return $"{Id} {node1} {node2} {FormatSpiceValue()}";
        }

        /// <summary>Ekran etiketi: "100mH", "47µH" vb.</summary>
        private string FormatDisplayValue()
        {
            if (Value >= 1.0)
                return $"{Value:G3}H";
            if (Value >= 1e-3)
                return $"{Value * 1e3:G3}mH";
            if (Value >= 1e-6)
                return $"{Value * 1e6:G3}µH";
            return $"{Value * 1e9:G3}nH";
        }

        /// <summary>SPICE formatı: "100m", "47u" vb.</summary>
        private string FormatSpiceValue()
        {
            if (Value >= 1.0)
                return Value.ToString("G4", CultureInfo.InvariantCulture);
            if (Value >= 1e-3)
                return $"{(Value * 1e3).ToString("G4", CultureInfo.InvariantCulture)}m";
            if (Value >= 1e-6)
                return $"{(Value * 1e6).ToString("G4", CultureInfo.InvariantCulture)}u";
            return $"{(Value * 1e9).ToString("G4", CultureInfo.InvariantCulture)}n";
        }
    }
}
