using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Güç üçgeninin geometrisi ve yazılarının yeri (saf hesap; çizim <see cref="PowerTriangleView"/>'da).
    /// Kenarlarda değerler yazar (P = … W, Q = … VAR, S = … VA, φ = …°); kompanzasyon gösterilirse
    /// anlatımdaki adlarla φ₁ / φ₂, Q_C ve kompanzasyondan sonraki Q′, S′ (anlatımdaki I′ gibi);
    /// kesikli kenarların değerleri <see cref="CompensationCaption"/> ile alttaki satırdadır.
    /// Yazılar birbirinin üstüne binmez ve tuvalin içinde kalır.
    /// </summary>
    internal static class PowerTriangleLayout
    {
        public const double FontSize = 12;
        public const double CompFontSize = 11.5;

        public sealed record PlacedLabel(string Key, string Text, Rect Box, bool IsCompensation);

        public sealed class Result
        {
            public Point P0, P1, P2, P2Comp;
            public bool IsLagging, IsUnity, HasComp;
            public double WidthP, HeightQ, HeightQComp;
            public List<PlacedLabel> Labels { get; } = new();
            public PlacedLabel? this[string key] => Labels.FirstOrDefault(l => l.Key == key);
        }

        /// <summary>Yazı kutusu tahmini: karakter başına ~0,6 yazı boyu (Segoe UI yarı kalın, rakamlar).</summary>
        public static Size Measure(string text, double fontSize) =>
            new(Math.Ceiling(text.Length * fontSize * 0.6 + 4), Math.Ceiling(fontSize * 1.4));

        /// <summary>Unicode eksiyle işaretli değer: "−600 VAR" (EngFormat ASCII '-' kullanır).</summary>
        public static string Signed(double value, string unit) =>
            value < 0 ? "−" + EngFormat.Format(-value, unit) : EngFormat.Format(value, unit);

        public static string Degrees(double deg) => TurkishNumber.Format(deg, "0.##") + "°";

        /// <param name="targetPf">Uygulanmış kompanzasyonun hedef cos φ₂'si; yoksa null.</param>
        public static Result Layout(double w, double h, double p, double q, string? pfType, double? targetPf)
        {
            var r = new Result();
            double pVal = Math.Abs(p);
            double qVal = Math.Abs(q);

            r.IsUnity = qVal < 1e-9 || string.Equals(pfType, "unity", StringComparison.OrdinalIgnoreCase);
            bool isLeading = string.Equals(pfType, "leading", StringComparison.OrdinalIgnoreCase) ||
                             (q < -1e-9 && !string.Equals(pfType, "lagging", StringComparison.OrdinalIgnoreCase));
            r.IsLagging = !isLeading;

            r.HasComp = targetPf.HasValue && !r.IsUnity && r.IsLagging;
            double phi = Math.Atan2(qVal, pVal);
            double phi2 = r.HasComp ? Math.Acos(Math.Clamp(targetPf!.Value, 1e-6, 1.0)) : 0;
            double qPrime = r.HasComp ? Compensated(pVal, targetPf!.Value).QPrime : 0;

            // ── Yazılar (önce metin: kenar boşlukları metin genişliğine göre ayrılır) ──
            string phiName = r.HasComp ? "φ₁" : "φ";
            var texts = new List<(string Key, string Text, bool Comp)>
            {
                ("P", "P = " + EngFormat.Format(p, "W"), false),
            };
            if (!r.IsUnity)
            {
                texts.Add(("Q", "Q = " + Signed(q, "VAR"), false));
                texts.Add(("S", "S = " + EngFormat.Format(Math.Sqrt(p * p + q * q), "VA"), false));
                texts.Add(("phi", $"{phiName} = {Degrees(phi * 180 / Math.PI)}", false));
            }
            else
            {
                texts.Add(("S", "S = " + EngFormat.Format(pVal, "VA") + " (Q = 0)", false));
            }
            if (r.HasComp)
            {
                // Kesikli (kompanzasyon sonrası) kenarlar adlarıyla; değerleri alttaki açıklama satırında
                // (CompensationCaption) — dar üçgende dört değer daha sığmaz
                texts.Add(("Qc", "Q_C", true));
                texts.Add(("Q2", "Q′", true));
                texts.Add(("S2", "S′", true));
                texts.Add(("phi2", "φ₂", true));
            }
            Size Sz(string key) { var t = texts.First(x => x.Key == key); return Measure(t.Text, t.Comp ? CompFontSize : FontSize); }

            double lineH = Measure("P", FontSize).Height;
            double rightW = texts.Where(t => t.Key is "Q" or "Qc").Select(t => Sz(t.Key).Width).DefaultIfEmpty(0).Max();
            double padRight = rightW + 12;
            double padLeft = 10;
            double padTop = lineH + 8;
            // Kompanzasyonda tabanın altında iki satır: P ve (sığmazsa) açı yazıları
            double padBottom = r.HasComp ? 2 * lineH + 10 : lineH + 8;

            double availW = Math.Max(20, w - padLeft - padRight);
            double availH = Math.Max(20, h - padTop - padBottom);
            double maxQ = Math.Max(qVal, qPrime);
            double scale;
            if (pVal < 1e-12 && maxQ < 1e-12) scale = 1.0;
            else if (pVal < 1e-12) scale = availH / maxQ;
            else if (maxQ < 1e-12 || r.IsUnity) scale = availW / pVal;
            else scale = Math.Min(availW / pVal, availH / maxQ);

            r.WidthP = pVal * scale;
            r.HeightQ = r.IsUnity ? 0 : qVal * scale;
            r.HeightQComp = qPrime * scale;
            // Dar (dik) üçgen ortalanır: S yazısına solda yer kalır
            double x0 = padLeft + Math.Max(0, (availW - r.WidthP) / 2.0);
            if (r.IsUnity)
            {
                double baseY = h / 2.0;
                r.P0 = new Point(x0, baseY);
                r.P1 = r.P2 = r.P2Comp = new Point(x0 + r.WidthP, baseY);
            }
            else
            {
                double baseY = r.IsLagging ? h - padBottom : padTop;
                double dir = r.IsLagging ? -1 : 1;     // Q'nun çizildiği yön (ekranda y)
                r.P0 = new Point(x0, baseY);
                r.P1 = new Point(x0 + r.WidthP, baseY);
                r.P2 = new Point(x0 + r.WidthP, baseY + dir * r.HeightQ);
                r.P2Comp = new Point(x0 + r.WidthP, baseY + dir * r.HeightQComp);
            }

            // ── Yerleştirme: her yazı için aday yerler (öncelik sırasıyla) ──
            var bounds = new Rect(0, 0, w, h);
            var placed = new List<Rect>();
            double dirY = r.IsLagging ? -1 : 1;

            Rect At(Size s, double cx, double cy) => new(cx - s.Width / 2, cy - s.Height / 2, s.Width, s.Height);
            Rect RightOf(Size s, double x, double cy) => new(x + 6, cy - s.Height / 2, s.Width, s.Height);
            Rect LeftOf(Size s, double x, double cy) => new(x - 6 - s.Width, cy - s.Height / 2, s.Width, s.Height);

            // Yazı, üçgenin kenarlarını (ve kesikli kompanzasyon kenarını) kesmesin
            var lines = new List<(Point A, Point B)> { (r.P0, r.P1) };
            if (!r.IsUnity)
            {
                lines.Add((r.P1, r.P2));
                lines.Add((r.P0, r.P2));
                if (r.HasComp) lines.Add((r.P0, r.P2Comp));
            }

            void Place(string key, IEnumerable<Rect> candidates)
            {
                var t = texts.FirstOrDefault(x => x.Key == key);
                if (t.Key == null) return;
                var list = candidates.ToList();
                var all = list.Concat(Rings(list[0])).Select(c => Clamp(c, bounds))
                              .Where(c => c.Width <= bounds.Width && c.Height <= bounds.Height)
                              .ToList();
                // 1. tur: ne yazılara ne çizgilere değer; 2. tur: yalnız yazılara değmez (dar tuval)
                Rect? best = all.Cast<Rect?>().FirstOrDefault(c =>
                                 !placed.Any(o => Overlaps(o, c!.Value)) && !lines.Any(l => Crosses(l.A, l.B, c!.Value)))
                             ?? all.Cast<Rect?>().FirstOrDefault(c => !placed.Any(o => Overlaps(o, c!.Value)));
                best ??= Clamp(list[0], bounds);
                placed.Add(best.Value);
                r.Labels.Add(new PlacedLabel(key, t.Text, best.Value, t.Comp));
            }

            var midBase = new Point((r.P0.X + r.P1.X) / 2, r.P0.Y);
            Size sP = Sz("P");
            double outside = r.IsLagging || r.IsUnity ? 1 : -1;   // taban yazısı üçgenin dışına
            Place("P", new[]
            {
                At(sP, midBase.X, r.P0.Y + outside * (sP.Height / 2 + 4)),
                At(sP, r.P0.X + sP.Width / 2, r.P0.Y + outside * (sP.Height / 2 + 4)),
                At(sP, r.P1.X - sP.Width / 2, r.P0.Y + outside * (sP.Height / 2 + 4)),
            });

            if (r.IsUnity)
            {
                Size sU = Sz("S");
                Place("S", new[] { At(sU, midBase.X, r.P0.Y - outside * (sU.Height / 2 + 4)) });
                return r;
            }

            // Q: dik kenarın sağında, ortasında
            Size sQ = Sz("Q");
            double qMid = (r.P1.Y + r.P2.Y) / 2;
            Place("Q", new[]
            {
                RightOf(sQ, r.P1.X, qMid),
                RightOf(sQ, r.P1.X, qMid + dirY * sQ.Height),
                RightOf(sQ, r.P1.X, qMid - dirY * sQ.Height),
                RightOf(sQ, r.P1.X, r.P2.Y),
            });

            // Kompanzasyonda kaldırılan kısım Q_C: dik kenarın sağında, Q′ ile Q arasındaki parçanın ortasında
            if (r.HasComp)
            {
                Size sC = Sz("Qc");
                double cMid = (r.P2Comp.Y + r.P2.Y) / 2;
                Place("Qc", new[]
                {
                    RightOf(sC, r.P1.X, cMid),
                    RightOf(sC, r.P1.X, r.P2.Y),
                    RightOf(sC, r.P1.X, r.P2.Y + dirY * sC.Height),
                });
            }

            // S: hipotenüsün dışında (geri yükte sol üstte), ortasından dik yönde
            Size sS = Sz("S");
            Vector hyp = r.P2 - r.P0;
            double len = Math.Max(1e-9, hyp.Length);
            var nOut = new Vector(hyp.Y / len, -hyp.X / len);                 // geri yükte sol üst
            if (!r.IsLagging) nOut = -nOut;
            Rect OnNormal(Point mid, Size s, Vector n, double gap)
            {
                // Kutunun hipotenüse en yakın köşesi çizgiden gap kadar uzakta
                double ex = Math.Abs(n.X) * s.Width / 2 + Math.Abs(n.Y) * s.Height / 2;
                var c = mid + n * (gap + ex);
                return At(s, c.X, c.Y);
            }
            Point Along(Point a, Point b, double t) => new(a.X + (b.X - a.X) * t, a.Y + (b.Y - a.Y) * t);
            Place("S", new[]
            {
                OnNormal(Along(r.P0, r.P2, 0.5), sS, nOut, 4),
                OnNormal(Along(r.P0, r.P2, 0.35), sS, nOut, 4),
                OnNormal(Along(r.P0, r.P2, 0.65), sS, nOut, 4),
                OnNormal(Along(r.P0, r.P2, 0.5), sS, nOut, 14),
            });

            // φ: açının içinde, açıortay boyunca yaydan dışarı doğru ilk boş yer. Ekranda açı, çizilen
            // kenarların açısıdır (ölçek iki eksende aynı); kompanzasyonda φ₁ yazısı S ile S′ arasına düşer.
            double rArc = ArcRadius(r);
            double phiPx = Math.Atan2(r.HeightQ, Math.Max(1e-9, r.WidthP));
            double phi2Px = r.HasComp ? Math.Atan2(r.HeightQComp, Math.Max(1e-9, r.WidthP)) : 0;
            IEnumerable<Rect> InWedge(Size s, double ang)
            {
                // Yalnız yayın yakınında: uzağa düşen açı yazısı hangi açıya ait olduğunu kaybeder
                for (double d = rArc + 4; d <= rArc + 4 + 60; d += 6)
                {
                    // kutunun açıortaydaki noktaya en yakın köşesi değil merkezi: yarım köşegen kadar öteye
                    double half = Math.Abs(Math.Cos(ang)) * s.Width / 2 + Math.Abs(Math.Sin(ang)) * s.Height / 2;
                    double cx = r.P0.X + (d + half) * Math.Cos(ang);
                    double cy = r.P0.Y + dirY * (d + half) * Math.Sin(ang);
                    if (cx + s.Width / 2 > r.P1.X - 2)
                        yield break;            // dik kenarı geçti: üçgenin dışı, artık Q'nun yanı
                    yield return At(s, cx, cy);
                }
            }
            // Açının içine sığmazsa: dik üçgende dik kenarın sağına, tabanın hemen üstüne; yassıda tabanın
            // üstüne, köşenin yanına; kompanzasyonda tabanın altındaki ikinci satıra, köşenin altına.
            Size sF = Sz("phi");
            double belowRow2 = r.P0.Y - dirY * (sP.Height * 1.5 + 6);
            var phiFallback = new List<Rect>
            {
                RightOf(sF, r.P1.X, r.P0.Y + dirY * (sF.Height / 2 + 3)),
                At(sF, r.P0.X + sF.Width / 2, r.P0.Y + dirY * (sF.Height / 2 + 3)),
            };
            if (r.HasComp)
                phiFallback.Insert(0, At(sF, r.P0.X + sF.Width / 2, belowRow2));
            Place("phi", InWedge(sF, r.HasComp ? (phiPx + phi2Px) / 2 : phiPx / 2).Concat(phiFallback));

            if (r.HasComp)
            {
                // Q′: dik kenarın solunda (üçgenin içinde), Q′ parçasının ortasında
                Size s2 = Sz("Q2");
                double q2Mid = (r.P1.Y + r.P2Comp.Y) / 2;
                Place("Q2", new[]
                {
                    LeftOf(s2, r.P1.X, q2Mid),
                    LeftOf(s2, r.P1.X, q2Mid + dirY * s2.Height),
                    RightOf(s2, r.P1.X, q2Mid),
                });

                // S′: kesikli hipotenüsün altında (üçgenin içinde)
                Size sS2 = Sz("S2");
                Vector hyp2 = r.P2Comp - r.P0;
                double len2 = Math.Max(1e-9, hyp2.Length);
                var nIn = new Vector(-hyp2.Y / len2, hyp2.X / len2);           // geri yükte sağ alt
                Place("S2", new[]
                {
                    OnNormal(Along(r.P0, r.P2Comp, 0.6), sS2, nIn, 3),
                    OnNormal(Along(r.P0, r.P2Comp, 0.75), sS2, nIn, 3),
                    OnNormal(Along(r.P0, r.P2Comp, 0.45), sS2, nIn, 3),
                });

                Size sF2 = Sz("phi2");
                Place("phi2", InWedge(sF2, phi2Px / 2).Concat(new[]
                {
                    At(sF2, r.P0.X + sF2.Width / 2, r.P0.Y - dirY * (sF2.Height / 2 + 4)),
                    At(sF2, r.P0.X + sF.Width + 8 + sF2.Width / 2, belowRow2),
                    At(sF2, r.P0.X + sF2.Width / 2, belowRow2),
                }));
            }
            return r;
        }

        /// <summary>Kompanzasyondan sonra (hedef cos φ₂'de, P değişmez): Q′ = P·tan φ₂, S′ = P / cos φ₂.</summary>
        public static (double QPrime, double SPrime) Compensated(double p, double targetPf)
        {
            double phi2 = Math.Acos(Math.Clamp(targetPf, 1e-6, 1.0));
            double pa = Math.Abs(p);
            return (Math.Max(0.0, pa * Math.Tan(phi2)), pa / Math.Cos(phi2));
        }

        /// <summary>
        /// Çizimin altındaki kompanzasyon satırına eklenen değerler, kesikli kenarların adlarıyla:
        /// "Kompanzasyondan sonra: Q′ = 328,7 VAR, S′ = 1,053 kVA, φ₂ = 18,19° (cos φ₂ = 0,95)".
        /// </summary>
        public static string CompensationCaption(double p, double targetPf)
        {
            var (qPrime, sPrime) = Compensated(p, targetPf);
            double phi2 = Math.Acos(Math.Clamp(targetPf, 1e-6, 1.0)) * 180 / Math.PI;
            return $"Kompanzasyondan sonra (kesikli): Q′ = {EngFormat.Format(qPrime, "VAR")}, " +
                   $"S′ = {EngFormat.Format(sPrime, "VA")}, φ₂ = {Degrees(phi2)} " +
                   $"(cos φ₂ = {TurkishNumber.Format(targetPf, "0.###")})";
        }

        /// <summary>φ yayının yarıçapı (çizimle aynı); yay çizilmeyecek kadar küçük üçgende 0.</summary>
        public static double ArcRadius(Result r) =>
            r.WidthP > 25 && r.HeightQ > 15 ? Math.Min(24.0, Math.Min(r.WidthP * 0.35, r.HeightQ * 0.35)) : 0;

        public static bool Overlaps(Rect a, Rect b, double margin = 2) =>
            a.Left < b.Right + margin && b.Left < a.Right + margin &&
            a.Top < b.Bottom + margin && b.Top < a.Bottom + margin;

        /// <summary>AB doğru parçası dikdörtgeni kesiyor mu (Liang–Barsky kırpması)?</summary>
        public static bool Crosses(Point a, Point b, Rect box)
        {
            double t0 = 0, t1 = 1, dx = b.X - a.X, dy = b.Y - a.Y;
            double[] p = { -dx, dx, -dy, dy };
            double[] q = { a.X - box.Left, box.Right - a.X, a.Y - box.Top, box.Bottom - a.Y };
            for (int i = 0; i < 4; i++)
            {
                if (Math.Abs(p[i]) < 1e-12)
                {
                    if (q[i] < 0) return false;
                    continue;
                }
                double t = q[i] / p[i];
                if (p[i] < 0) { if (t > t1) return false; if (t > t0) t0 = t; }
                else { if (t < t0) return false; if (t < t1) t1 = t; }
            }
            return t0 <= t1;
        }

        private static Rect Clamp(Rect c, Rect bounds)
        {
            double x = Math.Min(Math.Max(c.X, bounds.Left), bounds.Right - c.Width);
            double y = Math.Min(Math.Max(c.Y, bounds.Top), bounds.Bottom - c.Height);
            return new Rect(x, y, c.Width, c.Height);
        }

        /// <summary>Aday yerlerin hepsi doluysa ilk adayın çevresinde halka halka aranır.</summary>
        private static IEnumerable<Rect> Rings(Rect first)
        {
            for (int ring = 1; ring <= 12; ring++)
            {
                double d = ring * 6;
                for (int k = 0; k < 16; k++)
                {
                    double a = k * Math.PI / 8;
                    yield return new Rect(first.X + d * Math.Cos(a) * 1.6, first.Y + d * Math.Sin(a), first.Width, first.Height);
                }
            }
        }
    }
}
