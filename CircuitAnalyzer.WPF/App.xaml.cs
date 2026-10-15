using System;
using System.Windows;
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

            ThemeManager.Initialize(forced);
            base.OnStartup(e);
        }
    }
}
