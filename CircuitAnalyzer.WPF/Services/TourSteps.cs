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
        public Func<FrameworkElement?>? TargetAccessor { get; init; }
        public string Title { get; init; } = "";
        public string Body { get; init; } = "";
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
                    TargetAccessor = () => window?.SidebarCard,
                    Title = "Elemanlar",
                    Body = "Devre elemanlarını buradan ekleyin. Eklenen eleman çizim alanının ortasına gelir; sürükleyip yerleştirin."
                },
                new()
                {
                    TargetAccessor = () => window?.CanvasCard,
                    Title = "Çizim alanı",
                    Body = "Bir elemanın ucuna tıklayın, sonra bağlanacak uca tıklayın. (Esc: vazgeç) Çift tık: değeri değiştir · R: döndür · sağ tık: sil."
                },
                new()
                {
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
                    Body = "Açınca sonuçlar gizlenir, soruları kendiniz çözersiniz. Sol alttaki “Yeni soru” ile rastgele devre üretebilirsiniz."
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
