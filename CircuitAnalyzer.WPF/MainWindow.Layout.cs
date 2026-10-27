using System.Windows;
using System.Windows.Controls.Primitives;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF
{
    // MainWindow parçası: sağ "Analiz" panelinin genişliği (ayırıcıyla ayarlanır, ayarlara kaydedilir).
    public partial class MainWindow
    {
        /// <summary>Analiz panelinin varsayılan genişliği (piksel).</summary>
        internal const double AnalysisPanelDefaultWidth = 460;

        /// <summary>Analiz panelinin en küçük genişliği (piksel).</summary>
        internal const double AnalysisPanelMinWidth = 360;

        /// <summary>Analiz panelinin en büyük genişliği (piksel).</summary>
        internal const double AnalysisPanelMaxWidth = 900;

        /// <summary>Çizim alanının (canvas) korumaya çalışılan en küçük genişliği (piksel).</summary>
        internal const double MinCanvasAreaWidth = 400;

        // Kenar çubuğu (248) + iki boşluk sütunu (16 + 16) — MainWindow.xaml sütun tanımlarıyla aynı olmalı
        private const double FixedColumnsWidth = 248 + 16 + 16;

        /// <summary>Kaydedilmiş panel genişliğini geri yükler ve pencere boyutuna göre üst sınırı izler.</summary>
        private void InitializeAnalysisPanelLayout()
        {
            double saved = AppSettings.AnalysisPanelWidth ?? AnalysisPanelDefaultWidth;
            AnalysisColumn.Width = new GridLength(ClampAnalysisPanelWidth(saved));

            LayoutRoot.SizeChanged += (_, e) => UpdateAnalysisPanelMaxWidth(e.NewSize.Width);
        }

        /// <summary>Genişliği [en küçük, en büyük] aralığına çeker; geçersiz değer varsayılana döner.</summary>
        internal static double ClampAnalysisPanelWidth(double width)
        {
            if (double.IsNaN(width) || double.IsInfinity(width))
                return AnalysisPanelDefaultWidth;
            return Math.Clamp(width, AnalysisPanelMinWidth, AnalysisPanelMaxWidth);
        }

        /// <summary>
        /// Panelin o pencere genişliğinde alabileceği en büyük genişlik: çizim alanı en az
        /// <see cref="MinCanvasAreaWidth"/> kalır. Pencere çok darsa panel en küçük genişliğine iner.
        /// </summary>
        internal static double AnalysisPanelMaxWidthFor(double layoutWidth)
        {
            double max = layoutWidth - FixedColumnsWidth - MinCanvasAreaWidth;
            return Math.Clamp(max, AnalysisPanelMinWidth, AnalysisPanelMaxWidth);
        }

        private void UpdateAnalysisPanelMaxWidth(double layoutWidth)
        {
            if (layoutWidth > 0)
                AnalysisColumn.MaxWidth = AnalysisPanelMaxWidthFor(layoutWidth);
        }

        /// <summary>Ayırıcı bırakılınca seçilen genişlik ayarlara yazılır.</summary>
        private void AnalysisSplitter_DragCompleted(object sender, DragCompletedEventArgs e)
        {
            double width = ClampAnalysisPanelWidth(Math.Round(AnalysisColumn.ActualWidth));
            AnalysisColumn.Width = new GridLength(width);
            AppSettings.AnalysisPanelWidth = width;
            TxtStatus.Text = $"Analiz paneli genişliği: {width:F0} px";
        }
    }
}
