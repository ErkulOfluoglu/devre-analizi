using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using CircuitAnalyzer.WPF.Controls;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>Pencere içi mesajın türü: simgesini ve rengini belirler.</summary>
    public enum DialogKind { Info, Warning, Error, Question }

    /// <summary>Pencere içi mesajda bir düğme: Id seçildiğinde döner.</summary>
    public sealed record DialogButton(string Id, string Text, bool IsPrimary = false);

    /// <summary>
    /// Ana pencerenin içinde açılan genel diyalog kartı (ayrı pencere açmaz).
    /// Show(başlık, içerik) ile gösterilir; "Tamam", Esc veya Enter kapatır.
    /// ShowModal ise Windows'un mesaj kutusu gibi kullanıcı bir düğmeye basana kadar bekler
    /// (kaydetme sorusu, hata ve uyarılar), ama uygulamanın içinde ve onun görünüşüyle açılır.
    /// </summary>
    public partial class DialogOverlay : UserControl
    {
        public event Action? Closed;

        public bool IsOpen => Visibility == Visibility.Visible;

        public string Title => TitleText.Text;

        public object? Body => BodyHost.Content;

        public DialogOverlay()
        {
            InitializeComponent();
            Visibility = Visibility.Collapsed;
            SizeChanged += (_, _) => UpdateCardMaxHeight();
        }

        private void UpdateCardMaxHeight()
        {
            double h = ActualHeight;
            if (h <= 0 && Window.GetWindow(this) is { } w)
                h = w.ActualHeight;
            if (h > 48)
                CardBorder.MaxHeight = Math.Max(100, h - 48);
        }

        public void Show(string title, object body, double width = 520, bool animate = true)
        {
            TitleText.Text = title;
            BodyHost.Content = body;
            CardBorder.Width = width;

            Visibility = Visibility.Visible;
            UpdateCardMaxHeight();
            Focus();
            Keyboard.Focus(BtnOk);

            if (!animate)
            {
                Opacity = 1;
                CardScale.ScaleX = CardScale.ScaleY = 1;
                return;
            }

            // Pencere boyu katmanın saydamlığı canlandırılmaz (her karede pencere büyüklüğünde ek
            // çizim demekti): yalnız düz renkli perde ve kart ayrı ayrı belirir. Kart açılış
            // süresince gölgesiyle birlikte tek görüntü olarak önbelleklenir, bitince keskinleşir.
            var duration = TimeSpan.FromMilliseconds(150);
            var ease = new QuadraticEase { EasingMode = EasingMode.EaseOut };
            CardBorder.CacheMode = new BitmapCache { RenderAtScale = 1 };
            var grow = new DoubleAnimation(0.97, 1.0, duration) { EasingFunction = ease };
            grow.Completed += (_, _) => CardBorder.CacheMode = null;
            Scrim.BeginAnimation(OpacityProperty, new DoubleAnimation(0, 1, duration));
            CardBorder.BeginAnimation(OpacityProperty, new DoubleAnimation(0, 1, duration) { EasingFunction = ease });
            CardScale.BeginAnimation(ScaleTransform.ScaleXProperty, grow);
            CardScale.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(0.97, 1.0, duration) { EasingFunction = ease });
        }

        private DispatcherFrame? _modalFrame;
        private string? _modalResult;
        private string? _cancelId;
        private string? _defaultId;

        /// <summary>Bekleyen bir soru açık mı?</summary>
        public bool IsModal => _modalFrame != null;

        /// <summary>
        /// Simgeli bir mesaj gösterir ve kullanıcı bir düğmeye basana kadar bekler; seçilen
        /// düğmenin Id'sini döner. Esc cancelId'yi (yoksa varsayılan düğmeyi), Enter odaklı ya da
        /// varsayılan (IsPrimary) düğmeyi seçer.
        /// </summary>
        public string? ShowModal(string title, object message, DialogKind kind, IReadOnlyList<DialogButton> buttons, string? cancelId = null)
        {
            if (IsOpen)
                Close(animate: false);

            ChoiceButtons.Children.Clear();
            Button? focus = null;
            foreach (var choice in buttons)
            {
                var button = new Button { Content = choice.Text, Tag = choice.Id, Margin = new Thickness(8, 0, 0, 0) };
                button.SetResourceReference(StyleProperty, choice.IsPrimary ? "Button.Primary" : "Button.Secondary");
                button.Click += (_, _) => { _modalResult = choice.Id; Close(); };
                ChoiceButtons.Children.Add(button);
                if (choice.IsPrimary)
                    focus = button;
            }
            ChoiceButtons.Visibility = Visibility.Visible;
            BtnOk.Visibility = Visibility.Collapsed;
            _defaultId = buttons.FirstOrDefault(b => b.IsPrimary)?.Id ?? buttons.FirstOrDefault()?.Id;
            _cancelId = cancelId ?? _defaultId;
            _modalResult = _cancelId;

            Show(title, message is string text ? MessageBody(text, kind) : message, width: 460);
            Keyboard.Focus(focus ?? (IInputElement?)ChoiceButtons.Children.OfType<Button>().FirstOrDefault() ?? this);

            _modalFrame = new DispatcherFrame();
            Dispatcher.PushFrame(_modalFrame);
            _modalFrame = null;

            ChoiceButtons.Children.Clear();
            ChoiceButtons.Visibility = Visibility.Collapsed;
            BtnOk.Visibility = Visibility.Visible;
            return _modalResult;
        }

        /// <summary>Simge + metin: Bilgi mavi, uyarı turuncu, hata kırmızı, soru mavi.</summary>
        private static FrameworkElement MessageBody(string text, DialogKind kind)
        {
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            var icon = new Icon { Width = 22, Height = 22, Margin = new Thickness(0, 0, 14, 0), VerticalAlignment = VerticalAlignment.Top };
            icon.SetResourceReference(Icon.DataProperty, kind is DialogKind.Warning or DialogKind.Error ? "Icon.Warning" : "Icon.Info");
            icon.SetResourceReference(Icon.ForegroundProperty, kind switch
            {
                DialogKind.Warning => "Brush.Warning",
                DialogKind.Error => "Brush.Error",
                _ => "Brush.Accent",
            });
            grid.Children.Add(icon);
            var body = new TextBlock { Text = text };
            body.SetResourceReference(StyleProperty, "Text.Reading");
            Grid.SetColumn(body, 1);
            grid.Children.Add(body);
            return grid;
        }

        public void Close(bool animate = true)
        {
            if (!IsOpen) return;

            void Finish()
            {
                Visibility = Visibility.Collapsed;
                BeginAnimation(OpacityProperty, null);
                Opacity = 1;
                Scrim.BeginAnimation(OpacityProperty, null);
                CardBorder.BeginAnimation(OpacityProperty, null);
                CardBorder.CacheMode = null;
                BodyHost.Content = null;
                Closed?.Invoke();
                if (_modalFrame != null)
                    _modalFrame.Continue = false; // bekleyen ShowModal döner
            }

            if (!animate)
            {
                Finish();
                return;
            }

            var fadeTime = TimeSpan.FromMilliseconds(110);
            CardBorder.CacheMode = new BitmapCache { RenderAtScale = 1 };
            var fade = new DoubleAnimation(0, fadeTime);
            fade.Completed += (_, _) => Finish();
            Scrim.BeginAnimation(OpacityProperty, new DoubleAnimation(0, fadeTime));
            CardBorder.BeginAnimation(OpacityProperty, fade);
        }

        private void BtnOk_Click(object sender, RoutedEventArgs e) => Close();

        private void Absorb_MouseDown(object sender, MouseButtonEventArgs e) => e.Handled = true;

        protected override void OnPreviewKeyDown(KeyEventArgs e)
        {
            base.OnPreviewKeyDown(e);
            if (e.Handled) return;

            if (e.Key is Key.Escape or Key.Enter)
            {
                e.Handled = true;
                if (IsModal)
                {
                    _modalResult = e.Key == Key.Escape
                        ? _cancelId
                        : Keyboard.FocusedElement is Button { Tag: string id } ? id : _defaultId;
                }
                Close();
            }
        }
    }
}
