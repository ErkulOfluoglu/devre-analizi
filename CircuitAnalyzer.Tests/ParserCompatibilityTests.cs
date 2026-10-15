using System.Net;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Windows;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.Tests;

public class ParserCompatibilityTests : IClassFixture<BackendFixture>
{
    private readonly BackendFixture _fx;

    public ParserCompatibilityTests(BackendFixture fx) => _fx = fx;

    private static string BuildTinyGroundedNetlist(CircuitElement element)
    {
        var gnd = new GroundElement { Id = "GND1", Position = new Point(0, 200) };
        element.Position = new Point(0, 0);
        var wire = new Wire(element.Pins[1], gnd.Pins[0]);
        var result = NetlistBuilder.Build(new List<CircuitElement> { element, gnd }, new List<Wire> { wire });
        return result.Text;
    }

    private async Task AssertParseOnlyAsync(
        CircuitElement element,
        string expectedId,
        string expectedType,
        double expectedValue,
        bool isAc = false,
        double? frequency = null)
    {
        string netlist = BuildTinyGroundedNetlist(element);

        var payload = new
        {
            netlist,
            mode = isAc ? AnalysisModes.AcPhasor : AnalysisModes.Dc,
            frequency = isAc ? (frequency ?? 50.0) : (double?)null
        };

        using var http = new HttpClient();
        var jsonContent = new StringContent(
            JsonSerializer.Serialize(payload),
            Encoding.UTF8,
            "application/json");

        var response = await http.PostAsync(
            new Uri(_fx.Client.BaseAddress, "/parse-only"),
            jsonContent);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        string body = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(body);
        var root = doc.RootElement;

        // Warnings boş olmalı (tanınmayan satır yok)
        var warnings = root.GetProperty("warnings").EnumerateArray().ToList();
        Assert.Empty(warnings);

        // Eleman doğru ID ve tip ile görünmeli
        var elements = root.GetProperty("elements").EnumerateArray().ToList();
        var parsedElem = Assert.Single(elements);

        Assert.Equal(expectedId, parsedElem.GetProperty("id").GetString());
        Assert.Equal(expectedType, parsedElem.GetProperty("type").GetString());

        // Sayısal değer %0.1 bağıl tolerans içinde eşleşmeli
        double parsedVal = parsedElem.GetProperty("value").GetDouble();
        double relDiff = Math.Abs(parsedVal - expectedValue) / Math.Abs(expectedValue);
        Assert.True(relDiff <= 0.001,
            $"Eleman {expectedId} için beklenen: {expectedValue}, ayrıştırılan: {parsedVal}, bağıl fark: {relDiff:P3}");
    }

    [Fact]
    public Task ParseOnly_Resistor_4700() =>
        AssertParseOnlyAsync(new Resistor { Id = "R1", Value = 4700 }, "R1", "R", 4700);

    [Fact]
    public Task ParseOnly_Resistor_1Mega() =>
        AssertParseOnlyAsync(new Resistor { Id = "R1", Value = 1e6 }, "R1", "R", 1e6);

    [Fact]
    public Task ParseOnly_Capacitor_100uF() =>
        AssertParseOnlyAsync(new Capacitor { Id = "C1", Value = 100e-6 }, "C1", "C", 100e-6);

    [Fact]
    public Task ParseOnly_Capacitor_4_7nF() =>
        AssertParseOnlyAsync(new Capacitor { Id = "C1", Value = 4.7e-9 }, "C1", "C", 4.7e-9);

    [Fact]
    public Task ParseOnly_Capacitor_2_2F() =>
        AssertParseOnlyAsync(new Capacitor { Id = "C1", Value = 2.2 }, "C1", "C", 2.2);

    [Fact]
    public Task ParseOnly_Capacitor_12000uF() =>
        AssertParseOnlyAsync(new Capacitor { Id = "C1", Value = 12000e-6 }, "C1", "C", 12000e-6);

    [Fact]
    public Task ParseOnly_Inductor_0_1H() =>
        AssertParseOnlyAsync(new Inductor { Id = "L1", Value = 0.1 }, "L1", "L", 0.1);

    [Fact]
    public Task ParseOnly_Inductor_1_5H() =>
        AssertParseOnlyAsync(new Inductor { Id = "L1", Value = 1.5 }, "L1", "L", 1.5);

    [Fact]
    public Task ParseOnly_Inductor_2_2uH() =>
        AssertParseOnlyAsync(new Inductor { Id = "L1", Value = 2.2e-6 }, "L1", "L", 2.2e-6);

    [Fact]
    public Task ParseOnly_Impedance_Rectangular_NegativeImaginary()
    {
        var z = new ImpedanceElement
        {
            Id = "Z1",
            InputMode = ImpedanceInputMode.Rectangular,
            Impedance = ComplexValue.FromRectangular(50, -30)
        };
        // Empedans büyüklüğü: sqrt(50^2 + (-30)^2) ≈ 58.3095
        return AssertParseOnlyAsync(z, "Z1", "Z", z.Impedance.Magnitude);
    }

    [Fact]
    public Task ParseOnly_Impedance_Polar()
    {
        var z = new ImpedanceElement
        {
            Id = "Z1",
            InputMode = ImpedanceInputMode.Polar,
            Impedance = ComplexValue.FromPolar(58.31, 30.96)
        };
        return AssertParseOnlyAsync(z, "Z1", "Z", 58.31);
    }

    [Fact]
    public Task ParseOnly_VoltageSource_DC_12V() =>
        AssertParseOnlyAsync(new VoltageSource { Id = "V1", Value = 12 }, "V1", "V_DC", 12);

    [Fact]
    public Task ParseOnly_VoltageSource_DC_Negative5V() =>
        AssertParseOnlyAsync(new VoltageSource { Id = "V1", Value = -5 }, "V1", "V_DC", -5);

    [Fact]
    public Task ParseOnly_AcVoltageSource_Sine_10V_50Hz_30Deg()
    {
        var vac = new AcVoltageSource
        {
            Id = "VAC1",
            InputMode = AcInputMode.Physical,
            Amplitude = 10,
            Frequency = 50,
            Phase = 30
        };
        return AssertParseOnlyAsync(vac, "VAC1", "V_AC_SINE", 10, isAc: true, frequency: 50);
    }

    [Fact]
    public Task ParseOnly_AcVoltageSource_Phasor_12V_45Deg()
    {
        var vac = new AcVoltageSource
        {
            Id = "VAC1",
            InputMode = AcInputMode.Phasor,
            Amplitude = 12,
            Phase = 45
        };
        return AssertParseOnlyAsync(vac, "VAC1", "V_AC_PHASOR", 12, isAc: true, frequency: 50);
    }

    [Fact]
    public async Task FullAnalyze_AcPhysicalSource_InfresFrequencyFromSource()
    {
        // AC Physical (SINE 10 V, 50 Hz) + R 100 + C 100µF + GND
        var c = new TestCircuits();
        var vac = c.Add(new AcVoltageSource
        {
            Amplitude = 10,
            Frequency = 50,
            Phase = 0,
            InputMode = AcInputMode.Physical
        }, "VAC1");
        var r1 = c.Add(new Resistor { Value = 100 }, "R1");
        var c1 = c.Add(new Capacitor { Value = 100e-6 }, "C1");
        var gnd = c.Add(new GroundElement(), "GND1");

        c.Wire(vac.Pins[0], r1.Pins[0]);
        c.Wire(r1.Pins[1], c1.Pins[0]);
        c.Wire(c1.Pins[1], gnd.Pins[0]);
        c.Wire(vac.Pins[1], gnd.Pins[0]);

        var request = new AnalysisRequestDto
        {
            Netlist = NetlistBuilder.Build(c.Elements, c.Wires).Text,
            Mode = AnalysisModes.AcPhasor,
            Frequency = null, // Frekans null gönderilir; çözücü SINE kaynağından 50 Hz almalı
            AnalysisType = AnalysisTypes.Nodal
        };

        var resp = await _fx.Client.AnalyzeAsync(request);

        Assert.Equal("success", resp.Status);

        // Düğüm 2 gerilimi (RC alçak geçiren filtre çıkışı):
        // |Z_C| = 1 / (2 * pi * 50 * 100e-6) ≈ 31.831 Ω
        // |V_2| = 10 * (31.831 / sqrt(100^2 + 31.831^2)) ≈ 3.0331 V
        var v2 = resp.Results.NodeVoltages["2"].Value;
        Assert.True(v2.IsComplex);
        Assert.Equal(3.0331, v2.Magnitude, 3);

        // Kaynak frekansının otomatik kullanıldığı bilgisi uyarılarda yer almalı
        Assert.Contains(resp.Warnings, w => w.Contains("kaynak frekansı kullanıldı"));
    }
}
