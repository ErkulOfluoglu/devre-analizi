using System;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Çözücüye ulaşılamadı (sunucu kapalı / başlatılamadı).
    /// </summary>
    public sealed class BackendUnavailableException : Exception
    {
        public BackendUnavailableException(string message, Exception? inner = null)
            : base(message, inner) { }
    }

    /// <summary>
    /// Çözücü isteği reddetti (ör: netlist ayrıştırılamadı — HTTP 400/422).
    /// Mesaj kullanıcıya gösterilmeye uygundur.
    /// </summary>
    public sealed class AnalysisRequestException : Exception
    {
        public int StatusCode { get; }

        public AnalysisRequestException(int statusCode, string message)
            : base(message)
        {
            StatusCode = statusCode;
        }
    }

    /// <summary>
    /// Python FastAPI çözücüsüyle HTTP üzerinden konuşur.
    ///
    ///   GET  /health          → sunucu hazır mı
    ///   POST /analyze         → devreyi çöz
    ///   POST /practice/check  → alıştırma cevaplarını değerlendir
    ///   GET  /llm/status      → yerel yapay zekâ (Ollama) var mı
    ///   POST /llm/ask         → çözüm hakkında yapay zekâya soru
    /// </summary>
    public sealed class AnalysisApiClient : IDisposable
    {
        public const string ExpectedServiceName = "CircuitAnalyzer API";

        private readonly HttpClient _http;
        /// <summary>Yapay zekâ için: işlemcide çalışan model cevabı dakikalar sürebilir.</summary>
        private readonly HttpClient _httpLong;

        public static readonly TimeSpan LlmTimeout = TimeSpan.FromMinutes(6);

        public Uri BaseAddress => _http.BaseAddress!;

        public AnalysisApiClient(Uri baseAddress, TimeSpan? timeout = null)
        {
            _http = new HttpClient
            {
                BaseAddress = baseAddress,
                // Büyük AC devrelerinde sembolik çözüm birkaç saniye sürebilir
                Timeout = timeout ?? TimeSpan.FromSeconds(120),
            };
            _httpLong = new HttpClient
            {
                BaseAddress = baseAddress,
                Timeout = LlmTimeout,
            };
        }

        /// <summary>
        /// Sunucu çalışıyor ve gerçekten bizim çözücümüz mü? (Hata fırlatmaz.)
        /// </summary>
        public async Task<HealthDto?> TryGetHealthAsync(CancellationToken ct = default)
        {
            try
            {
                using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                cts.CancelAfter(TimeSpan.FromSeconds(3));
                var health = await _http.GetFromJsonAsync<HealthDto>("/health", cts.Token);
                return health?.Service == ExpectedServiceName ? health : null;
            }
            catch (Exception ex) when (ex is HttpRequestException
                                         or TaskCanceledException
                                         or JsonException
                                         or NotSupportedException)
            {
                return null;
            }
        }

        public Task<AnalysisResponseDto> AnalyzeAsync(
            AnalysisRequestDto request, CancellationToken ct = default)
            => PostAsync<AnalysisRequestDto, AnalysisResponseDto>("/analyze", request, ct);

        /// <summary>Alıştırma modu: öğrencinin cevaplarını değerlendirir.</summary>
        public Task<AnswerCheckResponseDto> CheckAnswersAsync(
            AnswerCheckRequestDto request, CancellationToken ct = default)
            => PostAsync<AnswerCheckRequestDto, AnswerCheckResponseDto>("/practice/check", request, ct);

        /// <summary>
        /// Yerel yapay zekâ durumu. Hata fırlatmaz: çözücüye ulaşılamazsa null.
        /// (Ollama kurulu değilse Available = false ve kurulum bilgisi döner.)
        /// </summary>
        public async Task<LlmStatusDto?> TryGetLlmStatusAsync(CancellationToken ct = default)
        {
            try
            {
                using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                cts.CancelAfter(TimeSpan.FromSeconds(8));
                return await _http.GetFromJsonAsync<LlmStatusDto>("/llm/status", cts.Token);
            }
            catch (Exception ex) when (ex is HttpRequestException
                                         or TaskCanceledException
                                         or JsonException
                                         or NotSupportedException)
            {
                return null;
            }
        }

        /// <summary>Kurulu ama kapalı Ollama'yı başlatır. Hata fırlatmaz: başarısızsa false.</summary>
        public async Task<bool> StartOllamaAsync(CancellationToken ct = default)
        {
            try
            {
                var r = await PostAsync<object, LlmActionResultDto>("/llm/start", new { }, ct);
                return r.Ok;
            }
            catch (Exception ex) when (ex is AnalysisRequestException or BackendUnavailableException)
            {
                return false;
            }
        }

        /// <summary>
        /// Model indirmeyi başlatır (model null → belleğe göre önerilen). Hemen döner;
        /// ilerleme GetModelPullAsync ile yoklanır. Diskte yer yoksa (400), indirme zaten
        /// sürüyorsa (409) ya da Ollama kapalıysa (503) Türkçe mesajlı AnalysisRequestException.
        /// </summary>
        public Task<LlmPullStatusDto> StartModelPullAsync(string? model, CancellationToken ct = default)
            => PostAsync<LlmPullRequestDto, LlmPullStatusDto>("/llm/pull", new LlmPullRequestDto { Model = model }, ct);

        /// <summary>İndirme durumu. Hata fırlatmaz: çözücüye ulaşılamazsa null.</summary>
        public async Task<LlmPullStatusDto?> GetModelPullAsync(CancellationToken ct = default)
        {
            try
            {
                using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                cts.CancelAfter(TimeSpan.FromSeconds(8));
                return await _http.GetFromJsonAsync<LlmPullStatusDto>("/llm/pull", cts.Token);
            }
            catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException
                                         or JsonException or NotSupportedException)
            {
                return null;
            }
        }

        /// <summary>İndirmeyi iptal eder (yeniden başlatınca kaldığı yerden devam eder). Hata fırlatmaz.</summary>
        public async Task<bool> CancelModelPullAsync(CancellationToken ct = default)
        {
            try
            {
                var r = await PostAsync<object, LlmActionResultDto>("/llm/pull/cancel", new { }, ct);
                return r.Ok;
            }
            catch (Exception ex) when (ex is AnalysisRequestException or BackendUnavailableException)
            {
                return false;
            }
        }

        /// <summary>
        /// Çözüm hakkında yapay zekâya soru. Ollama çalışmıyorsa
        /// AnalysisRequestException (StatusCode 503, Türkçe kurulum bilgisi).
        /// </summary>
        public Task<LlmAnswerDto> AskAsync(LlmAskRequestDto request, CancellationToken ct = default)
            => PostAsync<LlmAskRequestDto, LlmAnswerDto>("/llm/ask", request, ct, _httpLong,
                "Yapay zekâ zamanında cevap vermedi (zaman aşımı). Model bu bilgisayar için " +
                "fazla büyük olabilir; daha küçük bir model deneyin.");

        private async Task<TResponse> PostAsync<TRequest, TResponse>(
            string path, TRequest request, CancellationToken ct,
            HttpClient? http = null, string? timeoutMessage = null)
        {
            HttpResponseMessage response;
            try
            {
                response = await (http ?? _http).PostAsJsonAsync(path, request, ct);
            }
            catch (HttpRequestException ex)
            {
                throw new BackendUnavailableException(
                    "Çözücüye bağlanılamadı. Çözücü kapanmış olabilir.", ex);
            }
            catch (TaskCanceledException ex) when (!ct.IsCancellationRequested)
            {
                throw new BackendUnavailableException(
                    timeoutMessage ?? "Çözücü zamanında yanıt vermedi (zaman aşımı). " +
                    "Devre çok büyük olabilir.", ex);
            }

            using (response)
            {
                string body = await response.Content.ReadAsStringAsync(ct);

                if (!response.IsSuccessStatusCode)
                    throw new AnalysisRequestException(
                        (int)response.StatusCode, ExtractErrorDetail(body, (int)response.StatusCode));

                try
                {
                    return JsonSerializer.Deserialize<TResponse>(body)
                           ?? throw new JsonException("Boş yanıt");
                }
                catch (JsonException ex)
                {
                    throw new AnalysisRequestException(
                        (int)response.StatusCode,
                        $"Çözücünün yanıtı okunamadı: {ex.Message}");
                }
            }
        }

        /// <summary>
        /// FastAPI hata gövdesinden okunabilir mesaj çıkarır.
        ///   400: {"detail": "Netlist ayrıştırma hatası: ..."}
        ///   422: {"detail": [{"loc": [...], "msg": "..."}]}
        /// </summary>
        internal static string ExtractErrorDetail(string body, int statusCode)
        {
            try
            {
                using var doc = JsonDocument.Parse(body);
                if (doc.RootElement.TryGetProperty("detail", out var detail))
                {
                    if (detail.ValueKind == JsonValueKind.String)
                        return detail.GetString() ?? body;
                    if (detail.ValueKind == JsonValueKind.Array && detail.GetArrayLength() > 0)
                    {
                        var first = detail[0];
                        string msg = first.TryGetProperty("msg", out var m) ? m.GetString() ?? "" : "";
                        string loc = first.TryGetProperty("loc", out var l) ? l.ToString() : "";
                        return $"İstek doğrulama hatası ({loc}): {msg}";
                    }
                }
            }
            catch (JsonException)
            {
                // Gövde JSON değil — ham metni döndür
            }
            return $"Çözücü hatası (HTTP {statusCode}): {body}";
        }

        public void Dispose()
        {
            _http.Dispose();
            _httpLong.Dispose();
        }
    }
}
