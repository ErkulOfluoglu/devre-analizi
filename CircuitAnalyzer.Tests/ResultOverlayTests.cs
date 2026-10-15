using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests;

[Collection(WpfUiCollection.Name)]
public class ResultOverlayTests : IClassFixture<BackendFixture>
{
    private readonly BackendFixture _fx;

    public ResultOverlayTests(BackendFixture fx)
    {
        _fx = fx;
    }

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

    private static List<string> GetAllTexts(DependencyObject root)
    {
        var list = new List<string>();
        var visited = new HashSet<DependencyObject>();

        void Collect(DependencyObject obj)
        {
            if (!visited.Add(obj)) return;

            if (obj is TextBlock tb && !string.IsNullOrEmpty(tb.Text))
                list.Add(tb.Text);
            else if (obj is TextBox txt && !string.IsNullOrEmpty(txt.Text))
                list.Add(txt.Text);
            else if (obj is Button btn && btn.Content is string bs)
                list.Add(bs);
            else if (obj is HeaderedContentControl hcc && hcc.Header is string hs)
                list.Add(hs);

            if (obj is Border b && b.Child != null)
                Collect(b.Child);
            if (obj is Panel p)
            {
                foreach (UIElement child in p.Children)
                    Collect(child);
            }

            if (obj is Visual || obj is System.Windows.Media.Media3D.Visual3D)
            {
                int visualCount = VisualTreeHelper.GetChildrenCount(obj);
                for (int i = 0; i < visualCount; i++)
                {
                    Collect(VisualTreeHelper.GetChild(obj, i));
                }
            }

            foreach (var child in LogicalTreeHelper.GetChildren(obj))
            {
                if (child is DependencyObject dChild)
                {
                    Collect(dChild);
                }
            }
        }

        Collect(root);
        return list;
    }

    [Fact]
    public void ShowNodeNumbers_AddsOneBadgePerNonGroundNodeWithAtLeastTwoPins_AndNoneForNode0()
    {
        RunOnSta(() =>
        {
            var canvas = new Canvas();
            var unrelatedChild = new Border { Tag = "unrelated-existing-visual" };
            canvas.Children.Add(unrelatedChild);

            var circuit = ExampleCircuits.DcVoltageDivider();
            foreach (var wire in circuit.Wires)
            {
                wire.CreateOrUpdateVisual();
            }

            var netlist = NetlistBuilder.Build(circuit.Elements, circuit.Wires);

            // In DcVoltageDivider, non-ground nodes with >= 2 pins are node 1 and node 2
            var nonGroundMultiPinNodes = netlist.NodePins
                .Where(kv => kv.Key != 0 && kv.Value.Count >= 2)
                .Select(kv => kv.Key)
                .ToList();
            Assert.Equal(2, nonGroundMultiPinNodes.Count);

            var overlay = new ResultOverlay(canvas);
            overlay.ShowNodeNumbers(netlist, circuit.Wires);

            // Count overlay children added to the Canvas
            var overlayChildren = canvas.Children.Cast<UIElement>().Where(c => !ReferenceEquals(c, unrelatedChild)).ToList();
            Assert.Equal(nonGroundMultiPinNodes.Count, overlayChildren.Count);

            // All overlay elements have IsHitTestVisible == false
            Assert.All(overlayChildren, c => Assert.False(c.IsHitTestVisible));

            // Verify none of the badges is for node 0
            var allTexts = GetAllTexts(canvas);
            Assert.DoesNotContain("0", allTexts);
            Assert.Contains("1", allTexts);
            Assert.Contains("2", allTexts);

            // Clear() removes everything it added and leaves the elements' own visuals untouched
            overlay.Clear();
            Assert.Single(canvas.Children);
            Assert.Same(unrelatedChild, canvas.Children[0]);
        });
    }

    [Fact]
    public async Task ShowResults_WithRealSolver_RendersNodeBadgesAndCurrentLabels()
    {
        var circuit = ExampleCircuits.DcVoltageDivider();
        var netlist = NetlistBuilder.Build(circuit.Elements, circuit.Wires);

        var request = new AnalysisRequestDto
        {
            Netlist = netlist.Text,
            Mode = AnalysisModes.Dc,
            AnalysisType = AnalysisTypes.Nodal
        };

        // Fetch solver response on the test thread (async)
        var response = await _fx.Client.AnalyzeAsync(request);
        Assert.Equal("success", response.Status);

        // Do UI work on the STA thread
        RunOnSta(() =>
        {
            var canvas = new Canvas();
            var unrelatedChild = new Border { Tag = "unrelated-existing-visual" };
            canvas.Children.Add(unrelatedChild);

            foreach (var wire in circuit.Wires)
            {
                wire.CreateOrUpdateVisual();
            }

            var overlay = new ResultOverlay(canvas);
            overlay.ShowResults(netlist, circuit.Elements, circuit.Wires, response);

            var overlayChildren = canvas.Children.Cast<UIElement>().Where(c => !ReferenceEquals(c, unrelatedChild)).ToList();
            Assert.NotEmpty(overlayChildren);

            // All overlay elements have IsHitTestVisible == false
            Assert.All(overlayChildren, c => Assert.False(c.IsHitTestVisible));

            var allTexts = GetAllTexts(canvas);

            // Node badges containing "8 V"
            Assert.Contains(allTexts, t => t.Contains("8 V"));

            // Current labels containing "4 mA (1→2)" for R1
            Assert.Contains("4 mA (1→2)", allTexts);

            // Current labels containing "4 mA (0→1)" for V1 (source shown with real direction)
            Assert.Contains("4 mA (0→1)", allTexts);

            // Probe label containing "VP1: 8 V"
            Assert.Contains("VP1: 8 V", allTexts);

            // Clear() removes everything it added and leaves the elements' own visuals untouched
            overlay.Clear();
            Assert.Single(canvas.Children);
            Assert.Same(unrelatedChild, canvas.Children[0]);
        });
    }
}
