using System.Collections.Generic;
using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>
    /// Direnç (Resistor) devre elemanı.
    /// IEC 60617 standardına uygun dikdörtgen sembol kullanır.
    /// 
    /// Görsel yapısı (80×40 piksel, yatay konumda):
    /// 
    ///   Pin1                              Pin2
    ///    ●━━━━━━┏━━━━━━━━━━━━┓━━━━━━●
    ///    (0,20)  ┃   R = 1kΩ   ┃  (80,20)
    ///            ┗━━━━━━━━━━━━┛
    ///    
    ///    ← 20px →← 40px body →← 20px →
    ///    
    /// Pin konumları her zaman grid (20px) katlarına denk gelir,
    /// bu sayede başka elemanların pinleriyle düğüm eşleşmesi yapılabilir.
    /// </summary>
    public class Resistor : CircuitElement
    {
        // Görsel boyutlar (piksel cinsinden)
        private const double TotalWidth = 80;   // 4 grid birim
        private const double TotalHeight = 40;  // 2 grid birim
        private const double BodyWidth = 40;    // Dikdörtgen gövde genişliği
        private const double BodyHeight = 16;   // Dikdörtgen gövde yüksekliği
        private const double LeadLength = 20;   // Her iki taraftaki bağlantı teli

        public Resistor()
        {
            Unit = "Ω";
            Value = 1000; // Varsayılan: 1kΩ

            // Pinleri tanımla — yatay konumda sol ve sağ uçlar.
            // RelativePosition: elemanın kendi Canvas'ının sol-üst köşesine göre.
            Pins.Add(new Pin
            {
                Id = "1",
                RelativePosition = new Point(0, TotalHeight / 2),  // (0, 20) → sol uç
                Owner = this
            });
            Pins.Add(new Pin
            {
                Id = "2",
                RelativePosition = new Point(TotalWidth, TotalHeight / 2),  // (80, 20) → sağ uç
                Owner = this
            });
        }

        /// <summary>
        /// IEC dikdörtgen direnç sembolünü WPF şekilleriyle çizer.
        /// </summary>
        public override UIElement CreateVisual()
        {
            var container = new Canvas
            {
                Width = TotalWidth,
                Height = TotalHeight
            };

            double centerY = TotalHeight / 2;
            double bodyLeft = LeadLength;
            double bodyTop = centerY - (BodyHeight / 2);

            // ── Sol bağlantı teli (lead) ──
            var leftLead = new Line
            {
                X1 = 0, Y1 = centerY,
                X2 = bodyLeft, Y2 = centerY,
                StrokeThickness = 2
            };
            leftLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Sağ bağlantı teli (lead) ──
            var rightLead = new Line
            {
                X1 = bodyLeft + BodyWidth, Y1 = centerY,
                X2 = TotalWidth, Y2 = centerY,
                StrokeThickness = 2
            };
            rightLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Dikdörtgen gövde (IEC standardı) ──
            var body = new Rectangle
            {
                Width = BodyWidth,
                Height = BodyHeight,
                StrokeThickness = 2,
                RadiusX = 2,
                RadiusY = 2
            };
            body.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            body.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            Canvas.SetLeft(body, bodyLeft);
            Canvas.SetTop(body, bodyTop);

            // ── Değer etiketi (ör: "1kΩ") ──
            var label = new TextBlock
            {
                Text = FormatValue(),
                FontSize = 12,
                TextAlignment = TextAlignment.Center
            };
            label.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.LabelSecondary");
            label.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            // Etiket, gövdenin üzerinde ortalanır
            label.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(label, bodyLeft + (BodyWidth - label.DesiredSize.Width) / 2);
            Canvas.SetTop(label, bodyTop - label.DesiredSize.Height - 2);

            // ── ID etiketi (ör: "R1") ──
            var idLabel = new TextBlock
            {
                Text = Id,
                FontSize = 12
            };
            idLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Label");
            idLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            Canvas.SetLeft(idLabel, bodyLeft + 2);
            Canvas.SetTop(idLabel, bodyTop + BodyHeight + 2);

            // Şekilleri Canvas'a ekle
            container.Children.Add(leftLead);
            container.Children.Add(rightLead);
            container.Children.Add(body);
            container.Children.Add(label);
            container.Children.Add(idLabel);

            // Pin göstergelerini ekle (mavi noktalar)
            AddPinIndicators(container);

            return container;
        }

        /// <summary>
        /// SPICE Netlist satırı üretir.
        /// Örnek: "R1 1 0 1000" → R1 direnci, düğüm 1-0 arası, 1000Ω
        /// </summary>
        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int node1 = nodeMap[Pins[0]];
            int node2 = nodeMap[Pins[1]];
            return $"{Id} {node1} {node2} {Value.ToString(CultureInfo.InvariantCulture)}";
        }

        /// <summary>Değeri okunabilir formatta gösterir (ör: 1000 → "1kΩ")</summary>
        private string FormatValue()
        {
            if (Value >= 1_000_000)
                return $"{Value / 1_000_000:G4}MΩ";
            if (Value >= 1_000)
                return $"{Value / 1_000:G4}kΩ";
            return $"{Value:G4}Ω";
        }
    }
}
