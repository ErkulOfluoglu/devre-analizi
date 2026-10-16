using System;
using System.IO;
using CircuitAnalyzer.WPF;
using Xunit;

namespace CircuitAnalyzer.Tests
{
    public class DemoShotsTests
    {
        [Fact]
        public void TryGetDemoShots_ValidArgument_ReturnsFullPath()
        {
            string relativeDir = Path.Combine("build", "video", "shots");
            string[] args = { "CircuitAnalyzer.exe", "--demo-shots", relativeDir, "--theme", "light" };

            bool ok = MainWindow.TryGetDemoShots(args, out string? outputDir);

            Assert.True(ok);
            Assert.NotNull(outputDir);
            Assert.Equal(Path.GetFullPath(relativeDir), outputDir);
        }

        [Fact]
        public void TryGetDemoShots_CaseInsensitiveFlag_ReturnsFullPath()
        {
            string target = Path.Combine(Path.GetTempPath(), "demo_shots_out");
            string[] args = { "CircuitAnalyzer.exe", "--DEMO-SHOTS", target };

            bool ok = MainWindow.TryGetDemoShots(args, out string? outputDir);

            Assert.True(ok);
            Assert.Equal(Path.GetFullPath(target), outputDir);
        }

        [Fact]
        public void TryGetDemoShots_MissingArgumentOrFlag_ReturnsFalse()
        {
            // Bayrak hiç yok
            Assert.False(MainWindow.TryGetDemoShots(new[] { "CircuitAnalyzer.exe", "--theme", "light" }, out var dir1));
            Assert.Null(dir1);

            // Bayrak var ama dizin argümanı eksik
            Assert.False(MainWindow.TryGetDemoShots(new[] { "CircuitAnalyzer.exe", "--demo-shots" }, out var dir2));
            Assert.Null(dir2);

            // Bayraktan hemen sonra başka bir bayrak geliyor
            Assert.False(MainWindow.TryGetDemoShots(new[] { "CircuitAnalyzer.exe", "--demo-shots", "--theme", "light" }, out var dir3));
            Assert.Null(dir3);

            // Boş argüman
            Assert.False(MainWindow.TryGetDemoShots(new[] { "CircuitAnalyzer.exe", "--demo-shots", "   " }, out var dir4));
            Assert.Null(dir4);
        }

        [Fact]
        public void HasAnySelfTest_IncludesDemoShots()
        {
            Assert.True(MainWindow.HasAnySelfTest(new[] { "CircuitAnalyzer.exe", "--demo-shots", "out" }));
            Assert.True(MainWindow.HasAnySelfTest(new[] { "--DEMO-SHOTS" }));
            Assert.False(MainWindow.HasAnySelfTest(new[] { "CircuitAnalyzer.exe", "--theme", "light" }));
        }
    }
}
