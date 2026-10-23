using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using CircuitAnalyzer.WPF.Helpers;
using CircuitAnalyzer.WPF.Models;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Sistem panosu veya bellek içi test panosu için soyutlama arayüzü.
    /// </summary>
    public interface IClipboardService
    {
        /// <summary>Veriyi hem özel devre biçiminde hem de düz metin olarak panoya yazar.</summary>
        void SetCircuitData(string json);

        /// <summary>Panodan özel devre biçimini veya düz metni okur (yoksa null).</summary>
        string? GetCircuitData();

        /// <summary>Panoda geçerli bir devre verisi var mı?</summary>
        bool ContainsCircuit();
    }

    /// <summary>
    /// Windows sistem panosu (System.Windows.Clipboard) sarmalayıcısı.
    /// </summary>
    public sealed class SystemClipboardService : IClipboardService
    {
        public void SetCircuitData(string json)
        {
            if (string.IsNullOrEmpty(json))
                return;

            try
            {
                var dataObject = new DataObject();
                dataObject.SetData(CircuitClipboard.FormatName, json);
                dataObject.SetData(DataFormats.UnicodeText, json);
                dataObject.SetData(DataFormats.Text, json);
                Clipboard.SetDataObject(dataObject, copy: true);
            }
            catch
            {
                // Pano başka bir işlem tarafından kilitliyse sessizce geç
            }
        }

        public string? GetCircuitData()
        {
            try
            {
                if (Clipboard.ContainsData(CircuitClipboard.FormatName) &&
                    Clipboard.GetData(CircuitClipboard.FormatName) is string customJson &&
                    !string.IsNullOrWhiteSpace(customJson))
                {
                    return customJson;
                }

                if (Clipboard.ContainsText())
                {
                    string text = Clipboard.GetText();
                    if (CircuitClipboard.IsValidPayload(text))
                        return text;
                }
            }
            catch
            {
                // Pano erişim hatasında null dön
            }

            return null;
        }

        public bool ContainsCircuit()
        {
            return CircuitClipboard.IsValidPayload(GetCircuitData());
        }
    }

    /// <summary>
    /// Birim testler için bellek içi pano uygulaması (Windows panosuna dokunmaz).
    /// </summary>
    public sealed class InMemoryClipboardService : IClipboardService
    {
        private readonly Dictionary<string, object> _formats = new(StringComparer.Ordinal);

        /// <summary>Panodaki düz metin karşılığı.</summary>
        public string? PlainText { get; set; }

        /// <summary>İstenen biçimdeki ham veriyi döndürür.</summary>
        public object? GetData(string format)
            => _formats.TryGetValue(format, out var val) ? val : null;

        /// <summary>İstenen biçime ham veri yazar (yabancı/bozuk veri testleri için).</summary>
        public void SetData(string format, object value)
            => _formats[format] = value;

        /// <summary>Panoyu tamamen temizler.</summary>
        public void Clear()
        {
            _formats.Clear();
            PlainText = null;
        }

        public void SetCircuitData(string json)
        {
            _formats[CircuitClipboard.FormatName] = json;
            PlainText = json;
        }

        public string? GetCircuitData()
        {
            if (_formats.TryGetValue(CircuitClipboard.FormatName, out var custom) &&
                custom is string s &&
                !string.IsNullOrWhiteSpace(s))
            {
                return s;
            }

            return PlainText;
        }

        public bool ContainsCircuit()
        {
            return CircuitClipboard.IsValidPayload(GetCircuitData());
        }
    }

    /// <summary>
    /// Yapıştırma işleminin sonucu: yeni kimlikli ve kaydırılmış elemanlar ile iç teller.
    /// </summary>
    public sealed record PasteResult(List<CircuitElement> Elements, List<Wire> Wires);

    /// <summary>
    /// Devre elemanlarını ve iç tellerini kopyalama / yapıştırma servisi.
    /// CircuitDocument JSON biçimini yeniden kullanır; WPF görsel nesnelerine bağımlı değildir.
    /// </summary>
    public static class CircuitClipboard
    {
        /// <summary>Windows panosundaki özel veri biçimi adı.</summary>
        public const string FormatName = "DevreAnalizi.Circuit";

        /// <summary>
        /// Verilen elemanları ve YALNIZCA her iki ucu da bu elemanlar arasında olan telleri
        /// CircuitDocument JSON metnine dönüştürür.
        /// </summary>
        public static string Copy(IEnumerable<CircuitElement> elements, IEnumerable<Wire>? wires = null)
        {
            var elementList = (elements ?? Enumerable.Empty<CircuitElement>())
                .Where(e => e != null)
                .Distinct()
                .ToList();
            var elementSet = new HashSet<CircuitElement>(elementList);
            var wireList = (wires ?? Enumerable.Empty<Wire>())
                .Where(w => w?.StartPin?.Owner != null && w.EndPin?.Owner != null)
                .ToList();

            // Kopyalanan elemanlar arasındaki tellerin geçtiği bağlantı noktalarını (JunctionElement)
            // otomatik olarak dahil et ki T-bağlantıları kopmasın.
            bool addedJunction;
            do
            {
                addedJunction = false;
                var candidateJunctions = wireList
                    .SelectMany(w => new[] { w.StartPin.Owner!, w.EndPin.Owner! })
                    .OfType<JunctionElement>()
                    .Distinct()
                    .Where(j => !elementSet.Contains(j))
                    .ToList();

                foreach (var j in candidateJunctions)
                {
                    int connectedSelectedCount = wireList.Count(w =>
                        (w.StartPin.Owner == j && elementSet.Contains(w.EndPin.Owner!)) ||
                        (w.EndPin.Owner == j && elementSet.Contains(w.StartPin.Owner!)));

                    if (connectedSelectedCount >= 2)
                    {
                        elementSet.Add(j);
                        elementList.Add(j);
                        addedJunction = true;
                    }
                }
            } while (addedJunction);

            var internalWires = wireList
                .Where(w => elementSet.Contains(w.StartPin.Owner!) &&
                            elementSet.Contains(w.EndPin.Owner!))
                .ToList();

            var doc = CircuitDocument.FromCircuit(elementList, internalWires);
            return doc.ToJson();
        }

        /// <summary>Seçili elemanları ve iç tellerini verilen pano servisine kopyalar.</summary>
        public static string CopyToClipboard(
            IClipboardService clipboard,
            IEnumerable<CircuitElement> elements,
            IEnumerable<Wire>? wires = null)
        {
            if (clipboard == null)
                throw new ArgumentNullException(nameof(clipboard));

            var list = (elements ?? Enumerable.Empty<CircuitElement>()).Where(e => e != null).ToList();
            if (list.Count == 0)
                return string.Empty;

            string payload = Copy(list, wires);
            clipboard.SetCircuitData(payload);
            return payload;
        }

        /// <summary>
        /// Verilen JSON metninin geçerli ve en az bir eleman içeren bir devre panosu verisi olup olmadığını denetler.
        /// </summary>
        public static bool IsValidPayload(string? payload)
        {
            if (string.IsNullOrWhiteSpace(payload))
                return false;

            try
            {
                var doc = CircuitDocument.FromJson(payload);
                return doc.Elements.Count > 0;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Pano verisindeki elemanların sol-üst köşesini (minX, minY) bulur.
        /// </summary>
        public static bool TryGetTopLeft(string? payload, out Point topLeft)
        {
            topLeft = default;
            if (string.IsNullOrWhiteSpace(payload))
                return false;

            try
            {
                var doc = CircuitDocument.FromJson(payload);
                if (doc.Elements.Count == 0)
                    return false;

                double minX = doc.Elements.Min(e => e.X);
                double minY = doc.Elements.Min(e => e.Y);
                topLeft = new Point(minX, minY);
                return true;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Pano verisini çözer; elemanlara mevcut ve yeni yapıştırılan kimliklerle çakışmayan
        /// yeni kimlikler verir, konumları offset kadar kaydırıp GridHelper.GridSize'a oturtur
        /// ve kopyalanan hedefe bakan probların TargetElementId değerini yeni kimliğe günceller.
        /// Geçersiz veya boş veride boş sonuç döner.
        /// </summary>
        public static PasteResult Paste(string? payload, IEnumerable<string>? existingIds, Point offset)
        {
            if (string.IsNullOrWhiteSpace(payload))
                return new PasteResult(new List<CircuitElement>(), new List<Wire>());

            ExampleCircuit restored;
            try
            {
                var doc = CircuitDocument.FromJson(payload);
                if (doc.Elements.Count == 0)
                    return new PasteResult(new List<CircuitElement>(), new List<Wire>());

                restored = doc.ToCircuit("Pano");
            }
            catch
            {
                return new PasteResult(new List<CircuitElement>(), new List<Wire>());
            }

            var usedIds = new List<string>();
            if (existingIds != null)
            {
                foreach (var id in existingIds)
                {
                    if (!string.IsNullOrWhiteSpace(id))
                        usedIds.Add(id);
                }
            }

            var oldToNewId = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

            foreach (var element in restored.Elements)
            {
                string oldId = element.Id;
                string prefix = GetPrefixForElement(element);
                int maxNum = GetMaxNumberForPrefix(usedIds, prefix);
                string newId = $"{prefix}{maxNum + 1}";

                element.Id = newId;
                usedIds.Add(newId);

                if (!string.IsNullOrEmpty(oldId))
                {
                    oldToNewId[oldId] = newId;
                }

                element.Position = GridHelper.Snap(new Point(
                    element.Position.X + offset.X,
                    element.Position.Y + offset.Y));
            }

            // Akım probunun hedef elemanı da kopyalananlar arasındaysa yeni kimliğe eşle;
            // değilse eski hedef kimliğini olduğu gibi koru.
            foreach (var probe in restored.Elements.OfType<TestProbe>())
            {
                if (!string.IsNullOrEmpty(probe.TargetElementId) &&
                    oldToNewId.TryGetValue(probe.TargetElementId, out string? remappedId))
                {
                    probe.TargetElementId = remappedId;
                }
            }

            return new PasteResult(restored.Elements, restored.Wires);
        }

        /// <summary>Vector ofset ile yapıştırma aşırı yüklemesi.</summary>
        public static PasteResult Paste(string? payload, IEnumerable<string>? existingIds, Vector offset)
            => Paste(payload, existingIds, new Point(offset.X, offset.Y));

        /// <summary>Verilen pano servisinden okuyarak yapıştırma yapar.</summary>
        public static PasteResult PasteFromClipboard(
            IClipboardService clipboard,
            IEnumerable<string>? existingIds,
            Point offset)
        {
            if (clipboard == null)
                throw new ArgumentNullException(nameof(clipboard));

            string? payload = clipboard.GetCircuitData();
            return Paste(payload, existingIds, offset);
        }

        /// <summary>Eleman türüne karşılık gelen kimlik ön ekini döndürür.</summary>
        public static string GetPrefixForElement(CircuitElement element) => element switch
        {
            Resistor => "R",
            Capacitor => "C",
            Inductor => "L",
            ImpedanceElement => "Z",
            AcVoltageSource => "VAC",
            VoltageSource => "V",
            AcCurrentSource => "IAC",
            CurrentSource => "I",
            GroundElement => "GND",
            TestProbe => "VP",
            JunctionElement => "J",
            _ => "X",
        };

        /// <summary>
        /// Verilen kimlik listesindeki belirli bir ön ek (R, C, L, Z, V, VAC, I, IAC, GND, VP)
        /// için en büyük numarayı bulur. Örneğin "VAC1" kimliği "V" ön ekiyle eşleşmez.
        /// </summary>
        public static int GetMaxNumberForPrefix(IEnumerable<string> ids, string prefix)
        {
            int max = 0;
            foreach (var id in ids)
            {
                if (string.IsNullOrEmpty(id) || id.Length <= prefix.Length)
                    continue;

                if (!id.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                    continue;

                ReadOnlySpan<char> suffix = id.AsSpan(prefix.Length);
                if (int.TryParse(suffix, NumberStyles.None, CultureInfo.InvariantCulture, out int num) && num > max)
                {
                    max = num;
                }
            }
            return max;
        }
    }
}
