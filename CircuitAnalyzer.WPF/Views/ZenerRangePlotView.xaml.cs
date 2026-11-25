using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using CircuitAnalyzer.WPF.Services;
using ScottPlot;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Zener çalışma aralığı grafiği (ScottPlot 5):
    /// V_Y–x eğrisi, geçerli çalışma bandı gölgesi, min/maks kesikli çizgileri ve sağlama noktaları.
    /// </summary>
    public partial class ZenerRangePlotView : UserControl
    {
        public event EventHandler? EnlargeClicked;

        private ZenerRangeDto? _data;
        private double _xScale = 1.0;
        private string _xUnit = "";
        private ScottPlot.Plottables.Crosshair? _crosshair;
        private bool _builtForSize;

        public bool IsEnlarged
        {
            get => BtnEnlarge.Visibility == Visibility.Collapsed;
            set
            {
                BtnEnlarge.Visibility = value ? Visibility.Collapsed : Visibility.Visible;
                // Büyütülmüş pencerenin kendi başlığı var; başlık tekrarlanmasın
                TxtHeaderTitle.Visibility = value ? Visibility.Collapsed : Visibility.Visible;
            }
        }

        public ZenerRangePlotView()
        {
            InitializeComponent();
        }

        public void LoadData(ZenerRangeDto data)
        {
            _data = data;
            if (data == null)
                return;

            (_xScale, _xUnit) = XUnitFor(data);
            RenderPlot();
        }

        private void RenderPlot()
        {
            if (_data == null)
                return;

            double w = PlotMarkers.DataWidthPx(PlotZener.ActualWidth);
            double h = PlotMarkers.DataHeightPx(PlotZener.ActualHeight);
            _builtForSize = w > 0 && h > 0;
            _crosshair = BuildPlot(PlotZener.Plot, _data, _xScale, _xUnit, w, h, GetThemeColor);
            PlotZener.Refresh();
        }

        private void PlotZener_SizeChanged(object sender, SizeChangedEventArgs e)
        {
            if (!_builtForSize && _data != null)
                RenderPlot();
        }

        /// <summary>Grafik bandı ve kesikli çizgi sınırları: plot_min/plot_max varsa onları kullanır, yoksa min/max'a düşer.</summary>
        internal static (double? Min, double? Max) PlotBoundsFor(ZenerRangeDto data)
        {
            if (data.PlotMin.HasValue || data.PlotMax.HasValue)
                return (data.PlotMin, data.PlotMax);
            return (data.Min, data.Max);
        }

        private static string BaseXUnitFor(ZenerRangeDto data)
        {
            string raw = data.IsInverse && data.Given != null ? data.Given.Unit : data.Unit;
            return string.IsNullOrWhiteSpace(raw) ? "" : raw.Trim();
        }

        /// <summary>X ekseni için mühendislik ölçeği ve birimi (ör. ≥ 1000 Ω → kΩ, V → V).</summary>
        internal static (double Scale, string Unit) XUnitFor(ZenerRangeDto data)
        {
            string baseUnit = BaseXUnitFor(data);
            var (plotMin, plotMax) = PlotBoundsFor(data);
            double maxAbs = 0;

            if (data.Curve?.X is { Count: > 0 } xs)
            {
                foreach (double x in xs)
                    if (double.IsFinite(x))
                        maxAbs = Math.Max(maxAbs, Math.Abs(x));
            }
            if (plotMin is { } mn && double.IsFinite(mn)) maxAbs = Math.Max(maxAbs, Math.Abs(mn));
            if (plotMax is { } mx && double.IsFinite(mx)) maxAbs = Math.Max(maxAbs, Math.Abs(mx));
            // Ters problemde current_value cevap elemanına aittir, x ekseninde değildir
            if (!data.IsInverse && data.CurrentValue is { } cv && double.IsFinite(cv))
                maxAbs = Math.Max(maxAbs, Math.Abs(cv));
            if (data.Checks is { Count: > 0 } checks)
            {
                foreach (var c in checks)
                    if (double.IsFinite(c.X))
                        maxAbs = Math.Max(maxAbs, Math.Abs(c.X));
            }

            if (maxAbs == 0 || (maxAbs >= 1.0 && maxAbs < 1e3))
                return (1.0, baseUnit);
            if (maxAbs >= 1e6)
                return (1e-6, "M" + baseUnit);
            if (maxAbs >= 1e3)
                return (1e-3, "k" + baseUnit);
            if (maxAbs >= 1e-3)
                return (1e3, "m" + baseUnit);
            return (1e6, "µ" + baseUnit);
        }

        /// <summary>
        /// Zener aralığı grafiğini verilen <paramref name="plot"/>'a kurar. Ekrandaki kontrol uygulama
        /// temasının, yazdırma ise açık temanın renkleriyle (ekran dışı) çağırır.
        /// </summary>
        internal static ScottPlot.Plottables.Crosshair BuildPlot(
            Plot plot,
            ZenerRangeDto data,
            double xScale,
            string xUnit,
            double dataWidth,
            double dataHeight,
            Func<string, ScottPlot.Color> color)
        {
            plot.Clear();

            var bgCol = color("Brush.Bg.Surface");
            var textCol = color("Brush.Text.Primary");
            var subTextCol = color("Brush.Text.Secondary");
            var gridCol = color("Brush.Border.Default");
            var markerCol = color("Brush.Text.Tertiary");
            var curveCol = color("Brush.Accent");
            var okCol = color("Brush.Success");
            var warnCol = color("Brush.Warning");

            plot.FigureBackground.Color = bgCol;
            plot.DataBackground.Color = bgCol;
            plot.Axes.Color(subTextCol);
            plot.Grid.MajorLineColor = gridCol;

            bool hasCurve = data.Curve?.X is { Count: > 0 } cx
                && data.Curve.VY is { Count: > 0 } cy
                && cx.Count == cy.Count;

            double[] xVals = hasCurve ? new double[data.Curve!.X.Count] : Array.Empty<double>();
            double[] yVals = hasCurve ? new double[data.Curve!.VY.Count] : Array.Empty<double>();
            if (hasCurve)
            {
                for (int i = 0; i < xVals.Length; i++)
                {
                    xVals[i] = data.Curve!.X[i] * xScale;
                    yVals[i] = data.Curve.VY[i];
                }
            }

            var (plotMin, plotMax) = PlotBoundsFor(data);

            // Eksen sınırlarını eğri, sınır değerleri ve sağlama noktalarından hesapla
            var xCandidates = new List<double>();
            var yCandidates = new List<double>();
            if (hasCurve)
            {
                xCandidates.AddRange(xVals.Where(double.IsFinite));
                yCandidates.AddRange(yVals.Where(double.IsFinite));
            }
            if (plotMin is { } mn && double.IsFinite(mn)) xCandidates.Add(mn * xScale);
            if (plotMax is { } mx && double.IsFinite(mx)) xCandidates.Add(mx * xScale);
            if (data.Checks is { Count: > 0 })
            {
                foreach (var c in data.Checks)
                {
                    if (double.IsFinite(c.X)) xCandidates.Add(c.X * xScale);
                    if (double.IsFinite(c.VY)) yCandidates.Add(c.VY);
                }
            }

            double xMin = xCandidates.Count > 0 ? xCandidates.Min() : 0.0;
            double xMax = xCandidates.Count > 0 ? xCandidates.Max() : 1.0;
            double xSpan = Math.Max(1e-6, xMax - xMin);
            double left = Math.Max(0, xMin - xSpan * 0.06);
            double right = xMax + xSpan * 0.06;

            double yMin = yCandidates.Count > 0 ? yCandidates.Min() : 0.0;
            double yMax = yCandidates.Count > 0 ? yCandidates.Max() : 1.0;
            double ySpan = Math.Max(1e-6, yMax - yMin);
            double bottom = Math.Min(0, yMin - ySpan * 0.10);
            if (yMin >= 0)
                bottom = Math.Max(0, yMin - ySpan * 0.12);

            // Geçerli çalışma bandı hafif gölgeli — eğrinin altında kalsın diye önce eklenir
            if (plotMin is { } minVal && double.IsFinite(minVal))
            {
                double bandLeft = minVal * xScale;
                double bandRight = plotMax is { } maxVal && double.IsFinite(maxVal)
                    ? maxVal * xScale
                    : right;
                if (bandRight > bandLeft)
                {
                    var hspan = plot.Add.HorizontalSpan(bandLeft, bandRight);
                    hspan.FillColor = new ScottPlot.Color(okCol.R, okCol.G, okCol.B, 28);
                    hspan.LineColor = ScottPlot.Colors.Transparent;
                }
            }

            // Min ve maks sınırları: dikey kesikli çizgiler + üst rozet bandı
            var markers = new List<(double X, string Text)>();
            if (plotMin is { } minLine && double.IsFinite(minLine))
            {
                double xPos = minLine * xScale;
                var vl = plot.Add.VerticalLine(xPos);
                vl.LinePattern = ScottPlot.LinePattern.Dashed;
                vl.Color = markerCol;
                vl.LineWidth = 1.2f;
                markers.Add((xPos, "min"));
            }
            if (plotMax is { } maxLine && double.IsFinite(maxLine))
            {
                double xPos = maxLine * xScale;
                var vl = plot.Add.VerticalLine(xPos);
                vl.LinePattern = ScottPlot.LinePattern.Dashed;
                vl.Color = markerCol;
                vl.LineWidth = 1.2f;
                markers.Add((xPos, "maks"));
            }

            // V_Y(x) eğrisi
            if (hasCurve)
            {
                var scatter = plot.Add.Scatter(xVals, yVals, curveCol);
                scatter.LineWidth = 2.5f;
                scatter.MarkerSize = 0;
            }

            // Sağlama noktaları: OK yeşil, aralık dışı uyarı rengiyle işaretçi
            if (data.Checks is { Count: > 0 })
            {
                foreach (var c in data.Checks)
                {
                    if (!double.IsFinite(c.X) || !double.IsFinite(c.VY))
                        continue;
                    bool isOk = string.Equals(c.Verdict, "OK", StringComparison.OrdinalIgnoreCase);
                    var m = plot.Add.Marker(
                        c.X * xScale,
                        c.VY,
                        shape: MarkerShape.FilledCircle,
                        size: 9,
                        color: isOk ? okCol : warnCol);
                    m.MarkerLineColor = bgCol;
                    m.MarkerLineWidth = 1.5f;
                }
            }

            double yTop = PlotMarkers.AddBadges(
                plot, markers, left, right, bottom, yMax + ySpan * 0.08,
                dataWidth, dataHeight, 12f, textCol, bgCol, gridCol);
            plot.Axes.SetLimits(left, right, bottom, yTop);

            // Eksen başlıkları (kart başlığı zaten üstte, grafiğin içinde tekrarlanmaz)
            plot.Title("");
            string xLabel = FormatXLabel(data, xScale, xUnit);
            string yLabel = !string.IsNullOrWhiteSpace(data.YLabel)
                ? SubscriptText.Plain(data.YLabel)
                : "V_Y (V)";
            plot.XLabel(xLabel);
            plot.YLabel(yLabel);

            PlotMarkers.ApplyBottomTicks(plot, left, right, dataWidth);
            PlotMarkers.ApplyLeftTicks(plot);

            var crosshair = plot.Add.Crosshair(0, 0);
            crosshair.IsVisible = false;
            crosshair.LineColor = curveCol;
            crosshair.LinePattern = ScottPlot.LinePattern.Dotted;
            return crosshair;
        }

        /// <summary>X ekseni başlığı: önce API'nin x_label alanı (ölçeklendiyse birim güncellenir), yoksa sembol + birim.</summary>
        internal static string FormatXLabel(ZenerRangeDto data, double xScale, string xUnit)
        {
            if (!string.IsNullOrWhiteSpace(data.XLabel))
            {
                string raw = data.XLabel.Trim();
                string baseUnit = BaseXUnitFor(data);
                if (xScale != 1.0 && !string.IsNullOrEmpty(baseUnit) && !string.IsNullOrEmpty(xUnit))
                {
                    string baseSuffix = $"({baseUnit})";
                    if (raw.EndsWith(baseSuffix, StringComparison.Ordinal))
                        raw = raw[..^baseSuffix.Length] + $"({xUnit})";
                }
                return SubscriptText.Plain(raw);
            }

            string xSym = AnalysisPanel.ZenerCheckXSymbol(data);
            return string.IsNullOrEmpty(xUnit)
                ? SubscriptText.Plain(xSym)
                : $"{SubscriptText.Plain(xSym)} ({xUnit})";
        }

        private static ScottPlot.Color GetThemeColor(string resourceKey)
        {
            if (Application.Current?.TryFindResource(resourceKey) is SolidColorBrush b)
            {
                var c = b.Color;
                return new ScottPlot.Color(c.R, c.G, c.B, c.A);
            }
            return new ScottPlot.Color(128, 128, 128);
        }

        private void PlotZener_MouseMove(object sender, MouseEventArgs e)
        {
            if (_data?.Curve == null || _crosshair == null
                || _data.Curve.X == null || _data.Curve.VY == null
                || _data.Curve.X.Count == 0 || _data.Curve.X.Count != _data.Curve.VY.Count)
                return;

            var pos = e.GetPosition(PlotZener);
            var coords = PlotZener.Plot.GetCoordinates(new ScottPlot.Pixel(pos.X, pos.Y));
            double xScaled = coords.X;

            var xList = _data.Curve.X;
            var yList = _data.Curve.VY;

            double xMin = xList[0] * _xScale;
            double xMax = xList[^1] * _xScale;
            if (xMin > xMax)
                (xMin, xMax) = (xMax, xMin);

            if (xScaled < xMin || xScaled > xMax)
            {
                _crosshair.IsVisible = false;
                PlotZener.Refresh();
                TxtHover.Text = "";
                return;
            }

            int bestIdx = 0;
            double bestDist = Math.Abs(xList[0] * _xScale - xScaled);
            for (int i = 1; i < xList.Count; i++)
            {
                double dist = Math.Abs(xList[i] * _xScale - xScaled);
                if (dist < bestDist)
                {
                    bestDist = dist;
                    bestIdx = i;
                }
            }

            double nearestX = xList[bestIdx] * _xScale;
            double nearestY = yList[bestIdx];
            _crosshair.Position = new ScottPlot.Coordinates(nearestX, nearestY);
            _crosshair.IsVisible = true;
            PlotZener.Refresh();

            string sym = AnalysisPanel.ZenerCheckXSymbol(_data);
            string unitPart = string.IsNullOrEmpty(_xUnit) ? "" : " " + _xUnit;
            TxtHover.Text = $"{sym} = {TurkishNumber.FormatDisplay(nearestX, "G4")}{unitPart}, V_Y = {TurkishNumber.FormatDisplay(nearestY, "G4")} V";
            SubscriptText.Apply(TxtHover);
        }

        private void PlotZener_MouseLeave(object sender, MouseEventArgs e)
        {
            if (_crosshair != null)
            {
                _crosshair.IsVisible = false;
                PlotZener.Refresh();
            }
            TxtHover.Text = "";
        }

        private void BtnEnlarge_Click(object sender, RoutedEventArgs e)
        {
            EnlargeClicked?.Invoke(this, EventArgs.Empty);
        }
    }
}
