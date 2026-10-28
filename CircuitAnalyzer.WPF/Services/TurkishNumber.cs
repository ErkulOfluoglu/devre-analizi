using System;
using System.Globalization;
using System.Text.RegularExpressions;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Türkçe sayı biçimlendirme ve ayrıştırma yardımcı sınıfı.
    /// UI'da ondalık ayırıcı olarak virgül (",") gösterilmesini ve
    /// kullanıcının hem "." hem "," girmesine izin verilmesini sağlar.
    /// Binlik ayırıcı kullanılmaz.
    /// </summary>
    public static class TurkishNumber
    {
        public static readonly CultureInfo Culture = CultureInfo.GetCultureInfo("tr-TR");

        private static readonly Regex SpiceNumberRegex = new(
            @"^\s*([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-ZµΩ°]*)\s*$",
            RegexOptions.Compiled);

        private static readonly Regex DecimalDotRegex = new(
            @"(?<=\d)\.(?=\d)",
            RegexOptions.Compiled);

        /// <summary>
        /// Sayıyı Türkçe kültürüne göre (ondalık virgülüyle) biçimlendirir.
        /// </summary>
        public static string Format(double value, string? format = null)
        {
            return string.IsNullOrEmpty(format)
                ? value.ToString(Culture)
                : value.ToString(format, Culture);
        }

        /// <summary>
        /// Sayısal metin içerisindeki iki basamak arasındaki ondalık noktalarını virgüle çevirir.
        /// Örnek: "10.09 V" -> "10,09 V", "3.5-j4.5" -> "3,5-j4,5".
        /// </summary>
        public static string NormalizeForDisplay(string? text)
        {
            if (string.IsNullOrEmpty(text))
                return text ?? string.Empty;

            return DecimalDotRegex.Replace(text, ",");
        }

        /// <summary>
        /// Hem "." hem "," ondalık ayırıcısını kabul eden sayı ayrıştırıcı.
        /// Asla binlik ayırıcı olarak kabul etmez.
        /// </summary>
        public static bool TryParse(string? text, out double value)
        {
            value = 0;
            if (string.IsNullOrWhiteSpace(text))
                return false;

            string trimmed = text.Trim();
            int dotCount = 0;
            int commaCount = 0;
            for (int i = 0; i < trimmed.Length; i++)
            {
                if (trimmed[i] == '.') dotCount++;
                else if (trimmed[i] == ',') commaCount++;
            }

            // Birden fazla ayırıcı varsa (ör. "1.000,5" veya "1.2.3") geçersizdir
            if (dotCount + commaCount > 1)
                return false;

            string normalized = trimmed.Replace(',', '.');
            return double.TryParse(normalized, NumberStyles.Float, CultureInfo.InvariantCulture, out value);
        }

        /// <summary>
        /// SPICE mühendislik öneklerini (k, m, u/µ, n, p vb.) ve hem "." hem "," ondalık ayırıcısını
        /// destekleyen ayrıştırıcı.
        /// Örnek: "4,7k", "4.7k", "2,2 mA", "0,5"
        /// </summary>
        public static bool TryParseSpice(string? text, out double val)
        {
            val = 0;
            if (string.IsNullOrWhiteSpace(text))
                return false;

            var match = SpiceNumberRegex.Match(text.Trim());
            if (!match.Success)
                return false;

            string numPart = match.Groups[1].Value.Replace(',', '.');
            if (!double.TryParse(numPart, NumberStyles.Float, CultureInfo.InvariantCulture, out double num))
                return false;

            string suffix = match.Groups[2].Value.ToLowerInvariant();
            if (string.IsNullOrEmpty(suffix))
            {
                val = num;
                return true;
            }

            double multiplier = 1.0;
            if (suffix.StartsWith("meg")) multiplier = 1e6;
            else if (suffix.StartsWith("mil")) multiplier = 25.4e-6;
            else if (suffix.StartsWith("g")) multiplier = 1e9;
            else if (suffix.StartsWith("t")) multiplier = 1e12;
            else if (suffix.StartsWith("k")) multiplier = 1e3;
            else if (suffix.StartsWith("m")) multiplier = 1e-3;
            else if (suffix.StartsWith("u") || suffix.StartsWith("µ")) multiplier = 1e-6;
            else if (suffix.StartsWith("n")) multiplier = 1e-9;
            else if (suffix.StartsWith("p")) multiplier = 1e-12;
            else if (suffix.StartsWith("f")) multiplier = 1e-15;
            else if (suffix == "a" || suffix == "v" || suffix == "hz" || suffix == "ohm" || suffix == "ω" || suffix == "h")
                multiplier = 1.0;
            else
                return false;

            val = num * multiplier;
            return true;
        }
    }
}
