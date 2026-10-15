using System;
using System.Collections.Generic;
using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>
    /// AC kaynağın giriş modu.
    /// Physical: Genlik + Frekans + Faz (zaman alanı, SINE formatı)
    /// Phasor: Büyüklük + Açı (frekans alanı, fazör gösterimi)
    /// </summary>
    public enum AcInputMode
    {
        /// <summary>Fiziksel mod: v(t) = Vp·sin(2πft + φ)</summary>
        Physical,
        /// <summary>Fazör mod: V = Vm∠φ° (frekans JSON ile ayrıca gönderilir)</summary>
        Phasor
    }

    /// <summary>
    /// AC Gerilim Kaynağı (AC Voltage Source) devre elemanı.
    /// IEC 60617 standardına uygun daire + sinüs dalgası sembolü.
    /// 
    /// DC Kaynaktan farkları:
    /// ┌─────────────────────────────────────────────────────────────────┐
    /// │  Özellik         │  DC Kaynak        │  AC Kaynak              │
    /// │──────────────────│───────────────────│────────────────────────  │
    /// │  Value           │  Tek: Volt        │  Üç: Genlik, Frekans,   │
    /// │                  │                   │       Faz               │
    /// │  Sembol          │  ⊕⊖ (+ ve −)      │  ∿ (sinüs dalgası)     │
    /// │  Netlist         │  V1 1 0 DC 12     │  V1 1 0 SINE(0 10 50   │
    /// │                  │                   │         0 0 30)         │
    /// │  Renk            │  Altın sarısı     │  Mor/eflatun            │
    /// └─────────────────────────────────────────────────────────────────┘
    /// 
    /// Görsel yapısı (80×40 piksel, yatay konumda):
    /// 
    ///   Pin1 (+)                          Pin2 (−)
    ///     ●━━━━━╭────────────╮━━━━━●
    ///    (0,20) │    ∿∿∿     │  (80,20)
    ///           ╰────────────╯
    ///           
    /// SPICE Netlist formatı:
    ///   SINE(V_offset V_amplitude Freq T_delay Damping Phase)
    ///   Örnek: V1 1 0 SINE(0 10 50 0 0 30)
    ///     → 10V genlik, 50Hz frekans, 30° faz, 0V offset
    ///   
    ///   v(t) = V_offset + V_amplitude × sin(2π × Freq × t + Phase°)
    /// </summary>
    public class AcVoltageSource : CircuitElement
    {
        // Görsel boyutlar (piksel)
        private const double TotalWidth = 80;
        private const double TotalHeight = 40;
        private const double CircleDiameter = 36;
        private const double CircleRadius = CircleDiameter / 2;
        private const double LeadLength = (TotalWidth - CircleDiameter) / 2;

        // ═══════════════════════════════════════════════
        //  AC'ye Özgü Özellikler
        // ═══════════════════════════════════════════════

        /// <summary>
        /// Genlik (Amplitude) — Tepe gerilim değeri [V].
        /// Sinüs dalgasının maksimum değeri.
        /// Örneğin 220V şebeke için genlik = 220√2 ≈ 311V'tur.
        /// </summary>
        public double Amplitude { get; set; } = 10.0;

        /// <summary>
        /// Frekans (Frequency) — Saniyedeki çevrim sayısı [Hz].
        /// Türkiye şebeke frekansı: 50Hz.
        /// Periyot: T = 1/f → 50Hz için T = 20ms.
        /// Açısal frekans: ω = 2πf → 50Hz için ω ≈ 314.16 rad/s.
        /// </summary>
        public double Frequency { get; set; } = 50.0;

        /// <summary>
        /// Faz (Phase) — Sinüs dalgasının başlangıç açısı [derece].
        /// 0° → sin fonksiyonu sıfırdan başlar.
        /// 90° → cos fonksiyonu gibi tepeden başlar.
        /// Fazör gösteriminde: V = Amplitude ∠ Phase°
        /// </summary>
        public double Phase { get; set; } = 0.0;

        /// <summary>
        /// Giriş modu: Physical (varsayılan) veya Phasor.
        /// Fazör modunda Frequency devre dışı kalır — frekans bilgisi
        /// Python backend'e ayrı JSON parametresi olarak gönderilir.
        /// </summary>
        public AcInputMode InputMode { get; set; } = AcInputMode.Physical;

        public AcVoltageSource()
        {
            Unit = "V";
            Value = 10; // Amplitude ile senkronize başlangıç

            // Pin 1 = Pozitif terminal — sol uç
            // Pin 2 = Negatif terminal — sağ uç
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

        /// <summary>
        /// IEC daire + sinüs dalgası sembolü ile AC kaynağını çizer.
        /// DC kaynaktan farkı: + − işaretleri yerine sinüs dalgası çizilir.
        /// Renk: mor/eflatun tonu (DC'nin altın sarısından ayırt etmek için).
        /// </summary>
        public override UIElement CreateVisual()
        {
            var container = new Canvas
            {
                Width = TotalWidth,
                Height = TotalHeight
            };

            double centerX = TotalWidth / 2;   // 40
            double centerY = TotalHeight / 2;   // 20
            double circleLeft = LeadLength;

            // ── Sol bağlantı teli ──
            var leftLead = new Line
            {
                X1 = 0, Y1 = centerY,
                X2 = circleLeft, Y2 = centerY,
                StrokeThickness = 2
            };
            leftLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Sağ bağlantı teli ──
            var rightLead = new Line
            {
                X1 = circleLeft + CircleDiameter, Y1 = centerY,
                X2 = TotalWidth, Y2 = centerY,
                StrokeThickness = 2
            };
            rightLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            // ── Ana daire gövdesi ──
            var circle = new Ellipse
            {
                Width = CircleDiameter,
                Height = CircleDiameter,
                StrokeThickness = 2
            };
            circle.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            circle.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            Canvas.SetLeft(circle, circleLeft);
            Canvas.SetTop(circle, centerY - CircleRadius);

            // ── Sinüs dalgası (∿) — AC kaynağın ayırt edici sembolü ──
            // Dairenin içine sığan 1 tam periyot sinüs çizilir.
            // Path geometrisi: Cubic Bézier ile pürüzsüz eğri.
            var sineWave = new Path
            {
                StrokeThickness = 2,
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round,
                StrokeLineJoin = PenLineJoin.Round
            };
            sineWave.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");

            double waveLeft = centerX - 10;    // Dalganın sol başlangıcı
            double waveRight = centerX + 10;   // Dalganın sağ bitişi
            double waveMid = centerX;          // Dalganın orta noktası
            double waveAmp = 6.5;              // Dalga yüksekliği (piksel)

            // Bézier kontrol noktaları ile sinüs eğrisi:
            // İlk yarım periyot: sol → orta (yukarı tümsek)
            // İkinci yarım periyot: orta → sağ (aşağı çukur)
            var pathFigure = new PathFigure
            {
                StartPoint = new Point(waveLeft, centerY),
                IsClosed = false
            };

            // Yarım periyot 1: yukarı kavis
            pathFigure.Segments.Add(new BezierSegment(
                new Point(waveLeft + 3, centerY - waveAmp),    // Kontrol 1
                new Point(waveMid - 3, centerY - waveAmp),     // Kontrol 2
                new Point(waveMid, centerY),                     // Bitiş: orta nokta
                true));

            // Yarım periyot 2: aşağı kavis
            pathFigure.Segments.Add(new BezierSegment(
                new Point(waveMid + 3, centerY + waveAmp),     // Kontrol 1
                new Point(waveRight - 3, centerY + waveAmp),    // Kontrol 2
                new Point(waveRight, centerY),                    // Bitiş: sağ uç
                true));

            var pathGeometry = new PathGeometry();
            pathGeometry.Figures.Add(pathFigure);
            sineWave.Data = pathGeometry;

            // ── Değer etiketi (ör: "10V 50Hz ∠30°") ──
            var label = new TextBlock
            {
                Text = FormatValue(),
                FontSize = 12,
                TextAlignment = TextAlignment.Center
            };
            label.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.LabelSecondary");
            label.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            label.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(label, centerX - (label.DesiredSize.Width / 2));
            Canvas.SetTop(label, centerY - CircleRadius - label.DesiredSize.Height - 2);

            // ── ID etiketi (ör: "VAC1") ──
            var idLabel = new TextBlock
            {
                Text = Id,
                FontSize = 12
            };
            idLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Label");
            idLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            idLabel.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(idLabel, centerX - (idLabel.DesiredSize.Width / 2));
            Canvas.SetTop(idLabel, centerY + CircleRadius + 2);

            // Tüm şekilleri container'a ekle
            container.Children.Add(leftLead);
            container.Children.Add(rightLead);
            container.Children.Add(circle);
            container.Children.Add(sineWave);
            container.Children.Add(label);
            container.Children.Add(idLabel);

            // Pin göstergelerini ekle (base class'tan miras)
            AddPinIndicators(container);

            return container;
        }

        /// <summary>
        /// SPICE SINE kaynak formatında Netlist satırı üretir.
        /// 
        /// Format: SINE(V_offset V_amplitude Frequency T_delay Damping Phase)
        /// 
        /// Örnek: V1 1 0 SINE(0 10 50 0 0 30)
        ///   → DC offset = 0V (saf AC)
        ///   → Genlik = 10V (tepe değer)
        ///   → Frekans = 50Hz
        ///   → Zaman gecikmesi = 0s
        ///   → Sönümleme = 0 (sönümsüz)
        ///   → Faz = 30°
        /// 
        /// Zaman alanı denklemi:
        ///   v(t) = 0 + 10 × sin(2π × 50 × t + 30°)
        /// 
        /// Fazör gösterimi (Python backend'e gönderilecek):
        ///   V = 10 ∠ 30° V  (veya 10·e^(j·30°) V)
        /// </summary>
        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int nodePlus = nodeMap[Pins[0]];
            int nodeMinus = nodeMap[Pins[1]];

            // Fiziksel mod → SPICE SINE formatı
            // Fazör mod → özel AC_PHASOR formatı (frekans JSON ile ayrıca gönderilir)
            if (InputMode == AcInputMode.Phasor)
            {
                string mag = Amplitude.ToString(CultureInfo.InvariantCulture);
                string ph = Phase.ToString(CultureInfo.InvariantCulture);
                return $"{Id} {nodePlus} {nodeMinus} AC_PHASOR({mag}, {ph})";
            }

            string amp = Amplitude.ToString(CultureInfo.InvariantCulture);
            string freq = Frequency.ToString(CultureInfo.InvariantCulture);
            string phase = Phase.ToString(CultureInfo.InvariantCulture);

            return $"{Id} {nodePlus} {nodeMinus} SINE(0 {amp} {freq} 0 0 {phase})";
        }

        /// <summary>
        /// Değerleri okunabilir formatta gösterir.
        /// Örnek: "10V 50Hz ∠30°"
        /// </summary>
        private string FormatValue()
        {
            string ampStr;
            if (Amplitude >= 1000)
                ampStr = $"{Amplitude / 1000:G3}kV";
            else if (Amplitude >= 1)
                ampStr = $"{Amplitude:G3}V";
            else
                ampStr = $"{Amplitude * 1000:G3}mV";

            // Fazör modunda: "10V∠30°" (frekans gösterilmez)
            if (InputMode == AcInputMode.Phasor)
            {
                return $"{ampStr}∠{Phase:G3}°";
            }

            // Fiziksel modda: "10V 50Hz ∠30°"
            string freqStr;
            if (Frequency >= 1_000_000)
                freqStr = $"{Frequency / 1_000_000:G3}MHz";
            else if (Frequency >= 1000)
                freqStr = $"{Frequency / 1000:G3}kHz";
            else
                freqStr = $"{Frequency:G3}Hz";

            if (Math.Abs(Phase) < 0.01)
                return $"{ampStr} {freqStr}";

            return $"{ampStr} {freqStr} ∠{Phase:G3}°";
        }
    }
}
