using System;
using System.Collections.Generic;
using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using System.Windows.Shapes;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>Bağımlı (kontrollü) kaynağın türü.</summary>
    public enum DependentSourceKind
    {
        /// <summary>Gerilim Kontrollü Gerilim Kaynağı (GKGK) — netlist öneki E.</summary>
        Vcvs,
        /// <summary>Gerilim Kontrollü Akım Kaynağı (GKAK) — netlist öneki G.</summary>
        Vccs,
        /// <summary>Akım Kontrollü Gerilim Kaynağı (AKGK) — netlist öneki H.</summary>
        Ccvs,
        /// <summary>Akım Kontrollü Akım Kaynağı (AKAK) — netlist öneki F.</summary>
        Cccs,
    }

    /// <summary>
    /// Bağımlı (kontrollü) kaynak: çıkışı, devredeki BAŞKA bir elemanın gerilimi ya da akımıyla orantılıdır.
    ///
    /// Görsel yapısı (80×40 piksel, yatay konumda) — daire yerine eşkenar dörtgen:
    ///
    ///                 3·V_R2           (kazanç · kontrol büyüklüğü)
    ///   Pin1 (+)         ╱╲             Pin2 (−)
    ///     ●━━━━━━━━━━━━╱ + −╲━━━━━━━━━━━●
    ///    (0,20)         ╲  ╱              (80,20)
    ///                    ╲╱
    ///                    E1
    ///
    /// Gerilim çıkışlı türlerde (E, H) içinde "+" ve "−", akım çıkışlı türlerde (G, F) pin 1'den pin 2'ye
    /// bakan bir ok vardır (akım kaynağından sonra: akım kaynağın içinde n+ → n− yönünde akar,
    /// yani n− ucundan çıkıp dış devreye geçer).
    ///
    /// Netlist biçimi (WPF ↔ Python sözleşmesi):
    ///   E1 3 0 V(R2) 3        (Vn+ − Vn− = 3 · V(R2))
    ///   F1 0 4 I(-R1) 50      (kontrol akımı ters yönde alınır; baştaki "-" işareti)
    /// </summary>
    public class DependentSource : CircuitElement
    {
        private const double TotalWidth = 80;
        private const double TotalHeight = 40;
        private const double DiamondHalf = 18;                       // eşkenar dörtgenin yarı köşegeni
        private const double LeadLength = (TotalWidth - 2 * DiamondHalf) / 2;

        private static readonly CultureInfo Turkish = CultureInfo.GetCultureInfo("tr-TR");

        private DependentSourceKind _kind;

        public DependentSource() : this(DependentSourceKind.Vcvs)
        {
        }

        public DependentSource(DependentSourceKind kind)
        {
            Id = PrefixOf(kind);
            Kind = kind;
            Value = 1; // Kazanç (Gain) ile aynı alan

            Pins.Add(new Pin
            {
                Id = "+",
                RelativePosition = new Point(0, TotalHeight / 2),
                Owner = this
            });
            Pins.Add(new Pin
            {
                Id = "−",
                RelativePosition = new Point(TotalWidth, TotalHeight / 2),
                Owner = this
            });
        }

        /// <summary>Kaynağın türü (GKGK, GKAK, AKGK, AKAK).</summary>
        public DependentSourceKind Kind
        {
            get => _kind;
            set
            {
                _kind = value;
                Unit = IsVoltageOutput ? "V" : "A";
            }
        }

        /// <summary>Kazanç (gerçel, sıfırdan farklı; negatif olabilir). Birimi türe bağlıdır (bkz. GainUnit).</summary>
        public double Gain
        {
            get => Value;
            set => Value = value;
        }

        /// <summary>Kontrol eden elemanın kimliği (ör: "R2"). Boşsa henüz seçilmemiştir.</summary>
        public string ControlElementId { get; set; } = string.Empty;

        /// <summary>Doğruysa kontrol büyüklüğünün işareti ters alınır (netlistte V(-R2) / I(-R2)).</summary>
        public bool ControlReversed { get; set; }

        /// <summary>Kontrol büyüklüğü gerilim mi (GKGK, GKAK) yoksa akım mı (AKGK, AKAK)?</summary>
        public bool IsVoltageControlled => Kind is DependentSourceKind.Vcvs or DependentSourceKind.Vccs;

        /// <summary>Çıkış gerilim mi (GKGK, AKGK) yoksa akım mı (GKAK, AKAK)?</summary>
        public bool IsVoltageOutput => Kind is DependentSourceKind.Vcvs or DependentSourceKind.Ccvs;

        /// <summary>Netlist/kimlik öneki: E, G, H veya F.</summary>
        public string IdPrefix => PrefixOf(Kind);

        /// <summary>Kontrol büyüklüğünün harfi: "V" veya "I".</summary>
        public string ControlLetter => IsVoltageControlled ? "V" : "I";

        public string KindName => NameOf(Kind);

        public string GainUnit => GainUnitOf(Kind);

        public static string PrefixOf(DependentSourceKind kind) => kind switch
        {
            DependentSourceKind.Vcvs => "E",
            DependentSourceKind.Vccs => "G",
            DependentSourceKind.Ccvs => "H",
            _ => "F",
        };

        /// <summary>Türkçe tam ad ve kısaltma.</summary>
        public static string NameOf(DependentSourceKind kind) => kind switch
        {
            DependentSourceKind.Vcvs => "Gerilim Kontrollü Gerilim Kaynağı (GKGK)",
            DependentSourceKind.Vccs => "Gerilim Kontrollü Akım Kaynağı (GKAK)",
            DependentSourceKind.Ccvs => "Akım Kontrollü Gerilim Kaynağı (AKGK)",
            _ => "Akım Kontrollü Akım Kaynağı (AKAK)",
        };

        /// <summary>Kazancın birimi (ipucu olarak yalnızca düzenleyicide gösterilir).</summary>
        public static string GainUnitOf(DependentSourceKind kind) => kind switch
        {
            DependentSourceKind.Vcvs => "V/V",
            DependentSourceKind.Vccs => "A/V (S)",
            DependentSourceKind.Ccvs => "V/A (Ω)",
            _ => "A/A",
        };

        /// <summary>
        /// Bu eleman bir bağımlı kaynağın kontrol elemanı olabilir mi?
        /// İki uçlu devre elemanları olabilir; GND, prob ve bağlantı noktası olamaz.
        /// </summary>
        public static bool CanBeControl(CircuitElement element)
            => element is not GroundElement and not TestProbe and not JunctionElement
               and not SwitchElement and not SpdtSwitch and not TransformerElement
               and not ThreePhaseSource and not ThreePhaseLoad and not Wattmeter
               && element.Pins.Count == 2;

        // ═══════════════════════════════════════════════════════
        //  ETİKET METNİ
        // ═══════════════════════════════════════════════════════

        /// <summary>Ekranda gösterilen kazanç metni (Türkçe virgül, gerçek eksi işareti): "0,5", "−3".</summary>
        public static string FormatGain(double gain)
            => TurkishNumber.Format(gain, "G6").Replace('-', '−');

        /// <summary>
        /// Etiketin düz metin karşılığı (testler ve erişilebilirlik için): "3·V_R2", "0,5·I_R2" (ters kontrolde de eksi yok).
        /// Görselde kimlik alt simge olarak çizilir.
        /// </summary>
        public string LabelText
            => $"{FormatGain(Gain)}·{ControlLetter}_{ControlDisplayId}";

        private string ControlDisplayId => string.IsNullOrWhiteSpace(ControlElementId) ? "?" : ControlElementId;

        // ═══════════════════════════════════════════════════════
        //  GÖRSEL
        // ═══════════════════════════════════════════════════════

        public override UIElement CreateVisual()
        {
            var container = new Canvas
            {
                Width = TotalWidth,
                Height = TotalHeight
            };

            double centerX = TotalWidth / 2;
            double centerY = TotalHeight / 2;
            double diamondLeft = LeadLength;

            var leftLead = new Line
            {
                X1 = 0, Y1 = centerY,
                X2 = diamondLeft, Y2 = centerY,
                StrokeThickness = 2
            };
            leftLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            var rightLead = new Line
            {
                X1 = diamondLeft + 2 * DiamondHalf, Y1 = centerY,
                X2 = TotalWidth, Y2 = centerY,
                StrokeThickness = 2
            };
            rightLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            var diamond = new Polygon
            {
                StrokeThickness = 2,
                StrokeLineJoin = PenLineJoin.Round,
                Points = new PointCollection
                {
                    new Point(centerX, centerY - DiamondHalf),
                    new Point(centerX + DiamondHalf, centerY),
                    new Point(centerX, centerY + DiamondHalf),
                    new Point(centerX - DiamondHalf, centerY),
                }
            };
            diamond.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            diamond.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");

            // Sembolün içi: gerilim çıkışında "+ −", akım çıkışında pin 1 → pin 2 oku
            var inner = new Path
            {
                StrokeThickness = 2,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round,
                StrokeLineJoin = PenLineJoin.Round
            };
            inner.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            var geometry = new PathGeometry();
            if (IsVoltageOutput)
            {
                // "+" sol (pin 1) tarafta, "−" sağ (pin 2) tarafta
                AddLine(geometry, centerX - 11, centerY, centerX - 4, centerY);
                AddLine(geometry, centerX - 7.5, centerY - 3.5, centerX - 7.5, centerY + 3.5);
                AddLine(geometry, centerX + 4, centerY, centerX + 11, centerY);
            }
            else
            {
                AddLine(geometry, centerX - 10, centerY, centerX + 10, centerY);
                var head = new PathFigure { StartPoint = new Point(centerX + 4, centerY - 5), IsClosed = false };
                head.Segments.Add(new LineSegment(new Point(centerX + 10, centerY), true));
                head.Segments.Add(new LineSegment(new Point(centerX + 4, centerY + 5), true));
                geometry.Figures.Add(head);
            }
            inner.Data = geometry;

            // Üst etiket: kazanç · kontrol büyüklüğü (kimlik alt simge)
            var label = BuildLabel();
            label.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(label, centerX - (label.DesiredSize.Width / 2));
            Canvas.SetTop(label, centerY - DiamondHalf - label.DesiredSize.Height - 2);

            var idLabel = new TextBlock
            {
                Text = Id,
                FontSize = 12
            };
            idLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Label");
            idLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            idLabel.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(idLabel, centerX - (idLabel.DesiredSize.Width / 2));
            Canvas.SetTop(idLabel, centerY + DiamondHalf + 2);

            container.Children.Add(leftLead);
            container.Children.Add(rightLead);
            container.Children.Add(diamond);
            container.Children.Add(inner);
            container.Children.Add(label);
            container.Children.Add(idLabel);

            AddPinIndicators(container);

            return container;
        }

        private static void AddLine(PathGeometry geometry, double x1, double y1, double x2, double y2)
        {
            var figure = new PathFigure { StartPoint = new Point(x1, y1), IsClosed = false };
            figure.Segments.Add(new LineSegment(new Point(x2, y2), true));
            geometry.Figures.Add(figure);
        }

        private TextBlock BuildLabel()
        {
            var label = new TextBlock
            {
                FontSize = 12,
                TextAlignment = TextAlignment.Center
            };
            label.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.LabelSecondary");
            label.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");

            label.Inlines.Add(new Run($"{FormatGain(Gain)}·"));

            // Kontrol büyüklüğü, kontrol eden elemanın işaretlemesiyle aynı renkte
            // Ters kontrolde eksi yazılmaz: kontrol elemanındaki +/− ve ok ters çizilir,
            // V_R2 / I_R2 o işaretlere göre tanımlıdır (Python anlatımı da aynı kuralı izler)
            var control = new Run(ControlLetter);
            control.SetResourceReference(TextElement.ForegroundProperty, "Brush.Circuit.Probe");
            label.Inlines.Add(control);

            var sub = new Run(ControlDisplayId)
            {
                BaselineAlignment = BaselineAlignment.Subscript,
                FontSize = 9
            };
            sub.SetResourceReference(TextElement.ForegroundProperty, "Brush.Circuit.Probe");
            label.Inlines.Add(sub);
            return label;
        }

        // ═══════════════════════════════════════════════════════
        //  NETLİST
        // ═══════════════════════════════════════════════════════

        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int nodePlus = nodeMap[Pins[0]];
            int nodeMinus = nodeMap[Pins[1]];
            string control = $"{ControlLetter}({(ControlReversed ? "-" : "")}{ControlElementId})";
            return $"{Id} {nodePlus} {nodeMinus} {control} {Gain.ToString(CultureInfo.InvariantCulture)}";
        }
    }
}
