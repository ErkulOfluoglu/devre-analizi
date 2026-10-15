using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace CircuitAnalyzer.WPF.Services
{
    // ═══════════════════════════════════════════════════════
    //  İSTEK (C# → Python)  —  models/request.py ile birebir
    // ═══════════════════════════════════════════════════════

    public static class AnalysisModes
    {
        public const string Dc = "DC";
        public const string AcPhasor = "AC_PHASOR";
    }

    public static class AnalysisTypes
    {
        public const string Nodal = "NODAL";
        public const string Thevenin = "THEVENIN";
        public const string Norton = "NORTON";
        public const string Mesh = "MESH";
        public const string Superposition = "SUPERPOSITION";
    }

    public sealed class TerminalsDto
    {
        [JsonPropertyName("node_positive")] public string NodePositive { get; set; } = "";
        [JsonPropertyName("node_negative")] public string NodeNegative { get; set; } = "0";
    }

    public sealed class AnalysisRequestDto
    {
        [JsonPropertyName("netlist")] public string Netlist { get; set; } = "";
        [JsonPropertyName("mode")] public string Mode { get; set; } = AnalysisModes.Dc;
        [JsonPropertyName("frequency")] public double? Frequency { get; set; }
        [JsonPropertyName("analysis_type")] public string AnalysisType { get; set; } = AnalysisTypes.Nodal;
        [JsonPropertyName("thevenin_terminals")] public TerminalsDto? TheveninTerminals { get; set; }
    }

    // ═══════════════════════════════════════════════════════
    //  YANIT (Python → C#)  —  models/response.py ile birebir
    // ═══════════════════════════════════════════════════════

    public sealed class ComplexNumberDto
    {
        [JsonPropertyName("real")] public double Real { get; set; }
        [JsonPropertyName("imaginary")] public double Imaginary { get; set; }
        [JsonPropertyName("magnitude")] public double Magnitude { get; set; }
        [JsonPropertyName("phase_degrees")] public double PhaseDegrees { get; set; }
        [JsonPropertyName("rectangular_str")] public string RectangularStr { get; set; } = "";
        [JsonPropertyName("polar_str")] public string PolarStr { get; set; } = "";
    }

    /// <summary>
    /// Python'daki Union[float, ComplexNumber] alanı.
    /// DC sonuçları düz sayı, AC sonuçları karmaşık sayı nesnesi olarak gelir.
    /// </summary>
    [JsonConverter(typeof(ResultValueConverter))]
    public sealed class ResultValue
    {
        public double Real { get; init; }
        public double Imaginary { get; init; }
        public bool IsComplex { get; init; }

        /// <summary>Python'un ürettiği gösterimler (yalnızca AC'de dolu).</summary>
        public string? RectangularStr { get; init; }
        public string? PolarStr { get; init; }

        public double Magnitude => Math.Sqrt(Real * Real + Imaginary * Imaginary);

        public double PhaseDegrees =>
            Magnitude < 1e-15 ? 0 : Math.Atan2(Imaginary, Real) * 180.0 / Math.PI;

        public static ResultValue FromReal(double value) => new() { Real = value };

        public static ResultValue FromComplex(ComplexNumberDto c) => new()
        {
            Real = c.Real,
            Imaginary = c.Imaginary,
            IsComplex = true,
            RectangularStr = c.RectangularStr,
            PolarStr = c.PolarStr,
        };
    }

    public sealed class ResultValueConverter : JsonConverter<ResultValue>
    {
        public override ResultValue Read(
            ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
        {
            switch (reader.TokenType)
            {
                case JsonTokenType.Number:
                    return ResultValue.FromReal(reader.GetDouble());
                case JsonTokenType.StartObject:
                    var c = JsonSerializer.Deserialize<ComplexNumberDto>(ref reader, options)
                            ?? throw new JsonException("Boş karmaşık sayı nesnesi");
                    return ResultValue.FromComplex(c);
                default:
                    throw new JsonException(
                        $"Beklenmeyen değer tipi: {reader.TokenType} (sayı veya karmaşık sayı bekleniyordu)");
            }
        }

        public override void Write(
            Utf8JsonWriter writer, ResultValue value, JsonSerializerOptions options)
        {
            if (!value.IsComplex)
            {
                writer.WriteNumberValue(value.Real);
                return;
            }
            writer.WriteStartObject();
            writer.WriteNumber("real", value.Real);
            writer.WriteNumber("imaginary", value.Imaginary);
            writer.WriteEndObject();
        }
    }

    public sealed class NodeVoltageDto
    {
        [JsonPropertyName("value")] public ResultValue Value { get; set; } = ResultValue.FromReal(0);
        [JsonPropertyName("unit")] public string Unit { get; set; } = "V";
        [JsonPropertyName("label")] public string? Label { get; set; }
    }

    public sealed class ElementCurrentDto
    {
        [JsonPropertyName("value")] public ResultValue Value { get; set; } = ResultValue.FromReal(0);
        [JsonPropertyName("unit")] public string Unit { get; set; } = "A";
        /// <summary>Akım yönü, ör: "1→2" (eleman içinden, + pinden − pine).</summary>
        [JsonPropertyName("direction")] public string Direction { get; set; } = "";
    }

    public sealed class ProbeResultDto
    {
        [JsonPropertyName("probe_id")] public string ProbeId { get; set; } = "";
        [JsonPropertyName("type")] public string Type { get; set; } = "";
        [JsonPropertyName("value")] public ResultValue Value { get; set; } = ResultValue.FromReal(0);
        [JsonPropertyName("unit")] public string Unit { get; set; } = "";
    }

    public sealed class TheveninDto
    {
        [JsonPropertyName("vth")] public ComplexNumberDto Vth { get; set; } = new();
        [JsonPropertyName("zth")] public ComplexNumberDto Zth { get; set; } = new();
        [JsonPropertyName("node_positive")] public string NodePositive { get; set; } = "";
        [JsonPropertyName("node_negative")] public string NodeNegative { get; set; } = "";
    }

    public sealed class NortonDto
    {
        [JsonPropertyName("i_n")] public ComplexNumberDto In { get; set; } = new();
        /// <summary>null → Zn sonsuz (ideal akım kaynağı).</summary>
        [JsonPropertyName("z_n")] public ComplexNumberDto? Zn { get; set; }
        [JsonPropertyName("y_n")] public ComplexNumberDto Yn { get; set; } = new();
        [JsonPropertyName("node_positive")] public string NodePositive { get; set; } = "";
        [JsonPropertyName("node_negative")] public string NodeNegative { get; set; } = "";
    }

    public sealed class ReductionDto
    {
        /// <summary>"series" veya "parallel".</summary>
        [JsonPropertyName("type")] public string Type { get; set; } = "";
        [JsonPropertyName("elements")] public List<string> Elements { get; set; } = new();
        [JsonPropertyName("result_name")] public string ResultName { get; set; } = "";
        [JsonPropertyName("nodes")] public List<string> Nodes { get; set; } = new();
        [JsonPropertyName("formula")] public string Formula { get; set; } = "";
        [JsonPropertyName("latex")] public string Latex { get; set; } = "";
        [JsonPropertyName("impedance")] public ComplexNumberDto? Impedance { get; set; }
        [JsonPropertyName("original_elements")] public List<string> OriginalElements { get; set; } = new();
    }

    public sealed class ElementPowerDto
    {
        [JsonPropertyName("element_id")] public string ElementId { get; set; } = "";
        /// <summary>"source" veya "load".</summary>
        [JsonPropertyName("role")] public string Role { get; set; } = "";
        [JsonPropertyName("complex_power")] public ComplexNumberDto ComplexPower { get; set; } = new();
        [JsonPropertyName("active_power")] public double ActivePower { get; set; }
        [JsonPropertyName("reactive_power")] public double ReactivePower { get; set; }
        [JsonPropertyName("apparent_power")] public double ApparentPower { get; set; }
        [JsonPropertyName("power_factor")] public double? PowerFactor { get; set; }
        /// <summary>"geri", "ileri", "birim" veya null.</summary>
        [JsonPropertyName("power_factor_type")] public string? PowerFactorType { get; set; }
    }

    public sealed class PowerAnalysisDto
    {
        [JsonPropertyName("convention")] public string Convention { get; set; } = "";
        [JsonPropertyName("elements")] public Dictionary<string, ElementPowerDto> Elements { get; set; } = new();
        [JsonPropertyName("total_supplied")] public ComplexNumberDto TotalSupplied { get; set; } = new();
        [JsonPropertyName("total_absorbed")] public ComplexNumberDto TotalAbsorbed { get; set; } = new();
        [JsonPropertyName("power_factor")] public double? PowerFactor { get; set; }
        [JsonPropertyName("power_factor_type")] public string? PowerFactorType { get; set; }
        [JsonPropertyName("balance_error")] public double BalanceError { get; set; }
    }

    public sealed class SolutionStepDto
    {
        [JsonPropertyName("step_number")] public int StepNumber { get; set; }
        [JsonPropertyName("title")] public string Title { get; set; } = "";
        [JsonPropertyName("description")] public string Description { get; set; } = "";
        [JsonPropertyName("equations")] public List<string> Equations { get; set; } = new();
        [JsonPropertyName("latex_formula")] public string? LatexFormula { get; set; }
        [JsonPropertyName("result_snapshot")] public JsonElement? ResultSnapshot { get; set; }
    }

    public sealed class ExplanationBlockDto
    {
        [JsonPropertyName("kind")] public string Kind { get; set; } = "";
        [JsonPropertyName("text")] public string Text { get; set; } = "";
    }

    public sealed class ExplanationSectionDto
    {
        [JsonPropertyName("title")] public string Title { get; set; } = "";
        [JsonPropertyName("blocks")] public List<ExplanationBlockDto> Blocks { get; set; } = new();
    }

    public sealed class AnalysisResultsDto
    {
        [JsonPropertyName("node_voltages")] public Dictionary<string, NodeVoltageDto> NodeVoltages { get; set; } = new();
        [JsonPropertyName("element_currents")] public Dictionary<string, ElementCurrentDto> ElementCurrents { get; set; } = new();
        [JsonPropertyName("probe_results")] public List<ProbeResultDto> ProbeResults { get; set; } = new();
        [JsonPropertyName("thevenin")] public TheveninDto? Thevenin { get; set; }
        [JsonPropertyName("norton")] public NortonDto? Norton { get; set; }
        [JsonPropertyName("reductions")] public List<ReductionDto> Reductions { get; set; } = new();
        [JsonPropertyName("power")] public PowerAnalysisDto? Power { get; set; }
        [JsonPropertyName("explanation")] public List<ExplanationSectionDto> Explanation { get; set; } = new();
        /// <summary>Alıştırma modu soruları (öğrenci önce kendisi çözer).</summary>
        [JsonPropertyName("practice")] public List<PracticeQuestionDto> Practice { get; set; } = new();
    }

    // ═══════════════════════════════════════════════════════
    //  ALIŞTIRMA MODU
    // ═══════════════════════════════════════════════════════

    public sealed class PracticeAlternativeDto
    {
        [JsonPropertyName("value")] public ComplexNumberDto Value { get; set; } = new();
        [JsonPropertyName("message")] public string Message { get; set; } = "";
    }

    /// <summary>
    /// Öğrenciye sorulan tek büyüklük. Kontrol için /practice/check'e AYNEN
    /// geri gönderilir (sunucu durum tutmaz) — bu yüzden tüm alanlar burada.
    /// Expected, öğrenci "Çözümü Göster" diyene kadar ekranda gösterilmez.
    /// </summary>
    public sealed class PracticeQuestionDto
    {
        [JsonPropertyName("id")] public string Id { get; set; } = "";
        /// <summary>Sembol: "V₂", "I_R1", "I₁", "Vth".</summary>
        [JsonPropertyName("label")] public string Label { get; set; } = "";
        [JsonPropertyName("description")] public string Description { get; set; } = "";
        /// <summary>"V", "A", "Ω" veya "W".</summary>
        [JsonPropertyName("unit")] public string Unit { get; set; } = "";
        /// <summary>"main" (yöntemin asıl bilinmeyenleri) veya "extra" (ek sorular).</summary>
        [JsonPropertyName("group")] public string Group { get; set; } = "main";
        /// <summary>True → cevap fazör (büyüklük∠açı) olmalı.</summary>
        [JsonPropertyName("is_ac")] public bool IsAc { get; set; }
        [JsonPropertyName("frequency")] public double? Frequency { get; set; }
        [JsonPropertyName("expected")] public ComplexNumberDto Expected { get; set; } = new();
        [JsonPropertyName("scale")] public double Scale { get; set; }
        [JsonPropertyName("hint")] public string Hint { get; set; } = "";
        [JsonPropertyName("sign_hint")] public string SignHint { get; set; } = "";
        [JsonPropertyName("alternatives")] public List<PracticeAlternativeDto> Alternatives { get; set; } = new();
    }

    public sealed class AnswerCheckItemDto
    {
        [JsonPropertyName("question")] public PracticeQuestionDto Question { get; set; } = new();
        [JsonPropertyName("answer")] public string Answer { get; set; } = "";
    }

    public sealed class AnswerCheckRequestDto
    {
        [JsonPropertyName("items")] public List<AnswerCheckItemDto> Items { get; set; } = new();
    }

    public static class AnswerStatuses
    {
        public const string Correct = "correct";   // ±%1
        public const string Close = "close";       // ±%5 (yuvarlama)
        public const string Partial = "partial";   // ör. büyüklük doğru açı yok, birim yanlış
        public const string Wrong = "wrong";
        public const string Invalid = "invalid";   // okunamadı
        public const string Empty = "empty";
    }

    public sealed class AnswerVerdictDto
    {
        [JsonPropertyName("question_id")] public string QuestionId { get; set; } = "";
        /// <summary>AnswerStatuses sabitlerinden biri.</summary>
        [JsonPropertyName("status")] public string Status { get; set; } = "";
        /// <summary>Öğrenciye gösterilecek Türkçe geri bildirim (doğru cevabı söylemez).</summary>
        [JsonPropertyName("message")] public string Message { get; set; } = "";
        /// <summary>Cevabın nasıl okunduğu, ör. "4 mA".</summary>
        [JsonPropertyName("understood_as")] public string? UnderstoodAs { get; set; }
    }

    public sealed class AnswerCheckResponseDto
    {
        [JsonPropertyName("verdicts")] public List<AnswerVerdictDto> Verdicts { get; set; } = new();
        [JsonPropertyName("correct_count")] public int CorrectCount { get; set; }
        [JsonPropertyName("total")] public int Total { get; set; }
    }

    // ═══════════════════════════════════════════════════════
    //  YEREL YAPAY ZEKÂ (OLLAMA) — isteğe bağlı
    // ═══════════════════════════════════════════════════════

    public sealed class LlmStatusDto
    {
        [JsonPropertyName("available")] public bool Available { get; set; }
        [JsonPropertyName("version")] public string? Version { get; set; }
        [JsonPropertyName("models")] public List<string> Models { get; set; } = new();
        [JsonPropertyName("recommended_model")] public string RecommendedModel { get; set; } = "";
        /// <summary>Model seçilmezse kullanılacak model (kurulu model yoksa null).</summary>
        [JsonPropertyName("selected_model")] public string? SelectedModel { get; set; }
        /// <summary>Öğrenciye gösterilecek Türkçe durum / kurulum bilgisi.</summary>
        [JsonPropertyName("message")] public string Message { get; set; } = "";
        /// <summary>Ollama programı kurulu mu (çalışmıyor olsa bile) — "Başlat" düğmesi için.</summary>
        [JsonPropertyName("ollama_installed")] public bool OllamaInstalled { get; set; }
        [JsonPropertyName("ram_gb")] public double? RamGb { get; set; }
        [JsonPropertyName("free_disk_gb")] public double? FreeDiskGb { get; set; }
        /// <summary>Belleğe göre uygunluk: LlmFits sabitleri.</summary>
        [JsonPropertyName("fit")] public string Fit { get; set; } = LlmFits.Unknown;
        /// <summary>Önerilen modelin yaklaşık indirme boyutu (GB).</summary>
        [JsonPropertyName("approx_size_gb")] public double ApproxSizeGb { get; set; }
        /// <summary>Belleğe göre Türkçe tavsiye cümlesi.</summary>
        [JsonPropertyName("advice_message")] public string AdviceMessage { get; set; } = "";
    }

    public static class LlmFits
    {
        public const string Good = "good";       // ≥ 16 GB: büyük model rahat
        public const string Ok = "ok";           // 8–16 GB: küçük model
        public const string Low = "low";         // < 8 GB: önerilmez
        public const string Unknown = "unknown";
    }

    public static class LlmPullStates
    {
        public const string Idle = "idle";
        public const string Running = "running";
        public const string Done = "done";
        public const string Error = "error";
        public const string Cancelled = "cancelled";
    }

    /// <summary>GET/POST /llm/pull — model indirme durumu.</summary>
    public sealed class LlmPullStatusDto
    {
        [JsonPropertyName("model")] public string? Model { get; set; }
        /// <summary>LlmPullStates sabitlerinden biri.</summary>
        [JsonPropertyName("state")] public string State { get; set; } = LlmPullStates.Idle;
        [JsonPropertyName("completed_bytes")] public long CompletedBytes { get; set; }
        [JsonPropertyName("total_bytes")] public long TotalBytes { get; set; }
        [JsonPropertyName("percent")] public double? Percent { get; set; }
        [JsonPropertyName("speed_bps")] public double SpeedBps { get; set; }
        [JsonPropertyName("eta_seconds")] public double? EtaSeconds { get; set; }
        /// <summary>Türkçe durum mesajı ("İndiriliyor…", hata açıklaması…).</summary>
        [JsonPropertyName("message")] public string Message { get; set; } = "";
    }

    public sealed class LlmPullRequestDto
    {
        /// <summary>Boşsa sunucu belleğe göre önerilen modeli indirir.</summary>
        [JsonPropertyName("model")] public string? Model { get; set; }
    }

    public sealed class LlmActionResultDto
    {
        [JsonPropertyName("ok")] public bool Ok { get; set; }
        [JsonPropertyName("message")] public string Message { get; set; } = "";
    }

    public static class ChatRoles
    {
        public const string User = "user";
        public const string Assistant = "assistant";
    }

    public sealed class ChatTurnDto
    {
        [JsonPropertyName("role")] public string Role { get; set; } = ChatRoles.User;
        [JsonPropertyName("content")] public string Content { get; set; } = "";
    }

    /// <summary>
    /// POST /llm/ask — devre bilgileri /analyze ile aynı; sunucu devreyi yeniden
    /// çözer (istemci sonuç göndermez, model yalnızca doğrulanmış anlatımı görür).
    /// </summary>
    public sealed class LlmAskRequestDto
    {
        [JsonPropertyName("netlist")] public string Netlist { get; set; } = "";
        [JsonPropertyName("mode")] public string Mode { get; set; } = AnalysisModes.Dc;
        [JsonPropertyName("frequency")] public double? Frequency { get; set; }
        [JsonPropertyName("analysis_type")] public string AnalysisType { get; set; } = AnalysisTypes.Nodal;
        [JsonPropertyName("thevenin_terminals")] public TerminalsDto? TheveninTerminals { get; set; }
        [JsonPropertyName("question")] public string Question { get; set; } = "";
        /// <summary>Boşsa sunucu seçer (önerilen ya da ilk kurulu model).</summary>
        [JsonPropertyName("model")] public string? Model { get; set; }
        /// <summary>Önceki soru-cevaplar, en eski önce (sunucu son 6'sını kullanır).</summary>
        [JsonPropertyName("history")] public List<ChatTurnDto> History { get; set; } = new();
        /// <summary>Alıştırma sürüyor mu: true → model sonuçları görmez, cevap sayıları gizlenir.</summary>
        [JsonPropertyName("practice")] public bool Practice { get; set; }
        [JsonPropertyName("practice_questions")] public List<PracticeQuestionDto> PracticeQuestions { get; set; } = new();

        /// <summary>Çözüm isteğinin devre bilgilerini kopyalar.</summary>
        public static LlmAskRequestDto From(AnalysisRequestDto analysis, string question) => new()
        {
            Netlist = analysis.Netlist,
            Mode = analysis.Mode,
            Frequency = analysis.Frequency,
            AnalysisType = analysis.AnalysisType,
            TheveninTerminals = analysis.TheveninTerminals,
            Question = question,
        };
    }

    public static class LlmNumberStatuses
    {
        public const string Verified = "verified";       // çözümle uyuşuyor
        public const string Unverified = "unverified";   // doğrulanamadı
        public const string Redacted = "redacted";       // alıştırmada gizlendi (■■)
    }

    public sealed class LlmNumberCheckDto
    {
        [JsonPropertyName("text")] public string Text { get; set; } = "";
        [JsonPropertyName("status")] public string Status { get; set; } = "";
    }

    public sealed class LlmAnswerDto
    {
        [JsonPropertyName("answer")] public string Answer { get; set; } = "";
        [JsonPropertyName("model")] public string Model { get; set; } = "";
        [JsonPropertyName("numbers")] public List<LlmNumberCheckDto> Numbers { get; set; } = new();
        /// <summary>Doğrulanamayan / gizlenen sayılar için Türkçe uyarı (yoksa null).</summary>
        [JsonPropertyName("note")] public string? Note { get; set; }
    }

    public sealed class AnalysisResponseDto
    {
        /// <summary>"success" veya "warning".</summary>
        [JsonPropertyName("status")] public string Status { get; set; } = "";
        [JsonPropertyName("mode")] public string Mode { get; set; } = "";
        [JsonPropertyName("analysis_type")] public string AnalysisType { get; set; } = "";
        [JsonPropertyName("results")] public AnalysisResultsDto Results { get; set; } = new();
        [JsonPropertyName("solution_steps")] public List<SolutionStepDto> SolutionSteps { get; set; } = new();
        /// <summary>Hata/uyarı mesajları. '⚠' ile başlayanlar ciddi, 'ℹ' bilgilendirme.</summary>
        [JsonPropertyName("errors")] public List<string> Errors { get; set; } = new();
        [JsonPropertyName("warnings")] public List<string> Warnings { get; set; } = new();
    }

    public sealed class HealthDto
    {
        [JsonPropertyName("status")] public string Status { get; set; } = "";
        [JsonPropertyName("service")] public string Service { get; set; } = "";
        [JsonPropertyName("version")] public string Version { get; set; } = "";
    }

    // ═══════════════════════════════════════════════════════
    //  GÖRÜNTÜLEME YARDIMCILARI
    // ═══════════════════════════════════════════════════════

    /// <summary>
    /// Eleman akımını öğrencinin beklediği biçimde gösterir.
    ///
    /// Çözücü tüm elemanlar için pasif işaret kuralını kullanır: akım
    /// (+) pinden (−) pine doğru pozitiftir. Bu yüzden güç veren bir kaynak
    /// "−4 mA (1→0)" çıkar — doğru ama kafa karıştırıcı.
    ///   DC: değer negatifse yön ters çevrilir → "4 mA (0→1)" (gerçek akış yönü)
    ///   AC: kaynaklarda kaynağın VERDİĞİ akım gösterilir (fazör −1 ile çarpılır,
    ///       yön ters çevrilir); pasif elemanlarda referans yön korunur.
    /// </summary>
    public static class CurrentDisplay
    {
        public static (string Value, string Direction) Format(string elementId, ElementCurrentDto current)
        {
            var value = current.Value;
            string direction = current.Direction;
            string[] ends = direction.Split('→');
            bool canReverse = ends.Length == 2;
            // Only voltage sources ("V", "VAC") need inversion in AC because solver reports branch current
            // in passive convention (into positive terminal). Current sources ("I", "IAC") are reported
            // by the solver as +value in their delivered n+→n- direction, so keep isSource voltage-only.
            bool isSource = elementId.StartsWith("V", StringComparison.OrdinalIgnoreCase);

            bool reverse = canReverse && (value.IsComplex ? isSource : value.Real < 0);
            if (reverse)
            {
                direction = $"{ends[1]}→{ends[0]}";
                value = value.IsComplex
                    ? new ResultValue { Real = -value.Real, Imaginary = -value.Imaginary, IsComplex = true }
                    : ResultValue.FromReal(-value.Real);
            }
            return (EngFormat.Format(value, current.Unit), direction);
        }
    }

    /// <summary>
    /// Sayıları mühendislik notasyonunda gösterir: 0.004 A → "4 mA".
    /// </summary>
    public static class EngFormat
    {
        private static readonly (double Scale, string Prefix)[] Prefixes =
        {
            (1e9, "G"), (1e6, "M"), (1e3, "k"), (1, ""),
            (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"), (1e-12, "p"),
        };

        public static string Format(double value, string unit, int significant = 4)
        {
            if (double.IsNaN(value) || double.IsInfinity(value))
                return $"— {unit}";
            if (Math.Abs(value) < 1e-15)
                return $"0 {unit}";
            var (scale, prefix) = PrefixFor(Math.Abs(value));
            return $"{Number(value / scale, significant)} {prefix}{unit}";
        }

        /// <summary>DC: "8 V"; AC: "95.3∠7.984° mA" (kutupsal — öğrenci genlik/faz okur).</summary>
        public static string Format(ResultValue v, string unit)
        {
            if (!v.IsComplex)
                return Format(v.Real, unit);
            double mag = v.Magnitude;
            if (mag < 1e-15)
                return $"0 {unit}";
            var (scale, prefix) = PrefixFor(mag);
            return $"{Number(mag / scale, 4)}∠{Number(v.PhaseDegrees, 4)}° {prefix}{unit}";
        }

        private static (double Scale, string Prefix) PrefixFor(double abs)
        {
            foreach (var (scale, prefix) in Prefixes)
            {
                // 0.9995: 999.96 mA gibi değerlerin "1000 mA" yerine "1 A" olması için
                if (abs >= scale * 0.9995)
                    return (scale, prefix);
            }
            return (1e-12, "p");
        }

        private static string Number(double x, int significant)
        {
            string s = x.ToString("G" + significant, CultureInfo.InvariantCulture);
            return s.Contains('E') ? x.ToString("0.###", CultureInfo.InvariantCulture) : s;
        }
    }
}
