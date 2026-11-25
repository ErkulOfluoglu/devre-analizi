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
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views;

public partial class AnalysisPanel : UserControl
{
    public event EventHandler? SolveRequested;
    public event EventHandler? ValueDisplayChanged;
    public event EventHandler<TransientAnalysisDto>? EnlargePlotRequested;
    public event EventHandler<ResonanceDto>? EnlargeResonanceRequested;
    public event EventHandler<ZenerRangeDto>? EnlargeZenerRangeRequested;

    private BackendState _backendState = BackendState.Starting;
    private bool _isBusy;
    private bool _hasAcSource;
    private bool _needsFrequency;
    private string? _lastZenerRangeTarget;
    private bool _suppressZenerTargetChanged;
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
    public Func<CancellationToken, Task<(bool Ok, string Message)>>? LlmEnableGpu { get; set; }
    public Func<string?, CancellationToken, Task<LlmPullStatusDto>>? LlmStartPull { get; set; }
    public Func<CancellationToken, Task<LlmPullStatusDto?>>? LlmGetPull { get; set; }
    public Func<CancellationToken, Task<bool>>? LlmCancelPull { get; set; }
    public FrameworkElement ResultsCard => ResultsScrollViewer;
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

        UpdateModeLabel();
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

    /// <summary>Karşıtlık teoreminde ölçülebilecek pasif elemanların (R, L, C) kimliklerini eleman sırasıyla döndürür.</summary>
    internal static List<string> ReciprocityTargetIds(IEnumerable<CircuitElement> elements) =>
        elements
            .Where(e => e is Resistor or Inductor or Capacitor && !string.IsNullOrWhiteSpace(e.Id))
            .Select(e => e.Id)
            .ToList();

    /// <summary>Varsayılan karşıtlık hedefi: devredeki son R/L/C elemanın kimliği (yoksa null).</summary>
    internal static string? DefaultReciprocityTarget(IEnumerable<CircuitElement> elements)
    {
        var ids = ReciprocityTargetIds(elements);
        return ids.Count > 0 ? ids[^1] : null;
    }

    /// <summary>Karşıtlık hedefini seçer: önceki seçim listede varsa korur, yoksa son R/L/C elemana düşer.</summary>
    internal static string? ResolveReciprocityTarget(IReadOnlyList<string> candidates, string? preferred)
    {
        if (candidates.Count == 0)
            return null;
        if (!string.IsNullOrEmpty(preferred) && candidates.Contains(preferred, StringComparer.Ordinal))
            return preferred;
        return candidates[^1];
    }

    public void SetAvailableReciprocityTargets(IEnumerable<CircuitElement> elements) =>
        SetAvailableReciprocityTargetIds(ReciprocityTargetIds(elements));

    public void SetAvailableReciprocityTargetIds(IReadOnlyList<string> targetIds)
    {
        if (CmbReciprocityTarget == null) return;

        string? prev = GetSelectedTerminal(CmbReciprocityTarget);
        var list = targetIds.ToList();
        CmbReciprocityTarget.ItemsSource = list;
        CmbReciprocityTarget.SelectedItem = ResolveReciprocityTarget(list, prev);
    }

    /// <summary>Zener aralığında değişebilecek elemanların (dirençler ve DC gerilim kaynakları) kimliklerini döndürür.</summary>
    internal static List<string> ZenerRangeTargetIds(IEnumerable<CircuitElement> elements) =>
        elements
            .Where(e => e is Resistor or VoltageSource && !string.IsNullOrWhiteSpace(e.Id))
            .Select(e => e.Id)
            .ToList();

    /// <summary>Zener aralığı hedefini çözer: önceki seçim listede varsa korur, yoksa boş bırakır (API yükü otomatik seçer).</summary>
    internal static string? ResolveZenerRangeTarget(IReadOnlyList<string> candidates, string? preferred)
    {
        if (string.IsNullOrEmpty(preferred))
            return null;
        return candidates.Contains(preferred, StringComparer.Ordinal) ? preferred : null;
    }

    public void SetAvailableZenerRangeTargets(IEnumerable<CircuitElement> elements) =>
        SetAvailableZenerRangeTargetIds(ZenerRangeTargetIds(elements));

    public void SetAvailableZenerRangeTargetIds(IReadOnlyList<string> targetIds)
    {
        if (CmbZenerRangeTarget == null) return;

        string? prev = GetSelectedTerminal(CmbZenerRangeTarget);
        var list = targetIds.ToList();
        string? resolved = ResolveZenerRangeTarget(list, prev);

        // ItemsSource yenilenirken SelectionChanged geçici olarak null tetikler; hedef aynı kaldıysa aralığı silme
        _suppressZenerTargetChanged = true;
        try
        {
            CmbZenerRangeTarget.ItemsSource = list;
            CmbZenerRangeTarget.SelectedItem = resolved;
            _lastZenerRangeTarget = resolved;
        }
        finally
        {
            _suppressZenerTargetChanged = false;
        }

        if (!string.Equals(prev, resolved, StringComparison.Ordinal))
            ClearZenerRangeGiven();
    }

    private void CmbZenerRangeTarget_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressZenerTargetChanged) return;

        string? current = GetSelectedTerminal(CmbZenerRangeTarget);
        if (!string.Equals(_lastZenerRangeTarget, current, StringComparison.Ordinal))
        {
            _lastZenerRangeTarget = current;
            ClearZenerRangeGiven();
        }
    }

    private void TxtZenerRangeGiven_TextChanged(object sender, TextChangedEventArgs e)
    {
        SetZenerRangeGivenError(null);
    }

    private void ClearZenerRangeGiven()
    {
        if (TxtZenerRangeGivenMin != null) TxtZenerRangeGivenMin.Text = "";
        if (TxtZenerRangeGivenMax != null) TxtZenerRangeGivenMax.Text = "";
        SetZenerRangeGivenError(null);
    }

    private void SetZenerRangeGivenError(string? message)
    {
        if (TxtZenerRangeGivenError == null) return;
        if (string.IsNullOrWhiteSpace(message))
        {
            TxtZenerRangeGivenError.Text = "";
            TxtZenerRangeGivenError.Visibility = Visibility.Collapsed;
        }
        else
        {
            TxtZenerRangeGivenError.Text = message;
            TxtZenerRangeGivenError.Visibility = Visibility.Visible;
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
        else if (string.Equals(analysisType, AnalysisTypes.Reciprocity, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 6;
        }
        else if (string.Equals(analysisType, AnalysisTypes.SourceTransform, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 7;
        }
        else if (string.Equals(analysisType, AnalysisTypes.Transient, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 8;
        }
        else if (string.Equals(analysisType, AnalysisTypes.Power, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 9;
        }
        else if (string.Equals(analysisType, AnalysisTypes.Resonance, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 10;
        }
        else if (string.Equals(analysisType, AnalysisTypes.Transformer, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 11;
        }
        else if (string.Equals(analysisType, AnalysisTypes.ThreePhase, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 12;
        }
        else if (string.Equals(analysisType, AnalysisTypes.ZenerRange, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 13;
        }
        else
        {
            CmbAnalysisType.SelectedIndex = 0;
        }

        UpdateTerminalsVisibility();
        UpdatePowerFactorTargetVisibility();
        UpdateReciprocityTargetVisibility();
        UpdateZenerRangeTargetVisibility();

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

        string? givenMin = string.IsNullOrWhiteSpace(TxtZenerRangeGivenMin?.Text) ? null : TxtZenerRangeGivenMin.Text.Trim();
        string? givenMax = string.IsNullOrWhiteSpace(TxtZenerRangeGivenMax?.Text) ? null : TxtZenerRangeGivenMax.Text.Trim();

        return new CircuitDocument.AnalysisData
        {
            Type = AnalysisTypeFromText(selectedText),
            TerminalPositive = GetSelectedTerminal(CmbTerminalPositive),
            TerminalNegative = GetSelectedTerminal(CmbTerminalNegative),
            Frequency = TxtFrequency?.Text,
            ValueDisplay = ValueDisplay,
            PowerFactorTarget = TxtPowerFactorTarget?.Text,
            ReciprocityTarget = GetSelectedTerminal(CmbReciprocityTarget),
            ZenerRangeTarget = GetSelectedTerminal(CmbZenerRangeTarget),
            ZenerRangeGivenMin = givenMin,
            ZenerRangeGivenMax = givenMax,
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
        if (CmbReciprocityTarget?.ItemsSource is IEnumerable<string> recItems)
        {
            var candidates = recItems as IReadOnlyList<string> ?? recItems.ToList();
            CmbReciprocityTarget.SelectedItem = ResolveReciprocityTarget(candidates, settings.ReciprocityTarget);
        }
        if (CmbZenerRangeTarget?.ItemsSource is IEnumerable<string> zenerItems)
        {
            var candidates = zenerItems as IReadOnlyList<string> ?? zenerItems.ToList();
            string? resolved = ResolveZenerRangeTarget(candidates, settings.ZenerRangeTarget);
            _suppressZenerTargetChanged = true;
            try
            {
                CmbZenerRangeTarget.SelectedItem = resolved;
                _lastZenerRangeTarget = resolved;
            }
            finally
            {
                _suppressZenerTargetChanged = false;
            }
        }
        if (TxtZenerRangeGivenMin != null)
        {
            TxtZenerRangeGivenMin.Text = settings.ZenerRangeGivenMin ?? "";
        }
        if (TxtZenerRangeGivenMax != null)
        {
            TxtZenerRangeGivenMax.Text = settings.ZenerRangeGivenMax ?? "";
        }
        SetZenerRangeGivenError(null);
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

        // Varsayılan yalnız öğrencinin kendi seçimiyle değişir (notify = düğmeye tıklandı).
        // Tepe değerle kaydedilmiş bir dosyayı açmak sonraki devrelerin ayarını değiştirmez.
        if (notify)
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
        UpdateReciprocityTargetVisibility();
        UpdateZenerRangeTargetVisibility();
        UpdateModeLabel();
    }

    /// <summary>Çözücü durumunun altındaki mod yazısı: "Geçici durum" yöntemde, yoksa AC / DC.</summary>
    internal static string ModeLabelText(bool hasAcSource, string analysisType) =>
        string.Equals(analysisType, AnalysisTypes.Transient, StringComparison.OrdinalIgnoreCase)
            ? "Geçici durum"
            : hasAcSource ? "AC (fazör) analiz" : "DC analiz";

    private void UpdateModeLabel()
    {
        if (TxtModeLabel == null || CmbAnalysisType == null) return;
        string selectedText = (CmbAnalysisType.SelectedItem as ComboBoxItem)?.Content as string
            ?? CmbAnalysisType.SelectedItem as string
            ?? "";
        TxtModeLabel.Text = ModeLabelText(_hasAcSource, AnalysisTypeFromText(selectedText));
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

        bool isPower = string.Equals(AnalysisTypeFromText(selectedText), AnalysisTypes.Power, StringComparison.OrdinalIgnoreCase)
            || string.Equals(AnalysisTypeFromText(selectedText), AnalysisTypes.ThreePhase, StringComparison.OrdinalIgnoreCase);
        RowPowerFactorTarget.Visibility = isPower ? Visibility.Visible : Visibility.Collapsed;
    }

    private void UpdateReciprocityTargetVisibility()
    {
        if (RowReciprocityTarget == null) return;

        string selectedText = (CmbAnalysisType.SelectedItem as ComboBoxItem)?.Content as string
            ?? CmbAnalysisType.SelectedItem as string
            ?? "";

        bool isReciprocity = string.Equals(AnalysisTypeFromText(selectedText), AnalysisTypes.Reciprocity, StringComparison.OrdinalIgnoreCase);
        RowReciprocityTarget.Visibility = isReciprocity ? Visibility.Visible : Visibility.Collapsed;
    }

    private void UpdateZenerRangeTargetVisibility()
    {
        if (RowZenerRangeTarget == null) return;

        string selectedText = (CmbAnalysisType.SelectedItem as ComboBoxItem)?.Content as string
            ?? CmbAnalysisType.SelectedItem as string
            ?? "";

        bool isZenerRange = string.Equals(AnalysisTypeFromText(selectedText), AnalysisTypes.ZenerRange, StringComparison.OrdinalIgnoreCase);
        var vis = isZenerRange ? Visibility.Visible : Visibility.Collapsed;
        RowZenerRangeTarget.Visibility = vis;
        if (RowZenerRangeGiven != null)
            RowZenerRangeGiven.Visibility = vis;
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
        if (string.Equals(selectedText, "Karşıtlık", StringComparison.Ordinal))
            return AnalysisTypes.Reciprocity;
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
        if (selectedText.Contains("Üç Faz", StringComparison.OrdinalIgnoreCase))
            return AnalysisTypes.ThreePhase;
        if (string.Equals(selectedText, "Zener Aralığı", StringComparison.Ordinal))
            return AnalysisTypes.ZenerRange;
        return AnalysisTypes.Nodal;
    }

    /// <summary>
    /// Yöntem listesindeki yazılardan, verilen analiz türüne karşılık gelen ilkini bulur
    /// (eşleme <see cref="AnalysisTypeFromText"/> ile; ayrı bir ad listesi tutulmaz). Yoksa null.
    /// </summary>
    internal static string? MethodLabelFor(IEnumerable<string> selectorLabels, string? analysisType)
    {
        if (string.IsNullOrWhiteSpace(analysisType))
            return null;
        return selectorLabels.FirstOrDefault(label =>
            string.Equals(AnalysisTypeFromText(label), analysisType, StringComparison.OrdinalIgnoreCase));
    }

    /// <summary>Yöntem seçicisinin gösterdiği yazılar (sırasıyla).</summary>
    public IReadOnlyList<string> MethodLabels => CmbAnalysisType.Items
        .Cast<object>()
        .Select(i => (i as ComboBoxItem)?.Content as string ?? i as string ?? "")
        .Where(s => s.Length > 0)
        .ToList();

    /// <summary>
    /// Analiz türünün öğrenciye gösterilen adı, yöntem seçicisinde yazdığı gibi
    /// ("THREE_PHASE" → "Üç Faz"). Bilinmeyen türde listedeki ilk yöntemin adı (iç ad asla).
    /// </summary>
    public string MethodDisplayName(string? analysisType)
    {
        var labels = MethodLabels;
        return MethodLabelFor(labels, analysisType)
            ?? MethodLabelFor(labels, AnalysisTypes.Nodal)
            ?? "";
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
        // Kutu Güç ve Üç Faz yöntemlerinde görünür; ikisinde de çözücüye gönderilir
        if (string.Equals(analysisType, AnalysisTypes.Power, StringComparison.OrdinalIgnoreCase) ||
            string.Equals(analysisType, AnalysisTypes.ThreePhase, StringComparison.OrdinalIgnoreCase))
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

        string? reciprocityTarget = null;
        if (string.Equals(analysisType, AnalysisTypes.Reciprocity, StringComparison.OrdinalIgnoreCase))
        {
            reciprocityTarget = GetSelectedTerminal(CmbReciprocityTarget);
        }

        SetZenerRangeGivenError(null);

        string? zenerRangeTarget = null;
        double? zenerRangeGivenMin = null;
        double? zenerRangeGivenMax = null;
        if (string.Equals(analysisType, AnalysisTypes.ZenerRange, StringComparison.OrdinalIgnoreCase))
        {
            zenerRangeTarget = GetSelectedTerminal(CmbZenerRangeTarget);
            if (!TryParseZenerRangeGiven(
                    TxtZenerRangeGivenMin?.Text,
                    TxtZenerRangeGivenMax?.Text,
                    out zenerRangeGivenMin,
                    out zenerRangeGivenMax,
                    out string? rangeError))
            {
                SetZenerRangeGivenError(rangeError);
                error = rangeError;
                return false;
            }
        }

        options = new SolveOptions(
            analysisType, freq, pos, neg, ValueDisplay, powerFactorTarget, reciprocityTarget,
            zenerRangeTarget, zenerRangeGivenMin, zenerRangeGivenMax);
        return true;
    }

    /// <summary>
    /// Zener Aralığı ters problemi için isteğe bağlı [min, maks] girişini ayrıştırır.
    /// İkisi de boşsa ileri mod (null, null); biri boşsa ya da min ≥ maks ise hata döndürür.
    /// </summary>
    internal static bool TryParseZenerRangeGiven(
        string? minText,
        string? maxText,
        out double? min,
        out double? max,
        out string? error)
    {
        min = null;
        max = null;
        error = null;

        string minTrim = minText?.Trim() ?? "";
        string maxTrim = maxText?.Trim() ?? "";

        if (minTrim.Length == 0 && maxTrim.Length == 0)
            return true;

        if (minTrim.Length == 0 || maxTrim.Length == 0)
        {
            error = "Değişim aralığı için alt ve üst sınırın ikisi de girilmelidir.";
            return false;
        }

        if (!TurkishNumber.TryParseSpice(minTrim, out double parsedMin) ||
            !TurkishNumber.TryParseSpice(maxTrim, out double parsedMax))
        {
            error = "Değişim aralığı geçerli bir sayı olmalıdır (ör. 120 V, 1 kΩ).";
            return false;
        }

        if (parsedMin >= parsedMax)
        {
            error = "Alt sınır, üst sınırdan küçük olmalıdır.";
            return false;
        }

        min = parsedMin;
        max = parsedMax;
        return true;
    }

    private static string? GetSelectedTerminal(ComboBox cmb)
    {
        return cmb.SelectedItem switch
        {
            string s => string.IsNullOrWhiteSpace(s) ? null : s.Trim(),
            ComboBoxItem cbi => string.IsNullOrWhiteSpace(cbi.Content?.ToString()) ? null : cbi.Content!.ToString()!.Trim(),
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
        UpdateStepNav();
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

    internal static StackPanel BuildExplanationSectionPanel(ExplanationSectionDto section)
    {
        // Bölümleri çizgi değil boşluk ayırır (DESIGN.md, "Şekil ve boşluk")
        var sectionPanel = new StackPanel { Margin = new Thickness(0, 0, 0, 26) };

        var titleText = new TextBlock
        {
            Text = section.Title,
            Margin = new Thickness(0, 0, 0, 10)
        };
        titleText.SetResourceReference(StyleProperty, "Text.ReadingHeading");
        SubscriptText.Apply(titleText);
        sectionPanel.Children.Add(titleText);

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
                tb.SetResourceReference(StyleProperty, "Text.Reading");
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

        // Değerler arka uçtan da gelebilir ("3.033∠-72.34°"): eksi işareti ekranda Unicode "−"
        var val = new TextBlock
        {
            Text = PhasorText.KeepTogether(TurkishNumber.DisplayMinus(primaryValue)),
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
                Text = PhasorText.KeepTogether(TurkishNumber.DisplayMinus(secondaryValue)),
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

    /// <summary>
    /// Düğüm kutucuğunun başlığı: "V4", üç fazlı elemanın ucundaysa API'nin verdiği adla
    /// "V4 · R fazı (Y1)"; düğüm 0 her zaman "0 (GND)".
    /// </summary>
    internal static string NodeTileTitle(string key, string? label)
    {
        if (key == "0")
            return "0 (GND)";
        return string.IsNullOrWhiteSpace(label) || label == "GND" ? $"V{key}" : $"V{key} · {label}";
    }

    internal static string FormatDiodeModel(string? model) => (model ?? "").Trim().ToUpperInvariant() switch
    {
        "SI" => "Si",
        "GE" => "Ge",
        "IDEAL" => "İdeal",
        "ZENER" => "Zener",
        var m when !string.IsNullOrEmpty(m) => model!.Trim(),
        _ => "Si",
    };

    internal static string FormatDiodeState(string? state) => (state ?? "").Trim().ToUpperInvariant() switch
    {
        "ON" => "iletimde",
        "ZENER" => "ters iletimde (V_Z)",
        "OFF" => "yalıtımda",
        _ => state?.Trim() ?? "",
    };

    internal static string FormatDiodeLine(DiodeResultDto diode)
    {
        bool isZener = string.Equals(diode.Model?.Trim(), "ZENER", StringComparison.OrdinalIgnoreCase);
        string model = isZener && diode.Vz.HasValue
            ? $"Zener, V_Z = {FormatDiodeVoltage(diode.Vz.Value)}"
            : FormatDiodeModel(diode.Model);
        string state = FormatDiodeState(diode.State);
        string vAk = FormatDiodeVoltage(diode.VAk);
        string current = EngFormat.Format(diode.I, "A");
        string currentSymbol = isZener ? "I_Z" : "I";
        return $"{diode.Id} ({model}): {state} · V_AK = {vAk} · {currentSymbol} = {current}";
    }

    /// <summary>
    /// Diyot gerilimi kitaptaki gibi volt olarak: 0,7 V (700 mV değil), 4,3 V, −8 V.
    /// 1 mV altı ve 1000 V üstü değerler olağan önekli biçimde kalır.
    /// </summary>
    internal static string FormatDiodeVoltage(double v)
    {
        double a = Math.Abs(v);
        if (a < 1e-3 || a >= 1000 || double.IsNaN(v))
            return EngFormat.Format(v, "V");
        string s = a.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture).Replace('.', ',');
        return (v < 0 ? "−" : "") + s + " V";
    }

    /// <summary>Ters problemde verilen değişim aralığı satırı (ileri modda null).</summary>
    internal static string? FormatZenerGiven(ZenerRangeDto zr)
    {
        if (!zr.IsInverse || zr.Given == null)
            return null;
        string sym = !string.IsNullOrWhiteSpace(zr.Given.Symbol)
            ? zr.Given.Symbol
            : (!string.IsNullOrWhiteSpace(zr.TargetId) ? zr.TargetId : "x");
        string unit = zr.Given.Unit ?? "";
        return $"Verilen: {EngFormat.Format(zr.Given.Min, unit)} ≤ {sym} ≤ {EngFormat.Format(zr.Given.Max, unit)}";
    }

    /// <summary>Sağlama tablosunun ilk sütun başlığı: ters problemde verilen büyüklük, ileri modda hedef sembol.</summary>
    internal static string ZenerCheckXSymbol(ZenerRangeDto zr)
    {
        if (zr.IsInverse && !string.IsNullOrWhiteSpace(zr.Given?.Symbol))
            return zr.Given.Symbol;
        return !string.IsNullOrWhiteSpace(zr.Symbol) ? zr.Symbol : "x";
    }

    /// <summary>Sağlama tablosundaki x değerlerinin birimi: ters problemde verilen büyüklüğün birimi.</summary>
    internal static string ZenerCheckXUnit(ZenerRangeDto zr)
    {
        if (zr.IsInverse && zr.Given != null)
            return zr.Given.Unit ?? "";
        return zr.Unit ?? "";
    }

    /// <summary>Zener çalışma aralığı veya ters problem cevabı metni.</summary>
    internal static string FormatZenerRange(ZenerRangeDto zr)
    {
        if (zr.IsInverse && !zr.Feasible)
            return "Bu aralık için uygun değer yok";

        string sym = !string.IsNullOrWhiteSpace(zr.Symbol)
            ? zr.Symbol
            : (!string.IsNullOrWhiteSpace(zr.AnswerId) ? zr.AnswerId : (!string.IsNullOrWhiteSpace(zr.TargetId) ? zr.TargetId : "x"));
        string unit = zr.Unit ?? "";

        if (zr.IsInverse && zr.Unique)
        {
            double? val = zr.Min ?? zr.Max;
            if (val.HasValue)
                return $"{sym} = {EngFormat.Format(val.Value, unit)}";
        }

        if (zr.Min.HasValue && zr.Max.HasValue)
            return $"{EngFormat.Format(zr.Min.Value, unit)} ≤ {sym} ≤ {EngFormat.Format(zr.Max.Value, unit)}";
        if (zr.Min.HasValue)
            return $"{sym} ≥ {EngFormat.Format(zr.Min.Value, unit)} (üst sınır yok)";
        if (zr.Max.HasValue)
            return $"{sym} ≤ {EngFormat.Format(zr.Max.Value, unit)}";
        return "Geçerli aralık bulunamadı";
    }

    /// <summary>Devredeki mevcut değerin aralığın içinde/dışında olma ya da tekil çözümle karşılaştırma cümlesi (bilgi yoksa null).</summary>
    internal static string? FormatZenerCurrentStatus(ZenerRangeDto zr)
    {
        if (zr.IsInverse && !zr.Feasible)
            return null;

        string elem = zr.IsInverse
            ? (!string.IsNullOrWhiteSpace(zr.AnswerId) ? zr.AnswerId : (!string.IsNullOrWhiteSpace(zr.Symbol) ? zr.Symbol : zr.TargetId))
            : (!string.IsNullOrWhiteSpace(zr.TargetId) ? zr.TargetId : zr.Symbol);
        string unit = zr.Unit ?? "";

        if (zr.IsInverse && zr.Unique)
        {
            double? found = zr.Min ?? zr.Max;
            if (!zr.CurrentValue.HasValue || !found.HasValue)
                return null;
            return $"Devredeki {elem} = {EngFormat.Format(zr.CurrentValue.Value, unit)}, bulunan değer {EngFormat.Format(found.Value, unit)}";
        }

        if (!zr.CurrentValue.HasValue || !zr.CurrentInside.HasValue)
            return null;
        string valText = EngFormat.Format(zr.CurrentValue.Value, unit);
        return zr.CurrentInside.Value
            ? $"Devredeki {elem} = {valText} aralığın içinde ✓"
            : $"Devredeki {elem} = {valText} aralığın dışında";
    }

    /// <summary>Zener aralığı adım değeri: sayı varsa EngFormat ile, yoksa metin alanı.</summary>
    internal static string FormatZenerStepValue(ZenerRangeStepDto step)
    {
        if (step.Value.HasValue)
            return EngFormat.Format(step.Value.Value, step.Unit ?? "");
        if (!string.IsNullOrWhiteSpace(step.Text))
            return TurkishNumber.NormalizeForDisplay(step.Text);
        return "—";
    }

    /// <summary>Sağlama satırı kararı: OK yeşil, BELOW/ABOVE uyarı fırçasıyla.</summary>
    internal static (string Text, string BrushKey) FormatZenerVerdict(string? verdict) =>
        (verdict ?? "").Trim().ToUpperInvariant() switch
        {
            "OK" => ("Uygun ✓", "Brush.Success"),
            "BELOW" => ("Altında", "Brush.Warning"),
            "ABOVE" => ("Üstünde", "Brush.Warning"),
            var other when !string.IsNullOrEmpty(other) => (verdict!.Trim(), "Brush.Text.Secondary"),
            _ => ("—", "Brush.Text.Secondary"),
        };

    private Border BuildZenerRangeCard(ZenerRangeDto zr)
    {
        var card = new Border
        {
            Padding = new Thickness(14),
            Margin = new Thickness(0, 0, 0, 12)
        };
        card.SetResourceReference(StyleProperty, "Card.Embedded");

        var stack = new StackPanel();

        // Aralık başlığı, ters problemde verilen aralık satırı ve büyük cevap metni
        var lblTitle = new TextBlock
        {
            Text = "Zener Aralığı",
            Margin = new Thickness(0, 0, 0, 4)
        };
        lblTitle.SetResourceReference(StyleProperty, "Text.Caption");
        stack.Children.Add(lblTitle);

        if (FormatZenerGiven(zr) is { } givenText)
        {
            var txtGiven = new TextBlock
            {
                Text = givenText,
                FontSize = 12,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 2)
            };
            txtGiven.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
            SubscriptText.Apply(txtGiven);
            stack.Children.Add(txtGiven);
        }

        var txtRange = new TextBlock
        {
            Text = FormatZenerRange(zr),
            FontSize = 18,
            FontWeight = FontWeights.SemiBold,
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 0, 0, 4)
        };
        txtRange.SetResourceReference(
            TextBlock.ForegroundProperty,
            zr.IsInverse && !zr.Feasible ? "Brush.Warning" : "Brush.Text.Primary");
        SubscriptText.Apply(txtRange);
        stack.Children.Add(txtRange);

        // Devredeki mevcut değer aralığın içinde mi / tekil çözümle karşılaştırma
        if (FormatZenerCurrentStatus(zr) is { } statusText)
        {
            var txtStatus = new TextBlock
            {
                Text = statusText,
                FontSize = 13,
                FontWeight = FontWeights.SemiBold,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 2, 0, 10)
            };
            string statusBrush = zr.CurrentInside == true
                ? "Brush.Success"
                : (zr.IsInverse && zr.Unique ? "Brush.Text.Secondary" : "Brush.Warning");
            txtStatus.SetResourceReference(TextBlock.ForegroundProperty, statusBrush);
            SubscriptText.Apply(txtStatus);
            stack.Children.Add(txtStatus);
        }

        // Kompakt hesap adımları tablosu (symbol = value)
        if (zr.Steps is { Count: > 0 })
        {
            var stepsCard = new Border { Margin = new Thickness(0, 4, 0, 10) };
            stepsCard.SetResourceReference(StyleProperty, "Card.Inset");

            var stepsGrid = new Grid();
            stepsGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            stepsGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

            for (int r = 0; r < zr.Steps.Count; r++)
            {
                var step = zr.Steps[r];
                stepsGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

                var symTb = new TextBlock
                {
                    Text = string.IsNullOrWhiteSpace(step.Symbol) ? "—" : step.Symbol,
                    FontSize = 12,
                    FontWeight = FontWeights.SemiBold,
                    Margin = new Thickness(2, 2, 12, 2)
                };
                symTb.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
                SubscriptText.Apply(symTb);
                Grid.SetRow(symTb, r);
                Grid.SetColumn(symTb, 0);
                stepsGrid.Children.Add(symTb);

                var valTb = new TextBlock
                {
                    Text = FormatZenerStepValue(step),
                    FontSize = 12,
                    TextWrapping = TextWrapping.Wrap,
                    Margin = new Thickness(2, 2, 2, 2)
                };
                valTb.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
                valTb.SetResourceReference(TextBlock.FontFamilyProperty, "Font.Mono");
                Grid.SetRow(valTb, r);
                Grid.SetColumn(valTb, 1);
                stepsGrid.Children.Add(valTb);
            }

            stepsCard.Child = stepsGrid;
            stack.Children.Add(stepsCard);
        }

        // Sağlama tablosu
        if (zr.Checks is { Count: > 0 })
        {
            var checksHeader = new TextBlock
            {
                Text = "Sağlama",
                FontSize = 12,
                FontWeight = FontWeights.SemiBold,
                Margin = new Thickness(0, 2, 0, 6)
            };
            checksHeader.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
            stack.Children.Add(checksHeader);

            var checksCard = new Border { Margin = new Thickness(0, 0, 0, 10) };
            checksCard.SetResourceReference(StyleProperty, "Card.Inset");

            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            string xColHeader = ZenerCheckXSymbol(zr);
            string xColUnit = ZenerCheckXUnit(zr);
            string[] headers = { xColHeader, "Durum", "V_Y", "I_Z", "Karar" };
            for (int c = 0; c < headers.Length; c++)
            {
                var th = new TextBlock
                {
                    Text = headers[c],
                    FontSize = 11,
                    FontWeight = FontWeights.SemiBold,
                    Margin = new Thickness(2, 0, 8, 4)
                };
                th.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
                SubscriptText.Apply(th);
                Grid.SetRow(th, 0);
                Grid.SetColumn(th, c);
                grid.Children.Add(th);
            }

            for (int i = 0; i < zr.Checks.Count; i++)
            {
                var chk = zr.Checks[i];
                int row = i + 1;
                grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

                var (verdictText, verdictBrush) = FormatZenerVerdict(chk.Verdict);
                string[] vals =
                {
                    EngFormat.Format(chk.X, xColUnit),
                    FormatDiodeState(chk.State),
                    FormatDiodeVoltage(chk.VY),
                    EngFormat.Format(chk.IZ, "A"),
                    verdictText,
                };

                for (int c = 0; c < vals.Length; c++)
                {
                    var td = new TextBlock
                    {
                        Text = vals[c],
                        FontSize = 11,
                        Margin = new Thickness(2, 2, 8, 2),
                        TextWrapping = c == 1 ? TextWrapping.Wrap : TextWrapping.NoWrap
                    };

                    if (c == 4)
                    {
                        td.FontWeight = FontWeights.SemiBold;
                        td.SetResourceReference(TextBlock.ForegroundProperty, verdictBrush);
                    }
                    else if (c == 1)
                    {
                        td.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
                        SubscriptText.Apply(td);
                    }
                    else
                    {
                        td.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
                        td.SetResourceReference(TextBlock.FontFamilyProperty, "Font.Mono");
                    }

                    Grid.SetRow(td, row);
                    Grid.SetColumn(td, c);
                    grid.Children.Add(td);
                }
            }

            checksCard.Child = grid;
            stack.Children.Add(checksCard);
        }

        // V_Y(x) grafiği
        if (zr.Curve is { X.Count: > 0, VY.Count: > 0 })
        {
            var plotView = new ZenerRangePlotView { Margin = new Thickness(0, 4, 0, 0) };
            plotView.LoadData(zr);
            plotView.EnlargeClicked += (_, _) => EnlargeZenerRangeRequested?.Invoke(this, zr);
            stack.Children.Add(plotView);
        }

        card.Child = stack;
        return card;
    }

    /// <summary>
    /// Üç faz sonuçları, anlatımdaki adlarla (V_RN, V_RS, I_R, I_N, V_N′N, I_RS) bölüm bölüm.
    /// Değerler kutupsal (büyüklük∠açı), önekli birimle.
    /// </summary>
    internal static List<(string Header, List<(string Title, string Value)> Items)> ThreePhaseSections(ThreePhaseResultDto tp)
    {
        static string V(ComplexNumberDto c, string unit) => EngFormat.Format(ResultValue.FromComplex(c), unit);
        static List<(string, string)> Tiles(Dictionary<string, ComplexNumberDto> d, Func<string, string> title, string unit) =>
            d.Select(kv => (title(kv.Key), V(kv.Value, unit))).ToList();

        var sections = new List<(string, List<(string, string)>)>();
        if (tp.PhaseVoltages is { Count: > 0 } pv)
            sections.Add(("Kaynağın faz gerilimleri", Tiles(pv, k => $"V_{k}N", "V")));
        if (tp.LineVoltages is { Count: > 0 } lv)
            sections.Add(("Hat gerilimleri", Tiles(lv, k => $"V_{k}", "V")));
        if (tp.LineCurrents is { Count: > 0 } lc)
        {
            var tiles = Tiles(lc, k => $"I_{k}", "A");
            if (tp.NeutralCurrent != null)
                tiles.Add(("I_N", V(tp.NeutralCurrent, "A")));
            sections.Add(("Hat akımları", tiles));
        }
        if (tp.LoadVoltages is { Count: > 0 } ldv)
        {
            bool delta = string.Equals(tp.Load, "D", StringComparison.OrdinalIgnoreCase);
            var tiles = Tiles(ldv, k => delta ? $"V_{k}" : $"V_{k}N′", "V");
            if (tp.LoadNeutralVoltage != null)
                tiles.Add(("V_N′N", V(tp.LoadNeutralVoltage, "V")));
            sections.Add((delta ? "Üçgen yükün kol gerilimleri" : "Yıldız yükün kol gerilimleri", tiles));
        }
        if (tp.LoadPhaseCurrents is { Count: > 0 } phc)
            sections.Add(("Üçgen yükün faz akımları", Tiles(phc, k => $"I_{k}", "A")));
        return sections;
    }

    private StackPanel BuildResultsPanel(AnalysisResponseDto response)
    {
        var panel = new StackPanel();

        // Zener aralığı kartı (Sonuçlar sekmesinin en üstünde)
        if (response.ZenerRangeResult is { } zenerRange)
        {
            panel.Children.Add(BuildZenerRangeCard(zenerRange));
        }

        // Üç faz: kaynak ve yükün faz/hat gerilimleri ve akımları (anlatımdaki adlarla) en başta
        if (response.ThreePhaseResult is { } threePhase)
        {
            foreach (var (header, items) in ThreePhaseSections(threePhase))
            {
                AddSectionHeader(panel, header);
                panel.Children.Add(CreateTwoColumnGrid(items
                    .Select(t => CreateValueTile(t.Title, t.Value))
                    .ToList<UIElement>()));
            }
        }

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
                string nodeName = NodeTileTitle(kvp.Key, kvp.Value.Label);
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

        if (response.WattmeterResults is { Count: > 0 } wattmeters)
        {
            AddSectionHeader(panel, "Wattmetre okumaları");
            panel.Children.Add(CreateTwoColumnGrid(wattmeters
                .Select(w => CreateValueTile(w.Id, EngFormat.Format(w.P, "W")))
                .ToList<UIElement>()));
        }

        if (response.DiodeResults is { Count: > 0 } diodes)
        {
            AddSectionHeader(panel, "Diyotlar");
            var diodeList = new StackPanel { Margin = new Thickness(0, 0, 0, 12) };
            foreach (var d in diodes)
            {
                var rowCard = new Border { Margin = new Thickness(0, 0, 0, 6) };
                rowCard.SetResourceReference(StyleProperty, "Card.Inset");

                var tb = new TextBlock
                {
                    Text = FormatDiodeLine(d),
                    TextWrapping = TextWrapping.Wrap,
                    FontSize = 13.5
                };
                tb.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
                SubscriptText.Apply(tb);
                rowCard.Child = tb;
                diodeList.Children.Add(rowCard);
            }
            panel.Children.Add(diodeList);
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
                // Bir satırdaki P, Q, S tek önekle ("950 W | 1,2 kVAR" yerine "0,95 kW | 1,2 kVAR")
                var pqs = EngFormat.FormatGroup(
                    new[] { el.ActivePower, el.ReactivePower, el.ApparentPower }, new[] { "W", "VAR", "VA" });
                string pStr = pqs[0];
                string qStr = pqs[1];
                string sStr = pqs[2];
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
