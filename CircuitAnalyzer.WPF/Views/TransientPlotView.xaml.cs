using System;
using System.Collections.Generic;
using System.Globalization;
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
    /// Geçici durum zaman grafikleri bileşeni (ScottPlot 5).
    /// Üstte depolayıcı eleman gerilimi, altta akımı gösterilir.
    /// </summary>
    public partial class TransientPlotView : UserControl
    {
        public event EventHandler? EnlargeClicked;

        private TransientAnalysisDto? _data;
        private double _timeScale = 1.0;
        private string _timeUnit = "s";
        private double _tMinSeconds;
        private double _tMaxSeconds;

        private ScottPlot.Plottables.Crosshair? _crosshairTop;
        private ScottPlot.Plottables.Crosshair? _crosshairBottom;

        private TransientQuantityDto? _currentTopQuantity;
        private TransientQuantityDto? _currentBottomQuantity;

        public bool IsEnlarged
        {
            get => BtnEnlarge.Visibility == Visibility.Collapsed;
            set => BtnEnlarge.Visibility = value ? Visibility.Collapsed : Visibility.Visible;
        }

        public TransientPlotView()
        {
            InitializeComponent();
        }

        /// <summary>Eksenin en büyük zamanına (s) göre birim: 1,5 s → s, 10 ms → ms, 50 µs → µs.</summary>
        internal static (double Scale, string Unit) TimeUnitFor(double maxSeconds)
        {
            double t = Math.Abs(maxSeconds);
            if (t < 1e-6) return (1e9, "ns");
            if (t < 1e-3) return (1e6, "µs");
            if (t < 1.0) return (1e3, "ms");
            return (1.0, "s");
        }

        /// <summary>
        /// Değer ekseni önekli birimle: 6 mA'lik akım "0,006 A" yerine "6 mA" eksende görünür
        /// (anlatım metniyle aynı birim).
        /// </summary>
        internal static (double Scale, string Unit) ValueUnitFor(TransientQuantityDto q)
        {
            double m = Math.Max(Math.Abs(q.Before), Math.Max(Math.Abs(q.Start), Math.Abs(q.Final)));
            if (m == 0 || m >= 1 && m < 1e3) return (1.0, q.Unit);
            if (m >= 1e3) return (1e-3, "k" + q.Unit);
            if (m >= 1e-3) return (1e3, "m" + q.Unit);
            if (m >= 1e-6) return (1e6, "µ" + q.Unit);
            return (1e9, "n" + q.Unit);
        }

        public void LoadData(TransientAnalysisDto data)
        {
            _data = data;
            if (data == null || data.Quantities == null || data.Quantities.Count == 0)
                return;

            double tau = data.Tau;
            if (tau <= 0) tau = 1e-3;

            // Zaman birimi grafiğin sonuna (5τ) göre seçilir: τ = 0,3 s'de eksen "1500 ms" değil "1,5 s"
            (_timeScale, _timeUnit) = TimeUnitFor(5.0 * tau);

            _tMinSeconds = -0.5 * tau;
            _tMaxSeconds = 5.0 * tau;

            TxtTauInfo.Text = $"τ = {TurkishNumber.Format(tau * _timeScale, "G4")} {_timeUnit}  |  R_th = {EngFormat.Format(data.Rth, "Ω")}";
            SubscriptText.Apply(TxtTauInfo);

            // Seçiciler
            if (data.Quantities.Count > 2)
            {
                RowSelectors.Visibility = Visibility.Visible;
                CmbTopQuantity.ItemsSource = data.Quantities;
                CmbTopQuantity.DisplayMemberPath = "DisplayLabel";
                CmbBottomQuantity.ItemsSource = data.Quantities;
                CmbBottomQuantity.DisplayMemberPath = "DisplayLabel";

                CmbTopQuantity.SelectedIndex = 0;
                CmbBottomQuantity.SelectedIndex = 1;
            }
            else
            {
                RowSelectors.Visibility = Visibility.Collapsed;
                _currentTopQuantity = data.Quantities[0];
                _currentBottomQuantity = data.Quantities.Count > 1 ? data.Quantities[1] : data.Quantities[0];
                RenderBothPlots();
            }
        }

        private void CmbTopQuantity_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            if (CmbTopQuantity.SelectedItem is TransientQuantityDto q)
            {
                _currentTopQuantity = q;
                RenderTopPlot();
            }
        }

        private void CmbBottomQuantity_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            if (CmbBottomQuantity.SelectedItem is TransientQuantityDto q)
            {
                _currentBottomQuantity = q;
                RenderBottomPlot();
            }
        }

        private void RenderBothPlots()
        {
            RenderTopPlot();
            RenderBottomPlot();
        }

        private void RenderTopPlot()
        {
            if (_data == null || _currentTopQuantity == null) return;
            RenderPlot(PlotTop, _currentTopQuantity, isTop: true, out _crosshairTop);
        }

        private void RenderBottomPlot()
        {
            if (_data == null || _currentBottomQuantity == null) return;
            RenderPlot(PlotBottom, _currentBottomQuantity, isTop: false, out _crosshairBottom);
        }

        private void RenderPlot(
            WpfPlot wpfPlot,
            TransientQuantityDto q,
            bool isTop,
            out ScottPlot.Plottables.Crosshair crosshair)
        {
            double w = PlotMarkers.DataWidthPx(wpfPlot.ActualWidth);
            double h = PlotMarkers.DataHeightPx(wpfPlot.ActualHeight);
            if (isTop) _topBuiltForSize = w > 0 && h > 0;
            else _bottomBuiltForSize = w > 0 && h > 0;
            crosshair = BuildPlot(wpfPlot.Plot, _data!, q, isTop, w, h, GetThemeColor);
            wpfPlot.Refresh();
        }

        // Çizim kontrolün gerçek ölçüsüyle mi kuruldu (yerleşimden önce kurulduysa ilk ölçüde yenilenir)
        private bool _topBuiltForSize;
        private bool _bottomBuiltForSize;

        private void PlotTop_SizeChanged(object sender, SizeChangedEventArgs e)
        {
            if (!_topBuiltForSize)
                RenderTopPlot();
        }

        private void PlotBottom_SizeChanged(object sender, SizeChangedEventArgs e)
        {
            if (!_bottomBuiltForSize)
                RenderBottomPlot();
        }

        /// <summary>
        /// Bir büyüklüğün zaman grafiğini verilen <paramref name="plot"/>'a kurar. Ekrandaki kontrol
        /// uygulama temasının renkleriyle, yazdırma ise açık temanın renkleriyle (ekran dışı) çağırır.
        /// Dönüş: fare ile gezinme için (gizli) artı imleci.
        /// </summary>
        internal static ScottPlot.Plottables.Crosshair BuildPlot(
            Plot plot,
            TransientAnalysisDto data,
            TransientQuantityDto q,
            bool isTop,
            double dataWidth,
            double dataHeight,
            Func<string, ScottPlot.Color> color)
        {
            plot.Clear();

            double tau = data.Tau;
            if (tau <= 0) tau = 1e-3;
            var (timeScale, timeUnit) = TimeUnitFor(5.0 * tau);
            double tMinSeconds = -0.5 * tau;
            double tMaxSeconds = 5.0 * tau;

            // Renkler (temadan)
            var bgCol = color("Brush.Bg.Surface");
            var textCol = color("Brush.Text.Primary");
            var subTextCol = color("Brush.Text.Secondary");
            var gridCol = color("Brush.Border.Default");
            var markerCol = color("Brush.Text.Tertiary");
            var curveCol = isTop
                ? color("Brush.Accent")
                : color("Brush.Overlay.Current");

            plot.FigureBackground.Color = bgCol;
            plot.DataBackground.Color = bgCol;
            plot.Axes.Color(subTextCol);
            plot.Grid.MajorLineColor = gridCol;

            var (ys, yUnit) = ValueUnitFor(q);

            // Eğri noktalarını oluştur
            var xList = new List<double>();
            var yList = new List<double>();

            // t < 0 kısmı
            int preSteps = 30;
            double dtPre = (0 - tMinSeconds) / preSteps;
            for (int i = 0; i < preSteps; i++)
            {
                double t = tMinSeconds + i * dtPre;
                xList.Add(t * timeScale);
                yList.Add(q.Before * ys);
            }

            // t = 0 anı (sıçrama varsa hem before hem start ekle)
            xList.Add(0.0);
            yList.Add(q.Before * ys);
            if (Math.Abs(q.Before - q.Start) > 1e-12)
            {
                xList.Add(0.0);
                yList.Add(q.Start * ys);
            }

            // t > 0 kısmı (0'dan 5τ'ya)
            int postSteps = 170;
            double dtPost = tMaxSeconds / postSteps;
            for (int i = 1; i <= postSteps; i++)
            {
                double t = i * dtPost;
                double val = TransientCurveCalculator.Evaluate(q.Before, q.Start, q.Final, tau, t);
                xList.Add(t * timeScale);
                yList.Add(val * ys);
            }

            // Eğriyi çiz
            var scatter = plot.Add.Scatter(xList.ToArray(), yList.ToArray(), curveCol);
            scatter.LineWidth = 2.5f;
            scatter.MarkerSize = 0;

            // Yatay kesikli çizgi: Final (t -> sonsuz) değeri
            var hFinal = plot.Add.HorizontalLine(q.Final * ys);
            hFinal.LinePattern = ScottPlot.LinePattern.Dashed;
            hFinal.Color = markerCol;
            hFinal.LineWidth = 1.2f;

            // Dikey kesikli çizgiler: τ, 2τ, 3τ, 4τ, 5τ. Adları eksen sayılarının üstüne binmesin diye
            // çizginin kendisine değil, eğrinin üstündeki rozet bandına yazılır.
            var markers = new List<(double X, string Text)>();
            for (int k = 1; k <= 5; k++)
            {
                double tMarker = k * tau * timeScale;
                var vl = plot.Add.VerticalLine(tMarker);
                vl.LinePattern = ScottPlot.LinePattern.Dashed;
                vl.Color = markerCol;
                vl.LineWidth = 1.0f;
                markers.Add((tMarker, k == 1 ? "τ" : $"{k}τ"));
            }

            // Eksen etiketleri
            plot.Title($"{SubscriptText.Plain(q.Label)} ({yUnit})");
            plot.XLabel($"Zaman ({timeUnit})");
            plot.YLabel(yUnit);

            // Eksen sınırları
            double xMin = tMinSeconds * timeScale;
            double xMax = tMaxSeconds * timeScale;

            double yMin = Math.Min(q.Before, Math.Min(q.Start, q.Final)) * ys;
            double yMax = Math.Max(q.Before, Math.Max(q.Start, q.Final)) * ys;
            double ySpan = Math.Max(1e-6, yMax - yMin);
            double yBottom = yMin - ySpan * 0.15;
            double yTop = PlotMarkers.AddBadges(plot, markers, xMin, xMax, yBottom, yMax + ySpan * 0.05,
                dataWidth, dataHeight, 12f, textCol, bgCol, gridCol);
            plot.Axes.SetLimits(xMin, xMax, yBottom, yTop);

            // Eksen sayıları: okunur sayıda yuvarlak işaret (Türkçe ondalık virgülü, Unicode eksi)
            PlotMarkers.ApplyBottomTicks(plot, xMin, xMax, dataWidth);
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

        private void PlotTop_MouseMove(object sender, MouseEventArgs e)
        {
            HandlePlotMouseMove(PlotTop, _crosshairTop, _currentTopQuantity, TxtHoverTop, e);
        }

        private void PlotTop_MouseLeave(object sender, MouseEventArgs e)
        {
            if (_crosshairTop != null)
            {
                _crosshairTop.IsVisible = false;
                PlotTop.Refresh();
            }
            TxtHoverTop.Text = "";
        }

        private void PlotBottom_MouseMove(object sender, MouseEventArgs e)
        {
            HandlePlotMouseMove(PlotBottom, _crosshairBottom, _currentBottomQuantity, TxtHoverBottom, e);
        }

        private void PlotBottom_MouseLeave(object sender, MouseEventArgs e)
        {
            if (_crosshairBottom != null)
            {
                _crosshairBottom.IsVisible = false;
                PlotBottom.Refresh();
            }
            TxtHoverBottom.Text = "";
        }

        private void HandlePlotMouseMove(
            WpfPlot wpfPlot,
            ScottPlot.Plottables.Crosshair? crosshair,
            TransientQuantityDto? q,
            TextBlock txtHover,
            MouseEventArgs e)
        {
            if (_data == null || q == null || crosshair == null) return;

            // Ekran ölçeği (%125/%150) hesaba katılır; bkz. PlotMouse.
            var pixel = PlotMouse.ToPlotPixel(wpfPlot, e);
            var coords = wpfPlot.Plot.GetCoordinates(pixel);

            double tScaled = coords.X;
            double tSeconds = tScaled / _timeScale;

            if (tSeconds < _tMinSeconds || tSeconds > _tMaxSeconds)
            {
                crosshair.IsVisible = false;
                wpfPlot.Refresh();
                txtHover.Text = "";
                return;
            }

            var (ys, yUnit) = ValueUnitFor(q);
            double val = TransientCurveCalculator.Evaluate(q.Before, q.Start, q.Final, _data.Tau, tSeconds) * ys;
            crosshair.Position = new ScottPlot.Coordinates(tScaled, val);
            crosshair.IsVisible = true;
            wpfPlot.Refresh();

            txtHover.Text = $"t = {TurkishNumber.FormatDisplay(tScaled, "G4")} {_timeUnit}, {q.Label} = {TurkishNumber.FormatDisplay(val, "G4")} {yUnit}";
            SubscriptText.Apply(txtHover);
        }

        private void BtnEnlarge_Click(object sender, RoutedEventArgs e)
        {
            EnlargeClicked?.Invoke(this, EventArgs.Empty);
        }
    }
}
