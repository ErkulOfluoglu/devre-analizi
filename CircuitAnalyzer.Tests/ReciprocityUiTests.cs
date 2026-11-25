using System;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// "Karşıtlık" (RECIPROCITY) analiz yöntemi arayüz ve istek testleri:
/// yöntem eşlemesi, JSON serileştirme, varsayılan pasif eleman hedefi, satır görünürlüğü ve ayar kaydet/yükle.
/// </summary>
[Collection(WpfUiCollection.Name)]
public class ReciprocityUiTests
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

    [Fact]
    public void AnalysisTypeFromText_Reciprocity_MatchesExactLiteralAcrossCultures()
    {
        var original = CultureInfo.CurrentCulture;
        try
        {
            foreach (var cultureName in new[] { "tr-TR", "en-US", "" })
            {
                CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo(cultureName);
                Assert.Equal(AnalysisTypes.Reciprocity, AnalysisPanel.AnalysisTypeFromText("Karşıtlık"));
            }
        }
        finally
        {
            CultureInfo.CurrentCulture = original;
        }

        Assert.Equal("RECIPROCITY", AnalysisTypes.Reciprocity);
        Assert.False(AnalysisPanel.UsesTerminals(AnalysisTypes.Reciprocity));
    }

    [Fact]
    public void AnalysisRequestDto_ReciprocityTarget_SerializedWhenSet_OmittedWhenNull()
    {
        var withTarget = new AnalysisRequestDto
        {
            Netlist = "V1 1 0 10\nR1 1 2 100\nR4 2 0 200",
            AnalysisType = AnalysisTypes.Reciprocity,
            ReciprocityTarget = "R4",
        };
        string jsonWith = JsonSerializer.Serialize(withTarget);
        Assert.Contains("\"reciprocity_target\":\"R4\"", jsonWith.Replace(" ", ""));
        Assert.Contains("\"analysis_type\":\"RECIPROCITY\"", jsonWith.Replace(" ", ""));

        var deserialized = JsonSerializer.Deserialize<AnalysisRequestDto>(jsonWith);
        Assert.NotNull(deserialized);
        Assert.Equal("R4", deserialized!.ReciprocityTarget);

        var withoutTarget = new AnalysisRequestDto
        {
            Netlist = "V1 1 0 10\nR1 1 0 100",
            AnalysisType = AnalysisTypes.Nodal,
            ReciprocityTarget = null,
        };
        string jsonWithout = JsonSerializer.Serialize(withoutTarget);
        Assert.DoesNotContain("reciprocity_target", jsonWithout);
    }

    [Fact]
    public void LlmAskRequestDto_From_CopiesReciprocityTarget_AndOmitsWhenNull()
    {
        var req = new AnalysisRequestDto
        {
            Netlist = "V1 1 0 10\nR1 1 2 100\nR2 2 0 200",
            AnalysisType = AnalysisTypes.Reciprocity,
            ReciprocityTarget = "R2",
        };
        var ask = LlmAskRequestDto.From(req, "Neden eşit çıktı?");
        Assert.Equal("R2", ask.ReciprocityTarget);
        Assert.Contains("\"reciprocity_target\":\"R2\"", JsonSerializer.Serialize(ask).Replace(" ", ""));

        var reqNull = new AnalysisRequestDto { AnalysisType = AnalysisTypes.Nodal, ReciprocityTarget = null };
        var askNull = LlmAskRequestDto.From(reqNull, "Soru?");
        Assert.Null(askNull.ReciprocityTarget);
        Assert.DoesNotContain("reciprocity_target", JsonSerializer.Serialize(askNull));
    }

    [Fact]
    public void DefaultReciprocityTarget_PicksLastPassiveRlc_ExcludesSourcesGroundAndMeasurement()
    {
        var elements = new CircuitElement[]
        {
            new VoltageSource { Id = "V1", Value = 12 },
            new Resistor { Id = "R1", Value = 100 },
            new CurrentSource { Id = "I1", Value = 0.01 },
            new Inductor { Id = "L1", Value = 0.1 },
            new AcVoltageSource { Id = "VAC1", Amplitude = 10, Frequency = 50 },
            new Capacitor { Id = "C2", Value = 1e-6 },
            new ImpedanceElement { Id = "Z1" },
            new GroundElement { Id = "GND1" },
            new TestProbe { Id = "VP1" },
            new JunctionElement { Id = "J1" },
            new Wattmeter { Id = "W1" },
        };

        var ids = AnalysisPanel.ReciprocityTargetIds(elements);
        Assert.Equal(new[] { "R1", "L1", "C2" }, ids);
        Assert.Equal("C2", AnalysisPanel.DefaultReciprocityTarget(elements));
    }

    [Fact]
    public void DefaultReciprocityTarget_ReturnsNull_WhenNoPassiveRlcExists()
    {
        var elements = new CircuitElement[]
        {
            new VoltageSource { Id = "V1", Value = 10 },
            new GroundElement { Id = "GND1" },
            new TestProbe { Id = "VP1" },
        };

        Assert.Empty(AnalysisPanel.ReciprocityTargetIds(elements));
        Assert.Null(AnalysisPanel.DefaultReciprocityTarget(elements));
        Assert.Null(AnalysisPanel.ResolveReciprocityTarget(Array.Empty<string>(), "R1"));
    }

    [Fact]
    public void ResolveReciprocityTarget_KeepsValidPreviousOrFallsBackToLast()
    {
        var candidates = new[] { "R1", "L1", "R4" };
        Assert.Equal("L1", AnalysisPanel.ResolveReciprocityTarget(candidates, "L1"));
        Assert.Equal("R4", AnalysisPanel.ResolveReciprocityTarget(candidates, "R99"));
        Assert.Equal("R4", AnalysisPanel.ResolveReciprocityTarget(candidates, null));
    }

    [Fact]
    public void ReciprocityRow_VisibleOnlyWhenReciprocitySelected_AndTryGetOptionsPopulatesTarget()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAvailableReciprocityTargets(new CircuitElement[]
            {
                new VoltageSource { Id = "V1", Value = 12 },
                new Resistor { Id = "R1", Value = 100 },
                new Resistor { Id = "R4", Value = 200 },
                new GroundElement { Id = "GND1" },
            });

            // Varsayılan yöntem (Düğüm Gerilimleri): satır gizli, hedef istekte null
            Assert.Equal(Visibility.Collapsed, panel.RowReciprocityTarget.Visibility);
            Assert.True(panel.TryGetOptions(out var nodalOpt, out var err), err);
            Assert.Null(nodalOpt!.ReciprocityTarget);

            // Karşıtlık seçilince görünür ve son R/L/C ("R4") seçili
            panel.SetAnalysisType(AnalysisTypes.Reciprocity);
            Assert.Equal(6, panel.CmbAnalysisType.SelectedIndex);
            Assert.Equal(Visibility.Visible, panel.RowReciprocityTarget.Visibility);
            Assert.Equal(Visibility.Collapsed, panel.RowTerminals.Visibility);
            Assert.Equal("R4", panel.CmbReciprocityTarget.SelectedItem);

            Assert.True(panel.TryGetOptions(out var recOpt, out err), err);
            Assert.Equal(AnalysisTypes.Reciprocity, recOpt!.AnalysisType);
            Assert.Equal("R4", recOpt.ReciprocityTarget);

            // Önceki seçim ("R1") devre güncellenince hâlâ varsa korunur
            panel.CmbReciprocityTarget.SelectedItem = "R1";
            panel.SetAvailableReciprocityTargets(new CircuitElement[]
            {
                new Resistor { Id = "R1", Value = 100 },
                new Resistor { Id = "R4", Value = 200 },
                new Capacitor { Id = "C1", Value = 1e-6 },
            });
            Assert.Equal("R1", panel.CmbReciprocityTarget.SelectedItem);

            // Seçili eleman ("R1") silinince son R/L/C ("C1") seçilir
            panel.SetAvailableReciprocityTargets(new CircuitElement[]
            {
                new Resistor { Id = "R4", Value = 200 },
                new Capacitor { Id = "C1", Value = 1e-6 },
            });
            Assert.Equal("C1", panel.CmbReciprocityTarget.SelectedItem);

            // Başka yönteme geçince satır tekrar gizlenir
            panel.SetAnalysisType(AnalysisTypes.Millman);
            Assert.Equal(Visibility.Collapsed, panel.RowReciprocityTarget.Visibility);
        });
    }

    [Fact]
    public void AnalysisSettings_ReciprocityTarget_RoundTrip_AndFallbackOnMissingOrOldFile()
    {
        RunOnSta(() =>
        {
            var elements = new CircuitElement[]
            {
                new VoltageSource { Id = "V1", Value = 10 },
                new Resistor { Id = "R1", Value = 100 },
                new Resistor { Id = "R2", Value = 200 },
                new Resistor { Id = "R4", Value = 400 },
            };

            var panel1 = new AnalysisPanel();
            panel1.SetAvailableReciprocityTargets(elements);
            panel1.SetAnalysisType(AnalysisTypes.Reciprocity);
            panel1.CmbReciprocityTarget.SelectedItem = "R2";

            var settings = panel1.GetAnalysisSettings();
            Assert.Equal(AnalysisTypes.Reciprocity, settings.Type);
            Assert.Equal("R2", settings.ReciprocityTarget);

            // CircuitDocument JSON round-trip
            var doc = new CircuitDocument { Analysis = settings };
            string json = doc.ToJson();
            Assert.Contains("\"reciprocity_target\": \"R2\"", json);
            var loaded = CircuitDocument.FromJson(json);
            Assert.Equal("R2", loaded.Analysis!.ReciprocityTarget);

            // Geri yükleme: eleman varsa seçimi korur
            var panel2 = new AnalysisPanel();
            panel2.SetAvailableReciprocityTargets(elements);
            panel2.RestoreAnalysisSettings(loaded.Analysis);
            Assert.Equal(AnalysisTypes.Reciprocity, panel2.GetAnalysisSettings().Type);
            Assert.Equal("R2", panel2.CmbReciprocityTarget.SelectedItem);
            Assert.Equal("R2", panel2.GetAnalysisSettings().ReciprocityTarget);

            // Kayıtlı eleman artık devrede yoksa varsayılana (son R/L/C = "R4") düşer
            var panel3 = new AnalysisPanel();
            panel3.SetAvailableReciprocityTargets(elements);
            panel3.RestoreAnalysisSettings(new CircuitDocument.AnalysisData
            {
                Type = AnalysisTypes.Reciprocity,
                ReciprocityTarget = "R99",
            });
            Assert.Equal("R4", panel3.CmbReciprocityTarget.SelectedItem);

            // Eski .devre dosyası (reciprocity_target alanı yok) sorunsuz açılır ve varsayılana düşer
            const string legacyJson = """
            {
              "format": "devre-analizi",
              "version": 1,
              "elements": [],
              "wires": [],
              "analysis": {
                "type": "RECIPROCITY",
                "value_display": "RMS"
              }
            }
            """;
            var legacyDoc = CircuitDocument.FromJson(legacyJson);
            Assert.Null(legacyDoc.Analysis!.ReciprocityTarget);

            var panel4 = new AnalysisPanel();
            panel4.SetAvailableReciprocityTargets(elements);
            panel4.CmbReciprocityTarget.SelectedItem = "R1";
            panel4.RestoreAnalysisSettings(legacyDoc.Analysis);
            Assert.Equal("R4", panel4.CmbReciprocityTarget.SelectedItem);
        });
    }
}
