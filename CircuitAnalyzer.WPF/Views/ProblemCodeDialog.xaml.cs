using System.Globalization;
using System.Windows;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Soru kodu ile alıştırma sorusu açma diyaloğu.
    /// </summary>
    public partial class ProblemCodeDialog : Window
    {
        public int? Code { get; private set; }

        public ProblemCodeDialog()
        {
            InitializeComponent();
            ThemeManager.ApplyTitleBar(this);
            Loaded += (_, _) => TxtCode.Focus();
        }

        public static bool TryParseCode(string? text, out int code, out string? error)
        {
            code = 0;
            string trimmed = text?.Trim() ?? "";
            if (int.TryParse(trimmed, NumberStyles.Integer, CultureInfo.InvariantCulture, out int parsed)
                && ProblemGenerator.IsValidCode(parsed))
            {
                code = parsed;
                error = null;
                return true;
            }

            error = "1000 ile 9999 arasında bir sayı yazın.";
            return false;
        }

        private void BtnOpen_Click(object sender, RoutedEventArgs e)
        {
            if (TryParseCode(TxtCode.Text, out int parsedCode, out string? error))
            {
                Code = parsedCode;
                DialogResult = true;
            }
            else
            {
                TxtError.Text = error ?? "1000 ile 9999 arasında bir sayı yazın.";
                TxtError.Visibility = Visibility.Visible;
                TxtCode.Focus();
                TxtCode.SelectAll();
            }
        }

        private void BtnCancel_Click(object sender, RoutedEventArgs e)
        {
            DialogResult = false;
        }
    }
}
