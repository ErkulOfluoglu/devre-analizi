using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Threading.Tasks;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests
{
    public class ProblemGeneratorTests : IClassFixture<BackendFixture>
    {
        private readonly BackendFixture _fx;

        public ProblemGeneratorTests(BackendFixture fx)
        {
            _fx = fx;
        }

        [Theory]
        [InlineData(1000)]
        [InlineData(4821)]
        [InlineData(9999)]
        public void SameCodeTwice_ProducesIdenticalCircuits(int code)
        {
            var c1 = ProblemGenerator.Generate(code);
            var c2 = ProblemGenerator.Generate(code);

            Assert.Equal(c1.Elements.Count, c2.Elements.Count);
            Assert.Equal(c1.Wires.Count, c2.Wires.Count);
            Assert.Equal(c1.Name, c2.Name);
            Assert.Equal(c1.Description, c2.Description);
            Assert.Equal(c1.SuggestedAnalysisType, c2.SuggestedAnalysisType);
            Assert.Equal(c1.SuggestedTerminal, c2.SuggestedTerminal);
            Assert.Equal(c1.ProblemCode, c2.ProblemCode);

            for (int i = 0; i < c1.Elements.Count; i++)
            {
                var e1 = c1.Elements[i];
                var e2 = c2.Elements[i];

                Assert.Equal(e1.Id, e2.Id);
                Assert.Equal(e1.GetType(), e2.GetType());
                Assert.Equal(e1.Rotation, e2.Rotation);

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
        [InlineData(1000)]
        [InlineData(1001)]
        [InlineData(4821)]
        [InlineData(9999)]
        public void ValidCodes_AreAccepted(int code)
        {
            Assert.True(ProblemGenerator.IsValidCode(code));
            var c = ProblemGenerator.Generate(code);
            Assert.NotNull(c);
        }

        [Theory]
        [InlineData(999)]
        [InlineData(10000)]
        [InlineData(0)]
        [InlineData(-5)]
        public void InvalidCodes_ThrowArgumentOutOfRangeException(int code)
        {
            Assert.False(ProblemGenerator.IsValidCode(code));
            Assert.Throws<ArgumentOutOfRangeException>(() => ProblemGenerator.Generate(code));
        }

        [Fact]
        public void NewCode_Called200Times_AlwaysValid()
        {
            for (int i = 0; i < 200; i++)
            {
                int code = ProblemGenerator.NewCode();
                Assert.True(ProblemGenerator.IsValidCode(code), $"Kod geçersiz: {code}");
            }
        }

        [Theory]
        [InlineData(1000)]
        [InlineData(4821)]
        [InlineData(9999)]
        public void GeneratedCircuit_HasCorrectMetadata(int code)
        {
            var c = ProblemGenerator.Generate(code);
            Assert.Equal($"Soru #{code}", c.Name);
            Assert.Equal(code, c.ProblemCode);
            Assert.False(string.IsNullOrWhiteSpace(c.Description));
        }

        [Fact]
        public void Codes1000To2999_PassAllStructuralAndValueChecks()
        {
            var validAnalysisTypes = new HashSet<string>
            {
                AnalysisTypes.Nodal,
                AnalysisTypes.Thevenin,
                AnalysisTypes.Norton,
                AnalysisTypes.Mesh,
                AnalysisTypes.Superposition
            };

            var allowedDcResistors = new HashSet<double>
            {
                1e3, 2e3, 3e3, 4e3, 5e3, 6e3, 8e3, 10e3
            };

            bool seenNodal = false;
            bool seenMesh = false;
            bool seenThevenin = false;
            bool seenNorton = false;
            bool seenSuperposition = false;
            bool seenAcVoltageSource = false;

            for (int code = 1000; code <= 2999; code++)
            {
                var c = ProblemGenerator.Generate(code);

                // IDs must be unique
                var ids = c.Elements.Select(e => e.Id).ToList();
                Assert.Equal(ids.Count, ids.Distinct(StringComparer.OrdinalIgnoreCase).Count());

                // Netlist & GND
                var netlist = NetlistBuilder.Build(c.Elements, c.Wires);
                Assert.True(netlist.HasGround, $"Devrede GND bulunmalı: {c.Name}");

                // Pin connectivity: non-probe/non-ground pin's node has >= 2 pins
                foreach (var element in c.Elements)
                {
                    if (element is TestProbe or GroundElement)
                        continue;

                    foreach (var pin in element.Pins)
                    {
                        int node = netlist.NodeMap[pin];
                        int count = netlist.NodePins[node].Count;
                        Assert.True(count >= 2,
                            $"{c.Name}: Eleman {element.Id} pini {pin.Id} düğüm {node}'da ama sadece {count} pin bağlı.");
                    }
                }

                // SuggestedAnalysisType valid
                Assert.Contains(c.SuggestedAnalysisType, validAnalysisTypes);

                // Thevenin/Norton problems have SuggestedTerminal "3"
                if (c.SuggestedAnalysisType is AnalysisTypes.Thevenin or AnalysisTypes.Norton)
                {
                    Assert.Equal("3", c.SuggestedTerminal);
                }

                // Track appearances
                if (c.SuggestedAnalysisType == AnalysisTypes.Nodal) seenNodal = true;
                if (c.SuggestedAnalysisType == AnalysisTypes.Mesh) seenMesh = true;
                if (c.SuggestedAnalysisType == AnalysisTypes.Thevenin) seenThevenin = true;
                if (c.SuggestedAnalysisType == AnalysisTypes.Norton) seenNorton = true;
                if (c.SuggestedAnalysisType == AnalysisTypes.Superposition) seenSuperposition = true;

                bool hasAc = c.Elements.Any(e => e is AcVoltageSource or AcCurrentSource);
                if (c.Elements.Any(e => e is AcVoltageSource)) seenAcVoltageSource = true;

                // Value checks
                if (!hasAc)
                {
                    foreach (var r in c.Elements.OfType<Resistor>())
                    {
                        Assert.Contains(r.Value, allowedDcResistors);
                    }
                }
                else
                {
                    foreach (var el in c.Elements)
                    {
                        double val;
                        if (el is Capacitor cap) val = cap.Value;
                        else if (el is Inductor ind) val = ind.Value;
                        else continue;

                        double exponent = Math.Floor(Math.Log10(val));
                        double mantissa = Math.Round(val / Math.Pow(10, exponent), 6);
                        bool isE3 = Math.Abs(mantissa - 1.0) < 1e-4
                                 || Math.Abs(mantissa - 2.2) < 1e-4
                                 || Math.Abs(mantissa - 4.7) < 1e-4;
                        Assert.True(isE3, $"Değer {val} (mantissa {mantissa}) en fazla 2 anlamlı basamağa sahip olmalı.");
                    }
                }
            }

            Assert.True(seenNodal, "Nodal en az bir kez görülmeli");
            Assert.True(seenMesh, "Mesh en az bir kez görülmeli");
            Assert.True(seenThevenin, "Thevenin en az bir kez görülmeli");
            Assert.True(seenNorton, "Norton en az bir kez görülmeli");
            Assert.True(seenSuperposition, "Superposition en az bir kez görülmeli");
            Assert.True(seenAcVoltageSource, "AcVoltageSource en az bir kez görülmeli");
        }

        private static AnalysisRequestDto BuildSolverRequest(ExampleCircuit c, NetlistResult netlist) =>
            new()
            {
                Netlist = netlist.Text,
                Mode = netlist.HasAcSource ? AnalysisModes.AcPhasor : AnalysisModes.Dc,
                Frequency = null,
                AnalysisType = c.SuggestedAnalysisType,
                TheveninTerminals = c.SuggestedTerminal != null
                    ? new TerminalsDto { NodePositive = c.SuggestedTerminal, NodeNegative = "0" }
                    : null,
                ValueDisplay = "RMS"
            };

        [Fact]
        public async Task LiveBackend_25GeneratedProblems_SolveAndCheckAnswersSucceed()
        {
            for (int k = 0; k < 25; k++)
            {
                int code = 1000 + 357 * k;
                var c = ProblemGenerator.Generate(code);
                var netlist = NetlistBuilder.Build(c.Elements, c.Wires);
                var req = BuildSolverRequest(c, netlist);

                var resp = await _fx.Client.AnalyzeAsync(req);
                Assert.Equal("success", resp.Status);
                Assert.NotNull(resp.Results.Practice);
                Assert.NotEmpty(resp.Results.Practice);

                var checkReq = new AnswerCheckRequestDto
                {
                    Items = resp.Results.Practice.Select(q => new AnswerCheckItemDto
                    {
                        Question = q,
                        Answer = q.Expected.RectangularStr
                    }).ToList()
                };

                var checkResp = await _fx.Client.CheckAnswersAsync(checkReq);
                Assert.NotNull(checkResp.Verdicts);
                Assert.Equal(resp.Results.Practice.Count, checkResp.CorrectCount);
                Assert.Equal(resp.Results.Practice.Count, checkResp.Total);
            }
        }
    }
}
