using System.Windows;
using System.Windows.Input;
using System.Windows.Media;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Fare konumunu ScottPlot'un beklediği gerçek ekran pikseline çevirir.
    ///
    /// Neden: WPF konumu ölçeklenmiş birimde (DIP) verir; ScottPlot grafiği
    /// gerçek piksellerle çizer. Windows ekranı %125/%150 büyütülmüşse bu iki
    /// birim farklıdır ve imleç çizgisi fareden geride kalır. ScottPlot'un kendi
    /// DisplayScale değeri pencere açılmadan okunduğu için 1 kalabiliyor; bu
    /// yüzden ölçek her seferinde WPF'in kendisinden (VisualTreeHelper.GetDpi) alınır.
    /// </summary>
    internal static class PlotMouse
    {
        public static ScottPlot.Pixel ToPlotPixel(FrameworkElement plot, MouseEventArgs e)
        {
            Point pos = e.GetPosition(plot);
            DpiScale dpi = VisualTreeHelper.GetDpi(plot);
            return new ScottPlot.Pixel(pos.X * dpi.DpiScaleX, pos.Y * dpi.DpiScaleY);
        }
    }
}
