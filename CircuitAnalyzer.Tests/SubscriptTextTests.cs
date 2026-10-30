using System;
using System.Linq;
using System.Threading;
using System.Runtime.ExceptionServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

[Collection(WpfUiCollection.Name)]
public class SubscriptTextTests
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

    [Theory]
    [InlineData("V_C", "VC")]
    [InlineData("X_L", "XL")]
    [InlineData("I_R1", "IR1")]
    [InlineData("V_C1(0⁻)", "VC1(0⁻)")]
    [InlineData("i_R1(t)", "iR1(t)")]
    [InlineData("V_AB", "VAB")]
    [InlineData("V_düğüm", "Vdüğüm")]
    [InlineData("φ_1", "φ1")]
    [InlineData("P_R1 = 5 W", "PR1 = 5 W")]
    public void Plain_RemovesUnderscore_ForMatchingPatterns(string input, string expected)
    {
        Assert.Equal(expected, SubscriptText.Plain(input));
    }

    [Theory]
    [InlineData("AC_PHASOR")]
    [InlineData("value_kind")]
    [InlineData("düz metin")]
    [InlineData("_")]
    [InlineData("a_")]
    [InlineData("")]
    [InlineData("R1_2")]
    public void Plain_LeavesUntouched_ForNonMatchingPatterns(string input)
    {
        Assert.Equal(input, SubscriptText.Plain(input));
    }

    [Fact]
    public void ToInlines_EmptyOrNull_ReturnsEmpty()
    {
        Assert.Empty(SubscriptText.ToInlines("", 14));
        Assert.Empty(SubscriptText.ToInlines(null!, 14));
    }

    [Theory]
    [InlineData("AC_PHASOR")]
    [InlineData("value_kind")]
    [InlineData("düz metin")]
    [InlineData("_")]
    [InlineData("a_")]
    [InlineData("R1_2")]
    public void ToInlines_NonMatchingPatterns_ReturnsSinglePlainRun(string input)
    {
        var inlines = SubscriptText.ToInlines(input, 14);
        Assert.Single(inlines);
        var run = Assert.IsType<Run>(inlines[0]);
        Assert.Equal(input, run.Text);
        Assert.Equal(BaselineAlignment.Baseline, run.BaselineAlignment);
    }

    [Fact]
    public void ToInlines_SimpleTransform_VC()
    {
        var inlines = SubscriptText.ToInlines("V_C", 16);
        Assert.Equal(2, inlines.Count);

        var r0 = Assert.IsType<Run>(inlines[0]);
        Assert.Equal("V", r0.Text);
        Assert.Equal(BaselineAlignment.Baseline, r0.BaselineAlignment);

        var r1 = Assert.IsType<Run>(inlines[1]);
        Assert.Equal("C", r1.Text);
        Assert.Equal(BaselineAlignment.Subscript, r1.BaselineAlignment);
        Assert.Equal(12.0, r1.FontSize);
    }

    [Fact]
    public void ToInlines_WithSuffix_P_R1()
    {
        var inlines = SubscriptText.ToInlines("P_R1 = 5 W", 16);
        Assert.Equal(3, inlines.Count);

        var r0 = Assert.IsType<Run>(inlines[0]);
        Assert.Equal("P", r0.Text);
        Assert.Equal(BaselineAlignment.Baseline, r0.BaselineAlignment);

        var r1 = Assert.IsType<Run>(inlines[1]);
        Assert.Equal("R1", r1.Text);
        Assert.Equal(BaselineAlignment.Subscript, r1.BaselineAlignment);
        Assert.Equal(12.0, r1.FontSize);

        var r2 = Assert.IsType<Run>(inlines[2]);
        Assert.Equal(" = 5 W", r2.Text);
        Assert.Equal(BaselineAlignment.Baseline, r2.BaselineAlignment);
    }

    [Fact]
    public void ToInlines_WithTransientParentheses_V_C1()
    {
        var inlines = SubscriptText.ToInlines("V_C1(0⁻)", 16);
        Assert.Equal(3, inlines.Count);

        var r0 = Assert.IsType<Run>(inlines[0]);
        Assert.Equal("V", r0.Text);
        Assert.Equal(BaselineAlignment.Baseline, r0.BaselineAlignment);

        var r1 = Assert.IsType<Run>(inlines[1]);
        Assert.Equal("C1", r1.Text);
        Assert.Equal(BaselineAlignment.Subscript, r1.BaselineAlignment);
        Assert.Equal(12.0, r1.FontSize);

        var r2 = Assert.IsType<Run>(inlines[2]);
        Assert.Equal("(0⁻)", r2.Text);
        Assert.Equal(BaselineAlignment.Baseline, r2.BaselineAlignment);
    }

    [Fact]
    public void ToInlines_WithTimeFunction_i_R1()
    {
        var inlines = SubscriptText.ToInlines("i_R1(t)", 16);
        Assert.Equal(3, inlines.Count);

        var r0 = Assert.IsType<Run>(inlines[0]);
        Assert.Equal("i", r0.Text);
        Assert.Equal(BaselineAlignment.Baseline, r0.BaselineAlignment);

        var r1 = Assert.IsType<Run>(inlines[1]);
        Assert.Equal("R1", r1.Text);
        Assert.Equal(BaselineAlignment.Subscript, r1.BaselineAlignment);
        Assert.Equal(12.0, r1.FontSize);

        var r2 = Assert.IsType<Run>(inlines[2]);
        Assert.Equal("(t)", r2.Text);
        Assert.Equal(BaselineAlignment.Baseline, r2.BaselineAlignment);
    }

    [Fact]
    public void ToInlines_TwoLettersSubscript_V_AB()
    {
        var inlines = SubscriptText.ToInlines("V_AB", 16);
        Assert.Equal(2, inlines.Count);

        var r0 = Assert.IsType<Run>(inlines[0]);
        Assert.Equal("V", r0.Text);

        var r1 = Assert.IsType<Run>(inlines[1]);
        Assert.Equal("AB", r1.Text);
        Assert.Equal(BaselineAlignment.Subscript, r1.BaselineAlignment);
        Assert.Equal(12.0, r1.FontSize);
    }

    [Fact]
    public void ToInlines_TurkishWordSubscript_V_dugum()
    {
        var inlines = SubscriptText.ToInlines("V_düğüm", 16);
        Assert.Equal(2, inlines.Count);

        var r0 = Assert.IsType<Run>(inlines[0]);
        Assert.Equal("V", r0.Text);

        var r1 = Assert.IsType<Run>(inlines[1]);
        Assert.Equal("düğüm", r1.Text);
        Assert.Equal(BaselineAlignment.Subscript, r1.BaselineAlignment);
        Assert.Equal(12.0, r1.FontSize);
    }

    [Fact]
    public void ToInlines_GreekLetter_Phi_1()
    {
        var inlines = SubscriptText.ToInlines("φ_1", 16);
        Assert.Equal(2, inlines.Count);

        var r0 = Assert.IsType<Run>(inlines[0]);
        Assert.Equal("φ", r0.Text);

        var r1 = Assert.IsType<Run>(inlines[1]);
        Assert.Equal("1", r1.Text);
        Assert.Equal(BaselineAlignment.Subscript, r1.BaselineAlignment);
        Assert.Equal(12.0, r1.FontSize);
    }

    [Fact]
    public void Apply_TransformsTextBlockOnSta()
    {
        RunOnSta(() =>
        {
            var tb = new TextBlock
            {
                FontSize = 20,
                Text = "V_C1 = 5 V"
            };

            SubscriptText.Apply(tb);

            Assert.Equal(3, tb.Inlines.Count);

            var r0 = Assert.IsType<Run>(tb.Inlines.ElementAt(0));
            Assert.Equal("V", r0.Text);
            Assert.Equal(BaselineAlignment.Baseline, r0.BaselineAlignment);

            var r1 = Assert.IsType<Run>(tb.Inlines.ElementAt(1));
            Assert.Equal("C1", r1.Text);
            Assert.Equal(BaselineAlignment.Subscript, r1.BaselineAlignment);
            Assert.Equal(15.0, r1.FontSize);

            var r2 = Assert.IsType<Run>(tb.Inlines.ElementAt(2));
            Assert.Equal(" = 5 V", r2.Text);
            Assert.Equal(BaselineAlignment.Baseline, r2.BaselineAlignment);
        });
    }

    [Fact]
    public void Apply_DoesNothing_WhenNoPatternMatches()
    {
        RunOnSta(() =>
        {
            var tb = new TextBlock
            {
                FontSize = 14,
                Text = "AC_PHASOR ve value_kind"
            };

            SubscriptText.Apply(tb);

            Assert.Single(tb.Inlines);
            Assert.Equal("AC_PHASOR ve value_kind", tb.Text);
        });
    }

    [Fact]
    public void Apply_NullOrEmpty_DoesNotThrow()
    {
        RunOnSta(() =>
        {
            SubscriptText.Apply(null!);

            var tbEmpty = new TextBlock { Text = "" };
            SubscriptText.Apply(tbEmpty);
            Assert.Empty(tbEmpty.Inlines);
        });
    }

    [Theory]
    [InlineData("E₁", "E", "1")]
    [InlineData("φ₂", "φ", "2")]
    [InlineData("Δ₁₂", "Δ", "12")]
    [InlineData("V_C₁", "V", "C1")]
    public void UnicodeSubscriptDigits_BecomeRealSubscripts(string input, string baseText, string sub)
    {
        RunOnSta(() =>
        {
            var inlines = SubscriptText.ToInlines(input, 16);
            Assert.Equal(2, inlines.Count);
            Assert.Equal(baseText, ((Run)inlines[0]).Text);
            var subRun = (Run)inlines[1];
            Assert.Equal(sub, subRun.Text);
            Assert.Equal(BaselineAlignment.Subscript, subRun.BaselineAlignment);
            Assert.Equal(12, subRun.FontSize, 3);
        });
    }

    [Fact]
    public void MultilineAlignedBlock_KeepsSubscriptWidth()
    {
        RunOnSta(() =>
        {
            var inlines = SubscriptText.ToInlines("Δ₁ = | 1 2 |\n     | 3 4 |", 14);
            var subRun = (Run)inlines[1];
            Assert.Equal("1", subRun.Text);
            Assert.Equal(14, subRun.FontSize, 3);
        });
    }

    [Fact]
    public void Plain_UsesOrdinaryDigits()
    {
        Assert.Equal("V1 ve VC1", SubscriptText.Plain("V₁ ve V_C1"));
    }
}
