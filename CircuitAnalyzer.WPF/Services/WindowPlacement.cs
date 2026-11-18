using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using System.Windows;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>Ana pencerenin kaydedilen yeri: normal (büyütülmemiş) dikdörtgen ve büyütülmüş mü.</summary>
    public sealed record SavedWindowPlacement(double Left, double Top, double Width, double Height, bool Maximized);

    /// <summary>
    /// Kaydedilen pencere yerinin bu ekranlarda kullanılabilir olup olmadığına karar verir.
    /// (Monitör çıkarılmış, çözünürlük değişmiş olabilir.)
    /// </summary>
    public static class WindowPlacementRules
    {
        /// <summary>
        /// Başlık çubuğundan en az bu kadarı bir ekranın çalışma alanında görünmüyorsa pencere
        /// "ekran dışında" sayılır ve varsayılan yere açılır.
        /// </summary>
        public const double MinVisibleTitleWidth = 120;
        public const double TitleBarHeight = 32;

        /// <summary>
        /// Kaydedilen dikdörtgeni ekranlara uydurur. Kullanılamazsa (sayı değil, sıfır/eksi boyut,
        /// hiçbir ekranda başlık çubuğu görünmüyor) null döner: çağıran varsayılan boyut ve
        /// ortalanmış konumu kullanır. Kullanılabilirse, başlık çubuğunun en çok göründüğü ekranın
        /// çalışma alanına sığacak biçimde küçültülüp kaydırılmış dikdörtgen döner.
        /// </summary>
        public static Rect? Fit(double left, double top, double width, double height,
                                IReadOnlyList<Rect> workAreas, double minWidth, double minHeight)
        {
            if (!double.IsFinite(left) || !double.IsFinite(top) ||
                !double.IsFinite(width) || !double.IsFinite(height) ||
                width <= 0 || height <= 0)
                return null;

            var usable = workAreas.Where(a => !a.IsEmpty && a.Width > 0 && a.Height > 0).ToList();
            if (usable.Count == 0)
                return null;

            // Başlık çubuğu (pencereyi tutup taşımaya yarayan şerit) hangi ekranda en çok görünüyor?
            var title = new Rect(left, top, width, Math.Min(TitleBarHeight, height));
            Rect best = Rect.Empty;
            double bestWidth = 0;
            foreach (var area in usable)
            {
                var overlap = Rect.Intersect(title, area);
                if (!overlap.IsEmpty && overlap.Width > bestWidth)
                {
                    bestWidth = overlap.Width;
                    best = area;
                }
            }
            if (best.IsEmpty || bestWidth < Math.Min(MinVisibleTitleWidth, width))
                return null;

            // Ekrandan büyükse küçült (en küçük boyutun altına inme), sonra ekranın içine kaydır
            double w = Math.Max(Math.Min(width, best.Width), Math.Min(minWidth, best.Width));
            double h = Math.Max(Math.Min(height, best.Height), Math.Min(minHeight, best.Height));
            double x = Math.Min(Math.Max(left, best.Left), best.Right - w);
            double y = Math.Min(Math.Max(top, best.Top), best.Bottom - h);
            return new Rect(x, y, w, h);
        }

        /// <summary>
        /// Kayıtlı yer yokken (ilk açılış): varsayılan boyutu çalışma alanına sığdırır ve ortalar.
        /// Küçük ekranda (örn. 1366×768, %125 ölçek) pencere görev çubuğunun altına taşmaz;
        /// en küçük boyutlar da çalışma alanından büyük kalmaz.
        /// </summary>
        public static (Rect Bounds, double MinWidth, double MinHeight) FitDefault(
            double width, double height, double minWidth, double minHeight, Rect workArea)
        {
            if (workArea.IsEmpty || workArea.Width <= 0 || workArea.Height <= 0)
                return (new Rect(0, 0, width, height), minWidth, minHeight);

            double w = Math.Min(width, workArea.Width);
            double h = Math.Min(height, workArea.Height);
            double minW = Math.Min(minWidth, w);
            double minH = Math.Min(minHeight, h);
            double x = workArea.Left + (workArea.Width - w) / 2;
            double y = workArea.Top + (workArea.Height - h) / 2;
            return (new Rect(x, y, w, h), minW, minH);
        }

        /// <summary>
        /// Ekranların çalışma alanları (görev çubuğu hariç), WPF birimlerinde (1/96 inç).
        /// Sistem DPI'ı ile çevrilir; okunamazsa birincil ekranın çalışma alanı döner.
        /// </summary>
        public static IReadOnlyList<Rect> GetWorkAreas()
        {
            var list = new List<Rect>();
            try
            {
                double scale = 1.0;
                try
                {
                    uint dpi = GetDpiForSystem();
                    if (dpi > 0) scale = dpi / 96.0;
                }
                catch (Exception)
                {
                }

                MonitorEnumProc callback = (IntPtr monitor, IntPtr hdc, ref RECT rc, IntPtr data) =>
                {
                    var info = new MONITORINFO { cbSize = Marshal.SizeOf<MONITORINFO>() };
                    if (GetMonitorInfo(monitor, ref info))
                    {
                        var w = info.rcWork;
                        list.Add(new Rect(w.Left / scale, w.Top / scale,
                                          (w.Right - w.Left) / scale, (w.Bottom - w.Top) / scale));
                    }
                    return true;
                };
                EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, callback, IntPtr.Zero);
                GC.KeepAlive(callback);
            }
            catch (Exception)
            {
                list.Clear();
            }
            if (list.Count == 0)
                list.Add(SystemParameters.WorkArea);
            return list;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct RECT { public int Left, Top, Right, Bottom; }

        [StructLayout(LayoutKind.Sequential)]
        private struct MONITORINFO
        {
            public int cbSize;
            public RECT rcMonitor;
            public RECT rcWork;
            public uint dwFlags;
        }

        private delegate bool MonitorEnumProc(IntPtr monitor, IntPtr hdc, ref RECT rect, IntPtr data);

        [DllImport("user32.dll")]
        private static extern bool EnumDisplayMonitors(IntPtr hdc, IntPtr clip, MonitorEnumProc callback, IntPtr data);

        [DllImport("user32.dll")]
        private static extern bool GetMonitorInfo(IntPtr monitor, ref MONITORINFO info);

        [DllImport("user32.dll")]
        private static extern uint GetDpiForSystem();
    }
}
