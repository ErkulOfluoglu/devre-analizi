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

        // ── Sürükleme (Drag) durumu ──
        private bool _isDragging = false;
        private CircuitElement? _draggedElement = null;
        private UIElement? _draggedVisual = null;
        private Point _dragOffset;
        private Point _dragStartPosition;

        // ── Seçim durumu ('R' tuşu ile döndürme için) ──
        private CircuitElement? _selectedElement = null;
        private UIElement? _selectedVisual = null;

        // ── Tel çizim durumu ──
        private bool _isWireMode = false;
        private Pin? _wireStartPin = null;
        private Polyline? _wirePreview = null;
        private Ellipse? _pinHighlight = null;

        // ── UIElement → CircuitElement eşleştirmesi ──
        private readonly Dictionary<UIElement, CircuitElement> _visualToElement = new();

        // ── Pin algılama eşiği (piksel) ──
        private const double PinSnapThreshold = 12.0;

        // ── Seçim vurgu kutusu ──
        private Rectangle? _selectionHighlight = null;

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
            InitializeComponent();
            ThemeManager.ApplyTitleBar(this);
            ThemeManager.ThemeChanged += (_, _) => Dispatcher.Invoke(UpdateThemeButton);
            _undoHistory.Changed += (_, _) => Dispatcher.Invoke(UpdateUndoRedoButtons);
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
                ("R", "Seçili elemanı döndür"),
                ("Delete", "Seçili elemanı sil"),
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
        /// Bir CircuitElement'i Canvas'a ekler.
        /// 
        /// ★ YENİ: Sağ-tık bağlam menüsü ve çift-tık desteği eklendi.
        /// Her elemana otomatik olarak:
        ///   - Sürükleme (MouseLeftButtonDown)
        ///   - Çift tıklama → Değer düzenleme diyaloğu
        ///   - Sağ tıklama → Bağlam menüsü (Döndür / Düzenle / Sil)
        /// bağlanır.
        /// </summary>
        private void AddElementToCanvas(CircuitElement element)
        {
            _elements.Add(element);
            UIElement visual = element.CreateVisual();

            Canvas.SetLeft(visual, element.Position.X);
            Canvas.SetTop(visual, element.Position.Y);

            // Dönüş varsa uygula (Clear sonrası veya gelecekte dosyadan yükleme)
            if (element.Rotation != 0)
            {
                ApplyRotationTransform(visual, element.Rotation);
            }

            // Olay bağlantıları
            visual.MouseLeftButtonDown += Element_MouseLeftButtonDown;

            // ★ Sağ-tık bağlam menüsü (Context Menu)
            if (visual is FrameworkElement fe)
            {
                fe.ContextMenu = CreateElementContextMenu(element, visual);
            }

            _visualToElement[visual] = element;
            CircuitCanvas.Children.Add(visual);

            OnCircuitChanged();
        }

        /// <summary>
        /// Bir eleman için sağ-tık bağlam menüsü oluşturur.
        /// 
        /// Menü yapısı:
        ///   90° Döndür (R)
        ///   Değer düzenle
        ///   ──────────────
        ///   Sil
        /// </summary>
        private ContextMenu CreateElementContextMenu(CircuitElement element, UIElement visual)
        {
            var menu = new ContextMenu();

            // Döndür
            var rotateItem = new MenuItem
            {
                Header = "90° Döndür (R)"
            };
            rotateItem.Click += (s, args) => RotateElement(element, visual);
            menu.Items.Add(rotateItem);

            // Düzenle
            var editItem = new MenuItem
            {
                Header = "Değer düzenle"
            };
            editItem.Click += (s, args) => EditElement(element, visual);
            menu.Items.Add(editItem);

            menu.Items.Add(new Separator());

            // Sil
            var deleteItem = new MenuItem
            {
                Header = "Sil"
            };
            deleteItem.Click += (s, args) => DeleteElement(element, visual);
            menu.Items.Add(deleteItem);

            return menu;
        }

        // ═══════════════════════════════════════════════════════
        //  SÜRÜKLEME (DRAG & DROP + SNAP-TO-GRID)
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Bir eleman üzerinde fare sol tuşu basıldığında:
        /// - Tel modundaysa → HandleWireClick
        /// - Çift tıksa → Değer düzenleme diyaloğu
        /// - Tek tıksa → Sürükleme başlat + elemanı seç
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

            if (sender is UIElement visual && _visualToElement.ContainsKey(visual))
            {
                var element = _visualToElement[visual];

                // ── Çift tık → Değer düzenleme ──
                if (e.ClickCount == 2)
                {
                    EditElement(element, visual);
                    e.Handled = true;
                    return;
                }

                // ── Tek tık → Seç + sürükleme başlat ──
                SelectElement(element, visual);

                _isDragging = true;
                _draggedVisual = visual;
                _draggedElement = element;
                _dragStartPosition = element.Position;

                double elementX = Canvas.GetLeft(visual);
                double elementY = Canvas.GetTop(visual);
                _dragOffset = new Point(mousePos.X - elementX, mousePos.Y - elementY);

                visual.CaptureMouse();
                e.Handled = true;

                TxtStatus.Text = $"{element.Id} sürükleniyor... (R: döndür)";
            }
        }

        /// <summary>
        /// Canvas üzerinde fare hareket ettiğinde:
        /// - Tel modundaysa → pin vurgusu ve önizleme
        /// - Sürükleme aktifse → elemanı taşı + bağlı telleri güncelle
        /// </summary>
        private void CircuitCanvas_MouseMove(object sender, MouseEventArgs e)
        {
            Point mousePos = e.GetPosition(CircuitCanvas);

            Point snappedPos = GridHelper.Snap(mousePos);
            TxtCoords.Text = $"X: {snappedPos.X:F0}  Y: {snappedPos.Y:F0}";

            if (_isWireMode)
            {
                UpdatePinHighlight(mousePos);
                UpdateWirePreview(mousePos);
                return;
            }

            if (!_isDragging || _draggedVisual == null || _draggedElement == null)
                return;

            double newX = GridHelper.Snap(mousePos.X - _dragOffset.X);
            double newY = GridHelper.Snap(mousePos.Y - _dragOffset.Y);

            newX = Math.Max(0, Math.Min(newX, CircuitCanvas.ActualWidth - _draggedElement.VisualWidth));
            newY = Math.Max(0, Math.Min(newY, CircuitCanvas.ActualHeight - _draggedElement.VisualHeight));

            Canvas.SetLeft(_draggedVisual, newX);
            Canvas.SetTop(_draggedVisual, newY);

            // Taşıma başladı — eski konumdaki sonuç etiketleri yanıltmasın
            if (_draggedElement.Position != new Point(newX, newY))
                _overlay?.Clear();
            _draggedElement.Position = new Point(newX, newY);

            UpdateConnectedWires(_draggedElement);
            UpdateSelectionHighlight();
        }

        private void CircuitCanvas_MouseLeftButtonUp(object sender, MouseButtonEventArgs e)
        {
            if (_isDragging && _draggedVisual != null && _draggedElement != null)
            {
                _draggedVisual.ReleaseMouseCapture();
                bool moved = _draggedElement.Position != _dragStartPosition;

                TxtStatus.Text = $"{_draggedElement.Id} → Konum: " +
                    $"({_draggedElement.Position.X:F0}, {_draggedElement.Position.Y:F0})";

                _isDragging = false;
                _draggedVisual = null;
                _draggedElement = null;

                if (moved)
                    OnCircuitChanged();
            }
        }

        private void CircuitCanvas_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
        {
            Point pos = e.GetPosition(CircuitCanvas);

            if (_isWireMode)
            {
                HandleWireClick(pos);
                return;
            }

            // Boş alana tıklandığında seçimi kaldır
            DeselectElement();
            Point snapped = GridHelper.Snap(pos);
            TxtCoords.Text = $"Tıklama: ({snapped.X:F0}, {snapped.Y:F0})";
        }

        // ═══════════════════════════════════════════════════════
        //  SEÇİM MEKANİZMASI
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Bir elemanı "seçili" olarak işaretler.
        /// Seçili eleman 'R' tuşu ile döndürülebilir.
        /// </summary>
        private void SelectElement(CircuitElement element, UIElement visual)
        {
            // Önceki seçimi kaldır
            DeselectElement();

            _selectedElement = element;
            _selectedVisual = visual;

            // Seçili elemanın etrafına vurgu kutusu
            _selectionHighlight = new Rectangle
            {
                IsHitTestVisible = false,
                StrokeThickness = 2,
                RadiusX = 4,
                RadiusY = 4
            };
            _selectionHighlight.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Selection");
            _selectionHighlight.SetResourceReference(Shape.FillProperty, "Brush.Circuit.SelectionFill");
            CircuitCanvas.Children.Add(_selectionHighlight);
            UpdateSelectionHighlight();
        }

        /// <summary>Seçimi kaldırır ve vurgu kutusunu temizler.</summary>
        private void DeselectElement()
        {
            if (_selectionHighlight != null)
            {
                CircuitCanvas.Children.Remove(_selectionHighlight);
                _selectionHighlight = null;
            }
            _selectedElement = null;
            _selectedVisual = null;
        }

        private void UpdateSelectionHighlight()
        {
            if (_selectionHighlight == null || _selectedElement == null) return;

            double pad = 4;
            double w = _selectedElement.VisualWidth + pad * 2;
            double h = _selectedElement.VisualHeight + pad * 2;

            _selectionHighlight.Width = w;
            _selectionHighlight.Height = h;
            Canvas.SetLeft(_selectionHighlight, _selectedElement.Position.X - pad);
            Canvas.SetTop(_selectionHighlight, _selectedElement.Position.Y - pad);

            if (_selectedElement.Rotation != 0)
            {
                _selectionHighlight.RenderTransformOrigin = new Point(0.5, 0.5);
                _selectionHighlight.RenderTransform = new RotateTransform(_selectedElement.Rotation);
            }
            else
            {
                _selectionHighlight.RenderTransform = null;
            }
        }

        // ═══════════════════════════════════════════════════════
        //  DÖNDÜRME (ROTATION)
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Elemanı 90° saat yönünde döndürür.
        /// 
        /// Döndürme mekanizması iki katmanlıdır:
        /// 
        /// 1. GÖRSEL KATMAN:
        ///    RenderTransform ile elemanın Canvas üzerindeki çizimi döner.
        ///    RenderTransformOrigin = (0.5, 0.5) → merkez etrafında döner.
        ///    
        /// 2. ELEKTRİKSEL KATMAN:
        ///    Pin.AbsolutePosition, elemanın Rotation değerine göre
        ///    2D döndürme matrisi uygulayarak yeni pin konumlarını hesaplar.
        ///    Böylece teller doğru noktaya bağlı kalır.
        /// 
        /// İki katman senkronize çalışır:
        ///   RotateElement() → element.Rotation += 90°
        ///                   → visual.RenderTransform güncelle
        ///                   → UpdateConnectedWires() → Pin.AbsolutePosition
        ///                     yeni açıyla otomatik hesaplanır
        /// </summary>
        private void RotateElement(CircuitElement element, UIElement visual)
        {
            // Dönüş açısını 90° artır (0 → 90 → 180 → 270 → 0 ...)
            element.Rotation = (element.Rotation + 90) % 360;

            // Görsele döndürme dönüşümü uygula
            ApplyRotationTransform(visual, element.Rotation);

            // Bağlı telleri güncelle (pin pozisyonları değişti)
            UpdateConnectedWires(element);
            UpdateSelectionHighlight();
            OnCircuitChanged();

            TxtStatus.Text = $"{element.Id} → {element.Rotation}° döndürüldü";
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
        /// Kullanıcı değerleri değiştirip "Uygula" dediğinde:
        ///   1. Elemanın özellikleri güncellenir
        ///   2. Görsel yeniden çizilir (etiketler yeni değerleri gösterir)
        ///   3. Bağlı teller korunur
        /// </summary>
        private void EditElement(CircuitElement element, UIElement visual)
        {
            var editor = new ElementEditorWindow(element);
            editor.Owner = this;

            if (editor.ShowDialog() == true)
            {
                // ★ Görseli yeniden oluştur — etiketler değişti
                RefreshElementVisual(element, visual);
                OnCircuitChanged();
                TxtStatus.Text = $"{element.Id} güncellendi";
            }
        }

        /// <summary>
        /// Bir elemanın görselini yeniden oluşturur.
        /// 
        /// Neden tam yeniden çizim?
        /// Eleman etiketi (ör: "10µF" → "47µF") görsel Canvas'ın içindeki
        /// TextBlock'ta yazılıdır. Bunu doğrudan güncellemek yerine,
        /// tüm görseli yeniden oluşturmak daha güvenilirdir çünkü:
        ///   - TextBlock referanslarını ayrıca tutmak gereksiz karmaşıklık
        ///   - CreateVisual() zaten saf fonksiyon — her çağrıda temiz sonuç
        ///   - Rotation transform otomatik tekrar uygulanır
        /// </summary>
        private void RefreshElementVisual(CircuitElement element, UIElement oldVisual)
        {
            // Eski görseli kaldır
            CircuitCanvas.Children.Remove(oldVisual);
            _visualToElement.Remove(oldVisual);

            // Yeni görsel oluştur
            UIElement newVisual = element.CreateVisual();

            Canvas.SetLeft(newVisual, element.Position.X);
            Canvas.SetTop(newVisual, element.Position.Y);

            // Dönüş varsa uygula
            if (element.Rotation != 0)
            {
                ApplyRotationTransform(newVisual, element.Rotation);
            }

            // Olayları bağla
            newVisual.MouseLeftButtonDown += Element_MouseLeftButtonDown;
            if (newVisual is FrameworkElement fe)
            {
                fe.ContextMenu = CreateElementContextMenu(element, newVisual);
            }

            _visualToElement[newVisual] = element;
            CircuitCanvas.Children.Add(newVisual);

            // Seçimi yeni görsele taşı
            if (_selectedElement == element)
            {
                _selectedVisual = newVisual;
                SelectElement(element, newVisual);
            }
        }

        // ═══════════════════════════════════════════════════════
        //  ELEMAN SİLME
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Elemanı ve bağlı tüm tellerini Canvas'tan siler.
        /// </summary>
        private void DeleteElement(CircuitElement element, UIElement visual)
        {
            // Seçimi temizle
            if (_selectedElement == element)
                DeselectElement();

            // Bağlı telleri bul ve kaldır
            var connectedWires = _wires
                .Where(w => w.StartPin.Owner == element || w.EndPin.Owner == element)
                .ToList();

            foreach (var wire in connectedWires)
            {
                if (wire.Visual != null)
                    CircuitCanvas.Children.Remove(wire.Visual);
                _wires.Remove(wire);
            }

            // Görseli kaldır
            CircuitCanvas.Children.Remove(visual);
            _visualToElement.Remove(visual);
            _elements.Remove(element);
            OnCircuitChanged();

            TxtStatus.Text = $"{element.Id} silindi ({connectedWires.Count} tel de kaldırıldı)";
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
            _isWireMode = false;
            _wireStartPin = null;
            CircuitCanvas.Cursor = Cursors.Arrow;

            BtnDrawWire.ClearValue(BackgroundProperty);
            BtnDrawWire.ClearValue(ForegroundProperty);
            TxtDrawWire.Text = "Tel çiz";

            RemovePreviewVisuals();

            TxtStatus.Text = "Hazır — Araç kutusundan bir eleman seçin";
        }

        /// <summary>
        /// Klavye kısayolları:
        ///   F5 → Çöz
        ///   Ctrl+O → Aç, Ctrl+S → Kaydet, Ctrl+Shift+S → Farklı Kaydet, Ctrl+N → Yeni
        ///   Ctrl+Z → Geri Al, Ctrl+Y / Ctrl+Shift+Z → Yinele
        ///   Ctrl+0 → %100, Ctrl++ / Ctrl+- → Yakınlaştır / Uzaklaştır
        ///   Delete → Seçili elemanı sil
        ///   Escape → Tel modunu iptal et
        ///   R → Seçili elemanı 90° döndür
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

            // ── Escape: Tel iptal ──
            if (e.Key == Key.Escape && _isWireMode)
            {
                if (_wireStartPin != null)
                {
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

            // ── Delete: Seçili elemanı sil ──
            if (e.Key == Key.Delete && !_isWireMode &&
                _selectedElement != null && _selectedVisual != null)
            {
                DeleteElement(_selectedElement, _selectedVisual);
                e.Handled = true;
                return;
            }

            // ── R: Seçili elemanı döndür ──
            if (e.Key == Key.R && !_isWireMode &&
                _selectedElement != null && _selectedVisual != null)
            {
                RotateElement(_selectedElement, _selectedVisual);
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

            CompleteWire(_wireStartPin, nearestPin);
        }

        private void CompleteWire(Pin startPin, Pin endPin)
        {
            var wire = new Wire(startPin, endPin);
            _wires.Add(wire);

            var visual = wire.CreateOrUpdateVisual();
            CircuitCanvas.Children.Add(visual);

            RemovePreviewVisuals();
            _wireStartPin = null;
            OnCircuitChanged();

            TxtStatus.Text = $"Tel oluşturuldu: {startPin.Owner?.Id}.{startPin.Id} → " +
                $"{endPin.Owner?.Id}.{endPin.Id} — Yeni tel çizebilirsiniz (Esc: çık)";
        }

        // ═══════════════════════════════════════════════════════
        //  PIN ALGILAMA VE GÖRSEL GERİ BİLDİRİM
        // ═══════════════════════════════════════════════════════

        private Pin? FindNearestPin(Point mousePos)
        {
            Pin? nearest = null;
            double minDist = PinSnapThreshold;

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

        private void UpdateWirePreview(Point mousePos)
        {
            if (_wireStartPin == null) return;

            if (_wirePreview != null)
            {
                CircuitCanvas.Children.Remove(_wirePreview);
                _wirePreview = null;
            }

            Point start = _wireStartPin.AbsolutePosition;

            Pin? nearEnd = FindNearestPin(mousePos);
            Point end = nearEnd != null ? nearEnd.AbsolutePosition : GridHelper.Snap(mousePos);

            _wirePreview = Wire.CreatePreviewLine(start, end);
            CircuitCanvas.Children.Add(_wirePreview);
        }

        private void RemovePreviewVisuals()
        {
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
            DeselectElement();
            _overlay?.Clear();

            _elements.Clear();
            _wires.Clear();
            _visualToElement.Clear();
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
                    AddElementToCanvas(element);
                foreach (var wire in circuit.Wires)
                {
                    _wires.Add(wire);
                    CircuitCanvas.Children.Add(wire.CreateOrUpdateVisual());
                }
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
