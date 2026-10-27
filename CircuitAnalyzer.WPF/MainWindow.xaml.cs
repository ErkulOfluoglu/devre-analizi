using System.Linq;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using CircuitAnalyzer.WPF.Helpers;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;

namespace CircuitAnalyzer.WPF
{
    /// <summary>
    /// Ana pencere — Devre çizim arayüzü.
    /// 
    /// Etkileşim modları:
    /// 
    /// 1. NORMAL MOD (varsayılan):
    ///    - Sol tık + sürükle: Elemanı taşı
    ///    - Çift tık: Değer düzenleme diyaloğunu aç
    ///    - Sağ tık: Bağlam menüsü (Döndür / Düzenle / Sil)
    ///    - R tuşu: Seçili elemanı 90° döndür
    ///    
    /// 2. TEL ÇİZİM MODU (BtnDrawWire):
    ///    - Sol tık pine: Tel başlat / tamamla
    ///    - Escape: İptal
    /// </summary>
    public partial class MainWindow : Window
    {
        // ── Devre verileri ──
        private readonly List<CircuitElement> _elements = new();
        private readonly List<Wire> _wires = new();

        // ── UIElement ↔ CircuitElement eşleştirmesi ──
        private readonly Dictionary<UIElement, CircuitElement> _visualToElement = new();
        private readonly Dictionary<CircuitElement, UIElement> _elementToVisual = new();

        /// <summary>Seçim modeli (birim ve ekran testleri için erişilebilir).</summary>
        public SelectionModel Selection => _selection;

        /// <summary>Pano servisi (testlerde bellek içi pano ile değiştirilebilir).</summary>
        public IClipboardService ClipboardService { get; set; } = new SystemClipboardService();

        /// <summary>Tuvaldeki devre elemanları.</summary>
        public IReadOnlyList<CircuitElement> Elements => _elements;

        /// <summary>Tuvaldeki bağlantı telleri.</summary>
        public IReadOnlyList<Wire> Wires => _wires;

        /// <summary>Geri al / yinele geçmişi.</summary>
        public UndoHistory UndoHistory => _undoHistory;

        /// <summary>Belgede kaydedilmemiş değişiklik var mı?</summary>
        public bool IsDirty => _isDirty;

        public MainWindow()
        {
            if (Application.Current == null)
            {
                Resources.MergedDictionaries.Add(new ResourceDictionary
                {
                    Source = new Uri("pack://application:,,,/CircuitAnalyzer;component/Themes/Light.xaml")
                });
            }
            InitializeComponent();
            ThemeManager.ApplyTitleBar(this);
            EventHandler onThemeChanged = (_, _) =>
            {
                if (!Dispatcher.HasShutdownStarted && !Dispatcher.HasShutdownFinished)
                {
                    if (Dispatcher.CheckAccess())
                        UpdateThemeButton();
                    else
                        Dispatcher.BeginInvoke(UpdateThemeButton);
                }
            };
            ThemeManager.ThemeChanged += onThemeChanged;
            Closed += (_, _) => ThemeManager.ThemeChanged -= onThemeChanged;
            _undoHistory.Changed += (_, _) => Dispatcher.Invoke(UpdateUndoRedoButtons);
            _selection.Changed += (_, _) => UpdateSelectionHighlight();
            InitializeAnalysisPanelLayout();
            InitializePlacementInput(); // bağlam menüsünden önce: yerleştirirken sağ tık menü açmak yerine vazgeçer
            InitializeCanvasContextMenu();
            _undoHistory.Reset(CircuitDocument.Snapshot(_elements, _wires));
            Loaded += MainWindow_Loaded;
            UpdateThemeButton();
        }

        private void MainWindow_Loaded(object sender, RoutedEventArgs e)
        {
            InitializeAnalysis();
            UpdateEmptyCanvasHelper();
            UpdateTitle();
            UpdateUndoRedoButtons();
            UpdateZoomDisplay();
            _undoHistory.Reset(CircuitDocument.Snapshot(_elements, _wires));

            var args = Environment.GetCommandLineArgs();
            if (!HasAnySelfTest(args))
            {
                string? fileToOpen = args.Skip(1).FirstOrDefault(a =>
                    !a.StartsWith("--", StringComparison.Ordinal) &&
                    (a.EndsWith(".devre", StringComparison.OrdinalIgnoreCase) || System.IO.File.Exists(a)));

                if (!string.IsNullOrEmpty(fileToOpen))
                {
                    OpenFile(System.IO.Path.GetFullPath(fileToOpen));
                }
                else if (!AppSettings.OnboardingCompleted)
                {
                    Dispatcher.BeginInvoke(System.Windows.Threading.DispatcherPriority.Loaded, () =>
                    {
                        if (!AppSettings.OnboardingCompleted)
                        {
                            ShowOnboarding(0);
                        }
                    });
                }
            }
        }

        private void UpdateThemeButton()
        {
            ThemeIcon.SetResourceReference(Controls.Icon.DataProperty, ThemeManager.IsDark ? "Icon.Moon" : "Icon.Sun");
        }

        private void BtnTheme_Click(object sender, RoutedEventArgs e)
        {
            var menu = new ContextMenu();

            void AddItem(string title, ThemeChoice choice)
            {
                var item = new MenuItem();
                var dock = new DockPanel { LastChildFill = true };
                if (ThemeManager.Choice == choice)
                {
                    var checkIcon = new Controls.Icon
                    {
                        Width = 16,
                        Height = 16,
                        Margin = new Thickness(12, 0, 0, 0)
                    };
                    checkIcon.SetResourceReference(Controls.Icon.DataProperty, "Icon.Check");
                    DockPanel.SetDock(checkIcon, Dock.Right);
                    dock.Children.Add(checkIcon);
                }
                var text = new TextBlock
                {
                    Text = title,
                    VerticalAlignment = VerticalAlignment.Center
                };
                dock.Children.Add(text);
                item.Header = dock;
                item.Click += (_, _) => ThemeManager.SetChoice(choice);
                menu.Items.Add(item);
            }

            AddItem("Açık", ThemeChoice.Light);
            AddItem("Koyu", ThemeChoice.Dark);
            AddItem("Sistem (Windows'a uy)", ThemeChoice.System);

            menu.PlacementTarget = BtnTheme;
            menu.Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom;
            menu.IsOpen = true;
        }

        public void ShowOnboarding(int page = 0)
        {
            OnboardingOverlay.View.SetupView.StatusProvider = AnalysisPanel.LlmStatusProvider;
            OnboardingOverlay.View.SetupView.StartOllama = AnalysisPanel.LlmStartOllama;
            OnboardingOverlay.View.SetupView.StartPull = AnalysisPanel.LlmStartPull;
            OnboardingOverlay.View.SetupView.GetPull = AnalysisPanel.LlmGetPull;
            OnboardingOverlay.View.SetupView.CancelPull = AnalysisPanel.LlmCancelPull;

            Action<OnboardingResult>? onClosed = null;
            onClosed = result =>
            {
                OnboardingOverlay.Closed -= onClosed;
                AppSettings.OnboardingCompleted = true;

                if (result == OnboardingResult.StartExample)
                {
                    LoadExample(ExampleCircuits.All[0]());
                    _ = SolveAsync();
                }
                else if (result == OnboardingResult.StartTour)
                {
                    TourOverlay.Start();
                }
            };

            OnboardingOverlay.Closed += onClosed;
            OnboardingOverlay.Show(page);
        }

        public void ShowAbout()
        {
            AboutOverlay.Show();
        }

        /// <summary>Tanıtım, Hakkında veya genel diyalog kartı açık mı?</summary>
        public bool IsModalOverlayOpen =>
            OnboardingOverlay.Visibility == Visibility.Visible ||
            AboutOverlay.Visibility == Visibility.Visible ||
            DialogOverlay.IsOpen;

        private void BtnHelp_Click(object sender, RoutedEventArgs e)
        {
            var menu = new ContextMenu();

            var itemTour = new MenuItem { Header = "Tanıtımı göster" };
            itemTour.Click += (_, _) => ShowOnboarding(0);
            menu.Items.Add(itemTour);

            var itemAppTour = new MenuItem { Header = "Uygulamayı gezdir" };
            itemAppTour.Click += (_, _) => TourOverlay.Start();
            menu.Items.Add(itemAppTour);

            var itemShortcuts = new MenuItem { Header = "Kısayollar" };
            itemShortcuts.Click += (_, _) => ShowShortcutsDialog();
            menu.Items.Add(itemShortcuts);

            var itemAbout = new MenuItem { Header = "Hakkında" };
            itemAbout.Click += (_, _) => ShowAbout();
            menu.Items.Add(itemAbout);

            menu.PlacementTarget = BtnHelp;
            menu.Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom;
            menu.IsOpen = true;
        }

        private void ShowShortcutsDialog()
        {
            DialogOverlay.Show("Klavye ve fare kısayolları", BuildShortcutsView());
        }

        /// <summary>
        /// Klavye kısayolları:
        ///   F5 → Çöz
        ///   Ctrl+O → Aç, Ctrl+S → Kaydet, Ctrl+Shift+S → Farklı Kaydet, Ctrl+N → Yeni
        ///   Ctrl+Z → Geri Al, Ctrl+Y / Ctrl+Shift+Z → Yinele
        ///   Ctrl+C → Kopyala, Ctrl+X → Kes, Ctrl+V → Yapıştır, Ctrl+D → Çoğalt, Ctrl+A → Tümünü Seç
        ///   Ctrl+0 → %100, Ctrl++ / Ctrl+- → Yakınlaştır / Uzaklaştır
        ///   Delete → Seçili elemanları sil
        ///   Escape → Tel çizimini iptal et / seçimi temizle
        ///   R → Seçili elemanları 90° döndür
        /// </summary>
        private void Window_PreviewKeyDown(object sender, KeyEventArgs e)
        {
            // Pencere içi bir kart (Tanıtım, Hakkında, Kısayollar) açıkken arkadaki
            // devre kısayollara tepki vermesin; tuşları kartın kendisi işler.
            if (IsModalOverlayOpen)
                return;

            // ── F5: Çöz ──
            if (e.Key == Key.F5)
            {
                AnalysisPanel.RequestSolve();
                e.Handled = true;
                return;
            }

            // Metin kutusuna yazılıyorsa kısayolları devre dışı bırak
            // (TextBox'ın kendi geri al/yinele ve yazı yazma işlevlerini korur)
            if (e.OriginalSource is TextBox || Keyboard.FocusedElement is TextBox)
                return;

            var mods = Keyboard.Modifiers;

            // ── Yerleştirme modu: Esc vazgeç, R önizlemeyi döndür ──
            if (IsPlacing && mods == ModifierKeys.None && (e.Key == Key.Escape || e.Key == Key.R))
            {
                if (e.Key == Key.Escape)
                    CancelPlacement(announce: true);
                else
                    RotatePlacement();
                e.Handled = true;
                return;
            }

            // ── Ctrl+O: Aç ──
            if (e.Key == Key.O && mods == ModifierKeys.Control)
            {
                PromptAndOpenFileDialog();
                e.Handled = true;
                return;
            }

            // ── Ctrl+Shift+S: Farklı Kaydet ──
            if (e.Key == Key.S && mods == (ModifierKeys.Control | ModifierKeys.Shift))
            {
                SaveAsCircuit();
                e.Handled = true;
                return;
            }

            // ── Ctrl+S: Kaydet ──
            if (e.Key == Key.S && mods == ModifierKeys.Control)
            {
                SaveCircuit();
                e.Handled = true;
                return;
            }

            // ── Ctrl+P: Yazdır / PDF ──
            if (e.Key == Key.P && mods == ModifierKeys.Control)
            {
                PrintOrExportPdf();
                e.Handled = true;
                return;
            }

            // ── Ctrl+N: Yeni ──
            if (e.Key == Key.N && mods == ModifierKeys.Control)
            {
                NewCircuit();
                e.Handled = true;
                return;
            }

            // ── Ctrl+Z: Geri Al ──
            if (e.Key == Key.Z && mods == ModifierKeys.Control)
            {
                Undo();
                e.Handled = true;
                return;
            }

            // ── Ctrl+Y veya Ctrl+Shift+Z: Yinele ──
            if ((e.Key == Key.Y && mods == ModifierKeys.Control) ||
                (e.Key == Key.Z && mods == (ModifierKeys.Control | ModifierKeys.Shift)))
            {
                Redo();
                e.Handled = true;
                return;
            }

            // ── Ctrl+C: Kopyala ──
            if (e.Key == Key.C && mods == ModifierKeys.Control && !_isWireMode && !_isPinWiring)
            {
                CopySelected();
                e.Handled = true;
                return;
            }

            // ── Ctrl+X: Kes ──
            if (e.Key == Key.X && mods == ModifierKeys.Control && !_isWireMode && !_isPinWiring)
            {
                CutSelected();
                e.Handled = true;
                return;
            }

            // ── Ctrl+V: Yapıştır ──
            if (e.Key == Key.V && mods == ModifierKeys.Control && !_isWireMode && !_isPinWiring)
            {
                PasteFromClipboard();
                e.Handled = true;
                return;
            }

            // ── Ctrl+D: Çoğalt ──
            if (e.Key == Key.D && mods == ModifierKeys.Control && !_isWireMode && !_isPinWiring)
            {
                DuplicateSelected();
                e.Handled = true;
                return;
            }

            // ── Ctrl+A: Tümünü Seç ──
            if (e.Key == Key.A && mods == ModifierKeys.Control && !_isWireMode && !_isPinWiring)
            {
                SelectAllElements();
                e.Handled = true;
                return;
            }

            // ── Ctrl+0: %100 Yakınlaştırma ──
            if ((e.Key == Key.D0 || e.Key == Key.NumPad0) && mods == ModifierKeys.Control)
            {
                ResetZoom();
                e.Handled = true;
                return;
            }

            // ── Ctrl++: Yakınlaştır ──
            if ((e.Key == Key.OemPlus || e.Key == Key.Add) && mods == ModifierKeys.Control)
            {
                ZoomIn();
                e.Handled = true;
                return;
            }

            // ── Ctrl+-: Uzaklaştır ──
            if ((e.Key == Key.OemMinus || e.Key == Key.Subtract) && mods == ModifierKeys.Control)
            {
                ZoomOut();
                e.Handled = true;
                return;
            }

            // ── Space tuşu: Pan imleci ──
            if (e.Key == Key.Space && !e.IsRepeat && !_isPanning)
            {
                Mouse.OverrideCursor = Cursors.Hand;
            }

            // ── Escape: Tel çizimini iptal et veya seçimi temizle ──
            if (e.Key == Key.Escape)
            {
                if (_isWirePressPending)
                {
                    _isWirePressPending = false;
                    _pressedWire = null;
                    CircuitCanvas.ReleaseMouseCapture();
                }
                if (_isPinWiring)
                {
                    CancelPinWire();
                    e.Handled = true;
                    return;
                }
                if (_isWireMode)
                {
                    if (_wireStartPin != null)
                    {
                        RevertPendingStartSplit();
                        ResetCurrentWireState();
                        _wireStartPin = null;
                        RemovePreviewVisuals();
                        TxtStatus.Text = "TEL MODU — Çizim iptal edildi. Yeni bir pine tıklayın (Esc: çık)";
                    }
                    else
                    {
                        ExitWireMode();
                    }
                    e.Handled = true;
                    return;
                }
                if (_selection.HasSelection)
                {
                    DeselectElement();
                    TxtStatus.Text = "Seçim temizlendi";
                    e.Handled = true;
                    return;
                }
            }

            // ── Backspace: Tel çizimi sırasında son köşeyi geri al ──
            if (e.Key == Key.Back && mods == ModifierKeys.None)
            {
                if (IsDrawingWire)
                {
                    RemoveLastWireWaypoint();
                    e.Handled = true;
                }
                return;
            }

            // ── Delete: Seçili elemanları ve telleri sil ──
            if (e.Key == Key.Delete && !_isWireMode && _selection.HasSelection)
            {
                if (_isPinWiring)
                {
                    if (_pendingStartSplit != null)
                        return;
                    CancelPinWire();
                }
                DeleteSelected();
                e.Handled = true;
                return;
            }

            // ── R: Tel çizerken canlı kolun yönünü çevir; normal modda seçili elemanları döndür ──
            if (e.Key == Key.R && mods == ModifierKeys.None)
            {
                if (IsDrawingWire)
                {
                    FlipLiveWireLegOrientation();
                    e.Handled = true;
                    return;
                }
                if (!_isWireMode && !_isPinWiring && _selection.Count > 0)
                {
                    RotateSelected();
                    e.Handled = true;
                }
            }
        }

        protected override void OnPreviewKeyUp(KeyEventArgs e)
        {
            base.OnPreviewKeyUp(e);
            if (e.Key == Key.Space && !_isPanning)
            {
                Mouse.OverrideCursor = null;
            }
        }
    }
}
