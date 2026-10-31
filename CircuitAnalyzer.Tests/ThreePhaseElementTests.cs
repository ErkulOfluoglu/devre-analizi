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
    public class ThreePhaseElementTests
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

        // ═══════════════════════════════════════════════════════
        //  1. PIN DÜZENİ VE IZGARA (4 UÇ)
        // ═══════════════════════════════════════════════════════

        [Fact]
        public void ThreePhaseSource_Pins_FixedOrderAndGridPositions()
        {
            var src = new ThreePhaseSource();

            Assert.Equal(4, src.Pins.Count);
            Assert.Equal("R", src.Pins[0].Id);
            Assert.Equal("S", src.Pins[1].Id);
            Assert.Equal("T", src.Pins[2].Id);
            Assert.Equal("N", src.Pins[3].Id);

            // Sağda alt alta 40 px aralık (sonuç etiketleri için; VisualWidth = 140, VisualHeight = 120)
            Assert.Equal(new Point(140, 0), src.Pins[0].RelativePosition);
            Assert.Equal(new Point(140, 40), src.Pins[1].RelativePosition);
            Assert.Equal(new Point(140, 80), src.Pins[2].RelativePosition);
            Assert.Equal(new Point(140, 120), src.Pins[3].RelativePosition);
        }

        [Fact]
        public void ThreePhaseLoad_Pins_FixedOrderAndGridPositions()
        {
            var load = new ThreePhaseLoad();

            Assert.Equal(4, load.Pins.Count);
            Assert.Equal("R", load.Pins[0].Id);
            Assert.Equal("S", load.Pins[1].Id);
            Assert.Equal("T", load.Pins[2].Id);
            Assert.Equal("N", load.Pins[3].Id);

            // Solda alt alta 40 px aralık (sonuç etiketleri için; VisualWidth = 140, VisualHeight = 120)
            Assert.Equal(new Point(0, 0), load.Pins[0].RelativePosition);
            Assert.Equal(new Point(0, 40), load.Pins[1].RelativePosition);
            Assert.Equal(new Point(0, 80), load.Pins[2].RelativePosition);
            Assert.Equal(new Point(0, 120), load.Pins[3].RelativePosition);
        }

        [Fact]
        public void Wattmeter_Pins_FixedOrderAndGridPositions()
        {
            var wm = new Wattmeter();

            Assert.Equal(4, wm.Pins.Count);
            Assert.Equal("I+", wm.Pins[0].Id);
            Assert.Equal("I-", wm.Pins[1].Id);
            Assert.Equal("V+", wm.Pins[2].Id);
            Assert.Equal("V-", wm.Pins[3].Id);

            // Yatay akım bobini, dikey gerilim bobini 20px ızgara kontrolü (80x80)
            Assert.Equal(new Point(0, 40), wm.Pins[0].RelativePosition);
            Assert.Equal(new Point(80, 40), wm.Pins[1].RelativePosition);
            Assert.Equal(new Point(40, 0), wm.Pins[2].RelativePosition);
            Assert.Equal(new Point(40, 80), wm.Pins[3].RelativePosition);
        }

        // ═══════════════════════════════════════════════════════
        //  2. OUTWARD DIRECTION
        // ═══════════════════════════════════════════════════════

        [Fact]
        public void OutwardDirection_ThreePhaseSource_0And90Degrees()
        {
            var src0 = new ThreePhaseSource { Position = new Point(100, 100), Rotation = 0 };
            // Sağdaki uçlar sağa bakmalı (1, 0)
            Assert.Equal(new Vector(1, 0), src0.Pins[0].OutwardDirection);
            Assert.Equal(new Vector(1, 0), src0.Pins[1].OutwardDirection);
            Assert.Equal(new Vector(1, 0), src0.Pins[2].OutwardDirection);
            Assert.Equal(new Vector(1, 0), src0.Pins[3].OutwardDirection);

            var src90 = new ThreePhaseSource { Position = new Point(100, 100), Rotation = 90 };
            // 90° saat yönü dönüşte sağ (1, 0) -> aşağı (0, 1)
            Assert.Equal(new Vector(0, 1), src90.Pins[0].OutwardDirection);
            Assert.Equal(new Vector(0, 1), src90.Pins[1].OutwardDirection);
            Assert.Equal(new Vector(0, 1), src90.Pins[2].OutwardDirection);
            Assert.Equal(new Vector(0, 1), src90.Pins[3].OutwardDirection);
        }

        [Fact]
        public void OutwardDirection_ThreePhaseLoad_0And90Degrees()
        {
            var load0 = new ThreePhaseLoad { Position = new Point(100, 100), Rotation = 0 };
            // Soldaki uçlar sola bakmalı (-1, 0)
            Assert.Equal(new Vector(-1, 0), load0.Pins[0].OutwardDirection);
            Assert.Equal(new Vector(-1, 0), load0.Pins[1].OutwardDirection);
            Assert.Equal(new Vector(-1, 0), load0.Pins[2].OutwardDirection);
            Assert.Equal(new Vector(-1, 0), load0.Pins[3].OutwardDirection);

            var load90 = new ThreePhaseLoad { Position = new Point(100, 100), Rotation = 90 };
            // 90° saat yönü dönüşte sol (-1, 0) -> yukarı (0, -1)
            Assert.Equal(new Vector(0, -1), load90.Pins[0].OutwardDirection);
            Assert.Equal(new Vector(0, -1), load90.Pins[1].OutwardDirection);
            Assert.Equal(new Vector(0, -1), load90.Pins[2].OutwardDirection);
            Assert.Equal(new Vector(0, -1), load90.Pins[3].OutwardDirection);
        }

        [Fact]
        public void OutwardDirection_Wattmeter_0And90Degrees()
        {
            var wm0 = new Wattmeter { Position = new Point(100, 100), Rotation = 0 };
            Assert.Equal(new Vector(-1, 0), wm0.Pins[0].OutwardDirection); // I+ sol
            Assert.Equal(new Vector(1, 0), wm0.Pins[1].OutwardDirection);  // I- sağ
            Assert.Equal(new Vector(0, -1), wm0.Pins[2].OutwardDirection); // V+ üst
            Assert.Equal(new Vector(0, 1), wm0.Pins[3].OutwardDirection);  // V- alt

            var wm90 = new Wattmeter { Position = new Point(100, 100), Rotation = 90 };
            Assert.Equal(new Vector(0, -1), wm90.Pins[0].OutwardDirection); // sol -> üst
            Assert.Equal(new Vector(0, 1), wm90.Pins[1].OutwardDirection);  // sağ -> alt
            Assert.Equal(new Vector(1, 0), wm90.Pins[2].OutwardDirection);  // üst -> sağ
            Assert.Equal(new Vector(-1, 0), wm90.Pins[3].OutwardDirection); // alt -> sol
        }

        // ═══════════════════════════════════════════════════════
        //  3. NETLİST ÜRETİMİ
        // ═══════════════════════════════════════════════════════

        [Fact]
        public void ThreePhaseSource_ToNetlistEntry_StarLineRstRms()
        {
            var src = new ThreePhaseSource
            {
                Id = "U1",
                Connection = ThreePhaseConnection.Star,
                ValueBasis = ThreePhaseValueBasis.Line,
                Value = 380,
                Frequency = 50,
                Phase = 0,
                Sequence = ThreePhaseSequence.Rst,
                ValueKind = AcValueKind.Rms
            };
            var map = NodeMap(src, 1, 2, 3, 0);

            var entry = src.ToNetlistEntry(map);
            Assert.Equal("U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 0 RST RMS", entry);
        }

        [Fact]
        public void ThreePhaseSource_ToNetlistEntry_DeltaPhaseRtsPeak()
        {
            var src = new ThreePhaseSource
            {
                Id = "U2",
                Connection = ThreePhaseConnection.Delta,
                ValueBasis = ThreePhaseValueBasis.Phase,
                Value = 220.5,
                Frequency = 60,
                Phase = 30,
                Sequence = ThreePhaseSequence.Rts,
                ValueKind = AcValueKind.Peak
            };
            var map = NodeMap(src, 4, 5, 6, 7);

            var entry = src.ToNetlistEntry(map);
            Assert.Equal("U2 4 5 6 7 3PH_SOURCE D PHASE 220.5 60 30 RTS", entry);
        }

        [Fact]
        public void ThreePhaseLoad_ToNetlistEntry_StarBalancedZFormat()
        {
            var load = new ThreePhaseLoad
            {
                Id = "Y1",
                Connection = ThreePhaseConnection.Star,
                Balanced = true,
                ZR = ComplexValue.FromRectangular(10, 5),
                ZS = ComplexValue.FromRectangular(10, 5),
                ZT = ComplexValue.FromRectangular(10, 5)
            };
            var map = NodeMap(load, 1, 2, 3, 0);

            var entry = load.ToNetlistEntry(map);
            Assert.Equal("Y1 1 2 3 0 3PH_LOAD Y Z(10,5) Z(10,5) Z(10,5)", entry);
        }

        [Fact]
        public void ThreePhaseLoad_ToNetlistEntry_DeltaUnbalancedZFormat()
        {
            var load = new ThreePhaseLoad
            {
                Id = "Y2",
                Connection = ThreePhaseConnection.Delta,
                Balanced = false,
                ZR = ComplexValue.FromRectangular(15.5, 0),
                ZS = ComplexValue.FromRectangular(10, -5.2),
                ZT = ComplexValue.FromRectangular(20, 10)
            };
            var map = NodeMap(load, 1, 2, 3, 0);

            var entry = load.ToNetlistEntry(map);
            Assert.Equal("Y2 1 2 3 0 3PH_LOAD D Z(15.5,0) Z(10,-5.2) Z(20,10)", entry);
        }

        [Fact]
        public void Wattmeter_ToNetlistEntry_FormatsCorrectly()
        {
            var wm = new Wattmeter { Id = "W1" };
            var map = NodeMap(wm, 1, 2, 1, 0);

            var entry = wm.ToNetlistEntry(map);
            Assert.Equal("W1 1 2 1 0 WATTMETER", entry);
        }

        // ═══════════════════════════════════════════════════════
        //  4. DÜĞÜM NUMARALAMA (NETLISTBUILDER ENTEGRASYONU)
        // ═══════════════════════════════════════════════════════

        [Fact]
        public void NetlistBuilder_AssignsAllPinsNodesCorrectly()
        {
            var src = new ThreePhaseSource { Id = "U1", Position = new Point(0, 0) };
            var load = new ThreePhaseLoad { Id = "Y1", Position = new Point(100, 0) };
            var wm = new Wattmeter { Id = "W1", Position = new Point(200, 0) };
            var gnd = new GroundElement { Id = "GND1", Position = new Point(0, 60) };

            var elements = new List<CircuitElement> { src, load, wm, gnd };
            var wires = new List<Wire>
            {
                new Wire(src.Pins[3], gnd.Pins[0]), // N -> GND (Node 0)
                new Wire(src.Pins[0], load.Pins[0]), // R -> R
                new Wire(src.Pins[1], load.Pins[1]), // S -> S
                new Wire(src.Pins[2], load.Pins[2]), // T -> T
            };

            var res = NetlistBuilder.Build(elements, wires);

            Assert.Equal(0, res.NodeMap[src.Pins[3]]);
            Assert.Equal(res.NodeMap[src.Pins[0]], res.NodeMap[load.Pins[0]]);
            Assert.Equal(res.NodeMap[src.Pins[1]], res.NodeMap[load.Pins[1]]);
            Assert.Equal(res.NodeMap[src.Pins[2]], res.NodeMap[load.Pins[2]]);

            Assert.Contains("U1", res.Text);
            Assert.Contains("3PH_SOURCE", res.Text);
            Assert.Contains("Y1", res.Text);
            Assert.Contains("3PH_LOAD", res.Text);
            Assert.Contains("W1", res.Text);
            Assert.Contains("WATTMETER", res.Text);
        }

        // ═══════════════════════════════════════════════════════
        //  5. .DEVRE GİDİŞ-DÖNÜŞ VE EKSİK ALANLAR
        // ═══════════════════════════════════════════════════════

        [Fact]
        public void CircuitDocument_RoundTrip_ThreePhaseElements()
        {
            var src = new ThreePhaseSource
            {
                Id = "U1",
                Position = new Point(20, 20),
                Rotation = 0,
                Connection = ThreePhaseConnection.Delta,
                ValueBasis = ThreePhaseValueBasis.Phase,
                Value = 220,
                Frequency = 60,
                Phase = 15,
                Sequence = ThreePhaseSequence.Rts,
                ValueKind = AcValueKind.Peak
            };

            var load = new ThreePhaseLoad
            {
                Id = "Y1",
                Position = new Point(120, 20),
                Connection = ThreePhaseConnection.Star,
                Balanced = false,
                ZR = ComplexValue.FromRectangular(12, 4),
                ZS = ComplexValue.FromRectangular(10, 0),
                ZT = ComplexValue.FromRectangular(8, -2)
            };

            var wm = new Wattmeter
            {
                Id = "W1",
                Position = new Point(220, 20)
            };

            var doc = CircuitDocument.FromCircuit(new CircuitElement[] { src, load, wm }, Array.Empty<Wire>());
            string json = doc.ToJson();

            var loaded = CircuitDocument.FromJson(json).ToCircuit("Test");

            var loadedSrc = loaded.Elements.OfType<ThreePhaseSource>().Single();
            Assert.Equal("U1", loadedSrc.Id);
            Assert.Equal(ThreePhaseConnection.Delta, loadedSrc.Connection);
            Assert.Equal(ThreePhaseValueBasis.Phase, loadedSrc.ValueBasis);
            Assert.Equal(220, loadedSrc.Value);
            Assert.Equal(60, loadedSrc.Frequency);
            Assert.Equal(15, loadedSrc.Phase);
            Assert.Equal(ThreePhaseSequence.Rts, loadedSrc.Sequence);
            Assert.Equal(AcValueKind.Peak, loadedSrc.ValueKind);

            var loadedLoad = loaded.Elements.OfType<ThreePhaseLoad>().Single();
            Assert.Equal("Y1", loadedLoad.Id);
            Assert.Equal(ThreePhaseConnection.Star, loadedLoad.Connection);
            Assert.False(loadedLoad.Balanced);
            Assert.Equal(12, loadedLoad.ZR.Real);
            Assert.Equal(4, loadedLoad.ZR.Imaginary);
            Assert.Equal(10, loadedLoad.ZS.Real);
            Assert.Equal(0, loadedLoad.ZS.Imaginary);
            Assert.Equal(8, loadedLoad.ZT.Real);
            Assert.Equal(-2, loadedLoad.ZT.Imaginary);

            var loadedWm = loaded.Elements.OfType<Wattmeter>().Single();
            Assert.Equal("W1", loadedWm.Id);
        }

        [Fact]
        public void CircuitDocument_MissingFields_SafeDefaultsApplied()
        {
            string json = @"{
                ""format"": ""devre-analizi"",
                ""version"": 1,
                ""elements"": [
                    { ""type"": ""3PS"", ""id"": ""U1"", ""x"": 0, ""y"": 0, ""rotation"": 0 },
                    { ""type"": ""3PL"", ""id"": ""Y1"", ""x"": 100, ""y"": 0, ""rotation"": 0 },
                    { ""type"": ""W"", ""id"": ""W1"", ""x"": 200, ""y"": 0, ""rotation"": 0 }
                ],
                ""wires"": []
            }";

            var doc = CircuitDocument.FromJson(json);
            var circuit = doc.ToCircuit("Test");

            var src = circuit.Elements.OfType<ThreePhaseSource>().Single();
            Assert.Equal("U1", src.Id);
            Assert.Equal(ThreePhaseConnection.Star, src.Connection);
            Assert.Equal(ThreePhaseValueBasis.Line, src.ValueBasis);
            Assert.Equal(380.0, src.Value);
            Assert.Equal(50.0, src.Frequency);
            Assert.Equal(0.0, src.Phase);
            Assert.Equal(ThreePhaseSequence.Rst, src.Sequence);
            Assert.Equal(AcValueKind.Rms, src.ValueKind);

            var load = circuit.Elements.OfType<ThreePhaseLoad>().Single();
            Assert.Equal("Y1", load.Id);
            Assert.Equal(ThreePhaseConnection.Star, load.Connection);
            Assert.True(load.Balanced);
            Assert.Equal(10, load.ZR.Real);
            Assert.Equal(5, load.ZR.Imaginary);
            Assert.Equal(10, load.ZS.Real);
            Assert.Equal(5, load.ZS.Imaginary);
            Assert.Equal(10, load.ZT.Real);
            Assert.Equal(5, load.ZT.Imaginary);

            var wm = circuit.Elements.OfType<Wattmeter>().Single();
            Assert.Equal("W1", wm.Id);
        }

        // ═══════════════════════════════════════════════════════
        //  6. PANO (CIRCUITCLIPBOARD) KOPYALA / YAPIŞTIR
        // ═══════════════════════════════════════════════════════

        [Fact]
        public void Clipboard_CopyPaste_PreservesThreePhaseAndPrefixes()
        {
            var src = new ThreePhaseSource { Id = "U1", Position = new Point(20, 20) };
            var load = new ThreePhaseLoad { Id = "Y1", Position = new Point(120, 20) };
            var wm = new Wattmeter { Id = "W1", Position = new Point(220, 20) };
            var wire = new Wire(src.Pins[0], load.Pins[0]);

            string payload = CircuitClipboard.Copy(new CircuitElement[] { src, load, wm }, new[] { wire });

            var pasted = CircuitClipboard.Paste(payload, new[] { "U1", "Y1", "W1" }, new Point(40, 40));

            Assert.Equal(3, pasted.Elements.Count);
            var pSrc = pasted.Elements.OfType<ThreePhaseSource>().Single();
            var pLoad = pasted.Elements.OfType<ThreePhaseLoad>().Single();
            var pWm = pasted.Elements.OfType<Wattmeter>().Single();

            Assert.Equal("U2", pSrc.Id);
            Assert.Equal("Y2", pLoad.Id);
            Assert.Equal("W2", pWm.Id);

            Assert.Single(pasted.Wires);
            Assert.Same(pSrc.Pins[0], pasted.Wires[0].StartPin);
            Assert.Same(pLoad.Pins[0], pasted.Wires[0].EndPin);
        }

        // ═══════════════════════════════════════════════════════
        //  7. ETİKETLER VE DENGELİ/DENGESİZ EDİTÖR STATİK METOTLARI
        // ═══════════════════════════════════════════════════════

        [Fact]
        public void ThreePhaseSource_FormatDisplayValue_DisplaysLineAndHz()
        {
            var src = new ThreePhaseSource { Value = 380, ValueBasis = ThreePhaseValueBasis.Line, Frequency = 50 };
            Assert.Equal("380 V (hat) 50 Hz", src.FormatDisplayValue());

            var srcPhase = new ThreePhaseSource { Value = 220, ValueBasis = ThreePhaseValueBasis.Phase, Frequency = 60 };
            Assert.Equal("220 V (faz) 60 Hz", srcPhase.FormatDisplayValue());
        }

        [Fact]
        public void ThreePhaseLoad_StaticMethods_BalancedAndUnbalanced()
        {
            var labelsStar = ThreePhaseLoad.GetPhaseLabels(ThreePhaseConnection.Star);
            Assert.Equal(new[] { "Z_R", "Z_S", "Z_T" }, labelsStar);

            var labelsDelta = ThreePhaseLoad.GetPhaseLabels(ThreePhaseConnection.Delta);
            Assert.Equal(new[] { "Z_RS", "Z_ST", "Z_TR" }, labelsDelta);

            var z1 = ComplexValue.FromRectangular(10, 5);
            var z2 = ComplexValue.FromRectangular(10, 5);
            var z3 = ComplexValue.FromRectangular(10, 5);
            Assert.True(ThreePhaseLoad.CheckIsBalanced(z1, z2, z3));

            var zDiff = ComplexValue.FromRectangular(10, 2);
            Assert.False(ThreePhaseLoad.CheckIsBalanced(z1, z2, zDiff));

            Assert.Equal("10+j5 Ω", ThreePhaseLoad.FormatDisplayValue(true, z1));
            Assert.Equal("dengesiz", ThreePhaseLoad.FormatDisplayValue(false, z1));
        }

        // ═══════════════════════════════════════════════════════
        //  8. THREE_PHASE VE WATTMETERS JSON DESERIALIZATION
        // ═══════════════════════════════════════════════════════

        [Fact]
        public void ThreePhaseResultDto_Deserialization_TopLevelAndResults()
        {
            string jsonTopLevel = @"{
                ""status"": ""success"",
                ""mode"": ""AC_PHASOR"",
                ""analysis_type"": ""THREE_PHASE"",
                ""three_phase"": {
                    ""source"": ""Y"",
                    ""load"": ""Y"",
                    ""wires"": 4,
                    ""balanced"": true,
                    ""u_line"": 380.0,
                    ""u_phase"": 220.0,
                    ""line_currents"": {
                        ""R"": { ""real"": 10.0, ""imaginary"": -5.0, ""magnitude"": 11.18, ""phase_degrees"": -26.56, ""polar_str"": ""11.18∠-26.56°"" },
                        ""S"": { ""real"": -9.33, ""imaginary"": -6.16, ""magnitude"": 11.18, ""phase_degrees"": -146.56, ""polar_str"": ""11.18∠-146.56°"" },
                        ""T"": { ""real"": -0.67, ""imaginary"": 11.16, ""magnitude"": 11.18, ""phase_degrees"": 93.44, ""polar_str"": ""11.18∠93.44°"" }
                    },
                    ""neutral_current"": { ""real"": 0.0, ""imaginary"": 0.0, ""magnitude"": 0.0, ""phase_degrees"": 0.0, ""polar_str"": ""0∠0°"" },
                    ""load_phase_currents"": null,
                    ""p"": 6600.0,
                    ""q"": 3300.0,
                    ""s"": 7379.7,
                    ""pf"": 0.894,
                    ""pf_type"": ""lagging"",
                    ""aron"": { ""p_a"": 4000.0, ""p_b"": 2600.0 },
                    ""compensation"": {
                        ""target_pf"": 0.98,
                        ""q_c"": 1960.0,
                        ""c_y"": 4.3e-5,
                        ""c_delta"": 1.43e-5,
                        ""applied"": true,
                        ""reason"": null
                    }
                },
                ""wattmeters"": [
                    { ""id"": ""W1"", ""p"": 4000.0 },
                    { ""id"": ""W2"", ""p"": 2600.0 }
                ]
            }";

            var resTop = JsonSerializer.Deserialize<AnalysisResponseDto>(jsonTopLevel);
            Assert.NotNull(resTop);
            Assert.NotNull(resTop.ThreePhaseResult);
            Assert.Equal("Y", resTop.ThreePhaseResult.Source);
            Assert.Equal(4, resTop.ThreePhaseResult.Wires);
            Assert.True(resTop.ThreePhaseResult.Balanced);
            Assert.Equal(6600.0, resTop.ThreePhaseResult.P);
            Assert.NotNull(resTop.ThreePhaseResult.LineCurrents);
            Assert.Equal(3, resTop.ThreePhaseResult.LineCurrents.Count);
            Assert.NotNull(resTop.ThreePhaseResult.Aron);
            Assert.Equal(4000.0, resTop.ThreePhaseResult.Aron.Pa);
            Assert.NotNull(resTop.ThreePhaseResult.Compensation);
            Assert.True(resTop.ThreePhaseResult.Compensation.Applied);
            Assert.Equal(1960.0, resTop.ThreePhaseResult.Compensation.Qc);

            Assert.NotNull(resTop.WattmeterResults);
            Assert.Equal(2, resTop.WattmeterResults.Count);
            Assert.Equal("W1", resTop.WattmeterResults[0].Id);
            Assert.Equal(4000.0, resTop.WattmeterResults[0].P);

            string jsonInResults = @"{
                ""status"": ""success"",
                ""mode"": ""AC_PHASOR"",
                ""analysis_type"": ""THREE_PHASE"",
                ""results"": {
                    ""three_phase"": {
                        ""source"": ""D"",
                        ""load"": ""D"",
                        ""wires"": 3,
                        ""balanced"": false,
                        ""u_line"": 380.0,
                        ""u_phase"": 380.0,
                        ""p"": 5000.0,
                        ""q"": 2000.0,
                        ""s"": 5385.0,
                        ""pf"": 0.928,
                        ""pf_type"": ""lagging""
                    },
                    ""wattmeters"": [
                        { ""id"": ""W1"", ""p"": 5000.0 }
                    ]
                }
            }";

            var resResults = JsonSerializer.Deserialize<AnalysisResponseDto>(jsonInResults);
            Assert.NotNull(resResults);
            Assert.NotNull(resResults.ThreePhaseResult);
            Assert.Equal("D", resResults.ThreePhaseResult.Source);
            Assert.Equal(3, resResults.ThreePhaseResult.Wires);
            Assert.False(resResults.ThreePhaseResult.Balanced);
            Assert.NotNull(resResults.WattmeterResults);
            Assert.Single(resResults.WattmeterResults);
        }

        // ═══════════════════════════════════════════════════════
        //  9. ANALYSISTYPEFROMTEXT VE TERMINAL KULLANIMI
        // ═══════════════════════════════════════════════════════

        [Fact]
        public void AnalysisTypeFromText_ThreePhase_MatchesAndNeedsNoTerminals()
        {
            Assert.Equal(AnalysisTypes.ThreePhase, AnalysisPanel.AnalysisTypeFromText("Üç Faz"));
            Assert.False(AnalysisPanel.UsesTerminals(AnalysisTypes.ThreePhase));
        }

        // ═══════════════════════════════════════════════════════
        //  10. AC ALGILAMA (HASACSOURCE)
        // ═══════════════════════════════════════════════════════

        [Fact]
        public void NetlistBuilder_DetectsAcSource_ForThreePhaseSourceAndWattmeter()
        {
            var src = new ThreePhaseSource { Id = "U1" };
            var gnd = new GroundElement { Id = "GND1" };
            var res1 = NetlistBuilder.Build(new CircuitElement[] { src, gnd }, Array.Empty<Wire>());
            Assert.True(res1.HasAcSource);

            var wm = new Wattmeter { Id = "W1" };
            var dc = new VoltageSource { Id = "V1", Value = 12 };
            var res2 = NetlistBuilder.Build(new CircuitElement[] { wm, dc, gnd }, Array.Empty<Wire>());
            Assert.True(res2.HasAcSource);

            var r = new Resistor { Id = "R1", Value = 100 };
            var res3 = NetlistBuilder.Build(new CircuitElement[] { r, dc, gnd }, Array.Empty<Wire>());
            Assert.False(res3.HasAcSource);
        }

        // ═══════════════════════════════════════════════════════
        //  11. GÖRSEL KURULUM (CREATEVISUAL) - RUNONSTA
        // ═══════════════════════════════════════════════════════

        [Fact]
        public void CreateVisual_ThreePhaseElements_RendersWithoutErrors()
        {
            RunOnSta(() =>
            {
                var srcStar = new ThreePhaseSource { Id = "U1", Connection = ThreePhaseConnection.Star };
                var vSrcStar = srcStar.CreateVisual();
                Assert.NotNull(vSrcStar);
                Assert.IsType<Canvas>(vSrcStar);
                Assert.NotEmpty(((Canvas)vSrcStar).Children);

                var srcDelta = new ThreePhaseSource { Id = "U2", Connection = ThreePhaseConnection.Delta };
                var vSrcDelta = srcDelta.CreateVisual();
                Assert.NotNull(vSrcDelta);

                var loadStar = new ThreePhaseLoad { Id = "Y1", Connection = ThreePhaseConnection.Star };
                var vLoadStar = loadStar.CreateVisual();
                Assert.NotNull(vLoadStar);
                Assert.IsType<Canvas>(vLoadStar);
                Assert.NotEmpty(((Canvas)vLoadStar).Children);

                var loadDelta = new ThreePhaseLoad { Id = "Y2", Connection = ThreePhaseConnection.Delta };
                var vLoadDelta = loadDelta.CreateVisual();
                Assert.NotNull(vLoadDelta);

                var wm = new Wattmeter { Id = "W1" };
                var vWm = wm.CreateVisual();
                Assert.NotNull(vWm);
                Assert.IsType<Canvas>(vWm);
                Assert.NotEmpty(((Canvas)vWm).Children);
            });
        }
    }
}
