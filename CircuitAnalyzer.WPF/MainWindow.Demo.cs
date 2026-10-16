using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF
{
    /// <summary>
    /// Tanıtım videosu için otomatik ekran görüntüsü dizisi (--demo-shots) üretimi.
    /// Gerçek arayüzü adım adım çalıştırarak yüksek çözünürlüklü (2x) PNG dosyaları
    /// ve hedef koordinatlarını içeren shots.json manifest dosyasını kaydeder.
    /// </summary>
    public partial class MainWindow
    {
        private const double DemoScale = 2.0;
        private const int DemoWaitTimeoutSeconds = 30;

        /// <summary>
        /// Komut satırı argümanlarından --demo-shots dizin yolunu ayrıştırır.
        /// Argüman eksikse veya geçersizse false döner.
        /// </summary>
        internal static bool TryGetDemoShots(string[]? args, out string? outputDir)
        {
            outputDir = null;
            if (args == null)
                return false;

            int i = Array.FindIndex(args, a => string.Equals(a, "--demo-shots", StringComparison.OrdinalIgnoreCase));
            if (i < 0 || i + 1 >= args.Length)
                return false;

            string raw = args[i + 1].Trim().Trim('"');
            if (string.IsNullOrWhiteSpace(raw) || raw.StartsWith("--", StringComparison.Ordinal))
                return false;

            outputDir = Path.GetFullPath(raw);
            return true;
        }

        private sealed record DemoSizeDto(
            double Width,
            double Height);

        private sealed record DemoShotEntry(
            string Name,
            string File,
            string Kind,
            string Label,
            [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
            DemoSizeDto? Page,
            Dictionary<string, double[]> Targets);

        private sealed record DemoManifestDto(
            int Version,
            int Scale,
            DemoSizeDto Window,
            DemoSizeDto Page,
            List<DemoShotEntry> Shots);

        /// <summary>
        /// Tanıtım senaryosunu baştan sona çalıştırır, ekran görüntülerini ve manifesti yazar.
        /// Kullanıcı ayarlarını korumak için geçici bir ayar dosyası kullanır.
        /// </summary>
        private async Task RunDemoShotsAsync(string outDir)
        {
            string originalSettingsPath = AppSettings.SettingsPath;
            string tempSettingsPath = Path.Combine(
                Path.GetTempPath(),
                $"CircuitAnalyzer_demo_{Guid.NewGuid():N}_settings.json");

            try
            {
                Directory.CreateDirectory(outDir);

                // Kullanıcının gerçek ayarlarına dokunmamak için geçici dosyaya yönlendir
                AppSettings.SettingsPath = tempSettingsPath;
                AppSettings.OnboardingCompleted = true;

                // Pencereyi ekran dışında 1600x900 boyutunda konumlandır
                WindowState = WindowState.Normal;
                WindowStartupLocation = WindowStartupLocation.Manual;
                Left = -20000;
                Top = 0;
                ShowActivated = false;
                Width = 1600;
                Height = 900;

                // Açık tema ve temiz başlangıç durumu
                ThemeManager.SetChoice(ThemeChoice.Light);
                OnboardingOverlay.Visibility = Visibility.Collapsed;
                TourOverlay.Visibility = Visibility.Collapsed;
                AboutOverlay.Visibility = Visibility.Collapsed;
                DialogOverlay.Close(animate: false);

                Show();
                await WaitForUiIdleAsync("pencere açılışı");

                // Çözücü arka uç servisinin hazır olmasını bekle
                if (_backendStartTask != null)
                {
                    await WithTimeoutAsync(_backendStartTask, "Çözücü başlatma");
                }
                if (_api == null)
                {
                    throw new InvalidOperationException("Çözücü başlatılamadı (_api == null).");
                }

                var shots = new List<DemoShotEntry>();

                // 01 "empty" — açık tema, çözücü hazır, boş devre alanı, tanıtım kapalı
                ClearCircuit();
                _problemCode = null;
                AnalysisPanel.SetProblemCode(null);
                AnalysisPanel.IsPracticeMode = false;
                AnalysisPanel.ClearResults();
                AnalysisPanel.SetAnalysisType(AnalysisTypes.Nodal);
                OnCircuitChanged();
                SetZoom(1.0);
                CanvasScrollViewer.ScrollToHorizontalOffset(0);
                CanvasScrollViewer.ScrollToVerticalOffset(0);

                await WaitForUiIdleAsync("empty");
                shots.Add(CaptureWindowShot(
                    outDir,
                    name: "empty",
                    label: "Boş çalışma alanı — çözücü hazır"));

                // 02.."build_NN" — ExampleCircuits.All[4] devresini adım adım oluştur
                var example4 = ExampleCircuits.All[4]();
                int buildIndex = 0;

                foreach (var element in example4.Elements)
                {
                    buildIndex++;
                    string shotName = $"build_{buildIndex:D2}";

                    AddElementToCanvas(element);
                    SyncCountersFromIds();
                    TxtStatus.Text = $"{element.Id} eklendi";

                    await WaitForUiIdleAsync(shotName);

                    var elementVisual = _visualToElement
                        .FirstOrDefault(kv => ReferenceEquals(kv.Value, element)).Key as FrameworkElement;
                    var sidebarBtn = GetSidebarButtonForElement(element);

                    var extra = new Dictionary<string, double[]>();
                    if (TryGetElementBounds(elementVisual) is { } elBounds)
                        extra["lastAdded"] = elBounds;
                    if (TryGetElementBounds(sidebarBtn) is { } sbBounds)
                        extra["sidebarItem"] = sbBounds;

                    shots.Add(CaptureWindowShot(
                        outDir,
                        name: shotName,
                        label: $"{element.Id} eklendi",
                        extraTargets: extra));
                }

                // Telleri adım adım gerçek CompleteWire akışıyla ekle
                EnterWireMode();
                foreach (var wireTemplate in example4.Wires)
                {
                    buildIndex++;
                    string shotName = $"build_{buildIndex:D2}";

                    CompleteWire(wireTemplate.StartPin, wireTemplate.EndPin);
                    var addedWire = _wires[^1];

                    await WaitForUiIdleAsync(shotName);

                    var extra = new Dictionary<string, double[]>();
                    if (TryGetWireBounds(addedWire) is { } wireBounds)
                        extra["lastAdded"] = wireBounds;

                    string startOwner = wireTemplate.StartPin.Owner?.Id ?? "";
                    string endOwner = wireTemplate.EndPin.Owner?.Id ?? "";
                    shots.Add(CaptureWindowShot(
                        outDir,
                        name: shotName,
                        label: $"{startOwner} – {endOwner} bağlantısı eklendi",
                        extraTargets: extra));
                }
                ExitWireMode();

                // "method_set" — analiz yöntemini Çevre Akımları olarak ayarla
                AnalysisPanel.SetAnalysisType(example4.SuggestedAnalysisType, example4.SuggestedTerminal);
                TxtStatus.Text = $"Analiz yöntemi seçildi: Çevre Akımları";
                await WaitForUiIdleAsync("method_set");
                shots.Add(CaptureWindowShot(
                    outDir,
                    name: "method_set",
                    label: "Analiz yöntemi: Çevre Akımları"));

                // "solved" — devreyi çöz, etiketler tuvalde, Anlatım sekmesi en üstte
                AnalysisPanel.IsPracticeMode = false;
                await SolveAndWaitAsync("solved");
                AnalysisPanel.SelectExplanationView(true);
                AnalysisPanel.ResultsScrollViewer.ScrollToVerticalOffset(0);
                await WaitForUiIdleAsync("solved");
                shots.Add(CaptureWindowShot(
                    outDir,
                    name: "solved",
                    label: "Devre çözüldü — adım adım anlatım",
                    includeExplanation: true));

                // "explain_1".."explain_4" — anlatım alanını 0'dan %85'e 4 eşit adımda kaydır
                double scrollable = AnalysisPanel.ResultsScrollViewer.ScrollableHeight;
                double maxOffset = scrollable * 0.85;
                for (int step = 0; step < 4; step++)
                {
                    string shotName = $"explain_{step + 1}";
                    double offset = maxOffset * (step / 3.0);
                    AnalysisPanel.ResultsScrollViewer.ScrollToVerticalOffset(offset);
                    await WaitForUiIdleAsync(shotName);

                    shots.Add(CaptureWindowShot(
                        outDir,
                        name: shotName,
                        label: $"Adım adım çözüm anlatımı ({step + 1}/4)",
                        includeExplanation: true));
                }

                // "results_tab" — Sonuçlar sekmesi seçili
                AnalysisPanel.SelectExplanationView(false);
                AnalysisPanel.ResultsScrollViewer.ScrollToVerticalOffset(0);
                await WaitForUiIdleAsync("results_tab");
                shots.Add(CaptureWindowShot(
                    outDir,
                    name: "results_tab",
                    label: "Sonuçlar sekmesi",
                    includeExplanation: true));

                // Sonraki çözümler için varsayılan Anlatım sekmesine dön
                AnalysisPanel.SelectExplanationView(true);

                // "practice_blank" — soru kodu 4821, alıştırma modu açık, cevap kutuları boş
                LoadProblem(4821);
                AnalysisPanel.IsPracticeMode = true;
                await SolveAndWaitAsync("practice_blank");
                AnalysisPanel.ResultsScrollViewer.ScrollToVerticalOffset(0);
                await WaitForUiIdleAsync("practice_blank");

                var pv = AnalysisPanel.CurrentPracticeView
                    ?? throw new InvalidOperationException("Alıştırma görünümü oluşturulamadı (4821).");
                if (pv.Questions.Count < 2)
                {
                    throw new InvalidOperationException($"Soru 4821 için en az 2 soru bekleniyordu, bulunan: {pv.Questions.Count}");
                }

                await ScrollPracticeIntoViewAsync(pv, "practice_blank");

                shots.Add(CaptureWindowShot(
                    outDir,
                    name: "practice_blank",
                    label: "Soru kodu 4821 — alıştırma modu",
                    includePracticeTargets: true));

                // Soru 4821 yüklüyken yazdırma önizlemesi (print_page) görüntüsünü 2x çözünürlükte hazırla
                string printPageFile = "print_page.png";
                string printPagePath = Path.Combine(outDir, printPageFile);
                RenderPracticeWorksheetPage(4821, printPagePath, DemoScale);

                // "practice_typed" — ilk sorunun kutusuna "14.67" yazıldı, henüz kontrol edilmedi
                var box1 = pv.GetAnswerBox(pv.Questions[0].Id);
                box1.Focus();
                box1.Text = "14.67";
                box1.CaretIndex = box1.Text.Length;
                await ScrollPracticeIntoViewAsync(pv, "practice_typed");

                shots.Add(CaptureWindowShot(
                    outDir,
                    name: "practice_typed",
                    label: "İlk soruya 14.67 cevabı yazıldı",
                    includePracticeTargets: true));

                // "practice_checked" — Kontrol et'e basıldı, ilk cevap doğru (yeşil)
                await WithTimeoutAsync(pv.CheckAsync(), "Cevap kontrolü (practice_checked)");
                await ScrollPracticeIntoViewAsync(pv, "practice_checked");
                if (!string.Equals(pv.GetStatus(pv.Questions[0].Id), AnswerStatuses.Correct, StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidOperationException(
                        $"İlk soru doğru olarak işaretlenmedi. Durum: {pv.GetStatus(pv.Questions[0].Id)}");
                }

                shots.Add(CaptureWindowShot(
                    outDir,
                    name: "practice_checked",
                    label: "İlk cevap kontrol edildi — doğru",
                    includePracticeTargets: true));

                // "practice_wrong" — ikinci soruya "1234" yazılıp tekrar kontrol edildi -> kırmızı uyarı
                var box2 = pv.GetAnswerBox(pv.Questions[1].Id);
                box2.Focus();
                box2.Text = "1234";
                box2.CaretIndex = box2.Text.Length;
                await WithTimeoutAsync(pv.CheckAsync(), "Cevap kontrolü (practice_wrong)");
                await ScrollPracticeIntoViewAsync(pv, "practice_wrong");
                if (!string.Equals(pv.GetStatus(pv.Questions[1].Id), AnswerStatuses.Wrong, StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidOperationException(
                        $"İkinci soru yanlış olarak işaretlenmedi. Durum: {pv.GetStatus(pv.Questions[1].Id)}");
                }

                shots.Add(CaptureWindowShot(
                    outDir,
                    name: "practice_wrong",
                    label: "İkinci cevap yanlış — geri bildirim gösterildi",
                    includePracticeTargets: true));

                // "dark_solved" — koyu temaya geç, ExampleCircuits.All[5] yükle ve çöz, Anlatım en üstte
                ThemeManager.SetChoice(ThemeChoice.Dark);
                AnalysisPanel.IsPracticeMode = false;
                var example5 = ExampleCircuits.All[5]();
                LoadExample(example5);
                await SolveAndWaitAsync("dark_solved");
                AnalysisPanel.SelectExplanationView(true);
                AnalysisPanel.ResultsScrollViewer.ScrollToVerticalOffset(0);
                await WaitForUiIdleAsync("dark_solved");

                shots.Add(CaptureWindowShot(
                    outDir,
                    name: "dark_solved",
                    label: "Koyu tema — iki kaynaklı devre (Süperpozisyon)",
                    includeExplanation: true));

                // Koyu tema çekiminden sonra tekrar açık temaya dön
                ThemeManager.SetChoice(ThemeChoice.Light);
                await WaitForUiIdleAsync("light_restore");

                // "print_page" — soru 4821 çalışma kağıdının ilk sayfası (A4 boyutunda)
                shots.Add(new DemoShotEntry(
                    Name: "print_page",
                    File: printPageFile,
                    Kind: "page",
                    Label: "Soru 4821 — yazdırılabilir A4 alıştırma kağıdı",
                    Page: new DemoSizeDto(793.7, 1122.5),
                    Targets: new Dictionary<string, double[]>()));

                // "ai_setup" — açık temada pencere içi tanıtım 5. sayfası (Yapay Zeka kurulumu)
                OnboardingOverlay.View.SetupView.StatusProvider = AnalysisPanel.LlmStatusProvider;
                OnboardingOverlay.View.SetupView.StartOllama = AnalysisPanel.LlmStartOllama;
                OnboardingOverlay.View.SetupView.StartPull = AnalysisPanel.LlmStartPull;
                OnboardingOverlay.View.SetupView.GetPull = AnalysisPanel.LlmGetPull;
                OnboardingOverlay.View.SetupView.CancelPull = AnalysisPanel.LlmCancelPull;

                try
                {
                    await WithTimeoutAsync(OnboardingOverlay.View.SetupView.RefreshAsync(), "Yapay zeka durumu sorgulama");
                }
                catch
                {
                    // Yerel model kurulu değilse de görünüm geçerli durumu gösterir
                }

                OnboardingOverlay.Show(4, animate: false);
                await WaitForUiIdleAsync("ai_setup");

                var aiExtra = new Dictionary<string, double[]>();
                if (TryGetElementBounds(OnboardingOverlay.CardBorder) is { } obBounds)
                    aiExtra["onboardingCard"] = obBounds;

                shots.Add(CaptureWindowShot(
                    outDir,
                    name: "ai_setup",
                    label: "Yerel yapay zeka kurulum sayfası",
                    extraTargets: aiExtra));

                OnboardingOverlay.Close(Views.OnboardingResult.Skipped, animate: false);

                // Manifest dosyasını (shots.json) UTF-8 (BOM'suz) olarak kaydet
                var rootContent = (FrameworkElement)Content;
                double rootWidth = Math.Round(rootContent.ActualWidth > 0 ? rootContent.ActualWidth : Width, 1);
                double rootHeight = Math.Round(rootContent.ActualHeight > 0 ? rootContent.ActualHeight : Height, 1);

                var manifest = new DemoManifestDto(
                    Version: 1,
                    Scale: (int)DemoScale,
                    Window: new DemoSizeDto(rootWidth, rootHeight),
                    Page: new DemoSizeDto(793.7, 1122.5),
                    Shots: shots);

                var jsonOptions = new JsonSerializerOptions
                {
                    WriteIndented = true,
                    PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
                    DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
                    Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
                };

                string manifestJson = JsonSerializer.Serialize(manifest, jsonOptions);
                File.WriteAllText(
                    Path.Combine(outDir, "shots.json"),
                    manifestJson,
                    new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));

                Application.Current.Shutdown(0);
            }
            catch (Exception ex)
            {
                try
                {
                    Directory.CreateDirectory(outDir);
                    File.WriteAllText(
                        Path.Combine(outDir, "HATA.txt"),
                        ex.ToString(),
                        new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
                }
                catch
                {
                }
                Application.Current.Shutdown(1);
            }
            finally
            {
                AppSettings.SettingsPath = originalSettingsPath;
                if (File.Exists(tempSettingsPath))
                {
                    try { File.Delete(tempSettingsPath); } catch { }
                }
            }
        }

        private async Task SolveAndWaitAsync(string stepName)
        {
            await WithTimeoutAsync(SolveAsync(), $"Devre çözümü ({stepName})");
            if (!_hasResults || _lastResponse == null)
            {
                throw new InvalidOperationException(
                    $"Çözüm sonucu görüntülenemedi ({stepName}). Durum: {TxtStatus.Text}");
            }
        }

        private async Task WaitForUiIdleAsync(string stepName)
        {
            var idleTask = Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle).Task;
            await WithTimeoutAsync(idleTask, $"Arayüz boşta bekleme ({stepName})");
            UpdateLayout();
        }

        private async Task ScrollPracticeIntoViewAsync(Views.PracticeView pv, string stepName)
        {
            await WaitForUiIdleAsync(stepName);
            var sv = AnalysisPanel.ResultsScrollViewer;
            if (sv.Content is UIElement content && pv.BtnCheck.IsVisible)
            {
                var bottomPt = pv.BtnCheck.TranslatePoint(new Point(0, pv.BtnCheck.ActualHeight + 12), content);
                double targetOffset = Math.Max(0, bottomPt.Y - sv.ViewportHeight);
                sv.ScrollToVerticalOffset(targetOffset);
                await WaitForUiIdleAsync(stepName);
            }
        }

        private static async Task WithTimeoutAsync(Task task, string description, int timeoutSeconds = DemoWaitTimeoutSeconds)
        {
            var delayTask = Task.Delay(TimeSpan.FromSeconds(timeoutSeconds));
            var completed = await Task.WhenAny(task, delayTask);
            if (completed == delayTask)
            {
                throw new TimeoutException($"İşlem zaman aşımına uğradı ({timeoutSeconds} sn): {description}");
            }
            await task;
        }

        private DemoShotEntry CaptureWindowShot(
            string outDir,
            string name,
            string label,
            bool includeExplanation = false,
            bool includePracticeTargets = false,
            Dictionary<string, double[]>? extraTargets = null)
        {
            string fileName = $"{name}.png";
            string fullPath = Path.Combine(outDir, fileName);
            SaveScreenshot(fullPath, DemoScale);

            var targets = new Dictionary<string, double[]>();

            // Her "window" görüntüsü için standart hedefler
            if (TryGetElementBounds(CanvasScrollViewer) is { } canvasBounds)
                targets["canvas"] = canvasBounds;
            if (TryGetElementBounds(AnalysisPanel) is { } panelBounds)
                targets["panel"] = panelBounds;
            if (TryGetElementBounds(SidebarCard) is { } sidebarBounds)
                targets["sidebar"] = sidebarBounds;
            if (TryGetElementBounds(AnalysisPanel.BtnSolve) is { } solveBounds)
                targets["solveButton"] = solveBounds;
            if (TryGetElementBounds(BtnTheme) is { } themeBounds)
                targets["themeButton"] = themeBounds;

            if (includeExplanation)
            {
                if (TryGetElementBounds(AnalysisPanel.ResultsScrollViewer) is { } expBounds)
                    targets["explanation"] = expBounds;
            }

            if (includePracticeTargets)
            {
                var pv = AnalysisPanel.CurrentPracticeView;
                if (pv != null)
                {
                    if (pv.Questions.Count > 0 && TryGetElementBounds(pv.GetAnswerBox(pv.Questions[0].Id)) is { } a1Bounds)
                        targets["answer1"] = a1Bounds;
                    if (pv.Questions.Count > 1 && TryGetElementBounds(pv.GetAnswerBox(pv.Questions[1].Id)) is { } a2Bounds)
                        targets["answer2"] = a2Bounds;
                    if (TryGetElementBounds(pv.BtnCheck) is { } checkBounds)
                        targets["checkButton"] = checkBounds;
                }
                if (TryGetElementBounds(AnalysisPanel.CardProblemCode) is { } codeBounds)
                    targets["codeCard"] = codeBounds;
            }

            if (extraTargets != null)
            {
                foreach (var kv in extraTargets)
                {
                    targets[kv.Key] = kv.Value;
                }
            }

            return new DemoShotEntry(
                Name: name,
                File: fileName,
                Kind: "window",
                Label: label,
                Page: null,
                Targets: targets);
        }

        private void RenderPracticeWorksheetPage(int problemCode, string outputPath, double scale)
        {
            var circuitBmp = RenderCircuitBitmap();
            var settings = AnalysisPanel.GetAnalysisSettings();
            string methodDisplay = settings.Type switch
            {
                AnalysisTypes.Nodal => "Düğüm gerilimleri yöntemi",
                AnalysisTypes.Mesh => "Çevre akımları yöntemi",
                AnalysisTypes.Thevenin => "Thevenin eşdeğeri",
                AnalysisTypes.Norton => "Norton eşdeğeri",
                AnalysisTypes.Superposition => "Süperpozisyon yöntemi",
                _ => settings.Type ?? "Düğüm gerilimleri yöntemi"
            };

            string? terminals = null;
            if (settings.Type == AnalysisTypes.Thevenin || settings.Type == AnalysisTypes.Norton)
            {
                terminals = $"{settings.TerminalPositive ?? "?"} - {settings.TerminalNegative ?? "?"}";
            }
            string? freq = !string.IsNullOrWhiteSpace(settings.Frequency) ? settings.Frequency + " Hz" : null;

            var input = new PrintInput
            {
                Response = _lastResponse,
                Title = $"Soru #{problemCode}",
                Date = DateTime.Now,
                CircuitImage = circuitBmp,
                Method = methodDisplay,
                Terminals = terminals,
                Frequency = freq,
                IsPracticeMode = true,
                PracticeQuestions = _lastResponse?.Results?.Practice
            };

            var doc = SolutionPrinter.BuildDocument(input);
            RenderPrintPreview(doc, outputPath, scale);
        }

        private FrameworkElement? GetSidebarButtonForElement(CircuitElement element) => element switch
        {
            Resistor => BtnAddResistor,
            Capacitor => BtnAddCapacitor,
            Inductor => BtnAddInductor,
            ImpedanceElement => BtnAddImpedance,
            VoltageSource => BtnAddVoltageSource,
            AcVoltageSource => BtnAddAcSource,
            CurrentSource => BtnAddCurrentSource,
            AcCurrentSource => BtnAddAcCurrentSource,
            GroundElement => BtnAddGround,
            TestProbe => BtnAddProbe,
            _ => null,
        };

        private double[]? TryGetElementBounds(FrameworkElement? element)
        {
            if (element == null || !element.IsVisible || Content is not FrameworkElement rootContent)
                return null;

            try
            {
                var rect = element.TransformToAncestor(rootContent).TransformBounds(new Rect(element.RenderSize));
                if (rect.IsEmpty || double.IsNaN(rect.X) || double.IsNaN(rect.Y) || rect.Width <= 0 || rect.Height <= 0)
                    return null;

                return new[]
                {
                    Math.Round(rect.X, 1),
                    Math.Round(rect.Y, 1),
                    Math.Round(rect.Width, 1),
                    Math.Round(rect.Height, 1),
                };
            }
            catch
            {
                return null;
            }
        }

        private double[]? TryGetWireBounds(Wire? wire)
        {
            if (wire?.Visual == null || Content is not FrameworkElement rootContent)
                return null;

            try
            {
                var start = wire.StartPin.AbsolutePosition;
                var end = wire.EndPin.AbsolutePosition;
                double minX = Math.Min(start.X, end.X);
                double minY = Math.Min(start.Y, end.Y);
                double w = Math.Max(4.0, Math.Abs(end.X - start.X));
                double h = Math.Max(4.0, Math.Abs(end.Y - start.Y));

                var localRect = new Rect(minX, minY, w, h);
                var rect = CircuitCanvas.TransformToAncestor(rootContent).TransformBounds(localRect);
                if (rect.IsEmpty || double.IsNaN(rect.X) || double.IsNaN(rect.Y) || rect.Width <= 0 || rect.Height <= 0)
                    return null;

                return new[]
                {
                    Math.Round(rect.X, 1),
                    Math.Round(rect.Y, 1),
                    Math.Round(rect.Width, 1),
                    Math.Round(rect.Height, 1),
                };
            }
            catch
            {
                return null;
            }
        }

        private void SaveScreenshot(string path, double scale)
        {
            var root = (FrameworkElement)Content;
            double dipWidth = root.ActualWidth > 0 ? root.ActualWidth : Width;
            double dipHeight = root.ActualHeight > 0 ? root.ActualHeight : Height;
            int width = (int)Math.Ceiling(dipWidth * scale);
            int height = (int)Math.Ceiling(dipHeight * scale);
            double dpi = 96.0 * scale;

            var bitmap = new RenderTargetBitmap(width, height, dpi, dpi, PixelFormats.Pbgra32);
            var visual = new DrawingVisual();
            using (var dc = visual.RenderOpen())
            {
                dc.DrawRectangle(Background, null, new Rect(0, 0, dipWidth, dipHeight));
                var vb = new VisualBrush(root)
                {
                    Viewbox = new Rect(0, 0, dipWidth, dipHeight),
                    ViewboxUnits = BrushMappingMode.Absolute,
                    Stretch = Stretch.None,
                };
                dc.DrawRectangle(vb, null, new Rect(0, 0, dipWidth, dipHeight));
            }
            bitmap.Render(visual);

            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(bitmap));
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            using var stream = File.Create(path);
            encoder.Save(stream);
        }

        private static void RenderPrintPreview(FlowDocument doc, string outputPath, double scale)
        {
            doc.PageWidth = 793.7;
            doc.PageHeight = 1122.5;
            doc.ColumnWidth = 793.7;
            doc.PagePadding = new Thickness(75.6);

            var paginator = ((IDocumentPaginatorSource)doc).DocumentPaginator;
            paginator.PageSize = new Size(793.7, 1122.5);

            var page = paginator.GetPage(0);
            double dipWidth = Math.Ceiling(paginator.PageSize.Width);
            double dipHeight = Math.Ceiling(paginator.PageSize.Height);
            int width = (int)Math.Ceiling(dipWidth * scale);
            int height = (int)Math.Ceiling(dipHeight * scale);
            double dpi = 96.0 * scale;

            var rtb = new RenderTargetBitmap(width, height, dpi, dpi, PixelFormats.Pbgra32);
            var visual = new DrawingVisual();
            using (var dc = visual.RenderOpen())
            {
                var bgBrush = (Brush)doc.FindResource("Brush.Bg.Surface");
                dc.DrawRectangle(bgBrush, null, new Rect(0, 0, dipWidth, dipHeight));
                dc.DrawRectangle(new VisualBrush(page.Visual), null, new Rect(0, 0, dipWidth, dipHeight));
            }
            rtb.Render(visual);

            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(rtb));
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
            using var stream = File.Create(outputPath);
            encoder.Save(stream);
        }
    }
}
