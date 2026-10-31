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
    public enum TransformerMode
    {
        Ideal,
        Coupled
    }

    public enum CouplingInput
    {
        K,
        M
    }

    /// <summary>
    /// Transformatör (Transformer) devre elemanı.
    /// Sabit 4 uçlu:
    ///   Pins[0] = p+ (primer üst)
    ///   Pins[1] = p− (primer alt)
    ///   Pins[2] = s+ (sekonder üst)
    ///   Pins[3] = s− (sekonder alt)
    /// </summary>
    public class TransformerElement : CircuitElement
    {
        private const double TotalWidth = 80;
        private const double TotalHeight = 40;

        public override double VisualWidth => TotalWidth;
        public override double VisualHeight => TotalHeight;

        public TransformerMode Mode { get; set; } = TransformerMode.Ideal;

        /// <summary>Dönüştürme oranı a = N₂ / N₁ (varsayılan 1).</summary>
        public double Ratio { get; set; } = 1.0;

        /// <summary>Primer sarım sayısı (opsiyonel).</summary>
        public double? N1 { get; set; }

        /// <summary>Sekonder sarım sayısı (opsiyonel).</summary>
        public double? N2 { get; set; }

        /// <summary>Primer kendi kendine endüktansı L₁ (H, varsayılan 0.1).</summary>
        public double L1 { get; set; } = 0.1;

        /// <summary>Sekonder kendi kendine endüktansı L₂ (H, varsayılan 0.1).</summary>
        public double L2 { get; set; } = 0.1;

        /// <summary>Kuplaj katsayısı k (0 &lt; k ≤ 1, varsayılan 1).</summary>
        public double K { get; set; } = 1.0;

        /// <summary>Kuplaj giriş modu (K veya M).</summary>
        public CouplingInput CouplingInput { get; set; } = CouplingInput.K;

        public TransformerElement()
        {
            Id = "T";

            // Pins[0]: p+ (primer üst)
            Pins.Add(new Pin
            {
                Id = "p+",
                RelativePosition = new Point(0, 0),
                Owner = this
            });

            // Pins[1]: p− (primer alt)
            Pins.Add(new Pin
            {
                Id = "p-",
                RelativePosition = new Point(0, TotalHeight),
                Owner = this
            });

            // Pins[2]: s+ (sekonder üst)
            Pins.Add(new Pin
            {
                Id = "s+",
                RelativePosition = new Point(TotalWidth, 0),
                Owner = this
            });

            // Pins[3]: s− (sekonder alt)
            Pins.Add(new Pin
            {
                Id = "s-",
                RelativePosition = new Point(TotalWidth, TotalHeight),
                Owner = this
            });
        }

        /// <summary>
        /// Ortak endüktans M'den kuplaj katsayısı k'yi hesaplar: k = M / √(L₁·L₂).
        /// M, √(L₁·L₂) değerini aşamaz.
        /// </summary>
        public static double CalculateKFromM(double m, double l1, double l2)
        {
            if (l1 <= 0 || l2 <= 0)
                throw new ArgumentException("L₁ ve L₂ sıfırdan büyük olmalıdır.");
            if (m <= 0)
                throw new ArgumentException("M sıfırdan büyük olmalıdır.");

            double maxM = Math.Sqrt(l1 * l2);
            if (m > maxM + 1e-9)
                throw new InvalidOperationException("M, √(L₁·L₂) değerini aşamaz.");

            double k = m / maxM;
            return k > 1.0 ? 1.0 : k;
        }

        public string FormatDisplayValue()
        {
            if (Mode == TransformerMode.Ideal)
            {
                if (N1.HasValue && N2.HasValue)
                {
                    return $"{TurkishNumber.Format(N1.Value, "G4")} : {TurkishNumber.Format(N2.Value, "G4")}";
                }
                return $"1 : {TurkishNumber.Format(Ratio, "G4")}";
            }
            return $"k = {TurkishNumber.Format(K, "G4")}";
        }

        public override UIElement CreateVisual()
        {
            var container = new Canvas
            {
                Width = TotalWidth,
                Height = TotalHeight,
                Background = Brushes.Transparent
            };

            // Gövde dolgusu (ızgara çizgileri sembolün altından görünmesin)
            var bodyBg = new Rectangle
            {
                Width = 48,
                Height = TotalHeight,
            };
            bodyBg.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            Canvas.SetLeft(bodyBg, 16);
            Canvas.SetTop(bodyBg, 0);
            container.Children.Add(bodyBg);

            // ── Primer sargı (sol taraf) ──
            // (0,0) -> (28,0) -> (28,5) -> 3 yarım kavis -> (28,35) -> (28,40) -> (0,40)
            var pFigure = new PathFigure
            {
                StartPoint = new Point(0, 0),
                IsClosed = false
            };
            pFigure.Segments.Add(new LineSegment(new Point(28, 0), true));
            pFigure.Segments.Add(new LineSegment(new Point(28, 5), true));
            // 3 kavis, sola doğru kabarık
            pFigure.Segments.Add(new ArcSegment(new Point(28, 15), new Size(6, 5), 0, false, SweepDirection.Counterclockwise, true));
            pFigure.Segments.Add(new ArcSegment(new Point(28, 25), new Size(6, 5), 0, false, SweepDirection.Counterclockwise, true));
            pFigure.Segments.Add(new ArcSegment(new Point(28, 35), new Size(6, 5), 0, false, SweepDirection.Counterclockwise, true));
            pFigure.Segments.Add(new LineSegment(new Point(28, 40), true));
            pFigure.Segments.Add(new LineSegment(new Point(0, 40), true));

            var pGeom = new PathGeometry();
            pGeom.Figures.Add(pFigure);
            var pPath = new Path
            {
                Data = pGeom,
                StrokeThickness = 2,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round,
                StrokeLineJoin = PenLineJoin.Round,
                Fill = Brushes.Transparent
            };
            pPath.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(pPath);

            // ── Sekonder sargı (sağ taraf) ──
            // (80,0) -> (52,0) -> (52,5) -> 3 yarım kavis -> (52,35) -> (52,40) -> (80,40)
            var sFigure = new PathFigure
            {
                StartPoint = new Point(TotalWidth, 0),
                IsClosed = false
            };
            sFigure.Segments.Add(new LineSegment(new Point(52, 0), true));
            sFigure.Segments.Add(new LineSegment(new Point(52, 5), true));
            // 3 kavis, sağa doğru kabarık
            sFigure.Segments.Add(new ArcSegment(new Point(52, 15), new Size(6, 5), 0, false, SweepDirection.Clockwise, true));
            sFigure.Segments.Add(new ArcSegment(new Point(52, 25), new Size(6, 5), 0, false, SweepDirection.Clockwise, true));
            sFigure.Segments.Add(new ArcSegment(new Point(52, 35), new Size(6, 5), 0, false, SweepDirection.Clockwise, true));
            sFigure.Segments.Add(new LineSegment(new Point(52, 40), true));
            sFigure.Segments.Add(new LineSegment(new Point(TotalWidth, 40), true));

            var sGeom = new PathGeometry();
            sGeom.Figures.Add(sFigure);
            var sPath = new Path
            {
                Data = sGeom,
                StrokeThickness = 2,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round,
                StrokeLineJoin = PenLineJoin.Round,
                Fill = Brushes.Transparent
            };
            sPath.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(sPath);

            // ── Çekirdek çizgileri (ortada iki dikey çizgi) ──
            var core1 = new Line { X1 = 38, Y1 = 4, X2 = 38, Y2 = 36, StrokeThickness = 1.5 };
            core1.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            var core2 = new Line { X1 = 42, Y1 = 4, X2 = 42, Y2 = 36, StrokeThickness = 1.5 };
            core2.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(core1);
            container.Children.Add(core2);

            // ── Dolu polarite noktaları (p+ ve s+ yanında) ──
            var dotP = new Ellipse { Width = 5, Height = 5 };
            dotP.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Stroke");
            Canvas.SetLeft(dotP, 18);
            Canvas.SetTop(dotP, 6);
            container.Children.Add(dotP);

            var dotS = new Ellipse { Width = 5, Height = 5 };
            dotS.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Stroke");
            Canvas.SetLeft(dotS, 57);
            Canvas.SetTop(dotS, 6);
            container.Children.Add(dotS);

            // ── ID etiketi (üstte, ör: "T1") ──
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

            // ── Değer etiketi (altta, ör: "1 : 2" veya "k = 0,5") ──
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
            // Altta I₁ ve I₂ etiketleri durduğu için değer, adın üstüne yazılır
            Canvas.SetTop(valLabel, -idLabel.DesiredSize.Height - valLabel.DesiredSize.Height);
            container.Children.Add(valLabel);

            AddPinIndicators(container);

            return container;
        }

        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int pPlus = nodeMap[Pins[0]];
            int pMinus = nodeMap[Pins[1]];
            int sPlus = nodeMap[Pins[2]];
            int sMinus = nodeMap[Pins[3]];

            if (Mode == TransformerMode.Ideal)
            {
                string aStr = Ratio.ToString("G", CultureInfo.InvariantCulture);
                return $"{Id} {pPlus} {pMinus} {sPlus} {sMinus} IDEAL {aStr}";
            }
            else
            {
                string l1Str = L1.ToString("G", CultureInfo.InvariantCulture);
                string l2Str = L2.ToString("G", CultureInfo.InvariantCulture);
                string kStr = K.ToString("G", CultureInfo.InvariantCulture);
                return $"{Id} {pPlus} {pMinus} {sPlus} {sMinus} COUPLED {l1Str} {l2Str} {kStr}";
            }
        }
    }
}
