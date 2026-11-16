using System;
using System.Collections.Generic;
using System.Linq;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Grafik yerleşimi için saf hesaplar (çizimden bağımsız, birim testli):
    /// okunur sayıda eksen işareti, işaretçi rozetlerinin (τ, 2τ … / f₁, f₀, f₂) çakışmayan
    /// satırlara dağıtılması ve rozetler için eğrinin üstünde ayrılan bant.
    /// Rozetler eksen sayılarının değil, çizim alanının üst bandında durur; böylece zaman/frekans
    /// eksenindeki sayıların üstüne binmezler.
    /// </summary>
    internal static class PlotLayout
    {
        /// <summary>Bir eksen sayısının kapladığı yaklaşık genişlik + boşluk (px).</summary>
        public const double MinTickSpacingPx = 72;

        /// <summary>Genişliğe göre en çok kaç eksen işareti: 3 ile 8 arası (genişlik bilinmiyorsa 6).</summary>
        public static int TickBudget(double widthPx)
        {
            if (double.IsNaN(widthPx) || widthPx <= 0)
                return 6;
            return Math.Clamp((int)Math.Floor(widthPx / MinTickSpacingPx), 3, 8);
        }

        /// <summary>
        /// [min, max] aralığında 1·10ⁿ, 2·10ⁿ, 2,5·10ⁿ, 5·10ⁿ adımlı "yuvarlak" işaretler;
        /// sayısı en çok <paramref name="maxCount"/>. Sıfır, aralıktaysa her zaman işaretlerden biridir.
        /// </summary>
        public static double[] NiceTicks(double min, double max, int maxCount)
        {
            if (double.IsNaN(min) || double.IsNaN(max) || double.IsInfinity(min) || double.IsInfinity(max))
                return Array.Empty<double>();
            if (max < min)
                (min, max) = (max, min);
            maxCount = Math.Max(2, maxCount);
            double span = max - min;
            if (span <= 0)
                return new[] { min };

            double raw = span / maxCount;
            double mag = Math.Pow(10, Math.Floor(Math.Log10(raw)));
            double[] mults = { 1, 2, 2.5, 5, 10, 20 };
            foreach (double m in mults)
            {
                double step = m * mag;
                var ticks = TicksWithStep(min, max, step);
                if (ticks.Length <= maxCount && ticks.Length >= 2)
                    return ticks;
            }
            return TicksWithStep(min, max, 20 * mag);
        }

        private static double[] TicksWithStep(double min, double max, double step)
        {
            double eps = step * 1e-9;
            double first = Math.Ceiling((min - eps) / step);
            double last = Math.Floor((max + eps) / step);
            var list = new List<double>();
            for (double k = first; k <= last; k++)
            {
                double t = k * step;
                if (Math.Abs(t) < eps) t = 0.0;     // −0 ve 1e-17 gibi kalıntılar "0" olsun
                list.Add(t);
            }
            return list.ToArray();
        }

        /// <summary>
        /// Rozetleri satırlara dağıtır: soldan sağa, her rozet yatayda öncekiyle çakışmayan
        /// (arada en az <paramref name="gapPx"/> boşluk olan) ilk satıra konur.
        /// Dönen dizi, giriş sırasıyla her rozetin satır numarasıdır (0 = en üst).
        /// </summary>
        public static int[] BadgeRows(IReadOnlyList<double> centerPx, IReadOnlyList<double> widthPx, double gapPx = 6)
        {
            int n = centerPx.Count;
            var rows = new int[n];
            var rowRight = new List<double>();
            foreach (int i in Enumerable.Range(0, n).OrderBy(i => centerPx[i]))
            {
                double left = centerPx[i] - widthPx[i] / 2.0;
                double right = centerPx[i] + widthPx[i] / 2.0;
                int r = 0;
                while (r < rowRight.Count && left < rowRight[r] + gapPx)
                    r++;
                if (r == rowRight.Count)
                    rowRight.Add(right);
                else
                    rowRight[r] = right;
                rows[i] = r;
            }
            return rows;
        }

        /// <summary>
        /// Eğrinin üstünde rozetlere ayrılan bant: veri [dataMin, dataMax] aralığındadır;
        /// her rozet satırına veri aralığının <paramref name="rowFraction"/> katı yer açılır.
        /// Dönüş: yeni eksen üst sınırı ve her satırın orta y değeri (satır 0 en üstte).
        /// Bütün satırlar dataMax'ın üstünde, eksen üst sınırının altındadır.
        /// </summary>
        public static (double AxisMax, double[] RowCenters) TopBand(double dataMin, double dataMax, int rows, double rowFraction = 0.13)
        {
            rows = Math.Max(1, rows);
            double span = Math.Max(1e-12, dataMax - dataMin);
            double rowH = span * rowFraction;
            double bandBottom = dataMax + span * 0.04;
            double axisMax = bandBottom + rows * rowH;
            var centers = new double[rows];
            for (int r = 0; r < rows; r++)
                centers[r] = axisMax - (r + 0.5) * rowH;
            return (axisMax, centers);
        }

        /// <summary>Rozet genişliği tahmini (px): karakter başına ~0,62·yazı boyu + iç boşluk.</summary>
        public static double BadgeWidthPx(string text, double fontSize) =>
            (text?.Length ?? 0) * fontSize * 0.62 + 12;
    }
}
