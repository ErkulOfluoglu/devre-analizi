using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Threading;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF
{
    // MainWindow parçası: pencerenin yerini hatırlama ve ikinci açılıştan gelen dosyayı açma.
    public partial class MainWindow
    {
        /// <summary>Simge durumuna küçültülmeden önceki hâl (büyütülmüş mü, normal mi).</summary>
        private WindowState _stateBeforeMinimize = WindowState.Normal;

        /// <summary>İkinci açılıştan gelen, henüz açılamamış dosya (son gelen geçerlidir).</summary>
        private string? _pendingForwardedFile;
        private bool _isOpeningForwardedFile;
        private DispatcherTimer? _forwardedFileTimer;

        /// <summary>
        /// Gerçek program açılışı mı? Birim testleri pencereyi App olmadan kurar, ekran testleri
        /// bayrakla açılır: ikisinde de kullanıcının ayarlarına (pencere yeri) dokunulmaz.
        /// </summary>
        private static bool IsRealLaunch =>
            Application.Current is App && !HasAnySelfTest(Environment.GetCommandLineArgs());

        // ═══════════════════════════════════════════════════════
        //  PENCERE YERİ
        // ═══════════════════════════════════════════════════════

        /// <summary>Kaydedilen yeri ekranlara sığdırıp uygular (pencere gösterilmeden önce).</summary>
        private void RestoreWindowPlacement()
        {
            StateChanged += (_, _) =>
            {
                if (WindowState != WindowState.Minimized)
                    _stateBeforeMinimize = WindowState;
            };
            if (!IsRealLaunch)
                return;

            var saved = AppSettings.MainWindowPlacement;
            if (saved == null)
            {
                // İlk açılış: varsayılan boyut küçük ekrana sığmayabilir; sığdır ve ortala
                var (bounds, minW, minH) = WindowPlacementRules.FitDefault(
                    Width, Height, MinWidth, MinHeight, SystemParameters.WorkArea);
                MinWidth = minW;
                MinHeight = minH;
                Width = bounds.Width;
                Height = bounds.Height;
                WindowStartupLocation = WindowStartupLocation.Manual;
                Left = bounds.Left;
                Top = bounds.Top;
                return;
            }

            var fit = WindowPlacementRules.Fit(saved.Left, saved.Top, saved.Width, saved.Height,
                WindowPlacementRules.GetWorkAreas(), MinWidth, MinHeight);
            if (fit is Rect r)
            {
                WindowStartupLocation = WindowStartupLocation.Manual;
                Left = r.Left;
                Top = r.Top;
                Width = r.Width;
                Height = r.Height;
            }
            // Kullanılamayan dikdörtgende varsayılan boyut ve ortalanmış konum kalır
            if (saved.Maximized)
            {
                WindowState = WindowState.Maximized;
                _stateBeforeMinimize = WindowState.Maximized;   // gösterilmeden önce StateChanged gelmeyebilir
            }
        }

        /// <summary>Kapanışta normal dikdörtgeni ve büyütülmüş olup olmadığını kaydeder.</summary>
        private void SaveWindowPlacement()
        {
            if (!IsRealLaunch)
                return;
            // Büyütülmüş ya da simge durumundayken Left/Top/Width/Height normal yeri göstermez
            Rect r = WindowState == WindowState.Normal
                ? new Rect(Left, Top, Width, Height)
                : RestoreBounds;
            if (r.IsEmpty || !double.IsFinite(r.Left) || !double.IsFinite(r.Top) ||
                !double.IsFinite(r.Width) || !double.IsFinite(r.Height) || r.Width <= 0 || r.Height <= 0)
                return;
            bool maximized = WindowState == WindowState.Maximized ||
                             (WindowState == WindowState.Minimized && _stateBeforeMinimize == WindowState.Maximized);
            AppSettings.MainWindowPlacement = new SavedWindowPlacement(r.Left, r.Top, r.Width, r.Height, maximized);
        }

        // ═══════════════════════════════════════════════════════
        //  İKİNCİ AÇILIŞ
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Program yeniden açıldığında (ör. bir .devre dosyasına çift tıklandığında) çağrılır:
        /// pencere öne gelir (simge durumundaysa eski hâline döner); dosya varsa normal açma
        /// yoluyla, kaydedilmemiş değişiklik sorusu dahil açılır.
        /// </summary>
        internal void HandleSecondInstance(string? path)
        {
            BringToFront();
            if (string.IsNullOrEmpty(path))
                return;
            _pendingForwardedFile = path;
            TryOpenForwardedFile();
        }

        private void BringToFront()
        {
            var hwnd = new WindowInteropHelper(this).Handle;
            if (WindowState == WindowState.Minimized && hwnd != IntPtr.Zero)
                ShowWindow(hwnd, SW_RESTORE);   // büyütülmüş olarak küçültüldüyse büyütülmüş döner
            if (!IsVisible)
                Show();
            Activate();
        }

        /// <summary>
        /// Bekleyen dosyayı açar. Pencerede bir soru, kart ya da ayrı bir pencere (eleman düzenleyici)
        /// açıksa, ya da önceki dosya hâlâ açılıyorsa bekler; kısa aralıklarla yeniden dener.
        /// </summary>
        private void TryOpenForwardedFile()
        {
            if (_pendingForwardedFile == null)
                return;

            var hwnd = new WindowInteropHelper(this).Handle;
            bool busy = ShouldDeferForwardedFile(
                openingAlready: _isOpeningForwardedFile,
                questionOpen: DialogOverlay.IsModal,
                cardOpen: IsModalOverlayOpen,
                ownedWindowOpen: OwnedWindows.Cast<Window>().Any(w => w.IsVisible),
                windowEnabled: hwnd == IntPtr.Zero || IsWindowEnabled(hwnd));
            if (busy)
            {
                if (_forwardedFileTimer == null)
                {
                    _forwardedFileTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(400) };
                    _forwardedFileTimer.Tick += (_, _) => TryOpenForwardedFile();
                    _forwardedFileTimer.Start();
                    TxtStatus.Text = $"{System.IO.Path.GetFileName(_pendingForwardedFile)} açık pencere kapanınca açılacak";
                }
                return;
            }

            _forwardedFileTimer?.Stop();
            _forwardedFileTimer = null;

            string path = _pendingForwardedFile;
            _pendingForwardedFile = null;
            _isOpeningForwardedFile = true;
            try
            {
                if (PromptSaveIfDirty())
                    OpenFile(path);
            }
            finally
            {
                _isOpeningForwardedFile = false;
            }
            // Soru açıkken başka bir dosya geldiyse sıradaki o
            if (_pendingForwardedFile != null)
                Dispatcher.BeginInvoke(DispatcherPriority.Background, TryOpenForwardedFile);
        }

        /// <summary>
        /// İkinci açılıştan gelen dosya şimdi açılmamalı mı (beklesin mi)? Önceki dosya hâlâ
        /// açılıyorsa, pencere içi bir soru ya da kart açıksa, ayrı bir pencere (eleman düzenleyici)
        /// açıksa ya da pencere devre dışıysa (Windows'un Aç / Kaydet / Yazdır pencereleri açıkken
        /// ana pencere devre dışı kalır; o pencere kapanınca kendi dosyasıyla devam eder) bekler.
        /// </summary>
        internal static bool ShouldDeferForwardedFile(bool openingAlready, bool questionOpen, bool cardOpen,
                                                      bool ownedWindowOpen, bool windowEnabled) =>
            openingAlready || questionOpen || cardOpen || ownedWindowOpen || !windowEnabled;

        private const int SW_RESTORE = 9;

        [DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

        [DllImport("user32.dll")]
        private static extern bool IsWindowEnabled(IntPtr hWnd);
    }
}
