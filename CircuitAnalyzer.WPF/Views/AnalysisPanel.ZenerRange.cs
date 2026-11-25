// AnalysisPanel — Zener Aralığı sonuç kartı ve biçimlendirme yardımcıları.

using System.Windows;
using System.Windows.Controls;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views;

public partial class AnalysisPanel
{
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
}
