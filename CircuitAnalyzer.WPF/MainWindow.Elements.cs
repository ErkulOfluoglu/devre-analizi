using System.Linq;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using CircuitAnalyzer.WPF.Helpers;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF
{
    // MainWindow parçası: eleman ekleme, düzenleme, döndürme, silme, bağlam menüleri ve görsel yenileme.
    public partial class MainWindow
    {
        private int _resistorCounter = 0;
        private int _voltageSourceCounter = 0;
        private int _acSourceCounter = 0;
        private int _currentSourceCounter = 0;
        private int _acCurrentSourceCounter = 0;
        /// <summary>Bağımlı kaynak sayaçları: dizin = (int)DependentSourceKind (E, G, H, F).</summary>
        private readonly int[] _dependentCounters = new int[4];
        private int _capacitorCounter = 0;
        private int _inductorCounter = 0;
        private int _impedanceCounter = 0;
        private int _transformerCounter = 0;
        private int _groundCounter = 0;
        private int _probeCounter = 0;
        private int _junctionCounter = 0;
        private int _switchCounter = 0;

        private Point? _contextMenuCanvasPos = null;
        private ContextMenu? _canvasContextMenu = null;
        private MenuItem? _canvasPasteMenuItem = null;
        private MenuItem? _canvasSelectAllMenuItem = null;

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

        // Toolbox düğmeleri elemanı hemen eklemez: yerleştirme moduna girer (bkz. MainWindow.Placement.cs).
        // Id sayaç+1 olarak verilir ama sayaç artırılmaz; sayaç, eleman tuvale eklenince
        // AddElementToCanvas içinde tuvaldeki Id'lerden yeniden hesaplanır. Vazgeçilirse Id tüketilmez.

        private void BtnAddResistor_Click(object sender, RoutedEventArgs e)
        {
            var resistor = new Resistor
            {
                Id = $"R{_resistorCounter + 1}",
                Value = 1000
            };

            BeginPlacement(resistor, $"{resistor.Id} eklendi — Sürükle/Sağ-tık/Çift-tık");
        }

        private void BtnAddCapacitor_Click(object sender, RoutedEventArgs e)
        {
            var cap = new Capacitor
            {
                Id = $"C{_capacitorCounter + 1}",
                Value = 10e-6
            };

            BeginPlacement(cap, $"{cap.Id} (10µF) eklendi — Sürükle/Sağ-tık/Çift-tık");
        }

        private void BtnAddInductor_Click(object sender, RoutedEventArgs e)
        {
            var ind = new Inductor
            {
                Id = $"L{_inductorCounter + 1}",
                Value = 100e-3
            };

            BeginPlacement(ind, $"{ind.Id} (100mH) eklendi — Sürükle/Sağ-tık/Çift-tık");
        }

        private void BtnAddImpedance_Click(object sender, RoutedEventArgs e)
        {
            var z = new ImpedanceElement
            {
                Id = $"Z{_impedanceCounter + 1}",
                Impedance = ComplexValue.FromRectangular(50, 30)
            };

            BeginPlacement(z, $"{z.Id} ({z.Impedance.ToRectangularString()}Ω) eklendi — Sürükle/Sağ-tık/Çift-tık");
        }

        private void BtnAddTransformer_Click(object sender, RoutedEventArgs e)
        {
            var t = new TransformerElement
            {
                Id = $"T{_transformerCounter + 1}"
            };

            BeginPlacement(t, $"{t.Id} (Transformatör) eklendi — Sürükle/Sağ-tık/Çift-tık");
        }

        /// <summary>
        /// Toprak (GND) referans noktası ekler.
        /// SPICE standartında GND = Node 0'dır.
        /// Devrede en az bir GND olmadan Netlist geçerli değildir.
        /// </summary>
        private void BtnAddGround_Click(object sender, RoutedEventArgs e)
        {
            var gnd = new GroundElement
            {
                Id = $"GND{_groundCounter + 1}"
            };

            BeginPlacement(gnd, $"{gnd.Id} eklendi — Bağlı ağ otomatik Node 0 olur");
        }

        /// <summary>
        /// Ölçüm Probu ekler.
        /// Gerilim probu: bağlı düğümün gerilimini ölçer.
        /// Akım probu: hedef elemanın akımını ölçer.
        /// </summary>
        private void BtnAddProbe_Click(object sender, RoutedEventArgs e)
        {
            var probe = new TestProbe
            {
                Id = $"VP{_probeCounter + 1}",
                Type = ProbeType.Voltage
            };

            BeginPlacement(probe, $"{probe.Id} (Gerilim probu) eklendi — Çift-tıkla V/I değiştir");
        }

        private void BtnAddVoltageSource_Click(object sender, RoutedEventArgs e)
        {
            var source = new VoltageSource
            {
                Id = $"V{_voltageSourceCounter + 1}",
                Value = 12
            };

            BeginPlacement(source, $"{source.Id} ({source.Value}V DC) eklendi — Sürükle/Sağ-tık/Çift-tık");
        }

        private void BtnAddAcSource_Click(object sender, RoutedEventArgs e)
        {
            var acSource = new AcVoltageSource
            {
                Id = $"VAC{_acSourceCounter + 1}",
                Amplitude = 10,
                Frequency = 50,
                Phase = 0,
                ValueKind = AcValueKind.Rms
            };

            BeginPlacement(acSource, $"{acSource.Id} eklendi — {acSource.Amplitude}V, " +
                $"{acSource.Frequency}Hz, ∠{acSource.Phase}° — Sürükle/Sağ-tık/Çift-tık");
        }

        private void BtnAddCurrentSource_Click(object sender, RoutedEventArgs e)
        {
            var source = new CurrentSource
            {
                Id = $"I{_currentSourceCounter + 1}",
                Value = 0.001
            };

            BeginPlacement(source, $"{source.Id} ({source.Value}A DC) eklendi — Sürükle/Sağ-tık/Çift-tık");
        }

        private void BtnAddAcCurrentSource_Click(object sender, RoutedEventArgs e)
        {
            var acSource = new AcCurrentSource
            {
                Id = $"IAC{_acCurrentSourceCounter + 1}",
                Amplitude = 0.01,
                Frequency = 50,
                Phase = 0,
                ValueKind = AcValueKind.Rms
            };

            BeginPlacement(acSource, $"{acSource.Id} eklendi — {acSource.Amplitude}A, " +
                $"{acSource.Frequency}Hz, ∠{acSource.Phase}° — Sürükle/Sağ-tık/Çift-tık");
        }

        private void BtnAddVcvs_Click(object sender, RoutedEventArgs e) => BeginDependentSourcePlacement(DependentSourceKind.Vcvs);
        private void BtnAddVccs_Click(object sender, RoutedEventArgs e) => BeginDependentSourcePlacement(DependentSourceKind.Vccs);
        private void BtnAddCcvs_Click(object sender, RoutedEventArgs e) => BeginDependentSourcePlacement(DependentSourceKind.Ccvs);
        private void BtnAddCccs_Click(object sender, RoutedEventArgs e) => BeginDependentSourcePlacement(DependentSourceKind.Cccs);

        /// <summary>Bağımlı kaynak oluşturur (E1, G1, H1, F1…); tuvale eklemez, sayaç artırmaz.</summary>
        private DependentSource NewDependentSource(DependentSourceKind kind) =>
            new(kind)
            {
                Id = $"{DependentSource.PrefixOf(kind)}{_dependentCounters[(int)kind] + 1}",
                Gain = 2
            };

        private static string DependentSourceDoneStatus(DependentSource source) =>
            $"{source.Id} ({source.KindName}) eklendi — Çift-tıkla kontrol elemanını ve kazancı seç";

        /// <summary>Bağımlı kaynak için yerleştirme moduna girer (araç kutusu düğmeleri).</summary>
        private void BeginDependentSourcePlacement(DependentSourceKind kind)
        {
            var source = NewDependentSource(kind);
            BeginPlacement(source, DependentSourceDoneStatus(source));
        }

        private void BtnAddSwitch_Click(object sender, RoutedEventArgs e)
        {
            var sw = new SwitchElement
            {
                Id = $"S{_switchCounter + 1}",
                Mode = SwitchMode.NormallyOpen
            };

            BeginPlacement(sw, $"{sw.Id} (Anahtar) eklendi — Sürükle/Sağ-tık/Çift-tık");
        }

        private void BtnAddSpdtSwitch_Click(object sender, RoutedEventArgs e)
        {
            var spdt = new SpdtSwitch
            {
                Id = $"S{_switchCounter + 1}"
            };

            BeginPlacement(spdt, $"{spdt.Id} (İki konumlu anahtar) eklendi — Sürükle/Sağ-tık/Çift-tık");
        }

        /// <summary>
        /// Bağımlı kaynağı yerleştirme moduna girmeden hemen ekler (E1, G1, H1, F1…): görünür alanın
        /// ortasına en yakın boş yere konur. Kontrol elemanı çift tıklayınca açılan düzenleyiciden
        /// seçilir; seçilene kadar çözülemez.
        /// </summary>
        internal DependentSource AddDependentSource(DependentSourceKind kind)
        {
            ExitWireMode();
            var source = NewDependentSource(kind);
            AddElementImmediately(source, DependentSourceDoneStatus(source));
            return source;
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
        /// <summary>
        /// Elemanın kutusunun tamamını fareyle tutulabilir yapar. Arka plansız Canvas yalnızca
        /// çizgilerin üstünde fare olayı alır; GND gibi ince çizgili simgeler bu yüzden
        /// neredeyse sürüklenemiyordu. Bağlantı noktası kendi tutma alanını çizer, dokunulmaz.
        /// </summary>
        internal static void MakeBodyGrabbable(CircuitElement element, UIElement visual)
        {
            if (element is not JunctionElement && visual is Panel panel && panel.Background == null)
                panel.Background = Brushes.Transparent;
        }

        private UIElement AddElementToCanvasCore(CircuitElement element)
        {
            _elements.Add(element);
            UIElement visual = element.CreateVisual();
            MakeBodyGrabbable(element, visual);

            Canvas.SetLeft(visual, element.Position.X);
            Canvas.SetTop(visual, element.Position.Y);

            if (element.Rotation != 0)
            {
                ApplyRotationTransform(visual, element.Rotation);
            }

            visual.MouseLeftButtonDown += Element_MouseLeftButtonDown;
            visual.MouseRightButtonUp += Element_MouseRightButtonUp;

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
            // Tuş bırakılınca: sağ tuşla sürükleyip kaydırırken (fare yakalı) tel seçilmez, menü değişmez
            CircuitCanvas.PreviewMouseRightButtonUp += (_, e) =>
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

        private void Element_MouseRightButtonUp(object sender, MouseButtonEventArgs e)
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
        //  DÖNDÜRME (ROTATION)
        // ═══════════════════════════════════════════════════════

        /// <summary>Tek bir elemanı 90° saat yönünde döndürür.</summary>
        private void RotateElement(CircuitElement element, UIElement visual)
        {
            if (element is JunctionElement || _isWireMode || _isPinWiring)
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
            if (_isWireMode || _isPinWiring)
                return;

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
            KeepTextUpright(visual, angle);
        }

        /// <summary>
        /// Eleman döndürülünce içindeki yazılar (ad, değer, "t = 0"…) ters ya da yan kalmasın:
        /// her yazı kendi merkezi etrafında ters yönde döndürülür, böylece hep düz okunur.
        /// Dikey duran elemanda (90°/270°) yatay kalan yazı gövdeye doğru genişler; çizgilerin
        /// üstüne binmesin diye gövdeden uzağa, genişliği ile yüksekliği farkının yarısı kadar itilir.
        /// </summary>
        internal static void KeepTextUpright(UIElement visual, double angle)
        {
            double a = ((angle % 360) + 360) % 360;
            if (visual is Panel root)
            {
                double centerY = double.IsNaN(root.Height) ? double.NaN : root.Height / 2;
                foreach (var text in TextBlocksIn(root))
                    MakeUpright(text, a, centerY);
            }
            else if (visual is TextBlock single)
            {
                MakeUpright(single, a, double.NaN);
            }
        }

        private static IEnumerable<TextBlock> TextBlocksIn(Panel panel)
        {
            foreach (UIElement child in panel.Children)
            {
                if (child is TextBlock text)
                    yield return text;
                else if (child is Panel inner)
                    foreach (var t in TextBlocksIn(inner))
                        yield return t;
            }
        }

        private static void MakeUpright(TextBlock text, double angle, double elementCenterY)
        {
            text.RenderTransformOrigin = new Point(0.5, 0.5);
            if (angle == 0)
            {
                text.RenderTransform = Transform.Identity;
                return;
            }

            var group = new TransformGroup();
            group.Children.Add(new RotateTransform(-angle));

            double top = Canvas.GetTop(text);
            if ((angle == 90 || angle == 270) && !double.IsNaN(elementCenterY) && !double.IsNaN(top))
            {
                text.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
                Size size = text.DesiredSize;
                double offset = top + size.Height / 2 - elementCenterY;   // gövde eksenine dik uzaklık
                double push = Math.Max(0, (size.Width - size.Height) / 2);
                if (Math.Abs(offset) > 0.5 && push > 0)
                    group.Children.Add(new TranslateTransform(0, Math.Sign(offset) * push));
            }
            text.RenderTransform = group;
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

            var editor = new ElementEditorWindow(element, _elements);
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
            MakeBodyGrabbable(element, newVisual);

            Canvas.SetLeft(newVisual, element.Position.X);
            Canvas.SetTop(newVisual, element.Position.Y);

            if (element.Rotation != 0)
            {
                ApplyRotationTransform(newVisual, element.Rotation);
            }

            newVisual.MouseLeftButtonDown += Element_MouseLeftButtonDown;
            newVisual.MouseRightButtonUp += Element_MouseRightButtonUp;
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
            CancelPlacement();
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
            _dragInitialWaypoints.Clear();
            ResetCurrentWireState();
            _pasteCascadeCount = 0;
            _resistorCounter = 0;
            _voltageSourceCounter = 0;
            _acSourceCounter = 0;
            _currentSourceCounter = 0;
            _acCurrentSourceCounter = 0;
            Array.Clear(_dependentCounters);
            _capacitorCounter = 0;
            _inductorCounter = 0;
            _impedanceCounter = 0;
            _transformerCounter = 0;
            _groundCounter = 0;
            _probeCounter = 0;
            _junctionCounter = 0;
            _switchCounter = 0;
            _pendingStartSplit = null;

            _controlMarkers.Clear();
            CircuitCanvas.Children.Clear();
        }
    }
}
