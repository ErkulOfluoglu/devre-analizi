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
public class AssistantViewTests
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

    [Fact]
    public void StatusUnavailable_IsAvailableFalse_StatusTextContainsMessage_AskDoesNotCallAsker_LastErrorNotNull()
    {
        RunOnSta(() =>
        {
            var view = new AssistantView();
            view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
            {
                Available = false,
                Message = "Ollama bulunamadı. Lütfen ollama.com adresinden indirin."
            });

            bool askerCalled = false;
            view.Asker = (_, _) =>
            {
                askerCalled = true;
                return Task.FromResult(new LlmAnswerDto { Answer = "cevap" });
            };

            view.Configure(new AnalysisRequestDto { Netlist = "R1 1 0 100" }, practice: false, Array.Empty<PracticeQuestionDto>());

            RunAsync(view.RefreshStatusAsync);

            Assert.False(view.IsAvailable);
            Assert.Contains("ollama.com", view.StatusText);

            RunAsync(() => view.AskAsync("x"));

            Assert.False(askerCalled, "Yapay zekâ kullanılamaz durumdayken Asker çağrılmamalı.");
            Assert.NotNull(view.LastError);
            Assert.Contains("ollama.com", view.LastError);
        });
    }

    [Fact]
    public void StatusProviderReturnsNull_StatusTextIsCannotReachSolver()
    {
        RunOnSta(() =>
        {
            var view = new AssistantView();
            view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(null);

            RunAsync(view.RefreshStatusAsync);

            Assert.Equal("Çözücüye ulaşılamadı.", view.StatusText);
            Assert.False(view.IsAvailable);
        });
    }

    [Fact]
    public void AvailableWithModels_SelectedModelIsB()
    {
        RunOnSta(() =>
        {
            var view = new AssistantView();
            view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
            {
                Available = true,
                Models = new List<string> { "a", "b" },
                SelectedModel = "b"
            });

            RunAsync(view.RefreshStatusAsync);

            Assert.Equal("b", view.SelectedModel);
            Assert.True(view.IsAvailable);
            Assert.Equal("Hazır — b", view.StatusText);
        });
    }

    [Fact]
    public void AskAsyncTwice_SecondRequestHistoryContainsFirstTurnAndModelB_HistoryCountFour_LastNoteMatches()
    {
        RunOnSta(() =>
        {
            var view = new AssistantView();
            view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
            {
                Available = true,
                Models = new List<string> { "a", "b" },
                SelectedModel = "b"
            });

            var capturedRequests = new List<LlmAskRequestDto>();
            view.Asker = (req, _) =>
            {
                capturedRequests.Add(req);
                return Task.FromResult(new LlmAnswerDto
                {
                    Answer = $"Cevap: {req.Question}",
                    Note = "fake note",
                    Model = req.Model ?? ""
                });
            };

            view.Configure(new AnalysisRequestDto { Netlist = "R1 1 0 100" }, practice: false, Array.Empty<PracticeQuestionDto>());

            RunAsync(() => view.AskAsync("Soru 1"));
            RunAsync(() => view.AskAsync("Soru 2"));

            Assert.Equal(2, capturedRequests.Count);

            // İlk istekte history boş olmalı
            Assert.Empty(capturedRequests[0].History);

            // İkinci istekte önceki soru ve cevap sıralı olmalı
            var secondReqHistory = capturedRequests[1].History;
            Assert.Equal(2, secondReqHistory.Count);
            Assert.Equal(ChatRoles.User, secondReqHistory[0].Role);
            Assert.Equal("Soru 1", secondReqHistory[0].Content);
            Assert.Equal(ChatRoles.Assistant, secondReqHistory[1].Role);
            Assert.Equal("Cevap: Soru 1", secondReqHistory[1].Content);

            Assert.Equal("b", capturedRequests[1].Model);

            // Toplam history 4 kayıt olmalı: User, Assistant, User, Assistant
            Assert.Equal(4, view.History.Count);
            Assert.Equal(ChatRoles.User, view.History[0].Role);
            Assert.Equal("Soru 1", view.History[0].Content);
            Assert.Equal(ChatRoles.Assistant, view.History[1].Role);
            Assert.Equal("Cevap: Soru 1", view.History[1].Content);
            Assert.Equal(ChatRoles.User, view.History[2].Role);
            Assert.Equal("Soru 2", view.History[2].Content);
            Assert.Equal(ChatRoles.Assistant, view.History[3].Role);
            Assert.Equal("Cevap: Soru 2", view.History[3].Content);

            Assert.Equal("fake note", view.LastNote);
        });
    }

    [Fact]
    public void PracticeConfigure_RequestHasPracticeTrueAndSamePracticeQuestions()
    {
        RunOnSta(() =>
        {
            var view = new AssistantView();
            view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
            {
                Available = true,
                Models = new List<string> { "llama3" },
                SelectedModel = "llama3"
            });

            LlmAskRequestDto? capturedReq = null;
            view.Asker = (req, _) =>
            {
                capturedReq = req;
                return Task.FromResult(new LlmAnswerDto
                {
                    Answer = "Yol gösterici açıklama",
                    Model = "llama3"
                });
            };

            var questions = new List<PracticeQuestionDto>
            {
                new() { Id = "q1", Label = "V1", Expected = new ComplexNumberDto { Real = 5 } },
                new() { Id = "q2", Label = "I1", Expected = new ComplexNumberDto { Real = 2 } }
            };

            view.Configure(new AnalysisRequestDto { Netlist = "R1 1 0 100" }, practice: true, questions);

            Assert.True(view.IsPractice);

            RunAsync(() => view.AskAsync("Nereden başlamalıyım?"));

            Assert.NotNull(capturedReq);
            Assert.True(capturedReq!.Practice);
            Assert.Equal(2, capturedReq.PracticeQuestions.Count);
            Assert.Equal("q1", capturedReq.PracticeQuestions[0].Id);
            Assert.Equal("q2", capturedReq.PracticeQuestions[1].Id);
        });
    }

    [Fact]
    public void AskerThrowsAnalysisRequestException_LastErrorContainsOllamaYok_HistoryHasUserTurnOnly()
    {
        RunOnSta(() =>
        {
            var view = new AssistantView();
            view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
            {
                Available = true,
                Models = new List<string> { "m" },
                SelectedModel = "m"
            });

            view.Asker = (_, _) => throw new AnalysisRequestException(503, "Ollama yok");

            view.Configure(new AnalysisRequestDto { Netlist = "R1 1 0 100" }, practice: false, Array.Empty<PracticeQuestionDto>());

            RunAsync(() => view.AskAsync("Devre nasıl çalışır?"));

            Assert.NotNull(view.LastError);
            Assert.Contains("Ollama yok", view.LastError);
            Assert.Single(view.History);
            Assert.Equal(ChatRoles.User, view.History[0].Role);
            Assert.Equal("Devre nasıl çalışır?", view.History[0].Content);
        });
    }

    [Fact]
    public void EmptyQuestion_AskerNotCalled()
    {
        RunOnSta(() =>
        {
            var view = new AssistantView();
            view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
            {
                Available = true,
                Models = new List<string> { "m" },
                SelectedModel = "m"
            });

            bool called = false;
            view.Asker = (_, _) =>
            {
                called = true;
                return Task.FromResult(new LlmAnswerDto { Answer = "cevap" });
            };

            view.Configure(new AnalysisRequestDto { Netlist = "R1 1 0 100" }, practice: false, Array.Empty<PracticeQuestionDto>());

            RunAsync(() => view.AskAsync(""));
            RunAsync(() => view.AskAsync("   "));
            RunAsync(() => view.AskAsync("\t\r\n"));

            Assert.False(called, "Boş sorularda Asker çağrılmamalı.");
            Assert.Empty(view.History);
        });
    }

    [Fact]
    public void NotConfigured_LastErrorShowsSolveCircuitFirst()
    {
        RunOnSta(() =>
        {
            var view = new AssistantView();
            view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto { Available = true });
            view.Asker = (_, _) => Task.FromResult(new LlmAnswerDto());

            // Configure çağrılmadı
            RunAsync(() => view.AskAsync("Devre nasıl?"));

            Assert.Equal("Önce devreyi çözün.", view.LastError);
            Assert.Empty(view.History);
        });
    }

    [Fact]
    public void Cancel_CancelsRunningRequest_SetsLastErrorCancelled()
    {
        RunOnSta(() =>
        {
            var view = new AssistantView();
            view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
            {
                Available = true,
                Models = new List<string> { "m" },
                SelectedModel = "m"
            });

            var tcs = new TaskCompletionSource<LlmAnswerDto>();
            view.Asker = (_, ct) =>
            {
                ct.Register(() => tcs.TrySetCanceled());
                return tcs.Task;
            };

            view.Configure(new AnalysisRequestDto { Netlist = "R1 1 0 100" }, practice: false, Array.Empty<PracticeQuestionDto>());

            var askTask = view.AskAsync("Uzun soru");
            Assert.True(view.IsBusy);

            view.Cancel();

            RunAsync(() => askTask);

            Assert.False(view.IsBusy);
            Assert.Equal("İptal edildi.", view.LastError);
        });
    }
}
