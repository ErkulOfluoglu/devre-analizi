using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>
    /// İki konumlu anahtar (SPDT — Single Pole Double Throw) devre elemanı (3 pinli).
    ///   Pin 0: Ortak uç (c)
    ///   Pin 1: Konum 1 ucu (a) — t &lt; 0 anında bağlı
    ///   Pin 2: Konum 2 ucu (b) — t ≥ 0 anında bağlı
    /// Netlist satırı:
    ///   S1 c a b SPDT
    /// </summary>
    public class SpdtSwitch : CircuitElement
    {
        private const double TotalWidth = 80;
        private const double TotalHeight = 40;

        public SpdtSwitch()
        {
            Id = "S";

            // Ortak uç (c) — sol orta
            Pins.Add(new Pin
            {
                Id = "c",
                RelativePosition = new Point(0, TotalHeight / 2),
                Owner = this
            });

            // 1. uç (a) — sağ üst
            Pins.Add(new Pin
            {
                Id = "1",
                RelativePosition = new Point(TotalWidth, 0),
                Owner = this
            });

            // 2. uç (b) — sağ alt
            Pins.Add(new Pin
            {
                Id = "2",
                RelativePosition = new Point(TotalWidth, TotalHeight),
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
            double commonContactX = 24;
            double contact1X = 56;
            double contact1Y = 8;
            double contact2X = 56;
            double contact2Y = 32;

            // ── Ortak uç teli ve kontak noktası ──
            var commonLead = new Line
            {
                X1 = 0,
                Y1 = centerY,
                X2 = commonContactX,
                Y2 = centerY,
                StrokeThickness = 2
            };
            commonLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            var commonDot = new Ellipse
            {
                Width = 6,
                Height = 6,
                StrokeThickness = 1.5
            };
            commonDot.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            commonDot.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            Canvas.SetLeft(commonDot, commonContactX - 3);
            Canvas.SetTop(commonDot, centerY - 3);

            // ── Kontak 1 teli (üst) ve noktası ──
            var lead1Geom = new PathGeometry();
            var lead1Fig = new PathFigure { StartPoint = new Point(TotalWidth, 0) };
            lead1Fig.Segments.Add(new LineSegment(new Point(64, 0), true));
            lead1Fig.Segments.Add(new LineSegment(new Point(contact1X, contact1Y), true));
            lead1Geom.Figures.Add(lead1Fig);
            var lead1Path = new Path { Data = lead1Geom, StrokeThickness = 2 };
            lead1Path.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            var dot1 = new Ellipse
            {
                Width = 6,
                Height = 6,
                StrokeThickness = 1.5
            };
            dot1.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            dot1.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            Canvas.SetLeft(dot1, contact1X - 3);
            Canvas.SetTop(dot1, contact1Y - 3);

            // ── Kontak 2 teli (alt) ve noktası ──
            var lead2Geom = new PathGeometry();
            var lead2Fig = new PathFigure { StartPoint = new Point(TotalWidth, TotalHeight) };
            lead2Fig.Segments.Add(new LineSegment(new Point(64, TotalHeight), true));
            lead2Fig.Segments.Add(new LineSegment(new Point(contact2X, contact2Y), true));
            lead2Geom.Figures.Add(lead2Fig);
            var lead2Path = new Path { Data = lead2Geom, StrokeThickness = 2 };
            lead2Path.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            var dot2 = new Ellipse
            {
                Width = 6,
                Height = 6,
                StrokeThickness = 1.5
            };
            dot2.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            dot2.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            Canvas.SetLeft(dot2, contact2X - 3);
            Canvas.SetTop(dot2, contact2Y - 3);

            container.Children.Add(commonLead);
            container.Children.Add(commonDot);
            container.Children.Add(lead1Path);
            container.Children.Add(dot1);
            container.Children.Add(lead2Path);
            container.Children.Add(dot2);

            // ── Kontak etiketleri "1" ve "2" ──
            var label1 = new TextBlock
            {
                Text = "1",
                FontSize = 10,
                FontWeight = FontWeights.SemiBold
            };
            label1.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.LabelSecondary");
            label1.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            Canvas.SetLeft(label1, contact1X + 6);
            Canvas.SetTop(label1, contact1Y - 6);
            container.Children.Add(label1);

            var label2 = new TextBlock
            {
                Text = "2",
                FontSize = 10,
                FontWeight = FontWeights.SemiBold
            };
            label2.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.LabelSecondary");
            label2.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            Canvas.SetLeft(label2, contact2X + 6);
            Canvas.SetTop(label2, contact2Y - 11);   // kontağın sağ üstünde: 2. kontağın eğik teline binmesin
            container.Children.Add(label2);

            // ── Anahtar kolu: t < 0 anında ortak uç ile 1. kontak bağlıdır ──
            var blade = new Line
            {
                X1 = commonContactX,
                Y1 = centerY,
                X2 = contact1X,
                Y2 = contact1Y,
                StrokeThickness = 2,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round
            };
            blade.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(blade);

            // ── 1'den 2'ye geçişi gösteren kavisli ok: kol ortak uç etrafında döner ──
            SwitchElement.AddRotationArrow(container, new Point(commonContactX, centerY), 20, -15, 25);

            // ── "t = 0" metni — sol üstte, kola ve oka değmez ──
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

            // ── ID etiketi (ör: "S1") ──
            var idLabel = new TextBlock
            {
                Text = Id,
                FontSize = 12
            };
            idLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Label");
            idLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            idLabel.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(idLabel, 4);
            Canvas.SetTop(idLabel, centerY + 5);
            container.Children.Add(idLabel);

            AddPinIndicators(container);

            return container;
        }

        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int nodeC = nodeMap[Pins[0]];
            int nodeA = nodeMap[Pins[1]];
            int nodeB = nodeMap[Pins[2]];
            return $"{Id} {nodeC} {nodeA} {nodeB} SPDT";
        }
    }
}
