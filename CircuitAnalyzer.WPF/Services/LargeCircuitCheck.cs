using System;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Büyük AC devre uyarısı: sembolik AC çözümü eleman sayısıyla hızla uzar ve programın
    /// istek süresi sınırına (2 dakika, AnalysisApiClient) takılabilir.
    /// </summary>
    public static class LargeCircuitCheck
    {
        /// <summary>
        /// Bu kadar ve daha çok elemanlı AC devrede çözmeden önce uyarılır.
        /// Sayı bir denetimde ölçüldü: yaklaşık 85 elemanlı AC devrede sembolik çözücü 2 dakikalık
        /// süre sınırına takıldı (DC'de böyle bir sorun görülmedi). Sayılan elemanlar, tuvaldeki
        /// devre elemanlarıdır; toprak (GND), ölçüm probu ve bağlantı noktası sayılmaz.
        /// </summary>
        public const int LargeAcElementCount = 85;

        /// <summary>Çözmeden önce "büyük devre" uyarısı gösterilmeli mi?</summary>
        public static bool ShouldWarn(int elementCount, string mode) =>
            string.Equals(mode, AnalysisModes.AcPhasor, StringComparison.Ordinal) &&
            elementCount >= LargeAcElementCount;

        public const string WarningTitle = "Büyük devre";

        public static string WarningText(int elementCount) =>
            $"Bu devrede {elementCount} eleman var. Bu büyüklükteki AC devrelerin çözümü " +
            "yaklaşık iki dakika sürebilir, hatta bu sürede bitmeyebilir. Çözüm sürerken " +
            "programı kullanmaya devam edebilirsiniz.\n\nYine de çözülsün mü?";

        /// <summary>Uzun çözüm sürerken durum satırında gösterilen metin (her saniye yenilenir).</summary>
        public static string BusyText(TimeSpan elapsed) =>
            $"Büyük devre çözülüyor, lütfen bekleyin… {(int)elapsed.TotalMinutes}:{elapsed.Seconds:00} " +
            "(en çok yaklaşık 2 dakika)";
    }
}
