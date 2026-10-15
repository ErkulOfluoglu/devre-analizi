using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using CircuitAnalyzer.WPF.Controls;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

[Collection(WpfUiCollection.Name)]
public class ThemeTests
{
    private static string FindRepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir != null && !Directory.Exists(Path.Combine(dir.FullName, "CircuitAnalyzer.WPF")))
        {
            dir = dir.Parent;
        }
        if (dir == null)
            throw new InvalidOperationException("Could not find repository root containing CircuitAnalyzer.WPF");
        return dir.FullName;
    }

    [Fact]
    public void LightAndDarkXaml_DefineExactSameKeys()
    {
        string root = FindRepoRoot();
        string lightPath = Path.Combine(root, "CircuitAnalyzer.WPF", "Themes", "Light.xaml");
        string darkPath = Path.Combine(root, "CircuitAnalyzer.WPF", "Themes", "Dark.xaml");

        Assert.True(File.Exists(lightPath), $"Light.xaml not found at {lightPath}");
        Assert.True(File.Exists(darkPath), $"Dark.xaml not found at {darkPath}");

        var keyRegex = new Regex(@"x:Key=""([^""]+)""", RegexOptions.Compiled);

        var lightKeys = keyRegex.Matches(File.ReadAllText(lightPath))
            .Select(m => m.Groups[1].Value)
            .OrderBy(k => k)
            .ToList();

        var darkKeys = keyRegex.Matches(File.ReadAllText(darkPath))
            .Select(m => m.Groups[1].Value)
            .OrderBy(k => k)
            .ToList();

        Assert.NotEmpty(lightKeys);
        Assert.Equal(lightKeys, darkKeys);
    }

    [Fact]
    public void AllReferencedThemeKeys_ExistInThemes()
    {
        string root = FindRepoRoot();
        string wpfDir = Path.Combine(root, "CircuitAnalyzer.WPF");

        var definedKeys = new HashSet<string>(StringComparer.Ordinal);
        var keyRegex = new Regex(@"x:Key=""([^""]+)""", RegexOptions.Compiled);

        foreach (string themeFile in new[] { "Light.xaml", "Icons.xaml", "Controls.xaml" })
        {
            string path = Path.Combine(wpfDir, "Themes", themeFile);
            if (File.Exists(path))
            {
                foreach (Match m in keyRegex.Matches(File.ReadAllText(path)))
                {
                    definedKeys.Add(m.Groups[1].Value);
                }
            }
        }

        Assert.NotEmpty(definedKeys);

        var xamlFiles = Directory.GetFiles(wpfDir, "*.xaml", SearchOption.AllDirectories)
            .Where(p => !p.Contains("\\bin\\") && !p.Contains("\\obj\\"))
            .ToList();

        var dynamicResourceRegex = new Regex(@"\{DynamicResource\s+(?:ResourceKey=)?([A-Za-z0-9_\.]+)\}", RegexOptions.Compiled);
        var missingKeys = new List<string>();

        foreach (string file in xamlFiles)
        {
            string raw = File.ReadAllText(file);
            string withoutComments = Regex.Replace(raw, @"<!--.*?-->", "", RegexOptions.Singleline);

            foreach (Match m in dynamicResourceRegex.Matches(withoutComments))
            {
                string key = m.Groups[1].Value.Trim();
                if ((key.StartsWith("Brush.") || key.StartsWith("Icon.") || key.StartsWith("Text.") ||
                     key.StartsWith("Button.") || key.StartsWith("Card") || key.StartsWith("Chip.") ||
                     key.StartsWith("Pill.") || key.StartsWith("InfoBar.") || key.StartsWith("Segment.") ||
                     key.StartsWith("CheckBox.") || key.StartsWith("Expander.") || key.StartsWith("Toggle.") ||
                     key.StartsWith("Font.") || key.StartsWith("Radius.") || key.StartsWith("Effect.") ||
                     key.StartsWith("Window.")) && !definedKeys.Contains(key))
                {
                    missingKeys.Add($"{Path.GetFileName(file)}: DynamicResource {key}");
                }
            }
        }

        var csFiles = Directory.GetFiles(wpfDir, "*.cs", SearchOption.AllDirectories)
            .Where(p => !p.Contains("\\bin\\") && !p.Contains("\\obj\\"))
            .ToList();

        var csKeyRegex = new Regex(@"(?:SetResourceReference\s*\([^,]+,\s*""([^""]+)""\)|(?:TryFindResource|FindResource)\s*\(\s*""([^""]+)""\))", RegexOptions.Compiled);

        foreach (string file in csFiles)
        {
            string raw = File.ReadAllText(file);
            string withoutComments = Regex.Replace(raw, @"//.*$", "", RegexOptions.Multiline);

            foreach (Match m in csKeyRegex.Matches(withoutComments))
            {
                string key = m.Groups[1].Success ? m.Groups[1].Value : m.Groups[2].Value;
                if ((key.StartsWith("Brush.") || key.StartsWith("Icon.") || key.StartsWith("Text.") ||
                     key.StartsWith("Button.") || key.StartsWith("Card") || key.StartsWith("Chip.") ||
                     key.StartsWith("Pill.") || key.StartsWith("InfoBar.") || key.StartsWith("Segment.") ||
                     key.StartsWith("CheckBox.") || key.StartsWith("Expander.") || key.StartsWith("Toggle.") ||
                     key.StartsWith("Font.") || key.StartsWith("Radius.") || key.StartsWith("Effect.") ||
                     key.StartsWith("Window.")) && !definedKeys.Contains(key))
                {
                    missingKeys.Add($"{Path.GetFileName(file)}: code {key}");
                }
            }
        }

        Assert.Empty(missingKeys);
    }

    [Fact]
    public void ThemeManager_LifecycleAndFallback_WorksWithoutApplicationCurrent()
    {
        string tempSettings = Path.Combine(Path.GetTempPath(), $"settings_test_{Guid.NewGuid():N}.json");
        string originalSettings = ThemeManager.SettingsPath;
        var originalChoice = ThemeManager.Choice;

        try
        {
            ThemeManager.SettingsPath = tempSettings;

            ThemeManager.SetChoice(ThemeChoice.Dark);
            Assert.True(ThemeManager.IsDark);
            Assert.Equal(ThemeChoice.Dark, ThemeManager.Choice);
            Assert.True(File.Exists(tempSettings));
            Assert.Contains("Dark", File.ReadAllText(tempSettings));

            ThemeManager.SetChoice(ThemeChoice.Light);
            Assert.False(ThemeManager.IsDark);
            Assert.Equal(ThemeChoice.Light, ThemeManager.Choice);
            Assert.Contains("Light", File.ReadAllText(tempSettings));

            File.WriteAllText(tempSettings, "invalid corrupted json content {{{ [[");
            var ex = Record.Exception(() => ThemeManager.Initialize());
            Assert.Null(ex);
            Assert.Equal(ThemeChoice.System, ThemeManager.Choice);
        }
        finally
        {
            ThemeManager.SettingsPath = originalSettings;
            ThemeManager.SetChoice(originalChoice);
            if (File.Exists(tempSettings))
            {
                try { File.Delete(tempSettings); } catch { }
            }
        }
    }

    [Fact]
    public void ControlsIcon_RendersWithData_AndDoesNotThrowWithNull()
    {
        Exception? ex = null;
        var thread = new Thread(() =>
        {
            try
            {
                var icon = new Icon
                {
                    Data = Geometry.Parse("M2,12 H22"),
                    Foreground = Brushes.Black,
                    Width = 20,
                    Height = 20
                };

                icon.Measure(new Size(20, 20));
                icon.Arrange(new Rect(0, 0, 20, 20));
                icon.UpdateLayout();

                var rtb = new RenderTargetBitmap(20, 20, 96, 96, PixelFormats.Pbgra32);
                rtb.Render(icon);

                var pixels = new int[20 * 20];
                rtb.CopyPixels(pixels, 20 * 4, 0);

                bool hasNonTransparent = pixels.Any(p => ((p >> 24) & 0xFF) > 0);
                Assert.True(hasNonTransparent, "Icon should render at least one non-transparent pixel.");

                var nullIcon = new Icon
                {
                    Data = null,
                    Foreground = Brushes.Black,
                    Width = 20,
                    Height = 20
                };
                nullIcon.Measure(new Size(20, 20));
                nullIcon.Arrange(new Rect(0, 0, 20, 20));
                nullIcon.UpdateLayout();

                var rtbNull = new RenderTargetBitmap(20, 20, 96, 96, PixelFormats.Pbgra32);
                var nullRenderEx = Record.Exception(() => rtbNull.Render(nullIcon));
                Assert.Null(nullRenderEx);
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
            throw new AggregateException(ex);
    }
}
