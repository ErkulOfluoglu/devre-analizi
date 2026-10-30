using System;
using System.Collections.Generic;
using System.Windows;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

public class TurkishNumberTests
{
    private static void RunOnSta(Action action)
    {
        Exception? ex = null;
        var thread = new System.Threading.Thread(() =>
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
        thread.SetApartmentState(System.Threading.ApartmentState.STA);
        thread.Start();
        thread.Join();

        if (ex != null)
        {
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(ex).Throw();
        }
    }

    [Fact]
    public void EngFormat_ShowsTurkishDecimalComma()
    {
        Assert.Equal("10,09 V", EngFormat.Format(10.09, "V"));
        Assert.Equal("1,909 mA", EngFormat.Format(0.001909, "A"));
        Assert.Equal("4,7 kΩ", EngFormat.Format(4700.0, "Ω"));
        Assert.Equal("2,5 V", EngFormat.Format(2.5, "V"));
    }

    [Fact]
    public void CanvasElementValueLabels_ShowTurkishDecimalComma()
    {
        RunOnSta(() =>
        {
            var r = new Resistor { Id = "R1", Value = 4700 };
            var rVisual = r.CreateVisual();
            var texts = ExtractTexts(rVisual);
            Assert.Contains("4,7kΩ", texts);

            var v = new VoltageSource { Id = "V1", Value = 10.09 };
            var vVisual = v.CreateVisual();
            var vTexts = ExtractTexts(vVisual);
            Assert.Contains("10,09V", vTexts);

            var c = new Capacitor { Id = "C1", Value = 2.2e-6 };
            var cVisual = c.CreateVisual();
            var cTexts = ExtractTexts(cVisual);
            Assert.Contains("2,2µF", cTexts);

            var l = new Inductor { Id = "L1", Value = 4.7e-3 };
            var lVisual = l.CreateVisual();
            var lTexts = ExtractTexts(lVisual);
            Assert.Contains("4,7mH", lTexts);

            var cs = new CurrentSource { Id = "I1", Value = 0.0015 };
            var csVisual = cs.CreateVisual();
            var csTexts = ExtractTexts(csVisual);
            Assert.Contains("1,5 mA", csTexts);
        });
    }

    [Fact]
    public void ComplexValue_ToRectangularAndPolar_ShowComma()
    {
        var cv = ComplexValue.FromRectangular(50.5, 30.2);
        Assert.Equal("50,5+j30,2", cv.ToRectangularString());

        var polar = ComplexValue.FromPolar(10.5, 30.5);
        Assert.Equal("10,5∠30,5°", polar.ToPolarString());
    }

    [Theory]
    [InlineData("4,7k", "4.7k", 4700.0)]
    [InlineData("2,2 mA", "2.2 mA", 0.0022)]
    [InlineData("0,5", "0.5", 0.5)]
    [InlineData("10,09", "10.09", 10.09)]
    [InlineData("1000", "1000", 1000.0)]
    [InlineData("-2,5", "-2.5", -2.5)]
    [InlineData("47µ", "47u", 47e-6)]
    public void EditorParsing_AcceptsCommaAndDotEqually(string commaInput, string dotInput, double expected)
    {
        bool ok1 = TurkishNumber.TryParseSpice(commaInput, out double val1);
        bool ok2 = TurkishNumber.TryParseSpice(dotInput, out double val2);

        Assert.True(ok1, $"Failed to parse comma input: {commaInput}");
        Assert.True(ok2, $"Failed to parse dot input: {dotInput}");
        Assert.Equal(expected, val1, 6);
        Assert.Equal(expected, val2, 6);
        Assert.Equal(val1, val2);
    }

    [Theory]
    [InlineData("−12,5", -12.5)]
    [InlineData("−3,2m", -3.2e-3)]
    public void EditorParsing_AcceptsUnicodeMinus(string input, double expected)
    {
        Assert.True(TurkishNumber.TryParseSpice(input, out double val));
        Assert.Equal(expected, val, 9);
    }

    [Theory]
    [InlineData("1M", 1e6)]
    [InlineData("2,2 MΩ", 2.2e6)]
    [InlineData("1meg", 1e6)]
    [InlineData("1MEG", 1e6)]
    [InlineData("5m", 5e-3)]
    [InlineData("50 mA", 50e-3)]
    public void EditorParsing_UpperMIsMegaLowerMIsMilli(string input, double expected)
    {
        Assert.True(TurkishNumber.TryParseSpice(input, out double val));
        Assert.Equal(expected, val, 9);
    }

    [Theory]
    [InlineData("2,2", 1e6, 2.2)]        // düz sayı alanın biriminde (µF)
    [InlineData("100µ", 1e6, 100)]       // 100 µF
    [InlineData("100u", 1e6, 100)]
    [InlineData("470n", 1e6, 0.47)]      // 470 nF = 0,47 µF
    [InlineData("10 µF", 1e6, 10)]
    [InlineData("47m", 1e3, 47)]         // 47 mH
    [InlineData("1,5", 1e3, 1.5)]        // 1,5 mH
    [InlineData("4,7k", 1, 4700)]        // direnç alanı
    [InlineData("1e-3", 1e6, 1e-3)]      // üslü düz sayı da alanın biriminde
    public void EditorField_PrefixedInputIsConvertedToFieldUnit(string input, double unitScale, double expected)
    {
        Assert.True(CircuitAnalyzer.WPF.ElementEditorWindow.TryParseFieldValue(input, unitScale, out double val));
        Assert.Equal(expected, val, 9);
    }

    [Theory]
    [InlineData("1.000,5")]
    [InlineData("1,000.5")]
    [InlineData("1.2.3")]
    [InlineData("1,2,3")]
    public void EditorParsing_NeverTreatsSeparatorsAsThousands(string invalidInput)
    {
        // Birden fazla ayırıcı içeren girdiler binlik ayırıcı sanılmamalı, reddedilmeli
        Assert.False(TurkishNumber.TryParse(invalidInput, out _));
        Assert.False(TurkishNumber.TryParseSpice(invalidInput, out _));
    }

    [Fact]
    public void ComplexValue_TryParse_AcceptsCommaAndDotEqually()
    {
        bool ok1 = ComplexValue.TryParse("50,5+j30,2", out var cv1);
        bool ok2 = ComplexValue.TryParse("50.5+j30.2", out var cv2);
        Assert.True(ok1);
        Assert.True(ok2);
        Assert.Equal(cv1.Real, cv2.Real, 6);
        Assert.Equal(cv1.Imaginary, cv2.Imaginary, 6);

        bool okP1 = ComplexValue.TryParse("10,5∠30,5", out var cp1);
        bool okP2 = ComplexValue.TryParse("10.5∠30.5", out var cp2);
        Assert.True(okP1);
        Assert.True(okP2);
        Assert.Equal(cp1.Magnitude, cp2.Magnitude, 6);
        Assert.Equal(cp1.AngleDegrees, cp2.AngleDegrees, 6);
    }

    [Fact]
    public void NetlistBuilder_EmitsDots_For47kResistorAnd05Gain()
    {
        var r = new Resistor { Id = "R1", Value = 4700, Position = new Point(0, 0) };
        var dep = new DependentSource(DependentSourceKind.Vcvs)
        {
            Id = "E1",
            Gain = 0.5,
            ControlElementId = "R1",
            Position = new Point(100, 0)
        };
        var gnd = new GroundElement { Id = "GND1", Position = new Point(0, 100) };

        var w1 = new Wire(r.Pins[0], gnd.Pins[0]);
        var w2 = new Wire(r.Pins[1], dep.Pins[0]);
        var w3 = new Wire(dep.Pins[1], gnd.Pins[0]);

        var netlist = NetlistBuilder.Build(
            new List<CircuitElement> { r, dep, gnd },
            new List<Wire> { w1, w2, w3 });

        string netlistText = netlist.Text;

        // SPICE satırlarında kazanç 0.5 nokta ile olmalı, asla virgül içermemeli
        Assert.Contains("0.5", netlistText);
        Assert.DoesNotContain("0,5", netlistText);

        // Bir diğer direnç: 4.7 ohm
        var rFrac = new Resistor { Id = "R2", Value = 4.7 };
        var nodeMap = new Dictionary<Pin, int> { [rFrac.Pins[0]] = 1, [rFrac.Pins[1]] = 2 };
        string rEntry = rFrac.ToNetlistEntry(nodeMap);
        Assert.Equal("R2 1 2 4.7", rEntry);
        Assert.DoesNotContain(",", rEntry);
    }

    [Fact]
    public void DevreFile_RoundTrip_UnchangedAndPreservesValues()
    {
        RunOnSta(() =>
        {
            var r = new Resistor { Id = "R1", Value = 4700, Position = new Point(60, 60) };
            var c = new Capacitor { Id = "C1", Value = 2.2e-6, Position = new Point(140, 60) };
            var v = new VoltageSource { Id = "V1", Value = 10.5, Position = new Point(60, 140) };
            var dep = new DependentSource(DependentSourceKind.Vcvs)
            {
                Id = "E1",
                Gain = 0.5,
                ControlElementId = "R1",
                Position = new Point(140, 140)
            };
            var gnd = new GroundElement { Id = "GND1", Position = new Point(60, 220) };

            var wire = new Wire(r.Pins[1], c.Pins[0]);

            var elements = new List<CircuitElement> { r, c, v, dep, gnd };
            var wires = new List<Wire> { wire };

            var doc = CircuitDocument.FromCircuit(elements, wires);
            string json = doc.ToJson();

            // JSON içinde sayılar invariant olmalı (noktalı)
            Assert.Contains("4700", json);
            Assert.Contains("10.5", json);
            Assert.Contains("0.5", json);

            var restoredDoc = CircuitDocument.FromJson(json);
            var restoredCircuit = restoredDoc.ToCircuit("Restored");
            var restoredElements = restoredCircuit.Elements;

            Assert.Equal(elements.Count, restoredElements.Count);

            var restoredR = Assert.IsType<Resistor>(restoredElements[0]);
            Assert.Equal(4700, restoredR.Value);

            var restoredC = Assert.IsType<Capacitor>(restoredElements[1]);
            Assert.Equal(2.2e-6, restoredC.Value, 8);

            var restoredV = Assert.IsType<VoltageSource>(restoredElements[2]);
            Assert.Equal(10.5, restoredV.Value);

            var restoredDep = Assert.IsType<DependentSource>(restoredElements[3]);
            Assert.Equal(0.5, restoredDep.Gain);
        });
    }

    private static List<string> ExtractTexts(UIElement visual)
    {
        var list = new List<string>();
        if (visual is System.Windows.Controls.Panel panel)
        {
            foreach (UIElement child in panel.Children)
            {
                if (child is System.Windows.Controls.TextBlock tb && !string.IsNullOrEmpty(tb.Text))
                    list.Add(tb.Text);
            }
        }
        return list;
    }
}
