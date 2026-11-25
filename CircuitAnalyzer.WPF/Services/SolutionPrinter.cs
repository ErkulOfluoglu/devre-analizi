using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Yazdırma ve PDF dışa aktarma girdi modeli.
    /// </summary>
    public sealed class PrintInput
    {
        public AnalysisResponseDto? Response { get; set; }
        public string? Title { get; set; }
        public DateTime? Date { get; set; }
        public ImageSource? CircuitImage { get; set; }
        public string? Method { get; set; }
        public string? Terminals { get; set; }
        public string? Frequency { get; set; }
        public bool IsPracticeMode { get; set; }
        public IReadOnlyList<PracticeQuestionDto>? PracticeQuestions { get; set; }
    }

    /// <summary>
    /// Çözüm veya alıştırma çalışma yaprağı için FlowDocument oluşturan ve yazdıran servis.
    /// </summary>
    public static class SolutionPrinter
    {
        private static Brush GetBrush(FlowDocument doc, string key)
        {
            if (doc.TryFindResource(key) is Brush b) return b;
            if (Application.Current?.TryFindResource(key) is Brush ab) return ab;
            return Brushes.Transparent;
        }

        /// <summary>
        /// Yazdırma veya PDF kaydetme için A4 boyutunda beyaz zeminli FlowDocument oluşturur.
        /// </summary>
        public static FlowDocument BuildDocument(PrintInput input)
        {
            ArgumentNullException.ThrowIfNull(input);

            var doc = new FlowDocument
            {
                PageWidth = 793.7,      // A4 210 mm
                PageHeight = 1122.5,    // A4 297 mm
                ColumnWidth = 793.7,    // Tek sütun
                PagePadding = new Thickness(75.6), // 2 cm kenar boşluğu
                FontSize = 13,
                LineHeight = 18,
                FontFamily = new FontFamily("Segoe UI, -apple-system, sans-serif")
            };

            // Yazdırmada her zaman açık tema (beyaz sayfa, koyu yazı) kullanılır
            var lightDict = new ResourceDictionary
            {
                Source = new Uri("pack://application:,,,/CircuitAnalyzer;component/Themes/Light.xaml", UriKind.Absolute)
            };
            doc.Resources.MergedDictionaries.Add(lightDict);

            var brushBg = GetBrush(doc, "Brush.Bg.Surface");
            var brushPrimary = GetBrush(doc, "Brush.Text.Primary");
            var brushBody = GetBrush(doc, "Brush.Text.Body");
            var brushSecondary = GetBrush(doc, "Brush.Text.Secondary");
            var brushBorder = GetBrush(doc, "Brush.Border.Default");
            var brushSurfaceAlt = GetBrush(doc, "Brush.Bg.SurfaceAlt");
            var brushAccent = GetBrush(doc, "Brush.Accent");
            var brushAccentSoft = GetBrush(doc, "Brush.Accent.Soft");
            var brushAccentSoftText = GetBrush(doc, "Brush.Accent.SoftText");
            var brushSuccess = GetBrush(doc, "Brush.Success");

            doc.Background = brushBg;
            doc.Foreground = brushPrimary;

            // Sonuç tablolarının başlığı ve tablosu (sayfa sonunda birlikte tutulur)
            var tableGroups = new List<(Paragraph BreakTarget, Paragraph Heading, Table Table)>();

            // ═══════════════════════════════════════════════════════
            //  1. ÜST BAŞLIK (Logo + Başlık + Dosya/Tarih)
            // ═══════════════════════════════════════════════════════
            var headerGrid = new Grid { Margin = new Thickness(0, 0, 0, 14) };
            headerGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            headerGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            // Sol taraf: Logo + Başlık + Alt Başlık
            var headerLeft = new StackPanel { Orientation = Orientation.Horizontal };
            try
            {
                var logoImg = new Image
                {
                    Source = new BitmapImage(new Uri("pack://application:,,,/CircuitAnalyzer;component/Assets/logo-128.png", UriKind.Absolute)),
                    Width = 32,
                    Height = 32,
                    Margin = new Thickness(0, 0, 10, 0),
                    VerticalAlignment = VerticalAlignment.Center
                };
                headerLeft.Children.Add(logoImg);
            }
            catch
            {
                // Logo yüklenemezse devam et
            }

            var titlesPanel = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
            string mainTitle = input.IsPracticeMode ? "Devre Analizi — alıştırma yaprağı" : "Devre Analizi — çözüm";
            var txtMain = new TextBlock
            {
                Text = mainTitle,
                FontSize = 18,
                FontWeight = FontWeights.SemiBold,
                Foreground = brushPrimary
            };
            titlesPanel.Children.Add(txtMain);

            if (!string.IsNullOrWhiteSpace(input.Title))
            {
                var txtSub = new TextBlock
                {
                    Text = input.Title,
                    FontSize = 12,
                    Foreground = brushSecondary,
                    Margin = new Thickness(0, 2, 0, 0)
                };
                titlesPanel.Children.Add(txtSub);
            }
            headerLeft.Children.Add(titlesPanel);
            Grid.SetColumn(headerLeft, 0);
            headerGrid.Children.Add(headerLeft);

            // Sağ taraf: Tarih
            var dateStr = (input.Date ?? DateTime.Now).ToString("dd.MM.yyyy HH:mm", CultureInfo.InvariantCulture);
            var txtDate = new TextBlock
            {
                Text = dateStr,
                FontSize = 12,
                Foreground = brushSecondary,
                VerticalAlignment = VerticalAlignment.Center
            };
            Grid.SetColumn(txtDate, 1);
            headerGrid.Children.Add(txtDate);

            doc.Blocks.Add(new BlockUIContainer(headerGrid));

            // Ayırıcı çizgi
            var headerDivider = new Border
            {
                Height = 1,
                Background = brushBorder,
                Margin = new Thickness(0, 0, 0, 14)
            };
            doc.Blocks.Add(new BlockUIContainer(headerDivider));

            // ═══════════════════════════════════════════════════════
            //  2. DEVRE ÇİZİMİ RESMİ
            // ═══════════════════════════════════════════════════════
            if (input.CircuitImage != null)
            {
                var img = new Image
                {
                    Source = input.CircuitImage,
                    MaxHeight = 260,
                    Stretch = Stretch.Uniform,
                    HorizontalAlignment = HorizontalAlignment.Center
                };
                var imgBorder = new Border
                {
                    Background = brushSurfaceAlt,
                    BorderBrush = brushBorder,
                    BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(8),
                    Padding = new Thickness(10),
                    Margin = new Thickness(0, 0, 0, 14),
                    Child = img
                };
                doc.Blocks.Add(new BlockUIContainer(imgBorder));
            }

            // ═══════════════════════════════════════════════════════
            //  3. YÖNTEM VE SEÇENEKLER
            // ═══════════════════════════════════════════════════════
            var pMethod = new Paragraph { Margin = new Thickness(0, 0, 0, 14) };
            pMethod.Inlines.Add(new Bold(new Run("Yöntem: ")) { Foreground = brushPrimary });
            pMethod.Inlines.Add(new Run(input.Method ?? "Düğüm gerilimleri yöntemi") { Foreground = brushBody });

            if (!string.IsNullOrWhiteSpace(input.Terminals))
            {
                pMethod.Inlines.Add(new Run("   ·   Terminaller: " + input.Terminals) { Foreground = brushSecondary });
            }
            if (!string.IsNullOrWhiteSpace(input.Frequency))
            {
                pMethod.Inlines.Add(new Run("   ·   Frekans: " + TurkishNumber.NormalizeForDisplay(input.Frequency)) { Foreground = brushSecondary });
            }
            doc.Blocks.Add(pMethod);

            // ═══════════════════════════════════════════════════════
            //  4. ALIŞTIRMA MODU (Yalnızca sorular, cevaplar gizli)
            // ═══════════════════════════════════════════════════════
            if (input.IsPracticeMode)
            {
                var pQuestionsTitle = new Paragraph(new Run("Sorular"))
                {
                    FontSize = 16,
                    FontWeight = FontWeights.SemiBold,
                    Foreground = brushPrimary,
                    Margin = new Thickness(0, 6, 0, 10)
                };
                doc.Blocks.Add(pQuestionsTitle);

                var questions = input.PracticeQuestions ?? input.Response?.Results?.Practice;
                if (questions != null && questions.Count > 0)
                {
                    foreach (var q in questions)
                    {
                        var pQuestion = new Paragraph
                        {
                            Background = brushSurfaceAlt,
                            BorderBrush = brushBorder,
                            BorderThickness = new Thickness(1),
                            Padding = new Thickness(12, 10, 12, 10),
                            Margin = new Thickness(0, 0, 0, 10),
                            LineHeight = 22
                        };

                        var boldLabel = new Bold { Foreground = brushAccent };
                        boldLabel.Inlines.AddRange(SubscriptText.ToInlines($"[{q.Label}]  ", 12.5));
                        pQuestion.Inlines.Add(boldLabel);

                        var spanDesc = new Span { Foreground = brushBody };
                        spanDesc.Inlines.AddRange(SubscriptText.ToInlines($"{q.Description} [{q.Unit}]\n", 12.5));
                        pQuestion.Inlines.Add(spanDesc);

                        pQuestion.Inlines.Add(new Run("Cevap: ________________________________________________\n")
                        {
                            FontFamily = new FontFamily("Cascadia Mono, Consolas"),
                            FontSize = 12,
                            Foreground = brushSecondary
                        });

                        if (!string.IsNullOrWhiteSpace(q.Hint))
                        {
                            var italicHint = new Italic
                            {
                                FontSize = 11.5,
                                Foreground = brushSecondary
                            };
                            italicHint.Inlines.AddRange(SubscriptText.ToInlines($"İpucu: {q.Hint}", 11.5));
                            pQuestion.Inlines.Add(italicHint);
                        }

                        doc.Blocks.Add(pQuestion);
                    }
                }
            }
            else
            {
                // Şekiller (zaman grafiği, güç üçgeni, rezonans eğrisi): konusunu anlatan bölümün
                // ardına, öyle bölüm yoksa "Sonuçlar"ın önüne. Alıştırma yaprağında yok (cevabı gösterir).
                var figures = PrintContent.Figures(input.Response);
                var sectionTitles = input.Response?.Results?.Explanation?.Select(s => s.Title ?? "").ToList()
                                    ?? new List<string>();
                var figuresAfterSection = figures.ToLookup(f => PrintContent.AnchorSection(sectionTitles, f.Kind));

                // ═══════════════════════════════════════════════════════
                //  5. ÇÖZÜM MODU — ADIM ADIM ANLATIM
                // ═══════════════════════════════════════════════════════
                if (input.Response?.Results?.Explanation != null && input.Response.Results.Explanation.Count > 0)
                {
                    int sectionIndex = -1;
                    foreach (var section in input.Response.Results.Explanation)
                    {
                        sectionIndex++;

                        var pSecTitle = new Paragraph
                        {
                            FontSize = 15,
                            FontWeight = FontWeights.SemiBold,
                            Foreground = brushPrimary,
                            Margin = new Thickness(0, 14, 0, 4)
                        };
                        pSecTitle.Inlines.AddRange(SubscriptText.ToInlines(section.Title, 15));
                        doc.Blocks.Add(pSecTitle);

                        var secDivider = new Border
                        {
                            Height = 1,
                            Background = brushBorder,
                            Margin = new Thickness(0, 0, 0, 8)
                        };
                        doc.Blocks.Add(new BlockUIContainer(secDivider));

                        if (section.Blocks != null)
                        {
                            foreach (var block in section.Blocks)
                            {
                                if (string.IsNullOrWhiteSpace(block.Text)) continue;
                                string kind = block.Kind?.ToLowerInvariant() ?? "text";

                                switch (kind)
                                {
                                    case "math":
                                    {
                                        var mathBorder = new Border
                                        {
                                            Background = brushSurfaceAlt,
                                            BorderBrush = brushBorder,
                                            BorderThickness = new Thickness(1),
                                            CornerRadius = new CornerRadius(6),
                                            Padding = new Thickness(10, 8, 10, 8),
                                            Margin = new Thickness(0, 2, 0, 6)
                                        };
                                        var tbMath = new TextBlock
                                        {
                                            Text = block.Text,
                                            FontFamily = new FontFamily("Cascadia Mono, Consolas"),
                                            FontSize = 12,
                                            Foreground = brushPrimary
                                        };
                                        SubscriptText.Apply(tbMath);
                                        mathBorder.Child = tbMath;
                                        doc.Blocks.Add(new BlockUIContainer(mathBorder));
                                        break;
                                    }
                                    case "result":
                                    {
                                        var resBorder = new Border
                                        {
                                            Background = brushAccentSoft,
                                            BorderBrush = brushAccent,
                                            BorderThickness = new Thickness(1),
                                            CornerRadius = new CornerRadius(6),
                                            Padding = new Thickness(10, 6, 10, 6),
                                            Margin = new Thickness(0, 2, 0, 6)
                                        };
                                        var tbResult = new TextBlock
                                        {
                                            Text = block.Text,
                                            FontWeight = FontWeights.Bold,
                                            FontSize = 12.5,
                                            Foreground = brushAccentSoftText
                                        };
                                        SubscriptText.Apply(tbResult);
                                        resBorder.Child = tbResult;
                                        doc.Blocks.Add(new BlockUIContainer(resBorder));
                                        break;
                                    }
                                    case "note":
                                    {
                                        var pNote = new Paragraph
                                        {
                                            FontStyle = FontStyles.Italic,
                                            Foreground = brushSecondary,
                                            FontSize = 12,
                                            Margin = new Thickness(0, 2, 0, 6)
                                        };
                                        pNote.Inlines.AddRange(SubscriptText.ToInlines(block.Text, 12));
                                        doc.Blocks.Add(pNote);
                                        break;
                                    }
                                    case "check":
                                    {
                                        var pCheck = new Paragraph
                                        {
                                            Foreground = brushSuccess,
                                            FontWeight = FontWeights.SemiBold,
                                            FontSize = 12.5,
                                            Margin = new Thickness(0, 2, 0, 6)
                                        };
                                        pCheck.Inlines.AddRange(SubscriptText.ToInlines(block.Text, 12.5));
                                        doc.Blocks.Add(pCheck);
                                        break;
                                    }
                                    default:
                                    {
                                        var pText = new Paragraph
                                        {
                                            Foreground = brushBody,
                                            FontSize = 12.5,
                                            LineHeight = 18,
                                            Margin = new Thickness(0, 2, 0, 6)
                                        };
                                        pText.Inlines.AddRange(SubscriptText.ToInlines(block.Text, 12.5));
                                        doc.Blocks.Add(pText);
                                        break;
                                    }
                                }
                            }
                        }

                        AddFigures(doc, input.Response, figuresAfterSection[sectionIndex]);
                    }
                }

                // Konusu anlatımda bulunamayan şekiller "Sonuçlar"ın hemen önünde
                AddFigures(doc, input.Response, figuresAfterSection[-1]);

                // ═══════════════════════════════════════════════════════
                //  6. SONUÇ TABLOSU
                // ═══════════════════════════════════════════════════════
                if (input.Response?.Results != null || input.Response?.ThreePhaseResult != null || input.Response?.WattmeterResults != null || input.Response?.DiodeResults != null || input.Response?.ZenerRangeResult != null || input.Response?.WaveformResult != null)
                {
                    var results = input.Response.Results;
                    var waveform = input.Response.WaveformResult;
                    var waveformLevelRows = PrintContent.WaveformLevelRows(waveform);
                    var waveformDiodeRows = PrintContent.WaveformDiodeRows(waveform);
                    var waveformClamperLines = PrintContent.WaveformClamperSummaryLines(waveform);
                    var waveformClamperCheckRows = PrintContent.WaveformClamperCheckRows(waveform);
                    var waveformClamperRcNote = PrintContent.WaveformClamperRcNote(waveform);
                    var zenerRange = input.Response.ZenerRangeResult;
                    var zenerStepRows = PrintContent.ZenerRangeStepRows(zenerRange);
                    var zenerCheckRows = PrintContent.ZenerRangeCheckRows(zenerRange);
                    var threePhaseTables = PrintContent.ThreePhaseTables(input.Response.ThreePhaseResult);
                    var wattmeterRows = PrintContent.WattmeterRows(input.Response.WattmeterResults);
                    var diodeRows = PrintContent.DiodeRows(input.Response.DiodeResults);
                    var probeRows = PrintContent.ProbeRows(results?.ProbeResults);
                    bool hasWaveform = waveform != null;
                    bool hasZenerRange = zenerRange != null;
                    bool hasThreePhase = threePhaseTables.Count > 0;
                    bool hasVoltages = results?.NodeVoltages != null && results.NodeVoltages.Count > 0;
                    bool hasWattmeters = wattmeterRows.Count > 0;
                    bool hasDiodes = diodeRows.Count > 0;
                    bool hasCurrents = results?.ElementCurrents != null && results.ElementCurrents.Count > 0;
                    bool hasProbes = probeRows.Count > 0;
                    bool hasPower = results?.Power?.Elements != null && results.Power.Elements.Count > 0;

                    if (hasWaveform || hasZenerRange || hasThreePhase || hasVoltages || hasWattmeters || hasDiodes || hasCurrents || hasProbes || hasPower)
                    {
                        Paragraph TableHeading(string text, double top)
                        {
                            var p = new Paragraph
                            {
                                FontSize = 13,
                                Foreground = brushPrimary,
                                Margin = new Thickness(0, top, 0, 4),
                                KeepWithNext = true,
                                KeepTogether = true
                            };
                            var bold = new Bold();
                            bold.Inlines.AddRange(SubscriptText.ToInlines(text, 13));
                            p.Inlines.Add(bold);
                            doc.Blocks.Add(p);
                            return p;
                        }

                        var pResTitle = new Paragraph(new Run("Sonuçlar"))
                        {
                            FontSize = 15,
                            FontWeight = FontWeights.SemiBold,
                            Foreground = brushPrimary,
                            Margin = new Thickness(0, 16, 0, 6)
                        };
                        doc.Blocks.Add(pResTitle);

                        var resDivider = new Border
                        {
                            Height = 1,
                            Background = brushBorder,
                            Margin = new Thickness(0, 0, 0, 8)
                        };
                        doc.Blocks.Add(new BlockUIContainer(resDivider));

                        // Geçici durumda tablolar anahtardan çok sonraki kararlı hâldir: söylenir
                        if (PrintContent.ResultsTablesNote(input.Response) is { } tablesNote)
                        {
                            var pNote = new Paragraph
                            {
                                FontStyle = FontStyles.Italic,
                                Foreground = brushSecondary,
                                FontSize = 12,
                                Margin = new Thickness(0, 0, 0, 8),
                                Tag = ResultsNoteTag
                            };
                            pNote.Inlines.Add(new Run(tablesNote));
                            doc.Blocks.Add(pNote);
                        }

                        // Dalga Şekli: uç değerler, ortalama (DC) değer, kitap formülü, iletim açısı, seviyeler ve diyot aralıkları
                        if (waveform != null)
                        {
                            var pWfHead = TableHeading(
                                string.IsNullOrWhiteSpace(waveform.OutputLabel) ? "Dalga Şekli" : $"Dalga Şekli — {waveform.OutputLabel}",
                                4);

                            var pExtrema = new Paragraph
                            {
                                FontSize = 13,
                                Foreground = brushPrimary,
                                Margin = new Thickness(0, 2, 0, 2)
                            };
                            var boldExt = new Bold();
                            boldExt.Inlines.AddRange(SubscriptText.ToInlines(
                                PrintContent.UnicodeMinus(Views.AnalysisPanel.FormatWaveformExtrema(waveform)), 13));
                            pExtrema.Inlines.Add(boldExt);
                            doc.Blocks.Add(pExtrema);

                            var pDc = new Paragraph
                            {
                                FontSize = 12.5,
                                Foreground = brushPrimary,
                                Margin = new Thickness(0, 0, 0, 2)
                            };
                            pDc.Inlines.AddRange(SubscriptText.ToInlines(
                                PrintContent.UnicodeMinus(Views.AnalysisPanel.FormatWaveformDcNumeric(waveform)), 12.5));
                            doc.Blocks.Add(pDc);

                            if (waveform.Clamper == null && Views.AnalysisPanel.FormatWaveformBookFormula(waveform.BookFormula) is { } bookText)
                            {
                                var pBook = new Paragraph
                                {
                                    FontSize = 12,
                                    Foreground = brushSecondary,
                                    Margin = new Thickness(0, 0, 0, 2)
                                };
                                pBook.Inlines.AddRange(SubscriptText.ToInlines(PrintContent.UnicodeMinus(bookText), 12));
                                doc.Blocks.Add(pBook);
                            }

                            if (waveform.Clamper == null && Views.AnalysisPanel.FormatWaveformConductionAngle(waveform.ConductionAngleDeg) is { } angleText)
                            {
                                var pAngle = new Paragraph
                                {
                                    FontSize = 12,
                                    Foreground = brushSecondary,
                                    Margin = new Thickness(0, 0, 0, 6)
                                };
                                pAngle.Inlines.AddRange(SubscriptText.ToInlines(PrintContent.UnicodeMinus(angleText), 12));
                                doc.Blocks.Add(pAngle);
                            }

                            if (waveform.Clamper != null)
                            {
                                var pClampHead = TableHeading("Kenetleme", 6);

                                for (int i = 0; i < waveformClamperLines.Count; i++)
                                {
                                    var pLine = new Paragraph
                                    {
                                        FontSize = i == 0 ? 12.5 : 12,
                                        Foreground = i <= 1 ? brushPrimary : (i == 2 ? brushBody : brushSecondary),
                                        Margin = new Thickness(0, 0, 0, i == waveformClamperLines.Count - 1 ? 6 : 2)
                                    };
                                    if (i == 0)
                                    {
                                        var boldVc = new Bold();
                                        boldVc.Inlines.AddRange(SubscriptText.ToInlines(waveformClamperLines[i], 12.5));
                                        pLine.Inlines.Add(boldVc);
                                    }
                                    else
                                    {
                                        pLine.Inlines.AddRange(SubscriptText.ToInlines(waveformClamperLines[i], 12));
                                    }
                                    doc.Blocks.Add(pLine);
                                }

                                if (waveformClamperCheckRows.Count > 0)
                                {
                                    var tblClampChecks = CreateTable(doc,
                                        new[] { "Kontrol", "Karar", "Açıklama" },
                                        new[] { 120.0, 95.0, 305.0 });
                                    var rg = tblClampChecks.RowGroups[0];
                                    foreach (var (name, verdict, brushKey, text) in waveformClamperCheckRows)
                                    {
                                        var row = CreateRow(doc, new[] { name, verdict, text });
                                        if (row.Cells.Count > 1)
                                        {
                                            row.Cells[1].Foreground = GetBrush(doc, brushKey);
                                            row.Cells[1].FontWeight = FontWeights.SemiBold;
                                        }
                                        rg.Rows.Add(row);
                                    }
                                    doc.Blocks.Add(tblClampChecks);
                                    tableGroups.Add((tableGroups.Count == 0 ? pResTitle : pClampHead, pClampHead, tblClampChecks));
                                }

                                if (!string.IsNullOrWhiteSpace(waveformClamperRcNote))
                                {
                                    var pRcNote = new Paragraph
                                    {
                                        FontStyle = FontStyles.Italic,
                                        Foreground = brushSecondary,
                                        FontSize = 12,
                                        Margin = new Thickness(0, 2, 0, 6)
                                    };
                                    pRcNote.Inlines.AddRange(SubscriptText.ToInlines($"ℹ {waveformClamperRcNote}", 12));
                                    doc.Blocks.Add(pRcNote);
                                }
                            }

                            if (waveformLevelRows.Count > 0)
                            {
                                var pLvlHead = TableHeading("Seviyeler", 6);
                                var tblLvls = CreateTable(doc, new[] { "v_i", "v_O", "Diyot durumları" }, new[] { 100.0, 100.0, 320.0 });
                                var rg = tblLvls.RowGroups[0];
                                foreach (var (vIn, vOut, states) in waveformLevelRows)
                                    rg.Rows.Add(CreateRow(doc, new[] { vIn, vOut, states }));
                                doc.Blocks.Add(tblLvls);
                                tableGroups.Add((tableGroups.Count == 0 ? pResTitle : pLvlHead, pLvlHead, tblLvls));
                            }

                            if (waveformDiodeRows.Count > 0)
                            {
                                var pDiodeHead = TableHeading("Diyot iletim aralıkları", 6);
                                var tblWfDiodes = CreateTable(doc, new[] { "Diyot", "Aralıklar" }, new[] { 100.0, 420.0 });
                                var rg = tblWfDiodes.RowGroups[0];
                                foreach (var (id, intervals) in waveformDiodeRows)
                                    rg.Rows.Add(CreateRow(doc, new[] { id, intervals }));
                                doc.Blocks.Add(tblWfDiodes);
                                tableGroups.Add((tableGroups.Count == 0 ? pResTitle : pDiodeHead, pDiodeHead, tblWfDiodes));
                            }
                        }

                        // Zener Aralığı: verilen aralık (ters problem), cevap cümlesi, hesap adımları ve sağlama tablosu
                        if (zenerRange != null)
                        {
                            var pZrHead = TableHeading("Zener Aralığı", 4);
                            if (Views.AnalysisPanel.FormatZenerGiven(zenerRange) is { } givenText)
                            {
                                var pGiven = new Paragraph
                                {
                                    FontSize = 12,
                                    Foreground = brushSecondary,
                                    Margin = new Thickness(0, 2, 0, 2)
                                };
                                pGiven.Inlines.AddRange(SubscriptText.ToInlines(PrintContent.UnicodeMinus(givenText), 12));
                                doc.Blocks.Add(pGiven);
                            }

                            var pRange = new Paragraph
                            {
                                FontSize = 14,
                                Foreground = zenerRange.IsInverse && !zenerRange.Feasible
                                    ? GetBrush(doc, "Brush.Warning")
                                    : brushPrimary,
                                Margin = new Thickness(0, 2, 0, 4)
                            };
                            var boldRange = new Bold();
                            boldRange.Inlines.AddRange(SubscriptText.ToInlines(
                                PrintContent.UnicodeMinus(Views.AnalysisPanel.FormatZenerRange(zenerRange)), 14));
                            pRange.Inlines.Add(boldRange);
                            doc.Blocks.Add(pRange);

                            if (Views.AnalysisPanel.FormatZenerCurrentStatus(zenerRange) is { } currentStatus)
                            {
                                var pStatus = new Paragraph
                                {
                                    FontSize = 12.5,
                                    Foreground = zenerRange.CurrentInside == true
                                        ? brushSuccess
                                        : (zenerRange.IsInverse && zenerRange.Unique ? brushSecondary : GetBrush(doc, "Brush.Warning")),
                                    Margin = new Thickness(0, 0, 0, 8)
                                };
                                pStatus.Inlines.AddRange(SubscriptText.ToInlines(PrintContent.UnicodeMinus(currentStatus), 12.5));
                                doc.Blocks.Add(pStatus);
                            }

                            if (zenerStepRows.Count > 0)
                            {
                                var tblSteps = CreateTable(doc, new[] { "Büyüklük", "Değer" }, new[] { 200.0, 240.0 });
                                var rg = tblSteps.RowGroups[0];
                                foreach (var (sym, val) in zenerStepRows)
                                    rg.Rows.Add(CreateRow(doc, new[] { sym, val }));
                                doc.Blocks.Add(tblSteps);
                                tableGroups.Add((tableGroups.Count == 0 ? pResTitle : pZrHead, pZrHead, tblSteps));
                            }

                            if (zenerCheckRows.Count > 0)
                            {
                                var pCheckHead = TableHeading("Sağlama", 8);
                                string xCol = Views.AnalysisPanel.ZenerCheckXSymbol(zenerRange);
                                var tblChecks = CreateTable(doc,
                                    new[] { xCol, "Durum", "V_Y", "I_Z", "Karar" },
                                    new[] { 100.0, 145.0, 95.0, 95.0, 85.0 });
                                var rg = tblChecks.RowGroups[0];
                                foreach (var (x, state, vy, iz, verdict) in zenerCheckRows)
                                    rg.Rows.Add(CreateRow(doc, new[] { x, state, vy, iz, verdict }));
                                doc.Blocks.Add(tblChecks);
                                tableGroups.Add((tableGroups.Count == 0 ? pResTitle : pCheckHead, pCheckHead, tblChecks));
                            }
                        }

                        // Üç Faz Tabloları (faz/hat/yük gerilimleri, nötr gerilimi, hat/faz akımları)
                        foreach (var (header, rows) in threePhaseTables)
                        {
                            var pSub = TableHeading(header, tableGroups.Count == 0 ? 4 : 8);
                            string col1 = header.Contains("akım", StringComparison.OrdinalIgnoreCase) ? "Akım" : "Gerilim";
                            var tblTp = CreateTable(doc, new[] { "Büyüklük", col1 }, new[] { 240.0, 200.0 });
                            var rg = tblTp.RowGroups[0];
                            foreach (var (name, value) in rows)
                            {
                                rg.Rows.Add(CreateRow(doc, new[] { name, value }));
                            }
                            doc.Blocks.Add(tblTp);
                            tableGroups.Add((tableGroups.Count == 0 ? pResTitle : pSub, pSub, tblTp));
                        }

                        // Düğüm Gerilimleri Tablosu
                        if (hasVoltages)
                        {
                            var pSub = TableHeading("Düğüm Gerilimleri", tableGroups.Count == 0 ? 4 : 8);

                            var tblVoltages = CreateTable(doc, new[] { "Düğüm", "Gerilim" }, new[] { 240.0, 200.0 });
                            var rg = tblVoltages.RowGroups[0];
                            foreach (var (name, value) in PrintContent.NodeRows(results!.NodeVoltages))
                            {
                                rg.Rows.Add(CreateRow(doc, new[] { name, value }));
                            }
                            doc.Blocks.Add(tblVoltages);
                            tableGroups.Add((tableGroups.Count == 0 ? pResTitle : pSub, pSub, tblVoltages));
                        }

                        // Wattmetre Okumaları Tablosu
                        if (hasWattmeters)
                        {
                            var pSub = TableHeading("Wattmetre Okumaları", tableGroups.Count == 0 ? 4 : 8);

                            var tblWatt = CreateTable(doc, new[] { "Wattmetre", "Okuma" }, new[] { 240.0, 200.0 });
                            var rg = tblWatt.RowGroups[0];
                            foreach (var (name, value) in wattmeterRows)
                            {
                                rg.Rows.Add(CreateRow(doc, new[] { name, value }));
                            }
                            doc.Blocks.Add(tblWatt);
                            tableGroups.Add((tableGroups.Count == 0 ? pResTitle : pSub, pSub, tblWatt));
                        }

                        // Diyotlar Tablosu
                        if (hasDiodes)
                        {
                            var pSub = TableHeading("Diyotlar", tableGroups.Count == 0 ? 4 : 8);

                            var tblDiodes = CreateTable(doc, new[] { "Diyot", "Durum", "V_AK", "Akım" }, new[] { 120.0, 110.0, 110.0, 110.0 });
                            var rg = tblDiodes.RowGroups[0];
                            foreach (var (name, state, vAk, current) in diodeRows)
                            {
                                rg.Rows.Add(CreateRow(doc, new[] { name, state, vAk, current }));
                            }
                            doc.Blocks.Add(tblDiodes);
                            tableGroups.Add((tableGroups.Count == 0 ? pResTitle : pSub, pSub, tblDiodes));
                        }

                        // Eleman Akımları Tablosu
                        if (hasCurrents)
                        {
                            var pSub = TableHeading("Eleman Akımları", tableGroups.Count == 0 ? 4 : 8);

                            var tblCurrents = CreateTable(doc, new[] { "Eleman", "Akım", "Yön" }, new[] { 100.0, 160.0, 120.0 });
                            var rg = tblCurrents.RowGroups[0];
                            foreach (var (name, value, direction) in PrintContent.CurrentRows(results!.ElementCurrents))
                            {
                                rg.Rows.Add(CreateRow(doc, new[] { name, value, direction }));
                            }
                            doc.Blocks.Add(tblCurrents);
                            tableGroups.Add((tableGroups.Count == 0 ? pResTitle : pSub, pSub, tblCurrents));
                        }

                        // Ölçüm Probları Tablosu
                        if (hasProbes)
                        {
                            var pSub = TableHeading("Ölçüm Probları", tableGroups.Count == 0 ? 4 : 8);

                            var tblProbes = CreateTable(doc, new[] { "Prob", "Değer" }, new[] { 240.0, 200.0 });
                            var rg = tblProbes.RowGroups[0];
                            foreach (var (name, value) in probeRows)
                            {
                                rg.Rows.Add(CreateRow(doc, new[] { name, value }));
                            }
                            doc.Blocks.Add(tblProbes);
                            tableGroups.Add((tableGroups.Count == 0 ? pResTitle : pSub, pSub, tblProbes));
                        }

                        // Güç Analizi Tablosu
                        if (hasPower)
                        {
                            var pSub = TableHeading("Güç Analizi", tableGroups.Count == 0 ? 4 : 8);

                            var tblPower = CreateTable(doc,
                                new[] { "Eleman", "Aktif Güç", "Reaktif Güç", "Görünür Güç", "cos φ", "Rol" },
                                new[] { 80.0, 105.0, 105.0, 105.0, 105.0, 70.0 });
                            var rg = tblPower.RowGroups[0];
                            foreach (var (elem, ep) in results!.Power!.Elements)
                            {
                                rg.Rows.Add(CreateRow(doc, PrintContent.PowerRow(elem, ep)));
                            }
                            doc.Blocks.Add(tblPower);
                            tableGroups.Add((tableGroups.Count == 0 ? pResTitle : pSub, pSub, tblPower));
                        }
                    }
                }
            }

            // ═══════════════════════════════════════════════════════
            //  7. ALT SORUMLULUK REDDİ NOTU
            // ═══════════════════════════════════════════════════════
            var footerDivider = new Border
            {
                Height = 1,
                Background = brushBorder,
                Margin = new Thickness(0, 24, 0, 8)
            };
            doc.Blocks.Add(new BlockUIContainer(footerDivider));

            var pFooter = new Paragraph
            {
                FontSize = 9.5,
                LineHeight = 13,
                Foreground = brushSecondary,
                FontStyle = FontStyles.Italic,
                TextAlignment = TextAlignment.Center,
                Margin = new Thickness(0, 0, 0, 0)
            };
            pFooter.Inlines.Add(new Bold(new Run("Sorumluluk reddi: ")));
            pFooter.Inlines.Add(new Run(AppInfo.Disclaimer));
            doc.Blocks.Add(pFooter);

            KeepTablesWithHeadings(doc, tableGroups);
            return doc;
        }

        /// <summary>
        /// Tablo başlığı sayfa sonunda tek başına kalmasın, sayfaya sığan tablo bölünmesin
        /// (son satırı yeni sayfaya tek başına düşmesin). FlowDocument'ta tablonun "birlikte tut"
        /// özelliği yoktur ve paragrafın KeepWithNext'i tabloya uygulanmaz; bu yüzden belge A4'te
        /// sayfalanır, bölünen tablonun başlığına sayfa sonu konur ve yeniden sayfalanarak sınanır.
        /// Karar <see cref="PrintContent.TableBreakHelps"/>'te. İlk tabloda sayfa sonu "Sonuçlar"
        /// başlığının önüne konur (<paramref name="groups"/>'taki BreakTarget): o başlık da tablosuyla kalır.
        /// </summary>
        private static void KeepTablesWithHeadings(FlowDocument doc, List<(Paragraph BreakTarget, Paragraph Heading, Table Table)> groups)
        {
            if (groups.Count == 0)
                return;
            try
            {
                foreach (var (target, _, table) in groups)
                {
                    var before = Placement(doc, target, table);
                    if (!PrintContent.TableIsSplit(before))
                        continue;
                    target.BreakPageBefore = true;
                    var after = Placement(doc, target, table);
                    if (!PrintContent.TableBreakHelps(before, after))
                        target.BreakPageBefore = false;

                    // Sayfadan uzun tablonun son satırı yeni sayfada tek başına (dul satır)
                    // kaldıysa, sondan bir önceki satırı ikiye bölecek şekilde yeni sayfaya
                    // taşı (yeni sayfada en az 2 satır kalsın).
                    var starts = PageStarts(doc);
                    var rows = table.RowGroups[0].Rows;
                    var rowPages = rows.Select(r => PageOf(starts, r)).ToList();
                    int widowBreakIdx = PrintContent.WidowBreakRowIndex(rowPages);
                    if (widowBreakIdx >= 1 && widowBreakIdx < rows.Count)
                    {
                        SplitTableAtRow(doc, table, widowBreakIdx);
                    }
                }
            }
            catch (Exception ex)
            {
                // Sayfalama ölçülemezse belge yine basılır (yalnız sayfa sonları düzeltilmez)
                System.Diagnostics.Debug.WriteLine($"Tablo sayfa sonları ayarlanamadı: {ex}");
            }
        }

        private static TablePlacement Placement(FlowDocument doc, Paragraph heading, Table table)
        {
            var starts = PageStarts(doc);
            var rows = table.RowGroups.SelectMany(g => g.Rows).ToList();
            var first = rows.Count > 1 ? rows[1] : rows[0];   // satır 0 sütun başlıklarıdır
            return new TablePlacement(PageOf(starts, heading), PageOf(starts, first), PageOf(starts, rows[^1]));
        }

        /// <summary>
        /// Uzun bir tabloyu <paramref name="breakRowIndex"/> satırından yeni bir <see cref="TableRowGroup"/>'a
        /// böler ve o grubun başına sütun başlıklarının bir kopyasını ekler. Böylece kalan boşluğa
        /// yalnız 1 satır sığdığında eklenen başlık satırı yüzünden son iki veri satırı birlikte
        /// yeni sayfaya geçer (son sayfada en az 2 veri satırı + tekrarlanan başlık bulunur).
        /// </summary>
        private static void SplitTableAtRow(FlowDocument doc, Table table, int breakRowIndex)
        {
            var rows = table.RowGroups[0].Rows;
            if (breakRowIndex < 1 || breakRowIndex >= rows.Count)
                return;

            string[] headers = rows[0].Cells
                .Select(c => new TextRange(c.ContentStart, c.ContentEnd).Text.Trim())
                .ToArray();

            var movingRows = new List<TableRow>();
            while (rows.Count > breakRowIndex)
            {
                var r = rows[breakRowIndex];
                rows.RemoveAt(breakRowIndex);
                movingRows.Add(r);
            }

            var contGroup = new TableRowGroup();
            contGroup.Rows.Add(CreateHeaderRow(doc, headers));
            foreach (var r in movingRows)
            {
                contGroup.Rows.Add(r);
            }
            table.RowGroups.Add(contGroup);

            // Tekrarlanan başlık satırı önceki sayfanın sonunda tek başına kaldıysa
            // bir önceki satıra (ilk grubun son satırına) alt iç boşluk vererek onu da yeni sayfaya it.
            var starts = PageStarts(doc);
            if (PageOf(starts, contGroup.Rows[0]) < PageOf(starts, movingRows[0]) && rows.Count > 1)
            {
                foreach (var cell in rows[^1].Cells)
                {
                    cell.Padding = new Thickness(cell.Padding.Left, cell.Padding.Top, cell.Padding.Right, cell.Padding.Bottom + 28);
                }
            }
        }

        /// <summary>
        /// Tek satırlık öğenin (başlık, tablo satırı) sayfası. Sayfa başı konumu öğenin ilk yazı
        /// konumudur (öğenin başlangıcından sonra); bu yüzden öğenin sonu ile karşılaştırılır.
        /// </summary>
        internal static int PageOf(IReadOnlyList<TextPointer> pageStarts, TextElement element) =>
            PageOf(pageStarts, element.ContentEnd);

        /// <summary>Belgeyi A4'te sayfalar; her sayfanın başladığı içerik konumu.</summary>
        internal static List<TextPointer> PageStarts(FlowDocument doc)
        {
            var paginator = (DynamicDocumentPaginator)((IDocumentPaginatorSource)doc).DocumentPaginator;
            paginator.PageSize = new Size(doc.PageWidth, doc.PageHeight);
            paginator.ComputePageCount();
            var starts = new List<TextPointer>();
            for (int i = 0; i < paginator.PageCount; i++)
            {
                var page = paginator.GetPage(i);
                starts.Add(paginator.GetPagePosition(page) as TextPointer ?? doc.ContentStart);
            }
            return starts;
        }

        /// <summary>Konumun bulunduğu sayfa (0'dan).</summary>
        internal static int PageOf(IReadOnlyList<TextPointer> pageStarts, TextPointer position)
        {
            int page = 0;
            for (int i = 1; i < pageStarts.Count; i++)
                if (pageStarts[i].CompareTo(position) <= 0)
                    page = i;
            return page;
        }

        /// <summary>Geçici durum tablolarının üstündeki notun etiketi (testler bulur).</summary>
        internal const string ResultsNoteTag = "print:results-note";

        /// <summary>Şeklin sayfadaki genişliği (DIP): A4 içerik genişliği 642,5 eksi çerçeve ve iç boşluk.</summary>
        internal const double FigureWidth = 600;

        /// <summary>Güç üçgeni tuvalinin yüksekliği (DIP).</summary>
        internal const double TriangleHeight = 240;

        /// <summary>Kâğıttaki geçici durum grafiğinin (her büyüklük) ve rezonans eğrisinin yüksekliği (DIP).</summary>
        internal const double TransientPlotHeight = 230;
        internal const double ResonancePlotHeight = 300;
        internal const double ZenerRangePlotHeight = 250;
        internal const double WaveformPlotHeight = 250;

        /// <summary>Grafik görüntüsünün çözünürlük katı: 600 DIP → 1800 px (~270 dpi kâğıtta).</summary>
        private const double PlotPixelScale = 3;

        /// <summary>
        /// Şekilleri ekler: her biri tek bir <see cref="BlockUIContainer"/>'da (sayfa arasında
        /// bölünmez), altında açıklamasıyla. Renkler belgeye bağlı açık temadan gelir; uygulamanın
        /// teması değiştirilmez.
        /// </summary>
        private static void AddFigures(FlowDocument doc, AnalysisResponseDto? response, IEnumerable<PrintFigure> figures)
        {
            if (response == null)
                return;
            foreach (var figure in figures)
            {
                UIElement? body;
                try
                {
                    body = BuildFigureBody(doc, response, figure.Kind);
                }
                catch (Exception ex)
                {
                    // Şekil çizilemezse yazdırma yine sürer (şekil ve açıklaması basılmaz)
                    System.Diagnostics.Debug.WriteLine($"Yazdırma şekli çizilemedi ({figure.Kind}): {ex}");
                    body = null;
                }
                if (body == null)
                    continue;

                var caption = new TextBlock
                {
                    Text = figure.Caption,
                    FontSize = 11.5,
                    LineHeight = 16,
                    TextWrapping = TextWrapping.Wrap,
                    Foreground = GetBrush(doc, "Brush.Text.Secondary"),
                    Margin = new Thickness(2, 8, 2, 0)
                };
                SubscriptText.Apply(caption);

                var stack = new StackPanel();
                stack.Children.Add(body);
                stack.Children.Add(caption);

                var frame = new Border
                {
                    Tag = figure.Kind,
                    Background = GetBrush(doc, "Brush.Bg.Surface"),
                    BorderBrush = GetBrush(doc, "Brush.Border.Default"),
                    BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(8),
                    Padding = new Thickness(10),
                    Margin = new Thickness(0, 6, 0, 12),
                    Child = stack
                };
                doc.Blocks.Add(new BlockUIContainer(frame));
            }
        }

        private static UIElement? BuildFigureBody(FlowDocument doc, AnalysisResponseDto response, PrintFigureKind kind)
        {
            switch (kind)
            {
                case PrintFigureKind.TransientPlot:
                {
                    var data = response.Transient ?? response.Results?.Transient;
                    if (data == null)
                        return null;
                    var quantities = PrintContent.TransientPlotQuantities(data);
                    if (quantities.Count == 0)
                        return null;
                    var panel = new StackPanel();
                    for (int i = 0; i < quantities.Count; i++)
                    {
                        var q = quantities[i];
                        bool isTop = i == 0;
                        panel.Children.Add(PlotImage(doc, plot =>
                            Views.TransientPlotView.BuildPlot(plot, data, q, isTop,
                                Views.PlotMarkers.DataWidthPx(FigureWidth), Views.PlotMarkers.DataHeightPx(TransientPlotHeight),
                                c => ScottColor(doc, c)),
                            FigureWidth, TransientPlotHeight, i > 0 ? 6 : 0));
                    }
                    return panel;
                }
                case PrintFigureKind.ResonanceCurve:
                {
                    var data = response.Resonance ?? response.Results?.Resonance;
                    if (data == null)
                        return null;
                    var (scale, unit) = Views.ResonanceCurveView.FreqUnitFor(data);
                    return PlotImage(doc, plot =>
                        Views.ResonanceCurveView.BuildPlot(plot, data, scale, unit,
                            Views.PlotMarkers.DataWidthPx(FigureWidth), Views.PlotMarkers.DataHeightPx(ResonancePlotHeight),
                            c => ScottColor(doc, c)),
                        FigureWidth, ResonancePlotHeight, 0);
                }
                case PrintFigureKind.ZenerRangePlot:
                {
                    var data = response.ZenerRangeResult;
                    if (data == null)
                        return null;
                    var (scale, unit) = Views.ZenerRangePlotView.XUnitFor(data);
                    return PlotImage(doc, plot =>
                        Views.ZenerRangePlotView.BuildPlot(plot, data, scale, unit,
                            Views.PlotMarkers.DataWidthPx(FigureWidth), Views.PlotMarkers.DataHeightPx(ZenerRangePlotHeight),
                            c => ScottColor(doc, c)),
                        FigureWidth, ZenerRangePlotHeight, 0);
                }
                case PrintFigureKind.WaveformPlot:
                {
                    var data = response.WaveformResult;
                    if (data == null)
                        return null;
                    var (scale, unit) = Views.WaveformPlotView.TimeUnitFor(data);
                    return PlotImage(doc, plot =>
                        Views.WaveformPlotView.BuildPlot(plot, data, scale, unit,
                            Views.PlotMarkers.DataWidthPx(FigureWidth), Views.PlotMarkers.DataHeightPx(WaveformPlotHeight),
                            c => ScottColor(doc, c)),
                        FigureWidth, WaveformPlotHeight, 0);
                }
                case PrintFigureKind.PowerTriangle:
                {
                    var data = PrintContent.PowerTriangleData(response);
                    if (data == null)
                        return null;
                    // Vektör çizim (kâğıtta her ölçekte keskin); yerleşim ekrandakiyle aynı saf hesaptan
                    const double h = TriangleHeight;
                    var canvas = new Canvas { Width = FigureWidth, Height = h, ClipToBounds = true };
                    Views.PowerTriangleView.Draw(canvas, data, FigureWidth, h,
                        (el, prop, key) => el.SetValue(prop, GetBrush(doc, key)));
                    return canvas;
                }
                default:
                    return null;
            }
        }

        /// <summary>
        /// Grafiği ekran dışında, kâğıt boyutunda yeni bir ScottPlot çizimi olarak üretir
        /// (canlı kontrolün ekran görüntüsü alınmaz): 3 kat piksel, aynı oranlarla.
        /// </summary>
        private static Image PlotImage(FlowDocument doc, Action<ScottPlot.Plot> build, double width, double height, double topMargin)
        {
            var plot = new ScottPlot.Plot { ScaleFactor = (float)PlotPixelScale };
            build(plot);
            byte[] png = plot.GetImageBytes(
                (int)Math.Round(width * PlotPixelScale), (int)Math.Round(height * PlotPixelScale), ScottPlot.ImageFormat.Png);

            var bmp = new BitmapImage();
            using (var ms = new System.IO.MemoryStream(png))
            {
                bmp.BeginInit();
                bmp.CacheOption = BitmapCacheOption.OnLoad;
                bmp.StreamSource = ms;
                bmp.EndInit();
            }
            bmp.Freeze();

            var img = new Image
            {
                Source = bmp,
                Width = width,
                Height = height,
                Stretch = Stretch.Uniform,
                Margin = new Thickness(0, topMargin, 0, 0)
            };
            RenderOptions.SetBitmapScalingMode(img, BitmapScalingMode.HighQuality);
            return img;
        }

        private static ScottPlot.Color ScottColor(FlowDocument doc, string key)
        {
            if (GetBrush(doc, key) is SolidColorBrush b && b.Color.A > 0)
                return new ScottPlot.Color(b.Color.R, b.Color.G, b.Color.B, b.Color.A);
            return new ScottPlot.Color(128, 128, 128);
        }

        private static Table CreateTable(FlowDocument doc, string[] headers, double[] widths)
        {
            var table = new Table
            {
                CellSpacing = 0,
                Margin = new Thickness(0, 2, 0, 8)
            };

            foreach (double w in widths)
            {
                table.Columns.Add(new TableColumn { Width = new GridLength(w) });
            }

            var group = new TableRowGroup();
            table.RowGroups.Add(group);

            // Başlık satırı
            group.Rows.Add(CreateHeaderRow(doc, headers));

            return table;
        }

        private static TableRow CreateHeaderRow(FlowDocument doc, string[] headers)
        {
            var brushSurfaceAlt = GetBrush(doc, "Brush.Bg.SurfaceAlt");
            var brushPrimary = GetBrush(doc, "Brush.Text.Primary");
            var brushBorder = GetBrush(doc, "Brush.Border.Default");

            var headerRow = new TableRow { Background = brushSurfaceAlt };
            foreach (string h in headers)
            {
                var cell = new TableCell(new Paragraph(new Bold(new Run(h))) { Margin = new Thickness(0) })
                {
                    Padding = new Thickness(6, 4, 6, 4),
                    BorderThickness = new Thickness(0, 0, 0, 1),
                    BorderBrush = brushBorder,
                    Foreground = brushPrimary
                };
                headerRow.Cells.Add(cell);
            }
            return headerRow;
        }

        private static TableRow CreateRow(FlowDocument doc, string[] values)
        {
            var brushBody = GetBrush(doc, "Brush.Text.Body");
            var brushBorder = GetBrush(doc, "Brush.Border.Default");

            var row = new TableRow();
            foreach (string v in values)
            {
                var p = new Paragraph { Margin = new Thickness(0) };
                p.Inlines.AddRange(SubscriptText.ToInlines(v, doc.FontSize > 0 ? doc.FontSize : 12.5));
                var cell = new TableCell(p)
                {
                    Padding = new Thickness(6, 4, 6, 4),
                    BorderThickness = new Thickness(0, 0, 0, 1),
                    BorderBrush = brushBorder,
                    Foreground = brushBody
                };
                row.Cells.Add(cell);
            }
            return row;
        }
    }
}
