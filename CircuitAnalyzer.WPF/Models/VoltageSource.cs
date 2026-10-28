using System.Collections.Generic;
using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>
    /// DC Gerilim Kaynağı (Voltage Source) devre elemanı.
    /// IEC 60617 standardına uygun daire sembolü kullanır.
    /// 
    /// Görsel yapısı (80×40 piksel, yatay konumda):
    /// 
    ///   Pin1 (+)                         Pin2 (−)
    ///     ●━━━━━╭───────────╮━━━━━●
    ///    (0,20) │  +     −  │  (80,20)
    ///           ╰───────────╯
    ///           
    ///   ← 16px →← 48px ⌀  →← 16px →
    ///
    /// SPICE Netlist formatı:
    ///   V1 pozitif_düğüm negatif_düğüm değer
    ///   Örnek: V1 1 0 12  →  12V kaynak, düğüm 1 (+) ile 0/GND (−) arası
    ///
    /// OOP Kalıtım (Inheritance) Notu:
    ///   Bu sınıf, CircuitElement soyut sınıfından miras alır.
    ///   Resistor ile aynı kontratı (CreateVisual + ToNetlistEntry) uygular
    ///   ama kendi özgün görselini ve Netlist formatını üretir.
    ///   Polimorfizm sayesinde MainWindow, elemanın türünü bilmeden
    ///   AddElementToCanvas() ile her ikisini de ekleyebilir.
    /// </summary>
    public class VoltageSource : CircuitElement
    {
        // Görsel boyutlar (piksel)
        private const double TotalWidth = 80;    // 4 grid birim
        private const double TotalHeight = 40;   // 2 grid birim
        private const double CircleDiameter = 36; // Daire çapı
        private const double CircleRadius = CircleDiameter / 2;
        private const double LeadLength = (TotalWidth - CircleDiameter) / 2; // ~22px her taraf

        public VoltageSource()
        {
            Unit = "V";
            Value = 12; // Varsayılan: 12V DC

            // Pin 1 = Pozitif (+) terminal — sol uç
            // Pin 2 = Negatif (−) terminal — sağ uç
            // SPICE konvansiyonu: V_kaynak pozitif_node negatif_node değer
            Pins.Add(new Pin
            {
                Id = "+",
                RelativePosition = new Point(0, TotalHeight / 2),  // (0, 20)
                Owner = this
            });
            Pins.Add(new Pin
            {
                Id = "−",
                RelativePosition = new Point(TotalWidth, TotalHeight / 2),  // (80, 20)
                Owner = this
            });
        }

        /// <summary>
        /// IEC daire sembolü ile DC gerilim kaynağını çizer.
        /// Dairenin içinde + ve − polarite işaretleri bulunur.
        /// </summary>
        public override UIElement CreateVisual()
        {
            var container = new Canvas
            {
                Width = TotalWidth,
                Height = TotalHeight
            };

            double centerX = TotalWidth / 2;   // 40
            double centerY = TotalHeight / 2;   // 20
            double circleLeft = LeadLength;     // Dairenin sol kenarı

            // ── Sol bağlantı teli (lead) — pozitif taraf ──
            var leftLead = new Line
            {
                X1 = 0, Y1 = centerY,
                X2 = circleLeft, Y2 = centerY,
                StrokeThickness = 2
            };
            leftLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Sağ bağlantı teli (lead) — negatif taraf ──
            var rightLead = new Line
            {
                X1 = circleLeft + CircleDiameter, Y1 = centerY,
                X2 = TotalWidth, Y2 = centerY,
                StrokeThickness = 2
            };
            rightLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Ana daire gövdesi ──
            var circle = new Ellipse
            {
                Width = CircleDiameter,
                Height = CircleDiameter,
                StrokeThickness = 2
            };
            circle.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            circle.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            Canvas.SetLeft(circle, circleLeft);
            Canvas.SetTop(circle, centerY - CircleRadius);

            // ── "+" polarite işareti (dairenin sol yarısı) ──
            //    Yatay çizgi
            var plusH = new Line
            {
                X1 = centerX - 10, Y1 = centerY,
                X2 = centerX - 2, Y2 = centerY,
                StrokeThickness = 2,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round
            };
            plusH.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            //    Dikey çizgi
            var plusV = new Line
            {
                X1 = centerX - 6, Y1 = centerY - 4,
                X2 = centerX - 6, Y2 = centerY + 4,
                StrokeThickness = 2,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round
            };
            plusV.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── "−" polarite işareti (dairenin sağ yarısı) ──
            var minus = new Line
            {
                X1 = centerX + 2, Y1 = centerY,
                X2 = centerX + 10, Y2 = centerY,
                StrokeThickness = 2,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round
            };
            minus.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Değer etiketi (ör: "12V") — dairenin üstünde ──
            var label = new TextBlock
            {
                Text = FormatValue(),
                FontSize = 12,
                TextAlignment = TextAlignment.Center
            };
            label.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.LabelSecondary");
            label.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            label.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(label, centerX - (label.DesiredSize.Width / 2));
            Canvas.SetTop(label, centerY - CircleRadius - label.DesiredSize.Height - 2);

            // ── ID etiketi (ör: "V1") — dairenin altında ──
            var idLabel = new TextBlock
            {
                Text = Id,
                FontSize = 12
            };
            idLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Label");
            idLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            idLabel.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(idLabel, centerX - (idLabel.DesiredSize.Width / 2));
            Canvas.SetTop(idLabel, centerY + CircleRadius + 2);

            // Tüm şekilleri container'a ekle
            container.Children.Add(leftLead);
            container.Children.Add(rightLead);
            container.Children.Add(circle);
            container.Children.Add(plusH);
            container.Children.Add(plusV);
            container.Children.Add(minus);
            container.Children.Add(label);
            container.Children.Add(idLabel);

            // Pin göstergelerini ekle (mavi noktalar — base class'tan miras)
            AddPinIndicators(container);

            return container;
        }

        /// <summary>
        /// SPICE Netlist satırı üretir.
        /// Format: V_id pozitif_node negatif_node DC değer
        /// Örnek: "V1 1 0 12" → V1 kaynağı, düğüm 1(+) ile 0(−) arası, 12V
        /// 
        /// Not: SPICE'ta V kaynağının ilk düğümü (+) pozitif,
        /// ikinci düğümü (−) negatif terminali temsil eder.
        /// </summary>
        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int nodePlus = nodeMap[Pins[0]];   // (+) terminal
            int nodeMinus = nodeMap[Pins[1]];  // (−) terminal
            return $"{Id} {nodePlus} {nodeMinus} DC {Value.ToString(CultureInfo.InvariantCulture)}";
        }

        /// <summary>Değeri okunabilir formatta gösterir (ör: 0.005 → "5mV")</summary>
        private string FormatValue()
        {
            if (Value >= 1_000)
                return $"{TurkishNumber.Format(Value / 1_000, "G4")}kV";
            if (Value >= 1)
                return $"{TurkishNumber.Format(Value, "G4")}V";
            if (Value >= 0.001)
                return $"{TurkishNumber.Format(Value * 1_000, "G4")}mV";
            return $"{TurkishNumber.Format(Value, "G4")}V";
        }
    }
}
