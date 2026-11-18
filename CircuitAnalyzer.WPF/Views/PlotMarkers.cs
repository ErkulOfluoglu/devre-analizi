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

        /// <summary>Başlık, alt eksen sayıları ve eksen adı için çizim yüksekliğinden düşülen pay (px; ihtiyatlı).</summary>
        private const double VerticalAllowancePx = 95;

        /// <summary>Kontrol genişliğinden veri alanının yaklaşık genişliği (bilinmiyorsa 0).</summary>
        public static double DataWidthPx(double controlWidth) =>
            controlWidth > AxisAllowancePx ? controlWidth - AxisAllowancePx : 0;

        /// <summary>Kontrol yüksekliğinden veri alanının yaklaşık yüksekliği (bilinmiyorsa 0).</summary>
        public static double DataHeightPx(double controlHeight) =>
            controlHeight > VerticalAllowancePx + 20 ? controlHeight - VerticalAllowancePx : 0;

        /// <summary>Eksen sayısı: Türkçe ondalık virgülü ve Unicode eksi ("−0,5").</summary>
        public static string TickLabel(double v) => TurkishNumber.FormatDisplay(v, "G4");

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
                LabelFormatter = TickLabel,
            };
        }

        /// <summary>Sol eksen sayıları: Türkçe ondalık virgülü ve Unicode eksi.</summary>
        public static void ApplyLeftTicks(Plot plot)
        {
            plot.Axes.Left.TickGenerator = new ScottPlot.TickGenerators.NumericAutomatic
            {
                LabelFormatter = TickLabel,
            };
        }

        /// <summary>
        /// Rozetleri eğrinin üstündeki banda, çakışmayan satırlara yerleştirir. Kenardaki işaretçinin
        /// rozeti içeri kaydırılır (kutusu veri alanında kalır).
        /// <paramref name="axisMin"/> y ekseninin alt sınırı, <paramref name="dataMax"/> verinin üstü.
        /// Dönüş: y ekseninin yeni üst sınırı (bant dahil).
        /// </summary>
        public static double AddBadges(
            Plot plot, IReadOnlyList<(double X, string Text)> markers,
            double xMin, double xMax, double axisMin, double dataMax, double dataWidthPx, double dataHeightPx,
            float fontSize, Color fontColor, Color backColor, Color borderColor)
        {
            double badgeH = PlotLayout.BadgeHeightPx(fontSize);
            if (markers.Count == 0)
                return PlotLayout.TopBandPx(axisMin, dataMax, 0, dataHeightPx, badgeH).AxisMax;

            double w = dataWidthPx > 0 ? dataWidthPx : 400;
            double span = Math.Max(1e-12, xMax - xMin);
            var widths = markers.Select(m => PlotLayout.BadgeWidthPx(m.Text, fontSize)).ToList();
            var natural = markers.Select(m => (m.X - xMin) / span * w).ToList();
            var centers = natural.Select((c, i) => PlotLayout.ClampBadgeCenterPx(c, widths[i], w)).ToList();
            int[] rows = PlotLayout.BadgeRows(centers, widths);
            var (axisMax, rowY) = PlotLayout.TopBandPx(axisMin, dataMax, rows.Max() + 1, dataHeightPx, badgeH);

            for (int i = 0; i < markers.Count; i++)
            {
                var t = plot.Add.Text(markers[i].Text, markers[i].X, rowY[rows[i]]);
                StyleBadge(t, fontSize, fontColor, backColor, borderColor);
                t.LabelAlignment = Alignment.MiddleCenter;
                // Kenara taşan rozet piksel kadar içeri (veri alanı genişliğinden bağımsız: uçtaki
                // işaretçi her genişlikte kenardadır)
                t.LabelOffsetX = (float)(centers[i] - natural[i]);
            }
            return axisMax;
        }

        /// <summary>
        /// Yarım güç (0,707) çizgisinin etiketi: çizim alanının içinde, eğrinin bu çizginin altında kaldığı
        /// kenarda, çizginin hemen üstünde; işaretçi rozetleriyle aynı biçimde, döndürülmeden.
        /// </summary>
        public static void AddHalfPowerLabel(
            Plot plot, string text, double level, double xLeft, double xRight, double f1, double f2,
            float fontSize, Color fontColor, Color backColor, Color borderColor)
        {
            bool onRight = PlotLayout.HalfPowerLabelOnRight(xLeft, xRight, f1, f2);
            var t = plot.Add.Text(text, onRight ? xRight : xLeft, level);
            StyleBadge(t, fontSize, fontColor, backColor, borderColor);
            t.LabelBold = false;
            t.LabelAlignment = onRight ? Alignment.LowerRight : Alignment.LowerLeft;
            // Kutu yazının iç boşluğu kadar dışa taşar: kenardan pay + iç boşluk kadar içeri
            double inset = PlotLayout.HalfPowerAnchorOffsetPx;
            t.LabelOffsetX = (float)(onRight ? -inset : inset);
            t.LabelOffsetY = -3;
        }

        private static void StyleBadge(ScottPlot.Plottables.Text t, float fontSize, Color fontColor, Color backColor, Color borderColor)
        {
            t.LabelFontSize = fontSize;
            t.LabelBold = true;
            t.LabelFontColor = fontColor;
            t.LabelBackgroundColor = backColor;
            t.LabelBorderColor = borderColor;
            t.LabelBorderWidth = 1;
            t.LabelBorderRadius = 4;
            t.LabelPadding = (float)PlotLayout.BadgePaddingPx;
        }
    }
}
