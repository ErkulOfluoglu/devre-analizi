using System;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests
{
    public class ZoomTests
    {
        [Theory]
        [InlineData(0.1, 0.25)]
        [InlineData(0.25, 0.25)]
        [InlineData(1.0, 1.0)]
        [InlineData(4.0, 4.0)]
        [InlineData(5.5, 4.0)]
        public void ClampZoom_ClampsToMinAndMax(double input, double expected)
        {
            double actual = ZoomMath.ClampZoom(input);
            Assert.Equal(expected, actual, 4);
        }

        [Fact]
        public void ZoomIn_MultipliesByStepFactorAndClampsAtMax()
        {
            double initial = 1.0;
            double zoomed = ZoomMath.ZoomIn(initial);
            Assert.Equal(1.2, zoomed, 4);

            double maxClamped = ZoomMath.ZoomIn(3.8);
            Assert.Equal(4.0, maxClamped, 4);
        }

        [Fact]
        public void ZoomOut_DividesByStepFactorAndClampsAtMin()
        {
            double initial = 1.2;
            double zoomed = ZoomMath.ZoomOut(initial);
            Assert.Equal(1.0, zoomed, 4);

            double minClamped = ZoomMath.ZoomOut(0.28);
            Assert.Equal(0.25, minClamped, 4);
        }

        [Fact]
        public void ComputeZoomOffsets_PreservesCanvasPointUnderMouse()
        {
            // Viewport boyutu 800x600, fare imleci (400, 300)'de
            double oldZoom = 1.0;
            double newZoom = 2.0;
            double mouseX = 400;
            double mouseY = 300;
            double oldH = 100;
            double oldV = 50;

            // Yakınlaştırma öncesi imlecin gösterdiği tuval koordinatı:
            double canvasXBefore = (oldH + mouseX) / oldZoom;
            double canvasYBefore = (oldV + mouseY) / oldZoom;

            var (newH, newV) = ZoomMath.ComputeZoomOffsets(oldZoom, newZoom, mouseX, mouseY, oldH, oldV);

            // Yakınlaştırma sonrası imlecin gösterdiği tuval koordinatı:
            double canvasXAfter = (newH + mouseX) / newZoom;
            double canvasYAfter = (newV + mouseY) / newZoom;

            Assert.Equal(canvasXBefore, canvasXAfter, 4);
            Assert.Equal(canvasYBefore, canvasYAfter, 4);
        }

        [Fact]
        public void ComputeFit_ClampsBetween25And200Percent()
        {
            // Çok devasa devre (10000x8000) -> 0.25'e kenetlenmeli
            var (hugeFitZoom, _, _) = ZoomMath.ComputeFit(0, 0, 10000, 8000, 800, 600, 40);
            Assert.Equal(0.25, hugeFitZoom, 4);

            // Çok ufak devre (10x10) -> 2.0'a kenetlenmeli
            var (tinyFitZoom, _, _) = ZoomMath.ComputeFit(100, 100, 110, 110, 800, 600, 40);
            Assert.Equal(2.0, tinyFitZoom, 4);
        }

        [Fact]
        public void ComputeFit_CentersContentInViewport()
        {
            // İçerik: (100, 100) -> (900, 700), genişlik 800, yükseklik 600, merkez (500, 400)
            // Viewport: 1000x800, margin 40 -> kullanılabilir alan 920x720
            // zX = 920 / 800 = 1.15, zY = 720 / 600 = 1.2 -> fitZoom = 1.15
            var (fitZoom, hOff, vOff) = ZoomMath.ComputeFit(100, 100, 900, 700, 1000, 800, 40);
            Assert.Equal(1.15, fitZoom, 4);

            // Merkezleme kontrolü: tuval merkezi ekranda tam ortaya gelmeli
            double centerXInViewport = (500 * fitZoom) - hOff;
            double centerYInViewport = (400 * fitZoom) - vOff;
            Assert.Equal(500.0, centerXInViewport, 2);
            Assert.Equal(400.0, centerYInViewport, 2);
        }

        [Fact]
        public void NeedsFitAt100_DetectsOverflow()
        {
            // Viewport 800x600, margin 40 -> izin verilen azami boyut 720x520
            // İçerik 600x400 sığar -> false
            Assert.False(ZoomMath.NeedsFitAt100(0, 0, 600, 400, 800, 600, 40));

            // İçerik 750x400 genişlikten taşar -> true
            Assert.True(ZoomMath.NeedsFitAt100(0, 0, 750, 400, 800, 600, 40));

            // İçerik 500x550 yükseklikten taşar -> true
            Assert.True(ZoomMath.NeedsFitAt100(0, 0, 500, 550, 800, 600, 40));
        }

        [Fact]
        public void ComputeScrollToCenter_CentersContentWithoutScaling()
        {
            // İçerik (200, 100) -> (600, 500), merkez (400, 300)
            // Viewport: 800x600, zoom 1.0 -> merkez tam görünüm ortasına gelir (offset = 0)
            var (hOff, vOff) = ZoomMath.ComputeScrollToCenter(200, 100, 600, 500, 1.0, 800, 600);
            Assert.Equal(0, hOff, 2);
            Assert.Equal(0, vOff, 2);

            // İçerik sağa kayık (800, 600) -> (1200, 1000), merkez (1000, 800)
            // Viewport: 800x600, zoom 1.0 -> hOff = 1000 - 400 = 600, vOff = 800 - 300 = 500
            var (hOff2, vOff2) = ZoomMath.ComputeScrollToCenter(800, 600, 1200, 1000, 1.0, 800, 600);
            Assert.Equal(600, hOff2, 2);
            Assert.Equal(500, vOff2, 2);
        }
    }
}
