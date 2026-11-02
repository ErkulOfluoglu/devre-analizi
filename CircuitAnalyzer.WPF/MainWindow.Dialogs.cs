using CircuitAnalyzer.WPF.Views;

namespace CircuitAnalyzer.WPF
{
    // MainWindow parçası: uyarı ve bilgi mesajları. Windows'un ayrı mesaj kutusu yerine
    // uygulamanın içinde, onun görünüşüyle açılır (DialogOverlay.ShowModal); "Tamam"a basılana kadar bekler.
    public partial class MainWindow
    {
        /// <summary>Tek düğmeli ("Tamam") pencere içi mesaj.</summary>
        internal void Inform(string title, string message, DialogKind kind = DialogKind.Info) =>
            DialogOverlay.ShowModal(title, message, kind, new[] { new DialogButton("ok", "Tamam", IsPrimary: true) });
    }
}
