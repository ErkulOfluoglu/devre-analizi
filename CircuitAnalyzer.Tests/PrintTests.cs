using System;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Documents;
using System.Windows.Media;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests
{
    [Collection(WpfUiCollection.Name)]
    public class PrintTests : IClassFixture<BackendFixture>
    {
        private readonly BackendFixture _fx;

        public PrintTests(BackendFixture fx)
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
        public async Task BuildDocument_WithRealAnalysisResponse_ContainsSectionTitlesAndDisclaimer()
        {
            var resp = await GetExample0ResponseAsync();
            Assert.NotNull(resp.Results?.Explanation);
            Assert.NotEmpty(resp.Results.Explanation);

            RunOnSta(() =>
            {
                var input = new PrintInput
                {
                    Response = resp,
                    Title = "Örnek 0 — Gerilim Bölücü",
                    Method = "Düğüm gerilimleri yöntemi",
                    IsPracticeMode = false
                };

                var doc = SolutionPrinter.BuildDocument(input);
                Assert.NotNull(doc);

                var tr = new TextRange(doc.ContentStart, doc.ContentEnd);
                string text = tr.Text;

                // Anlatım bölüm başlıkları bulunmalı
                foreach (var section in resp.Results.Explanation)
                {
                    Assert.Contains(section.Title, text);
                }

                // Sorumluluk reddi metni bulunmalı
                Assert.Contains("Sorumluluk", text);
                Assert.Contains("doğruluğu, eksiksizliği", text);

                // Beyaz sayfa üzerinde koyu mürekkep kontrolü
                Assert.NotNull(doc.Foreground);
                Assert.NotNull(doc.Background);

                if (doc.Foreground is SolidColorBrush fg)
                {
                    // Koyu mürekkep: R, G, B değerleri düşük olmalı (ör: siyah/koyu gri)
                    Assert.True(fg.Color.R < 100 && fg.Color.G < 100 && fg.Color.B < 100, "Yazı rengi koyu olmalı.");
                }

                if (doc.Background is SolidColorBrush bg)
                {
                    // Beyaz/açık sayfa zemin: R, G, B değerleri yüksek olmalı
                    Assert.True(bg.Color.R > 200 && bg.Color.G > 200 && bg.Color.B > 200, "Sayfa arka planı açık olmalı.");
                }
            });
        }

        [Fact]
        public async Task BuildDocument_InPracticeMode_ContainsQuestionLabelsButNotAnswersOrExplanation()
        {
            var resp = await GetExample0ResponseAsync();
            Assert.NotNull(resp.Results?.Practice);
            Assert.NotEmpty(resp.Results.Practice);

            RunOnSta(() =>
            {
                var input = new PrintInput
                {
                    Response = resp,
                    Title = "Soru #1001",
                    Method = "Düğüm gerilimleri yöntemi",
                    IsPracticeMode = true,
                    PracticeQuestions = resp.Results.Practice
                };

                var doc = SolutionPrinter.BuildDocument(input);
                Assert.NotNull(doc);

                var tr = new TextRange(doc.ContentStart, doc.ContentEnd);
                string text = tr.Text;

                // Soru etiketleri bulunmalı
                foreach (var q in resp.Results.Practice)
                {
                    Assert.Contains(q.Label, text);
                }

                // Soru başlığı bulunmalı
                Assert.Contains("Sorular", text);

                // Cevap değerleri (örnek: "8 V") yer ALMAMALI
                Assert.DoesNotContain("8 V", text);

                // Anlatım bölüm başlıkları yer ALMAMALI
                string textWithoutDisclaimer = text.Replace(AppInfo.Disclaimer, "");
                if (resp.Results.Explanation != null)
                {
                    foreach (var section in resp.Results.Explanation)
                    {
                        Assert.DoesNotContain(section.Title, textWithoutDisclaimer);
                    }
                }

                // Sorumluluk reddi metni yine de bulunmalı
                Assert.Contains("Sorumluluk", text);
            });
        }
    }
}
