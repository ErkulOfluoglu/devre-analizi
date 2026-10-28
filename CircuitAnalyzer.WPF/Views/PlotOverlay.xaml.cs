using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Büyütülmüş zaman grafiği için pencere içi katman (ayrı Window açmaz).
    /// Karartma perdesi ve ortalanmış kart içerir; Esc veya Kapat düğmesi kapatır.
    /// </summary>
    public partial class PlotOverlay : UserControl
    {
        public event Action? Closed;

        public bool IsOpen => Visibility == Visibility.Visible;

        public PlotOverlay()
        {
            InitializeComponent();
            Visibility = Visibility.Collapsed;
            SizeChanged += (_, _) => UpdateCardMaxHeight();
        }

        private void UpdateCardMaxHeight()
        {
            double h = ActualHeight;
            if (h <= 0 && Window.GetWindow(this) is { } w)
                h = w.ActualHeight;
            if (h > 60)
                CardBorder.MaxHeight = Math.Max(200, h - 40);
        }

        public void Show(TransientAnalysisDto data, bool animate = true)
        {
            var plotView = new TransientPlotView
            {
                IsEnlarged = true
            };
            plotView.LoadData(data);
            PlotHost.Child = plotView;

            Visibility = Visibility.Visible;
            UpdateCardMaxHeight();
            Focus();
            Keyboard.Focus(BtnClose);

            if (!animate)
            {
                Opacity = 1;
                CardScale.ScaleX = 1;
                CardScale.ScaleY = 1;
                return;
            }

            var duration = TimeSpan.FromMilliseconds(180);
            var ease = new QuadraticEase { EasingMode = EasingMode.EaseOut };
            BeginAnimation(OpacityProperty, new DoubleAnimation(0, 1, duration) { EasingFunction = ease });
            CardScale.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(0.97, 1.0, duration) { EasingFunction = ease });
            CardScale.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(0.97, 1.0, duration) { EasingFunction = ease });
        }

        public void Close(bool animate = true)
        {
            if (!IsOpen) return;

            void Finish()
            {
                Visibility = Visibility.Collapsed;
                BeginAnimation(OpacityProperty, null);
                Opacity = 1;
                PlotHost.Child = null;
                Closed?.Invoke();
            }

            if (!animate)
            {
                Finish();
                return;
            }

            var fade = new DoubleAnimation(Opacity, 0, TimeSpan.FromMilliseconds(120));
            fade.Completed += (_, _) => Finish();
            BeginAnimation(OpacityProperty, fade);
        }

        private void BtnClose_Click(object sender, RoutedEventArgs e) => Close();

        private void Scrim_MouseDown(object sender, MouseButtonEventArgs e) => e.Handled = true;

        private void Card_MouseDown(object sender, MouseButtonEventArgs e) => e.Handled = true;

        protected override void OnPreviewKeyDown(KeyEventArgs e)
        {
            base.OnPreviewKeyDown(e);
            if (e.Handled) return;

            if (e.Key == Key.Escape)
            {
                e.Handled = true;
                Close();
            }
        }
    }
}
