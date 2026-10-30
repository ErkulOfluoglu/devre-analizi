using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using CircuitAnalyzer.WPF.Services;
using ScottPlot;
using ScottPlot.WPF;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Rezonans frekans eğrisi bileşeni (ScottPlot 5).
    /// Seri RLC için akım I(f), paralel RLC için empedans Z(f) eğrisini;
    /// f0, f1, f2 dikey çizgilerini, BW hafif gölgelendirmesini ve 0,707 yatay kesim çizgisini gösterir.
    /// </summary>
    public partial class ResonanceCurveView : UserControl
    {
        public event EventHandler? EnlargeClicked;

        private ResonanceDto? _data;
        private double _freqScale = 1.0;
        private string _freqUnit = "Hz";
        private ScottPlot.Plottables.Crosshair? _crosshair;

        public bool IsEnlarged
        {
            get => BtnEnlarge.Visibility == Visibility.Collapsed;
            set => BtnEnlarge.Visibility = value ? Visibility.Collapsed : Visibility.Visible;
        }

        public ResonanceCurveView()
        {
            InitializeComponent();
        }

        public void LoadData(ResonanceDto data)
        {
            _data = data;
            if (data == null) return;

            // Frekans birimi seçimi: f0 >= 1000 veya eğri tepe noktası >= 1000 ise kHz
            bool hasCurve = data.Curve != null
                && data.Curve.F != null
                && data.Curve.Y != null
                && data.Curve.F.Count > 0
                && data.Curve.F.Count == data.Curve.Y.Count;

            double maxF = data.F0;
            if (hasCurve && data.Curve?.F is { Count: > 0 } fList)
            {
                maxF = Math.Max(maxF, fList.Max());
            }

            if (maxF >= 1e6)
            {
                _freqUnit = "MHz";
                _freqScale = 1e-6;
            }
            else if (maxF >= 1000)
            {
                _freqUnit = "kHz";
                _freqScale = 1e-3;
            }
            else
            {
                _freqUnit = "Hz";
                _freqScale = 1.0;
            }

            TxtSummaryInfo.Text = $"f₀ = {EngFormat.Format(data.F0, "Hz")} | Q = {TurkishNumber.Format(data.Q, "G4")} | BW = {EngFormat.Format(data.Bw, "Hz")}";

            RenderPlot();
        }

        private void RenderPlot()
        {
            if (_data == null) return;

            var plot = PlotResonance.Plot;
            plot.Clear();

            var bgCol = GetThemeColor("Brush.Bg.Surface");
            var subTextCol = GetThemeColor("Brush.Text.Secondary");
            var gridCol = GetThemeColor("Brush.Border.Default");
            var markerCol = GetThemeColor("Brush.Text.Tertiary");
            var curveCol = GetThemeColor("Brush.Accent");

            plot.FigureBackground.Color = bgCol;
            plot.DataBackground.Color = bgCol;
            plot.Axes.Color(subTextCol);
            plot.Grid.MajorLineColor = gridCol;

            bool isParallel = string.Equals(_data.Kind, "parallel", StringComparison.OrdinalIgnoreCase);
            bool hasCurve = _data.Curve != null
                && _data.Curve.F != null
                && _data.Curve.Y != null
                && _data.Curve.F.Count > 0
                && _data.Curve.F.Count == _data.Curve.Y.Count;

            double f1 = _data.F1Exact > 0 ? _data.F1Exact : _data.F1;
            double f2 = _data.F2Exact > 0 ? _data.F2Exact : _data.F2;

            // f1-f2 arası hafif gölgeli (BW) - eğrinin altında kalsın diye önce eklenir
            if (f1 > 0 && f2 > f1)
            {
                var hspan = plot.Add.HorizontalSpan(f1 * _freqScale, f2 * _freqScale);
                hspan.FillColor = new ScottPlot.Color(curveCol.R, curveCol.G, curveCol.B, 30);
                hspan.LineColor = ScottPlot.Colors.Transparent;
            }

            // Dikey kesikli çizgiler ve etiketler: f0, f1, f2
            if (_data.F0 > 0)
            {
                var vl0 = plot.Add.VerticalLine(_data.F0 * _freqScale);
                vl0.LinePattern = ScottPlot.LinePattern.Dashed;
                vl0.Color = markerCol;
                vl0.LineWidth = 1.2f;
                vl0.Text = "f₀";
            }
            if (f1 > 0)
            {
                var vl1 = plot.Add.VerticalLine(f1 * _freqScale);
                vl1.LinePattern = ScottPlot.LinePattern.Dashed;
                vl1.Color = markerCol;
                vl1.LineWidth = 1.0f;
                vl1.Text = "f₁";
            }
            if (f2 > 0)
            {
                var vl2 = plot.Add.VerticalLine(f2 * _freqScale);
                vl2.LinePattern = ScottPlot.LinePattern.Dashed;
                vl2.Color = markerCol;
                vl2.LineWidth = 1.0f;
                vl2.Text = "f₂";
            }

            // Yatay kesikli çizgi: seride I_max * 0.707 (i0 * 0.707), paralelde Z0 * 0.707 (z0 * 0.707), etiket "0,707"
            double peak = isParallel ? _data.Z0 : _data.I0;
            if (peak <= 0 && hasCurve && _data.Curve?.Y is { Count: > 0 } curveYList)
            {
                peak = curveYList.Max();
            }
            double cutoffLevel = peak * 0.707;
            if (cutoffLevel > 0)
            {
                var hl = plot.Add.HorizontalLine(cutoffLevel);
                hl.LinePattern = ScottPlot.LinePattern.Dashed;
                hl.Color = markerCol;
                hl.LineWidth = 1.0f;
                hl.Text = "0,707";
            }

            // Eğri noktalarını çiz
            var curve = _data.Curve;
            if (hasCurve && curve?.F is { } fList && curve.Y is { } yList)
            {
                double[] xVals = new double[fList.Count];
                double[] yVals = new double[yList.Count];
                for (int i = 0; i < xVals.Length; i++)
                {
                    xVals[i] = fList[i] * _freqScale;
                    yVals[i] = yList[i];
                }

                var scatter = plot.Add.Scatter(xVals, yVals, curveCol);
                scatter.LineWidth = 2.5f;
                scatter.MarkerSize = 0;

                double xMin = xVals.Min();
                double xMax = xVals.Max();
                double yMin = yVals.Min();
                double yMax = yVals.Max();

                if (_data.F0 > 0)
                {
                    xMin = Math.Min(xMin, _data.F0 * _freqScale);
                    xMax = Math.Max(xMax, _data.F0 * _freqScale);
                }
                if (f1 > 0) xMin = Math.Min(xMin, f1 * _freqScale);
                if (f2 > 0) xMax = Math.Max(xMax, f2 * _freqScale);

                double xSpan = Math.Max(1e-6, xMax - xMin);
                double ySpan = Math.Max(1e-6, yMax - yMin);
                plot.Axes.SetLimits(
                    xMin - xSpan * 0.05,
                    xMax + xSpan * 0.05,
                    Math.Max(0, yMin - ySpan * 0.1),
                    yMax + ySpan * 0.15);
            }
            else
            {
                double xCenter = _data.F0 > 0 ? _data.F0 * _freqScale : 1000 * _freqScale;
                double span = _data.Bw > 0 ? _data.Bw * _freqScale * 3 : Math.Max(100 * _freqScale, xCenter * 0.5);
                double yTop = Math.Max(1.0, peak > 0 ? peak * 1.2 : 1.0);
                plot.Axes.SetLimits(Math.Max(0, xCenter - span), xCenter + span, 0, yTop);
            }

            // Eksen ve başlık
            plot.Title("Rezonans Eğrisi");
            plot.XLabel($"Frekans ({_freqUnit})");
            plot.YLabel(isParallel ? "Empedans (Ω)" : "Akım (A)");

            // Sayı biçimlendirici (Türkçe ondalık virgülü)
            var autoBottom = new ScottPlot.TickGenerators.NumericAutomatic
            {
                LabelFormatter = pos => TurkishNumber.Format(pos, "G4")
            };
            plot.Axes.Bottom.TickGenerator = autoBottom;

            var autoLeft = new ScottPlot.TickGenerators.NumericAutomatic
            {
                LabelFormatter = pos => TurkishNumber.Format(pos, "G4")
            };
            plot.Axes.Left.TickGenerator = autoLeft;

            // Crosshair (fare ile gezinme)
            _crosshair = plot.Add.Crosshair(0, 0);
            _crosshair.IsVisible = false;
            _crosshair.LineColor = curveCol;
            _crosshair.LinePattern = ScottPlot.LinePattern.Dotted;

            PlotResonance.Refresh();
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

        private void PlotResonance_MouseMove(object sender, MouseEventArgs e)
        {
            if (_data?.Curve == null || _crosshair == null || _data.Curve.F == null || _data.Curve.Y == null || _data.Curve.F.Count == 0)
                return;

            var pos = e.GetPosition(PlotResonance);
            var pixel = new ScottPlot.Pixel(pos.X, pos.Y);
            var coords = PlotResonance.Plot.GetCoordinates(pixel);

            double fScaled = coords.X;
            var fList = _data.Curve.F;
            var yList = _data.Curve.Y;

            if (fList.Count != yList.Count || fList.Count == 0)
            {
                _crosshair.IsVisible = false;
                PlotResonance.Refresh();
                TxtHover.Text = "";
                return;
            }

            double fMinScaled = fList[0] * _freqScale;
            double fMaxScaled = fList[^1] * _freqScale;
            if (fMinScaled > fMaxScaled)
            {
                (fMinScaled, fMaxScaled) = (fMaxScaled, fMinScaled);
            }

            if (fScaled < fMinScaled || fScaled > fMaxScaled)
            {
                _crosshair.IsVisible = false;
                PlotResonance.Refresh();
                TxtHover.Text = "";
                return;
            }

            // En yakın frekans noktasını bul
            int bestIdx = 0;
            double bestDist = Math.Abs(fList[0] * _freqScale - fScaled);
            for (int i = 1; i < fList.Count; i++)
            {
                double dist = Math.Abs(fList[i] * _freqScale - fScaled);
                if (dist < bestDist)
                {
                    bestDist = dist;
                    bestIdx = i;
                }
            }

            double nearestFScaled = fList[bestIdx] * _freqScale;
            double nearestY = yList[bestIdx];

            _crosshair.Position = new ScottPlot.Coordinates(nearestFScaled, nearestY);
            _crosshair.IsVisible = true;
            PlotResonance.Refresh();

            bool isParallel = string.Equals(_data.Kind, "parallel", StringComparison.OrdinalIgnoreCase);
            string yQuantity = !string.IsNullOrEmpty(_data.Curve.Quantity)
                ? _data.Curve.Quantity
                : (isParallel ? "Z" : "I");
            string yUnit = !string.IsNullOrEmpty(_data.Curve.Unit)
                ? _data.Curve.Unit
                : (isParallel ? "Ω" : "A");

            TxtHover.Text = $"f = {TurkishNumber.Format(nearestFScaled, "G4")} {_freqUnit}, {yQuantity} = {TurkishNumber.Format(nearestY, "G4")} {yUnit}";
        }

        private void PlotResonance_MouseLeave(object sender, MouseEventArgs e)
        {
            if (_crosshair != null)
            {
                _crosshair.IsVisible = false;
                PlotResonance.Refresh();
            }
            TxtHover.Text = "";
        }

        private void BtnEnlarge_Click(object sender, RoutedEventArgs e)
        {
            EnlargeClicked?.Invoke(this, EventArgs.Empty);
        }
    }
}
