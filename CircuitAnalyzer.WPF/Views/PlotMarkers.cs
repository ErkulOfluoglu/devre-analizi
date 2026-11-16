using System;
using System.Collections.Generic;
using System.Linq;
using CircuitAnalyzer.WPF.Services;
using ScottPlot;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// ScottPlot grafiklerinde alt eksen sayıları ve dikey işaretçi rozetleri (τ … 5τ, f₁ f₀ f₂).
    /// Yerleşim kararları <see cref="PlotLayout"/>'taki saf fonksiyonlardadır; burası yalnız çizer.
    /// </summary>
    internal static class PlotMarkers
    {
        /// <summary>Sol eksen sayıları ve sağ kenar için çizim genişliğinden düşülen pay (px).</summary>
        private const double AxisAllowancePx = 70;

        /// <summary>Kontrol genişliğinden veri alanının yaklaşık genişliği (bilinmiyorsa 0).</summary>
        public static double DataWidthPx(double controlWidth) =>
            controlWidth > AxisAllowancePx ? controlWidth - AxisAllowancePx : 0;

        /// <summary>Alt eksene okunur sayıda (en çok 8) yuvarlak işaret koyar, Türkçe ondalık virgülüyle.</summary>
        public static void ApplyBottomTicks(Plot plot, double xMin, double xMax, double dataWidthPx)
        {
            // Otomatik üreteç: kullanıcı yakınlaştırınca/kaydırınca sayılar yenilenir (sabit
            // liste yenilenmezdi). Sayı adedi, NiceTicks'in bu genişlikte ürettiği kadar hedeflenir.
            int target = Math.Max(2, PlotLayout.NiceTicks(
                xMin, xMax, PlotLayout.TickBudget(dataWidthPx)).Count());
            plot.Axes.Bottom.TickGenerator = new ScottPlot.TickGenerators.NumericAutomatic
            {
                TargetTickCount = target,
                LabelFormatter = v => TurkishNumber.Format(v, "G4"),
            };
        }

        /// <summary>
        /// Rozetleri eğrinin üstündeki banda, çakışmayan satırlara yerleştirir.
        /// Dönüş: y ekseninin yeni üst sınırı (bant dahil).
        /// </summary>
        public static double AddBadges(
            Plot plot, IReadOnlyList<(double X, string Text)> markers,
            double xMin, double xMax, double yMin, double yMax, double dataWidthPx,
            float fontSize, Color fontColor, Color backColor, Color borderColor)
        {
            if (markers.Count == 0)
                return PlotLayout.TopBand(yMin, yMax, 0).AxisMax;

            double w = dataWidthPx > 0 ? dataWidthPx : 400;
            double span = Math.Max(1e-12, xMax - xMin);
            var centers = markers.Select(m => (m.X - xMin) / span * w).ToList();
            var widths = markers.Select(m => PlotLayout.BadgeWidthPx(m.Text, fontSize)).ToList();
            int[] rows = PlotLayout.BadgeRows(centers, widths);
            var (axisMax, rowY) = PlotLayout.TopBand(yMin, yMax, rows.Max() + 1);

            for (int i = 0; i < markers.Count; i++)
            {
                var t = plot.Add.Text(markers[i].Text, markers[i].X, rowY[rows[i]]);
                t.LabelFontSize = fontSize;
                t.LabelBold = true;
                t.LabelFontColor = fontColor;
                t.LabelBackgroundColor = backColor;
                t.LabelBorderColor = borderColor;
                t.LabelBorderWidth = 1;
                t.LabelBorderRadius = 4;
                t.LabelPadding = 3;
                t.LabelAlignment = Alignment.MiddleCenter;
            }
            return axisMax;
        }
    }
}
