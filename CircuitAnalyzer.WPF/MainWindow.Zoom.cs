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
    // MainWindow parçası: yakınlaştırma ve kaydırma.
    public partial class MainWindow
    {
        // ── Yakınlaştırma ve Kaydırma durumu ──
        private double _currentZoom = 1.0;
        private bool _isPanning;
        private Point _panStartMouse;
        private double _panStartH;
        private double _panStartV;
        // Sağ tuş: basılı sürüklenirse kaydırır, sürüklenmezse sağ tık menüsü açılır
        private bool _rightPanPending;
        private bool _suppressContextMenu;
        private const double RightPanThreshold = 4;

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
                foreach (var wp in w.Waypoints)
                {
                    minX = Math.Min(minX, wp.X);
                    minY = Math.Min(minY, wp.Y);
                    maxX = Math.Max(maxX, wp.X);
                    maxY = Math.Max(maxY, wp.Y);
                }
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
                foreach (var wp in w.Waypoints)
                {
                    minX = Math.Min(minX, wp.X);
                    minY = Math.Min(minY, wp.Y);
                    maxX = Math.Max(maxX, wp.X);
                    maxY = Math.Max(maxY, wp.Y);
                }
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
            else if (e.ChangedButton == MouseButton.Right)
            {
                _rightPanPending = true;
                _suppressContextMenu = false;
                _panStartMouse = e.GetPosition(CanvasScrollViewer);
                _panStartH = CanvasScrollViewer.HorizontalOffset;
                _panStartV = CanvasScrollViewer.VerticalOffset;
            }
        }

        private void CanvasScrollViewer_PreviewMouseMove(object sender, MouseEventArgs e)
        {
            if (!_rightPanPending)
                return;

            if (e.RightButton != MouseButtonState.Pressed)
            {
                _rightPanPending = false;
                return;
            }

            Vector moved = e.GetPosition(CanvasScrollViewer) - _panStartMouse;
            if (moved.Length < RightPanThreshold)
                return;

            _rightPanPending = false;
            _suppressContextMenu = true;
            _isPanning = true;
            Mouse.Capture(CanvasScrollViewer);
            Mouse.OverrideCursor = Cursors.ScrollAll;
        }

        private void CanvasScrollViewer_ContextMenuOpening(object sender, ContextMenuEventArgs e)
        {
            if (_suppressContextMenu)
            {
                _suppressContextMenu = false;
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

        private void BtnZoomOut_Click(object sender, RoutedEventArgs e) => ZoomOut();
        private void BtnZoomIn_Click(object sender, RoutedEventArgs e) => ZoomIn();
        private void BtnZoomFit_Click(object sender, RoutedEventArgs e) => FitToCircuit();
        private void TxtZoomPercent_MouseLeftButtonDown(object sender, MouseButtonEventArgs e) => ResetZoom();
    }
}
