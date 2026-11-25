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
            set
            {
                BtnEnlarge.Visibility = value ? Visibility.Collapsed : Visibility.Visible;
                // Büyütülmüş pencerenin kendi başlığı var; kart başlığı iki kez görünmesin
                TxtHeaderTitle.Visibility = value ? Visibility.Collapsed : Visibility.Visible;
            }
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
            (_freqScale, _freqUnit) = FreqUnitFor(data);

            TxtSummaryInfo.Text = $"f₀ = {EngFormat.Format(data.F0, "Hz")} | Q = {TurkishNumber.Format(data.Q, "G4")} | BW = {EngFormat.Format(data.Bw, "Hz")}";
            SubscriptText.Apply(TxtSummaryInfo);

            RenderPlot();
        }

        private void RenderPlot()
        {
            if (_data == null) return;

            double w = PlotMarkers.DataWidthPx(PlotResonance.ActualWidth);
            double h = PlotMarkers.DataHeightPx(PlotResonance.ActualHeight);
            _builtForSize = w > 0 && h > 0;
            _crosshair = BuildPlot(PlotResonance.Plot, _data, _freqScale, _freqUnit, w, h, GetThemeColor);
            PlotResonance.Refresh();
        }

        /// <summary>Çizim, kontrolün gerçek ölçüsüyle mi kuruldu (yerleşimden önce kurulduysa ilk ölçüde yenilenir).</summary>
        private bool _builtForSize;

        private void PlotResonance_SizeChanged(object sender, SizeChangedEventArgs e)
        {
            if (!_builtForSize && _data != null)
                RenderPlot();
        }

        /// <summary>Eğrinin frekans birimi: en büyük frekans 1 MHz ve üstüyse MHz, 1 kHz ve üstüyse kHz.</summary>
        internal static (double Scale, string Unit) FreqUnitFor(ResonanceDto data)
        {
            double maxF = data.F0;
            if (data.Curve?.F is { Count: > 0 } fList && data.Curve.Y != null && data.Curve.Y.Count == fList.Count)
                maxF = Math.Max(maxF, fList.Max());
            if (maxF >= 1e6) return (1e-6, "MHz");
            if (maxF >= 1000) return (1e-3, "kHz");
            return (1.0, "Hz");
        }

        /// <summary>
        /// Rezonans eğrisini verilen <paramref name="plot"/>'a kurar. Ekrandaki kontrol uygulama
        /// temasının, yazdırma açık temanın renkleriyle (ekran dışı) çağırır.
        /// </summary>
        internal static ScottPlot.Plottables.Crosshair BuildPlot(
            Plot plot, ResonanceDto data, double freqScale, string freqUnit,
            double dataWidth, double dataHeight, Func<string, ScottPlot.Color> color)
        {
            plot.Clear();

            var bgCol = color("Brush.Bg.Surface");
            var subTextCol = color("Brush.Text.Secondary");
            var gridCol = color("Brush.Border.Default");
            var markerCol = color("Brush.Text.Tertiary");
            var curveCol = color("Brush.Accent");

            plot.FigureBackground.Color = bgCol;
            plot.DataBackground.Color = bgCol;
            plot.Axes.Color(subTextCol);
            plot.Grid.MajorLineColor = gridCol;

            bool isParallel = string.Equals(data.Kind, "parallel", StringComparison.OrdinalIgnoreCase);
            bool hasCurve = data.Curve != null
                && data.Curve.F != null
                && data.Curve.Y != null
                && data.Curve.F.Count > 0
                && data.Curve.F.Count == data.Curve.Y.Count;

            double f1 = data.F1Exact > 0 ? data.F1Exact : data.F1;
            double f2 = data.F2Exact > 0 ? data.F2Exact : data.F2;

            // f1-f2 arası hafif gölgeli (BW) - eğrinin altında kalsın diye önce eklenir
            if (f1 > 0 && f2 > f1)
            {
                var hspan = plot.Add.HorizontalSpan(f1 * freqScale, f2 * freqScale);
                hspan.FillColor = new ScottPlot.Color(curveCol.R, curveCol.G, curveCol.B, 30);
                hspan.LineColor = ScottPlot.Colors.Transparent;
            }

            // Dikey kesikli çizgiler: f0, f1, f2. Adları eksen sayılarının üstüne binmesin diye eğrinin
            // üstündeki rozet bandına yazılır (yakın çıkarlarsa alt alta satırlara).
            var markers = new List<(double X, string Text)>();
            if (data.F0 > 0)
            {
                var vl0 = plot.Add.VerticalLine(data.F0 * freqScale);
                vl0.LinePattern = ScottPlot.LinePattern.Dashed;
                vl0.Color = markerCol;
                vl0.LineWidth = 1.2f;
                markers.Add((data.F0 * freqScale, "f₀"));
            }
            if (f1 > 0)
            {
                var vl1 = plot.Add.VerticalLine(f1 * freqScale);
                vl1.LinePattern = ScottPlot.LinePattern.Dashed;
                vl1.Color = markerCol;
                vl1.LineWidth = 1.0f;
                markers.Add((f1 * freqScale, "f₁"));
            }
            if (f2 > 0)
            {
                var vl2 = plot.Add.VerticalLine(f2 * freqScale);
                vl2.LinePattern = ScottPlot.LinePattern.Dashed;
                vl2.Color = markerCol;
                vl2.LineWidth = 1.0f;
                markers.Add((f2 * freqScale, "f₂"));
            }
            var textCol = color("Brush.Text.Primary");

            // Yatay kesikli çizgi: seride I_max * 0.707 (i0 * 0.707), paralelde Z0 * 0.707 (z0 * 0.707), etiket "0,707"
            double peak = isParallel ? data.Z0 : data.I0;
            if (peak <= 0 && hasCurve && data.Curve?.Y is { Count: > 0 } curveYList)
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
                // Etiketi eksen sayılarının üstüne değil, çizim alanına (eksen sınırları belli olunca)
            }
            // Eksen paralelde Ω, seride A: etiket neyin 0,707 katı olduğunu söylesin
            string cutoffText = isParallel ? "0,707·Z₀" : "0,707·Iₘₐₓ";

            // Eğri noktalarını çiz
            var curve = data.Curve;
            if (hasCurve && curve?.F is { } fList && curve.Y is { } yList)
            {
                double[] xVals = new double[fList.Count];
                double[] yVals = new double[yList.Count];
                for (int i = 0; i < xVals.Length; i++)
                {
                    xVals[i] = fList[i] * freqScale;
                    yVals[i] = yList[i];
                }

                var scatter = plot.Add.Scatter(xVals, yVals, curveCol);
                scatter.LineWidth = 2.5f;
                scatter.MarkerSize = 0;

                double xMin = xVals.Min();
                double xMax = xVals.Max();
                double yMin = yVals.Min();
                double yMax = yVals.Max();

                if (data.F0 > 0)
                {
                    xMin = Math.Min(xMin, data.F0 * freqScale);
                    xMax = Math.Max(xMax, data.F0 * freqScale);
                }
                if (f1 > 0) xMin = Math.Min(xMin, f1 * freqScale);
                if (f2 > 0) xMax = Math.Max(xMax, f2 * freqScale);

                double xSpan = Math.Max(1e-6, xMax - xMin);
                double ySpan = Math.Max(1e-6, yMax - yMin);
                double left = xMin - xSpan * 0.05, right = xMax + xSpan * 0.05;
                double bottom = Math.Max(0, yMin - ySpan * 0.1);
                double yTop = PlotMarkers.AddBadges(plot, markers, left, right, bottom, yMax + ySpan * 0.05,
                    dataWidth, dataHeight, 14f, textCol, bgCol, gridCol);
                plot.Axes.SetLimits(left, right, bottom, yTop);
                PlotMarkers.ApplyBottomTicks(plot, left, right, dataWidth);
                if (cutoffLevel > 0)
                    PlotMarkers.AddHalfPowerLabel(plot, cutoffText, cutoffLevel, left, right,
                        f1 * freqScale, f2 * freqScale, 12f, textCol, bgCol, gridCol);
            }
            else
            {
                double xCenter = data.F0 > 0 ? data.F0 * freqScale : 1000 * freqScale;
                double span = data.Bw > 0 ? data.Bw * freqScale * 3 : Math.Max(100 * freqScale, xCenter * 0.5);
                double yData = Math.Max(1.0, peak > 0 ? peak * 1.05 : 1.0);
                double left = Math.Max(0, xCenter - span), right = xCenter + span;
                double yTop = PlotMarkers.AddBadges(plot, markers, left, right, 0, yData, dataWidth, dataHeight,
                    14f, textCol, bgCol, gridCol);
                plot.Axes.SetLimits(left, right, 0, yTop);
                PlotMarkers.ApplyBottomTicks(plot, left, right, dataWidth);
                if (cutoffLevel > 0)
                    PlotMarkers.AddHalfPowerLabel(plot, cutoffText, cutoffLevel, left, right,
                        f1 * freqScale, f2 * freqScale, 12f, textCol, bgCol, gridCol);
            }

            // Eksen ve başlık
            // Başlık kartın üstünde (küçük kart) ya da büyütülmüş pencerenin başlığında zaten yazıyor;
            // grafiğin içinde üçüncü kez tekrarlanmaz.
            plot.Title("");
            plot.XLabel($"Frekans ({freqUnit})");
            plot.YLabel(isParallel ? "Empedans (Ω)" : "Akım (A)");

            // Sayı biçimlendirici (Türkçe ondalık virgülü, Unicode eksi); alt eksen yukarıda (ApplyBottomTicks)
            PlotMarkers.ApplyLeftTicks(plot);

            // Crosshair (fare ile gezinme)
            var crosshair = plot.Add.Crosshair(0, 0);
            crosshair.IsVisible = false;
            crosshair.LineColor = curveCol;
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

        private void PlotResonance_MouseMove(object sender, MouseEventArgs e)
        {
            if (_data?.Curve == null || _crosshair == null || _data.Curve.F == null || _data.Curve.Y == null || _data.Curve.F.Count == 0)
                return;

            // Ekran ölçeği (%125/%150) hesaba katılır; bkz. PlotMouse.
            var pixel = PlotMouse.ToPlotPixel(PlotResonance, e);
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
