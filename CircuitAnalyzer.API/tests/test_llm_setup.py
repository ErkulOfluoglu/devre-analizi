"""
CircuitAnalyzer API — Yapay Zekâ Kurulum ve Yönetim Testleri

Test edilen modüller ve uç noktalar:
- llm/system_info.py (recommend, total_ram_gb, free_disk_gb, models_dir, find_ollama_app, start_ollama)
- llm/ollama.py (pick_model with preferred)
- llm/pull.py (PullManager, akış ayrıştırma, ilerleme, iptal, hata yönetimi)
- main.py (/llm/status, /llm/start, /llm/pull, /llm/pull/cancel)
"""

import shutil
import subprocess
import threading
import urllib.error
from pathlib import Path
from typing import List, Optional

import pytest

from llm import ollama, pull, system_info


# ═══════════════════════════════════════════════════════
#  YARDIMCI SAHTE SINIFLAR
# ═══════════════════════════════════════════════════════

class FakeStreamResponse:
    """urllib.request.urlopen yanıtını taklit eden içerik yöneticisi."""

    def __init__(self, lines: Optional[List[str]] = None, generator=None, on_close=None):
        self._lines = lines
        self._gen = generator
        self._on_close = on_close
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __iter__(self):
        if self._gen is not None:
            return self._gen()
        return (line.encode("utf-8") if isinstance(line, str) else line for line in self._lines or [])

    def close(self):
        self.closed = True
        if self._on_close:
            self._on_close()


class StubPullManager:
    """API uç noktası testleri için sahte PullManager."""

    def __init__(self, initial_state: Optional[pull.PullState] = None, start_ok: bool = True, cancel_ok: bool = True):
        self._state = initial_state or pull.PullState()
        self.start_ok = start_ok
        self.cancel_ok = cancel_ok
        self.started_model: Optional[str] = None
        self.cancel_called = False

    def snapshot(self) -> pull.PullState:
        return self._state

    def start(self, model: str) -> bool:
        self.started_model = model
        if self.start_ok:
            self._state = pull.PullState(model=model, state="running", message="Başlatılıyor…")
            return True
        return False

    def cancel(self) -> bool:
        self.cancel_called = True
        if self.cancel_ok:
            self._state.state = "cancelled"
            return True
        return False


# ═══════════════════════════════════════════════════════
#  1) SİSTEM BİLGİSİ VE MODEL TAVSİYESİ (system_info)
# ═══════════════════════════════════════════════════════

def test_recommend_ram_thresholds_and_messages():
    """Bellek eşiklerine göre doğru model, uygunluk seviyesi ve Türkçe mesaj üretimi."""
    cases = [
        (27.7, system_info.MODEL_LARGE, "good"),
        (15.4, system_info.MODEL_LARGE, "good"),
        (12.0, system_info.MODEL_SMALL, "ok"),
        (7.6, system_info.MODEL_SMALL, "ok"),
        (6.0, system_info.MODEL_SMALL, "low"),
        (None, system_info.MODEL_SMALL, "unknown"),
    ]
    for ram, expected_model, expected_fit in cases:
        advice = system_info.recommend(ram)
        assert advice.model == expected_model
        assert advice.fit == expected_fit
        assert isinstance(advice.message, str) and len(advice.message.strip()) > 0
        if ram is not None:
            # Bellek değeri Türkçe metinde GB olarak geçmeli (örn. "28 GB", "15 GB", "12 GB")
            gb_str = f"{ram:.0f} GB"
            assert gb_str in advice.message
        else:
            assert "Bellek ölçülemedi" in advice.message
            assert "GB" not in advice.message


def test_system_info_measurements(tmp_path):
    """total_ram_gb ve free_disk_gb fonksiyonlarının hatasız ve doğru çalışması."""
    ram = system_info.total_ram_gb()
    assert ram is None or (isinstance(ram, float) and ram > 0)

    # Var olan dizinde boş disk alanı pozitif bir float olmalı
    disk = system_info.free_disk_gb(tmp_path)
    assert disk is not None and isinstance(disk, float) and disk > 0

    # Henüz var olmayan alt dizinde üst klasörlere tırmanarak boş alanı bulmalı
    subfolder = tmp_path / "olmayan" / "alt" / "dizin"
    assert not subfolder.exists()
    disk_sub = system_info.free_disk_gb(subfolder)
    assert disk_sub is not None and isinstance(disk_sub, float) and disk_sub > 0


def test_models_dir_honours_ollama_models(tmp_path, monkeypatch):
    """OLLAMA_MODELS ortam değişkeni tanımlıysa o yol, yoksa varsayılan ~/.ollama/models yolu seçilmeli."""
    custom_path = tmp_path / "custom_models"
    monkeypatch.setenv("OLLAMA_MODELS", str(custom_path))
    assert system_info.models_dir() == custom_path

    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    assert system_info.models_dir() == Path.home() / ".ollama" / "models"


def test_find_ollama_app_and_start(tmp_path, monkeypatch):
    """LOCALAPPDATA altındaki ollama app.exe dosyasının bulunması ve Popen ile başlatılması."""
    app_dir = tmp_path / "Programs" / "Ollama"
    app_dir.mkdir(parents=True, exist_ok=True)
    fake_exe = app_dir / "ollama app.exe"
    fake_exe.touch()

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _: None)

    found = system_info.find_ollama_app()
    assert found == fake_exe

    popen_calls = []

    def fake_popen(args, **kwargs):
        popen_calls.append((args, kwargs))
        return None

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    # Uygulama varken başlatma başarılı olmalı ve subprocess.Popen bir kez exe yoluyla çağrılmalı
    assert system_info.start_ollama() is True
    assert len(popen_calls) == 1
    assert popen_calls[0][0] == [str(fake_exe)]

    # Uygulama bulunamadığında False dönmeli ve Popen çağrılmamalı
    monkeypatch.setattr(system_info, "find_ollama_app", lambda: None)
    popen_calls.clear()
    assert system_info.start_ollama() is False
    assert len(popen_calls) == 0


# ═══════════════════════════════════════════════════════
#  2) MODEL SEÇİMİ (ollama.pick_model)
# ═══════════════════════════════════════════════════════

def test_pick_model_preferred_and_fallbacks():
    """Tercih edilen model, varsayılan öneriler ve kurulu modeller hiyerarşisi."""
    installed = ["gemma4:e2b", "gemma4:e4b"]

    # preferred verilmiş ve kuruluysa doğrudan o seçilir
    assert ollama.pick_model(None, installed, preferred="gemma4:e2b") == "gemma4:e2b"

    # preferred kurulu değilse RECOMMENDED_MODEL kuruluysa o
    assert ollama.pick_model(None, ["gemma4:e4b", "diger:model"], preferred="yok:model") == ollama.RECOMMENDED_MODEL

    # RECOMMENDED_MODEL de yoksa SMALL_MODEL
    assert ollama.pick_model(None, ["gemma4:e2b", "diger:model"], preferred="yok:model") == ollama.SMALL_MODEL

    # İkisi de yoksa listedeki ilk model
    assert ollama.pick_model(None, ["ozel:1b", "ozel:2b"], preferred="yok:model") == "ozel:1b"

    # Hiçbir model kurulu değilse None
    assert ollama.pick_model(None, [], preferred="gemma4:e2b") is None


def test_pick_model_requested_priority():
    """İstenen (requested) model kuruluysa veya :latest ekiyle mevcutsa her zaman kazanır."""
    installed = ["gemma4:e2b", "gemma4:e4b", "ozel:model", "etiketsiz:latest"]

    assert ollama.pick_model("ozel:model", installed, preferred="gemma4:e2b") == "ozel:model"
    assert ollama.pick_model("etiketsiz", installed, preferred="gemma4:e2b") == "etiketsiz:latest"

    # İstenen model listede yoksa preferred modeline geri dönülür
    assert ollama.pick_model("olmayan:model", installed, preferred="gemma4:e2b") == "gemma4:e2b"


# ═══════════════════════════════════════════════════════
#  3) MODEL İNDİRME YÖNETİCİSİ (pull.PullManager)
# ═══════════════════════════════════════════════════════

def test_pull_manager_success_stream():
    """NDJSON akışı başarıyla tamamlandığında snapshot 'done' olmalı ve katman baytları toplanmalı."""
    lines = [
        '{"status":"pulling manifest"}\n',
        '{"status":"pulling abc","digest":"sha256:abc","total":1000,"completed":0}\n',
        '{"status":"pulling abc","digest":"sha256:abc","total":1000,"completed":600}\n',
        '{"status":"pulling def","digest":"sha256:def","total":1000,"completed":1000}\n',
        '{"status":"verifying sha256 digest"}\n',
        '{"status":"success"}\n',
    ]

    fake = FakeStreamResponse(lines=lines)
    mgr = pull.PullManager(opener=lambda req: fake)

    assert mgr.start("gemma4:e4b") is True
    mgr.wait()

    snap = mgr.snapshot()
    assert snap.state == "done"
    assert snap.total == 2000
    assert snap.completed >= 1600
    assert snap.percent is not None
    assert snap.percent == pytest.approx(80.0)
    assert snap.message == "Model hazır."


def test_pull_manager_second_start_rejected():
    """İndirme sürerken başlatılmak istenen ikinci indirme reddedilmeli (False)."""
    started_event = threading.Event()
    release_event = threading.Event()

    def blocking_stream():
        started_event.set()
        release_event.wait(timeout=5.0)
        yield b'{"status":"success"}\n'

    fake = FakeStreamResponse(generator=blocking_stream, on_close=release_event.set)
    mgr = pull.PullManager(opener=lambda req: fake)

    assert mgr.start("gemma4:e4b") is True
    assert started_event.wait(timeout=2.0)
    assert mgr.running is True

    # Aynı anda ikinci indirme başlatılamaz
    assert mgr.start("gemma4:e2b") is False

    release_event.set()
    mgr.wait()
    assert mgr.snapshot().state == "done"


def test_pull_manager_error_line():
    """Akıştan gelen hata mesajında durum 'error' olmalı ve model adını içermeli."""
    lines = ['{"error":"pull model manifest: file does not exist"}\n']
    fake = FakeStreamResponse(lines=lines)
    mgr = pull.PullManager(opener=lambda req: fake)

    assert mgr.start("olmayan-model") is True
    mgr.wait()

    snap = mgr.snapshot()
    assert snap.state == "error"
    assert "olmayan-model" in snap.message


def test_pull_manager_stream_ends_without_success():
    """'success' satırı gelmeden kesilen akışta durum 'error' olmalı ve bağlantı uyarısı vermeli."""
    lines = [
        '{"status":"pulling manifest"}\n',
        '{"status":"pulling abc","digest":"sha256:abc","total":1000,"completed":500}\n',
    ]
    fake = FakeStreamResponse(lines=lines)
    mgr = pull.PullManager(opener=lambda req: fake)

    assert mgr.start("gemma4:e2b") is True
    mgr.wait()

    snap = mgr.snapshot()
    assert snap.state == "error"
    assert "bağlantı" in snap.message.lower() or "internet" in snap.message.lower()


def test_pull_manager_cancel():
    """İndirme iptal edildiğinde durum 'cancelled' olmalı ve kaldığı yerden devam mesajı içermeli."""
    yielded_first = threading.Event()
    unblock_event = threading.Event()

    def cancellable_stream():
        yield b'{"status":"pulling manifest"}\n'
        yielded_first.set()
        unblock_event.wait(timeout=5.0)
        yield b'{"status":"success"}\n'

    fake = FakeStreamResponse(generator=cancellable_stream, on_close=unblock_event.set)
    mgr = pull.PullManager(opener=lambda req: fake)

    assert mgr.start("gemma4:e2b") is True
    assert yielded_first.wait(timeout=2.0)

    assert mgr.cancel() is True
    unblock_event.set()
    mgr.wait()

    snap = mgr.snapshot()
    assert snap.state == "cancelled"
    assert "kaldığı yerden" in snap.message


def test_pull_manager_opener_network_error():
    """urllib.error.URLError fırlatıldığında durum 'error' olmalı ve mesajda 'Ollama' geçmeli."""
    def broken_opener(req):
        raise urllib.error.URLError("Connection refused")

    mgr = pull.PullManager(opener=broken_opener)
    assert mgr.start("gemma4:e2b") is True
    mgr.wait()

    snap = mgr.snapshot()
    assert snap.state == "error"
    assert "Ollama" in snap.message


# ═══════════════════════════════════════════════════════
#  4) API ENDPOINT TESTLERİ (main.py)
# ═══════════════════════════════════════════════════════

def test_api_get_llm_status_not_available_with_app(client, monkeypatch):
    """Ollama kapalı ama uygulama kuruluysa ollama_installed True olmalı ve 'Başlat' tavsiyesi verilmeli."""
    monkeypatch.setattr(ollama, "get_status", lambda: ollama.OllamaStatus(available=False))
    monkeypatch.setattr(system_info, "find_ollama_app", lambda: Path("C:/fake/ollama app.exe"))
    monkeypatch.setattr(system_info, "total_ram_gb", lambda: 16.0)
    monkeypatch.setattr(system_info, "free_disk_gb", lambda: 50.0)

    resp = client.get("/llm/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert data["ollama_installed"] is True
    assert "Başlat" in data["message"]


def test_api_get_llm_status_not_available_no_app(client, monkeypatch):
    """Ollama kapalı ve kurulu değilse ollama_installed False olmalı ve 'ollama.com' indirme önerisi verilmeli."""
    monkeypatch.setattr(ollama, "get_status", lambda: ollama.OllamaStatus(available=False))
    monkeypatch.setattr(system_info, "find_ollama_app", lambda: None)
    monkeypatch.setattr(system_info, "total_ram_gb", lambda: 16.0)
    monkeypatch.setattr(system_info, "free_disk_gb", lambda: 50.0)

    resp = client.get("/llm/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert data["ollama_installed"] is False
    assert "ollama.com adresinden" in data["message"]


def test_api_get_llm_status_available_with_model(client, monkeypatch):
    """Ollama açık, gemma4:e2b kurulu ve 12 GB RAM varken doğru model ve donanım tavsiyesi dönmeli."""
    monkeypatch.setattr(ollama, "get_status", lambda: ollama.OllamaStatus(available=True, version="0.1.30", models=["gemma4:e2b"]))
    monkeypatch.setattr(system_info, "total_ram_gb", lambda: 12.0)
    monkeypatch.setattr(system_info, "free_disk_gb", lambda: 30.0)
    monkeypatch.setattr(system_info, "find_ollama_app", lambda: None)

    resp = client.get("/llm/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["recommended_model"] == "gemma4:e2b"
    assert data["fit"] == "ok"
    assert data["selected_model"] == "gemma4:e2b"
    assert data["approx_size_gb"] == pytest.approx(4.6)
    assert data["ram_gb"] == 12.0


def test_api_get_llm_status_available_no_models(client, monkeypatch):
    """Ollama açık ama model kurulu değilse mesajda 'Modeli indir' tavsiyesi geçmeli."""
    monkeypatch.setattr(ollama, "get_status", lambda: ollama.OllamaStatus(available=True, version="0.1.30", models=[]))
    monkeypatch.setattr(system_info, "total_ram_gb", lambda: 16.0)
    monkeypatch.setattr(system_info, "free_disk_gb", lambda: 30.0)

    resp = client.get("/llm/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert "Modeli indir" in data["message"]


def test_api_post_llm_start(client, monkeypatch):
    """POST /llm/start: zaten açık, başlatılıyor ve bulunamadı durumları."""
    # 1. Zaten çalışıyor -> ok=True, "zaten"
    monkeypatch.setattr(ollama, "get_status", lambda: ollama.OllamaStatus(available=True))
    resp = client.post("/llm/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "zaten" in data["message"].lower()

    # 2. Kapalı ve başlatma başarılı -> ok=True
    monkeypatch.setattr(ollama, "get_status", lambda: ollama.OllamaStatus(available=False))
    monkeypatch.setattr(system_info, "start_ollama", lambda: True)
    resp = client.post("/llm/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True

    # 3. Kapalı ve başlatma başarısız -> ok=False
    monkeypatch.setattr(system_info, "start_ollama", lambda: False)
    resp = client.post("/llm/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False


def test_api_post_llm_pull(client, monkeypatch):
    """POST /llm/pull: Ollama kapalı (503), yetersiz disk (400), çakışan indirme (409) ve model atamaları."""
    # 1. Ollama çalışmıyor -> 503
    monkeypatch.setattr(ollama, "get_status", lambda: ollama.OllamaStatus(available=False))
    resp = client.post("/llm/pull", json={})
    assert resp.status_code == 503

    # Ollama çalışır duruma getirilir
    monkeypatch.setattr(ollama, "get_status", lambda: ollama.OllamaStatus(available=True, models=[]))
    monkeypatch.setattr(system_info, "total_ram_gb", lambda: 16.0)

    # 2. Yetersiz disk alanı -> 400 ve 'yer' detayı
    monkeypatch.setattr(system_info, "free_disk_gb", lambda: 3.0)
    resp_disk = client.post("/llm/pull", json={})
    assert resp_disk.status_code == 400
    assert "yer" in resp_disk.json()["detail"].lower()

    # Disk yeterli seviyeye getirilir
    monkeypatch.setattr(system_info, "free_disk_gb", lambda: 50.0)

    # 3. Normal başlatma (boş gövde): RAM'e göre önerilen model (16 GB -> gemma4:e4b)
    stub_mgr = StubPullManager()
    monkeypatch.setattr(pull, "MANAGER", stub_mgr)
    resp_default = client.post("/llm/pull", json={})
    assert resp_default.status_code == 200
    data_default = resp_default.json()
    assert data_default["state"] == "running"
    assert stub_mgr.started_model == system_info.MODEL_LARGE
    assert data_default["model"] == system_info.MODEL_LARGE

    # 4. Normal başlatma (belirtilen model): model parametresi aktarılır
    stub_mgr_custom = StubPullManager()
    monkeypatch.setattr(pull, "MANAGER", stub_mgr_custom)
    resp_custom = client.post("/llm/pull", json={"model": "ozel-model:v1"})
    assert resp_custom.status_code == 200
    assert stub_mgr_custom.started_model == "ozel-model:v1"

    # 5. İndirme zaten sürüyorsa -> 409
    stub_mgr_busy = StubPullManager(start_ok=False)
    monkeypatch.setattr(pull, "MANAGER", stub_mgr_busy)
    resp_conflict = client.post("/llm/pull", json={})
    assert resp_conflict.status_code == 409
    assert "zaten sürüyor" in resp_conflict.json()["detail"]


def test_api_get_llm_pull_and_cancel(client, monkeypatch):
    """GET /llm/pull snapshot alanları (yuvarlanmış yüzde, tam sayı/null eta) ve POST /llm/pull/cancel kontrolü."""
    # GET: aktif indirme durumu, float yuvarlamaları
    active_state = pull.PullState(
        model="gemma4:e2b",
        state="running",
        completed=750,
        total=1000,
        speed_bps=250000.45,
        eta_seconds=1.23,
        message="İndiriliyor…",
    )
    stub_mgr = StubPullManager(initial_state=active_state)
    monkeypatch.setattr(pull, "MANAGER", stub_mgr)

    resp_get = client.get("/llm/pull")
    assert resp_get.status_code == 200
    data_get = resp_get.json()
    assert data_get["model"] == "gemma4:e2b"
    assert data_get["state"] == "running"
    assert data_get["completed_bytes"] == 750
    assert data_get["total_bytes"] == 1000
    assert data_get["percent"] == 75.0
    assert data_get["speed_bps"] == 250000.5
    assert data_get["eta_seconds"] == 1
    assert data_get["message"] == "İndiriliyor…"

    # GET: tamamlanmamış / boş durumda None eta ve percent
    idle_state = pull.PullState(
        model=None,
        state="idle",
        completed=0,
        total=0,
        speed_bps=0.0,
        eta_seconds=None,
        message="",
    )
    stub_mgr_idle = StubPullManager(initial_state=idle_state)
    monkeypatch.setattr(pull, "MANAGER", stub_mgr_idle)
    resp_idle = client.get("/llm/pull")
    assert resp_idle.status_code == 200
    assert resp_idle.json()["percent"] is None
    assert resp_idle.json()["eta_seconds"] is None

    # POST cancel: başarılı
    stub_mgr_cancel_ok = StubPullManager(cancel_ok=True)
    monkeypatch.setattr(pull, "MANAGER", stub_mgr_cancel_ok)
    resp_cancel_ok = client.post("/llm/pull/cancel")
    assert resp_cancel_ok.status_code == 200
    assert resp_cancel_ok.json()["ok"] is True

    # POST cancel: başarısız (iptal edilecek indirme yok)
    stub_mgr_cancel_fail = StubPullManager(cancel_ok=False)
    monkeypatch.setattr(pull, "MANAGER", stub_mgr_cancel_fail)
    resp_cancel_fail = client.post("/llm/pull/cancel")
    assert resp_cancel_fail.status_code == 200
    assert resp_cancel_fail.json()["ok"] is False
