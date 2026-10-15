using System;
using System.Collections.Generic;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Threading;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

[Collection(WpfUiCollection.Name)]
public class AssistantIntegrationTests : IClassFixture<BackendFixture>
{
    private readonly BackendFixture _fx;

    public AssistantIntegrationTests(BackendFixture fx)
    {
        _fx = fx;
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

    private static void RunAsync(Func<Task> asyncFunc)
    {
        var task = asyncFunc();
        if (!task.IsCompleted)
        {
            var frame = new DispatcherFrame();
            task.ContinueWith(_ => frame.Continue = false);
            Dispatcher.PushFrame(frame);
        }
        task.GetAwaiter().GetResult();
    }

    private async Task<(AnalysisRequestDto req, AnalysisResponseDto resp)> GetExample0DataAsync()
    {
        var example = ExampleCircuits.All[0]();
        var netlist = NetlistBuilder.Build(example.Elements, example.Wires);
        var req = new AnalysisRequestDto
        {
            Netlist = netlist.Text,
            Mode = netlist.HasAcSource ? AnalysisModes.AcPhasor : AnalysisModes.Dc,
            Frequency = null,
            AnalysisType = example.SuggestedAnalysisType,
            TheveninTerminals = example.SuggestedTerminal != null
                ? new TerminalsDto { NodePositive = example.SuggestedTerminal, NodeNegative = "0" }
                : null
        };
        var resp = await _fx.Client.AnalyzeAsync(req);
        return (req, resp);
    }

    [Fact]
    public async Task AnalysisPanel_WithCurrentRequest_ShowResults_CurrentAssistantViewNotNull()
    {
        var (req, resp) = await GetExample0DataAsync();

        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.CurrentRequest = req;
            panel.ShowResults(resp);

            Assert.NotNull(panel.CurrentAssistantView);
        });
    }

    [Fact]
    public async Task AnalysisPanel_WithoutCurrentRequest_ShowResults_CurrentAssistantViewNull()
    {
        var (_, resp) = await GetExample0DataAsync();

        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.CurrentRequest = null;
            panel.ShowResults(resp);

            Assert.Null(panel.CurrentAssistantView);
        });
    }

    [Fact]
    public async Task PracticeMode_RevealSolution_ReusesAssistantViewInstance_PreservesHistory()
    {
        var (req, resp) = await GetExample0DataAsync();

        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.IsPracticeMode = true;
            panel.CurrentRequest = req;
            panel.LlmStatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
            {
                Available = true,
                Models = new List<string> { "llama3" },
                SelectedModel = "llama3"
            });
            panel.LlmAsker = (askReq, _) => Task.FromResult(new LlmAnswerDto
            {
                Answer = "Alıştırma için yol gösterici açıklama",
                Model = "llama3"
            });

            panel.ShowResults(resp);

            var initialAssistant = panel.CurrentAssistantView;
            Assert.NotNull(initialAssistant);
            Assert.True(initialAssistant!.IsPractice);

            // Sahte soru-cevap işlemi
            RunAsync(() => initialAssistant.AskAsync("Nereden başlamalıyım?"));

            Assert.Equal(2, initialAssistant.History.Count);

            // Çözümü göster
            panel.RevealSolution();

            // Aynı nesne referansı korunmalı, IsPractice false olmalı ve geçmiş saklanmalı
            Assert.Same(initialAssistant, panel.CurrentAssistantView);
            Assert.False(panel.CurrentAssistantView.IsPractice);
            Assert.Equal(2, panel.CurrentAssistantView.History.Count);
        });
    }

    [Fact]
    public async Task LiveClient_TryGetLlmStatusAsync_ReturnsNonNullWithNonEmptyMessage()
    {
        var status = await _fx.Client.TryGetLlmStatusAsync();

        Assert.NotNull(status);
        Assert.False(string.IsNullOrWhiteSpace(status!.Message));
    }
}
