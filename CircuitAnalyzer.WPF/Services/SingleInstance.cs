using System;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Programın aynı kullanıcı oturumunda tek kopya çalışmasını sağlar.
    ///
    /// İlk açılan kopya adlı bir mutex'i (Local\ = yalnız bu oturum) alır ve hemen bir
    /// adlı kanal (named pipe) dinlemeye başlar. Sonradan açılan kopya mutex'i alamaz;
    /// komut satırındaki dosyayı (varsa) kanaldan ilk kopyaya gönderir ve kapanır.
    /// Ağ soketi kullanılmaz; kanal yalnız aynı kullanıcıya açıktır (CurrentUserOnly) ve
    /// adında kullanıcının SID'i ile oturum numarası vardır.
    ///
    /// Yarışlar:
    ///   • İlk kopya henüz açılıyorsa: kanal mutex'ten hemen sonra açılır; gönderen kopya
    ///     birkaç saniye boyunca yeniden dener.
    ///   • Çöken kopyadan kalan mutex: Windows mutex'i "terk edilmiş" sayar; WaitOne bunu
    ///     AbandonedMutexException ile bildirir ve mutex artık bizimdir.
    ///   • İlk kopya bu sürede hiç cevap vermezse (kilitlenmiş ya da kapanıyor): yeni kopya
    ///     tek kopya düzeni olmadan normal açılır; kullanıcı hiç değilse dosyasını görür.
    /// </summary>
    public sealed class SingleInstance : IDisposable
    {
        /// <summary>Mesajın başı: başka bir programın kanala yazdığı rastgele veri dosya sanılmasın.</summary>
        internal const string MessageHeader = "DEVRE-ANALIZI-AC/1";

        /// <summary>Kanaldan okunacak en uzun mesaj (karakter).</summary>
        internal const int MaxMessageChars = 8192;

        private readonly Mutex _mutex;
        private readonly CancellationTokenSource _cts = new();
        private Task? _listenTask;

        public string PipeName { get; }

        private SingleInstance(Mutex mutex, string pipeName)
        {
            _mutex = mutex;
            PipeName = pipeName;
        }

        /// <summary>Bu kullanıcı ve oturum için ad kökü (testler kendi GUID adlarını verir).</summary>
        public static string DefaultBaseName
        {
            get
            {
                string sid;
                try { sid = WindowsIdentity.GetCurrent().User?.Value ?? Environment.UserName; }
                catch (Exception) { sid = Environment.UserName; }
                int session;
                try { session = Process.GetCurrentProcess().SessionId; }
                catch (Exception) { session = 0; }
                return BaseNameFor(sid, session);
            }
        }

        internal static string BaseNameFor(string userSid, int sessionId)
        {
            // Mutex ve kanal adlarında ters bölü olamaz
            string safe = new string(userSid.Select(c => char.IsLetterOrDigit(c) || c == '-' ? c : '_').ToArray());
            return $"DevreAnalizi-{safe}-{sessionId}";
        }

        internal static string MutexNameFor(string baseName) => $@"Local\{baseName}.tek-kopya";

        internal static string PipeNameFor(string baseName) => $"{baseName}.kanal";

        // ═══════════════════════════════════════════════════════
        //  MESAJ
        // ═══════════════════════════════════════════════════════

        /// <summary>Gönderilecek mesaj: başlık satırı ve (varsa) dosyanın tam yolu.</summary>
        internal static string EncodeMessage(string? filePath) =>
            MessageHeader + "\n" + (filePath ?? "");

        /// <summary>
        /// Mesajı çözer. Başlık yoksa false. Dosya yoksa path null (yalnız pencereyi öne getir).
        /// Tam olmayan (göreli) yollar kabul edilmez: göreli yol gönderenin klasörüne göredir.
        /// </summary>
        internal static bool TryDecodeMessage(string? text, out string? filePath)
        {
            filePath = null;
            if (text == null)
                return false;
            string normalized = text.Replace("\r\n", "\n");
            if (!normalized.StartsWith(MessageHeader + "\n", StringComparison.Ordinal) &&
                normalized != MessageHeader)
                return false;
            string rest = normalized.Length > MessageHeader.Length + 1
                ? normalized[(MessageHeader.Length + 1)..].Trim()
                : "";
            if (rest.Length == 0)
                return true;
            if (rest.Contains('\n') || rest.IndexOfAny(Path.GetInvalidPathChars()) >= 0)
                return false;
            try
            {
                if (!Path.IsPathFullyQualified(rest))
                    return false;
            }
            catch (ArgumentException)
            {
                return false;
            }
            filePath = rest;
            return true;
        }

        // ═══════════════════════════════════════════════════════
        //  BAŞLANGIÇ
        // ═══════════════════════════════════════════════════════

        /// <summary>
        /// Tek kopya düzenini kurar. Dönüş:
        ///   • Primary dolu → bu kopya ilk kopyadır; StartListening ile kanalı açın.
        ///   • Forwarded true → dosya ilk kopyaya iletildi; bu kopya kapanmalıdır.
        ///   • İkisi de değil → ilk kopyaya ulaşılamadı; tek kopya düzeni olmadan açılın.
        /// </summary>
        public static (SingleInstance? Primary, bool Forwarded) Acquire(
            string baseName, string? fileToForward, TimeSpan timeout)
        {
            string mutexName = MutexNameFor(baseName);
            string pipeName = PipeNameFor(baseName);
            string message = EncodeMessage(fileToForward);
            var sw = Stopwatch.StartNew();

            while (true)
            {
                var mutex = TryOwnMutex(mutexName);
                if (mutex != null)
                    return (new SingleInstance(mutex, pipeName), false);

                if (TrySend(pipeName, message, TimeSpan.FromMilliseconds(500)))
                    return (null, true);

                if (sw.Elapsed >= timeout)
                    return (null, false);
                Thread.Sleep(100);
            }
        }

        /// <summary>Mutex'i almayı dener; başka bir canlı kopya tutuyorsa null.</summary>
        private static Mutex? TryOwnMutex(string name)
        {
            Mutex mutex;
            bool createdNew;
            try
            {
                mutex = new Mutex(initiallyOwned: true, name, out createdNew);
            }
            catch (Exception ex) when (ex is UnauthorizedAccessException or IOException or WaitHandleCannotBeOpenedException)
            {
                return null;
            }
            if (createdNew)
                return mutex;

            bool owned;
            try
            {
                owned = mutex.WaitOne(0);
            }
            catch (AbandonedMutexException)
            {
                owned = true;   // önceki kopya çökmüş: mutex artık bizim
            }
            if (owned)
                return mutex;
            mutex.Dispose();
            return null;
        }

        /// <summary>
        /// İlk kopyanın kanalına mesaj gönderir; ulaşılamazsa false. Göndermeden önce ilk kopyanın
        /// penceresini öne getirmesine izin verir (yoksa Windows yalnız görev çubuğunda yanıp söndürür).
        /// </summary>
        internal static bool TrySend(string pipeName, string message, TimeSpan connectTimeout)
        {
            try
            {
                using var client = new NamedPipeClientStream(".", pipeName, PipeDirection.Out,
                    PipeOptions.CurrentUserOnly);
                client.Connect((int)Math.Max(1, connectTimeout.TotalMilliseconds));
                try
                {
                    if (GetNamedPipeServerProcessId(client.SafePipeHandle.DangerousGetHandle(), out uint pid))
                        AllowSetForegroundWindow(pid);
                }
                catch (Exception)
                {
                    // Öne getirme izni verilemezse pencere yine açılır, yalnız öne gelmeyebilir
                }
                byte[] bytes = Encoding.UTF8.GetBytes(message);
                client.Write(bytes, 0, bytes.Length);
                client.Flush();
                return true;
            }
            catch (Exception ex) when (ex is TimeoutException or IOException or UnauthorizedAccessException)
            {
                return false;
            }
        }

        /// <summary>
        /// Kanalı arka planda dinler; her geçerli mesajda onMessage(dosya yolu ya da null) çağrılır
        /// (arka plan iş parçacığında: çağıran arayüz iş parçacığına kendisi aktarmalı).
        /// </summary>
        public void StartListening(Action<string?> onMessage)
        {
            if (_listenTask != null)
                return;
            var ct = _cts.Token;
            _listenTask = Task.Run(async () =>
            {
                while (!ct.IsCancellationRequested)
                {
                    try
                    {
                        using var server = new NamedPipeServerStream(PipeName, PipeDirection.In, 1,
                            PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
                        await server.WaitForConnectionAsync(ct).ConfigureAwait(false);
                        string? text = await ReadMessageAsync(server, ct).ConfigureAwait(false);
                        if (TryDecodeMessage(text, out string? path))
                            onMessage(path);
                    }
                    catch (OperationCanceledException)
                    {
                        break;
                    }
                    catch (Exception)
                    {
                        // Bozuk bağlantı ya da kanal o an açılamadı: kısa bekleyip yeniden dinle
                        try { await Task.Delay(200, ct).ConfigureAwait(false); }
                        catch (OperationCanceledException) { break; }
                    }
                }
            }, ct);
        }

        private static async Task<string?> ReadMessageAsync(Stream stream, CancellationToken ct)
        {
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
            timeout.CancelAfter(TimeSpan.FromSeconds(3));
            var buffer = new byte[4096];
            using var ms = new MemoryStream();
            while (ms.Length <= MaxMessageChars * 4)
            {
                int n = await stream.ReadAsync(buffer.AsMemory(0, buffer.Length), timeout.Token).ConfigureAwait(false);
                if (n == 0)
                    break;
                ms.Write(buffer, 0, n);
            }
            if (ms.Length > MaxMessageChars * 4)
                return null;
            string text = Encoding.UTF8.GetString(ms.ToArray());
            return text.Length > MaxMessageChars ? null : text;
        }

        public void Dispose()
        {
            _cts.Cancel();
            try
            {
                _mutex.ReleaseMutex();
            }
            catch (Exception)
            {
                // Başka iş parçacığından çağrıldıysa: süreç kapanınca Windows bırakır
            }
            _mutex.Dispose();
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetNamedPipeServerProcessId(IntPtr pipe, out uint serverProcessId);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool AllowSetForegroundWindow(uint processId);
    }

    /// <summary>Komut satırı yardımcıları (ilk kopya ve ikinci kopya aynı kuralı kullanır).</summary>
    public static class StartupArgs
    {
        /// <summary>
        /// Komut satırından açılacak devre dosyasını bulur (program yolu hariç argümanlar):
        /// "--" ile başlamayan, .devre uzantılı ya da var olan ilk dosya. Yoksa null.
        /// </summary>
        public static string? FindFileArgument(IEnumerable<string> args, Func<string, bool>? fileExists = null)
        {
            fileExists ??= File.Exists;
            return args.FirstOrDefault(a =>
                !string.IsNullOrWhiteSpace(a) &&
                !a.StartsWith("--", StringComparison.Ordinal) &&
                (a.EndsWith(".devre", StringComparison.OrdinalIgnoreCase) || fileExists(a)));
        }
    }
}
