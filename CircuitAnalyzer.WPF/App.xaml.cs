using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF
{
    public partial class App : Application
    {
        /// <summary>Tek kopya kilidi; program kapanana kadar tutulur (çöp toplayıcı bırakmasın).</summary>
        private static SingleInstance? _singleInstance;

        /// <summary>Pencere yüklenmeden gelen "dosyayı aç / öne gel" istekleri (null: yalnız öne gel).</summary>
        private readonly List<string?> _pendingActivations = new();

        protected override void OnStartup(StartupEventArgs e)
        {
            // Tek kopya: ikinci açılış dosyasını ilk kopyaya iletip hemen kapanır. Ekran testleri
            // (--selftest, --*-shot) buna katılmaz: kullanıcının açık programına bir şey iletmez,
            // o açıkken de çalışabilir.
            if (!CircuitAnalyzer.WPF.MainWindow.HasAnySelfTest(e.Args))
            {
                string? file = StartupArgs.FindFileArgument(e.Args);
                string? fullPath = null;
                if (file != null)
                {
                    try { fullPath = System.IO.Path.GetFullPath(file); }   // göreli yol bu kopyanın klasörüne göredir
                    catch (Exception) { fullPath = null; }
                }

                var (primary, forwarded) = SingleInstance.Acquire(
                    SingleInstance.DefaultBaseName, fullPath, TimeSpan.FromSeconds(8));
                if (forwarded)
                {
                    // Shutdown() burada StartupUri penceresinin açılmasını kesin olarak durdurmuyor
                    Environment.Exit(0);
                    return;
                }
                if (primary != null)
                {
                    _singleInstance = primary;
                    primary.StartListening(path =>
                        Dispatcher.BeginInvoke(new Action(() => DeliverActivation(path))));
                }
            }

            // Türkçe sayı ve arayüz biçimlendirmesi (ondalık virgülü)
            System.Globalization.CultureInfo.DefaultThreadCurrentCulture = TurkishNumber.Culture;
            System.Globalization.CultureInfo.DefaultThreadCurrentUICulture = TurkishNumber.Culture;
            System.Threading.Thread.CurrentThread.CurrentCulture = TurkishNumber.Culture;
            System.Threading.Thread.CurrentThread.CurrentUICulture = TurkishNumber.Culture;
            FrameworkElement.LanguageProperty.OverrideMetadata(
                typeof(FrameworkElement),
                new FrameworkPropertyMetadata(System.Windows.Markup.XmlLanguage.GetLanguage("tr-TR")));

            // Ekran testi için: --theme light|dark (kayıtlı seçimi değiştirmez)
            ThemeChoice? forced = null;
            int i = Array.FindIndex(e.Args, a => string.Equals(a, "--theme", StringComparison.OrdinalIgnoreCase));
            if (i >= 0 && i + 1 < e.Args.Length && Enum.TryParse(e.Args[i + 1], ignoreCase: true, out ThemeChoice c))
                forced = c;

            // Ekran kartı sürücüsü sorunlarına karşı: --software-render ya da ayarlardaki SoftwareRendering
            if (AppSettings.SoftwareRendering
                || Array.Exists(e.Args, a => string.Equals(a, "--software-render", StringComparison.OrdinalIgnoreCase)))
                RenderOptions.ProcessRenderMode = RenderMode.SoftwareOnly;

            ThemeManager.Initialize(forced);
            base.OnStartup(e);
        }

        /// <summary>İkinci açılıştan gelen istek: pencere hazırsa hemen işlenir, değilse sıraya girer.</summary>
        private void DeliverActivation(string? path)
        {
            if (MainWindow is CircuitAnalyzer.WPF.MainWindow window && window.IsLoaded)
                window.HandleSecondInstance(path);
            else
                _pendingActivations.Add(path);
        }

        /// <summary>Pencere yüklenince bekleyen istekleri alır (ve sırayı boşaltır).</summary>
        internal IReadOnlyList<string?> TakePendingActivations()
        {
            var list = _pendingActivations.ToArray();
            _pendingActivations.Clear();
            return list;
        }

        protected override void OnExit(ExitEventArgs e)
        {
            _singleInstance?.Dispose();
            _singleInstance = null;
            base.OnExit(e);
        }
    }
}
