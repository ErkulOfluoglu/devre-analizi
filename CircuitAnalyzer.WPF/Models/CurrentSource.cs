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
    /// DC Akım Kaynağı (Current Source) devre elemanı.
    /// Daire içinde akım yönünü gösteren ok sembolü kullanır.
    ///
    /// Görsel yapısı (80×40 piksel, yatay konumda):
    ///
    ///   Pin1 (+)                         Pin2 (−)
    ///     ●━━━━━╭───────────╮━━━━━●
    ///    (0,20) │    ───►   │  (80,20)
    ///           ╰───────────╯
    ///
    /// SPICE Netlist formatı:
    ///   I1 pozitif_düğüm negatif_düğüm DC değer
    ///   Örnek: I1 0 2 DC 0.002  →  2mA kaynak, akım düğüm 0'dan (+) düğüm 2'ye (−) akar
    ///
    /// SPICE konvansiyonu: Akım kaynak içinde n+ 'dan n- 'ye doğru akar,
    /// yani n- ucundan çıkarak harici devreye akar.
    /// </summary>
    public class CurrentSource : CircuitElement
    {
        private const double TotalWidth = 80;
        private const double TotalHeight = 40;
        private const double CircleDiameter = 36;
        private const double CircleRadius = CircleDiameter / 2;
        private const double LeadLength = (TotalWidth - CircleDiameter) / 2;

        public CurrentSource()
        {
            Id = "I";
            Unit = "A";
            Value = 0.001; // Varsayılan: 1 mA (0.001 A)

            Pins.Add(new Pin
            {
                Id = "+",
                RelativePosition = new Point(0, TotalHeight / 2),
                Owner = this
            });
            Pins.Add(new Pin
            {
                Id = "−",
                RelativePosition = new Point(TotalWidth, TotalHeight / 2),
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

            double centerX = TotalWidth / 2;
            double centerY = TotalHeight / 2;
            double circleLeft = LeadLength;

            var leftLead = new Line
            {
                X1 = 0, Y1 = centerY,
                X2 = circleLeft, Y2 = centerY,
                StrokeThickness = 2
            };
            leftLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            var rightLead = new Line
            {
                X1 = circleLeft + CircleDiameter, Y1 = centerY,
                X2 = TotalWidth, Y2 = centerY,
                StrokeThickness = 2
            };
            rightLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

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

            // Daire içinde akım yönünü gösteren ok (sol → sağ)
            var arrowPath = new Path
            {
                StrokeThickness = 2,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round,
                StrokeLineJoin = PenLineJoin.Round
            };
            arrowPath.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            var pathGeometry = new PathGeometry();
            var shaftFigure = new PathFigure
            {
                StartPoint = new Point(centerX - 10, centerY),
                IsClosed = false
            };
            shaftFigure.Segments.Add(new LineSegment(new Point(centerX + 10, centerY), true));
            pathGeometry.Figures.Add(shaftFigure);

            var headFigure = new PathFigure
            {
                StartPoint = new Point(centerX + 4, centerY - 5),
                IsClosed = false
            };
            headFigure.Segments.Add(new LineSegment(new Point(centerX + 10, centerY), true));
            headFigure.Segments.Add(new LineSegment(new Point(centerX + 4, centerY + 5), true));
            pathGeometry.Figures.Add(headFigure);

            arrowPath.Data = pathGeometry;

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

            container.Children.Add(leftLead);
            container.Children.Add(rightLead);
            container.Children.Add(circle);
            container.Children.Add(arrowPath);
            container.Children.Add(label);
            container.Children.Add(idLabel);

            AddPinIndicators(container);

            return container;
        }

        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int nodePlus = nodeMap[Pins[0]];
            int nodeMinus = nodeMap[Pins[1]];
            return $"{Id} {nodePlus} {nodeMinus} DC {Value.ToString(CultureInfo.InvariantCulture)}";
        }

        private string FormatValue()
        {
            double abs = Math.Abs(Value);
            string sign = Value < 0 ? "-" : "";
            if (abs >= 1_000)
                return $"{sign}{abs / 1_000:G4} kA";
            if (abs >= 1)
                return $"{sign}{abs:G4} A";
            if (abs >= 0.001)
                return $"{sign}{abs * 1_000:G4} mA";
            if (abs >= 0.000_001)
                return $"{sign}{abs * 1_000_000:G4} µA";
            if (abs >= 0.000_000_001)
                return $"{sign}{abs * 1_000_000_000:G4} nA";
            return $"{sign}{abs:G4} A";
        }
    }
}
