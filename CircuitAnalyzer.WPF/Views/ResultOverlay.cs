using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
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
        private readonly List<(FrameworkElement Badge, Point Pin)> _badges = new();
        private readonly CurrentFlowLayer _flow;
        private CircuitElement? _selected;

        private NetlistResult? _lastNetlist;
        private IEnumerable<CircuitElement>? _lastElements;
        private IEnumerable<Wire>? _lastWires;
        private AnalysisResponseDto? _lastResponse;

        public ResultOverlay(Canvas canvas)
        {
            _canvas = canvas;
            _flow = new CurrentFlowLayer(canvas);
            ThemeManager.ThemeChanged += (_, _) => Refresh();
        }

        /// <summary>Sonuçlar gösterildi, silindi ya da yenilendi (cam kart buna göre güncellenir).</summary>
        public event EventHandler? Changed;

        /// <summary>Gösterilen çözüm (yoksa null) ve ona ait düğüm haritası.</summary>
        public AnalysisResponseDto? Response => _lastResponse;
        public NetlistResult? Netlist => _lastNetlist;

        /// <summary>Akım ışığı: seçili elemanın kolu yanar (null: söner). DC ve AC (fazör) çözümde.</summary>
        public void HighlightBranch(CircuitElement? selected)
        {
            _selected = selected;
            _flow.Show(selected);
        }

        public CurrentFlowLayer Flow => _flow;

        /// <summary>Görünen sonuç etiketlerinin tuval koordinatlarındaki kutuları ("sığdır" bunları da katar).</summary>
        public IReadOnlyList<Rect> ItemBounds()
        {
            var list = new List<Rect>();
            foreach (var item in _items)
            {
                if (item is not FrameworkElement fe)
                    continue;
                double left = Canvas.GetLeft(fe);
                double top = Canvas.GetTop(fe);
                if (double.IsNaN(left) || double.IsNaN(top))
                    continue;
                if (!fe.IsMeasureValid)
                    fe.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
                var size = fe.DesiredSize;
                if (size.Width <= 0 || size.Height <= 0)
                    continue;
                list.Add(new Rect(left, top, size.Width, size.Height));
            }
            return list;
        }

        public void Clear()
        {
            _flow.Clear();
            foreach (var item in _items)
                _canvas.Children.Remove(item);
            _items.Clear();
            _badges.Clear();
            _lastNetlist = null;
            _lastElements = null;
            _lastWires = null;
            _lastResponse = null;
            Changed?.Invoke(this, EventArgs.Empty);
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
            _flow.Clear();
            foreach (var item in _items)
                _canvas.Children.Remove(item);
            _items.Clear();
            _badges.Clear();

            _lastNetlist = netlist;
            _lastWires = wires;
            _lastElements = null;
            _lastResponse = null;

            foreach (var (node, anchor) in NodeAnchors(netlist, wires))
                AddNodeBadge(anchor, node, null);
            Changed?.Invoke(this, EventArgs.Empty);
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
            _badges.Clear();

            _lastNetlist = netlist;
            _lastElements = elements;
            _lastWires = wires;
            _lastResponse = response;

            var results = response.Results;
            var elementCurrents = results?.ElementCurrents ?? new Dictionary<string, ElementCurrentDto>();
            var nodeVoltages = results?.NodeVoltages ?? new Dictionary<string, NodeVoltageDto>();
            var probeList = results?.ProbeResults ?? new List<ProbeResultDto>();

            // Akım ışığı: DC'de akar, AC'de yavaşlatılmış salınır. Etiketlerin altında kalsın diye önce
            bool isDc = string.Equals(response.Mode, AnalysisModes.Dc, StringComparison.OrdinalIgnoreCase);
            bool isAc = string.Equals(response.Mode, AnalysisModes.AcPhasor, StringComparison.OrdinalIgnoreCase);
            if (isDc || isAc)
            {
                _flow.Prepare(elements, wires, netlist, elementCurrents, isAc);
                _flow.Show(_selected != null && elements.Contains(_selected) ? _selected : null);
            }
            else
            {
                _flow.Clear();
            }

            foreach (var (node, anchor) in NodeAnchors(netlist, wires))
            {
                string? voltage = nodeVoltages.TryGetValue(node.ToString(), out var nv) && nv != null
                    ? EngFormat.Format(nv.Value, "V")
                    : null;
                AddNodeBadge(anchor, node, voltage);
            }

            var probeValues = probeList.ToDictionary(p => p.ProbeId);

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

                if (element is TransformerElement tfEl)
                {
                    var tf = response.Transformer ?? results?.Transformer;
                    if (tf != null && (string.IsNullOrEmpty(tf.Id) || string.Equals(tf.Id, tfEl.Id, StringComparison.OrdinalIgnoreCase)))
                    {
                        var (pPos, sPos) = TransformerCurrentAnchors(tfEl);
                        if (tf.I1 != null)
                        {
                            var i1Val = ResultValue.FromComplex(tf.I1);
                            AddLabel(pPos, $"I₁: {EngFormat.Format(i1Val, "A")}", "Brush.Overlay.Current", bold: false);
                        }
                        if (tf.I2 != null)
                        {
                            var i2Val = ResultValue.FromComplex(tf.I2);
                            AddLabel(sPos, $"I₂: {EngFormat.Format(i2Val, "A")}", "Brush.Overlay.Current", bold: false);
                        }
                    }
                    continue;
                }

                if (element is ThreePhaseLoad loadEl)
                {
                    var tp = response.ThreePhaseResult;
                    if (tp != null && tp.LineCurrents != null)
                    {
                        if (tp.LineCurrents.TryGetValue("R", out var ir))
                        {
                            var irVal = ResultValue.FromComplex(ir);
                            AddLabel(ThreePhaseLoadPinAnchor(loadEl.Pins[0]), $"I_R: {EngFormat.Format(irVal, "A")}", "Brush.Overlay.Current", bold: false);
                        }
                        if (tp.LineCurrents.TryGetValue("S", out var isCur))
                        {
                            var isVal = ResultValue.FromComplex(isCur);
                            AddLabel(ThreePhaseLoadPinAnchor(loadEl.Pins[1]), $"I_S: {EngFormat.Format(isVal, "A")}", "Brush.Overlay.Current", bold: false);
                        }
                        if (tp.LineCurrents.TryGetValue("T", out var it))
                        {
                            var itVal = ResultValue.FromComplex(it);
                            AddLabel(ThreePhaseLoadPinAnchor(loadEl.Pins[2]), $"I_T: {EngFormat.Format(itVal, "A")}", "Brush.Overlay.Current", bold: false);
                        }

                        bool nConnected = netlist.NodeMap.TryGetValue(loadEl.Pins[3], out int nNode) &&
                                          netlist.NodePins.TryGetValue(nNode, out var nPins) && nPins.Count >= 2;
                        if (nConnected && tp.NeutralCurrent != null)
                        {
                            var inVal = ResultValue.FromComplex(tp.NeutralCurrent);
                            AddLabel(ThreePhaseLoadPinAnchor(loadEl.Pins[3]), $"I_N: {EngFormat.Format(inVal, "A")}", "Brush.Overlay.Current", bold: false);
                        }
                    }
                    continue;
                }

                if (element is Wattmeter wm)
                {
                    var wmRes = response.WattmeterResults?.FirstOrDefault(w => string.Equals(w.Id, wm.Id, StringComparison.OrdinalIgnoreCase));
                    if (wmRes != null)
                    {
                        AddLabel(BelowOrRight(wm), $"P = {EngFormat.Format(wmRes.P, "W")}", "Brush.Overlay.Current", bold: true);
                    }
                    continue;
                }

                if (element is Diode diode)
                {
                    // Akım ve durum tek satırda: iki satır alt alta konunca diyotun kendi adını
                    // ("D2") ve paralel koldaki diyotun model yazısını ("Si") örtüyordu.
                    string? currentText = null;
                    if (elementCurrents.TryGetValue(diode.Id, out var diodeCurrent) && diodeCurrent != null)
                    {
                        var (value, direction) = CurrentDisplay.Format(diode.Id, diodeCurrent);
                        currentText = string.IsNullOrEmpty(direction) ? value : $"{value} ({direction})";
                    }

                    var diodeRes = response.DiodeResults?.FirstOrDefault(d => string.Equals(d.Id, diode.Id, StringComparison.OrdinalIgnoreCase));
                    string? stateText = diodeRes?.State?.Trim().ToUpperInvariant() switch
                    {
                        "ON" => "iletimde",
                        "ZENER" => "ters iletimde (V_Z)",
                        "OFF" => "yalıtımda",
                        _ => null
                    };
                    if (currentText != null || stateText != null)
                        AddDiodeLabel(DiodeLabelAnchor(diode), currentText, stateText,
                            stacked: Math.Abs(diode.Rotation % 180 - 90) < 1);
                    continue;
                }

                // Kenetleyicide kondansatör üstünde V_C (varsa akımla birlikte) tek etikette gösterilir
                if (element is Capacitor cap && response.WaveformResult?.Clamper is { } clamper)
                {
                    string vcText = $"V_C = {AnalysisPanel.FormatDiodeVoltage(Math.Abs(clamper.VC))}";
                    string labelText = vcText;
                    if (elementCurrents.TryGetValue(cap.Id, out var capCurrent) && capCurrent != null)
                    {
                        var (value, direction) = CurrentDisplay.Format(cap.Id, capCurrent);
                        string curText = string.IsNullOrEmpty(direction) ? value : $"{value} ({direction})";
                        labelText = $"{vcText} · {curText}";
                    }
                    // Yatay kondansatörün kimliği ("C1") gövdenin hemen altında yazılı; uzun V_C
                    // etiketi aynı yere konunca kimliği örtüyordu, bu yüzden bir satır aşağı iner.
                    var capAnchor = BelowOrRight(cap);
                    if (Math.Abs(cap.Rotation % 180 - 90) >= 1)
                        capAnchor.Offset(0, 14);
                    AddLabel(capAnchor, labelText, "Brush.Overlay.Current", bold: false);
                    continue;
                }

                if (elementCurrents.TryGetValue(element.Id, out var current) && current != null)
                {
                    var (value, direction) = CurrentDisplay.Format(element.Id, current);
                    string text = string.IsNullOrEmpty(direction) ? value : $"{value} ({direction})";
                    AddLabel(BelowOrRight(element), text, "Brush.Overlay.Current", bold: false);
                }
            }
            ResolveBadgeCollisions();
            Changed?.Invoke(this, EventArgs.Empty);
        }

        /// <summary>
        /// Düğüm rozeti varsayılan olarak ucun sağ üstünde durur. Kısa dikey kollarda (Millman gibi)
        /// bu yer, elemanın akım etiketine denk gelip onu örtüyordu. Çakışan rozet sırayla sol üst,
        /// sağ alt ve sol alt yerlerini dener; hepsi doluysa varsayılanda kalır.
        /// </summary>
        private void ResolveBadgeCollisions()
        {
            if (_badges.Count == 0)
                return;
            var occupied = new List<Rect>();
            foreach (var item in _items)
            {
                if (item is FrameworkElement fe && !_badges.Any(b => ReferenceEquals(b.Badge, fe)))
                    occupied.Add(BoundsOf(fe));
            }
            foreach (var (badge, pin) in _badges)
            {
                var size = BoundsOf(badge).Size;
                var candidates = BadgeCandidates(pin, size);
                var chosen = candidates[0];
                foreach (var c in candidates)
                {
                    if (!occupied.Any(o => Collides(o, c)))
                    {
                        chosen = c;
                        break;
                    }
                }
                Canvas.SetLeft(badge, chosen.Left);
                Canvas.SetTop(badge, chosen.Top);
                occupied.Add(chosen);
            }
        }

        /// <summary>Rozetin denenecek yerleri, tercih sırasıyla (ilki eski varsayılan yer).</summary>
        internal static Rect[] BadgeCandidates(Point pin, Size size) => new[]
        {
            new Rect(new Point(pin.X + 4, pin.Y - 20), size),
            new Rect(new Point(pin.X - 4 - size.Width, pin.Y - 20), size),
            new Rect(new Point(pin.X + 4, pin.Y + 4), size),
            new Rect(new Point(pin.X - 4 - size.Width, pin.Y + 4), size),
        };

        /// <summary>İki kutu (aralarında <paramref name="margin"/> kadar pay bırakılarak) üst üste biniyor mu.</summary>
        internal static bool Collides(Rect a, Rect b, double margin = 1) =>
            a.Left < b.Right + margin && b.Left < a.Right + margin &&
            a.Top < b.Bottom + margin && b.Top < a.Bottom + margin;

        private static Rect BoundsOf(FrameworkElement fe)
        {
            if (!fe.IsMeasureValid)
                fe.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            return new Rect(Canvas.GetLeft(fe), Canvas.GetTop(fe), fe.DesiredSize.Width, fe.DesiredSize.Height);
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

        internal static Point BelowOrRight(CircuitElement element)
        {
            double cx = element.Position.X + element.VisualWidth / 2;
            double cy = element.Position.Y + element.VisualHeight / 2;
            bool vertical = Math.Abs(element.Rotation % 180 - 90) < 1;
            // Dikey elemanda değer yazısı ("200Ω") gövdenin sağında, ortada durur: akım etiketi
            // aynı yere konunca yazıyı örtüyordu ("200C"). Etiket sağda ama yazının altına iner.
            return vertical
                ? new Point(cx + 12, cy + 12)
                : new Point(cx - element.VisualWidth / 2, cy + element.VisualHeight / 2 + 2);
        }

        private static (Point Primary, Point Secondary) TransformerCurrentAnchors(TransformerElement element)
        {
            var p1 = element.Pins[0].AbsolutePosition;
            var p2 = element.Pins[1].AbsolutePosition;
            var s1 = element.Pins[2].AbsolutePosition;
            var s2 = element.Pins[3].AbsolutePosition;
            var pMid = new Point((p1.X + p2.X) / 2, (p1.Y + p2.Y) / 2);
            var sMid = new Point((s1.X + s2.X) / 2, (s1.Y + s2.Y) / 2);

            bool vertical = Math.Abs(element.Rotation % 180 - 90) < 1;
            if (vertical)
            {
                return (new Point(pMid.X + 16, pMid.Y - 10),
                        new Point(sMid.X + 16, sMid.Y - 10));
            }
            return (new Point(pMid.X - 10, pMid.Y + 24),
                    new Point(sMid.X - 10, sMid.Y + 24));
        }

        private static Point ThreePhaseLoadPinAnchor(Pin pin)
        {
            // Etiketler gövdenin arkasına yazılır: uç tarafında tel ve düğüm etiketleri var
            const double behindBody = 146;
            var pos = pin.AbsolutePosition;
            var dir = pin.OutwardDirection ?? new Vector(-1, 0);

            if (dir.X < -0.5) // sola bakıyor (0°)
                return new Point(pos.X + behindBody, pos.Y - 10);
            if (dir.X > 0.5) // sağa bakıyor (180°)
                return new Point(pos.X - behindBody - 100, pos.Y - 10);

            // Dikey durumda uçlar yan yana kalır; etiketler sığsın diye alt alta dizilir
            var owner = pin.Owner!;
            double centerX = owner.Position.X + owner.VisualWidth / 2;
            int row = owner.Pins.IndexOf(pin);
            return dir.Y < 0 // yukarı bakıyor (90°)
                ? new Point(centerX - 50, pos.Y + behindBody + row * 20)
                : new Point(centerX - 50, pos.Y - behindBody - (owner.Pins.Count - row) * 20);
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
                _badges.Add((badge, pinPosition));
            }
        }

        /// <summary>
        /// Yatay diyotta gövdenin hemen altı ve üstü diyotun kendi yazılarına ayrılmıştır
        /// (ad ve Si/Ge; 180° döndürülünce yer değiştirirler). Etiket bu yazıların altından başlar.
        /// </summary>
        internal static Point DiodeLabelAnchor(Diode diode)
        {
            bool vertical = Math.Abs(diode.Rotation % 180 - 90) < 1;
            if (vertical)
                return BelowOrRight(diode);
            double cy = diode.Position.Y + diode.VisualHeight / 2;
            return new Point(diode.Position.X, cy + Diode.TextZoneBelow);
        }

        /// <summary>"3,667 mA (2→3) · iletimde": akım akım renginde, durum kendi renginde ve kalın.</summary>
        private void AddDiodeLabel(Point position, string? currentText, string? stateText, bool stacked)
        {
            // Dikey diyotun sağında yer dar: yan koldaki elemanın etiketine taşmasın diye durum
            // alt satıra iner. Yatayda alt satır, paralel koldaki diyotun yazısını örterdi.
            var label = new Border
            {
                CornerRadius = new CornerRadius(stacked ? 8 : 999),
                Padding = new Thickness(6, 2, 6, 2),
            };
            label.SetResourceReference(Border.BackgroundProperty, "Brush.Overlay.BadgeBg");

            var tb = new TextBlock { FontSize = 12, FontWeight = FontWeights.SemiBold };
            tb.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            if (currentText != null)
            {
                var run = new Run(currentText);
                run.SetResourceReference(TextElement.ForegroundProperty, "Brush.Overlay.Current");
                tb.Inlines.Add(run);
            }
            if (stateText != null)
            {
                if (currentText != null && stacked)
                {
                    tb.Inlines.Add(new LineBreak());
                }
                else if (currentText != null)
                {
                    var sep = new Run(" · ");
                    sep.SetResourceReference(TextElement.ForegroundProperty, "Brush.Text.Secondary");
                    tb.Inlines.Add(sep);
                }
                var state = new Span { FontWeight = FontWeights.Bold };
                state.Inlines.AddRange(SubscriptText.ToInlines(stateText, 12));
                bool isConducting = stateText == "iletimde" || stateText == "ters iletimde (V_Z)";
                state.SetResourceReference(TextElement.ForegroundProperty,
                    isConducting ? "Brush.Success" : "Brush.Text.Secondary");
                tb.Inlines.Add(state);
            }
            label.Child = tb;
            Place(label, position);
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
            SubscriptText.Apply(tb);
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
