using System;
using System.Collections.Generic;
using System.Windows;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Eleman kartının yerini seçer: elemanın sağı, solu, altı, üstü denenir; diğer elemanları
    /// en az örten (ve seçili elemanın üstüne binmeyen) yer kazanır. Eşitlikte sıra: sağ, sol, alt, üst.
    /// Tüm dikdörtgenler aynı koordinat sisteminde (tuval katmanı) verilir.
    /// </summary>
    public static class ElementCardPlacement
    {
        public const double Margin = 8;

        public static Point Choose(Rect target, Size card, Size area, IEnumerable<Rect> others, double gap)
        {
            double cx = target.Left + target.Width / 2 - card.Width / 2;
            double cy = target.Top + target.Height / 2 - card.Height / 2;
            var candidates = new[]
            {
                new Point(target.Right + gap, cy),            // sağ
                new Point(target.Left - gap - card.Width, cy), // sol
                new Point(cx, target.Bottom + gap),            // alt
                new Point(cx, target.Top - gap - card.Height), // üst
            };

            var otherList = new List<Rect>(others);
            Point best = Clamp(candidates[0], card, area);
            double bestScore = double.MaxValue;
            foreach (var raw in candidates)
            {
                var p = Clamp(raw, card, area);
                var rect = new Rect(p, card);
                double score = Overlap(rect, target) * 4;   // seçili elemanı örtmek en kötüsü
                foreach (var o in otherList)
                    score += Overlap(rect, o);
                if (score < bestScore - 0.5)
                {
                    bestScore = score;
                    best = p;
                }
            }
            return best;
        }

        private static Point Clamp(Point p, Size card, Size area) => new(
            Math.Max(Margin, Math.Min(p.X, area.Width - card.Width - Margin)),
            Math.Max(Margin, Math.Min(p.Y, area.Height - card.Height - Margin)));

        private static double Overlap(Rect a, Rect b)
        {
            var i = Rect.Intersect(a, b);
            return i.IsEmpty ? 0 : i.Width * i.Height;
        }
    }
}
