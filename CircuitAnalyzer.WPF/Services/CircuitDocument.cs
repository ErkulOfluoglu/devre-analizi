using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Windows;
using CircuitAnalyzer.WPF.Models;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>Devre dosyası okunamadı; mesaj öğrenciye gösterilir.</summary>
    public sealed class CircuitFileException : Exception
    {
        public CircuitFileException(string message, Exception? inner = null) : base(message, inner) { }
    }

    /// <summary>
    /// Devrenin dosya biçimi (.devre, JSON). Hem "Kaydet/Aç" hem de "Geri al /
    /// Yinele" aynı biçimi kullanır: her değişiklikte devrenin JSON hâli saklanır.
    ///
    /// Elemanlar türü, kimliği, konumu, dönüşü ve değerleriyle; teller iki ucun
    /// "eleman kimliği + pin sırası" ile kaydedilir. Bilinmeyen alanlar yok
    /// sayılır, böylece ileriki sürümlerin dosyaları da açılabilir.
    /// </summary>
    public sealed class CircuitDocument
    {
        public const string FileExtension = ".devre";
        public const string FileFilter = "Devre dosyası (*.devre)|*.devre";
        public const string FormatName = "devre-analizi";
        public const int CurrentVersion = 1;

        [JsonPropertyName("format")] public string Format { get; set; } = FormatName;
        [JsonPropertyName("version")] public int Version { get; set; } = CurrentVersion;
        [JsonPropertyName("elements")] public List<ElementData> Elements { get; set; } = new();
        [JsonPropertyName("wires")] public List<WireData> Wires { get; set; } = new();

        /// <summary>Analiz ayarları (yöntem, terminaller, frekans) — açınca geri yüklenir.</summary>
        [JsonPropertyName("analysis")] public AnalysisData? Analysis { get; set; }

        /// <summary>Rastgele üretilmiş sorunun kodu (varsa).</summary>
        [JsonPropertyName("problem_code")] public int? ProblemCode { get; set; }

        public sealed class ElementData
        {
            /// <summary>"R", "C", "L", "Z", "V", "VAC", "I", "IAC", "DEP", "GND", "PROBE", "J"</summary>
            [JsonPropertyName("type")] public string Type { get; set; } = "";
            [JsonPropertyName("id")] public string Id { get; set; } = "";
            [JsonPropertyName("x")] public double X { get; set; }
            [JsonPropertyName("y")] public double Y { get; set; }
            [JsonPropertyName("rotation")] public double Rotation { get; set; }
            [JsonPropertyName("value")] public double? Value { get; set; }
            [JsonPropertyName("amplitude")] public double? Amplitude { get; set; }
            [JsonPropertyName("frequency")] public double? Frequency { get; set; }
            [JsonPropertyName("phase")] public double? Phase { get; set; }
            [JsonPropertyName("input_mode")] public string? InputMode { get; set; }
            [JsonPropertyName("re")] public double? Re { get; set; }
            [JsonPropertyName("im")] public double? Im { get; set; }
            [JsonPropertyName("probe_type")] public string? ProbeType { get; set; }
            [JsonPropertyName("target")] public string? Target { get; set; }
            [JsonPropertyName("value_kind")] public string? ValueKind { get; set; }

            // ── Bağımlı kaynak ("DEP"): türü, kazancı, kontrol elemanı. Eski dosyalarda yoktur (varsayılanlar geçerli). ──
            [JsonPropertyName("kind")] public string? Kind { get; set; }
            [JsonPropertyName("gain")] public double? Gain { get; set; }
            [JsonPropertyName("control")] public string? Control { get; set; }
            [JsonPropertyName("control_reversed")] public bool? ControlReversed { get; set; }

            // ── Transformatör ("T"): mod, oran, sarımlar, L1, L2, k, kuplaj girişi ──
            [JsonPropertyName("mode")] public string? Mode { get; set; }
            [JsonPropertyName("ratio")] public double? Ratio { get; set; }
            [JsonPropertyName("n1")] public double? N1 { get; set; }
            [JsonPropertyName("n2")] public double? N2 { get; set; }
            [JsonPropertyName("l1")] public double? L1 { get; set; }
            [JsonPropertyName("l2")] public double? L2 { get; set; }
            [JsonPropertyName("k")] public double? K { get; set; }
            [JsonPropertyName("coupling_input")] public string? CouplingInput { get; set; }
        }

        public sealed class WireData
        {
            [JsonPropertyName("from")] public string From { get; set; } = "";
            [JsonPropertyName("from_pin")] public int FromPin { get; set; }
            [JsonPropertyName("to")] public string To { get; set; } = "";
            [JsonPropertyName("to_pin")] public int ToPin { get; set; }
            [JsonPropertyName("points")]
            [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
            public List<double[]>? Points { get; set; }
            [JsonPropertyName("vertical_first")]
            [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)]
            public bool VerticalFirst { get; set; }
        }

        public sealed class AnalysisData
        {
            [JsonPropertyName("type")] public string? Type { get; set; }
            [JsonPropertyName("terminal_positive")] public string? TerminalPositive { get; set; }
            [JsonPropertyName("terminal_negative")] public string? TerminalNegative { get; set; }
            [JsonPropertyName("frequency")] public string? Frequency { get; set; }
            [JsonPropertyName("value_display")] public string? ValueDisplay { get; set; }
            [JsonPropertyName("power_factor_target")] public string? PowerFactorTarget { get; set; }
        }

        private static readonly JsonSerializerOptions JsonOptions = new()
        {
            WriteIndented = true,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        };

        // ═══════════════════════════════════════════════════════
        //  DEVRE → BELGE
        // ═══════════════════════════════════════════════════════

        public static CircuitDocument FromCircuit(IEnumerable<CircuitElement> elements, IEnumerable<Wire> wires)
        {
            var doc = new CircuitDocument();
            var list = elements.ToList();
            foreach (var e in list)
                doc.Elements.Add(ToData(e));

            foreach (var w in wires)
            {
                var a = w.StartPin.Owner;
                var b = w.EndPin.Owner;
                if (a == null || b == null)
                    continue;
                doc.Wires.Add(new WireData
                {
                    From = a.Id, FromPin = a.Pins.IndexOf(w.StartPin),
                    To = b.Id, ToPin = b.Pins.IndexOf(w.EndPin),
                    Points = w.Waypoints is { Count: > 0 }
                        ? w.Waypoints.Select(p => new[] { p.X, p.Y }).ToList()
                        : null,
                    VerticalFirst = w.LastLegVerticalFirst,
                });
            }
            return doc;
        }

        private static ElementData ToData(CircuitElement e)
        {
            var d = new ElementData { Id = e.Id, X = e.Position.X, Y = e.Position.Y, Rotation = e.Rotation };
            switch (e)
            {
                case DependentSource dep:
                    d.Type = "DEP"; d.Kind = dep.Kind.ToString(); d.Gain = dep.Gain;
                    d.Control = string.IsNullOrEmpty(dep.ControlElementId) ? null : dep.ControlElementId;
                    d.ControlReversed = dep.ControlReversed;
                    break;
                case AcVoltageSource ac:
                    d.Type = "VAC"; d.Amplitude = ac.Amplitude; d.Frequency = ac.Frequency; d.Phase = ac.Phase;
                    d.InputMode = ac.InputMode.ToString();
                    d.ValueKind = ac.ValueKind == AcValueKind.Rms ? "rms" : "peak";
                    break;
                case AcCurrentSource aci:
                    d.Type = "IAC"; d.Amplitude = aci.Amplitude; d.Frequency = aci.Frequency; d.Phase = aci.Phase;
                    d.InputMode = aci.InputMode.ToString();
                    d.ValueKind = aci.ValueKind == AcValueKind.Rms ? "rms" : "peak";
                    break;
                case ImpedanceElement z:
                    d.Type = "Z"; d.Re = z.Impedance.Real; d.Im = z.Impedance.Imaginary; d.InputMode = z.InputMode.ToString();
                    break;
                case TestProbe p:
                    d.Type = "PROBE"; d.ProbeType = p.Type.ToString();
                    d.Target = string.IsNullOrEmpty(p.TargetElementId) ? null : p.TargetElementId;
                    break;
                case GroundElement:
                    d.Type = "GND";
                    break;
                case JunctionElement:
                    d.Type = "J";
                    d.Rotation = 0;
                    break;
                case Resistor: d.Type = "R"; d.Value = e.Value; break;
                case Capacitor: d.Type = "C"; d.Value = e.Value; break;
                case Inductor: d.Type = "L"; d.Value = e.Value; break;
                case VoltageSource: d.Type = "V"; d.Value = e.Value; break;
                case CurrentSource: d.Type = "I"; d.Value = e.Value; break;
                case SwitchElement sw:
                    d.Type = "SWITCH";
                    d.Kind = sw.Mode == SwitchMode.NormallyClosed ? "NC" : "NO";
                    break;
                case SpdtSwitch:
                    d.Type = "SPDT";
                    break;
                case TransformerElement t:
                    d.Type = "T";
                    d.Mode = t.Mode == TransformerMode.Ideal ? "ideal" : "coupled";
                    d.Ratio = t.Ratio;
                    d.N1 = t.N1;
                    d.N2 = t.N2;
                    d.L1 = t.L1;
                    d.L2 = t.L2;
                    d.K = t.K;
                    d.CouplingInput = t.CouplingInput == CouplingInput.M ? "M" : "K";
                    break;
                default:
                    throw new NotSupportedException($"Kaydedilemeyen eleman türü: {e.GetType().Name}");
            }
            return d;
        }

        // ═══════════════════════════════════════════════════════
        //  BELGE → DEVRE
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Elemanları ve telleri yeniden kurar (görseller oluşturulmaz; MainWindow
        /// LoadExample ile tuvale ekler). Bozuk içerikte CircuitFileException.
        /// </summary>
        public ExampleCircuit ToCircuit(string name)
        {
            var circuit = new ExampleCircuit
            {
                Name = name,
                Description = "",
                SuggestedAnalysisType = Analysis?.Type is { Length: > 0 } t ? t : AnalysisTypes.Nodal,
                SuggestedTerminal = Analysis?.TerminalPositive,
                ProblemCode = ProblemCode,
            };

            var byId = new Dictionary<string, CircuitElement>(StringComparer.OrdinalIgnoreCase);
            foreach (var d in Elements)
            {
                if (string.IsNullOrWhiteSpace(d.Id))
                    throw new CircuitFileException("Dosyada kimliği olmayan bir eleman var.");
                if (byId.ContainsKey(d.Id))
                    throw new CircuitFileException($"Dosyada aynı kimlik iki kez geçiyor: {d.Id}");
                var e = FromData(d);
                e.Id = d.Id;
                e.Position = new Point(d.X, d.Y);
                e.Rotation = e is JunctionElement ? 0 : NormalizeRotation(d.Rotation);
                circuit.Elements.Add(e);
                byId[d.Id] = e;
            }

            foreach (var w in Wires)
            {
                var wire = new Wire(PinOf(byId, w.From, w.FromPin), PinOf(byId, w.To, w.ToPin))
                {
                    LastLegVerticalFirst = w.VerticalFirst,
                };
                if (w.Points != null)
                {
                    foreach (var pt in w.Points)
                    {
                        if (pt != null && pt.Length >= 2 && double.IsFinite(pt[0]) && double.IsFinite(pt[1]))
                        {
                            wire.Waypoints.Add(new Point(pt[0], pt[1]));
                        }
                    }
                }
                circuit.Wires.Add(wire);
            }

            foreach (var j in circuit.Elements.OfType<JunctionElement>())
            {
                var pin = j.Pins[0];
                j.AttachedWireCount = circuit.Wires.Count(w => w.StartPin == pin || w.EndPin == pin);
            }

            return circuit;
        }

        private static Pin PinOf(Dictionary<string, CircuitElement> byId, string id, int index)
        {
            if (!byId.TryGetValue(id ?? "", out var e))
                throw new CircuitFileException($"Tel, dosyada olmayan bir elemana bağlı: {id}");
            if (index < 0 || index >= e.Pins.Count)
                throw new CircuitFileException($"{id} elemanının {index + 1}. ucu yok.");
            return e.Pins[index];
        }

        private static double NormalizeRotation(double r)
        {
            double n = ((r % 360) + 360) % 360;
            return Math.Round(n / 90) * 90 % 360;
        }

        private static CircuitElement FromData(ElementData d)
        {
            double V(double? x, string what) => x is { } v && double.IsFinite(v)
                ? v
                : throw new CircuitFileException($"{d.Id}: {what} değeri eksik ya da geçersiz.");

            switch ((d.Type ?? "").ToUpperInvariant())
            {
                case "R": return new Resistor { Value = V(d.Value, "direnç") };
                case "C": return new Capacitor { Value = V(d.Value, "kapasite") };
                case "L": return new Inductor { Value = V(d.Value, "endüktans") };
                case "V": return new VoltageSource { Value = V(d.Value, "gerilim") };
                case "I": return new CurrentSource { Value = V(d.Value, "akım") };
                case "DEP":
                    {
                        var kind = ParseEnum(d.Kind, DependentSourceKind.Vcvs);
                        if (!Enum.IsDefined(kind))
                            kind = DependentSourceKind.Vcvs;
                        return new DependentSource(kind)
                        {
                            // Eksik kayıtta varsayılanlar: kazanç 1, kontrol seçilmemiş, yön düz
                            Gain = d.Gain is { } g && double.IsFinite(g) ? g : 1,
                            ControlElementId = d.Control ?? string.Empty,
                            ControlReversed = d.ControlReversed ?? false,
                        };
                    }
                case "GND": return new GroundElement();
                case "J": return new JunctionElement();
                case "VAC":
                    return new AcVoltageSource
                    {
                        Amplitude = V(d.Amplitude, "genlik"), Frequency = V(d.Frequency, "frekans"),
                        Phase = d.Phase ?? 0, InputMode = ParseEnum(d.InputMode, AcInputMode.Physical),
                        ValueKind = string.Equals(d.ValueKind, "rms", StringComparison.OrdinalIgnoreCase)
                            ? AcValueKind.Rms
                            : AcValueKind.Peak,
                    };
                case "IAC":
                    return new AcCurrentSource
                    {
                        Amplitude = V(d.Amplitude, "genlik"), Frequency = V(d.Frequency, "frekans"),
                        Phase = d.Phase ?? 0, InputMode = ParseEnum(d.InputMode, AcInputMode.Physical),
                        ValueKind = string.Equals(d.ValueKind, "rms", StringComparison.OrdinalIgnoreCase)
                            ? AcValueKind.Rms
                            : AcValueKind.Peak,
                    };
                case "Z":
                    return new ImpedanceElement
                    {
                        Impedance = ComplexValue.FromRectangular(V(d.Re, "empedans (gerçel)"), V(d.Im, "empedans (sanal)")),
                        InputMode = ParseEnum(d.InputMode, ImpedanceInputMode.Rectangular),
                    };
                case "PROBE":
                    return new TestProbe
                    {
                        Type = ParseEnum(d.ProbeType, Models.ProbeType.Voltage),
                        TargetElementId = d.Target ?? string.Empty,
                    };
                case "SWITCH":
                case "S":
                    {
                        bool isNc = string.Equals(d.Kind, "NC", StringComparison.OrdinalIgnoreCase) ||
                                    (d.Kind ?? "").Contains("Closed", StringComparison.OrdinalIgnoreCase);
                        return new SwitchElement(isNc ? SwitchMode.NormallyClosed : SwitchMode.NormallyOpen);
                    }
                case "SPDT":
                    return new SpdtSwitch();
                case "T":
                    {
                        var mode = string.Equals(d.Mode, "coupled", StringComparison.OrdinalIgnoreCase)
                            ? TransformerMode.Coupled
                            : TransformerMode.Ideal;
                        var couplingInput = string.Equals(d.CouplingInput, "M", StringComparison.OrdinalIgnoreCase)
                            ? CouplingInput.M
                            : CouplingInput.K;
                        return new TransformerElement
                        {
                            Mode = mode,
                            Ratio = d.Ratio is { } r && r > 0 ? r : 1.0,
                            N1 = d.N1,
                            N2 = d.N2,
                            L1 = d.L1 is { } l1 && l1 > 0 ? l1 : 0.1,
                            L2 = d.L2 is { } l2 && l2 > 0 ? l2 : 0.1,
                            K = d.K is { } k && k > 0 && k <= 1.0 ? k : 1.0,
                            CouplingInput = couplingInput,
                        };
                    }
                default:
                    throw new CircuitFileException($"Tanınmayan eleman türü: “{d.Type}”. Dosya daha yeni bir sürümle kaydedilmiş olabilir.");
            }
        }

        private static T ParseEnum<T>(string? s, T fallback) where T : struct, Enum
            => Enum.TryParse(s, ignoreCase: true, out T v) ? v : fallback;

        // ═══════════════════════════════════════════════════════
        //  JSON / DOSYA
        // ═══════════════════════════════════════════════════════

        public string ToJson() => JsonSerializer.Serialize(this, JsonOptions);

        public static CircuitDocument FromJson(string json)
        {
            CircuitDocument? doc;
            try
            {
                doc = JsonSerializer.Deserialize<CircuitDocument>(json);
            }
            catch (JsonException ex)
            {
                throw new CircuitFileException("Dosya okunamadı: bir devre dosyası değil ya da bozulmuş.", ex);
            }
            if (doc == null || !string.Equals(doc.Format, FormatName, StringComparison.Ordinal))
                throw new CircuitFileException("Bu dosya bir Devre Analizi dosyası değil.");
            if (doc.Version > CurrentVersion)
                throw new CircuitFileException(
                    "Bu dosya programın daha yeni bir sürümüyle kaydedilmiş. Programı güncelleyip yeniden deneyin.");
            doc.Elements ??= new();
            doc.Wires ??= new();
            return doc;
        }

        /// <summary>Dosyaya yazar: önce geçici dosyaya, sonra yerine taşır (yarım dosya kalmasın).</summary>
        public void Save(string path)
        {
            string tmp = path + ".tmp";
            try
            {
                File.WriteAllText(tmp, ToJson());
                File.Move(tmp, path, overwrite: true);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                try { File.Delete(tmp); } catch (Exception) { /* yoksa sorun değil */ }
                throw new CircuitFileException($"Dosya kaydedilemedi: {ex.Message}", ex);
            }
        }

        public static CircuitDocument Load(string path)
        {
            try
            {
                return FromJson(File.ReadAllText(path));
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                throw new CircuitFileException($"Dosya açılamadı: {ex.Message}", ex);
            }
        }

        /// <summary>Geri al için devrenin hafif özeti: aynı içerik → aynı metin.</summary>
        public static string Snapshot(IEnumerable<CircuitElement> elements, IEnumerable<Wire> wires)
            => JsonSerializer.Serialize(FromCircuit(elements, wires));

        public static string FormatDouble(double v) => v.ToString("R", CultureInfo.InvariantCulture);
    }

    /// <summary>
    /// Geri al / Yinele geçmişi: devrenin JSON anlık görüntüleri.
    /// Her "tamamlanmış" değişiklikten SONRA Record çağrılır (sürükleme bitince,
    /// eleman eklenince/silinince, değer değişince…). İlk Record başlangıç
    /// durumudur. En fazla Capacity adım saklanır.
    /// </summary>
    public sealed class UndoHistory
    {
        private readonly List<string> _states = new();
        private int _index = -1;

        public int Capacity { get; }

        public UndoHistory(int capacity = 100)
        {
            Capacity = Math.Max(2, capacity);
        }

        public bool CanUndo => _index > 0;
        public bool CanRedo => _index >= 0 && _index < _states.Count - 1;

        /// <summary>Şu anki durum (yoksa null).</summary>
        public string? Current => _index >= 0 ? _states[_index] : null;

        public event EventHandler? Changed;

        /// <summary>Yeni durumu kaydeder; öncekiyle aynıysa yok sayar. İleri geçmiş silinir.</summary>
        public void Record(string state)
        {
            if (_index >= 0 && _states[_index] == state)
                return;
            if (_index < _states.Count - 1)
                _states.RemoveRange(_index + 1, _states.Count - _index - 1);
            _states.Add(state);
            if (_states.Count > Capacity)
                _states.RemoveAt(0);
            _index = _states.Count - 1;
            Changed?.Invoke(this, EventArgs.Empty);
        }

        /// <summary>Bir önceki durum (geri yüklenecek JSON); yoksa null.</summary>
        public string? Undo()
        {
            if (!CanUndo)
                return null;
            _index--;
            Changed?.Invoke(this, EventArgs.Empty);
            return _states[_index];
        }

        public string? Redo()
        {
            if (!CanRedo)
                return null;
            _index++;
            Changed?.Invoke(this, EventArgs.Empty);
            return _states[_index];
        }

        /// <summary>Yeni devre / dosya açıldı: geçmişi bu durumla yeniden başlatır.</summary>
        public void Reset(string state)
        {
            _states.Clear();
            _states.Add(state);
            _index = 0;
            Changed?.Invoke(this, EventArgs.Empty);
        }
    }
}
