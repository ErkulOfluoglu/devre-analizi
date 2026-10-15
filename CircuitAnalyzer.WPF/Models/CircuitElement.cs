using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>
    /// Tüm devre elemanlarının (direnç, kaynak, kondansatör, bobin vb.)
    /// miras alacağı soyut (abstract) temel sınıf.
    /// 
    /// OOP Tasarım Kararları:
    /// 1. Her eleman kendi görselini (CreateVisual) ve Netlist satırını
    ///    (ToNetlistEntry) üretmekten sorumludur.
    /// 2. Pinler, elemanın gövdesine göre sabit konumlarda tanımlanır.
    /// 3. Position, elemanın Canvas üzerindeki sol-üst köşe konumudur
    ///    ve her zaman grid'e snap'lenir.
    /// </summary>
    public abstract class CircuitElement
    {
        /// <summary>
        /// Elemanın benzersiz kimliği.
        /// SPICE Netlist formatında kullanılır: R1, R2, V1, C1 vb.
        /// </summary>
        public string Id { get; set; } = string.Empty;

        /// <summary>
        /// Elemanın Canvas üzerindeki konumu (sol-üst köşe).
        /// Her zaman GridHelper.Snap() ile grid'e oturtulmuş olmalıdır.
        /// </summary>
        public Point Position { get; set; }

        /// <summary>Elemanın değeri (ör: 1000 ohm, 5 volt)</summary>
        public double Value { get; set; }

        /// <summary>Değerin birimi (ör: "Ω", "V", "A", "F", "H")</summary>
        public string Unit { get; set; } = string.Empty;

        /// <summary>
        /// Elemanın dönüş açısı (0°, 90°, 180°, 270°).
        /// Döndürme işleminde pinlerin göreceli konumları da güncellenir.
        /// RenderTransform ile görsel döndürme, Pin.AbsolutePosition
        /// ile elektriksel bağlantı hesaplaması yapılır.
        /// </summary>
        public double Rotation { get; set; }

        /// <summary>Elemanın bağlantı noktaları (pinleri)</summary>
        public List<Pin> Pins { get; set; } = new();

        /// <summary>
        /// Elemanın görsel genişliği (piksel).
        /// Pin döndürme hesaplamasında merkez noktası bulmak için kullanılır.
        /// Tüm elemanlarımız 80px genişliğindedir; farklı boyutlu bir eleman
        /// eklenirse bu özellik override edilir.
        /// </summary>
        public virtual double VisualWidth => 80;

        /// <summary>
        /// Elemanın görsel yüksekliği (piksel).
        /// Döndürme merkezinin Y bileşeni = VisualHeight / 2.
        /// </summary>
        public virtual double VisualHeight => 40;

        /// <summary>
        /// Elemanın Canvas üzerinde gösterilecek görsel temsilini oluşturur.
        /// Her alt sınıf (Resistor, VoltageSource vb.) kendi sembolünü çizer.
        /// Dönen UIElement, MainWindow'daki Canvas'a eklenir.
        /// </summary>
        public abstract UIElement CreateVisual();

        /// <summary>
        /// Elemanı SPICE Netlist formatına çevirir.
        /// nodeMap: Her pinin hangi düğüm numarasına bağlı olduğunu belirtir.
        /// Örnek çıktı: "R1 1 0 1000" (R1 direnci, düğüm 1 ile 0 arasında, 1000Ω)
        /// </summary>
        /// <param name="nodeMap">Pin → Düğüm numarası eşleştirmesi</param>
        public abstract string ToNetlistEntry(Dictionary<Pin, int> nodeMap);

        /// <summary>
        /// Pin noktalarını gösteren küçük daireler oluşturur.
        /// Kullanıcı hangi noktalarda bağlantı yapabileceğini böyle görür.
        /// </summary>
        protected void AddPinIndicators(Canvas container)
        {
            foreach (var pin in Pins)
            {
                var indicator = new Ellipse
                {
                    Width = 6,
                    Height = 6,
                    StrokeThickness = 1
                };
                indicator.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Pin");
                indicator.SetResourceReference(Shape.StrokeProperty, "Brush.Circuit.Fill");
                Canvas.SetLeft(indicator, pin.RelativePosition.X - 3); // -3: merkez hizalama
                Canvas.SetTop(indicator, pin.RelativePosition.Y - 3);
                container.Children.Add(indicator);
            }
        }
    }
}
