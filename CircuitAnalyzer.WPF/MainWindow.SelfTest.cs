using System.IO;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;

namespace CircuitAnalyzer.WPF
{
    // MainWindow parçası: otomatik ekran testleri ve komut satırı bayrak ayrıştırıcıları.
    public partial class MainWindow
    {
        // ═══════════════════════════════════════════════════════
        //  OTOMATİK EKRAN TESTİ  (--selftest / --onboarding-shot / --tour-shot / --editor-shot)
        // ═══════════════════════════════════════════════════════

        internal sealed record OnboardingShotOptions(int Page, string OutputPng);
        internal sealed record TourShotOptions(int Step, string OutputPng);

        internal static bool HasAnySelfTest(string[] args)
        {
            return args.Contains("--selftest", StringComparer.OrdinalIgnoreCase) ||
                   args.Contains("--onboarding-shot", StringComparer.OrdinalIgnoreCase) ||
                   args.Contains("--about-shot", StringComparer.OrdinalIgnoreCase) ||
                   args.Contains("--shortcuts-shot", StringComparer.OrdinalIgnoreCase) ||
                   args.Contains("--editor-shot", StringComparer.OrdinalIgnoreCase) ||
                   args.Contains("--tour-shot", StringComparer.OrdinalIgnoreCase) ||
                   args.Contains("--junction-shot", StringComparer.OrdinalIgnoreCase) ||
                   args.Contains("--wire-select-shot", StringComparer.OrdinalIgnoreCase) ||
                   args.Contains("--bend-shot", StringComparer.OrdinalIgnoreCase) ||
                   args.Contains("--dependent-shot", StringComparer.OrdinalIgnoreCase);
        }

        internal static bool TryGetOnboardingShot(string[] args, out OnboardingShotOptions? options)
        {
            options = null;
            int i = Array.FindIndex(args, a => string.Equals(a, "--onboarding-shot", StringComparison.OrdinalIgnoreCase));
            if (i < 0 || i + 2 >= args.Length || !int.TryParse(args[i + 1], out int page))
                return false;
            options = new OnboardingShotOptions(page, Path.GetFullPath(args[i + 2]));
            return true;
        }

        internal static bool TryGetAboutShot(string[] args, out string? outputPng)
        {
            outputPng = null;
            int i = Array.FindIndex(args, a => string.Equals(a, "--about-shot", StringComparison.OrdinalIgnoreCase));
            if (i < 0 || i + 1 >= args.Length)
                return false;
            outputPng = Path.GetFullPath(args[i + 1]);
            return true;
        }

        internal static bool TryGetShortcutsShot(string[] args, out string? outputPng)
        {
            outputPng = null;
            int i = Array.FindIndex(args, a => string.Equals(a, "--shortcuts-shot", StringComparison.OrdinalIgnoreCase));
            if (i < 0 || i + 1 >= args.Length)
                return false;
            outputPng = Path.GetFullPath(args[i + 1]);
            return true;
        }

        internal static bool TryGetEditorShot(string[] args, out string? outputPng)
        {
            outputPng = null;
            int i = Array.FindIndex(args, a => string.Equals(a, "--editor-shot", StringComparison.OrdinalIgnoreCase));
            if (i < 0 || i + 1 >= args.Length)
                return false;
            outputPng = Path.GetFullPath(args[i + 1]);
            return true;
        }

        internal static bool TryGetTourShot(string[] args, out TourShotOptions? options)
        {
            options = null;
            int i = Array.FindIndex(args, a => string.Equals(a, "--tour-shot", StringComparison.OrdinalIgnoreCase));
            if (i < 0 || i + 2 >= args.Length || !int.TryParse(args[i + 1], out int step))
                return false;
            options = new TourShotOptions(step, Path.GetFullPath(args[i + 2]));
            return true;
        }

        internal static bool TryGetJunctionShot(string[] args, out string? outputPng)
        {
            outputPng = null;
            int i = Array.FindIndex(args, a =>
                string.Equals(a, "--junction-shot", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(a, "--wire-select-shot", StringComparison.OrdinalIgnoreCase));
            if (i < 0 || i + 1 >= args.Length)
                return false;
            outputPng = Path.GetFullPath(args[i + 1]);
            return true;
        }

        internal static bool TryGetBendShot(string[] args, out string? outputPng)
        {
            outputPng = null;
            int i = Array.FindIndex(args, a => string.Equals(a, "--bend-shot", StringComparison.OrdinalIgnoreCase));
            if (i < 0 || i + 1 >= args.Length)
                return false;
            outputPng = Path.GetFullPath(args[i + 1]);
            return true;
        }

        internal static bool TryGetDependentShot(string[] args, out string? outputPng)
        {
            outputPng = null;
            int i = Array.FindIndex(args, a => string.Equals(a, "--dependent-shot", StringComparison.OrdinalIgnoreCase));
            if (i < 0 || i + 1 >= args.Length)
                return false;
            outputPng = Path.GetFullPath(args[i + 1]);
            return true;
        }

        private sealed record SelfTestOptions(
            int ExampleIndex,
            string OutputPng,
            bool Practice = false,
            int? ProblemCode = null,
            string? AskQuestion = null,
            string? OpenFile = null,
            double? ZoomPercent = null,
            string? PrintPreview = null)
        {
            public static bool TryParse(string[] args, out SelfTestOptions? options)
            {
                options = null;
                int i = Array.IndexOf(args, "--selftest");
                if (i < 0 || i + 2 >= args.Length || !int.TryParse(args[i + 1], out int index))
                    return false;
                int? problemCode = null;
                int p = Array.FindIndex(args, a => string.Equals(a, "--problem", StringComparison.OrdinalIgnoreCase));
                if (p >= 0 && p + 1 < args.Length && int.TryParse(args[p + 1], out int parsedCode))
                {
                    problemCode = parsedCode;
                }
                bool practice = args.Contains("--practice", StringComparer.OrdinalIgnoreCase) || problemCode.HasValue;
                string? askQuestion = null;
                int askIdx = Array.FindIndex(args, a => string.Equals(a, "--ask", StringComparison.OrdinalIgnoreCase));
                if (askIdx >= 0 && askIdx + 1 < args.Length)
                {
                    var qTokens = new List<string>();
                    for (int k = askIdx + 1; k < args.Length; k++)
                    {
                        if (args[k].StartsWith("--")) break;
                        qTokens.Add(args[k]);
                    }
                    askQuestion = string.Join(" ", qTokens).Trim('"');
                }
                string? openFile = null;
                int openIdx = Array.FindIndex(args, a => string.Equals(a, "--open", StringComparison.OrdinalIgnoreCase));
                if (openIdx >= 0 && openIdx + 1 < args.Length)
                {
                    openFile = Path.GetFullPath(args[openIdx + 1].Trim('"'));
                }
                double? zoomPercent = null;
                int zoomIdx = Array.FindIndex(args, a => string.Equals(a, "--zoom", StringComparison.OrdinalIgnoreCase));
                if (zoomIdx >= 0 && zoomIdx + 1 < args.Length && double.TryParse(args[zoomIdx + 1], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out double zp))
                {
                    zoomPercent = zp;
                }
                string? printPreview = null;
                int printIdx = Array.FindIndex(args, a => string.Equals(a, "--print-preview", StringComparison.OrdinalIgnoreCase));
                if (printIdx >= 0 && printIdx + 1 < args.Length)
                {
                    printPreview = Path.GetFullPath(args[printIdx + 1]);
                }
                options = new SelfTestOptions(index, Path.GetFullPath(args[i + 2]), practice, problemCode, askQuestion, openFile, zoomPercent, printPreview);
                return true;
            }
        }

        /// <summary>
        /// Örnek devreyi yükler, çözer, pencerenin ekran görüntüsünü PNG olarak
        /// kaydeder ve programı kapatır. Çıkış kodu: 0 = başarılı, 1 = hata.
        /// Yanına aynı adla .txt özet yazılır.
        /// </summary>
        private async Task RunSelfTestAsync(SelfTestOptions options)
        {
            var summary = new StringBuilder();
            int exitCode = 1;
            // Kullanıcının ekranını rahatsız etmesin — çizim ekran dışında da yapılır
            WindowStartupLocation = WindowStartupLocation.Manual;
            Left = -20000;
            Top = 0;
            ShowActivated = false;
            Height = 1500;
            try
            {
                if (options.OpenFile is { } filePath)
                {
                    bool opened = OpenFile(filePath, isSelfTest: true);
                    if (!opened)
                        throw new InvalidOperationException($"Dosya açılamadı: {filePath}");
                    summary.AppendLine($"Dosya açıldı: {filePath}");
                }
                else if (options.ProblemCode is { } code)
                {
                    var problem = ProblemGenerator.Generate(code);
                    LoadProblem(code);
                    summary.AppendLine($"Soru: #{code} — {problem.Description} — yöntem {problem.SuggestedAnalysisType}");
                }
                else
                {
                    var example = ExampleCircuits.All[options.ExampleIndex]();
                    LoadExample(example);
                    summary.AppendLine($"Örnek: {example.Name}");
                }

                if (_backendStartTask != null)
                    await _backendStartTask;
                if (_api == null)
                    throw new InvalidOperationException("Çözücü başlamadı");

                if (options.Practice)
                {
                    AnalysisPanel.IsPracticeMode = true;
                }

                await SolveAsync();

                if (options.Practice && AnalysisPanel.CurrentPracticeView is { } pv)
                {
                    if (pv.Questions.Count > 0)
                    {
                        var q1 = pv.Questions[0];
                        pv.GetAnswerBox(q1.Id).Text = q1.Expected.RectangularStr;
                    }
                    if (pv.Questions.Count > 1)
                    {
                        var q2 = pv.Questions[1];
                        pv.GetAnswerBox(q2.Id).Text = "1234";
                    }

                    await pv.CheckAsync();
                    pv.ShowNextHint();
                }

                if (options.AskQuestion is { } question && AnalysisPanel.CurrentAssistantView is { } assistant)
                {
                    assistant.IsExpanded = true;
                    await assistant.RefreshStatusAsync();
                    if (assistant.IsAvailable)
                    {
                        await assistant.AskAsync(question);
                    }
                }

                if (options.ZoomPercent is { } zoomVal)
                {
                    SetZoom(zoomVal / 100.0);
                }

                // Düzenin ve etiketlerin çizilmesini bekle
                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                UpdateLayout();

                SaveScreenshot(options.OutputPng);
                summary.AppendLine($"Durum çubuğu: {TxtStatus.Text}");
                summary.AppendLine($"Sonuç var: {_hasResults}");

                if (options.PrintPreview is { } previewPath)
                {
                    var circuitBmp = RenderCircuitBitmap();
                    string title = options.ProblemCode.HasValue
                        ? $"Soru #{options.ProblemCode.Value}"
                        : (!string.IsNullOrEmpty(_currentFilePath) ? Path.GetFileName(_currentFilePath) : "Örnek");

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
                        Title = title,
                        Date = DateTime.Now,
                        CircuitImage = circuitBmp,
                        Method = methodDisplay,
                        Terminals = terminals,
                        Frequency = freq,
                        IsPracticeMode = options.Practice,
                        PracticeQuestions = _lastResponse?.Results?.Practice
                    };

                    var doc = SolutionPrinter.BuildDocument(input);
                    RenderPrintPreview(doc, previewPath);
                    summary.AppendLine($"Yazdırma önizlemesi: {previewPath}");
                }

                if (options.Practice && AnalysisPanel.CurrentPracticeView is { } practiceView)
                {
                    foreach (var q in practiceView.Questions)
                    {
                        summary.AppendLine($"{q.Id} {q.Label} status={practiceView.GetStatus(q.Id) ?? "-"} feedback={practiceView.GetFeedback(q.Id)}");
                    }
                    summary.AppendLine($"Pratik: doğru={practiceView.CorrectCount}/{practiceView.Questions.Count}, ipucu={practiceView.HintsShown}/{practiceView.HintsAvailable}");
                }

                if (options.AskQuestion is { } askQ)
                {
                    var asst = AnalysisPanel.CurrentAssistantView;
                    string lastAns = asst?.History.LastOrDefault(h => h.Role == ChatRoles.Assistant)?.Content ?? "-";
                    summary.AppendLine($"Yapay zekâ: {asst?.StatusText ?? "-"}");
                    summary.AppendLine($"Soru: {askQ}");
                    summary.AppendLine($"Cevap: {lastAns}");
                    summary.AppendLine($"Not: {asst?.LastNote ?? "-"}");
                    summary.AppendLine($"Hata: {asst?.LastError ?? "-"}");
                }

                if (_hasResults)
                {
                    if (options.Practice)
                    {
                        var currentPv = AnalysisPanel.CurrentPracticeView;
                        exitCode = (currentPv != null && currentPv.Questions.Count > 0 && currentPv.GetStatus(currentPv.Questions[0].Id) == "correct")
                            ? 0
                            : 1;
                    }
                    else
                    {
                        exitCode = 0;
                    }
                }
                else
                {
                    exitCode = 1;
                }
            }
            catch (Exception ex)
            {
                summary.AppendLine($"HATA: {ex}");
            }
            finally
            {
                summary.AppendLine("--- Çözücü günlüğü ---");
                summary.AppendLine(_backend.LogText);
                File.WriteAllText(Path.ChangeExtension(options.OutputPng, ".txt"), summary.ToString());
                Application.Current.Shutdown(exitCode);
            }
        }

        private async Task RunOnboardingShotAsync(OnboardingShotOptions options)
        {
            try
            {
                WindowStartupLocation = WindowStartupLocation.Manual;
                Left = -20000;
                Top = 0;
                ShowActivated = false;

                int page = Math.Clamp(options.Page - 1, 0, 4);

                OnboardingOverlay.View.SetupView.StatusProvider = AnalysisPanel.LlmStatusProvider;
                OnboardingOverlay.View.SetupView.StartOllama = AnalysisPanel.LlmStartOllama;
                OnboardingOverlay.View.SetupView.StartPull = AnalysisPanel.LlmStartPull;
                OnboardingOverlay.View.SetupView.GetPull = AnalysisPanel.LlmGetPull;
                OnboardingOverlay.View.SetupView.CancelPull = AnalysisPanel.LlmCancelPull;

                if (options.Page == 5)
                {
                    if (_backendStartTask != null)
                    {
                        try { await _backendStartTask; } catch { }
                    }
                    try { await OnboardingOverlay.View.SetupView.RefreshAsync(); } catch { }
                }

                OnboardingOverlay.Show(page, animate: false);
                Show();
                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                UpdateLayout();

                SaveScreenshot(options.OutputPng);
                File.WriteAllText(Path.ChangeExtension(options.OutputPng, ".txt"), OnboardingOverlay.View.VisibleTitle);
                Application.Current.Shutdown(0);
            }
            catch (Exception ex)
            {
                File.WriteAllText(Path.ChangeExtension(options.OutputPng, ".txt"), $"HATA: {ex}");
                Application.Current.Shutdown(1);
            }
        }

        private async Task RunAboutShotAsync(string outputPng)
        {
            try
            {
                WindowStartupLocation = WindowStartupLocation.Manual;
                Left = -20000;
                Top = 0;
                ShowActivated = false;

                ShowAbout();
                Show();
                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                UpdateLayout();

                SaveScreenshot(outputPng);
                File.WriteAllText(Path.ChangeExtension(outputPng, ".txt"), "Hakkında");
                Application.Current.Shutdown(0);
            }
            catch (Exception ex)
            {
                File.WriteAllText(Path.ChangeExtension(outputPng, ".txt"), $"HATA: {ex}");
                Application.Current.Shutdown(1);
            }
        }

        private async Task RunShortcutsShotAsync(string outputPng)
        {
            try
            {
                WindowStartupLocation = WindowStartupLocation.Manual;
                Left = -20000;
                Top = 0;
                ShowActivated = false;

                Show();
                DialogOverlay.Show("Klavye ve fare kısayolları", BuildShortcutsView(), animate: false);
                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                UpdateLayout();

                SaveScreenshot(outputPng);
                File.WriteAllText(Path.ChangeExtension(outputPng, ".txt"), "Kısayollar");
                Application.Current.Shutdown(0);
            }
            catch (Exception ex)
            {
                File.WriteAllText(Path.ChangeExtension(outputPng, ".txt"), $"HATA: {ex}");
                Application.Current.Shutdown(1);
            }
        }

        private async Task RunEditorShotAsync(string outputPng)
        {
            try
            {
                WindowStartupLocation = WindowStartupLocation.Manual;
                Left = -20000;
                Top = 0;
                ShowActivated = false;

                Show();
                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                LoadExample(ExampleCircuits.All[0]());
                SelectAllElements();
                DuplicateSelected();
                UpdateLayout();

                SaveScreenshot(outputPng);
                File.WriteAllText(Path.ChangeExtension(outputPng, ".txt"), TxtStatus.Text);
                Application.Current.Shutdown(0);
            }
            catch (Exception ex)
            {
                File.WriteAllText(Path.ChangeExtension(outputPng, ".txt"), $"HATA: {ex}");
                Application.Current.Shutdown(1);
            }
        }

        private async Task RunJunctionShotAsync(string outputPng)
        {
            try
            {
                WindowStartupLocation = WindowStartupLocation.Manual;
                Left = -20000;
                Top = 0;
                ShowActivated = false;
                Height = 1100;

                var c = new ExampleCircuit
                {
                    Name = "T-Bağlantılı RLC Devresi",
                    Description = "VAC1 – R1 – L1 – C1 seri, C2 üst ucu R1–L1 telinin ortasına (J1) bağlı.",
                    SuggestedAnalysisType = AnalysisTypes.Nodal,
                };
                var vac1 = c.Add(new AcVoltageSource { Amplitude = 10, Frequency = 50, Phase = 0 }, "VAC1", 80, 200, 90);
                var r1 = c.Add(new Resistor { Value = 100 }, "R1", 160, 100);
                var l1 = c.Add(new Inductor { Value = 0.1 }, "L1", 400, 100);
                var c1 = c.Add(new Capacitor { Value = 10e-6 }, "C1", 480, 200, 90);
                var c2 = c.Add(new Capacitor { Value = 10e-6 }, "C2", 320, 200, 90);
                var gnd1 = c.Add(new GroundElement(), "GND1", 340, 300);

                c.Connect(r1.Pins[0], vac1.Pins[0]);
                c.Connect(r1.Pins[1], l1.Pins[0]);
                c.Connect(l1.Pins[1], c1.Pins[0]);
                c.Connect(vac1.Pins[1], gnd1.Pins[0]);
                c.Connect(c1.Pins[1], gnd1.Pins[0]);
                c.Connect(c2.Pins[1], gnd1.Pins[0]);

                Show();
                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                LoadExample(c);

                // C2'nin üst ucundan başlatıp R1–L1 telinin ortasına (360, 120) tıkla
                StartPinWire(c2.Pins[0]);
                HandlePinWireClick(new Point(360, 120));

                if (_backendStartTask != null)
                    await _backendStartTask;
                if (_api == null)
                    throw new InvalidOperationException("Çözücü başlamadı");

                await SolveAsync();

                // C2 dal telini (360, 180) → (360, 120) tık yoluyla seç
                var branchMid = new Point(360, 150);
                HandleCanvasLeftButtonDown(branchMid);
                HandleCanvasLeftButtonUp(branchMid);

                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                UpdateLayout();

                SaveScreenshot(outputPng);
                File.WriteAllText(Path.ChangeExtension(outputPng, ".txt"), TxtStatus.Text);
                Application.Current.Shutdown(_hasResults ? 0 : 1);
            }
            catch (Exception ex)
            {
                File.WriteAllText(Path.ChangeExtension(outputPng, ".txt"), $"HATA: {ex}");
                Application.Current.Shutdown(1);
            }
        }

        private async Task RunBendShotAsync(string outputPng)
        {
            try
            {
                WindowStartupLocation = WindowStartupLocation.Manual;
                Left = -20000;
                Top = 0;
                ShowActivated = false;
                Height = 1100;

                var c = new ExampleCircuit
                {
                    Name = "Köşeli Tel ve T-Bağlantı Devresi",
                    Description = "R1–L1 teli R2'nin etrafından köşelerle dolaşır; R2 sağ ucu bükümlü tel koluna T-bağlantı (J1) ile bağlanır.",
                    SuggestedAnalysisType = AnalysisTypes.Nodal,
                };
                var vac1 = c.Add(new AcVoltageSource { Amplitude = 10, Frequency = 50, Phase = 0 }, "VAC1", 60, 220, 90);
                var r1 = c.Add(new Resistor { Value = 100 }, "R1", 140, 140);
                var r2 = c.Add(new Resistor { Value = 220 }, "R2", 260, 140);
                var l1 = c.Add(new Inductor { Value = 0.1 }, "L1", 400, 140);
                var c1 = c.Add(new Capacitor { Value = 10e-6 }, "C1", 220, 240, 90);
                var c2 = c.Add(new Capacitor { Value = 10e-6 }, "C2", 440, 240, 90);
                var gnd1 = c.Add(new GroundElement(), "GND1", 340, 340);

                c.Connect(r1.Pins[0], vac1.Pins[0]);
                c.Connect(r2.Pins[0], c1.Pins[0]);
                c.Connect(l1.Pins[1], c2.Pins[0]);
                c.Connect(vac1.Pins[1], gnd1.Pins[0]);
                c.Connect(c1.Pins[1], gnd1.Pins[0]);
                c.Connect(c2.Pins[1], gnd1.Pins[0]);

                Show();
                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                LoadExample(c);

                // R1 sağ ucundan (220, 160) başlayıp R2'nin üstünden köşelerle L1 sol ucuna (400, 160) tel çiz
                StartPinWire(r1.Pins[1]);
                HandlePinWireClick(new Point(240, 100));
                HandlePinWireClick(new Point(380, 100));
                HandlePinWireClick(new Point(380, 160));
                HandlePinWireClick(l1.Pins[0].AbsolutePosition);

                // R2 sağ ucundan (340, 160) başlayıp üstteki bükümlü tel koluna (340, 100) T-bağlantısı (J1) indir
                StartPinWire(r2.Pins[1]);
                HandlePinWireClick(new Point(340, 100));

                if (_backendStartTask != null)
                    await _backendStartTask;
                if (_api == null)
                    throw new InvalidOperationException("Çözücü başlamadı");

                await SolveAsync();

                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                UpdateLayout();

                SaveScreenshot(outputPng);
                File.WriteAllText(Path.ChangeExtension(outputPng, ".txt"), TxtStatus.Text);
                Application.Current.Shutdown(_hasResults ? 0 : 1);
            }
            catch (Exception ex)
            {
                File.WriteAllText(Path.ChangeExtension(outputPng, ".txt"), $"HATA: {ex}");
                Application.Current.Shutdown(1);
            }
        }

        /// <summary>
        /// Dört bağımlı kaynağı (GKGK, GKAK, AKGK, AKAK) direnç dizisine bağlı çizer ve kontrol
        /// işaretlerini gösterir. Çözücü gerekmez: çözme yapılmaz.
        /// </summary>
        internal static ExampleCircuit BuildDependentShotCircuit()
        {
            var c = new ExampleCircuit
            {
                Name = "Bağımlı Kaynaklar",
                Description = "Dört bağımlı kaynak, soldaki direnç dizisinin gerilim ve akımlarıyla kontrol edilir.",
                SuggestedAnalysisType = AnalysisTypes.Nodal,
            };

            // Kontrol edilen direnç dizisi: V1 – R1 – R3 üst hat, R2 ve R4 aşağı doğru
            var v1 = c.Add(new VoltageSource { Value = 10 }, "V1", 60, 200, 90);
            var r1 = c.Add(new Resistor { Value = 100 }, "R1", 120, 160);
            var r2 = c.Add(new Resistor { Value = 200 }, "R2", 160, 200, 90);
            var r3 = c.Add(new Resistor { Value = 300 }, "R3", 220, 160);
            var r4 = c.Add(new Resistor { Value = 400 }, "R4", 260, 200, 90);
            var gnd = c.Add(new GroundElement(), "GND1", 180, 300);

            c.Connect(v1.Pins[0], r1.Pins[0]);
            c.Connect(r2.Pins[0], r3.Pins[0]);
            c.Connect(gnd.Pins[0], r2.Pins[1]);
            c.Connect(v1.Pins[1], r2.Pins[1]);
            c.Connect(r4.Pins[1], r2.Pins[1]);

            // Bir bağımlı kaynak + yük direnci + toprak
            // Yük (dikey) solda, bağımlı kaynak sağda: kaynağın + ucu yüke, − ucu toprağa bağlanır
            void Branch(DependentSource dep, double x, double dy, string loadId, string gndId)
            {
                var load = c.Add(new Resistor { Value = 1000 }, loadId, x, 200 + dy, 90);
                c.Add(dep, dep.Id, x + 100, 160 + dy);
                var g = c.Add(new GroundElement(), gndId, x + 90, 300 + dy);
                c.Connect(load.Pins[0], dep.Pins[0]);
                c.Connect(g.Pins[0], dep.Pins[1]);
                c.Connect(g.Pins[0], load.Pins[1]);
            }

            Branch(new DependentSource(DependentSourceKind.Vcvs) { Id = "E1", Gain = 3, ControlElementId = "R2" }, 440, 0, "R5", "GND2");
            Branch(new DependentSource(DependentSourceKind.Vccs) { Id = "G1", Gain = 0.5, ControlElementId = "R4", ControlReversed = true }, 700, 0, "R6", "GND3");
            Branch(new DependentSource(DependentSourceKind.Ccvs) { Id = "H1", Gain = 2, ControlElementId = "R3" }, 440, 240, "R7", "GND4");
            Branch(new DependentSource(DependentSourceKind.Cccs) { Id = "F1", Gain = -1.5, ControlElementId = "R1", ControlReversed = true }, 700, 240, "R8", "GND5");
            return c;
        }

        private async Task RunDependentShotAsync(string outputPng)
        {
            try
            {
                WindowStartupLocation = WindowStartupLocation.Manual;
                Left = -20000;
                Top = 0;
                ShowActivated = false;
                Height = 1100;

                Show();
                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                LoadExample(BuildDependentShotCircuit());

                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                UpdateLayout();

                SaveScreenshot(outputPng);

                // Ayrıntıyı okuyabilmek için devre alanının büyütülmüş görüntüsü (<ad>_canvas.png)
                SetZoom(1.0);
                UpdateLayout();
                SaveCanvasScreenshot(
                    Path.Combine(Path.GetDirectoryName(outputPng)!, Path.GetFileNameWithoutExtension(outputPng) + "_canvas.png"),
                    new Rect(40, 100, 900, 460), 1.8);

                File.WriteAllText(Path.ChangeExtension(outputPng, ".txt"),
                    string.Join(Environment.NewLine, _elements.OfType<DependentSource>().Select(d => $"{d.Id}: {d.LabelText}")) +
                    Environment.NewLine + NetlistBuilder.Build(_elements, _wires).Text);
                Application.Current.Shutdown(0);
            }
            catch (Exception ex)
            {
                File.WriteAllText(Path.ChangeExtension(outputPng, ".txt"), $"HATA: {ex}");
                Application.Current.Shutdown(1);
            }
        }

        private static void RenderPrintPreview(FlowDocument doc, string outputPath)
        {
            doc.PageWidth = 793.7;
            doc.PageHeight = 1122.5;
            doc.ColumnWidth = 793.7;
            doc.PagePadding = new Thickness(75.6);

            var paginator = ((System.Windows.Documents.IDocumentPaginatorSource)doc).DocumentPaginator;
            paginator.PageSize = new Size(793.7, 1122.5);

            var page = paginator.GetPage(0);
            int width = (int)Math.Ceiling(paginator.PageSize.Width);
            int height = (int)Math.Ceiling(paginator.PageSize.Height);

            var rtb = new RenderTargetBitmap(width, height, 96, 96, PixelFormats.Pbgra32);
            var visual = new DrawingVisual();
            using (var dc = visual.RenderOpen())
            {
                var bgBrush = (Brush)doc.FindResource("Brush.Bg.Surface");
                dc.DrawRectangle(bgBrush, null, new Rect(0, 0, width, height));
                dc.DrawRectangle(new VisualBrush(page.Visual), null, new Rect(0, 0, width, height));
            }
            rtb.Render(visual);

            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(rtb));
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
            using var stream = File.Create(outputPath);
            encoder.Save(stream);
        }

        private async Task RunTourShotAsync(TourShotOptions options)
        {
            try
            {
                WindowStartupLocation = WindowStartupLocation.Manual;
                Left = -20000;
                Top = 0;
                ShowActivated = false;

                var example = ExampleCircuits.All[0]();
                LoadExample(example);

                if (_backendStartTask != null)
                    await _backendStartTask;
                if (_api == null)
                    throw new InvalidOperationException("Çözücü başlamadı");

                await SolveAsync();

                int stepIndex = Math.Clamp(options.Step - 1, 0, 5);
                TourOverlay.Start(stepIndex);

                await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                UpdateLayout();
                TourOverlay.UpdateLayoutAndPosition();

                SaveScreenshot(options.OutputPng);
                var defaultSteps = TourSteps.CreateDefaultSteps(this);
                string title = stepIndex < defaultSteps.Count ? defaultSteps[stepIndex].Title : "";
                File.WriteAllText(Path.ChangeExtension(options.OutputPng, ".txt"), title);
                Application.Current.Shutdown(0);
            }
            catch (Exception ex)
            {
                File.WriteAllText(Path.ChangeExtension(options.OutputPng, ".txt"), $"HATA: {ex}");
                Application.Current.Shutdown(1);
            }
        }

        private void SaveScreenshotOf(Window window, string path)
        {
            var root = (FrameworkElement)window.Content;
            int width = (int)Math.Ceiling(window.ActualWidth > 0 ? window.ActualWidth : window.Width);
            int height = (int)Math.Ceiling(window.ActualHeight > 0 ? window.ActualHeight : window.Height);
            var bitmap = new RenderTargetBitmap(width, height, 96, 96, PixelFormats.Pbgra32);
            var visual = new DrawingVisual();
            using (var dc = visual.RenderOpen())
            {
                dc.DrawRectangle(window.Background, null, new Rect(0, 0, width, height));
                dc.DrawRectangle(new VisualBrush(root), null, new Rect(0, 0, width, height));
            }
            bitmap.Render(visual);

            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(bitmap));
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            using var stream = File.Create(path);
            encoder.Save(stream);
        }

        /// <summary>Çizim alanının (tuval koordinatlarında) belirtilen dikdörtgenini scale kat büyütüp PNG'ye yazar.</summary>
        private void SaveCanvasScreenshot(string path, Rect region, double scale)
        {
            int width = (int)Math.Ceiling(region.Width * scale);
            int height = (int)Math.Ceiling(region.Height * scale);
            var bitmap = new RenderTargetBitmap(width, height, 96, 96, PixelFormats.Pbgra32);
            var visual = new DrawingVisual();
            using (var dc = visual.RenderOpen())
            {
                dc.DrawRectangle((Brush)FindResource("Brush.Canvas.Bg"), null, new Rect(0, 0, width, height));
                dc.PushTransform(new ScaleTransform(scale, scale));
                dc.DrawRectangle(new VisualBrush(CircuitCanvas)
                {
                    Stretch = Stretch.None,
                    AlignmentX = AlignmentX.Left,
                    AlignmentY = AlignmentY.Top,
                    ViewboxUnits = BrushMappingMode.Absolute,
                    Viewbox = region,
                    ViewportUnits = BrushMappingMode.Absolute,
                    Viewport = new Rect(0, 0, region.Width, region.Height),
                }, null, new Rect(0, 0, region.Width, region.Height));
                dc.Pop();
            }
            bitmap.Render(visual);

            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(bitmap));
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            using var stream = File.Create(path);
            encoder.Save(stream);
        }

        private void SaveScreenshot(string path)
        {
            var root = (FrameworkElement)Content;
            int width = (int)Math.Ceiling(root.ActualWidth);
            int height = (int)Math.Ceiling(root.ActualHeight);
            var bitmap = new RenderTargetBitmap(width, height, 96, 96, PixelFormats.Pbgra32);
            // Pencere arka planı (Background) Content'e dahil değil — önce boya
            var visual = new DrawingVisual();
            using (var dc = visual.RenderOpen())
            {
                dc.DrawRectangle(Background, null, new Rect(0, 0, width, height));
                dc.DrawRectangle(new VisualBrush(root), null, new Rect(0, 0, width, height));
            }
            bitmap.Render(visual);

            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(bitmap));
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            using var stream = File.Create(path);
            encoder.Save(stream);
        }
    }
}
