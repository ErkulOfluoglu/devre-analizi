namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>Çözücüye neden ulaşılamadığı.</summary>
    public enum BackendFailure
    {
        /// <summary>Çözücü programı yerinde yok (kurulum eksik ya da virüs koruması silmiş).</summary>
        Missing,
        /// <summary>Çözücü programı var ama Windows onu çalıştıramadı.</summary>
        CouldNotStart,
        /// <summary>Çalıştı ama zamanında hazır olmadı (ya da açılırken kapandı).</summary>
        NotReady,
        /// <summary>Hazırdı, sonra kapandı.</summary>
        Stopped,
        /// <summary>Çalışıyor ama istek zamanında bitmedi.</summary>
        Timeout,
        /// <summary>Bağlanılamadı (süreç durumu bilinmiyor).</summary>
        Unreachable,
    }

    /// <summary>
    /// Çözücü hatalarında kullanıcıya gösterilen başlık ve metin. Kurulan programda Python
    /// yoktur (çözücü paketlenmiştir): Python ipucu yalnızca kaynak koddan çalıştırırken verilir.
    /// </summary>
    public static class BackendMessages
    {
        public const string RetryText = "Yeniden dene";

        /// <param name="failure">Hatanın türü.</param>
        /// <param name="developerRun">Kaynak koddan (Python ile) çalıştırılıyor mu?</param>
        /// <param name="detail">Geliştiriciye gösterilecek ek ayrıntı (yalnız developerRun iken eklenir).</param>
        /// <param name="requestMessage">İsteğin kendi mesajı (zaman aşımı gibi; yoksa varsayılan metin).</param>
        public static (string Title, string Text) Describe(BackendFailure failure, bool developerRun,
                                                         string? detail = null, string? requestMessage = null)
        {
            (string title, string text) = failure switch
            {
                BackendFailure.Missing => ("Çözücü bulunamadı",
                    "Devreleri çözen program parçası, Devre Analizi'nin klasöründe bulunamadı. Kurulum " +
                    "yarım kalmış ya da bir virüs koruma programı bu parçayı kaldırmış olabilir. " +
                    "Devre Analizi'ni yeniden kurup tekrar deneyin."),
                BackendFailure.CouldNotStart => developerRun
                    ? ("Çözücü başlatılamadı",
                       "'python' çalıştırılamadı. Python kurulu ve PATH'te mi?")
                    : ("Çözücü başlatılamadı",
                       "Devreleri çözen program parçası çalıştırılamadı. Bir virüs koruma programı " +
                       "engellemiş olabilir. Yeniden deneyin; sorun sürerse Devre Analizi'ni yeniden kurun."),
                BackendFailure.NotReady => developerRun
                    ? ("Çözücü hazır olmadı",
                       "Çözücü başlatıldı ama zamanında hazır olmadı. Python paketleri " +
                       "(CircuitAnalyzer.API\\requirements.txt) kurulu mu?")
                    : ("Çözücü hazır olmadı",
                       "Devreleri çözen program parçası başlatıldı ama zamanında hazır olmadı. " +
                       "Bilgisayar o sırada çok meşgul olabilir. Birkaç saniye sonra yeniden deneyin."),
                BackendFailure.Stopped => ("Çözücü kapandı",
                    "Devreleri çözen program parçası beklenmedik biçimde kapandı. Yeniden deneyin; " +
                    "çizdiğiniz devre yerinde kalır."),
                BackendFailure.Timeout => ("Çözüm zamanında bitmedi",
                    (requestMessage ?? "Çözücü zamanında yanıt vermedi. Devre çok büyük olabilir.") +
                    "\n\n“Yeniden dene” çözücüyü yeniden başlatır; çizdiğiniz devre yerinde kalır. " +
                    "Devreyi küçültüp yeniden çözebilirsiniz."),
                _ => ("Çözücüye ulaşılamadı",
                    "Devreleri çözen program parçasına ulaşılamadı. Yeniden deneyin; " +
                    "çizdiğiniz devre yerinde kalır."),
            };

            if (developerRun && !string.IsNullOrWhiteSpace(detail))
                text += "\n\n" + detail.Trim();
            return (title, text);
        }
    }
}
