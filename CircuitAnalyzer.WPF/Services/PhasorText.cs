using System.Text;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Fazör değerinin ("21,94∠−36,87° A") dar kartta "21,94∠" / "−36,87° A" diye iki satıra
    /// bölünmesini önler. YALNIZ EKRAN içindir: sonuç yazıları panoya, dosyaya, yazdırma
    /// tablosuna, yapay zekâya ya da ayrıştırıcıya giderken bu karakterler olmamalıdır;
    /// o yollarda <see cref="Strip"/> ile temizlenir ya da hiç eklenmez.
    /// </summary>
    public static class PhasorText
    {
        /// <summary>U+2060 WORD JOINER: görünmez, iki yanındaki karakterlerin ayrılmasını engeller.</summary>
        public const char WordJoiner = '⁠';

        /// <summary>U+00A0 NO-BREAK SPACE: değer ile birim arasında satır bölünmez.</summary>
        public const char NoBreakSpace = ' ';

        /// <summary>
        /// "∠" içeren değerde sayı, ∠, açı ve birimi bir arada tutar. ∠ içermeyen yazıya dokunmaz.
        /// </summary>
        public static string KeepTogether(string? text)
        {
            if (string.IsNullOrEmpty(text) || text.IndexOf('∠') < 0)
                return text ?? "";

            var sb = new StringBuilder(text.Length + 4);
            foreach (char c in text)
            {
                switch (c)
                {
                    case '∠':
                        sb.Append(WordJoiner).Append(c).Append(WordJoiner);
                        break;
                    case ' ':
                        sb.Append(NoBreakSpace);
                        break;
                    default:
                        sb.Append(c);
                        break;
                }
            }
            return sb.ToString();
        }

        /// <summary>Ekran için eklenen karakterleri geri alır (panoya / dosyaya / ayrıştırıcıya giderken).</summary>
        public static string Strip(string? text)
        {
            if (string.IsNullOrEmpty(text))
                return text ?? "";
            return text.Replace(WordJoiner.ToString(), "").Replace(NoBreakSpace, ' ');
        }
    }
}
