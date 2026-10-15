using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using CircuitAnalyzer.WPF;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

[Collection(WpfUiCollection.Name)]
public class DialogOverlayTests
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

    private static void PumpDispatcher(Func<bool> condition, int timeoutMs = 2000)
    {
        var sw = Stopwatch.StartNew();
        while (!condition() && sw.ElapsedMilliseconds < timeoutMs)
        {
            var frame = new DispatcherFrame();
            Dispatcher.CurrentDispatcher.BeginInvoke(
                DispatcherPriority.Background,
                new Action(() => frame.Continue = false));
            Dispatcher.PushFrame(frame);
            Thread.Sleep(10);
        }
    }

    private static string FindRepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir != null && !File.Exists(Path.Combine(dir.FullName, "CircuitAnalyzer.sln")))
        {
            dir = dir.Parent;
        }
        if (dir == null)
            throw new InvalidOperationException("Could not find repository root containing CircuitAnalyzer.sln");
        return dir.FullName;
    }

    private static List<string> GetAllTexts(DependencyObject root)
    {
        var list = new List<string>();
        var visited = new HashSet<DependencyObject>();

        void Collect(DependencyObject? obj)
        {
            if (obj == null || !visited.Add(obj)) return;

            if (obj is TextBlock tb && !string.IsNullOrEmpty(tb.Text))
                list.Add(tb.Text);
            else if (obj is TextBox txt && !string.IsNullOrEmpty(txt.Text))
                list.Add(txt.Text);
            else if (obj is Button btn && btn.Content is string bs)
                list.Add(bs);

            foreach (var child in LogicalTreeHelper.GetChildren(obj))
            {
                if (child is DependencyObject dChild)
                {
                    Collect(dChild);
                }
            }

            if (obj is Visual || obj is System.Windows.Media.Media3D.Visual3D)
            {
                int count = VisualTreeHelper.GetChildrenCount(obj);
                for (int i = 0; i < count; i++)
                {
                    Collect(VisualTreeHelper.GetChild(obj, i));
                }
            }

            if (obj is Panel panel)
            {
                foreach (UIElement child in panel.Children)
                {
                    Collect(child);
                }
            }
            else if (obj is Decorator decorator && decorator.Child != null)
            {
                Collect(decorator.Child);
            }
            else if (obj is ContentControl cc && cc.Content is DependencyObject docContent)
            {
                Collect(docContent);
            }
        }

        Collect(root);
        return list;
    }

    [Fact]
    public void Test1_ShowAndClose_WithoutAnimation()
    {
        RunOnSta(() =>
        {
            var overlay = new DialogOverlay();
            int closedCount = 0;
            overlay.Closed += () => closedCount++;

            var bodyObj = new TextBlock { Text = "Test Body" };
            overlay.Show("Test Title", bodyObj, animate: false);

            Assert.True(overlay.IsOpen);
            Assert.Equal("Test Title", overlay.Title);
            Assert.Same(bodyObj, overlay.Body);
            Assert.Equal(0, closedCount);

            overlay.Close(animate: false);

            Assert.False(overlay.IsOpen);
            Assert.Equal(1, closedCount);
            Assert.Null(overlay.Body);
        });
    }

    [Fact]
    public void Test2_EscapeAndEnter_CloseOverlay()
    {
        RunOnSta(() =>
        {
            var window = new Window
            {
                Width = 800,
                Height = 600,
                WindowStartupLocation = WindowStartupLocation.Manual,
                Left = -20000,
                Top = -20000,
                ShowActivated = false
            };
            var overlay = new DialogOverlay();
            window.Content = overlay;
            window.Show();

            var source = PresentationSource.FromVisual(overlay);
            Assert.NotNull(source);

            // 1. Esc tuşu ile kapatma
            overlay.Show("Title Esc", new TextBlock { Text = "Body" }, animate: false);
            Assert.True(overlay.IsOpen);

            var escArgs = new KeyEventArgs(Keyboard.PrimaryDevice, source, 0, Key.Escape)
            {
                RoutedEvent = UIElement.PreviewKeyDownEvent
            };
            overlay.RaiseEvent(escArgs);
            PumpDispatcher(() => !overlay.IsOpen);

            Assert.False(overlay.IsOpen);
            Assert.True(escArgs.Handled);

            // 2. Enter tuşu ile kapatma
            overlay.Show("Title Enter", new TextBlock { Text = "Body" }, animate: false);
            Assert.True(overlay.IsOpen);

            var enterArgs = new KeyEventArgs(Keyboard.PrimaryDevice, source, 0, Key.Enter)
            {
                RoutedEvent = UIElement.PreviewKeyDownEvent
            };
            overlay.RaiseEvent(enterArgs);
            PumpDispatcher(() => !overlay.IsOpen);

            Assert.False(overlay.IsOpen);
            Assert.True(enterArgs.Handled);

            window.Close();
        });
    }

    [Fact]
    public void Test3_ClickingBtnOk_ClosesOverlay()
    {
        RunOnSta(() =>
        {
            var window = new Window
            {
                Width = 800,
                Height = 600,
                WindowStartupLocation = WindowStartupLocation.Manual,
                Left = -20000,
                Top = -20000,
                ShowActivated = false
            };
            var overlay = new DialogOverlay();
            window.Content = overlay;
            window.Show();

            int closedCount = 0;
            overlay.Closed += () => closedCount++;

            overlay.Show("Title Ok", new TextBlock { Text = "Body" }, animate: false);
            Assert.True(overlay.IsOpen);

            overlay.BtnOk.RaiseEvent(new RoutedEventArgs(ButtonBase.ClickEvent));
            PumpDispatcher(() => !overlay.IsOpen);

            Assert.False(overlay.IsOpen);
            Assert.Equal(1, closedCount);

            window.Close();
        });
    }

    [Fact]
    public void Test4_CloseWhenNotOpen_DoesNothing()
    {
        RunOnSta(() =>
        {
            var overlay = new DialogOverlay();
            int closedCount = 0;
            overlay.Closed += () => closedCount++;

            Assert.False(overlay.IsOpen);
            overlay.Close(animate: false);

            Assert.False(overlay.IsOpen);
            Assert.Equal(0, closedCount);
        });
    }

    [Fact]
    public void Test5_BuildShortcutsView_ContainsAllGroupsAndKeys()
    {
        RunOnSta(() =>
        {
            // 1. Gruplar tam olarak "Çözüm", "Dosya", "Düzen", "Görünüm" olmalı
            string[] expectedGroups = { "Çözüm", "Dosya", "Düzen", "Görünüm" };
            var actualGroups = MainWindow.ShortcutGroups.Select(g => g.Group).ToArray();
            Assert.Equal(expectedGroups, actualGroups);

            // 2. F5, Ctrl+S, Ctrl+Z, Ctrl+Y, Ctrl+P, Delete öğelerini içermeli
            string[] requiredKeys = { "F5", "Ctrl+S", "Ctrl+Z", "Ctrl+Y", "Ctrl+P", "Delete" };
            var allShortcutKeys = MainWindow.ShortcutGroups.SelectMany(g => g.Items).Select(i => i.Key).ToList();
            foreach (string reqKey in requiredKeys)
            {
                Assert.Contains(reqKey, allShortcutKeys);
            }

            // 3. BuildShortcutsView() ağacında tüm Key ve Desc metinleri TextBlock olarak bulunmalı
            var shortcutsElement = MainWindow.BuildShortcutsView();
            var texts = GetAllTexts(shortcutsElement);

            foreach (var (group, items) in MainWindow.ShortcutGroups)
            {
                Assert.Contains(group, texts);
                foreach (var (key, desc) in items)
                {
                    Assert.Contains(key, texts);
                    Assert.Contains(desc, texts);
                }
            }

            foreach (string reqKey in requiredKeys)
            {
                Assert.Contains(reqKey, texts);
            }
        });
    }

    [Fact]
    public void Test6_ShortcutGroupsMatchWindowPreviewKeyDown()
    {
        string root = FindRepoRoot();
        string mainWindowCsPath = Path.Combine(root, "CircuitAnalyzer.WPF", "MainWindow.xaml.cs");
        Assert.True(File.Exists(mainWindowCsPath), $"MainWindow.xaml.cs not found at {mainWindowCsPath}");

        string sourceText = File.ReadAllText(mainWindowCsPath);

        // Window_PreviewKeyDown metodunun gövdesini sınırla
        int methodIndex = sourceText.IndexOf("void Window_PreviewKeyDown(", StringComparison.Ordinal);
        Assert.True(methodIndex > 0, "Window_PreviewKeyDown method not found");

        int methodEndIndex = sourceText.IndexOf("void OnPreviewKeyUp(", methodIndex, StringComparison.Ordinal);
        Assert.True(methodEndIndex > methodIndex, "End of Window_PreviewKeyDown could not be located");

        string previewKeyDownBody = sourceText.Substring(methodIndex, methodEndIndex - methodIndex);

        var allShortcuts = MainWindow.ShortcutGroups.SelectMany(g => g.Items).Select(i => i.Key).ToList();

        foreach (string key in allShortcuts)
        {
            string? expectedKeyEnum = null;

            if (key.StartsWith("Ctrl+", StringComparison.Ordinal) && key.Length == 6 && char.IsLetter(key[5]))
            {
                // Ctrl+N, Ctrl+O, Ctrl+S, Ctrl+P, Ctrl+Z, Ctrl+Y
                expectedKeyEnum = key[5].ToString().ToUpperInvariant();
            }
            else if (key == "F5")
            {
                expectedKeyEnum = "F5";
            }
            else if (key == "Delete")
            {
                expectedKeyEnum = "Delete";
            }
            else if (key == "R")
            {
                expectedKeyEnum = "R";
            }
            else if (key == "Esc")
            {
                expectedKeyEnum = "Escape";
            }

            if (expectedKeyEnum != null)
            {
                Assert.True(
                    previewKeyDownBody.Contains($"Key.{expectedKeyEnum}"),
                    $"Shortcut '{key}' (expected Key.{expectedKeyEnum}) is listed in ShortcutGroups but not handled in Window_PreviewKeyDown");
            }
        }
    }

    [Fact]
    public void MouseClicks_OnScrimAndCard_AreAbsorbed()
    {
        RunOnSta(() =>
        {
            var overlay = new DialogOverlay();
            var grid = (Grid)overlay.Content;
            var scrim = (Border)grid.Children[0];
            var card = overlay.CardBorder;

            var leftClickScrim = new MouseButtonEventArgs(Mouse.PrimaryDevice, 0, MouseButton.Left)
            {
                RoutedEvent = UIElement.MouseLeftButtonDownEvent
            };
            scrim.RaiseEvent(leftClickScrim);
            Assert.True(leftClickScrim.Handled);

            var rightClickScrim = new MouseButtonEventArgs(Mouse.PrimaryDevice, 0, MouseButton.Right)
            {
                RoutedEvent = UIElement.MouseRightButtonDownEvent
            };
            scrim.RaiseEvent(rightClickScrim);
            Assert.True(rightClickScrim.Handled);

            var leftClickCard = new MouseButtonEventArgs(Mouse.PrimaryDevice, 0, MouseButton.Left)
            {
                RoutedEvent = UIElement.MouseLeftButtonDownEvent
            };
            card.RaiseEvent(leftClickCard);
            Assert.True(leftClickCard.Handled);

            var rightClickCard = new MouseButtonEventArgs(Mouse.PrimaryDevice, 0, MouseButton.Right)
            {
                RoutedEvent = UIElement.MouseRightButtonDownEvent
            };
            card.RaiseEvent(rightClickCard);
            Assert.True(rightClickCard.Handled);
        });
    }
}
