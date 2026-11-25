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
            // Çözüm gösterilince, silinince ya da devre değişince ışık ve cam kart güncellenir
            _overlay.Changed += (_, _) => UpdateCurrentFlowAndCard();
            CanvasScrollViewer.ScrollChanged += (_, _) => PositionElementCard();
            CanvasLayer.SizeChanged += (_, _) => PositionElementCard();
            // Pencere içi diyalog, Hakkında, Tanıtım ya da büyük grafik açıkken akım ışığı duraklar
            foreach (var layer in new FrameworkElement[] { DialogOverlay, AboutOverlay, OnboardingOverlay, PlotOverlay })
                layer.IsVisibleChanged += (_, _) => { if (_overlay != null) _overlay.Flow.Paused = IsModalOverlayOpen; };
            AnalysisPanel.SolveRequested += async (_, _) => await SolveAsync();
            AnalysisPanel.ValueDisplayChanged += async (_, _) =>
            {
                // Bu devre az önce süre sınırı içinde çözüldü: büyük devre sorusu yeniden sorulmaz
                if (_hasResults) await SolveAsync(confirmLarge: false);
            };
            AnalysisPanel.EnlargePlotRequested += (_, data) => PlotOverlay.Show(data);
            AnalysisPanel.EnlargeResonanceRequested += (_, data) => PlotOverlay.Show(data);
            AnalysisPanel.EnlargeZenerRangeRequested += (_, data) => PlotOverlay.Show(data);
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
            AnalysisPanel.LlmEnableGpu = async ct =>
            {
                if (_api == null) return (false, GpuEnableResult.DefaultFailure);
                var r = await _api.EnableGpuAsync(ct);
                // Ayar yapıldı: program kapanırken (ya da çözücü yeniden başlarken) Ollama eski hâline döner
                if (r.Ok) _backend.NoteGpuSwitched(r.RestoreCommand);
                return (r.Ok, r.Message);
            };
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

        /// <summary>Panelde çözücü hata kartı (Yeniden dene düğmeli) mi gösteriliyor?</summary>
        private bool _backendErrorShown;

        private async Task StartBackendAsync()
        {
            bool isRetry = _backendErrorShown;
            _api = null;
            AnalysisPanel.SetBackendStatus(BackendState.Starting, "Çözücü başlatılıyor…");
            try
            {
                var progress = new Progress<string>(msg => TxtStatus.Text = msg);
                _api = await _backend.StartAsync(progress);
                var health = await _api.TryGetHealthAsync();
                AnalysisPanel.SetBackendStatus(BackendState.Ready,
                    $"Çözücü hazır — {_api.BaseAddress} (sürüm {health?.Version})");
                if (_backendErrorShown)
                {
                    // Eski hata kartı kalmasın: çözücü yeniden hazır
                    AnalysisPanel.ClearResults();
                    _backendErrorShown = false;
                }
                TxtStatus.Text = isRetry
                    ? "Çözücü yeniden başlatıldı — ▶ Çöz'e basabilirsiniz (F5)"
                    : "Çözücü hazır — devreyi çizip ▶ Çöz'e basın (F5)";
            }
            catch (BackendUnavailableException ex)
            {
                ShowBackendFailure(ex, ex.Failure ?? BackendFailure.NotReady);
                TxtStatus.Text = "Çözücü başlatılamadı — ayrıntılar sağ panelde";
            }
        }

        /// <summary>
        /// Çözücüyü yeniden başlatır ("Yeniden dene"). Başlatma zaten sürüyorsa yenisini açmaz;
        /// BackendManager eski süreci kapatmadan yenisini başlatmaz (iki çözücü birden çalışmaz).
        /// </summary>
        private Task RestartBackendAsync()
        {
            if (_backendStartTask is { IsCompleted: false })
                return _backendStartTask;
            return _backendStartTask = StartBackendAsync();
        }

        /// <summary>Çözücü hatasını türüne göre Türkçe metinle ve "Yeniden dene" düğmesiyle gösterir.</summary>
        private void ShowBackendFailure(BackendUnavailableException ex, BackendFailure failure)
        {
            var (title, text) = BackendMessages.Describe(failure, BackendManager.IsDeveloperRun,
                detail: ex.Detail, requestMessage: failure == BackendFailure.Timeout ? ex.Message : null);
            AnalysisPanel.SetBackendStatus(BackendState.Failed, title);
            AnalysisPanel.ShowError(title, text, BackendMessages.RetryText, () => _ = RestartBackendAsync());
            _backendErrorShown = true;
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
                string snapshot = CircuitDocument.Snapshot(_elements, _wires);
                _undoHistory.Record(snapshot);   // aynı içerik yeni adım açmaz
                _isDirty = snapshot != _savedSnapshot;
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
            AnalysisPanel.SetAvailableReciprocityTargets(_elements);
            AnalysisPanel.SetAvailableZenerRangeTargets(_elements);
            _overlay?.ShowNodeNumbers(netlist, _wires);
        }

        // ═══════════════════════════════════════════════════════
        //  ÇÖZME
        // ═══════════════════════════════════════════════════════

        /// <param name="confirmLarge">Büyük AC devrede çözmeden önce sorulsun mu (Etkin/Tepe ile yeniden çözmede hayır).</param>
        private async Task SolveAsync(bool confirmLarge = true)
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
            // Çözücü daha önce hazırdı ama sonradan kapandıysa isteği hiç göndermeden söyle
            if (!_backend.IsAlive)
            {
                ShowBackendFailure(new BackendUnavailableException(BackendFailure.Stopped, "Çözücü kapandı."),
                    BackendFailure.Stopped);
                TxtStatus.Text = "Çözücü kapandı — sağ paneldeki “Yeniden dene” ile başlatın";
                return;
            }
            int elementCount = _elements.Count(e => e is not GroundElement and not TestProbe and not JunctionElement);
            if (elementCount == 0)
            {
                AnalysisPanel.ShowError("Devre boş", "Önce soldaki şeritten eleman ekleyip tellerle bağlayın.");
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
                TheveninTerminals = (options.AnalysisType == AnalysisTypes.Nodal || options.AnalysisType == AnalysisTypes.Power || !AnalysisPanel.UsesTerminals(options.AnalysisType))
                    ? null
                    : new TerminalsDto
                    {
                        NodePositive = options.TerminalPositive ?? "",
                        NodeNegative = options.TerminalNegative,
                    },
                ValueDisplay = AnalysisPanel.ValueDisplay,
                PowerFactorTarget = (options.AnalysisType == AnalysisTypes.Power || options.AnalysisType == AnalysisTypes.ThreePhase) ? options.PowerFactorTarget : null,
                ReciprocityTarget = string.Equals(options.AnalysisType, AnalysisTypes.Reciprocity, StringComparison.OrdinalIgnoreCase)
                    ? options.ReciprocityTarget
                    : null,
                ZenerRangeTarget = string.Equals(options.AnalysisType, AnalysisTypes.ZenerRange, StringComparison.OrdinalIgnoreCase)
                    ? options.ZenerRangeTarget
                    : null,
                ZenerRangeGivenMin = string.Equals(options.AnalysisType, AnalysisTypes.ZenerRange, StringComparison.OrdinalIgnoreCase)
                    ? options.ZenerRangeGivenMin
                    : null,
                ZenerRangeGivenMax = string.Equals(options.AnalysisType, AnalysisTypes.ZenerRange, StringComparison.OrdinalIgnoreCase)
                    ? options.ZenerRangeGivenMax
                    : null,
            };

            // Büyük AC devre: 2 dakikalık sınıra takılabilir, önce sor (ekran testlerinde sorulmaz)
            bool isLarge = LargeCircuitCheck.ShouldWarn(elementCount, request.Mode);
            if (isLarge && confirmLarge && !HasAnySelfTest(Environment.GetCommandLineArgs()))
            {
                string? choice = DialogOverlay.ShowModal(
                    LargeCircuitCheck.WarningTitle,
                    LargeCircuitCheck.WarningText(elementCount),
                    DialogKind.Warning,
                    new[] { new DialogButton("cancel", "Vazgeç"), new DialogButton("solve", "Çöz", IsPrimary: true) },
                    cancelId: "cancel");
                if (choice != "solve")
                {
                    TxtStatus.Text = "Çözüm başlatılmadı";
                    return;
                }
                if (_api == null)
                    return;   // soru açıkken çözücü yeniden başlatılıyor olabilir
            }

            int versionAtStart = _circuitVersion;
            AnalysisPanel.SetBusy(true);
            TxtStatus.Text = "Çözülüyor…";
            _backendErrorShown = false;
            var api = _api;
            var stoppedToken = _backend.StoppedToken;
            // Uzun çözümde durum satırı her saniye "hâlâ çalışıyor" desin
            DispatcherTimer? busyTimer = null;
            if (isLarge)
            {
                var started = System.Diagnostics.Stopwatch.StartNew();
                TxtStatus.Text = LargeCircuitCheck.BusyText(TimeSpan.Zero);
                busyTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
                busyTimer.Tick += (_, _) => TxtStatus.Text = LargeCircuitCheck.BusyText(started.Elapsed);
                busyTimer.Start();
            }
            try
            {
                var response = await api.AnalyzeAsync(request, stoppedToken);
                busyTimer?.Stop();
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
                    // Adım sayısı sağ paneldeki anlatımla aynı olsun (yoksa eski çözüm adımları)
                    int stepCount = response.Results?.Explanation?.Count is > 0 and int n ? n : response.SolutionSteps.Count;
                    TxtStatus.Text = response.Status == "success"
                        ? stepCount > 0
                            ? $"Çözüldü — {netlist.NodeCount} düğüm, {stepCount} adım"
                            : $"Çözüldü — {netlist.NodeCount} düğüm"
                        : "Uyarılarla çözüldü — ayrıntılar sağ panelde";
                    // Geçici durumda devre üzerindeki değerler anahtardan çok sonraki kararlı hâldir;
                    // söylenmezse öğrenci her yerde "0 A" görüp şaşırıyor
                    if (response.Transient != null)
                        TxtStatus.Text += " · devre üzerindeki değerler: t → ∞ (yeni kararlı hâl); zamanla değişim grafikte";
                }
            }
            catch (AnalysisRequestException ex)
            {
                AnalysisPanel.ShowError("Devre çözülemedi", ex.Message);
                TxtStatus.Text = "Devre çözülemedi";
            }
            catch (OperationCanceledException) when (stoppedToken.IsCancellationRequested)
            {
                // Çözücü süreci istek sürerken kapandı: zaman aşımını beklemeden söyle
                ShowBackendFailure(new BackendUnavailableException(BackendFailure.Stopped, "Çözücü kapandı."),
                    BackendFailure.Stopped);
                TxtStatus.Text = "Çözücü kapandı — sağ paneldeki “Yeniden dene” ile başlatın";
            }
            catch (BackendUnavailableException ex)
            {
                // Süreç ölmüşse "kapandı"; yaşıyorsa zaman aşımı ya da bağlantı sorunu
                var failure = !_backend.IsAlive ? BackendFailure.Stopped : ex.Failure ?? BackendFailure.Unreachable;
                ShowBackendFailure(ex, failure);
                TxtStatus.Text = failure == BackendFailure.Timeout
                    ? "Çözüm zamanında bitmedi — ayrıntılar sağ panelde"
                    : "Çözücüye ulaşılamadı — ayrıntılar sağ panelde";
            }
            finally
            {
                busyTimer?.Stop();
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
            // Örnek ya da soru yeni bir belgedir: Ctrl+S öğrencinin önceki dosyasının üstüne yazmasın.
            // (OpenFile dosya yolunu bundan sonra kendisi atar.)
            _currentFilePath = null;
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

            ResetHistoryAsSaved();
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
            _transformerCounter = Max("T");
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
            _threePhaseSourceCounter = Max("U");
            _threePhaseLoadCounter = Max("Y");
            _wattmeterCounter = Max("W");
            _diodeCounter = Max("D");
        }

        // ═══════════════════════════════════════════════════════
        //  NETLİST OLUŞTURMA (Union-Find ile Düğüm Tespiti)
        // ═══════════════════════════════════════════════════════

        private void BtnGenerateNetlist_Click(object sender, RoutedEventArgs e)
        {
            if (_elements.Count == 0)
            {
                Inform("Netlist oluşturulamadı", "Çizim alanında hiç eleman yok. Önce soldaki şeritten eleman ekleyin.", DialogKind.Warning);
                return;
            }

            // ═══ GND kontrolü ═══
            bool hasGround = _elements.Any(el => el is GroundElement);
            if (!hasGround)
            {
                string? choice = DialogOverlay.ShowModal(
                    "Toprak (GND) yok",
                    "SPICE analizi için 0 numaralı referans düğümü gerekir. GND olmadan devam ederseniz " +
                    "düğüm numaraları 1'den başlar ve 0 numaralı düğüm olmaz.",
                    DialogKind.Warning,
                    new[] { new DialogButton("cancel", "Vazgeç", IsPrimary: true), new DialogButton("continue", "Yine de devam et") },
                    cancelId: "cancel");
                if (choice != "continue")
                    return;
            }

            var netlist = NetlistBuilder.Build(_elements, _wires);
            int totalNodes = netlist.NodeCount;

            // Netlist seçilip kopyalanabilsin diye salt okunur, eş aralıklı bir metin kutusunda
            var netlistBox = new TextBox
            {
                Text = netlist.Text,
                IsReadOnly = true,
                TextWrapping = TextWrapping.NoWrap,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Auto,
                MaxHeight = 360,
            };
            netlistBox.SetResourceReference(FontFamilyProperty, "Font.Mono");
            DialogOverlay.Show("SPICE netlist", netlistBox, width: 560);

            TxtStatus.Text = $"Netlist oluşturuldu — {_elements.Count} eleman, {_wires.Count} tel, " +
                $"{totalNodes} düğüm" + (hasGround ? " (GND=0)" : " (GND yok!)");
        }
    }
}
