using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF.Views
{
    /// <summary>
    /// Tanıtım turu kaplaması (spotlight overlay).
    /// Pencereyi yarı saydam karartır, hedef bileşenin etrafında delik açar
    /// ve hemen yanında yönlendirici bir kart gösterir.
    /// </summary>
    public sealed class TourOverlay : Grid
    {
        private readonly Path _scrimPath;
        private readonly Border _calloutCard;
        private readonly TextBlock _txtStep;
        private readonly TextBlock _txtTitle;
        private readonly TextBlock _txtBody;
        private readonly Button _btnEnd;
        private readonly Button _btnBack;
        private readonly Button _btnNext;

        public int Step { get; private set; }
        public bool IsActive { get; private set; }
        public event EventHandler? Ended;

        public IReadOnlyList<TourStep>? Steps { get; set; }

        public TourOverlay()
        {
            Visibility = Visibility.Collapsed;
            ClipToBounds = true;
            Focusable = true;

            // Karartma perdesi (tıklamalar dışarı geçmez)
            _scrimPath = new Path
            {
                HorizontalAlignment = HorizontalAlignment.Stretch,
                VerticalAlignment = VerticalAlignment.Stretch
            };
            _scrimPath.SetResourceReference(Shape.FillProperty, "Brush.Overlay.Scrim");
            _scrimPath.MouseLeftButtonDown += (_, e) => e.Handled = true;
            _scrimPath.MouseRightButtonDown += (_, e) => e.Handled = true;
            Children.Add(_scrimPath);

            // Açıklama kartı (340 px genişliğinde, açılır pencere gölgesi)
            _calloutCard = new Border
            {
                Width = 340,
                HorizontalAlignment = HorizontalAlignment.Left,
                VerticalAlignment = VerticalAlignment.Top
            };
            _calloutCard.SetResourceReference(StyleProperty, "Card");
            _calloutCard.SetResourceReference(EffectProperty, "Effect.Popup");
            _calloutCard.MouseLeftButtonDown += (_, e) => e.Handled = true;
            _calloutCard.MouseRightButtonDown += (_, e) => e.Handled = true;

            var sp = new StackPanel();

            _txtStep = new TextBlock
            {
                Margin = new Thickness(0, 0, 0, 4)
            };
            _txtStep.SetResourceReference(StyleProperty, "Text.Caption");
            sp.Children.Add(_txtStep);

            _txtTitle = new TextBlock
            {
                FontSize = 17,
                FontWeight = FontWeights.SemiBold,
                Margin = new Thickness(0, 0, 0, 6)
            };
            _txtTitle.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
            sp.Children.Add(_txtTitle);

            _txtBody = new TextBlock
            {
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 16)
            };
            _txtBody.SetResourceReference(StyleProperty, "Text.Body");
            sp.Children.Add(_txtBody);

            // Düğmeler satırı
            var dock = new DockPanel { LastChildFill = false };

            _btnEnd = new Button
            {
                Content = "Turu bitir",
                Height = 36
            };
            _btnEnd.SetResourceReference(StyleProperty, "Button.Ghost");
            _btnEnd.Click += (_, _) => End();
            DockPanel.SetDock(_btnEnd, Dock.Left);
            dock.Children.Add(_btnEnd);

            var rightButtons = new StackPanel
            {
                Orientation = Orientation.Horizontal
            };
            DockPanel.SetDock(rightButtons, Dock.Right);

            _btnBack = new Button
            {
                Content = "Geri",
                Height = 36,
                Margin = new Thickness(0, 0, 8, 0)
            };
            _btnBack.SetResourceReference(StyleProperty, "Button.Secondary");
            _btnBack.Click += (_, _) => Back();
            rightButtons.Children.Add(_btnBack);

            _btnNext = new Button
            {
                Content = "İleri",
                Height = 36
            };
            _btnNext.SetResourceReference(StyleProperty, "Button.Primary");
            _btnNext.Click += (_, _) =>
            {
                var steps = GetResolvedSteps();
                if (Step >= steps.Count - 1)
                    End();
                else
                    Next();
            };
            rightButtons.Children.Add(_btnNext);

            dock.Children.Add(rightButtons);
            sp.Children.Add(dock);

            _calloutCard.Child = sp;
            Children.Add(_calloutCard);

            PreviewKeyDown += TourOverlay_PreviewKeyDown;
        }

        private void TourOverlay_PreviewKeyDown(object sender, KeyEventArgs e)
        {
            if (e.Key == Key.Escape)
            {
                e.Handled = true;
                End();
            }
        }

        private IReadOnlyList<TourStep> GetResolvedSteps()
        {
            if (Steps != null && Steps.Count > 0)
                return Steps;
            var win = Window.GetWindow(this) as MainWindow;
            return TourSteps.CreateDefaultSteps(win);
        }

        public void Start(int initialStep = 0)
        {
            var steps = GetResolvedSteps();
            if (steps.Count == 0)
                return;

            Step = Math.Clamp(initialStep, 0, steps.Count - 1);
            IsActive = true;
            Visibility = Visibility.Visible;
            Focus();
            UpdateLayoutAndPosition();
        }

        public void Next()
        {
            var steps = GetResolvedSteps();
            if (Step < steps.Count - 1)
            {
                Step++;
                UpdateLayoutAndPosition();
            }
            else
            {
                End();
            }
        }

        public void Back()
        {
            if (Step > 0)
            {
                Step--;
                UpdateLayoutAndPosition();
            }
        }

        public void End()
        {
            if (!IsActive && Visibility != Visibility.Visible)
                return;

            IsActive = false;
            Visibility = Visibility.Collapsed;
            Ended?.Invoke(this, EventArgs.Empty);
        }

        protected override void OnRenderSizeChanged(SizeChangedInfo sizeInfo)
        {
            base.OnRenderSizeChanged(sizeInfo);
            if (IsActive)
            {
                UpdateLayoutAndPosition();
            }
        }

        public void UpdateLayoutAndPosition()
        {
            var steps = GetResolvedSteps();
            if (steps.Count == 0 || Step < 0 || Step >= steps.Count)
                return;

            var currentStep = steps[Step];
            _txtStep.Text = $"{Step + 1} / {steps.Count}";
            _txtTitle.Text = currentStep.Title;
            _txtBody.Text = currentStep.Body;
            _btnBack.Visibility = Step > 0 ? Visibility.Visible : Visibility.Collapsed;
            _btnNext.Content = Step == steps.Count - 1 ? "Bitir" : "İleri";

            double w = ActualWidth > 0 ? ActualWidth : (Parent is FrameworkElement fe ? fe.ActualWidth : 1280);
            double h = ActualHeight > 0 ? ActualHeight : (Parent is FrameworkElement pfe ? pfe.ActualHeight : 800);
            if (w <= 0) w = 1280;
            if (h <= 0) h = 800;

            var target = currentStep.TargetAccessor?.Invoke();
            Rect holeRect;

            if (target != null && target.IsVisible && target.ActualWidth > 0 && target.ActualHeight > 0)
            {
                try
                {
                    var transform = target.TransformToVisual(this);
                    var bounds = transform.TransformBounds(new Rect(0, 0, target.ActualWidth, target.ActualHeight));
                    holeRect = new Rect(bounds.X - 6, bounds.Y - 6, bounds.Width + 12, bounds.Height + 12);
                }
                catch (Exception)
                {
                    holeRect = new Rect(Math.Max(0, (w - 240) / 2), Math.Max(0, (h - 140) / 2), 240, 140);
                }
            }
            else
            {
                holeRect = new Rect(Math.Max(0, (w - 240) / 2), Math.Max(0, (h - 140) / 2), 240, 140);
            }

            var fullGeom = new RectangleGeometry(new Rect(0, 0, w, h));
            var holeGeom = new RectangleGeometry(holeRect, 14, 14);
            _scrimPath.Data = new CombinedGeometry(GeometryCombineMode.Exclude, fullGeom, holeGeom);

            // Açıklama kartı konumu hesaplama
            double cardW = 340;
            _calloutCard.Measure(new Size(cardW, double.PositiveInfinity));
            double cardH = _calloutCard.DesiredSize.Height > 0 ? _calloutCard.DesiredSize.Height : 200;

            double x, y;
            // Hedefin sağına veya soluna yerleştir; sığmazsa altına veya üstüne
            if (holeRect.Right + 16 + cardW <= w)
            {
                x = holeRect.Right + 16;
                y = holeRect.Top + (holeRect.Height - cardH) / 2;
            }
            else if (holeRect.Left - 16 - cardW >= 0)
            {
                x = holeRect.Left - 16 - cardW;
                y = holeRect.Top + (holeRect.Height - cardH) / 2;
            }
            else if (holeRect.Bottom + 16 + cardH <= h)
            {
                x = holeRect.Left + (holeRect.Width - cardW) / 2;
                y = holeRect.Bottom + 16;
            }
            else
            {
                x = holeRect.Left + (holeRect.Width - cardW) / 2;
                y = Math.Max(16, holeRect.Top - 16 - cardH);
            }

            // Ekran sınırlarına kelepçele
            x = Math.Max(16, Math.Min(w - cardW - 16, x));
            y = Math.Max(16, Math.Min(h - cardH - 16, y));

            _calloutCard.Margin = new Thickness(x, y, 0, 0);
        }
    }
}
