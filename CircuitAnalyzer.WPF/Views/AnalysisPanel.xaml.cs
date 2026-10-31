using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using CircuitAnalyzer.WPF.Controls;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views;

public partial class AnalysisPanel : UserControl
{
    public event EventHandler? SolveRequested;
    public event EventHandler? ValueDisplayChanged;
    public event EventHandler<TransientAnalysisDto>? EnlargePlotRequested;
    public event EventHandler<ResonanceDto>? EnlargeResonanceRequested;

    private BackendState _backendState = BackendState.Starting;
    private bool _isBusy;
    private bool _hasAcSource;
    private bool _needsFrequency;
    private bool? _userSelectedExplanation;
    private Border? _viewToggleBorder;
    private ToggleButton? _btnViewExplanation;
    private ToggleButton? _btnViewResults;
    private StackPanel? _explanationPanel;
    private StackPanel? _resultsPanel;

    public bool IsPracticeMode
    {
        get => ChkPracticeMode.IsChecked == true;
        set => ChkPracticeMode.IsChecked = value;
    }

    public void SetProblemCode(int? code)
    {
        if (code is { } c)
        {
            TxtProblemCode.Text = $"Soru #{c}";
            TxtProblemCode.Visibility = Visibility.Visible;
            TxtProblemCodeBig.Text = $"Soru kodu: {c}";
            CardProblemCode.Visibility = Visibility.Visible;
            if (TxtCopyProblemCode != null)
                TxtCopyProblemCode.Text = "Kopyala";
            if (IconCopyProblemCode != null)
                IconCopyProblemCode.SetResourceReference(Icon.DataProperty, "Icon.Copy");
        }
        else
        {
            TxtProblemCode.Text = "";
            TxtProblemCode.Visibility = Visibility.Collapsed;
            CardProblemCode.Visibility = Visibility.Collapsed;
        }
        _problemCode = code;
    }

    private int? _problemCode;

    private void BtnCopyProblemCode_Click(object sender, RoutedEventArgs e)
    {
        if (_problemCode is not { } c)
            return;
        try
        {
            Clipboard.SetText(c.ToString(CultureInfo.InvariantCulture));
            if (TxtCopyProblemCode != null)
                TxtCopyProblemCode.Text = "Kopyalandı";
            if (IconCopyProblemCode != null)
                IconCopyProblemCode.SetResourceReference(Icon.DataProperty, "Icon.Check");
        }
        catch (System.Runtime.InteropServices.COMException)
        {
            // Pano başka bir program tarafından kilitliyse sessizce geç
        }
    }

    public string? ProblemCodeText => TxtProblemCode.Visibility == Visibility.Visible ? TxtProblemCode.Text : null;

    public Func<AnswerCheckRequestDto, Task<AnswerCheckResponseDto>>? AnswerChecker { get; set; }

    public Func<CancellationToken, Task<LlmStatusDto?>>? LlmStatusProvider { get; set; }
    public Func<LlmAskRequestDto, CancellationToken, Task<LlmAnswerDto>>? LlmAsker { get; set; }
    public Func<CancellationToken, Task<bool>>? LlmStartOllama { get; set; }
    public Func<string?, CancellationToken, Task<LlmPullStatusDto>>? LlmStartPull { get; set; }
    public Func<CancellationToken, Task<LlmPullStatusDto?>>? LlmGetPull { get; set; }
    public Func<CancellationToken, Task<bool>>? LlmCancelPull { get; set; }
    public FrameworkElement ResultsCard => (FrameworkElement)ResultsScrollViewer.Parent;
    public AnalysisRequestDto? CurrentRequest { get; set; }
    public AssistantView? CurrentAssistantView { get; private set; }

    public event EventHandler? SolutionRevealed;

    public bool IsShowingPractice { get; private set; }

    public PracticeView? CurrentPracticeView { get; private set; }

    private AnalysisResponseDto? _lastPracticeResponse;

    public void RevealSolution()
    {
        if (_lastPracticeResponse != null)
        {
            var resp = _lastPracticeResponse;
            _lastPracticeResponse = null;
            if (CurrentAssistantView != null && CurrentRequest != null)
            {
                CurrentAssistantView.Configure(CurrentRequest, practice: false, Array.Empty<PracticeQuestionDto>());
            }
            ShowFullResults(resp);
            SelectExplanationView(true);
            SolutionRevealed?.Invoke(this, EventArgs.Empty);
        }
    }

    public bool IsExplanationViewSelected { get; private set; }

    public void SelectExplanationView(bool explanation)
    {
        _userSelectedExplanation = explanation;
        IsExplanationViewSelected = explanation;

        UpdateToggleButtonsState();
        UpdateViewVisibility();
    }

    public AnalysisPanel()
    {
        InitializeComponent();

        SetValueDisplay(AppSettings.AcValueDisplay, notify: false);
        SetBackendStatus(BackendState.Starting, "Çözücü başlatılıyor…");
        SetCircuitInfo(hasAcSource: false, needsFrequency: false);
    }

    public void RequestSolve()
    {
        if (_backendState != BackendState.Ready || _isBusy)
            return;

        SolveRequested?.Invoke(this, EventArgs.Empty);
    }

    private void BtnSolve_Click(object sender, RoutedEventArgs e)
    {
        RequestSolve();
    }

    public void SetBackendStatus(BackendState state, string message)
    {
        _backendState = state;
        PillBackendStatus.ToolTip = message;

        switch (state)
        {
            case BackendState.Starting:
                PillBackendStatus.SetResourceReference(StyleProperty, "Pill.Neutral");
                TxtBackendStatus.Text = "Çözücü başlatılıyor…";
                break;
            case BackendState.Ready:
                PillBackendStatus.SetResourceReference(StyleProperty, "Pill.Success");
                TxtBackendStatus.Text = "Hazır";
                break;
            case BackendState.Failed:
                PillBackendStatus.SetResourceReference(StyleProperty, "Pill.Error");
                TxtBackendStatus.Text = "Başarısız";
                break;
        }

        UpdateSolveButtonState();
    }

    public void SetBusy(bool busy)
    {
        _isBusy = busy;
        if (TxtSolve != null)
        {
            TxtSolve.Text = busy ? "Çözülüyor…" : "Çöz";
        }
        if (TxtSolveKey != null)
        {
            TxtSolveKey.Visibility = busy ? Visibility.Collapsed : Visibility.Visible;
        }
        if (IconSolve != null)
        {
            IconSolve.SetResourceReference(Icon.DataProperty, busy ? "Icon.Pulse" : "Icon.Play");
        }
        UpdateSolveButtonState();
    }

    private void UpdateSolveButtonState()
    {
        BtnSolve.IsEnabled = (_backendState == BackendState.Ready) && !_isBusy;
    }

    public void SetCircuitInfo(bool hasAcSource, bool needsFrequency)
    {
        _hasAcSource = hasAcSource;
        _needsFrequency = needsFrequency;

        TxtModeLabel.Text = hasAcSource ? "AC (fazör) analiz" : "DC analiz";
        RowFrequency.Visibility = hasAcSource ? Visibility.Visible : Visibility.Collapsed;
        RowValueDisplay.Visibility = hasAcSource ? Visibility.Visible : Visibility.Collapsed;
        TxtFrequencyLabel.Text = needsFrequency
            ? "Frekans (Hz) — gerekli"
            : "Frekans (Hz) — boş bırakılırsa kaynaktan alınır";
    }

    public void SetAvailableNodes(IReadOnlyList<int> nodes)
    {
        string? prevPos = GetSelectedTerminal(CmbTerminalPositive);
        string? prevNeg = GetSelectedTerminal(CmbTerminalNegative);

        var nodeStrings = nodes.OrderBy(n => n).Select(n => n.ToString()).ToList();

        CmbTerminalPositive.ItemsSource = nodeStrings;
        CmbTerminalNegative.ItemsSource = nodeStrings.ToList();

        if (prevPos != null && nodeStrings.Contains(prevPos))
        {
            CmbTerminalPositive.SelectedItem = prevPos;
        }
        else
        {
            CmbTerminalPositive.SelectedItem = null;
        }

        if (prevNeg != null && nodeStrings.Contains(prevNeg))
        {
            CmbTerminalNegative.SelectedItem = prevNeg;
        }
        else if (nodeStrings.Contains("0"))
        {
            CmbTerminalNegative.SelectedItem = "0";
        }
        else
        {
            CmbTerminalNegative.SelectedItem = null;
        }
    }

    public void SetAnalysisType(string analysisType, string? terminalPositive = null)
    {
        if (string.Equals(analysisType, AnalysisTypes.Thevenin, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 1;
        }
        else if (string.Equals(analysisType, AnalysisTypes.Norton, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 2;
        }
        else if (string.Equals(analysisType, AnalysisTypes.Mesh, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 3;
        }
        else if (string.Equals(analysisType, AnalysisTypes.Superposition, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 4;
        }
        else if (string.Equals(analysisType, AnalysisTypes.Millman, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 5;
        }
        else if (string.Equals(analysisType, AnalysisTypes.SourceTransform, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 6;
        }
        else if (string.Equals(analysisType, AnalysisTypes.Transient, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 7;
        }
        else if (string.Equals(analysisType, AnalysisTypes.Power, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 8;
        }
        else if (string.Equals(analysisType, AnalysisTypes.Resonance, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 9;
        }
        else if (string.Equals(analysisType, AnalysisTypes.Transformer, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 10;
        }
        else
        {
            CmbAnalysisType.SelectedIndex = 0;
        }

        UpdateTerminalsVisibility();
        UpdatePowerFactorTargetVisibility();

        if (terminalPositive != null && CmbTerminalPositive.ItemsSource is IEnumerable<string> items && items.Contains(terminalPositive))
        {
            CmbTerminalPositive.SelectedItem = terminalPositive;
        }

        if (CmbTerminalNegative.SelectedItem == null && CmbTerminalNegative.ItemsSource is IEnumerable<string> negItems && negItems.Contains("0"))
        {
            CmbTerminalNegative.SelectedItem = "0";
        }
    }

    /// <summary>Şu anki analiz ayarlarını (yöntem, terminaller, frekans, değer gösterimi) CircuitDocument için döndürür.</summary>
    public CircuitDocument.AnalysisData GetAnalysisSettings()
    {
        string selectedText = (CmbAnalysisType.SelectedItem as ComboBoxItem)?.Content as string
            ?? CmbAnalysisType.SelectedItem as string
            ?? "";

        return new CircuitDocument.AnalysisData
        {
            Type = AnalysisTypeFromText(selectedText),
            TerminalPositive = GetSelectedTerminal(CmbTerminalPositive),
            TerminalNegative = GetSelectedTerminal(CmbTerminalNegative),
            Frequency = TxtFrequency?.Text,
            ValueDisplay = ValueDisplay,
            PowerFactorTarget = TxtPowerFactorTarget?.Text,
        };
    }

    /// <summary>Kaydedilmiş analiz ayarlarını panele geri yükler.</summary>
    public void RestoreAnalysisSettings(CircuitDocument.AnalysisData? settings)
    {
        if (settings == null)
            return;

        SetAnalysisType(settings.Type ?? AnalysisTypes.Nodal, settings.TerminalPositive);
        if (!string.IsNullOrEmpty(settings.TerminalNegative) &&
            CmbTerminalNegative.ItemsSource is IEnumerable<string> negItems &&
            negItems.Contains(settings.TerminalNegative))
        {
            CmbTerminalNegative.SelectedItem = settings.TerminalNegative;
        }
        if (settings.Frequency != null && TxtFrequency != null)
        {
            TxtFrequency.Text = settings.Frequency;
        }
        if (settings.PowerFactorTarget != null && TxtPowerFactorTarget != null)
        {
            TxtPowerFactorTarget.Text = settings.PowerFactorTarget;
        }
        if (!string.IsNullOrEmpty(settings.ValueDisplay))
        {
            SetValueDisplay(settings.ValueDisplay, notify: false);
        }
    }

    /// <summary>"RMS" | "PEAK"</summary>
    public string ValueDisplay => BtnDisplayPeak?.IsChecked == true ? "PEAK" : "RMS";

    private void BtnDisplayRms_Click(object sender, RoutedEventArgs e)
    {
        if (BtnDisplayPeak?.IsChecked == true)
        {
            SetValueDisplay("RMS", notify: true);
        }
        else if (BtnDisplayRms != null)
        {
            BtnDisplayRms.IsChecked = true;
        }
    }

    private void BtnDisplayPeak_Click(object sender, RoutedEventArgs e)
    {
        if (BtnDisplayRms?.IsChecked == true)
        {
            SetValueDisplay("PEAK", notify: true);
        }
        else if (BtnDisplayPeak != null)
        {
            BtnDisplayPeak.IsChecked = true;
        }
    }

    public void SetValueDisplay(string valueDisplay, bool notify = false)
    {
        bool isPeak = string.Equals(valueDisplay, "PEAK", StringComparison.OrdinalIgnoreCase);
        string normalized = isPeak ? "PEAK" : "RMS";
        bool changed = (isPeak && BtnDisplayRms?.IsChecked == true) || (!isPeak && BtnDisplayPeak?.IsChecked == true);

        if (BtnDisplayRms != null) BtnDisplayRms.IsChecked = !isPeak;
        if (BtnDisplayPeak != null) BtnDisplayPeak.IsChecked = isPeak;

        AppSettings.AcValueDisplay = normalized;

        if (notify && changed)
        {
            ValueDisplayChanged?.Invoke(this, EventArgs.Empty);
        }
    }

    private void CmbAnalysisType_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        UpdateTerminalsVisibility();
        UpdatePowerFactorTargetVisibility();
    }

    private void UpdateTerminalsVisibility()
    {
        if (RowTerminals == null) return;

        string selectedText = (CmbAnalysisType.SelectedItem as ComboBoxItem)?.Content as string
            ?? CmbAnalysisType.SelectedItem as string
            ?? "";

        RowTerminals.Visibility = UsesTerminals(AnalysisTypeFromText(selectedText))
            ? Visibility.Visible : Visibility.Collapsed;
    }

    private void UpdatePowerFactorTargetVisibility()
    {
        if (RowPowerFactorTarget == null) return;

        string selectedText = (CmbAnalysisType.SelectedItem as ComboBoxItem)?.Content as string
            ?? CmbAnalysisType.SelectedItem as string
            ?? "";

        bool isPower = string.Equals(AnalysisTypeFromText(selectedText), AnalysisTypes.Power, StringComparison.OrdinalIgnoreCase);
        RowPowerFactorTarget.Visibility = isPower ? Visibility.Visible : Visibility.Collapsed;
    }

    /// <summary>Yöntem listesindeki yazıdan API analiz türünü (AnalysisTypes) bulur.</summary>
    internal static string AnalysisTypeFromText(string selectedText)
    {
        if (selectedText.Contains("Thevenin", StringComparison.OrdinalIgnoreCase))
            return AnalysisTypes.Thevenin;
        if (selectedText.Contains("Norton", StringComparison.OrdinalIgnoreCase))
            return AnalysisTypes.Norton;
        if (selectedText.Contains("Çevre", StringComparison.OrdinalIgnoreCase))
            return AnalysisTypes.Mesh;
        if (selectedText.Contains("Süperpozisyon", StringComparison.OrdinalIgnoreCase))
            return AnalysisTypes.Superposition;
        if (selectedText.Contains("Millman", StringComparison.OrdinalIgnoreCase))
            return AnalysisTypes.Millman;
        if (selectedText.Contains("Kaynak Dönüşümü", StringComparison.OrdinalIgnoreCase))
            return AnalysisTypes.SourceTransform;
        if (selectedText.Contains("Geçici", StringComparison.OrdinalIgnoreCase))
            return AnalysisTypes.Transient;
        if (selectedText.Contains("Güç", StringComparison.OrdinalIgnoreCase))
            return AnalysisTypes.Power;
        if (selectedText.Contains("Rezonans", StringComparison.OrdinalIgnoreCase))
            return AnalysisTypes.Resonance;
        if (selectedText.Contains("Transformatör", StringComparison.OrdinalIgnoreCase))
            return AnalysisTypes.Transformer;
        return AnalysisTypes.Nodal;
    }

    /// <summary>Bu yöntem terminal çifti (+ ve −) ister mi?</summary>
    internal static bool UsesTerminals(string analysisType) =>
        analysisType == AnalysisTypes.Thevenin
        || analysisType == AnalysisTypes.Norton
        || analysisType == AnalysisTypes.SourceTransform;

    public bool TryGetOptions(out SolveOptions? options, out string? error)
    {
        options = null;
        error = null;

        string selectedText = (CmbAnalysisType.SelectedItem as ComboBoxItem)?.Content as string
            ?? CmbAnalysisType.SelectedItem as string
            ?? "";

        string analysisType = AnalysisTypeFromText(selectedText);
        bool isTheveninOrNorton = UsesTerminals(analysisType);

        string? pos = null;
        string neg = "0";

        if (isTheveninOrNorton)
        {
            pos = GetSelectedTerminal(CmbTerminalPositive);
            string? n = GetSelectedTerminal(CmbTerminalNegative);

            if (string.IsNullOrEmpty(pos))
            {
                error = "+ terminal seçilmelidir.";
                return false;
            }

            if (string.IsNullOrEmpty(n))
            {
                error = "− terminal seçilmelidir.";
                return false;
            }

            if (pos == n)
            {
                error = "+ ve − terminaller aynı olamaz.";
                return false;
            }

            neg = n;
        }

        double? freq = null;
        if (_hasAcSource)
        {
            string freqText = TxtFrequency.Text?.Trim() ?? "";
            if (string.IsNullOrEmpty(freqText))
            {
                if (_needsFrequency)
                {
                    error = "Frekans değeri gerekli.";
                    return false;
                }
                freq = null;
            }
            else
            {
                if (!TryParseFrequency(freqText, out double parsedFreq, out string? parseError))
                {
                    error = parseError;
                    return false;
                }
                freq = parsedFreq;
            }
        }

        double? powerFactorTarget = null;
        if (string.Equals(analysisType, AnalysisTypes.Power, StringComparison.OrdinalIgnoreCase))
        {
            string pfText = TxtPowerFactorTarget?.Text?.Trim() ?? "";
            if (!string.IsNullOrEmpty(pfText))
            {
                if (!TurkishNumber.TryParse(pfText, out double pfVal) || double.IsNaN(pfVal) || double.IsInfinity(pfVal) || pfVal <= 0 || pfVal > 1)
                {
                    error = "Hedef cos φ 0 ile 1 arasında olmalıdır.";
                    return false;
                }
                powerFactorTarget = pfVal;
            }
        }

        options = new SolveOptions(analysisType, freq, pos, neg, ValueDisplay, powerFactorTarget);
        return true;
    }

    private static string? GetSelectedTerminal(ComboBox cmb)
    {
        return cmb.SelectedItem switch
        {
            string s => s.Trim(),
            ComboBoxItem cbi => cbi.Content?.ToString()?.Trim(),
            _ => !string.IsNullOrWhiteSpace(cmb.Text) ? cmb.Text.Trim() : null
        };
    }

    private static bool TryParseFrequency(string text, out double value, out string? error)
    {
        value = 0;
        error = null;
        text = text.Trim();

        double multiplier = 1.0;
        string numPart = text;

        if (numPart.EndsWith("kHz", StringComparison.OrdinalIgnoreCase))
        {
            multiplier = 1e3;
            numPart = numPart[..^3].Trim();
        }
        else if (numPart.EndsWith("MHz", StringComparison.OrdinalIgnoreCase))
        {
            multiplier = 1e6;
            numPart = numPart[..^3].Trim();
        }
        else if (numPart.EndsWith("Hz", StringComparison.OrdinalIgnoreCase))
        {
            multiplier = 1.0;
            numPart = numPart[..^2].Trim();
        }
        else if (numPart.EndsWith("k", StringComparison.OrdinalIgnoreCase))
        {
            multiplier = 1e3;
            numPart = numPart[..^1].Trim();
        }
        else if (numPart.EndsWith("M", StringComparison.OrdinalIgnoreCase))
        {
            multiplier = 1e6;
            numPart = numPart[..^1].Trim();
        }

        numPart = numPart.Replace(',', '.');

        if (!double.TryParse(numPart, NumberStyles.Float, CultureInfo.InvariantCulture, out double parsed))
        {
            error = "Frekans geçerli bir sayı olmalı.";
            return false;
        }

        double result = parsed * multiplier;
        if (result <= 0 || double.IsNaN(result) || double.IsInfinity(result))
        {
            error = "Frekans pozitif bir sayı olmalı";
            return false;
        }

        value = result;
        return true;
    }

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

            // Yapay zekâ asistanı
            if (CurrentAssistantView != null)
            {
                ResultsContainer.Children.Add(CurrentAssistantView);
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

        // 1. Durum Satırı
        bool isSuccess = string.Equals(response.Status, "success", StringComparison.OrdinalIgnoreCase);
        var statusBorder = new Border
        {
            Margin = new Thickness(0, 0, 0, 12)
        };
        statusBorder.SetResourceReference(StyleProperty, isSuccess ? "InfoBar.Success" : "InfoBar.Warning");
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

        // Yapay zekâ asistanı
        if (CurrentAssistantView != null)
        {
            ResultsContainer.Children.Add(CurrentAssistantView);
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
            plotCard.SetResourceReference(StyleProperty, "Card");

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
        if (powerSummary != null)
        {
            var powerCard = new Border
            {
                Padding = new Thickness(12),
                Margin = new Thickness(0, 0, 0, 12)
            };
            powerCard.SetResourceReference(StyleProperty, "Card");

            var triangleView = new PowerTriangleView();
            triangleView.LoadData(powerSummary);

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
            resCard.SetResourceReference(StyleProperty, "Card");

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
            _explanationPanel = BuildExplanationPanel(response.Results!.Explanation);

            if (_userSelectedExplanation.HasValue)
                IsExplanationViewSelected = _userSelectedExplanation.Value;
            else
                IsExplanationViewSelected = true;

            _viewToggleBorder = CreateSegmentedToggle();
            ResultsContainer.Children.Add(_viewToggleBorder);
            ResultsContainer.Children.Add(_resultsPanel);

            UpdateToggleButtonsState();
            UpdateViewVisibility();
        }
        else
        {
            IsExplanationViewSelected = false;
            ResultsContainer.Children.Add(_resultsPanel);
            _resultsPanel.Visibility = Visibility.Visible;
        }
    }

    private void UpdateToggleButtonsState()
    {
        if (_btnViewExplanation == null || _btnViewResults == null) return;

        _btnViewExplanation.IsChecked = IsExplanationViewSelected;
        _btnViewResults.IsChecked = !IsExplanationViewSelected;
    }

    private void UpdateViewVisibility()
    {
        if (_resultsPanel == null) return;

        if (IsExplanationViewSelected)
        {
            if (_explanationPanel != null)
            {
                if (!ResultsContainer.Children.Contains(_explanationPanel))
                {
                    int idx = ResultsContainer.Children.IndexOf(_resultsPanel);
                    if (idx >= 0)
                        ResultsContainer.Children.Insert(idx, _explanationPanel);
                    else
                        ResultsContainer.Children.Add(_explanationPanel);
                }
                _explanationPanel.Visibility = Visibility.Visible;
            }
            _resultsPanel.Visibility = Visibility.Collapsed;
        }
        else
        {
            if (_explanationPanel != null && ResultsContainer.Children.Contains(_explanationPanel))
            {
                ResultsContainer.Children.Remove(_explanationPanel);
            }
            if (!ResultsContainer.Children.Contains(_resultsPanel))
            {
                ResultsContainer.Children.Add(_resultsPanel);
            }
            _resultsPanel.Visibility = Visibility.Visible;
        }
    }

    private Border CreateSegmentedToggle()
    {
        var border = new Border
        {
            Margin = new Thickness(0, 4, 0, 14)
        };
        border.SetResourceReference(StyleProperty, "Segment.Track");

        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        _btnViewExplanation = new ToggleButton
        {
            Content = "Anlatım"
        };
        _btnViewExplanation.SetResourceReference(StyleProperty, "Segment.Item");
        _btnViewExplanation.Click += (s, e) => SelectExplanationView(true);
        Grid.SetColumn(_btnViewExplanation, 0);
        grid.Children.Add(_btnViewExplanation);

        _btnViewResults = new ToggleButton
        {
            Content = "Sonuçlar"
        };
        _btnViewResults.SetResourceReference(StyleProperty, "Segment.Item");
        _btnViewResults.Click += (s, e) => SelectExplanationView(false);
        Grid.SetColumn(_btnViewResults, 1);
        grid.Children.Add(_btnViewResults);

        border.Child = grid;
        return border;
    }

    private static StackPanel BuildExplanationPanel(List<ExplanationSectionDto> sections)
    {
        var panel = new StackPanel();

        foreach (var section in sections)
        {
            panel.Children.Add(BuildExplanationSectionPanel(section));
        }

        return panel;
    }

    internal static StackPanel BuildExplanationSectionPanel(ExplanationSectionDto section)
    {
        var sectionPanel = new StackPanel { Margin = new Thickness(0, 0, 0, 18) };

        var titleText = new TextBlock
        {
            Text = section.Title,
            Margin = new Thickness(0, 0, 0, 8)
        };
        titleText.SetResourceReference(StyleProperty, "Text.Section");
        SubscriptText.Apply(titleText);
        sectionPanel.Children.Add(titleText);

        var divider = new Border
        {
            Height = 1,
            Margin = new Thickness(0, 0, 0, 10)
        };
        divider.SetResourceReference(Border.BackgroundProperty, "Brush.Border.Default");
        sectionPanel.Children.Add(divider);

        if (section.Blocks != null)
        {
            foreach (var block in section.Blocks)
            {
                var el = CreateBlockElement(block);
                if (el != null)
                    sectionPanel.Children.Add(el);
            }
        }

        return sectionPanel;
    }

    private static UIElement? CreateBlockElement(ExplanationBlockDto block)
    {
        if (block == null || string.IsNullOrEmpty(block.Text))
            return null;

        string kind = block.Kind?.ToLowerInvariant() ?? "text";

        switch (kind)
        {
            case "math":
            {
                var mathBorder = new Border
                {
                    Margin = new Thickness(0, 0, 0, 10)
                };
                mathBorder.SetResourceReference(StyleProperty, "Card.Inset");

                var tb = new TextBlock
                {
                    Text = block.Text
                };
                tb.SetResourceReference(StyleProperty, "Text.Mono");
                SubscriptText.Apply(tb);
                mathBorder.Child = tb;
                return mathBorder;
            }

            case "result":
            {
                var resultBorder = new Border
                {
                    Margin = new Thickness(0, 0, 0, 10)
                };
                resultBorder.SetResourceReference(StyleProperty, "Chip.Accent");

                var tb = new TextBlock
                {
                    Text = block.Text,
                    TextWrapping = TextWrapping.Wrap
                };
                SubscriptText.Apply(tb);
                resultBorder.Child = tb;
                return resultBorder;
            }

            case "note":
            {
                string noteText = block.Text.TrimStart('ℹ', ' ');
                var grid = new Grid { Margin = new Thickness(0, 0, 0, 10) };
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

                var icon = new Icon
                {
                    Width = 16,
                    Height = 16,
                    Margin = new Thickness(0, 2, 8, 0),
                    VerticalAlignment = VerticalAlignment.Top
                };
                icon.SetResourceReference(Icon.DataProperty, "Icon.Info");
                icon.SetResourceReference(Icon.ForegroundProperty, "Brush.Text.Secondary");
                Grid.SetColumn(icon, 0);
                grid.Children.Add(icon);

                var tb = new TextBlock
                {
                    Text = noteText
                };
                tb.SetResourceReference(StyleProperty, "Text.Caption");
                SubscriptText.Apply(tb);
                Grid.SetColumn(tb, 1);
                grid.Children.Add(tb);
                return grid;
            }

            case "check":
            {
                string checkText = block.Text.TrimStart('✓', ' ');
                var grid = new Grid { Margin = new Thickness(0, 0, 0, 10) };
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

                var icon = new Icon
                {
                    Width = 16,
                    Height = 16,
                    Margin = new Thickness(0, 2, 8, 0),
                    VerticalAlignment = VerticalAlignment.Top
                };
                icon.SetResourceReference(Icon.DataProperty, "Icon.Check");
                icon.SetResourceReference(Icon.ForegroundProperty, "Brush.Success");
                Grid.SetColumn(icon, 0);
                grid.Children.Add(icon);

                var tb = new TextBlock
                {
                    Text = checkText,
                    TextWrapping = TextWrapping.Wrap,
                    FontSize = 13
                };
                tb.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Success");
                SubscriptText.Apply(tb);
                Grid.SetColumn(tb, 1);
                grid.Children.Add(tb);
                return grid;
            }

            case "text":
            default:
            {
                var tb = new TextBlock
                {
                    Text = block.Text,
                    Margin = new Thickness(0, 0, 0, 10)
                };
                tb.SetResourceReference(StyleProperty, "Text.Body");
                SubscriptText.Apply(tb);
                return tb;
            }
        }
    }

    private static Border CreateValueTile(string label, string primaryValue, string? secondaryValue = null)
    {
        var tile = new Border();
        tile.SetResourceReference(StyleProperty, "Card.Inset");

        var sp = new StackPanel();

        var lbl = new TextBlock
        {
            Text = label
        };
        lbl.SetResourceReference(StyleProperty, "Text.Caption");
        SubscriptText.Apply(lbl);
        sp.Children.Add(lbl);

        var val = new TextBlock
        {
            Text = primaryValue,
            FontSize = 15,
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(0, 2, 0, 0)
        };
        val.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
        SubscriptText.Apply(val);
        sp.Children.Add(val);

        if (!string.IsNullOrWhiteSpace(secondaryValue))
        {
            var sec = new TextBlock
            {
                Text = secondaryValue,
                Margin = new Thickness(0, 2, 0, 0)
            };
            sec.SetResourceReference(StyleProperty, "Text.Caption");
            SubscriptText.Apply(sec);
            sp.Children.Add(sec);
        }

        tile.Child = sp;
        return tile;
    }

    private static Grid CreateTwoColumnGrid(List<UIElement> tiles)
    {
        var grid = new Grid { Margin = new Thickness(0, 0, 0, 12) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        int rowCount = (tiles.Count + 1) / 2;
        for (int r = 0; r < rowCount; r++)
        {
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        }

        for (int i = 0; i < tiles.Count; i++)
        {
            int row = i / 2;
            int col = i % 2;
            var tile = tiles[i];
            if (tile is FrameworkElement fe)
            {
                fe.Margin = col == 0 ? new Thickness(0, 0, 4, 8) : new Thickness(4, 0, 0, 8);
            }
            Grid.SetRow(tile, row);
            Grid.SetColumn(tile, col);
            grid.Children.Add(tile);
        }

        return grid;
    }

    private StackPanel BuildResultsPanel(AnalysisResponseDto response)
    {
        var panel = new StackPanel();

        // 3. Düğüm Gerilimleri
        if (response.Results?.NodeVoltages != null && response.Results.NodeVoltages.Count > 0)
        {
            AddSectionHeader(panel, "Düğüm gerilimleri");

            var sortedNodes = response.Results.NodeVoltages
                .OrderBy(kv => int.TryParse(kv.Key, out int n) ? n : int.MaxValue)
                .ThenBy(kv => kv.Key);

            var tiles = new List<UIElement>();
            foreach (var kvp in sortedNodes)
            {
                string nodeName = kvp.Key == "0" ? "0 (GND)" : $"V{kvp.Key}";
                string formattedVal = EngFormat.Format(kvp.Value.Value, kvp.Value.Unit ?? "V");
                string? secVal = null;
                if (kvp.Value.Value.IsComplex && !string.IsNullOrWhiteSpace(kvp.Value.Value.RectangularStr))
                {
                    secVal = $"{TurkishNumber.NormalizeForDisplay(kvp.Value.Value.RectangularStr)} {kvp.Value.Unit ?? "V"}";
                }
                tiles.Add(CreateValueTile(nodeName, formattedVal, secVal));
            }
            panel.Children.Add(CreateTwoColumnGrid(tiles));
        }

        // 4. Eleman Akımları
        if (response.Results?.ElementCurrents != null && response.Results.ElementCurrents.Count > 0)
        {
            AddSectionHeader(panel, "Eleman akımları");

            var tiles = new List<UIElement>();
            foreach (var kvp in response.Results.ElementCurrents)
            {
                var (currentText, directionText) = CurrentDisplay.Format(kvp.Key, kvp.Value);
                string label = string.IsNullOrEmpty(directionText) ? $"I_{kvp.Key}" : $"I_{kvp.Key} · {directionText}";
                tiles.Add(CreateValueTile(label, currentText));
            }
            panel.Children.Add(CreateTwoColumnGrid(tiles));
        }

        // 5. Ölçüm Probları
        if (response.Results?.ProbeResults != null && response.Results.ProbeResults.Count > 0)
        {
            AddSectionHeader(panel, "Ölçüm probları");

            var tiles = new List<UIElement>();
            foreach (var probe in response.Results.ProbeResults)
            {
                string formattedVal = EngFormat.Format(probe.Value, probe.Unit ?? "");
                tiles.Add(CreateValueTile(probe.ProbeId, formattedVal));
            }
            panel.Children.Add(CreateTwoColumnGrid(tiles));
        }

        // 6. Thevenin Kartı
        if (response.Results?.Thevenin != null)
        {
            var th = response.Results.Thevenin;
            AddSectionHeader(panel, "Thevenin eşdeğeri");

            string vthRect = !string.IsNullOrEmpty(th.Vth.RectangularStr) ? TurkishNumber.NormalizeForDisplay(th.Vth.RectangularStr) : TurkishNumber.Format(th.Vth.Real, "G4");
            string vthPolar = !string.IsNullOrEmpty(th.Vth.PolarStr) ? TurkishNumber.NormalizeForDisplay(th.Vth.PolarStr) : TurkishNumber.Format(th.Vth.Real, "G4");
            string? secVth = !string.IsNullOrEmpty(th.Vth.PolarStr) && Math.Abs(th.Vth.Imaginary) > 1e-12 ? $"{vthPolar} V" : null;

            string zthRect = !string.IsNullOrEmpty(th.Zth.RectangularStr) ? TurkishNumber.NormalizeForDisplay(th.Zth.RectangularStr) : TurkishNumber.Format(th.Zth.Real, "G4");
            string zthPolar = !string.IsNullOrEmpty(th.Zth.PolarStr) ? TurkishNumber.NormalizeForDisplay(th.Zth.PolarStr) : TurkishNumber.Format(th.Zth.Real, "G4");
            string? secZth = !string.IsNullOrEmpty(th.Zth.PolarStr) && Math.Abs(th.Zth.Imaginary) > 1e-12 ? $"{zthPolar} Ω" : null;

            var tiles = new List<UIElement>
            {
                CreateValueTile($"Vth ({th.NodePositive} – {th.NodeNegative})", $"{vthRect} V", secVth),
                CreateValueTile("Zth", $"{zthRect} Ω", secZth)
            };
            panel.Children.Add(CreateTwoColumnGrid(tiles));
        }

        // 7. Norton Kartı
        if (response.Results?.Norton != null)
        {
            var no = response.Results.Norton;
            AddSectionHeader(panel, "Norton eşdeğeri");

            string inRect = !string.IsNullOrEmpty(no.In.RectangularStr) ? TurkishNumber.NormalizeForDisplay(no.In.RectangularStr) : TurkishNumber.Format(no.In.Real, "G4");
            string inPolar = !string.IsNullOrEmpty(no.In.PolarStr) ? TurkishNumber.NormalizeForDisplay(no.In.PolarStr) : TurkishNumber.Format(no.In.Real, "G4");
            string? secIn = !string.IsNullOrEmpty(no.In.PolarStr) && Math.Abs(no.In.Imaginary) > 1e-12 ? $"{inPolar} A" : null;

            string znStr = no.Zn != null
                ? (!string.IsNullOrEmpty(no.Zn.RectangularStr) ? TurkishNumber.NormalizeForDisplay(no.Zn.RectangularStr) : TurkishNumber.Format(no.Zn.Real, "G4")) + " Ω"
                : "∞ (ideal)";
            string? secZn = no.Zn != null && !string.IsNullOrEmpty(no.Zn.PolarStr) && Math.Abs(no.Zn.Imaginary) > 1e-12 ? $"{TurkishNumber.NormalizeForDisplay(no.Zn.PolarStr)} Ω" : null;

            var tiles = new List<UIElement>
            {
                CreateValueTile($"In ({no.NodePositive} – {no.NodeNegative})", $"{inRect} A", secIn),
                CreateValueTile("Zn", znStr, secZn)
            };

            if (no.Yn != null)
            {
                string ynRect = !string.IsNullOrEmpty(no.Yn.RectangularStr) ? TurkishNumber.NormalizeForDisplay(no.Yn.RectangularStr) : TurkishNumber.Format(no.Yn.Real, "G4");
                string ynPolar = !string.IsNullOrEmpty(no.Yn.PolarStr) ? TurkishNumber.NormalizeForDisplay(no.Yn.PolarStr) : TurkishNumber.Format(no.Yn.Real, "G4");
                string? secYn = !string.IsNullOrEmpty(no.Yn.PolarStr) && Math.Abs(no.Yn.Imaginary) > 1e-12 ? $"{ynPolar} S" : null;
                tiles.Add(CreateValueTile("Yn", $"{ynRect} S", secYn));
            }

            panel.Children.Add(CreateTwoColumnGrid(tiles));
        }

        // 8. Güç Analizi
        if (response.Results?.Power != null)
        {
            var power = response.Results.Power;
            AddSectionHeader(panel, "Güç analizi");

            var card = new Border { Margin = new Thickness(0, 0, 0, 10) };
            card.SetResourceReference(StyleProperty, "Card.Inset");
            var stack = new StackPanel();

            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            string[] headers = { "Eleman", "P", "Q", "S", "cos φ" };
            for (int c = 0; c < headers.Length; c++)
            {
                var th = new TextBlock
                {
                    Text = headers[c],
                    FontSize = 11,
                    FontWeight = FontWeights.SemiBold,
                    Margin = new Thickness(2, 0, c == 0 ? 12 : 2, 4)
                };
                th.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
                Grid.SetRow(th, 0);
                Grid.SetColumn(th, c);
                grid.Children.Add(th);
            }

            int r = 1;
            foreach (var kvp in power.Elements)
            {
                var el = kvp.Value;
                grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

                string name = el.Role == "source" ? $"{el.ElementId} ⚡" : el.ElementId;
                string pStr = EngFormat.Format(el.ActivePower, "W");
                string qStr = EngFormat.Format(el.ReactivePower, "VAR");
                string sStr = EngFormat.Format(el.ApparentPower, "VA");
                string pfStr;
                if (el.PowerFactor.HasValue)
                {
                    string num = TurkishNumber.Format(el.PowerFactor.Value, "0.000");
                    pfStr = !string.IsNullOrEmpty(el.PowerFactorType) ? $"{num} {el.PowerFactorType}" : num;
                }
                else
                {
                    pfStr = "—";
                }

                string[] rowVals = { name, pStr, qStr, sStr, pfStr };
                for (int c = 0; c < rowVals.Length; c++)
                {
                    var td = new TextBlock
                    {
                        Text = rowVals[c],
                        FontSize = 11,
                        Margin = new Thickness(2, 2, c == 0 ? 12 : 2, 2),
                        TextWrapping = TextWrapping.NoWrap
                    };
                    if (c == 0)
                    {
                        td.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
                    }
                    else if (c == 4)
                    {
                        td.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
                    }
                    else
                    {
                        td.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
                        td.SetResourceReference(TextBlock.FontFamilyProperty, "Font.Mono");
                    }
                    Grid.SetRow(td, r);
                    Grid.SetColumn(td, c);
                    grid.Children.Add(td);
                }
                r++;
            }

            stack.Children.Add(grid);

            var footnote = new TextBlock
            {
                Text = "⚡ kaynak — değerler elemanın çektiği güçtür; negatif P/Q, elemanın o gücü devreye verdiği anlamına gelir.",
                FontSize = 11,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 8, 0, 0)
            };
            footnote.SetResourceReference(StyleProperty, "Text.Caption");
            stack.Children.Add(footnote);

            card.Child = stack;
            panel.Children.Add(card);

            if (power.TotalSupplied != null || power.PowerFactor.HasValue)
            {
                var summaryTiles = new List<UIElement>();
                if (power.TotalSupplied != null)
                {
                    string supStr = !string.IsNullOrEmpty(power.TotalSupplied.RectangularStr)
                        ? TurkishNumber.NormalizeForDisplay(power.TotalSupplied.RectangularStr)
                        : EngFormat.Format(power.TotalSupplied.Magnitude, "");
                    summaryTiles.Add(CreateValueTile("Verilen güç", $"{supStr} VA"));
                }
                if (power.PowerFactor.HasValue)
                {
                    string dpf = TurkishNumber.Format(power.PowerFactor.Value, "0.000");
                    string dpfType = !string.IsNullOrEmpty(power.PowerFactorType) ? $" ({power.PowerFactorType})" : "";
                    summaryTiles.Add(CreateValueTile("Devre güç faktörü", $"{dpf}{dpfType}"));
                }
                panel.Children.Add(CreateTwoColumnGrid(summaryTiles));
            }
        }

        // 9. Seri / Paralel Bağlantılar
        if (response.Results?.Reductions != null && response.Results.Reductions.Count > 0)
        {
            AddSectionHeader(panel, "Seri / paralel bağlantılar");

            var tiles = new List<UIElement>();
            foreach (var red in response.Results.Reductions)
            {
                string label = red.Type.ToLowerInvariant().Contains("seri") || red.Type.ToLowerInvariant().Contains("series") ? "Seri bağlantı" : "Paralel bağlantı";
                tiles.Add(CreateValueTile(label, red.Formula));
            }
            panel.Children.Add(CreateTwoColumnGrid(tiles));
        }

        // 10. Adım Adım Çözüm
        if (response.SolutionSteps != null && response.SolutionSteps.Count > 0)
        {
            AddSectionHeader(panel, "Adım adım çözüm");

            for (int i = 0; i < response.SolutionSteps.Count; i++)
            {
                var step = response.SolutionSteps[i];
                var expander = new Expander
                {
                    Header = $"{step.StepNumber}. {step.Title}",
                    IsExpanded = (i == 0),
                    Margin = new Thickness(0, 0, 0, 8)
                };
                expander.SetResourceReference(StyleProperty, "Expander.Card");

                var stepPanel = new StackPanel();
                if (!string.IsNullOrWhiteSpace(step.Description))
                {
                    var txtDesc = new TextBlock
                    {
                        Text = step.Description,
                        Margin = new Thickness(0, 0, 0, 8)
                    };
                    txtDesc.SetResourceReference(StyleProperty, "Text.Body");
                    stepPanel.Children.Add(txtDesc);
                }

                if (step.Equations != null)
                {
                    foreach (var eq in step.Equations)
                    {
                        if (string.IsNullOrWhiteSpace(eq)) continue;
                        var mathBorder = new Border
                        {
                            Margin = new Thickness(0, 0, 0, 6)
                        };
                        mathBorder.SetResourceReference(StyleProperty, "Card.Inset");

                        var txtEq = new TextBlock
                        {
                            Text = eq
                        };
                        txtEq.SetResourceReference(StyleProperty, "Text.Mono");
                        mathBorder.Child = txtEq;
                        stepPanel.Children.Add(mathBorder);
                    }
                }

                expander.Content = stepPanel;
                panel.Children.Add(expander);
            }
        }

        return panel;
    }

    public void ShowError(string title, string message)
    {
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
        BannerStale.Visibility = Visibility.Collapsed;
        ResultsScrollViewer.Opacity = 1.0;
        ResultsContainer.Children.Clear();
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

    private static void AddSectionHeader(Panel target, string title)
    {
        var txtHeader = new TextBlock
        {
            Text = title,
            Margin = new Thickness(0, 14, 0, 8)
        };
        txtHeader.SetResourceReference(StyleProperty, "Text.Section");
        target.Children.Add(txtHeader);
    }
}
