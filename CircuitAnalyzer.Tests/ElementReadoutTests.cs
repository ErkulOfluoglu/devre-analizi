using System.Windows;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.Tests
{
    /// <summary>
    /// Seçili elemanın cam kartı: akım ve yönü, uçlarındaki gerilim, güç ve DC'de düğümdeki
    /// akım dengesi çözüm sonuçlarından doğru kurulur.
    /// </summary>
    public class ElementReadoutTests
    {
        private static ElementCurrentDto Dc(double amps, string direction) =>
            new() { Value = ResultValue.FromReal(amps), Unit = "A", Direction = direction };

        // V1 (10 V, 2 A) ortak uçtan iki paralel dirence: R1 1,5 A, R2 0,5 A
        private static (List<CircuitElement> Els, Dictionary<Pin, int> Map, AnalysisResultsDto Results) Parallel()
        {
            var v = new VoltageSource { Id = "V1", Position = new Point(0, 0), Value = 10, Unit = "V" };
            var r1 = new Resistor { Id = "R1", Position = new Point(100, 0), Value = 20, Unit = "Ω" };
            var r2 = new Resistor { Id = "R2", Position = new Point(100, 100), Value = 20, Unit = "Ω" };
            var map = new Dictionary<Pin, int>
            {
                [v.Pins[0]] = 1, [r1.Pins[0]] = 1, [r2.Pins[0]] = 1,
                [r1.Pins[1]] = 0, [r2.Pins[1]] = 0, [v.Pins[1]] = 0,
            };
            var results = new AnalysisResultsDto
            {
                NodeVoltages = new() { ["1"] = new NodeVoltageDto { Value = ResultValue.FromReal(10) } },
                ElementCurrents = new()
                {
                    ["V1"] = Dc(2, "0→1"), ["R1"] = Dc(1.5, "1→0"), ["R2"] = Dc(0.5, "1→0"),
                },
                Power = new PowerAnalysisDto
                {
                    Elements = new()
                    {
                        ["V1"] = new ElementPowerDto { ElementId = "V1", Role = "source", ActivePower = -20 },
                        ["R1"] = new ElementPowerDto { ElementId = "R1", Role = "load", ActivePower = 15 },
                    }
                }
            };
            return (new List<CircuitElement> { v, r1, r2 }, map, results);
        }

        [Fact]
        public void Resistor_ShowsCurrentVoltagePowerAndNodeBalance()
        {
            var (els, map, results) = Parallel();

            var r = ElementReadoutBuilder.Build(els[1], els, map, results, isDc: true);

            Assert.NotNull(r);
            Assert.Equal("R1", r!.Name);
            Assert.Equal(EngFormat.Format(20, "Ω"), r.Value);
            Assert.Equal(EngFormat.Format(1.5, "A"), r.Current);
            Assert.Equal("Düğüm 1 → 0", r.Direction);
            Assert.Equal(EngFormat.Format(10, "V"), r.Voltage);
            Assert.Equal(EngFormat.Format(15, "W"), r.Power);
            Assert.Equal(
                $"Düğüm 1: giren {EngFormat.Format(2, "A")} (V1) = çıkan {EngFormat.Format(1.5, "A")} (R1) + {EngFormat.Format(0.5, "A")} (R2)",
                r.NodeBalance);
        }

        [Fact]
        public void Source_SaysItDelivers_AndBalanceUsesItsNonGroundNode()
        {
            var (els, map, results) = Parallel();

            var r = ElementReadoutBuilder.Build(els[0], els, map, results, isDc: true);

            Assert.NotNull(r);
            Assert.Equal("Düğüm 0 → 1", r!.Direction);
            Assert.Equal(EngFormat.Format(10, "V"), r.Voltage); // büyüklük; yönü akım satırı söyler
            Assert.Equal(EngFormat.Format(20, "W") + " (verir)", r.Power);
            Assert.StartsWith("Düğüm 1:", r.NodeBalance);
        }

        [Fact]
        public void Ac_HasNoNodeBalance_AndUnknownCurrentHasNoCard()
        {
            var (els, map, results) = Parallel();

            Assert.Null(ElementReadoutBuilder.Build(els[1], els, map, results, isDc: false)!.NodeBalance);

            results.ElementCurrents.Remove("R2");
            Assert.Null(ElementReadoutBuilder.Build(els[2], els, map, results, isDc: true));
            // Düğümde akımı bilinmeyen bir eleman varsa denge yazılmaz
            Assert.Null(ElementReadoutBuilder.Build(els[1], els, map, results, isDc: true)!.NodeBalance);
        }
    }
}
