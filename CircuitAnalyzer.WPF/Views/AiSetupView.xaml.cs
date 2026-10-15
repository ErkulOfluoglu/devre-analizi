using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Yerel yapay zekâ (Ollama) kurulum sihirbazı.
    /// Tanıtım penceresi 5. sayfada ve AssistantView içinde yapay zekâ hazır değilken kullanılır.
    /// </summary>
    public partial class AiSetupView : UserControl
    {
        private LlmStatusDto? _lastStatus;
        private LlmPullStatusDto? _lastPull;
        private bool _isPulling;
        private bool _readyRaised;
        private CancellationTokenSource? _pollCts;

        public Func<CancellationToken, Task<LlmStatusDto?>>? StatusProvider { get; set; }
        public Func<CancellationToken, Task<bool>>? StartOllama { get; set; }
        public Func<string?, CancellationToken, Task<LlmPullStatusDto>>? StartPull { get; set; }
        public Func<CancellationToken, Task<LlmPullStatusDto?>>? GetPull { get; set; }
        public Func<CancellationToken, Task<bool>>? CancelPull { get; set; }
        public Action<string>? OpenUrl { get; set; } = url =>
        {
            try
            {
                Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            }
            catch
            {
                // Tarayıcı açılamazsa sessizce yut
            }
        };

        public event EventHandler? Ready;

        public LlmStatusDto? LastStatus => _lastStatus;
        public LlmPullStatusDto? LastPull => _lastPull;
        public bool IsPolling => _pollCts != null;

        public string Stage
        {
            get
            {
                if (_lastStatus == null)
                    return "offline";
                if (_isPulling || (_lastPull != null && _lastPull.State == LlmPullStates.Running))
                    return "downloading";
                if (_lastStatus.Available && !string.IsNullOrEmpty(_lastStatus.SelectedModel))
                    return "ready";
                if (_lastStatus.Available && string.IsNullOrEmpty(_lastStatus.SelectedModel))
                    return "nomodel";
                if (!_lastStatus.Available && _lastStatus.OllamaInstalled)
                    return "stopped";
                return "none";
            }
        }

        public AiSetupView()
        {
            InitializeComponent();
            UpdateUi();
        }

        public async Task RefreshAsync()
        {
            if (StatusProvider != null)
            {
                try
                {
                    using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(8));
                    _lastStatus = await StatusProvider(cts.Token);
                }
                catch
                {
                    _lastStatus = null;
                }
            }
            else
            {
                _lastStatus = null;
            }

            UpdateUi();

            if (Stage == "ready" && !_readyRaised)
            {
                _readyRaised = true;
                Ready?.Invoke(this, EventArgs.Empty);
            }
        }

        public void UpdateUi()
        {
            string currentStage = Stage;

            // ── Düşük bellek uyarısı ──
            bool isLowMemory = _lastStatus?.Fit == LlmFits.Low;
            BannerLowMemory.Visibility = isLowMemory ? Visibility.Visible : Visibility.Collapsed;

            // ── 1. Adım: Ollama programı ──
            if (currentStage == "none")
            {
                TxtStep1Caption.Text = "Bulunamadı. Ücretsiz; her program gibi kurulur (İleri, İleri, Bitir).";
                BtnInstallOllama.Visibility = Visibility.Visible;
                BtnStartOllama.Visibility = Visibility.Collapsed;
                TxtBadgeStep1.Visibility = Visibility.Visible;
                IconCheckStep1.Visibility = Visibility.Collapsed;
                BadgeStep1.SetResourceReference(BackgroundProperty, "Brush.Accent.Soft");
            }
            else if (currentStage == "stopped")
            {
                TxtStep1Caption.Text = "Kurulu ama kapalı.";
                BtnInstallOllama.Visibility = Visibility.Collapsed;
                BtnStartOllama.Visibility = Visibility.Visible;
                TxtBadgeStep1.Visibility = Visibility.Visible;
                IconCheckStep1.Visibility = Visibility.Collapsed;
                BadgeStep1.SetResourceReference(BackgroundProperty, "Brush.Accent.Soft");
            }
            else if (currentStage == "offline")
            {
                TxtStep1Caption.Text = "Çözücüye bağlanılamadı. Çözücü başlatılıyor olabilir.";
                BtnInstallOllama.Visibility = Visibility.Collapsed;
                BtnStartOllama.Visibility = Visibility.Collapsed;
                TxtBadgeStep1.Visibility = Visibility.Visible;
                IconCheckStep1.Visibility = Visibility.Collapsed;
                BadgeStep1.SetResourceReference(BackgroundProperty, "Brush.Bg.Subtle");
            }
            else // nomodel, downloading, ready
            {
                TxtStep1Caption.Text = "Bulundu ve çalışıyor.";
                BtnInstallOllama.Visibility = Visibility.Collapsed;
                BtnStartOllama.Visibility = Visibility.Collapsed;
                TxtBadgeStep1.Visibility = Visibility.Collapsed;
                IconCheckStep1.Visibility = Visibility.Visible;
                BadgeStep1.SetResourceReference(BackgroundProperty, "Brush.Success.Soft");
            }

            // ── 2. Adım: Model ──
            string recModel = !string.IsNullOrEmpty(_lastStatus?.RecommendedModel)
                ? _lastStatus.RecommendedModel
                : "gemma4:e2b";
            double approxGb = _lastStatus?.ApproxSizeGb ?? 5;
            TxtStep2Title.Text = $"Yapay zekâ modeli: {recModel}";

            if (!string.IsNullOrEmpty(_lastStatus?.AdviceMessage))
            {
                TxtStep2Advice.Text = _lastStatus.AdviceMessage;
            }
            else
            {
                TxtStep2Advice.Text = "Belleğinize uygun model önerilir.";
            }

            bool step1Done = currentStage is "nomodel" or "downloading" or "ready";

            if (!step1Done)
            {
                RowStep2.Opacity = 0.5;
                BadgeStep2.SetResourceReference(BackgroundProperty, "Brush.Bg.Subtle");
                TxtBadgeStep2.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Tertiary");
                TxtBadgeStep2.Visibility = Visibility.Visible;
                IconCheckStep2.Visibility = Visibility.Collapsed;
                BtnDownloadModel.Visibility = Visibility.Visible;
                BtnDownloadModel.IsEnabled = false;
                BtnDownloadModel.Content = $"Modeli indir (≈{approxGb:0} GB)";
                TxtDiskError.Visibility = Visibility.Collapsed;
                PanelDownloading.Visibility = Visibility.Collapsed;
                TxtPullMessage.Visibility = Visibility.Collapsed;
                BannerReady.Visibility = Visibility.Collapsed;
            }
            else
            {
                RowStep2.Opacity = 1.0;

                if (currentStage == "nomodel")
                {
                    BadgeStep2.SetResourceReference(BackgroundProperty, "Brush.Accent.Soft");
                    TxtBadgeStep2.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Accent.SoftText");
                    TxtBadgeStep2.Visibility = Visibility.Visible;
                    IconCheckStep2.Visibility = Visibility.Collapsed;
                    BtnDownloadModel.Visibility = Visibility.Visible;
                    PanelDownloading.Visibility = Visibility.Collapsed;
                    BannerReady.Visibility = Visibility.Collapsed;

                    string btnText = _lastPull?.State == LlmPullStates.Error
                        ? "Yeniden dene"
                        : $"Modeli indir (≈{approxGb:0} GB)";
                    BtnDownloadModel.Content = btnText;

                    // Disk kontrolü
                    if (_lastStatus?.FreeDiskGb is { } freeDisk && freeDisk < approxGb + 1)
                    {
                        BtnDownloadModel.IsEnabled = false;
                        TxtDiskError.Visibility = Visibility.Visible;
                        TxtDiskError.Text = $"Diskte yeterli yer yok (≈{approxGb + 1:0} GB gerekli)";
                    }
                    else
                    {
                        BtnDownloadModel.IsEnabled = true;
                        TxtDiskError.Visibility = Visibility.Collapsed;
                    }

                    if (_lastPull?.State is LlmPullStates.Error or LlmPullStates.Cancelled)
                    {
                        TxtPullMessage.Visibility = Visibility.Visible;
                        TxtPullMessage.Text = _lastPull.Message;
                        TxtPullMessage.SetResourceReference(TextBlock.ForegroundProperty,
                            _lastPull.State == LlmPullStates.Error ? "Brush.Error" : "Brush.Text.Secondary");
                    }
                    else
                    {
                        TxtPullMessage.Visibility = Visibility.Collapsed;
                    }
                }
                else if (currentStage == "downloading")
                {
                    BadgeStep2.SetResourceReference(BackgroundProperty, "Brush.Accent.Soft");
                    TxtBadgeStep2.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Accent.SoftText");
                    TxtBadgeStep2.Visibility = Visibility.Visible;
                    IconCheckStep2.Visibility = Visibility.Collapsed;
                    BtnDownloadModel.Visibility = Visibility.Collapsed;
                    TxtDiskError.Visibility = Visibility.Collapsed;
                    TxtPullMessage.Visibility = Visibility.Collapsed;
                    BannerReady.Visibility = Visibility.Collapsed;
                    PanelDownloading.Visibility = Visibility.Visible;

                    if (_lastPull != null)
                    {
                        double p = _lastPull.Percent ?? 0;
                        double trackW = TrackDownloadProgress.ActualWidth > 0 ? TrackDownloadProgress.ActualWidth : 200;
                        BarDownloadProgress.Width = Math.Max(0, Math.Min(trackW, (p / 100.0) * trackW));
                        TxtDownloadProgressCaption.Text = FormatProgressText(_lastPull);
                    }
                }
                else if (currentStage == "ready")
                {
                    BadgeStep2.SetResourceReference(BackgroundProperty, "Brush.Success.Soft");
                    TxtBadgeStep2.Visibility = Visibility.Collapsed;
                    IconCheckStep2.Visibility = Visibility.Visible;
                    BtnDownloadModel.Visibility = Visibility.Collapsed;
                    TxtDiskError.Visibility = Visibility.Collapsed;
                    TxtPullMessage.Visibility = Visibility.Collapsed;
                    PanelDownloading.Visibility = Visibility.Collapsed;
                    BannerReady.Visibility = Visibility.Visible;
                    TxtReadyMessage.Text = $"Hazır — {_lastStatus?.SelectedModel} kurulu.";
                }
            }

            // ── Sistem gereksinimleri hapı ──
            double ram = _lastStatus?.RamGb ?? 0;
            string fit = _lastStatus?.Fit ?? LlmFits.Unknown;

            if (fit == LlmFits.Good)
            {
                PillRam.SetResourceReference(StyleProperty, "Pill.Success");
                TxtPillRam.Text = $"Bu bilgisayar: {ram:0} GB bellek — {recModel} önerilir";
            }
            else if (fit == LlmFits.Ok)
            {
                PillRam.SetResourceReference(StyleProperty, "Pill.Warning");
                TxtPillRam.Text = $"Bu bilgisayar: {ram:0} GB bellek — {recModel} önerilir";
            }
            else if (fit == LlmFits.Low)
            {
                PillRam.SetResourceReference(StyleProperty, "Pill.Error");
                TxtPillRam.Text = $"Bu bilgisayar: {ram:0} GB bellek — yapay zekâ önerilmez";
            }
            else
            {
                PillRam.SetResourceReference(StyleProperty, "Pill.Neutral");
                TxtPillRam.Text = ram > 0 ? $"Bu bilgisayar: {ram:0} GB bellek" : "Bu bilgisayar: bellek bilinmiyor";
            }
        }

        public void BtnInstallOllama_Click(object sender, RoutedEventArgs e)
        {
            OpenUrl?.Invoke("https://ollama.com/download");
            StartPolling(TimeSpan.FromSeconds(3), 600, async () =>
            {
                await RefreshAsync();
                return Stage != "none" && Stage != "offline";
            });
        }

        public async void BtnStartOllama_Click(object sender, RoutedEventArgs e)
        {
            if (StartOllama != null)
            {
                try
                {
                    await StartOllama(CancellationToken.None);
                }
                catch
                {
                    // Başlatma hatasını RefreshAsync gösterecektir
                }
            }

            StartPolling(TimeSpan.FromSeconds(1), 20, async () =>
            {
                await RefreshAsync();
                return Stage != "stopped" && Stage != "offline";
            });
        }

        public async void BtnDownloadModel_Click(object sender, RoutedEventArgs e)
        {
            _isPulling = true;
            string? model = _lastStatus?.RecommendedModel;

            if (StartPull != null)
            {
                try
                {
                    _lastPull = await StartPull(model, CancellationToken.None);
                }
                catch (Exception ex)
                {
                    _lastPull = new LlmPullStatusDto
                    {
                        State = LlmPullStates.Error,
                        Message = ex.Message
                    };
                }
            }
            else
            {
                _lastPull = new LlmPullStatusDto
                {
                    State = LlmPullStates.Running,
                    Message = "İndirme başlatıldı."
                };
            }

            UpdateUi();

            if (_lastPull?.State == LlmPullStates.Error)
            {
                _isPulling = false;
                UpdateUi();
                return;
            }

            StartPolling(TimeSpan.FromSeconds(1), 36000, async () =>
            {
                if (GetPull != null)
                {
                    try
                    {
                        _lastPull = await GetPull(CancellationToken.None);
                    }
                    catch
                    {
                        // Geçici sorgu hatası
                    }
                }

                if (_lastPull?.State == LlmPullStates.Done)
                {
                    _isPulling = false;
                    await RefreshAsync();
                    return true;
                }

                if (_lastPull?.State is LlmPullStates.Error or LlmPullStates.Cancelled)
                {
                    _isPulling = false;
                    UpdateUi();
                    return true;
                }

                UpdateUi();
                return false;
            });
        }

        public async void BtnCancelDownload_Click(object sender, RoutedEventArgs e)
        {
            StopPolling();
            _isPulling = false;

            if (CancelPull != null)
            {
                try
                {
                    await CancelPull(CancellationToken.None);
                }
                catch
                {
                    // İptal hatası
                }
            }

            _lastPull = new LlmPullStatusDto
            {
                State = LlmPullStates.Cancelled,
                Message = "İptal edildi."
            };
            UpdateUi();
        }

        public void StartPolling(TimeSpan interval, int maxCount, Func<Task<bool>> step)
        {
            StopPolling();
            var cts = new CancellationTokenSource();
            _pollCts = cts;
            _ = PollLoopAsync(interval, maxCount, cts, step);
        }

        public void StopPolling()
        {
            if (_pollCts != null)
            {
                try
                {
                    _pollCts.Cancel();
                    _pollCts.Dispose();
                }
                catch
                {
                    // Zaten iptal edilmiş
                }
                _pollCts = null;
            }
        }

        private async Task PollLoopAsync(TimeSpan interval, int maxCount, CancellationTokenSource cts, Func<Task<bool>> step)
        {
            try
            {
                for (int i = 0; i < maxCount && !cts.IsCancellationRequested; i++)
                {
                    await Task.Delay(interval, cts.Token);
                    if (cts.IsCancellationRequested) break;
                    bool stop = await step();
                    if (stop) break;
                }
            }
            catch (OperationCanceledException)
            {
                // Beklenen iptal
            }
            finally
            {
                if (_pollCts == cts)
                {
                    _pollCts = null;
                }
            }
        }

        private void UserControl_Unloaded(object sender, RoutedEventArgs e)
        {
            StopPolling();
        }

        public static string FormatEta(double? seconds)
        {
            if (seconds == null || seconds <= 0 || double.IsNaN(seconds.Value) || double.IsInfinity(seconds.Value))
                return "";
            double s = seconds.Value;
            if (s >= 60)
            {
                int min = (int)Math.Max(1, Math.Round(s / 60.0));
                return $"{min} dk";
            }
            int sec = (int)Math.Max(1, Math.Round(s));
            return $"{sec} sn";
        }

        public static string FormatProgressText(LlmPullStatusDto pull)
        {
            var parts = new List<string>();
            if (pull.Percent is { } p)
            {
                parts.Add($"%{p:0}");
            }
            if (pull.TotalBytes > 0)
            {
                double doneGb = pull.CompletedBytes / (1024.0 * 1024 * 1024);
                double totalGb = pull.TotalBytes / (1024.0 * 1024 * 1024);
                parts.Add(string.Create(CultureInfo.InvariantCulture, $"{doneGb:0.0} / {totalGb:0.0} GB"));
            }
            if (pull.SpeedBps > 0)
            {
                double speedMb = pull.SpeedBps / (1024.0 * 1024);
                parts.Add($"{speedMb:0} MB/sn");
            }
            string eta = FormatEta(pull.EtaSeconds);
            if (!string.IsNullOrEmpty(eta))
            {
                parts.Add($"yaklaşık {eta} kaldı");
            }
            string prefix = parts.Count > 0 ? string.Join(" · ", parts) + ". " : "";
            return $"{prefix}İnerken programı kullanmaya devam edebilirsiniz.";
        }
    }
}
