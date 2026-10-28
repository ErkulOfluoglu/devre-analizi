using System;
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
    /// AC Akım Kaynağı (AC Current Source) devre elemanı.
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
    ///   Fiziksel: IAC1 <n+> <n-> SINE(0 <amp> <freq> 0 0 <phase>)
    ///   Fazör:    IAC1 <n+> <n-> AC_PHASOR(<mag>, <phase>)
    ///
    /// SPICE konvansiyonu: Akım kaynak içinde n+ 'dan n- 'ye doğru akar,
    /// yani n- ucundan çıkarak harici devreye akar.
    /// </summary>
    public class AcCurrentSource : CircuitElement
    {
        private const double TotalWidth = 80;
        private const double TotalHeight = 40;
        private const double CircleDiameter = 36;
        private const double CircleRadius = CircleDiameter / 2;
        private const double LeadLength = (TotalWidth - CircleDiameter) / 2;

        public double Amplitude { get; set; } = 0.01; // Varsayılan: 10 mA tepe
        public double Frequency { get; set; } = 50.0; // Varsayılan: 50 Hz
        public double Phase { get; set; } = 0.0;     // Varsayılan: 0°
        public AcInputMode InputMode { get; set; } = AcInputMode.Physical;

        public AcCurrentSource()
        {
            Id = "IAC";
            Unit = "A";
            Value = 0.01;

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

            if (InputMode == AcInputMode.Phasor)
            {
                string mag = Amplitude.ToString(CultureInfo.InvariantCulture);
                string ph = Phase.ToString(CultureInfo.InvariantCulture);
                return $"{Id} {nodePlus} {nodeMinus} AC_PHASOR({mag}, {ph})";
            }

            string amp = Amplitude.ToString(CultureInfo.InvariantCulture);
            string freq = Frequency.ToString(CultureInfo.InvariantCulture);
            string phase = Phase.ToString(CultureInfo.InvariantCulture);

            return $"{Id} {nodePlus} {nodeMinus} SINE(0 {amp} {freq} 0 0 {phase})";
        }

        private string FormatValue()
        {
            string ampStr;
            if (Amplitude >= 1000)
                ampStr = $"{TurkishNumber.Format(Amplitude / 1000, "G3")}kA";
            else if (Amplitude >= 1)
                ampStr = $"{TurkishNumber.Format(Amplitude, "G3")}A";
            else if (Amplitude >= 0.001)
                ampStr = $"{TurkishNumber.Format(Amplitude * 1000, "G3")}mA";
            else if (Amplitude >= 0.000001)
                ampStr = $"{TurkishNumber.Format(Amplitude * 1000000, "G3")}µA";
            else
                ampStr = $"{TurkishNumber.Format(Amplitude * 1000, "G3")}mA";

            if (InputMode == AcInputMode.Phasor)
            {
                return $"{ampStr}∠{TurkishNumber.Format(Phase, "G3")}°";
            }

            string freqStr;
            if (Frequency >= 1_000_000)
                freqStr = $"{TurkishNumber.Format(Frequency / 1_000_000, "G3")}MHz";
            else if (Frequency >= 1000)
                freqStr = $"{TurkishNumber.Format(Frequency / 1000, "G3")}kHz";
            else
                freqStr = $"{TurkishNumber.Format(Frequency, "G3")}Hz";

            if (Math.Abs(Phase) < 0.01)
                return $"{ampStr} {freqStr}";

            return $"{ampStr} {freqStr} ∠{TurkishNumber.Format(Phase, "G3")}°";
        }
    }
}
