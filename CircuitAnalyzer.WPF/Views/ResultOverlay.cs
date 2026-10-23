using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Devre çizimi üzerine düğüm numaraları ve çözüm sonuçlarını yerleştirir ("Işık" tasarım sistemi).
    ///
    ///   • Düğüm rozeti:  "②"  veya çözümden sonra  "② 8 V"
    ///   • Eleman akımı:  "4 mA (1→2)"   (elemanın yanında)
    ///   • Prob değeri:   "VP1: 8 V"
    ///
    /// Etiketler fare olaylarını engellemez (IsHitTestVisible = false) ve
    /// devre her değiştiğinde temizlenir — eski sonuç yanlış anlaşılmasın.
    /// </summary>
    public sealed class ResultOverlay
    {
        private readonly Canvas _canvas;
        private readonly List<UIElement> _items = new();

        private NetlistResult? _lastNetlist;
        private IEnumerable<CircuitElement>? _lastElements;
        private IEnumerable<Wire>? _lastWires;
        private AnalysisResponseDto? _lastResponse;

        public ResultOverlay(Canvas canvas)
        {
            _canvas = canvas;
            ThemeManager.ThemeChanged += (_, _) => Refresh();
        }

        public void Clear()
        {
            foreach (var item in _items)
                _canvas.Children.Remove(item);
            _items.Clear();
            _lastNetlist = null;
            _lastElements = null;
            _lastWires = null;
            _lastResponse = null;
        }

        private void Refresh()
        {
            if (_lastResponse != null && _lastNetlist != null && _lastElements != null && _lastWires != null)
            {
                ShowResults(_lastNetlist, _lastElements, _lastWires, _lastResponse);
            }
            else if (_lastNetlist != null && _lastWires != null)
            {
                ShowNodeNumbers(_lastNetlist, _lastWires);
            }
        }

        /// <summary>Sadece düğüm numaralarını gösterir (çözüm öncesi).</summary>
        public void ShowNodeNumbers(NetlistResult netlist, IEnumerable<Wire> wires)
        {
            foreach (var item in _items)
                _canvas.Children.Remove(item);
            _items.Clear();

            _lastNetlist = netlist;
            _lastWires = wires;
            _lastElements = null;
            _lastResponse = null;

            foreach (var (node, anchor) in NodeAnchors(netlist, wires))
                AddNodeBadge(anchor, node, null);
        }

        /// <summary>Düğüm gerilimleri, eleman akımları ve prob değerlerini gösterir.</summary>
        public void ShowResults(
            NetlistResult netlist,
            IEnumerable<CircuitElement> elements,
            IEnumerable<Wire> wires,
            AnalysisResponseDto response)
        {
            foreach (var item in _items)
                _canvas.Children.Remove(item);
            _items.Clear();

            _lastNetlist = netlist;
            _lastElements = elements;
            _lastWires = wires;
            _lastResponse = response;

            var results = response.Results;

            foreach (var (node, anchor) in NodeAnchors(netlist, wires))
            {
                string? voltage = results.NodeVoltages.TryGetValue(node.ToString(), out var nv)
                    ? EngFormat.Format(nv.Value, "V")
                    : null;
                AddNodeBadge(anchor, node, voltage);
            }

            var probeValues = results.ProbeResults.ToDictionary(p => p.ProbeId);

            foreach (var element in elements)
            {
                if (element is JunctionElement)
                    continue;

                if (element is TestProbe probe)
                {
                    if (probeValues.TryGetValue(probe.Id, out var pr))
                        AddLabel(BelowOrRight(probe), $"{probe.Id}: {EngFormat.Format(pr.Value, pr.Unit)}",
                                 "Brush.Overlay.Probe", bold: true);
                    continue;
                }

                if (results.ElementCurrents.TryGetValue(element.Id, out var current))
                {
                    var (value, direction) = CurrentDisplay.Format(element.Id, current);
                    AddLabel(BelowOrRight(element), $"{value} ({direction})", "Brush.Overlay.Current", bold: false);
                }
            }
        }

        // ═══════════════════════════════════════════════════════
        //  Konum hesapları
        // ═══════════════════════════════════════════════════════

        private static IEnumerable<(int Node, Point Anchor)> NodeAnchors(
            NetlistResult netlist, IEnumerable<Wire> wires)
        {
            var wirePoints = new Dictionary<int, List<Point>>();
            foreach (var wire in wires)
            {
                if (!netlist.NodeMap.TryGetValue(wire.StartPin, out int wireNode))
                    continue;
                if (!wirePoints.TryGetValue(wireNode, out var list))
                    wirePoints[wireNode] = list = new List<Point>();
                if (wire.Visual != null)
                    list.AddRange(wire.Visual.Points);
            }

            foreach (var (node, pins) in netlist.NodePins.OrderBy(kv => kv.Key))
            {
                // GND gösterilmez; tek pinlik düğüm = henüz bağlanmamış uç
                if (node == 0 || pins.Count < 2)
                    continue;
                var candidates = pins
                    .Where(p => p.Owner is not TestProbe and not GroundElement and not JunctionElement)
                    .Select(p => p.AbsolutePosition)
                    .ToList();
                if (candidates.Count == 0)
                {
                    var junctionCandidates = pins
                        .Where(p => p.Owner is JunctionElement)
                        .Select(p => p.AbsolutePosition)
                        .ToList();
                    if (junctionCandidates.Count < 2)
                        continue; // Sadece prob veya tek bağlantı noktasından oluşan düğüm
                    candidates.AddRange(junctionCandidates);
                }
                if (wirePoints.TryGetValue(node, out var corners))
                    candidates.AddRange(corners);
                var anchor = candidates
                    .OrderBy(p => p.Y)
                    .ThenBy(p => p.X)
                    .First();
                yield return (node, anchor);
            }
        }

        private static Point BelowOrRight(CircuitElement element)
        {
            double cx = element.Position.X + element.VisualWidth / 2;
            double cy = element.Position.Y + element.VisualHeight / 2;
            bool vertical = Math.Abs(element.Rotation % 180 - 90) < 1;
            return vertical
                ? new Point(cx + element.VisualHeight / 2 + 14, cy - 8)
                : new Point(cx - element.VisualWidth / 2, cy + element.VisualHeight / 2 + 2);
        }

        // ═══════════════════════════════════════════════════════
        //  Görseller
        // ═══════════════════════════════════════════════════════

        private void AddNodeBadge(Point pinPosition, int node, string? voltage)
        {
            if (voltage == null)
            {
                // Çözüm öncesi: yalnızca düğüm numarası rozeti
                var nodeBadge = new Border
                {
                    CornerRadius = new CornerRadius(999),
                    Padding = new Thickness(6, 2, 6, 2)
                };
                nodeBadge.SetResourceReference(Border.BackgroundProperty, "Brush.Accent.Soft");

                var nodeTb = new TextBlock
                {
                    Text = node.ToString(),
                    FontSize = 12,
                    FontWeight = FontWeights.SemiBold
                };
                nodeTb.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Accent.SoftText");
                nodeTb.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
                nodeBadge.Child = nodeTb;

                Place(nodeBadge, new Point(pinPosition.X + 4, pinPosition.Y - 20));
            }
            else
            {
                // Çözüm sonrası: düğüm numarası + gerilim değeri
                var panel = new StackPanel { Orientation = Orientation.Horizontal };

                var nodePill = new Border
                {
                    CornerRadius = new CornerRadius(999),
                    Padding = new Thickness(5, 1, 5, 1),
                    Margin = new Thickness(0, 0, 4, 0)
                };
                nodePill.SetResourceReference(Border.BackgroundProperty, "Brush.Accent.Soft");

                var nodeTb = new TextBlock
                {
                    Text = node.ToString(),
                    FontSize = 12,
                    FontWeight = FontWeights.SemiBold
                };
                nodeTb.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Accent.SoftText");
                nodeTb.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
                nodePill.Child = nodeTb;
                panel.Children.Add(nodePill);

                var voltTb = new TextBlock
                {
                    Text = voltage,
                    FontSize = 12,
                    FontWeight = FontWeights.SemiBold,
                    VerticalAlignment = VerticalAlignment.Center,
                    Margin = new Thickness(0, 0, 2, 0)
                };
                voltTb.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Overlay.NodeText");
                voltTb.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
                panel.Children.Add(voltTb);

                var badge = new Border
                {
                    Child = panel,
                    CornerRadius = new CornerRadius(999),
                    Padding = new Thickness(2, 2, 6, 2)
                };
                badge.SetResourceReference(Border.BackgroundProperty, "Brush.Overlay.NodeBg");

                Place(badge, new Point(pinPosition.X + 4, pinPosition.Y - 20));
            }
        }

        private void AddLabel(Point position, string text, string foregroundToken, bool bold)
        {
            var label = new Border
            {
                CornerRadius = new CornerRadius(999),
                Padding = new Thickness(6, 2, 6, 2),
            };
            label.SetResourceReference(Border.BackgroundProperty, "Brush.Overlay.BadgeBg");

            var tb = new TextBlock
            {
                Text = text,
                FontSize = 12,
                FontWeight = bold ? FontWeights.Bold : FontWeights.SemiBold,
            };
            tb.SetResourceReference(TextBlock.ForegroundProperty, foregroundToken);
            tb.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            label.Child = tb;

            Place(label, position);
        }

        private void Place(FrameworkElement item, Point position)
        {
            item.IsHitTestVisible = false;
            Canvas.SetLeft(item, position.X);
            Canvas.SetTop(item, position.Y);
            Panel.SetZIndex(item, 1000);
            _canvas.Children.Add(item);
            _items.Add(item);
        }
    }
}
