using System.Collections.Generic;
using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>
    /// Tek konumlu anahtarın çalışma şekli (t = 0 anındaki durum değişimi).
    /// </summary>
    public enum SwitchMode
    {
        /// <summary>Normalde Açık (NO): t &lt; 0 açık, t ≥ 0 kapalı ("t = 0'da kapanır").</summary>
        NormallyOpen,

        /// <summary>Normalde Kapalı (NC): t &lt; 0 kapalı, t ≥ 0 açık ("t = 0'da açılır").</summary>
        NormallyClosed
    }

    /// <summary>
    /// Tek konumlu anahtar devre elemanı (2 pinli).
    /// Netlist satırı:
    ///   S1 a b NO  (t &lt; 0 açık, t ≥ 0 kapalı)
    ///   S1 a b NC  (t &lt; 0 kapalı, t ≥ 0 açık)
    /// </summary>
    public class SwitchElement : CircuitElement
    {
        private const double TotalWidth = 80;
        private const double TotalHeight = 40;

        public SwitchMode Mode { get; set; } = SwitchMode.NormallyOpen;

        public SwitchElement() : this(SwitchMode.NormallyOpen)
        {
        }

        public SwitchElement(SwitchMode mode)
        {
            Id = "S";
            Mode = mode;

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

        public override UIElement CreateVisual()
        {
            var container = new Canvas
            {
                Width = TotalWidth,
                Height = TotalHeight,
                Background = Brushes.Transparent
            };

            double centerY = TotalHeight / 2;
            double leftContactX = 26;
            double rightContactX = 54;

            // Sol lead
            var leftLead = new Line
            {
                X1 = 0,
                Y1 = centerY,
                X2 = leftContactX,
                Y2 = centerY,
                StrokeThickness = 2
            };
            leftLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // Sol kontak noktası (küçük daire)
            var leftDot = new Ellipse
            {
                Width = 6,
                Height = 6,
                StrokeThickness = 1.5
            };
            leftDot.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            leftDot.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            Canvas.SetLeft(leftDot, leftContactX - 3);
            Canvas.SetTop(leftDot, centerY - 3);

            // Sağ lead
            var rightLead = new Line
            {
                X1 = rightContactX,
                Y1 = centerY,
                X2 = TotalWidth,
                Y2 = centerY,
                StrokeThickness = 2
            };
            rightLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // Sağ kontak noktası (küçük daire)
            var rightDot = new Ellipse
            {
                Width = 6,
                Height = 6,
                StrokeThickness = 1.5
            };
            rightDot.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            rightDot.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            Canvas.SetLeft(rightDot, rightContactX - 3);
            Canvas.SetTop(rightDot, centerY - 3);

            container.Children.Add(leftLead);
            container.Children.Add(leftDot);
            container.Children.Add(rightLead);
            container.Children.Add(rightDot);

            // Anahtar kolu t < 0 konumunda çizilir; ok, kolun t = 0 anındaki hareketini gösterir
            // (sol kontak etrafında dönen bir yay — ders kitaplarındaki gibi).
            var pivot = new Point(leftContactX, centerY);
            bool closesAtZero = Mode == SwitchMode.NormallyOpen;
            var blade = new Line
            {
                X1 = leftContactX,
                Y1 = centerY,
                // NO: kol yukarı kalkık (açık); NC: kol sağ kontağın üstüne değiyor (kapalı)
                X2 = closesAtZero ? rightContactX - 2 : rightContactX,
                Y2 = closesAtZero ? centerY - 12 : centerY - 3,
                StrokeThickness = 2,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round
            };
            blade.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(blade);

            // NO: yukarıdan aşağı (kapanır); NC: aşağıdan yukarı (açılır)
            AddRotationArrow(container, pivot, 34, closesAtZero ? -22 : -4, closesAtZero ? -4 : -22);

            // "t = 0" metni — sol üstte, kola ve oka değmez
            var t0Text = new TextBlock
            {
                Text = "t = 0",
                FontSize = 10,
                FontWeight = FontWeights.SemiBold
            };
            t0Text.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.LabelSecondary");
            t0Text.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            Canvas.SetLeft(t0Text, 0);
            Canvas.SetTop(t0Text, 0);
            container.Children.Add(t0Text);

            // Eleman ID etiketi (ör: "S1")
            var idLabel = new TextBlock
            {
                Text = Id,
                FontSize = 12
            };
            idLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Label");
            idLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            idLabel.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(idLabel, (TotalWidth - idLabel.DesiredSize.Width) / 2);
            Canvas.SetTop(idLabel, centerY + 5);
            container.Children.Add(idLabel);

            AddPinIndicators(container);

            return container;
        }

        /// <summary>
        /// Kolun bir kontak etrafında dönüşünü gösteren kavisli ok: <paramref name="pivot"/> merkezli,
        /// <paramref name="radius"/> yarıçaplı yay; açılar derece (0° = sağ, artı = aşağı).
        /// Ucunda dolu küçük bir üçgen vardır.
        /// </summary>
        internal static void AddRotationArrow(Canvas container, Point pivot, double radius, double fromDeg, double toDeg)
        {
            static Point At(Point c, double r, double deg) =>
                new(c.X + r * System.Math.Cos(deg * System.Math.PI / 180), c.Y + r * System.Math.Sin(deg * System.Math.PI / 180));

            bool clockwise = toDeg > fromDeg;
            Point start = At(pivot, radius, fromDeg);
            Point end = At(pivot, radius, toDeg);

            var fig = new PathFigure { StartPoint = start };
            fig.Segments.Add(new ArcSegment(end, new Size(radius, radius), 0, false,
                clockwise ? SweepDirection.Clockwise : SweepDirection.Counterclockwise, true));
            var arc = new Path
            {
                Data = new PathGeometry(new[] { fig }),
                StrokeThickness = 1.2,
                StrokeStartLineCap = PenLineCap.Round
            };
            arc.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(arc);

            // Yayın ucundaki teğet yönünde ok başı
            double t = toDeg * System.Math.PI / 180;
            var dir = clockwise ? new Vector(-System.Math.Sin(t), System.Math.Cos(t)) : new Vector(System.Math.Sin(t), -System.Math.Cos(t));
            var normal = new Vector(-dir.Y, dir.X);
            Point tip = end + dir * 1.5;
            Point baseCenter = end - dir * 4;
            var head = new Polygon
            {
                Points = new PointCollection { tip, baseCenter + normal * 2.6, baseCenter - normal * 2.6 }
            };
            head.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Stroke");
            container.Children.Add(head);
        }

        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int node1 = nodeMap[Pins[0]];
            int node2 = nodeMap[Pins[1]];
            string modeStr = Mode == SwitchMode.NormallyOpen ? "NO" : "NC";
            return $"{Id} {node1} {node2} {modeStr}";
        }
    }
}
