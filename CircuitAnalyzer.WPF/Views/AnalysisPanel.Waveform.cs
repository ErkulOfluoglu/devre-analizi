// AnalysisPanel — Dalga Şekli sonuç kartı, kenetleyici ve biçimlendirme yardımcıları.

using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using CircuitAnalyzer.WPF.Controls;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views;

public partial class AnalysisPanel
{
    // ═══════════════════════════════════════════════════════
    //  DALGA ŞEKLİ SONUÇ KARTI VE BİÇİMLENDİRME
    // ═══════════════════════════════════════════════════════

    internal static string FormatWaveformExtrema(WaveformResultDto wf) =>
        $"V_O,max = {FormatDiodeVoltage(wf.VOutMax)} · V_O,min = {FormatDiodeVoltage(wf.VOutMin)}";

    internal static string FormatWaveformDcNumeric(WaveformResultDto wf) =>
        $"Ortalama (DC) değer: {FormatDiodeVoltage(wf.VDcNumeric)} (sayısal)";

    internal static string? FormatWaveformBookFormula(WaveformBookFormulaDto? bf)
    {
        if (bf == null)
            return null;

        string text = TurkishNumber.NormalizeForDisplay(bf.Text?.Trim() ?? "");
        if (string.IsNullOrEmpty(text))
            text = $"V_DC = {FormatDiodeVoltage(bf.Value)}";
        else if (!text.EndsWith("V", StringComparison.Ordinal))
            text = $"{text} = {FormatDiodeVoltage(bf.Value)}";

        return string.IsNullOrWhiteSpace(bf.Name)
            ? $"Kitap formülü: {text}"
            : $"Kitap formülü ({bf.Name.Trim()}): {text}";
    }

    internal static string? FormatWaveformConductionAngle(double? angleDeg)
    {
        if (!angleDeg.HasValue || !double.IsFinite(angleDeg.Value))
            return null;
        return $"İletim θ = {TurkishNumber.Format(angleDeg.Value, "0.##")}° den başlar";
    }

    internal static string FormatWaveformDiodeIntervals(WaveformDiodeDto diode, double timeScale, string timeUnit)
    {
        if (diode?.Intervals == null || diode.Intervals.Count == 0)
            return "—";
        return string.Join(" · ", diode.Intervals.Select(iv =>
            $"{TurkishNumber.Format(iv.TStart * timeScale, "0.##")}–{TurkishNumber.Format(iv.TEnd * timeScale, "0.##")} {timeUnit} {FormatDiodeState(iv.State)}"));
    }

    internal static string FormatWaveformLevelStates(Dictionary<string, string>? states)
    {
        if (states == null || states.Count == 0)
            return "—";
        return string.Join(", ", states.Select(kv => $"{kv.Key}: {FormatDiodeState(kv.Value)}"));
    }

    internal static string FormatWaveformClamperVC(WaveformClamperDto clamper)
    {
        string mag = FormatDiodeVoltage(Math.Abs(clamper.VC));
        string side = (clamper.VCPlusSide ?? "").Trim().ToUpperInvariant() switch
        {
            "INPUT" => "giriş tarafında",
            "OUTPUT" => "çıkış tarafında",
            _ => "",
        };
        return string.IsNullOrEmpty(side)
            ? $"V_C = {mag}"
            : $"V_C = {mag} (+ ucu {side})";
    }

    internal static string FormatWaveformClamperConductingVO(WaveformClamperDto clamper) =>
        $"Diyot iletimdeyken V_O = {FormatDiodeVoltage(clamper.VK)}";

    internal static string FormatWaveformClamperShift(WaveformClamperDto clamper)
    {
        string mag = FormatDiodeVoltage(Math.Abs(clamper.VC));
        string dir = string.Equals(clamper.Shift?.Trim(), "UP", StringComparison.OrdinalIgnoreCase)
            ? "yukarı"
            : "aşağı";
        return $"Çıkış, girişin {mag} {dir} kaymış hâlidir";
    }

    internal static string FormatWaveformClamperSwing(WaveformClamperDto clamper) =>
        $"Salınım: Giriş {FormatDiodeVoltage(clamper.InputSwing)} · Çıkış {FormatDiodeVoltage(clamper.OutputSwing)}";

    /// <summary>Kenetleyici sağlama satırı kararı: true yeşil, false hata fırçası, null ikincil yazı.</summary>
    internal static (string Text, string BrushKey) FormatWaveformClamperCheckVerdict(bool? ok) => ok switch
    {
        true => ("Uygun ✓", "Brush.Success"),
        false => ("Uymuyor ✗", "Brush.Error"),
        null => ("Uygulanmaz", "Brush.Text.Secondary"),
    };

    internal static string? FormatWaveformClamperRcNote(string? rcNote)
    {
        if (string.IsNullOrWhiteSpace(rcNote))
            return null;
        string cleaned = rcNote.Trim().TrimStart('ℹ', ' ');
        return string.IsNullOrWhiteSpace(cleaned) ? null : TurkishNumber.NormalizeForDisplay(cleaned);
    }

    private Border BuildWaveformCard(WaveformResultDto wf)
    {
        var card = new Border
        {
            Padding = new Thickness(14),
            Margin = new Thickness(0, 0, 0, 12)
        };
        card.SetResourceReference(StyleProperty, "Card");

        var stack = new StackPanel();

        var header = new TextBlock
        {
            Text = string.IsNullOrWhiteSpace(wf.OutputLabel) ? "Dalga Şekli" : $"Dalga Şekli — {wf.OutputLabel}",
            FontSize = 14,
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(0, 0, 0, 8)
        };
        header.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
        SubscriptText.Apply(header);
        stack.Children.Add(header);

        // Giriş / çıkış dalga şekli grafiği
        if (wf.T is { Count: > 0 } && wf.VOut is { Count: > 0 })
        {
            var plotView = new WaveformPlotView { Margin = new Thickness(0, 0, 0, 10) };
            plotView.LoadData(wf);
            plotView.EnlargeClicked += (_, _) => EnlargeWaveformRequested?.Invoke(this, wf);
            stack.Children.Add(plotView);
        }

        // Temel değerler: V_O,max · V_O,min, sayısal DC, kitap formülü, iletim açısı
        var txtExtrema = new TextBlock
        {
            Text = FormatWaveformExtrema(wf),
            FontSize = 13.5,
            FontWeight = FontWeights.SemiBold,
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 0, 0, 4)
        };
        txtExtrema.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
        SubscriptText.Apply(txtExtrema);
        stack.Children.Add(txtExtrema);

        var txtDc = new TextBlock
        {
            Text = FormatWaveformDcNumeric(wf),
            FontSize = 12.5,
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 0, 0, 4)
        };
        txtDc.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
        SubscriptText.Apply(txtDc);
        stack.Children.Add(txtDc);

        // Kenetleyicide kitap formülü ve iletim açısı satırları gösterilmez
        if (wf.Clamper == null && FormatWaveformBookFormula(wf.BookFormula) is { } bookText)
        {
            var txtBook = new TextBlock
            {
                Text = bookText,
                FontSize = 12,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 4)
            };
            txtBook.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
            SubscriptText.Apply(txtBook);
            stack.Children.Add(txtBook);
        }

        if (wf.Clamper == null && FormatWaveformConductionAngle(wf.ConductionAngleDeg) is { } angleText)
        {
            var txtAngle = new TextBlock
            {
                Text = angleText,
                FontSize = 12,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 8)
            };
            txtAngle.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
            SubscriptText.Apply(txtAngle);
            stack.Children.Add(txtAngle);
        }

        // Kenetleme özeti, sağlama tablosu ve RC notu
        if (wf.Clamper is { } clamper)
        {
            var clampHeader = new TextBlock
            {
                Text = "Kenetleme",
                FontSize = 12,
                FontWeight = FontWeights.SemiBold,
                Margin = new Thickness(0, 6, 0, 6)
            };
            clampHeader.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
            stack.Children.Add(clampHeader);

            var summaryCard = new Border { Margin = new Thickness(0, 0, 0, 8) };
            summaryCard.SetResourceReference(StyleProperty, "Card.Inset");
            var summaryStack = new StackPanel();

            var txtVc = new TextBlock
            {
                Text = FormatWaveformClamperVC(clamper),
                FontSize = 12.5,
                FontWeight = FontWeights.SemiBold,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 3)
            };
            txtVc.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
            SubscriptText.Apply(txtVc);
            summaryStack.Children.Add(txtVc);

            var txtVk = new TextBlock
            {
                Text = FormatWaveformClamperConductingVO(clamper),
                FontSize = 12,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 3)
            };
            txtVk.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
            SubscriptText.Apply(txtVk);
            summaryStack.Children.Add(txtVk);

            var txtShift = new TextBlock
            {
                Text = FormatWaveformClamperShift(clamper),
                FontSize = 12,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 3)
            };
            txtShift.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Body");
            SubscriptText.Apply(txtShift);
            summaryStack.Children.Add(txtShift);

            var txtSwing = new TextBlock
            {
                Text = FormatWaveformClamperSwing(clamper),
                FontSize = 12,
                TextWrapping = TextWrapping.Wrap
            };
            txtSwing.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
            SubscriptText.Apply(txtSwing);
            summaryStack.Children.Add(txtSwing);

            summaryCard.Child = summaryStack;
            stack.Children.Add(summaryCard);

            // Sağlama tablosu (Zener sağlama tablosuyla aynı kompakt biçem)
            if (clamper.Checks is { Count: > 0 })
            {
                var checksCard = new Border { Margin = new Thickness(0, 0, 0, 8) };
                checksCard.SetResourceReference(StyleProperty, "Card.Inset");

                var grid = new Grid();
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

                grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                string[] headers = { "Kontrol", "Karar", "Açıklama" };
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
                    Grid.SetRow(th, 0);
                    Grid.SetColumn(th, c);
                    grid.Children.Add(th);
                }

                for (int i = 0; i < clamper.Checks.Count; i++)
                {
                    var chk = clamper.Checks[i];
                    int row = i + 1;
                    grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

                    var (verdictText, verdictBrush) = FormatWaveformClamperCheckVerdict(chk.Ok);
                    string[] vals =
                    {
                        chk.Name ?? "",
                        verdictText,
                        TurkishNumber.NormalizeForDisplay(chk.Text ?? ""),
                    };

                    for (int c = 0; c < vals.Length; c++)
                    {
                        var td = new TextBlock
                        {
                            Text = vals[c],
                            FontSize = 11,
                            Margin = new Thickness(2, 2, 8, 2),
                            TextWrapping = c == 2 ? TextWrapping.Wrap : TextWrapping.NoWrap
                        };
                        if (c == 1)
                        {
                            td.FontWeight = FontWeights.SemiBold;
                            td.SetResourceReference(TextBlock.ForegroundProperty, verdictBrush);
                        }
                        else if (c == 0)
                        {
                            td.FontWeight = FontWeights.SemiBold;
                            td.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
                            SubscriptText.Apply(td);
                        }
                        else
                        {
                            td.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
                            SubscriptText.Apply(td);
                        }
                        Grid.SetRow(td, row);
                        Grid.SetColumn(td, c);
                        grid.Children.Add(td);
                    }
                }

                checksCard.Child = grid;
                stack.Children.Add(checksCard);
            }

            if (FormatWaveformClamperRcNote(clamper.RcNote) is { } rcNote)
            {
                var noteBorder = new Border { Margin = new Thickness(0, 0, 0, 8) };
                noteBorder.SetResourceReference(StyleProperty, "InfoBar.Info");

                var noteGrid = new Grid();
                noteGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                noteGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

                var noteIcon = new Icon
                {
                    Width = 16,
                    Height = 16,
                    Margin = new Thickness(0, 2, 8, 0),
                    VerticalAlignment = VerticalAlignment.Top
                };
                noteIcon.SetResourceReference(Icon.DataProperty, "Icon.Info");
                Grid.SetColumn(noteIcon, 0);
                noteGrid.Children.Add(noteIcon);

                var noteTb = new TextBlock
                {
                    Text = rcNote,
                    FontSize = 12,
                    TextWrapping = TextWrapping.Wrap,
                    VerticalAlignment = VerticalAlignment.Center
                };
                SubscriptText.Apply(noteTb);
                Grid.SetColumn(noteTb, 1);
                noteGrid.Children.Add(noteTb);

                noteBorder.Child = noteGrid;
                stack.Children.Add(noteBorder);
            }
        }

        // Kare dalga iki seviye tablosu
        if (wf.Levels is { Count: > 0 })
        {
            var lvlHeader = new TextBlock
            {
                Text = "Seviyeler",
                FontSize = 12,
                FontWeight = FontWeights.SemiBold,
                Margin = new Thickness(0, 4, 0, 6)
            };
            lvlHeader.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
            stack.Children.Add(lvlHeader);

            var lvlCard = new Border { Margin = new Thickness(0, 0, 0, 10) };
            lvlCard.SetResourceReference(StyleProperty, "Card.Inset");

            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            string[] headers = { "v_i", "v_O", "Diyot durumları" };
            for (int c = 0; c < headers.Length; c++)
            {
                var th = new TextBlock
                {
                    Text = headers[c],
                    FontSize = 11,
                    FontWeight = FontWeights.SemiBold,
                    Margin = new Thickness(2, 0, 10, 4)
                };
                th.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
                SubscriptText.Apply(th);
                Grid.SetRow(th, 0);
                Grid.SetColumn(th, c);
                grid.Children.Add(th);
            }

            for (int i = 0; i < wf.Levels.Count; i++)
            {
                var lvl = wf.Levels[i];
                int row = i + 1;
                grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

                string[] vals =
                {
                    FormatDiodeVoltage(lvl.VIn),
                    FormatDiodeVoltage(lvl.VOut),
                    FormatWaveformLevelStates(lvl.States),
                };

                for (int c = 0; c < vals.Length; c++)
                {
                    var td = new TextBlock
                    {
                        Text = vals[c],
                        FontSize = 11.5,
                        Margin = new Thickness(2, 2, 10, 2),
                        TextWrapping = c == 2 ? TextWrapping.Wrap : TextWrapping.NoWrap
                    };
                    if (c == 2)
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

            lvlCard.Child = grid;
            stack.Children.Add(lvlCard);
        }

        // Diyot iletim aralıkları tablosu
        if (wf.Diodes is { Count: > 0 })
        {
            var (tScale, tUnit) = WaveformPlotView.TimeUnitFor(wf);

            var diodeHeader = new TextBlock
            {
                Text = "Diyot iletim aralıkları",
                FontSize = 12,
                FontWeight = FontWeights.SemiBold,
                Margin = new Thickness(0, 4, 0, 6)
            };
            diodeHeader.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
            stack.Children.Add(diodeHeader);

            var diodeCard = new Border();
            diodeCard.SetResourceReference(StyleProperty, "Card.Inset");

            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

            for (int r = 0; r < wf.Diodes.Count; r++)
            {
                var d = wf.Diodes[r];
                grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

                var idTb = new TextBlock
                {
                    Text = d.Id,
                    FontSize = 12,
                    FontWeight = FontWeights.SemiBold,
                    Margin = new Thickness(2, 2, 12, 2)
                };
                idTb.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
                Grid.SetRow(idTb, r);
                Grid.SetColumn(idTb, 0);
                grid.Children.Add(idTb);

                var ivTb = new TextBlock
                {
                    Text = FormatWaveformDiodeIntervals(d, tScale, tUnit),
                    FontSize = 12,
                    TextWrapping = TextWrapping.Wrap,
                    Margin = new Thickness(2, 2, 2, 2)
                };
                ivTb.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Secondary");
                SubscriptText.Apply(ivTb);
                Grid.SetRow(ivTb, r);
                Grid.SetColumn(ivTb, 1);
                grid.Children.Add(ivTb);
            }

            diodeCard.Child = grid;
            stack.Children.Add(diodeCard);
        }

        card.Child = stack;
        return card;
    }
}
