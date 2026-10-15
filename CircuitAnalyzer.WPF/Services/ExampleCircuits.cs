using System;
using System.Collections.Generic;
using System.Windows;
using CircuitAnalyzer.WPF.Models;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>Hazır örnek devre: elemanlar (konum/dönüş ayarlı) + teller.</summary>
    public sealed class ExampleCircuit
    {
        public string Name { get; init; } = "";
        public string Description { get; init; } = "";
        public List<CircuitElement> Elements { get; } = new();
        public List<Wire> Wires { get; } = new();

        /// <summary>Önerilen analiz (ör: Thevenin örneği için port).</summary>
        public string SuggestedAnalysisType { get; init; } = AnalysisTypes.Nodal;
        public string? SuggestedTerminal { get; init; }

        /// <summary>Rastgele üretilmiş sorunun kodu (hazır örneklerde null).</summary>
        public int? ProblemCode { get; init; }

        internal T Add<T>(T element, string id, double x, double y, double rotation = 0)
            where T : CircuitElement
        {
            element.Id = id;
            element.Position = new Point(x, y);
            element.Rotation = rotation;
            Elements.Add(element);
            return element;
        }

        /// <summary>
        /// Tel: önce yatay, sonra dikey çizilir (Wire.CreateOrUpdateVisual).
        /// Köşenin üstte kalması için başlangıç pini üstteki pindir.
        /// </summary>
        internal void Connect(Pin from, Pin to) => Wires.Add(new Wire(from, to));
    }

    /// <summary>
    /// Öğrenciler için hazır örnek devreler — ders kitaplarındaki klasik sorular.
    ///
    /// Yerleşim (grid = 20 px): 80×40'lık elemanlar 90° döndürülünce pinleri
    /// merkezin 40 px üstüne/altına gelir. Kaynak 90° döndürülünce (+) üstte olur.
    ///   Kaynak  @ (100,200) rot 90 → (+) (140,180), (−) (140,260)
    ///   Üst R   @ (200,100)        → pinler (200,120), (280,120)
    ///   Dikey R @ (300,200) rot 90 → pinler (340,180), (340,260)
    ///   GND     @ (220,300)        → pin (240,300)
    ///
    /// Yerleşimler (Layout…) eleman örneklerini dışarıdan alır; hem hazır
    /// örnekler hem de rastgele soru üreticisi (ProblemGenerator) kullanır.
    /// </summary>
    public static class ExampleCircuits
    {
        public static IReadOnlyList<Func<ExampleCircuit>> All { get; } = new Func<ExampleCircuit>[]
        {
            DcVoltageDivider,
            DcLadderThevenin,
            AcRcLowPass,
            AcRlSeries,
            DcMeshWithCurrentSource,
            DcSuperpositionTwoSources,
        };

        // ═══════════════════════════════════════════════════════
        //  YERLEŞİMLER
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Kaynak – üst eleman – dikey eleman (tek düğüm: 2).
        ///   source rot 90, top @ (200,100), shunt @ (300,200) rot 90
        /// </summary>
        internal static ExampleCircuit LayoutSeriesShunt(
            ExampleCircuit c, CircuitElement source, string sourceId,
            CircuitElement top, string topId, CircuitElement shunt, string shuntId)
        {
            var src = c.Add(source, sourceId, 100, 200, 90);
            var t = c.Add(top, topId, 200, 100);
            var sh = c.Add(shunt, shuntId, 300, 200, 90);
            var gnd = c.Add(new GroundElement(), "GND1", 220, 300);

            c.Connect(t.Pins[0], src.Pins[0]);
            c.Connect(t.Pins[1], sh.Pins[0]);
            c.Connect(src.Pins[1], gnd.Pins[0]);
            c.Connect(sh.Pins[1], gnd.Pins[0]);
            return c;
        }

        /// <summary>
        /// Merdiven: kaynak – üst1 – dikey1 – üst2 – dikey2 (düğümler 1, 2, 3).
        /// </summary>
        internal static ExampleCircuit LayoutLadder(
            ExampleCircuit c, CircuitElement source, string sourceId,
            CircuitElement top1, string top1Id, CircuitElement shunt1, string shunt1Id,
            CircuitElement top2, string top2Id, CircuitElement shunt2, string shunt2Id)
        {
            var src = c.Add(source, sourceId, 100, 200, 90);
            var t1 = c.Add(top1, top1Id, 200, 100);
            var s1 = c.Add(shunt1, shunt1Id, 300, 200, 90);
            var t2 = c.Add(top2, top2Id, 400, 100);
            var s2 = c.Add(shunt2, shunt2Id, 500, 200, 90);
            var gnd = c.Add(new GroundElement(), "GND1", 220, 300);

            c.Connect(t1.Pins[0], src.Pins[0]);
            c.Connect(t1.Pins[1], s1.Pins[0]);
            c.Connect(t2.Pins[0], s1.Pins[0]);
            c.Connect(t2.Pins[1], s2.Pins[0]);
            c.Connect(src.Pins[1], gnd.Pins[0]);
            c.Connect(s1.Pins[1], gnd.Pins[0]);
            c.Connect(s2.Pins[1], gnd.Pins[0]);
            return c;
        }

        /// <summary>
        /// İki gözlü devre: sol kaynak – üst1 – orta dikey – üst2 – sağ kaynak.
        /// Sağ kaynak 90° (gerilim kaynağı, (+) üstte) ya da 270° (akım kaynağı,
        /// ok yukarı → akımı üst düğüme verir) döndürülür.
        /// </summary>
        internal static ExampleCircuit LayoutTwoLoop(
            ExampleCircuit c, CircuitElement left, string leftId,
            CircuitElement top1, string top1Id, CircuitElement middle, string middleId,
            CircuitElement top2, string top2Id, CircuitElement right, string rightId,
            double rightRotation)
        {
            var l = c.Add(left, leftId, 100, 200, 90);
            var t1 = c.Add(top1, top1Id, 200, 100);
            var m = c.Add(middle, middleId, 300, 200, 90);
            var t2 = c.Add(top2, top2Id, 400, 100);
            var r = c.Add(right, rightId, 500, 200, rightRotation);
            var gnd = c.Add(new GroundElement(), "GND1", 220, 300);

            // 270°'de pinlerin yeri yer değiştirir: Pins[1] üstte
            bool flipped = Math.Abs(rightRotation - 270) < 1e-9;
            Pin rightTop = flipped ? r.Pins[1] : r.Pins[0];
            Pin rightBottom = flipped ? r.Pins[0] : r.Pins[1];

            c.Connect(t1.Pins[0], l.Pins[0]);
            c.Connect(t1.Pins[1], m.Pins[0]);
            c.Connect(t2.Pins[0], m.Pins[0]);
            c.Connect(t2.Pins[1], rightTop);
            c.Connect(l.Pins[1], gnd.Pins[0]);
            c.Connect(m.Pins[1], gnd.Pins[0]);
            c.Connect(rightBottom, gnd.Pins[0]);
            return c;
        }

        // ═══════════════════════════════════════════════════════
        //  HAZIR ÖRNEKLER
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// İki gözlü devre, sağ dış kolda akım kaynağı (çevre akımları yöntemi).
        /// El hesabı: V₂ = 8 V, V₃ = 10 V; sağ çevrenin akımı doğrudan I1 = 2 mA.
        /// Akım kaynağı 270° döndürülür: (+) uç altta, ok yukarı → akımı Düğüm 3'e verir.
        /// </summary>
        public static ExampleCircuit DcMeshWithCurrentSource() => LayoutTwoLoop(
            new ExampleCircuit
            {
                Name = "Akım Kaynaklı İki Gözlü Devre (Çevre Akımları)",
                Description = "10 V gerilim kaynağı ve 2 mA akım kaynağı. Çevre akımları yöntemiyle çözün.",
                SuggestedAnalysisType = AnalysisTypes.Mesh,
            },
            new VoltageSource { Value = 10 }, "V1",
            new Resistor { Value = 1000 }, "R1",
            new Resistor { Value = 2000 }, "R2",
            new Resistor { Value = 1000 }, "R3",
            new CurrentSource { Value = 0.002 }, "I1", 270);

        /// <summary>
        /// İki gerilim kaynaklı devre (süperpozisyon).
        /// El hesabı: V₂′ = 4.8 V (yalnız V1), V₂″ = 2.4 V (yalnız V2), V₂ = 7.2 V.
        /// </summary>
        public static ExampleCircuit DcSuperpositionTwoSources() => LayoutTwoLoop(
            new ExampleCircuit
            {
                Name = "İki Kaynaklı Devre (Süperpozisyon)",
                Description = "12 V ve 6 V kaynaklar. Her kaynağın etkisini ayrı bulup toplayın.",
                SuggestedAnalysisType = AnalysisTypes.Superposition,
            },
            new VoltageSource { Value = 12 }, "V1",
            new Resistor { Value = 1000 }, "R1",
            new Resistor { Value = 2000 }, "R2",
            new Resistor { Value = 1000 }, "R3",
            new VoltageSource { Value = 6 }, "V2", 90);

        /// <summary>V1 = 12 V, R1 = 1 kΩ, R2 = 2 kΩ → V(2) = 8 V, I = 4 mA.</summary>
        public static ExampleCircuit DcVoltageDivider()
        {
            var c = LayoutSeriesShunt(
                new ExampleCircuit
                {
                    Name = "DC Gerilim Bölücü",
                    Description = "12 V kaynak, 1 kΩ ve 2 kΩ seri dirençler. Orta noktanın gerilimi probla ölçülür.",
                },
                new VoltageSource { Value = 12 }, "V1",
                new Resistor { Value = 1000 }, "R1",
                new Resistor { Value = 2000 }, "R2");
            var r2 = c.Elements.Find(e => e.Id == "R2")!;
            var vp1 = c.Add(new TestProbe { Type = ProbeType.Voltage }, "VP1", 360, 120);
            c.Connect(vp1.Pins[0], r2.Pins[0]);
            return c;
        }

        /// <summary>
        /// Merdiven devre: Thevenin eşdeğeri düğüm 3'te.
        /// Vth = 12·(2k∥2k)/(1k+2k∥2k) · 1/2 = 3 V,  Zth = ((1k∥2k)+1k) ∥ 1k = 625 Ω
        /// </summary>
        public static ExampleCircuit DcLadderThevenin() => LayoutLadder(
            new ExampleCircuit
            {
                Name = "DC Merdiven Devre (Thevenin)",
                Description = "Thevenin eşdeğerini Düğüm 3 – GND arasında bulun.",
                SuggestedAnalysisType = AnalysisTypes.Thevenin,
                SuggestedTerminal = "3",
            },
            new VoltageSource { Value = 12 }, "V1",
            new Resistor { Value = 1000 }, "R1",
            new Resistor { Value = 2000 }, "R2",
            new Resistor { Value = 1000 }, "R3",
            new Resistor { Value = 1000 }, "R4");

        /// <summary>VAC = 10 V, 50 Hz; R = 100 Ω, C = 100 µF → |V(2)| = 3.033 V ∠ −72.34°.</summary>
        public static ExampleCircuit AcRcLowPass() => LayoutSeriesShunt(
            new ExampleCircuit
            {
                Name = "AC RC Alçak Geçiren Filtre",
                Description = "10 V, 50 Hz kaynak; çıkış kondansatör üzerinden alınır.",
            },
            new AcVoltageSource { Amplitude = 10, Frequency = 50, Phase = 0 }, "VAC1",
            new Resistor { Value = 100 }, "R1",
            new Capacitor { Value = 100e-6 }, "C1");

        /// <summary>VAC = 20 V ∠45°, 60 Hz; R = 50 Ω, L = 100 mH → |I| = 0.3194 A, cos φ = 0.80 geri.</summary>
        public static ExampleCircuit AcRlSeries() => LayoutSeriesShunt(
            new ExampleCircuit
            {
                Name = "AC RL Seri Devre (Güç)",
                Description = "20 V ∠45°, 60 Hz kaynak; R–L seri. Güç üçgenini ve güç faktörünü inceleyin.",
            },
            new AcVoltageSource { Amplitude = 20, Frequency = 60, Phase = 45 }, "VAC1",
            new Resistor { Value = 50 }, "R1",
            new Inductor { Value = 0.1 }, "L1");
    }
}
