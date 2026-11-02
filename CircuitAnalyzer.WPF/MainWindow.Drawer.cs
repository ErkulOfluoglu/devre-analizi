using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;

namespace CircuitAnalyzer.WPF
{
    // MainWindow parçası: sol şerit ve açılan eleman listesi (DESIGN.md, "Sol şerit", "Açılan eleman listesi").
    public partial class MainWindow
    {
        /// <summary>Açık kategorinin şerit düğmesi; liste kapalıysa null.</summary>
        private ToggleButton? _openRailButton;

        /// <summary>Eleman listesi açık mı?</summary>
        public bool IsElementDrawerOpen => ElementDrawer.Visibility == Visibility.Visible;

        private (ToggleButton Rail, StackPanel Items)[] RailCategories =>
        [
            (RailPassive, DrawerPassive),
            (RailSources, DrawerSources),
            (RailDependent, DrawerDependent),
            (RailSwitches, DrawerSwitches),
            (RailMeasure, DrawerMeasure),
        ];

        // Tıklama yerine Checked/Unchecked: klavye, fare ve ekran okuyucu aynı yoldan geçer
        private void RailButton_Checked(object sender, RoutedEventArgs e)
        {
            if (sender is ToggleButton rail && rail != _openRailButton)
                OpenElementDrawer(rail);
        }

        private void RailButton_Unchecked(object sender, RoutedEventArgs e)
        {
            if (sender == _openRailButton)
                CloseElementDrawer();
        }

        /// <summary>Şeritteki bir kategorinin listesini açar (diğerleri kapanır).</summary>
        public void OpenElementDrawer(ToggleButton rail)
        {
            _openRailButton = rail;
            foreach (var (r, items) in RailCategories)
            {
                bool isOpen = r == rail;
                r.IsChecked = isOpen;
                items.Visibility = isOpen ? Visibility.Visible : Visibility.Collapsed;
            }
            TxtDrawerTitle.Text = rail.Tag as string ?? "";
            ElementDrawer.Visibility = Visibility.Visible;
        }

        /// <summary>Eleman listesini kapatır; zaten kapalıysa false döner.</summary>
        public bool CloseElementDrawer()
        {
            if (_openRailButton == null)
                return false;
            _openRailButton = null;
            foreach (var (r, _) in RailCategories)
                r.IsChecked = false;
            ElementDrawer.Visibility = Visibility.Collapsed;
            return true;
        }

        /// <summary>Listeden bir eleman seçilince liste kapanır, tuval yerleştirmeye açılır.</summary>
        private void ElementDrawer_Click(object sender, RoutedEventArgs e)
        {
            if (e.OriginalSource is ButtonBase)
                CloseElementDrawer();
        }
    }
}
