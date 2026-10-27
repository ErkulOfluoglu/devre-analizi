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

namespace CircuitAnalyzer.WPF
{
    // MainWindow parçası: klavye kısayolları ve tuval fare olaylarının dağıtıcıları.
    public partial class MainWindow
    {
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
                ("Boş yere tıkla", "Tel çizerken köşe ekle"),
                ("R (tel çizerken)", "Köşe yönünü çevir"),
                ("Backspace", "Son köşeyi geri al"),
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
            _lastMouseCanvasPos = mousePos;
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
                    if (_wireStartPin != null)
                    {
                        TxtStatus.Text = DrawingWireStatusText;
                    }
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
                    else if (_wireStartPin != null)
                    {
                        TxtStatus.Text = DrawingWireStatusText;
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
                }

                // Her iki uç elemanı da taşınan seçimdeyse telin ara köşelerini (Waypoints) aynı delta ile kaydır
                foreach (var (wire, initWps) in _dragInitialWaypoints)
                {
                    if (wire.StartPin.Owner != null && _dragInitialPositions.TryGetValue(wire.StartPin.Owner, out var ownerStart))
                    {
                        Vector delta = wire.StartPin.Owner.Position - ownerStart;
                        for (int i = 0; i < initWps.Count && i < wire.Waypoints.Count; i++)
                        {
                            wire.Waypoints[i] = GridHelper.Snap(new Point(initWps[i].X + delta.X, initWps[i].Y + delta.Y));
                        }
                    }
                }

                foreach (var (el, _) in _dragInitialPositions)
                {
                    UpdateConnectedWires(el);
                }

                RefreshControlMarkers();
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
                _dragInitialWaypoints.Clear();

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

        internal bool HandleKeyDown(Key key, ModifierKeys mods = ModifierKeys.None)
        {
            if (IsModalOverlayOpen)
                return false;

            if (key == Key.Escape)
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
                    return true;
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
                    return true;
                }
                if (_selection.HasSelection)
                {
                    DeselectElement();
                    TxtStatus.Text = "Seçim temizlendi";
                    return true;
                }
                return false;
            }

            if (key == Key.Back && mods == ModifierKeys.None)
            {
                if (IsDrawingWire)
                {
                    RemoveLastWireWaypoint();
                    return true;
                }
                return false;
            }

            if (key == Key.R && mods == ModifierKeys.None)
            {
                if (IsDrawingWire)
                {
                    FlipLiveWireLegOrientation();
                    return true;
                }
                if (!_isWireMode && !_isPinWiring && _selection.Count > 0)
                {
                    RotateSelected();
                    return true;
                }
                return false;
            }

            return false;
        }
    }
}
