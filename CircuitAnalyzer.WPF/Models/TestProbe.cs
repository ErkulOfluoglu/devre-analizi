using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>
    /// Ölçüm probu tipi.
    /// </summary>
    public enum ProbeType
    {
        /// <summary>Gerilim probu — düğüm gerilimini ölçer: V(node)</summary>
        Voltage,
        /// <summary>Akım probu — eleman akımını ölçer: I(element)</summary>
        Current
    }

    /// <summary>
    /// Ölçüm Probu (Test Probe) — Python backend'e hangi büyüklüğün
    /// hesaplanacağını söyleyen işaretçi eleman.
    /// 
    /// Kullanım senaryoları:
    ///   "R1 üzerindeki gerilimi bulun"     → Gerilim probu, düğümü bağla
    ///   "L1'den geçen akımı hesaplayın"    → Akım probu, TargetElementId = "L1"
    ///   "Thevenin eşdeğerini bulun"        → Probu çıkış terminallerine koy
    /// 
    /// Görsel yapısı (40×40 piksel):
    /// 
    ///       Pin (20, 0) — tek pin, üst merkez
    ///         ●
    ///         │  dikey bağlantı çizgisi
    ///        ╭─╮
    ///        │V│  veya │I│  (daire içinde tip göstergesi)
    ///        ╰─╯
    ///         ▼  ok ucu (ölçüm yönü)
    /// 
    /// Netlist çıktısı (ölçüm direktifi):
    ///   * PROBE VP1 V(2)      ; Düğüm 2'deki gerilim
    ///   * PROBE IP1 I(R1)     ; R1'den geçen akım
    /// 
    /// Bu prob devreyi elektriksel olarak ETKİLEMEZ —
    /// ideal ölçüm cihazıdır (iç direnci V: ∞, I: 0).
    /// </summary>
    public class TestProbe : CircuitElement
    {
        private const double TotalWidth = 40;
        private const double TotalHeight = 40;

        public override double VisualWidth => TotalWidth;
        public override double VisualHeight => TotalHeight;

        /// <summary>Ölçüm tipi: Gerilim (V) veya Akım (I)</summary>
        public ProbeType Type { get; set; } = ProbeType.Voltage;

        /// <summary>
        /// Akım ölçümünde hedef eleman kimliği (ör: "R1", "L1").
        /// Gerilim modunda kullanılmaz — düğüm otomatik algılanır.
        /// </summary>
        public string TargetElementId { get; set; } = string.Empty;

        public TestProbe()
        {
            Unit = "";
            Value = 0;

            // Tek pin — üst merkez (devreye bağlantı noktası)
            Pins.Add(new Pin
            {
                Id = "P",
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

            // ── Dikey bağlantı çizgisi ──
            var stem = new Line
            {
                X1 = centerX, Y1 = 0,
                X2 = centerX, Y2 = 10,
                StrokeThickness = 2
            };
            stem.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Probe");
            container.Children.Add(stem);

            // ── Daire gövde ──
            var circle = new Ellipse
            {
                Width = 20,
                Height = 20,
                StrokeThickness = 2
            };
            circle.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Probe");
            circle.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            Canvas.SetLeft(circle, centerX - 10);
            Canvas.SetTop(circle, 10);
            container.Children.Add(circle);

            // ── Tip göstergesi (V veya I) ──
            var typeLabel = new TextBlock
            {
                Text = Type == ProbeType.Voltage ? "V" : "I",
                FontSize = 12,
                FontWeight = FontWeights.Bold
            };
            typeLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Probe");
            typeLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            typeLabel.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(typeLabel, centerX - typeLabel.DesiredSize.Width / 2);
            Canvas.SetTop(typeLabel, 12);
            container.Children.Add(typeLabel);

            // ── Ok ucu (üçgen, aşağı bakan) ──
            var arrow = new Polygon
            {
                Points = new PointCollection
                {
                    new Point(centerX - 5, 30),
                    new Point(centerX + 5, 30),
                    new Point(centerX, 38)
                }
            };
            arrow.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Probe");
            container.Children.Add(arrow);

            // ── ID + hedef etiketi ──
            string labelText = Id;
            if (Type == ProbeType.Current && !string.IsNullOrEmpty(TargetElementId))
                labelText += $"→{TargetElementId}";

            var idLabel = new TextBlock
            {
                Text = labelText,
                FontSize = 12
            };
            idLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.LabelSecondary");
            idLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            idLabel.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            double labelX = centerX + 12;
            Canvas.SetLeft(idLabel, labelX);
            Canvas.SetTop(idLabel, 14);
            container.Children.Add(idLabel);

            // Pin göstergesi
            AddPinIndicators(container);

            return container;
        }

        /// <summary>
        /// Ölçüm direktifi üretir.
        /// 
        /// Gerilim modu: * PROBE VP1 V(düğüm_numarası)
        /// Akım modu:    * PROBE IP1 I(hedef_eleman)
        /// 
        /// Python backend bu satırları regex ile ayrıştırır:
        ///   match = re.match(r'\* PROBE (\w+) ([VI])\((.+)\)', line)
        /// </summary>
        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            if (Type == ProbeType.Voltage)
            {
                int node = nodeMap.ContainsKey(Pins[0]) ? nodeMap[Pins[0]] : -1;
                return $"* PROBE {Id} V({node})";
            }
            else
            {
                string target = string.IsNullOrEmpty(TargetElementId)
                    ? "?" : TargetElementId;
                return $"* PROBE {Id} I({target})";
            }
        }
    }
}
