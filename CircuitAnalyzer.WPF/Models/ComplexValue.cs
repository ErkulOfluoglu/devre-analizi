using System;
using System.Globalization;
using System.Text.RegularExpressions;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>
    /// Karmaşık sayı değeri — Fazör (Phasor) desteğinin temel yapı taşı.
    /// 
    /// İki gösterim formu arasında dönüşüm sağlar:
    /// 
    ///   Dikdörtgensel (Rectangular)       Kutupsal (Polar)
    ///        a + jb              ⟷          r ∠ θ°
    ///
    ///     a = reel kısım                 r = |Z| = √(a² + b²)
    ///     b = sanal kısım                θ = arg(Z) = atan2(b, a) [derece]
    ///
    /// Euler bağlantısı:
    ///   Z = r·e^(jθ) = r·(cosθ + j·sinθ) = a + jb
    ///   
    /// Neden System.Numerics.Complex yerine özel sınıf?
    ///   1. Açı birimi: System.Numerics.Complex radyan kullanır,
    ///      biz derece (°) kullanıyoruz — öğrenciler dereceye alışıktır.
    ///   2. Notasyon: Matematik 'i' kullanır, elektronik 'j' kullanır —
    ///      parser ikisini de kabul etmeli.
    ///   3. Formatlama: Netlist ve UI için özel gösterim gerekiyor.
    /// </summary>
    public class ComplexValue
    {
        /// <summary>Reel kısım (a). Direnç bileşeni (R) olarak yorumlanır.</summary>
        public double Real { get; set; }

        /// <summary>Sanal kısım (b). Reaktans bileşeni (X) olarak yorumlanır.</summary>
        public double Imaginary { get; set; }

        /// <summary>
        /// Büyüklük (Magnitude): |Z| = √(a² + b²)
        /// Empedansın toplam "büyüklüğü" — Ohm cinsinden.
        /// </summary>
        public double Magnitude => Math.Sqrt(Real * Real + Imaginary * Imaginary);

        /// <summary>
        /// Faz açısı (derece): θ = atan2(b, a) × (180/π)
        /// Gerilim ile akım arasındaki faz farkını belirler.
        ///   θ > 0 → indüktif (akım geride)
        ///   θ &lt; 0 → kapasitif (akım ileride)
        ///   θ = 0 → direnç (faz farkı yok)
        /// </summary>
        public double AngleDegrees =>
            Math.Abs(Magnitude) < 1e-15 ? 0 : Math.Atan2(Imaginary, Real) * (180.0 / Math.PI);

        // ═══════════════════════════════════════════════════
        //  FABRİKA METOTLARI (Static Factory Methods)
        // ═══════════════════════════════════════════════════

        /// <summary>Dikdörtgensel formdan oluştur: Z = a + jb</summary>
        public static ComplexValue FromRectangular(double real, double imaginary)
            => new ComplexValue { Real = real, Imaginary = imaginary };

        /// <summary>
        /// Kutupsal formdan oluştur: Z = r∠θ°
        /// Euler formülü ile kartezyen dönüşüm:
        ///   a = r · cos(θ)
        ///   b = r · sin(θ)
        /// </summary>
        public static ComplexValue FromPolar(double magnitude, double angleDegrees)
        {
            double angleRad = angleDegrees * Math.PI / 180.0;
            return new ComplexValue
            {
                Real = magnitude * Math.Cos(angleRad),
                Imaginary = magnitude * Math.Sin(angleRad)
            };
        }

        // ═══════════════════════════════════════════════════
        //  AKILLI PARSER (Çok Formatlı Ayrıştırıcı)
        // ═══════════════════════════════════════════════════

        /// <summary>
        /// Kullanıcının girdiği metni karmaşık sayıya çevirir.
        /// 
        /// ★ Desteklenen formatlar:
        /// 
        /// Dikdörtgensel (j notasyonu — elektronik standardı):
        ///   "50+j30"    →  50 + j30      ✓
        ///   "50-j30"    →  50 − j30      ✓
        ///   "50+30j"    →  50 + j30      ✓ (j sonda)
        ///   "j30"       →  0  + j30      ✓ (saf sanal)
        ///   "-j30"      →  0  − j30      ✓
        ///   "30j"       →  0  + j30      ✓
        ///   "j"         →  0  + j1       ✓ (birim sanal)
        ///   "50"        →  50 + j0       ✓ (saf reel)
        ///   
        /// Dikdörtgensel (i notasyonu — matematik geleneği):
        ///   "4+3i"      →  4  + j3       ✓ (i → j otomatik dönüşüm)
        ///   "4+i3"      →  4  + j3       ✓ (i önde)
        ///   "4-i3"      →  4  − j3       ✓
        ///   
        /// Kutupsal:
        ///   "10∠30"     →  10∠30°        ✓ (∠ sembolü)
        ///   "10∠30°"    →  10∠30°        ✓ (° dahil)
        ///   "10&lt;30"     →  10∠30°        ✓ (&lt; alternatif)
        ///   "10∠-45"    →  10∠-45°       ✓ (negatif açı)
        ///   
        /// Tüm formatlarda boşluk ve * karakteri yoksayılır:
        ///   "50 + j * 30" →  50 + j30    ✓
        /// </summary>
        public static bool TryParse(string input, out ComplexValue result)
        {
            result = new ComplexValue();
            if (string.IsNullOrWhiteSpace(input))
                return false;

            // ── Adım 1: Girdiyi temizle ──
            string s = input.Trim()
                .Replace(" ", "")
                .Replace("*", "")
                .Replace("°", "")
                .Replace('−', '-');   // ToRectangularString ve anlatım Unicode eksi kullanır

            // ── Adım 2: Kutupsal format kontrolü (∠ veya < ile) ──
            // Önce kontrol: çünkü "10<30" içindeki < işareti
            // dikdörtgensel parseri karıştırabilir.
            var polarPattern = new Regex(
                @"^([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)\s*[∠<]\s*([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)$");
            var polarMatch = polarPattern.Match(s);
            if (polarMatch.Success)
            {
                if (double.TryParse(polarMatch.Groups[1].Value.Replace(',', '.'),
                        NumberStyles.Float, CultureInfo.InvariantCulture, out double r) &&
                    double.TryParse(polarMatch.Groups[2].Value.Replace(',', '.'),
                        NumberStyles.Float, CultureInfo.InvariantCulture, out double theta))
                {
                    result = FromPolar(r, theta);
                    return true;
                }
            }

            // ── Adım 3: i → j normalizasyonu ──
            // "4+3i" → "4+3j",  "4+i3" → "4+j3"
            // DİKKAT: Bilimsel notasyondaki 'e' harfini korumak için
            // sadece 'e'/'E' harfinden sonra gelmeyen 'i'leri dönüştür.
            s = Regex.Replace(s, @"(?<![eE])i", "j");

            // ── Adım 4: 'j' yoksa → saf reel sayı ──
            if (!s.Contains('j'))
            {
                string realStr = s.Replace(',', '.');
                if (double.TryParse(realStr, NumberStyles.Float,
                    CultureInfo.InvariantCulture, out double realOnly))
                {
                    result = FromRectangular(realOnly, 0);
                    return true;
                }
                return false;
            }

            // ── Adım 5: 'j' var → karmaşık sayı ayrıştır ──

            // Birim sanal: "j" veya "-j" veya "+j"
            if (s == "j" || s == "+j")
            {
                result = FromRectangular(0, 1);
                return true;
            }
            if (s == "-j")
            {
                result = FromRectangular(0, -1);
                return true;
            }

            // Saf sanal, j önde: "j30", "-j30", "+j30", "j3.14", "j3,14"
            var jPrefixOnly = new Regex(
                @"^([+-]?)j((?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)$");
            var jPrefixOnlyMatch = jPrefixOnly.Match(s);
            if (jPrefixOnlyMatch.Success)
            {
                if (double.TryParse(jPrefixOnlyMatch.Groups[2].Value.Replace(',', '.'),
                    NumberStyles.Float, CultureInfo.InvariantCulture, out double imag))
                {
                    result = FromRectangular(0,
                        jPrefixOnlyMatch.Groups[1].Value == "-" ? -imag : imag);
                    return true;
                }
            }

            // Saf sanal, j sonda: "30j", "-30j", "+30j"
            var jSuffixOnly = new Regex(
                @"^([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)j$");
            var jSuffixOnlyMatch = jSuffixOnly.Match(s);
            if (jSuffixOnlyMatch.Success)
            {
                if (double.TryParse(jSuffixOnlyMatch.Groups[1].Value.Replace(',', '.'),
                    NumberStyles.Float, CultureInfo.InvariantCulture, out double imag))
                {
                    result = FromRectangular(0, imag);
                    return true;
                }
            }

            // Tam karmaşık, j önde: "50+j30", "50-j30", "-50+j30"
            // "50+j" → sanal kısım = 1
            var complexJPrefix = new Regex(
                @"^([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)([+-])j((?:\d*(?:[.,]\d*)?|[.,]\d+)?(?:[eE][+-]?\d+)?)$");
            var cjpMatch = complexJPrefix.Match(s);
            if (cjpMatch.Success)
            {
                string imagStr = cjpMatch.Groups[3].Value.Replace(',', '.');
                if (string.IsNullOrEmpty(imagStr)) imagStr = "1";

                if (double.TryParse(cjpMatch.Groups[1].Value.Replace(',', '.'),
                        NumberStyles.Float, CultureInfo.InvariantCulture, out double real) &&
                    double.TryParse(imagStr,
                        NumberStyles.Float, CultureInfo.InvariantCulture, out double imag))
                {
                    result = FromRectangular(real,
                        cjpMatch.Groups[2].Value == "-" ? -imag : imag);
                    return true;
                }
            }

            // Tam karmaşık, j sonda: "50+30j", "50-30j"
            var complexJSuffix = new Regex(
                @"^([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)([+-])((?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)j$");
            var cjsMatch = complexJSuffix.Match(s);
            if (cjsMatch.Success)
            {
                if (double.TryParse(cjsMatch.Groups[1].Value.Replace(',', '.'),
                        NumberStyles.Float, CultureInfo.InvariantCulture, out double real) &&
                    double.TryParse(cjsMatch.Groups[3].Value.Replace(',', '.'),
                        NumberStyles.Float, CultureInfo.InvariantCulture, out double imag))
                {
                    result = FromRectangular(real,
                        cjsMatch.Groups[2].Value == "-" ? -imag : imag);
                    return true;
                }
            }

            return false;
        }

        // ═══════════════════════════════════════════════════
        //  FORMATLAMA (Display & Netlist)
        // ═══════════════════════════════════════════════════

        /// <summary>
        /// Dikdörtgensel formatta gösterir: "50+j30" veya "50−j30"
        /// Elektronik mühendisliği standardında 'j' kullanılır.
        /// </summary>
        public string ToRectangularString()
        {
            if (Math.Abs(Imaginary) < 1e-10)
                return TurkishNumber.Format(Real, "G4");
            if (Math.Abs(Real) < 1e-10)
                return $"{(Imaginary < 0 ? "−" : "")}j{TurkishNumber.Format(Math.Abs(Imaginary), "G4")}";

            string sign = Imaginary >= 0 ? "+" : "−";
            return $"{TurkishNumber.Format(Real, "G4")}{sign}j{TurkishNumber.Format(Math.Abs(Imaginary), "G4")}";
        }

        /// <summary>
        /// Kutupsal formatta gösterir: "58.31∠30.96°" -> "58,31∠30,96°"
        /// </summary>
        public string ToPolarString()
        {
            if (Math.Abs(Magnitude) < 1e-10)
                return "0∠0°";
            return $"{TurkishNumber.Format(Magnitude, "G4")}∠{TurkishNumber.Format(AngleDegrees, "G4")}°";
        }

        /// <summary>
        /// Netlist COMPLEX formatı: "COMPLEX(50, 30)"
        /// Python backend bu formatı regex ile ayrıştırır.
        /// </summary>
        public string ToNetlistRectangular()
        {
            return $"COMPLEX({Real.ToString("G6", CultureInfo.InvariantCulture)}, " +
                   $"{Imaginary.ToString("G6", CultureInfo.InvariantCulture)})";
        }

        /// <summary>
        /// Netlist POLAR formatı: "POLAR(58.31, 30.96)"
        /// </summary>
        public string ToNetlistPolar()
        {
            return $"POLAR({Magnitude.ToString("G6", CultureInfo.InvariantCulture)}, " +
                   $"{AngleDegrees.ToString("G6", CultureInfo.InvariantCulture)})";
        }

        public override string ToString() => ToRectangularString();
    }
}
