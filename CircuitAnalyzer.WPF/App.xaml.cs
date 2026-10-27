using System;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF
{
    public partial class App : Application
    {
        protected override void OnStartup(StartupEventArgs e)
        {
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
    }
}
