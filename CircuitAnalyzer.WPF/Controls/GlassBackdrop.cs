using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Effects;
using System.Windows.Shapes;
using Microsoft.Win32;

namespace CircuitAnalyzer.WPF.Controls
{
    /// <summary>
    /// Tuvalin üstünde yüzen parçaların camı (DESIGN.md, "Cam kuralları"): Source görselinin
    /// panelin altında kalan kısmını bulanıklaştırır, üstüne yarı saydam bir ton ve
    /// üstü parlak ince bir kenar çizer. WPF'te pencere içi arka plan bulanıklığı olmadığı
    /// için görselin kopyası (VisualBrush) kullanılır.
    ///
    /// Windows'ta saydamlık kapalıysa ya da yüksek karşıtlık modundaysa bulanıklık çizilmez,
    /// panel aynı tonda düz renk olur (Brush.Bg.Popup).
    /// </summary>
    public sealed class GlassBackdrop : Grid
    {
        private const double BlurRadius = 24;

        public static readonly DependencyProperty SourceProperty = DependencyProperty.Register(
            nameof(Source), typeof(Visual), typeof(GlassBackdrop),
            new PropertyMetadata(null, (d, e) => ((GlassBackdrop)d).OnSourceChanged()));

        public static readonly DependencyProperty RadiusProperty = DependencyProperty.Register(
            nameof(Radius), typeof(double), typeof(GlassBackdrop),
            new PropertyMetadata(12.0, (d, e) => ((GlassBackdrop)d).UpdateClip()));

        /// <summary>Tonun kaynak anahtarı: "Brush.Glass.Tint" (araç çubuğu, kart) ya da "Brush.Glass.Acrylic" (eleman listesi).</summary>
        public static readonly DependencyProperty TintKeyProperty = DependencyProperty.Register(
            nameof(TintKey), typeof(string), typeof(GlassBackdrop),
            new PropertyMetadata("Brush.Glass.Tint", (d, e) => ((GlassBackdrop)d).ApplyTint()));

        private readonly VisualBrush _brush = new()
        {
            ViewboxUnits = BrushMappingMode.Absolute,
            Stretch = Stretch.Fill,
            TileMode = TileMode.None,
            AutoLayoutContent = false
        };
        private readonly Rectangle _blurred;
        private readonly Border _sheet;
        private Rect _lastViewbox;

        public GlassBackdrop()
        {
            IsHitTestVisible = false;
            Focusable = false;

            // Opak taban: altındaki gerçek devre camdan net görünmesin, yalnız bulanık kopyası görünsün
            var baseFill = new Rectangle();
            baseFill.SetResourceReference(Shape.FillProperty, "Brush.Glass.Base");
            Children.Add(baseFill);

            _blurred = new Rectangle
            {
                Fill = _brush,
                Margin = new Thickness(-BlurRadius),
                Effect = new BlurEffect { Radius = BlurRadius, RenderingBias = RenderingBias.Performance }
            };
            Children.Add(_blurred);

            _sheet = new Border { BorderThickness = new Thickness(1) };
            _sheet.SetResourceReference(Border.BorderBrushProperty, "Brush.Glass.Edge");
            Children.Add(_sheet);

            ApplyTint();
            LayoutUpdated += (_, _) => UpdateViewbox();
            SizeChanged += (_, _) => UpdateClip();
        }

        public Visual? Source
        {
            get => (Visual?)GetValue(SourceProperty);
            set => SetValue(SourceProperty, value);
        }

        public double Radius
        {
            get => (double)GetValue(RadiusProperty);
            set => SetValue(RadiusProperty, value);
        }

        public string TintKey
        {
            get => (string)GetValue(TintKeyProperty);
            set => SetValue(TintKeyProperty, value);
        }

        /// <summary>Cam çizilebilir mi? Saydamlık kapalı ya da yüksek karşıtlık açıksa hayır.</summary>
        public static bool IsGlassAllowed()
        {
            if (SystemParameters.HighContrast)
                return false;
            try
            {
                using var key = Registry.CurrentUser.OpenSubKey(
                    @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");
                return key?.GetValue("EnableTransparency") is not int v || v != 0;
            }
            catch (Exception)
            {
                return true;
            }
        }

        private void ApplyTint()
        {
            bool glass = IsGlassAllowed();
            _blurred.Visibility = glass ? Visibility.Visible : Visibility.Collapsed;
            _sheet.SetResourceReference(Border.BackgroundProperty, glass ? TintKey : "Brush.Bg.Popup");
        }

        private void OnSourceChanged()
        {
            _brush.Visual = Source;
            _lastViewbox = default;
            UpdateViewbox();
        }

        private void UpdateClip()
        {
            Clip = new RectangleGeometry(new Rect(RenderSize), Radius, Radius);
            _sheet.CornerRadius = new CornerRadius(Radius);
        }

        private void UpdateViewbox()
        {
            if (Source == null || !IsVisible || RenderSize.Width <= 0 || _blurred.Visibility != Visibility.Visible)
                return;
            if (Source is not UIElement target || !target.IsVisible)
                return;

            var topLeft = TransformToVisual(Source).Transform(new Point(-BlurRadius, -BlurRadius));
            var box = new Rect(topLeft, new Size(RenderSize.Width + 2 * BlurRadius, RenderSize.Height + 2 * BlurRadius));
            if (box != _lastViewbox)
            {
                _lastViewbox = box;
                _brush.Viewbox = box;
            }
        }
    }
}
