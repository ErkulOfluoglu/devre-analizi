using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Python çözücüsünü (FastAPI) arka planda başlatır, hazır olmasını
    /// bekler ve uygulama kapanınca durdurur. Öğrenci hiçbir terminal görmez.
    ///
    /// Çözücü bulma sırası:
    ///   1. CIRCUIT_ANALYZER_API_URL ortam değişkeni → zaten çalışan sunucu
    ///   2. Uygulama klasöründe paketlenmiş çözücü: backend\CircuitAnalyzerAPI.exe
    ///      (ileride kurulum paketi için)
    ///   3. Geliştirme: üst klasörlerde CircuitAnalyzer.API\main.py ara,
    ///      'python -m uvicorn main:app' ile boş bir portta başlat
    ///
    /// ★ Hayalet süreç koruması: Başlatılan süreç bir Windows Job Object'e
    ///   bağlanır (KILL_ON_JOB_CLOSE). Uygulama çökse bile Windows çözücüyü
    ///   otomatik kapatır.
    /// </summary>
    public sealed class BackendManager : IDisposable
    {
        private const string UrlEnvVar = "CIRCUIT_ANALYZER_API_URL";
        private const string BundledExe = @"backend\CircuitAnalyzerAPI.exe";

        private Process? _process;
        private JobObject? _job;
        private readonly StringBuilder _log = new();
        private readonly object _logLock = new();

        /// <summary>Süren başlatma (aynı anda ikinci bir başlatma onu bekler, ikinci süreç açılmaz).</summary>
        private Task<AnalysisApiClient>? _startTask;

        /// <summary>Çalışan süreç kapanınca iptal olur (bekleyen istek zaman aşımını beklemesin).</summary>
        private CancellationTokenSource _stoppedCts = new();

        /// <summary>Dışarıdan verilen (ortam değişkeni) sunucu kullanılıyor: süreç bizim değil.</summary>
        private bool _external;
        private bool _disposed;

        public AnalysisApiClient? Client { get; private set; }

        /// <summary>
        /// Kaynak koddan mı çalışıyor (paketlenmiş çözücü yok, Python ile başlatılıyor ya da ortam
        /// değişkeniyle dış sunucu verilmiş)? Yalnız o zaman hata metinlerinde Python ipucu verilir.
        /// </summary>
        public static bool IsDeveloperRun =>
            !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable(UrlEnvVar)) ||
            (!File.Exists(Path.Combine(AppContext.BaseDirectory, BundledExe)) &&
             FindApiSourceDir(AppContext.BaseDirectory) != null);

        /// <summary>
        /// Çözücü hâlâ çalışıyor mu? (Dış sunucuda bilinemez: true.) Başlatılmadıysa false.
        /// </summary>
        public bool IsAlive
        {
            get
            {
                if (Client == null) return false;
                if (_external) return true;
                try { return _process is { HasExited: false }; }
                catch (InvalidOperationException) { return false; }
            }
        }

        /// <summary>Çözücü süreci kapanınca iptal olan belirteç (istekler buna bağlanır).</summary>
        public CancellationToken StoppedToken => _stoppedCts.Token;

        /// <summary>Çözücü sürecinin kimliği (testler için); süreç yoksa null.</summary>
        internal int? ProcessId
        {
            get
            {
                try { return _process?.Id; }
                catch (InvalidOperationException) { return null; }
            }
        }

        /// <summary>
        /// Çözücüyü (yeniden) başlatır: önceki süreç ve bağlantı kapatılır, sonra yenisi açılır.
        /// Başlatma sürerken çağrılırsa yeni süreç açmaz, sürenin sonucunu bekler.
        /// </summary>
        /// <exception cref="BackendUnavailableException">Çözücü başlatılamazsa.</exception>
        public Task<AnalysisApiClient> StartAsync(
            IProgress<string>? progress = null, CancellationToken ct = default)
        {
            if (_startTask is { IsCompleted: false })
                return _startTask;
            return _startTask = StartCoreAsync(progress, ct);
        }

        /// <summary>Çözücü süreç çıktısı (hata teşhisi için).</summary>
        public string LogText
        {
            get { lock (_logLock) return _log.ToString(); }
        }

        private async Task<AnalysisApiClient> StartCoreAsync(
            IProgress<string>? progress, CancellationToken ct)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);

            // Yeniden başlatma: eski bağlantı ve süreç önce kapanır (iki çözücü birden çalışmasın)
            Client?.Dispose();
            Client = null;
            Stop();
            _external = false;
            lock (_logLock) _log.Clear();

            // 1. Dışarıdan verilen sunucu
            string? envUrl = Environment.GetEnvironmentVariable(UrlEnvVar);
            if (!string.IsNullOrWhiteSpace(envUrl))
            {
                var client = new AnalysisApiClient(new Uri(envUrl));
                progress?.Report($"Çözücüye bağlanılıyor: {envUrl}");
                if (await WaitForHealthAsync(client, TimeSpan.FromSeconds(10), ct))
                {
                    _external = true;
                    return Client = client;
                }
                client.Dispose();
                throw new BackendUnavailableException(BackendFailure.NotReady,
                    $"{UrlEnvVar} ile verilen çözücüye ulaşılamadı: {envUrl}",
                    detail: $"{UrlEnvVar} = {envUrl}");
            }

            int port = GetFreePort();
            var baseUri = new Uri($"http://127.0.0.1:{port}");
            ProcessStartInfo psi = CreateStartInfo(port);

            progress?.Report("Çözücü başlatılıyor…");
            StartProcess(psi);

            var apiClient = new AnalysisApiClient(baseUri);
            // İlk açılışta lcapy/SymPy yüklemesi birkaç saniye sürer
            bool ready = await WaitForHealthAsync(apiClient, TimeSpan.FromSeconds(90), ct);
            if (!ready || _disposed)
            {
                apiClient.Dispose();
                string tail = Tail(LogText, 1200);
                Stop();
                ObjectDisposedException.ThrowIf(_disposed, this);
                throw new BackendUnavailableException(BackendFailure.NotReady,
                    "Çözücü başlatılamadı.",
                    detail: string.IsNullOrWhiteSpace(tail) ? null : $"Çözücü çıktısı:\n{tail}");
            }

            progress?.Report("Çözücü hazır");
            return Client = apiClient;
        }

        private ProcessStartInfo CreateStartInfo(int port)
        {
            string baseDir = AppContext.BaseDirectory;

            // 2. Paketlenmiş çözücü
            string bundled = Path.Combine(baseDir, BundledExe);
            if (File.Exists(bundled))
            {
                var psiBundled = new ProcessStartInfo(bundled)
                {
                    WorkingDirectory = Path.GetDirectoryName(bundled)!,
                };
                psiBundled.ArgumentList.Add("--port");
                psiBundled.ArgumentList.Add(port.ToString());
                return Configure(psiBundled);
            }

            // 3. Geliştirme ortamı: kaynak koddan çalıştır
            string? apiDir = FindApiSourceDir(baseDir)
                ?? throw new BackendUnavailableException(BackendFailure.Missing,
                    "Çözücü bulunamadı.",
                    detail: $"Ne '{BundledExe}' ne de üst klasörlerde 'CircuitAnalyzer.API\\main.py' var.");

            var psi = new ProcessStartInfo("python")
            {
                WorkingDirectory = apiDir,
            };
            foreach (var arg in new[] { "-m", "uvicorn", "main:app",
                                        "--host", "127.0.0.1", "--port", port.ToString(),
                                        "--log-level", "warning" })
                psi.ArgumentList.Add(arg);
            return Configure(psi);
        }

        private static ProcessStartInfo Configure(ProcessStartInfo psi)
        {
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.StandardOutputEncoding = Encoding.UTF8;
            psi.StandardErrorEncoding = Encoding.UTF8;
            // Türkçe karakterler ve ⚠ gibi semboller için
            psi.Environment["PYTHONUTF8"] = "1";
            psi.Environment["PYTHONIOENCODING"] = "utf-8";
            return psi;
        }

        /// <summary>
        /// Uygulama klasöründen yukarı doğru CircuitAnalyzer.API\main.py arar.
        /// (bin\Debug\net10.0-windows → ... → proje kökü)
        /// </summary>
        internal static string? FindApiSourceDir(string startDir)
        {
            var dir = new DirectoryInfo(startDir);
            while (dir != null)
            {
                string candidate = Path.Combine(dir.FullName, "CircuitAnalyzer.API");
                if (File.Exists(Path.Combine(candidate, "main.py")))
                    return candidate;
                dir = dir.Parent;
            }
            return null;
        }

        private void StartProcess(ProcessStartInfo psi)
        {
            var process = new Process { StartInfo = psi, EnableRaisingEvents = true };
            process.OutputDataReceived += (_, e) => AppendLog(e.Data);
            process.ErrorDataReceived += (_, e) => AppendLog(e.Data);
            // Kapanınca bekleyen istekler hemen düşsün (zaman aşımını beklemesin)
            var stopped = new CancellationTokenSource();
            _stoppedCts = stopped;
            process.Exited += (_, _) =>
            {
                try { stopped.Cancel(); }
                catch (ObjectDisposedException) { }
            };

            try
            {
                if (!process.Start())
                    throw new BackendUnavailableException(BackendFailure.CouldNotStart, "Çözücü süreci başlatılamadı.");
            }
            catch (Win32Exception ex)
            {
                process.Dispose();
                throw new BackendUnavailableException(BackendFailure.CouldNotStart,
                    $"'{psi.FileName}' çalıştırılamadı.", detail: ex.Message, inner: ex);
            }

            try
            {
                _job = new JobObject();
                _job.Assign(process);
            }
            catch (Win32Exception ex)
            {
                // Job Object başarısız olsa da çözücü çalışır; sadece çökme
                // durumunda arkada kalabilir. Kapanışta Stop() yine öldürür.
                AppendLog($"[uyarı] Job Object atanamadı: {ex.Message}");
                _job?.Dispose();
                _job = null;
            }

            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            _process = process;
        }

        private async Task<bool> WaitForHealthAsync(
            AnalysisApiClient client, TimeSpan timeout, CancellationToken ct)
        {
            var sw = Stopwatch.StartNew();
            while (sw.Elapsed < timeout)
            {
                ct.ThrowIfCancellationRequested();
                if (_disposed)
                    return false;   // program kapanıyor
                if (_process is { HasExited: true })
                    return false;   // Süreç erken öldü (ör: modül eksik)
                if (await client.TryGetHealthAsync(ct) != null)
                    return true;
                await Task.Delay(300, ct);
            }
            return false;
        }

        private void AppendLog(string? line)
        {
            if (line == null) return;
            lock (_logLock)
            {
                _log.AppendLine(line);
                // Sınırsız büyümesin
                if (_log.Length > 64_000)
                    _log.Remove(0, _log.Length - 48_000);
            }
        }

        private static int GetFreePort()
        {
            var listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            int port = ((IPEndPoint)listener.LocalEndpoint).Port;
            listener.Stop();
            return port;
        }

        private static string Tail(string text, int maxChars) =>
            text.Length <= maxChars ? text : "…" + text[^maxChars..];

        public void Stop()
        {
            try
            {
                if (_process is { HasExited: false })
                    _process.Kill(entireProcessTree: true);
            }
            catch (Exception ex) when (ex is InvalidOperationException or Win32Exception)
            {
                // Zaten kapanmış
            }
            _process?.Dispose();
            _process = null;
            _job?.Dispose();   // KILL_ON_JOB_CLOSE — kalan alt süreçleri de kapatır
            _job = null;
        }

        public void Dispose()
        {
            _disposed = true;
            Client?.Dispose();
            Client = null;
            Stop();
        }

        // ═══════════════════════════════════════════════════════
        //  Windows Job Object (KILL_ON_JOB_CLOSE)
        // ═══════════════════════════════════════════════════════

        private sealed class JobObject : IDisposable
        {
            private IntPtr _handle;

            public JobObject()
            {
                _handle = CreateJobObject(IntPtr.Zero, null);
                if (_handle == IntPtr.Zero)
                    throw new Win32Exception(Marshal.GetLastWin32Error());

                var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION
                {
                    BasicLimitInformation = new JOBOBJECT_BASIC_LIMIT_INFORMATION
                    {
                        LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
                    },
                };
                int size = Marshal.SizeOf<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>();
                IntPtr ptr = Marshal.AllocHGlobal(size);
                try
                {
                    Marshal.StructureToPtr(info, ptr, false);
                    if (!SetInformationJobObject(_handle, JobObjectExtendedLimitInformation, ptr, (uint)size))
                        throw new Win32Exception(Marshal.GetLastWin32Error());
                }
                finally
                {
                    Marshal.FreeHGlobal(ptr);
                }
            }

            public void Assign(Process process)
            {
                if (!AssignProcessToJobObject(_handle, process.Handle))
                    throw new Win32Exception(Marshal.GetLastWin32Error());
            }

            public void Dispose()
            {
                if (_handle != IntPtr.Zero)
                {
                    CloseHandle(_handle);
                    _handle = IntPtr.Zero;
                }
            }

            private const int JobObjectExtendedLimitInformation = 9;
            private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000;

            [StructLayout(LayoutKind.Sequential)]
            private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
            {
                public long PerProcessUserTimeLimit;
                public long PerJobUserTimeLimit;
                public uint LimitFlags;
                public UIntPtr MinimumWorkingSetSize;
                public UIntPtr MaximumWorkingSetSize;
                public uint ActiveProcessLimit;
                public UIntPtr Affinity;
                public uint PriorityClass;
                public uint SchedulingClass;
            }

            [StructLayout(LayoutKind.Sequential)]
            private struct IO_COUNTERS
            {
                public ulong ReadOperationCount;
                public ulong WriteOperationCount;
                public ulong OtherOperationCount;
                public ulong ReadTransferCount;
                public ulong WriteTransferCount;
                public ulong OtherTransferCount;
            }

            [StructLayout(LayoutKind.Sequential)]
            private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
            {
                public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
                public IO_COUNTERS IoInfo;
                public UIntPtr ProcessMemoryLimit;
                public UIntPtr JobMemoryLimit;
                public UIntPtr PeakProcessMemoryUsed;
                public UIntPtr PeakJobMemoryUsed;
            }

            [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
            private static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string? lpName);

            [DllImport("kernel32.dll", SetLastError = true)]
            private static extern bool SetInformationJobObject(
                IntPtr hJob, int infoType, IntPtr lpJobObjectInfo, uint cbJobObjectInfoLength);

            [DllImport("kernel32.dll", SetLastError = true)]
            private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

            [DllImport("kernel32.dll", SetLastError = true)]
            private static extern bool CloseHandle(IntPtr handle);
        }
    }
}
