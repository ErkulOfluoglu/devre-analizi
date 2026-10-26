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
    // MainWindow parçası: tel çizimi, köşe noktaları, T-bağlantı bölme, önizleme ve tel seçme/hover yardımcıları.
    public partial class MainWindow
    {
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
        private readonly List<Point> _currentWaypoints = new();
        private readonly Stack<int> _waypointCommitCounts = new();
        private bool _liveLegVerticalFirst = false;
        private Point _lastMouseCanvasPos;
        internal const string DrawingWireStatusText =
            "Tel çiziliyor — boş yere tıkla: köşe · R: yön çevir · Backspace: köşeyi geri al · Esc: vazgeç";

        private sealed record PendingWireSplit(Wire OriginalWire, JunctionElement Junction, Wire FirstPart, Wire SecondPart);
        private PendingWireSplit? _pendingStartSplit = null;

        // ── Pin algılama eşiği (piksel) ──
        private const double PinSnapThreshold = 12.0;
        /// <summary>Normal modda uç algılama yarıçapının tuval birimi cinsinden üst sınırı.</summary>
        private const double NormalModePinRadiusCap = 14.0;
        // ── Tel yakalama eşiği (ekran pikseli ve tuval birimi üst sınırı) ──
        private const double WireSnapThreshold = 6.0;
        private const double WireToleranceCap = 8.0;

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
            ResetCurrentWireState();
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
            ResetCurrentWireState();
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

        /// <summary>Bir tel çizimi şu anda aktif mi (başlangıç ucu seçilmiş mi)?</summary>
        internal bool IsDrawingWire => (_isPinWiring || _isWireMode) && _wireStartPin != null;

        /// <summary>Aktif tel çizimindeki somutlaştırılmış ara köşe noktaları.</summary>
        internal IReadOnlyList<Point> CurrentWaypoints => _currentWaypoints;

        /// <summary>Aktif tel çizimindeki canlı kolun yönü (true = önce dikey, false = önce yatay).</summary>
        internal bool LiveLegVerticalFirst => _liveLegVerticalFirst;

        /// <summary>Aktif tel önizleme çizgisi.</summary>
        internal Polyline? WirePreview => _wirePreview;

        private void ResetCurrentWireState()
        {
            _currentWaypoints.Clear();
            _waypointCommitCounts.Clear();
            _liveLegVerticalFirst = false;
        }

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
            ResetCurrentWireState();
            _isPinWiring = true;
            _wireStartPin = startPin;
            _lastMouseCanvasPos = startPin.AbsolutePosition;
            CircuitCanvas.Cursor = Cursors.Cross;
            UpdatePinHighlight(startPin.AbsolutePosition);
            TxtStatus.Text = DrawingWireStatusText;
        }

        /// <summary>Normal modda başlatılan tel çizimini iptal eder ve normal moda döner.</summary>
        internal void CancelPinWire()
        {
            if (!_isPinWiring)
                return;

            RevertPendingStartSplit();
            ResetCurrentWireState();
            _isPinWiring = false;
            _wireStartPin = null;
            RemovePreviewVisuals();
            CircuitCanvas.Cursor = Cursors.Arrow;
            TxtStatus.Text = "Tel çizimi iptal edildi";
        }

        /// <summary>
        /// Çizim sırasında boş tuvale tıklandığında mevcut kolu sabitler:
        /// tıklanan nokta (ve kol L-şeklindeyse onun köşesi) ara köşe noktası olarak kaydedilir.
        /// </summary>
        internal void AddWireWaypoint(Point snappedPt)
        {
            if (_wireStartPin == null)
                return;

            Point anchor = _currentWaypoints.Count > 0
                ? _currentWaypoints[^1]
                : _wireStartPin.AbsolutePosition;

            if (WireGeometry.PointsCoincide(snappedPt, anchor))
                return;

            double dx = Math.Abs(anchor.X - snappedPt.X);
            double dy = Math.Abs(anchor.Y - snappedPt.Y);

            if (dx > 0.5 && dy > 0.5)
            {
                Point corner = _liveLegVerticalFirst
                    ? new Point(anchor.X, snappedPt.Y)
                    : new Point(snappedPt.X, anchor.Y);
                _currentWaypoints.Add(corner);
                _currentWaypoints.Add(snappedPt);
                _waypointCommitCounts.Push(2);
            }
            else
            {
                _currentWaypoints.Add(snappedPt);
                _waypointCommitCounts.Push(1);
            }

            UpdateWirePreview(_lastMouseCanvasPos);
            TxtStatus.Text = DrawingWireStatusText;
        }

        /// <summary>
        /// Çizim sırasında R tuşuna basıldığında fareyi izleyen canlı kolun yönünü çevirir
        /// (önce yatay ↔ önce dikey) ve önizlemeyi günceller.
        /// </summary>
        internal void FlipLiveWireLegOrientation()
        {
            if (!IsDrawingWire)
                return;

            _liveLegVerticalFirst = !_liveLegVerticalFirst;
            UpdateWirePreview(_lastMouseCanvasPos);
            TxtStatus.Text = DrawingWireStatusText;
        }

        /// <summary>
        /// Çizim sırasında Backspace tuşuna basıldığında son eklenen ara köşeyi
        /// (ve birlikte eklendiyse örtük L-köşesini) geri alır; köşe yoksa hiçbir şey yapmaz.
        /// </summary>
        internal void RemoveLastWireWaypoint()
        {
            if (!IsDrawingWire || _currentWaypoints.Count == 0)
                return;

            int count = _waypointCommitCounts.Count > 0 ? _waypointCommitCounts.Pop() : 1;
            int removeCount = Math.Min(count, _currentWaypoints.Count);
            _currentWaypoints.RemoveRange(_currentWaypoints.Count - removeCount, removeCount);
            UpdateWirePreview(_lastMouseCanvasPos);
            TxtStatus.Text = DrawingWireStatusText;
        }

        internal void HandlePinWireClick(Point mousePos)
        {
            _lastMouseCanvasPos = mousePos;
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

                // Boş tuvale tıklandı → mevcut kolu sabitleyip ara köşe (waypoint) ekle
                AddWireWaypoint(GridHelper.Snap(mousePos));
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

        internal void HandleWireClick(Point mousePos)
        {
            _lastMouseCanvasPos = mousePos;
            Pin? nearestPin = FindNearestPin(mousePos);

            if (nearestPin == null)
            {
                var wireHit = WireGeometry.HitTestWire(_wires, mousePos, GetWireTolerance());
                if (wireHit is var (hitWire, snapped))
                {
                    if (_wireStartPin == null)
                    {
                        ResetCurrentWireState();
                        UpdateJunctionPreview(null);
                        _pendingStartSplit = SplitWireOnCanvasCore(hitWire, snapped);
                        _wireStartPin = _pendingStartSplit.Junction.Pins[0];
                        TxtStatus.Text = DrawingWireStatusText;
                        return;
                    }

                    Pin startPin = _wireStartPin;
                    var endSplit = SplitWireOnCanvasCore(hitWire, snapped);
                    _pendingStartSplit = null;
                    CompleteWire(startPin, endSplit.Junction.Pins[0]);
                    TxtStatus.Text = $"Tel ortasından bağlandı ({endSplit.Junction.Id})";
                    return;
                }

                if (_wireStartPin != null)
                {
                    AddWireWaypoint(GridHelper.Snap(mousePos));
                    return;
                }

                TxtStatus.Text = "TEL MODU — Pin bulunamadı! Bir elemanın pin noktasına tıklayın";
                return;
            }

            if (_wireStartPin == null)
            {
                ResetCurrentWireState();
                _wireStartPin = nearestPin;
                TxtStatus.Text = DrawingWireStatusText;
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
            var waypoints = new List<Point>(_currentWaypoints);
            while (waypoints.Count > 0 && WireGeometry.PointsCoincide(waypoints[0], startPin.AbsolutePosition))
                waypoints.RemoveAt(0);
            while (waypoints.Count > 0 && WireGeometry.PointsCoincide(waypoints[^1], endPin.AbsolutePosition))
                waypoints.RemoveAt(waypoints.Count - 1);

            var wire = new Wire(startPin, endPin, waypoints, _liveLegVerticalFirst);
            _wires.Add(wire);

            var visual = wire.CreateOrUpdateVisual();
            CircuitCanvas.Children.Add(visual);

            RefreshJunctionWireCounts();
            RemovePreviewVisuals();
            _wireStartPin = null;
            ResetCurrentWireState();
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

            _wirePreview = Wire.CreatePreviewLine(start, _currentWaypoints, end, _liveLegVerticalFirst);
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
    }
}
