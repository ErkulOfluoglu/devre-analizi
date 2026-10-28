using System;
using System.Collections.Generic;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;
using Xunit;

namespace CircuitAnalyzer.Tests
{
    [Collection(WpfUiCollection.Name)]
    public class AboutTests
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

                if (obj is Visual || obj is System.Windows.Media.Media3D.Visual3D)
                {
                    int count = VisualTreeHelper.GetChildrenCount(obj);
                    for (int i = 0; i < count; i++)
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
        public void AboutView_ShowsDisclaimerVersionLicenseHolderAndAll11Components()
        {
            RunOnSta(() =>
            {
                var view = new AboutView();
                var texts = GetAllTexts(view);
                string joined = string.Join(" ", texts);

                // 1. Sorumluluk reddi metni birebir aynı olmalı
                string exactDisclaimer =
                    "Bu program bilgi paylaşımı ve eğitim amacıyla hazırlanmıştır. Olduğu gibi sunulur; " +
                    "doğruluğu, eksiksizliği veya belirli bir amaca uygunluğu konusunda hiçbir garanti verilmez. " +
                    "Sonuçları kendiniz kontrol edin. Programın kullanımından doğabilecek her türlü sonuçtan kullanıcı sorumludur; " +
                    "geliştirici sorumlu tutulamaz. Bu koşulları kabul etmiyorsanız programı kullanmayın.";

                Assert.Contains(exactDisclaimer, texts);

                // 2. Sürüm dizesi
                Assert.Contains($"Sürüm {AppInfo.Version}", texts);

                // 3. Lisans sahibi (LicenseHolder)
                Assert.Contains(AppInfo.LicenseHolder, joined);

                // 4. Tüm 11 açık kaynak bileşeni
                string[] components =
                {
                    ".NET / WPF",
                    "Python",
                    "FastAPI",
                    "Pydantic",
                    "Uvicorn",
                    "lcapy",
                    "SymPy",
                    "NumPy",
                    "mpmath",
                    "NetworkX",
                    "Starlette",
                    "ScottPlot"
                };

                foreach (string comp in components)
                {
                    Assert.Contains(comp, texts);
                }
            });
        }
    }
}
