using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Xunit;

namespace CircuitAnalyzer.Tests;

public class DesignLintTests
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
    public void NoHardCodedColorsInWpfSource()
    {
        string root = FindRepoRoot();
        string wpfDir = Path.Combine(root, "CircuitAnalyzer.WPF");

        var files = Directory.GetFiles(wpfDir, "*.*", SearchOption.AllDirectories)
            .Where(f => f.EndsWith(".cs", StringComparison.OrdinalIgnoreCase) || f.EndsWith(".xaml", StringComparison.OrdinalIgnoreCase))
            .Where(f => !f.Contains("\\bin\\") && !f.Contains("\\obj\\") && !f.Contains("\\Themes\\"))
            .ToList();

        Assert.NotEmpty(files);

        var hexRegex = new Regex(@"#[0-9A-Fa-f]{6,8}\b", RegexOptions.Compiled);
        var colorFromRgbRegex = new Regex(@"\bColor\.(FromRgb|FromArgb)", RegexOptions.Compiled);
        var brushesRegex = new Regex(@"\bBrushes\.(?!Transparent\b)[A-Za-z]+", RegexOptions.Compiled);
        var colorsRegex = new Regex(@"\bColors\.(?!Transparent\b)[A-Za-z]+", RegexOptions.Compiled);

        var violations = new List<string>();

        foreach (string file in files)
        {
            string[] lines = File.ReadAllLines(file);
            bool isIconCs = file.EndsWith(Path.Combine("Controls", "Icon.cs"), StringComparison.OrdinalIgnoreCase);

            for (int i = 0; i < lines.Length; i++)
            {
                string line = lines[i];
                string codeLine = line;

                if (file.EndsWith(".cs", StringComparison.OrdinalIgnoreCase))
                {
                    codeLine = Regex.Replace(line, @"//.*$", "");
                }

                if (hexRegex.IsMatch(codeLine))
                {
                    violations.Add($"{file}:{i + 1}: Hex color match in line: {line.Trim()}");
                }
                if (colorFromRgbRegex.IsMatch(codeLine))
                {
                    violations.Add($"{file}:{i + 1}: Color.FromRgb/FromArgb match in line: {line.Trim()}");
                }
                if (brushesRegex.IsMatch(codeLine))
                {
                    violations.Add($"{file}:{i + 1}: Brushes.<Name> (non-Transparent) match in line: {line.Trim()}");
                }
                if (colorsRegex.IsMatch(codeLine))
                {
                    // Controls/Icon.cs may use SystemColors — allowed
                    if (!isIconCs || !codeLine.Contains("SystemColors."))
                    {
                        violations.Add($"{file}:{i + 1}: Colors.<Name> (non-Transparent) match in line: {line.Trim()}");
                    }
                }
            }
        }

        if (violations.Count > 0)
        {
            string report = string.Join(Environment.NewLine, violations);
            Assert.Fail($"Found {violations.Count} hard-coded color violations in CircuitAnalyzer.WPF:{Environment.NewLine}{report}");
        }
    }
}
