using System;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Windows 11'in Mica malzemesini pencere zeminine koyar (DESIGN.md, "Katmanlar").
    ///
    /// Mica duvar kâğıdının rengini çok hafif alan, opak bir zemindir; Windows
    /// çizer, WPF yalnızca kendi zeminini saydam bırakır. Desteklenmeyen
    /// Windows'ta hiçbir şey değişmez ve pencere düz Brush.Bg.Window ile kalır.
    /// Açık/koyu ayrımını ThemeManager.ApplyTitleBar'ın verdiği koyu mod bayrağı belirler.
    /// </summary>
    public static class WindowBackdrop
    {
        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

        [DllImport("dwmapi.dll")]
        private static extern int DwmExtendFrameIntoClientArea(IntPtr hwnd, ref Margins margins);

        [StructLayout(LayoutKind.Sequential)]
        private struct Margins
        {
            public int Left, Right, Top, Bottom;
        }

        private const int DWMWA_SYSTEMBACKDROP_TYPE = 38;
        private const int DWMSBT_MAINWINDOW = 2; // Mica

        /// <summary>Mica için gereken en düşük Windows 11 sürümü (22H2).</summary>
        private const int MinimumBuild = 22621;

        /// <summary>Bu pencerede Mica açık mı?</summary>
        public static bool IsMicaActive(Window window) => window.Background == Brushes.Transparent;

        /// <summary>Mica'yı açmayı dener; açılırsa true döner.</summary>
        public static bool TryApplyMica(Window window)
        {
            if (Environment.OSVersion.Version.Build < MinimumBuild)
                return false;

            var hwnd = new WindowInteropHelper(window).Handle;
            if (hwnd == IntPtr.Zero || HwndSource.FromHwnd(hwnd) is not HwndSource source)
                return false;

            try
            {
                int type = DWMSBT_MAINWINDOW;
                if (DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, ref type, sizeof(int)) != 0)
                    return false;

                // Pencere çerçevesini tüm içeriğe yay: Mica yalnız çerçevenin altında görünür
                var margins = new Margins { Left = -1, Right = -1, Top = -1, Bottom = -1 };
                DwmExtendFrameIntoClientArea(hwnd, ref margins);
            }
            catch (Exception)
            {
                return false;
            }

            if (source.CompositionTarget != null)
                source.CompositionTarget.BackgroundColor = Colors.Transparent;
            window.Background = Brushes.Transparent;
            return true;
        }
    }
}
