using System.Diagnostics;
using System.IO;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Gerçek Python çözücüsünü BackendManager ile başlatır (tüm sınıf için bir kez).
/// </summary>
public sealed class BackendFixture : IAsyncLifetime
{
    public BackendManager Manager { get; } = new();
    public AnalysisApiClient Client { get; private set; } = null!;

    public async Task InitializeAsync() => Client = await Manager.StartAsync();

    public Task DisposeAsync()
    {
        Manager.Dispose();
        return Task.CompletedTask;
    }
}

public class BackendIntegrationTests : IClassFixture<BackendFixture>
{
    private readonly BackendFixture _fx;

    public BackendIntegrationTests(BackendFixture fx) => _fx = fx;

    private static AnalysisRequestDto Request(TestCircuits c, string mode,
        double? frequency = null, string type = AnalysisTypes.Nodal, TerminalsDto? terminals = null) =>
        new()
        {
            Netlist = NetlistBuilder.Build(c.Elements, c.Wires).Text,
            Mode = mode,
            Frequency = frequency,
            AnalysisType = type,
            TheveninTerminals = terminals,
        };

    [Fact]
    public async Task Health_ReportsOurService()
    {
        var health = await _fx.Client.TryGetHealthAsync();
        Assert.NotNull(health);
        Assert.Equal(AnalysisApiClient.ExpectedServiceName, health!.Service);
    }

    [Fact]
    public async Task DcDivider_SolvesFromDrawnCircuit()
    {
        var resp = await _fx.Client.AnalyzeAsync(Request(TestCircuits.DcDivider(), AnalysisModes.Dc));

        Assert.Equal("success", resp.Status);
        Assert.Equal(8.0, resp.Results.NodeVoltages["2"].Value.Real, 6);
        Assert.False(resp.Results.NodeVoltages["2"].Value.IsComplex);
        Assert.Equal(0.004, resp.Results.ElementCurrents["R1"].Value.Real, 6);
        Assert.Equal("1→2", resp.Results.ElementCurrents["R1"].Direction);

        var probe = Assert.Single(resp.Results.ProbeResults);
        Assert.Equal("VP1", probe.ProbeId);
        Assert.Equal(8.0, probe.Value.Real, 6);

        Assert.NotNull(resp.Results.Power);
        Assert.Equal(-0.048, resp.Results.Power!.Elements["V1"].ActivePower, 6);
        Assert.Contains(resp.SolutionSteps, s => s.Title.StartsWith("KCL"));
    }

    [Fact]
    public async Task AcRc_ReturnsComplexValues()
    {
        var resp = await _fx.Client.AnalyzeAsync(
            Request(TestCircuits.AcRcLowPass(), AnalysisModes.AcPhasor, frequency: 50));

        var v2 = resp.Results.NodeVoltages["2"].Value;
        Assert.True(v2.IsComplex);
        Assert.Equal(3.0331, v2.Magnitude, 3);
        Assert.Equal(-72.34, v2.PhaseDegrees, 1);
        Assert.Equal("ileri", resp.Results.Power!.PowerFactorType);
    }

    [Fact]
    public async Task Thevenin_And_Norton_RoundTrip()
    {
        var term = new TerminalsDto { NodePositive = "2", NodeNegative = "0" };
        var th = await _fx.Client.AnalyzeAsync(
            Request(TestCircuits.DcDivider(), AnalysisModes.Dc, type: AnalysisTypes.Thevenin, terminals: term));
        Assert.Equal(8.0, th.Results.Thevenin!.Vth.Real, 6);
        Assert.Equal(666.666667, th.Results.Thevenin.Zth.Real, 4);

        var no = await _fx.Client.AnalyzeAsync(
            Request(TestCircuits.DcDivider(), AnalysisModes.Dc, type: AnalysisTypes.Norton, terminals: term));
        Assert.Equal(0.012, no.Results.Norton!.In.Real, 6);
        Assert.NotNull(no.Results.Norton.Zn);
    }

    [Fact]
    public async Task MissingFrequencyForPhasor_ComesBackAsError()
    {
        var resp = await _fx.Client.AnalyzeAsync(
            Request(TestCircuits.AcRcLowPass(), AnalysisModes.AcPhasor, frequency: null));
        Assert.Equal("warning", resp.Status);
        Assert.Contains(resp.Errors, e => e.Contains("frekans gerekli"));
    }

    [Fact]
    public async Task EmptyNetlist_Throws400WithReadableMessage()
    {
        var ex = await Assert.ThrowsAsync<AnalysisRequestException>(() =>
            _fx.Client.AnalyzeAsync(new AnalysisRequestDto { Netlist = "* sadece yorum", Mode = "DC" }));
        Assert.Equal(400, ex.StatusCode);
        Assert.Contains("devre elemanı bulunamadı", ex.Message);
    }

    [Fact]
    public void FindApiSourceDir_LocatesPythonProject()
    {
        string? dir = BackendManager.FindApiSourceDir(AppContext.BaseDirectory);
        Assert.NotNull(dir);
        Assert.True(File.Exists(Path.Combine(dir!, "main.py")));
    }
}

public class BackendLifecycleTests
{
    [Fact]
    public async Task Dispose_StopsPythonProcess()
    {
        var manager = new BackendManager();
        var client = await manager.StartAsync();
        int port = client.BaseAddress.Port;
        Assert.NotNull(await client.TryGetHealthAsync());

        manager.Dispose();

        using var probe = new AnalysisApiClient(new Uri($"http://127.0.0.1:{port}"));
        var sw = Stopwatch.StartNew();
        while (await probe.TryGetHealthAsync() != null && sw.Elapsed < TimeSpan.FromSeconds(5))
            await Task.Delay(200);
        Assert.Null(await probe.TryGetHealthAsync());
    }
}
