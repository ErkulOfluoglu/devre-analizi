using System.Linq;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using CircuitAnalyzer.WPF.Helpers;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;
using CircuitAnalyzer.WPF.Views;

namespace CircuitAnalyzer.WPF
{
    // MainWindow parçası: yeni / aç / kaydet, son dosyalar, kirli durum, geri al / yinele ve yazdırma.
    public partial class MainWindow
    {
        // ── Dosya ve Geri Al / Yinele durumu ──
        private string? _currentFilePath;
        private bool _isDirty;
        private readonly UndoHistory _undoHistory = new();
        private bool _isRestoringHistory;
        private int? _problemCode;

        // ═══════════════════════════════════════════════════════
        //  DOSYA (KAYDET / AÇ / YENİ) VE BAŞLIK
        // ═══════════════════════════════════════════════════════

        public void UpdateTitle()
        {
            string docName = !string.IsNullOrEmpty(_currentFilePath)
                ? System.IO.Path.GetFileNameWithoutExtension(_currentFilePath)
                : "Adsız";
            Title = $"Devre Analizi — {docName}{(_isDirty ? " •" : "")}";
        }

        private void UpdateUndoRedoButtons()
        {
            if (BtnUndo != null) BtnUndo.IsEnabled = _undoHistory.CanUndo;
            if (BtnRedo != null) BtnRedo.IsEnabled = _undoHistory.CanRedo;
        }

        public void Undo()
        {
            if (!_undoHistory.CanUndo) return;
            string? json = _undoHistory.Undo();
            if (json != null)
            {
                RestoreCircuitFromSnapshot(json);
            }
        }

        public void Redo()
        {
            if (!_undoHistory.CanRedo) return;
            string? json = _undoHistory.Redo();
            if (json != null)
            {
                RestoreCircuitFromSnapshot(json);
            }
        }

        private void RestoreCircuitFromSnapshot(string json)
        {
            var doc = CircuitDocument.FromJson(json);
            var circuit = doc.ToCircuit("Geri Yükleme");
            _isRestoringHistory = true;
            try
            {
                ClearCircuit();
                foreach (var element in circuit.Elements)
                    AddElementToCanvasCore(element);
                foreach (var wire in circuit.Wires)
                {
                    _wires.Add(wire);
                    CircuitCanvas.Children.Add(wire.CreateOrUpdateVisual());
                }
                RefreshJunctionWireCounts();
                SyncCountersFromIds();

                OnCircuitChanged();
                _isDirty = true;
                UpdateTitle();
                TxtStatus.Text = "Devre durumu geri yüklendi";
            }
            finally
            {
                _isRestoringHistory = false;
            }
        }

        public bool SaveCircuit()
        {
            if (string.IsNullOrEmpty(_currentFilePath))
                return SaveAsCircuit();
            return SaveTo(_currentFilePath);
        }

        public bool SaveAsCircuit()
        {
            string initialName = _problemCode.HasValue
                ? $"Soru-{_problemCode.Value}.devre"
                : "Devre1.devre";

            var dialog = new Microsoft.Win32.SaveFileDialog
            {
                Filter = CircuitDocument.FileFilter,
                DefaultExt = CircuitDocument.FileExtension,
                FileName = initialName,
            };

            if (dialog.ShowDialog(this) == true)
            {
                return SaveTo(dialog.FileName);
            }
            return false;
        }

        private bool SaveTo(string path)
        {
            try
            {
                var doc = CircuitDocument.FromCircuit(_elements, _wires);
                doc.Analysis = AnalysisPanel.GetAnalysisSettings();
                doc.ProblemCode = _problemCode;
                doc.Save(path);

                _currentFilePath = path;
                _isDirty = false;
                AppSettings.AddRecentFile(path);
                UpdateTitle();
                TxtStatus.Text = $"Kaydedildi: {System.IO.Path.GetFileName(path)}";
                return true;
            }
            catch (CircuitFileException ex)
            {
                MessageBox.Show(this, ex.Message, "Kaydetme Hatası", MessageBoxButton.OK, MessageBoxImage.Error);
                return false;
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, $"Dosya kaydedilemedi: {ex.Message}", "Kaydetme Hatası", MessageBoxButton.OK, MessageBoxImage.Error);
                return false;
            }
        }

        public bool OpenFile(string path, bool isSelfTest = false)
        {
            if (!System.IO.File.Exists(path))
            {
                if (!isSelfTest && !HasAnySelfTest(Environment.GetCommandLineArgs()))
                    MessageBox.Show(this, $"Dosya bulunamadı:\n{path}", "Dosya Açılamadı", MessageBoxButton.OK, MessageBoxImage.Warning);
                AppSettings.RemoveRecentFile(path);
                return false;
            }

            try
            {
                var doc = CircuitDocument.Load(path);
                string fileName = System.IO.Path.GetFileNameWithoutExtension(path);
                var circuit = doc.ToCircuit(fileName);

                LoadExample(circuit);
                AnalysisPanel.RestoreAnalysisSettings(doc.Analysis);
                if (doc.ProblemCode != null)
                {
                    _problemCode = doc.ProblemCode;
                    AnalysisPanel.IsPracticeMode = true;
                    AnalysisPanel.SetProblemCode(doc.ProblemCode);
                }
                else
                {
                    _problemCode = null;
                    AnalysisPanel.SetProblemCode(null);
                }

                _currentFilePath = path;
                _isDirty = false;
                _undoHistory.Reset(CircuitDocument.Snapshot(_elements, _wires));
                AppSettings.AddRecentFile(path);
                UpdateTitle();
                AutoFitOrScrollCircuit();
                TxtStatus.Text = $"Açıldı: {System.IO.Path.GetFileName(path)}";
                return true;
            }
            catch (CircuitFileException ex)
            {
                if (!isSelfTest && !HasAnySelfTest(Environment.GetCommandLineArgs()))
                    MessageBox.Show(this, ex.Message, "Dosya Açılamadı", MessageBoxButton.OK, MessageBoxImage.Error);
                return false;
            }
            catch (Exception ex)
            {
                if (!isSelfTest && !HasAnySelfTest(Environment.GetCommandLineArgs()))
                    MessageBox.Show(this, $"Dosya okunamadı: {ex.Message}", "Dosya Açılamadı", MessageBoxButton.OK, MessageBoxImage.Error);
                return false;
            }
        }

        private void PromptAndOpenFileDialog()
        {
            if (!PromptSaveIfDirty()) return;

            var dialog = new Microsoft.Win32.OpenFileDialog
            {
                Filter = CircuitDocument.FileFilter,
                DefaultExt = CircuitDocument.FileExtension,
            };

            if (dialog.ShowDialog(this) == true)
            {
                OpenFile(dialog.FileName);
            }
        }

        public void NewCircuit()
        {
            if (!PromptSaveIfDirty())
                return;

            ClearCircuit();
            _problemCode = null;
            AnalysisPanel.SetProblemCode(null);
            _currentFilePath = null;
            _isDirty = false;
            _undoHistory.Reset(CircuitDocument.Snapshot(_elements, _wires));
            UpdateTitle();
            AnalysisPanel.ClearResults();
            AutoFitOrScrollCircuit();
            TxtStatus.Text = "Yeni devre oluşturuldu";
        }

        public bool PromptSaveIfDirty()
        {
            if (!_isDirty || HasAnySelfTest(Environment.GetCommandLineArgs()))
                return true;

            var result = MessageBox.Show(
                this,
                "Değişiklikleri kaydetmek istiyor musunuz?",
                "Devre Analizi",
                MessageBoxButton.YesNoCancel,
                MessageBoxImage.Question);

            if (result == MessageBoxResult.Yes)
            {
                return SaveCircuit();
            }
            else if (result == MessageBoxResult.No)
            {
                return true;
            }
            else
            {
                return false;
            }
        }

        protected override void OnClosing(System.ComponentModel.CancelEventArgs e)
        {
            if (!PromptSaveIfDirty())
            {
                e.Cancel = true;
                return;
            }
            base.OnClosing(e);
        }

        private void BtnOpen_Click(object sender, RoutedEventArgs e)
        {
            var menu = new ContextMenu
            {
                PlacementTarget = BtnOpen,
                Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom,
            };

            var chooseItem = new MenuItem
            {
                Header = "Dosya seç…",
                InputGestureText = "Ctrl+O",
            };
            chooseItem.Click += (_, _) => PromptAndOpenFileDialog();
            menu.Items.Add(chooseItem);

            var recent = AppSettings.RecentFiles;
            if (recent.Count > 0)
            {
                menu.Items.Add(new Separator());
                foreach (var file in recent)
                {
                    string filePath = file;
                    var item = new MenuItem
                    {
                        Header = System.IO.Path.GetFileName(filePath),
                        ToolTip = filePath,
                    };
                    item.Click += (_, _) =>
                    {
                        if (!System.IO.File.Exists(filePath))
                        {
                            MessageBox.Show(this, $"Dosya bulunamadı:\n{filePath}", "Dosya Yok", MessageBoxButton.OK, MessageBoxImage.Warning);
                            AppSettings.RemoveRecentFile(filePath);
                            return;
                        }
                        if (!PromptSaveIfDirty()) return;
                        OpenFile(filePath);
                    };
                    menu.Items.Add(item);
                }
            }

            menu.IsOpen = true;
        }

        private void BtnSave_Click(object sender, RoutedEventArgs e)
        {
            SaveCircuit();
        }

        private void BtnPrint_Click(object sender, RoutedEventArgs e)
        {
            PrintOrExportPdf();
        }

        public void PrintOrExportPdf(bool isSelfTest = false)
        {
            if (_lastResponse == null || _lastSolveVersion != _circuitVersion)
            {
                MessageBox.Show(this, "Önce devreyi çözün.", "Yazdır / PDF", MessageBoxButton.OK, MessageBoxImage.Information);
                return;
            }

            bool isPractice = AnalysisPanel.IsShowingPractice;
            var circuitBmp = RenderCircuitBitmap();

            string title = !string.IsNullOrEmpty(_currentFilePath)
                ? System.IO.Path.GetFileName(_currentFilePath)
                : (_problemCode.HasValue ? $"Soru #{_problemCode.Value}" : "Devre Analizi");

            var settings = AnalysisPanel.GetAnalysisSettings();
            string methodDisplay = settings.Type switch
            {
                AnalysisTypes.Nodal => "Düğüm gerilimleri yöntemi",
                AnalysisTypes.Mesh => "Çevre akımları yöntemi",
                AnalysisTypes.Thevenin => "Thevenin eşdeğeri",
                AnalysisTypes.Norton => "Norton eşdeğeri",
                AnalysisTypes.Superposition => "Süperpozisyon yöntemi",
                _ => settings.Type ?? "Düğüm gerilimleri yöntemi"
            };

            string? terminals = null;
            if (settings.Type == AnalysisTypes.Thevenin || settings.Type == AnalysisTypes.Norton)
            {
                terminals = $"{settings.TerminalPositive ?? "?"} - {settings.TerminalNegative ?? "?"}";
            }
            string? freq = !string.IsNullOrWhiteSpace(settings.Frequency) ? settings.Frequency + " Hz" : null;

            var input = new PrintInput
            {
                Response = _lastResponse,
                Title = title,
                Date = DateTime.Now,
                CircuitImage = circuitBmp,
                Method = methodDisplay,
                Terminals = terminals,
                Frequency = freq,
                IsPracticeMode = isPractice,
                PracticeQuestions = _lastResponse.Results?.Practice
            };

            var doc = SolutionPrinter.BuildDocument(input);

            if (isSelfTest) return;

            var dialog = new PrintDialog();
            TxtStatus.Text = "PDF için yazıcı olarak “Microsoft Print to PDF”i seçin";
            if (dialog.ShowDialog() == true)
            {
                var paginator = ((System.Windows.Documents.IDocumentPaginatorSource)doc).DocumentPaginator;
                dialog.PrintDocument(paginator, "Devre Analizi — PDF için yazıcı olarak “Microsoft Print to PDF”i seçin");
                TxtStatus.Text = "Belge yazıcıya gönderildi";
            }
        }

        public RenderTargetBitmap? RenderCircuitBitmap()
        {
            if (_elements.Count == 0 && _wires.Count == 0)
                return null;

            double minX = double.MaxValue, minY = double.MaxValue;
            double maxX = double.MinValue, maxY = double.MinValue;

            foreach (var el in _elements)
            {
                minX = Math.Min(minX, el.Position.X);
                minY = Math.Min(minY, el.Position.Y);
                maxX = Math.Max(maxX, el.Position.X + 80);
                maxY = Math.Max(maxY, el.Position.Y + 40);
            }
            foreach (var wire in _wires)
            {
                minX = Math.Min(minX, Math.Min(wire.StartPin.AbsolutePosition.X, wire.EndPin.AbsolutePosition.X));
                minY = Math.Min(minY, Math.Min(wire.StartPin.AbsolutePosition.Y, wire.EndPin.AbsolutePosition.Y));
                maxX = Math.Max(maxX, Math.Max(wire.StartPin.AbsolutePosition.X, wire.EndPin.AbsolutePosition.X));
                maxY = Math.Max(maxY, Math.Max(wire.StartPin.AbsolutePosition.Y, wire.EndPin.AbsolutePosition.Y));
                foreach (var wp in wire.Waypoints)
                {
                    minX = Math.Min(minX, wp.X);
                    minY = Math.Min(minY, wp.Y);
                    maxX = Math.Max(maxX, wp.X);
                    maxY = Math.Max(maxY, wp.Y);
                }
            }

            double margin = 30.0;
            minX = Math.Max(0, minX - margin);
            minY = Math.Max(0, minY - margin);
            maxX += margin;
            maxY += margin;

            double w = Math.Max(50, maxX - minX);
            double h = Math.Max(50, maxY - minY);

            var prevChoice = ThemeManager.Choice;
            double oldZoom = _currentZoom;

            try
            {
                if (ThemeManager.IsDark)
                {
                    ThemeManager.SetChoice(ThemeChoice.Light);
                }
                SetZoom(1.0);
                CircuitCanvas.UpdateLayout();

                int bmpW = (int)Math.Ceiling(w * 2.0);
                int bmpH = (int)Math.Ceiling(h * 2.0);
                var rtb = new RenderTargetBitmap(bmpW, bmpH, 96 * 2.0, 96 * 2.0, PixelFormats.Pbgra32);
                var visual = new DrawingVisual();
                using (var dc = visual.RenderOpen())
                {
                    var bgBrush = (Brush)Application.Current.FindResource("Brush.Bg.Surface");
                    dc.DrawRectangle(bgBrush, null, new Rect(0, 0, w, h));
                    var vb = new VisualBrush(CircuitCanvas)
                    {
                        Viewbox = new Rect(minX, minY, w, h),
                        ViewboxUnits = BrushMappingMode.Absolute
                    };
                    dc.DrawRectangle(vb, null, new Rect(0, 0, w, h));
                }
                rtb.Render(visual);
                return rtb;
            }
            catch
            {
                return null;
            }
            finally
            {
                SetZoom(oldZoom);
                if (ThemeManager.Choice != prevChoice)
                {
                    ThemeManager.SetChoice(prevChoice);
                }
            }
        }

        private void BtnUndo_Click(object sender, RoutedEventArgs e) => Undo();
        private void BtnRedo_Click(object sender, RoutedEventArgs e) => Redo();
    }
}
