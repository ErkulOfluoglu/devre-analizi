using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Numerics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Effects;
using System.Windows.Shapes;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Akım ışığı (DESIGN.md, "Akım ışığı"). Çözümden sonra her telde soluk bir akış görünür;
    /// bir eleman seçilince onun kolu tam parlar, öteki kollar daha da söner.
    ///
    /// Darbeler kuyrukludur: parlak baş önde, sönerek uzayan kuyruk ve geniş, soluk bir parıltı
    /// arkada. DC'de bütün darbeler aynı sakin hızla, gerçek akım yönünde gider; akımın büyüklüğünü
    /// ışığın kalınlığı ve parlaklığı gösterir. Darbelerin yeri kaynaklardan ölçülen yol uzunluğuyla
    /// belirlenir, böylece dalga gibi kaynaktan çıkıp düğümlerde kollara ayrılır, tellerde kopmaz.
    ///
    /// AC'de akım sürekli yön değiştirir: ışık bir yöne gider, yavaşlar, durur ve geri döner
    /// (yavaşlatılmış, bir gidiş-geliş 3,2 sn). Başı her zaman gittiği yöndedir; akım sıfırdan
    /// geçerken söner. Zamanlama akımın fazıdır ve bütün teller aynı saate bağlıdır, bu yüzden
    /// örneğin kondansatör kolunun dirençten önde gittiği aynı anda görülür.
    ///
    /// Windows'ta animasyonlar kapalıysa ışık hareket etmez, durağan darbeler olarak görünür.
    /// </summary>
    public sealed class CurrentFlowLayer
    {
        // Desen: 48 px'lik dönemde 34 px'lik kuyruklu darbe
        private const double Period = 48;
        private const double TailLength = 34;
        private const double Speed = 30;               // DC: tuval birimi / sn, her telde aynı
        private const double AcCycle = 3.2;            // AC: bir gidiş-geliş (sn)
        private const double AcMinTravel = 40;         // AC: salınım genliği (tuval birimi)
        private const double AcMaxTravel = 90;

        // Görünürlük: seçim yokken akımla orantılı soluk, seçilen kol tam, ötekiler daha soluk
        private const double IdleStrength = 0.42;
        private const double OthersWhenSelected = 0.05;
        private const double DimmedWireOpacity = 0.45;

        private static readonly Stopwatch Clock = Stopwatch.StartNew();

        private sealed class Layer
        {
            public required Polyline Line { get; init; }
            public required double Thickness { get; init; }
            public required double BaseOpacity { get; init; }
            public required bool HeadForward { get; init; }
            public required double Lead { get; init; }    // desenin, darbe başına göre kaydırılması
            public required bool IsGlow { get; init; }    // bulanık parıltı: yalnız seçili kolda çizilir
        }

        private sealed class WireLight
        {
            public required Wire Wire { get; init; }
            public required double ArcStart { get; init; }
            public required double Strength { get; init; }     // 0..1, akımın en büyüğe oranı (karekök)
            public required double Travel { get; init; }       // AC salınım genliği
            public required double Phase { get; init; }        // AC: ileri yöndeki akımın fazı (rad)
            public List<Layer> Layers { get; } = new();
            public double Factor { get; set; } = 1;
            public bool Glow { get; set; }
        }

        private readonly Canvas _canvas;
        private readonly List<WireLight> _lights = new();
        private readonly List<(Polyline Wire, double Opacity)> _dimmed = new();

        private List<WireFlow> _flows = new();
        private IReadOnlyList<CircuitElement> _elements = Array.Empty<CircuitElement>();
        private IReadOnlyList<Wire> _wires = Array.Empty<Wire>();
        private IReadOnlyDictionary<Pin, int> _nodeMap = new Dictionary<Pin, int>();
        private IReadOnlyDictionary<string, ElementCurrentDto> _currents = new Dictionary<string, ElementCurrentDto>();
        private bool _isAc;
        private bool _ticking;

        public CurrentFlowLayer(Canvas canvas)
        {
            _canvas = canvas;
        }

        /// <summary>Çizili ışık çizgisi sayısı.</summary>
        public int LineCount => _lights.Sum(l => l.Layers.Count);

        /// <summary>Tam parlak yanan teller (seçili elemanın kolu); seçim yoksa boş.</summary>
        public IReadOnlyList<Wire> LitWires { get; private set; } = Array.Empty<Wire>();

        /// <summary>Işığı olan bütün teller.</summary>
        public IReadOnlyList<Wire> FlowingWires => _lights.Select(l => l.Wire).ToList();

        /// <summary>Her telin akımını hesaplar ve bütün devrede soluk akışı başlatır.</summary>
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
            if (_flows.Count == 0)
                return;

            double max = _flows.Max(f => f.Amps);
            var starts = WaveStarts(_elements, _flows, _nodeMap, _currents);
            bool animate = SystemParameters.ClientAreaAnimation;

            foreach (var flow in _flows)
            {
                if (flow.Wire.Visual == null || flow.Wire.Visual.Points.Count < 2)
                    continue;
                double ratio = Math.Sqrt(flow.Amps / max);
                // "İleri" yöndeki akım (DC'de pozitif gerçel, AC'de fazör)
                Complex forward = flow.Forward ? flow.Phasor : -flow.Phasor;
                var light = new WireLight
                {
                    Wire = flow.Wire,
                    ArcStart = starts.GetValueOrDefault(flow.Wire),
                    Strength = ratio,
                    Travel = AcMinTravel + (AcMaxTravel - AcMinTravel) * ratio,
                    Phase = forward.Phase,
                };
                var points = flow.Forward ? flow.Wire.Visual.Points : new PointCollection(flow.Wire.Visual.Points.Reverse());
                AddComet(light, points, ratio, headForward: true, animate);
                if (_isAc && animate)
                    AddComet(light, points, ratio, headForward: false, animate); // geri giderken başı arkada
                _lights.Add(light);
            }

            ApplyFactors(null);
            if (_isAc && animate && _lights.Count > 0)
            {
                CompositionTarget.Rendering += OnAcFrame;
                _ticking = true;
                OnAcFrame(this, EventArgs.Empty);
            }
        }

        /// <summary>Işığı söndürür ve hesapları unutur (devre değişti ya da çözüm silindi).</summary>
        public void Clear()
        {
            if (_ticking)
            {
                CompositionTarget.Rendering -= OnAcFrame;
                _ticking = false;
            }
            foreach (var light in _lights)
                foreach (var layer in light.Layers)
                    _canvas.Children.Remove(layer.Line);
            _lights.Clear();
            RestoreWires();
            _flows = new List<WireFlow>();
            LitWires = Array.Empty<Wire>();
        }

        /// <summary>Seçili elemanın kolunu parlatır; null seçimi kaldırır (bütün devre soluk akar).</summary>
        public void Show(CircuitElement? selected)
        {
            if (_lights.Count == 0)
            {
                LitWires = Array.Empty<Wire>();
                return;
            }
            HashSet<Wire>? branch = null;
            if (selected != null && CurrentFlow.TryBranch(selected, _nodeMap, _currents, out _, out _, out double amps) && amps > 0)
            {
                branch = CurrentFlow.BranchWires(selected, _elements, _flows, _nodeMap, _currents);
                if (branch.Count == 0)
                    branch = null;
            }
            ApplyFactors(branch);
        }

        private void ApplyFactors(HashSet<Wire>? branch)
        {
            RestoreWires();
            foreach (var light in _lights)
            {
                light.Factor = branch == null
                    ? IdleStrength * (0.35 + 0.65 * light.Strength)
                    : branch.Contains(light.Wire) ? 1 : OthersWhenSelected;
                // Parıltı filtresi pahalı: yalnız seçili kolda; soluk akışta zaten seçilmez
                light.Glow = branch != null && branch.Contains(light.Wire);
                foreach (var layer in light.Layers)
                {
                    if (layer.IsGlow)
                        layer.Line.Visibility = light.Glow ? Visibility.Visible : Visibility.Collapsed;
                    if (!_ticking)
                        layer.Line.Opacity = layer.BaseOpacity * light.Factor;
                }
            }
            LitWires = branch?.Where(w => _lights.Any(l => l.Wire == w)).ToList() ?? (IReadOnlyList<Wire>)Array.Empty<Wire>();

            if (branch == null)
                return;
            foreach (var wire in _wires)
            {
                if (branch.Contains(wire) || wire.Visual == null)
                    continue;
                _dimmed.Add((wire.Visual, wire.Visual.Opacity));
                wire.Visual.Opacity = DimmedWireOpacity;
            }
        }

        private void RestoreWires()
        {
            foreach (var (wire, opacity) in _dimmed)
                wire.Opacity = opacity;
            _dimmed.Clear();
        }

        /// <summary>
        /// Kuyruklu darbe: ince uzun kuyruk, daha kalın kısa gövde, parlak yuvarlak baş ve başın
        /// çevresinde bulanık parıltı. Hepsinin başı desende aynı noktadadır; headForward değilse
        /// desen ters çevrilir, baş geride kalır.
        /// </summary>
        private void AddComet(WireLight light, PointCollection points, double ratio, bool headForward, bool animate)
        {
            (double Width, double Length, double Opacity, string Brush, bool Glow)[] parts =
            {
                (8 + 6 * ratio, 10, 0.55, "Brush.Accent", true),            // parıltı (bulanık)
                (1.5 + 1.2 * ratio, TailLength, 0.35, "Brush.Accent", false), // kuyruk
                (2.5 + 1.8 * ratio, 16, 0.6, "Brush.Accent", false),          // gövde
                (3 + 2 * ratio, 3, 1.0, "Brush.Accent.SoftText", false),      // baş
            };
            foreach (var (width, length, opacity, brush, glow) in parts)
            {
                var line = new Polyline
                {
                    Points = points,
                    StrokeThickness = width,
                    StrokeLineJoin = PenLineJoin.Round,
                    StrokeDashCap = PenLineCap.Round,
                    IsHitTestVisible = false,
                };
                if (glow)
                    line.Effect = new BlurEffect { Radius = 6, RenderingBias = RenderingBias.Performance };
                line.SetResourceReference(Shape.StrokeProperty, brush);
                // Üç parçanın başı aynı noktada: ileri giden darbede parça [Kuyruk − uzunluk, Kuyruk]
                // aralığında, geri gidende [0, uzunluk] aralığında. Desen bir kesikle başlamalı
                // (yuvarlak uçlu sıfır kesik nokta çizer), bu yüzden aradaki boşluk kaydırmaya katılır.
                double lead = headForward ? TailLength - length : 0;
                line.StrokeDashArray = new DoubleCollection { length / width, (Period - length) / width };
                line.StrokeDashOffset = (light.ArcStart - lead) / width;
                var layer = new Layer { Line = line, Thickness = width, BaseOpacity = opacity, HeadForward = headForward, Lead = lead, IsGlow = glow };
                light.Layers.Add(layer);
                _canvas.Children.Add(line);

                if (animate && !_isAc)
                {
                    double from = (light.ArcStart - lead) / width;
                    var animation = new DoubleAnimation(from, from - Period / width, TimeSpan.FromSeconds(Period / Speed))
                    {
                        RepeatBehavior = RepeatBehavior.Forever
                    };
                    animation.Freeze();
                    line.BeginAnimation(Shape.StrokeDashOffsetProperty, animation);
                }
            }
        }

        /// <summary>
        /// AC: yük yer değiştirmesi x = genlik·sin(ωt + φ), akım cos(ωt + φ). Desen x kadar kayar;
        /// giderken başı önde olan, dönerken başı arkada olan darbe görünür; parlaklık |akım|'la artar.
        /// </summary>
        private void OnAcFrame(object? sender, EventArgs e)
        {
            double w = 2 * Math.PI / AcCycle;
            double t = Clock.Elapsed.TotalSeconds;
            foreach (var light in _lights)
            {
                double angle = w * t + light.Phase;
                double shift = light.Travel * Math.Sin(angle);
                double current = Math.Cos(angle);
                double glow = 0.12 + 0.88 * Math.Abs(current);
                foreach (var layer in light.Layers)
                {
                    layer.Line.StrokeDashOffset = (light.ArcStart - layer.Lead - shift) / layer.Thickness;
                    // Görünmeyen yöndeki darbe hiç çizilmesin (parıltı filtresi pahalı)
                    bool visible = layer.HeadForward == (current >= 0) && (!layer.IsGlow || light.Glow);
                    layer.Line.Visibility = visible ? Visibility.Visible : Visibility.Hidden;
                    if (visible)
                        layer.Line.Opacity = layer.BaseOpacity * light.Factor * glow;
                }
            }
        }

        /// <summary>
        /// Dalga koordinatı: her telin, ileri yönde başladığı noktanın kaynaklardan ölçülen yol
        /// uzunluğu. Kaynakların giriş ucu 0'dır; akım yönünde teller ve elemanlar boyunca en kısa
        /// yol alınır. Desen bu uzunlukla başlayınca darbeler düğümlerden kopmadan kollara ayrılır.
        /// Kaynağa ulaşılamayan teller (ör. yalnız akım kaynağı olmayan bölüm) kendi başından başlar.
        /// </summary>
        internal static Dictionary<Wire, double> WaveStarts(
            IReadOnlyList<CircuitElement> elements,
            IReadOnlyList<WireFlow> flows,
            IReadOnlyDictionary<Pin, int> nodeMap,
            IReadOnlyDictionary<string, ElementCurrentDto> currents)
        {
            var starts = new Dictionary<Wire, double>();
            var flowsFrom = new Dictionary<Pin, List<WireFlow>>();
            foreach (var flow in flows)
            {
                Pin start = flow.Forward ? flow.Wire.StartPin : flow.Wire.EndPin;
                if (!flowsFrom.TryGetValue(start, out var list))
                    flowsFrom[start] = list = new List<WireFlow>();
                list.Add(flow);
            }

            // Eleman içinden geçiş: giriş ucundan çıkış ucuna
            var through = new Dictionary<Pin, (Pin To, double Length)>();
            var queue = new PriorityQueue<Pin, double>();
            var best = new Dictionary<Pin, double>();
            foreach (var element in elements)
            {
                if (!CurrentFlow.TryBranch(element, nodeMap, currents, out var from, out var to, out _))
                    continue;
                through[from] = (to, Distance(from, to));
                if (element is VoltageSource or AcVoltageSource or CurrentSource or AcCurrentSource)
                {
                    best[from] = 0;
                    queue.Enqueue(from, 0);
                }
            }

            while (queue.TryDequeue(out var pin, out double at))
            {
                if (best.TryGetValue(pin, out double known) && known < at)
                    continue;
                void Reach(Pin next, double distance)
                {
                    if (!best.TryGetValue(next, out double old) || distance < old)
                    {
                        best[next] = distance;
                        queue.Enqueue(next, distance);
                    }
                }
                if (through.TryGetValue(pin, out var step))
                    Reach(step.To, at + step.Length);
                if (flowsFrom.TryGetValue(pin, out var outgoing))
                {
                    foreach (var flow in outgoing)
                    {
                        if (!starts.ContainsKey(flow.Wire) || at < starts[flow.Wire])
                            starts[flow.Wire] = at;
                        Reach(flow.Forward ? flow.Wire.EndPin : flow.Wire.StartPin, at + Length(flow.Wire));
                    }
                }
            }
            return starts;
        }

        private static double Distance(Pin a, Pin b) => (a.AbsolutePosition - b.AbsolutePosition).Length;

        private static double Length(Wire wire)
        {
            var pts = wire.Visual?.Points;
            if (pts == null || pts.Count < 2)
                return Distance(wire.StartPin, wire.EndPin);
            double sum = 0;
            for (int i = 1; i < pts.Count; i++)
                sum += (pts[i] - pts[i - 1]).Length;
            return sum;
        }
    }
}
