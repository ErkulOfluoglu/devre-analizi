using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Ana pencere üzerinde gösterilen in-window "Hakkında" katmanı.
    /// </summary>
    public partial class AboutOverlay : UserControl
    {
        public AboutView View => AboutContent;

        public event Action? Closed;

        public AboutOverlay()
        {
            InitializeComponent();
            Visibility = Visibility.Collapsed;

            SizeChanged += (_, _) => UpdateCardMaxHeight();
            Loaded += (_, _) => UpdateCardMaxHeight();
        }

        public void UpdateCardMaxHeight()
        {
            double h = ActualHeight;
            if (h <= 0 && Parent is FrameworkElement fe)
            {
                h = fe.ActualHeight;
            }
            if (h <= 0 && Window.GetWindow(this) is { } w)
            {
                h = w.ActualHeight;
            }

            if (h > 48)
            {
                CardBorder.MaxHeight = Math.Max(100, h - 48);
            }
        }

        public void Show(bool animate = true)
        {
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

            var fadeAnim = new DoubleAnimation(0, 1, duration) { EasingFunction = ease };
            var scaleXAnim = new DoubleAnimation(0.97, 1.0, duration) { EasingFunction = ease };
            var scaleYAnim = new DoubleAnimation(0.97, 1.0, duration) { EasingFunction = ease };

            BeginAnimation(OpacityProperty, fadeAnim);
            CardScale.BeginAnimation(ScaleTransform.ScaleXProperty, scaleXAnim);
            CardScale.BeginAnimation(ScaleTransform.ScaleYProperty, scaleYAnim);
        }

        public void Close(bool animate = true)
        {
            if (Visibility != Visibility.Visible) return;

            void Finish()
            {
                Visibility = Visibility.Collapsed;
                Opacity = 1;
                CardScale.ScaleX = 1;
                CardScale.ScaleY = 1;
                Closed?.Invoke();
            }

            if (!animate)
            {
                Finish();
                return;
            }

            var duration = TimeSpan.FromMilliseconds(120);
            var fadeAnim = new DoubleAnimation(Opacity, 0, duration);
            fadeAnim.Completed += (_, _) => Finish();
            BeginAnimation(OpacityProperty, fadeAnim);
        }

        private void BtnClose_Click(object sender, RoutedEventArgs e)
        {
            Close();
        }

        private void Scrim_MouseDown(object sender, MouseButtonEventArgs e)
        {
            e.Handled = true;
        }

        private void Card_MouseDown(object sender, MouseButtonEventArgs e)
        {
            e.Handled = true;
        }

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
