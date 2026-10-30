using System;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// "Güç ve Güç Katsayısı" (POWER) çözüm yöntemi testleri:
/// DTO'lar, JSON eşleme, panel ayarları, hedef cos φ doğrulaması ve PowerTriangleView.
/// </summary>
[Collection(WpfUiCollection.Name)]
public class PowerMethodTests
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
    [InlineData("Güç ve Güç Katsayısı")]
    [InlineData("Güç")]
    [InlineData("GÜÇ")]
    public void AnalysisTypeFromText_Power_Matches(string text)
    {
        Assert.Equal(AnalysisTypes.Power, AnalysisPanel.AnalysisTypeFromText(text));
    }

    [Fact]
    public void UsesTerminals_Power_ReturnsFalse()
    {
        Assert.False(AnalysisPanel.UsesTerminals(AnalysisTypes.Power));
    }

    [Fact]
    public void Power_TerminalRow_NotVisible_AndNeedsNoTerminals()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAnalysisType(AnalysisTypes.Power);

            Assert.Equal(8, panel.CmbAnalysisType.SelectedIndex);
            Assert.Equal(Visibility.Collapsed, panel.RowTerminals.Visibility);
            Assert.Equal(Visibility.Visible, panel.RowPowerFactorTarget.Visibility);

            Assert.True(panel.TryGetOptions(out var opt, out var err), err);
            Assert.NotNull(opt);
            Assert.Equal(AnalysisTypes.Power, opt!.AnalysisType);
            Assert.Null(opt.TerminalPositive);
        });
    }

    [Fact]
    public void TryGetOptions_PowerFactorTarget_Validation()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAnalysisType(AnalysisTypes.Power);

            // 1. Boş
            panel.TxtPowerFactorTarget.Text = "";
            Assert.True(panel.TryGetOptions(out var opt, out var err), err);
            Assert.Null(opt!.PowerFactorTarget);

            // 2. 0,95 (Türkçe virgül)
            panel.TxtPowerFactorTarget.Text = "0,95";
            Assert.True(panel.TryGetOptions(out opt, out err), err);
            Assert.Equal(0.95, opt!.PowerFactorTarget);

            // 3. 0.95 (İngilizce nokta)
            panel.TxtPowerFactorTarget.Text = "0.95";
            Assert.True(panel.TryGetOptions(out opt, out err), err);
            Assert.Equal(0.95, opt!.PowerFactorTarget);

            // 4. 0 (geçersiz: 0 < x <= 1 kuralı)
            panel.TxtPowerFactorTarget.Text = "0";
            Assert.False(panel.TryGetOptions(out opt, out err));
            Assert.Equal("Hedef cos φ 0 ile 1 arasında olmalıdır.", err);

            // 5. 1,5 (geçersiz: > 1)
            panel.TxtPowerFactorTarget.Text = "1,5";
            Assert.False(panel.TryGetOptions(out opt, out err));
            Assert.Equal("Hedef cos φ 0 ile 1 arasında olmalıdır.", err);

            // 6. Harf (geçersiz)
            panel.TxtPowerFactorTarget.Text = "harf";
            Assert.False(panel.TryGetOptions(out opt, out err));
            Assert.Equal("Hedef cos φ 0 ile 1 arasında olmalıdır.", err);
        });
    }

    [Fact]
    public void AnalysisData_PowerFactorTarget_RoundTrip()
    {
        RunOnSta(() =>
        {
            var panel = new AnalysisPanel();
            panel.SetAnalysisType(AnalysisTypes.Power);
            panel.TxtPowerFactorTarget.Text = "0,95";

            var settings = panel.GetAnalysisSettings();
            Assert.Equal(AnalysisTypes.Power, settings.Type);
            Assert.Equal("0,95", settings.PowerFactorTarget);

            var panel2 = new AnalysisPanel();
            panel2.RestoreAnalysisSettings(settings);

            Assert.Equal(8, panel2.CmbAnalysisType.SelectedIndex);
            Assert.Equal("0,95", panel2.TxtPowerFactorTarget.Text);
            Assert.Equal(AnalysisTypes.Power, panel2.GetAnalysisSettings().Type);
            Assert.Equal("0,95", panel2.GetAnalysisSettings().PowerFactorTarget);
        });
    }

    [Fact]
    public void CircuitDocument_Json_RoundTrips_PowerFactorTarget()
    {
        var doc = new CircuitDocument
        {
            Analysis = new CircuitDocument.AnalysisData
            {
                Type = AnalysisTypes.Power,
                PowerFactorTarget = "0,95",
            }
        };

        string json = doc.ToJson();
        Assert.Contains("\"power_factor_target\": \"0,95\"", json);

        var loaded = CircuitDocument.FromJson(json);
        Assert.NotNull(loaded.Analysis);
        Assert.Equal(AnalysisTypes.Power, loaded.Analysis!.Type);
        Assert.Equal("0,95", loaded.Analysis.PowerFactorTarget);
    }

    [Fact]
    public void AnalysisRequestDto_PowerFactorTarget_JsonSerialization()
    {
        var req = new AnalysisRequestDto
        {
            AnalysisType = AnalysisTypes.Power,
            PowerFactorTarget = 0.95
        };

        string json = JsonSerializer.Serialize(req);
        Assert.Contains("\"power_factor_target\":0.95", json.Replace(" ", ""));

        var deserialized = JsonSerializer.Deserialize<AnalysisRequestDto>(json);
        Assert.NotNull(deserialized);
        Assert.Equal(0.95, deserialized!.PowerFactorTarget);
    }

    [Fact]
    public void LlmAskRequestDto_From_CopiesPowerFactorTarget()
    {
        var req = new AnalysisRequestDto
        {
            Netlist = "R1 1 0 10",
            AnalysisType = AnalysisTypes.Power,
            PowerFactorTarget = 0.92
        };

        var ask = LlmAskRequestDto.From(req, "Toplam güç ne kadar?");
        Assert.Equal(0.92, ask.PowerFactorTarget);

        var reqNull = new AnalysisRequestDto
        {
            AnalysisType = AnalysisTypes.Nodal,
            PowerFactorTarget = null
        };
        var askNull = LlmAskRequestDto.From(reqNull, "Soru?");
        Assert.Null(askNull.PowerFactorTarget);
    }

    [Fact]
    public void PowerSummary_JsonReading_CompensationNull()
    {
        const string json = """
        {
          "status": "success",
          "mode": "AC_PHASOR",
          "analysis_type": "POWER",
          "power_summary": {
            "p": 1200.0,
            "q": 800.0,
            "s": 1442.22,
            "pf": 0.832,
            "pf_type": "lagging",
            "phi_deg": 33.69,
            "compensation": null
          }
        }
        """;

        var response = JsonSerializer.Deserialize<AnalysisResponseDto>(json);
        Assert.NotNull(response);
        Assert.NotNull(response!.PowerSummary);
        Assert.Equal(1200.0, response.PowerSummary!.P);
        Assert.Equal(800.0, response.PowerSummary.Q);
        Assert.Equal(1442.22, response.PowerSummary.S);
        Assert.Equal(0.832, response.PowerSummary.Pf);
        Assert.Equal("lagging", response.PowerSummary.PfType);
        Assert.Equal(33.69, response.PowerSummary.PhiDeg);
        Assert.Null(response.PowerSummary.Compensation);
    }

    [Fact]
    public void PowerSummary_JsonReading_InsideResults_CompensationPopulated()
    {
        const string json = """
        {
          "status": "success",
          "mode": "AC_PHASOR",
          "analysis_type": "POWER",
          "results": {
            "power_summary": {
              "p": 2500.0,
              "q": 1800.0,
              "s": 3080.58,
              "pf": 0.812,
              "pf_type": "lagging",
              "phi_deg": 35.75,
              "compensation": {
                "target_pf": 0.95,
                "q_c": 978.5,
                "c": 0.000054,
                "i_before": 13.4,
                "i_after": 11.45,
                "applied": true,
                "reason": null
              }
            }
          }
        }
        """;

        var response = JsonSerializer.Deserialize<AnalysisResponseDto>(json);
        Assert.NotNull(response);
        var ps = response!.PowerSummary ?? response.Results.PowerSummary;
        Assert.NotNull(ps);
        Assert.Equal(2500.0, ps!.P);
        Assert.Equal(1800.0, ps.Q);
        Assert.NotNull(ps.Compensation);
        Assert.Equal(0.95, ps.Compensation!.TargetPf);
        Assert.Equal(978.5, ps.Compensation.Qc);
        Assert.Equal(0.000054, ps.Compensation.C);
        Assert.Equal(13.4, ps.Compensation.IBefore);
        Assert.Equal(11.45, ps.Compensation.IAfter);
        Assert.True(ps.Compensation.Applied);
        Assert.Null(ps.Compensation.Reason);
    }

    [Fact]
    public void PowerTriangleView_RendersWithoutCrashing()
    {
        RunOnSta(() =>
        {
            var view = new PowerTriangleView();

            // 1. lagging
            view.LoadData(new PowerSummaryDto
            {
                P = 1000, Q = 500, S = 1118.03, Pf = 0.894, PfType = "lagging", PhiDeg = 26.56
            });
            Assert.Contains("P = 1 kW", view.TxtSummary.Text);
            Assert.Contains("Q = 500 VAR", view.TxtSummary.Text);
            Assert.Contains("geri", view.TxtSummary.Text);

            // 2. leading
            view.LoadData(new PowerSummaryDto
            {
                P = 1200, Q = -400, S = 1264.91, Pf = 0.948, PfType = "leading", PhiDeg = -18.43
            });
            Assert.Contains("ileri", view.TxtSummary.Text);

            // 3. unity
            view.LoadData(new PowerSummaryDto
            {
                P = 800, Q = 0, S = 800, Pf = 1.0, PfType = "unity", PhiDeg = 0
            });
            Assert.Contains("birim", view.TxtSummary.Text);

            // 4. P = 0, S = 0
            view.LoadData(new PowerSummaryDto
            {
                P = 0, Q = 0, S = 0, Pf = 1.0, PfType = "unity", PhiDeg = 0
            });
            Assert.Contains("P = 0 W", view.TxtSummary.Text);

            // 5. applied = false (reason text shown)
            view.LoadData(new PowerSummaryDto
            {
                P = 1000, Q = 500, S = 1118.03, Pf = 0.894, PfType = "lagging", PhiDeg = 26.56,
                Compensation = new PowerCompensationDto
                {
                    TargetPf = 0.95,
                    Applied = false,
                    Reason = "Hedef güç katsayısı zaten sağlanıyor."
                }
            });
            Assert.Equal(Visibility.Visible, view.TxtCompensation.Visibility);
            Assert.Equal("Hedef güç katsayısı zaten sağlanıyor.", view.TxtCompensation.Text);

            // 6. applied = true (second dashed triangle + metrics)
            view.LoadData(new PowerSummaryDto
            {
                P = 1000, Q = 500, S = 1118.03, Pf = 0.894, PfType = "lagging", PhiDeg = 26.56,
                Compensation = new PowerCompensationDto
                {
                    TargetPf = 0.95,
                    Applied = true,
                    Qc = 200,
                    C = 15e-6,
                    IBefore = 5.0,
                    IAfter = 4.2
                }
            });
            Assert.Equal(Visibility.Visible, view.TxtCompensation.Visibility);
            Assert.Contains("Q_C =", view.TxtCompensation.Text);
            Assert.Contains("15 µF", view.TxtCompensation.Text);
        });
    }
}
