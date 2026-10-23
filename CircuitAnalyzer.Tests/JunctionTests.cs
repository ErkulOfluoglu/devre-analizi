using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Input;
using CircuitAnalyzer.WPF;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests
{
    /// <summary>
    /// T-bağlantı noktası (JunctionElement) birim ve entegrasyon testleri:
    /// NetlistBuilder düğüm birleştirme, CircuitDocument kaydet/aç, CircuitClipboard
    /// yeniden numaralandırma, tel silme sonrası otomatik temizleme/birleştirme,
    /// MainWindow etkileşimi + tek geri-al adımı ve çözücü doğrulaması.
    /// </summary>
    public class JunctionTests : IClassFixture<BackendFixture>
    {
        private readonly BackendFixture _backend;

        public JunctionTests(BackendFixture backend)
        {
            _backend = backend;
        }

        private static void RunInSta(Action action)
        {
            Exception? caught = null;
            var thread = new Thread(() =>
            {
                try
                {
                    action();
                }
                catch (Exception ex)
                {
                    caught = ex;
                }
            });
            thread.SetApartmentState(ApartmentState.STA);
            thread.Start();
            thread.Join();
            if (caught != null)
                throw new AggregateException(caught);
        }

        /// <summary>
        /// VAC1 – R1 – L1 – C1 seri devresi ve C2'nin (a) doğrudan R1 sağ pinine,
        /// (b) R1–L1 telinin ortasındaki J1 bağlantı noktasına bağlandığı iki eşdeğer devre kurar.
        /// </summary>
        private static (ExampleCircuit PinToPin, ExampleCircuit WithJunction, JunctionElement Junction, Wire BranchWire)
            BuildEquivalentCircuits()
        {
            DateTime fixedTime = new(2026, 5, 1, 12, 0, 0);
            _ = fixedTime;

            ExampleCircuit MakeBase(out AcVoltageSource vac, out Resistor r1, out Inductor l1, out Capacitor c1, out Capacitor c2, out GroundElement gnd)
            {
                var c = new ExampleCircuit { Name = "RLC" };
                vac = new AcVoltageSource { Id = "VAC1", Amplitude = 10, Frequency = 50, Phase = 0, Position = new Point(100, 200), Rotation = 90 };
                r1 = new Resistor { Id = "R1", Value = 100, Position = new Point(200, 100) };
                l1 = new Inductor { Id = "L1", Value = 0.1, Position = new Point(400, 100) };
                c1 = new Capacitor { Id = "C1", Value = 10e-6, Position = new Point(500, 200), Rotation = 90 };
                c2 = new Capacitor { Id = "C2", Value = 10e-6, Position = new Point(300, 200), Rotation = 90 };
                gnd = new GroundElement { Id = "GND1", Position = new Point(320, 300) };

                c.Elements.AddRange(new CircuitElement[] { vac, r1, l1, c1, c2, gnd });
                c.Wires.Add(new Wire(r1.Pins[0], vac.Pins[0]));
                c.Wires.Add(new Wire(l1.Pins[1], c1.Pins[0]));
                c.Wires.Add(new Wire(vac.Pins[1], gnd.Pins[0]));
                c.Wires.Add(new Wire(c1.Pins[1], gnd.Pins[0]));
                c.Wires.Add(new Wire(c2.Pins[1], gnd.Pins[0]));
                return c;
            }

            var pinToPin = MakeBase(out _, out var r1A, out var l1A, out _, out var c2A, out _);
            pinToPin.Wires.Add(new Wire(r1A.Pins[1], l1A.Pins[0]));
            pinToPin.Wires.Add(new Wire(c2A.Pins[0], r1A.Pins[1]));

            var withJ = MakeBase(out _, out var r1B, out var l1B, out _, out var c2B, out _);
            var j1 = new JunctionElement { Id = "J1", Position = new Point(340, 120) };
            withJ.Elements.Add(j1);
            var wFirst = new Wire(r1B.Pins[1], j1.Pins[0]);
            var wSecond = new Wire(j1.Pins[0], l1B.Pins[0]);
            var wBranch = new Wire(c2B.Pins[0], j1.Pins[0]);
            withJ.Wires.Add(wFirst);
            withJ.Wires.Add(wSecond);
            withJ.Wires.Add(wBranch);
            j1.AttachedWireCount = 3;

            return (pinToPin, withJ, j1, wBranch);
        }

        [Fact]
        public void NetlistBuilder_JunctionInMiddleOfWire_YieldsSameNodesAndComponentLinesWithoutJLine()
        {
            var (pinToPin, withJ, j1, _) = BuildEquivalentCircuits();
            var ts = new DateTime(2026, 5, 1, 12, 0, 0);

            var nlDirect = NetlistBuilder.Build(pinToPin.Elements, pinToPin.Wires, ts);
            var nlJunction = NetlistBuilder.Build(withJ.Elements, withJ.Wires, ts);

            Assert.Equal(nlDirect.NodeCount, nlJunction.NodeCount);
            Assert.Equal(nlDirect.HasGround, nlJunction.HasGround);
            Assert.Equal(nlDirect.HasAcSource, nlJunction.HasAcSource);

            // Yorum olmayan tüm devre satırları birebir aynı olmalı ve hiçbir satır "J" ile başlamamalı
            var directLines = nlDirect.Text.Split('\n', StringSplitOptions.RemoveEmptyEntries)
                .Select(l => l.Trim())
                .Where(l => !l.StartsWith('*'))
                .ToList();
            var junctionLines = nlJunction.Text.Split('\n', StringSplitOptions.RemoveEmptyEntries)
                .Select(l => l.Trim())
                .Where(l => !l.StartsWith('*'))
                .ToList();

            Assert.Equal(directLines, junctionLines);
            Assert.DoesNotContain(junctionLines, l => l.StartsWith("J", StringComparison.OrdinalIgnoreCase));
            Assert.Contains("* Eleman sayısı: 6", nlJunction.Text);

            // J1 pini, R1 sağ pini, L1 sol pini ve C2 üst pini aynı düğümde (Node 2) birleşmeli
            int jNode = nlJunction.NodeMap[j1.Pins[0]];
            var r1 = withJ.Elements.OfType<Resistor>().Single();
            var l1 = withJ.Elements.OfType<Inductor>().Single();
            var c2 = withJ.Elements.OfType<Capacitor>().Single(c => c.Id == "C2");
            Assert.Equal(jNode, nlJunction.NodeMap[r1.Pins[1]]);
            Assert.Equal(jNode, nlJunction.NodeMap[l1.Pins[0]]);
            Assert.Equal(jNode, nlJunction.NodeMap[c2.Pins[0]]);
        }

        [Fact]
        public void CircuitDocument_RoundTripWithJunction_PreservesJunctionTypePositionAndWires()
        {
            var (_, withJ, j1, _) = BuildEquivalentCircuits();

            var doc = CircuitDocument.FromCircuit(withJ.Elements, withJ.Wires);
            var jData = Assert.Single(doc.Elements, e => e.Type == "J");
            Assert.Equal("J1", jData.Id);
            Assert.Equal(340, jData.X);
            Assert.Equal(120, jData.Y);
            Assert.Null(jData.Value);

            string json = doc.ToJson();
            var restored = CircuitDocument.FromJson(json).ToCircuit("Restored");

            var restoredJ = Assert.Single(restored.Elements.OfType<JunctionElement>());
            Assert.Equal("J1", restoredJ.Id);
            Assert.Equal(new Point(340, 120), restoredJ.Position);
            Assert.Equal(3, restoredJ.AttachedWireCount);
            Assert.Equal(withJ.Wires.Count, restored.Wires.Count);
        }

        [Fact]
        public void CircuitClipboard_CopyAndPaste_RenumbersJunctionIdsAndKeepsWiresToJunctions()
        {
            var (_, withJ, _, _) = BuildEquivalentCircuits();

            // J1 açıkça seçilmese bile bağlı olduğu elemanlar kopyalandığında J1 ve telleri dahil edilmeli
            var nonJunctionSelection = withJ.Elements.Where(e => e is not JunctionElement).ToList();
            string payload = CircuitClipboard.Copy(nonJunctionSelection, withJ.Wires);

            var existingIds = withJ.Elements.Select(e => e.Id).ToList();
            var pasted = CircuitClipboard.Paste(payload, existingIds, new Point(40, 40));

            var pastedJ = Assert.Single(pasted.Elements.OfType<JunctionElement>());
            Assert.Equal("J2", pastedJ.Id);
            Assert.Equal(new Point(380, 160), pastedJ.Position);
            Assert.Equal(3, pastedJ.AttachedWireCount);

            int wiresAtPastedJ = pasted.Wires.Count(w => w.StartPin == pastedJ.Pins[0] || w.EndPin == pastedJ.Pins[0]);
            Assert.Equal(3, wiresAtPastedJ);
        }

        [Fact]
        public void CleanupJunctions_DeletingBranchWireMergesStraightAndRemovesZeroOrOneWireJunctions()
        {
            var (_, withJ, j1, branchWire) = BuildEquivalentCircuits();
            var r1 = withJ.Elements.OfType<Resistor>().Single();
            var l1 = withJ.Elements.OfType<Inductor>().Single();
            var expectedRoute = WireGeometry.Route(r1.Pins[1].AbsolutePosition, l1.Pins[0].AbsolutePosition);

            // T-bağlantısının dal telini sil → kalan 2 tel tek telde (R1.Pin1 → L1.Pin0) birleşmeli ve J1 kalkmalı
            withJ.Wires.Remove(branchWire);
            WireGeometry.CleanupJunctions(withJ.Elements, withJ.Wires);

            Assert.DoesNotContain(j1, withJ.Elements);
            var mergedWire = Assert.Single(withJ.Wires, w =>
                (w.StartPin == r1.Pins[1] && w.EndPin == l1.Pins[0]) ||
                (w.StartPin == l1.Pins[0] && w.EndPin == r1.Pins[1]));
            Assert.Equal(expectedRoute, WireGeometry.Route(mergedWire.StartPin.AbsolutePosition, mergedWire.EndPin.AbsolutePosition));

            // 0 telli ve 1 telli bağlantı noktaları da (sarkan telle birlikte) temizlenmeli
            var jZero = new JunctionElement { Id = "J2", Position = new Point(200, 200) };
            var jOne = new JunctionElement { Id = "J3", Position = new Point(240, 200) };
            var dangling = new Wire(r1.Pins[0], jOne.Pins[0]);
            withJ.Elements.Add(jZero);
            withJ.Elements.Add(jOne);
            withJ.Wires.Add(dangling);

            WireGeometry.CleanupJunctions(withJ.Elements, withJ.Wires);

            Assert.Empty(withJ.Elements.OfType<JunctionElement>());
            Assert.DoesNotContain(dangling, withJ.Wires);
        }

        [Fact]
        public void MainWindow_WireToMiddleOfWireAndUndo_CreatesOneJunctionThreeWiresAndRestoresInOneUndoStep()
        {
            RunInSta(() =>
            {
                var window = new MainWindow();
                var baseCircuit = new ExampleCircuit { Name = "TTest" };
                var r1 = baseCircuit.Add(new Resistor { Value = 100 }, "R1", 200, 100);
                var l1 = baseCircuit.Add(new Inductor { Value = 0.1 }, "L1", 400, 100);
                var c2 = baseCircuit.Add(new Capacitor { Value = 10e-6 }, "C2", 300, 200, 90);
                baseCircuit.Connect(r1.Pins[1], l1.Pins[0]);

                window.LoadExample(baseCircuit);
                Assert.Single(window.Wires);
                Assert.Empty(window.Elements.OfType<JunctionElement>());
                Assert.False(window.IsDirty);

                // C2'nin üst ucundan tel başlatıp R1–L1 telinin ortasına (340, 120) tıkla
                window.StartPinWire(c2.Pins[0]);
                window.HandlePinWireClick(new Point(340, 120));

                var j1 = Assert.Single(window.Elements.OfType<JunctionElement>());
                Assert.Equal("J1", j1.Id);
                Assert.Equal(new Point(340, 120), j1.Position);
                Assert.Equal(3, j1.AttachedWireCount);
                Assert.Equal(3, window.Wires.Count);
                Assert.True(window.IsDirty);

                // Tek bir geri-al (Undo) adımı devreyi başlangıçtaki tek telli, J'siz hâline döndürmeli
                window.Undo();
                Assert.Empty(window.Elements.OfType<JunctionElement>());
                Assert.Single(window.Wires);

                // Yinele (Redo) tekrar J1 + 3 teli geri getirmeli; dal telini silmek de tek adımda birleştirmeli
                window.Redo();
                Assert.Single(window.Elements.OfType<JunctionElement>());
                Assert.Equal(3, window.Wires.Count);

                var branch = window.Wires.Single(w => w.StartPin.Owner?.Id == "C2" || w.EndPin.Owner?.Id == "C2");
                window.Selection.Select(branch);
                window.DeleteSelected();
                Assert.Empty(window.Elements.OfType<JunctionElement>());
                Assert.Single(window.Wires);
            });
        }

        [Fact]
        public async Task BackendSolve_CircuitWithJunction_MatchesPinToPinNodeVoltages()
        {
            var (pinToPin, withJ, _, _) = BuildEquivalentCircuits();

            var nlDirect = NetlistBuilder.Build(pinToPin.Elements, pinToPin.Wires);
            var nlJunction = NetlistBuilder.Build(withJ.Elements, withJ.Wires);

            var respDirect = await _backend.Client.AnalyzeAsync(new AnalysisRequestDto
            {
                Netlist = nlDirect.Text,
                Mode = AnalysisModes.AcPhasor,
                AnalysisType = AnalysisTypes.Nodal,
            });
            var respJunction = await _backend.Client.AnalyzeAsync(new AnalysisRequestDto
            {
                Netlist = nlJunction.Text,
                Mode = AnalysisModes.AcPhasor,
                AnalysisType = AnalysisTypes.Nodal,
            });

            Assert.Equal("success", respDirect.Status);
            Assert.Equal("success", respJunction.Status);
            Assert.Equal(respDirect.Results.NodeVoltages.Count, respJunction.Results.NodeVoltages.Count);

            foreach (var (node, directVal) in respDirect.Results.NodeVoltages)
            {
                Assert.True(respJunction.Results.NodeVoltages.TryGetValue(node, out var jVal));
                Assert.Equal(directVal.Value.Real, jVal!.Value.Real, precision: 6);
                Assert.Equal(directVal.Value.Imaginary, jVal.Value.Imaginary, precision: 6);
            }
        }
    }
}
