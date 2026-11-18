using System.Collections.Generic;

namespace CircuitAnalyzer.WPF.Services
{
    /// <summary>
    /// Ekran kartı ayarı için kapatılan Ollama'nın kapanışta eski hâline getirilmesi kararları
    /// (saf işlevler; süreç ya da ağ kullanmaz, bu yüzden doğrudan test edilir).
    /// </summary>
    public static class GpuRestorePolicy
    {
        /// <summary>
        /// Çözücüden /llm/gpu/release istensin mi? Ayar yapıldıysa ve çözücü yaşıyorsa evet:
        /// ekran kartı ayarlı Ollama'yı çözücü kapatıp eskisini açar.
        /// </summary>
        public static bool ShouldAskBackendToRelease(bool gpuSwitched, bool backendAlive)
            => gpuSwitched && backendAlive;

        /// <summary>
        /// Program Ollama'yı kendisi açsın mı? Ayar yapıldıysa, çözücü bunu başaramadıysa
        /// (ölü / zaman aşımı / hata) ve açılacak bir komut varsa (önceden hiçbir şey
        /// çalışmıyorduysa komut yoktur) evet.
        /// </summary>
        public static bool ShouldRestoreOurselves(
            bool gpuSwitched, bool backendReleased, IReadOnlyList<string>? restoreCommand)
            => gpuSwitched && !backendReleased && restoreCommand is { Count: > 0 };
    }
}
