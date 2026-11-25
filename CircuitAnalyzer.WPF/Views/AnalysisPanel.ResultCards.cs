// AnalysisPanel — Sonuçlar sekmesi kartları (üç faz, düğüm gerilimleri, akımlar, Thevenin/Norton, güç, bağlantılar) ve ortak kutucuk yardımcıları.

using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views;

public partial class AnalysisPanel
{
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

        // Dalga şekli kartı (Sonuçlar sekmesinin en üstünde)
        if (response.WaveformResult is { } waveform)
        {
            panel.Children.Add(BuildWaveformCard(waveform));
        }

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
