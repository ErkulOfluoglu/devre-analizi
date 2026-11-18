using System;
using System.Collections.Generic;
using System.Windows;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Tanıtım turundaki tek bir adım.
    /// Hedef bileşeni (vurgulanacak alan), başlığı ve açıklama metnini içerir.
    /// </summary>
    public sealed class TourStep
    {
        /// <summary>Açıklama kartının hedefe göre tercih edilen yanları (sırayla denenir); null: sağ, sol, alt, üst.</summary>
        public IReadOnlyList<TourSide>? PreferredSides { get; init; }

        public Func<FrameworkElement?>? TargetAccessor { get; init; }
        public string Title { get; init; } = "";
        public string Body { get; init; } = "";
    }

    public enum TourSide { Right, Left, Below, Above }

    /// <summary>Açıklama kartının konumunu hesaplar (saf işlev: birim testlenebilir).</summary>
    public static class TourPlacement
    {
        public static readonly TourSide[] DefaultOrder = { TourSide.Right, TourSide.Left, TourSide.Below, TourSide.Above };

        /// <summary>
        /// Tercih sırasındaki ilk sığan yan seçilir; hiçbiri sığmazsa son çare olarak üst. Sonuç pencereye kelepçelenir.
        /// </summary>
        public static Point Place(Rect hole, double cardW, double cardH, double w, double h,
                                  IReadOnlyList<TourSide>? order = null)
        {
            double x = 0, y = 0;
            bool placed = false;
            foreach (var side in order is { Count: > 0 } ? order : DefaultOrder)
            {
                switch (side)
                {
                    case TourSide.Right when hole.Right + 16 + cardW <= w:
                        x = hole.Right + 16; y = hole.Top + (hole.Height - cardH) / 2; placed = true; break;
                    case TourSide.Left when hole.Left - 16 - cardW >= 0:
                        x = hole.Left - 16 - cardW; y = hole.Top + (hole.Height - cardH) / 2; placed = true; break;
                    case TourSide.Below when hole.Bottom + 16 + cardH <= h:
                        x = hole.Left + (hole.Width - cardW) / 2; y = hole.Bottom + 16; placed = true; break;
                    case TourSide.Above when hole.Top - 16 - cardH >= 0:
                        x = hole.Left + (hole.Width - cardW) / 2; y = hole.Top - 16 - cardH; placed = true; break;
                }
                if (placed) break;
            }
            if (!placed)
            {
                x = hole.Left + (hole.Width - cardW) / 2;
                y = Math.Max(16, hole.Top - 16 - cardH);
            }

            x = Math.Max(16, Math.Min(w - cardW - 16, x));
            y = Math.Max(16, Math.Min(h - cardH - 16, y));
            return new Point(x, y);
        }
    }

    /// <summary>
    /// Tanıtım turunun 6 adımı.
    /// </summary>
    public static class TourSteps
    {
        /// <summary>Varsayılan adımlar (testler ve genel kontrol için).</summary>
        public static IReadOnlyList<TourStep> Steps => CreateDefaultSteps(null);

        /// <summary>Ana pencere bileşenlerine bağlı adımları oluşturur.</summary>
        public static IReadOnlyList<TourStep> CreateDefaultSteps(MainWindow? window)
        {
            return new List<TourStep>
            {
                new()
                {
                    // Şerit dar ve solda: kart sağa gelince devreyi örter; önce altına
                    PreferredSides = new[] { TourSide.Below, TourSide.Right },
                    TargetAccessor = () => window?.ElementRail,
                    Title = "Elemanlar",
                    Body = "Bir kategoriye tıklayın, açılan listeden elemanı seçin. Eleman fareyi izler; çizim alanında istediğiniz yere tıklayıp bırakın. (R: döndür · Esc: vazgeç)"
                },
                new()
                {
                    TargetAccessor = () => window?.CanvasCard,
                    Title = "Çizim alanı",
                    Body = "Bir elemanın ucuna tıklayın, sonra bağlanacak uca tıklayın. (Esc: vazgeç) Çift tık: değeri değiştir · R: döndür · sağ tık: sil."
                },
                new()
                {
                    // Sağ panelde: sola gelince yöntem kutusunu / devreyi örter; önce altına
                    PreferredSides = new[] { TourSide.Below, TourSide.Left },
                    TargetAccessor = () => window?.AnalysisPanel.BtnSolve,
                    Title = "Çöz",
                    Body = "Yöntemi seçip buraya basın ya da F5'e basın. Çözüm saniyeler içinde gelir: anlatım bu panelde, değerler devrenin üzerinde görünür."
                },
                new()
                {
                    TargetAccessor = () => window?.AnalysisPanel.ResultsCard,
                    Title = "Anlatım ve sonuçlar",
                    Body = "Anlatım çözümü adım adım anlatır; Sonuçlar tüm değerleri listeler."
                },
                new()
                {
                    TargetAccessor = () => window?.AnalysisPanel.ChkPracticeMode,
                    Title = "Alıştırma modu",
                    Body = "Açınca sonuçlar gizlenir, soruları kendiniz çözersiniz. Üstteki “Yeni soru” ile rastgele devre üretebilirsiniz."
                },
                new()
                {
                    TargetAccessor = () => (FrameworkElement?)window?.AnalysisPanel.CurrentAssistantView ?? window?.AnalysisPanel.ResultsCard,
                    Title = "Yapay zekâya sor",
                    Body = "Çözümden sonra bu bölümü açıp soru sorabilirsiniz. İsteğe bağlıdır; kurulum adımlarını program gösterir."
                }
            };
        }
    }
}
