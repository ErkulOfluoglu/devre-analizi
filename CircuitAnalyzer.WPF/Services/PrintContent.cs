using System;
using System.Collections.Generic;
using System.Linq;
using CircuitAnalyzer.WPF.Views;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>Yazdırılan çözümde gösterilebilecek şekiller (ekrandaki kartların kâğıttaki karşılığı).</summary>
    internal enum PrintFigureKind
    {
        TransientPlot,
        PowerTriangle,
        ResonanceCurve,
    }

    internal sealed record PrintFigure(PrintFigureKind Kind, string Caption);

    /// <summary>Bir sonuç tablosunun sayfalanmış yeri: başlığın, ilk veri satırının ve son satırın sayfası (0'dan).</summary>
    internal readonly record struct TablePlacement(int Heading, int FirstRow, int LastRow);

    /// <summary>
    /// Yazdırılan çözümün içerik kararları (saf fonksiyonlar; çizim <see cref="SolutionPrinter"/>'da):
    /// tablo hücreleri ekrandaki "Sonuçlar" sekmesiyle aynı biçimde, hangi şekillerin ve
    /// hangi açıklamaların basılacağı, şekillerin anlatımda nereye gireceği.
    /// </summary>
    internal static class PrintContent
    {
        /// <summary>Sayıların önündeki ASCII '-' işaretini Unicode eksiye çevirir: "1∠-90° A" → "1∠−90° A".</summary>
        public static string UnicodeMinus(string text) => TurkishNumber.DisplayMinus(text);

        /// <summary>Düğüm gerilimleri tablosu: ekrandaki sırayla ve başlıklarla (üç fazda faz adlarıyla).</summary>
        public static List<(string Name, string Value)> NodeRows(IReadOnlyDictionary<string, NodeVoltageDto>? nodes)
        {
            if (nodes == null)
                return new();
            return nodes
                .OrderBy(kv => int.TryParse(kv.Key, out int n) ? n : int.MaxValue)
                .ThenBy(kv => kv.Key, StringComparer.Ordinal)
                .Select(kv => (AnalysisPanel.NodeTileTitle(kv.Key, kv.Value.Label),
                               UnicodeMinus(EngFormat.Format(kv.Value.Value, kv.Value.Unit ?? "V"))))
                .ToList();
        }

        /// <summary>Eleman akımları tablosu: ekrandaki gibi gerçek akış yönüyle (<see cref="CurrentDisplay"/>).</summary>
        public static List<(string Name, string Value, string Direction)> CurrentRows(IReadOnlyDictionary<string, ElementCurrentDto>? currents)
        {
            if (currents == null)
                return new();
            return currents
                .Select(kv =>
                {
                    var (value, direction) = CurrentDisplay.Format(kv.Key, kv.Value);
                    return ($"I_{kv.Key}", UnicodeMinus(value), string.IsNullOrEmpty(direction) ? "—" : direction);
                })
                .ToList();
        }

        /// <summary>Güç tablosu satırı: önekli birimlerle (9,874 kW), ekrandaki cos φ sütunu ve rol.</summary>
        public static string[] PowerRow(string key, ElementPowerDto el)
        {
            string pf = "—";
            if (el.PowerFactor.HasValue)
            {
                string num = TurkishNumber.Format(el.PowerFactor.Value, "0.000");
                pf = string.IsNullOrEmpty(el.PowerFactorType) ? num : $"{num} {el.PowerFactorType}";
            }
            string role = el.Role switch
            {
                "source" => "Kaynak",
                "load" => "Yük",
                _ => "—"
            };
            return new[]
            {
                string.IsNullOrEmpty(el.ElementId) ? key : el.ElementId,
                UnicodeMinus(EngFormat.Format(el.ActivePower, "W")),
                UnicodeMinus(EngFormat.Format(el.ReactivePower, "VAR")),
                UnicodeMinus(EngFormat.Format(el.ApparentPower, "VA")),
                pf,
                role
            };
        }

        /// <summary>
        /// Üç faz sonuçları: ekrandaki <see cref="AnalysisPanel.ThreePhaseSections"/> ile aynı
        /// başlıklar ve satırlar; değerler Unicode eksi ile.
        /// </summary>
        public static List<(string Header, List<(string Name, string Value)> Rows)> ThreePhaseTables(ThreePhaseResultDto? tp)
        {
            if (tp == null)
                return new();
            return AnalysisPanel.ThreePhaseSections(tp)
                .Select(sec => (sec.Header,
                                sec.Items.Select(it => (it.Title, UnicodeMinus(it.Value))).ToList()))
                .ToList();
        }

        /// <summary>Wattmetre okumaları tablosu: ekrandaki ad ve W birimiyle.</summary>
        public static List<(string Name, string Value)> WattmeterRows(IReadOnlyList<WattmeterResultDto>? wattmeters)
        {
            if (wattmeters == null)
                return new();
            return wattmeters
                .Select(w => (w.Id, UnicodeMinus(EngFormat.Format(w.P, "W"))))
                .ToList();
        }

        /// <summary>Ölçüm probları tablosu: ekrandaki sırayla, önekli birimle.</summary>
        public static List<(string Name, string Value)> ProbeRows(IReadOnlyList<ProbeResultDto>? probes)
        {
            if (probes == null)
                return new();
            return probes
                .Select(p => (p.ProbeId, UnicodeMinus(EngFormat.Format(p.Value, p.Unit ?? ""))))
                .ToList();
        }

        /// <summary>Başlık + tablo sayfaya bölünmüş mü (başlık ile son satır ayrı sayfalarda).</summary>
        public static bool TableIsSplit(TablePlacement p) => p.Heading != p.LastRow;

        /// <summary>
        /// Başlığın önüne konan sayfa sonu kalsın mı: tablo artık tek sayfada (sayfaya sığan tablo
        /// bölünmez, son satırı tek başına kalmaz) ya da sayfadan uzun tabloda başlık en azından
        /// ilk satırlarıyla buluştu. Aksi hâlde sayfa sonu boşuna yer harcar, kaldırılır.
        /// </summary>
        public static bool TableBreakHelps(TablePlacement before, TablePlacement after) =>
            !TableIsSplit(after)
            || (before.Heading != before.FirstRow && after.Heading == after.FirstRow);

        /// <summary>
        /// Sayfadan uzun bir tabloda son veri satırı yeni sayfanın başında tek başına (dul satır)
        /// kaldıysa, bir önceki satırın önüne sayfa sonu konarak son sayfaya en az 2 satır düşmesi
        /// sağlanır. Dönüş: <c>BreakPageBefore = true</c> yapılacak satırın <paramref name="rowPages"/>
        /// içindeki dizini (0 sütun başlığıdır; veri satırları 1'den başlar); tablo yalnızca tek bir
        /// sayfada yer alıyorsa (sayfaya sığıyorsa) veya son sayfada zaten ≥ 2 satır varsa −1.
        /// </summary>
        public static int WidowBreakRowIndex(IReadOnlyList<int> rowPages)
        {
            // En az 1 başlık + 3 veri satırı olmalı ve tablo gerçekten sayfaya bölünmüş olmalı
            // (ilk veri satırı ile son veri satırı farklı sayfalarda).
            if (rowPages == null || rowPages.Count < 4)
                return -1;
            int firstDataPage = rowPages[1];
            int lastPage = rowPages[^1];
            int prevPage = rowPages[^2];
            if (lastPage > firstDataPage && lastPage > prevPage)
                return rowPages.Count - 2;
            return -1;
        }

        private static TransientAnalysisDto? Transient(AnalysisResponseDto r) => r.Transient ?? r.Results?.Transient;

        /// <summary>
        /// Çözümün kâğıda girecek şekilleri, ekrandaki kartlarla aynı koşullarla
        /// (<see cref="AnalysisPanel"/>.ShowFullResults): geçici durum grafiği, güç üçgeni (güç ve üç faz),
        /// rezonans eğrisi. Veri yoksa şekil de açıklama da yoktur.
        /// </summary>
        public static List<PrintFigure> Figures(AnalysisResponseDto? response)
        {
            var list = new List<PrintFigure>();
            if (response == null)
                return list;

            if (Transient(response) is { Quantities.Count: > 0 } tr)
                list.Add(new PrintFigure(PrintFigureKind.TransientPlot, TransientPlotCaption(tr)));

            var power = PowerTriangleData(response);
            if (power != null)
                list.Add(new PrintFigure(PrintFigureKind.PowerTriangle, PowerTriangleCaption(power)));

            if ((response.Resonance ?? response.Results?.Resonance) is { } res)
                list.Add(new PrintFigure(PrintFigureKind.ResonanceCurve, ResonanceCaption(res)));

            return list;
        }

        /// <summary>Güç üçgeninin verisi: güç yönteminin özeti, yoksa üç faz toplamı (ekrandaki sırayla).</summary>
        public static PowerSummaryDto? PowerTriangleData(AnalysisResponseDto response)
        {
            var summary = response.PowerSummary ?? response.Results?.PowerSummary;
            if (summary != null)
                return summary;
            return response.ThreePhaseResult is { } tp ? PowerTriangleView.FromThreePhase(tp) : null;
        }

        /// <summary>Geçici durum grafiğinde çizilen büyüklükler: ekranın ilk açılışta gösterdiği ilk iki büyüklük.</summary>
        public static List<TransientQuantityDto> TransientPlotQuantities(TransientAnalysisDto data) =>
            data.Quantities.Take(2).ToList();

        public static string TransientPlotCaption(TransientAnalysisDto data)
        {
            string tau = data.Tau > 0 ? $" Zaman sabiti τ = {EngFormat.Format(data.Tau, "s")}." : "";
            return "Zaman grafiği: anahtar konum değiştirdikten sonra (t = 0) büyüklüklerin zamanla değişimi. " +
                   "Kesikli dikey çizgiler τ, 2τ … 5τ anlarını, kesikli yatay çizgi t → ∞ (yeni kararlı hâl) değerini gösterir." +
                   tau;
        }

        public static string PowerTriangleCaption(PowerSummaryDto data)
        {
            string text = "Güç üçgeni: P aktif güç, Q reaktif güç, S görünür güç, φ güç açısı. " +
                          PowerTriangleView.SummaryText(data);
            if (data.Compensation is { Applied: true } comp)
                text += "\n" + PowerTriangleLayout.CompensationCaption(data.P, comp.TargetPf);
            return UnicodeMinus(text);
        }

        public static string ResonanceCaption(ResonanceDto data)
        {
            bool parallel = string.Equals(data.Kind, "parallel", StringComparison.OrdinalIgnoreCase);
            return (parallel
                       ? "Rezonans eğrisi: paralel devrede empedansın frekansla değişimi. "
                       : "Rezonans eğrisi: seri devrede akımın frekansla değişimi. ") +
                   "Gölgeli bölge bant genişliğidir (f₁ … f₂); kesikli yatay çizgi tepe değerin 0,707 katıdır. " +
                   $"f₀ = {EngFormat.Format(data.F0, "Hz")}, Q = {TurkishNumber.Format(data.Q, "G4")}, BW = {EngFormat.Format(data.Bw, "Hz")}.";
        }

        /// <summary>
        /// Şeklin anlatımda gireceği yer: konusunu anlatan bölümün hemen ardı. Dönüş, ardına
        /// girilecek bölümün sırası; uygun bölüm yoksa −1 (şekil "Sonuçlar"ın hemen önüne girer).
        /// </summary>
        public static int AnchorSection(IReadOnlyList<string> sectionTitles, PrintFigureKind kind)
        {
            string[] anchors = kind switch
            {
                PrintFigureKind.TransientPlot => new[] { "Zamana Bağlı İfade" },
                PrintFigureKind.ResonanceCurve => new[] { "Bant Genişliği" },
                // Güç yöntemi "Güç Üçgeni", üç faz "Güç" bölümünde anlatır
                PrintFigureKind.PowerTriangle => new[] { "Güç Üçgeni", "Güç" },
                _ => Array.Empty<string>()
            };
            foreach (string anchor in anchors)
            {
                for (int i = 0; i < sectionTitles.Count; i++)
                {
                    if (string.Equals(sectionTitles[i]?.Trim(), anchor, StringComparison.Ordinal))
                        return i;
                }
            }
            return -1;
        }

        /// <summary>
        /// Geçici durumda "Sonuçlar" tablolarının üstündeki not: tablolar anahtardan çok sonraki
        /// kararlı hâli gösterir (çoğu kez hep 0); söylenmezse öğrenci şaşırıyor. Geçici durum değilse null.
        /// </summary>
        public static string? ResultsTablesNote(AnalysisResponseDto? response)
        {
            if (response == null || Transient(response) is not { } tr)
                return null;
            string note = "Bu tablolardaki değerler t → ∞ (yeni kararlı hâl) değerleridir: anahtar konum değiştirdikten çok sonra devrede kalan değerler.";
            if (tr.Quantities.Count > 0)
                note += " Zamanla değişim yukarıdaki zaman grafiğindedir.";
            return note;
        }
    }
}
