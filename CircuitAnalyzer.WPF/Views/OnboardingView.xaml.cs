using System;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Input;

namespace CircuitAnalyzer.WPF.Views
{
    public enum OnboardingResult
    {
        Skipped,
        StartExample,
        StartTour
    }

    /// <summary>
    /// İlk açılışta ve yardım menüsünde gösterilen 5 sayfalık tanıtım görünümü.
    /// </summary>
    public partial class OnboardingView : UserControl
    {
        private int _page;

        public OnboardingResult Result { get; private set; } = OnboardingResult.Skipped;

        public event Action<OnboardingResult>? Closed;

        public int Page
        {
            get => _page;
            set => SetPage(Math.Clamp(value, 0, 4));
        }

        public string VisibleTitle => Page switch
        {
            0 => "Devre Analizi'ne hoş geldiniz",
            1 => "Devre çizmek",
            2 => "Çöz ve adım adım öğren",
            3 => "Kendinizi deneyin",
            4 => "Yapay zekâya sorun (isteğe bağlı)",
            _ => ""
        };

        public OnboardingView()
        {
            InitializeComponent();

            AutomationProperties.SetName(Dot0, "1. sayfa");
            AutomationProperties.SetName(Dot1, "2. sayfa");
            AutomationProperties.SetName(Dot2, "3. sayfa");
            AutomationProperties.SetName(Dot3, "4. sayfa");
            AutomationProperties.SetName(Dot4, "5. sayfa");

            SetPage(0);
        }

        public void Next()
        {
            if (Page < 4)
            {
                Page++;
            }
        }

        public void Back()
        {
            if (Page > 0)
            {
                Page--;
            }
        }

        public void Close(OnboardingResult result)
        {
            Result = result;
            Closed?.Invoke(result);
        }

        private void SetPage(int page)
        {
            _page = page;

            // Sayfa görünürlükleri
            Page1.Visibility = page == 0 ? Visibility.Visible : Visibility.Collapsed;
            Page2.Visibility = page == 1 ? Visibility.Visible : Visibility.Collapsed;
            Page3.Visibility = page == 2 ? Visibility.Visible : Visibility.Collapsed;
            Page4.Visibility = page == 3 ? Visibility.Visible : Visibility.Collapsed;
            Page5.Visibility = page == 4 ? Visibility.Visible : Visibility.Collapsed;

            // Üst gösterge
            TxtPageIndicator.Text = $"{page + 1} / 5";

            // Alt butonlar
            if (page == 4)
            {
                BtnBack.Visibility = Visibility.Visible;
                BtnNext.Visibility = Visibility.Collapsed;
                BtnStartTour.Visibility = Visibility.Visible;
                BtnStartExample.Visibility = Visibility.Visible;
            }
            else
            {
                BtnBack.Visibility = page > 0 ? Visibility.Visible : Visibility.Collapsed;
                BtnNext.Visibility = Visibility.Visible;
                BtnStartTour.Visibility = Visibility.Collapsed;
                BtnStartExample.Visibility = Visibility.Collapsed;
            }

            // Nokta göstergeleri (aktif olan 22x8 pill Brush.Accent, diğerleri 8x8 Brush.Border.Strong)
            UpdateDot(DotVisual0, page == 0);
            UpdateDot(DotVisual1, page == 1);
            UpdateDot(DotVisual2, page == 2);
            UpdateDot(DotVisual3, page == 3);
            UpdateDot(DotVisual4, page == 4);
        }

        private static void UpdateDot(Border dot, bool isActive)
        {
            if (isActive)
            {
                dot.Width = 22;
                dot.SetResourceReference(Border.BackgroundProperty, "Brush.Accent");
            }
            else
            {
                dot.Width = 8;
                dot.SetResourceReference(Border.BackgroundProperty, "Brush.Border.Strong");
            }
        }

        private void Dot_Click(object sender, RoutedEventArgs e)
        {
            if (sender is FrameworkElement fe && fe.Tag is string s && int.TryParse(s, out int p))
            {
                Page = p;
            }
        }

        private void BtnNext_Click(object sender, RoutedEventArgs e) => Next();

        private void BtnBack_Click(object sender, RoutedEventArgs e) => Back();

        private void BtnSkip_Click(object sender, RoutedEventArgs e)
        {
            Close(OnboardingResult.Skipped);
        }

        private void BtnStartTour_Click(object sender, RoutedEventArgs e)
        {
            Close(OnboardingResult.StartTour);
        }

        private void BtnStartExample_Click(object sender, RoutedEventArgs e)
        {
            Close(OnboardingResult.StartExample);
        }

        protected override void OnPreviewKeyDown(KeyEventArgs e)
        {
            base.OnPreviewKeyDown(e);
            if (e.Handled) return;

            if (e.Key == Key.Escape)
            {
                e.Handled = true;
                Close(OnboardingResult.Skipped);
            }
            else if (e.Key == Key.Left)
            {
                e.Handled = true;
                Back();
            }
            else if (e.Key == Key.Right)
            {
                e.Handled = true;
                Next();
            }
        }
    }
}
