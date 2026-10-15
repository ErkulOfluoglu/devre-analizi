using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests
{
    [Collection(WpfUiCollection.Name)]
    public class OnboardingTests
    {
        private static void RunOnSta(Action action)
        {
            Exception? ex = null;
            var thread = new Thread(() =>
            {
                try
                {
                    action();
                }
                catch (Exception e)
                {
                    ex = e;
                }
            });
            thread.SetApartmentState(ApartmentState.STA);
            thread.Start();
            thread.Join();

            if (ex != null)
            {
                ExceptionDispatchInfo.Capture(ex).Throw();
            }
        }

        [Fact]
        public void PageNavigation_NextBack_StaysWithinBounds()
        {
            RunOnSta(() =>
            {
                var view = new OnboardingView();

                Assert.Equal(0, view.Page);

                // Geri basınca 0'ın altına inmemeli
                view.Back();
                Assert.Equal(0, view.Page);

                // İleri adımları
                view.Next();
                Assert.Equal(1, view.Page);
                view.Next();
                Assert.Equal(2, view.Page);
                view.Next();
                Assert.Equal(3, view.Page);
                view.Next();
                Assert.Equal(4, view.Page);

                // 4'ün üstüne çıkmamalı
                view.Next();
                Assert.Equal(4, view.Page);

                // Doğrudan aralık dışı değer atamaları kelepçelenmeli
                view.Page = -10;
                Assert.Equal(0, view.Page);

                view.Page = 99;
                Assert.Equal(4, view.Page);
            });
        }

        [Fact]
        public void Dots_UpdateActiveVisualWidth()
        {
            RunOnSta(() =>
            {
                var view = new OnboardingView();

                view.Page = 0;
                Assert.Equal(22, view.DotVisual0.Width);
                Assert.Equal(8, view.DotVisual1.Width);

                view.Page = 2;
                Assert.Equal(8, view.DotVisual0.Width);
                Assert.Equal(22, view.DotVisual2.Width);
            });
        }

        [Fact]
        public void ResultValues_Atla_SetsSkipped()
        {
            RunOnSta(() =>
            {
                var view = new OnboardingView();
                view.BtnSkip.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));

                Assert.Equal(OnboardingResult.Skipped, view.Result);
            });
        }

        [Fact]
        public void ResultValues_StartTour_SetsStartTour()
        {
            RunOnSta(() =>
            {
                var view = new OnboardingView { Page = 4 };
                view.BtnStartTour.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));

                Assert.Equal(OnboardingResult.StartTour, view.Result);
            });
        }

        [Fact]
        public void ResultValues_StartExample_SetsStartExample()
        {
            RunOnSta(() =>
            {
                var view = new OnboardingView { Page = 4 };
                view.BtnStartExample.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));

                Assert.Equal(OnboardingResult.StartExample, view.Result);
            });
        }

        [Fact]
        public void OnboardingOverlay_ClosedRaisedOnHostGrid_AtlaEscFinalButtons()
        {
            RunOnSta(() =>
            {
                var hostGrid = new Grid
                {
                    Width = 1000,
                    Height = 700
                };

                var overlay = new OnboardingOverlay
                {
                    Width = 1000,
                    Height = 700
                };
                hostGrid.Children.Add(overlay);

                // 1. Atla butonu -> Skipped
                overlay.Show(0, animate: false);
                OnboardingResult? result = null;
                overlay.Closed += r => result = r;

                overlay.View.BtnSkip.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                Assert.Equal(OnboardingResult.Skipped, result);
                Assert.Equal(Visibility.Collapsed, overlay.Visibility);

                // 2. Esc tuşu -> Skipped
                overlay.Show(0, animate: false);
                result = null;
                overlay.HandleKeyDown(System.Windows.Input.Key.Escape);
                Assert.Equal(OnboardingResult.Skipped, result);
                Assert.Equal(Visibility.Collapsed, overlay.Visibility);

                // 3. 5. sayfadaki "Örnek devreyle başla" -> StartExample
                overlay.Show(4, animate: false);
                result = null;
                overlay.View.BtnStartExample.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                Assert.Equal(OnboardingResult.StartExample, result);
                Assert.Equal(Visibility.Collapsed, overlay.Visibility);

                // 4. 5. sayfadaki "Uygulamayı gezdir" -> StartTour
                overlay.Show(4, animate: false);
                result = null;
                overlay.View.BtnStartTour.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                Assert.Equal(OnboardingResult.StartTour, result);
                Assert.Equal(Visibility.Collapsed, overlay.Visibility);
            });
        }

        [Fact]
        public void AppSettings_Persistence_WithTempSettingsPath()
        {
            string origPath = AppSettings.SettingsPath;
            string tempDir = Path.Combine(Path.GetTempPath(), "CircuitAnalyzerTests_" + Guid.NewGuid().ToString("N"));
            string tempFile = Path.Combine(tempDir, "settings.json");

            try
            {
                AppSettings.SettingsPath = tempFile;

                Assert.False(AppSettings.OnboardingCompleted);

                AppSettings.OnboardingCompleted = true;
                Assert.True(AppSettings.OnboardingCompleted);

                // Dosyanın gerçekten diske yazıldığını ve tekrar okunduğunu doğrula
                Assert.True(File.Exists(tempFile));
                string json = File.ReadAllText(tempFile);
                Assert.Contains("\"OnboardingCompleted\": true", json);
            }
            finally
            {
                AppSettings.SettingsPath = origPath;
                if (Directory.Exists(tempDir))
                {
                    try { Directory.Delete(tempDir, recursive: true); } catch { }
                }
            }
        }

        [Fact]
        public void TourSteps_HasSixSteps_WithNonEmptyTitlesAndBodies()
        {
            var steps = TourSteps.Steps;

            Assert.Equal(6, steps.Count);

            foreach (var step in steps)
            {
                Assert.False(string.IsNullOrWhiteSpace(step.Title), "Tur adımının başlığı boş olmamalı.");
                Assert.False(string.IsNullOrWhiteSpace(step.Body), "Tur adımının açıklaması boş olmamalı.");
            }
        }

        [Fact]
        public void TourOverlay_StartNextBackEnd_RaisesEndedOnHostGrid()
        {
            RunOnSta(() =>
            {
                var hostGrid = new Grid
                {
                    Width = 1000,
                    Height = 700
                };

                var dummy1 = new Border { Width = 100, Height = 50 };
                var dummy2 = new Border { Width = 120, Height = 60 };
                hostGrid.Children.Add(dummy1);
                hostGrid.Children.Add(dummy2);

                var overlay = new TourOverlay
                {
                    Width = 1000,
                    Height = 700,
                    Steps = new List<TourStep>
                    {
                        new() { TargetAccessor = () => dummy1, Title = "Adım 1", Body = "Gövde 1" },
                        new() { TargetAccessor = () => dummy2, Title = "Adım 2", Body = "Gövde 2" }
                    }
                };
                hostGrid.Children.Add(overlay);

                Assert.False(overlay.IsActive);
                Assert.Equal(Visibility.Collapsed, overlay.Visibility);

                // Başlat
                overlay.Start(0);
                Assert.True(overlay.IsActive);
                Assert.Equal(Visibility.Visible, overlay.Visibility);
                Assert.Equal(0, overlay.Step);

                // İleri
                overlay.Next();
                Assert.Equal(1, overlay.Step);

                // Geri
                overlay.Back();
                Assert.Equal(0, overlay.Step);

                // Bitir
                bool endedCalled = false;
                overlay.Ended += (_, _) => endedCalled = true;

                overlay.End();
                Assert.False(overlay.IsActive);
                Assert.Equal(Visibility.Collapsed, overlay.Visibility);
                Assert.True(endedCalled);
            });
        }
    }
}
