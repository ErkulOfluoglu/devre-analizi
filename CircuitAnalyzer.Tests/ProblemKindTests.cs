using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests
{
    [Collection(WpfUiCollection.Name)]
    public class ProblemKindTests
    {
        private static void RunOnSta(Action action)
        {
            Exception? ex = null;
            var thread = new Thread(() =>
            {
                try
                {
                    action();
                }
                catch (Exception e)
                {
                    ex = e;
                }
            });
            thread.SetApartmentState(ApartmentState.STA);
            thread.Start();
            thread.Join();

            if (ex != null)
            {
                ExceptionDispatchInfo.Capture(ex).Throw();
            }
        }

        private static bool CircuitMatchesKind(ExampleCircuit c, ProblemKind kind) => kind switch
        {
            ProblemKind.Any => true,
            ProblemKind.Nodal => c.SuggestedAnalysisType == AnalysisTypes.Nodal && !c.Elements.Any(e => e is AcVoltageSource),
            ProblemKind.Mesh => c.SuggestedAnalysisType == AnalysisTypes.Mesh,
            ProblemKind.Thevenin => c.SuggestedAnalysisType == AnalysisTypes.Thevenin,
            ProblemKind.Norton => c.SuggestedAnalysisType == AnalysisTypes.Norton,
            ProblemKind.Superposition => c.SuggestedAnalysisType == AnalysisTypes.Superposition,
            ProblemKind.Ac => c.Elements.Any(e => e is AcVoltageSource),
            _ => false,
        };

        // 1) ProblemGenerator.Kinds contains every ProblemKind value exactly once, first item is ProblemKind.Any, titles non-empty.
        [Fact]
        public void Kinds_ContainsEveryProblemKindExactlyOnce_FirstIsAny_TitlesNonEmpty()
        {
            var allKinds = Enum.GetValues<ProblemKind>();

            Assert.Equal(allKinds.Length, ProblemGenerator.Kinds.Count);
            Assert.Equal(allKinds.Length, ProblemGenerator.Kinds.Select(k => k.Kind).Distinct().Count());
            Assert.Equal(ProblemKind.Any, ProblemGenerator.Kinds[0].Kind);

            foreach (var (kind, title) in ProblemGenerator.Kinds)
            {
                Assert.Contains(kind, allKinds);
                Assert.False(string.IsNullOrWhiteSpace(title));
            }
        }

        // 2) For each kind (Theory over all ProblemKind values): call NewCode(kind) 40 times -> each code IsValidCode and Matches(code, kind);
        //    generate the circuit and check it really is that kind
        [Theory]
        [InlineData(ProblemKind.Any)]
        [InlineData(ProblemKind.Nodal)]
        [InlineData(ProblemKind.Mesh)]
        [InlineData(ProblemKind.Thevenin)]
        [InlineData(ProblemKind.Norton)]
        [InlineData(ProblemKind.Superposition)]
        [InlineData(ProblemKind.Ac)]
        public void NewCode_GeneratesMatchingCircuits(ProblemKind kind)
        {
            for (int i = 0; i < 40; i++)
            {
                int code = ProblemGenerator.NewCode(kind);

                Assert.True(ProblemGenerator.IsValidCode(code), $"Kod {code} geçersiz.");
                Assert.True(ProblemGenerator.Matches(code, kind), $"Matches({code}, {kind}) false döndü.");

                var circuit = ProblemGenerator.Generate(code);
                Assert.True(CircuitMatchesKind(circuit, kind), $"Devre {code} {kind} kuralına uymuyor.");
            }
        }

        // 3) Consistency over codes 1000..3999: for every code and every kind, Matches(code, kind) == (the rule above applied to Generate(code)).
        [Fact]
        public void ConsistencyOverCodes1000To3999_MatchesReflectsGeneratedCircuit()
        {
            var kinds = Enum.GetValues<ProblemKind>();

            for (int code = 1000; code <= 3999; code++)
            {
                var circuit = ProblemGenerator.Generate(code);
                foreach (var kind in kinds)
                {
                    bool expected = CircuitMatchesKind(circuit, kind);
                    bool actual = ProblemGenerator.Matches(code, kind);
                    Assert.True(expected == actual,
                        $"Uyumsuzluk: code={code}, kind={kind}, expected={expected}, actual={actual}");
                }
            }
        }

        // 4) Every kind except Any has at least one matching code in 1000..9999 and covers at least 3% of the codes.
        [Fact]
        public void EveryKindExceptAny_HasMatchingCodesAndCoversAtLeast3Percent()
        {
            const int minCode = 1000;
            const int maxCode = 9999;
            const int totalCodes = maxCode - minCode + 1;

            var kinds = Enum.GetValues<ProblemKind>().Where(k => k != ProblemKind.Any).ToList();
            var counts = kinds.ToDictionary(k => k, _ => 0);

            for (int code = minCode; code <= maxCode; code++)
            {
                foreach (var kind in kinds)
                {
                    if (ProblemGenerator.Matches(code, kind))
                    {
                        counts[kind]++;
                    }
                }
            }

            foreach (var kind in kinds)
            {
                int count = counts[kind];
                Assert.True(count > 0, $"{kind} türünde 1000..9999 arasında hiç soru kodu bulunamadı.");
                double coverage = (double)count / totalCodes;
                Assert.True(coverage >= 0.03,
                    $"{kind} türü kodların %{coverage * 100:F2}'sini kapsıyor, en az %3 bekleniyordu.");
            }
        }

        // 5) Matches(999, Any), Matches(10000, Any) are false.
        [Fact]
        public void Matches_OutsideRange_ReturnsFalse()
        {
            Assert.False(ProblemGenerator.Matches(999, ProblemKind.Any));
            Assert.False(ProblemGenerator.Matches(10000, ProblemKind.Any));
        }

        // 6) Code stability (teachers share codes, so a code must keep producing the same circuit):
        //    Generate(4821) twice gives identical element ids, types and values;
        //    and record the CURRENT values for codes 1000, 4821 and 9999 (SuggestedAnalysisType + element id list + resistor values)
        //    as hard-coded expectations in the test.
        [Fact]
        public void CodeStability_Generate4821Twice_ProducesIdenticalCircuits()
        {
            var c1 = ProblemGenerator.Generate(4821);
            var c2 = ProblemGenerator.Generate(4821);

            Assert.Equal(c1.Elements.Count, c2.Elements.Count);
            for (int i = 0; i < c1.Elements.Count; i++)
            {
                var e1 = c1.Elements[i];
                var e2 = c2.Elements[i];

                Assert.Equal(e1.Id, e2.Id);
                Assert.Equal(e1.GetType(), e2.GetType());

                switch (e1)
                {
                    case Resistor r1 when e2 is Resistor r2:
                        Assert.Equal(r1.Value, r2.Value);
                        break;
                    case Capacitor cap1 when e2 is Capacitor cap2:
                        Assert.Equal(cap1.Value, cap2.Value);
                        break;
                    case Inductor ind1 when e2 is Inductor ind2:
                        Assert.Equal(ind1.Value, ind2.Value);
                        break;
                    case VoltageSource vs1 when e2 is VoltageSource vs2:
                        Assert.Equal(vs1.Value, vs2.Value);
                        break;
                    case CurrentSource cs1 when e2 is CurrentSource cs2:
                        Assert.Equal(cs1.Value, cs2.Value);
                        break;
                    case AcVoltageSource ac1 when e2 is AcVoltageSource ac2:
                        Assert.Equal(ac1.Amplitude, ac2.Amplitude);
                        Assert.Equal(ac1.Frequency, ac2.Frequency);
                        Assert.Equal(ac1.Phase, ac2.Phase);
                        break;
                    case AcCurrentSource ac1 when e2 is AcCurrentSource ac2:
                        Assert.Equal(ac1.Amplitude, ac2.Amplitude);
                        Assert.Equal(ac1.Frequency, ac2.Frequency);
                        Assert.Equal(ac1.Phase, ac2.Phase);
                        break;
                }
            }
        }

        [Theory]
        [InlineData(1000, AnalysisTypes.Thevenin,
            new[] { "VAC1", "R1", "C1", "L1", "R2", "GND1" },
            new[] { 47.0, 10.0 })]
        [InlineData(4821, AnalysisTypes.Nodal,
            new[] { "V1", "R1", "R2", "R3", "I1", "GND1" },
            new[] { 4000.0, 8000.0, 5000.0 })]
        [InlineData(9999, AnalysisTypes.Norton,
            new[] { "V1", "R1", "R2", "R3", "R4", "GND1" },
            new[] { 8000.0, 8000.0, 3000.0, 3000.0 })]
        public void CodeStability_HardcodedExpectationsForCodes(
            int code,
            string expectedSuggestedAnalysisType,
            string[] expectedElementIds,
            double[] expectedResistorValues)
        {
            var circuit = ProblemGenerator.Generate(code);

            Assert.Equal(expectedSuggestedAnalysisType, circuit.SuggestedAnalysisType);
            Assert.Equal(expectedElementIds, circuit.Elements.Select(e => e.Id).ToArray());

            var actualResistors = circuit.Elements.OfType<Resistor>().Select(r => r.Value).ToArray();
            Assert.Equal(expectedResistorValues, actualResistors);
        }

        // 7) WPF (STA, [Collection(WpfUiCollection.Name)]): new AnalysisPanel(); SetProblemCode(4821) -> CardProblemCode.Visibility == Visible,
        //    TxtProblemCodeBig.Text == "Soru kodu: 4821", ProblemCodeText == "Soru #4821"; SetProblemCode(null) -> CardProblemCode Collapsed and
        //    ProblemCodeText null.
        [Fact]
        public void Wpf_AnalysisPanel_SetProblemCode_UpdatesVisibilityAndText()
        {
            RunOnSta(() =>
            {
                var panel = new AnalysisPanel();

                panel.SetProblemCode(4821);
                Assert.Equal(Visibility.Visible, panel.CardProblemCode.Visibility);
                Assert.Equal("Soru kodu: 4821", panel.TxtProblemCodeBig.Text);
                Assert.Equal("Soru #4821", panel.ProblemCodeText);

                panel.SetProblemCode(null);
                Assert.Equal(Visibility.Collapsed, panel.CardProblemCode.Visibility);
                Assert.Null(panel.ProblemCodeText);
            });
        }
    }
}
