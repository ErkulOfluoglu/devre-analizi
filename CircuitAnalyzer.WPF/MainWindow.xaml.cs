using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
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
        private int _resistorCounter = 0;
        private int _voltageSourceCounter = 0;
        private int _acSourceCounter = 0;
        private int _currentSourceCounter = 0;
        private int _acCurrentSourceCounter = 0;
        private int _capacitorCounter = 0;
        private int _inductorCounter = 0;
        private int _impedanceCounter = 0;
        private int _groundCounter = 0;
        private int _probeCounter = 0;
        private int _junctionCounter = 0;

        // ── Sürükleme (Drag) durumu ──
        private bool _isDragging = false;
        private CircuitElement? _draggedElement = null;
        private UIElement? _draggedVisual = null;
        private Point _dragOffset;
        private Point _dragStartPosition;
        private Dictionary<CircuitElement, Point> _dragInitialPositions = new();

        // ── Seçim durumu (tekli ve çoklu seçim modeli) ──
        private readonly SelectionModel _selection = new();
        private CircuitElement? _selectedElement = null;
        private UIElement? _selectedVisual = null;
        private readonly List<Rectangle> _selectionHighlights = new();

        // ── Çerçeve (Rubber-band) seçim durumu ──
        private const double RubberBandThreshold = 4.0;
        private bool _isRubberBandPending = false;
        private bool _isRubberBandActive = false;
        private Point _rubberBandStart;
        private ModifierKeys _rubberBandModifiers = ModifierKeys.None;
        private Rectangle? _rubberBandRect = null;

        // ── Tel basış / sürükleme / üzerine gelme (hover) durumu ──
        private bool _isWirePressPending = false;
        private Wire? _pressedWire = null;
        private Point _wirePressPos;
        private Point _wirePressSnapped;
        private ModifierKeys _wirePressModifiers = ModifierKeys.None;
        private Wire? _hoveredWire = null;

        // ── Tel çizim durumu (Tel modu + normal modda uca tıklayarak tel çizme) ──
        private bool _isWireMode = false;
        private bool _isPinWiring = false;
        private Pin? _wireStartPin = null;
        private Polyline? _wirePreview = null;
        private Ellipse? _pinHighlight = null;
        private Ellipse? _junctionPreview = null;

        private sealed record PendingWireSplit(Wire OriginalWire, JunctionElement Junction, Wire FirstPart, Wire SecondPart);
        private PendingWireSplit? _pendingStartSplit = null;

        // ── UIElement ↔ CircuitElement eşleştirmesi ──
        private readonly Dictionary<UIElement, CircuitElement> _visualToElement = new();
        private readonly Dictionary<CircuitElement, UIElement> _elementToVisual = new();

        // ── Pano ve sağ-tık bağlam menüsü durumu ──
        private int _pasteCascadeCount = 0;
        private Point? _contextMenuCanvasPos = null;
        private ContextMenu? _canvasContextMenu = null;
        private MenuItem? _canvasPasteMenuItem = null;
        private MenuItem? _canvasSelectAllMenuItem = null;

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

        // ── Pin algılama eşiği (piksel) ──
        private const double PinSnapThreshold = 12.0;
        /// <summary>Normal modda uç algılama yarıçapının tuval birimi cinsinden üst sınırı.</summary>
        private const double NormalModePinRadiusCap = 14.0;
        // ── Tel yakalama eşiği (ekran pikseli ve tuval birimi üst sınırı) ──
        private const double WireSnapThreshold = 6.0;
        private const double WireToleranceCap = 8.0;

        // ── Dosya ve Geri Al / Yinele durumu ──
        private string? _currentFilePath;
        private bool _isDirty;
        private readonly UndoHistory _undoHistory = new();
        private bool _isRestoringHistory;
        private int? _problemCode;

        // ── Yakınlaştırma ve Kaydırma durumu ──
        private double _currentZoom = 1.0;
        private bool _isPanning;
        private Point _panStartMouse;
        private double _panStartH;
        private double _panStartV;

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

        /// <summary>Kısayollar listesi (pencere içi kartta gösterilir).</summary>
        internal static readonly (string Group, (string Key, string Desc)[] Items)[] ShortcutGroups =
        {
            ("Çözüm", new[]
            {
                ("F5", "Çöz"),
            }),
            ("Dosya", new[]
            {
                ("Ctrl+N", "Yeni devre"),
                ("Ctrl+O", "Aç"),
                ("Ctrl+S", "Kaydet"),
                ("Ctrl+Shift+S", "Farklı kaydet"),
                ("Ctrl+P", "Yazdır / PDF"),
            }),
            ("Düzen", new[]
            {
                ("Ctrl+Z", "Geri al"),
                ("Ctrl+Y", "Yinele"),
                ("Ctrl+C", "Kopyala"),
                ("Ctrl+X", "Kes"),
                ("Ctrl+V", "Yapıştır"),
                ("Ctrl+D", "Çoğalt"),
                ("Ctrl+A", "Tümünü seç"),
                ("R", "Seçili elemanı döndür"),
                ("Delete", "Seçili elemanı sil"),
                ("Uca tıkla", "Tel çiz"),
                ("Tele tıkla", "Teli seç (Delete: sil)"),
                ("Telden sürükle", "Telin ortasından yeni tel (T)"),
                ("Ctrl+tık", "Seçime ekle/çıkar"),
                ("Boş alanda sürükle", "Toplu seçim"),
                ("Çift tık", "Değeri düzenle"),
                ("Sağ tık", "Döndür / düzenle / sil"),
                ("Esc", "Tel çizmeyi bırak"),
            }),
            ("Görünüm", new[]
            {
                ("Ctrl+tekerlek", "Yakınlaştır / uzaklaştır"),
                ("Ctrl+ +  /  Ctrl+ −", "Yakınlaştır / uzaklaştır"),
                ("Ctrl+0", "%100 boyut"),
                ("Boşluk+sürükle", "Çizim alanını kaydır (orta tuşla da olur)"),
            }),
        };

        private void ShowShortcutsDialog()
        {
            DialogOverlay.Show("Klavye ve fare kısayolları", BuildShortcutsView());
        }

        internal static FrameworkElement BuildShortcutsView()
        {
            var sp = new StackPanel();
            bool first = true;

            foreach (var (group, items) in ShortcutGroups)
            {
                var header = new TextBlock
                {
                    Text = group,
                    Margin = new Thickness(0, first ? 0 : 14, 0, 6),
                };
                header.SetResourceReference(StyleProperty, "Text.Caption");
                header.FontWeight = FontWeights.SemiBold;
                sp.Children.Add(header);
                first = false;

                var card = new Border { Padding = new Thickness(14, 8, 14, 8) };
                card.SetResourceReference(StyleProperty, "Card.Inset");
                var rows = new StackPanel();

                foreach (var (key, desc) in items)
                {
                    var row = new Grid { Margin = new Thickness(0, 3, 0, 3) };
                    row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(150) });
                    row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

                    var keyBorder = new Border
                    {
                        CornerRadius = new CornerRadius(6),
                        Padding = new Thickness(8, 3, 8, 3),
                        BorderThickness = new Thickness(1),
                        HorizontalAlignment = HorizontalAlignment.Left,
                    };
                    keyBorder.SetResourceReference(Border.BackgroundProperty, "Brush.Bg.Surface");
                    keyBorder.SetResourceReference(Border.BorderBrushProperty, "Brush.Border.Strong");
                    var keyText = new TextBlock
                    {
                        Text = key,
                        FontWeight = FontWeights.SemiBold,
                        FontSize = 12.5,
                    };
                    keyText.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
                    keyBorder.Child = keyText;
                    row.Children.Add(keyBorder);

                    var descText = new TextBlock
                    {
                        Text = desc,
                        VerticalAlignment = VerticalAlignment.Center,
                        TextWrapping = TextWrapping.Wrap,
                        FontSize = 13.5,
                    };
                    descText.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Body");
                    Grid.SetColumn(descText, 1);
                    row.Children.Add(descText);

                    rows.Children.Add(row);
                }

                card.Child = rows;
                sp.Children.Add(card);
            }

            return sp;
        }

        // ═══════════════════════════════════════════════════════
        //  ELEMAN EKLEME
        // ═══════════════════════════════════════════════════════

        private Point GetViewportCenterInCanvas()
        {
            double vw = CanvasScrollViewer != null && CanvasScrollViewer.ViewportWidth > 0
                ? CanvasScrollViewer.ViewportWidth
                : (CanvasScrollViewer != null && CanvasScrollViewer.ActualWidth > 0 ? CanvasScrollViewer.ActualWidth : 800);
            double vh = CanvasScrollViewer != null && CanvasScrollViewer.ViewportHeight > 0
                ? CanvasScrollViewer.ViewportHeight
                : (CanvasScrollViewer != null && CanvasScrollViewer.ActualHeight > 0 ? CanvasScrollViewer.ActualHeight : 600);
            double zoom = _currentZoom > 0 ? _currentZoom : 1.0;
            double hOff = CanvasScrollViewer?.HorizontalOffset ?? 0;
            double vOff = CanvasScrollViewer?.VerticalOffset ?? 0;

            double cx = (hOff + vw / 2.0) / zoom;
            double cy = (vOff + vh / 2.0) / zoom;
            return new Point(cx, cy);
        }

        private void BtnAddResistor_Click(object sender, RoutedEventArgs e)
        {
            ExitWireMode();
            _resistorCounter++;

            var resistor = new Resistor
            {
                Id = $"R{_resistorCounter}",
                Value = 1000
            };

            var center = GetViewportCenterInCanvas();
            double centerX = GridHelper.Snap(center.X - 40);
            double centerY = GridHelper.Snap(center.Y - 20);
            centerY += (_resistorCounter - 1) * GridHelper.GridSize * 3;

            resistor.Position = new Point(centerX, centerY);
            AddElementToCanvas(resistor);

            TxtStatus.Text = $"{resistor.Id} eklendi — Sürükle/Sağ-tık/Çift-tık";
        }

        private void BtnAddCapacitor_Click(object sender, RoutedEventArgs e)
        {
            ExitWireMode();
            _capacitorCounter++;

            var cap = new Capacitor
            {
                Id = $"C{_capacitorCounter}",
                Value = 10e-6
            };

            var center = GetViewportCenterInCanvas();
            double centerX = GridHelper.Snap(center.X + 80);
            double centerY = GridHelper.Snap(center.Y - 20);
            centerY += (_capacitorCounter - 1) * GridHelper.GridSize * 3;

            cap.Position = new Point(centerX, centerY);
            AddElementToCanvas(cap);

            TxtStatus.Text = $"{cap.Id} (10µF) eklendi — Sürükle/Sağ-tık/Çift-tık";
        }

        private void BtnAddInductor_Click(object sender, RoutedEventArgs e)
        {
            ExitWireMode();
            _inductorCounter++;

            var ind = new Inductor
            {
                Id = $"L{_inductorCounter}",
                Value = 100e-3
            };

            var center = GetViewportCenterInCanvas();
            double centerX = GridHelper.Snap(center.X + 200);
            double centerY = GridHelper.Snap(center.Y - 20);
            centerY += (_inductorCounter - 1) * GridHelper.GridSize * 3;

            ind.Position = new Point(centerX, centerY);
            AddElementToCanvas(ind);

            TxtStatus.Text = $"{ind.Id} (100mH) eklendi — Sürükle/Sağ-tık/Çift-tık";
        }

        private void BtnAddImpedance_Click(object sender, RoutedEventArgs e)
        {
            ExitWireMode();
            _impedanceCounter++;

            var z = new ImpedanceElement
            {
                Id = $"Z{_impedanceCounter}",
                Impedance = ComplexValue.FromRectangular(50, 30)
            };

            var center = GetViewportCenterInCanvas();
            double centerX = GridHelper.Snap(center.X - 60);
            double centerY = GridHelper.Snap(center.Y + 60);
            centerY += (_impedanceCounter - 1) * GridHelper.GridSize * 3;

            z.Position = new Point(centerX, centerY);
            AddElementToCanvas(z);

            TxtStatus.Text = $"{z.Id} ({z.Impedance.ToRectangularString()}Ω) eklendi — Sürükle/Sağ-tık/Çift-tık";
        }

        /// <summary>
        /// Toprak (GND) referans noktası ekler.
        /// SPICE standartında GND = Node 0'dır.
        /// Devrede en az bir GND olmadan Netlist geçerli değildir.
        /// </summary>
        private void BtnAddGround_Click(object sender, RoutedEventArgs e)
        {
            ExitWireMode();
            _groundCounter++;

            var gnd = new GroundElement
            {
                Id = $"GND{_groundCounter}"
            };

            var center = GetViewportCenterInCanvas();
            double centerX = GridHelper.Snap(center.X - 20);
            double centerY = GridHelper.Snap(center.Y + 40);
            centerY += (_groundCounter - 1) * GridHelper.GridSize * 3;

            gnd.Position = new Point(centerX, centerY);
            AddElementToCanvas(gnd);

            TxtStatus.Text = $"{gnd.Id} eklendi — Bağlı ağ otomatik Node 0 olur";
        }

        /// <summary>
        /// Ölçüm Probu ekler.
        /// Gerilim probu: bağlı düğümün gerilimini ölçer.
        /// Akım probu: hedef elemanın akımını ölçer.
        /// </summary>
        private void BtnAddProbe_Click(object sender, RoutedEventArgs e)
        {
            ExitWireMode();
            _probeCounter++;

            var probe = new TestProbe
            {
                Id = $"VP{_probeCounter}",
                Type = ProbeType.Voltage
            };

            var center = GetViewportCenterInCanvas();
            double centerX = GridHelper.Snap(center.X + 120);
            double centerY = GridHelper.Snap(center.Y - 40);
            centerY += (_probeCounter - 1) * GridHelper.GridSize * 3;

            probe.Position = new Point(centerX, centerY);
            AddElementToCanvas(probe);

            TxtStatus.Text = $"{probe.Id} (Gerilim probu) eklendi — Çift-tıkla V/I değiştir";
        }

        private void BtnAddVoltageSource_Click(object sender, RoutedEventArgs e)
        {
            ExitWireMode();
            _voltageSourceCounter++;

            var source = new VoltageSource
            {
                Id = $"V{_voltageSourceCounter}",
                Value = 12
            };

            var center = GetViewportCenterInCanvas();
            double centerX = GridHelper.Snap(center.X - 160);
            double centerY = GridHelper.Snap(center.Y - 20);
            centerY += (_voltageSourceCounter - 1) * GridHelper.GridSize * 3;

            source.Position = new Point(centerX, centerY);
            AddElementToCanvas(source);

            TxtStatus.Text = $"{source.Id} ({source.Value}V DC) eklendi — Sürükle/Sağ-tık/Çift-tık";
        }

        private void BtnAddAcSource_Click(object sender, RoutedEventArgs e)
        {
            ExitWireMode();
            _acSourceCounter++;

            var acSource = new AcVoltageSource
            {
                Id = $"VAC{_acSourceCounter}",
                Amplitude = 10,
                Frequency = 50,
                Phase = 0
            };

            var center = GetViewportCenterInCanvas();
            double centerX = GridHelper.Snap(center.X - 280);
            double centerY = GridHelper.Snap(center.Y - 20);
            centerY += (_acSourceCounter - 1) * GridHelper.GridSize * 3;

            acSource.Position = new Point(centerX, centerY);
            AddElementToCanvas(acSource);

            TxtStatus.Text = $"{acSource.Id} eklendi — {acSource.Amplitude}V, " +
                $"{acSource.Frequency}Hz, ∠{acSource.Phase}° — Sürükle/Sağ-tık/Çift-tık";
        }

        private void BtnAddCurrentSource_Click(object sender, RoutedEventArgs e)
        {
            ExitWireMode();
            _currentSourceCounter++;

            var source = new CurrentSource
            {
                Id = $"I{_currentSourceCounter}",
                Value = 0.001
            };

            var center = GetViewportCenterInCanvas();
            double centerX = GridHelper.Snap(center.X - 160);
            double centerY = GridHelper.Snap(center.Y - 20);
            centerY += (_currentSourceCounter - 1) * GridHelper.GridSize * 3;

            source.Position = new Point(centerX, centerY);
            AddElementToCanvas(source);

            TxtStatus.Text = $"{source.Id} ({source.Value}A DC) eklendi — Sürükle/Sağ-tık/Çift-tık";
        }

        private void BtnAddAcCurrentSource_Click(object sender, RoutedEventArgs e)
        {
            ExitWireMode();
            _acCurrentSourceCounter++;

            var acSource = new AcCurrentSource
            {
                Id = $"IAC{_acCurrentSourceCounter}",
                Amplitude = 0.01,
                Frequency = 50,
                Phase = 0
            };

            var center = GetViewportCenterInCanvas();
            double centerX = GridHelper.Snap(center.X - 280);
            double centerY = GridHelper.Snap(center.Y - 20);
            centerY += (_acCurrentSourceCounter - 1) * GridHelper.GridSize * 3;

            acSource.Position = new Point(centerX, centerY);
            AddElementToCanvas(acSource);

            TxtStatus.Text = $"{acSource.Id} eklendi — {acSource.Amplitude}A, " +
                $"{acSource.Frequency}Hz, ∠{acSource.Phase}° — Sürükle/Sağ-tık/Çift-tık";
        }

        /// <summary>
        /// Bir CircuitElement'i Canvas'a ekler ve devre değişikliği kaydeder.
        /// </summary>
        private void AddElementToCanvas(CircuitElement element)
        {
            AddElementToCanvasCore(element);
            SyncCountersFromIds();
            OnCircuitChanged();
        }

        /// <summary>
        /// Bir CircuitElement'i ve görselini Canvas'a ekler (OnCircuitChanged çağırmaz;
        /// toplu yükleme ve yapıştırma işlemlerinde tek geri-al adımı üretmek için kullanılır).
        /// </summary>
        private UIElement AddElementToCanvasCore(CircuitElement element)
        {
            _elements.Add(element);
            UIElement visual = element.CreateVisual();

            Canvas.SetLeft(visual, element.Position.X);
            Canvas.SetTop(visual, element.Position.Y);

            if (element.Rotation != 0)
            {
                ApplyRotationTransform(visual, element.Rotation);
            }

            visual.MouseLeftButtonDown += Element_MouseLeftButtonDown;
            visual.MouseRightButtonDown += Element_MouseRightButtonDown;

            if (visual is FrameworkElement fe)
            {
                fe.ContextMenu = CreateElementContextMenu(element, visual);
            }

            _visualToElement[visual] = element;
            _elementToVisual[element] = visual;
            CircuitCanvas.Children.Add(visual);
            return visual;
        }

        /// <summary>
        /// Bir eleman için sağ-tık bağlam menüsü oluşturur.
        /// </summary>
        private ContextMenu CreateElementContextMenu(CircuitElement element, UIElement visual)
        {
            var menu = new ContextMenu();

            // Döndür
            var rotateItem = new MenuItem
            {
                Header = "90° Döndür (R)"
            };
            rotateItem.Click += (s, args) =>
            {
                if (_selection.IsSelected(element) && _selection.Count > 1)
                    RotateSelected();
                else
                    RotateElement(element, visual);
            };
            menu.Items.Add(rotateItem);

            // Düzenle
            var editItem = new MenuItem
            {
                Header = "Değer düzenle"
            };
            editItem.Click += (s, args) => EditElement(element, visual);
            menu.Items.Add(editItem);

            menu.Items.Add(new Separator());

            // Kopyala
            var copyItem = new MenuItem
            {
                Header = "Kopyala (Ctrl+C)"
            };
            copyItem.Click += (s, args) =>
            {
                if (!_selection.IsSelected(element))
                    _selection.Select(element);
                CopySelected();
            };
            menu.Items.Add(copyItem);

            // Kes
            var cutItem = new MenuItem
            {
                Header = "Kes (Ctrl+X)"
            };
            cutItem.Click += (s, args) =>
            {
                if (!_selection.IsSelected(element))
                    _selection.Select(element);
                CutSelected();
            };
            menu.Items.Add(cutItem);

            // Çoğalt
            var duplicateItem = new MenuItem
            {
                Header = "Çoğalt (Ctrl+D)"
            };
            duplicateItem.Click += (s, args) =>
            {
                if (!_selection.IsSelected(element))
                    _selection.Select(element);
                DuplicateSelected();
            };
            menu.Items.Add(duplicateItem);

            menu.Items.Add(new Separator());

            // Sil
            var deleteItem = new MenuItem
            {
                Header = "Sil"
            };
            deleteItem.Click += (s, args) =>
            {
                if (_selection.IsSelected(element) && _selection.Count > 1)
                    DeleteSelected();
                else
                    DeleteElement(element, visual);
            };
            menu.Items.Add(deleteItem);

            return menu;
        }

        /// <summary>
        /// Boş çizim alanı için sağ-tık bağlam menüsünü oluşturur (Yapıştır ve Tümünü seç).
        /// </summary>
        private void InitializeCanvasContextMenu()
        {
            var menu = new ContextMenu();

            _canvasPasteMenuItem = new MenuItem
            {
                Header = "Yapıştır (Ctrl+V)",
                IsEnabled = false
            };
            _canvasPasteMenuItem.Click += (_, _) => PasteFromClipboard(_contextMenuCanvasPos);
            menu.Items.Add(_canvasPasteMenuItem);

            _canvasSelectAllMenuItem = new MenuItem
            {
                Header = "Tümünü seç (Ctrl+A)"
            };
            _canvasSelectAllMenuItem.Click += (_, _) => SelectAllElements();
            menu.Items.Add(_canvasSelectAllMenuItem);

            menu.Opened += (_, _) => UpdateCanvasContextMenuState();

            _canvasContextMenu = menu;
            CircuitCanvas.ContextMenu = menu;
            CircuitCanvas.PreviewMouseRightButtonDown += (_, e) =>
            {
                if (IsDescendantOfAnyElementVisual(e.OriginalSource as DependencyObject))
                    return;

                Point pos = e.GetPosition(CircuitCanvas);
                HandleCanvasRightButtonDown(pos);
            };
        }

        private bool IsDescendantOfAnyElementVisual(DependencyObject? source)
        {
            while (source != null && !ReferenceEquals(source, CircuitCanvas))
            {
                if (source is UIElement ui && _visualToElement.ContainsKey(ui))
                    return true;
                source = VisualTreeHelper.GetParent(source);
            }
            return false;
        }

        /// <summary>
        /// Tuval üzerinde sağ tıklandığında tel üzerindeyse teli seçip tel bağlam menüsünü,
        /// boş alandaysa tuval bağlam menüsünü hazırlar.
        /// </summary>
        internal ContextMenu? HandleCanvasRightButtonDown(Point pos)
        {
            _contextMenuCanvasPos = pos;

            if (!_isWireMode && !_isPinWiring && FindNearestPin(pos) == null)
            {
                var wireHit = WireGeometry.HitTestWire(_wires, pos, GetWireTolerance());
                if (wireHit is var (hitWire, snapped))
                {
                    if (!_selection.IsSelected(hitWire))
                    {
                        _selection.Select(hitWire);
                    }
                    var wireMenu = CreateWireContextMenu(hitWire, snapped);
                    CircuitCanvas.ContextMenu = wireMenu;
                    return wireMenu;
                }
            }

            CircuitCanvas.ContextMenu = _canvasContextMenu;
            UpdateCanvasContextMenuState();
            return _canvasContextMenu;
        }

        /// <summary>
        /// Bir tel için sağ-tık bağlam menüsü oluşturur ("Teli sil (Delete)" ve "Buradan tel çiz").
        /// </summary>
        internal ContextMenu CreateWireContextMenu(Wire wire, Point snappedPoint)
        {
            var menu = new ContextMenu();

            var deleteItem = new MenuItem
            {
                Header = "Teli sil (Delete)"
            };
            deleteItem.Click += (_, _) =>
            {
                if (!_selection.IsSelected(wire))
                {
                    _selection.Select(wire);
                }
                DeleteSelected();
            };
            menu.Items.Add(deleteItem);

            var drawFromHereItem = new MenuItem
            {
                Header = "Buradan tel çiz"
            };
            drawFromHereItem.Click += (_, _) =>
            {
                StartPinWireFromWire(wire, snappedPoint);
            };
            menu.Items.Add(drawFromHereItem);

            return menu;
        }

        private void UpdateCanvasContextMenuState()
        {
            if (_canvasPasteMenuItem != null)
                _canvasPasteMenuItem.IsEnabled = ClipboardService.ContainsCircuit();
            if (_canvasSelectAllMenuItem != null)
                _canvasSelectAllMenuItem.IsEnabled = _elements.Count > 0 || _wires.Count > 0;
        }

        private void Element_MouseRightButtonDown(object sender, MouseButtonEventArgs e)
        {
            if (sender is UIElement visual && _visualToElement.TryGetValue(visual, out var element))
            {
                if (!_selection.IsSelected(element))
                {
                    _selection.Select(element);
                }
            }
        }

        // ═══════════════════════════════════════════════════════
        //  SÜRÜKLEME (DRAG & DROP + SNAP-TO-GRID) VE ÇERÇEVE SEÇİMİ
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Bir eleman üzerinde fare sol tuşu basıldığında:
        /// - Tel modundaysa → HandleWireClick
        /// - Pin tel çizimi sürüyorsa → HandlePinWireClick
        /// - Çift tıksa → Değer düzenleme diyaloğu
        /// - Ctrl+tıksa → Seçime ekle/çıkar
        /// - Normal modda pin üzerindeyse → Tel çizimini başlat
        /// - Eleman gövdesindeyse → Seç + toplu sürükleme başlat
        /// </summary>
        private void Element_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
        {
            Point mousePos = e.GetPosition(CircuitCanvas);

            // ── Tel çizim modundaysa ──
            if (_isWireMode)
            {
                HandleWireClick(mousePos);
                e.Handled = true;
                return;
            }

            // ── Normal modda pin tel çizimi aktifse ──
            if (_isPinWiring)
            {
                if (e.ClickCount == 2 && sender is UIElement dblVisual && _visualToElement.TryGetValue(dblVisual, out var dblElement))
                {
                    CancelPinWire();
                    EditElement(dblElement, dblVisual);
                    e.Handled = true;
                    return;
                }
                HandlePinWireClick(mousePos);
                e.Handled = true;
                return;
            }

            if (sender is UIElement visual && _visualToElement.TryGetValue(visual, out var element))
            {
                // ── Çift tık → Değer düzenleme ──
                if (e.ClickCount == 2)
                {
                    EditElement(element, visual);
                    e.Handled = true;
                    return;
                }

                // ── Ctrl+tık → Seçime ekle / çıkar ──
                if (Keyboard.Modifiers.HasFlag(ModifierKeys.Control))
                {
                    _selection.Toggle(element);
                    TxtStatus.Text = FormatSelectionStatus();
                    e.Handled = true;
                    return;
                }

                // ── Normal modda bir pinin yakınına basıldıysa doğrudan tel başlat ──
                // Not: Bağlantı noktası (JunctionElement) tek pinli olduğundan sürüklenebilmesi için
                // basışta sürükleme başlatılır; sürüklenmeden bırakılırsa tel çizimine geçilir.
                if (element is not JunctionElement)
                {
                    Pin? nearPin = FindNearestPin(mousePos);
                    if (nearPin != null)
                    {
                        StartPinWire(nearPin);
                        e.Handled = true;
                        return;
                    }
                }

                // ── Gövdeye tek tık → Seç + sürükleme başlat ──
                if (!_selection.IsSelected(element))
                {
                    _selection.Select(element);
                }

                RemovePreviewVisuals();
                _isDragging = true;
                _draggedVisual = visual;
                _draggedElement = element;
                _dragStartPosition = element.Position;
                _dragInitialPositions = _selection.Elements.ToDictionary(el => el, el => el.Position);

                double elementX = Canvas.GetLeft(visual);
                double elementY = Canvas.GetTop(visual);
                _dragOffset = new Point(mousePos.X - elementX, mousePos.Y - elementY);

                visual.CaptureMouse();
                e.Handled = true;

                TxtStatus.Text = _selection.Count > 1
                    ? $"{_selection.Count} eleman sürükleniyor..."
                    : $"{element.Id} sürükleniyor... (R: döndür)";
            }
        }

        /// <summary>
        /// Canvas üzerinde fare hareket ettiğinde:
        /// - Tel üzerinde basılı tutup >4px sürüklendiyse → tel böl ve yeni tel çizimini başlat
        /// - Tel modunda veya pin tel çizimindeyse → pin vurgusu ve önizleme çizgisi
        /// - Sürükleme aktifse → seçili tüm elemanları aynı grid-snapped delta ile taşı
        /// - Çerçeve seçimi sürüyorsa → 4px eşiği aşılınca seçim dikdörtgenini güncelle
        /// - Normal boş gezinmede → pin üzerindeyse Cross, tel üzerindeyse Hand ve vurgu
        /// </summary>
        private void CircuitCanvas_MouseMove(object sender, MouseEventArgs e)
        {
            HandleCanvasMouseMove(e.GetPosition(CircuitCanvas));
        }

        internal void HandleCanvasMouseMove(Point mousePos)
        {
            Point snappedPos = GridHelper.Snap(mousePos);
            TxtCoords.Text = $"X: {snappedPos.X:F0}  Y: {snappedPos.Y:F0}";

            if (_isWirePressPending && _pressedWire != null)
            {
                double dist = (mousePos - _wirePressPos).Length * Math.Max(0.25, _currentZoom);
                if (dist > RubberBandThreshold)
                {
                    var wireToSplit = _pressedWire;
                    var snapped = _wirePressSnapped;
                    _isWirePressPending = false;
                    _pressedWire = null;
                    CircuitCanvas.ReleaseMouseCapture();

                    StartPinWireFromWire(wireToSplit, snapped);
                }
                else
                {
                    return;
                }
            }

            if (_isWireMode || _isPinWiring)
            {
                SetHoveredWire(null);
                UpdatePinHighlight(mousePos);
                if (_pinHighlight != null)
                {
                    UpdateJunctionPreview(null);
                    UpdateWirePreview(mousePos, null);
                }
                else
                {
                    var wireHit = WireGeometry.HitTestWire(_wires, mousePos, GetWireTolerance());
                    UpdateJunctionPreview(wireHit?.snapped);
                    UpdateWirePreview(mousePos, wireHit?.snapped);
                    if (wireHit != null)
                    {
                        TxtStatus.Text = "Bu tele bağlamak için tıklayın";
                    }
                }
                CircuitCanvas.Cursor = Cursors.Cross;
                return;
            }

            if (_isDragging && _draggedVisual != null && _draggedElement != null)
            {
                double newX = GridHelper.Snap(mousePos.X - _dragOffset.X);
                double newY = GridHelper.Snap(mousePos.Y - _dragOffset.Y);

                double canvasW = CircuitCanvas.ActualWidth > 0 ? CircuitCanvas.ActualWidth : CircuitCanvas.Width;
                double canvasH = CircuitCanvas.ActualHeight > 0 ? CircuitCanvas.ActualHeight : CircuitCanvas.Height;

                newX = Math.Max(0, Math.Min(newX, canvasW - _draggedElement.VisualWidth));
                newY = Math.Max(0, Math.Min(newY, canvasH - _draggedElement.VisualHeight));

                double dx = newX - _dragStartPosition.X;
                double dy = newY - _dragStartPosition.Y;

                foreach (var (el, startPos) in _dragInitialPositions)
                {
                    double elNewX = GridHelper.Snap(Math.Max(0, Math.Min(startPos.X + dx, canvasW - el.VisualWidth)));
                    double elNewY = GridHelper.Snap(Math.Max(0, Math.Min(startPos.Y + dy, canvasH - el.VisualHeight)));
                    var targetPos = new Point(elNewX, elNewY);

                    if (el.Position != targetPos)
                    {
                        _overlay?.Clear();
                        el.Position = targetPos;
                    }

                    if (_elementToVisual.TryGetValue(el, out var elVisual))
                    {
                        Canvas.SetLeft(elVisual, targetPos.X);
                        Canvas.SetTop(elVisual, targetPos.Y);
                    }

                    UpdateConnectedWires(el);
                }

                UpdateSelectionHighlight();
                return;
            }

            if (_isRubberBandPending)
            {
                double dist = (mousePos - _rubberBandStart).Length * Math.Max(0.25, _currentZoom);
                if (!_isRubberBandActive && dist >= RubberBandThreshold)
                {
                    _isRubberBandActive = true;
                    RemovePreviewVisuals();
                    EnsureRubberBandVisual();
                }

                if (_isRubberBandActive && _rubberBandRect != null)
                {
                    var rect = new Rect(_rubberBandStart, mousePos);
                    Canvas.SetLeft(_rubberBandRect, rect.X);
                    Canvas.SetTop(_rubberBandRect, rect.Y);
                    _rubberBandRect.Width = rect.Width;
                    _rubberBandRect.Height = rect.Height;
                }
                return;
            }

            // Normal modda pin üzerine gelindiğinde Cross; tel üzerine gelindiğinde Hand ve tel vurgusu
            UpdatePinHighlight(mousePos);
            if (_pinHighlight != null)
            {
                SetHoveredWire(null);
                UpdateJunctionPreview(null);
                CircuitCanvas.Cursor = Cursors.Cross;
            }
            else
            {
                UpdateJunctionPreview(null);
                var wireHit = WireGeometry.HitTestWire(_wires, mousePos, GetWireTolerance());
                SetHoveredWire(wireHit?.wire);
                if (wireHit != null)
                {
                    CircuitCanvas.Cursor = Cursors.Hand;
                    TxtStatus.Text = "Tıkla: teli seç · Sürükle: buradan yeni tel";
                }
                else
                {
                    CircuitCanvas.Cursor = Cursors.Arrow;
                }
            }
        }

        private void EnsureRubberBandVisual()
        {
            if (_rubberBandRect != null)
                return;

            _rubberBandRect = new Rectangle
            {
                StrokeThickness = 1,
                IsHitTestVisible = false
            };
            _rubberBandRect.SetResourceReference(Shape.StrokeProperty, "Brush.Accent");
            _rubberBandRect.SetResourceReference(Shape.FillProperty, "Brush.Circuit.SelectionFill");
            Panel.SetZIndex(_rubberBandRect, 900);
            CircuitCanvas.Children.Add(_rubberBandRect);
        }

        private void RemoveRubberBandVisual()
        {
            if (_rubberBandRect != null)
            {
                CircuitCanvas.Children.Remove(_rubberBandRect);
                _rubberBandRect = null;
            }
        }

        private void CircuitCanvas_MouseLeftButtonUp(object sender, MouseButtonEventArgs e)
        {
            HandleCanvasLeftButtonUp(e.GetPosition(CircuitCanvas));
        }

        internal void HandleCanvasLeftButtonUp(Point releasePos, ModifierKeys? modifiers = null)
        {
            ModifierKeys mods = modifiers ?? Keyboard.Modifiers;

            if (_isDragging && _draggedVisual != null && _draggedElement != null)
            {
                _draggedVisual.ReleaseMouseCapture();
                bool moved = _dragInitialPositions.Any(kv => kv.Key.Position != kv.Value);
                var clickedElement = _draggedElement;
                int movedCount = _dragInitialPositions.Count;

                _isDragging = false;
                _draggedVisual = null;
                _draggedElement = null;
                _dragInitialPositions.Clear();

                if (moved)
                {
                    OnCircuitChanged();
                    TxtStatus.Text = movedCount > 1
                        ? $"{movedCount} eleman taşındı"
                        : $"{clickedElement.Id} → Konum: ({clickedElement.Position.X:F0}, {clickedElement.Position.Y:F0})";
                }
                else
                {
                    if (_selection.Count > 1 || _selection.Wires.Count > 0)
                    {
                        // Çoklu seçimdeki bir elemana sürüklemeden tek tıklandıysa yalnızca onu seç
                        _selection.Select(clickedElement);
                    }
                    if (clickedElement is JunctionElement junction && junction.Pins.Count > 0)
                    {
                        StartPinWire(junction.Pins[0]);
                    }
                }
                return;
            }

            if (_isWirePressPending)
            {
                CircuitCanvas.ReleaseMouseCapture();
                var hitWire = _pressedWire;
                var snapped = _wirePressSnapped;
                var pressPos = _wirePressPos;
                var pressMods = _wirePressModifiers;
                _isWirePressPending = false;
                _pressedWire = null;

                if (hitWire != null)
                {
                    double dist = (releasePos - pressPos).Length * Math.Max(0.25, _currentZoom);
                    if (dist > RubberBandThreshold)
                    {
                        StartPinWireFromWire(hitWire, snapped);
                        return;
                    }

                    bool isCtrl = mods.HasFlag(ModifierKeys.Control) || pressMods.HasFlag(ModifierKeys.Control);
                    if (isCtrl)
                    {
                        _selection.Toggle(hitWire);
                    }
                    else
                    {
                        _selection.Select(hitWire);
                    }
                    TxtStatus.Text = FormatSelectionStatus();
                }
                return;
            }

            if (_isRubberBandPending)
            {
                CircuitCanvas.ReleaseMouseCapture();
                _isRubberBandPending = false;
                bool isCtrl = mods.HasFlag(ModifierKeys.Control) || _rubberBandModifiers.HasFlag(ModifierKeys.Control);

                if (_isRubberBandActive)
                {
                    _isRubberBandActive = false;
                    RemoveRubberBandVisual();
                    var rect = new Rect(_rubberBandStart, releasePos);
                    _selection.SelectInRect(rect, _elements, _wires, isCtrl);
                    TxtStatus.Text = FormatSelectionStatus();
                }
                else
                {
                    RemoveRubberBandVisual();
                    if (!isCtrl)
                    {
                        DeselectElement();
                    }
                    Point snapped = GridHelper.Snap(releasePos);
                    TxtCoords.Text = $"Tıklama: ({snapped.X:F0}, {snapped.Y:F0})";
                }
            }
        }

        private void CircuitCanvas_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
        {
            HandleCanvasLeftButtonDown(e.GetPosition(CircuitCanvas));
        }

        internal void HandleCanvasLeftButtonDown(Point pos, ModifierKeys? modifiers = null)
        {
            if (_isPanning || Keyboard.IsKeyDown(Key.Space))
                return;

            ModifierKeys mods = modifiers ?? Keyboard.Modifiers;

            if (_isWireMode)
            {
                HandleWireClick(pos);
                return;
            }

            if (_isPinWiring)
            {
                HandlePinWireClick(pos);
                return;
            }

            // Normal modda pin yakınına tıklandıysa tel başlat (pin önceliklidir)
            if (mods == ModifierKeys.None)
            {
                Pin? nearPin = FindNearestPin(pos);
                if (nearPin != null)
                {
                    StartPinWire(nearPin);
                    return;
                }
            }

            // Normal modda tel üzerine basıldıysa: bırakılırsa seç/toggle, >4px sürüklenirse tel böl + yeni tel başlat
            if (mods == ModifierKeys.None || mods == ModifierKeys.Control)
            {
                if (FindNearestPin(pos) == null)
                {
                    var wireHit = WireGeometry.HitTestWire(_wires, pos, GetWireTolerance());
                    if (wireHit is var (hitWire, snapped))
                    {
                        _isWirePressPending = true;
                        _pressedWire = hitWire;
                        _wirePressPos = pos;
                        _wirePressSnapped = snapped;
                        _wirePressModifiers = mods;
                        CircuitCanvas.CaptureMouse();
                        return;
                    }
                }
            }

            // Boş alanda sürükleme (Rubber-band) veya tek tıkla seçim temizleme başlat
            SetHoveredWire(null);
            _isRubberBandPending = true;
            _isRubberBandActive = false;
            _rubberBandStart = pos;
            _rubberBandModifiers = mods;
            CircuitCanvas.CaptureMouse();
        }

        // ═══════════════════════════════════════════════════════
        //  SEÇİM MEKANİZMASI
        // ═══════════════════════════════════════════════════════

        /// <summary>Tek bir elemanı seçer.</summary>
        private void SelectElement(CircuitElement element, UIElement visual)
        {
            _selection.Select(element);
        }

        /// <summary>Tüm seçimi kaldırır ve vurgu kutularını temizler.</summary>
        private void DeselectElement()
        {
            _hoveredWire = null;
            _selection.Clear();
        }

        /// <summary>Tuvaldeki tüm elemanları ve telleri seçer (Ctrl+A).</summary>
        public void SelectAllElements()
        {
            if (_elements.Count == 0 && _wires.Count == 0)
                return;

            _selection.SelectAll(_elements, _wires);
            TxtStatus.Text = FormatSelectionStatus();
        }

        private string FormatSelectionStatus()
        {
            int elemCount = _selection.Count;
            int wireCount = _selection.Wires.Count;

            if (elemCount == 0 && wireCount == 0)
                return "Seçim temizlendi";
            if (elemCount == 0 && wireCount == 1)
                return "Tel seçildi (Delete: sil)";
            if (elemCount == 0)
                return $"{wireCount} tel seçildi";
            if (wireCount == 0)
                return $"{elemCount} eleman seçildi";
            return $"{elemCount} eleman, {wireCount} tel seçildi";
        }

        private void SetHoveredWire(Wire? wire)
        {
            if (ReferenceEquals(_hoveredWire, wire))
                return;

            var prev = _hoveredWire;
            _hoveredWire = wire;

            if (prev != null)
                ApplyWireVisualStyle(prev);
            if (_hoveredWire != null)
                ApplyWireVisualStyle(_hoveredWire);
        }

        private void ApplyWireVisualStyle(Wire wire)
        {
            if (wire.Visual == null)
                return;

            bool selected = _selection.IsSelected(wire);
            if (selected)
            {
                wire.Visual.SetResourceReference(Shape.StrokeProperty, "Brush.Accent");
                wire.Visual.StrokeThickness = 3;
                wire.Visual.Opacity = 1.0;
            }
            else if (ReferenceEquals(wire, _hoveredWire))
            {
                wire.Visual.SetResourceReference(Shape.StrokeProperty, "Brush.Accent");
                wire.Visual.StrokeThickness = 2;
                wire.Visual.Opacity = 0.65;
            }
            else
            {
                wire.Visual.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Wire");
                wire.Visual.StrokeThickness = 2;
                wire.Visual.Opacity = 1.0;
            }
        }

        /// <summary>
        /// Seçili tüm elemanların etrafındaki vurgu kutularını ve seçili tellerin görünümünü günceller.
        /// </summary>
        private void UpdateSelectionHighlight()
        {
            foreach (var rect in _selectionHighlights)
            {
                CircuitCanvas.Children.Remove(rect);
            }
            _selectionHighlights.Clear();

            _selectedElement = _selection.PrimaryElement;
            _selectedVisual = _selectedElement != null && _elementToVisual.TryGetValue(_selectedElement, out var vis)
                ? vis
                : null;

            double pad = 4;
            foreach (var element in _selection.Elements)
            {
                double w = element.VisualWidth + pad * 2;
                double h = element.VisualHeight + pad * 2;

                var highlight = new Rectangle
                {
                    IsHitTestVisible = false,
                    StrokeThickness = 2,
                    RadiusX = 4,
                    RadiusY = 4,
                    Width = w,
                    Height = h
                };
                highlight.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Selection");
                highlight.SetResourceReference(Shape.FillProperty, "Brush.Circuit.SelectionFill");
                Canvas.SetLeft(highlight, element.Position.X - pad);
                Canvas.SetTop(highlight, element.Position.Y - pad);

                if (element.Rotation != 0)
                {
                    highlight.RenderTransformOrigin = new Point(0.5, 0.5);
                    highlight.RenderTransform = new RotateTransform(element.Rotation);
                }

                CircuitCanvas.Children.Add(highlight);
                _selectionHighlights.Add(highlight);
            }

            foreach (var wire in _wires)
            {
                ApplyWireVisualStyle(wire);
            }
        }

        // ═══════════════════════════════════════════════════════
        //  DÖNDÜRME (ROTATION)
        // ═══════════════════════════════════════════════════════

        /// <summary>Tek bir elemanı 90° saat yönünde döndürür.</summary>
        private void RotateElement(CircuitElement element, UIElement visual)
        {
            if (element is JunctionElement)
                return;

            element.Rotation = (element.Rotation + 90) % 360;
            ApplyRotationTransform(visual, element.Rotation);

            UpdateConnectedWires(element);
            UpdateSelectionHighlight();
            OnCircuitChanged();

            TxtStatus.Text = $"{element.Id} → {element.Rotation}° döndürüldü";
        }

        /// <summary>Seçili tüm elemanları kendi merkezleri etrafında 90° döndürür (tek geri-al adımı).</summary>
        public void RotateSelected()
        {
            var selected = _selection.Elements.Where(e => e is not JunctionElement).ToList();
            if (selected.Count == 0)
                return;

            if (selected.Count == 1 && _elementToVisual.TryGetValue(selected[0], out var singleVis))
            {
                RotateElement(selected[0], singleVis);
                return;
            }

            foreach (var element in selected)
            {
                element.Rotation = (element.Rotation + 90) % 360;
                if (_elementToVisual.TryGetValue(element, out var visual))
                {
                    ApplyRotationTransform(visual, element.Rotation);
                }
                UpdateConnectedWires(element);
            }

            UpdateSelectionHighlight();
            OnCircuitChanged();
            TxtStatus.Text = $"{selected.Count} eleman 90° döndürüldü";
        }

        /// <summary>
        /// UIElement'e RenderTransform ile döndürme uygular.
        /// Merkez nokta olarak elemanın görsel merkezini kullanır.
        /// </summary>
        private void ApplyRotationTransform(UIElement visual, double angle)
        {
            visual.RenderTransformOrigin = new Point(0.5, 0.5);
            visual.RenderTransform = new RotateTransform(angle);
        }

        // ═══════════════════════════════════════════════════════
        //  DEĞER DÜZENLEME (VALUE EDITING)
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Değer düzenleme diyaloğunu açar.
        /// </summary>
        private void EditElement(CircuitElement element, UIElement visual)
        {
            if (element is JunctionElement)
                return;

            var editor = new ElementEditorWindow(element);
            editor.Owner = this;

            if (editor.ShowDialog() == true)
            {
                RefreshElementVisual(element, visual);
                OnCircuitChanged();
                TxtStatus.Text = $"{element.Id} güncellendi";
            }
        }

        /// <summary>Bir elemanın görselini yeniden oluşturur.</summary>
        private void RefreshElementVisual(CircuitElement element, UIElement oldVisual)
        {
            CircuitCanvas.Children.Remove(oldVisual);
            _visualToElement.Remove(oldVisual);
            _elementToVisual.Remove(element);

            UIElement newVisual = element.CreateVisual();

            Canvas.SetLeft(newVisual, element.Position.X);
            Canvas.SetTop(newVisual, element.Position.Y);

            if (element.Rotation != 0)
            {
                ApplyRotationTransform(newVisual, element.Rotation);
            }

            newVisual.MouseLeftButtonDown += Element_MouseLeftButtonDown;
            newVisual.MouseRightButtonDown += Element_MouseRightButtonDown;
            if (newVisual is FrameworkElement fe)
            {
                fe.ContextMenu = CreateElementContextMenu(element, newVisual);
            }

            _visualToElement[newVisual] = element;
            _elementToVisual[element] = newVisual;
            CircuitCanvas.Children.Add(newVisual);

            UpdateSelectionHighlight();
        }

        // ═══════════════════════════════════════════════════════
        //  ELEMAN SİLME VE PANO (KOPYALA / KES / YAPIŞTIR / ÇOĞALT)
        // ═══════════════════════════════════════════════════════

        /// <summary>Tek bir elemanı ve bağlı tüm tellerini Canvas'tan siler.</summary>
        private void DeleteElement(CircuitElement element, UIElement visual)
        {
            bool wasSelected = _selection.IsSelected(element);
            if (wasSelected)
            {
                var remainingElem = _selection.Elements.Where(e => e != element).ToList();
                var remainingWires = _selection.Wires
                    .Where(w => w.StartPin.Owner != element && w.EndPin.Owner != element)
                    .ToList();
                _selection.Select(remainingElem, remainingWires);
            }

            var connectedWires = _wires
                .Where(w => w.StartPin.Owner == element || w.EndPin.Owner == element)
                .ToList();

            foreach (var wire in connectedWires)
            {
                if (wire.Visual != null)
                    CircuitCanvas.Children.Remove(wire.Visual);
                _wires.Remove(wire);
            }

            CircuitCanvas.Children.Remove(visual);
            _visualToElement.Remove(visual);
            _elementToVisual.Remove(element);
            _elements.Remove(element);
            CleanupJunctionsOnCanvas();
            OnCircuitChanged();

            TxtStatus.Text = $"{element.Id} silindi ({connectedWires.Count} tel de kaldırıldı)";
        }

        /// <summary>
        /// Seçili tüm elemanları, onlara bağlı telleri ve seçili telleri tek geri-al adımında siler.
        /// </summary>
        public void DeleteSelected()
        {
            if (!_selection.HasSelection)
                return;

            var elementsToRemove = _selection.Elements.ToList();
            int selectedWiresCount = _selection.Wires.Count;
            var elementSet = new HashSet<CircuitElement>(elementsToRemove);
            var wiresToRemove = _wires
                .Where(w => _selection.IsSelected(w) ||
                            (w.StartPin.Owner != null && elementSet.Contains(w.StartPin.Owner)) ||
                            (w.EndPin.Owner != null && elementSet.Contains(w.EndPin.Owner)))
                .Distinct()
                .ToList();

            if (elementsToRemove.Count == 1 && selectedWiresCount == 0 &&
                _elementToVisual.TryGetValue(elementsToRemove[0], out var singleVisual))
            {
                DeleteElement(elementsToRemove[0], singleVisual);
                return;
            }

            _selection.Clear();
            SetHoveredWire(null);

            foreach (var wire in wiresToRemove)
            {
                if (wire.Visual != null)
                    CircuitCanvas.Children.Remove(wire.Visual);
                _wires.Remove(wire);
            }

            foreach (var element in elementsToRemove)
            {
                if (_elementToVisual.TryGetValue(element, out var visual))
                {
                    CircuitCanvas.Children.Remove(visual);
                    _visualToElement.Remove(visual);
                    _elementToVisual.Remove(element);
                }
                _elements.Remove(element);
            }

            CleanupJunctionsOnCanvas();
            OnCircuitChanged();

            if (elementsToRemove.Count == 0 && selectedWiresCount == 1)
            {
                TxtStatus.Text = "Tel silindi";
            }
            else
            {
                int totalDeleted = elementsToRemove.Count + selectedWiresCount;
                TxtStatus.Text = $"{totalDeleted} öğe silindi";
            }
        }

        /// <summary>Seçili elemanları ve iç tellerini panoya kopyalar (Ctrl+C).</summary>
        public bool CopySelected()
        {
            if (_selection.Count == 0)
                return false;

            int count = _selection.Count;
            CircuitClipboard.CopyToClipboard(ClipboardService, _selection.Elements, _wires);
            _pasteCascadeCount = 0;
            UpdateCanvasContextMenuState();
            TxtStatus.Text = $"{count} eleman kopyalandı";
            return true;
        }

        /// <summary>Seçili elemanları panoya kopyalar ve tuvalden siler (Ctrl+X, tek geri-al adımı).</summary>
        public bool CutSelected()
        {
            if (!_selection.HasSelection)
                return false;

            int count = _selection.Count;
            if (count > 0)
            {
                CircuitClipboard.CopyToClipboard(ClipboardService, _selection.Elements, _wires);
                _pasteCascadeCount = 0;
                UpdateCanvasContextMenuState();
            }

            DeleteSelected();
            if (count > 0)
            {
                TxtStatus.Text = $"{count} eleman kesildi";
            }
            return true;
        }

        /// <summary>
        /// Panodaki devreyi tuvale yapıştırır (Ctrl+V, tek geri-al adımı).
        /// Fare tuvalin üzerindeyse (veya canvasPosition verilmişse) grup sol-üstü o konuma,
        /// değilse her yapıştırmada 2 ızgara karesi kaydırılarak yerleştirilir.
        /// </summary>
        public bool PasteFromClipboard(Point? canvasPosition = null)
        {
            string? payload = ClipboardService.GetCircuitData();
            if (!CircuitClipboard.IsValidPayload(payload))
                return false;

            Point offset;
            if (canvasPosition.HasValue && CircuitClipboard.TryGetTopLeft(payload, out var topLeftExplicit))
            {
                Point snappedTarget = GridHelper.Snap(canvasPosition.Value);
                offset = new Point(snappedTarget.X - topLeftExplicit.X, snappedTarget.Y - topLeftExplicit.Y);
            }
            else if (CircuitCanvas.IsMouseOver && CircuitClipboard.TryGetTopLeft(payload, out var topLeftMouse))
            {
                Point snappedMouse = GridHelper.Snap(Mouse.GetPosition(CircuitCanvas));
                offset = new Point(snappedMouse.X - topLeftMouse.X, snappedMouse.Y - topLeftMouse.Y);
            }
            else
            {
                _pasteCascadeCount++;
                double step = 2 * GridHelper.GridSize * _pasteCascadeCount;
                offset = new Point(step, step);
            }

            var pasted = CircuitClipboard.Paste(payload, _elements.Select(e => e.Id), offset);
            if (pasted.Elements.Count == 0)
                return false;

            InsertPastedItems(pasted);
            TxtStatus.Text = $"{pasted.Elements.Count} eleman yapıştırıldı";
            return true;
        }

        /// <summary>
        /// Seçili elemanları sistem panosuna dokunmadan 2 ızgara karesi ofsetle çoğaltır (Ctrl+D, tek geri-al adımı).
        /// </summary>
        public bool DuplicateSelected()
        {
            if (_selection.Count == 0)
                return false;

            string payload = CircuitClipboard.Copy(_selection.Elements, _wires);
            double step = 2 * GridHelper.GridSize;
            var pasted = CircuitClipboard.Paste(payload, _elements.Select(e => e.Id), new Point(step, step));
            if (pasted.Elements.Count == 0)
                return false;

            InsertPastedItems(pasted);
            TxtStatus.Text = $"{pasted.Elements.Count} eleman çoğaltıldı";
            return true;
        }

        private void InsertPastedItems(PasteResult pasted)
        {
            foreach (var element in pasted.Elements)
            {
                AddElementToCanvasCore(element);
            }
            foreach (var wire in pasted.Wires)
            {
                _wires.Add(wire);
                CircuitCanvas.Children.Add(wire.CreateOrUpdateVisual());
            }

            RefreshJunctionWireCounts();
            SyncCountersFromIds();
            _selection.Select(pasted.Elements, pasted.Wires);
            OnCircuitChanged();
        }

        // ═══════════════════════════════════════════════════════
        //  TEL ÇİZİM MOTORU
        // ═══════════════════════════════════════════════════════

        private void BtnDrawWire_Click(object sender, RoutedEventArgs e)
        {
            if (_isWireMode)
                ExitWireMode();
            else
                EnterWireMode();
        }

        private void EnterWireMode()
        {
            CancelPinWire();
            DeselectElement();
            _isWireMode = true;
            _wireStartPin = null;
            CircuitCanvas.Cursor = Cursors.Cross;

            BtnDrawWire.SetResourceReference(BackgroundProperty, "Brush.Bg.Selected");
            BtnDrawWire.SetResourceReference(ForegroundProperty, "Brush.Accent.SoftText");
            TxtDrawWire.Text = "Tel çiz — çıkmak için Esc";

            TxtStatus.Text = "TEL MODU — Bir pine tıklayarak tel çizmeye başlayın (Esc: çık)";
        }

        private void ExitWireMode()
        {
            RevertPendingStartSplit();
            _isWireMode = false;
            _isPinWiring = false;
            _wireStartPin = null;
            CircuitCanvas.Cursor = Cursors.Arrow;

            BtnDrawWire.ClearValue(BackgroundProperty);
            BtnDrawWire.ClearValue(ForegroundProperty);
            TxtDrawWire.Text = "Tel çiz";

            RemovePreviewVisuals();

            TxtStatus.Text = "Hazır — Araç kutusundan bir eleman seçin";
        }

        /// <summary>Normal modda bir elemanın ucuna tıklandığında tel çizimini başlatır.</summary>
        internal bool IsPinWiring => _isPinWiring;

        /// <summary>Bir teli verilen noktada bağlantı noktası ile bölerek yeni tel çizimini başlatır.</summary>
        internal void StartPinWireFromWire(Wire wireToSplit, Point snappedPoint)
        {
            SetHoveredWire(null);
            UpdateJunctionPreview(null);
            _pendingStartSplit = SplitWireOnCanvasCore(wireToSplit, snappedPoint);
            StartPinWire(_pendingStartSplit.Junction.Pins[0]);
        }

        internal void StartPinWire(Pin startPin)
        {
            SetHoveredWire(null);
            _isPinWiring = true;
            _wireStartPin = startPin;
            CircuitCanvas.Cursor = Cursors.Cross;
            UpdatePinHighlight(startPin.AbsolutePosition);
            TxtStatus.Text = "Tel çiziliyor — diğer uca tıklayın (Esc: vazgeç)";
        }

        /// <summary>Normal modda başlatılan tel çizimini iptal eder ve normal moda döner.</summary>
        internal void CancelPinWire()
        {
            if (!_isPinWiring)
                return;

            RevertPendingStartSplit();
            _isPinWiring = false;
            _wireStartPin = null;
            RemovePreviewVisuals();
            CircuitCanvas.Cursor = Cursors.Arrow;
            TxtStatus.Text = "Tel çizimi iptal edildi";
        }

        internal void HandlePinWireClick(Point mousePos)
        {
            if (_wireStartPin == null)
            {
                CancelPinWire();
                return;
            }

            Pin startPin = _wireStartPin;
            Pin? nearestPin = FindNearestPin(mousePos);

            if (nearestPin == null)
            {
                var wireHit = WireGeometry.HitTestWire(_wires, mousePos, GetWireTolerance());
                if (wireHit is var (hitWire, snapped))
                {
                    var endSplit = SplitWireOnCanvasCore(hitWire, snapped);
                    _pendingStartSplit = null;
                    _isPinWiring = false;
                    CircuitCanvas.Cursor = Cursors.Arrow;
                    CompleteWire(startPin, endSplit.Junction.Pins[0]);
                    TxtStatus.Text = $"Tel ortasından bağlandı ({endSplit.Junction.Id})";
                    return;
                }

                CancelPinWire();
                return;
            }

            if (nearestPin == startPin)
            {
                CancelPinWire();
                return;
            }

            JunctionElement? startSplitJunction = _pendingStartSplit?.Junction;
            _pendingStartSplit = null;
            _isPinWiring = false;
            CircuitCanvas.Cursor = Cursors.Arrow;
            CompleteWire(startPin, nearestPin);
            TxtStatus.Text = startSplitJunction != null
                ? $"Tel ortasından bağlandı ({startSplitJunction.Id})"
                : $"Tel oluşturuldu: {startPin.Owner?.Id}.{startPin.Id} → {nearestPin.Owner?.Id}.{nearestPin.Id}";
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

            // ── R: Seçili elemanları döndür ──
            if (e.Key == Key.R && mods == ModifierKeys.None && !_isWireMode && !_isPinWiring && _selection.Count > 0)
            {
                RotateSelected();
                e.Handled = true;
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

        private void HandleWireClick(Point mousePos)
        {
            Pin? nearestPin = FindNearestPin(mousePos);

            if (nearestPin == null)
            {
                var wireHit = WireGeometry.HitTestWire(_wires, mousePos, GetWireTolerance());
                if (wireHit is var (hitWire, snapped))
                {
                    if (_wireStartPin == null)
                    {
                        UpdateJunctionPreview(null);
                        _pendingStartSplit = SplitWireOnCanvasCore(hitWire, snapped);
                        _wireStartPin = _pendingStartSplit.Junction.Pins[0];
                        TxtStatus.Text = $"TEL MODU — Başlangıç: {_pendingStartSplit.Junction.Id}.Pin0 " +
                            $"→ Şimdi bitiş pinine tıklayın (Esc: iptal)";
                        return;
                    }

                    Pin startPin = _wireStartPin;
                    var endSplit = SplitWireOnCanvasCore(hitWire, snapped);
                    _pendingStartSplit = null;
                    CompleteWire(startPin, endSplit.Junction.Pins[0]);
                    TxtStatus.Text = $"Tel ortasından bağlandı ({endSplit.Junction.Id})";
                    return;
                }

                TxtStatus.Text = "TEL MODU — Pin bulunamadı! Bir elemanın pin noktasına tıklayın";
                return;
            }

            if (_wireStartPin == null)
            {
                _wireStartPin = nearestPin;
                TxtStatus.Text = $"TEL MODU — Başlangıç: {nearestPin.Owner?.Id}.Pin{nearestPin.Id} " +
                    $"→ Şimdi bitiş pinine tıklayın (Esc: iptal)";
                return;
            }

            if (nearestPin == _wireStartPin)
            {
                TxtStatus.Text = "TEL MODU — Aynı pin! Farklı bir pine tıklayın";
                return;
            }

            JunctionElement? startSplitJunction = _pendingStartSplit?.Junction;
            _pendingStartSplit = null;
            CompleteWire(_wireStartPin, nearestPin);
            if (startSplitJunction != null)
            {
                TxtStatus.Text = $"Tel ortasından bağlandı ({startSplitJunction.Id})";
            }
        }

        private void CompleteWire(Pin startPin, Pin endPin)
        {
            var wire = new Wire(startPin, endPin);
            _wires.Add(wire);

            var visual = wire.CreateOrUpdateVisual();
            CircuitCanvas.Children.Add(visual);

            RefreshJunctionWireCounts();
            RemovePreviewVisuals();
            _wireStartPin = null;
            OnCircuitChanged();

            TxtStatus.Text = $"Tel oluşturuldu: {startPin.Owner?.Id}.{startPin.Id} → " +
                $"{endPin.Owner?.Id}.{endPin.Id} — Yeni tel çizebilirsiniz (Esc: çık)";
        }

        internal double GetWireTolerance()
        {
            double zoom = _currentZoom > 0.01 ? _currentZoom : 1.0;
            return Math.Min(WireSnapThreshold / zoom, WireToleranceCap);
        }

        private void UpdateJunctionPreview(Point? snappedPoint)
        {
            if (_junctionPreview != null)
            {
                CircuitCanvas.Children.Remove(_junctionPreview);
                _junctionPreview = null;
            }

            if (snappedPoint == null)
                return;

            Point pt = snappedPoint.Value;
            _junctionPreview = new Ellipse
            {
                Width = 10,
                Height = 10,
                Fill = Brushes.Transparent,
                StrokeThickness = 2,
                IsHitTestVisible = false
            };
            _junctionPreview.SetResourceReference(Shape.StrokeProperty, "Brush.Accent");

            Canvas.SetLeft(_junctionPreview, pt.X - 5);
            Canvas.SetTop(_junctionPreview, pt.Y - 5);
            CircuitCanvas.Children.Add(_junctionPreview);
        }

        private PendingWireSplit SplitWireOnCanvasCore(Wire hitWire, Point snappedPoint)
        {
            _junctionCounter++;
            var junction = new JunctionElement
            {
                Id = $"J{_junctionCounter}",
                Position = snappedPoint,
            };
            AddElementToCanvasCore(junction);

            var (first, second) = WireGeometry.Split(hitWire, junction);
            int idx = _wires.IndexOf(hitWire);
            if (hitWire.Visual != null)
            {
                CircuitCanvas.Children.Remove(hitWire.Visual);
            }

            if (idx >= 0)
            {
                _wires.RemoveAt(idx);
                _wires.Insert(idx, first);
                _wires.Insert(idx + 1, second);
            }
            else
            {
                _wires.Add(first);
                _wires.Add(second);
            }

            CircuitCanvas.Children.Add(first.CreateOrUpdateVisual());
            CircuitCanvas.Children.Add(second.CreateOrUpdateVisual());
            RefreshJunctionWireCounts();
            SyncCountersFromIds();
            return new PendingWireSplit(hitWire, junction, first, second);
        }

        private void RevertPendingStartSplit()
        {
            if (_pendingStartSplit == null)
                return;

            var pending = _pendingStartSplit;
            _pendingStartSplit = null;

            if (pending.FirstPart.Visual != null)
                CircuitCanvas.Children.Remove(pending.FirstPart.Visual);
            if (pending.SecondPart.Visual != null)
                CircuitCanvas.Children.Remove(pending.SecondPart.Visual);

            int idx = _wires.IndexOf(pending.FirstPart);
            _wires.Remove(pending.FirstPart);
            _wires.Remove(pending.SecondPart);

            if (_elementToVisual.TryGetValue(pending.Junction, out var jVis))
            {
                CircuitCanvas.Children.Remove(jVis);
                _visualToElement.Remove(jVis);
                _elementToVisual.Remove(pending.Junction);
            }
            _elements.Remove(pending.Junction);

            if (idx >= 0 && idx <= _wires.Count)
                _wires.Insert(idx, pending.OriginalWire);
            else
                _wires.Add(pending.OriginalWire);

            CircuitCanvas.Children.Add(pending.OriginalWire.CreateOrUpdateVisual());
            RefreshJunctionWireCounts();
            SyncCountersFromIds();
            UpdateSelectionHighlight();
        }

        private void RefreshJunctionWireCounts()
        {
            foreach (var j in _elements.OfType<JunctionElement>())
            {
                var pin = j.Pins[0];
                j.AttachedWireCount = _wires.Count(w => w.StartPin == pin || w.EndPin == pin);
            }
        }

        private void CleanupJunctionsOnCanvas()
        {
            var wiresBefore = _wires.ToList();
            WireGeometry.CleanupJunctions(_elements, _wires);

            var remainingElements = new HashSet<CircuitElement>(_elements);
            var removedElements = _elementToVisual.Keys.Where(e => !remainingElements.Contains(e)).ToList();
            foreach (var el in removedElements)
            {
                if (_elementToVisual.TryGetValue(el, out var vis))
                {
                    CircuitCanvas.Children.Remove(vis);
                    _visualToElement.Remove(vis);
                    _elementToVisual.Remove(el);
                }
            }

            var remainingWires = new HashSet<Wire>(_wires);
            foreach (var oldWire in wiresBefore)
            {
                if (!remainingWires.Contains(oldWire) && oldWire.Visual != null)
                {
                    CircuitCanvas.Children.Remove(oldWire.Visual);
                }
            }

            foreach (var wire in _wires)
            {
                if (wire.Visual == null)
                {
                    CircuitCanvas.Children.Add(wire.CreateOrUpdateVisual());
                }
                else
                {
                    wire.CreateOrUpdateVisual();
                }
            }

            RefreshJunctionWireCounts();
            SyncCountersFromIds();
            UpdateSelectionHighlight();
        }

        // ═══════════════════════════════════════════════════════
        //  PIN ALGILAMA VE GÖRSEL GERİ BİLDİRİM
        // ═══════════════════════════════════════════════════════

        internal Pin? FindNearestPin(Point mousePos)
        {
            Pin? nearest = null;
            double zoom = _currentZoom > 0.01 ? _currentZoom : 1.0;
            double minDist = PinSnapThreshold / zoom;

            // Normal modda (tel çizimi başlamamışken) uç algılama alanını sınırla: uzaklaştırılmış
            // görünümde 12/zoom çok büyür ve küçük elemanların (GND, prob) tüm gövdesini kaplar;
            // o zaman eleman sürüklenemez, her basış tel başlatır.
            if (!_isWireMode && !_isPinWiring)
                minDist = Math.Min(minDist, NormalModePinRadiusCap);

            foreach (var element in _elements)
            {
                foreach (var pin in element.Pins)
                {
                    Point pinPos = pin.AbsolutePosition;
                    double dist = Math.Sqrt(
                        Math.Pow(pinPos.X - mousePos.X, 2) +
                        Math.Pow(pinPos.Y - mousePos.Y, 2));

                    if (dist < minDist)
                    {
                        minDist = dist;
                        nearest = pin;
                    }
                }
            }

            return nearest;
        }

        private void UpdatePinHighlight(Point mousePos)
        {
            if (_pinHighlight != null)
            {
                CircuitCanvas.Children.Remove(_pinHighlight);
                _pinHighlight = null;
            }

            Pin? nearest = FindNearestPin(mousePos);
            if (nearest == null) return;

            Point pinPos = nearest.AbsolutePosition;

            _pinHighlight = new Ellipse
            {
                Width = 14,
                Height = 14,
                Fill = Brushes.Transparent,
                StrokeThickness = 2,
                IsHitTestVisible = false
            };
            _pinHighlight.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Pin");

            Canvas.SetLeft(_pinHighlight, pinPos.X - 7);
            Canvas.SetTop(_pinHighlight, pinPos.Y - 7);
            CircuitCanvas.Children.Add(_pinHighlight);
        }

        private void UpdateWirePreview(Point mousePos, Point? wireSnap = null)
        {
            if (_wireStartPin == null) return;

            if (_wirePreview != null)
            {
                CircuitCanvas.Children.Remove(_wirePreview);
                _wirePreview = null;
            }

            Point start = _wireStartPin.AbsolutePosition;

            Pin? nearEnd = FindNearestPin(mousePos);
            Point end = nearEnd != null ? nearEnd.AbsolutePosition : (wireSnap ?? GridHelper.Snap(mousePos));

            _wirePreview = Wire.CreatePreviewLine(start, end);
            CircuitCanvas.Children.Add(_wirePreview);
        }

        private void RemovePreviewVisuals()
        {
            SetHoveredWire(null);
            if (_wirePreview != null)
            {
                CircuitCanvas.Children.Remove(_wirePreview);
                _wirePreview = null;
            }
            if (_pinHighlight != null)
            {
                CircuitCanvas.Children.Remove(_pinHighlight);
                _pinHighlight = null;
            }
            if (_junctionPreview != null)
            {
                CircuitCanvas.Children.Remove(_junctionPreview);
                _junctionPreview = null;
            }
        }

        private void UpdateConnectedWires(CircuitElement element)
        {
            foreach (var wire in _wires)
            {
                if (wire.StartPin.Owner == element || wire.EndPin.Owner == element)
                {
                    wire.CreateOrUpdateVisual();
                }
            }
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

        private void BtnClearCanvas_Click(object sender, RoutedEventArgs e)
        {
            if (!PromptSaveIfDirty())
                return;

            ClearCircuit();
            _problemCode = null;
            AnalysisPanel?.SetProblemCode(null);
            _currentFilePath = null;
            _isDirty = false;
            _undoHistory.Reset(CircuitDocument.Snapshot(_elements, _wires));
            UpdateTitle();
            OnCircuitChanged();
            AnalysisPanel?.ClearResults();
            TxtStatus.Text = "Canvas temizlendi";
        }

        /// <summary>Tüm elemanları, telleri ve sayaçları sıfırlar.</summary>
        private void ClearCircuit()
        {
            ExitWireMode();
            CancelPinWire();
            _isWirePressPending = false;
            _pressedWire = null;
            _hoveredWire = null;
            _isRubberBandPending = false;
            _isRubberBandActive = false;
            RemoveRubberBandVisual();
            DeselectElement();
            _overlay?.Clear();

            _elements.Clear();
            _wires.Clear();
            _visualToElement.Clear();
            _elementToVisual.Clear();
            _selectionHighlights.Clear();
            _dragInitialPositions.Clear();
            _pasteCascadeCount = 0;
            _resistorCounter = 0;
            _voltageSourceCounter = 0;
            _acSourceCounter = 0;
            _currentSourceCounter = 0;
            _acCurrentSourceCounter = 0;
            _capacitorCounter = 0;
            _inductorCounter = 0;
            _impedanceCounter = 0;
            _groundCounter = 0;
            _probeCounter = 0;
            _junctionCounter = 0;
            _pendingStartSplit = null;

            CircuitCanvas.Children.Clear();
        }

        // ═══════════════════════════════════════════════════════
        //  DOSYA (KAYDET / AÇ / YENİ) VE BAŞLIK
        // ═══════════════════════════════════════════════════════

        public void UpdateTitle()
        {
            string docName = !string.IsNullOrEmpty(_currentFilePath)
                ? System.IO.Path.GetFileNameWithoutExtension(_currentFilePath)
                : "Adsız";
            Title = $"Devre Analizi — {docName}{(_isDirty ? " •" : "")}";
        }

        private void UpdateUndoRedoButtons()
        {
            if (BtnUndo != null) BtnUndo.IsEnabled = _undoHistory.CanUndo;
            if (BtnRedo != null) BtnRedo.IsEnabled = _undoHistory.CanRedo;
        }

        public void Undo()
        {
            if (!_undoHistory.CanUndo) return;
            string? json = _undoHistory.Undo();
            if (json != null)
            {
                RestoreCircuitFromSnapshot(json);
            }
        }

        public void Redo()
        {
            if (!_undoHistory.CanRedo) return;
            string? json = _undoHistory.Redo();
            if (json != null)
            {
                RestoreCircuitFromSnapshot(json);
            }
        }

        private void RestoreCircuitFromSnapshot(string json)
        {
            var doc = CircuitDocument.FromJson(json);
            var circuit = doc.ToCircuit("Geri Yükleme");
            _isRestoringHistory = true;
            try
            {
                ClearCircuit();
                foreach (var element in circuit.Elements)
                    AddElementToCanvasCore(element);
                foreach (var wire in circuit.Wires)
                {
                    _wires.Add(wire);
                    CircuitCanvas.Children.Add(wire.CreateOrUpdateVisual());
                }
                RefreshJunctionWireCounts();
                SyncCountersFromIds();

                OnCircuitChanged();
                _isDirty = true;
                UpdateTitle();
                TxtStatus.Text = "Devre durumu geri yüklendi";
            }
            finally
            {
                _isRestoringHistory = false;
            }
        }

        public bool SaveCircuit()
        {
            if (string.IsNullOrEmpty(_currentFilePath))
                return SaveAsCircuit();
            return SaveTo(_currentFilePath);
        }

        public bool SaveAsCircuit()
        {
            string initialName = _problemCode.HasValue
                ? $"Soru-{_problemCode.Value}.devre"
                : "Devre1.devre";

            var dialog = new Microsoft.Win32.SaveFileDialog
            {
                Filter = CircuitDocument.FileFilter,
                DefaultExt = CircuitDocument.FileExtension,
                FileName = initialName,
            };

            if (dialog.ShowDialog(this) == true)
            {
                return SaveTo(dialog.FileName);
            }
            return false;
        }

        private bool SaveTo(string path)
        {
            try
            {
                var doc = CircuitDocument.FromCircuit(_elements, _wires);
                doc.Analysis = AnalysisPanel.GetAnalysisSettings();
                doc.ProblemCode = _problemCode;
                doc.Save(path);

                _currentFilePath = path;
                _isDirty = false;
                AppSettings.AddRecentFile(path);
                UpdateTitle();
                TxtStatus.Text = $"Kaydedildi: {System.IO.Path.GetFileName(path)}";
                return true;
            }
            catch (CircuitFileException ex)
            {
                MessageBox.Show(this, ex.Message, "Kaydetme Hatası", MessageBoxButton.OK, MessageBoxImage.Error);
                return false;
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, $"Dosya kaydedilemedi: {ex.Message}", "Kaydetme Hatası", MessageBoxButton.OK, MessageBoxImage.Error);
                return false;
            }
        }

        public bool OpenFile(string path, bool isSelfTest = false)
        {
            if (!System.IO.File.Exists(path))
            {
                if (!isSelfTest && !HasAnySelfTest(Environment.GetCommandLineArgs()))
                    MessageBox.Show(this, $"Dosya bulunamadı:\n{path}", "Dosya Açılamadı", MessageBoxButton.OK, MessageBoxImage.Warning);
                AppSettings.RemoveRecentFile(path);
                return false;
            }

            try
            {
                var doc = CircuitDocument.Load(path);
                string fileName = System.IO.Path.GetFileNameWithoutExtension(path);
                var circuit = doc.ToCircuit(fileName);

                LoadExample(circuit);
                AnalysisPanel.RestoreAnalysisSettings(doc.Analysis);
                if (doc.ProblemCode != null)
                {
                    _problemCode = doc.ProblemCode;
                    AnalysisPanel.IsPracticeMode = true;
                    AnalysisPanel.SetProblemCode(doc.ProblemCode);
                }
                else
                {
                    _problemCode = null;
                    AnalysisPanel.SetProblemCode(null);
                }

                _currentFilePath = path;
                _isDirty = false;
                _undoHistory.Reset(CircuitDocument.Snapshot(_elements, _wires));
                AppSettings.AddRecentFile(path);
                UpdateTitle();
                AutoFitOrScrollCircuit();
                TxtStatus.Text = $"Açıldı: {System.IO.Path.GetFileName(path)}";
                return true;
            }
            catch (CircuitFileException ex)
            {
                if (!isSelfTest && !HasAnySelfTest(Environment.GetCommandLineArgs()))
                    MessageBox.Show(this, ex.Message, "Dosya Açılamadı", MessageBoxButton.OK, MessageBoxImage.Error);
                return false;
            }
            catch (Exception ex)
            {
                if (!isSelfTest && !HasAnySelfTest(Environment.GetCommandLineArgs()))
                    MessageBox.Show(this, $"Dosya okunamadı: {ex.Message}", "Dosya Açılamadı", MessageBoxButton.OK, MessageBoxImage.Error);
                return false;
            }
        }

        private void PromptAndOpenFileDialog()
        {
            if (!PromptSaveIfDirty()) return;

            var dialog = new Microsoft.Win32.OpenFileDialog
            {
                Filter = CircuitDocument.FileFilter,
                DefaultExt = CircuitDocument.FileExtension,
            };

            if (dialog.ShowDialog(this) == true)
            {
                OpenFile(dialog.FileName);
            }
        }

        public void NewCircuit()
        {
            if (!PromptSaveIfDirty())
                return;

            ClearCircuit();
            _problemCode = null;
            AnalysisPanel.SetProblemCode(null);
            _currentFilePath = null;
            _isDirty = false;
            _undoHistory.Reset(CircuitDocument.Snapshot(_elements, _wires));
            UpdateTitle();
            AnalysisPanel.ClearResults();
            AutoFitOrScrollCircuit();
            TxtStatus.Text = "Yeni devre oluşturuldu";
        }

        public bool PromptSaveIfDirty()
        {
            if (!_isDirty || HasAnySelfTest(Environment.GetCommandLineArgs()))
                return true;

            var result = MessageBox.Show(
                this,
                "Değişiklikleri kaydetmek istiyor musunuz?",
                "Devre Analizi",
                MessageBoxButton.YesNoCancel,
                MessageBoxImage.Question);

            if (result == MessageBoxResult.Yes)
            {
                return SaveCircuit();
            }
            else if (result == MessageBoxResult.No)
            {
                return true;
            }
            else
            {
                return false;
            }
        }

        protected override void OnClosing(System.ComponentModel.CancelEventArgs e)
        {
            if (!PromptSaveIfDirty())
            {
                e.Cancel = true;
                return;
            }
            base.OnClosing(e);
        }

        private void BtnOpen_Click(object sender, RoutedEventArgs e)
        {
            var menu = new ContextMenu
            {
                PlacementTarget = BtnOpen,
                Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom,
            };

            var chooseItem = new MenuItem
            {
                Header = "Dosya seç…",
                InputGestureText = "Ctrl+O",
            };
            chooseItem.Click += (_, _) => PromptAndOpenFileDialog();
            menu.Items.Add(chooseItem);

            var recent = AppSettings.RecentFiles;
            if (recent.Count > 0)
            {
                menu.Items.Add(new Separator());
                foreach (var file in recent)
                {
                    string filePath = file;
                    var item = new MenuItem
                    {
                        Header = System.IO.Path.GetFileName(filePath),
                        ToolTip = filePath,
                    };
                    item.Click += (_, _) =>
                    {
                        if (!System.IO.File.Exists(filePath))
                        {
                            MessageBox.Show(this, $"Dosya bulunamadı:\n{filePath}", "Dosya Yok", MessageBoxButton.OK, MessageBoxImage.Warning);
                            AppSettings.RemoveRecentFile(filePath);
                            return;
                        }
                        if (!PromptSaveIfDirty()) return;
                        OpenFile(filePath);
                    };
                    menu.Items.Add(item);
                }
            }

            menu.IsOpen = true;
        }

        private void BtnSave_Click(object sender, RoutedEventArgs e)
        {
            SaveCircuit();
        }

        private void BtnPrint_Click(object sender, RoutedEventArgs e)
        {
            PrintOrExportPdf();
        }

        public void PrintOrExportPdf(bool isSelfTest = false)
        {
            if (_lastResponse == null || _lastSolveVersion != _circuitVersion)
            {
                MessageBox.Show(this, "Önce devreyi çözün.", "Yazdır / PDF", MessageBoxButton.OK, MessageBoxImage.Information);
                return;
            }

            bool isPractice = AnalysisPanel.IsShowingPractice;
            var circuitBmp = RenderCircuitBitmap();

            string title = !string.IsNullOrEmpty(_currentFilePath)
                ? System.IO.Path.GetFileName(_currentFilePath)
                : (_problemCode.HasValue ? $"Soru #{_problemCode.Value}" : "Devre Analizi");

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
                IsPracticeMode = isPractice,
                PracticeQuestions = _lastResponse.Results?.Practice
            };

            var doc = SolutionPrinter.BuildDocument(input);

            if (isSelfTest) return;

            var dialog = new PrintDialog();
            TxtStatus.Text = "PDF için yazıcı olarak “Microsoft Print to PDF”i seçin";
            if (dialog.ShowDialog() == true)
            {
                var paginator = ((System.Windows.Documents.IDocumentPaginatorSource)doc).DocumentPaginator;
                dialog.PrintDocument(paginator, "Devre Analizi — PDF için yazıcı olarak “Microsoft Print to PDF”i seçin");
                TxtStatus.Text = "Belge yazıcıya gönderildi";
            }
        }

        public RenderTargetBitmap? RenderCircuitBitmap()
        {
            if (_elements.Count == 0 && _wires.Count == 0)
                return null;

            double minX = double.MaxValue, minY = double.MaxValue;
            double maxX = double.MinValue, maxY = double.MinValue;

            foreach (var el in _elements)
            {
                minX = Math.Min(minX, el.Position.X);
                minY = Math.Min(minY, el.Position.Y);
                maxX = Math.Max(maxX, el.Position.X + 80);
                maxY = Math.Max(maxY, el.Position.Y + 40);
            }
            foreach (var wire in _wires)
            {
                minX = Math.Min(minX, Math.Min(wire.StartPin.AbsolutePosition.X, wire.EndPin.AbsolutePosition.X));
                minY = Math.Min(minY, Math.Min(wire.StartPin.AbsolutePosition.Y, wire.EndPin.AbsolutePosition.Y));
                maxX = Math.Max(maxX, Math.Max(wire.StartPin.AbsolutePosition.X, wire.EndPin.AbsolutePosition.X));
                maxY = Math.Max(maxY, Math.Max(wire.StartPin.AbsolutePosition.Y, wire.EndPin.AbsolutePosition.Y));
            }

            double margin = 30.0;
            minX = Math.Max(0, minX - margin);
            minY = Math.Max(0, minY - margin);
            maxX += margin;
            maxY += margin;

            double w = Math.Max(50, maxX - minX);
            double h = Math.Max(50, maxY - minY);

            var prevChoice = ThemeManager.Choice;
            double oldZoom = _currentZoom;

            try
            {
                if (ThemeManager.IsDark)
                {
                    ThemeManager.SetChoice(ThemeChoice.Light);
                }
                SetZoom(1.0);
                CircuitCanvas.UpdateLayout();

                int bmpW = (int)Math.Ceiling(w * 2.0);
                int bmpH = (int)Math.Ceiling(h * 2.0);
                var rtb = new RenderTargetBitmap(bmpW, bmpH, 96 * 2.0, 96 * 2.0, PixelFormats.Pbgra32);
                var visual = new DrawingVisual();
                using (var dc = visual.RenderOpen())
                {
                    var bgBrush = (Brush)Application.Current.FindResource("Brush.Bg.Surface");
                    dc.DrawRectangle(bgBrush, null, new Rect(0, 0, w, h));
                    var vb = new VisualBrush(CircuitCanvas)
                    {
                        Viewbox = new Rect(minX, minY, w, h),
                        ViewboxUnits = BrushMappingMode.Absolute
                    };
                    dc.DrawRectangle(vb, null, new Rect(0, 0, w, h));
                }
                rtb.Render(visual);
                return rtb;
            }
            catch
            {
                return null;
            }
            finally
            {
                SetZoom(oldZoom);
                if (ThemeManager.Choice != prevChoice)
                {
                    ThemeManager.SetChoice(prevChoice);
                }
            }
        }

        // ═══════════════════════════════════════════════════════
        //  YAKINLAŞTIRMA (ZOOM) VE KAYDIRMA (PAN)
        // ═══════════════════════════════════════════════════════

        public void SetZoom(double zoom, Point? mouseInViewport = null)
        {
            double clamped = ZoomMath.ClampZoom(zoom);
            double oldZoom = _currentZoom;
            if (Math.Abs(oldZoom - clamped) < 0.0001 && mouseInViewport == null)
                return;

            _currentZoom = clamped;
            CanvasScaleTransform.ScaleX = clamped;
            CanvasScaleTransform.ScaleY = clamped;

            if (mouseInViewport.HasValue)
            {
                var (newH, newV) = ZoomMath.ComputeZoomOffsets(
                    oldZoom,
                    clamped,
                    mouseInViewport.Value.X,
                    mouseInViewport.Value.Y,
                    CanvasScrollViewer.HorizontalOffset,
                    CanvasScrollViewer.VerticalOffset);
                CanvasScrollViewer.UpdateLayout();
                CanvasScrollViewer.ScrollToHorizontalOffset(newH);
                CanvasScrollViewer.ScrollToVerticalOffset(newV);
            }
            else
            {
                CanvasScrollViewer.UpdateLayout();
            }
            UpdateZoomDisplay();
        }

        public void ZoomIn()
        {
            double vw = CanvasScrollViewer.ViewportWidth > 0 ? CanvasScrollViewer.ViewportWidth : CanvasScrollViewer.ActualWidth;
            double vh = CanvasScrollViewer.ViewportHeight > 0 ? CanvasScrollViewer.ViewportHeight : CanvasScrollViewer.ActualHeight;
            SetZoom(ZoomMath.ZoomIn(_currentZoom), new Point(vw / 2.0, vh / 2.0));
        }

        public void ZoomOut()
        {
            double vw = CanvasScrollViewer.ViewportWidth > 0 ? CanvasScrollViewer.ViewportWidth : CanvasScrollViewer.ActualWidth;
            double vh = CanvasScrollViewer.ViewportHeight > 0 ? CanvasScrollViewer.ViewportHeight : CanvasScrollViewer.ActualHeight;
            SetZoom(ZoomMath.ZoomOut(_currentZoom), new Point(vw / 2.0, vh / 2.0));
        }

        public void ResetZoom()
        {
            double vw = CanvasScrollViewer.ViewportWidth > 0 ? CanvasScrollViewer.ViewportWidth : CanvasScrollViewer.ActualWidth;
            double vh = CanvasScrollViewer.ViewportHeight > 0 ? CanvasScrollViewer.ViewportHeight : CanvasScrollViewer.ActualHeight;
            SetZoom(1.0, new Point(vw / 2.0, vh / 2.0));
        }

        private void UpdateZoomDisplay()
        {
            if (TxtZoomPercent != null)
            {
                TxtZoomPercent.Text = $"{Math.Round(_currentZoom * 100)}%";
            }
        }

        public void FitToCircuit()
        {
            if (_elements.Count == 0)
            {
                SetZoom(1.0);
                CanvasScrollViewer.ScrollToHorizontalOffset(0);
                CanvasScrollViewer.ScrollToVerticalOffset(0);
                return;
            }

            double minX = double.MaxValue, minY = double.MaxValue;
            double maxX = double.MinValue, maxY = double.MinValue;

            foreach (var e in _elements)
            {
                minX = Math.Min(minX, e.Position.X);
                minY = Math.Min(minY, e.Position.Y);
                maxX = Math.Max(maxX, e.Position.X + 80);
                maxY = Math.Max(maxY, e.Position.Y + 40);
            }

            foreach (var w in _wires)
            {
                minX = Math.Min(minX, Math.Min(w.StartPin.AbsolutePosition.X, w.EndPin.AbsolutePosition.X));
                minY = Math.Min(minY, Math.Min(w.StartPin.AbsolutePosition.Y, w.EndPin.AbsolutePosition.Y));
                maxX = Math.Max(maxX, Math.Max(w.StartPin.AbsolutePosition.X, w.EndPin.AbsolutePosition.X));
                maxY = Math.Max(maxY, Math.Max(w.StartPin.AbsolutePosition.Y, w.EndPin.AbsolutePosition.Y));
            }

            double vw = CanvasScrollViewer.ViewportWidth > 0 ? CanvasScrollViewer.ViewportWidth : CanvasScrollViewer.ActualWidth;
            double vh = CanvasScrollViewer.ViewportHeight > 0 ? CanvasScrollViewer.ViewportHeight : CanvasScrollViewer.ActualHeight;
            if (vw <= 0) vw = 800;
            if (vh <= 0) vh = 600;

            var (fitZoom, hOff, vOff) = ZoomMath.ComputeFit(minX, minY, maxX, maxY, vw, vh);
            _currentZoom = fitZoom;
            CanvasScaleTransform.ScaleX = fitZoom;
            CanvasScaleTransform.ScaleY = fitZoom;
            CanvasScrollViewer.UpdateLayout();
            CanvasScrollViewer.ScrollToHorizontalOffset(hOff);
            CanvasScrollViewer.ScrollToVerticalOffset(vOff);
            UpdateZoomDisplay();
        }

        public void AutoFitOrScrollCircuit()
        {
            if (_elements.Count == 0)
            {
                SetZoom(1.0);
                CanvasScrollViewer.ScrollToHorizontalOffset(0);
                CanvasScrollViewer.ScrollToVerticalOffset(0);
                return;
            }

            double minX = double.MaxValue, minY = double.MaxValue;
            double maxX = double.MinValue, maxY = double.MinValue;

            foreach (var e in _elements)
            {
                minX = Math.Min(minX, e.Position.X);
                minY = Math.Min(minY, e.Position.Y);
                maxX = Math.Max(maxX, e.Position.X + 80);
                maxY = Math.Max(maxY, e.Position.Y + 40);
            }

            foreach (var w in _wires)
            {
                minX = Math.Min(minX, Math.Min(w.StartPin.AbsolutePosition.X, w.EndPin.AbsolutePosition.X));
                minY = Math.Min(minY, Math.Min(w.StartPin.AbsolutePosition.Y, w.EndPin.AbsolutePosition.Y));
                maxX = Math.Max(maxX, Math.Max(w.StartPin.AbsolutePosition.X, w.EndPin.AbsolutePosition.X));
                maxY = Math.Max(maxY, Math.Max(w.StartPin.AbsolutePosition.Y, w.EndPin.AbsolutePosition.Y));
            }

            double vw = CanvasScrollViewer.ViewportWidth > 0 ? CanvasScrollViewer.ViewportWidth : CanvasScrollViewer.ActualWidth;
            double vh = CanvasScrollViewer.ViewportHeight > 0 ? CanvasScrollViewer.ViewportHeight : CanvasScrollViewer.ActualHeight;
            if (vw <= 0) vw = 800;
            if (vh <= 0) vh = 600;

            if (ZoomMath.NeedsFitAt100(minX, minY, maxX, maxY, vw, vh))
            {
                var (fitZoom, hOff, vOff) = ZoomMath.ComputeFit(minX, minY, maxX, maxY, vw, vh);
                _currentZoom = fitZoom;
                CanvasScaleTransform.ScaleX = fitZoom;
                CanvasScaleTransform.ScaleY = fitZoom;
                CanvasScrollViewer.UpdateLayout();
                CanvasScrollViewer.ScrollToHorizontalOffset(hOff);
                CanvasScrollViewer.ScrollToVerticalOffset(vOff);
                UpdateZoomDisplay();
            }
            else
            {
                _currentZoom = 1.0;
                CanvasScaleTransform.ScaleX = 1.0;
                CanvasScaleTransform.ScaleY = 1.0;
                var (hOff, vOff) = ZoomMath.ComputeScrollToCenter(minX, minY, maxX, maxY, 1.0, vw, vh);
                CanvasScrollViewer.UpdateLayout();
                CanvasScrollViewer.ScrollToHorizontalOffset(hOff);
                CanvasScrollViewer.ScrollToVerticalOffset(vOff);
                UpdateZoomDisplay();
            }
        }

        private void CanvasScrollViewer_PreviewMouseWheel(object sender, MouseWheelEventArgs e)
        {
            if (Keyboard.Modifiers.HasFlag(ModifierKeys.Control))
            {
                e.Handled = true;
                double factor = e.Delta > 0 ? 1.2 : (1.0 / 1.2);
                Point mousePos = e.GetPosition(CanvasScrollViewer);
                SetZoom(_currentZoom * factor, mousePos);
            }
        }

        private void CanvasScrollViewer_PreviewMouseDown(object sender, MouseButtonEventArgs e)
        {
            bool isMiddle = e.ChangedButton == MouseButton.Middle;
            bool isSpaceLeft = e.ChangedButton == MouseButton.Left && Keyboard.IsKeyDown(Key.Space);

            if (isMiddle || isSpaceLeft)
            {
                _isPanning = true;
                _panStartMouse = e.GetPosition(CanvasScrollViewer);
                _panStartH = CanvasScrollViewer.HorizontalOffset;
                _panStartV = CanvasScrollViewer.VerticalOffset;
                Mouse.Capture(CanvasScrollViewer);
                Mouse.OverrideCursor = isMiddle ? Cursors.ScrollAll : Cursors.Hand;
                e.Handled = true;
            }
        }

        private void CanvasScrollViewer_MouseMove(object sender, MouseEventArgs e)
        {
            if (_isPanning)
            {
                Point current = e.GetPosition(CanvasScrollViewer);
                double dx = current.X - _panStartMouse.X;
                double dy = current.Y - _panStartMouse.Y;
                CanvasScrollViewer.ScrollToHorizontalOffset(_panStartH - dx);
                CanvasScrollViewer.ScrollToVerticalOffset(_panStartV - dy);
                e.Handled = true;
            }
        }

        private void CanvasScrollViewer_MouseUp(object sender, MouseButtonEventArgs e)
        {
            if (_isPanning)
            {
                _isPanning = false;
                Mouse.Capture(null);
                Mouse.OverrideCursor = null;
                e.Handled = true;
            }
        }

        private void BtnUndo_Click(object sender, RoutedEventArgs e) => Undo();
        private void BtnRedo_Click(object sender, RoutedEventArgs e) => Redo();
        private void BtnZoomOut_Click(object sender, RoutedEventArgs e) => ZoomOut();
        private void BtnZoomIn_Click(object sender, RoutedEventArgs e) => ZoomIn();
        private void BtnZoomFit_Click(object sender, RoutedEventArgs e) => FitToCircuit();
        private void TxtZoomPercent_MouseLeftButtonDown(object sender, MouseButtonEventArgs e) => ResetZoom();
    }
}
