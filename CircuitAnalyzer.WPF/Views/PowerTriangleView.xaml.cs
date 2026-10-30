using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Güç üçgeni görselleştirme bileşeni (WPF Canvas/Path).
    /// P yatay, Q düşey (geri: yukarı, ileri: aşağı), S hipotenüs, φ açısı.
    /// Kompanzasyon uygulanmışsa ikinci kesikli üçgen ve ayrıntı satırı gösterilir.
    /// </summary>
    public partial class PowerTriangleView : UserControl
    {
        private PowerSummaryDto? _data;

        public PowerTriangleView()
        {
            InitializeComponent();
        }

        public void LoadData(PowerSummaryDto data)
        {
            _data = data;
            if (data == null)
                return;

            string pfTypeTr = (data.PfType ?? "").ToLowerInvariant() switch
            {
                "lagging" => "geri",
                "leading" => "ileri",
                "unity" => "birim",
                _ => data.PfType ?? ""
            };

            string pfFormatted = TurkishNumber.Format(data.Pf, "0.###");
            string pfText = string.IsNullOrEmpty(pfTypeTr) ? pfFormatted : $"{pfFormatted} {pfTypeTr}";

            TxtSummary.Text = $"P = {EngFormat.Format(data.P, "W")} | Q = {EngFormat.Format(data.Q, "VAR")} | S = {EngFormat.Format(data.S, "VA")} | cos φ = {pfText}";

            if (data.Compensation == null)
            {
                TxtCompensation.Visibility = Visibility.Collapsed;
            }
            else if (data.Compensation.Applied)
            {
                TxtCompensation.Visibility = Visibility.Visible;
                TxtCompensation.Text = $"Q_C = {EngFormat.Format(data.Compensation.Qc ?? 0, "VAR")}, C = {EngFormat.Format(data.Compensation.C ?? 0, "F")}, akım {EngFormat.Format(data.Compensation.IBefore ?? 0, "A")} → {EngFormat.Format(data.Compensation.IAfter ?? 0, "A")}";
            }
            else
            {
                TxtCompensation.Visibility = Visibility.Visible;
                TxtCompensation.Text = data.Compensation.Reason ?? "";
            }

            Redraw();
        }

        private void TriangleCanvas_SizeChanged(object sender, SizeChangedEventArgs e)
        {
            Redraw();
        }

        private void Redraw()
        {
            if (_data == null || TriangleCanvas == null)
                return;

            TriangleCanvas.Children.Clear();

            double w = TriangleCanvas.ActualWidth > 0 ? TriangleCanvas.ActualWidth : 340;
            double h = TriangleCanvas.ActualHeight > 0 ? TriangleCanvas.ActualHeight : 180;

            const double padLeft = 35;
            const double padRight = 45;
            const double padTop = 25;
            const double padBottom = 30;

            double availW = Math.Max(20, w - padLeft - padRight);
            double availH = Math.Max(20, h - padTop - padBottom);

            double pVal = Math.Abs(_data.P);
            double qVal = Math.Abs(_data.Q);

            bool hasComp = _data.Compensation != null && _data.Compensation.Applied;
            double qPrimeVal = 0;
            if (hasComp)
            {
                double targetPf = Math.Clamp(_data.Compensation!.TargetPf, 1e-6, 1.0);
                double phiTarget = Math.Acos(targetPf);
                qPrimeVal = Math.Max(0.0, pVal * Math.Tan(phiTarget));
            }

            double maxQ = Math.Max(qVal, hasComp ? qPrimeVal : 0.0);

            double scale;
            if (pVal < 1e-12 && maxQ < 1e-12)
            {
                scale = 1.0;
            }
            else if (pVal < 1e-12)
            {
                scale = availH / maxQ;
            }
            else if (maxQ < 1e-12)
            {
                scale = availW / pVal;
            }
            else
            {
                scale = Math.Min(availW / pVal, availH / maxQ);
            }

            double wP = pVal * scale;
            double hQ = qVal * scale;
            double hQPrime = hasComp ? qPrimeVal * scale : 0.0;

            bool isLeading = string.Equals(_data.PfType, "leading", StringComparison.OrdinalIgnoreCase) ||
                             (_data.Q < -1e-9 && !string.Equals(_data.PfType, "lagging", StringComparison.OrdinalIgnoreCase));
            bool isLagging = !isLeading && (string.Equals(_data.PfType, "lagging", StringComparison.OrdinalIgnoreCase) ||
                             _data.Q > 1e-9 || string.IsNullOrEmpty(_data.PfType));
            bool isUnity = Math.Abs(qVal) < 1e-9 || string.Equals(_data.PfType, "unity", StringComparison.OrdinalIgnoreCase);

            Point p0, p1, p2, p2Comp;
            if (isUnity)
            {
                double baseY = h / 2.0;
                p0 = new Point(padLeft, baseY);
                p1 = new Point(padLeft + wP, baseY);
                p2 = p1;
                p2Comp = p1;
            }
            else if (isLagging)
            {
                double baseY = h - padBottom;
                p0 = new Point(padLeft, baseY);
                p1 = new Point(padLeft + wP, baseY);
                p2 = new Point(padLeft + wP, baseY - hQ);
                p2Comp = new Point(padLeft + wP, baseY - hQPrime);
            }
            else // leading
            {
                double baseY = padTop;
                p0 = new Point(padLeft, baseY);
                p1 = new Point(padLeft + wP, baseY);
                p2 = new Point(padLeft + wP, baseY + hQ);
                p2Comp = new Point(padLeft + wP, baseY + hQPrime);
            }

            // 1. Ana Üçgen Alanı (hafif dolgu)
            if (wP > 2 && hQ > 2)
            {
                var fillPolygon = new Polygon
                {
                    Points = new PointCollection { p0, p1, p2 },
                    Opacity = 0.15
                };
                fillPolygon.SetResourceReference(Shape.FillProperty, "Brush.Accent");
                TriangleCanvas.Children.Add(fillPolygon);
            }

            // 2. Ana Üçgen Çizgileri (P, Q, S)
            var lineP = new Line
            {
                X1 = p0.X, Y1 = p0.Y,
                X2 = p1.X, Y2 = p1.Y,
                StrokeThickness = 2.0
            };
            lineP.SetResourceReference(Shape.StrokeProperty, "Brush.Accent");
            TriangleCanvas.Children.Add(lineP);

            if (hQ > 0.5)
            {
                var lineQ = new Line
                {
                    X1 = p1.X, Y1 = p1.Y,
                    X2 = p2.X, Y2 = p2.Y,
                    StrokeThickness = 2.0
                };
                lineQ.SetResourceReference(Shape.StrokeProperty, "Brush.Accent");
                TriangleCanvas.Children.Add(lineQ);

                var lineS = new Line
                {
                    X1 = p0.X, Y1 = p0.Y,
                    X2 = p2.X, Y2 = p2.Y,
                    StrokeThickness = 2.5
                };
                lineS.SetResourceReference(Shape.StrokeProperty, "Brush.Accent");
                TriangleCanvas.Children.Add(lineS);
            }

            // 3. Kompanzasyon Üçgeni (kesikli Q' ve S')
            if (hasComp && (wP > 2 || hQPrime > 2))
            {
                var lineCompQ = new Line
                {
                    X1 = p1.X, Y1 = p1.Y,
                    X2 = p2Comp.X, Y2 = p2Comp.Y,
                    StrokeThickness = 2.0,
                    StrokeDashArray = new DoubleCollection { 4, 2 }
                };
                lineCompQ.SetResourceReference(Shape.StrokeProperty, "Brush.Success");
                TriangleCanvas.Children.Add(lineCompQ);

                var lineCompS = new Line
                {
                    X1 = p0.X, Y1 = p0.Y,
                    X2 = p2Comp.X, Y2 = p2Comp.Y,
                    StrokeThickness = 2.0,
                    StrokeDashArray = new DoubleCollection { 4, 2 }
                };
                lineCompS.SetResourceReference(Shape.StrokeProperty, "Brush.Success");
                TriangleCanvas.Children.Add(lineCompS);
            }

            // 4. Dik Açı İşareti
            if (wP > 20 && hQ > 20)
            {
                double sq = Math.Min(8.0, Math.Min(wP * 0.2, hQ * 0.2));
                double sqY = isLagging ? -sq : sq;
                var rightAngle = new Polyline
                {
                    Points = new PointCollection
                    {
                        new Point(p1.X - sq, p1.Y),
                        new Point(p1.X - sq, p1.Y + sqY),
                        new Point(p1.X, p1.Y + sqY)
                    },
                    StrokeThickness = 1.0
                };
                rightAngle.SetResourceReference(Shape.StrokeProperty, "Brush.Text.Tertiary");
                TriangleCanvas.Children.Add(rightAngle);
            }

            // 5. φ Yayı ve Etiketi
            if (wP > 25 && hQ > 15)
            {
                double rArc = Math.Min(24.0, Math.Min(wP * 0.35, hQ * 0.35));
                double phi = Math.Atan2(hQ, wP);
                double endArcX = p0.X + rArc * Math.Cos(phi);
                double endArcY = isLagging ? p0.Y - rArc * Math.Sin(phi) : p0.Y + rArc * Math.Sin(phi);

                var arcGeom = new PathGeometry();
                var fig = new PathFigure { StartPoint = new Point(p0.X + rArc, p0.Y), IsClosed = false };
                fig.Segments.Add(new ArcSegment
                {
                    Point = new Point(endArcX, endArcY),
                    Size = new Size(rArc, rArc),
                    SweepDirection = isLagging ? SweepDirection.Counterclockwise : SweepDirection.Clockwise,
                    IsLargeArc = false
                });
                arcGeom.Figures.Add(fig);

                var arcPath = new Path
                {
                    Data = arcGeom,
                    StrokeThickness = 1.2
                };
                arcPath.SetResourceReference(Shape.StrokeProperty, "Brush.Text.Secondary");
                TriangleCanvas.Children.Add(arcPath);

                var lblPhi = CreateLabel("φ");
                Canvas.SetLeft(lblPhi, p0.X + rArc + 4);
                Canvas.SetTop(lblPhi, isLagging ? p0.Y - 14 : p0.Y + 2);
                TriangleCanvas.Children.Add(lblPhi);
            }

            // 6. Kenar Etiketleri (P, Q, S)
            var lblP = CreateLabel("P");
            Canvas.SetLeft(lblP, p0.X + Math.Max(0, wP / 2.0 - 6));
            Canvas.SetTop(lblP, isLagging ? p0.Y + 4 : p0.Y - 18);
            TriangleCanvas.Children.Add(lblP);

            if (hQ > 5 || maxQ > 5)
            {
                var lblQ = CreateLabel("Q");
                Canvas.SetLeft(lblQ, p1.X + 6);
                Canvas.SetTop(lblQ, isLagging ? (p1.Y - hQ / 2.0 - 8) : (p1.Y + hQ / 2.0 - 8));
                TriangleCanvas.Children.Add(lblQ);
            }

            if (wP > 10 || hQ > 10)
            {
                var lblS = CreateLabel("S");
                Canvas.SetLeft(lblS, Math.Max(0, p0.X + wP / 2.0 - 16));
                Canvas.SetTop(lblS, isLagging ? (p0.Y - hQ / 2.0 - 12) : (p0.Y + hQ / 2.0 + 2));
                TriangleCanvas.Children.Add(lblS);
            }
        }

        private static TextBlock CreateLabel(string text)
        {
            var tb = new TextBlock
            {
                Text = text,
                FontSize = 12,
                FontWeight = FontWeights.SemiBold
            };
            tb.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
            return tb;
        }
    }
}