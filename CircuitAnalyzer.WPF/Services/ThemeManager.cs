using System;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Windows;
using System.Windows.Interop;
using Microsoft.Win32;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>Kullanıcının tema seçimi.</summary>
    public enum ThemeChoice
    {
        /// <summary>Windows'un açık/koyu ayarını izler (varsayılan).</summary>
        System,
        Light,
        Dark,
    }

    /// <summary>
    /// Açık ("Işık") / koyu ("Gece") tema.
    ///
    /// Uygulama kaynaklarında renk sözlüğü (Themes/Light.xaml ya da Dark.xaml)
    /// ilk sırada durur; tema değişince yalnızca o sözlük değiştirilir.
    /// Görünümler renkleri DynamicResource ile kullandığı için her şey
    /// kendiliğinden yeniden boyanır. Seçim %AppData%\CircuitAnalyzer\settings.json
    /// dosyasında saklanır.
    /// </summary>
    public static class ThemeManager
    {
        private static readonly Uri LightUri;
        private static readonly Uri DarkUri;

        static ThemeManager()
        {
            if (!UriParser.IsKnownScheme("pack"))
                _ = System.IO.Packaging.PackUriHelper.UriSchemePack;
            LightUri = new("pack://application:,,,/CircuitAnalyzer;component/Themes/Light.xaml");
            DarkUri = new("pack://application:,,,/CircuitAnalyzer;component/Themes/Dark.xaml");
        }

        public static ThemeChoice Choice { get; private set; } = ThemeChoice.System;

        /// <summary>Şu an koyu tema mı gösteriliyor (Sistem seçiliyse Windows ayarına göre).</summary>
        public static bool IsDark { get; private set; }

        public static event EventHandler? ThemeChanged;

        /// <summary>Ayar dosyası — AppSettings.SettingsPath ile aynı (testler başka bir yol verebilir).</summary>
        public static string SettingsPath
        {
            get => AppSettings.SettingsPath;
            set => AppSettings.SettingsPath = value;
        }

        /// <summary>Uygulama açılışında: kayıtlı seçimi yükler ve uygular.</summary>
        public static void Initialize(ThemeChoice? overrideChoice = null)
        {
            Choice = overrideChoice ?? LoadChoice();
            ApplyCore();
            SystemEvents.UserPreferenceChanged += (_, e) =>
            {
                // Windows'ta açık/koyu değişince "Sistem" seçiliyse takip et
                if (e.Category == UserPreferenceCategory.General && Choice == ThemeChoice.System)
                    Application.Current?.Dispatcher.BeginInvoke(ApplyCore);
            };
        }

        /// <summary>Tema seçimini değiştirir, kaydeder ve uygular.</summary>
        public static void SetChoice(ThemeChoice choice)
        {
            Choice = choice;
            SaveChoice(choice);
            ApplyCore();
        }

        private static void ApplyCore()
        {
            IsDark = Choice switch
            {
                ThemeChoice.Dark => true,
                ThemeChoice.Light => false,
                _ => SystemPrefersDark(),
            };

            var app = Application.Current;
            if (app != null)
            {
                var dicts = app.Resources.MergedDictionaries;
                var palette = new ResourceDictionary { Source = IsDark ? DarkUri : LightUri };
                int index = dicts.ToList().FindIndex(d =>
                    d.Source != null && (d.Source.OriginalString.EndsWith("Light.xaml", StringComparison.OrdinalIgnoreCase)
                                         || d.Source.OriginalString.EndsWith("Dark.xaml", StringComparison.OrdinalIgnoreCase)));
                if (index >= 0)
                    dicts[index] = palette;
                else
                    dicts.Insert(0, palette);

                foreach (Window w in app.Windows)
                    ApplyTitleBar(w);
            }
            ThemeChanged?.Invoke(null, EventArgs.Empty);
        }

        /// <summary>Windows "uygulamalar için koyu mod" açık mı?</summary>
        public static bool SystemPrefersDark()
        {
            try
            {
                using var key = Registry.CurrentUser.OpenSubKey(
                    @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");
                return key?.GetValue("AppsUseLightTheme") is int v && v == 0;
            }
            catch (Exception)
            {
                return false;
            }
        }

        // ── Başlık çubuğu: koyu temada Windows'un başlık çubuğu da koyu olsun ──

        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

        private const int DWMWA_USE_IMMERSIVE_DARK_MODE = 20;

        /// <summary>Pencerenin başlık çubuğunu temaya uydurur (pencere açıldıktan sonra da çağrılabilir).</summary>
        public static void ApplyTitleBar(Window window)
        {
            void Apply()
            {
                try
                {
                    var hwnd = new WindowInteropHelper(window).Handle;
                    if (hwnd == IntPtr.Zero)
                        return;
                    int dark = IsDark ? 1 : 0;
                    DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ref dark, sizeof(int));
                }
                catch (Exception)
                {
                    // Eski Windows: başlık çubuğu açık kalır, sorun değil
                }
            }

            if (new WindowInteropHelper(window).Handle == IntPtr.Zero)
                window.SourceInitialized += (_, _) => Apply();
            else
                Apply();
        }

        // ── Ayar dosyası (AppSettings: diğer ayarlar korunur) ──

        private static ThemeChoice LoadChoice()
            => Enum.TryParse(AppSettings.Theme, ignoreCase: true, out ThemeChoice c) ? c : ThemeChoice.System;

        private static void SaveChoice(ThemeChoice choice) => AppSettings.Theme = choice.ToString();
    }
}
