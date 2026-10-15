using System;
using System.Collections.Generic;
using System.Globalization;
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
                pMethod.Inlines.Add(new Run("   ·   Frekans: " + input.Frequency) { Foreground = brushSecondary });
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

                        pQuestion.Inlines.Add(new Bold(new Run($"[{q.Label}]  ")) { Foreground = brushAccent });
                        pQuestion.Inlines.Add(new Run($"{q.Description} [{q.Unit}]\n") { Foreground = brushBody });
                        pQuestion.Inlines.Add(new Run("Cevap: ________________________________________________\n")
                        {
                            FontFamily = new FontFamily("Cascadia Mono, Consolas"),
                            FontSize = 12,
                            Foreground = brushSecondary
                        });

                        if (!string.IsNullOrWhiteSpace(q.Hint))
                        {
                            pQuestion.Inlines.Add(new Italic(new Run($"İpucu: {q.Hint}"))
                            {
                                FontSize = 11.5,
                                Foreground = brushSecondary
                            });
                        }

                        doc.Blocks.Add(pQuestion);
                    }
                }
            }
            else
            {
                // ═══════════════════════════════════════════════════════
                //  5. ÇÖZÜM MODU — ADIM ADIM ANLATIM
                // ═══════════════════════════════════════════════════════
                if (input.Response?.Results?.Explanation != null && input.Response.Results.Explanation.Count > 0)
                {
                    foreach (var section in input.Response.Results.Explanation)
                    {
                        var pSecTitle = new Paragraph(new Run(section.Title))
                        {
                            FontSize = 15,
                            FontWeight = FontWeights.SemiBold,
                            Foreground = brushPrimary,
                            Margin = new Thickness(0, 14, 0, 4)
                        };
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
                                        mathBorder.Child = new TextBlock
                                        {
                                            Text = block.Text,
                                            FontFamily = new FontFamily("Cascadia Mono, Consolas"),
                                            FontSize = 12,
                                            Foreground = brushPrimary
                                        };
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
                                        resBorder.Child = new TextBlock
                                        {
                                            Text = block.Text,
                                            FontWeight = FontWeights.Bold,
                                            FontSize = 12.5,
                                            Foreground = brushAccentSoftText
                                        };
                                        doc.Blocks.Add(new BlockUIContainer(resBorder));
                                        break;
                                    }
                                    case "note":
                                    {
                                        var pNote = new Paragraph(new Run(block.Text))
                                        {
                                            FontStyle = FontStyles.Italic,
                                            Foreground = brushSecondary,
                                            FontSize = 12,
                                            Margin = new Thickness(0, 2, 0, 6)
                                        };
                                        doc.Blocks.Add(pNote);
                                        break;
                                    }
                                    case "check":
                                    {
                                        var pCheck = new Paragraph(new Run(block.Text))
                                        {
                                            Foreground = brushSuccess,
                                            FontWeight = FontWeights.SemiBold,
                                            FontSize = 12.5,
                                            Margin = new Thickness(0, 2, 0, 6)
                                        };
                                        doc.Blocks.Add(pCheck);
                                        break;
                                    }
                                    default:
                                    {
                                        var pText = new Paragraph(new Run(block.Text))
                                        {
                                            Foreground = brushBody,
                                            FontSize = 12.5,
                                            LineHeight = 18,
                                            Margin = new Thickness(0, 2, 0, 6)
                                        };
                                        doc.Blocks.Add(pText);
                                        break;
                                    }
                                }
                            }
                        }
                    }
                }

                // ═══════════════════════════════════════════════════════
                //  6. SONUÇ TABLOSU
                // ═══════════════════════════════════════════════════════
                if (input.Response?.Results != null)
                {
                    var results = input.Response.Results;
                    bool hasVoltages = results.NodeVoltages != null && results.NodeVoltages.Count > 0;
                    bool hasCurrents = results.ElementCurrents != null && results.ElementCurrents.Count > 0;
                    bool hasPower = results.Power?.Elements != null && results.Power.Elements.Count > 0;

                    if (hasVoltages || hasCurrents || hasPower)
                    {
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

                        // Düğüm Gerilimleri Tablosu
                        if (hasVoltages)
                        {
                            var pSub = new Paragraph(new Bold(new Run("Düğüm Gerilimleri")))
                            {
                                FontSize = 13,
                                Foreground = brushPrimary,
                                Margin = new Thickness(0, 4, 0, 4)
                            };
                            doc.Blocks.Add(pSub);

                            var tblVoltages = CreateTable(doc, new[] { "Düğüm", "Gerilim" }, new[] { 120.0, 200.0 });
                            var rg = tblVoltages.RowGroups[0];
                            foreach (var (node, nv) in results.NodeVoltages!)
                            {
                                string valStr = nv.Value != null ? EngFormat.Format(nv.Value, nv.Unit ?? "V") : "—";
                                rg.Rows.Add(CreateRow(doc, new[] { $"V({node})", valStr }));
                            }
                            doc.Blocks.Add(tblVoltages);
                        }

                        // Eleman Akımları Tablosu
                        if (hasCurrents)
                        {
                            var pSub = new Paragraph(new Bold(new Run("Eleman Akımları")))
                            {
                                FontSize = 13,
                                Foreground = brushPrimary,
                                Margin = new Thickness(0, 8, 0, 4)
                            };
                            doc.Blocks.Add(pSub);

                            var tblCurrents = CreateTable(doc, new[] { "Eleman", "Akım", "Yön" }, new[] { 100.0, 160.0, 120.0 });
                            var rg = tblCurrents.RowGroups[0];
                            foreach (var (elem, ec) in results.ElementCurrents!)
                            {
                                var (currentText, directionText) = CurrentDisplay.Format(elem, ec);
                                rg.Rows.Add(CreateRow(doc, new[] { $"I({elem})", currentText, string.IsNullOrEmpty(directionText) ? (ec.Direction ?? "—") : directionText }));
                            }
                            doc.Blocks.Add(tblCurrents);
                        }

                        // Güç Analizi Tablosu
                        if (hasPower)
                        {
                            var pSub = new Paragraph(new Bold(new Run("Güç Analizi")))
                            {
                                FontSize = 13,
                                Foreground = brushPrimary,
                                Margin = new Thickness(0, 8, 0, 4)
                            };
                            doc.Blocks.Add(pSub);

                            var tblPower = CreateTable(doc,
                                new[] { "Eleman", "Aktif Güç", "Reaktif Güç", "Görünür Güç", "Rol" },
                                new[] { 90.0, 110.0, 110.0, 110.0, 80.0 });
                            var rg = tblPower.RowGroups[0];
                            foreach (var (elem, ep) in results.Power!.Elements)
                            {
                                string roleStr = ep.Role switch
                                {
                                    "source" => "Kaynak",
                                    "load" => "Yük",
                                    _ => ep.Role ?? "—"
                                };
                                rg.Rows.Add(CreateRow(doc, new[]
                                {
                                    elem,
                                    $"{ep.ActivePower:0.###} W",
                                    $"{ep.ReactivePower:0.###} VAR",
                                    $"{ep.ApparentPower:0.###} VA",
                                    roleStr
                                }));
                            }
                            doc.Blocks.Add(tblPower);
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

            return doc;
        }

        private static Table CreateTable(FlowDocument doc, string[] headers, double[] widths)
        {
            var brushSurfaceAlt = GetBrush(doc, "Brush.Bg.SurfaceAlt");
            var brushPrimary = GetBrush(doc, "Brush.Text.Primary");
            var brushBorder = GetBrush(doc, "Brush.Border.Default");

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
            group.Rows.Add(headerRow);

            return table;
        }

        private static TableRow CreateRow(FlowDocument doc, string[] values)
        {
            var brushBody = GetBrush(doc, "Brush.Text.Body");
            var brushBorder = GetBrush(doc, "Brush.Border.Default");

            var row = new TableRow();
            foreach (string v in values)
            {
                var cell = new TableCell(new Paragraph(new Run(v)) { Margin = new Thickness(0) })
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
