using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Ana pencerenin içinde açılan genel diyalog kartı (ayrı pencere açmaz).
    /// Show(başlık, içerik) ile gösterilir; "Tamam", Esc veya Enter kapatır.
    /// </summary>
    public partial class DialogOverlay : UserControl
    {
        public event Action? Closed;

        public bool IsOpen => Visibility == Visibility.Visible;

        public string Title => TitleText.Text;

        public object? Body => BodyHost.Content;

        public DialogOverlay()
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
            if (h > 48)
                CardBorder.MaxHeight = Math.Max(100, h - 48);
        }

        public void Show(string title, object body, double width = 520, bool animate = true)
        {
            TitleText.Text = title;
            BodyHost.Content = body;
            CardBorder.Width = width;

            Visibility = Visibility.Visible;
            UpdateCardMaxHeight();
            Focus();
            Keyboard.Focus(BtnOk);

            if (!animate)
            {
                Opacity = 1;
                CardScale.ScaleX = CardScale.ScaleY = 1;
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
                BodyHost.Content = null;
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

        private void BtnOk_Click(object sender, RoutedEventArgs e) => Close();

        private void Absorb_MouseDown(object sender, MouseButtonEventArgs e) => e.Handled = true;

        protected override void OnPreviewKeyDown(KeyEventArgs e)
        {
            base.OnPreviewKeyDown(e);
            if (e.Handled) return;

            if (e.Key is Key.Escape or Key.Enter)
            {
                e.Handled = true;
                Close();
            }
        }
    }
}
