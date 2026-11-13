using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Shapes;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views;

// AnalysisPanel parçası: anlatımın adım zinciri (DESIGN.md, "Adım zinciri").
// Her bölüm dikey bir çizgiye bağlı numaralı bir adımdır. Kapalı adımda başlık ve tek
// satırlık özet görünür; aynı anda bir adım açıktır ("Tümünü aç" hepsini açar).
// Önceki / Sonraki zinciri bir adım ilerletir. Yazdırma bu zinciri kullanmaz.
public partial class AnalysisPanel
{
    private static readonly Regex StepNumberPrefix = new(@"^\s*\d+\.\s*Adım\s*[—–-]\s*", RegexOptions.Compiled);

    /// <summary>
    /// Zincir her adımı kendisi numaralar; anlatımın kendi "1. Adım — Vth" numarası çift
    /// numara olurdu ("6" dairesinde "1. Adım"). Zincirde yalnız konu kalır: "Vth (Açık Devre Gerilimi)".
    /// </summary>
    internal static string ChainTitle(string? title) => StepNumberPrefix.Replace(title ?? string.Empty, string.Empty);

    private sealed class StepItem
    {
        public required Grid Root { get; init; }
        public required Border Circle { get; init; }
        public required TextBlock Mark { get; init; }
        public required Rectangle Line { get; init; }
        public required ToggleButton Header { get; init; }
        public required TextBlock Title { get; init; }
        public required TextBlock Summary { get; init; }
        public required StackPanel Body { get; init; }
    }

    private readonly List<StepItem> _steps = new();
    private int _openStep = -1;
    private bool _allStepsOpen;
    private Button? _btnToggleAllSteps;

    /// <summary>Zincirdeki adımlar; anlatım görünmüyorsa boş.</summary>
    internal IReadOnlyList<FrameworkElement> StepSections =>
        IsExplanationViewSelected && _explanationPanel != null && ResultsContainer.Children.Contains(_explanationPanel)
            ? _steps.Select(s => (FrameworkElement)s.Root).ToList()
            : Array.Empty<FrameworkElement>();

    /// <summary>Açık (okunan) adımın sırası, 0'dan; hiçbiri açık değilse −1.</summary>
    internal int CurrentStepIndex => StepSections.Count == 0 ? -1 : _openStep;

    /// <summary>Bütün adımlar açık mı ("Tümünü aç")?</summary>
    internal bool AllStepsOpen => _allStepsOpen;

    /// <summary>Bir adımın gövdesi (açıklama, denklemler) görünüyor mu?</summary>
    internal bool IsStepOpen(int index) =>
        index >= 0 && index < _steps.Count && _steps[index].Body.Visibility == Visibility.Visible;

    private StackPanel BuildStepChain(List<ExplanationSectionDto> sections)
    {
        _steps.Clear();
        var panel = new StackPanel();

        var top = new Grid { Margin = new Thickness(0, 0, 0, 10) };
        top.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        top.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var count = new TextBlock
        {
            Text = $"{sections.Count} adımda çözüm",
            FontWeight = FontWeights.SemiBold,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(2, 0, 0, 0)
        };
        count.SetResourceReference(StyleProperty, "Text.Caption");
        top.Children.Add(count);
        _btnToggleAllSteps = new Button { Content = "Tümünü aç", Height = 28, FontSize = 12, Padding = new Thickness(10, 0, 10, 0) };
        _btnToggleAllSteps.SetResourceReference(StyleProperty, "Button.Ghost");
        _btnToggleAllSteps.SetResourceReference(ForegroundProperty, "Brush.Accent.SoftText");
        _btnToggleAllSteps.Click += (_, _) => SetAllStepsOpen(!_allStepsOpen);
        Grid.SetColumn(_btnToggleAllSteps, 1);
        top.Children.Add(_btnToggleAllSteps);
        panel.Children.Add(top);

        for (int i = 0; i < sections.Count; i++)
        {
            var item = BuildStepItem(sections[i], i);
            _steps.Add(item);
            panel.Children.Add(item.Root);
        }

        _allStepsOpen = false;
        _openStep = sections.Count > 0 ? 0 : -1;
        ApplyStepState();
        return panel;
    }

    private StepItem BuildStepItem(ExplanationSectionDto section, int index)
    {
        var root = new Grid();
        root.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(38) }); // 26 px yuvarlak + 12 px boşluk
        root.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        // Sol sütun: numaralı yuvarlak ve bir sonraki adıma inen çizgi
        var rail = new Grid { Margin = new Thickness(0, 0, 12, 0) };
        rail.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        rail.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        var mark = new TextBlock
        {
            FontSize = 12,
            FontWeight = FontWeights.Bold,
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center
        };
        var circle = new Border
        {
            Width = 26,
            Height = 26,
            CornerRadius = new CornerRadius(13),
            BorderThickness = new Thickness(1.5),
            Margin = new Thickness(0, 7, 0, 0),
            Child = mark
        };
        rail.Children.Add(circle);
        var line = new Rectangle { Width = 2, MinHeight = 12, RadiusX = 1, RadiusY = 1, Margin = new Thickness(0, 4, 0, 0) };
        Grid.SetRow(line, 1);
        rail.Children.Add(line);
        root.Children.Add(rail);

        // Sağ sütun: başlık + özet (tıklanınca açılır), altında adımın içeriği
        var content = new StackPanel();
        Grid.SetColumn(content, 1);

        var title = new TextBlock { Text = ChainTitle(section.Title) };
        title.SetResourceReference(StyleProperty, "Text.ReadingHeading");
        title.FontSize = 15;
        title.LineHeight = 22;
        SubscriptText.Apply(title);
        var summary = new TextBlock
        {
            Text = SummarizeStep(section),
            TextTrimming = TextTrimming.CharacterEllipsis,
            TextWrapping = TextWrapping.NoWrap,
            FontSize = 13,
            Margin = new Thickness(0, 1, 0, 0)
        };
        summary.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
        SubscriptText.Apply(summary);
        var headStack = new StackPanel();
        headStack.Children.Add(title);
        headStack.Children.Add(summary);

        var header = new ToggleButton
        {
            Content = headStack,
            Height = double.NaN,
            Padding = new Thickness(8, 6, 8, 6),
            Margin = new Thickness(-8, 0, 0, 0),
            HorizontalContentAlignment = HorizontalAlignment.Stretch
        };
        header.SetResourceReference(StyleProperty, "Button.Nav");
        System.Windows.Automation.AutomationProperties.SetName(header, $"Adım {index + 1}: {ChainTitle(section.Title)}");
        header.Click += (_, _) => OnStepHeaderClicked(index);
        content.Children.Add(header);

        var body = new StackPanel { Margin = new Thickness(0, 6, 0, 4) };
        foreach (var block in section.Blocks ?? new List<ExplanationBlockDto>())
        {
            if (CreateBlockElement(block) is { } el)
                body.Children.Add(el);
        }
        content.Children.Add(body);
        root.Children.Add(content);

        return new StepItem
        {
            Root = root,
            Circle = circle,
            Mark = mark,
            Line = line,
            Header = header,
            Title = title,
            Summary = summary,
            Body = body
        };
    }

    internal void OnStepHeaderClicked(int index)
    {
        // Açık adımın başlığına basmak onu kapatır; "Tümünü aç" açıkken yalnız seçer
        _openStep = index == _openStep && !_allStepsOpen ? -1 : index;
        ApplyStepState();
        ScrollToStep(_openStep);
    }

    internal void SetAllStepsOpen(bool open)
    {
        _allStepsOpen = open;
        if (!open && _openStep < 0 && _steps.Count > 0)
            _openStep = 0;
        ApplyStepState();
    }

    /// <summary>Bir sonraki (+1) ya da önceki (−1) adımı açar ve başına kaydırır.</summary>
    internal void GoToStep(int delta)
    {
        if (StepSections.Count == 0)
            return;
        int from = _openStep < 0 ? (delta > 0 ? -1 : _steps.Count) : _openStep;
        _openStep = Math.Clamp(from + delta, 0, _steps.Count - 1);
        ApplyStepState();
        ScrollToStep(_openStep);
    }

    private void BtnPrevStep_Click(object sender, RoutedEventArgs e) => GoToStep(-1);

    private void BtnNextStep_Click(object sender, RoutedEventArgs e) => GoToStep(+1);

    /// <summary>Yuvarlakları, çizgileri, açık/kapalı gövdeleri ve alttaki geçişi günceller.</summary>
    private void ApplyStepState()
    {
        int n = _steps.Count;
        for (int i = 0; i < n; i++)
        {
            var s = _steps[i];
            bool isCurrent = i == _openStep;
            bool done = _openStep >= 0 && i < _openStep;
            bool isOpen = _allStepsOpen || isCurrent;

            s.Body.Visibility = isOpen ? Visibility.Visible : Visibility.Collapsed;
            s.Summary.Visibility = isOpen ? Visibility.Collapsed : Visibility.Visible;
            s.Root.Margin = new Thickness(0, 0, 0, isOpen ? 14 : 6);
            s.Header.IsChecked = isOpen;

            // Geçilen adım ✓ ile soluk mavi, okunan adım dolu mavi, gelecek adımlar boş halka
            s.Mark.Text = done ? "✓" : (i + 1).ToString();
            s.Circle.SetResourceReference(Border.BackgroundProperty,
                isCurrent ? "Brush.Accent" : done ? "Brush.Accent.Soft" : "Brush.Bg.Surface");
            s.Circle.SetResourceReference(Border.BorderBrushProperty,
                isCurrent ? "Brush.Accent" : done ? "Brush.Accent.Soft" : "Brush.Border.Strong");
            s.Mark.SetResourceReference(TextBlock.ForegroundProperty,
                isCurrent ? "Brush.Text.OnAccent" : done ? "Brush.Accent.SoftText" : "Brush.Text.Secondary");
            s.Line.Visibility = i == n - 1 ? Visibility.Hidden : Visibility.Visible;
            s.Line.SetResourceReference(Shape.FillProperty, done ? "Brush.Accent.Soft" : "Brush.Border.Default");
            if (isCurrent)
                s.Title.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Accent.SoftText");
            else
                s.Title.ClearValue(TextBlock.ForegroundProperty);
        }
        if (_btnToggleAllSteps != null)
            _btnToggleAllSteps.Content = _allStepsOpen ? "Tümünü kapat" : "Tümünü aç";
        UpdateStepNav();
    }

    private void UpdateStepNav()
    {
        int n = StepSections.Count;
        if (n < 2)
        {
            StepNavBar.Visibility = Visibility.Collapsed;
            return;
        }
        StepNavBar.Visibility = Visibility.Visible;
        int k = _openStep;
        TxtStepLabel.Text = k >= 0 ? $"Adım {k + 1} / {n} · {_steps[k].Title.Text}" : $"{n} adım";
        BtnPrevStep.IsEnabled = k != 0;
        BtnNextStep.IsEnabled = k < n - 1;
    }

    /// <summary>Adımın başını görünür yapar (açılıp kapanan gövdeler yerleştikten sonra).</summary>
    private void ScrollToStep(int index)
    {
        if (index < 0 || index >= _steps.Count)
            return;
        ResultsScrollViewer.UpdateLayout();
        try
        {
            double top = _steps[index].Root.TranslatePoint(new Point(0, 0), ResultsContainer).Y + ResultsContainer.Margin.Top;
            double offset = Math.Clamp(top - 8, 0, ResultsScrollViewer.ScrollableHeight);
            ResultsScrollViewer.ScrollToVerticalOffset(offset);
        }
        catch (InvalidOperationException)
        {
            // henüz ekrana yerleşmemiş
        }
    }

    // ── Kapalı adımın tek satırlık özeti ──
    // Sıra: sonuçlar, kontroller, düğüm/çevre denklemleri, kısa denklemler, ilk cümle.

    private static readonly Regex TrailingNote = new(@"\s*\([^()]*\)\s*$");
    private static readonly Regex EquationLine = new(@"^(Düğüm|Çevre) \d+:");

    /// <summary>"x = … = son (açıklama)" → "x = son".</summary>
    internal static string ShortEquation(string text)
    {
        var parts = TrailingNote.Replace(text.Trim(), "").Split(" = ");
        return parts.Length > 2 ? $"{parts[0]} = {parts[^1]}" : string.Join(" = ", parts);
    }

    internal static string SummarizeStep(ExplanationSectionDto section)
    {
        var blocks = section.Blocks ?? new List<ExplanationBlockDto>();
        List<string> Of(string kind) => blocks
            .Where(b => string.Equals(b.Kind, kind, StringComparison.OrdinalIgnoreCase) && !string.IsNullOrWhiteSpace(b.Text))
            .Select(b => b.Text.Trim())
            .ToList();

        var results = Of("result");
        if (results.Count > 0)
            return string.Join(" · ", results.Select(ShortEquation));

        var checks = Of("check");
        if (checks.Count == 1)
            return checks[0].Split(':')[0].TrimStart('✓', ' ') + " ✓";
        if (checks.Count > 1)
            return $"{checks.Count} kontrol tuttu ✓";

        var math = Of("math");
        int equations = math.Count(m => EquationLine.IsMatch(m));
        if (equations > 0)
            return $"{equations} bilinmeyen için {equations} denklem";
        if (math.Count > 0)
            return string.Join(" · ", math.Take(2).Select(ShortEquation)) + (math.Count > 2 ? " · …" : "");

        return Of("text").FirstOrDefault() ?? "";
    }
}

