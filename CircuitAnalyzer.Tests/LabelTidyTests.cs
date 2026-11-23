using System.Linq;
using System.Windows;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Video çekiminde görülen pürüzler: aynı satırda karışık önek (W + kW), düğüm rozetinin
/// akım etiketini örtmesi (Millman).
/// </summary>
public class LabelTidyTests
{
    [Fact]
    public void FormatGroup_UsesPrefixOfLargestValue()
    {
        var s = EngFormat.FormatGroup(new[] { 1979.0, 194.6, 1988.0 }, new[] { "W", "VAR", "VA" });
        Assert.Equal(new[] { "1,979 kW", "0,1946 kVAR", "1,988 kVA" }, s);
    }

    [Fact]
    public void FormatGroup_NegativeAndSmallValues()
    {
        var s = EngFormat.FormatGroup(new[] { 898.6, -1080.0 }, new[] { "W", "VAR" });
        Assert.Equal(new[] { "0,8986 kW", "−1,08 kVAR" }, s);
    }

    [Fact]
    public void FormatGroup_ZeroValuesStayPlain()
    {
        Assert.Equal(new[] { "0 W", "5 mW" }, EngFormat.FormatGroup(new[] { 0.0, 0.005 }, new[] { "W", "W" }));
        Assert.Equal(new[] { "0 W", "0 VAR" }, EngFormat.FormatGroup(new[] { 0.0, 0.0 }, new[] { "W", "VAR" }));
    }

    [Fact]
    public void BadgeCandidates_FirstIsOldDefault_ThenLeftAndBelow()
    {
        var pin = new Point(100, 200);
        var c = ResultOverlay.BadgeCandidates(pin, new Size(60, 18));
        Assert.Equal(new Rect(104, 180, 60, 18), c[0]);   // sağ üst (eski yer)
        Assert.Equal(new Rect(36, 180, 60, 18), c[1]);    // sol üst
        Assert.Equal(new Rect(104, 204, 60, 18), c[2]);   // sağ alt
        Assert.Equal(new Rect(36, 204, 60, 18), c[3]);    // sol alt
    }

    [Fact]
    public void BadgeCandidates_LeftSpotDoesNotHitCurrentLabelRightOfPin()
    {
        // Millman: akım etiketi ucun sağında, rozetin eski yerine biniyor
        var pin = new Point(100, 200);
        var currentLabel = new Rect(112, 185, 120, 20);
        var c = ResultOverlay.BadgeCandidates(pin, new Size(60, 18));
        Assert.True(ResultOverlay.Collides(currentLabel, c[0]));
        Assert.False(ResultOverlay.Collides(currentLabel, c[1]));
        Assert.Equal(c[1], c.First(r => !ResultOverlay.Collides(currentLabel, r)));
    }

    [Fact]
    public void Collides_TouchingWithMarginCountsButFarApartDoesNot()
    {
        Assert.True(ResultOverlay.Collides(new Rect(0, 0, 10, 10), new Rect(10.5, 0, 10, 10)));
        Assert.False(ResultOverlay.Collides(new Rect(0, 0, 10, 10), new Rect(20, 0, 10, 10)));
    }
}
