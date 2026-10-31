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
    /// Üç fazlı empedans yükü devre elemanı.
    /// Sabit 4 uçlu (solda alt alta):
    ///   Pins[0] = R
    ///   Pins[1] = S
    ///   Pins[2] = T
    ///   Pins[3] = N
    /// </summary>
    public class ThreePhaseLoad : CircuitElement
    {
        private const double TotalWidth = 80;
        private const double TotalHeight = 60;

        public override double VisualWidth => TotalWidth;
        public override double VisualHeight => TotalHeight;

        public ThreePhaseConnection Connection { get; set; } = ThreePhaseConnection.Star;
        public bool Balanced { get; set; } = true;

        public ComplexValue ZR { get; set; } = ComplexValue.FromRectangular(10, 5);
        public ComplexValue ZS { get; set; } = ComplexValue.FromRectangular(10, 5);
        public ComplexValue ZT { get; set; } = ComplexValue.FromRectangular(10, 5);

        public ThreePhaseLoad()
        {
            Id = "Y";

            Pins.Add(new Pin
            {
                Id = "R",
                RelativePosition = new Point(0, 0),
                Owner = this
            });

            Pins.Add(new Pin
            {
                Id = "S",
                RelativePosition = new Point(0, 20),
                Owner = this
            });

            Pins.Add(new Pin
            {
                Id = "T",
                RelativePosition = new Point(0, 40),
                Owner = this
            });

            Pins.Add(new Pin
            {
                Id = "N",
                RelativePosition = new Point(0, 60),
                Owner = this
            });
        }

        public static string[] GetPhaseLabels(ThreePhaseConnection connection)
        {
            return connection == ThreePhaseConnection.Star
                ? new[] { "Z_R", "Z_S", "Z_T" }
                : new[] { "Z_RS", "Z_ST", "Z_TR" };
        }

        public static bool CheckIsBalanced(ComplexValue zR, ComplexValue zS, ComplexValue zT)
        {
            const double eps = 1e-6;
            return Math.Abs(zR.Real - zS.Real) < eps &&
                   Math.Abs(zR.Imaginary - zS.Imaginary) < eps &&
                   Math.Abs(zR.Real - zT.Real) < eps &&
                   Math.Abs(zR.Imaginary - zT.Imaginary) < eps;
        }

        public static string FormatDisplayValue(bool balanced, ComplexValue zR, ComplexValue? zS = null, ComplexValue? zT = null)
        {
            if (balanced)
                return $"{zR.ToRectangularString()} Ω";
            return "dengesiz";
        }

        public string FormatDisplayValue() => FormatDisplayValue(Balanced, ZR, ZS, ZT);

        public override UIElement CreateVisual()
        {
            var container = new Canvas
            {
                Width = TotalWidth,
                Height = TotalHeight,
                Background = Brushes.Transparent
            };

            // Kutu gövde dolgusu ve çerçevesi
            var box = new Rectangle
            {
                Width = 46,
                Height = 44,
                StrokeThickness = 1.5,
                RadiusX = 2,
                RadiusY = 2
            };
            box.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            box.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            Canvas.SetLeft(box, 24);
            Canvas.SetTop(box, 8);
            container.Children.Add(box);

            // Soldaki 4 uçtan kutuya giden hatlar (R, S, T, N)
            var leadR = new Path
            {
                Data = Geometry.Parse("M 0,0 L 16,0 L 24,14"),
                StrokeThickness = 1.5
            };
            leadR.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(leadR);

            var leadS = new Line { X1 = 0, Y1 = 20, X2 = 24, Y2 = 20, StrokeThickness = 1.5 };
            leadS.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(leadS);

            var leadT = new Line { X1 = 0, Y1 = 40, X2 = 24, Y2 = 40, StrokeThickness = 1.5 };
            leadT.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(leadT);

            var leadN = new Path
            {
                Data = Geometry.Parse("M 0,60 L 16,60 L 24,46"),
                StrokeThickness = 1.5
            };
            leadN.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(leadN);

            // Kutu içinde Y ya da Δ çizimi
            if (Connection == ThreePhaseConnection.Star)
            {
                var yPath = new Path
                {
                    Data = Geometry.Parse("M 38,18 L 47,30 L 56,18 M 47,30 L 47,42"),
                    StrokeThickness = 1.8,
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round
                };
                yPath.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
                container.Children.Add(yPath);
            }
            else
            {
                var deltaPath = new Path
                {
                    Data = Geometry.Parse("M 47,18 L 57,40 L 37,40 Z"),
                    StrokeThickness = 1.8,
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round,
                    StrokeLineJoin = PenLineJoin.Round
                };
                deltaPath.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
                container.Children.Add(deltaPath);
            }

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
                Canvas.SetLeft(lbl, 4);
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

        private static string FormatZ(ComplexValue z)
            => $"Z({z.Real.ToString("G", CultureInfo.InvariantCulture)},{z.Imaginary.ToString("G", CultureInfo.InvariantCulture)})";

        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int r = nodeMap[Pins[0]];
            int s = nodeMap[Pins[1]];
            int t = nodeMap[Pins[2]];
            int n = nodeMap[Pins[3]];

            string conn = Connection == ThreePhaseConnection.Star ? "Y" : "D";
            return $"{Id} {r} {s} {t} {n} 3PH_LOAD {conn} {FormatZ(ZR)} {FormatZ(ZS)} {FormatZ(ZT)}";
        }
    }
}
