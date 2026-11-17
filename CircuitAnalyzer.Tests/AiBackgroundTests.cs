using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
using CircuitAnalyzer.WPF.Services;
using Xunit;

namespace CircuitAnalyzer.Tests;

/// <summary>
/// Yapay zekâ süreçlerinin sahipliği: "Başlat" ile açılan Ollama program kapanınca açık kalır,
/// FastFlowLM / ekran kartı ayarlı Ollama kapanır; ekran kartı ayarında geri açma kararları.
///
/// GÜVENLİK: Gerçek Ollama/flm'ye dokunulmaz. Tek gerçek süreçler bu testlerin kendi açtığı
/// zararsız "python -c time.sleep" süreçleridir; finally içinde mutlaka kapatılır.
/// </summary>
public class AiBackgroundTests
{
    private const string SleeperPy = "import time; time.sleep(60)";

    // Ana süreç: biri CREATE_BREAKAWAY_FROM_JOB (0x01000000) ile, biri bayraksız iki uyuyan süreç açar
    // ve PID'lerini yazdırır.
    private const string ParentPy =
        "import subprocess, sys, time\n" +
        "sl = ['python', '-c', 'import time; time.sleep(60)']\n" +
        "a = subprocess.Popen(sl, creationflags=0x01000000)\n" +
        "b = subprocess.Popen(sl)\n" +
        "print(a.pid, b.pid, flush=True)\n" +
        "time.sleep(60)\n";

    private static Process StartParent(string script)
    {
        var psi = new ProcessStartInfo("python")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        psi.ArgumentList.Add("-c");
        psi.ArgumentList.Add(script);
        return Process.Start(psi)!;
    }

    private static (int Breakaway, int InJob) ReadPids(Process parent)
    {
        var line = parent.StandardOutput.ReadLineAsync();
        Assert.True(line.Wait(TimeSpan.FromSeconds(20)), "ana süreç PID yazmadı: " + ReadErr(parent));
        var parts = (line.Result ?? "").Split(' ');
        Assert.True(parts.Length == 2, "beklenmeyen çıktı: '" + line.Result + "' " + ReadErr(parent));
        return (int.Parse(parts[0]), int.Parse(parts[1]));
    }

    private static string ReadErr(Process p)
    {
        try
        {
            if (!p.HasExited) return "";
            return p.StandardError.ReadToEnd();
        }
        catch { return ""; }
    }

    private static bool IsAlive(int pid)
    {
        try
        {
            using var p = Process.GetProcessById(pid);
            return !p.WaitForExit(0);
        }
        catch (ArgumentException) { return false; }
        catch (InvalidOperationException) { return false; }
    }

    private static bool WaitUntilDead(int pid, int ms = 8000)
    {
        var sw = Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < ms)
        {
            if (!IsAlive(pid)) return true;
            Thread.Sleep(50);
        }
        return !IsAlive(pid);
    }

    private static void KillQuietly(int pid)
    {
        try { using var p = Process.GetProcessById(pid); p.Kill(); } catch { }
    }

    [Fact]
    public void JobObject_AllowsBreakaway_ButNotSilently()
    {
        // Win32 JOBOBJECT_BASIC_LIMIT_INFORMATION değerleri
        Assert.Equal(0x00000800u, BackendManager.JobObject.JOB_OBJECT_LIMIT_BREAKAWAY_OK);
    }

    [Fact]
    public void Stop_KeepsTheBreakawayChild_AndKillsTheOneInTheJob()
    {
        Process? parent = null;
        BackendManager.JobObject? job = null;
        int a = 0, b = 0;
        try
        {
            parent = StartParent(ParentPy);
            job = new BackendManager.JobObject();
            job.Assign(parent);
            (a, b) = ReadPids(parent);
            Assert.True(IsAlive(a) && IsAlive(b), "iki uyuyan süreç de başta açık olmalı");

            // Backend Stop() ile aynı dizi: yalnız ana süreci öldür, sonra işi kapat
            BackendManager.StopProcessAndJob(parent, job);
            job = null;

            Assert.True(WaitUntilDead(b), "işin içindeki çocuk kapanmalı (FastFlowLM / ekran kartı ayarlı Ollama gibi)");
            Assert.True(parent.WaitForExit(5000), "ana süreç kapanmalı");
            Assert.True(IsAlive(a), "iş nesnesinden ayrılan çocuk (\"Başlat\" ile açılan Ollama gibi) açık kalmalı");
        }
        finally
        {
            job?.Dispose();
            if (parent != null) { try { if (!parent.HasExited) parent.Kill(true); } catch { } parent.Dispose(); }
            if (a != 0) KillQuietly(a);
            if (b != 0) KillQuietly(b);
        }
    }

    [Fact]
    public void Stop_WithoutAJob_FallsBackToKillingTheWholeTree()
    {
        Process? parent = null;
        int a = 0, b = 0;
        try
        {
            parent = StartParent(ParentPy);
            (a, b) = ReadPids(parent);

            BackendManager.StopProcessAndJob(parent, null);

            Assert.True(parent.WaitForExit(5000));
            Assert.True(WaitUntilDead(b), "iş nesnesi yoksa süreç ağacı kapanmalı");
            Assert.True(WaitUntilDead(a), "iş nesnesi yoksa süreç ağacı kapanmalı");
        }
        finally
        {
            if (parent != null) { try { if (!parent.HasExited) parent.Kill(true); } catch { } parent.Dispose(); }
            if (a != 0) KillQuietly(a);
            if (b != 0) KillQuietly(b);
        }
    }

    [Fact]
    public void Stop_OnAnAlreadyExitedProcess_StillClosesTheJob()
    {
        var job = new BackendManager.JobObject();
        using var parent = StartParent("print('x')");
        parent.WaitForExit(10000);
        BackendManager.StopProcessAndJob(parent, job);   // fırlatmamalı
    }

    // ── Karar işlevleri ──

    [Theory]
    [InlineData(true, true, true)]
    [InlineData(true, false, false)]    // çözücü ölü: istek yapılmaz
    [InlineData(false, true, false)]    // ayar hiç yapılmadı
    [InlineData(false, false, false)]
    public void ShouldAskBackendToRelease(bool switched, bool alive, bool expected)
        => Assert.Equal(expected, GpuRestorePolicy.ShouldAskBackendToRelease(switched, alive));

    [Fact]
    public void ShouldRestoreOurselves_OnlyWhenSwitchedBackendFailedAndThereIsACommand()
    {
        var cmd = new List<string> { @"C:\o\ollama app.exe" };
        Assert.True(GpuRestorePolicy.ShouldRestoreOurselves(true, false, cmd));       // çözücü ölü / zaman aşımı
        Assert.False(GpuRestorePolicy.ShouldRestoreOurselves(true, true, cmd));       // çözücü zaten yaptı
        Assert.False(GpuRestorePolicy.ShouldRestoreOurselves(false, false, cmd));     // ayar yapılmadı
        Assert.False(GpuRestorePolicy.ShouldRestoreOurselves(true, false, null));     // önceden Ollama kapalıydı
        Assert.False(GpuRestorePolicy.ShouldRestoreOurselves(true, false, new List<string>()));
    }

    [Fact]
    public void GpuEnableResult_ReadsTheServerJson()
    {
        const string json = "{\"ok\":true,\"message\":\"tamam\",\"restore_command\":[\"C:\\\\o\\\\ollama app.exe\"]}";
        var dto = System.Text.Json.JsonSerializer.Deserialize<LlmActionResultDto>(json)!;
        Assert.True(dto.Ok);
        Assert.Equal(new[] { @"C:\o\ollama app.exe" }, dto.RestoreCommand);
        var none = System.Text.Json.JsonSerializer.Deserialize<LlmActionResultDto>("{\"ok\":false,\"message\":\"m\"}")!;
        Assert.Null(none.RestoreCommand);
    }

    [Fact]
    public void ReleaseTimeout_IsShortEnoughForTheClosingWindow()
        => Assert.True(BackendManager.GpuReleaseTimeout <= TimeSpan.FromSeconds(8));
}
