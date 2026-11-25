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
    /// Dalga şekli zaman grafiği (ScottPlot 5):
    /// Giriş v_i (kesikli ikincil renk), çıkış v_O (düz vurgu rengi), sıfır çizgisi ve fare imleci.
    /// </summary>
    public partial class WaveformPlotView : UserControl
    {
        public event EventHandler? EnlargeClicked;

        private WaveformResultDto? _data;
        private double _timeScale = 1.0;
        private string _timeUnit = "s";
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

        public WaveformPlotView()
        {
            InitializeComponent();
        }

        /// <summary>Dalga şekli zaman ekseni için birim ve ölçek (TransientPlotView.TimeUnitFor ile uyumlu).</summary>
        internal static (double Scale, string Unit) TimeUnitFor(WaveformResultDto data)
        {
            double maxT = data.Period > 0 && double.IsFinite(data.Period) ? data.Period : 0.0;
            if (data.T is { Count: > 0 })
            {
                foreach (double t in data.T)
                    if (double.IsFinite(t))
                        maxT = Math.Max(maxT, Math.Abs(t));
            }
            if (maxT <= 0 && data.Frequency > 0 && double.IsFinite(data.Frequency))
                maxT = 1.0 / data.Frequency;
            if (maxT <= 0)
                return (1e3, "ms");

            return TransientPlotView.TimeUnitFor(maxT);
        }

        public void LoadData(WaveformResultDto data)
        {
            _data = data;
            if (data == null)
                return;

            (_timeScale, _timeUnit) = TimeUnitFor(data);
            RenderPlot();
        }

        private void RenderPlot()
        {
            if (_data == null)
                return;

            double w = PlotMarkers.DataWidthPx(PlotWaveform.ActualWidth);
            double h = PlotMarkers.DataHeightPx(PlotWaveform.ActualHeight);
            _builtForSize = w > 0 && h > 0;
            _crosshair = BuildPlot(PlotWaveform.Plot, _data, _timeScale, _timeUnit, w, h, GetThemeColor);
            PlotWaveform.Refresh();
        }

        private void PlotWaveform_SizeChanged(object sender, SizeChangedEventArgs e)
        {
            if (!_builtForSize && _data != null)
                RenderPlot();
        }

        /// <summary>
        /// Dalga şekli grafiğini verilen <paramref name="plot"/>'a kurar.
        /// Ekrandaki kontrol uygulama temasının, yazdırma ise açık temanın renkleriyle çağırır.
        /// </summary>
        internal static ScottPlot.Plottables.Crosshair BuildPlot(
            Plot plot,
            WaveformResultDto data,
            double timeScale,
            string timeUnit,
            double dataWidth,
            double dataHeight,
            Func<string, ScottPlot.Color> color)
        {
            plot.Clear();

            var bgCol = color("Brush.Bg.Surface");
            var textCol = color("Brush.Text.Primary");
            var subTextCol = color("Brush.Text.Secondary");
            var gridCol = color("Brush.Border.Default");
            var outCol = color("Brush.Accent");

            plot.FigureBackground.Color = bgCol;
            plot.DataBackground.Color = bgCol;
            plot.Axes.Color(subTextCol);
            plot.Grid.MajorLineColor = gridCol;

            int n = data.T?.Count ?? 0;
            bool hasIn = n > 0 && data.VIn is { Count: > 0 } && data.VIn.Count == n;
            bool hasOut = n > 0 && data.VOut is { Count: > 0 } && data.VOut.Count == n;

            double[] tVals = n > 0 ? new double[n] : Array.Empty<double>();
            for (int i = 0; i < n; i++)
                tVals[i] = data.T![i] * timeScale;

            // Sıfır ekseni çizgisi — eğrilerin altında kalsın diye önce eklenir
            var zeroLine = plot.Add.HorizontalLine(0);
            zeroLine.Color = gridCol;
            zeroLine.LineWidth = 1.1f;

            var yCandidates = new List<double> { 0.0 };

            if (hasIn)
            {
                double[] vIn = data.VIn.ToArray();
                yCandidates.AddRange(vIn.Where(double.IsFinite));
                var sIn = plot.Add.Scatter(tVals, vIn, subTextCol);
                sIn.LineWidth = 1.8f;
                sIn.LinePattern = ScottPlot.LinePattern.Dashed;
                sIn.MarkerSize = 0;
                sIn.LegendText = "Giriş v_i";
            }

            if (hasOut)
            {
                double[] vOut = data.VOut.ToArray();
                yCandidates.AddRange(vOut.Where(double.IsFinite));
                var sOut = plot.Add.Scatter(tVals, vOut, outCol);
                sOut.LineWidth = 2.5f;
                sOut.MarkerSize = 0;
                sOut.LegendText = "Çıkış v_O";
            }

            if (hasIn || hasOut)
            {
                plot.ShowLegend(Alignment.UpperRight);
                plot.Legend.BackgroundColor = bgCol;
                plot.Legend.FontColor = textCol;
                plot.Legend.OutlineColor = gridCol;
            }

            double xMin = n > 0 ? tVals.Where(double.IsFinite).DefaultIfEmpty(0.0).Min() : 0.0;
            double xMax = n > 0 ? tVals.Where(double.IsFinite).DefaultIfEmpty(1.0).Max() : 1.0;
            if (xMax <= xMin) xMax = xMin + 1.0;

            double yMin = yCandidates.Min();
            double yMax = yCandidates.Max();
            double ySpan = Math.Max(1e-6, yMax - yMin);
            double yBottom = yMin - ySpan * 0.12;
            double yTop = yMax + ySpan * 0.14;

            plot.Axes.SetLimits(xMin, xMax, yBottom, yTop);
            plot.Title("");
            plot.XLabel($"Zaman ({timeUnit})");
            plot.YLabel("Gerilim (V)");

            PlotMarkers.ApplyBottomTicks(plot, xMin, xMax, dataWidth);
            PlotMarkers.ApplyLeftTicks(plot);

            var crosshair = plot.Add.Crosshair(0, 0);
            crosshair.IsVisible = false;
            crosshair.LineColor = outCol;
            crosshair.LinePattern = ScottPlot.LinePattern.Dotted;
            return crosshair;
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

        private void PlotWaveform_MouseMove(object sender, MouseEventArgs e)
        {
            if (_data == null || _crosshair == null
                || _data.T == null || _data.T.Count == 0
                || _data.VOut == null || _data.VOut.Count != _data.T.Count)
                return;

            // Ekran ölçeği (%125/%150) hesaba katılır; bkz. PlotMouse.
            var coords = PlotWaveform.Plot.GetCoordinates(PlotMouse.ToPlotPixel(PlotWaveform, e));
            double tScaled = coords.X;

            double tMin = _data.T[0] * _timeScale;
            double tMax = _data.T[^1] * _timeScale;
            if (tMin > tMax) (tMin, tMax) = (tMax, tMin);

            if (tScaled < tMin || tScaled > tMax)
            {
                _crosshair.IsVisible = false;
                PlotWaveform.Refresh();
                TxtHover.Text = "";
                return;
            }

            int bestIdx = 0;
            double bestDist = Math.Abs(_data.T[0] * _timeScale - tScaled);
            for (int i = 1; i < _data.T.Count; i++)
            {
                double dist = Math.Abs(_data.T[i] * _timeScale - tScaled);
                if (dist < bestDist)
                {
                    bestDist = dist;
                    bestIdx = i;
                }
            }

            double nearestT = _data.T[bestIdx] * _timeScale;
            double nearestOut = _data.VOut[bestIdx];
            _crosshair.Position = new ScottPlot.Coordinates(nearestT, nearestOut);
            _crosshair.IsVisible = true;
            PlotWaveform.Refresh();

            bool hasIn = _data.VIn != null && _data.VIn.Count == _data.T.Count;
            string inPart = hasIn ? $", v_i = {TurkishNumber.FormatDisplay(_data.VIn![bestIdx], "G4")} V" : "";
            TxtHover.Text = $"t = {TurkishNumber.FormatDisplay(nearestT, "G4")} {_timeUnit}{inPart}, v_O = {TurkishNumber.FormatDisplay(nearestOut, "G4")} V";
            SubscriptText.Apply(TxtHover);
        }

        private void PlotWaveform_MouseLeave(object sender, MouseEventArgs e)
        {
            if (_crosshair != null)
            {
                _crosshair.IsVisible = false;
                PlotWaveform.Refresh();
            }
            TxtHover.Text = "";
        }

        private void BtnEnlarge_Click(object sender, RoutedEventArgs e)
        {
            EnlargeClicked?.Invoke(this, EventArgs.Empty);
        }
    }
}
