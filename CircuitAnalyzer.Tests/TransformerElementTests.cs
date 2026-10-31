using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests
{
    [Collection(WpfUiCollection.Name)]
    public class TransformerElementTests
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
                finally
                {
                    System.Windows.Threading.Dispatcher.CurrentDispatcher.InvokeShutdown();
                }
            });
            thread.SetApartmentState(ApartmentState.STA);
            thread.Start();
            thread.Join();

            if (ex != null)
                ExceptionDispatchInfo.Capture(ex).Throw();
        }

        private static Dictionary<Pin, int> NodeMap(CircuitElement el, params int[] nodes)
        {
            var map = new Dictionary<Pin, int>();
            for (int i = 0; i < el.Pins.Count && i < nodes.Length; i++)
            {
                map[el.Pins[i]] = nodes[i];
            }
            return map;
        }

        [Fact]
        public void Pins_FixedOrderAndGridPositions()
        {
            var tf = new TransformerElement();

            Assert.Equal(4, tf.Pins.Count);
            Assert.Equal("p+", tf.Pins[0].Id);
            Assert.Equal("p-", tf.Pins[1].Id);
            Assert.Equal("s+", tf.Pins[2].Id);
            Assert.Equal("s-", tf.Pins[3].Id);

            // 20 piksellik ızgara kontrolü
            Assert.Equal(new Point(0, 0), tf.Pins[0].RelativePosition);
            Assert.Equal(new Point(0, 40), tf.Pins[1].RelativePosition);
            Assert.Equal(new Point(80, 0), tf.Pins[2].RelativePosition);
            Assert.Equal(new Point(80, 40), tf.Pins[3].RelativePosition);
        }

        [Fact]
        public void ToNetlistEntry_IdealMode_FormatsCorrectly()
        {
            var tf = new TransformerElement
            {
                Id = "T1",
                Mode = TransformerMode.Ideal,
                Ratio = 2.5
            };
            var map = NodeMap(tf, 1, 0, 2, 0);

            var entry = tf.ToNetlistEntry(map);

            Assert.Equal("T1 1 0 2 0 IDEAL 2.5", entry);
        }

        [Fact]
        public void ToNetlistEntry_CoupledMode_FormatsCorrectly()
        {
            var tf = new TransformerElement
            {
                Id = "T2",
                Mode = TransformerMode.Coupled,
                L1 = 0.05,
                L2 = 0.2,
                K = 0.85
            };
            var map = NodeMap(tf, 3, 4, 5, 6);

            var entry = tf.ToNetlistEntry(map);

            Assert.Equal("T2 3 4 5 6 COUPLED 0.05 0.2 0.85", entry);
        }

        [Fact]
        public void NetlistBuilder_FourPins_AssignsNodesCorrectly()
        {
            var tf = new TransformerElement { Id = "T1", Position = new Point(0, 0) };
            var gnd = new GroundElement { Id = "GND1", Position = new Point(0, 40) };
            var r = new Resistor { Id = "R1", Position = new Point(80, 0) };

            var elements = new List<CircuitElement> { tf, gnd, r };
            var wires = new List<Wire>();

            var result = NetlistBuilder.Build(elements, wires);

            Assert.Equal(4, tf.Pins.Count);
            foreach (var pin in tf.Pins)
            {
                Assert.True(result.NodeMap.ContainsKey(pin));
            }

            Assert.Contains("T1", result.Text);
            Assert.Contains("IDEAL", result.Text);
        }

        [Fact]
        public void Pin_OutwardDirection_At0Degrees_PointsHorizontal()
        {
            var tf = new TransformerElement { Position = new Point(100, 100), Rotation = 0 };

            // Soldaki uçlar sola bakmalı
            Assert.Equal(new Vector(-1, 0), tf.Pins[0].OutwardDirection);
            Assert.Equal(new Vector(-1, 0), tf.Pins[1].OutwardDirection);

            // Sağdaki uçlar sağa bakmalı
            Assert.Equal(new Vector(1, 0), tf.Pins[2].OutwardDirection);
            Assert.Equal(new Vector(1, 0), tf.Pins[3].OutwardDirection);
        }

        [Fact]
        public void Pin_OutwardDirection_At90Degrees_PointsVertical()
        {
            var tf = new TransformerElement { Position = new Point(100, 100), Rotation = 90 };

            // 90° saat yönü dönüşte sol (-1,0) -> yukarı (0,-1), sağ (1,0) -> aşağı (0,1)
            Assert.Equal(new Vector(0, -1), tf.Pins[0].OutwardDirection);
            Assert.Equal(new Vector(0, -1), tf.Pins[1].OutwardDirection);
            Assert.Equal(new Vector(0, 1), tf.Pins[2].OutwardDirection);
            Assert.Equal(new Vector(0, 1), tf.Pins[3].OutwardDirection);
        }

        [Fact]
        public void FormatDisplayValue_IdealAndCoupled()
        {
            var tfIdealRatio = new TransformerElement
            {
                Mode = TransformerMode.Ideal,
                Ratio = 2.0
            };
            Assert.Equal("1 : 2", tfIdealRatio.FormatDisplayValue());

            var tfIdealTurns = new TransformerElement
            {
                Mode = TransformerMode.Ideal,
                Ratio = 2.0,
                N1 = 100,
                N2 = 200
            };
            Assert.Equal("100 : 200", tfIdealTurns.FormatDisplayValue());

            var tfCoupled = new TransformerElement
            {
                Mode = TransformerMode.Coupled,
                K = 0.5
            };
            Assert.Equal("k = 0,5", tfCoupled.FormatDisplayValue());
        }

        [Fact]
        public void CalculateKFromM_CalculatesCorrectK()
        {
            double k1 = TransformerElement.CalculateKFromM(0.05, 0.1, 0.1);
            Assert.Equal(0.5, k1, 3);

            double k2 = TransformerElement.CalculateKFromM(0.16, 0.1, 0.4);
            Assert.Equal(0.8, k2, 3);
        }

        [Fact]
        public void CalculateKFromM_ExceedingMax_ThrowsInvalidOperationException()
        {
            var ex = Assert.Throws<InvalidOperationException>(() =>
                TransformerElement.CalculateKFromM(0.15, 0.1, 0.1));

            Assert.Contains("M, √(L₁·L₂) değerini aşamaz.", ex.Message);
        }

        [Fact]
        public void CircuitDocument_RoundTrip_IdealMode()
        {
            var tf = new TransformerElement
            {
                Id = "T1",
                Position = new Point(40, 60),
                Rotation = 0,
                Mode = TransformerMode.Ideal,
                Ratio = 2.5,
                N1 = 100,
                N2 = 250
            };

            var r = new Resistor { Id = "R1", Position = new Point(140, 60) };
            var w1 = new Wire(tf.Pins[2], r.Pins[0]);
            var w2 = new Wire(tf.Pins[3], r.Pins[1]);

            var doc = CircuitDocument.FromCircuit(new CircuitElement[] { tf, r }, new[] { w1, w2 });
            string json = doc.ToJson();

            var loadedDoc = CircuitDocument.FromJson(json);
            var circuit = loadedDoc.ToCircuit("Test");

            var loadedTf = circuit.Elements.OfType<TransformerElement>().Single();
            Assert.Equal("T1", loadedTf.Id);
            Assert.Equal(TransformerMode.Ideal, loadedTf.Mode);
            Assert.Equal(2.5, loadedTf.Ratio);
            Assert.Equal(100, loadedTf.N1);
            Assert.Equal(250, loadedTf.N2);
            Assert.Equal(2, circuit.Wires.Count);
        }

        [Fact]
        public void CircuitDocument_RoundTrip_CoupledMode()
        {
            var tf = new TransformerElement
            {
                Id = "T1",
                Position = new Point(40, 60),
                Mode = TransformerMode.Coupled,
                L1 = 0.05,
                L2 = 0.2,
                K = 0.8,
                CouplingInput = CouplingInput.M
            };

            var doc = CircuitDocument.FromCircuit(new[] { tf }, Array.Empty<Wire>());
            string json = doc.ToJson();

            var loadedDoc = CircuitDocument.FromJson(json);
            var circuit = loadedDoc.ToCircuit("Test");

            var loadedTf = circuit.Elements.OfType<TransformerElement>().Single();
            Assert.Equal(TransformerMode.Coupled, loadedTf.Mode);
            Assert.Equal(0.05, loadedTf.L1);
            Assert.Equal(0.2, loadedTf.L2);
            Assert.Equal(0.8, loadedTf.K);
            Assert.Equal(CouplingInput.M, loadedTf.CouplingInput);
        }

        [Fact]
        public void CircuitDocument_MissingFields_FallbacksApplied()
        {
            string json = @"{
                ""format"": ""devre-analizi"",
                ""version"": 1,
                ""elements"": [
                    { ""type"": ""T"", ""id"": ""T1"", ""x"": 0, ""y"": 0, ""rotation"": 0 }
                ],
                ""wires"": []
            }";

            var doc = CircuitDocument.FromJson(json);
            var circuit = doc.ToCircuit("Test");

            var tf = circuit.Elements.OfType<TransformerElement>().Single();
            Assert.Equal("T1", tf.Id);
            Assert.Equal(TransformerMode.Ideal, tf.Mode);
            Assert.Equal(1.0, tf.Ratio);
            Assert.Equal(0.1, tf.L1);
            Assert.Equal(0.1, tf.L2);
            Assert.Equal(1.0, tf.K);
            Assert.Equal(CouplingInput.K, tf.CouplingInput);
        }

        [Fact]
        public void Clipboard_CopyPaste_PreservesTransformerAndWires()
        {
            var tf = new TransformerElement
            {
                Id = "T1",
                Position = new Point(20, 20),
                Mode = TransformerMode.Ideal,
                Ratio = 3.0
            };
            var r = new Resistor { Id = "R1", Position = new Point(120, 20) };
            var wire = new Wire(tf.Pins[2], r.Pins[0]);

            string payload = CircuitClipboard.Copy(new CircuitElement[] { tf, r }, new[] { wire });

            var pasted = CircuitClipboard.Paste(payload, new[] { "T1", "R1" }, new Point(40, 40));

            Assert.Equal(2, pasted.Elements.Count);
            var pastedTf = pasted.Elements.OfType<TransformerElement>().Single();
            Assert.Equal("T2", pastedTf.Id);
            Assert.Equal(TransformerMode.Ideal, pastedTf.Mode);
            Assert.Equal(3.0, pastedTf.Ratio);
            Assert.Equal(new Point(60, 60), pastedTf.Position);

            Assert.Single(pasted.Wires);
            Assert.Same(pastedTf.Pins[2], pasted.Wires[0].StartPin);
        }

        [Fact]
        public void TransformerResultDto_Deserialization_TopLevelAndResults()
        {
            string jsonTopLevel = @"{
                ""status"": ""success"",
                ""mode"": ""AC_PHASOR"",
                ""analysis_type"": ""TRANSFORMER"",
                ""transformer"": {
                    ""kind"": ""ideal"",
                    ""id"": ""T1"",
                    ""a"": 2.0,
                    ""k"": null,
                    ""m"": null,
                    ""v1"": { ""real"": 10.0, ""imaginary"": 0.0, ""magnitude"": 10.0, ""phase_degrees"": 0.0, ""polar_str"": ""10∠0°"" },
                    ""v2"": { ""real"": 20.0, ""imaginary"": 0.0, ""magnitude"": 20.0, ""phase_degrees"": 0.0, ""polar_str"": ""20∠0°"" },
                    ""i1"": { ""real"": 2.0, ""imaginary"": 0.0, ""magnitude"": 2.0, ""phase_degrees"": 0.0, ""polar_str"": ""2∠0°"" },
                    ""i2"": { ""real"": 1.0, ""imaginary"": 0.0, ""magnitude"": 1.0, ""phase_degrees"": 0.0, ""polar_str"": ""1∠0°"" },
                    ""floating_secondary"": false
                }
            }";

            var resTop = JsonSerializer.Deserialize<AnalysisResponseDto>(jsonTopLevel);
            Assert.NotNull(resTop);
            Assert.NotNull(resTop.TransformerResult);
            Assert.Equal("ideal", resTop.TransformerResult.Kind);
            Assert.Equal("T1", resTop.TransformerResult.Id);
            Assert.Equal(2.0, resTop.TransformerResult.A);
            Assert.NotNull(resTop.TransformerResult.I1);
            Assert.Equal(2.0, resTop.TransformerResult.I1.Magnitude);

            string jsonInResults = @"{
                ""status"": ""success"",
                ""mode"": ""AC_PHASOR"",
                ""analysis_type"": ""TRANSFORMER"",
                ""results"": {
                    ""node_voltages"": {},
                    ""element_currents"": {},
                    ""transformer"": {
                        ""kind"": ""coupled"",
                        ""id"": ""T2"",
                        ""a"": null,
                        ""k"": 0.8,
                        ""m"": 0.08,
                        ""floating_secondary"": true
                    }
                }
            }";

            var resResults = JsonSerializer.Deserialize<AnalysisResponseDto>(jsonInResults);
            Assert.NotNull(resResults);
            Assert.NotNull(resResults.TransformerResult);
            Assert.Equal("coupled", resResults.TransformerResult.Kind);
            Assert.Equal("T2", resResults.TransformerResult.Id);
            Assert.Equal(0.8, resResults.TransformerResult.K);
            Assert.Equal(0.08, resResults.TransformerResult.M);
            Assert.True(resResults.TransformerResult.FloatingSecondary);
        }

        [Fact]
        public void AnalysisTypeFromText_Transformer_Matches()
        {
            Assert.Equal(AnalysisTypes.Transformer, AnalysisPanel.AnalysisTypeFromText("Transformatör"));
            Assert.False(AnalysisPanel.UsesTerminals(AnalysisTypes.Transformer));
        }

        [Fact]
        public void CreateVisual_RendersWithoutErrors()
        {
            RunOnSta(() =>
            {
                var tf = new TransformerElement { Id = "T1" };
                var visual = tf.CreateVisual();

                Assert.NotNull(visual);
                Assert.IsType<Canvas>(visual);
                var canvas = (Canvas)visual;
                Assert.NotEmpty(canvas.Children);
            });
        }
    }
}
