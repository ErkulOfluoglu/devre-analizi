using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Json;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;
using Xunit.Abstractions;

namespace CircuitAnalyzer.Tests;

[Collection(WpfUiCollection.Name)]
public class Step3IntegrationTests : IClassFixture<BackendFixture>
{
    private readonly BackendFixture _fx;
    private readonly ITestOutputHelper _output;

    public Step3IntegrationTests(BackendFixture fx, ITestOutputHelper output)
    {
        _fx = fx;
        _output = output;
    }

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

    private static string? FindAppExe()
    {
        var current = new DirectoryInfo(AppContext.BaseDirectory);
        while (current != null)
        {
            var wpfDir = Path.Combine(current.FullName, "CircuitAnalyzer.WPF");
            if (Directory.Exists(wpfDir))
            {
                var binDir = Path.Combine(wpfDir, "bin");
                if (Directory.Exists(binDir))
                {
                    var candidates = new[]
                    {
                        Path.Combine(binDir, "Debug", "net8.0-windows", "CircuitAnalyzer.exe"),
                        Path.Combine(binDir, "Release", "net8.0-windows", "CircuitAnalyzer.exe")
                    };

                    foreach (var candidate in candidates)
                    {
                        if (File.Exists(candidate))
                            return candidate;
                    }

                    foreach (var configDir in Directory.GetDirectories(binDir))
                    {
                        var candidate = Path.Combine(configDir, "net8.0-windows", "CircuitAnalyzer.exe");
                        if (File.Exists(candidate))
                            return candidate;
                    }
                }
            }
            current = current.Parent;
        }
        return null;
    }

    // ═══════════════════════════════════════════════════════
    // 1. NetlistBuilder NODEPOS
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void NetlistBuilder_DcDivider_EmitsNodePosLinesWithPinAverages_AndEndsWithEnd()
    {
        var circuit = TestCircuits.DcDivider();
        var result = NetlistBuilder.Build(circuit.Elements, circuit.Wires);

        // Ends with .end
        Assert.EndsWith(".end", result.Text.TrimEnd());

        // Nodes 0, 1, 2
        Assert.True(result.NodePins.ContainsKey(0));
        Assert.True(result.NodePins.ContainsKey(1));
        Assert.True(result.NodePins.ContainsKey(2));
        Assert.Equal(3, result.NodePins.Count);

        var lines = result.Text.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.None);
        var nodePosLines = lines.Where(l => l.StartsWith("* NODEPOS ")).ToList();
        Assert.Equal(3, nodePosLines.Count);

        foreach (int node in new[] { 0, 1, 2 })
        {
            var pins = result.NodePins[node];
            double avgX = pins.Average(p => p.AbsolutePosition.X);
            double avgY = pins.Average(p => p.AbsolutePosition.Y);
            string expectedLine = string.Create(CultureInfo.InvariantCulture, $"* NODEPOS {node} {avgX:0.#} {avgY:0.#}");
            Assert.Contains(expectedLine, result.Text);
        }
    }

    [Fact]
    public void NetlistBuilder_DcDivider_UnderTrCulture_CoordinatesStillUsePeriod()
    {
        var prevCulture = CultureInfo.CurrentCulture;
        var prevUiCulture = CultureInfo.CurrentUICulture;
        try
        {
            CultureInfo.CurrentCulture = new CultureInfo("tr-TR");
            CultureInfo.CurrentUICulture = new CultureInfo("tr-TR");

            var circuit = TestCircuits.DcDivider();
            var result = NetlistBuilder.Build(circuit.Elements, circuit.Wires);

            var lines = result.Text.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.None);
            var nodePosLines = lines.Where(l => l.StartsWith("* NODEPOS ")).ToList();
            Assert.Equal(3, nodePosLines.Count);

            foreach (var line in nodePosLines)
            {
                Assert.DoesNotContain(",", line);
                Assert.Matches(@"^\* NODEPOS \d+ -?\d+(\.\d+)? -?\d+(\.\d+)?$", line);
            }
        }
        finally
        {
            CultureInfo.CurrentCulture = prevCulture;
            CultureInfo.CurrentUICulture = prevUiCulture;
        }
    }

    // ═══════════════════════════════════════════════════════
    // 2. Panel (STA): Mesh & Superposition options & UI
    // ═══════════════════════════════════════════════════════

    [Fact]
    public void AnalysisPanel_Mesh_OptionsSucceedWithoutTerminals_AndHidesTerminalRow()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAnalysisType(AnalysisTypes.Mesh);

            bool ok = panel.TryGetOptions(out var opt, out var err);
            Assert.True(ok);
            Assert.Null(err);
            Assert.NotNull(opt);
            Assert.Equal(AnalysisTypes.Mesh, opt!.AnalysisType);
            Assert.Null(opt.TerminalPositive);
            Assert.Equal(Visibility.Collapsed, panel.RowTerminals.Visibility);
        });
    }

    [Fact]
    public void AnalysisPanel_Superposition_OptionsSucceedWithoutTerminals_AndHidesTerminalRow()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAnalysisType(AnalysisTypes.Superposition);

            bool ok = panel.TryGetOptions(out var opt, out var err);
            Assert.True(ok);
            Assert.Null(err);
            Assert.NotNull(opt);
            Assert.Equal(AnalysisTypes.Superposition, opt!.AnalysisType);
            Assert.Null(opt.TerminalPositive);
            Assert.Equal(Visibility.Collapsed, panel.RowTerminals.Visibility);
        });
    }

    [Fact]
    public void AnalysisPanel_SwitchingFromTheveninToMeshOrSuperposition_HidesTerminalRow()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAvailableNodes(new[] { 0, 1, 2, 3 });

            panel.SetAnalysisType(AnalysisTypes.Thevenin, "2");
            Assert.Equal(Visibility.Visible, panel.RowTerminals.Visibility);

            panel.SetAnalysisType(AnalysisTypes.Mesh);
            Assert.Equal(Visibility.Collapsed, panel.RowTerminals.Visibility);
            Assert.True(panel.TryGetOptions(out var meshOpt, out _));
            Assert.Equal(AnalysisTypes.Mesh, meshOpt!.AnalysisType);

            panel.SetAnalysisType(AnalysisTypes.Thevenin, "2");
            Assert.Equal(Visibility.Visible, panel.RowTerminals.Visibility);

            panel.SetAnalysisType(AnalysisTypes.Superposition);
            Assert.Equal(Visibility.Collapsed, panel.RowTerminals.Visibility);
            Assert.True(panel.TryGetOptions(out var supOpt, out _));
            Assert.Equal(AnalysisTypes.Superposition, supOpt!.AnalysisType);
        });
    }

    // ═══════════════════════════════════════════════════════
    // 3. Real solver: Example 4 (Mesh) & Example 5 (Superposition)
    // ═══════════════════════════════════════════════════════

    [Fact]
    public async Task RealSolver_Example4_MeshAnalysis_VerifiesVoltagesCurrentsAndMeshNarrative()
    {
        var circuit = ExampleCircuits.All[4]();
        var netlist = NetlistBuilder.Build(circuit.Elements, circuit.Wires);

        var r2 = circuit.Elements.First(e => e.Id == "R2");
        var r3 = circuit.Elements.First(e => e.Id == "R3");
        int middleNode = netlist.NodeMap[r2.Pins[0]];
        int rightTopNode = netlist.NodeMap[r3.Pins[1]];

        var request = new AnalysisRequestDto
        {
            Netlist = netlist.Text,
            Mode = AnalysisModes.Dc,
            AnalysisType = AnalysisTypes.Mesh,
        };

        using var http = new HttpClient();
        var httpResp = await http.PostAsJsonAsync(new Uri(_fx.Client.BaseAddress, "/analyze"), request);
        Assert.True(httpResp.IsSuccessStatusCode);
        string json = await httpResp.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);
        var response = JsonSerializer.Deserialize<AnalysisResponseDto>(json)!;

        // V(middle node) = 8 V
        Assert.Equal(8.0, response.Results.NodeVoltages[middleNode.ToString()].Value.Real, 4);

        // V(right top node) = 10 V
        Assert.Equal(10.0, response.Results.NodeVoltages[rightTopNode.ToString()].Value.Real, 4);

        // I(I1) = 2 mA (0.002 A)
        Assert.Equal(0.002, response.Results.ElementCurrents["I1"].Value.Real, 6);

        // response.Results.Meshes has 2 entries
        var resultsElem = doc.RootElement.GetProperty("results");
        Assert.True(resultsElem.TryGetProperty("meshes", out var meshesElem));
        Assert.Equal(2, meshesElem.GetArrayLength());

        // explanation contains a section "Çevreler (Gözler)" whose blocks mention "saat yönünde"
        var meshSection = response.Results.Explanation.FirstOrDefault(s => s.Title == "Çevreler (Gözler)");
        Assert.NotNull(meshSection);
        Assert.Contains(meshSection.Blocks, b => b.Text.Contains("saat yönünde"));
    }

    [Fact]
    public async Task RealSolver_Example5_Superposition_VerifiesContributionsAndTotalsNarrative()
    {
        var circuit = ExampleCircuits.All[5]();
        var netlist = NetlistBuilder.Build(circuit.Elements, circuit.Wires);

        var r2 = circuit.Elements.First(e => e.Id == "R2");
        int middleNode = netlist.NodeMap[r2.Pins[0]];

        var request = new AnalysisRequestDto
        {
            Netlist = netlist.Text,
            Mode = AnalysisModes.Dc,
            AnalysisType = AnalysisTypes.Superposition,
        };

        using var http = new HttpClient();
        var httpResp = await http.PostAsJsonAsync(new Uri(_fx.Client.BaseAddress, "/analyze"), request);
        Assert.True(httpResp.IsSuccessStatusCode);
        string json = await httpResp.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);
        var response = JsonSerializer.Deserialize<AnalysisResponseDto>(json)!;

        // response.Results.Superposition has 2 entries (V1, V2)
        var resultsElem = doc.RootElement.GetProperty("results");
        Assert.True(resultsElem.TryGetProperty("superposition", out var supElem));
        Assert.Equal(2, supElem.GetArrayLength());

        double? v1MiddleContrib = null;
        double? v2MiddleContrib = null;

        foreach (var item in supElem.EnumerateArray())
        {
            string sourceId = item.GetProperty("source_id").GetString()!;
            var nodeVoltages = item.GetProperty("node_voltages");
            double middleVal = nodeVoltages.GetProperty(middleNode.ToString()).GetProperty("real").GetDouble();

            if (sourceId == "V1")
                v1MiddleContrib = middleVal;
            else if (sourceId == "V2")
                v2MiddleContrib = middleVal;
        }

        Assert.NotNull(v1MiddleContrib);
        Assert.NotNull(v2MiddleContrib);

        // V(middle) contributions 4.8 V and 2.4 V
        Assert.Equal(4.8, v1MiddleContrib.Value, 4);
        Assert.Equal(2.4, v2MiddleContrib.Value, 4);

        // explanation contains "Toplam: Katkıların Toplanması" with "7.2 V" and a check block containing "✓"
        var totalSection = response.Results.Explanation.FirstOrDefault(s => s.Title == "Toplam: Katkıların Toplanması");
        Assert.NotNull(totalSection);
        Assert.Contains(totalSection.Blocks, b => b.Text.Contains("7.2 V"));
        Assert.Contains(totalSection.Blocks, b => b.Kind == "check" && b.Text.Contains("✓"));
    }

    // ═══════════════════════════════════════════════════════
    // 4. --selftest smoke: examples 4 and 5
    // ═══════════════════════════════════════════════════════

    [Theory]
    [InlineData(4)]
    [InlineData(5)]
    public void Selftest_Smoke_ExitsZero_WritesNonEmptyPngAndTxt(int exampleIndex)
    {
        string? exePath = FindAppExe();
        if (exePath == null)
        {
            _output.WriteLine("CircuitAnalyzer.exe not found; skipping selftest smoke test.");
            return;
        }

        string tempPng = Path.Combine(Path.GetTempPath(), $"selftest_{exampleIndex}_{Guid.NewGuid():N}.png");
        string tempTxt = Path.ChangeExtension(tempPng, ".txt");

        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = exePath,
                Arguments = $"--selftest {exampleIndex} \"{tempPng}\"",
                UseShellExecute = false,
                CreateNoWindow = true,
            };

            using var process = Process.Start(psi);
            Assert.NotNull(process);

            bool exited = process.WaitForExit(120_000);
            Assert.True(exited, $"CircuitAnalyzer.exe --selftest {exampleIndex} did not exit within 120 seconds.");
            Assert.Equal(0, process.ExitCode);

            Assert.True(File.Exists(tempPng), $"Expected PNG output not found at: {tempPng}");
            Assert.True(new FileInfo(tempPng).Length > 0, "Expected PNG file to be non-empty.");

            Assert.True(File.Exists(tempTxt), $"Expected TXT output not found at: {tempTxt}");
            string txtContent = File.ReadAllText(tempTxt);
            Assert.Contains("Sonuç var: True", txtContent);
        }
        finally
        {
            try { if (File.Exists(tempPng)) File.Delete(tempPng); } catch { }
            try { if (File.Exists(tempTxt)) File.Delete(tempTxt); } catch { }
        }
    }
}
