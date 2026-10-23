using System.Windows;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// SelectionModel birim testleri (tekli seçim, Ctrl+tık, tümünü seç, çerçeve kesişimi ve olay bildirimi).
/// </summary>
public class SelectionModelTests
{
    [Fact]
    public void Select_SingleElement_ReplacesSelectionAndSetsPrimary()
    {
        var model = new SelectionModel();
        var r1 = new Resistor { Id = "R1", Position = new Point(100, 100) };
        var r2 = new Resistor { Id = "R2", Position = new Point(200, 100) };

        int changedCount = 0;
        model.Changed += (_, _) => changedCount++;

        model.Select(r1);
        Assert.Equal(1, model.Count);
        Assert.True(model.IsSelected(r1));
        Assert.Same(r1, model.PrimaryElement);
        Assert.Equal(1, changedCount);

        // Başka eleman seçildiğinde önceki seçim kalkmalı
        model.Select(r2);
        Assert.Equal(1, model.Count);
        Assert.False(model.IsSelected(r1));
        Assert.True(model.IsSelected(r2));
        Assert.Same(r2, model.PrimaryElement);
        Assert.Equal(2, changedCount);
    }

    [Fact]
    public void Toggle_AddsAndRemovesElementsAndWires()
    {
        var model = new SelectionModel();
        var r1 = new Resistor { Id = "R1", Position = new Point(100, 100) };
        var r2 = new Resistor { Id = "R2", Position = new Point(200, 100) };
        var wire = new Wire(r1.Pins[1], r2.Pins[0]);

        int changedCount = 0;
        model.Changed += (_, _) => changedCount++;

        model.Toggle(r1);
        Assert.True(model.IsSelected(r1));
        Assert.Same(r1, model.PrimaryElement);

        model.Toggle(r2);
        Assert.Equal(2, model.Count);
        Assert.True(model.IsSelected(r1));
        Assert.True(model.IsSelected(r2));

        model.Toggle(wire);
        Assert.Single(model.Wires);
        Assert.True(model.IsSelected(wire));

        // r1'i seçimden çıkarınca PrimaryElement r2 olmalı
        model.Toggle(r1);
        Assert.Equal(1, model.Count);
        Assert.False(model.IsSelected(r1));
        Assert.Same(r2, model.PrimaryElement);

        model.Toggle(wire);
        Assert.Empty(model.Wires);
        Assert.Equal(5, changedCount);
    }

    [Fact]
    public void Clear_And_SelectAll_WorkAndRaiseChanged()
    {
        var model = new SelectionModel();
        var r1 = new Resistor { Id = "R1", Position = new Point(40, 40) };
        var r2 = new Capacitor { Id = "C1", Position = new Point(160, 40) };
        var gnd = new GroundElement { Id = "GND1", Position = new Point(40, 120) };
        var w1 = new Wire(r1.Pins[1], r2.Pins[0]);

        int changedCount = 0;
        model.Changed += (_, _) => changedCount++;

        model.SelectAll(new CircuitElement[] { r1, r2, gnd }, new[] { w1 });
        Assert.Equal(3, model.Count);
        Assert.Single(model.Wires);
        Assert.True(model.HasSelection);
        Assert.Equal(1, changedCount);

        model.Clear();
        Assert.Equal(0, model.Count);
        Assert.Empty(model.Wires);
        Assert.False(model.HasSelection);
        Assert.Null(model.PrimaryElement);
        Assert.Equal(2, changedCount);
    }

    [Fact]
    public void HitTest_PartiallyOverlappingElementCounts_WireCountsOnlyIfBothEndsInside()
    {
        // R1: (100, 100) -> genişlik 80, yükseklik 50 => [100..180, 100..150]
        var r1 = new Resistor { Id = "R1", Position = new Point(100, 100) };
        // R2: (300, 100) -> [300..380, 100..150]
        var r2 = new Resistor { Id = "R2", Position = new Point(300, 100) };
        // R3: (500, 100) -> [500..580, 100..150]
        var r3 = new Resistor { Id = "R3", Position = new Point(500, 100) };

        // w12: R1.Pin2 (180, 120) -> R2.Pin1 (300, 120)
        var w12 = new Wire(r1.Pins[1], r2.Pins[0]);
        // w23: R2.Pin2 (380, 120) -> R3.Pin1 (500, 120)
        var w23 = new Wire(r2.Pins[1], r3.Pins[0]);

        var elements = new CircuitElement[] { r1, r2, r3 };
        var wires = new[] { w12, w23 };

        // Dikdörtgen: [170..350, 90..160]
        // R1 ile kısmen kesişir (170..180), R2 ile kısmen kesişir (300..350), R3 dışarıda.
        // w12'nin iki ucu (180,120) ve (300,120) dikdörtgenin içinde -> seçilmeli.
        // w23'ün hiçbir ucu (380,120) ve (500,120) dikdörtgenin içinde değil -> seçilmemeli.
        var rect = new Rect(new Point(170, 90), new Point(350, 160));
        var (hitElements, hitWires) = SelectionModel.HitTest(rect, elements, wires);

        Assert.Equal(2, hitElements.Count);
        Assert.Contains(r1, hitElements);
        Assert.Contains(r2, hitElements);
        Assert.DoesNotContain(r3, hitElements);

        Assert.Single(hitWires);
        Assert.Contains(w12, hitWires);
        Assert.DoesNotContain(w23, hitWires);

        // Tek ucu içeride olan tel seçilmemeli: [170..250, 90..160] -> sadece (180,120) içeride, (300,120) dışarıda
        var rectSingleEnd = new Rect(new Point(170, 90), new Point(250, 160));
        var (hitEl2, hitWires2) = SelectionModel.HitTest(rectSingleEnd, elements, wires);
        Assert.Single(hitEl2);
        Assert.Contains(r1, hitEl2);
        Assert.Empty(hitWires2);
    }

    [Fact]
    public void SelectInRect_SupportsReplaceAndAdditiveCtrlMode()
    {
        var model = new SelectionModel();
        var r1 = new Resistor { Id = "R1", Position = new Point(100, 100) };
        var r2 = new Resistor { Id = "R2", Position = new Point(300, 100) };
        var elements = new CircuitElement[] { r1, r2 };
        var wires = System.Array.Empty<Wire>();

        model.Select(r1);
        Assert.True(model.IsSelected(r1));

        // Normal çerçeve seçimi (additive = false) mevcut seçimi değiştirir
        model.SelectInRect(new Rect(new Point(290, 90), new Point(390, 160)), elements, wires, additive: false);
        Assert.Equal(1, model.Count);
        Assert.False(model.IsSelected(r1));
        Assert.True(model.IsSelected(r2));

        // Ctrl ile çerçeve seçimi (additive = true) mevcut seçime ekler
        model.SelectInRect(new Rect(new Point(90, 90), new Point(190, 160)), elements, wires, additive: true);
        Assert.Equal(2, model.Count);
        Assert.True(model.IsSelected(r1));
        Assert.True(model.IsSelected(r2));
    }
}
