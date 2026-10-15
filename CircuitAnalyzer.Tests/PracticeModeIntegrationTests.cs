using System;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Threading.Tasks;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests
{
    [Collection(WpfUiCollection.Name)]
    public class PracticeModeIntegrationTests : IClassFixture<BackendFixture>
    {
        private readonly BackendFixture _fx;

        public PracticeModeIntegrationTests(BackendFixture fx)
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

        private async Task<AnalysisResponseDto> GetExample0ResponseAsync()
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
            return await _fx.Client.AnalyzeAsync(req);
        }

        [Fact]
        public async Task PracticeMode_True_RendersPracticeView_AndRevealsSolution()
        {
            var resp = await GetExample0ResponseAsync();

            RunOnSta(() =>
            {
                var panel = new AnalysisPanel();
                panel.IsPracticeMode = true;
                panel.ShowResults(resp);

                Assert.True(panel.IsShowingPractice);
                Assert.NotNull(panel.CurrentPracticeView);

                bool revealedFired = false;
                panel.SolutionRevealed += (_, _) => revealedFired = true;

                panel.RevealSolution();

                Assert.True(revealedFired);
                Assert.False(panel.IsShowingPractice);
            });
        }

        [Fact]
        public async Task PracticeMode_False_RendersNormalResultsView()
        {
            var resp = await GetExample0ResponseAsync();

            RunOnSta(() =>
            {
                var panel = new AnalysisPanel();
                panel.IsPracticeMode = false;
                panel.ShowResults(resp);

                Assert.False(panel.IsShowingPractice);
                Assert.Null(panel.CurrentPracticeView);
            });
        }

        [Fact]
        public void SetProblemCode_SetsVisibleText_AndClearsWhenNull()
        {
            RunOnSta(() =>
            {
                var panel = new AnalysisPanel();

                panel.SetProblemCode(4821);
                Assert.Equal("Soru #4821", panel.ProblemCodeText);

                panel.SetProblemCode(null);
                Assert.Null(panel.ProblemCodeText);
            });
        }
    }
}
