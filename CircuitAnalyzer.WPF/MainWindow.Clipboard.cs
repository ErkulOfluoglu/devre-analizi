using System.Linq;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using CircuitAnalyzer.WPF.Helpers;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF
{
    // MainWindow parçası: kopyala / kes / yapıştır / çoğalt.
    public partial class MainWindow
    {
        // ── Pano ve sağ-tık bağlam menüsü durumu ──
        private int _pasteCascadeCount = 0;

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
            // Yapıştırılan Id'ler bekleyen yerleştirmenin Id'siyle çakışabilir
            CancelPlacement();
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
    }
}
