using System;
using System.Windows;
using System.Windows.Documents;
using System.Windows.Media;

namespace CircuitAnalyzer.WPF.Controls
{
    /// <summary>
    /// 24×24 birimlik çizgi ikonu çizer (Themes/Icons.xaml geometrileri).
    ///
    /// Rengi yazı rengini izler (TextElement.Foreground kalıtımı): bir düğmenin
    /// içine konunca düğmenin yazı rengini alır, tema değişince kendiliğinden
    /// güncellenir. Şablon gerektirmez — uygulama kaynakları yüklenmeden
    /// (ör. birim testlerinde) de hatasız çalışır.
    /// </summary>
    public sealed class Icon : FrameworkElement
    {
        public static readonly DependencyProperty DataProperty = DependencyProperty.Register(
            nameof(Data), typeof(Geometry), typeof(Icon),
            new FrameworkPropertyMetadata(null, FrameworkPropertyMetadataOptions.AffectsRender));

        public static readonly DependencyProperty ForegroundProperty =
            TextElement.ForegroundProperty.AddOwner(typeof(Icon),
                new FrameworkPropertyMetadata(SystemColors.ControlTextBrush,
                    FrameworkPropertyMetadataOptions.Inherits | FrameworkPropertyMetadataOptions.AffectsRender));

        /// <summary>Çizgi kalınlığı, 24 birimlik kutuya göre (20 px'te ≈ 1.4 px).</summary>
        public static readonly DependencyProperty StrokeThicknessProperty = DependencyProperty.Register(
            nameof(StrokeThickness), typeof(double), typeof(Icon),
            new FrameworkPropertyMetadata(1.7, FrameworkPropertyMetadataOptions.AffectsRender));

        public Geometry? Data
        {
            get => (Geometry?)GetValue(DataProperty);
            set => SetValue(DataProperty, value);
        }

        public Brush Foreground
        {
            get => (Brush)GetValue(ForegroundProperty);
            set => SetValue(ForegroundProperty, value);
        }

        public double StrokeThickness
        {
            get => (double)GetValue(StrokeThicknessProperty);
            set => SetValue(StrokeThicknessProperty, value);
        }

        static Icon()
        {
            WidthProperty.OverrideMetadata(typeof(Icon), new FrameworkPropertyMetadata(20.0));
            HeightProperty.OverrideMetadata(typeof(Icon), new FrameworkPropertyMetadata(20.0));
            SnapsToDevicePixelsProperty.OverrideMetadata(typeof(Icon), new FrameworkPropertyMetadata(true));
        }

        protected override void OnRender(DrawingContext dc)
        {
            var data = Data;
            if (data == null || ActualWidth <= 0 || ActualHeight <= 0)
                return;

            double scale = Math.Min(ActualWidth, ActualHeight) / 24.0;
            var pen = new Pen(Foreground, StrokeThickness)
            {
                StartLineCap = PenLineCap.Round,
                EndLineCap = PenLineCap.Round,
                LineJoin = PenLineJoin.Round,
            };
            dc.PushTransform(new TranslateTransform((ActualWidth - 24 * scale) / 2, (ActualHeight - 24 * scale) / 2));
            dc.PushTransform(new ScaleTransform(scale, scale));
            dc.DrawGeometry(null, pen, data);
            dc.Pop();
            dc.Pop();
        }
    }
}
