using System.Linq;
using System.Windows;
using System.Windows.Controls;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF
{
    // MainWindow parçası: bağımlı kaynaklar — kontrol eden elemanın işaretlenmesi ve çözmeden önce denetim.
    public partial class MainWindow
    {
        /// <summary>Kontrol edilen elemanların üzerindeki işaret görselleri (tuvalin çocukları; her yenilemede baştan kurulur).</summary>
        private readonly List<UIElement> _controlMarkers = new();

        /// <summary>Şu an tuvalde görünen kontrol işaretleri (testler için).</summary>
        internal IReadOnlyList<UIElement> ControlMarkerVisuals => _controlMarkers;

        /// <summary>
        /// Bağımlı kaynakların kontrol ettiği elemanlara işaretleri yeniden çizer:
        /// gerilim kontrolünde "+ −" ve "V_X", akım kontrolünde ok ve "I_X".
        /// Devre her değiştiğinde (ekleme, silme, döndürme, geri al, yapıştırma, düzenleme)
        /// ve eleman sürüklenirken çağrılır; hep sıfırdan kurulduğu için bayat işaret kalmaz.
        /// </summary>
        private void RefreshControlMarkers()
        {
            foreach (var marker in _controlMarkers)
                CircuitCanvas.Children.Remove(marker);
            _controlMarkers.Clear();

            var dependents = _elements.OfType<DependentSource>().ToList();
            if (dependents.Count == 0)
                return;

            // Gerilim kontrolü olan elemanlar (aynı elemanın akımı da kontrol ediliyorsa ok karşı yüze çizilir)
            var voltageControlled = new HashSet<CircuitElement>(
                dependents.Where(d => d.IsVoltageControlled)
                          .Select(FindControlElement)
                          .OfType<CircuitElement>());

            // Aynı eleman için aynı büyüklük (V ya da I) tek kez işaretlenir; ilk bağımlı kaynak belirler
            var drawn = new HashSet<(CircuitElement Element, bool Voltage)>();
            foreach (var dep in dependents)
            {
                var control = FindControlElement(dep);
                if (control == null)
                    continue;

                bool voltage = dep.IsVoltageControlled;
                if (!drawn.Add((control, voltage)))
                    continue;

                bool otherSide = !voltage && voltageControlled.Contains(control);
                foreach (var marker in ControlMarkers.Create(control, voltage, dep.ControlReversed, otherSide))
                {
                    CircuitCanvas.Children.Add(marker);
                    _controlMarkers.Add(marker);
                }
            }
        }

        /// <summary>Bağımlı kaynağın kontrol ettiği elemanı döndürür; seçilmemişse ya da geçersizse null.</summary>
        private CircuitElement? FindControlElement(DependentSource dep)
        {
            if (string.IsNullOrWhiteSpace(dep.ControlElementId))
                return null;
            var control = _elements.FirstOrDefault(e =>
                string.Equals(e.Id, dep.ControlElementId, StringComparison.OrdinalIgnoreCase));
            return control != null && control != dep && DependentSource.CanBeControl(control) ? control : null;
        }

        /// <summary>
        /// Çözmeden önce bağımlı kaynakların kontrol elemanlarını denetler. Sorun varsa pencere içi
        /// diyalog kartında Türkçe mesaj gösterir ve false döner (çözücüye gidilmez).
        /// </summary>
        internal bool ValidateDependentSources()
        {
            string? message = NetlistBuilder.ValidateDependentSources(_elements);
            if (message == null)
                return true;

            var body = new TextBlock
            {
                Text = message + ".\n\nBağımlı kaynağa çift tıklayıp “Kontrol eden eleman” listesinden devredeki bir eleman seçin.",
                TextWrapping = TextWrapping.Wrap,
                FontSize = 13.5,
            };
            body.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Body");
            DialogOverlay.Show("Bağımlı kaynak eksik", body, width: 440);
            TxtStatus.Text = message;
            return false;
        }
    }
}
