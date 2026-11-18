using System;
using System.IO;
using System.Text;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Beklenmeyen hataları bir dosyaya yazar (öğrenci "bir şey oldu" der, ayrıntı elde kalsın).
    /// Yazma hatası sessizce yutulur: hata kaydı programı ikinci kez çökertmesin.
    /// </summary>
    public static class CrashLog
    {
        private static readonly object Gate = new();
        private const long MaxBytes = 512 * 1024;

        /// <summary>Hata dosyası (testler geçici bir yol verebilir).</summary>
        public static string LogPath { get; set; } = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "CircuitAnalyzer", "hata.log");

        /// <summary>Hatayı tarih ve kaynakla dosyanın sonuna ekler. Yazılabildiyse true.</summary>
        public static bool Write(Exception? ex, string source)
        {
            try
            {
                lock (Gate)
                {
                    string? dir = Path.GetDirectoryName(LogPath);
                    if (!string.IsNullOrEmpty(dir))
                        Directory.CreateDirectory(dir);

                    // Dosya şişmesin: büyürse eskisi .eski olarak bir kez yedeklenir
                    var info = new FileInfo(LogPath);
                    if (info.Exists && info.Length > MaxBytes)
                    {
                        string old = LogPath + ".eski";
                        if (File.Exists(old))
                            File.Delete(old);
                        File.Move(LogPath, old);
                    }

                    var sb = new StringBuilder();
                    sb.Append('[').Append(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")).Append("] ").AppendLine(source);
                    sb.AppendLine(ex?.ToString() ?? "(ayrıntı yok)");
                    sb.AppendLine();
                    File.AppendAllText(LogPath, sb.ToString(), Encoding.UTF8);
                    return true;
                }
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>Öğrenciye gösterilen kısa Türkçe ileti.</summary>
        public static string UserMessage() =>
            $"Beklenmeyen bir hata oldu. Çalışmanızı kaydetmenizi öneririz. Ayrıntı: {LogPath}";
    }
}
