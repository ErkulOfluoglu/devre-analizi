using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Shapes;
using CircuitAnalyzer.WPF;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

[Collection(WpfUiCollection.Name)]
public class DiodeTests
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

    [Fact]
    public void DefaultConstructor_UsesSiModel_AndHasAnodeCathodePins()
    {
        var diode = new Diode();
        Assert.Equal(DiodeModel.Si, diode.Model);
        Assert.Equal(2, diode.Pins.Count);
        Assert.Equal("A", diode.Pins[0].Id);
        Assert.Equal("K", diode.Pins[1].Id);
        Assert.Equal(new Point(0, 20), diode.Pins[0].RelativePosition);
        Assert.Equal(new Point(80, 20), diode.Pins[1].RelativePosition);
    }

    [Theory]
    [InlineData(DiodeModel.Ideal, "IDEAL", "")]
    [InlineData(DiodeModel.Si, "SI", "Si")]
    [InlineData(DiodeModel.Ge, "GE", "Ge")]
    public void ToNetlistEntry_FormatsAnodeCathodeAndModel(DiodeModel model, string expectedToken, string expectedLabel)
    {
        var diode = new Diode(model) { Id = "D1" };
        var nodeMap = new Dictionary<Pin, int>
        {
            [diode.Pins[0]] = 2, // anot
            [diode.Pins[1]] = 5, // katot
        };

        Assert.Equal(expectedLabel, diode.ModelLabel);
        Assert.Equal($"D1 2 5 {expectedToken}", diode.ToNetlistEntry(nodeMap));
    }

    [Fact]
    public void Zener_ToNetlistEntry_FormatsWithAndWithoutIzmUsingInvariantDecimal()
    {
        var zenerWithoutIzm = new Diode(DiodeModel.Zener) { Id = "D1" }; // varsayılan VZ=5.1, IZM=null
        var map1 = new Dictionary<Pin, int>
        {
            [zenerWithoutIzm.Pins[0]] = 2,
            [zenerWithoutIzm.Pins[1]] = 5,
        };
        Assert.Equal(5.1, zenerWithoutIzm.ZenerVoltage, 6);
        Assert.Null(zenerWithoutIzm.ZenerMaxCurrent);
        Assert.Equal("Vz=5,1V", zenerWithoutIzm.ModelLabel);
        Assert.Equal("D1 2 5 ZENER VZ=5.1", zenerWithoutIzm.ToNetlistEntry(map1));

        var zenerWithIzm = new Diode(DiodeModel.Zener)
        {
            Id = "D2",
            ZenerVoltage = 5.1,
            ZenerMaxCurrent = 0.03
        };
        var map2 = new Dictionary<Pin, int>
        {
            [zenerWithIzm.Pins[0]] = 0,
            [zenerWithIzm.Pins[1]] = 2,
        };
        Assert.Equal("D2 0 2 ZENER VZ=5.1 IZM=0.03", zenerWithIzm.ToNetlistEntry(map2));
    }

    [Fact]
    public void ToNetlistEntry_Rotated180_PreservesAnodeCathodeNetlistOrder()
    {
        // 180° döndürülünce: Pins[0] (Anot) sağda (280,120), Pins[1] (Katot) solda (200,120).
        var v1 = new VoltageSource { Id = "V1", Value = 12, Position = new Point(100, 200), Rotation = 90 };
        var d1 = new Diode(DiodeModel.Si) { Id = "D1", Position = new Point(200, 100), Rotation = 180 };
        var r1 = new Resistor { Id = "R1", Value = 1000, Position = new Point(300, 200), Rotation = 90 };
        var gnd = new GroundElement { Id = "GND1", Position = new Point(200, 300) };

        Assert.Equal(new Point(280, 120), d1.Pins[0].AbsolutePosition);
        Assert.Equal(new Point(200, 120), d1.Pins[1].AbsolutePosition);

        var elements = new CircuitElement[] { v1, d1, r1, gnd };
        var wires = new[]
        {
            new Wire(v1.Pins[0], d1.Pins[1]), // kaynak (+) → katot (sol uç)
            new Wire(d1.Pins[0], r1.Pins[0]), // anot (sağ uç) → direnç üstü
            new Wire(v1.Pins[1], gnd.Pins[0]),
            new Wire(r1.Pins[1], gnd.Pins[0]),
        };

        var netlist = NetlistBuilder.Build(elements, wires);
        int anodeNode = netlist.NodeMap[d1.Pins[0]];
        int cathodeNode = netlist.NodeMap[d1.Pins[1]];
        int sourcePlusNode = netlist.NodeMap[v1.Pins[0]];

        Assert.Equal(sourcePlusNode, cathodeNode);
        Assert.NotEqual(anodeNode, cathodeNode);
        Assert.Contains($"D1 {anodeNode} {cathodeNode} SI", netlist.Text);
    }

    [Theory]
    [InlineData(DiodeModel.Ideal, "IDEAL")]
    [InlineData(DiodeModel.Si, "SI")]
    [InlineData(DiodeModel.Ge, "GE")]
    public void CircuitDocument_RoundTrip_PreservesDiodeModel(DiodeModel model, string expectedJsonModel)
    {
        var diode = new Diode(model)
        {
            Id = "D1",
            Position = new Point(120, 80),
            Rotation = 90
        };

        var doc = CircuitDocument.FromCircuit(new[] { diode }, Array.Empty<Wire>());
        string json = doc.ToJson();

        Assert.Contains("\"type\": \"DIODE\"", json);
        Assert.Contains($"\"model\": \"{expectedJsonModel}\"", json);

        var loaded = CircuitDocument.FromJson(json).ToCircuit("Test");
        var restored = Assert.Single(loaded.Elements.OfType<Diode>());
        Assert.Equal("D1", restored.Id);
        Assert.Equal(model, restored.Model);
        Assert.Equal(new Point(120, 80), restored.Position);
        Assert.Equal(90, restored.Rotation);
    }

    [Fact]
    public void CircuitDocument_MissingModelField_DefaultsToSi()
    {
        const string json = """
        {
          "format": "devre-analizi",
          "version": 1,
          "elements": [
            { "type": "DIODE", "id": "D1", "x": 100, "y": 100, "rotation": 0 }
          ],
          "wires": []
        }
        """;

        var circuit = CircuitDocument.FromJson(json).ToCircuit("Legacy");
        var diode = Assert.Single(circuit.Elements.OfType<Diode>());
        Assert.Equal("D1", diode.Id);
        Assert.Equal(DiodeModel.Si, diode.Model);
    }

    [Fact]
    public void CircuitDocument_RoundTrip_PreservesZenerVzAndOptionalIzm()
    {
        var d1 = new Diode(DiodeModel.Zener)
        {
            Id = "D1",
            ZenerVoltage = 20,
            ZenerMaxCurrent = 0.03,
            Position = new Point(160, 200),
            Rotation = 270
        };
        var d2 = new Diode(DiodeModel.Zener)
        {
            Id = "D2",
            ZenerVoltage = 5.1,
            ZenerMaxCurrent = null,
            Position = new Point(260, 200),
            Rotation = 90
        };

        var doc = CircuitDocument.FromCircuit(new CircuitElement[] { d1, d2 }, Array.Empty<Wire>());
        string json = doc.ToJson();

        Assert.Contains("\"model\": \"ZENER\"", json);
        Assert.Contains("\"vz\": 20", json);
        Assert.Contains("\"izm\": 0.03", json);

        var loaded = CircuitDocument.FromJson(json).ToCircuit("ZenerTest");
        var restored1 = loaded.Elements.OfType<Diode>().Single(d => d.Id == "D1");
        var restored2 = loaded.Elements.OfType<Diode>().Single(d => d.Id == "D2");

        Assert.Equal(DiodeModel.Zener, restored1.Model);
        Assert.Equal(20, restored1.ZenerVoltage, 6);
        Assert.Equal(0.03, restored1.ZenerMaxCurrent!.Value, 6);
        Assert.Equal(270, restored1.Rotation);

        Assert.Equal(DiodeModel.Zener, restored2.Model);
        Assert.Equal(5.1, restored2.ZenerVoltage, 6);
        Assert.Null(restored2.ZenerMaxCurrent);
    }

    [Fact]
    public void CircuitDocument_OldDiodeFileWithoutVzIzm_LoadsFine()
    {
        const string json = """
        {
          "format": "devre-analizi",
          "version": 1,
          "elements": [
            { "type": "DIODE", "id": "D1", "model": "GE", "x": 100, "y": 100, "rotation": 0 }
          ],
          "wires": []
        }
        """;

        var circuit = CircuitDocument.FromJson(json).ToCircuit("OldDiode");
        var diode = Assert.Single(circuit.Elements.OfType<Diode>());
        Assert.Equal(DiodeModel.Ge, diode.Model);
        Assert.Equal(5.1, diode.ZenerVoltage, 6);
        Assert.Null(diode.ZenerMaxCurrent);
    }

    [Fact]
    public void Editor_ValidateZenerFields_AcceptsValidAndRejectsInvalid()
    {
        Assert.Null(ElementEditorWindow.ValidateZenerFields("5,1", "", out double vz1, out double? izm1));
        Assert.Equal(5.1, vz1, 6);
        Assert.Null(izm1);

        Assert.Null(ElementEditorWindow.ValidateZenerFields("20", "30 mA", out double vz2, out double? izm2));
        Assert.Equal(20, vz2, 6);
        Assert.Equal(0.03, izm2!.Value, 6);

        Assert.NotNull(ElementEditorWindow.ValidateZenerFields("", "", out _, out _));
        Assert.NotNull(ElementEditorWindow.ValidateZenerFields("0", "", out _, out _));
        Assert.NotNull(ElementEditorWindow.ValidateZenerFields("-5,1", "", out _, out _));
        Assert.NotNull(ElementEditorWindow.ValidateZenerFields("abc", "", out _, out _));
        Assert.NotNull(ElementEditorWindow.ValidateZenerFields("5,1", "0", out _, out _));
        Assert.NotNull(ElementEditorWindow.ValidateZenerFields("5,1", "-0,01", out _, out _));
        Assert.NotNull(ElementEditorWindow.ValidateZenerFields("5,1", "xyz", out _, out _));
    }

    [Fact]
    public void Clipboard_GetPrefixForDiode_ReturnsD()
    {
        Assert.Equal("D", CircuitClipboard.GetPrefixForElement(new Diode()));
    }

    [Fact]
    public void DependentSource_CanBeControl_RejectsDiode()
    {
        Assert.False(DependentSource.CanBeControl(new Diode(DiodeModel.Si)));
        Assert.False(DependentSource.CanBeControl(new Diode(DiodeModel.Ge)));
        Assert.False(DependentSource.CanBeControl(new Diode(DiodeModel.Ideal)));
        Assert.False(DependentSource.CanBeControl(new Diode(DiodeModel.Zener)));
    }

    [Fact]
    public void ApiModels_DeserializeDiodeResults_ParsesAllFields()
    {
        const string json = """
        {
          "status": "success",
          "mode": "DC",
          "analysis_type": "NODAL",
          "results": {
            "node_voltages": {},
            "element_currents": {}
          },
          "diodes": [
            { "id": "D1", "model": "SI", "v_t": 0.7, "state": "ON", "v_ak": 0.7, "i": 0.0043 },
            { "id": "D2", "model": "GE", "v_t": 0.3, "state": "OFF", "v_ak": -2.5, "i": 0.0 }
          ]
        }
        """;

        var dto = JsonSerializer.Deserialize<AnalysisResponseDto>(json);
        Assert.NotNull(dto);
        Assert.NotNull(dto!.DiodeResults);
        Assert.Equal(2, dto.DiodeResults!.Count);

        var d1 = dto.DiodeResults[0];
        Assert.Equal("D1", d1.Id);
        Assert.Equal("SI", d1.Model);
        Assert.Equal(0.7, d1.VT, 6);
        Assert.Equal("ON", d1.State);
        Assert.Equal(0.7, d1.VAk, 6);
        Assert.Equal(0.0043, d1.I, 6);

        var d2 = dto.DiodeResults[1];
        Assert.Equal("D2", d2.Id);
        Assert.Equal("GE", d2.Model);
        Assert.Equal(0.3, d2.VT, 6);
        Assert.Equal("OFF", d2.State);
        Assert.Equal(-2.5, d2.VAk, 6);
        Assert.Equal(0.0, d2.I, 6);
    }

    [Fact]
    public void ApiModels_DeserializeWithoutDiodesField_IsNull()
    {
        const string json = """
        {
          "status": "success",
          "mode": "DC",
          "analysis_type": "NODAL",
          "results": {
            "node_voltages": {},
            "element_currents": {}
          }
        }
        """;

        var dto = JsonSerializer.Deserialize<AnalysisResponseDto>(json);
        Assert.NotNull(dto);
        Assert.Null(dto!.Diodes);
        Assert.Null(dto.Results.Diodes);
        Assert.Null(dto.DiodeResults);
    }

    [Fact]
    public void AnalysisPanel_FormatDiodeLine_AndPrintContent_FormatCorrectly()
    {
        var dOn = new DiodeResultDto
        {
            Id = "D1",
            Model = "SI",
            VT = 0.7,
            State = "ON",
            VAk = 0.7,
            I = 0.0043
        };
        var dOff = new DiodeResultDto
        {
            Id = "D2",
            Model = "GE",
            VT = 0.3,
            State = "OFF",
            VAk = -1.5,
            I = 0.0
        };
        var dIdeal = new DiodeResultDto
        {
            Id = "D3",
            Model = "IDEAL",
            VT = 0.0,
            State = "ON",
            VAk = 0.0,
            I = 0.012
        };

        Assert.Equal(
            $"D1 (Si): iletimde · V_AK = 0,7 V · I = {EngFormat.Format(0.0043, "A")}",
            AnalysisPanel.FormatDiodeLine(dOn));
        Assert.Contains("4,3 mA", AnalysisPanel.FormatDiodeLine(dOn));

        Assert.Equal(
            "D2 (Ge): yalıtımda · V_AK = −1,5 V · I = 0 A",
            AnalysisPanel.FormatDiodeLine(dOff));

        Assert.Equal(
            "D3 (İdeal): iletimde · V_AK = 0 V · I = 12 mA",
            AnalysisPanel.FormatDiodeLine(dIdeal));

        var rows = PrintContent.DiodeRows(new[] { dOn, dOff });
        Assert.Equal(2, rows.Count);
        Assert.Equal(("D1 (Si)", "iletimde", "0,7 V", "4,3 mA"), rows[0]);
        Assert.Equal(("D2 (Ge)", "yalıtımda", "−1,5 V", "0 A"), rows[1]);
        Assert.Empty(PrintContent.DiodeRows(null));
    }

    [Fact]
    public void ApiModels_AndFormatting_ZenerResultDto_FormatsCorrectly()
    {
        const string json = """
        {
          "status": "success",
          "mode": "DC",
          "analysis_type": "NODAL",
          "results": {
            "node_voltages": {},
            "element_currents": {}
          },
          "diodes": [
            { "id": "D1", "model": "ZENER", "v_t": 0.7, "vz": 20.0, "izm": 0.03, "state": "ZENER", "v_ak": -20.0, "i": 0.0133333333 }
          ]
        }
        """;

        var dto = JsonSerializer.Deserialize<AnalysisResponseDto>(json);
        Assert.NotNull(dto);
        var z = Assert.Single(dto!.DiodeResults!);
        Assert.Equal("D1", z.Id);
        Assert.Equal("ZENER", z.Model);
        Assert.Equal(20.0, z.Vz!.Value, 6);
        Assert.Equal(0.03, z.Izm!.Value, 6);
        Assert.Equal("ZENER", z.State);
        Assert.Equal(-20.0, z.VAk, 6);

        Assert.Equal(
            $"D1 (Zener, V_Z = 20 V): ters iletimde (V_Z) · V_AK = −20 V · I_Z = {EngFormat.Format(z.I, "A")}",
            AnalysisPanel.FormatDiodeLine(z));

        var rows = PrintContent.DiodeRows(new[] { z });
        var row = Assert.Single(rows);
        Assert.Equal(("D1 (Zener 20 V)", "ters iletimde (V_Z)", "−20 V", EngFormat.Format(z.I, "A")), row);
    }

    [Fact]
    public void CreateVisual_ShowsModelLabelOnlyForSiAndGe()
    {
        RunOnSta(() =>
        {
            static List<string> TextBlocksOf(Diode diode)
            {
                var canvas = Assert.IsType<Canvas>(diode.CreateVisual());
                return canvas.Children.OfType<TextBlock>().Select(t => t.Text).ToList();
            }

            var siTexts = TextBlocksOf(new Diode(DiodeModel.Si) { Id = "D1" });
            Assert.Contains("Si", siTexts);
            Assert.Contains("D1", siTexts);

            var geTexts = TextBlocksOf(new Diode(DiodeModel.Ge) { Id = "D2" });
            Assert.Contains("Ge", geTexts);
            Assert.Contains("D2", geTexts);

            var idealTexts = TextBlocksOf(new Diode(DiodeModel.Ideal) { Id = "D3" });
            Assert.DoesNotContain("Si", idealTexts);
            Assert.DoesNotContain("Ge", idealTexts);
            Assert.Equal(new[] { "D3" }, idealTexts);

            var zenerCanvas = Assert.IsType<Canvas>(new Diode(DiodeModel.Zener) { Id = "D4" }.CreateVisual());
            var zenerTexts = zenerCanvas.Children.OfType<TextBlock>().Select(t => t.Text).ToList();
            Assert.Contains("Vz=5,1V", zenerTexts);
            Assert.Contains("D4", zenerTexts);
            Assert.Single(zenerCanvas.Children.OfType<Polyline>());
        });
    }

    [Fact]
    public void ExampleCircuit_DcSeriesParallelDiodes_HasValidNetlistAndParallelReverseDiode()
    {
        var c = ExampleCircuits.DcSeriesParallelDiodes();
        Assert.Contains((Func<ExampleCircuit>)ExampleCircuits.DcSeriesParallelDiodes, ExampleCircuits.All);
        Assert.Equal("Diyot: Seri ve Paralel Diyotlar", c.Name);
        Assert.Equal(AnalysisTypes.Nodal, c.SuggestedAnalysisType);

        var netlist = NetlistBuilder.Build(c.Elements, c.Wires);
        Assert.True(netlist.HasGround);

        var d3 = c.Elements.OfType<Diode>().Single(d => d.Id == "D3");
        var d2 = c.Elements.OfType<Diode>().Single(d => d.Id == "D2");
        var d1 = c.Elements.OfType<Diode>().Single(d => d.Id == "D1");

        Assert.Equal(DiodeModel.Si, d3.Model);
        Assert.Equal(DiodeModel.Ge, d2.Model);
        Assert.Equal(DiodeModel.Si, d1.Model);

        // D2 ve D1 aynı iki düğüm arasında ters yönlü paralel bağlı olmalı
        Assert.Equal(netlist.NodeMap[d2.Pins[0]], netlist.NodeMap[d1.Pins[1]]);
        Assert.Equal(netlist.NodeMap[d2.Pins[1]], netlist.NodeMap[d1.Pins[0]]);
        Assert.Equal(netlist.NodeMap[d3.Pins[1]], netlist.NodeMap[d2.Pins[0]]);
    }

    [Fact]
    public void ExampleCircuit_DcZenerVoltageRegulator_IsLastAndHasValidNetlist()
    {
        Assert.Equal((Func<ExampleCircuit>)ExampleCircuits.DcZenerVoltageRegulator, ExampleCircuits.All[^1]);

        var c = ExampleCircuits.DcZenerVoltageRegulator();
        Assert.Equal("Zener: Gerilim Regülatörü", c.Name);
        Assert.Equal("Zener ters iletimde; çıkış V_Y = V_Z = 20 V, I_Z = 13,33 mA.", c.Description);
        Assert.Equal(AnalysisTypes.Nodal, c.SuggestedAnalysisType);

        var netlist = NetlistBuilder.Build(c.Elements, c.Wires);
        Assert.True(netlist.HasGround);

        var d1 = c.Elements.OfType<Diode>().Single(d => d.Id == "D1");
        var ry = c.Elements.OfType<Resistor>().Single(r => r.Id == "RY");
        Assert.Equal(DiodeModel.Zener, d1.Model);
        Assert.Equal(20, d1.ZenerVoltage, 6);
        Assert.Equal(0.03, d1.ZenerMaxCurrent!.Value, 6);

        // Anot toprakta (0), katot çıkış düğümünde (RY'nin üst ucuyla aynı)
        Assert.Equal(0, netlist.NodeMap[d1.Pins[0]]);
        Assert.Equal(netlist.NodeMap[ry.Pins[0]], netlist.NodeMap[d1.Pins[1]]);
        Assert.Contains($"D1 0 {netlist.NodeMap[d1.Pins[1]]} ZENER VZ=20 IZM=0.03", netlist.Text);
    }
}
