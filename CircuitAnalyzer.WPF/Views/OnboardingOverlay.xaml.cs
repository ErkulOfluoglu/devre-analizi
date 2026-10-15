using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Ana pencere üzerinde gösterilen in-window tanıtım katmanı.
    /// </summary>
    public partial class OnboardingOverlay : UserControl
    {
        public OnboardingView View => OnboardingView;

        public event Action<OnboardingResult>? Closed;

        private bool _animate = true;

        public OnboardingOverlay()
        {
            InitializeComponent();
            Visibility = Visibility.Collapsed;

            SizeChanged += (_, _) => UpdateCardMaxHeight();
            Loaded += (_, _) => UpdateCardMaxHeight();

            OnboardingView.Closed += res => Close(res, animate: _animate);
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

        public void Show(int page = 0, bool animate = true)
        {
            _animate = animate;
            Visibility = Visibility.Visible;
            OnboardingView.Page = page;
            UpdateCardMaxHeight();
            Focus();
            Keyboard.Focus(OnboardingView);

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

        public void Close(OnboardingResult result, bool? animate = null)
        {
            if (Visibility != Visibility.Visible) return;

            bool shouldAnimate = animate ?? _animate;

            void Finish()
            {
                Visibility = Visibility.Collapsed;
                Opacity = 1;
                CardScale.ScaleX = 1;
                CardScale.ScaleY = 1;
                Closed?.Invoke(result);
            }

            if (!shouldAnimate)
            {
                Finish();
                return;
            }

            var duration = TimeSpan.FromMilliseconds(120);
            var fadeAnim = new DoubleAnimation(Opacity, 0, duration);
            fadeAnim.Completed += (_, _) => Finish();
            BeginAnimation(OpacityProperty, fadeAnim);
        }

        private void Scrim_MouseDown(object sender, MouseButtonEventArgs e)
        {
            // Tıklamaların arkadaki bileşenlere geçmesini engelle
            e.Handled = true;
        }

        private void Card_MouseDown(object sender, MouseButtonEventArgs e)
        {
            // Kart içine tıklanınca da arkaya geçmesin
            e.Handled = true;
        }

        public void HandleKeyDown(Key key)
        {
            if (key == Key.Escape)
            {
                Close(OnboardingResult.Skipped, animate: false);
            }
            else if (key == Key.Left)
            {
                OnboardingView.Back();
            }
            else if (key == Key.Right)
            {
                OnboardingView.Next();
            }
        }

        protected override void OnPreviewKeyDown(KeyEventArgs e)
        {
            base.OnPreviewKeyDown(e);
            if (e.Handled) return;

            if (e.Key is Key.Escape or Key.Left or Key.Right)
            {
                e.Handled = true;
                HandleKeyDown(e.Key);
            }
        }
    }
}
