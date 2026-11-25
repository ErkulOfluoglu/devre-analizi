using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>
    /// Diyot modeli (eşik gerilimi seçimi).
    /// </summary>
    public enum DiodeModel
    {
        /// <summary>İdeal diyot (V_T = 0 V).</summary>
        Ideal,

        /// <summary>Silisyum diyot (V_T = 0,7 V).</summary>
        Si,

        /// <summary>Germanyum diyot (V_T = 0,3 V).</summary>
        Ge
    }

    /// <summary>
    /// Diyot devre elemanı (2 pinli, polar: Pins[0] = Anot, Pins[1] = Katot).
    ///
    /// Görsel yapısı (80×40 piksel, yatay konumda):
    ///
    ///                     Si
    ///   Pin0 (A)         |\|         Pin1 (K)
    ///     ●━━━━━━━━━━━━━━|/|━━━━━━━━━━━━●
    ///    (0,20)         (28..50)      (80,20)
    ///                     D1
    ///
    /// Netlist satırı:
    ///   D1 anot_düğümü katot_düğümü MODEL   (MODEL = IDEAL | SI | GE)
    /// </summary>
    public class Diode : CircuitElement
    {
        private const double TotalWidth = 80;
        private const double TotalHeight = 40;
        private const double TriangleLeft = 28;
        private const double TriangleRight = 50;
        private const double HalfBodyHeight = 11;

        /// <summary>
        /// Gövde merkezinden aşağıda, diyotun kendi yazısının (ad ya da döndürülmüşse Si/Ge)
        /// bittiği yer. Sonuç etiketleri bunun altına konur ki yazıyı örtmesin.
        /// </summary>
        public const double TextZoneBelow = HalfBodyHeight + 2 + 17;

        public DiodeModel Model { get; set; } = DiodeModel.Si;

        /// <summary>Ekranda gövde üstünde gösterilen model etiketi (Ideal için boş).</summary>
        public string ModelLabel => Model switch
        {
            DiodeModel.Si => "Si",
            DiodeModel.Ge => "Ge",
            _ => string.Empty
        };

        /// <summary>Netlist ve dosya kaydı için model kodu: IDEAL | SI | GE.</summary>
        public string NetlistModel => Model switch
        {
            DiodeModel.Ideal => "IDEAL",
            DiodeModel.Ge => "GE",
            _ => "SI"
        };

        public Diode() : this(DiodeModel.Si)
        {
        }

        public Diode(DiodeModel model)
        {
            Id = "D";
            Model = model;

            // Pin 0 = Anot (sol uç)
            // Pin 1 = Katot (sağ uç, çizgili taraf)
            Pins.Add(new Pin
            {
                Id = "A",
                RelativePosition = new Point(0, TotalHeight / 2),
                Owner = this
            });
            Pins.Add(new Pin
            {
                Id = "K",
                RelativePosition = new Point(TotalWidth, TotalHeight / 2),
                Owner = this
            });
        }

        public override UIElement CreateVisual()
        {
            var container = new Canvas
            {
                Width = TotalWidth,
                Height = TotalHeight,
                Background = Brushes.Transparent
            };

            double centerX = TotalWidth / 2;
            double centerY = TotalHeight / 2;

            // ── Sol bağlantı ucu (anot tarafı) ──
            var leftLead = new Line
            {
                X1 = 0, Y1 = centerY,
                X2 = TriangleLeft, Y2 = centerY,
                StrokeThickness = 2
            };
            leftLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Sağ bağlantı ucu (katot tarafı) ──
            var rightLead = new Line
            {
                X1 = TriangleRight, Y1 = centerY,
                X2 = TotalWidth, Y2 = centerY,
                StrokeThickness = 2
            };
            rightLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Üçgen (anot solda, katoda doğru işaret eder) ──
            var triangle = new Polygon
            {
                Points = new PointCollection
                {
                    new Point(TriangleLeft, centerY - HalfBodyHeight),
                    new Point(TriangleRight, centerY),
                    new Point(TriangleLeft, centerY + HalfBodyHeight)
                },
                StrokeThickness = 2,
                StrokeLineJoin = PenLineJoin.Round
            };
            triangle.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            triangle.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");

            // ── Katot çubuğu ──
            var cathodeBar = new Line
            {
                X1 = TriangleRight, Y1 = centerY - HalfBodyHeight,
                X2 = TriangleRight, Y2 = centerY + HalfBodyHeight,
                StrokeThickness = 2.2,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round
            };
            cathodeBar.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            container.Children.Add(leftLead);
            container.Children.Add(rightLead);
            container.Children.Add(triangle);
            container.Children.Add(cathodeBar);

            // ── Model etiketi ("Si" / "Ge", Ideal için boş) — gövdenin üstünde ──
            string modelText = ModelLabel;
            if (!string.IsNullOrEmpty(modelText))
            {
                var label = new TextBlock
                {
                    Text = modelText,
                    FontSize = 12,
                    TextAlignment = TextAlignment.Center
                };
                label.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.LabelSecondary");
                label.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
                label.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
                Canvas.SetLeft(label, centerX - (label.DesiredSize.Width / 2));
                Canvas.SetTop(label, centerY - HalfBodyHeight - label.DesiredSize.Height - 2);
                container.Children.Add(label);
            }

            // ── ID etiketi (ör: "D1") — gövdenin altında ──
            var idLabel = new TextBlock
            {
                Text = Id,
                FontSize = 12
            };
            idLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Label");
            idLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            idLabel.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(idLabel, centerX - (idLabel.DesiredSize.Width / 2));
            Canvas.SetTop(idLabel, centerY + HalfBodyHeight + 2);
            container.Children.Add(idLabel);

            AddPinIndicators(container);

            return container;
        }

        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int nodeAnode = nodeMap[Pins[0]];
            int nodeCathode = nodeMap[Pins[1]];
            return $"{Id} {nodeAnode} {nodeCathode} {NetlistModel}";
        }
    }
}
