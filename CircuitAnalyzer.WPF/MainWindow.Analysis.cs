using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using System.Windows.Threading;
using CircuitAnalyzer.WPF.Helpers;
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
            AnalysisPanel.ValueDisplayChanged += async (_, _) =>
            {
                if (_hasResults) await SolveAsync();
            };
            AnalysisPanel.EnlargePlotRequested += (_, data) => PlotOverlay.Show(data);
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

            var args = Environment.GetCommandLineArgs();
            // --dependent-shot çözücüye ihtiyaç duymaz: arka ucu hiç başlatma
            if (!TryGetDependentShot(args, out _))
                _backendStartTask = StartBackendAsync();

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
            else if (TryGetBendShot(args, out var bendPng))
            {
                _ = RunBendShotAsync(bendPng!);
            }
            else if (TryGetDependentShot(args, out var dependentPng))
            {
                _ = RunDependentShotAsync(dependentPng!);
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
            RefreshControlMarkers();
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
            AnalysisPanel.SetCircuitInfo(netlist.HasAcSource, needsFrequency: false);
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
            // Bağımlı kaynağın kontrol elemanı eksikse arka uca hiç gitmeden kullanıcıyı uyar
            if (!ValidateDependentSources())
                return;

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
            if (options!.Frequency == null && netlist.PhasorFrequencies.Count > 1)
            {
                AnalysisPanel.ShowError("Frekanslar farklı",
                    "Fazör kaynakların frekansları farklı. Fazör çözümü tek bir frekansta yapılır: " +
                    "sağdaki Frekans kutusuna ortak frekansı yazın ya da farklı frekanslı kaynakları " +
                    "Fiziksel moda alıp Süperpozisyon yöntemini seçin.");
                return;
            }

            var request = new AnalysisRequestDto
            {
                Netlist = netlist.Text,
                Mode = netlist.HasAcSource ? AnalysisModes.AcPhasor : AnalysisModes.Dc,
                Frequency = netlist.HasAcSource
                    ? options.Frequency ?? (netlist.PhasorFrequencies.Count == 1 ? netlist.PhasorFrequencies[0] : null)
                    : null,
                AnalysisType = options!.AnalysisType,
                TheveninTerminals = options.AnalysisType == AnalysisTypes.Nodal
                    ? null
                    : new TerminalsDto
                    {
                        NodePositive = options.TerminalPositive ?? "",
                        NodeNegative = options.TerminalNegative,
                    },
                ValueDisplay = AnalysisPanel.ValueDisplay,
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
            foreach (DependentSourceKind kind in Enum.GetValues<DependentSourceKind>())
            {
                string prefix = DependentSource.PrefixOf(kind);
                _dependentCounters[(int)kind] = _elements.OfType<DependentSource>()
                    .Where(e => e.Kind == kind && e.Id.StartsWith(prefix, StringComparison.Ordinal))
                    .Select(e => int.TryParse(e.Id[prefix.Length..], out int n) ? n : 0)
                    .DefaultIfEmpty(0).Max();
            }
            _groundCounter = Max("GND");
            _probeCounter = Math.Max(Max("VP"), Max("IP"));
            _junctionCounter = Max("J");
            _switchCounter = Max("S");
        }

        // ═══════════════════════════════════════════════════════
        //  NETLİST OLUŞTURMA (Union-Find ile Düğüm Tespiti)
        // ═══════════════════════════════════════════════════════

        private void BtnGenerateNetlist_Click(object sender, RoutedEventArgs e)
        {
            if (_elements.Count == 0)
            {
                MessageBox.Show("Canvas'ta hiç eleman yok!\nÖnce araç kutusundan eleman ekleyin.",
                    "Netlist Hatası", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            // ═══ GND kontrolü ═══
            bool hasGround = _elements.Any(el => el is GroundElement);
            if (!hasGround)
            {
                var result = MessageBox.Show(
                    "Devrede Toprak (GND) referans noktası yok!\n\n" +
                    "SPICE analizi için Node 0 (referans) gereklidir.\n" +
                    "GND olmadan devam etmek istiyor musunuz?\n\n" +
                    "(Düğüm numaraları 1'den başlayacak, Node 0 olmayacak)",
                    "GND Eksik", MessageBoxButton.YesNo, MessageBoxImage.Warning);
                if (result == MessageBoxResult.No)
                    return;
            }

            var netlist = NetlistBuilder.Build(_elements, _wires);
            int totalNodes = netlist.NodeCount;

            MessageBox.Show(netlist.Text, "SPICE Netlist", MessageBoxButton.OK, MessageBoxImage.Information);

            TxtStatus.Text = $"Netlist oluşturuldu — {_elements.Count} eleman, {_wires.Count} tel, " +
                $"{totalNodes} düğüm" + (hasGround ? " (GND=0)" : " (GND yok!)");
        }
    }
}
