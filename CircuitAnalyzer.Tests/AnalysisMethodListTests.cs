using System;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Yöntem listesindeki yeni "Millman" ve "Kaynak Dönüşümü" seçenekleri: API türüne eşleme,
/// terminal satırının görünürlüğü, kayıtlı ayarların geri yüklenmesi. Mevcut sıra değişmez.
/// </summary>
[Collection(WpfUiCollection.Name)]
public class AnalysisMethodListTests
{
    private static void RunOnSta(Action action)
    {
        Exception? ex = null;
        var thread = new Thread(() =>
        {
            try { action(); }
            catch (Exception e) { ex = e; }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        if (ex != null) ExceptionDispatchInfo.Capture(ex).Throw();
    }

    [Theory]
    [InlineData(0, "Düğüm Gerilimleri", AnalysisTypes.Nodal, false)]
    [InlineData(1, "Thevenin Eşdeğeri", AnalysisTypes.Thevenin, true)]
    [InlineData(2, "Norton Eşdeğeri", AnalysisTypes.Norton, true)]
    [InlineData(3, "Çevre Akımları", AnalysisTypes.Mesh, false)]
    [InlineData(4, "Süperpozisyon", AnalysisTypes.Superposition, false)]
    [InlineData(5, "Millman", AnalysisTypes.Millman, false)]
    [InlineData(6, "Kaynak Dönüşümü", AnalysisTypes.SourceTransform, true)]
    [InlineData(7, "Geçici Durum (Anahtar)", AnalysisTypes.Transient, false)]
    [InlineData(8, "Güç ve Güç Katsayısı", AnalysisTypes.Power, false)]
    public void ComboItem_MapsToApiTypeAndTerminalsRow(int index, string label, string apiType, bool showsTerminals)
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            Assert.Equal(9, panel.CmbAnalysisType.Items.Count);
            Assert.Equal(label, (panel.CmbAnalysisType.Items[index] as ComboBoxItem)?.Content as string);

            panel.CmbAnalysisType.SelectedIndex = index;

            Assert.Equal(apiType, panel.GetAnalysisSettings().Type);
            Assert.Equal(showsTerminals ? Visibility.Visible : Visibility.Collapsed,
                panel.RowTerminals.Visibility);
        });
    }

    [Fact]
    public void NewMethods_ApiTypeNames_MatchPython()
    {
        Assert.Equal("MILLMAN", AnalysisTypes.Millman);
        Assert.Equal("SOURCE_TRANSFORM", AnalysisTypes.SourceTransform);
        Assert.Equal("TRANSIENT", AnalysisTypes.Transient);
        Assert.Equal("POWER", AnalysisTypes.Power);
    }

    [Fact]
    public void Transient_TryGetOptions_NeedsNoTerminals()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAnalysisType(AnalysisTypes.Transient);
            Assert.Equal(7, panel.CmbAnalysisType.SelectedIndex);

            Assert.True(panel.TryGetOptions(out var opt, out var err), err);
            Assert.Equal(AnalysisTypes.Transient, opt!.AnalysisType);
        });
    }

    [Fact]
    public void SourceTransform_TryGetOptions_NeedsTerminals_AndPassesType()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAnalysisType(AnalysisTypes.SourceTransform);
            Assert.Equal(6, panel.CmbAnalysisType.SelectedIndex);

            // Terminal seçilmeden Thevenin gibi hata verir
            Assert.False(panel.TryGetOptions(out var none, out var err));
            Assert.Null(none);
            Assert.Contains("+ terminal", err!);

            panel.SetAvailableNodes(new[] { 0, 1, 2 });
            panel.CmbTerminalPositive.SelectedItem = "2";
            panel.CmbTerminalNegative.SelectedItem = "0";
            Assert.True(panel.TryGetOptions(out var opt, out err), err);
            Assert.Equal(AnalysisTypes.SourceTransform, opt!.AnalysisType);
            Assert.Equal("2", opt.TerminalPositive);
            Assert.Equal("0", opt.TerminalNegative);
        });
    }

    [Fact]
    public void Millman_TryGetOptions_NeedsNoTerminals()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAnalysisType(AnalysisTypes.Millman);
            Assert.Equal(5, panel.CmbAnalysisType.SelectedIndex);

            Assert.True(panel.TryGetOptions(out var opt, out var err), err);
            Assert.Equal(AnalysisTypes.Millman, opt!.AnalysisType);
        });
    }

    [Fact]
    public void RestoreAnalysisSettings_NewMethods_RoundTrip()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            foreach (var type in new[] { AnalysisTypes.Millman, AnalysisTypes.SourceTransform })
            {
                panel.RestoreAnalysisSettings(new CircuitDocument.AnalysisData { Type = type });
                Assert.Equal(type, panel.GetAnalysisSettings().Type);
            }
        });
    }
}
