using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using CircuitAnalyzer.WPF.Models;
using CircuitAnalyzer.WPF.Services;

namespace CircuitAnalyzer.WPF
{
    /// <summary>
    /// Devre elemanı düzenleme diyaloğu.
    /// 
    /// ★ Fazör Desteği:
    /// Standart sayısal alanların yanı sıra, karmaşık sayı girişi
    /// ve mod seçimi (RadioButton) desteği vardır.
    /// 
    /// Form tipleri:
    ///   Resistor       → Direnç (Ω)                    [sayısal]
    ///   Capacitor      → Kapasitans (µF)                [sayısal]
    ///   Inductor       → İndüktans (mH)                 [sayısal]
    ///   VoltageSource  → Gerilim (V)                    [sayısal]
    ///   AcVoltageSource→ Mod seçimi: Fiziksel / Fazör   [mod + sayısal/karmaşık]
    ///   ImpedanceElement→ Mod seçimi: Dik.sel / Kutupsal [mod + karmaşık]
    /// </summary>
    public partial class ElementEditorWindow : Window
    {
        private readonly CircuitElement _element;

        // ── Standart sayısal alanlar ──
        private readonly List<TextBox> _valueBoxes = new();
        private readonly List<Action<double>> _setters = new();
        private readonly List<double> _unitScales = new();

        // ── Karmaşık sayı alanları ──
        private readonly List<(TextBox Box, Action<ComplexValue> Setter)> _complexInputs = new();
        private TextBox? _complexInputBox = null;
        private Action<ComplexValue>? _complexSetter = null;
        private TextBlock? _previewText = null;

        // ── Dinamik alan paneli (mod değiştiğinde yeniden oluşturulur) ──
        private StackPanel? _dynamicPanel = null;
        private bool _transformerIdealUseRatio = true;
        private bool _transformerCoupledUseK = true;

        // ── Bağımlı kaynak formu: kontrol listesi, işaret kutusu ve onaylanınca uygulanacak işlemler ──
        private readonly IReadOnlyList<CircuitElement> _circuitElements;
        private readonly List<Action> _commitActions = new();
        private ComboBox? _controlCombo = null;
        private CheckBox? _reversedCheck = null;
        private readonly List<string> _controlIds = new();

        /// <summary>
        /// circuitElements: tuvaldaki tüm elemanlar. Bağımlı kaynağın "Kontrol eden eleman" listesi
        /// bunlardan doldurulur (verilmezse liste boş kalır). Diğer eleman türleri bunu kullanmaz.
        /// </summary>
        public ElementEditorWindow(CircuitElement element, IEnumerable<CircuitElement>? circuitElements = null)
        {
            InitializeComponent();
            CircuitAnalyzer.WPF.Services.ThemeManager.ApplyTitleBar(this);
            _element = element;
            _circuitElements = circuitElements?.ToList() ?? new List<CircuitElement>();
            BuildForm();
        }

        // ═══════════════════════════════════════════════════════
        //  FORM OLUŞTURMA
        // ═══════════════════════════════════════════════════════

        private void BuildForm()
        {
            TxtTitle.Text = $"{_element.Id} — Düzenle";

            switch (_element)
            {
                case ImpedanceElement z:
                    BuildImpedanceForm(z);
                    break;

                case AcVoltageSource ac:
                    BuildAcSourceForm(ac);
                    break;

                case AcCurrentSource acCurrent:
                    BuildAcSourceForm(acCurrent);
                    break;

                case DependentSource dep:
                    BuildDependentSourceForm(dep);
                    break;

                case VoltageSource vs:
                    Title = $"{vs.Id} — DC Kaynak Düzenle";
                    AddField("Gerilim (V)", vs.Value, v => vs.Value = v);
                    break;

                case CurrentSource cs:
                    Title = $"{cs.Id} — DC Akım Kaynağı Düzenle";
                    AddField("Akım (A)", cs.Value, v => cs.Value = v);
                    break;

                case Resistor r:
                    Title = $"{r.Id} — Direnç Düzenle";
                    AddField("Direnç (Ω)", r.Value, v => r.Value = v);
                    break;

                case Capacitor c:
                    Title = $"{c.Id} — Kapasitör Düzenle";
                    AddField("Kapasitans (µF)", c.Value * 1e6,
                        v => c.Value = v * 1e-6, unitScale: 1e6);
                    break;

                case Inductor l:
                    Title = $"{l.Id} — Bobin Düzenle";
                    AddField("İndüktans (mH)", l.Value * 1e3,
                        v => l.Value = v * 1e-3, unitScale: 1e3);
                    break;

                case TestProbe probe:
                    BuildProbeForm(probe);
                    break;

                case GroundElement gnd:
                    Title = $"{gnd.Id} — Toprak Referansı";
                    AddHintText("Toprak (GND) referans noktasıdır.\n" +
                        "Bağlı olduğu ağ otomatik olarak Node 0 atanır.\n" +
                        "Düzenlenecek parametresi yoktur.");
                    break;

                case SwitchElement sw:
                    BuildSwitchForm(sw);
                    break;

                case SpdtSwitch spdt:
                    BuildSpdtSwitchForm(spdt);
                    break;

                case TransformerElement tf:
                    BuildTransformerForm(tf);
                    break;

                case ThreePhaseSource tps:
                    BuildThreePhaseSourceForm(tps);
                    break;

                case ThreePhaseLoad tpl:
                    BuildThreePhaseLoadForm(tpl);
                    break;

                case Wattmeter wm:
                    BuildWattmeterForm(wm);
                    break;
            }

            // İlk TextBox'a odaklan
            if (_valueBoxes.Count > 0)
            {
                _valueBoxes[0].Focus();
                _valueBoxes[0].SelectAll();
            }
            else if (_complexInputBox != null)
            {
                _complexInputBox.Focus();
                _complexInputBox.SelectAll();
            }
        }

        // ═══════════════════════════════════════════════════════
        //  EMPEDANS FORMU (Dikdörtgensel / Kutupsal mod seçimi)
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Empedans düzenleme formu:
        /// - Mod seçici (RadioButton): Dikdörtgensel (a+jb) / Kutupsal (r∠θ)
        /// - Tek metin kutusu: Kullanıcı istediği formatta yazar
        /// - Canlı önizleme: Her iki formatta değeri gösterir
        /// </summary>
        private void BuildImpedanceForm(ImpedanceElement z)
        {
            Title = $"{z.Id} — Empedans Düzenle";

            // Mod seçici
            AddModeSelector(
                "Giriş Modu:",
                "Dikdörtgensel (a + jb)",
                "Kutupsal (r∠θ)",
                z.InputMode == ImpedanceInputMode.Rectangular,
                isFirst =>
                {
                    z.InputMode = isFirst
                        ? ImpedanceInputMode.Rectangular
                        : ImpedanceInputMode.Polar;
                });

            // Dinamik alanlar paneli
            _dynamicPanel = new StackPanel { Margin = new Thickness(0, 4, 0, 0) };
            PropertiesPanel.Children.Add(_dynamicPanel);

            // Metin giriş alanı
            string currentText = z.InputMode == ImpedanceInputMode.Rectangular
                ? z.Impedance.ToRectangularString()
                : z.Impedance.ToPolarString();

            AddComplexField("Empedans değeri:", currentText, cv =>
            {
                z.Impedance = cv;
            });

            // Önizleme
            AddPreview(z.Impedance);

            // İpuçları
            AddHintText("Kabul edilen formatlar: 50+j30, 50+30j, 4+3i, j30, 10∠30, 10<30°");
        }

        // ═══════════════════════════════════════════════════════
        //  AC KAYNAK FORMU (Fiziksel / Fazör mod seçimi)
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// AC kaynak düzenleme formu:
        /// - Fiziksel mod: Genlik (V) + Frekans (Hz) + Faz (°)
        /// - Fazör mod: Tek metin kutusuna "10∠30" veya "10+j5" yazılır
        /// </summary>
        private void BuildAcSourceForm(AcVoltageSource ac)
        {
            Title = $"{ac.Id} — AC Kaynak Düzenle";

            // Mod seçici
            AddModeSelector(
                "Giriş Modu:",
                "Fiziksel (Genlik, Frekans, Faz)",
                "Fazör (V∠θ°)",
                ac.InputMode == AcInputMode.Physical,
                isFirst =>
                {
                    SyncValuesBeforeRebuild(ac);
                    ac.InputMode = isFirst ? AcInputMode.Physical : AcInputMode.Phasor;
                    RebuildAcFields(ac);
                },
                "InputMode_" + ac.Id);

            // Değer türü seçici
            AddModeSelector(
                "Değer türü:",
                "Etkin",
                "Tepe",
                ac.ValueKind == AcValueKind.Rms,
                isEtkin =>
                {
                    SyncValuesBeforeRebuild(ac);
                    ac.ValueKind = isEtkin ? AcValueKind.Rms : AcValueKind.Peak;
                    RebuildAcFields(ac);
                },
                "ValueKind_" + ac.Id);

            // Dinamik alanlar paneli
            _dynamicPanel = new StackPanel { Margin = new Thickness(0, 4, 0, 0) };
            PropertiesPanel.Children.Add(_dynamicPanel);

            RebuildAcFields(ac);
        }

        private void SyncValuesBeforeRebuild(AcVoltageSource ac)
        {
            if (ac.InputMode == AcInputMode.Physical && _valueBoxes.Count >= 3)
            {
                if (TurkishNumber.TryParse(_valueBoxes[0].Text, out double a)) ac.Amplitude = a;
                if (TurkishNumber.TryParse(_valueBoxes[1].Text, out double f)) ac.Frequency = f;
                if (TurkishNumber.TryParse(_valueBoxes[2].Text, out double p)) ac.Phase = p;
            }
            else if (ac.InputMode == AcInputMode.Phasor && _complexInputBox != null)
            {
                if (ComplexValue.TryParse(_complexInputBox.Text, out var cv))
                {
                    ac.Amplitude = cv.Magnitude;
                    ac.Phase = cv.AngleDegrees;
                }
                if (_valueBoxes.Count >= 1 && TurkishNumber.TryParse(_valueBoxes[0].Text, out double f))
                    ac.Frequency = f;
            }
        }

        /// <summary>
        /// AC kaynak alanlarını mod değişikliğinde yeniden oluşturur.
        /// </summary>
        private void RebuildAcFields(AcVoltageSource ac)
        {
            if (_dynamicPanel == null) return;

            _dynamicPanel.Children.Clear();
            _valueBoxes.Clear();
            _setters.Clear();
            _unitScales.Clear();
            _complexInputs.Clear();
            _complexInputBox = null;
            _complexSetter = null;

            if (ac.InputMode == AcInputMode.Physical)
            {
                // ── Fiziksel mod: üç ayrı sayısal alan ──
                string ampLabel = ac.ValueKind == AcValueKind.Rms ? "Etkin değer (V)" : "Tepe değer Um (V)";
                AddFieldTo(_dynamicPanel, ampLabel, ac.Amplitude,
                    v => ac.Amplitude = v);
                AddFieldTo(_dynamicPanel, "Frekans (Hz)", ac.Frequency,
                    v => ac.Frequency = v);
                AddFieldTo(_dynamicPanel, "Faz (°)", ac.Phase,
                    v => ac.Phase = v);
            }
            else
            {
                // ── Fazör mod: kutupsal metin girişi ──
                string phasorLabel = ac.ValueKind == AcValueKind.Rms
                    ? "Fazör değeri, etkin (V∠θ°)"
                    : "Fazör değeri, tepe (Um∠θ°)";

                string currentText = $"{TurkishNumber.Format(ac.Amplitude, "G4")}∠{TurkishNumber.Format(ac.Phase, "G4")}";

                AddComplexFieldTo(_dynamicPanel, phasorLabel,
                    currentText, cv =>
                    {
                        ac.Amplitude = cv.Magnitude;
                        ac.Phase = cv.AngleDegrees;
                    });

                AddFieldTo(_dynamicPanel, "Frekans (Hz)", ac.Frequency,
                    v => ac.Frequency = v);

                AddHintTextTo(_dynamicPanel,
                    "Örnek: 10∠30, 12<45, 7,07+j7,07");
            }

            // İlk kutuya odaklan
            if (_valueBoxes.Count > 0)
            {
                _valueBoxes[0].Focus();
                _valueBoxes[0].SelectAll();
            }
            else if (_complexInputBox != null)
            {
                _complexInputBox.Focus();
                _complexInputBox.SelectAll();
            }
        }

        /// <summary>
        /// AC akım kaynağı düzenleme formu:
        /// - Fiziksel mod: Genlik (A) + Frekans (Hz) + Faz (°)
        /// - Fazör mod: Tek metin kutusuna "10∠30" veya "0.01<45" yazılır
        /// </summary>
        private void BuildAcSourceForm(AcCurrentSource ac)
        {
            Title = $"{ac.Id} — AC Akım Kaynağı Düzenle";

            AddModeSelector(
                "Giriş Modu:",
                "Fiziksel (Genlik, Frekans, Faz)",
                "Fazör (A∠θ°)",
                ac.InputMode == AcInputMode.Physical,
                isFirst =>
                {
                    SyncValuesBeforeRebuild(ac);
                    ac.InputMode = isFirst ? AcInputMode.Physical : AcInputMode.Phasor;
                    RebuildAcFields(ac);
                },
                "InputMode_" + ac.Id);

            AddModeSelector(
                "Değer türü:",
                "Etkin",
                "Tepe",
                ac.ValueKind == AcValueKind.Rms,
                isEtkin =>
                {
                    SyncValuesBeforeRebuild(ac);
                    ac.ValueKind = isEtkin ? AcValueKind.Rms : AcValueKind.Peak;
                    RebuildAcFields(ac);
                },
                "ValueKind_" + ac.Id);

            _dynamicPanel = new StackPanel { Margin = new Thickness(0, 4, 0, 0) };
            PropertiesPanel.Children.Add(_dynamicPanel);

            RebuildAcFields(ac);
        }

        private void SyncValuesBeforeRebuild(AcCurrentSource ac)
        {
            if (ac.InputMode == AcInputMode.Physical && _valueBoxes.Count >= 3)
            {
                if (TurkishNumber.TryParse(_valueBoxes[0].Text, out double a)) ac.Amplitude = a;
                if (TurkishNumber.TryParse(_valueBoxes[1].Text, out double f)) ac.Frequency = f;
                if (TurkishNumber.TryParse(_valueBoxes[2].Text, out double p)) ac.Phase = p;
            }
            else if (ac.InputMode == AcInputMode.Phasor && _complexInputBox != null)
            {
                if (ComplexValue.TryParse(_complexInputBox.Text, out var cv))
                {
                    ac.Amplitude = cv.Magnitude;
                    ac.Phase = cv.AngleDegrees;
                }
                if (_valueBoxes.Count >= 1 && TurkishNumber.TryParse(_valueBoxes[0].Text, out double f))
                    ac.Frequency = f;
            }
        }

        private void RebuildAcFields(AcCurrentSource ac)
        {
            if (_dynamicPanel == null) return;

            _dynamicPanel.Children.Clear();
            _valueBoxes.Clear();
            _setters.Clear();
            _unitScales.Clear();
            _complexInputs.Clear();
            _complexInputBox = null;
            _complexSetter = null;

            if (ac.InputMode == AcInputMode.Physical)
            {
                string ampLabel = ac.ValueKind == AcValueKind.Rms ? "Etkin değer (A)" : "Tepe değer Im (A)";
                AddFieldTo(_dynamicPanel, ampLabel, ac.Amplitude,
                    v => ac.Amplitude = v);
                AddFieldTo(_dynamicPanel, "Frekans (Hz)", ac.Frequency,
                    v => ac.Frequency = v);
                AddFieldTo(_dynamicPanel, "Faz (°)", ac.Phase,
                    v => ac.Phase = v);
            }
            else
            {
                string phasorLabel = ac.ValueKind == AcValueKind.Rms
                    ? "Fazör değeri, etkin (A∠θ°)"
                    : "Fazör değeri, tepe (Im∠θ°)";

                string currentText = $"{TurkishNumber.Format(ac.Amplitude, "G4")}∠{TurkishNumber.Format(ac.Phase, "G4")}";

                AddComplexFieldTo(_dynamicPanel, phasorLabel,
                    currentText, cv =>
                    {
                        ac.Amplitude = cv.Magnitude;
                        ac.Phase = cv.AngleDegrees;
                    });

                AddFieldTo(_dynamicPanel, "Frekans (Hz)", ac.Frequency,
                    v => ac.Frequency = v);

                AddHintTextTo(_dynamicPanel,
                    "Örnek: 10∠30, 0,01<45, 0,007+j0,007");
            }

            if (_complexInputBox == null && _valueBoxes.Count > 0)
            {
                _valueBoxes[0].Focus();
                _valueBoxes[0].SelectAll();
            }
            else if (_complexInputBox != null)
            {
                _complexInputBox.Focus();
                _complexInputBox.SelectAll();
            }
        }

        // ═══════════════════════════════════════════════════════
        //  BAĞIMLI KAYNAK FORMU
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Bağımlı kaynak formu: tür adı, kazanç (sıfırdan farklı herhangi bir gerçel sayı, birim ipucuyla),
        /// "Kontrol eden eleman" listesi (kaynağın kendisi, GND, prob ve bağlantı noktaları hariç)
        /// ve "Yönü ters çevir" kutusu.
        /// </summary>
        private void BuildDependentSourceForm(DependentSource dep)
        {
            Title = $"{dep.Id} — Bağımlı Kaynak Düzenle";

            var kindText = new TextBlock
            {
                Text = dep.KindName,
                FontWeight = FontWeights.SemiBold,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 4)
            };
            kindText.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Text.Primary");
            PropertiesPanel.Children.Add(kindText);

            AddField($"Kazanç ({dep.GainUnit})", dep.Gain, v => dep.Gain = v);

            string output = dep.IsVoltageOutput ? "gerilimi" : "akımı";
            string control = dep.IsVoltageControlled ? "gerilimi" : "akımı";
            AddHintText($"Çıkış {output} = kazanç · kontrol eden elemanın {control}. " +
                        "Kazanç sıfırdan farklı herhangi bir gerçel sayıdır (negatif olabilir; ondalık için nokta ya da virgül).");

            // Kontrol eden eleman listesi
            var lbl = new TextBlock
            {
                Text = "Kontrol eden eleman",
                Style = (Style)FindResource("Text.Caption"),
                Margin = new Thickness(0, 8, 0, 4)
            };
            _controlCombo = new ComboBox { Margin = new Thickness(0, 0, 0, 8) };

            var choices = BuildControlChoices(dep, _circuitElements);
            _controlIds.Clear();
            _controlIds.AddRange(choices.Ids);
            foreach (string label in choices.Labels)
                _controlCombo.Items.Add(label);
            _controlCombo.SelectedIndex = choices.SelectedIndex;

            PropertiesPanel.Children.Add(lbl);
            PropertiesPanel.Children.Add(_controlCombo);

            _reversedCheck = new CheckBox
            {
                Content = "Yönü ters çevir",
                IsChecked = dep.ControlReversed,
                Margin = new Thickness(0, 0, 0, 4)
            };
            _reversedCheck.SetResourceReference(Control.ForegroundProperty, "Brush.Text.Primary");
            PropertiesPanel.Children.Add(_reversedCheck);

            AddHintText(dep.IsVoltageControlled
                ? "Kontrol gerilimi, o elemanın 1. ucu (+) ile 2. ucu (−) arasındaki gerilimdir. Ters çevirirseniz işareti değişir."
                : "Kontrol akımı, o elemanın içinden 1. uçtan 2. uca doğru akan akımdır. Ters çevirirseniz işareti değişir.");

            _commitActions.Add(() =>
            {
                int index = _controlCombo.SelectedIndex;
                dep.ControlElementId = index >= 0 && index < _controlIds.Count ? _controlIds[index] : string.Empty;
                dep.ControlReversed = _reversedCheck.IsChecked == true;
            });
        }

        /// <summary>
        /// "Kontrol eden eleman" listesi: ilk satır "(seçilmedi)", sonra tuvaldeki diğer iki uçlu elemanların
        /// kimlikleri (kaynağın kendisi, GND, prob ve bağlantı noktaları hariç). Kayıtlı kontrol elemanı
        /// artık devrede yoksa "(devrede yok)" notuyla sona eklenir ki öğrenci fark etsin.
        /// </summary>
        internal static (List<string> Labels, List<string> Ids, int SelectedIndex) BuildControlChoices(
            DependentSource dep, IEnumerable<CircuitElement> circuitElements)
        {
            var labels = new List<string> { "(seçilmedi)" };
            var ids = new List<string> { string.Empty };

            foreach (var candidate in circuitElements)
            {
                if (ReferenceEquals(candidate, dep) || !DependentSource.CanBeControl(candidate))
                    continue;
                if (string.IsNullOrEmpty(candidate.Id) || ids.Contains(candidate.Id))
                    continue;
                labels.Add(candidate.Id);
                ids.Add(candidate.Id);
            }

            int selected = string.IsNullOrEmpty(dep.ControlElementId)
                ? 0
                : ids.FindIndex(id => string.Equals(id, dep.ControlElementId, StringComparison.OrdinalIgnoreCase));
            if (selected < 0)
            {
                labels.Add($"{dep.ControlElementId} (devrede yok)");
                ids.Add(dep.ControlElementId);
                selected = ids.Count - 1;
            }
            return (labels, ids, selected);
        }

        private TextBox AddNameField(string currentId, Action<string> setter)
        {
            var lbl = new TextBlock
            {
                Text = "Eleman Adı (ID)",
                Style = (Style)FindResource("Text.Caption"),
                Margin = new Thickness(0, 4, 0, 4)
            };

            var textBox = new TextBox
            {
                Text = currentId,
                Margin = new Thickness(0, 0, 0, 8)
            };

            PropertiesPanel.Children.Add(lbl);
            PropertiesPanel.Children.Add(textBox);

            _commitActions.Add(() =>
            {
                string text = textBox.Text.Trim();
                if (!string.IsNullOrEmpty(text))
                {
                    setter(text);
                }
            });

            return textBox;
        }

        private void BuildSwitchForm(SwitchElement sw)
        {
            Title = $"{sw.Id} — Anahtar Düzenle";
            AddNameField(sw.Id, id => sw.Id = id);

            var lbl = new TextBlock
            {
                Text = "Konum Değişimi (t = 0 anında)",
                Style = (Style)FindResource("Text.Caption"),
                Margin = new Thickness(0, 8, 0, 4)
            };

            var combo = new ComboBox
            {
                Margin = new Thickness(0, 0, 0, 8)
            };
            combo.Items.Add(new ComboBoxItem { Content = "t = 0'da kapanır (Normalde Açık — NO)" });
            combo.Items.Add(new ComboBoxItem { Content = "t = 0'da açılır (Normalde Kapalı — NC)" });
            combo.SelectedIndex = sw.Mode == SwitchMode.NormallyOpen ? 0 : 1;

            PropertiesPanel.Children.Add(lbl);
            PropertiesPanel.Children.Add(combo);

            _commitActions.Add(() =>
            {
                sw.Mode = combo.SelectedIndex == 1 ? SwitchMode.NormallyClosed : SwitchMode.NormallyOpen;
            });

            AddHintText("NO (Normalde Açık): t < 0 açık, t ≥ 0 kapalı.\n" +
                        "NC (Normalde Kapalı): t < 0 kapalı, t ≥ 0 açık.");
        }

        private void BuildSpdtSwitchForm(SpdtSwitch spdt)
        {
            Title = $"{spdt.Id} — İki Konumlu Anahtar";
            AddNameField(spdt.Id, id => spdt.Id = id);

            AddHintText("İki konumlu anahtar (SPDT — tek kutuplu çift yönlü).\n" +
                        "Ortak uç (c): t < 0 anında 1. uca (a), t ≥ 0 anında 2. uca (b) bağlıdır.\n" +
                        "İsim dışında düzenlenecek parametresi yoktur.");
        }

        private void BuildTransformerForm(TransformerElement tf)
        {
            Title = $"{tf.Id} — Transformatör";
            AddNameField(tf.Id, id => tf.Id = id);

            _transformerIdealUseRatio = !tf.N1.HasValue || !tf.N2.HasValue;
            _transformerCoupledUseK = tf.CouplingInput == CouplingInput.K;

            AddModeSelector("Mod:", "İdeal", "Kuplajlı", tf.Mode == TransformerMode.Ideal, isIdeal =>
            {
                tf.Mode = isIdeal ? TransformerMode.Ideal : TransformerMode.Coupled;
                RebuildTransformerFields(tf);
            }, "TfModeGroup");

            _dynamicPanel = new StackPanel();
            PropertiesPanel.Children.Add(_dynamicPanel);

            RebuildTransformerFields(tf);

            AddHintText("Nokta işaretli uçlar aynı anda pozitiftir.");
        }

        private void RebuildTransformerFields(TransformerElement tf)
        {
            if (_dynamicPanel == null) return;

            _dynamicPanel.Children.Clear();
            _valueBoxes.Clear();
            _setters.Clear();
            _unitScales.Clear();
            _complexInputs.Clear();
            _complexInputBox = null;
            _complexSetter = null;

            if (tf.Mode == TransformerMode.Ideal)
            {
                AddModeSelectorTo(_dynamicPanel, "Giriş türü:", "Oran", "Sarım sayısı", _transformerIdealUseRatio, isRatio =>
                {
                    _transformerIdealUseRatio = isRatio;
                    RebuildTransformerFields(tf);
                }, "TfIdealTypeGroup");

                if (_transformerIdealUseRatio)
                {
                    AddFieldTo(_dynamicPanel, "Oran a = N₂/N₁", tf.Ratio, v =>
                    {
                        tf.Ratio = v;
                        tf.N1 = null;
                        tf.N2 = null;
                    });
                }
                else
                {
                    double n1 = tf.N1 ?? 100;
                    double n2 = tf.N2 ?? (n1 * tf.Ratio);
                    double tempN1 = n1;
                    double tempN2 = n2;

                    AddFieldTo(_dynamicPanel, "Primer sarım sayısı (N₁)", n1, v =>
                    {
                        tempN1 = v;
                        tf.N1 = v;
                        if (tempN1 > 0 && tempN2 > 0) tf.Ratio = tempN2 / tempN1;
                    });
                    AddFieldTo(_dynamicPanel, "Sekonder sarım sayısı (N₂)", n2, v =>
                    {
                        tempN2 = v;
                        tf.N2 = v;
                        if (tempN1 > 0 && tempN2 > 0) tf.Ratio = tempN2 / tempN1;
                    });
                }
            }
            else
            {
                AddFieldTo(_dynamicPanel, "L₁ (mH)", tf.L1 * 1e3, v => tf.L1 = v * 1e-3, unitScale: 1e3);
                AddFieldTo(_dynamicPanel, "L₂ (mH)", tf.L2 * 1e3, v => tf.L2 = v * 1e-3, unitScale: 1e3);

                AddModeSelectorTo(_dynamicPanel, "Kuplaj parametresi:", "k", "M (mH)", _transformerCoupledUseK, isK =>
                {
                    _transformerCoupledUseK = isK;
                    RebuildTransformerFields(tf);
                }, "TfCouplingParamGroup");

                if (_transformerCoupledUseK)
                {
                    AddFieldTo(_dynamicPanel, "Kuplaj katsayısı k (0 < k ≤ 1)", tf.K, v =>
                    {
                        tf.K = v;
                        tf.CouplingInput = CouplingInput.K;
                    });
                }
                else
                {
                    double currentM = (tf.K * Math.Sqrt(tf.L1 * tf.L2)) * 1e3;
                    AddFieldTo(_dynamicPanel, "Ortak endüktans M (mH)", currentM, v =>
                    {
                        double mInH = v * 1e-3;
                        tf.K = TransformerElement.CalculateKFromM(mInH, tf.L1, tf.L2);
                        tf.CouplingInput = CouplingInput.M;
                    }, unitScale: 1e3);
                }
            }

            if (_valueBoxes.Count > 0)
            {
                _valueBoxes[0].Focus();
                _valueBoxes[0].SelectAll();
            }
        }

        private void BuildThreePhaseSourceForm(ThreePhaseSource src)
        {
            Title = $"{src.Id} — Üç Fazlı Kaynak";
            AddNameField(src.Id, id => src.Id = id);

            AddModeSelector("Bağlantı:", "Yıldız (Y)", "Üçgen (Δ)", src.Connection == ThreePhaseConnection.Star, isStar =>
            {
                src.Connection = isStar ? ThreePhaseConnection.Star : ThreePhaseConnection.Delta;
            }, "3psConnGroup");

            AddModeSelector("Değer:", "Hat gerilimi", "Faz gerilimi", src.ValueBasis == ThreePhaseValueBasis.Line, isLine =>
            {
                src.ValueBasis = isLine ? ThreePhaseValueBasis.Line : ThreePhaseValueBasis.Phase;
            }, "3psBasisGroup");

            AddModeSelector("Değer türü:", "Etkin", "Tepe", src.ValueKind == AcValueKind.Rms, isEtkin =>
            {
                src.ValueKind = isEtkin ? AcValueKind.Rms : AcValueKind.Peak;
            }, "3psValueKindGroup");

            AddField("Değer (V)", src.Value, v => src.Value = v);
            AddField("Frekans (Hz)", src.Frequency, f => src.Frequency = f);
            AddField("Faz (°)", src.Phase, p => src.Phase = p);

            AddModeSelector("Sıra:", "RST", "RTS", src.Sequence == ThreePhaseSequence.Rst, isRst =>
            {
                src.Sequence = isRst ? ThreePhaseSequence.Rst : ThreePhaseSequence.Rts;
            }, "3psSeqGroup");
        }

        private void BuildThreePhaseLoadForm(ThreePhaseLoad load)
        {
            Title = $"{load.Id} — Üç Fazlı Yük";
            AddNameField(load.Id, id => load.Id = id);

            AddModeSelector("Bağlantı:", "Yıldız (Y)", "Üçgen (Δ)", load.Connection == ThreePhaseConnection.Star, isStar =>
            {
                load.Connection = isStar ? ThreePhaseConnection.Star : ThreePhaseConnection.Delta;
                RebuildThreePhaseLoadFields(load);
            }, "3plConnGroup");

            var chkBalanced = new CheckBox
            {
                Content = "Dengeli",
                IsChecked = load.Balanced,
                Margin = new Thickness(0, 8, 0, 8)
            };
            chkBalanced.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            chkBalanced.Checked += (s, e) =>
            {
                load.Balanced = true;
                RebuildThreePhaseLoadFields(load);
            };
            chkBalanced.Unchecked += (s, e) =>
            {
                load.Balanced = false;
                RebuildThreePhaseLoadFields(load);
            };
            PropertiesPanel.Children.Add(chkBalanced);

            _dynamicPanel = new StackPanel();
            PropertiesPanel.Children.Add(_dynamicPanel);

            RebuildThreePhaseLoadFields(load);

            AddHintText("N ucu bağlı değilse üç iletkenli çalışır.");
        }

        private void RebuildThreePhaseLoadFields(ThreePhaseLoad load)
        {
            if (_dynamicPanel == null) return;

            _dynamicPanel.Children.Clear();
            _valueBoxes.Clear();
            _setters.Clear();
            _unitScales.Clear();
            _complexInputs.Clear();
            _complexInputBox = null;
            _complexSetter = null;

            if (load.Balanced)
            {
                AddComplexFieldTo(_dynamicPanel, "Empedans Z:", load.ZR.ToRectangularString(), cv =>
                {
                    load.ZR = cv;
                    load.ZS = ComplexValue.FromRectangular(cv.Real, cv.Imaginary);
                    load.ZT = ComplexValue.FromRectangular(cv.Real, cv.Imaginary);
                });
            }
            else
            {
                var labels = ThreePhaseLoad.GetPhaseLabels(load.Connection);
                AddComplexFieldTo(_dynamicPanel, $"{labels[0]}:", load.ZR.ToRectangularString(), cv => load.ZR = cv);
                AddComplexFieldTo(_dynamicPanel, $"{labels[1]}:", load.ZS.ToRectangularString(), cv => load.ZS = cv);
                AddComplexFieldTo(_dynamicPanel, $"{labels[2]}:", load.ZT.ToRectangularString(), cv => load.ZT = cv);
            }

            if (_complexInputBox != null)
            {
                _complexInputBox.Focus();
                _complexInputBox.SelectAll();
            }
        }

        private void BuildWattmeterForm(Wattmeter wm)
        {
            Title = $"{wm.Id} — Wattmetre";
            AddNameField(wm.Id, id => wm.Id = id);
            AddHintText("Akım bobinini hatta seri, gerilim bobinini ölçülecek iki noktaya bağlayın.");
        }

        // ═══════════════════════════════════════════════════════
        //  FORM BİLEŞENLERİ
        // ═══════════════════════════════════════════════════════

        /// <summary>Standart sayısal alan ekler (ana panele).</summary>
        /// <param name="unitScale">Alan birimi SI biriminin kaçta biriyse (µF için 1e6). Önekli
        /// girişler ("100µ", "47 mH") SI değeri olarak okunup alan birimine çevrilir.</param>
        private void AddField(string label, double currentValue, Action<double> setter, double unitScale = 1)
        {
            AddFieldTo(PropertiesPanel, label, currentValue, setter, unitScale);
        }

        /// <summary>Standart sayısal alan ekler (belirtilen panele).</summary>
        private void AddFieldTo(Panel panel, string label, double currentValue,
            Action<double> setter, double unitScale = 1)
        {
            var lbl = new TextBlock
            {
                Text = label,
                Style = (Style)FindResource("Text.Caption"),
                Margin = new Thickness(0, 8, 0, 4)
            };

            var textBox = new TextBox
            {
                Text = currentValue.ToString("G6", TurkishNumber.Culture),
                Margin = new Thickness(0, 0, 0, 8)
            };

            panel.Children.Add(lbl);
            panel.Children.Add(textBox);

            _valueBoxes.Add(textBox);
            _setters.Add(setter);
            _unitScales.Add(unitScale);
        }

        /// <summary>
        /// Karmaşık sayı giriş alanı ekler (ana panele).
        /// Tek metin kutusu + canlı önizleme.
        /// </summary>
        private void AddComplexField(string label, string currentText,
            Action<ComplexValue> setter)
        {
            AddComplexFieldTo(PropertiesPanel, label, currentText, setter);
        }

        /// <summary>Karmaşık sayı giriş alanı ekler (belirtilen panele).</summary>
        private void AddComplexFieldTo(Panel panel, string label, string currentText,
            Action<ComplexValue> setter)
        {
            var lbl = new TextBlock
            {
                Text = label,
                Style = (Style)FindResource("Text.Caption"),
                Margin = new Thickness(0, 8, 0, 4)
            };

            var textBox = new TextBox
            {
                Text = currentText,
                Margin = new Thickness(0, 0, 0, 8)
            };

            // Önizleme alanı
            var previewBlock = new TextBlock
            {
                FontSize = 12,
                Margin = new Thickness(0, 2, 0, 8),
                TextWrapping = TextWrapping.Wrap
            };
            previewBlock.SetResourceReference(TextBlock.FontFamilyProperty, "Font.UI");
            _previewText = previewBlock;

            void UpdatePreview(string input)
            {
                if (ComplexValue.TryParse(input, out var cv))
                {
                    previewBlock.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Success");
                    string unit = _element switch
                    {
                        AcVoltageSource => "V",
                        AcCurrentSource => "A",
                        _ => "Ω",
                    };
                    previewBlock.Text =
                        $"Dikdörtgensel: {cv.ToRectangularString()} {unit}\n" +
                        $"Kutupsal: {cv.ToPolarString()} {unit}";
                }
                else
                {
                    previewBlock.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Error");
                    previewBlock.Text = "Geçersiz format — Örnek: 50+j30, 10∠30, 4+3i";
                }
            }

            // Yazarken canlı önizleme güncelle
            textBox.TextChanged += (s, e) => UpdatePreview(textBox.Text);

            panel.Children.Add(lbl);
            panel.Children.Add(textBox);
            panel.Children.Add(previewBlock);

            _complexInputs.Add((textBox, setter));
            _complexInputBox = textBox;
            _complexSetter = setter;

            // Başlangıç önizlemesi
            UpdatePreview(currentText);
        }

        /// <summary>
        /// Kullanıcı yazarken karmaşık sayı önizlemesini günceller.
        /// Her iki formatta (dikdörtgensel + kutupsal) gösterir.
        /// </summary>
        private void UpdateComplexPreview(string input)
        {
            if (_previewText == null) return;

            if (ComplexValue.TryParse(input, out var cv))
            {
                _previewText.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Success");
                string unit = _element switch
                {
                    AcVoltageSource => "V",
                    AcCurrentSource => "A",
                    _ => "Ω",
                };
                _previewText.Text =
                    $"Dikdörtgensel: {cv.ToRectangularString()} {unit}\n" +
                    $"Kutupsal: {cv.ToPolarString()} {unit}";
            }
            else
            {
                _previewText.SetResourceReference(TextBlock.ForegroundProperty, "Brush.Error");
                _previewText.Text = "Geçersiz format — Örnek: 50+j30, 10∠30, 4+3i";
            }
        }

        /// <summary>Empedans için başlangıç önizlemesi.</summary>
        private void AddPreview(ComplexValue cv)
        {
            // Zaten AddComplexField içinde oluşturuluyor
            // Bu metot ek bir statik önizleme eklemek için kullanılabilir
        }

        /// <summary>Mod seçici RadioButton çifti ekler (ana panele).</summary>
        private void AddModeSelector(string label, string option1, string option2,
            bool isFirstSelected, Action<bool> onChanged, string groupName = "InputMode")
        {
            AddModeSelectorTo(PropertiesPanel, label, option1, option2, isFirstSelected, onChanged, groupName);
        }

        /// <summary>Mod seçici RadioButton çifti ekler (belirtilen panele).</summary>
        private void AddModeSelectorTo(Panel panel, string label, string option1, string option2,
            bool isFirstSelected, Action<bool> onChanged, string groupName = "InputMode")
        {
            var lbl = new TextBlock
            {
                Text = label,
                Style = (Style)FindResource("Text.Caption"),
                Margin = new Thickness(0, 8, 0, 6)
            };

            var radioPanel = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Margin = new Thickness(0, 0, 0, 8)
            };

            var radio1 = new RadioButton
            {
                Content = option1,
                IsChecked = isFirstSelected,
                GroupName = groupName,
                Margin = new Thickness(0, 0, 16, 0)
            };
            radio1.SetResourceReference(Control.ForegroundProperty, "Brush.Text.Primary");

            var radio2 = new RadioButton
            {
                Content = option2,
                IsChecked = !isFirstSelected,
                GroupName = groupName
            };
            radio2.SetResourceReference(Control.ForegroundProperty, "Brush.Text.Primary");

            radio1.Checked += (s, e) => onChanged(true);
            radio2.Checked += (s, e) => onChanged(false);

            radioPanel.Children.Add(radio1);
            radioPanel.Children.Add(radio2);

            panel.Children.Add(lbl);
            panel.Children.Add(radioPanel);
        }

        /// <summary>İpucu metni ekler (ana panele).</summary>
        private void AddHintText(string text)
        {
            AddHintTextTo(PropertiesPanel, text);
        }

        /// <summary>İpucu metni ekler (belirtilen panele).</summary>
        private void AddHintTextTo(Panel panel, string text)
        {
            var tb = new TextBlock
            {
                Text = text,
                Style = (Style)FindResource("Text.Caption"),
                FontStyle = FontStyles.Italic,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 4, 0, 0)
            };
            panel.Children.Add(tb);
        }

        // ═══════════════════════════════════════════════════════
        //  DOĞRULAMA VE UYGULAMA
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Alan değerini okur. Düz sayı ("2,2") alanın kendi birimindedir (ör. µF);
        /// önekli/birimli giriş ("100µ", "47 mH") SI değeri olarak okunup alan birimine çevrilir.
        /// </summary>
        internal static bool TryParseFieldValue(string text, double unitScale, out double val)
        {
            if (TurkishNumber.TryParse(text, out val))
                return true;
            if (!TurkishNumber.TryParseSpice(text, out double si))
                return false;
            val = si * unitScale;
            return true;
        }

        private void BtnApply_Click(object sender, RoutedEventArgs e)
        {
            // ── 1. Standart sayısal alanları doğrula ──
            for (int i = 0; i < _valueBoxes.Count; i++)
            {
                string text = _valueBoxes[i].Text.Trim();

                if (!TryParseFieldValue(text, _unitScales[i], out double val))
                {
                    MessageBox.Show(
                        $"Geçersiz sayı: \"{text}\"\n\n" +
                        "Lütfen geçerli bir ondalıklı sayı girin.\n" +
                        "Örnek: 1000, 4,7, 0,01",
                        "Giriş Hatası",
                        MessageBoxButton.OK,
                        MessageBoxImage.Warning);

                    _valueBoxes[i].Focus();
                    _valueBoxes[i].SelectAll();
                    return;
                }

                // Faz açısı dışındaki değerler pozitif olmalı (CurrentSource hariç: negatif serbest, sıfır yasak)
                bool isPhaseField = i == _valueBoxes.Count - 1 &&
                    ((_element is AcVoltageSource vac && vac.InputMode == AcInputMode.Physical) ||
                     (_element is AcCurrentSource iac && iac.InputMode == AcInputMode.Physical));

                if (_element is CurrentSource)
                {
                    if (Math.Abs(val) < 1e-15)
                    {
                        MessageBox.Show(
                            "Akım değeri sıfır olamaz.",
                            "Giriş Hatası",
                            MessageBoxButton.OK,
                            MessageBoxImage.Warning);

                        _valueBoxes[i].Focus();
                        _valueBoxes[i].SelectAll();
                        return;
                    }
                }
                else if (_element is DependentSource)
                {
                    // Kazanç: negatif serbest, yalnızca sıfır yasak
                    if (Math.Abs(val) < 1e-15)
                    {
                        MessageBox.Show(
                            "Kazanç sıfır olamaz.",
                            "Giriş Hatası",
                            MessageBoxButton.OK,
                            MessageBoxImage.Warning);

                        _valueBoxes[i].Focus();
                        _valueBoxes[i].SelectAll();
                        return;
                    }
                }
                else if (val <= 0 && !isPhaseField)
                {
                    MessageBox.Show(
                        "Değer sıfırdan büyük olmalıdır.",
                        "Giriş Hatası",
                        MessageBoxButton.OK,
                        MessageBoxImage.Warning);

                    _valueBoxes[i].Focus();
                    _valueBoxes[i].SelectAll();
                    return;
                }

                try
                {
                    _setters[i](val);
                }
                catch (InvalidOperationException ex)
                {
                    MessageBox.Show(
                        ex.Message,
                        "Giriş Hatası",
                        MessageBoxButton.OK,
                        MessageBoxImage.Warning);

                    _valueBoxes[i].Focus();
                    _valueBoxes[i].SelectAll();
                    return;
                }
            }

            if (_element is TransformerElement tfCheck && tfCheck.Mode == TransformerMode.Coupled && _transformerCoupledUseK)
            {
                if (tfCheck.K <= 0 || tfCheck.K > 1.0)
                {
                    MessageBox.Show(
                        "Kuplaj katsayısı k, 0 ile 1 arasında olmalıdır (0 < k ≤ 1).",
                        "Giriş Hatası",
                        MessageBoxButton.OK,
                        MessageBoxImage.Warning);
                    return;
                }
            }

            // ── 2. Karmaşık sayı alanını doğrula ──
            if (_complexInputs.Count > 0)
            {
                var validated = new List<(Action<ComplexValue> Setter, ComplexValue Value)>();
                foreach (var (box, setter) in _complexInputs)
                {
                    string complexText = box.Text.Trim();
                    if (!ComplexValue.TryParse(complexText, out var cv))
                    {
                        MessageBox.Show(
                            $"Geçersiz karmaşık sayı: \"{complexText}\"\n\n" +
                            "Kabul edilen formatlar:\n" +
                            "  Dikdörtgensel: 50+j30, 50+30j, 4+3i, 4+i3\n" +
                            "  Kutupsal: 10∠30, 10<30°\n" +
                            "  Saf reel: 100\n" +
                            "  Saf sanal: j50, -j30",
                            "Giriş Hatası",
                            MessageBoxButton.OK,
                            MessageBoxImage.Warning);

                        box.Focus();
                        box.SelectAll();
                        return;
                    }
                    validated.Add((setter, cv));
                }

                foreach (var (setter, cv) in validated)
                {
                    setter(cv);
                }
            }
            else if (_complexInputBox != null && _complexSetter != null)
            {
                string complexText = _complexInputBox.Text.Trim();

                if (!ComplexValue.TryParse(complexText, out var cv))
                {
                    MessageBox.Show(
                        $"Geçersiz karmaşık sayı: \"{complexText}\"\n\n" +
                        "Kabul edilen formatlar:\n" +
                        "  Dikdörtgensel: 50+j30, 50+30j, 4+3i, 4+i3\n" +
                        "  Kutupsal: 10∠30, 10<30°\n" +
                        "  Saf reel: 100\n" +
                        "  Saf sanal: j50, -j30",
                        "Giriş Hatası",
                        MessageBoxButton.OK,
                        MessageBoxImage.Warning);

                    _complexInputBox.Focus();
                    _complexInputBox.SelectAll();
                    return;
                }

                _complexSetter(cv);
            }

            // ── 3. Üç fazlı kaynak ek doğrulaması ──
            if (_element is ThreePhaseSource tpsCheck)
            {
                if (tpsCheck.Value <= 0)
                {
                    MessageBox.Show("Gerilim sıfırdan büyük olmalıdır.",
                        "Giriş Hatası", MessageBoxButton.OK, MessageBoxImage.Warning);
                    return;
                }
                if (tpsCheck.Frequency <= 0)
                {
                    MessageBox.Show("Frekans sıfırdan büyük olmalıdır.",
                        "Giriş Hatası", MessageBoxButton.OK, MessageBoxImage.Warning);
                    return;
                }
            }

            // ── 3. AC kaynak ek doğrulaması ──
            if (_element is AcVoltageSource acSrc)
            {
                if (acSrc.Amplitude <= 0)
                {
                    MessageBox.Show("Genlik sıfırdan büyük olmalıdır.",
                        "Giriş Hatası", MessageBoxButton.OK, MessageBoxImage.Warning);
                    return;
                }
                if (acSrc.InputMode == AcInputMode.Physical && acSrc.Frequency <= 0)
                {
                    MessageBox.Show("Frekans sıfırdan büyük olmalıdır.",
                        "Giriş Hatası", MessageBoxButton.OK, MessageBoxImage.Warning);
                    return;
                }
            }
            if (_element is AcCurrentSource acCurrentSrc)
            {
                if (acCurrentSrc.Amplitude <= 0)
                {
                    MessageBox.Show("Genlik sıfırdan büyük olmalıdır.",
                        "Giriş Hatası", MessageBoxButton.OK, MessageBoxImage.Warning);
                    return;
                }
                if (acCurrentSrc.InputMode == AcInputMode.Physical && acCurrentSrc.Frequency <= 0)
                {
                    MessageBox.Show("Frekans sıfırdan büyük olmalıdır.",
                        "Giriş Hatası", MessageBoxButton.OK, MessageBoxImage.Warning);
                    return;
                }
            }

            // ── 4. Metin alanını uygula (Probe hedef ID) ──
            if (_stringInputBox != null && _stringSetter != null)
            {
                _stringSetter(_stringInputBox.Text.Trim());
            }

            // ── 5. Bağımlı kaynağın liste/işaret kutusu ──
            foreach (var commit in _commitActions)
                commit();

            DialogResult = true;
            Close();
        }

        private void BtnCancel_Click(object sender, RoutedEventArgs e)
        {
            DialogResult = false;
            Close();
        }
        // ═══════════════════════════════════════════════════════
        //  ÖLÇÜM PROBU FORMU
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Ölçüm probu düzenleme formu:
        /// - Mod seçici: Gerilim (V) / Akım (I)
        /// - Gerilim modunda: bilgi mesajı (düğüm otomatik algılanır)
        /// - Akım modunda: hedef eleman ID'si giriş alanı
        /// </summary>
        private void BuildProbeForm(TestProbe probe)
        {
            Title = $"{probe.Id} — Ölçüm Probu Düzenle";

            AddModeSelector(
                "Ölçüm Tipi:",
                "Gerilim (V) — Düğüm gerilimi",
                "Akım (I) — Eleman akımı",
                probe.Type == ProbeType.Voltage,
                isVoltage =>
                {
                    probe.Type = isVoltage ? ProbeType.Voltage : ProbeType.Current;
                    // ID önekini güncelle (VP / IP)
                    string num = probe.Id.Replace("VP", "").Replace("IP", "");
                    probe.Id = (isVoltage ? "VP" : "IP") + num;
                    RebuildProbeFields(probe);
                });

            _dynamicPanel = new StackPanel { Margin = new Thickness(0, 4, 0, 0) };
            PropertiesPanel.Children.Add(_dynamicPanel);

            RebuildProbeFields(probe);
        }

        private void RebuildProbeFields(TestProbe probe)
        {
            if (_dynamicPanel == null) return;

            _dynamicPanel.Children.Clear();
            _valueBoxes.Clear();
            _setters.Clear();
            _unitScales.Clear();
            _stringInputBox = null;
            _stringSetter = null;

            if (probe.Type == ProbeType.Current)
            {
                AddStringFieldTo(_dynamicPanel,
                    "Hedef Eleman ID (ör: R1, L1, C1):",
                    probe.TargetElementId,
                    v => probe.TargetElementId = v);

                AddHintTextTo(_dynamicPanel,
                    "Akım probu, belirtilen elemandan geçen akımı ölçer.\n" +
                    "Canvas'taki elemanın ID'sini yazın.");
            }
            else
            {
                AddHintTextTo(_dynamicPanel,
                    "Gerilim probu, bağlı olduğu düğümün\n" +
                    "GND'ye göre gerilimini ölçer.\n" +
                    "Probu bir pine tel ile bağlayın.");
            }
        }

        // ═══════════════════════════════════════════════════════
        //  METİN (STRING) ALAN DESTEĞİ
        // ═══════════════════════════════════════════════════════

        private TextBox? _stringInputBox = null;
        private Action<string>? _stringSetter = null;

        /// <summary>Metin alanı ekler (belirtilen panele).</summary>
        private void AddStringFieldTo(Panel panel, string label, string currentValue,
            Action<string> setter)
        {
            var lbl = new TextBlock
            {
                Text = label,
                Style = (Style)FindResource("Text.Caption"),
                Margin = new Thickness(0, 8, 0, 4)
            };

            var textBox = new TextBox
            {
                Text = currentValue ?? "",
                Margin = new Thickness(0, 0, 0, 8)
            };

            panel.Children.Add(lbl);
            panel.Children.Add(textBox);

            _stringInputBox = textBox;
            _stringSetter = setter;
        }
    }
}
