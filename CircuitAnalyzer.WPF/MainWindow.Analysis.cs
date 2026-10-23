using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
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
    /// <summary>
    /// Ana pencere — çözücü bağlantısı, çözme akışı, sonuç etiketleri,
    /// örnek devreler ve otomatik ekran testi (--selftest).
    /// </summary>
    public partial class MainWindow
    {
        private readonly BackendManager _backend = new();
        private Task? _backendStartTask;
        private AnalysisApiClient? _api;
        private ResultOverlay? _overlay;
        private NetlistResult? _lastNetlist;
        private AnalysisResponseDto? _lastResponse;
        private int _lastSolveVersion = -1;

        /// <summary>Her devre değişikliğinde artar — çözüm sürerken değişiklik olursa sonuç bayat sayılır.</summary>
        private int _circuitVersion;
        private bool _hasResults;

        // ═══════════════════════════════════════════════════════
        //  BAŞLATMA / KAPATMA
        // ═══════════════════════════════════════════════════════

        private void InitializeAnalysis()
        {
            _overlay = new ResultOverlay(CircuitCanvas);
            AnalysisPanel.SolveRequested += async (_, _) => await SolveAsync();
            Closed += (_, _) => _backend.Dispose();

            AnalysisPanel.AnswerChecker = async req =>
            {
                if (_api == null) throw new BackendUnavailableException("Çözücü hazır değil.");
                return await _api.CheckAnswersAsync(req);
            };
            AnalysisPanel.SolutionRevealed += (_, _) => ShowOverlayForLastSolve();

            AnalysisPanel.LlmStatusProvider = ct => _api != null ? _api.TryGetLlmStatusAsync(ct) : Task.FromResult<LlmStatusDto?>(null);
            AnalysisPanel.LlmAsker = async (req, ct) =>
            {
                if (_api == null) throw new BackendUnavailableException("Çözücü hazır değil.");
                return await _api.AskAsync(req, ct);
            };
            AnalysisPanel.LlmStartOllama = ct => _api != null ? _api.StartOllamaAsync(ct) : Task.FromResult(false);
            AnalysisPanel.LlmStartPull = (m, ct) => _api != null ? _api.StartModelPullAsync(m, ct) : Task.FromException<LlmPullStatusDto>(new BackendUnavailableException("Çözücü hazır değil."));
            AnalysisPanel.LlmGetPull = ct => _api != null ? _api.GetModelPullAsync(ct) : Task.FromResult<LlmPullStatusDto?>(null);
            AnalysisPanel.LlmCancelPull = ct => _api != null ? _api.CancelModelPullAsync(ct) : Task.FromResult(false);

            RefreshCircuitInfo();
            _backendStartTask = StartBackendAsync();

            var args = Environment.GetCommandLineArgs();
            if (TryGetOnboardingShot(args, out var obs))
            {
                _ = RunOnboardingShotAsync(obs!);
            }
            else if (TryGetAboutShot(args, out var aboutPng))
            {
                _ = RunAboutShotAsync(aboutPng!);
            }
            else if (TryGetShortcutsShot(args, out var shortcutsPng))
            {
                _ = RunShortcutsShotAsync(shortcutsPng!);
            }
            else if (TryGetEditorShot(args, out var editorPng))
            {
                _ = RunEditorShotAsync(editorPng!);
            }
            else if (TryGetTourShot(args, out var ts))
            {
                _ = RunTourShotAsync(ts!);
            }
            else if (TryGetJunctionShot(args, out var junctionPng))
            {
                _ = RunJunctionShotAsync(junctionPng!);
            }
            else if (SelfTestOptions.TryParse(args, out var selfTest))
            {
                _ = RunSelfTestAsync(selfTest!);
            }
        }

        private async Task StartBackendAsync()
        {
            AnalysisPanel.SetBackendStatus(BackendState.Starting, "Çözücü başlatılıyor…");
            try
            {
                var progress = new Progress<string>(msg => TxtStatus.Text = msg);
                _api = await _backend.StartAsync(progress);
                var health = await _api.TryGetHealthAsync();
                AnalysisPanel.SetBackendStatus(BackendState.Ready,
                    $"Çözücü hazır — {_api.BaseAddress} (sürüm {health?.Version})");
                TxtStatus.Text = "Çözücü hazır — devreyi çizip ▶ Çöz'e basın (F5)";
            }
            catch (BackendUnavailableException ex)
            {
                AnalysisPanel.SetBackendStatus(BackendState.Failed, ex.Message);
                AnalysisPanel.ShowError("Çözücü başlatılamadı", ex.Message);
                TxtStatus.Text = "Çözücü başlatılamadı — ayrıntılar sağ panelde";
            }
        }

        // ═══════════════════════════════════════════════════════
        //  DEVRE DEĞİŞİKLİĞİ
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Devre her değiştiğinde çağrılır: eski sonuç etiketlerini siler,
        /// paneli "bayat" işaretler ve düğüm numaralarını günceller.
        /// </summary>
        private void OnCircuitChanged()
        {
            _circuitVersion++;
            if (_hasResults)
            {
                AnalysisPanel.MarkStale();
                _hasResults = false;
            }
            RefreshCircuitInfo();
            UpdateEmptyCanvasHelper();

            if (!_isRestoringHistory)
            {
                _undoHistory.Record(CircuitDocument.Snapshot(_elements, _wires));
                _isDirty = true;
                UpdateTitle();
            }
        }

        private void UpdateEmptyCanvasHelper()
        {
            if (EmptyCanvasHelper != null)
            {
                EmptyCanvasHelper.Visibility = _elements.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
            }
        }

        private void RefreshCircuitInfo()
        {
            var netlist = NetlistBuilder.Build(_elements, _wires);
            AnalysisPanel.SetCircuitInfo(netlist.HasAcSource, netlist.HasPhasorSource);
            // Tek pinlik düğüm = bağlanmamış uç; terminal olarak sunulmaz
            AnalysisPanel.SetAvailableNodes(netlist.NodePins
                .Where(kv => kv.Key == 0 || kv.Value.Count >= 2)
                .Select(kv => kv.Key)
                .OrderBy(n => n)
                .ToList());
            _overlay?.ShowNodeNumbers(netlist, _wires);
        }

        // ═══════════════════════════════════════════════════════
        //  ÇÖZME
        // ═══════════════════════════════════════════════════════

        private async Task SolveAsync()
        {
            if (_api == null)
            {
                AnalysisPanel.ShowError("Çözücü hazır değil",
                    "Çözücü henüz başlamadı veya başlatılamadı. Lütfen birkaç saniye bekleyin.");
                return;
            }
            if (!_elements.Any(e => e is not GroundElement and not TestProbe and not JunctionElement))
            {
                AnalysisPanel.ShowError("Devre boş", "Önce araç kutusundan eleman ekleyip tellerle bağlayın.");
                return;
            }
            if (!AnalysisPanel.TryGetOptions(out var options, out string? optionError))
            {
                AnalysisPanel.ShowError("Analiz ayarı eksik", optionError ?? "Ayarları kontrol edin.");
                return;
            }

            var netlist = NetlistBuilder.Build(_elements, _wires);
            var request = new AnalysisRequestDto
            {
                Netlist = netlist.Text,
                Mode = netlist.HasAcSource ? AnalysisModes.AcPhasor : AnalysisModes.Dc,
                Frequency = netlist.HasAcSource ? options!.Frequency : null,
                AnalysisType = options!.AnalysisType,
                TheveninTerminals = options.AnalysisType == AnalysisTypes.Nodal
                    ? null
                    : new TerminalsDto
                    {
                        NodePositive = options.TerminalPositive ?? "",
                        NodeNegative = options.TerminalNegative,
                    },
            };

            int versionAtStart = _circuitVersion;
            AnalysisPanel.SetBusy(true);
            TxtStatus.Text = "Çözülüyor…";
            try
            {
                var response = await _api.AnalyzeAsync(request);
                AnalysisPanel.CurrentRequest = request;
                AnalysisPanel.ShowResults(response);

                if (versionAtStart != _circuitVersion)
                {
                    // Çözüm sürerken devre değişti — sonuçlar eski devreye ait
                    AnalysisPanel.MarkStale();
                    TxtStatus.Text = "Çözüm sırasında devre değişti — tekrar ▶ Çöz'e basın";
                    return;
                }

                _lastNetlist = netlist;
                _lastResponse = response;
                _lastSolveVersion = _circuitVersion;

                if (AnalysisPanel.IsShowingPractice)
                {
                    // Önceki normal çözümden kalan değer etiketleri cevapları göstermesin
                    _overlay?.ShowNodeNumbers(netlist, _wires);
                    _hasResults = true;
                    TxtStatus.Text = "Alıştırma: soruları çözüp cevaplarınızı kontrol edin (sonuçlar gizli)";
                }
                else
                {
                    _overlay?.ShowResults(netlist, _elements, _wires, response);
                    _hasResults = true;
                    TxtStatus.Text = response.Status == "success"
                        ? $"Çözüldü — {netlist.NodeCount} düğüm, {response.SolutionSteps.Count} çözüm adımı"
                        : "Uyarılarla çözüldü — ayrıntılar sağ panelde";
                }
            }
            catch (AnalysisRequestException ex)
            {
                AnalysisPanel.ShowError("Devre çözülemedi", ex.Message);
                TxtStatus.Text = "Devre çözülemedi";
            }
            catch (BackendUnavailableException ex)
            {
                AnalysisPanel.SetBackendStatus(BackendState.Failed, ex.Message);
                AnalysisPanel.ShowError("Çözücüye ulaşılamadı",
                    ex.Message + "\n\nProgramı kapatıp yeniden açmayı deneyin.");
                TxtStatus.Text = "Çözücüye ulaşılamadı";
            }
            finally
            {
                AnalysisPanel.SetBusy(false);
            }
        }

        private void ShowOverlayForLastSolve()
        {
            if (_lastResponse != null && _lastSolveVersion == _circuitVersion)
            {
                _overlay?.ShowResults(_lastNetlist!, _elements, _wires, _lastResponse);
                TxtStatus.Text = "Çözüm gösteriliyor";
            }
        }

        // ═══════════════════════════════════════════════════════
        //  ÖRNEK DEVRELER
        // ═══════════════════════════════════════════════════════

        private void BtnExamples_Click(object sender, RoutedEventArgs e)
        {
            var menu = new ContextMenu
            {
                PlacementTarget = (UIElement)sender,
                Placement = System.Windows.Controls.Primitives.PlacementMode.Right,
            };
            foreach (var factory in ExampleCircuits.All)
            {
                var example = factory();
                var item = new MenuItem
                {
                    Header = example.Name,
                    ToolTip = example.Description,
                };
                item.Click += (_, _) =>
                {
                    if (!PromptSaveIfDirty())
                        return;
                    LoadExample(factory());
                };
                menu.Items.Add(item);
            }
            menu.IsOpen = true;
        }

        private void BtnNewProblem_Click(object sender, RoutedEventArgs e)
        {
            var menu = new ContextMenu
            {
                PlacementTarget = (UIElement)sender,
                Placement = System.Windows.Controls.Primitives.PlacementMode.Right,
            };

            // Öğretmen türü seçer, program o türde soru ve kodunu üretir;
            // öğrenci kodu girince tür seçmeden aynı soruyu görür
            menu.Items.Add(new MenuItem
            {
                Header = "Yeni soru üret:",
                IsEnabled = false,
            });
            foreach (var (kind, title) in ProblemGenerator.Kinds)
            {
                var item = new MenuItem
                {
                    Header = "   " + title,
                };
                item.Click += (_, _) =>
                {
                    if (!PromptSaveIfDirty())
                        return;
                    LoadProblem(ProblemGenerator.NewCode(kind));
                };
                menu.Items.Add(item);
            }
            menu.Items.Add(new Separator());

            var itemWithCode = new MenuItem
            {
                Header = "Soru koduyla aç…",
            };
            itemWithCode.Click += (_, _) =>
            {
                var dialog = new ProblemCodeDialog { Owner = this };
                if (dialog.ShowDialog() == true && dialog.Code is { } code)
                {
                    if (!PromptSaveIfDirty())
                        return;
                    LoadProblem(code);
                }
            };
            menu.Items.Add(itemWithCode);

            menu.IsOpen = true;
        }

        private void LoadProblem(int code)
        {
            var problem = ProblemGenerator.Generate(code);
            LoadExample(problem);
            _problemCode = code;
            AnalysisPanel.IsPracticeMode = true;
            AnalysisPanel.SetProblemCode(code);
            TxtStatus.Text = $"Soru kodu {code} — {problem.Description} Aynı soruyu öğrencilere vermek için bu kodu " +
                             "paylaşın (Yeni Soru → Soru koduyla aç). Çözmek için ▶ Çöz'e basın; sonuçlar gizli kalır.";
        }

        public void LoadExample(ExampleCircuit example)
        {
            ClearCircuit();
            _problemCode = example.ProblemCode;
            AnalysisPanel.SetProblemCode(example.ProblemCode);

            foreach (var element in example.Elements)
                AddElementToCanvasCore(element);
            foreach (var wire in example.Wires)
            {
                _wires.Add(wire);
                CircuitCanvas.Children.Add(wire.CreateOrUpdateVisual());
            }
            RefreshJunctionWireCounts();
            SyncCountersFromIds();

            OnCircuitChanged();
            AnalysisPanel.ClearResults();
            AnalysisPanel.SetAnalysisType(example.SuggestedAnalysisType, example.SuggestedTerminal);
            TxtStatus.Text = $"Örnek yüklendi: {example.Name} — {example.Description}";

            _isDirty = false;
            _undoHistory.Reset(CircuitDocument.Snapshot(_elements, _wires));
            UpdateTitle();
            AutoFitOrScrollCircuit();
        }

        /// <summary>
        /// Yüklenen elemanların ID'lerine göre sayaçları ayarlar
        /// (yeni eklenen R'ler R3, R4… diye devam etsin, ID çakışmasın).
        /// </summary>
        private void SyncCountersFromIds()
        {
            int Max(string prefix) => _elements
                .Select(e => e.Id)
                .Where(id => id.StartsWith(prefix, StringComparison.Ordinal))
                .Select(id => int.TryParse(id[prefix.Length..], out int n) ? n : 0)
                .DefaultIfEmpty(0)
                .Max();

            _resistorCounter = Max("R");
            _capacitorCounter = Max("C");
            _inductorCounter = Max("L");
            _impedanceCounter = Max("Z");
            _acSourceCounter = Max("VAC");
            _voltageSourceCounter = _elements.OfType<VoltageSource>()
                .Select(e => int.TryParse(e.Id[1..], out int n) ? n : 0)
                .DefaultIfEmpty(0).Max();
            _acCurrentSourceCounter = Max("IAC");
            _currentSourceCounter = _elements.OfType<CurrentSource>()
                .Select(e => int.TryParse(e.Id[1..], out int n) ? n : 0)
                .DefaultIfEmpty(0).Max();
            _groundCounter = Max("GND");
            _probeCounter = Math.Max(Max("VP"), Max("IP"));
            _junctionCounter = Max("J");
        }

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
                   args.Contains("--wire-select-shot", StringComparer.OrdinalIgnoreCase);
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
