"""
CircuitAnalyzer API — Yapay zekâ süreçlerinin sahipliği

Test edilen:
- llm/devices.py: parse_tasklist, ollama_state, restore_command_for, restart_ollama_with_igpu,
  release_igpu, npu_info (tek denetim, kilitsiz bekleme)
- llm/system_info.py: spawn_surviving (iş nesnesinden ayrılma + yedek deneme)
- main.py: POST /llm/gpu/enable (indirme sürerken reddeder), POST /llm/gpu/release

GÜVENLİK: Hiçbir test gerçek taskkill/tasklist çalıştırmaz, gerçek Ollama ya da flm'ye
dokunmaz; süreç açma/kapama işlevleri sahte olanlarla değiştirilir.
"""

import subprocess
import threading
import time
from pathlib import Path

import pytest

from llm import devices, pull, system_info


# ═══════════════════════════════════════════════════════
#  tasklist çıktısı
# ═══════════════════════════════════════════════════════

TASKLIST_TRAY = (
    '"System Idle Process","0","Services","0","8 K"\n'
    '"ollama app.exe","4321","Console","1","61.234 K"\n'
    '"ollama.exe","5678","Console","1","1,024,000 K"\n'
)
TASKLIST_SERVE = '"OLLAMA.EXE","5678","Console","1","61.234 K"\n"python.exe","99","Console","1","10 K"\n'
TASKLIST_TURKISH_NONE = "BİLGİ: Belirtilen ölçütlere uyan görev çalışmıyor.\n"
TASKLIST_TURKISH_TRAY = (
    '"Sistem Boşta İşlemi","0","Services","0","8 K"\n'
    '"ollama app.exe","4321","Console","1","61.234 K"\n'
)


def test_parse_tasklist_names_are_lowercase():
    assert {"ollama app.exe", "ollama.exe"} <= devices.parse_tasklist(TASKLIST_TRAY)
    assert "ollama.exe" in devices.parse_tasklist(TASKLIST_SERVE)


def test_parse_tasklist_turkish_locale():
    assert devices.parse_tasklist(TASKLIST_TURKISH_NONE) == set()
    assert "ollama app.exe" in devices.parse_tasklist(TASKLIST_TURKISH_TRAY)


@pytest.mark.parametrize("text, state", [
    (TASKLIST_TRAY, "tray"),
    (TASKLIST_TURKISH_TRAY, "tray"),
    (TASKLIST_SERVE, "serve"),
    (TASKLIST_TURKISH_NONE, "none"),
    ("", "none"),
])
def test_ollama_state(text, state):
    assert devices.ollama_state(devices.parse_tasklist(text)) == state


def test_restore_command_for(tmp_path):
    app = tmp_path / "ollama app.exe"
    (tmp_path / "ollama.exe").touch()
    assert devices.restore_command_for("none", app) is None
    assert devices.restore_command_for("serve", app) == [str(tmp_path / "ollama.exe"), "serve"]
    # tepsi uygulaması dosyası yoksa sunucuyla yetinilir
    assert devices.restore_command_for("tray", app) == [str(tmp_path / "ollama.exe"), "serve"]
    app.touch()
    assert devices.restore_command_for("tray", app) == [str(app)]


# ═══════════════════════════════════════════════════════
#  Ekran kartı ayarı: kaydet, kapat, başlat, geri aç
# ═══════════════════════════════════════════════════════

class SpyProc:
    pid = 777

    def __init__(self):
        self.alive = True
        self.waited = None

    def poll(self):
        return None if self.alive else 0

    def wait(self, timeout=None):
        self.waited = timeout
        self.alive = False

    def kill(self):
        self.alive = False


@pytest.fixture
def ollama_world(monkeypatch, tmp_path):
    """Sahte Ollama kurulumu; kapatılan/başlatılan her şey `events` listesine yazılır."""
    app = tmp_path / "ollama app.exe"
    app.touch()
    (tmp_path / "ollama.exe").touch()
    events = []
    world = {"events": events, "tasklist": TASKLIST_TRAY, "app": app, "proc": SpyProc()}

    monkeypatch.setattr(system_info, "find_ollama_app", lambda: app)
    monkeypatch.setattr(devices, "_tasklist", lambda: world["tasklist"])
    monkeypatch.setattr(devices, "_kill_image", lambda image: events.append(("kill_image", image)))
    monkeypatch.setattr(devices, "_kill_tree", lambda pid: events.append(("kill_tree", pid)))
    monkeypatch.setattr(devices, "_pause", lambda s: None)
    monkeypatch.setattr(devices, "_ollama_answers", lambda: False)
    monkeypatch.setattr(devices, "_start_igpu_ollama",
                        lambda exe: events.append(("start_igpu", str(exe))) or world["proc"])
    monkeypatch.setattr(system_info, "spawn_surviving",
                        lambda args: events.append(("spawn", list(args))) or True)
    monkeypatch.setattr(devices.sys, "platform", "win32")
    return world


def test_enable_records_what_ran_and_release_restores_the_tray_app(ollama_world):
    ev = ollama_world["events"]
    assert devices.restart_ollama_with_igpu() is True
    assert [e[0] for e in ev] == ["kill_image", "kill_image", "start_igpu"]
    assert devices.igpu_enabled()
    assert devices.igpu_restore_command() == [str(ollama_world["app"])]

    ev.clear()
    ok, _ = devices.release_igpu()
    assert ok
    assert ev == [("kill_tree", 777), ("spawn", [str(ollama_world["app"])])]
    assert ollama_world["proc"].waited == devices.RELEASE_WAIT_SECONDS
    assert not devices.igpu_enabled()
    assert devices.igpu_restore_command() is None


def test_release_restores_a_bare_serve(ollama_world, tmp_path):
    ollama_world["tasklist"] = TASKLIST_SERVE
    devices.restart_ollama_with_igpu()
    ollama_world["events"].clear()
    devices.release_igpu()
    assert ollama_world["events"][-1] == ("spawn", [str(tmp_path / "ollama.exe"), "serve"])


def test_release_restores_nothing_when_nothing_was_running(ollama_world):
    ollama_world["tasklist"] = TASKLIST_TURKISH_NONE
    devices.restart_ollama_with_igpu()
    assert devices.igpu_restore_command() is None
    ollama_world["events"].clear()
    ok, _ = devices.release_igpu()
    assert ok and ollama_world["events"] == [("kill_tree", 777)]


def test_release_is_idempotent_and_quick_when_nothing_to_do(ollama_world):
    ok, _ = devices.release_igpu()
    assert ok and ollama_world["events"] == []
    devices.restart_ollama_with_igpu()
    devices.release_igpu()
    ollama_world["events"].clear()
    assert devices.release_igpu()[0] and ollama_world["events"] == []


def test_enable_twice_does_not_kill_again(ollama_world):
    devices.restart_ollama_with_igpu()
    ollama_world["events"].clear()
    assert devices.restart_ollama_with_igpu() is True
    assert ollama_world["events"] == []
    assert devices.igpu_restore_command() == [str(ollama_world["app"])]


def test_simultaneous_enable_calls_start_one_ollama(ollama_world, monkeypatch):
    gate = threading.Event()
    starts = []

    def slow_start(exe):
        starts.append(1)
        gate.wait(5)
        return ollama_world["proc"]
    monkeypatch.setattr(devices, "_start_igpu_ollama", slow_start)
    results = []
    threads = [threading.Thread(target=lambda: results.append(devices.restart_ollama_with_igpu()))
               for _ in range(2)]
    for t in threads:
        t.start()
    time.sleep(0.3)
    gate.set()
    for t in threads:
        t.join(5)
    assert results == [True, True]
    assert len(starts) == 1
    assert [e for e in ollama_world["events"] if e[0] == "kill_image"] == [
        ("kill_image", "ollama app.exe"), ("kill_image", "ollama.exe")]


def test_failed_start_brings_the_users_ollama_back(ollama_world, monkeypatch):
    def boom(exe):
        raise OSError("başlatılamadı")
    monkeypatch.setattr(devices, "_start_igpu_ollama", boom)
    assert devices.restart_ollama_with_igpu() is False
    assert ollama_world["events"][-1] == ("spawn", [str(ollama_world["app"])])
    assert not devices.igpu_enabled()


def test_igpu_enabled_follows_the_process(monkeypatch):
    p = SpyProc()
    monkeypatch.setattr(devices, "_igpu_proc", p)
    assert devices.igpu_enabled()
    p.alive = False                    # Ollama'mız öldü: bayrak takılı kalmasın
    assert not devices.igpu_enabled()
    monkeypatch.setenv("OLLAMA_IGPU_ENABLE", "1")
    assert devices.igpu_enabled()


def test_dead_igpu_ollama_is_not_restored_over_a_running_one(ollama_world, monkeypatch):
    devices.restart_ollama_with_igpu()
    ollama_world["proc"].alive = False
    monkeypatch.setattr(devices, "_ollama_answers", lambda: True)
    ollama_world["events"].clear()
    assert devices.release_igpu()[0]
    assert ollama_world["events"] == []


# ═══════════════════════════════════════════════════════
#  Uç noktalar
# ═══════════════════════════════════════════════════════

def test_gpu_enable_is_refused_while_a_download_runs(client, monkeypatch):
    called = []
    monkeypatch.setattr(devices, "restart_ollama_with_igpu", lambda: called.append(1) or True)
    monkeypatch.setattr(type(pull.MANAGER), "running", property(lambda self: True))
    data = client.post("/llm/gpu/enable").json()
    assert data["ok"] is False and "indirmesi sürüyor" in data["message"]
    assert called == []


def test_gpu_enable_reports_the_restore_command(client, monkeypatch):
    monkeypatch.setattr(devices, "restart_ollama_with_igpu", lambda: True)
    monkeypatch.setattr(devices, "_igpu_restore", ["C:\\o\\ollama app.exe"])
    data = client.post("/llm/gpu/enable").json()
    assert data["ok"] is True and data["restore_command"] == ["C:\\o\\ollama app.exe"]


def test_gpu_release_endpoint(client, monkeypatch):
    monkeypatch.setattr(devices, "release_igpu", lambda: (True, "Ollama eski hâliyle yeniden açılıyor."))
    data = client.post("/llm/gpu/release").json()
    assert data == {"ok": True, "message": "Ollama eski hâliyle yeniden açılıyor.", "restore_command": None}


# ═══════════════════════════════════════════════════════
#  "Başlat": Ollama programdan bağımsız açılır
# ═══════════════════════════════════════════════════════

def test_start_ollama_breaks_away_from_the_job(monkeypatch, tmp_path):
    app = tmp_path / "ollama app.exe"
    monkeypatch.setattr(system_info, "find_ollama_app", lambda: app)
    monkeypatch.setattr(system_info.sys, "platform", "win32")
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: calls.append(kw["creationflags"]))
    assert system_info.start_ollama() is True
    assert len(calls) == 1 and calls[0] & subprocess.CREATE_BREAKAWAY_FROM_JOB


def test_start_ollama_retries_without_breakaway_when_the_job_forbids_it(monkeypatch, tmp_path):
    app = tmp_path / "ollama app.exe"
    monkeypatch.setattr(system_info, "find_ollama_app", lambda: app)
    monkeypatch.setattr(system_info.sys, "platform", "win32")
    calls = []

    def popen(args, **kw):
        calls.append(kw["creationflags"])
        if kw["creationflags"] & subprocess.CREATE_BREAKAWAY_FROM_JOB:
            raise PermissionError(5, "Erişim engellendi")
    monkeypatch.setattr(subprocess, "Popen", popen)
    assert system_info.start_ollama() is True
    assert len(calls) == 2
    assert calls[0] & subprocess.CREATE_BREAKAWAY_FROM_JOB and not calls[1] & subprocess.CREATE_BREAKAWAY_FROM_JOB


def test_start_ollama_fails_cleanly_when_both_attempts_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(system_info, "find_ollama_app", lambda: tmp_path / "ollama app.exe")
    monkeypatch.setattr(system_info.sys, "platform", "win32")

    def popen(args, **kw):
        raise OSError("yok")
    monkeypatch.setattr(subprocess, "Popen", popen)
    assert system_info.start_ollama() is False


# ═══════════════════════════════════════════════════════
#  NPU denetimi başka işleri bekletmez
# ═══════════════════════════════════════════════════════

class SlowProbe:
    """Olayla yönetilen sahte denetim: release() denilene kadar bitmez."""

    def __init__(self, result=None):
        self.release = threading.Event()
        self.started = threading.Event()
        self.calls = 0
        self.result = result or devices.NpuInfo(True, None, "", ["gemma4-it:e4b"])

    def __call__(self):
        self.calls += 1
        self.started.set()
        self.release.wait(10)
        return self.result


def _wait_probe_idle():
    deadline = time.time() + 5
    while devices._probe_event is not None and time.time() < deadline:
        time.sleep(0.01)
    assert devices._probe_event is None


def test_flm_lock_is_free_while_a_slow_probe_runs(monkeypatch):
    probe = SlowProbe()
    monkeypatch.setattr(devices, "_probe_npu", probe)
    out = []
    t = threading.Thread(target=lambda: out.append(devices.npu_info("gemma4:e4b")))
    t.start()
    assert probe.started.wait(5)
    try:
        assert devices._lock.acquire(timeout=0.5), "FastFlowLM kilidi denetim yüzünden kilitli"
        devices._lock.release()
        monkeypatch.setattr(devices, "flm_running", lambda: False)
        monkeypatch.setattr(devices, "find_flm", lambda: None)
        t0 = time.time()
        assert devices.ensure_flm("gemma4-it:e4b") is False   # flm yok: hemen döner
        devices.stop_flm()
        assert time.time() - t0 < 1.0
    finally:
        probe.release.set()
        t.join(5)
    assert out and out[0].available


def test_stale_cache_returns_at_once_and_refreshes_once_in_background(monkeypatch):
    old = devices.NpuInfo(True, None, "", ["gemma4-it:e4b"])
    monkeypatch.setattr(devices, "_npu_cached", old)
    monkeypatch.setattr(devices, "_npu_cached_at", time.time() - devices.CACHE_SECONDS - 1)
    fresh = devices.NpuInfo(False, None, "NPU kapandı")
    probe = SlowProbe(fresh)
    monkeypatch.setattr(devices, "_probe_npu", probe)

    t0 = time.time()
    first = devices.npu_info("gemma4:e4b")
    second = devices.npu_info("gemma4:e4b")
    assert time.time() - t0 < 1.0
    assert first.available and second.available          # eski değer hemen verildi
    assert probe.started.wait(5)
    probe.release.set()
    _wait_probe_idle()
    assert probe.calls == 1                               # iki çağrıya rağmen tek yenileme
    assert devices._npu_cached is fresh
    assert not devices.npu_info("gemma4:e4b").available


def test_cold_cache_waits_for_the_probe_result(monkeypatch):
    probe = SlowProbe()
    monkeypatch.setattr(devices, "_probe_npu", probe)
    out = []
    t = threading.Thread(target=lambda: out.append(devices.npu_info("gemma4:e4b")))
    t.start()
    assert probe.started.wait(5)
    time.sleep(0.2)
    assert out == []                                      # "NPU yok" diye erken cevap verilmedi
    probe.release.set()
    t.join(5)
    assert out[0].available and out[0].model == "gemma4-it:e4b"


def test_two_cold_callers_cause_one_probe(monkeypatch):
    probe = SlowProbe()
    monkeypatch.setattr(devices, "_probe_npu", probe)
    out = []
    threads = [threading.Thread(target=lambda: out.append(devices.npu_info("gemma4:e4b")))
               for _ in range(2)]
    threads[0].start()
    assert probe.started.wait(5)
    threads[1].start()
    time.sleep(0.2)
    probe.release.set()
    for t in threads:
        t.join(5)
    assert probe.calls == 1
    assert len(out) == 2 and all(o.available for o in out)


def test_refresh_true_forces_a_new_probe(monkeypatch):
    probe = SlowProbe()
    probe.release.set()
    monkeypatch.setattr(devices, "_probe_npu", probe)
    devices.npu_info("gemma4:e4b")
    devices.npu_info("gemma4:e4b")
    assert probe.calls == 1                               # tazeyken önbellekten
    devices.npu_info("gemma4:e4b", refresh=True)
    assert probe.calls == 2


def test_a_crashing_probe_does_not_leave_callers_hanging(monkeypatch):
    def boom():
        raise RuntimeError("flm çöktü")
    monkeypatch.setattr(devices, "_probe_npu", boom)
    info = devices.npu_info("gemma4:e4b")
    assert not info.available and info.reason
