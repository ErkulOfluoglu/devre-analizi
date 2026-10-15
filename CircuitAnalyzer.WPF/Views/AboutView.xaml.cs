using System;
using System.Diagnostics;
using System.Windows.Controls;
using System.Windows.Navigation;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Program hakkında, sorumluluk reddi, lisans ve açık kaynak bileşenler görünümü.
    /// </summary>
    public partial class AboutView : UserControl
    {
        public AboutView()
        {
            InitializeComponent();

            TxtVersion.Text = $"Sürüm {AppInfo.Version}";
            TxtLicense.Text = $"MIT Lisansı · © 2026 {AppInfo.LicenseHolder}";
        }

        private void Hyperlink_RequestNavigate(object sender, RequestNavigateEventArgs e)
        {
            try
            {
                Process.Start(new ProcessStartInfo(e.Uri.AbsoluteUri) { UseShellExecute = true });
            }
            catch
            {
                // Tarayıcı açılamazsa sessizce geç
            }
            e.Handled = true;
        }
    }
}
