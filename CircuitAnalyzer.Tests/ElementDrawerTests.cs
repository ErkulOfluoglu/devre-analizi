using System;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using CircuitAnalyzer.WPF;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Sol şerit ve açılan eleman listesi: bir kategori açılınca yalnız onun elemanları görünür,
/// eleman seçmek, Esc ya da aynı kategoriye yeniden basmak listeyi kapatır.
/// </summary>
[Collection(WpfUiCollection.Name)]
public class ElementDrawerTests
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
            finally
            {
                System.Windows.Threading.Dispatcher.CurrentDispatcher.InvokeShutdown();
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();

        if (ex != null)
            ExceptionDispatchInfo.Capture(ex).Throw();
    }

    [Fact]
    public void CheckingRail_OpensOnlyThatCategory()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow();
            Assert.False(win.IsElementDrawerOpen);

            win.RailSources.IsChecked = true;
            Assert.True(win.IsElementDrawerOpen);
            Assert.Equal(Visibility.Visible, win.DrawerSources.Visibility);
            Assert.Equal(Visibility.Collapsed, win.DrawerPassive.Visibility);
            Assert.Equal("Kaynaklar", win.TxtDrawerTitle.Text);

            // Başka kategoriye geçmek öncekini kapatır, liste açık kalır
            win.RailPassive.IsChecked = true;
            Assert.True(win.IsElementDrawerOpen);
            Assert.False(win.RailSources.IsChecked);
            Assert.Equal(Visibility.Visible, win.DrawerPassive.Visibility);
            Assert.Equal(Visibility.Collapsed, win.DrawerSources.Visibility);

            // Aynı kategoriye yeniden basmak listeyi kapatır
            win.RailPassive.IsChecked = false;
            Assert.False(win.IsElementDrawerOpen);
        });
    }

    [Fact]
    public void Escape_ClosesDrawerBeforeAnythingElse()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow();
            win.RailMeasure.IsChecked = true;

            Assert.True(win.HandleKeyDown(Key.Escape));
            Assert.False(win.IsElementDrawerOpen);
            Assert.False(win.RailMeasure.IsChecked);
            Assert.False(win.CloseElementDrawer());
        });
    }

    [Fact]
    public void ChoosingElement_ClosesDrawerAndStartsPlacement()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow();
            win.RailPassive.IsChecked = true;

            win.BtnAddResistor.RaiseEvent(new RoutedEventArgs(ButtonBase.ClickEvent));

            Assert.False(win.IsElementDrawerOpen);
            Assert.False(win.RailPassive.IsChecked);
            // Yerleştirme başladı: Esc onu iptal eder (liste zaten kapalı)
            Assert.True(win.HandleKeyDown(Key.Escape));
        });
    }
}
