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

            // Anahtar kolu (blade) t < 0 konumunda çizilir
            if (Mode == SwitchMode.NormallyOpen)
            {
                // NO: t < 0 açık — kol yukarı kalkık
                var blade = new Line
                {
                    X1 = leftContactX,
                    Y1 = centerY,
                    X2 = rightContactX - 2,
                    Y2 = centerY - 12,
                    StrokeThickness = 2,
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round
                };
                blade.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
                container.Children.Add(blade);

                // Aşağı doğru kapanma hareketini gösteren kavisli ok (t = 0 anında kapanır)
                var arrowPath = new Path
                {
                    StrokeThickness = 1.2,
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round
                };
                arrowPath.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
                var geom = new PathGeometry();
                var fig = new PathFigure { StartPoint = new Point(44, centerY - 14) };
                fig.Segments.Add(new ArcSegment(new Point(49, centerY - 3), new Size(12, 12), 0, false, SweepDirection.Clockwise, true));
                fig.Segments.Add(new LineSegment(new Point(45, centerY - 5), true));
                fig.Segments.Add(new LineSegment(new Point(49, centerY - 3), true));
                fig.Segments.Add(new LineSegment(new Point(49, centerY - 8), true));
                geom.Figures.Add(fig);
                arrowPath.Data = geom;
                container.Children.Add(arrowPath);
            }
            else
            {
                // NC: t < 0 kapalı — kol temas halinde
                var blade = new Line
                {
                    X1 = leftContactX,
                    Y1 = centerY,
                    X2 = rightContactX,
                    Y2 = centerY,
                    StrokeThickness = 2,
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round
                };
                blade.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
                container.Children.Add(blade);

                // Yukarı doğru açılma hareketini gösteren kavisli ok (t = 0 anında açılır)
                var arrowPath = new Path
                {
                    StrokeThickness = 1.2,
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round
                };
                arrowPath.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
                var geom = new PathGeometry();
                var fig = new PathFigure { StartPoint = new Point(49, centerY - 3) };
                fig.Segments.Add(new ArcSegment(new Point(44, centerY - 14), new Size(12, 12), 0, false, SweepDirection.Counterclockwise, true));
                fig.Segments.Add(new LineSegment(new Point(47, centerY - 12), true));
                fig.Segments.Add(new LineSegment(new Point(44, centerY - 14), true));
                fig.Segments.Add(new LineSegment(new Point(43, centerY - 9), true));
                geom.Figures.Add(fig);
                arrowPath.Data = geom;
                container.Children.Add(arrowPath);
            }

            // "t = 0" metni
            var t0Text = new TextBlock
            {
                Text = "t = 0",
                FontSize = 10,
                FontWeight = FontWeights.SemiBold
            };
            t0Text.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.LabelSecondary");
            t0Text.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            t0Text.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(t0Text, (TotalWidth - t0Text.DesiredSize.Width) / 2 - 10);
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

        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int node1 = nodeMap[Pins[0]];
            int node2 = nodeMap[Pins[1]];
            string modeStr = Mode == SwitchMode.NormallyOpen ? "NO" : "NC";
            return $"{Id} {node1} {node2} {modeStr}";
        }
    }
}
