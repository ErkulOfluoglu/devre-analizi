// AnalysisPanel — Sonuç gösterimi, grafik/durum kartları, hata bildirimi ve temizleme.

using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using CircuitAnalyzer.WPF.Controls;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views;

public partial class AnalysisPanel
{
    public void ShowResults(AnalysisResponseDto response)
    {
        if (CurrentAssistantView is { IsBusy: true } oldAv)
            oldAv.Cancel();

        if (CurrentRequest != null)
        {
            var assistant = new AssistantView
            {
                StatusProvider = LlmStatusProvider,
                Asker = LlmAsker,
                StartOllama = LlmStartOllama,
                EnableGpu = LlmEnableGpu,
                StartPull = LlmStartPull,
                GetPull = LlmGetPull,
                CancelPull = LlmCancelPull
            };
            bool isPractice = IsPracticeMode && response.Results?.Practice is { Count: > 0 };
            var questions = response.Results?.Practice ?? (IReadOnlyList<PracticeQuestionDto>)Array.Empty<PracticeQuestionDto>();
            assistant.Configure(CurrentRequest, practice: isPractice, questions);
            CurrentAssistantView = assistant;
        }
        else
        {
            CurrentAssistantView = null;
        }

        if (IsPracticeMode && response.Results?.Practice is { Count: > 0 })
        {
            ClearResultsContent();
            _lastPracticeResponse = response;
            IsShowingPractice = true;

            // 1. Durum Satırı
            var statusBorder = new Border
            {
                Margin = new Thickness(0, 0, 0, 12)
            };
            statusBorder.SetResourceReference(StyleProperty, "InfoBar.Info");
            var sp = new StackPanel { Orientation = Orientation.Horizontal };
            var icon = new Icon
            {
                Width = 16,
                Height = 16,
                Margin = new Thickness(0, 0, 8, 0),
                VerticalAlignment = VerticalAlignment.Center
            };
            icon.SetResourceReference(Icon.DataProperty, "Icon.School");
            var tb = new TextBlock
            {
                Text = "Alıştırma — sonuçlar gizli",
                FontWeight = FontWeights.SemiBold,
                VerticalAlignment = VerticalAlignment.Center
            };
            sp.Children.Add(icon);
            sp.Children.Add(tb);
            statusBorder.Child = sp;
            ResultsContainer.Children.Add(statusBorder);

            // 2. Mesajlar (Warnings then Errors)
            var messages = new List<string>();
            if (response.Warnings != null) messages.AddRange(response.Warnings);
            if (response.Errors != null) messages.AddRange(response.Errors);

            foreach (var msg in messages)
            {
                if (string.IsNullOrWhiteSpace(msg)) continue;
                AddMessageCard(msg);
            }

            // 3. PracticeView oluştur
            var practiceView = new PracticeView
            {
                AnswerChecker = this.AnswerChecker,
                ValueDisplay = this.ValueDisplay
            };
            practiceView.Load(response.Results.Practice, response.Results.Explanation ?? new List<ExplanationSectionDto>());
            practiceView.RevealRequested += (_, _) => RevealSolution();
            CurrentPracticeView = practiceView;

            ResultsContainer.Children.Add(practiceView);

            // Yapay zekâ asistanı soruların altında (önce öğrenci kendisi denesin)
            if (CurrentAssistantView != null)
            {
                ResultsContainer.Children.Add(CurrentAssistantView);
            }
        }
        else
        {
            ShowFullResults(response);
        }
    }

    private void ShowFullResults(AnalysisResponseDto response)
    {
        IsShowingPractice = false;
        CurrentPracticeView = null;
        ClearResultsContent();

        // 1. Durum satırı: başarıda yalnız küçük bir onay satırı, uyarıda şerit
        bool isSuccess = string.Equals(response.Status, "success", StringComparison.OrdinalIgnoreCase);
        var statusBorder = new Border
        {
            Margin = new Thickness(0, 0, 0, isSuccess ? 14 : 12)
        };
        if (isSuccess)
            statusBorder.SetResourceReference(System.Windows.Documents.TextElement.ForegroundProperty, "Brush.Success");
        else
            statusBorder.SetResourceReference(StyleProperty, "InfoBar.Warning");
        var sp = new StackPanel { Orientation = Orientation.Horizontal };
        var icon = new Icon
        {
            Width = 16,
            Height = 16,
            Margin = new Thickness(0, 0, 8, 0),
            VerticalAlignment = VerticalAlignment.Center
        };
        icon.SetResourceReference(Icon.DataProperty, isSuccess ? "Icon.Check" : "Icon.Warning");
        var tb = new TextBlock
        {
            Text = isSuccess ? "Çözüm başarılı" : "Uyarılarla çözüldü",
            FontWeight = FontWeights.SemiBold,
            FontSize = 13,
            VerticalAlignment = VerticalAlignment.Center
        };
        sp.Children.Add(icon);
        sp.Children.Add(tb);
        statusBorder.Child = sp;
        ResultsContainer.Children.Add(statusBorder);

        // 2. Mesajlar (Warnings then Errors)
        var messages = new List<string>();
        if (response.Warnings != null) messages.AddRange(response.Warnings);
        if (response.Errors != null) messages.AddRange(response.Errors);

        foreach (var msg in messages)
        {
            if (string.IsNullOrWhiteSpace(msg)) continue;
            AddMessageCard(msg);
        }

        // Zaman Grafiği (Geçici durum analizi başarılıysa)
        var transientData = response.Transient ?? response.Results?.Transient;
        if (transientData != null)
        {
            var plotCard = new Border
            {
                Padding = new Thickness(12),
                Margin = new Thickness(0, 0, 0, 12)
            };
            plotCard.SetResourceReference(StyleProperty, "Card.Embedded");

            var plotView = new TransientPlotView();
            plotView.LoadData(transientData);
            plotView.EnlargeClicked += (_, _) =>
            {
                EnlargePlotRequested?.Invoke(this, transientData);
            };

            plotCard.Child = plotView;
            ResultsContainer.Children.Add(plotCard);
        }

        // Güç Üçgeni Kartı
        var powerSummary = response.PowerSummary ?? response.Results?.PowerSummary;
        var threePhase = response.ThreePhaseResult;
        if (powerSummary != null)
        {
            var powerCard = new Border
            {
                Padding = new Thickness(12),
                Margin = new Thickness(0, 0, 0, 12)
            };
            powerCard.SetResourceReference(StyleProperty, "Card.Embedded");

            var triangleView = new PowerTriangleView();
            triangleView.LoadData(powerSummary);

            powerCard.Child = triangleView;
            ResultsContainer.Children.Add(powerCard);
        }
        else if (threePhase != null)
        {
            var powerCard = new Border
            {
                Padding = new Thickness(12),
                Margin = new Thickness(0, 0, 0, 12)
            };
            powerCard.SetResourceReference(StyleProperty, "Card.Embedded");

            var triangleView = new PowerTriangleView();
            triangleView.LoadData(threePhase);

            powerCard.Child = triangleView;
            ResultsContainer.Children.Add(powerCard);
        }

        // Rezonans Eğrisi Kartı
        var resonanceData = response.Resonance ?? response.Results?.Resonance;
        if (resonanceData != null)
        {
            var resCard = new Border
            {
                Padding = new Thickness(12),
                Margin = new Thickness(0, 0, 0, 12)
            };
            resCard.SetResourceReference(StyleProperty, "Card.Embedded");

            var resView = new ResonanceCurveView();
            resView.LoadData(resonanceData);
            resView.EnlargeClicked += (_, _) =>
            {
                EnlargeResonanceRequested?.Invoke(this, resonanceData);
            };

            resCard.Child = resView;
            ResultsContainer.Children.Add(resCard);
        }

        bool hasExplanation = response.Results?.Explanation != null && response.Results.Explanation.Count > 0;
        _resultsPanel = BuildResultsPanel(response);

        if (hasExplanation)
        {
            _explanationPanel = BuildStepChain(response.Results!.Explanation);

            if (_userSelectedExplanation.HasValue)
                IsExplanationViewSelected = _userSelectedExplanation.Value;
            else
                IsExplanationViewSelected = true;

            _viewToggleBorder = CreateSegmentedToggle();
            ResultsContainer.Children.Add(_viewToggleBorder);
            ResultsContainer.Children.Add(_resultsPanel);
            AddAssistantAtEnd();

            UpdateToggleButtonsState();
            UpdateViewVisibility();
        }
        else
        {
            IsExplanationViewSelected = false;
            ResultsContainer.Children.Add(_resultsPanel);
            _resultsPanel.Visibility = Visibility.Visible;
            AddAssistantAtEnd();
            UpdateStepNav();
        }
    }

    // Yapay zekâya sor: çözüm okunduktan sonra, en altta
    private void AddAssistantAtEnd()
    {
        if (CurrentAssistantView != null)
            ResultsContainer.Children.Add(CurrentAssistantView);
    }

    /// <summary>Son hata kartındaki eylem düğmesi (ör. "Yeniden dene"); yoksa null. Testler için.</summary>
    public Button? ErrorActionButton { get; private set; }

    /// <summary>
    /// Hata kartı gösterir. actionText ve action verilirse kartın altında ikincil bir düğme
    /// (ör. "Yeniden dene") olur; basılınca düğme kapanır ve action çalışır.
    /// </summary>
    public void ShowError(string title, string message, string? actionText, Action? action)
    {
        ShowError(title, message);
        if (actionText == null || action == null || ResultsContainer.Children.Count == 0 ||
            ResultsContainer.Children[^1] is not Border { Child: StackPanel stack })
            return;

        var button = new Button
        {
            Content = actionText,
            HorizontalAlignment = HorizontalAlignment.Left,
            MinHeight = 32,
            Margin = new Thickness(0, 10, 0, 0),
        };
        button.SetResourceReference(StyleProperty, "Button.Secondary");
        button.Click += (_, _) =>
        {
            button.IsEnabled = false;   // çift tıklama iki kez başlatmasın
            action();
        };
        stack.Children.Add(button);
        ErrorActionButton = button;
    }

    public void ShowError(string title, string message)
    {
        ErrorActionButton = null;
        if (CurrentAssistantView is { IsBusy: true } av)
            av.Cancel();
        CurrentAssistantView = null;
        ClearResultsContent();

        var card = new Border
        {
            Margin = new Thickness(0, 4, 0, 4)
        };
        card.SetResourceReference(StyleProperty, "InfoBar.Error");

        var stack = new StackPanel();
        var txtTitle = new TextBlock
        {
            Text = title,
            FontWeight = FontWeights.SemiBold,
            FontSize = 14,
            Margin = new Thickness(0, 0, 0, 4)
        };
        stack.Children.Add(txtTitle);

        var txtMsg = new TextBlock
        {
            Text = message,
            TextWrapping = TextWrapping.Wrap,
            FontSize = 13
        };
        stack.Children.Add(txtMsg);

        card.Child = stack;
        ResultsContainer.Children.Add(card);
    }

    public void MarkStale()
    {
        BannerStale.Visibility = Visibility.Visible;
        ResultsScrollViewer.Opacity = 0.45;
    }

    public void ClearResults()
    {
        _lastPracticeResponse = null;
        if (CurrentAssistantView is { IsBusy: true } av)
            av.Cancel();
        CurrentAssistantView = null;
        ClearResultsContent();
    }

    private void ClearResultsContent()
    {
        ErrorActionButton = null;
        BannerStale.Visibility = Visibility.Collapsed;
        ResultsScrollViewer.Opacity = 1.0;
        ResultsContainer.Children.Clear();
        StepNavBar.Visibility = Visibility.Collapsed;
        ResultsScrollViewer.ScrollToVerticalOffset(0);
        _steps.Clear();
        _openStep = -1;
        _allStepsOpen = false;
        _explanationPanel = null;
        _resultsPanel = null;
        _viewToggleBorder = null;
        _btnViewExplanation = null;
        _btnViewResults = null;
        CurrentPracticeView = null;
        IsShowingPractice = false;
    }

    private void AddMessageCard(string msg)
    {
        string styleKey;
        string iconKey;
        string cleanMsg = msg;

        if (msg.StartsWith("⚠"))
        {
            styleKey = "InfoBar.Warning";
            iconKey = "Icon.Warning";
            cleanMsg = msg.TrimStart('⚠', ' ');
        }
        else if (msg.StartsWith("ℹ"))
        {
            styleKey = "InfoBar.Info";
            iconKey = "Icon.Info";
            cleanMsg = msg.TrimStart('ℹ', ' ');
        }
        else
        {
            styleKey = "InfoBar.Error";
            iconKey = "Icon.Warning";
            cleanMsg = msg.TrimStart('✗', '❌', ' ');
        }

        var border = new Border
        {
            Margin = new Thickness(0, 0, 0, 10)
        };
        border.SetResourceReference(StyleProperty, styleKey);

        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        var icon = new Icon
        {
            Width = 16,
            Height = 16,
            Margin = new Thickness(0, 2, 8, 0),
            VerticalAlignment = VerticalAlignment.Top
        };
        icon.SetResourceReference(Icon.DataProperty, iconKey);
        Grid.SetColumn(icon, 0);
        grid.Children.Add(icon);

        var tb = new TextBlock
        {
            Text = cleanMsg,
            TextWrapping = TextWrapping.Wrap,
            VerticalAlignment = VerticalAlignment.Center
        };
        Grid.SetColumn(tb, 1);
        grid.Children.Add(tb);

        border.Child = grid;
        ResultsContainer.Children.Add(border);
    }
}
