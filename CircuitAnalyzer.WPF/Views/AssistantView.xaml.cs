using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using CircuitAnalyzer.WPF.Controls;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views;

/// <summary>
/// Yerel yapay zekâ (Ollama) ile soru-cevap arayüzü.
/// Çözülen devre hakkında soru sorma ve alıştırma modunda rehberlik sunar.
/// </summary>
public partial class AssistantView : UserControl
{
    private AnalysisRequestDto? _analysisRequest;
    private IReadOnlyList<PracticeQuestionDto> _practiceQuestions = Array.Empty<PracticeQuestionDto>();
    private readonly List<ChatTurnDto> _history = new();
    private LlmStatusDto? _lastStatus;
    private bool _statusFetched;
    private CancellationTokenSource? _cts;
    private string _statusText = "Yapay zekâ aranıyor…";

    public Func<CancellationToken, Task<LlmStatusDto?>>? StatusProvider { get; set; }
    public Func<LlmAskRequestDto, CancellationToken, Task<LlmAnswerDto>>? Asker { get; set; }
    public Func<CancellationToken, Task<bool>>? StartOllama { get; set; }
    public Func<string?, CancellationToken, Task<LlmPullStatusDto>>? StartPull { get; set; }
    public Func<CancellationToken, Task<LlmPullStatusDto?>>? GetPull { get; set; }
    public Func<CancellationToken, Task<bool>>? CancelPull { get; set; }

    public bool IsPractice { get; private set; }

    public bool IsAvailable => (_lastStatus?.Available == true) && !string.IsNullOrEmpty(SelectedModel);

    public bool IsBusy { get; private set; }

    public string StatusText => _statusText;

    public string? SelectedModel => CmbModel?.SelectedItem as string ?? _lastStatus?.SelectedModel;

    public IReadOnlyList<ChatTurnDto> History => _history;

    public string? LastNote { get; private set; }

    public string? LastError { get; private set; }

    public bool IsExpanded
    {
        get => AssistantExpander?.IsExpanded == true;
        set
        {
            if (AssistantExpander != null)
                AssistantExpander.IsExpanded = value;
        }
    }

    public AssistantView()
    {
        InitializeComponent();
        UpdateSuggestions();
        if (SetupWizard != null)
        {
            SetupWizard.Ready += async (_, _) => await RefreshStatusAsync();
        }
    }

    /// <summary>
    /// Devre isteğini ve alıştırma parametrelerini ayarlar.
    /// Önceki sohbet geçmişini korur.
    /// </summary>
    public void Configure(AnalysisRequestDto analysisRequest, bool practice, IReadOnlyList<PracticeQuestionDto> practiceQuestions)
    {
        _analysisRequest = analysisRequest;
        IsPractice = practice;
        _practiceQuestions = practiceQuestions ?? Array.Empty<PracticeQuestionDto>();

        if (PracticeNotice != null)
        {
            PracticeNotice.Visibility = practice ? Visibility.Visible : Visibility.Collapsed;
        }
        UpdateSuggestions();
    }

    /// <summary>
    /// Yapay zekâ durumunu sorgular ve arayüzü günceller.
    /// </summary>
    public async Task RefreshStatusAsync()
    {
        _statusText = "Yapay zekâ aranıyor…";
        if (TxtStatusLine != null)
        {
            TxtStatusLine.Text = _statusText;
            TxtStatusLine.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
        }
        if (BtnRetry != null) BtnRetry.Visibility = Visibility.Collapsed;
        if (RowModel != null) RowModel.Visibility = Visibility.Collapsed;
        if (SuggestionsContainer != null) SuggestionsContainer.Visibility = Visibility.Collapsed;
        if (RowInput != null) RowInput.Visibility = Visibility.Collapsed;

        if (StatusProvider == null)
        {
            _lastStatus = null;
            _statusText = "Çözücüye ulaşılamadı.";
            _statusFetched = true;
            UpdateStatusUi();
            return;
        }

        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            var status = await StatusProvider(cts.Token);
            _lastStatus = status;

            if (status == null)
            {
                _statusText = "Çözücüye ulaşılamadı.";
            }
            else if (status.Available && !string.IsNullOrEmpty(status.SelectedModel))
            {
                if (CmbModel != null)
                {
                    CmbModel.ItemsSource = status.Models;
                    if (status.Models.Contains(status.SelectedModel))
                    {
                        CmbModel.SelectedItem = status.SelectedModel;
                    }
                    else
                    {
                        var list = new List<string>(status.Models) { status.SelectedModel };
                        CmbModel.ItemsSource = list;
                        CmbModel.SelectedItem = status.SelectedModel;
                    }
                }
                _statusText = $"Hazır — {SelectedModel}";
            }
            else
            {
                _statusText = status.Message;
            }
        }
        catch (Exception)
        {
            _lastStatus = null;
            _statusText = "Çözücüye ulaşılamadı.";
        }

        _statusFetched = true;
        UpdateStatusUi();
    }

    private void UpdateStatusUi()
    {
        if (SetupWizard != null)
        {
            SetupWizard.StatusProvider = StatusProvider;
            SetupWizard.StartOllama = StartOllama;
            SetupWizard.StartPull = StartPull;
            SetupWizard.GetPull = GetPull;
            SetupWizard.CancelPull = CancelPull;

            if (!IsAvailable)
            {
                SetupWizard.Visibility = Visibility.Visible;
                _ = SetupWizard.RefreshAsync();
            }
            else
            {
                SetupWizard.Visibility = Visibility.Collapsed;
            }
        }

        if (TxtStatusLine != null)
        {
            TxtStatusLine.Text = _statusText;
            bool isAvail = IsAvailable;
            TxtStatusLine.SetResourceReference(TextBlock.ForegroundProperty, isAvail ? "Brush.Success" : "Brush.Text.Secondary");
            TxtStatusLine.Visibility = isAvail ? Visibility.Visible : Visibility.Collapsed;
        }

        if (BtnRetry != null)
        {
            BtnRetry.Visibility = Visibility.Collapsed;
        }

        if (RowModel != null)
        {
            RowModel.Visibility = IsAvailable ? Visibility.Visible : Visibility.Collapsed;
        }

        var askVisibility = IsAvailable ? Visibility.Visible : Visibility.Collapsed;
        if (SuggestionsContainer != null) SuggestionsContainer.Visibility = askVisibility;
        if (RowInput != null) RowInput.Visibility = askVisibility;
    }

    /// <summary>
    /// Yapay zekâya soru sorar (kutudan yazıp Gönder'e basmakla aynı).
    /// </summary>
    public async Task AskAsync(string question)
    {
        if (string.IsNullOrWhiteSpace(question))
            return;

        if (IsBusy)
            return;

        if (_analysisRequest == null || Asker == null)
        {
            LastError = "Önce devreyi çözün.";
            ShowError(LastError);
            return;
        }

        if (!_statusFetched)
        {
            await RefreshStatusAsync();
        }

        if (!IsAvailable)
        {
            LastError = StatusText;
            ShowError(LastError);
            return;
        }

        LastError = null;
        HideError();

        var req = LlmAskRequestDto.From(_analysisRequest, question);
        req.Model = SelectedModel;
        req.History = new List<ChatTurnDto>(_history);
        req.Practice = IsPractice;
        req.PracticeQuestions = new List<PracticeQuestionDto>(_practiceQuestions);

        var userTurn = new ChatTurnDto { Role = ChatRoles.User, Content = question };
        _history.Add(userTurn);
        AddUserBubble(question);

        IsBusy = true;
        UpdateBusyState();
        _cts = new CancellationTokenSource();

        try
        {
            var answer = await Asker(req, _cts.Token);
            LastNote = answer.Note;
            var assistantTurn = new ChatTurnDto { Role = ChatRoles.Assistant, Content = answer.Answer };
            _history.Add(assistantTurn);
            AddAssistantBubble(answer);
        }
        catch (OperationCanceledException)
        {
            LastError = "İptal edildi.";
            ShowError(LastError);
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
            ShowError(LastError);
        }
        finally
        {
            IsBusy = false;
            _cts?.Dispose();
            _cts = null;
            UpdateBusyState();
        }
    }

    /// <summary>
    /// Devam eden yapay zekâ sorgusunu iptal eder.
    /// </summary>
    public void Cancel()
    {
        _cts?.Cancel();
    }

    private void AddUserBubble(string text)
    {
        if (ChatContainer == null) return;

        var border = new Border
        {
            CornerRadius = new CornerRadius(14, 14, 4, 14),
            Padding = new Thickness(12, 8, 12, 8),
            Margin = new Thickness(36, 4, 0, 4),
            HorizontalAlignment = HorizontalAlignment.Right
        };
        border.SetResourceReference(Border.BackgroundProperty, "Brush.Accent");
        if (ChatScrollViewer != null && ChatScrollViewer.ActualWidth > 50)
            border.MaxWidth = ChatScrollViewer.ActualWidth * 0.85;

        var tb = new TextBlock
        {
            Text = text,
            FontSize = 13,
            TextWrapping = TextWrapping.Wrap
        };
        tb.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.OnAccent");
        border.Child = tb;
        ChatContainer.Children.Add(border);
        ChatScrollViewer?.ScrollToEnd();
    }

    private void AddAssistantBubble(LlmAnswerDto answer)
    {
        if (ChatContainer == null) return;

        var wrapper = new StackPanel
        {
            HorizontalAlignment = HorizontalAlignment.Left,
            Margin = new Thickness(0, 4, 36, 4)
        };
        if (ChatScrollViewer != null && ChatScrollViewer.ActualWidth > 50)
            wrapper.MaxWidth = ChatScrollViewer.ActualWidth * 0.85;

        var border = new Border
        {
            CornerRadius = new CornerRadius(14, 14, 14, 4),
            Padding = new Thickness(12, 8, 12, 8)
        };
        border.SetResourceReference(Border.BackgroundProperty, "Brush.Bg.SurfaceAlt");

        var tb = new TextBlock
        {
            Text = answer.Answer,
            FontSize = 13,
            TextWrapping = TextWrapping.Wrap
        };
        tb.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
        border.Child = tb;
        wrapper.Children.Add(border);

        // Not uyarısı (InfoBar.Warning, FontSize 12)
        if (!string.IsNullOrWhiteSpace(answer.Note))
        {
            var noteBorder = new Border
            {
                Margin = new Thickness(0, 4, 0, 2)
            };
            noteBorder.SetResourceReference(StyleProperty, "InfoBar.Warning");
            var tbNote = new TextBlock
            {
                Text = answer.Note,
                FontSize = 12,
                TextWrapping = TextWrapping.Wrap
            };
            noteBorder.Child = tbNote;
            wrapper.Children.Add(noteBorder);
        }

        // Sayı doğrulama rozeti (tüm sayılar doğrulanmışsa yeşil onay: Brush.Success 12px with Icon.Check 14px)
        if (answer.Numbers != null && answer.Numbers.Count > 0 &&
            answer.Numbers.All(n => string.Equals(n.Status, LlmNumberStatuses.Verified, StringComparison.OrdinalIgnoreCase)))
        {
            var spVerified = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Margin = new Thickness(2, 4, 0, 0)
            };
            var iconVerified = new Icon
            {
                Width = 14,
                Height = 14,
                Margin = new Thickness(0, 0, 6, 0),
                VerticalAlignment = VerticalAlignment.Center
            };
            iconVerified.SetResourceReference(Icon.DataProperty, "Icon.Check");
            iconVerified.SetResourceReference(Icon.ForegroundProperty, "Brush.Success");
            spVerified.Children.Add(iconVerified);

            var tbVerified = new TextBlock
            {
                Text = "Sayılar çözümle doğrulandı",
                FontSize = 12,
                VerticalAlignment = VerticalAlignment.Center
            };
            tbVerified.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Success");
            spVerified.Children.Add(tbVerified);
            wrapper.Children.Add(spVerified);
        }

        ChatContainer.Children.Add(wrapper);
        ChatScrollViewer?.ScrollToEnd();
    }

    private void ShowError(string error)
    {
        if (TxtError != null)
        {
            TxtError.Text = error;
            TxtError.Visibility = Visibility.Visible;
        }
    }

    private void HideError()
    {
        if (TxtError != null)
        {
            TxtError.Text = "";
            TxtError.Visibility = Visibility.Collapsed;
        }
    }

    private void UpdateBusyState()
    {
        if (RowBusy != null)
            RowBusy.Visibility = IsBusy ? Visibility.Visible : Visibility.Collapsed;

        if (BtnSend != null)
            BtnSend.IsEnabled = !IsBusy;

        if (TxtQuestion != null)
            TxtQuestion.IsEnabled = !IsBusy;

        if (BtnRetry != null)
            BtnRetry.IsEnabled = !IsBusy;

        if (CmbModel != null)
            CmbModel.IsEnabled = !IsBusy;

        if (SuggestionsContainer != null)
            SuggestionsContainer.IsEnabled = !IsBusy;
    }

    private void UpdateSuggestions()
    {
        if (SuggestionsContainer == null) return;
        SuggestionsContainer.Children.Clear();

        string[] suggestions = IsPractice
            ? new[] { "Nereden başlamalıyım?", "Hangi denklemi kurmalıyım?" }
            : new[] { "Bu çözümü kısaca anlat", "Neden bu yöntemi kullandık?", "Eksi çıkan akım ne demek?" };

        foreach (var text in suggestions)
        {
            var btn = new Button
            {
                Content = text,
                Height = 32,
                FontSize = 13,
                Padding = new Thickness(10, 0, 10, 0),
                Margin = new Thickness(0, 0, 6, 6)
            };
            btn.SetResourceReference(StyleProperty, "Button.Secondary");
            btn.Click += async (_, _) =>
            {
                if (!IsBusy)
                {
                    await AskAsync(text);
                }
            };
            SuggestionsContainer.Children.Add(btn);
        }
    }

    private async void AssistantExpander_Expanded(object sender, RoutedEventArgs e)
    {
        if (!_statusFetched)
        {
            await RefreshStatusAsync();
        }
    }

    private async void BtnRetry_Click(object sender, RoutedEventArgs e)
    {
        await RefreshStatusAsync();
    }

    private void CmbModel_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_lastStatus?.Available == true)
        {
            _statusText = $"Hazır — {SelectedModel}";
            if (TxtStatusLine != null)
            {
                TxtStatusLine.Text = _statusText;
            }
        }
    }

    private void BtnCancel_Click(object sender, RoutedEventArgs e)
    {
        Cancel();
    }

    private void TxtQuestion_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            if ((Keyboard.Modifiers & ModifierKeys.Shift) == 0)
            {
                e.Handled = true;
                string q = TxtQuestion.Text;
                TxtQuestion.Text = "";
                _ = AskAsync(q);
            }
        }
    }

    private void BtnSend_Click(object sender, RoutedEventArgs e)
    {
        string q = TxtQuestion.Text;
        TxtQuestion.Text = "";
        _ = AskAsync(q);
    }
}
