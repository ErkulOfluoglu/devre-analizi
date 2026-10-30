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

        public void LoadData(TransientAnalysisDto data)
        {
            _data = data;
            if (data == null || data.Quantities == null || data.Quantities.Count == 0)
                return;

            double tau = data.Tau;
            if (tau <= 0) tau = 1e-3;

            // Zaman birimi seçimi
            if (tau < 1e-6)
            {
                _timeUnit = "ns";
                _timeScale = 1e9;
            }
            else if (tau < 1e-3)
            {
                _timeUnit = "µs";
                _timeScale = 1e6;
            }
            else if (tau < 1.0)
            {
                _timeUnit = "ms";
                _timeScale = 1e3;
            }
            else
            {
                _timeUnit = "s";
                _timeScale = 1.0;
            }

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
            var plot = wpfPlot.Plot;
            plot.Clear();

            double tau = _data!.Tau;
            if (tau <= 0) tau = 1e-3;

            // Renkler (Temadan)
            var bgCol = GetThemeColor("Brush.Bg.Surface");
            var textCol = GetThemeColor("Brush.Text.Primary");
            var subTextCol = GetThemeColor("Brush.Text.Secondary");
            var gridCol = GetThemeColor("Brush.Border.Default");
            var markerCol = GetThemeColor("Brush.Text.Tertiary");
            var curveCol = isTop
                ? GetThemeColor("Brush.Accent")
                : GetThemeColor("Brush.Overlay.Current");

            plot.FigureBackground.Color = bgCol;
            plot.DataBackground.Color = bgCol;
            plot.Axes.Color(subTextCol);
            plot.Grid.MajorLineColor = gridCol;

            // Eğri noktalarını oluştur
            var xList = new List<double>();
            var yList = new List<double>();

            // t < 0 kısmı
            int preSteps = 30;
            double dtPre = (0 - _tMinSeconds) / preSteps;
            for (int i = 0; i < preSteps; i++)
            {
                double t = _tMinSeconds + i * dtPre;
                xList.Add(t * _timeScale);
                yList.Add(q.Before);
            }

            // t = 0 anı (sıçrama varsa hem before hem start ekle)
            xList.Add(0.0);
            yList.Add(q.Before);
            if (Math.Abs(q.Before - q.Start) > 1e-12)
            {
                xList.Add(0.0);
                yList.Add(q.Start);
            }

            // t > 0 kısmı (0'dan 5τ'ya)
            int postSteps = 170;
            double dtPost = _tMaxSeconds / postSteps;
            for (int i = 1; i <= postSteps; i++)
            {
                double t = i * dtPost;
                double val = TransientCurveCalculator.Evaluate(q.Before, q.Start, q.Final, tau, t);
                xList.Add(t * _timeScale);
                yList.Add(val);
            }

            // Eğriyi çiz
            var scatter = plot.Add.Scatter(xList.ToArray(), yList.ToArray(), curveCol);
            scatter.LineWidth = 2.5f;
            scatter.MarkerSize = 0;

            // Yatay kesikli çizgi: Final (t -> sonsuz) değeri
            var hFinal = plot.Add.HorizontalLine(q.Final);
            hFinal.LinePattern = ScottPlot.LinePattern.Dashed;
            hFinal.Color = markerCol;
            hFinal.LineWidth = 1.2f;

            // Dikey kesikli çizgiler: τ, 2τ, 3τ, 4τ, 5τ
            for (int k = 1; k <= 5; k++)
            {
                double tMarker = k * tau * _timeScale;
                var vl = plot.Add.VerticalLine(tMarker);
                vl.LinePattern = ScottPlot.LinePattern.Dashed;
                vl.Color = markerCol;
                vl.LineWidth = 1.0f;
                vl.Text = k == 1 ? "τ" : $"{k}τ";
            }

            // Eksen etiketleri
            plot.Title($"{SubscriptText.Plain(q.Label)} ({q.Unit})");
            plot.XLabel($"Zaman ({_timeUnit})");
            plot.YLabel(q.Unit);

            // Eksen sınırları
            double xMin = _tMinSeconds * _timeScale;
            double xMax = _tMaxSeconds * _timeScale;

            double yMin = Math.Min(q.Before, Math.Min(q.Start, q.Final));
            double yMax = Math.Max(q.Before, Math.Max(q.Start, q.Final));
            double ySpan = Math.Max(1e-6, yMax - yMin);
            plot.Axes.SetLimits(xMin, xMax, yMin - ySpan * 0.15, yMax + ySpan * 0.15);

            // Eksen sayı formatlayıcıları (Türkçe ondalık virgülü)
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
            crosshair = plot.Add.Crosshair(0, 0);
            crosshair.IsVisible = false;
            crosshair.LineColor = curveCol;
            crosshair.LinePattern = ScottPlot.LinePattern.Dotted;

            wpfPlot.Refresh();
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

            var pos = e.GetPosition(wpfPlot);
            var pixel = new ScottPlot.Pixel(pos.X, pos.Y);
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

            double val = TransientCurveCalculator.Evaluate(q.Before, q.Start, q.Final, _data.Tau, tSeconds);
            crosshair.Position = new ScottPlot.Coordinates(tScaled, val);
            crosshair.IsVisible = true;
            wpfPlot.Refresh();

            txtHover.Text = $"t = {TurkishNumber.Format(tScaled, "G4")} {_timeUnit}, {q.Label} = {TurkishNumber.Format(val, "G4")} {q.Unit}";
            SubscriptText.Apply(txtHover);
        }

        private void BtnEnlarge_Click(object sender, RoutedEventArgs e)
        {
            EnlargeClicked?.Invoke(this, EventArgs.Empty);
        }
    }
}
