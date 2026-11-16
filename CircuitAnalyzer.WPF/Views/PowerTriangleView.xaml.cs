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
                TxtCompensation.Text = $"Q_C = {EngFormat.Format(data.Compensation.Qc ?? 0, "VAR")}, C = {EngFormat.Format(data.Compensation.C ?? 0, "F")}, akım {EngFormat.Format(data.Compensation.IBefore ?? 0, "A")} → {EngFormat.Format(data.Compensation.IAfter ?? 0, "A")}"
                    + "\n" + PowerTriangleLayout.CompensationCaption(data.P, data.Compensation.TargetPf);
                SubscriptText.Apply(TxtCompensation);
            }
            else
            {
                TxtCompensation.Visibility = Visibility.Visible;
                TxtCompensation.Text = data.Compensation.Reason ?? "";
                SubscriptText.Apply(TxtCompensation);
            }

            Redraw();
        }

        public void LoadData(ThreePhaseResultDto data)
        {
            if (data == null)
                return;

            _data = new PowerSummaryDto
            {
                P = data.P,
                Q = data.Q,
                S = data.S,
                Pf = data.Pf,
                PfType = data.PfType,
                Compensation = data.Compensation == null ? null : new PowerCompensationDto
                {
                    TargetPf = data.Compensation.TargetPf,
                    Qc = data.Compensation.Qc,
                    Applied = data.Compensation.Applied,
                    Reason = data.Compensation.Reason
                }
            };

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
                string qcStr = EngFormat.Format(data.Compensation.Qc ?? 0, "VAR");
                string cyStr = EngFormat.Format(data.Compensation.CY ?? 0, "F");
                string cDeltaStr = EngFormat.Format(data.Compensation.CDelta ?? 0, "F");
                TxtCompensation.Text = $"Q_C = {qcStr}, C_Y = {cyStr}, C_Δ = {cDeltaStr}"
                    + "\n" + PowerTriangleLayout.CompensationCaption(data.P, data.Compensation.TargetPf);
                SubscriptText.Apply(TxtCompensation);
            }
            else
            {
                TxtCompensation.Visibility = Visibility.Visible;
                TxtCompensation.Text = data.Compensation.Reason ?? "";
                SubscriptText.Apply(TxtCompensation);
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

            // Geometri ve yazı yerleri saf hesapta (PowerTriangleLayout): yazılar çakışmaz, tuvalde kalır
            bool hasComp = _data.Compensation != null && _data.Compensation.Applied;
            var layout = PowerTriangleLayout.Layout(w, h, _data.P, _data.Q, _data.PfType,
                hasComp ? _data.Compensation!.TargetPf : null);
            hasComp = layout.HasComp;
            double wP = layout.WidthP;
            double hQ = layout.HeightQ;
            double hQPrime = layout.HeightQComp;
            bool isLagging = layout.IsLagging;
            Point p0 = layout.P0, p1 = layout.P1, p2 = layout.P2, p2Comp = layout.P2Comp;

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
            }

            // 6. Kenar yazıları: değerleriyle P, Q, S, φ; kompanzasyonda Q_C, Q′, S′, φ₂ (yerleri layout'tan)
            foreach (var lbl in layout.Labels)
            {
                var tb = CreateLabel(lbl.Text, lbl.IsCompensation);
                Canvas.SetLeft(tb, lbl.Box.X);
                Canvas.SetTop(tb, lbl.Box.Y);
                TriangleCanvas.Children.Add(tb);
            }
        }

        /// <summary>
        /// Kenar yazısı. Renkler temadan (açık/koyu): asıl üçgen birincil yazı rengi, kompanzasyon
        /// yazıları ikincil yazı rengi; mavi kullanılmaz (DESIGN.md: mavi yalnız eylem/seçim/akım).
        /// </summary>
        private static TextBlock CreateLabel(string text, bool compensation = false)
        {
            var tb = new TextBlock
            {
                Text = text,
                FontSize = compensation ? PowerTriangleLayout.CompFontSize : PowerTriangleLayout.FontSize,
                FontWeight = compensation ? FontWeights.Normal : FontWeights.SemiBold
            };
            tb.SetResourceReference(TextBlock.ForegroundProperty, compensation ? "Brush.Text.Secondary" : "Brush.Text.Primary");
            SubscriptText.Apply(tb);
            return tb;
        }
    }
}
