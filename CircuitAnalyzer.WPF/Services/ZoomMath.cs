using System;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Tuval yakınlaştırma (zoom), kaydırma (pan) ve sığdırma (fit) hesaplamaları.
    /// WPF bağımsız saf matematik — birim testlerle doğrudan test edilir.
    /// </summary>
    public static class ZoomMath
    {
        public const double MinZoom = 0.25;
        public const double MaxZoom = 4.0;
        public const double StepFactor = 1.2;
        public const double FitMinZoom = 0.25;
        public const double FitMaxZoom = 2.0;
        public const double FitMargin = 40.0;

        /// <summary>Yakınlaştırma oranını %25 ile %400 arasında sınırlar.</summary>
        public static double ClampZoom(double zoom) => Math.Clamp(zoom, MinZoom, MaxZoom);

        /// <summary>Bir adım (%120) yakınlaştırır.</summary>
        public static double ZoomIn(double currentZoom) => ClampZoom(currentZoom * StepFactor);

        /// <summary>Bir adım (%120) uzaklaştırır.</summary>
        public static double ZoomOut(double currentZoom) => ClampZoom(currentZoom / StepFactor);

        /// <summary>
        /// Fare imlecinin altındaki tuval noktasını sabit tutacak yeni kaydırma konumlarını hesaplar.
        /// </summary>
        public static (double newHorizontalOffset, double newVerticalOffset) ComputeZoomOffsets(
            double oldZoom,
            double newZoom,
            double mouseViewportX,
            double mouseViewportY,
            double currentHorizontalOffset,
            double currentVerticalOffset)
        {
            if (oldZoom <= 0) oldZoom = 1.0;
            if (newZoom <= 0) newZoom = 1.0;

            double newH = (currentHorizontalOffset + mouseViewportX) * (newZoom / oldZoom) - mouseViewportX;
            double newV = (currentVerticalOffset + mouseViewportY) * (newZoom / oldZoom) - mouseViewportY;
            return (Math.Max(0, newH), Math.Max(0, newV));
        }

        /// <summary>
        /// İçeriğin tamamını verilen kenar boşluğuyla görünüme sığdıracak oran ve kaydırma konumlarını hesaplar.
        /// </summary>
        public static (double zoom, double horizontalOffset, double verticalOffset) ComputeFit(
            double contentMinX,
            double contentMinY,
            double contentMaxX,
            double contentMaxY,
            double viewportWidth,
            double viewportHeight,
            double margin = FitMargin)
        {
            double contentW = contentMaxX - contentMinX;
            double contentH = contentMaxY - contentMinY;

            if (contentW <= 0 || contentH <= 0 || viewportWidth <= 0 || viewportHeight <= 0)
            {
                return (1.0, 0, 0);
            }

            double availW = Math.Max(10, viewportWidth - 2 * margin);
            double availH = Math.Max(10, viewportHeight - 2 * margin);

            double zX = availW / contentW;
            double zY = availH / contentH;
            double fitZoom = Math.Clamp(Math.Min(zX, zY), FitMinZoom, FitMaxZoom);

            double centerX = (contentMinX + contentMaxX) / 2.0;
            double centerY = (contentMinY + contentMaxY) / 2.0;

            double hOffset = Math.Max(0, centerX * fitZoom - viewportWidth / 2.0);
            double vOffset = Math.Max(0, centerY * fitZoom - viewportHeight / 2.0);

            return (fitZoom, hOffset, vOffset);
        }

        /// <summary>
        /// İçerik %100 ölçekte ve 40 px kenar boşluğuyla görünüme sığıyor mu kontrol eder.
        /// </summary>
        public static bool NeedsFitAt100(
            double contentMinX,
            double contentMinY,
            double contentMaxX,
            double contentMaxY,
            double viewportWidth,
            double viewportHeight,
            double margin = FitMargin)
        {
            double contentW = contentMaxX - contentMinX;
            double contentH = contentMaxY - contentMinY;
            if (contentW <= 0 || contentH <= 0) return false;
            double availW = viewportWidth - 2 * margin;
            double availH = viewportHeight - 2 * margin;
            return contentW > availW || contentH > availH;
        }

        /// <summary>
        /// Verilen ölçekte içeriği görünümün ortasına getirecek kaydırma konumlarını hesaplar.
        /// </summary>
        public static (double horizontalOffset, double verticalOffset) ComputeScrollToCenter(
            double contentMinX,
            double contentMinY,
            double contentMaxX,
            double contentMaxY,
            double zoom,
            double viewportWidth,
            double viewportHeight)
        {
            double centerX = (contentMinX + contentMaxX) / 2.0;
            double centerY = (contentMinY + contentMaxY) / 2.0;
            double hOffset = Math.Max(0, centerX * zoom - viewportWidth / 2.0);
            double vOffset = Math.Max(0, centerY * zoom - viewportHeight / 2.0);
            return (hOffset, vOffset);
        }
    }
}
