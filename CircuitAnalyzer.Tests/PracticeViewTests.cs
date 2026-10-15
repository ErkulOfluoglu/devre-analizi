using System;
using System.Collections.Generic;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests
{
    [Collection(WpfUiCollection.Name)]
    public class PracticeViewTests
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

        private static (List<PracticeQuestionDto> questions, List<ExplanationSectionDto> explanations) CreateFakeData()
        {
            var questions = new List<PracticeQuestionDto>
            {
                new()
                {
                    Id = "q1",
                    Label = "V1 gerilimi",
                    Group = "main",
                    Unit = "V",
                    Expected = new ComplexNumberDto { Real = 5, RectangularStr = "5" }
                },
                new()
                {
                    Id = "q2",
                    Label = "I1 akımı",
                    Group = "main",
                    IsAc = true,
                    Unit = "A",
                    Expected = new ComplexNumberDto { Real = 2, RectangularStr = "2<0" }
                },
                new()
                {
                    Id = "q3",
                    Label = "P1 gücü",
                    Group = "extra",
                    Unit = "W",
                    Expected = new ComplexNumberDto { Real = 10, RectangularStr = "10" }
                }
            };

            var explanations = new List<ExplanationSectionDto>
            {
                new()
                {
                    Title = "1. Adım: Düğüm Seçimi",
                    Blocks = new List<ExplanationBlockDto>
                    {
                        new() { Kind = "text", Text = "Düğüm 1 referans alındı." }
                    }
                },
                new()
                {
                    Title = "2. Adım: KCL Uygulaması",
                    Blocks = new List<ExplanationBlockDto>
                    {
                        new() { Kind = "text", Text = "Düğüm denklemleri yazıldı." }
                    }
                },
                new()
                {
                    Title = "Sonuç",
                    Blocks = new List<ExplanationBlockDto>
                    {
                        new() { Kind = "text", Text = "V1 = 5V, I1 = 2A." }
                    }
                }
            };

            return (questions, explanations);
        }

        [Fact]
        public void Load_ThreeQuestionsAndThreeSections_SetsUpCorrectly()
        {
            RunOnSta(() =>
            {
                var pv = new PracticeView();
                var (questions, explanations) = CreateFakeData();

                pv.Load(questions, explanations);

                Assert.Equal(3, pv.Questions.Count);
                // "Sonuç" başlıklı son bölüm hariç tutulmalı → 2
                Assert.Equal(2, pv.HintsAvailable);

                Assert.NotNull(pv.GetAnswerBox("q1"));
                Assert.NotNull(pv.GetAnswerBox("q2"));
                Assert.NotNull(pv.GetAnswerBox("q3"));

                Assert.Throws<KeyNotFoundException>(() => pv.GetAnswerBox("unknown_id"));
            });
        }

        [Fact]
        public void CheckAsync_AllBoxesEmpty_DoesNotCallChecker_ShowsError()
        {
            RunOnSta(() =>
            {
                var pv = new PracticeView();
                var (questions, explanations) = CreateFakeData();
                pv.Load(questions, explanations);

                bool checkerCalled = false;
                pv.AnswerChecker = _ =>
                {
                    checkerCalled = true;
                    return Task.FromResult(new AnswerCheckResponseDto());
                };

                RunAsync(pv.CheckAsync);

                Assert.False(checkerCalled, "Cevaplar boşken denetleyici çağrılmamalı.");

                var txtError = (TextBlock)pv.FindName("TxtError");
                Assert.NotNull(txtError);
                Assert.Equal(Visibility.Visible, txtError.Visibility);
                Assert.Contains("Önce en az bir cevap yazın.", txtError.Text);
            });
        }

        [Fact]
        public void CheckAsync_FakeChecker_UpdatesRowsAndDoesNotResendCorrectAnswers()
        {
            RunOnSta(() =>
            {
                var pv = new PracticeView();
                var (questions, explanations) = CreateFakeData();
                pv.Load(questions, explanations);

                pv.GetAnswerBox("q1").Text = "5";
                pv.GetAnswerBox("q2").Text = "1";

                var sentRequests = new List<AnswerCheckRequestDto>();
                pv.AnswerChecker = req =>
                {
                    sentRequests.Add(req);
                    return Task.FromResult(new AnswerCheckResponseDto
                    {
                        CorrectCount = 1,
                        Total = 2,
                        Verdicts = new List<AnswerVerdictDto>
                        {
                            new()
                            {
                                QuestionId = "q1",
                                Status = AnswerStatuses.Correct,
                                Message = "Doğru!",
                                UnderstoodAs = "5 V"
                            },
                            new()
                            {
                                QuestionId = "q2",
                                Status = AnswerStatuses.Wrong,
                                Message = "Yanlış değer.",
                                UnderstoodAs = "1 A"
                            }
                        }
                    });
                };

                RunAsync(pv.CheckAsync);

                Assert.Single(sentRequests);
                Assert.Equal(2, sentRequests[0].Items.Count);

                Assert.Equal(AnswerStatuses.Correct, pv.GetStatus("q1"));
                Assert.Equal("Doğru!", pv.GetFeedback("q1"));
                Assert.Equal(AnswerStatuses.Wrong, pv.GetStatus("q2"));
                Assert.Equal("Yanlış değer.", pv.GetFeedback("q2"));
                Assert.Equal(1, pv.CorrectCount);
                Assert.True(pv.GetAnswerBox("q1").IsReadOnly);

                // İkinci kontrol: q1 doğru olduğundan tekrar gönderilmemeli
                sentRequests.Clear();
                pv.GetAnswerBox("q2").Text = "2";
                RunAsync(pv.CheckAsync);

                Assert.Single(sentRequests);
                Assert.DoesNotContain(sentRequests[0].Items, item => item.Question.Id == "q1");
                Assert.Contains(sentRequests[0].Items, item => item.Question.Id == "q2");
            });
        }

        [Fact]
        public void CheckAsync_CheckerThrowsException_ShowsErrorMessageWithoutCrashing()
        {
            RunOnSta(() =>
            {
                var pv = new PracticeView();
                var (questions, explanations) = CreateFakeData();
                pv.Load(questions, explanations);

                pv.GetAnswerBox("q1").Text = "5";

                pv.AnswerChecker = _ => Task.FromException<AnswerCheckResponseDto>(
                    new InvalidOperationException("Sunucu bağlantısı koptu."));

                // Hata fırlatılmamalı, yakalanıp gösterilmeli
                RunAsync(pv.CheckAsync);

                var txtError = (TextBlock)pv.FindName("TxtError");
                Assert.NotNull(txtError);
                Assert.Equal(Visibility.Visible, txtError.Visibility);
                Assert.Contains("kontrol edilemedi", txtError.Text);
            });
        }

        [Fact]
        public void ShowNextHint_IncrementsHintsShownUntilMax()
        {
            RunOnSta(() =>
            {
                var pv = new PracticeView();
                var (questions, explanations) = CreateFakeData();
                pv.Load(questions, explanations);

                Assert.Equal(2, pv.HintsAvailable);
                Assert.Equal(0, pv.HintsShown);

                pv.ShowNextHint();
                Assert.Equal(1, pv.HintsShown);

                pv.ShowNextHint();
                Assert.Equal(2, pv.HintsShown);

                pv.ShowNextHint();
                Assert.Equal(2, pv.HintsShown);
            });
        }

        [Fact]
        public void RevealRequested_FiresWhenRevealButtonRaised()
        {
            RunOnSta(() =>
            {
                var pv = new PracticeView();
                var (questions, explanations) = CreateFakeData();
                pv.Load(questions, explanations);

                bool fired = false;
                pv.RevealRequested += (_, _) => fired = true;

                var btnReveal = (Button)pv.FindName("BtnReveal");
                Assert.NotNull(btnReveal);
                btnReveal.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));

                Assert.True(fired);
            });
        }
    }
}
