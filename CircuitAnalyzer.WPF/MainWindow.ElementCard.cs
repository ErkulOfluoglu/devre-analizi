using System;
using System.Linq;
using System.Windows;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF
{
    // MainWindow parçası: akım ışığı ve seçili elemanın cam kartı (DESIGN.md, "Akım ışığı").
    // Çözümden sonra tek bir eleman seçilince kolu yanar, yanında değerleri gösteren kart açılır.
    // Alıştırma modunda sonuçlar gizli olduğundan ikisi de görünmez.
    public partial class MainWindow
    {
        private const double CardGap = 14;

        /// <summary>Kartta gösterilen eleman (kart kapalıysa null).</summary>
        internal CircuitElement? ElementCardTarget { get; private set; }

        /// <summary>Seçim ya da çözüm değişince ışığı ve kartı günceller.</summary>
        internal void UpdateCurrentFlowAndCard()
        {
            var selected = _selection.Elements.Count == 1 ? _selection.PrimaryElement : null;
            _overlay?.HighlightBranch(selected);

            var response = _overlay?.Response;
            var netlist = _overlay?.Netlist;
            ElementReadout? readout = null;
            if (selected != null && response?.Results != null && netlist != null && !AnalysisPanel.IsShowingPractice)
            {
                bool isDc = string.Equals(response.Mode, AnalysisModes.Dc, StringComparison.OrdinalIgnoreCase);
                readout = ElementReadoutBuilder.Build(selected, _elements, netlist.NodeMap, response.Results, isDc);
            }

            if (readout == null)
            {
                ElementCard.Visibility = Visibility.Collapsed;
                ElementCardTarget = null;
                return;
            }

            TxtCardName.Text = readout.Name;
            TxtCardValue.Text = readout.Value ?? "";
            TxtCardCurrent.Text = readout.Current;
            TxtCardDirection.Text = readout.Direction;
            TxtCardVoltage.Text = readout.Voltage ?? "";
            LblCardVoltage.Visibility = TxtCardVoltage.Visibility = readout.Voltage != null ? Visibility.Visible : Visibility.Collapsed;
            TxtCardPower.Text = readout.Power ?? "";
            LblCardPower.Visibility = TxtCardPower.Visibility = readout.Power != null ? Visibility.Visible : Visibility.Collapsed;
            TxtCardBalance.Text = readout.NodeBalance ?? "";
            CardBalanceRow.Visibility = readout.NodeBalance != null ? Visibility.Visible : Visibility.Collapsed;
            SubscriptText.Apply(TxtCardBalance);

            ElementCardTarget = selected;
            ElementCard.Visibility = Visibility.Visible;
            PositionElementCard();
        }

        /// <summary>Kartı elemanın sağına (sığmazsa soluna) koyar; kaydırma ve yakınlaştırmada izler.</summary>
        private void PositionElementCard()
        {
            if (ElementCardTarget is not { } element || ElementCard.Visibility != Visibility.Visible)
                return;

            ElementCard.UpdateLayout();
            Rect bounds = SelectionModel.GetElementBounds(element);
            Point topLeft, bottomRight;
            try
            {
                topLeft = CircuitCanvas.TranslatePoint(bounds.TopLeft, CanvasLayer);
                bottomRight = CircuitCanvas.TranslatePoint(bounds.BottomRight, CanvasLayer);
            }
            catch (InvalidOperationException)
            {
                return; // henüz ekrana yerleşmemiş
            }

            double width = ElementCard.ActualWidth > 0 ? ElementCard.ActualWidth : ElementCard.Width;
            double height = ElementCard.ActualHeight;
            double areaWidth = CanvasLayer.ActualWidth;
            double areaHeight = CanvasLayer.ActualHeight;

            double left = bottomRight.X + CardGap;
            if (left + width > areaWidth - 8)
                left = topLeft.X - CardGap - width;
            double top = topLeft.Y + (bottomRight.Y - topLeft.Y) / 2 - height / 2;
            left = Math.Max(8, Math.Min(left, areaWidth - width - 8));
            top = Math.Max(8, Math.Min(top, areaHeight - height - 8));
            ElementCard.Margin = new Thickness(left, top, 0, 0);
        }
    }
}
