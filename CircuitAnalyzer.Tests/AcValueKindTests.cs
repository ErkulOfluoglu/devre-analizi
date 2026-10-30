using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows.Controls;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

public class AcValueKindTests
{
    private static void RunOnSta(Action action)
    {
        Exception? error = null;
        var thread = new Thread(() =>
        {
            try
            {
                action();
            }
            catch (Exception ex)
            {
                error = ex;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        if (error != null)
            ExceptionDispatchInfo.Capture(error).Throw();
    }

    private static Dictionary<Pin, int> NodeMap(CircuitElement el, int n1 = 1, int n2 = 0)
    {
        var map = new Dictionary<Pin, int>();
        if (el.Pins.Count > 0) map[el.Pins[0]] = n1;
        if (el.Pins.Count > 1) map[el.Pins[1]] = n2;
        return map;
    }

    [Fact]
    public void Default_ValueKind_IsPeak()
    {
        var vac = new AcVoltageSource();
        Assert.Equal(AcValueKind.Peak, vac.ValueKind);

        var iac = new AcCurrentSource();
        Assert.Equal(AcValueKind.Peak, iac.ValueKind);
    }

    [Theory]
    [InlineData(AcValueKind.Peak, "V1 1 0 SINE(0 220 50 0 0 30)")]
    [InlineData(AcValueKind.Rms, "V1 1 0 SINE(0 220 50 0 0 30) RMS")]
    public void AcVoltageSource_ToNetlistEntry_Physical(AcValueKind kind, string expected)
    {
        var vac = new AcVoltageSource
        {
            Id = "V1",
            Amplitude = 220,
            Frequency = 50,
            Phase = 30,
            InputMode = AcInputMode.Physical,
            ValueKind = kind
        };

        string line = vac.ToNetlistEntry(NodeMap(vac, 1, 0));
        Assert.Equal(expected, line);
    }

    [Theory]
    [InlineData(AcValueKind.Peak, "V1 1 0 AC_PHASOR(220, 30)")]
    [InlineData(AcValueKind.Rms, "V1 1 0 AC_PHASOR(220, 30) RMS")]
    public void AcVoltageSource_ToNetlistEntry_Phasor(AcValueKind kind, string expected)
    {
        var vac = new AcVoltageSource
        {
            Id = "V1",
            Amplitude = 220,
            Phase = 30,
            InputMode = AcInputMode.Phasor,
            ValueKind = kind
        };

        string line = vac.ToNetlistEntry(NodeMap(vac, 1, 0));
        Assert.Equal(expected, line);
    }

    [Theory]
    [InlineData(AcValueKind.Peak, "I1 1 0 SINE(0 0.01 50 0 0 30)")]
    [InlineData(AcValueKind.Rms, "I1 1 0 SINE(0 0.01 50 0 0 30) RMS")]
    public void AcCurrentSource_ToNetlistEntry_Physical(AcValueKind kind, string expected)
    {
        var iac = new AcCurrentSource
        {
            Id = "I1",
            Amplitude = 0.01,
            Frequency = 50,
            Phase = 30,
            InputMode = AcInputMode.Physical,
            ValueKind = kind
        };

        string line = iac.ToNetlistEntry(NodeMap(iac, 1, 0));
        Assert.Equal(expected, line);
    }

    [Theory]
    [InlineData(AcValueKind.Peak, "I1 1 0 AC_PHASOR(0.01, 30)")]
    [InlineData(AcValueKind.Rms, "I1 1 0 AC_PHASOR(0.01, 30) RMS")]
    public void AcCurrentSource_ToNetlistEntry_Phasor(AcValueKind kind, string expected)
    {
        var iac = new AcCurrentSource
        {
            Id = "I1",
            Amplitude = 0.01,
            Phase = 30,
            InputMode = AcInputMode.Phasor,
            ValueKind = kind
        };

        string line = iac.ToNetlistEntry(NodeMap(iac, 1, 0));
        Assert.Equal(expected, line);
    }

    [Fact]
    public void ValueLabel_AcVoltageSource_FormatValue()
    {
        var vacRms = new AcVoltageSource
        {
            Amplitude = 220,
            Frequency = 50,
            Phase = 0,
            ValueKind = AcValueKind.Rms
        };
        Assert.Equal("220V 50Hz", vacRms.FormatValue());

        var vacPeak = new AcVoltageSource
        {
            Amplitude = 311,
            Frequency = 50,
            Phase = 0,
            ValueKind = AcValueKind.Peak
        };
        Assert.Equal("Um 311V 50Hz", vacPeak.FormatValue());

        var vacRmsPhasor = new AcVoltageSource
        {
            Amplitude = 220,
            Phase = 30,
            InputMode = AcInputMode.Phasor,
            ValueKind = AcValueKind.Rms
        };
        Assert.Equal("220V∠30°", vacRmsPhasor.FormatValue());

        var vacPeakPhasor = new AcVoltageSource
        {
            Amplitude = 311,
            Phase = 30,
            InputMode = AcInputMode.Phasor,
            ValueKind = AcValueKind.Peak
        };
        Assert.Equal("Um 311V∠30°", vacPeakPhasor.FormatValue());
    }

    [Fact]
    public void ValueLabel_AcCurrentSource_FormatValue()
    {
        var iacRms = new AcCurrentSource
        {
            Amplitude = 0.01,
            Frequency = 50,
            Phase = 0,
            ValueKind = AcValueKind.Rms
        };
        Assert.Equal("10mA 50Hz", iacRms.FormatValue());

        var iacPeak = new AcCurrentSource
        {
            Amplitude = 0.01,
            Frequency = 50,
            Phase = 0,
            ValueKind = AcValueKind.Peak
        };
        Assert.Equal("Im 10mA 50Hz", iacPeak.FormatValue());

        var iacRmsPhasor = new AcCurrentSource
        {
            Amplitude = 0.01,
            Phase = 30,
            InputMode = AcInputMode.Phasor,
            ValueKind = AcValueKind.Rms
        };
        Assert.Equal("10mA∠30°", iacRmsPhasor.FormatValue());

        var iacPeakPhasor = new AcCurrentSource
        {
            Amplitude = 0.01,
            Phase = 30,
            InputMode = AcInputMode.Phasor,
            ValueKind = AcValueKind.Peak
        };
        Assert.Equal("Im 10mA∠30°", iacPeakPhasor.FormatValue());
    }

    [Fact]
    public void ValueLabel_CreateVisual_ShowsExpectedLabelOnCanvas()
    {
        RunOnSta(() =>
        {
            var vac = new AcVoltageSource
            {
                Amplitude = 311,
                Frequency = 50,
                Phase = 0,
                ValueKind = AcValueKind.Peak
            };
            var visual = Assert.IsType<Canvas>(vac.CreateVisual());
            var textBlocks = visual.Children.OfType<TextBlock>().ToList();
            Assert.Contains(textBlocks, tb => tb.Text == "Um 311V 50Hz");
        });
    }

    [Fact]
    public void CircuitDocument_RoundTrip_PreservesValueKind()
    {
        var vac = new AcVoltageSource
        {
            Id = "VAC1",
            Amplitude = 220,
            Frequency = 50,
            Phase = 15,
            ValueKind = AcValueKind.Rms
        };
        var iac = new AcCurrentSource
        {
            Id = "IAC1",
            Amplitude = 0.05,
            Frequency = 60,
            Phase = -30,
            ValueKind = AcValueKind.Peak
        };

        var doc = CircuitDocument.FromCircuit(new CircuitElement[] { vac, iac }, Enumerable.Empty<Wire>());
        string json = doc.ToJson();

        Assert.Contains("\"value_kind\": \"rms\"", json);
        Assert.Contains("\"value_kind\": \"peak\"", json);

        var restoredDoc = CircuitDocument.FromJson(json);
        var circuit = restoredDoc.ToCircuit("TestCircuit");

        var restoredVac = circuit.Elements.OfType<AcVoltageSource>().Single();
        Assert.Equal(AcValueKind.Rms, restoredVac.ValueKind);
        Assert.Equal(220, restoredVac.Amplitude);

        var restoredIac = circuit.Elements.OfType<AcCurrentSource>().Single();
        Assert.Equal(AcValueKind.Peak, restoredIac.ValueKind);
        Assert.Equal(0.05, restoredIac.Amplitude);
    }

    [Fact]
    public void CircuitDocument_LegacyFileWithoutValueKind_OpensAsPeak()
    {
        string legacyJson = """
        {
            "format": "devre-analizi",
            "version": 1,
            "elements": [
                {
                    "type": "VAC",
                    "id": "VAC1",
                    "x": 100,
                    "y": 100,
                    "amplitude": 120,
                    "frequency": 60,
                    "phase": 0
                },
                {
                    "type": "IAC",
                    "id": "IAC1",
                    "x": 200,
                    "y": 100,
                    "amplitude": 0.02,
                    "frequency": 60,
                    "phase": 0
                }
            ],
            "wires": []
        }
        """;

        var doc = CircuitDocument.FromJson(legacyJson);
        var circuit = doc.ToCircuit("LegacyCircuit");

        var vac = circuit.Elements.OfType<AcVoltageSource>().Single();
        Assert.Equal(AcValueKind.Peak, vac.ValueKind);

        var iac = circuit.Elements.OfType<AcCurrentSource>().Single();
        Assert.Equal(AcValueKind.Peak, iac.ValueKind);
    }

    [Fact]
    public void CircuitDocument_AnalysisData_ValueDisplay_RoundTrip()
    {
        var doc = new CircuitDocument
        {
            Analysis = new CircuitDocument.AnalysisData
            {
                Type = "nodal",
                ValueDisplay = "PEAK"
            }
        };

        string json = doc.ToJson();
        Assert.Contains("\"value_display\": \"PEAK\"", json);

        var restored = CircuitDocument.FromJson(json);
        Assert.NotNull(restored.Analysis);
        Assert.Equal("PEAK", restored.Analysis!.ValueDisplay);
    }

    [Fact]
    public void AnalysisRequestDto_Serializes_ValueDisplay()
    {
        var req = new AnalysisRequestDto
        {
            Netlist = "V1 1 0 SINE(0 10 50 0 0 0)",
            ValueDisplay = "RMS"
        };
        string json = JsonSerializer.Serialize(req);
        Assert.Contains("\"value_display\":\"RMS\"", json);

        req.ValueDisplay = "PEAK";
        json = JsonSerializer.Serialize(req);
        Assert.Contains("\"value_display\":\"PEAK\"", json);
    }

    [Fact]
    public void LlmAskRequestDto_From_CopiesValueDisplay()
    {
        var analysis = new AnalysisRequestDto
        {
            Netlist = "V1 1 0 SINE(0 10 50 0 0 0)",
            Mode = "ac_phasor",
            Frequency = 50,
            AnalysisType = "nodal",
            ValueDisplay = "PEAK"
        };

        var ask = LlmAskRequestDto.From(analysis, "Devre akımı nedir?");
        Assert.Equal("PEAK", ask.ValueDisplay);

        analysis.ValueDisplay = "RMS";
        var askRms = LlmAskRequestDto.From(analysis, "Gerilim nedir?");
        Assert.Equal("RMS", askRms.ValueDisplay);
    }

    [Fact]
    public void ExampleCircuits_AcCircuits_UseRmsValueKind()
    {
        var lowPass = ExampleCircuits.AcRcLowPass();
        var vacLowPass = lowPass.Elements.OfType<AcVoltageSource>().Single();
        Assert.Equal(AcValueKind.Rms, vacLowPass.ValueKind);

        var rlSeries = ExampleCircuits.AcRlSeries();
        var vacRl = rlSeries.Elements.OfType<AcVoltageSource>().Single();
        Assert.Equal(AcValueKind.Rms, vacRl.ValueKind);
    }

    [Fact]
    public void ProblemGenerator_AcCircuits_UseRmsValueKind()
    {
        // 1000..9999 aralığında AC soru türlerinden biri üretildiğinde ValueKind Rms olmalı
        bool tested = false;
        for (int code = 1000; code < 2000; code++)
        {
            var problem = ProblemGenerator.Generate(code);
            var ac = problem.Elements.OfType<AcVoltageSource>().FirstOrDefault();
            if (ac != null)
            {
                Assert.Equal(AcValueKind.Rms, ac.ValueKind);
                tested = true;
                break;
            }
        }
        Assert.True(tested, "En az bir AC üretilen soru test edilmiş olmalı.");
    }

    [Fact]
    public void AnalysisPanel_ValueDisplay_DefaultAndEvents()
    {
        RunOnSta(() =>
        {
            string tempSettings = Path.Combine(Path.GetTempPath(), $"settings_{Guid.NewGuid()}.json");
            AppSettings.SettingsPath = tempSettings;

            try
            {
                var panel = new AnalysisPanel();
                Assert.Equal("RMS", panel.ValueDisplay);

                bool eventFired = false;
                panel.ValueDisplayChanged += (_, _) => eventFired = true;

                panel.SetValueDisplay("PEAK", notify: true);
                Assert.Equal("PEAK", panel.ValueDisplay);
                Assert.True(eventFired);
                Assert.Equal("PEAK", AppSettings.AcValueDisplay);

                var settings = panel.GetAnalysisSettings();
                Assert.Equal("PEAK", settings.ValueDisplay);

                // Boş veya null ValueDisplay geldiğinde mevcut ayar korunmalı
                panel.RestoreAnalysisSettings(new CircuitDocument.AnalysisData { ValueDisplay = null });
                Assert.Equal("PEAK", panel.ValueDisplay);

                panel.RestoreAnalysisSettings(new CircuitDocument.AnalysisData { ValueDisplay = "RMS" });
                Assert.Equal("RMS", panel.ValueDisplay);
            }
            finally
            {
                if (File.Exists(tempSettings)) File.Delete(tempSettings);
            }
        });
    }
}
