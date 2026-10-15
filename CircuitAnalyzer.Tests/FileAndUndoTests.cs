using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.ExceptionServices;
using System.Threading;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests
{
    [Collection(WpfUiCollection.Name)]
    public class FileAndUndoTests
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

        private static string CleanNetlist(string text)
        {
            var lines = text.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.None)
                .Where(l => !l.StartsWith("* Tarih:", StringComparison.OrdinalIgnoreCase))
                .Select(l => l.Trim());
            return string.Join("\n", lines);
        }

        [Fact]
        public void CircuitDocument_RoundTrip_AllExampleCircuits()
        {
            RunOnSta(() =>
            {
                for (int i = 0; i < ExampleCircuits.All.Count; i++)
                {
                    var original = ExampleCircuits.All[i]();
                    string netlistBefore = CleanNetlist(NetlistBuilder.Build(original.Elements, original.Wires).Text);

                    var doc = CircuitDocument.FromCircuit(original.Elements, original.Wires);
                    string json = doc.ToJson();

                    var loadedDoc = CircuitDocument.FromJson(json);
                    var restoredCircuit = loadedDoc.ToCircuit("Restored");
                    string netlistAfter = CleanNetlist(NetlistBuilder.Build(restoredCircuit.Elements, restoredCircuit.Wires).Text);

                    Assert.Equal(netlistBefore, netlistAfter);
                }
            });
        }

        [Theory]
        [InlineData(1000)]
        [InlineData(4821)]
        [InlineData(9999)]
        public void CircuitDocument_RoundTrip_ProblemGenerator(int problemCode)
        {
            RunOnSta(() =>
            {
                var problem = ProblemGenerator.Generate(problemCode);
                string netlistBefore = CleanNetlist(NetlistBuilder.Build(problem.Elements, problem.Wires).Text);

                var doc = CircuitDocument.FromCircuit(problem.Elements, problem.Wires);
                doc.ProblemCode = problemCode;
                string json = doc.ToJson();

                var loadedDoc = CircuitDocument.FromJson(json);
                Assert.Equal(problemCode, loadedDoc.ProblemCode);

                var restoredCircuit = loadedDoc.ToCircuit("Problem");
                string netlistAfter = CleanNetlist(NetlistBuilder.Build(restoredCircuit.Elements, restoredCircuit.Wires).Text);

                Assert.Equal(netlistBefore, netlistAfter);
            });
        }

        [Fact]
        public void CircuitDocument_SaveAndLoad_TempFile()
        {
            RunOnSta(() =>
            {
                var original = ExampleCircuits.All[0]();
                var doc = CircuitDocument.FromCircuit(original.Elements, original.Wires);
                doc.Analysis = new CircuitDocument.AnalysisData
                {
                    Type = "nodal",
                    Frequency = "1000",
                };
                doc.ProblemCode = 1234;

                string tempFile = Path.Combine(Path.GetTempPath(), $"circuittest_{Guid.NewGuid():N}.devre");
                try
                {
                    doc.Save(tempFile);
                    Assert.True(File.Exists(tempFile));

                    var loaded = CircuitDocument.Load(tempFile);
                    Assert.Equal(doc.Elements.Count, loaded.Elements.Count);
                    Assert.Equal(doc.Wires.Count, loaded.Wires.Count);
                    Assert.Equal("nodal", loaded.Analysis?.Type);
                    Assert.Equal("1000", loaded.Analysis?.Frequency);
                    Assert.Equal(1234, loaded.ProblemCode);
                }
                finally
                {
                    if (File.Exists(tempFile))
                    {
                        File.Delete(tempFile);
                    }
                }
            });
        }

        [Fact]
        public void CircuitDocument_InvalidJson_ThrowsCircuitFileExceptionWithTurkishMessage()
        {
            var ex = Assert.Throws<CircuitFileException>(() => CircuitDocument.FromJson("{ bu bir json değil"));
            Assert.Contains("bozulmuş", ex.Message, StringComparison.OrdinalIgnoreCase);
        }

        [Fact]
        public void CircuitDocument_WrongFormat_ThrowsCircuitFileException()
        {
            var ex = Assert.Throws<CircuitFileException>(() => CircuitDocument.FromJson("{\"format\": \"baska-uygulama\", \"version\": 1}"));
            Assert.Contains("Devre Analizi dosyası değil", ex.Message);
        }

        [Fact]
        public void CircuitDocument_NewerVersion_ThrowsCircuitFileException()
        {
            var ex = Assert.Throws<CircuitFileException>(() => CircuitDocument.FromJson("{\"format\": \"devre-analizi\", \"version\": 999}"));
            Assert.Contains("daha yeni bir sürümüyle", ex.Message);
        }

        [Fact]
        public void CircuitDocument_UnknownElementType_ThrowsCircuitFileException()
        {
            RunOnSta(() =>
            {
                var doc = new CircuitDocument();
                doc.Elements.Add(new CircuitDocument.ElementData
                {
                    Type = "BILINMEYEN_ELEMAN",
                    Id = "X1",
                    X = 100,
                    Y = 100,
                });

                var ex = Assert.Throws<CircuitFileException>(() => doc.ToCircuit("Test"));
                Assert.Contains("Tanınmayan eleman türü", ex.Message);
            });
        }

        [Fact]
        public void CircuitDocument_WireToMissingElement_ThrowsCircuitFileException()
        {
            RunOnSta(() =>
            {
                var doc = new CircuitDocument();
                doc.Elements.Add(new CircuitDocument.ElementData
                {
                    Type = "R",
                    Id = "R1",
                    Value = 1000,
                    X = 100,
                    Y = 100,
                });
                doc.Wires.Add(new CircuitDocument.WireData
                {
                    From = "R1",
                    FromPin = 0,
                    To = "OLMAYAN_ELEMAN",
                    ToPin = 0,
                });

                var ex = Assert.Throws<CircuitFileException>(() => doc.ToCircuit("Test"));
                Assert.Contains("olmayan bir elemana bağlı", ex.Message);
            });
        }

        [Fact]
        public void UndoHistory_RecordDeduplication_IgnoresIdenticalConsecutiveState()
        {
            var history = new UndoHistory();
            int changeEventCount = 0;
            history.Changed += (_, _) => changeEventCount++;

            history.Record("state1");
            Assert.Equal(1, changeEventCount);
            Assert.Equal("state1", history.Current);
            Assert.False(history.CanUndo);
            Assert.False(history.CanRedo);

            // Aynı durum tekrar kaydedildiğinde yok sayılmalı
            history.Record("state1");
            Assert.Equal(1, changeEventCount);
            Assert.Equal("state1", history.Current);
            Assert.False(history.CanUndo);
        }

        [Fact]
        public void UndoHistory_UndoRedoOrder_OperatesLIFO()
        {
            var history = new UndoHistory();
            history.Record("A");
            history.Record("B");
            history.Record("C");

            Assert.True(history.CanUndo);
            Assert.False(history.CanRedo);
            Assert.Equal("C", history.Current);

            Assert.Equal("B", history.Undo());
            Assert.True(history.CanUndo);
            Assert.True(history.CanRedo);

            Assert.Equal("A", history.Undo());
            Assert.False(history.CanUndo);
            Assert.True(history.CanRedo);

            Assert.Null(history.Undo());

            Assert.Equal("B", history.Redo());
            Assert.Equal("C", history.Redo());
            Assert.False(history.CanRedo);
        }

        [Fact]
        public void UndoHistory_NewRecord_DropsRedoBranch()
        {
            var history = new UndoHistory();
            history.Record("A");
            history.Record("B");
            history.Record("C");

            history.Undo(); // B'ye döndük
            Assert.True(history.CanRedo);

            history.Record("D"); // İleri geçmiş temizlenmeli
            Assert.False(history.CanRedo);
            Assert.Equal("D", history.Current);

            Assert.Equal("B", history.Undo());
            Assert.Equal("A", history.Undo());
            Assert.Equal("B", history.Redo());
            Assert.Equal("D", history.Redo());
            Assert.False(history.CanRedo);
        }

        [Fact]
        public void UndoHistory_CapacityTrimming_DiscardsOldestStates()
        {
            var history = new UndoHistory(capacity: 3);
            history.Record("1");
            history.Record("2");
            history.Record("3");
            history.Record("4"); // "1" atılmış olmalı

            Assert.Equal("3", history.Undo());
            Assert.Equal("2", history.Undo());
            Assert.False(history.CanUndo); // "1"e geri dönemeyiz
        }

        [Fact]
        public void UndoHistory_Reset_ClearsHistoryAndSetsInitialState()
        {
            var history = new UndoHistory();
            history.Record("A");
            history.Record("B");

            history.Reset("Initial");
            Assert.Equal("Initial", history.Current);
            Assert.False(history.CanUndo);
            Assert.False(history.CanRedo);
        }

        [Fact]
        public void AppSettings_RecentFiles_CapacityDedupeAndOrder()
        {
            string tempSettings = Path.Combine(Path.GetTempPath(), $"settings_{Guid.NewGuid():N}.json");
            string originalSettingsPath = AppSettings.SettingsPath;
            try
            {
                AppSettings.SettingsPath = tempSettings;
                Assert.Empty(AppSettings.RecentFiles);

                // Dosya ekleme
                string f1 = Path.GetFullPath(@"C:\temp\Devre1.devre");
                string f2 = Path.GetFullPath(@"C:\temp\Devre2.devre");
                AppSettings.AddRecentFile(f1);
                AppSettings.AddRecentFile(f2);

                var files = AppSettings.RecentFiles;
                Assert.Equal(2, files.Count);
                Assert.Equal(f2, files[0]);
                Assert.Equal(f1, files[1]);

                // Büyük/küçük harf duyarsız tekilleştirme ve başa alma
                string f1Lower = f1.ToLowerInvariant();
                AppSettings.AddRecentFile(f1Lower);

                files = AppSettings.RecentFiles;
                Assert.Equal(2, files.Count);
                Assert.Equal(f1Lower, files[0]);
                Assert.Equal(f2, files[1]);

                // En fazla 8 dosya sınırı
                for (int i = 0; i < 10; i++)
                {
                    AppSettings.AddRecentFile(Path.GetFullPath($@"C:\temp\Devre_{i}.devre"));
                }

                files = AppSettings.RecentFiles;
                Assert.Equal(8, files.Count);
                Assert.Equal(Path.GetFullPath(@"C:\temp\Devre_9.devre"), files[0]);

                // Dosya silme
                AppSettings.RemoveRecentFile(Path.GetFullPath(@"C:\temp\Devre_9.devre"));
                files = AppSettings.RecentFiles;
                Assert.Equal(7, files.Count);
                Assert.DoesNotContain(Path.GetFullPath(@"C:\temp\Devre_9.devre"), files);
            }
            finally
            {
                AppSettings.SettingsPath = originalSettingsPath;
                if (File.Exists(tempSettings))
                {
                    try { File.Delete(tempSettings); } catch { }
                }
            }
        }
    }
}
