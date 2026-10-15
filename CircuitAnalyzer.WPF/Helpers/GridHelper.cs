using System.Windows;

namespace CircuitAnalyzer.WPF.Helpers
{
    /// <summary>
    /// Grid (ızgara) yakalama mantığını yöneten yardımcı sınıf.
    /// 
    /// Snap-to-Grid neden gerekli?
    /// - Devre elemanlarının pinleri grid noktalarına oturmazsa,
    ///   Netlist oluşturulurken düğüm tespiti hatalı olur.
    /// - Kullanıcının çizdiği devre düzgün ve profesyonel görünür.
    /// - Pin-pin bağlantılarının tespiti basitleşir (aynı grid noktası = aynı düğüm).
    /// </summary>
    public static class GridHelper
    {
        /// <summary>
        /// Grid kareleri arasındaki mesafe (piksel).
        /// 20px, devre çiziminde yaygın kullanılan bir boyuttur.
        /// Elemanlar ve pinler her zaman bu boyutun katlarına hizalanır.
        /// </summary>
        public const double GridSize = 20.0;

        /// <summary>
        /// Tek bir koordinat değerini en yakın grid noktasına yuvarlar.
        /// Örnek: Snap(53) → 60, Snap(47) → 40
        /// Matematiksel formül: round(value / gridSize) × gridSize
        /// </summary>
        public static double Snap(double value)
        {
            return Math.Round(value / GridSize) * GridSize;
        }

        /// <summary>
        /// Bir noktanın (Point) hem X hem Y koordinatlarını
        /// en yakın grid noktasına yuvarlar.
        /// </summary>
        public static Point Snap(Point point)
        {
            return new Point(Snap(point.X), Snap(point.Y));
        }
    }
}
