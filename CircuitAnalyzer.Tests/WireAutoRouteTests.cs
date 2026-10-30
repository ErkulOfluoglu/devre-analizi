using System.Windows;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>Tel kolunun uç yönlerine göre "dıştan" dönmesi.</summary>
public class WireAutoRouteTests
{
    private static readonly Vector Up = new(0, -1);
    private static readonly Vector Down = new(0, 1);
    private static readonly Vector Left = new(-1, 0);
    private static readonly Vector Right = new(1, 0);

    [Fact]
    public void SourceTopPin_ToResistorLeftPin_GoesUpFirst()
    {
        // Kaynağın üst ucu yukarı, direncin sol ucu sola bakar: önce yukarı, sonra sağa
        Assert.True(WireGeometry.PreferVerticalFirst(
            new Point(80, 160), Up, new Point(140, 70), Left, fallback: false));
    }

    [Fact]
    public void ResistorLeftPin_ToSourceTopPin_GoesLeftFirst()
    {
        // Aynı tel ters yönde çizilse de aynı köşeyi kullanır (140,70 → 80,70 → 80,160)
        Assert.False(WireGeometry.PreferVerticalFirst(
            new Point(140, 70), Left, new Point(80, 160), Up, fallback: true));
    }

    [Fact]
    public void FreeEnd_FollowsStartPinDirection()
    {
        Assert.True(WireGeometry.PreferVerticalFirst(new Point(0, 0), Up, new Point(100, -100), null, fallback: false));
        Assert.False(WireGeometry.PreferVerticalFirst(new Point(0, 0), Right, new Point(100, 100), null, fallback: true));
    }

    [Fact]
    public void TargetBehindPin_DoesNotRunThroughElement()
    {
        // Sağa bakan uçtan sola gidilecekse önce yatay gitmek elemanın içinden geçerdi
        Assert.True(WireGeometry.PreferVerticalFirst(new Point(100, 0), Right, new Point(0, 100), null, fallback: false));
    }

    [Fact]
    public void BottomPin_ToGroundTopPin_ArrivesFromAbove()
    {
        Assert.False(WireGeometry.PreferVerticalFirst(new Point(0, 0), Right, new Point(100, 100), Up, fallback: true));
        Assert.True(WireGeometry.PreferVerticalFirst(new Point(0, 0), Down, new Point(100, 100), Left, fallback: false));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void NoInformationOrStraightLeg_KeepsFallback(bool fallback)
    {
        Assert.Equal(fallback, WireGeometry.PreferVerticalFirst(new Point(0, 0), null, new Point(100, 100), null, fallback));
        Assert.Equal(fallback, WireGeometry.PreferVerticalFirst(new Point(0, 0), Up, new Point(100, 0), Left, fallback));
    }
}
