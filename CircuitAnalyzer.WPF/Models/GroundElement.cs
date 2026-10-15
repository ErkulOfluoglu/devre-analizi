using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>
    /// Toprak (Ground / GND) referans noktası.
    /// 
    /// Devre analizinde tüm gerilimlerin ölçüldüğü referans noktasıdır.
    /// SPICE standardında GND = Node 0'dır.
    /// 
    /// ★ Kritik Özellik:
    /// GND pini ile aynı ağda (net) bulunan tüm pinler,
    /// Union-Find algoritmasında otomatik olarak Düğüm 0 (Node 0)
    /// numarasını alır. Bu atama MainWindow.BtnGenerateNetlist_Click
    /// içinde gerçekleşir.
    /// 
    /// Görsel yapısı (40×40 piksel):
    /// 
    ///       Pin (20, 0) — tek pin, üst merkez
    ///         ●
    ///         │  dikey gövde çizgisi
    ///    ━━━━━━━━━━  geniş yatay çizgi (32px)
    ///      ━━━━━━    orta yatay çizgi (20px)
    ///        ━━      dar yatay çizgi (8px)
    /// 
    /// Bu sembol IEC 60617-2 standardındaki
    /// "referans toprak" sembolüdür.
    /// 
    /// Netlist çıktısı: Yok (GND bir bileşen değil, referanstır).
    /// Etkisi: Bağlı olduğu ağa Node 0 atanır.
    /// </summary>
    public class GroundElement : CircuitElement
    {
        private const double TotalWidth = 40;
        private const double TotalHeight = 40;

        public override double VisualWidth => TotalWidth;
        public override double VisualHeight => TotalHeight;

        public GroundElement()
        {
            Unit = "";
            Value = 0;

            // Tek pin — üst merkez
            Pins.Add(new Pin
            {
                Id = "GND",
                RelativePosition = new Point(TotalWidth / 2, 0),
                Owner = this
            });
        }

        public override UIElement CreateVisual()
        {
            var container = new Canvas
            {
                Width = TotalWidth,
                Height = TotalHeight
            };

            double centerX = TotalWidth / 2; // 20

            // ── Dikey gövde çizgisi: pin → ilk yatay çizgi ──
            var stem = new Line
            {
                X1 = centerX, Y1 = 0,
                X2 = centerX, Y2 = 12,
                StrokeThickness = 2
            };
            stem.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(stem);

            // ── Üç yatay çizgi (küçülen genişlik) ──

            // Çizgi 1 — geniş (32px)
            var line1 = new Line
            {
                X1 = 4, Y1 = 12,
                X2 = 36, Y2 = 12,
                StrokeThickness = 2
            };
            line1.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(line1);

            // Çizgi 2 — orta (20px)
            var line2 = new Line
            {
                X1 = 10, Y1 = 20,
                X2 = 30, Y2 = 20,
                StrokeThickness = 2
            };
            line2.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(line2);

            // Çizgi 3 — dar (8px)
            var line3 = new Line
            {
                X1 = 16, Y1 = 28,
                X2 = 24, Y2 = 28,
                StrokeThickness = 2
            };
            line3.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(line3);

            // ── GND etiketi ──
            var label = new TextBlock
            {
                Text = Id,
                FontSize = 12
            };
            label.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Label");
            label.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            label.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(label, (TotalWidth - label.DesiredSize.Width) / 2);
            Canvas.SetTop(label, 30);
            container.Children.Add(label);

            // Pin göstergesi
            AddPinIndicators(container);

            return container;
        }

        /// <summary>
        /// GND bir bileşen değildir — Netlist'te satır üretmez.
        /// Etkisi Union-Find'da Node 0 atamasıdır.
        /// </summary>
        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            return $"* {Id} — Referans toprak (Node 0)";
        }
    }
}
