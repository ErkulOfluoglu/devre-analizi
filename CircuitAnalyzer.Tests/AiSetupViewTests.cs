using System;
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
    public class AiSetupViewTests
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
        public void Stage_Offline_WhenStatusNull()
        {
            RunOnSta(() =>
            {
                var view = new AiSetupView();
                view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(null);

                RunAsync(view.RefreshAsync);

                Assert.Equal("offline", view.Stage);
            });
        }

        [Fact]
        public void Stage_None_WhenNotAvailableAndOllamaNotInstalled()
        {
            RunOnSta(() =>
            {
                var view = new AiSetupView();
                view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
                {
                    Available = false,
                    OllamaInstalled = false
                });

                RunAsync(view.RefreshAsync);

                Assert.Equal("none", view.Stage);
                Assert.Equal(Visibility.Visible, view.BtnInstallOllama.Visibility);
                Assert.Equal(Visibility.Collapsed, view.BtnStartOllama.Visibility);
            });
        }

        [Fact]
        public void Stage_Stopped_WhenNotAvailableAndOllamaInstalled()
        {
            RunOnSta(() =>
            {
                var view = new AiSetupView();
                view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
                {
                    Available = false,
                    OllamaInstalled = true
                });

                RunAsync(view.RefreshAsync);

                Assert.Equal("stopped", view.Stage);
                Assert.Equal(Visibility.Collapsed, view.BtnInstallOllama.Visibility);
                Assert.Equal(Visibility.Visible, view.BtnStartOllama.Visibility);
            });
        }

        [Fact]
        public void Stage_NoModel_WhenAvailableAndNoSelectedModel()
        {
            RunOnSta(() =>
            {
                var view = new AiSetupView();
                view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
                {
                    Available = true,
                    SelectedModel = null,
                    RecommendedModel = "gemma4:e2b",
                    ApproxSizeGb = 5.0
                });

                RunAsync(view.RefreshAsync);

                Assert.Equal("nomodel", view.Stage);
                Assert.Equal(Visibility.Visible, view.BtnDownloadModel.Visibility);
            });
        }

        [Fact]
        public void Stage_Ready_WhenAvailableAndSelectedModelNotNull()
        {
            RunOnSta(() =>
            {
                var view = new AiSetupView();
                view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
                {
                    Available = true,
                    SelectedModel = "gemma4:e2b"
                });

                RunAsync(view.RefreshAsync);

                Assert.Equal("ready", view.Stage);
                Assert.Equal(Visibility.Visible, view.BannerReady.Visibility);
                Assert.Contains("gemma4:e2b", view.TxtReadyMessage.Text);
            });
        }

        [Fact]
        public void LowMemory_ShowsWarningAndErrorPill()
        {
            RunOnSta(() =>
            {
                var view = new AiSetupView();
                view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
                {
                    Available = false,
                    OllamaInstalled = false,
                    Fit = LlmFits.Low,
                    RamGb = 4.0
                });

                RunAsync(view.RefreshAsync);

                Assert.Equal(Visibility.Visible, view.BannerLowMemory.Visibility);
                Assert.Contains("yapay zekâ önerilmez", view.TxtPillRam.Text);
            });
        }

        [Fact]
        public void InstallOllama_CallsOpenUrl_WithDownloadUrl()
        {
            RunOnSta(() =>
            {
                var view = new AiSetupView();
                string? openedUrl = null;
                view.OpenUrl = url => openedUrl = url;

                view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
                {
                    Available = false,
                    OllamaInstalled = false
                });

                RunAsync(view.RefreshAsync);
                view.BtnInstallOllama.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));

                Assert.Equal("https://ollama.com/download", openedUrl);
                Assert.True(view.IsPolling);
                view.StopPolling();
            });
        }

        [Fact]
        public void StartOllama_CallsStartOllamaDelegate()
        {
            RunOnSta(() =>
            {
                var view = new AiSetupView();
                bool startCalled = false;
                view.StartOllama = _ =>
                {
                    startCalled = true;
                    return Task.FromResult(true);
                };

                view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
                {
                    Available = false,
                    OllamaInstalled = true
                });

                RunAsync(view.RefreshAsync);
                view.BtnStartOllama.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));

                Assert.True(startCalled);
                Assert.True(view.IsPolling);
                view.StopPolling();
            });
        }

        [Fact]
        public void DownloadModel_CallsStartPull_WithRecommendedModel()
        {
            RunOnSta(() =>
            {
                var view = new AiSetupView();
                string? pulledModel = null;
                view.StartPull = (model, _) =>
                {
                    pulledModel = model;
                    return Task.FromResult(new LlmPullStatusDto
                    {
                        State = LlmPullStates.Running,
                        Model = model,
                        Percent = 10
                    });
                };

                view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
                {
                    Available = true,
                    SelectedModel = null,
                    RecommendedModel = "gemma4:e2b",
                    ApproxSizeGb = 5.0
                });

                RunAsync(view.RefreshAsync);
                view.BtnDownloadModel.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));

                Assert.Equal("gemma4:e2b", pulledModel);
                Assert.Equal("downloading", view.Stage);
                Assert.Equal(Visibility.Visible, view.PanelDownloading.Visibility);
                view.StopPolling();
            });
        }

        [Fact]
        public void ProgressText_Formatting_PercentGbSpeedEta()
        {
            // ETA format kontrolü: 240 saniye -> 4 dk, 40 saniye -> 40 sn
            Assert.Equal("4 dk", AiSetupView.FormatEta(240));
            Assert.Equal("40 sn", AiSetupView.FormatEta(40));

            var pull = new LlmPullStatusDto
            {
                Percent = 50,
                CompletedBytes = (long)(2.5 * 1024 * 1024 * 1024),
                TotalBytes = (long)(5.0 * 1024 * 1024 * 1024),
                SpeedBps = 20.0 * 1024 * 1024,
                EtaSeconds = 240
            };

            string text = AiSetupView.FormatProgressText(pull);

            Assert.Contains("%50", text);
            Assert.Contains("2,5 / 5,0 GB", text);
            Assert.Contains("20 MB/sn", text);
            Assert.Contains("yaklaşık 4 dk kaldı", text);
            Assert.Contains("İnerken programı kullanmaya devam edebilirsiniz", text);
        }

        [Fact]
        public void CancelPull_CallsCancelPullDelegate()
        {
            RunOnSta(() =>
            {
                var view = new AiSetupView();
                bool cancelCalled = false;
                view.CancelPull = _ =>
                {
                    cancelCalled = true;
                    return Task.FromResult(true);
                };

                view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
                {
                    Available = true,
                    SelectedModel = null,
                    RecommendedModel = "gemma4:e2b"
                });

                RunAsync(view.RefreshAsync);

                view.BtnCancelDownload.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));

                Assert.True(cancelCalled);
                Assert.False(view.IsPolling);
                Assert.Equal("İptal edildi.", view.LastPull?.Message);
            });
        }

        [Fact]
        public void Ready_RaisedOnce_WhenAiBecomesReady()
        {
            RunOnSta(() =>
            {
                var view = new AiSetupView();
                int readyCount = 0;
                view.Ready += (_, _) => readyCount++;

                // İlk durum: nomodel
                view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
                {
                    Available = true,
                    SelectedModel = null
                });
                RunAsync(view.RefreshAsync);
                Assert.Equal(0, readyCount);

                // İkinci durum: ready
                view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
                {
                    Available = true,
                    SelectedModel = "gemma4:e2b"
                });
                RunAsync(view.RefreshAsync);
                Assert.Equal(1, readyCount);

                // Tekrar refresh çağrıldığında Ready ikinci kez tetiklenmemeli
                RunAsync(view.RefreshAsync);
                Assert.Equal(1, readyCount);
            });
        }

        [Fact]
        public void InsufficientDisk_DisablesDownloadButton_AndShowsError()
        {
            RunOnSta(() =>
            {
                var view = new AiSetupView();
                view.StatusProvider = _ => Task.FromResult<LlmStatusDto?>(new LlmStatusDto
                {
                    Available = true,
                    SelectedModel = null,
                    RecommendedModel = "gemma4:e2b",
                    ApproxSizeGb = 5.0,
                    FreeDiskGb = 4.0 // 5 + 1 = 6 GB gerekli, 4 GB var -> yetersiz
                });

                RunAsync(view.RefreshAsync);

                Assert.False(view.BtnDownloadModel.IsEnabled);
                Assert.Equal(Visibility.Visible, view.TxtDiskError.Visibility);
                Assert.Contains("Diskte yeterli yer yok", view.TxtDiskError.Text);
            });
        }
    }
}
