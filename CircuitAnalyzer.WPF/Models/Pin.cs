using System;
using System.Windows;

namespace CircuitAnalyzer.WPF.Models
{
    /// <summary>
    /// Bir devre elemanı üzerindeki bağlantı noktasını (pin) temsil eder.
    /// Her pin, elemanın gövdesine göre göreceli (relative) bir konumda durur.
    /// İki farklı elemanın pinleri aynı grid noktasına denk geldiğinde,
    /// Netlist oluşturulurken bu pinler aynı düğüme (node) atanır.
    /// </summary>
    public class Pin
    {
        /// <summary>Pinin benzersiz tanımlayıcısı (ör: "1", "2", "+", "-")</summary>
        public string Id { get; set; } = string.Empty;

        /// <summary>
        /// Pinin, sahibi olan elemanın sol-üst köşesine göre konumu.
        /// Bu konum, eleman 0° dönüşteykenki (yatay) konumdur.
        /// Eleman döndürüldüğünde AbsolutePosition otomatik hesaplanır.
        /// </summary>
        public Point RelativePosition { get; set; }

        /// <summary>Bu pinin ait olduğu devre elemanı</summary>
        public CircuitElement? Owner { get; set; }

        /// <summary>
        /// Canvas üzerindeki mutlak (absolute) konum.
        /// 
        /// ★ Döndürme Desteği:
        /// Eleman döndürüldüğünde (90°, 180°, 270°), pin'in mutlak konumu
        /// elemanın görsel merkezine göre döndürme matrisi ile hesaplanır.
        /// 
        /// Döndürme matrisi (2D rotasyon):
        ///   ┌ x' ┐   ┌ cosθ  -sinθ ┐ ┌ dx ┐   ┌ cx ┐
        ///   │    │ = │             │·│    │ + │    │
        ///   └ y' ┘   └ sinθ   cosθ ┘ └ dy ┘   └ cy ┘
        /// 
        /// Burada:
        ///   (cx, cy) = elemanın görsel merkezi (VisualWidth/2, VisualHeight/2)
        ///   (dx, dy) = pinin merkeze göre ofseti (RelativeX - cx, RelativeY - cy)
        ///   θ = dönüş açısı (radyan)
        /// 
        /// Örnek: Direnç (80×40), Pin1 = (0, 20), 90° döndürme
        ///   Merkez: (40, 20)
        ///   dx = 0 - 40 = -40,  dy = 20 - 20 = 0
        ///   cos90° = 0,  sin90° = 1
        ///   x' = 40 + (-40·0 - 0·1) = 40
        ///   y' = 20 + (-40·1 + 0·0) = -20
        ///   Mutlak: (Position.X + 40, Position.Y - 20) → artık dikey yönde!
        /// </summary>
        public Point AbsolutePosition
        {
            get
            {
                if (Owner == null) return RelativePosition;

                // Eleman döndürülmemişse (0°) → basit toplama
                if (Math.Abs(Owner.Rotation) < 0.01)
                {
                    return new Point(
                        Owner.Position.X + RelativePosition.X,
                        Owner.Position.Y + RelativePosition.Y);
                }

                // Dönüş merkezi = elemanın görsel merkezi
                double cx = Owner.VisualWidth / 2.0;
                double cy = Owner.VisualHeight / 2.0;

                // Pinin merkeze göre ofseti
                double dx = RelativePosition.X - cx;
                double dy = RelativePosition.Y - cy;

                // Açıyı radyana çevir
                double angle = Owner.Rotation * Math.PI / 180.0;
                double cos = Math.Cos(angle);
                double sin = Math.Sin(angle);

                // 2D döndürme matrisi uygula
                double rotatedX = cx + (dx * cos) - (dy * sin);
                double rotatedY = cy + (dx * sin) + (dy * cos);

                return new Point(
                    Owner.Position.X + rotatedX,
                    Owner.Position.Y + rotatedY);
            }
        }
    }
}
