using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using CircuitAnalyzer.WPF.Controls;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views;

/// <summary>
/// Öğrenci alıştırma modu kontrolü.
/// Soruları listeler, öğrenci cevaplarını /practice/check ile kontrol eder,
/// adım adım ipuçları gösterir ve isteğe bağlı çözümü açar.
/// </summary>
public partial class PracticeView : UserControl
{
    public event EventHandler? RevealRequested;

    public Func<AnswerCheckRequestDto, Task<AnswerCheckResponseDto>>? AnswerChecker { get; set; }

    public IReadOnlyList<PracticeQuestionDto> Questions { get; private set; } = Array.Empty<PracticeQuestionDto>();

    public int CorrectCount => _rows.Values.Count(r => r.IsCorrect);

    public int HintsShown { get; private set; }

    public int HintsAvailable { get; private set; }

    private readonly Dictionary<string, QuestionRow> _rows = new(StringComparer.OrdinalIgnoreCase);
    private List<ExplanationSectionDto> _hintSections = new();

    private sealed class QuestionRow
    {
        public PracticeQuestionDto Question { get; }
        public TextBox AnswerBox { get; }
        public Icon StatusIcon { get; }
        public TextBlock FeedbackText { get; }
        public TextBlock UnderstoodText { get; }
        public string? LastStatus { get; set; }
        public string LastFeedback { get; set; } = "";
        public bool IsCorrect { get; set; }

        public QuestionRow(
            PracticeQuestionDto question,
            TextBox answerBox,
            Icon statusIcon,
            TextBlock feedbackText,
            TextBlock understoodText)
        {
            Question = question;
            AnswerBox = answerBox;
            StatusIcon = statusIcon;
            FeedbackText = feedbackText;
            UnderstoodText = understoodText;
        }
    }

    public PracticeView()
    {
        InitializeComponent();
    }

    public void Load(IReadOnlyList<PracticeQuestionDto> questions, IReadOnlyList<ExplanationSectionDto> explanation)
    {
        Questions = questions ?? Array.Empty<PracticeQuestionDto>();
        _rows.Clear();
        ContainerMain.Children.Clear();
        ContainerExtra.Children.Clear();
        HintsContainer.Children.Clear();

        TxtScore.Visibility = Visibility.Collapsed;
        BannerCongrats.Visibility = Visibility.Collapsed;
        if (BannerError != null) BannerError.Visibility = Visibility.Collapsed;
        TxtError.Visibility = Visibility.Collapsed;

        // "Sonuç" başlıklı son bölüm cevapları listelediği için ipuçlarından hariç tutulur
        var hintCandidates = (explanation ?? Array.Empty<ExplanationSectionDto>()).ToList();
        if (hintCandidates.Count > 0 && string.Equals(hintCandidates[^1].Title?.Trim(), "Sonuç", StringComparison.OrdinalIgnoreCase))
        {
            hintCandidates.RemoveAt(hintCandidates.Count - 1);
        }
        _hintSections = hintCandidates;
        HintsAvailable = _hintSections.Count;
        HintsShown = 0;

        if (TxtBtnHint != null)
            TxtBtnHint.Text = $"İpucu ({HintsShown}/{HintsAvailable})";
        BtnHint.IsEnabled = HintsAvailable > 0;

        bool hasMain = false;
        bool hasExtra = false;

        foreach (var q in Questions)
        {
            var card = CreateQuestionRowCard(q, out var row);
            _rows[q.Id] = row;

            if (string.Equals(q.Group, "extra", StringComparison.OrdinalIgnoreCase))
            {
                ContainerExtra.Children.Add(card);
                hasExtra = true;
            }
            else
            {
                ContainerMain.Children.Add(card);
                hasMain = true;
            }
        }

        HeaderMainSection.Visibility = hasMain ? Visibility.Visible : Visibility.Collapsed;
        ExpanderExtra.Visibility = hasExtra ? Visibility.Visible : Visibility.Collapsed;
        ExpanderExtra.IsExpanded = false;
    }

    public TextBox GetAnswerBox(string questionId)
    {
        if (_rows.TryGetValue(questionId, out var row))
            return row.AnswerBox;

        throw new KeyNotFoundException($"Bilinmeyen soru ID: '{questionId}'");
    }

    public string? GetStatus(string questionId)
    {
        return _rows.TryGetValue(questionId, out var row) ? row.LastStatus : null;
    }

    public string GetFeedback(string questionId)
    {
        return _rows.TryGetValue(questionId, out var row) ? row.LastFeedback : "";
    }

    public async Task CheckAsync()
    {
        if (BannerError != null) BannerError.Visibility = Visibility.Collapsed;
        TxtError.Visibility = Visibility.Collapsed;
        TxtError.Text = "";

        var items = new List<AnswerCheckItemDto>();
        foreach (var q in Questions)
        {
            if (!_rows.TryGetValue(q.Id, out var row))
                continue;

            if (row.IsCorrect)
                continue;

            string text = row.AnswerBox.Text?.Trim() ?? "";
            if (string.IsNullOrEmpty(text))
                continue;

            items.Add(new AnswerCheckItemDto
            {
                Question = q,
                Answer = text
            });
        }

        if (items.Count == 0)
        {
            TxtError.Text = "Önce en az bir cevap yazın.";
            TxtError.Visibility = Visibility.Visible;
            if (BannerError != null) BannerError.Visibility = Visibility.Visible;
            return;
        }

        if (AnswerChecker == null)
        {
            TxtError.Text = "Çözücü hazır değil.";
            TxtError.Visibility = Visibility.Visible;
            if (BannerError != null) BannerError.Visibility = Visibility.Visible;
            return;
        }

        BtnCheck.IsEnabled = false;
        try
        {
            var req = new AnswerCheckRequestDto { Items = items };
            var res = await AnswerChecker(req);

            if (res.Verdicts != null)
            {
                foreach (var verdict in res.Verdicts)
                {
                    if (!_rows.TryGetValue(verdict.QuestionId, out var row))
                        continue;

                    row.LastStatus = verdict.Status;
                    row.LastFeedback = verdict.Message ?? "";

                    string iconKey;
                    string colorToken;
                    switch (verdict.Status?.ToLowerInvariant())
                    {
                        case AnswerStatuses.Correct:
                            iconKey = "Icon.Check";
                            colorToken = "Brush.Success";
                            break;
                        case AnswerStatuses.Close:
                        case AnswerStatuses.Partial:
                            iconKey = "Icon.Warning";
                            colorToken = "Brush.Warning";
                            break;
                        case AnswerStatuses.Wrong:
                            iconKey = "Icon.Close";
                            colorToken = "Brush.Error";
                            break;
                        case AnswerStatuses.Invalid:
                        case AnswerStatuses.Empty:
                        default:
                            iconKey = "Icon.Info";
                            colorToken = "Brush.Text.Secondary";
                            break;
                    }

                    row.StatusIcon.SetResourceReference(Icon.DataProperty, iconKey);
                    row.StatusIcon.SetResourceReference(Icon.ForegroundProperty, colorToken);

                    if (!string.IsNullOrEmpty(verdict.Message))
                    {
                        row.FeedbackText.Text = verdict.Message;
                        row.FeedbackText.SetResourceReference(TextBlock.ForegroundProperty, colorToken);
                        row.FeedbackText.Visibility = Visibility.Visible;
                    }
                    else
                    {
                        row.FeedbackText.Visibility = Visibility.Collapsed;
                    }

                    if (!string.IsNullOrEmpty(verdict.UnderstoodAs))
                    {
                        row.UnderstoodText.Text = $"Okunan: {verdict.UnderstoodAs}";
                        row.UnderstoodText.Visibility = Visibility.Visible;
                    }
                    else
                    {
                        row.UnderstoodText.Visibility = Visibility.Collapsed;
                    }

                    if (string.Equals(verdict.Status, AnswerStatuses.Correct, StringComparison.OrdinalIgnoreCase))
                    {
                        row.IsCorrect = true;
                        row.AnswerBox.IsReadOnly = true;
                        row.AnswerBox.SetResourceReference(Control.BorderBrushProperty, "Brush.Success");
                    }
                }
            }

            TxtScore.Text = $"Doğru: {CorrectCount} / {Questions.Count}";
            TxtScore.SetResourceReference(TextBlock.ForegroundProperty, (CorrectCount == Questions.Count)
                ? "Brush.Success"
                : "Brush.Text.Primary");
            TxtScore.Visibility = Visibility.Visible;

            var mainQuestions = Questions
                .Where(q => !string.Equals(q.Group, "extra", StringComparison.OrdinalIgnoreCase))
                .ToList();
            bool allMainCorrect = mainQuestions.Count > 0 &&
                mainQuestions.All(q => _rows.TryGetValue(q.Id, out var r) && r.IsCorrect);
            BannerCongrats.Visibility = allMainCorrect ? Visibility.Visible : Visibility.Collapsed;
        }
        catch (Exception ex)
        {
            TxtError.Text = $"Cevaplar kontrol edilemedi: {ex.Message}";
            TxtError.Visibility = Visibility.Visible;
            if (BannerError != null) BannerError.Visibility = Visibility.Visible;
        }
        finally
        {
            BtnCheck.IsEnabled = true;
        }
    }

    public void ShowNextHint()
    {
        if (HintsAvailable == 0 || HintsShown >= HintsAvailable)
        {
            BtnHint.IsEnabled = false;
            return;
        }

        var section = _hintSections[HintsShown];
        HintsShown++;
        var sectionPanel = AnalysisPanel.BuildExplanationSectionPanel(section);
        HintsContainer.Children.Add(sectionPanel);

        if (TxtBtnHint != null)
            TxtBtnHint.Text = $"İpucu ({HintsShown}/{HintsAvailable})";
        if (HintsShown >= HintsAvailable)
        {
            BtnHint.IsEnabled = false;
        }
    }

    private void BtnCheck_Click(object sender, RoutedEventArgs e)
    {
        _ = CheckAsync();
    }

    private void BtnHint_Click(object sender, RoutedEventArgs e)
    {
        ShowNextHint();
    }

    private void BtnReveal_Click(object sender, RoutedEventArgs e)
    {
        RevealRequested?.Invoke(this, EventArgs.Empty);
    }

    private FrameworkElement CreateQuestionRowCard(PracticeQuestionDto q, out QuestionRow row)
    {
        var card = new Border
        {
            CornerRadius = new CornerRadius(12),
            Padding = new Thickness(14),
            Margin = new Thickness(0, 0, 0, 10)
        };
        card.SetResourceReference(Border.BackgroundProperty, "Brush.Bg.SurfaceAlt");

        var stack = new StackPanel();

        // 1. Satır: Soru sembolü (Brush.Accent.SoftText, SemiBold) ve tanımı (Text.Body)
        var headerPanel = new WrapPanel { Margin = new Thickness(0, 0, 0, 6) };
        var txtLabel = new TextBlock
        {
            Text = q.Label + "  ",
            FontWeight = FontWeights.SemiBold,
            FontSize = 14
        };
        txtLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Accent.SoftText");
        headerPanel.Children.Add(txtLabel);

        var txtDesc = new TextBlock
        {
            Text = q.Description
        };
        txtDesc.SetResourceReference(StyleProperty, "Text.Body");
        headerPanel.Children.Add(txtDesc);
        stack.Children.Add(headerPanel);

        // AC ise ek bilgi satırı (Text.Caption)
        if (q.IsAc)
        {
            string acText = q.Frequency.HasValue
                ? $"Fazör (tepe değer), f = {q.Frequency.Value} Hz"
                : "Fazör (tepe değer)";
            var txtAc = new TextBlock
            {
                Text = acText,
                Margin = new Thickness(0, 0, 0, 6)
            };
            txtAc.SetResourceReference(StyleProperty, "Text.Caption");
            stack.Children.Add(txtAc);
        }

        // 2. Satır: Grid [ TextBox (stretch) | unit TextBlock | status Icon ]
        var gridLine2 = new Grid { Margin = new Thickness(0, 4, 0, 0) };
        gridLine2.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        gridLine2.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        gridLine2.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

        var inputGrid = new Grid();
        var textBox = new TextBox();

        string placeholder = q.IsAc
            ? "ör. 3.03∠-72.3"
            : q.Unit switch
            {
                "A" => "ör. 4m veya 4 mA",
                "Ω" => "ör. 2.2k veya 2200",
                "W" => "ör. 36m veya 36 mW",
                _ => "ör. 7.5 veya 750m",
            };
        var watermark = new TextBlock
        {
            Text = placeholder,
            Margin = new Thickness(12, 0, 0, 0),
            VerticalAlignment = VerticalAlignment.Center,
            IsHitTestVisible = false,
            Visibility = string.IsNullOrEmpty(textBox.Text) ? Visibility.Visible : Visibility.Collapsed
        };
        watermark.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Tertiary");
        watermark.SetResourceReference(TextBlock.FontFamilyProperty, "Font.Mono");

        textBox.TextChanged += (_, _) =>
        {
            watermark.Visibility = string.IsNullOrEmpty(textBox.Text) ? Visibility.Visible : Visibility.Collapsed;
        };
        textBox.KeyDown += async (s, e) =>
        {
            if (e.Key == Key.Enter)
            {
                e.Handled = true;
                await CheckAsync();
            }
        };

        inputGrid.Children.Add(textBox);
        inputGrid.Children.Add(watermark);
        Grid.SetColumn(inputGrid, 0);
        gridLine2.Children.Add(inputGrid);

        var txtUnit = new TextBlock
        {
            Text = q.Unit,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(8, 0, 6, 0)
        };
        txtUnit.SetResourceReference(StyleProperty, "Text.Caption");
        Grid.SetColumn(txtUnit, 1);
        gridLine2.Children.Add(txtUnit);

        var iconStatus = new Icon
        {
            Width = 18,
            Height = 18,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(4, 0, 2, 0)
        };
        Grid.SetColumn(iconStatus, 2);
        gridLine2.Children.Add(iconStatus);

        stack.Children.Add(gridLine2);

        // 3. Satır: Geri bildirim metni
        var txtFeedback = new TextBlock
        {
            TextWrapping = TextWrapping.Wrap,
            FontSize = 12,
            Margin = new Thickness(0, 6, 0, 0),
            Visibility = Visibility.Collapsed
        };
        stack.Children.Add(txtFeedback);

        // 4. Satır: "Okunan: {UnderstoodAs}"
        var txtUnderstood = new TextBlock
        {
            Margin = new Thickness(0, 2, 0, 0),
            Visibility = Visibility.Collapsed
        };
        txtUnderstood.SetResourceReference(StyleProperty, "Text.Caption");
        stack.Children.Add(txtUnderstood);

        card.Child = stack;

        row = new QuestionRow(q, textBox, iconStatus, txtFeedback, txtUnderstood);
        return card;
    }
}
