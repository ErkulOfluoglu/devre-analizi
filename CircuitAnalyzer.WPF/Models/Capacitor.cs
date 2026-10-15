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
    /// Kapasitör (Capacitor) devre elemanı.
    /// IEC 60617 standardına uygun paralel iki düz çizgi sembolü.
    /// 
    /// Görsel yapısı (80×40 piksel, yatay konumda):
    /// 
    ///   Pin1                              Pin2
    ///    ●━━━━━━━━━━━━━━━┃  ┃━━━━━━━━━━━━━━━●
    ///    (0,20)         (32)(48)         (80,20)
    ///                    ┃  ┃
    ///                  plakalar
    ///
    ///    ← 32px lead →←16→← 32px lead →
    ///
    /// Fiziksel Bilgi (Öğrenci İçin):
    ///   Kapasitör, iki iletken plaka arasında elektrik alanı depolayan elemandır.
    ///   Kapasitans birimi: Farad (F) — pratikte µF, nF, pF kullanılır.
    ///   
    ///   AC devrelerde empedansı:
    ///     Z_C = 1 / (jωC)  =  1 / (j·2πfC)
    ///   
    ///   Örnek: C = 10µF, f = 50Hz →
    ///     Z_C = 1 / (j·2π·50·10⁻⁵) ≈ -j318.3 Ω
    ///     (Kapasitif reaktans: X_C = 318.3 Ω, gerilim akımın 90° gerisinde)
    ///
    /// SPICE Netlist formatı:
    ///   C1 düğüm1 düğüm2 değer
    ///   Örnek: C1 1 2 10u  →  10µF kapasitör, düğüm 1 ile 2 arası
    /// </summary>
    public class Capacitor : CircuitElement
    {
        // Görsel boyutlar (piksel)
        private const double TotalWidth = 80;
        private const double TotalHeight = 40;
        private const double PlateGap = 16;       // İki plaka arasındaki boşluk
        private const double PlateHeight = 28;     // Plaka yüksekliği
        private const double LeadLength = 32;      // Her taraftaki bağlantı teli

        public Capacitor()
        {
            Unit = "F";
            Value = 10e-6; // Varsayılan: 10µF

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
        /// IEC paralel plaka kapasitör sembolünü çizer.
        /// İki dikey çizgi (plakalar) + yatay bağlantı telleri.
        /// Renk: Camgöbeği/cyan — reaktif elemanları pasiflerden ayırmak için.
        /// </summary>
        public override UIElement CreateVisual()
        {
            var container = new Canvas
            {
                Width = TotalWidth,
                Height = TotalHeight
            };

            double centerY = TotalHeight / 2;
            double plateTop = centerY - (PlateHeight / 2);     // 6
            double plateBottom = centerY + (PlateHeight / 2);   // 34
            double leftPlateX = LeadLength;                     // 32
            double rightPlateX = LeadLength + PlateGap;         // 48

            // ── Gövde dolgusu (ızgara alttan görünmesin) ──
            var body = new Rectangle
            {
                Width = PlateGap + 4,
                Height = PlateHeight,
            };
            body.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            Canvas.SetLeft(body, leftPlateX - 2);
            Canvas.SetTop(body, plateTop);

            // ── Sol bağlantı teli ──
            var leftLead = new Line
            {
                X1 = 0, Y1 = centerY,
                X2 = leftPlateX, Y2 = centerY,
                StrokeThickness = 2
            };
            leftLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Sağ bağlantı teli ──
            var rightLead = new Line
            {
                X1 = rightPlateX, Y1 = centerY,
                X2 = TotalWidth, Y2 = centerY,
                StrokeThickness = 2
            };
            rightLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Sol plaka (dikey çizgi) ──
            var leftPlate = new Line
            {
                X1 = leftPlateX, Y1 = plateTop,
                X2 = leftPlateX, Y2 = plateBottom,
                StrokeThickness = 2,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round
            };
            leftPlate.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Sağ plaka (dikey çizgi) ──
            var rightPlate = new Line
            {
                X1 = rightPlateX, Y1 = plateTop,
                X2 = rightPlateX, Y2 = plateBottom,
                StrokeThickness = 2,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round
            };
            rightPlate.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Değer etiketi (ör: "10µF") ──
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
            Canvas.SetTop(label, plateTop - label.DesiredSize.Height - 2);

            // ── ID etiketi (ör: "C1") ──
            var idLabel = new TextBlock
            {
                Text = Id,
                FontSize = 12
            };
            idLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Label");
            idLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            idLabel.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(idLabel, (TotalWidth - idLabel.DesiredSize.Width) / 2);
            Canvas.SetTop(idLabel, plateBottom + 2);

            container.Children.Add(body);
            container.Children.Add(leftLead);
            container.Children.Add(rightLead);
            container.Children.Add(leftPlate);
            container.Children.Add(rightPlate);
            container.Children.Add(label);
            container.Children.Add(idLabel);

            AddPinIndicators(container);

            return container;
        }

        /// <summary>
        /// SPICE Netlist satırı üretir.
        /// Format: C_id düğüm1 düğüm2 değer
        /// 
        /// SPICE değer gösterimi SI ön ekleri kullanır:
        ///   p = pico (10⁻¹²), n = nano (10⁻⁹),
        ///   u = micro (10⁻⁶), m = milli (10⁻³)
        /// 
        /// Örnek: "C1 1 2 10u" → C1, düğüm 1-2, 10µF
        /// </summary>
        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int node1 = nodeMap[Pins[0]];
            int node2 = nodeMap[Pins[1]];
            return $"{Id} {node1} {node2} {FormatSpiceValue()}";
        }

        /// <summary>Ekran etiketi: "10µF", "100nF" vb.</summary>
        private string FormatDisplayValue()
        {
            if (Value >= 1.0)
                return $"{Value:G3}F";
            if (Value >= 1e-3)
                return $"{Value * 1e3:G3}mF";
            if (Value >= 1e-6)
                return $"{Value * 1e6:G3}µF";
            if (Value >= 1e-9)
                return $"{Value * 1e9:G3}nF";
            return $"{Value * 1e12:G3}pF";
        }

        /// <summary>SPICE formatı: "10u", "100n" vb.</summary>
        private string FormatSpiceValue()
        {
            if (Value >= 1.0)
                return Value.ToString("G4", CultureInfo.InvariantCulture);
            if (Value >= 1e-3)
                return $"{(Value * 1e3).ToString("G4", CultureInfo.InvariantCulture)}m";
            if (Value >= 1e-6)
                return $"{(Value * 1e6).ToString("G4", CultureInfo.InvariantCulture)}u";
            if (Value >= 1e-9)
                return $"{(Value * 1e9).ToString("G4", CultureInfo.InvariantCulture)}n";
            return $"{(Value * 1e12).ToString("G4", CultureInfo.InvariantCulture)}p";
        }
    }
}
