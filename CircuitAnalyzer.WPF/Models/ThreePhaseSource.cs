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
    public enum ThreePhaseConnection
    {
        Star,
        Delta
    }

    public enum ThreePhaseValueBasis
    {
        Line,
        Phase
    }

    public enum ThreePhaseSequence
    {
        Rst,
        Rts
    }

    /// <summary>
    /// Üç fazlı AC gerilim kaynağı devre elemanı.
    /// Sabit 4 uçlu (sağda alt alta):
    ///   Pins[0] = R
    ///   Pins[1] = S
    ///   Pins[2] = T
    ///   Pins[3] = N
    /// </summary>
    public class ThreePhaseSource : CircuitElement
    {
        private const double TotalWidth = 80;
        private const double TotalHeight = 60;

        public override double VisualWidth => TotalWidth;
        public override double VisualHeight => TotalHeight;

        public ThreePhaseConnection Connection { get; set; } = ThreePhaseConnection.Star;
        public ThreePhaseValueBasis ValueBasis { get; set; } = ThreePhaseValueBasis.Line;
        public double Frequency { get; set; } = 50.0;
        public double Phase { get; set; } = 0.0;
        public ThreePhaseSequence Sequence { get; set; } = ThreePhaseSequence.Rst;
        public AcValueKind ValueKind { get; set; } = AcValueKind.Rms;

        public ThreePhaseSource()
        {
            Id = "U";
            Value = 380.0;
            Unit = "V";

            Pins.Add(new Pin
            {
                Id = "R",
                RelativePosition = new Point(TotalWidth, 0),
                Owner = this
            });

            Pins.Add(new Pin
            {
                Id = "S",
                RelativePosition = new Point(TotalWidth, 20),
                Owner = this
            });

            Pins.Add(new Pin
            {
                Id = "T",
                RelativePosition = new Point(TotalWidth, 40),
                Owner = this
            });

            Pins.Add(new Pin
            {
                Id = "N",
                RelativePosition = new Point(TotalWidth, 60),
                Owner = this
            });
        }

        public string FormatDisplayValue()
        {
            string basisStr = ValueBasis == ThreePhaseValueBasis.Line ? "hat" : "faz";
            return $"{TurkishNumber.Format(Value, "G4")} V ({basisStr}) {TurkishNumber.Format(Frequency, "G4")} Hz";
        }

        public override UIElement CreateVisual()
        {
            var container = new Canvas
            {
                Width = TotalWidth,
                Height = TotalHeight,
                Background = Brushes.Transparent
            };

            // Daire gövde dolgusu ve çerçevesi
            var circle = new Ellipse
            {
                Width = 40,
                Height = 40,
                StrokeThickness = 1.5
            };
            circle.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            circle.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            Canvas.SetLeft(circle, 10);
            Canvas.SetTop(circle, 10);
            container.Children.Add(circle);

            // Sağdaki 4 uca giden hatlar (R, S, T, N)
            // (10+20, 10+20) = merkez (30, 30), daire yarıçapı 20
            var leadR = new Path
            {
                Data = Geometry.Parse("M 46,16 L 60,0 L 80,0"),
                StrokeThickness = 1.5
            };
            leadR.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(leadR);

            var leadS = new Line { X1 = 50, Y1 = 20, X2 = 80, Y2 = 20, StrokeThickness = 1.5 };
            leadS.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(leadS);

            var leadT = new Line { X1 = 50, Y1 = 40, X2 = 80, Y2 = 40, StrokeThickness = 1.5 };
            leadT.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(leadT);

            var leadN = new Path
            {
                Data = Geometry.Parse("M 46,44 L 60,60 L 80,60"),
                StrokeThickness = 1.5
            };
            leadN.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(leadN);

            // Daire içinde "3~" sembolü
            var symText = new TextBlock
            {
                Text = "3~",
                FontSize = 12,
                FontWeight = FontWeights.Bold
            };
            symText.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Stroke");
            symText.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            symText.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(symText, 30 - symText.DesiredSize.Width / 2);
            Canvas.SetTop(symText, 14);
            container.Children.Add(symText);

            // Daire içinde Y/Δ bağlantı metni
            var connText = new TextBlock
            {
                Text = Connection == ThreePhaseConnection.Star ? "Y" : "Δ",
                FontSize = 11,
                FontWeight = FontWeights.SemiBold
            };
            connText.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.LabelSecondary");
            connText.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            connText.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(connText, 30 - connText.DesiredSize.Width / 2);
            Canvas.SetTop(connText, 28);
            container.Children.Add(connText);

            // Uç etiketleri (R, S, T, N)
            void AddPinLabel(string text, double y)
            {
                var lbl = new TextBlock
                {
                    Text = text,
                    FontSize = 10,
                    FontWeight = FontWeights.SemiBold
                };
                lbl.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.LabelSecondary");
                lbl.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
                lbl.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
                Canvas.SetLeft(lbl, TotalWidth - lbl.DesiredSize.Width - 6);
                Canvas.SetTop(lbl, y - lbl.DesiredSize.Height / 2);
                container.Children.Add(lbl);
            }

            AddPinLabel("R", 0);
            AddPinLabel("S", 20);
            AddPinLabel("T", 40);
            AddPinLabel("N", 60);

            // Eleman ID etiketi (üstte)
            var idLabel = new TextBlock
            {
                Text = Id,
                FontSize = 12
            };
            idLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Label");
            idLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            idLabel.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(idLabel, (TotalWidth - idLabel.DesiredSize.Width) / 2);
            Canvas.SetTop(idLabel, -idLabel.DesiredSize.Height);
            container.Children.Add(idLabel);

            // Değer etiketi (altta)
            var valLabel = new TextBlock
            {
                Text = FormatDisplayValue(),
                FontSize = 11,
                TextAlignment = TextAlignment.Center
            };
            valLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.LabelSecondary");
            valLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            valLabel.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(valLabel, (TotalWidth - valLabel.DesiredSize.Width) / 2);
            Canvas.SetTop(valLabel, TotalHeight + 2);
            container.Children.Add(valLabel);

            AddPinIndicators(container);

            return container;
        }

        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int r = nodeMap[Pins[0]];
            int s = nodeMap[Pins[1]];
            int t = nodeMap[Pins[2]];
            int n = nodeMap[Pins[3]];

            string conn = Connection == ThreePhaseConnection.Star ? "Y" : "D";
            string basis = ValueBasis == ThreePhaseValueBasis.Line ? "LINE" : "PHASE";
            string valStr = Value.ToString("G", CultureInfo.InvariantCulture);
            string freqStr = Frequency.ToString("G", CultureInfo.InvariantCulture);
            string phaseStr = Phase.ToString("G", CultureInfo.InvariantCulture);
            string seq = Sequence == ThreePhaseSequence.Rst ? "RST" : "RTS";
            string rmsSuffix = ValueKind == AcValueKind.Rms ? " RMS" : "";

            return $"{Id} {r} {s} {t} {n} 3PH_SOURCE {conn} {basis} {valStr} {freqStr} {phaseStr} {seq}{rmsSuffix}";
        }
    }
}
