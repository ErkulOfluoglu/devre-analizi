using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>
    /// Wattmetre devre elemanı.
    /// Sabit 4 uçlu:
    ///   Pins[0] = I+ (sol)
    ///   Pins[1] = I− (sağ)
    ///   Pins[2] = V+ (üst)
    ///   Pins[3] = V− (alt)
    /// </summary>
    public class Wattmeter : CircuitElement
    {
        private const double TotalSize = 80;

        public override double VisualWidth => TotalSize;
        public override double VisualHeight => TotalSize;

        public Wattmeter()
        {
            Id = "W";

            Pins.Add(new Pin
            {
                Id = "I+",
                RelativePosition = new Point(0, 40),
                Owner = this
            });

            Pins.Add(new Pin
            {
                Id = "I-",
                RelativePosition = new Point(TotalSize, 40),
                Owner = this
            });

            Pins.Add(new Pin
            {
                Id = "V+",
                RelativePosition = new Point(40, 0),
                Owner = this
            });

            Pins.Add(new Pin
            {
                Id = "V-",
                RelativePosition = new Point(40, TotalSize),
                Owner = this
            });
        }

        public override UIElement CreateVisual()
        {
            var container = new Canvas
            {
                Width = TotalSize,
                Height = TotalSize,
                Background = Brushes.Transparent
            };

            // Daire gövde dolgusu ve çerçevesi
            var circle = new Ellipse
            {
                Width = 44,
                Height = 44,
                StrokeThickness = 1.5
            };
            circle.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            circle.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            Canvas.SetLeft(circle, 18);
            Canvas.SetTop(circle, 18);
            container.Children.Add(circle);

            // Bağlantı kolları (Leads)
            // Akım bobini (yatay): (0, 40) -> (18, 40) ve (62, 40) -> (80, 40)
            var leadIPlus = new Line { X1 = 0, Y1 = 40, X2 = 18, Y2 = 40, StrokeThickness = 1.5 };
            leadIPlus.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(leadIPlus);

            var leadIMinus = new Line { X1 = 62, Y1 = 40, X2 = 80, Y2 = 40, StrokeThickness = 1.5 };
            leadIMinus.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(leadIMinus);

            // Gerilim bobini (dikey): (40, 0) -> (40, 18) ve (40, 62) -> (40, 80)
            var leadVPlus = new Line { X1 = 40, Y1 = 0, X2 = 40, Y2 = 18, StrokeThickness = 1.5 };
            leadVPlus.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(leadVPlus);

            var leadVMinus = new Line { X1 = 40, Y1 = 62, X2 = 40, Y2 = 80, StrokeThickness = 1.5 };
            leadVMinus.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(leadVMinus);

            // Daire içinde "W" harfi
            var symW = new TextBlock
            {
                Text = "W",
                FontSize = 18,
                FontWeight = FontWeights.Bold
            };
            symW.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Stroke");
            symW.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            symW.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(symW, 40 - symW.DesiredSize.Width / 2);
            Canvas.SetTop(symW, 40 - symW.DesiredSize.Height / 2);
            container.Children.Add(symW);

            // Pin etiketleri (I+, I−, V+, V−)
            void AddPinLabel(string text, double x, double y)
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
                Canvas.SetLeft(lbl, x);
                Canvas.SetTop(lbl, y);
                container.Children.Add(lbl);
            }

            AddPinLabel("I+", 4, 24);
            AddPinLabel("I−", 62, 24);
            AddPinLabel("V+", 44, 4);
            AddPinLabel("V−", 44, 62);

            // Eleman ID etiketi (üstte)
            var idLabel = new TextBlock
            {
                Text = Id,
                FontSize = 12
            };
            idLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Label");
            idLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            idLabel.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(idLabel, 10);
            Canvas.SetTop(idLabel, -idLabel.DesiredSize.Height);
            container.Children.Add(idLabel);

            AddPinIndicators(container);

            return container;
        }

        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int iPlus = nodeMap[Pins[0]];
            int iMinus = nodeMap[Pins[1]];
            int vPlus = nodeMap[Pins[2]];
            int vMinus = nodeMap[Pins[3]];

            return $"{Id} {iPlus} {iMinus} {vPlus} {vMinus} WATTMETER";
        }
    }
}
