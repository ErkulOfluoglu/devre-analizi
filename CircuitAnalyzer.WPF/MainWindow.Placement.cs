using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using CircuitAnalyzer.WPF.Helpers;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF
{
    // MainWindow parçası: yerleştirme modu (araç kutusundan seçilen eleman fareyi izler, tıklayınca bırakılır)
    // ve boş yer bulma yardımcısı.
    public partial class MainWindow
    {
        /// <summary>Yerleştirme modundaki eleman ve bırakılınca gösterilecek durum metni.</summary>
        private sealed record PlacementState(CircuitElement Element, UIElement Preview, string DoneStatus);

        /// <summary>Yarı saydam önizlemenin opaklığı.</summary>
        private const double PlacementPreviewOpacity = 0.6;

        /// <summary>Yerleşimde elemanın çevresinde bırakılan boşluk (ızgara karesi).</summary>
        private const double FreeSpotMarginCells = 1;

        /// <summary>Boş yer aramasının en uzak halkası (ızgara karesi).</summary>
        private const int FreeSpotMaxRing = 80;

        private PlacementState? _placement;

        /// <summary>Sağ tıkla iptalden sonra gelen bağlam menüsünü bastırmak için.</summary>
        private bool _suppressNextContextMenu;

        /// <summary>Şu an bir eleman yerleştirme modunda mı?</summary>
        internal bool IsPlacing => _placement != null;

        /// <summary>Yerleştirilmekte olan (henüz tuvale eklenmemiş) eleman; yoksa null.</summary>
        internal CircuitElement? PlacingElement => _placement?.Element;

        /// <summary>Yerleştirme önizlemesinin görseli; yoksa null.</summary>
        internal UIElement? PlacementPreview => _placement?.Preview;

        // ═══════════════════════════════════════════════════════
        //  YERLEŞTİRME MODU
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Elemanı henüz eklemeden yerleştirme moduna girer: yarı saydam önizleme fareyi izler,
        /// sol tık bırakır, Esc / sağ tık vazgeçer. Önceki yerleştirme ve tel modu iptal edilir.
        /// Fare tuvalin üzerinde değilse önizleme görünür alanın ortasına yakın boş bir yerde başlar.
        /// </summary>
        internal void BeginPlacement(CircuitElement element, string doneStatus)
        {
            CancelPlacement();
            ExitWireMode();

            UIElement preview = element.CreateVisual();
            preview.IsHitTestVisible = false;
            preview.Opacity = PlacementPreviewOpacity;

            _placement = new PlacementState(element, preview, doneStatus);
            CircuitCanvas.Children.Add(preview);
            CircuitCanvas.Cursor = Cursors.Arrow;

            Point start;
            if (CircuitCanvas.IsMouseOver)
            {
                start = PlacementPositionFor(element, Mouse.GetPosition(CircuitCanvas));
            }
            else
            {
                var center = GetViewportCenterInCanvas();
                start = FindFreePosition(element, CenteredPosition(element, center));
            }
            MovePlacementTo(start);

            TxtStatus.Text = PlacementStatusText(element);
        }

        private static string PlacementStatusText(CircuitElement element) =>
            $"{element.Id} yerleştir — tıkla: bırak · R: döndür · Esc: vazgeç";

        /// <summary>
        /// Yerleştirmeyi iptal eder (eleman eklenmez; Id sayaçları değişmez, çünkü sayaç yalnızca
        /// eleman tuvale eklenince tuvaldeki Id'lerden yeniden hesaplanır).
        /// </summary>
        /// <param name="announce">true ise durum satırında "iptal edildi" yazar.</param>
        /// <returns>Bir yerleştirme iptal edildiyse true.</returns>
        internal bool CancelPlacement(bool announce = false)
        {
            if (_placement == null)
                return false;

            var state = _placement;
            _placement = null;
            CircuitCanvas.Children.Remove(state.Preview);
            CircuitCanvas.Cursor = Cursors.Arrow;

            if (announce)
                TxtStatus.Text = $"{state.Element.Id} yerleştirme iptal edildi";
            return true;
        }

        /// <summary>
        /// Yerleştirmedeki elemanı verilen tuval noktasına (ızgaraya oturtup ortalayarak) bırakır:
        /// tek geri-al adımı, sayaçlar ve devre değişikliği bildirimi AddElementToCanvas ile aynıdır.
        /// </summary>
        internal bool CommitPlacement(Point canvasPoint)
        {
            if (_placement == null)
                return false;

            var state = _placement;
            _placement = null;
            CircuitCanvas.Children.Remove(state.Preview);
            CircuitCanvas.Cursor = Cursors.Arrow;

            state.Element.Position = PlacementPositionFor(state.Element, canvasPoint);
            AddElementToCanvas(state.Element);
            TxtStatus.Text = state.DoneStatus;
            return true;
        }

        /// <summary>Fare tuval üzerinde hareket edince önizlemeyi ızgaraya oturtarak taşır.</summary>
        internal void UpdatePlacementPreview(Point mousePos)
        {
            if (_placement == null)
                return;

            MovePlacementTo(PlacementPositionFor(_placement.Element, mousePos));
        }

        /// <summary>R: yerleştirilen elemanı (ve önizlemesini) 90° döndürür.</summary>
        internal bool RotatePlacement()
        {
            if (_placement == null)
                return false;

            var element = _placement.Element;
            element.Rotation = (element.Rotation + 90) % 360;
            ApplyRotationTransform(_placement.Preview, element.Rotation);

            // Döndürünce kutu tuval kenarından taşabilir; konumu içeri çek
            MovePlacementTo(ClampToCanvas(element, element.Position));
            return true;
        }

        private void MovePlacementTo(Point position)
        {
            if (_placement == null)
                return;

            _placement.Element.Position = position;
            Canvas.SetLeft(_placement.Preview, position.X);
            Canvas.SetTop(_placement.Preview, position.Y);
        }

        /// <summary>Elemanın merkezi verilen noktada olacak biçimde, ızgaraya oturmuş sol-üst konum.</summary>
        private static Point CenteredPosition(CircuitElement element, Point center) =>
            GridHelper.Snap(new Point(center.X - element.VisualWidth / 2.0, center.Y - element.VisualHeight / 2.0));

        /// <summary>İmleç konumuna göre ortalanmış, ızgaraya oturmuş ve tuval içine alınmış konum.</summary>
        private Point PlacementPositionFor(CircuitElement element, Point cursor) =>
            ClampToCanvas(element, CenteredPosition(element, cursor));

        // ═══════════════════════════════════════════════════════
        //  ANINDA EKLEME VE BOŞ YER BULMA
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Elemanı yerleştirme moduna girmeden hemen ekler: görünür alanın ortasına en yakın boş yeri bulur
        /// (programatik çağrılar, testler ve ekran görüntüsü yolları için).
        /// </summary>
        internal void AddElementImmediately(CircuitElement element, string doneStatus, Point? preferredCenter = null)
        {
            CancelPlacement();

            Point center = preferredCenter ?? GetViewportCenterInCanvas();
            element.Position = FindFreePosition(element, CenteredPosition(element, center));
            AddElementToCanvas(element);
            TxtStatus.Text = doneStatus;
        }

        /// <summary>
        /// Tercih edilen konumdan başlayıp ızgara üzerinde dışa doğru (halka halka, yakından uzağa) arar ve
        /// sınırlayıcı kutusu (çevresinde 1 ızgara karelik boşlukla) tuvaldeki hiçbir elemanın kutusuyla
        /// kesişmeyen ilk konumu döndürür. Hiç yer bulunamazsa tercih edilen konum döner.
        /// </summary>
        /// <param name="element">Yerleştirilecek eleman (dönüşü hesaba katılır; listede olmamalıdır).</param>
        /// <param name="preferred">Tercih edilen sol-üst konum.</param>
        internal Point FindFreePosition(CircuitElement element, Point preferred)
        {
            preferred = ClampToCanvas(element, GridHelper.Snap(preferred));

            var occupied = _elements
                .Where(e => !ReferenceEquals(e, element))
                .Select(SelectionModel.GetElementBounds)
                .ToList();

            double margin = FreeSpotMarginCells * GridHelper.GridSize;
            bool IsFree(Point pos)
            {
                Rect box = BoundsAt(element, pos);
                if (!IsInsideCanvas(box))
                    return false;
                box.Inflate(margin, margin);
                return !occupied.Any(o => o.IntersectsWith(box));
            }

            if (IsFree(preferred))
                return preferred;

            for (int ring = 1; ring <= FreeSpotMaxRing; ring++)
            {
                var candidates = new List<(Point Pos, double Dist)>();
                for (int dx = -ring; dx <= ring; dx++)
                {
                    for (int dy = -ring; dy <= ring; dy++)
                    {
                        if (Math.Max(Math.Abs(dx), Math.Abs(dy)) != ring)
                            continue;
                        var pos = new Point(preferred.X + dx * GridHelper.GridSize, preferred.Y + dy * GridHelper.GridSize);
                        candidates.Add((pos, dx * dx + dy * dy));
                    }
                }

                foreach (var (pos, _) in candidates.OrderBy(c => c.Dist))
                {
                    if (IsFree(pos))
                        return pos;
                }
            }

            return preferred;
        }

        /// <summary>Elemanın verilen sol-üst konumdaki (dönüşü dahil) sınırlayıcı kutusu.</summary>
        internal static Rect BoundsAt(CircuitElement element, Point position)
        {
            double w = element.VisualWidth;
            double h = element.VisualHeight;
            double normRot = ((element.Rotation % 360) + 360) % 360;

            if (Math.Abs(normRot - 90) < 0.01 || Math.Abs(normRot - 270) < 0.01)
            {
                double cx = position.X + w / 2.0;
                double cy = position.Y + h / 2.0;
                return new Rect(cx - h / 2.0, cy - w / 2.0, h, w);
            }
            return new Rect(position.X, position.Y, w, h);
        }

        private double CanvasWidth => CircuitCanvas.ActualWidth > 0 ? CircuitCanvas.ActualWidth : CircuitCanvas.Width;
        private double CanvasHeight => CircuitCanvas.ActualHeight > 0 ? CircuitCanvas.ActualHeight : CircuitCanvas.Height;

        private bool IsInsideCanvas(Rect box) =>
            box.Left >= 0 && box.Top >= 0 && box.Right <= CanvasWidth && box.Bottom <= CanvasHeight;

        /// <summary>Konumu, elemanın (dönüşlü) kutusu tuval içinde kalacak biçimde kaydırır.</summary>
        private Point ClampToCanvas(CircuitElement element, Point position)
        {
            Rect box = BoundsAt(element, position);
            double dx = 0, dy = 0;
            if (box.Left < 0) dx = -box.Left;
            else if (box.Right > CanvasWidth) dx = CanvasWidth - box.Right;
            if (box.Top < 0) dy = -box.Top;
            else if (box.Bottom > CanvasHeight) dy = CanvasHeight - box.Bottom;
            return GridHelper.Snap(new Point(position.X + dx, position.Y + dy));
        }

        // ═══════════════════════════════════════════════════════
        //  FARE OLAYLARI (tuvalın Preview olayları)
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Tuvaldeki Preview olaylarını bağlar: sol tık bırakır, sağ tık vazgeçer
        /// (üstünde eleman olsa bile; böylece mevcut elemanlar sürüklenmeye / menüye geçmez).
        /// </summary>
        private void InitializePlacementInput()
        {
            CircuitCanvas.PreviewMouseLeftButtonDown += (_, e) =>
            {
                if (_placement == null || _isPanning || Keyboard.IsKeyDown(Key.Space))
                    return;

                CommitPlacement(e.GetPosition(CircuitCanvas));
                e.Handled = true;
            };

            CircuitCanvas.PreviewMouseRightButtonDown += (_, e) =>
            {
                if (_placement == null)
                    return;

                CancelPlacement(announce: true);
                _suppressNextContextMenu = true;
                e.Handled = true;
            };

            CircuitCanvas.PreviewMouseRightButtonUp += (_, e) =>
            {
                if (!_suppressNextContextMenu)
                    return;

                _suppressNextContextMenu = false;
                e.Handled = true;
            };
        }
    }
}
