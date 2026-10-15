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
    /// Empedans giriş modu.
    /// Kullanıcı arayüzde hangi formatta giriş yaptığını belirler.
    /// Her iki modda da arka plandaki ComplexValue aynıdır — sadece
    /// gösterim ve Netlist çıktı formatı değişir.
    /// </summary>
    public enum ImpedanceInputMode
    {
        /// <summary>Dikdörtgensel: Z = a + jb (ör: 50+j30)</summary>
        Rectangular,
        /// <summary>Kutupsal: Z = r∠θ° (ör: 58.31∠30.96°)</summary>
        Polar
    }

    /// <summary>
    /// Genel Empedans (Impedance) devre elemanı.
    /// 
    /// Sınav sorularında devre elemanları fiziksel birim yerine
    /// doğrudan karmaşık empedans olarak verilir:
    ///   "Z₁ = 50 + j30 Ω" veya "Z₂ = 100∠−45° Ω"
    /// 
    /// Bu eleman, öğrencinin bu değerleri doğrudan girmesine olanak tanır.
    /// R, L, C ayrımı yapmadan genel bir empedans kutusu sunar.
    /// 
    /// Görsel yapısı (120×40 piksel, geniş kutu):
    /// 
    ///   Pin1                                              Pin2
    ///    ●━━━━┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓━━━━●
    ///   (0,20)┃  Z     50+j30 Ω               ┃(120,20)
    ///         ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
    /// 
    /// SPICE Netlist formatı (özel uzantı — standart SPICE'ta yoktur):
    ///   Z1 1 2 COMPLEX(50, 30)       ; dikdörtgensel mod
    ///   Z1 1 2 POLAR(58.31, 30.96)   ; kutupsal mod
    /// 
    /// Python backend bu özel formatları regex ile ayrıştırır ve
    /// R-L-C seri/paralel kombinasyonuna dönüştürür.
    /// </summary>
    public class ImpedanceElement : CircuitElement
    {
        // ── Geniş boyut: 120×40 piksel ──
        // Neden 120px? Karmaşık sayı etiketi (ör: "120.5+j314.15Ω")
        // standart 80px'e sığmaz. 120 = 6×20 → grid snap'e uyumlu.
        private const double TotalWidth = 120;
        private const double TotalHeight = 40;
        private const double LeadLength = 16;
        private const double BoxWidth = TotalWidth - (2 * LeadLength); // 88px
        private const double BoxHeight = 30;

        /// <summary>Karmaşık empedans değeri: Z = a + jb</summary>
        public ComplexValue Impedance { get; set; } = ComplexValue.FromRectangular(50, 30);

        /// <summary>
        /// Giriş modu — UI'da ve Netlist'te hangi format kullanılacağını belirler.
        /// Arka plandaki ComplexValue her zaman aynı; sadece gösterim değişir.
        /// </summary>
        public ImpedanceInputMode InputMode { get; set; } = ImpedanceInputMode.Rectangular;

        /// <summary>Geniş boyut: 120px (standart elemanlar 80px)</summary>
        public override double VisualWidth => TotalWidth;

        public ImpedanceElement()
        {
            Unit = "Ω";
            Value = 0; // ComplexValue kullanılıyor, Value alanı kullanılmaz

            Pins.Add(new Pin
            {
                Id = "1",
                RelativePosition = new Point(0, TotalHeight / 2),
                Owner = this
            });
            Pins.Add(new Pin
            {
                Id = "2",
                RelativePosition = new Point(TotalWidth, TotalHeight / 2),
                Owner = this
            });
        }

        /// <summary>
        /// Empedans kutusu çizer: dikdörtgen çerçeve + "Z" harfi + değer etiketi.
        /// Renk: Zümrüt yeşili — R (turkuaz), C (cyan), L (turuncu) ile karışmaz.
        /// </summary>
        public override UIElement CreateVisual()
        {
            var container = new Canvas
            {
                Width = TotalWidth,
                Height = TotalHeight
            };

            double centerY = TotalHeight / 2;
            double boxTop = centerY - (BoxHeight / 2);

            // ── Sol bağlantı teli ──
            var leftLead = new Line
            {
                X1 = 0, Y1 = centerY,
                X2 = LeadLength, Y2 = centerY,
                StrokeThickness = 2
            };
            leftLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(leftLead);

            // ── Sağ bağlantı teli ──
            var rightLead = new Line
            {
                X1 = TotalWidth - LeadLength, Y1 = centerY,
                X2 = TotalWidth, Y2 = centerY,
                StrokeThickness = 2
            };
            rightLead.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            container.Children.Add(rightLead);

            // ── Dikdörtgen gövde ──
            var box = new Rectangle
            {
                Width = BoxWidth,
                Height = BoxHeight,
                StrokeThickness = 2,
                RadiusX = 3,
                RadiusY = 3
            };
            box.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Stroke");
            box.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Fill");
            Canvas.SetLeft(box, LeadLength);
            Canvas.SetTop(box, boxTop);

            // ── "Z" harfi (sol tarafta, büyük) ──
            var zLabel = new TextBlock
            {
                Text = "Z",
                FontSize = 14,
                FontWeight = FontWeights.Bold
            };
            zLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Stroke");
            zLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            Canvas.SetLeft(zLabel, LeadLength + 6);
            Canvas.SetTop(zLabel, boxTop + 4);

            // ── Empedans değer etiketi ──
            string valueText = InputMode == ImpedanceInputMode.Rectangular
                ? Impedance.ToRectangularString() + "Ω"
                : Impedance.ToPolarString().Replace("°", "°Ω");

            var valueLabel = new TextBlock
            {
                Text = valueText,
                FontSize = 12,
                TextAlignment = TextAlignment.Center
            };
            valueLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.LabelSecondary");
            valueLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            valueLabel.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            double valueLabelX = LeadLength + 22;
            Canvas.SetLeft(valueLabel, valueLabelX);
            Canvas.SetTop(valueLabel, boxTop + 8);

            // ── ID etiketi (ör: "Z1") ──
            var idLabel = new TextBlock
            {
                Text = Id,
                FontSize = 12
            };
            idLabel.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Circuit.Label");
            idLabel.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            idLabel.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            Canvas.SetLeft(idLabel, (TotalWidth - idLabel.DesiredSize.Width) / 2);
            Canvas.SetTop(idLabel, boxTop + BoxHeight - 12);

            container.Children.Add(box);
            container.Children.Add(zLabel);
            container.Children.Add(valueLabel);
            container.Children.Add(idLabel);

            AddPinIndicators(container);

            return container;
        }

        /// <summary>
        /// Özel SPICE Netlist formatı üretir.
        /// 
        /// Standart SPICE'ta 'Z' elemanı yoktur. Bu bizim eğitim uzantımızdır.
        /// Python backend regex ile ayrıştırır:
        ///   COMPLEX(a, b)  →  complex(a, b) Python nesnesi
        ///   POLAR(r, θ)    →  r * exp(j*θ*π/180)
        /// </summary>
        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            int node1 = nodeMap[Pins[0]];
            int node2 = nodeMap[Pins[1]];

            string valueStr = InputMode == ImpedanceInputMode.Rectangular
                ? Impedance.ToNetlistRectangular()
                : Impedance.ToNetlistPolar();

            return $"{Id} {node1} {node2} {valueStr}";
        }
    }
}
