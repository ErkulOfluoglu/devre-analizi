using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
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
    public event EventHandler<WaveformResultDto>? EnlargeWaveformRequested;

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

    private int? _problemCode;

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

    private AnalysisResponseDto? _lastPracticeResponse;

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
        UpdateWaveformOutputVisibility();   // Gösterim satırı yönteme de bağlı
        TxtFrequencyLabel.Text = needsFrequency
            ? "Frekans (Hz) — gerekli"
            : "Frekans (Hz) — boş bırakılırsa kaynaktan alınır";
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
        else if (string.Equals(analysisType, AnalysisTypes.Waveform, StringComparison.OrdinalIgnoreCase))
        {
            CmbAnalysisType.SelectedIndex = 14;
        }
        else
        {
            CmbAnalysisType.SelectedIndex = 0;
        }

        UpdateTerminalsVisibility();
        UpdatePowerFactorTargetVisibility();
        UpdateReciprocityTargetVisibility();
        UpdateZenerRangeTargetVisibility();
        UpdateWaveformOutputVisibility();

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
            WaveformOutput = GetSelectedTerminal(CmbWaveformOutput),
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
        if (CmbWaveformOutput?.ItemsSource is IEnumerable<string> wfItems)
        {
            var candidates = wfItems as IReadOnlyList<string> ?? wfItems.ToList();
            CmbWaveformOutput.SelectedItem = ResolveWaveformOutput(candidates, settings.WaveformOutput);
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
        UpdateWaveformOutputVisibility();
        UpdateModeLabel();
    }

    /// <summary>Çözücü durumunun altındaki mod yazısı: "Geçici durum" / "Dalga şekli" yöntemde, yoksa AC / DC.</summary>
    internal static string ModeLabelText(bool hasAcSource, string analysisType) =>
        string.Equals(analysisType, AnalysisTypes.Transient, StringComparison.OrdinalIgnoreCase)
            ? "Geçici durum"
            : string.Equals(analysisType, AnalysisTypes.Waveform, StringComparison.OrdinalIgnoreCase)
                ? "Dalga şekli"
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

    private void UpdateWaveformOutputVisibility()
    {
        if (RowWaveformOutput == null) return;

        string selectedText = (CmbAnalysisType.SelectedItem as ComboBoxItem)?.Content as string
            ?? CmbAnalysisType.SelectedItem as string
            ?? "";

        bool isWaveform = string.Equals(AnalysisTypeFromText(selectedText), AnalysisTypes.Waveform, StringComparison.OrdinalIgnoreCase);
        RowWaveformOutput.Visibility = isWaveform ? Visibility.Visible : Visibility.Collapsed;
        // Dalga Şekli anlık (tepe) değerlerle çalışır; Etkin/Tepe seçimi sonucu değiştirmediği
        // için gösterilmez (doğrultulmuş dalganın etkin değeri V_m/√2 değildir, karışıklık olmasın).
        RowValueDisplay.Visibility = _hasAcSource && !isWaveform ? Visibility.Visible : Visibility.Collapsed;
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
        if (string.Equals(selectedText, "Dalga Şekli", StringComparison.Ordinal))
            return AnalysisTypes.Waveform;
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

        string? waveformOutput = null;
        if (string.Equals(analysisType, AnalysisTypes.Waveform, StringComparison.OrdinalIgnoreCase))
        {
            waveformOutput = GetSelectedTerminal(CmbWaveformOutput);
        }

        options = new SolveOptions(
            analysisType, freq, pos, neg, ValueDisplay, powerFactorTarget, reciprocityTarget,
            zenerRangeTarget, zenerRangeGivenMin, zenerRangeGivenMax, waveformOutput);
        return true;
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
}
