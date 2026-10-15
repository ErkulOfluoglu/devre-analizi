using System.Reflection;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Uygulama üst veri ve lisans bilgileri.
    /// </summary>
    public static class AppInfo
    {
        public const string LicenseHolder = "Erkul Ofluoğlu";

        public const string Disclaimer =
            "Bu program bilgi paylaşımı ve eğitim amacıyla hazırlanmıştır. Olduğu gibi sunulur; " +
            "doğruluğu, eksiksizliği veya belirli bir amaca uygunluğu konusunda hiçbir garanti verilmez. " +
            "Sonuçları kendiniz kontrol edin. Programın kullanımından doğabilecek her türlü sonuçtan kullanıcı sorumludur; " +
            "geliştirici sorumlu tutulamaz. Bu koşulları kabul etmiyorsanız programı kullanmayın.";

        public static string Version
        {
            get
            {
                var asm = Assembly.GetExecutingAssembly();
                var ver = asm.GetName().Version;
                return ver != null ? $"{ver.Major}.{ver.Minor}.{ver.Build}" : "1.0.0";
            }
        }
    }
}
