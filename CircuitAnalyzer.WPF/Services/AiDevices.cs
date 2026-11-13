using System.Collections.Generic;
using System.Linq;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>"Çalıştığı yer" listesindeki bir seçenek.</summary>
    public sealed class AiDeviceItem
    {
        public string Id { get; init; } = AiDeviceIds.Auto;
        /// <summary>Listede ve seçili kutuda görünen ad: "Otomatik (NPU)", "Ekran kartı"…</summary>
        public string Display { get; init; } = "";
        /// <summary>Seçeneğin altındaki açıklama ya da kullanılamama sebebi.</summary>
        public string Note { get; init; } = "";
        public bool Available { get; init; } = true;
    }

    /// <summary>
    /// Yapay zekânın çalıştığı yer (ekran kartı, işlemci, NPU) için arayüz kuralları.
    /// Asıl karar arka uçta (llm/devices.py); burada yalnızca gösterim var.
    /// </summary>
    public static class AiDevices
    {
        private static readonly Dictionary<string, string> Names = new()
        {
            [AiDeviceIds.Npu] = "NPU",
            [AiDeviceIds.Gpu] = "ekran kartı",
            [AiDeviceIds.Cpu] = "işlemci",
        };

        /// <summary>Durumdan liste; eski çözücü seçenek bildirmezse yalnız Otomatik.</summary>
        public static IReadOnlyList<AiDeviceItem> Items(LlmStatusDto? status)
        {
            var options = status?.DeviceOptions ?? new List<LlmDeviceOptionDto>();
            if (options.Count == 0)
                return new[] { new AiDeviceItem { Id = AiDeviceIds.Auto, Display = "Otomatik", Note = "En hızlısını seçer." } };
            string auto = Names.GetValueOrDefault(status!.AutoDevice, "işlemci");
            return options.Select(o => new AiDeviceItem
            {
                Id = o.Id,
                Display = o.Id == AiDeviceIds.Auto ? $"{o.Label} ({auto})" : o.Label,
                Note = o.Note,
                Available = o.Available,
            }).ToList();
        }

        /// <summary>Kayıtlı seçim bu bilgisayarda yoksa ya da kullanılamıyorsa Otomatik.</summary>
        public static AiDeviceItem Pick(IReadOnlyList<AiDeviceItem> items, string? saved)
            => items.FirstOrDefault(i => i.Id == saved && i.Available)
               ?? items.First(i => i.Id == AiDeviceIds.Auto);

        /// <summary>Otomatik seçiliyse gerçekte kullanılacak yer.</summary>
        public static string Effective(string selected, LlmStatusDto? status)
            => selected == AiDeviceIds.Auto ? (status?.AutoDevice ?? AiDeviceIds.Cpu) : selected;

        /// <summary>Cevap beklenirken gösterilen yazı.</summary>
        public static string BusyText(string effective) => effective switch
        {
            AiDeviceIds.Npu => "Düşünüyor… (NPU'da genelde yarım dakika; ilk soruda model yüklenir)",
            AiDeviceIds.Gpu => "Düşünüyor… (ekran kartında genelde yarım dakikanın altında)",
            _ => "Düşünüyor… (işlemcide 1 dakikayı bulabilir)",
        };

        /// <summary>"Şu an: …" satırı; yer bilinmiyorsa null (satır gizlenir).</summary>
        public static string? PlacementLine(string? placement)
            => string.IsNullOrWhiteSpace(placement) ? null : $"Şu an: {placement}";

        /// <summary>Cevabın geldiği yere göre "Şu an" bilgisi (sunucu yer bildirmediyse).</summary>
        public static string? PlacementFromAnswer(LlmAnswerDto answer)
            => !string.IsNullOrWhiteSpace(answer.Placement) ? answer.Placement
               : answer.Device switch
               {
                   AiDeviceIds.Npu => "NPU'da",
                   AiDeviceIds.Cpu => "işlemcide",
                   _ => null,
               };

        /// <summary>Ekran kartı seçilmiş ama model işlemcide kalmışsa uyarı rengi gösterilir.</summary>
        public static bool IsMismatch(string effective, string? placement)
            => effective == AiDeviceIds.Gpu && placement == "işlemcide";
    }
}
