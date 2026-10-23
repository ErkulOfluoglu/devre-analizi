using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>
    /// Tel ortası bağlantı noktası (T-ek / Junction).
    /// 
    /// Bir telin ortasına başka bir tel bağlandığında otomatik oluşturulur.
    ///   - Tek pini kendi merkezindedir (RelativePosition = (0, 0)).
    ///   - 3 veya daha fazla tel bağlıyken Ø 8 DIP dolu daire olarak çizilir.
    ///   - 2 tel bağlıyken görünmezdir, ancak Ø 12 DIP yakalama alanı sayesinde
    ///     seçilebilir ve sürüklenebilir.
    ///   - Değeri, etiketi, düzenleme diyaloğu ve döndürmesi yoktur.
    ///   - Netlist'te bileşen satırı üretmez; pini Union-Find düğüm birleştirmesine katılır.
    /// </summary>
    public class JunctionElement : CircuitElement
    {
        private Ellipse? _dot;
        private int _attachedWireCount;

        public override double VisualWidth => 0;
        public override double VisualHeight => 0;

        /// <summary>Bu bağlantı noktasına bağlı tel sayısı (3+ olduğunda nokta görünür olur).</summary>
        public int AttachedWireCount
        {
            get => _attachedWireCount;
            set
            {
                _attachedWireCount = value;
                if (_dot != null)
                {
                    _dot.Visibility = _attachedWireCount >= 3 ? Visibility.Visible : Visibility.Collapsed;
                }
            }
        }

        public JunctionElement()
        {
            Unit = "";
            Value = 0;

            Pins.Add(new Pin
            {
                Id = "1",
                RelativePosition = new Point(0, 0),
                Owner = this
            });
        }

        public override UIElement CreateVisual()
        {
            var container = new Canvas
            {
                Width = 0,
                Height = 0
            };
            Panel.SetZIndex(container, 5);

            // Görünmez yakalama alanı (Ø 12 DIP) — sürükleme ve seçim için
            var hitArea = new Ellipse
            {
                Width = 12,
                Height = 12,
                Fill = Brushes.Transparent
            };
            Canvas.SetLeft(hitArea, -6);
            Canvas.SetTop(hitArea, -6);
            container.Children.Add(hitArea);

            // 3 veya daha fazla tel bağlıyken çizilen dolu nokta (Ø 8 DIP)
            _dot = new Ellipse
            {
                Width = 8,
                Height = 8,
                IsHitTestVisible = false,
                Visibility = _attachedWireCount >= 3 ? Visibility.Visible : Visibility.Collapsed
            };
            _dot.SetResourceReference(Shape.FillProperty, "Brush.Circuit.Wire");
            Canvas.SetLeft(_dot, -4);
            Canvas.SetTop(_dot, -4);
            container.Children.Add(_dot);

            return container;
        }

        public override string ToNetlistEntry(Dictionary<Pin, int> nodeMap)
        {
            return string.Empty;
        }
    }
}
