// AnalysisPanel — Anlatım / Sonuçlar görünüm geçişi ve anlatım blok öğeleri.

using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using CircuitAnalyzer.WPF.Controls;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views;

public partial class AnalysisPanel
{
    public bool IsExplanationViewSelected { get; private set; }

    public void SelectExplanationView(bool explanation)
    {
        _userSelectedExplanation = explanation;
        IsExplanationViewSelected = explanation;

        UpdateToggleButtonsState();
        UpdateViewVisibility();
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
}
