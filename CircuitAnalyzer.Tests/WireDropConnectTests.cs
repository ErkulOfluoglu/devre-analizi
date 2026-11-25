using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using CircuitAnalyzer.WPF;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests
{
    /// <summary>
    /// Eleman tele/uca bırakıldığında otomatik bağlanma (WireDropConnector + MainWindow etkileşimi) testleri.
    /// Python arka ucu gerekmez.
    /// </summary>
    [Collection(WpfUiCollection.Name)]
    public class WireDropConnectTests
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

        private static void Click(Button button) => button.RaiseEvent(new RoutedEventArgs(ButtonBase.ClickEvent));

        // ═══════════════════════════════════════════════════════
        //  SAF MANTIK TESTLERİ (WireDropConnector)
        // ═══════════════════════════════════════════════════════

        [Fact]
        public void VerticalDiode_BottomPinLandsOnHorizontalGroundWire_ConnectsToGroundNode()
        {
            var v1 = new VoltageSource { Id = "V1", Value = 10, Position = new Point(60, 140), Rotation = 90 };   // Pin0=(100,120), Pin1=(100,200)
            var gnd = new GroundElement { Id = "GND1", Position = new Point(320, 200) };                           // Pin0=(340,200)
            var d1 = new Diode { Id = "D1", Position = new Point(160, 140), Rotation = 90 };                       // Pin0=(200,120), Pin1=(200,200)

            var elements = new List<CircuitElement> { v1, gnd, d1 };
            var gndWire = new Wire(v1.Pins[1], gnd.Pins[0]);
            var wires = new List<Wire> { gndWire };

            var result = WireDropConnector.Connect(elements, wires, d1);

            Assert.True(result.AnyConnected);
            var j = Assert.Single(result.AddedJunctions);
            Assert.Equal("J1", j.Id);
            Assert.Equal(new Point(200, 200), j.Position);
            Assert.Equal(3, j.AttachedWireCount);
            Assert.DoesNotContain(gndWire, wires);
            Assert.Equal(3, wires.Count);
            Assert.Equal("D1 tele bağlandı", WireDropConnector.FormatStatusMessage(result));

            // Netlist'te diyodun alt ucu toprak düğümünde (Node 0), üst ucu ayrı düğümde olmalı
            var netlist = NetlistBuilder.Build(elements, wires);
            Assert.Equal(0, netlist.NodeMap[d1.Pins[1]]);
            Assert.NotEqual(0, netlist.NodeMap[d1.Pins[0]]);
        }

        [Fact]
        public void GroundElement_DroppedOntoWire_ConnectsAndGroundsNet()
        {
            var r1 = new Resistor { Id = "R1", Value = 100, Position = new Point(20, 100) };     // Pin1=(100,120)
            var r2 = new Resistor { Id = "R2", Value = 200, Position = new Point(340, 100) };    // Pin0=(340,120)
            var gnd = new GroundElement { Id = "GND1", Position = new Point(200, 120) };         // Pin0=(220,120)

            var elements = new List<CircuitElement> { r1, r2, gnd };
            var wires = new List<Wire> { new Wire(r1.Pins[1], r2.Pins[0]) };

            var result = WireDropConnector.Connect(elements, wires, gnd);

            Assert.True(result.AnyConnected);
            var j = Assert.Single(result.AddedJunctions);
            Assert.Equal(new Point(220, 120), j.Position);
            Assert.Equal(3, j.AttachedWireCount);

            var netlist = NetlistBuilder.Build(elements, wires);
            Assert.Equal(0, netlist.NodeMap[r1.Pins[1]]);
            Assert.Equal(0, netlist.NodeMap[r2.Pins[0]]);
            Assert.Equal(0, netlist.NodeMap[gnd.Pins[0]]);
        }

        [Fact]
        public void PinNearButNotOnWire_DoesNotConnect()
        {
            var v1 = new VoltageSource { Id = "V1", Value = 10, Position = new Point(60, 140), Rotation = 90 };
            var gnd = new GroundElement { Id = "GND1", Position = new Point(320, 200) };
            // Bir ızgara hücresi yukarıda: alt pin (200, 180), tel Y=200'de (20px uzak)
            var dGridAway = new Diode { Id = "D1", Position = new Point(160, 120), Rotation = 90 };
            // Izgara dışı ama telin 4px yukarısında (telin üzerinde değil): alt pin (200, 196)
            var dSlightlyOff = new Diode { Id = "D2", Position = new Point(160, 136), Rotation = 90 };

            var elements = new List<CircuitElement> { v1, gnd, dGridAway, dSlightlyOff };
            var wire = new Wire(v1.Pins[1], gnd.Pins[0]);
            var wires = new List<Wire> { wire };

            var r1 = WireDropConnector.Connect(elements, wires, dGridAway);
            var r2 = WireDropConnector.Connect(elements, wires, dSlightlyOff);

            Assert.False(r1.AnyConnected);
            Assert.False(r2.AnyConnected);
            Assert.Single(wires);
            Assert.Same(wire, wires[0]);
            Assert.Empty(elements.OfType<JunctionElement>());
        }

        [Fact]
        public void PinOnWireEndpointPin_ConnectsWithoutDuplicatesOrBogusJunction()
        {
            var r1 = new Resistor { Id = "R1", Value = 100, Position = new Point(20, 100) };     // Pin1=(100,120)
            var r2 = new Resistor { Id = "R2", Value = 200, Position = new Point(340, 100) };    // Pin0=(340,120)
            // D1 alt ucu tam olarak R1.Pin1 = (100, 120) tel uç noktasına iniyor
            var d1 = new Diode { Id = "D1", Position = new Point(60, 60), Rotation = 90 };       // Pin0=(100,40), Pin1=(100,120)

            var elements = new List<CircuitElement> { r1, r2, d1 };
            var wire = new Wire(r1.Pins[1], r2.Pins[0]);
            var wires = new List<Wire> { wire };

            var result = WireDropConnector.Connect(elements, wires, d1);

            Assert.True(result.AnyConnected);
            Assert.Empty(result.AddedJunctions);
            Assert.Empty(result.RemovedWires);
            var added = Assert.Single(result.AddedWires);
            Assert.Equal(2, wires.Count);
            Assert.True((added.StartPin == d1.Pins[1] && added.EndPin == r1.Pins[1]) ||
                        (added.StartPin == r1.Pins[1] && added.EndPin == d1.Pins[1]));

            // Tekrar çağrılırsa D1.Pin1 artık bağlı olduğu için kopya tel oluşturmaz
            var secondPass = WireDropConnector.Connect(elements, wires, d1);
            Assert.False(secondPass.AnyConnected);
            Assert.Equal(2, wires.Count);

            var netlist = NetlistBuilder.Build(elements, wires);
            Assert.Equal(netlist.NodeMap[r1.Pins[1]], netlist.NodeMap[d1.Pins[1]]);
            Assert.Equal(netlist.NodeMap[r2.Pins[0]], netlist.NodeMap[d1.Pins[1]]);
        }

        [Fact]
        public void HorizontalResistor_DroppedOntoHorizontalWire_InsertsInSeries()
        {
            var r1 = new Resistor { Id = "R1", Value = 100, Position = new Point(20, 100) };     // Pin1=(100,120)
            var r3 = new Resistor { Id = "R3", Value = 300, Position = new Point(340, 100) };    // Pin0=(340,120)
            var r2 = new Resistor { Id = "R2", Value = 200, Position = new Point(180, 100) };    // Pin0=(180,120), Pin1=(260,120)

            var elements = new List<CircuitElement> { r1, r3, r2 };
            var originalWire = new Wire(r1.Pins[1], r3.Pins[0]);
            var wires = new List<Wire> { originalWire };

            var result = WireDropConnector.Connect(elements, wires, r2);

            Assert.True(result.AnyConnected);
            Assert.True(result.HasSeriesInsert);
            Assert.Empty(result.AddedJunctions);
            Assert.DoesNotContain(originalWire, wires);
            Assert.Equal(2, wires.Count);
            Assert.Equal("R2 tele seri eklendi", WireDropConnector.FormatStatusMessage(result));

            // Sol tel R1.Pin1 → R2.Pin0, sağ tel R2.Pin1 → R3.Pin0 olmalı (aradaki parça çıkarılmış)
            Assert.Contains(wires, w => w.StartPin == r1.Pins[1] && w.EndPin == r2.Pins[0]);
            Assert.Contains(wires, w => w.StartPin == r2.Pins[1] && w.EndPin == r3.Pins[0]);

            // Netlist'te R2 eski telin iki ucu arasına seri girmiş olmalı (iki uç farklı düğüm)
            var netlist = NetlistBuilder.Build(elements, wires);
            Assert.Equal(netlist.NodeMap[r1.Pins[1]], netlist.NodeMap[r2.Pins[0]]);
            Assert.Equal(netlist.NodeMap[r2.Pins[1]], netlist.NodeMap[r3.Pins[0]]);
            Assert.NotEqual(netlist.NodeMap[r2.Pins[0]], netlist.NodeMap[r2.Pins[1]]);
        }

        [Fact]
        public void Rotated180Resistor_DroppedOntoHorizontalWire_InsertsWithoutCrossingLeads()
        {
            var r1 = new Resistor { Id = "R1", Value = 100, Position = new Point(20, 100) };
            var r3 = new Resistor { Id = "R3", Value = 300, Position = new Point(340, 100) };
            // 180° döndürülmüş: Pin0=(260,120) sağda, Pin1=(180,120) solda
            var r2 = new Resistor { Id = "R2", Value = 200, Position = new Point(180, 100), Rotation = 180 };

            var elements = new List<CircuitElement> { r1, r3, r2 };
            var wires = new List<Wire> { new Wire(r1.Pins[1], r3.Pins[0]) };

            var result = WireDropConnector.Connect(elements, wires, r2);

            Assert.True(result.HasSeriesInsert);
            // Sol uç (R1.Pin1) soldaki R2.Pin1'e, sağdaki R2.Pin0 ise R3.Pin0'a bağlanmalı (çaprazlanmamalı)
            Assert.Contains(wires, w => w.StartPin == r1.Pins[1] && w.EndPin == r2.Pins[1]);
            Assert.Contains(wires, w => w.StartPin == r2.Pins[0] && w.EndPin == r3.Pins[0]);
        }

        [Fact]
        public void VerticalResistor_DroppedOntoVerticalWire_InsertsInSeries()
        {
            var r1 = new Resistor { Id = "R1", Value = 100, Position = new Point(160, 0), Rotation = 90 };    // Pin1=(200,60)
            var r3 = new Resistor { Id = "R3", Value = 300, Position = new Point(160, 320), Rotation = 90 };  // Pin0=(200,300)
            var r2 = new Resistor { Id = "R2", Value = 200, Position = new Point(160, 160), Rotation = 90 };  // Pin0=(200,140), Pin1=(200,220)

            var elements = new List<CircuitElement> { r1, r3, r2 };
            var wires = new List<Wire> { new Wire(r1.Pins[1], r3.Pins[0]) };

            var result = WireDropConnector.Connect(elements, wires, r2);

            Assert.True(result.HasSeriesInsert);
            Assert.Contains(wires, w => w.StartPin == r1.Pins[1] && w.EndPin == r2.Pins[0]);
            Assert.Contains(wires, w => w.StartPin == r2.Pins[1] && w.EndPin == r3.Pins[0]);
        }

        [Fact]
        public void PinOntoAnotherElementsFreePin_ConnectsWithZeroLengthWire()
        {
            var r1 = new Resistor { Id = "R1", Value = 100, Position = new Point(100, 100) };  // Pin1=(180,120)
            var r2 = new Resistor { Id = "R2", Value = 200, Position = new Point(180, 100) };  // Pin0=(180,120)

            var elements = new List<CircuitElement> { r1, r2 };
            var wires = new List<Wire>();

            var result = WireDropConnector.Connect(elements, wires, r2);

            Assert.True(result.AnyConnected);
            Assert.Empty(result.AddedJunctions);
            var w = Assert.Single(wires);
            Assert.True((w.StartPin == r2.Pins[0] && w.EndPin == r1.Pins[1]) ||
                        (w.StartPin == r1.Pins[1] && w.EndPin == r2.Pins[0]));
            Assert.Equal("R2 R1 ucuna bağlandı", WireDropConnector.FormatStatusMessage(result));

            var netlist = NetlistBuilder.Build(elements, wires);
            Assert.Equal(netlist.NodeMap[r1.Pins[1]], netlist.NodeMap[r2.Pins[0]]);
        }

        [Fact]
        public void AlreadyConnectedPin_RemainsUntouched()
        {
            var r1 = new Resistor { Id = "R1", Value = 100, Position = new Point(20, 100) };     // Pin1=(100,120)
            var r2 = new Resistor { Id = "R2", Value = 200, Position = new Point(340, 100) };    // Pin0=(340,120)
            var r3 = new Resistor { Id = "R3", Value = 300, Position = new Point(20, 260) };     // Pin1=(100,280)
            var d1 = new Diode { Id = "D1", Position = new Point(160, 60), Rotation = 90 };      // Pin0=(200,40), Pin1=(200,120)

            var horizontalWire = new Wire(r1.Pins[1], r2.Pins[0]);
            // D1.Pin1 zaten R3'e bağlı
            var existingWire = new Wire(d1.Pins[1], r3.Pins[1]);
            var elements = new List<CircuitElement> { r1, r2, r3, d1 };
            var wires = new List<Wire> { horizontalWire, existingWire };

            var result = WireDropConnector.Connect(elements, wires, d1);

            Assert.False(result.AnyConnected);
            Assert.Equal(2, wires.Count);
            Assert.Empty(elements.OfType<JunctionElement>());
        }

        [Fact]
        public void ElementOntoOwnWire_DoesNotSelfConnect()
        {
            var r1 = new Resistor { Id = "R1", Value = 100, Position = new Point(180, 100) };    // Pin0=(180,120), Pin1=(260,120)
            var r2 = new Resistor { Id = "R2", Value = 200, Position = new Point(340, 100) };    // Pin0=(340,120)

            // R1.Pin0'dan R2.Pin0'a giden tel R1.Pin1=(260,120) üzerinden geçiyor (elemanın kendi teli)
            var ownWire = new Wire(r1.Pins[0], r2.Pins[0]);
            var elements = new List<CircuitElement> { r1, r2 };
            var wires = new List<Wire> { ownWire };

            var result = WireDropConnector.Connect(elements, wires, r1);

            Assert.False(result.AnyConnected);
            Assert.Single(wires);
            Assert.Same(ownWire, wires[0]);
        }

        [Fact]
        public void PolylineWireWithWaypoints_PinOnSecondSegment_SplitsAndPreservesWaypoints()
        {
            var r1 = new Resistor { Id = "R1", Value = 100, Position = new Point(20, 200) };     // Pin1=(100,220)
            var r2 = new Resistor { Id = "R2", Value = 200, Position = new Point(360, 200) };    // Pin0=(360,220)
            // Üç segmentli tel: (100,220) → (100,120) → (360,120) → (360,220)
            var polyWire = new Wire(
                r1.Pins[1],
                r2.Pins[0],
                new[] { new Point(100, 120), new Point(360, 120) },
                lastLegVerticalFirst: false);
            var expectedRoute = WireGeometry.Route(polyWire);

            // D1 alt ucu ikinci segmentin ortasına (220, 120) iniyor
            var d1 = new Diode { Id = "D1", Position = new Point(180, 60), Rotation = 90 };      // Pin0=(220,40), Pin1=(220,120)

            var elements = new List<CircuitElement> { r1, r2, d1 };
            var wires = new List<Wire> { polyWire };

            var result = WireDropConnector.Connect(elements, wires, d1);

            Assert.True(result.AnyConnected);
            var j = Assert.Single(result.AddedJunctions);
            Assert.Equal(new Point(220, 120), j.Position);
            Assert.Equal(3, j.AttachedWireCount);

            var first = wires.Single(w => w.StartPin == r1.Pins[1] && w.EndPin == j.Pins[0]);
            var second = wires.Single(w => w.StartPin == j.Pins[0] && w.EndPin == r2.Pins[0]);
            Assert.Contains(new Point(100, 120), first.Waypoints);
            Assert.Contains(new Point(360, 120), second.Waypoints);
            Assert.True(WireGeometry.CombinedRouteMatches(WireGeometry.Route(first), WireGeometry.Route(second), expectedRoute));
        }

        [Fact]
        public void PolylineWireWithWaypoints_SeriesInsertOnMiddleSegment_PreservesWaypointsOnBothSides()
        {
            var r1 = new Resistor { Id = "R1", Value = 100, Position = new Point(20, 200) };     // Pin1=(100,220)
            var r3 = new Resistor { Id = "R3", Value = 300, Position = new Point(360, 200) };    // Pin0=(360,220)
            var polyWire = new Wire(
                r1.Pins[1],
                r3.Pins[0],
                new[] { new Point(100, 120), new Point(360, 120) });

            var r2 = new Resistor { Id = "R2", Value = 200, Position = new Point(180, 100) };    // Pin0=(180,120), Pin1=(260,120)

            var elements = new List<CircuitElement> { r1, r3, r2 };
            var wires = new List<Wire> { polyWire };

            var result = WireDropConnector.Connect(elements, wires, r2);

            Assert.True(result.HasSeriesInsert);
            Assert.Equal(2, wires.Count);

            var left = wires.Single(w => w.StartPin == r1.Pins[1] && w.EndPin == r2.Pins[0]);
            var right = wires.Single(w => w.StartPin == r2.Pins[1] && w.EndPin == r3.Pins[0]);
            Assert.Contains(new Point(100, 120), left.Waypoints);
            Assert.Contains(new Point(360, 120), right.Waypoints);
        }

        [Fact]
        public void JunctionAndCurrentProbe_AreSkipped_VoltageProbeConnects()
        {
            var r1 = new Resistor { Id = "R1", Value = 100, Position = new Point(20, 100) };
            var r2 = new Resistor { Id = "R2", Value = 200, Position = new Point(340, 100) };
            var jLoose = new JunctionElement { Id = "J9", Position = new Point(180, 120) };
            var iProbe = new TestProbe { Id = "IP1", Type = ProbeType.Current, TargetElementId = "R1", Position = new Point(200, 120) };
            var vProbe = new TestProbe { Id = "VP1", Type = ProbeType.Voltage, Position = new Point(240, 120) }; // Pin=(260,120)

            var elements = new List<CircuitElement> { r1, r2, jLoose, iProbe, vProbe };
            var wires = new List<Wire> { new Wire(r1.Pins[1], r2.Pins[0]) };

            Assert.False(WireDropConnector.Connect(elements, wires, jLoose).AnyConnected);
            Assert.False(WireDropConnector.Connect(elements, wires, iProbe).AnyConnected);

            var vpResult = WireDropConnector.Connect(elements, wires, vProbe);
            Assert.True(vpResult.AnyConnected);
            var netlist = NetlistBuilder.Build(elements, wires);
            Assert.Equal(netlist.NodeMap[r1.Pins[1]], netlist.NodeMap[vProbe.Pins[0]]);
        }

        [Fact]
        public void RoundTrip_SaveAndLoadDevre_PreservesDropConnectivityAndJunctionCounts()
        {
            var v1 = new VoltageSource { Id = "V1", Value = 10, Position = new Point(60, 140), Rotation = 90 };
            var gnd = new GroundElement { Id = "GND1", Position = new Point(320, 200) };
            var d1 = new Diode { Id = "D1", Position = new Point(160, 140), Rotation = 90 };
            var r1 = new Resistor { Id = "R1", Value = 1000, Position = new Point(200, 100) };

            var elements = new List<CircuitElement> { v1, gnd, d1, r1 };
            var wires = new List<Wire>
            {
                new Wire(v1.Pins[1], gnd.Pins[0]),
                new Wire(v1.Pins[0], r1.Pins[0]),
            };

            WireDropConnector.Connect(elements, wires, d1);
            var nlBefore = NetlistBuilder.Build(elements, wires, new DateTime(2026, 5, 1));

            string json = CircuitDocument.FromCircuit(elements, wires).ToJson();
            var restored = CircuitDocument.FromJson(json).ToCircuit("RoundTrip");
            var nlAfter = NetlistBuilder.Build(restored.Elements, restored.Wires, new DateTime(2026, 5, 1));

            Assert.Equal(nlBefore.Text, nlAfter.Text);
            var restoredJ = Assert.Single(restored.Elements.OfType<JunctionElement>());
            Assert.Equal(3, restoredJ.AttachedWireCount);
            var restoredD1 = restored.Elements.OfType<Diode>().Single();
            Assert.Equal(0, nlAfter.NodeMap[restoredD1.Pins[1]]);
        }

        // ═══════════════════════════════════════════════════════
        //  MAINWINDOW ENTEGRASYON TESTLERİ (YERLEŞTİRME / SÜRÜKLEME / DÖNDÜRME / YAPIŞTIRMA / GERİ AL)
        // ═══════════════════════════════════════════════════════

        [Fact]
        public void MainWindow_PlaceDiodeOntoGroundWire_ConnectsWithPreviewAndSingleUndoStep()
        {
            RunOnSta(() =>
            {
                var win = new MainWindow();
                var baseCircuit = new ExampleCircuit { Name = "GndWire" };
                var v1 = baseCircuit.Add(new VoltageSource { Value = 10 }, "V1", 60, 140, 90);
                var gnd = baseCircuit.Add(new GroundElement(), "GND1", 320, 200);
                baseCircuit.Connect(v1.Pins[1], gnd.Pins[0]);
                win.LoadExample(baseCircuit);

                // Sol şeritten diyot seç, 90° döndür, alt ucu telin ortasına (200, 200) gelecek yere götür
                Click(win.BtnAddDiode);
                Assert.True(win.HandleKeyDown(Key.R));
                win.HandleCanvasMouseMove(new Point(200, 160));

                // Önizleme halkası tel üzerindeki (200, 200) noktasını göstermeli
                Assert.Single(win.DropConnectPreviews);

                // Bırak → diyot + J1 + 3 tel tek geri-al adımında oluşmalı
                win.HandleCanvasLeftButtonDown(new Point(200, 160));

                Assert.Empty(win.DropConnectPreviews);
                var j1 = Assert.Single(win.Elements.OfType<JunctionElement>());
                Assert.Equal(3, j1.AttachedWireCount);
                Assert.Equal(3, win.Wires.Count);
                Assert.Equal("D1 tele bağlandı", win.TxtStatus.Text);

                var nl = NetlistBuilder.Build(win.Elements, win.Wires);
                var d1 = win.Elements.OfType<Diode>().Single();
                Assert.Equal(0, nl.NodeMap[d1.Pins[1]]);

                // Tek geri-al (Undo) adımı hem diyodu hem bağlantı noktasını kaldırıp tek teli geri getirmeli
                win.Undo();
                Assert.Empty(win.Elements.OfType<Diode>());
                Assert.Empty(win.Elements.OfType<JunctionElement>());
                Assert.Single(win.Wires);

                // Yinele (Redo) tekrar aynı bağlantıyı geri getirmeli
                win.Redo();
                Assert.Single(win.Elements.OfType<Diode>());
                Assert.Single(win.Elements.OfType<JunctionElement>());
                Assert.Equal(3, win.Wires.Count);
            });
        }

        [Fact]
        public void MainWindow_DragResistorOntoHorizontalWire_InsertsInSeriesInOneUndoStep()
        {
            RunOnSta(() =>
            {
                var win = new MainWindow();
                var baseCircuit = new ExampleCircuit { Name = "SeriesDrag" };
                var r1 = baseCircuit.Add(new Resistor { Value = 100 }, "R1", 20, 100);
                var r3 = baseCircuit.Add(new Resistor { Value = 300 }, "R3", 340, 100);
                var r2 = baseCircuit.Add(new Resistor { Value = 200 }, "R2", 180, 220);
                baseCircuit.Connect(r1.Pins[1], r3.Pins[0]);
                win.LoadExample(baseCircuit);

                // R2'nin gövdesini (220, 240) tutup (220, 120)'ye sürükle → Position=(180, 100), pinler (180,120)-(260,120)
                win.HandleElementLeftButtonDown(r2, new Point(220, 240));
                win.HandleCanvasMouseMove(new Point(220, 120));

                // Sürüklerken iki uç için iki önizleme halkası görünmeli
                Assert.Equal(2, win.DropConnectPreviews.Count);

                win.HandleCanvasLeftButtonUp(new Point(220, 120));

                Assert.Empty(win.DropConnectPreviews);
                Assert.Equal(2, win.Wires.Count);
                Assert.Empty(win.Elements.OfType<JunctionElement>());
                Assert.Equal("R2 tele seri eklendi", win.TxtStatus.Text);

                var nl = NetlistBuilder.Build(win.Elements, win.Wires);
                Assert.Equal(nl.NodeMap[r1.Pins[1]], nl.NodeMap[r2.Pins[0]]);
                Assert.Equal(nl.NodeMap[r2.Pins[1]], nl.NodeMap[r3.Pins[0]]);
                Assert.NotEqual(nl.NodeMap[r2.Pins[0]], nl.NodeMap[r2.Pins[1]]);

                // Tek Undo adımı R2'yi eski konumuna ve tek teli eski hâline döndürmeli
                win.Undo();
                Assert.Single(win.Wires);
                Assert.Equal(new Point(180, 220), win.Elements.OfType<Resistor>().Single(r => r.Id == "R2").Position);
            });
        }

        [Fact]
        public void MainWindow_RotateElementOntoWire_ConnectsInOneUndoStep()
        {
            RunOnSta(() =>
            {
                var win = new MainWindow();
                var baseCircuit = new ExampleCircuit { Name = "RotateConnect" };
                var v1 = baseCircuit.Add(new VoltageSource { Value = 10 }, "V1", 60, 140, 90);
                var gnd = baseCircuit.Add(new GroundElement(), "GND1", 320, 200);
                // D1 yatay (0°) iken pinleri (160,160) ve (240,160) — tele değmez; 90° dönünce alt pin (200,200) tele oturur
                var d1 = baseCircuit.Add(new Diode(), "D1", 160, 140, 0);
                baseCircuit.Connect(v1.Pins[1], gnd.Pins[0]);
                win.LoadExample(baseCircuit);

                win.Selection.Select(d1);
                win.RotateSelected();

                Assert.Equal(90, d1.Rotation);
                Assert.Single(win.Elements.OfType<JunctionElement>());
                Assert.Equal(3, win.Wires.Count);
                Assert.Equal("D1 tele bağlandı", win.TxtStatus.Text);

                // Tek Undo adımı hem dönüşü hem tel bölünmesini geri almalı
                win.Undo();
                Assert.Equal(0, win.Elements.OfType<Diode>().Single().Rotation);
                Assert.Empty(win.Elements.OfType<JunctionElement>());
                Assert.Single(win.Wires);
            });
        }

        [Fact]
        public void MainWindow_PasteOntoWire_ConnectsInOneUndoStep()
        {
            RunOnSta(() =>
            {
                var win = new MainWindow
                {
                    ClipboardService = new InMemoryClipboardService()
                };
                var baseCircuit = new ExampleCircuit { Name = "PasteConnect" };
                var r1 = baseCircuit.Add(new Resistor { Value = 100 }, "R1", 20, 100);
                var r3 = baseCircuit.Add(new Resistor { Value = 300 }, "R3", 340, 100);
                var src = baseCircuit.Add(new Resistor { Value = 200 }, "R2", 180, 260);
                baseCircuit.Connect(r1.Pins[1], r3.Pins[0]);
                win.LoadExample(baseCircuit);

                win.Selection.Select(src);
                Assert.True(win.CopySelected());

                // (180, 100) konumuna yapıştır → yeni R4 teli seri bölerek eklenmeli
                Assert.True(win.PasteFromClipboard(new Point(180, 100)));

                var r4 = win.Elements.OfType<Resistor>().Single(r => r.Id == "R4");
                Assert.Equal(new Point(180, 100), r4.Position);
                Assert.Equal(2, win.Wires.Count);
                Assert.Equal("R4 tele seri eklendi", win.TxtStatus.Text);

                win.Undo();
                Assert.DoesNotContain(win.Elements, e => e.Id == "R4");
                Assert.Single(win.Wires);
            });
        }

        [Fact]
        public void MainWindow_WireMode_DoesNotAutoConnectOnRotateOrClick()
        {
            RunOnSta(() =>
            {
                var win = new MainWindow();
                var baseCircuit = new ExampleCircuit { Name = "WireModeGuard" };
                var v1 = baseCircuit.Add(new VoltageSource { Value = 10 }, "V1", 60, 140, 90);
                var gnd = baseCircuit.Add(new GroundElement(), "GND1", 320, 200);
                var d1 = baseCircuit.Add(new Diode(), "D1", 160, 140, 0);
                baseCircuit.Connect(v1.Pins[1], gnd.Pins[0]);
                win.LoadExample(baseCircuit);

                // Tel moduna gir
                Click(win.BtnDrawWire);
                win.Selection.Select(d1);
                win.RotateSelected();

                // Tel modunda döndürme ve otomatik bağlama çalışmamalı
                Assert.Equal(0, d1.Rotation);
                Assert.Empty(win.Elements.OfType<JunctionElement>());
                Assert.Single(win.Wires);
            });
        }
    }
}
