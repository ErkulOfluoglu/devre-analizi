using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Numerics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Shapes;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Akım ışığı (DESIGN.md, "Akım ışığı"): yalnız bir eleman seçilince, o elemanın kolundaki
    /// tellerde gerçek akım yönünde sakin ışık darbeleri akar; öteki teller soluklaşır.
    /// Darbeler kol boyunca kesintisizdir: her telin deseni kolun başından ölçülen uzaklıkla başlar.
    /// Hız akımla artar (karekökle), elektronun gerçek hızı değildir. Windows'ta animasyonlar
    /// kapalıysa ışık akmaz, sabit çizgi olur.
    ///
    /// AC'de akım sürekli yön değiştirir: ışık kol boyunca ileri geri salınır (yavaşlatılmış,
    /// bir salınım 2 sn). Salınım genişliği akımın büyüklüğünü, zamanlaması fazını gösterir;
    /// bütün AC kolları aynı saate bağlıdır, iki elemanı sırayla seçen faz farkını görür.
    /// </summary>
    public sealed class CurrentFlowLayer
    {
        // Desen: 14 px ışık, 34 px boşluk (48 px'lik dönem)
        private const double Period = 48;
        private const double DashLength = 14;
        private const double CoreThickness = 3;
        private const double HaloThickness = 10;
        // Saniyede tuval birimi: en büyük akımda bir dönem ~1,7 sn, küçük akımlarda ~3 sn
        private const double MinSpeed = 10;
        private const double MaxSpeed = 28;
        private const double DimmedWireOpacity = 0.55;
        // AC: yavaşlatılmış salınım (Hz) ve tuval biriminde salınım genliği
        private const double AcSlowFrequency = 0.5;
        private const double AcMinAmplitude = 12;
        private const double AcMaxAmplitude = 34;

        // Bütün AC kollarının ortak saati: faz farkları seçimler arasında korunur
        private static readonly Stopwatch AcClock = Stopwatch.StartNew();

        private readonly Canvas _canvas;
        private readonly List<Polyline> _lines = new();
        private readonly List<(Polyline Wire, double Opacity)> _dimmed = new();

        private List<WireFlow> _flows = new();
        private IReadOnlyList<CircuitElement> _elements = Array.Empty<CircuitElement>();
        private IReadOnlyList<Wire> _wires = Array.Empty<Wire>();
        private IReadOnlyDictionary<Pin, int> _nodeMap = new Dictionary<Pin, int>();
        private IReadOnlyDictionary<string, ElementCurrentDto> _currents = new Dictionary<string, ElementCurrentDto>();
        private double _maxAmps;
        private bool _isAc;
        private readonly List<(Polyline Line, double ArcStart, double Thickness)> _acLines = new();
        private double _acAmplitude;
        private double _acPhase;
        private bool _acTicking;

        public CurrentFlowLayer(Canvas canvas)
        {
            _canvas = canvas;
        }

        /// <summary>Çizili ışık çizgisi sayısı (çekirdek + hale).</summary>
        public int LineCount => _lines.Count;

        /// <summary>Şu an ışığı yanan teller.</summary>
        public IReadOnlyList<Wire> LitWires { get; private set; } = Array.Empty<Wire>();

        /// <summary>Her telin akımını hesaplar; ışık seçim gelince yanar.</summary>
        public void Prepare(
            IEnumerable<CircuitElement> elements,
            IEnumerable<Wire> wires,
            NetlistResult netlist,
            IReadOnlyDictionary<string, ElementCurrentDto> currents,
            bool isAc = false)
        {
            Clear();
            _isAc = isAc;
            _elements = elements.ToList();
            _wires = wires.ToList();
            _nodeMap = netlist.NodeMap;
            _currents = currents;
            _flows = CurrentFlow.Compute(_elements, _wires, netlist.NodeMap, currents);
            _maxAmps = _flows.Count > 0 ? _flows.Max(f => f.Amps) : 0;
        }

        /// <summary>Işığı söndürür ve hesapları unutur (devre değişti ya da çözüm silindi).</summary>
        public void Clear()
        {
            ClearLines();
            _flows = new List<WireFlow>();
            _maxAmps = 0;
        }

        /// <summary>Seçili elemanın kolunu yakar; null ya da kolu bulunamayan eleman ışığı söndürür.</summary>
        public void Show(CircuitElement? selected)
        {
            ClearLines();
            if (selected == null || _flows.Count == 0
                || !CurrentFlow.TryPhasor(selected, _nodeMap, _currents, out var from, out var to, out Complex reference)
                || reference.Magnitude <= 0)
                return;
            double amps = reference.Magnitude;

            var branch = CurrentFlow.BranchWires(selected, _elements, _flows, _nodeMap, _currents);
            if (branch.Count == 0)
                return;

            var flowOf = _flows.Where(f => branch.Contains(f.Wire)).ToDictionary(f => f.Wire);
            if (_isAc)
            {
                // AC'de "ileri", seçili elemanın fazörüyle aynı yön: kolun bütün telleri aynı fazda salınır
                flowOf = flowOf.ToDictionary(
                    kv => kv.Key,
                    kv => kv.Value with { Forward = (kv.Value.Phasor * Complex.Conjugate(reference)).Real >= 0 });
            }
            var start = ArcStarts(selected, from, to, flowOf);

            double ratio = Math.Sqrt(amps / _maxAmps);
            var duration = TimeSpan.FromSeconds(Period / (MinSpeed + (MaxSpeed - MinSpeed) * ratio));
            bool animate = SystemParameters.ClientAreaAnimation;
            _acAmplitude = AcMinAmplitude + (AcMaxAmplitude - AcMinAmplitude) * ratio;
            _acPhase = reference.Phase;

            foreach (var (wire, flow) in flowOf)
            {
                if (wire.Visual == null || wire.Visual.Points.Count < 2)
                    continue;
                var points = flow.Forward ? wire.Visual.Points : new PointCollection(wire.Visual.Points.Reverse());
                double s0 = start.GetValueOrDefault(wire);
                _canvas.Children.Add(Pulse(points, HaloThickness, 0.16 + 0.12 * ratio, s0, duration, animate));
                _canvas.Children.Add(Pulse(points, CoreThickness, 0.6 + 0.4 * ratio, s0, duration, animate));
            }
            LitWires = flowOf.Keys.ToList();
            if (_acLines.Count > 0 && !_acTicking)
            {
                CompositionTarget.Rendering += OnAcFrame;
                _acTicking = true;
                OnAcFrame(this, EventArgs.Empty);
            }

            foreach (var wire in _wires)
            {
                if (branch.Contains(wire) || wire.Visual == null)
                    continue;
                _dimmed.Add((wire.Visual, wire.Visual.Opacity));
                wire.Visual.Opacity = DimmedWireOpacity;
            }
        }

        private void ClearLines()
        {
            if (_acTicking)
            {
                CompositionTarget.Rendering -= OnAcFrame;
                _acTicking = false;
            }
            _acLines.Clear();
            foreach (var line in _lines)
                _canvas.Children.Remove(line);
            _lines.Clear();
            foreach (var (wire, opacity) in _dimmed)
                wire.Opacity = opacity;
            _dimmed.Clear();
            LitWires = Array.Empty<Wire>();
        }

        /// <summary>
        /// Her telin, akım yönünde başladığı noktanın kol boyunca uzaklığı. Seçili elemanın giriş
        /// ucu 0'dır; akım yönünde ileri, ters yönde geri yürünür. Aynı akımı taşıyan seri
        /// elemanların içinden geçilir. Bu uzaklık desenin başlangıcı olunca darbeler teller
        /// arasında kopmadan akar.
        /// </summary>
        private Dictionary<Wire, double> ArcStarts(CircuitElement selected, Pin from, Pin to, Dictionary<Wire, WireFlow> flowOf)
        {
            var start = new Dictionary<Wire, double>();
            var owners = new Dictionary<Pin, CircuitElement>();
            foreach (var element in _elements)
                foreach (var pin in element.Pins)
                    owners[pin] = element;

            var queue = new Queue<(Pin Pin, double At, bool Forward)>();
            queue.Enqueue((to, Distance(from, to), true));
            queue.Enqueue((from, 0, false));
            var seen = new HashSet<(Pin, bool)>();
            while (queue.Count > 0)
            {
                var (pin, at, forward) = queue.Dequeue();
                if (!seen.Add((pin, forward)))
                    continue;

                foreach (var (wire, flow) in flowOf)
                {
                    if (start.ContainsKey(wire))
                        continue;
                    Pin flowStart = flow.Forward ? wire.StartPin : wire.EndPin;
                    Pin flowEnd = flow.Forward ? wire.EndPin : wire.StartPin;
                    double length = Length(wire);
                    if (forward && flowStart == pin)
                    {
                        start[wire] = at;
                        queue.Enqueue((flowEnd, at + length, true));
                    }
                    else if (!forward && flowEnd == pin)
                    {
                        start[wire] = at - length;
                        queue.Enqueue((flowStart, at - length, false));
                    }
                }

                // Seri eleman: aynı akım, giriş ucundan çıkış ucuna (ya da tersi) geç
                if (owners.TryGetValue(pin, out var owner) && owner != selected
                    && CurrentFlow.TryBranch(owner, _nodeMap, _currents, out var oFrom, out var oTo, out _))
                {
                    if (forward && oFrom == pin)
                        queue.Enqueue((oTo, at + Distance(oFrom, oTo), true));
                    else if (!forward && oTo == pin)
                        queue.Enqueue((oFrom, at - Distance(oFrom, oTo), false));
                }
            }
            return start;
        }

        private static double Distance(Pin a, Pin b) => (a.AbsolutePosition - b.AbsolutePosition).Length;

        private static double Length(Wire wire)
        {
            var pts = wire.Visual?.Points;
            if (pts == null)
                return Distance(wire.StartPin, wire.EndPin);
            double sum = 0;
            for (int i = 1; i < pts.Count; i++)
                sum += (pts[i] - pts[i - 1]).Length;
            return sum;
        }

        private Polyline Pulse(PointCollection points, double thickness, double strength, double arcStart, TimeSpan duration, bool animate)
        {
            var line = new Polyline
            {
                Points = points,
                StrokeThickness = thickness,
                StrokeLineJoin = PenLineJoin.Round,
                IsHitTestVisible = false,
                Opacity = strength
            };
            line.SetResourceReference(Shape.StrokeProperty, "Brush.Accent");
            _lines.Add(line);
            if (!animate)
                return line; // hareket azaltıldı: sabit parlak çizgi

            // Kesik desen kalınlık biriminde; desen kolun başından ölçülen uzaklıkla başlar
            line.StrokeDashCap = PenLineCap.Round;
            line.StrokeDashArray = new DoubleCollection { DashLength / thickness, (Period - DashLength) / thickness };
            double offset = arcStart / thickness;
            if (_isAc)
            {
                // AC: her karede salınımın yerine göre kaydırılır (OnAcFrame)
                line.StrokeDashOffset = offset;
                _acLines.Add((line, arcStart, thickness));
                return line;
            }
            var animation = new DoubleAnimation(offset, offset - Period / thickness, duration) { RepeatBehavior = RepeatBehavior.Forever };
            animation.Freeze();
            line.BeginAnimation(Shape.StrokeDashOffsetProperty, animation);
            return line;
        }

        /// <summary>
        /// AC salınımı: i = |I|·cos(ωt + φ) ise yük yer değiştirmesi sin(ωt + φ) ile orantılıdır;
        /// desen bu kadar ileri geri kaydırılır.
        /// </summary>
        private void OnAcFrame(object? sender, EventArgs e)
        {
            double t = AcClock.Elapsed.TotalSeconds;
            double shift = _acAmplitude * Math.Sin(2 * Math.PI * AcSlowFrequency * t + _acPhase);
            foreach (var (line, arcStart, thickness) in _acLines)
                line.StrokeDashOffset = (arcStart - shift) / thickness;
        }
    }
}
