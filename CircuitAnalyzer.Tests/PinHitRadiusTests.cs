using System;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using CircuitAnalyzer.WPF;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

[Collection(WpfUiCollection.Name)]
public class PinHitRadiusTests
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
            finally
            {
                System.Windows.Threading.Dispatcher.CurrentDispatcher.InvokeShutdown();
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

    [Fact]
    public void FindNearestPin_CapsRadiusInNormalMode_UncappedInWireMode()
    {
        RunOnSta(() =>
        {
            var win = new MainWindow
            {
                ClipboardService = new InMemoryClipboardService()
            };

            var example = new ExampleCircuit { Name = "PinHitTest" };
            var resistor = example.Add(new Resistor { Value = 1000 }, "R1", 100, 100);
            var ground = example.Add(new GroundElement(), "GND1", 300, 100);
            win.LoadExample(example);

            // R1 @ (100,100): pins at (100,120) and (180,120), centre at (140,120)
            // GND1 @ (300,100): pin at (320,100), centre at (320,120)

            // 1. zoom 1.0: 8 units from resistor pin -> that pin; resistor centre -> null
            win.SetZoom(1.0);
            Assert.Same(resistor.Pins[0], win.FindNearestPin(new Point(108, 120)));
            Assert.Null(win.FindNearestPin(new Point(140, 120)));

            // 2. zoom 0.25, normal mode (capped at 14): resistor centre -> null; ground centre (20,20) -> null; 6 units from ground pin -> that pin
            win.SetZoom(0.25);
            Assert.Null(win.FindNearestPin(new Point(140, 120)));
            Assert.Null(win.FindNearestPin(new Point(320, 120)));
            Assert.Same(ground.Pins[0], win.FindNearestPin(new Point(320, 106)));

            // 3. zoom 0.25, wire mode active (uncapped radius = 12 / 0.25 = 48): 30 units from pin -> that pin
            win.BtnDrawWire.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            Assert.Same(resistor.Pins[0], win.FindNearestPin(new Point(130, 120)));
            Assert.Same(ground.Pins[0], win.FindNearestPin(new Point(320, 130)));
        });
    }
}
