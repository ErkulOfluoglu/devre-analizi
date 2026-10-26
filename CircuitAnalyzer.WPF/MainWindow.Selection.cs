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
    // MainWindow parçası: seçim durumu, çerçeve seçimi, sürükleyerek taşıma ve seçim vurgusu.
    public partial class MainWindow
    {
        // ── Sürükleme (Drag) durumu ──
        private bool _isDragging = false;
        private CircuitElement? _draggedElement = null;
        private UIElement? _draggedVisual = null;
        private Point _dragOffset;
        private Point _dragStartPosition;
        private Dictionary<CircuitElement, Point> _dragInitialPositions = new();
        private Dictionary<Wire, List<Point>> _dragInitialWaypoints = new();

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
                HandleElementLeftButtonDown(element, visual, mousePos, e.ClickCount, Keyboard.Modifiers);
                e.Handled = true;
            }
        }

        internal void HandleElementLeftButtonDown(
            CircuitElement element,
            Point mousePos,
            int clickCount = 1,
            ModifierKeys? modifiers = null)
        {
            if (_elementToVisual.TryGetValue(element, out var visual))
            {
                HandleElementLeftButtonDown(element, visual, mousePos, clickCount, modifiers);
            }
        }

        private void HandleElementLeftButtonDown(
            CircuitElement element,
            UIElement visual,
            Point mousePos,
            int clickCount = 1,
            ModifierKeys? modifiers = null)
        {
            ModifierKeys mods = modifiers ?? Keyboard.Modifiers;

            if (_isWireMode)
            {
                HandleWireClick(mousePos);
                return;
            }

            if (_isPinWiring)
            {
                if (clickCount == 2)
                {
                    CancelPinWire();
                    EditElement(element, visual);
                    return;
                }
                HandlePinWireClick(mousePos);
                return;
            }

            // ── Çift tık → Değer düzenleme ──
            if (clickCount == 2)
            {
                EditElement(element, visual);
                return;
            }

            // ── Ctrl+tık → Seçime ekle / çıkar ──
            if (mods.HasFlag(ModifierKeys.Control))
            {
                _selection.Toggle(element);
                TxtStatus.Text = FormatSelectionStatus();
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
            _dragInitialWaypoints = _wires
                .Where(w => w.Waypoints.Count > 0 &&
                            w.StartPin.Owner != null &&
                            w.EndPin.Owner != null &&
                            _dragInitialPositions.ContainsKey(w.StartPin.Owner) &&
                            _dragInitialPositions.ContainsKey(w.EndPin.Owner))
                .ToDictionary(w => w, w => w.Waypoints.ToList());

            double elementX = Canvas.GetLeft(visual);
            double elementY = Canvas.GetTop(visual);
            if (double.IsNaN(elementX)) elementX = element.Position.X;
            if (double.IsNaN(elementY)) elementY = element.Position.Y;
            _dragOffset = new Point(mousePos.X - elementX, mousePos.Y - elementY);

            visual.CaptureMouse();

            TxtStatus.Text = _selection.Count > 1
                ? $"{_selection.Count} eleman sürükleniyor..."
                : $"{element.Id} sürükleniyor... (R: döndür)";
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
    }
}
