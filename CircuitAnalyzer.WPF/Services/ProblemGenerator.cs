using System;
using System.Collections.Generic;
using CircuitAnalyzer.WPF.Models;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Rastgele alıştırma sorusu üretir. Her sorunun 4 haneli bir kodu vardır
    /// (1000–9999): aynı kod her bilgisayarda aynı devreyi verir — hoca
    /// "4821 numaralı soruyu çözün" dediğinde bütün sınıf aynı soruyu görür.
    ///
    /// Bu yüzden .NET'in Random sınıfı yerine sürümden bağımsız, kendi küçük
    /// sayı üretecimiz (LCG) kullanılır. Şablon listesinin SONUNA ekleme
    /// yapılabilir; mevcut şablonların sırası ve değer listeleri değişirse
    /// eski kodlar başka devre verir.
    /// </summary>
    /// <summary>Öğretmenin seçebileceği soru türleri.</summary>
    public enum ProblemKind
    {
        Any,
        Nodal,
        Mesh,
        Thevenin,
        Norton,
        Superposition,
        Ac,
    }

    public static class ProblemGenerator
    {
        public const int MinCode = 1000;
        public const int MaxCode = 9999;

        public static bool IsValidCode(int code) => code is >= MinCode and <= MaxCode;

        public static int NewCode() => Random.Shared.Next(MinCode, MaxCode + 1);

        /// <summary>Koddan devreyi üretir. Geçersiz kodda ArgumentOutOfRangeException.</summary>
        public static ExampleCircuit Generate(int code)
        {
            if (!IsValidCode(code))
                throw new ArgumentOutOfRangeException(nameof(code),
                    $"Soru kodu {MinCode}–{MaxCode} arasında olmalı.");
            var rng = new Lcg(code);
            var template = Templates[rng.Next(Templates.Length)];
            return template(rng, code);
        }

        // ═══════════════════════════════════════════════════════
        //  DEĞER LİSTELERİ (el hesabına uygun "temiz" değerler)
        // ═══════════════════════════════════════════════════════

        private static readonly double[] DcResistors = { 1e3, 2e3, 3e3, 4e3, 5e3, 6e3, 8e3, 10e3 };
        private static readonly double[] DcVoltages = { 5, 6, 9, 10, 12, 15, 18, 20, 24 };
        private static readonly double[] DcCurrents = { 1e-3, 2e-3, 3e-3, 4e-3, 5e-3 };

        private static readonly double[] AcResistors = { 10, 22, 47, 100, 220 };
        private static readonly double[] AcAmplitudes = { 5, 10, 12, 20 };
        private static readonly double[] AcPhases = { 0, 0, 30, 45, -30 };
        private static readonly double[] AcFrequencies = { 50, 60, 100, 1000 };
        /// <summary>E6 serisi tabanı: 1, 2.2, 4.7 × 10ⁿ.</summary>
        private static readonly double[] E3 = { 1.0, 2.2, 4.7 };

        // ═══════════════════════════════════════════════════════
        //  ŞABLONLAR
        // ═══════════════════════════════════════════════════════

        private delegate ExampleCircuit Template(Lcg rng, int code);

        private static readonly Template[] Templates =
        {
            DcDividerNodal,
            DcLadderNodal,
            DcLadderThevenin,
            DcLadderNorton,
            DcCurrentSourceMesh,
            DcCurrentSourceNodal,
            DcTwoSourcesSuperposition,
            DcTwoSourcesMesh,
            AcRcNodal,
            AcRlNodal,
            AcLadderThevenin,
        };

        /// <summary>Şablonların yöntemi ve AC olup olmadığı — Templates ile AYNI sırada.</summary>
        private static readonly (string Type, bool IsAc)[] TemplateInfo =
        {
            (AnalysisTypes.Nodal, false),
            (AnalysisTypes.Nodal, false),
            (AnalysisTypes.Thevenin, false),
            (AnalysisTypes.Norton, false),
            (AnalysisTypes.Mesh, false),
            (AnalysisTypes.Nodal, false),
            (AnalysisTypes.Superposition, false),
            (AnalysisTypes.Mesh, false),
            (AnalysisTypes.Nodal, true),
            (AnalysisTypes.Nodal, true),
            (AnalysisTypes.Thevenin, true),
        };

        // ═══════════════════════════════════════════════════════
        //  TÜRE GÖRE SORU (öğretmen "bir Thevenin sorusu" ister)
        // ═══════════════════════════════════════════════════════

        /// <summary>Menüdeki sıra ve Türkçe adlar.</summary>
        public static IReadOnlyList<(ProblemKind Kind, string Title)> Kinds { get; } = new[]
        {
            (ProblemKind.Any, "Rastgele (her tür)"),
            (ProblemKind.Nodal, "Düğüm gerilimleri (DC)"),
            (ProblemKind.Mesh, "Çevre akımları (DC)"),
            (ProblemKind.Thevenin, "Thevenin eşdeğeri"),
            (ProblemKind.Norton, "Norton eşdeğeri"),
            (ProblemKind.Superposition, "Süperpozisyon"),
            (ProblemKind.Ac, "AC devre (fazör)"),
        };

        /// <summary>Kodun hangi şablonu seçtiği — Generate ile aynı ilk sayı.</summary>
        private static int TemplateIndex(int code) => new Lcg(code).Next(Templates.Length);

        /// <summary>Bu koddan üretilen soru istenen türde mi?</summary>
        public static bool Matches(int code, ProblemKind kind)
        {
            if (!IsValidCode(code))
                return false;
            var (type, isAc) = TemplateInfo[TemplateIndex(code)];
            return kind switch
            {
                ProblemKind.Any => true,
                ProblemKind.Nodal => type == AnalysisTypes.Nodal && !isAc,
                ProblemKind.Mesh => type == AnalysisTypes.Mesh,
                ProblemKind.Thevenin => type == AnalysisTypes.Thevenin,
                ProblemKind.Norton => type == AnalysisTypes.Norton,
                ProblemKind.Superposition => type == AnalysisTypes.Superposition,
                ProblemKind.Ac => isAc,
                _ => false,
            };
        }

        /// <summary>
        /// İstenen türde rastgele kod. Kod hâlâ tek başına devreyi belirler:
        /// öğrenci aynı kodu girince tür seçmeden aynı soruyu görür.
        /// </summary>
        public static int NewCode(ProblemKind kind)
        {
            // Her tür şablonların en az 1/11'i → birkaç denemede bulunur
            for (int i = 0; i < 100_000; i++)
            {
                int code = NewCode();
                if (Matches(code, kind))
                    return code;
            }
            throw new InvalidOperationException($"'{kind}' türünde soru üretilemedi.");
        }

        private static ExampleCircuit Header(int code, string description, string type, string? terminal = null) => new()
        {
            Name = $"Soru #{code}",
            Description = description,
            SuggestedAnalysisType = type,
            SuggestedTerminal = terminal,
            ProblemCode = code,
        };

        private static Resistor R(double v) => new() { Value = v };

        private static ExampleCircuit DcDividerNodal(Lcg rng, int code) => ExampleCircuits.LayoutSeriesShunt(
            Header(code, "Düğüm 2'nin gerilimini ve eleman akımlarını bulun.", AnalysisTypes.Nodal),
            new VoltageSource { Value = rng.Pick(DcVoltages) }, "V1",
            R(rng.Pick(DcResistors)), "R1",
            R(rng.Pick(DcResistors)), "R2");

        private static ExampleCircuit DcLadder(Lcg rng, ExampleCircuit header) => ExampleCircuits.LayoutLadder(
            header,
            new VoltageSource { Value = rng.Pick(DcVoltages) }, "V1",
            R(rng.Pick(DcResistors)), "R1",
            R(rng.Pick(DcResistors)), "R2",
            R(rng.Pick(DcResistors)), "R3",
            R(rng.Pick(DcResistors)), "R4");

        private static ExampleCircuit DcLadderNodal(Lcg rng, int code) => DcLadder(rng,
            Header(code, "Düğüm gerilimleri yöntemiyle V₂ ve V₃'ü bulun.", AnalysisTypes.Nodal));

        private static ExampleCircuit DcLadderThevenin(Lcg rng, int code) => DcLadder(rng,
            Header(code, "Düğüm 3 – GND arasında Thevenin eşdeğerini bulun.", AnalysisTypes.Thevenin, "3"));

        private static ExampleCircuit DcLadderNorton(Lcg rng, int code) => DcLadder(rng,
            Header(code, "Düğüm 3 – GND arasında Norton eşdeğerini bulun.", AnalysisTypes.Norton, "3"));

        private static ExampleCircuit DcWithCurrentSource(Lcg rng, ExampleCircuit header) => ExampleCircuits.LayoutTwoLoop(
            header,
            new VoltageSource { Value = rng.Pick(DcVoltages) }, "V1",
            R(rng.Pick(DcResistors)), "R1",
            R(rng.Pick(DcResistors)), "R2",
            R(rng.Pick(DcResistors)), "R3",
            new CurrentSource { Value = rng.Pick(DcCurrents) }, "I1", 270);

        private static ExampleCircuit DcCurrentSourceMesh(Lcg rng, int code) => DcWithCurrentSource(rng,
            Header(code, "Çevre akımları yöntemiyle çözün.", AnalysisTypes.Mesh));

        private static ExampleCircuit DcCurrentSourceNodal(Lcg rng, int code) => DcWithCurrentSource(rng,
            Header(code, "Düğüm gerilimleri yöntemiyle çözün.", AnalysisTypes.Nodal));

        private static ExampleCircuit DcTwoSources(Lcg rng, ExampleCircuit header) => ExampleCircuits.LayoutTwoLoop(
            header,
            new VoltageSource { Value = rng.Pick(DcVoltages) }, "V1",
            R(rng.Pick(DcResistors)), "R1",
            R(rng.Pick(DcResistors)), "R2",
            R(rng.Pick(DcResistors)), "R3",
            new VoltageSource { Value = rng.Pick(DcVoltages) }, "V2", 90);

        private static ExampleCircuit DcTwoSourcesSuperposition(Lcg rng, int code) => DcTwoSources(rng,
            Header(code, "Her kaynağın Düğüm 2'ye katkısını ayrı bulup toplayın.", AnalysisTypes.Superposition));

        private static ExampleCircuit DcTwoSourcesMesh(Lcg rng, int code) => DcTwoSources(rng,
            Header(code, "Çevre akımları yöntemiyle çözün.", AnalysisTypes.Mesh));

        private static AcVoltageSource AcSource(Lcg rng, double frequency) => new()
        {
            Amplitude = rng.Pick(AcAmplitudes),
            Frequency = frequency,
            Phase = rng.Pick(AcPhases),
        };

        /// <summary>
        /// Reaktansı R'nin 0.5–2 katı olacak E6 değerini seçer (faz açısı ne
        /// 0°'ye ne 90°'ye yapışsın). Bobinde X = ωL, kondansatörde X = 1/(ωC).
        /// </summary>
        private static double PickReactive(Lcg rng, double r, double omega, bool capacitor)
        {
            double[] ratios = { 0.5, 0.75, 1.0, 1.5, 2.0 };
            double targetX = r * rng.Pick(ratios);
            double ideal = capacitor ? 1.0 / (omega * targetX) : targetX / omega;
            double best = ideal, bestErr = double.MaxValue;
            int decade = (int)Math.Floor(Math.Log10(ideal));
            for (int d = decade - 1; d <= decade + 1; d++)
                foreach (double m in E3)
                {
                    double v = m * Math.Pow(10, d);
                    double err = Math.Abs(Math.Log(v / ideal));
                    if (err < bestErr) { best = v; bestErr = err; }
                }
            // 2.2e-5 gibi kayan nokta artıklarını temizle
            return double.Parse(best.ToString("G3", System.Globalization.CultureInfo.InvariantCulture),
                                System.Globalization.CultureInfo.InvariantCulture);
        }

        private static ExampleCircuit AcRcNodal(Lcg rng, int code)
        {
            double f = rng.Pick(AcFrequencies);
            double r = rng.Pick(AcResistors);
            var src = AcSource(rng, f);
            return ExampleCircuits.LayoutSeriesShunt(
                Header(code, "Kondansatör gerilimini (V₂) fazör olarak bulun.", AnalysisTypes.Nodal),
                src, "VAC1", R(r), "R1",
                new Capacitor { Value = PickReactive(rng, r, 2 * Math.PI * f, capacitor: true) }, "C1");
        }

        private static ExampleCircuit AcRlNodal(Lcg rng, int code)
        {
            double f = rng.Pick(AcFrequencies);
            double r = rng.Pick(AcResistors);
            var src = AcSource(rng, f);
            return ExampleCircuits.LayoutSeriesShunt(
                Header(code, "Bobin gerilimini (V₂) ve devre akımını fazör olarak bulun.", AnalysisTypes.Nodal),
                src, "VAC1", R(r), "R1",
                new Inductor { Value = PickReactive(rng, r, 2 * Math.PI * f, capacitor: false) }, "L1");
        }

        private static ExampleCircuit AcLadderThevenin(Lcg rng, int code)
        {
            double f = rng.Pick(AcFrequencies);
            double omega = 2 * Math.PI * f;
            double r1 = rng.Pick(AcResistors);
            double r2 = rng.Pick(AcResistors);
            var src = AcSource(rng, f);
            return ExampleCircuits.LayoutLadder(
                Header(code, "Düğüm 3 – GND arasında Thevenin eşdeğerini (Vth, Zth) bulun.",
                       AnalysisTypes.Thevenin, "3"),
                src, "VAC1",
                R(r1), "R1",
                new Capacitor { Value = PickReactive(rng, r1, omega, capacitor: true) }, "C1",
                new Inductor { Value = PickReactive(rng, r2, omega, capacitor: false) }, "L1",
                R(r2), "R2");
        }

        // ═══════════════════════════════════════════════════════
        //  SÜRÜMDEN BAĞIMSIZ SAYI ÜRETECİ
        // ═══════════════════════════════════════════════════════

        /// <summary>64 bit doğrusal eşlenik üreteç (Knuth MMIX sabitleri).</summary>
        private sealed class Lcg
        {
            private ulong _state;

            public Lcg(int seed)
            {
                _state = (ulong)seed;
                NextUInt();
                NextUInt();
            }

            private uint NextUInt()
            {
                _state = unchecked(_state * 6364136223846793005UL + 1442695040888963407UL);
                return (uint)(_state >> 33);
            }

            public int Next(int n) => (int)(NextUInt() % (uint)n);

            public T Pick<T>(IReadOnlyList<T> items) => items[Next(items.Count)];
        }
    }
}
