"""
CircuitAnalyzer API — Yapay zekânın çalıştığı yer (ekran kartı, işlemci, NPU)

Öğrenci "Çalıştığı yer" ayarından seçer:

    auto  → NPU kullanılabiliyorsa NPU, değilse Ollama'nın kendi tercihi
    gpu   → Ollama, ekran kartı açık (tümleşik AMD/Intel kartlarda Ollama'nın
            OLLAMA_IGPU_ENABLE=1 ile yeniden başlatılması gerekir; öğrenci onaylar)
    cpu   → Ollama, ekran kartı kapalı (istekte num_gpu = 0)
    npu   → FastFlowLM (yalnız AMD Ryzen AI NPU'larında; ayrı kurulur)

FastFlowLM Ollama ile aynı uç noktaları konuşur (/api/chat, /api/tags), bu
yüzden aynı istemci yalnız adres ve model adı değiştirilerek kullanılır.
NPU'nun uygun olup olmadığına FastFlowLM'in kendi denetimi ("flm validate")
karar verir; işlemcinin adına bakılmaz.

Programın başlattığı süreçler (FastFlowLM sunucusu, ekran kartı ayarlı Ollama)
arka ucun iş nesnesine (Job Object) bağlıdır: program kapanınca onlar da kapanır.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from llm import system_info

AUTO, GPU, CPU, NPU = "auto", "gpu", "cpu", "npu"
DEVICES = (AUTO, GPU, CPU, NPU)

FLM_HOST = "http://127.0.0.1:52625"
# Ollama modeli → aynı modelin FastFlowLM (NPU) sürümü
NPU_MODELS: Dict[str, str] = {"gemma4:e4b": "gemma4-it:e4b", "gemma4:e2b": "gemma4-it:e2b"}
NPU_PREFERRED = ("gemma4-it:e4b", "gemma4-it:e2b")
NPU_CTX = 8192
NPU_START_TIMEOUT = 90.0
CACHE_SECONDS = 600.0   # flm validate ~4 sn sürer; NPU ve modeller sık değişmez

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


# ── FastFlowLM (NPU) ──

def find_flm() -> Optional[Path]:
    """Kurulu FastFlowLM'in flm.exe dosyası (yoksa None)."""
    candidates = []
    program_files = os.environ.get("ProgramFiles", "")
    if program_files:
        candidates.append(Path(program_files) / "flm" / "flm.exe")
    found = shutil.which("flm")
    if found:
        candidates.append(Path(found))
    for c in candidates:
        if c.is_file():
            return c
    return None


def _run_json(args: List[str], timeout: float = 20.0) -> Optional[dict]:
    try:
        out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout, creationflags=_NO_WINDOW)
        text = out.stdout.strip()
        start = text.find("{")
        return json.loads(text[start:]) if start >= 0 else None
    except Exception:
        return None


@dataclass
class NpuInfo:
    available: bool
    model: Optional[str] = None      # FastFlowLM model adı (ör. gemma4-it:e4b)
    reason: str = ""                 # kullanılamıyorsa Türkçe sebep
    installed_models: List[str] = field(default_factory=list)


_npu_cached: Optional[NpuInfo] = None
_npu_cached_at = 0.0
_lock = threading.Lock()


def npu_info(ollama_model: Optional[str] = None, refresh: bool = False) -> NpuInfo:
    """NPU kullanılabilir mi? (FastFlowLM kurulu + NPU hazır + uygun model var)"""
    global _npu_cached, _npu_cached_at
    with _lock:
        if not refresh and _npu_cached is not None and time.time() - _npu_cached_at < CACHE_SECONDS:
            base = _npu_cached
        else:
            base = _probe_npu()
            _npu_cached, _npu_cached_at = base, time.time()
    if not base.installed_models:
        return base
    wanted = NPU_MODELS.get(ollama_model or "")
    model = wanted if wanted in base.installed_models else next(
        (m for m in NPU_PREFERRED if m in base.installed_models), None)
    if model is None:
        return NpuInfo(False, None, "NPU için uygun model kurulu değil (gemma4-it:e4b).",
                       base.installed_models)
    return NpuInfo(True, model, "", base.installed_models)


def warm_up():
    """Program açılırken NPU denetimini arka planda yapar; kart açılınca beklenmesin."""
    threading.Thread(target=lambda: npu_info(refresh=True), daemon=True).start()


def _probe_npu() -> NpuInfo:
    flm = find_flm()
    if flm is None:
        return NpuInfo(False, None, "Bu bilgisayarda FastFlowLM kurulu değil.")
    v = _run_json([str(flm), "validate", "--json"])
    if not v or not v.get("ready"):
        return NpuInfo(False, None, "Bu bilgisayarda uygun NPU yok (AMD Ryzen AI 300 serisi gerekir).")
    lst = _run_json([str(flm), "list", "--filter", "installed", "--json"]) or {}
    names = [m.get("name") or m.get("model") for m in lst.get("models", [])]
    names = [n for n in names if n]
    if not names:
        return NpuInfo(False, None, "NPU için uygun model kurulu değil (gemma4-it:e4b).")
    return NpuInfo(True, None, "", names)


def flm_running() -> bool:
    try:
        with urllib.request.urlopen(FLM_HOST + "/api/version", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


_flm_proc: Optional[subprocess.Popen] = None


def ensure_flm(model: str) -> bool:
    """FastFlowLM sunucusu kapalıysa başlatır ve hazır olmasını bekler."""
    global _flm_proc
    if flm_running():
        return True
    flm = find_flm()
    if flm is None:
        return False
    with _lock:
        if _flm_proc is None or _flm_proc.poll() is not None:
            try:
                _flm_proc = subprocess.Popen(
                    [str(flm), "serve", model, "--ctx-len", str(NPU_CTX), "--quiet"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=_NO_WINDOW)
            except Exception:
                return False
    deadline = time.time() + NPU_START_TIMEOUT
    while time.time() < deadline:
        if flm_running():
            return True
        if _flm_proc is not None and _flm_proc.poll() is not None:
            return False
        time.sleep(0.5)
    return False


# ── Ekran kartı ──

@dataclass
class GpuInfo:
    kind: str     # "dedicated" (Ollama kendiliğinden kullanır) | "integrated" (ayar gerekir) | "none"
    name: str = ""


def _display_adapters() -> List[str]:
    """Windows'taki ekran bağdaştırıcılarının adları (EnumDisplayDevices; hızlı)."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                    ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                    ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]

    names, i = [], 0
    try:
        while True:
            d = DISPLAY_DEVICEW()
            d.cb = ctypes.sizeof(d)
            if not ctypes.windll.user32.EnumDisplayDevicesW(None, i, ctypes.byref(d), 0):
                break
            if d.DeviceString and d.DeviceString not in names:
                names.append(d.DeviceString)
            i += 1
    except Exception:
        pass
    return names


def classify_gpu(names: List[str]) -> GpuInfo:
    """Ada göre: NVIDIA ve ayrık AMD/Intel kartları Ollama kendisi kullanır; tümleşikler ayar ister."""
    best = GpuInfo("none")
    for n in names:
        low = n.lower()
        if "nvidia" in low:
            return GpuInfo("dedicated", n)
        if ("radeon" in low or "amd" in low) and any(k in low for k in (" rx ", "rx ", "radeon pro")):
            best = GpuInfo("dedicated", n)
        elif "intel" in low and "arc" in low and best.kind != "dedicated":
            best = GpuInfo("dedicated", n)
        elif ("radeon" in low or "intel" in low) and best.kind == "none":
            best = GpuInfo("integrated", n)
    return best


def gpu_info() -> GpuInfo:
    return classify_gpu(_display_adapters())


def igpu_enabled() -> bool:
    """Çalışan Ollama'ya tümleşik kart ayarı verildi mi (bizim başlattığımız ya da kullanıcı ortamı)?"""
    return _igpu_started or os.environ.get("OLLAMA_IGPU_ENABLE", "").strip() == "1"


_igpu_started = False


def restart_ollama_with_igpu() -> bool:
    """
    Ollama'yı kapatıp OLLAMA_IGPU_ENABLE=1 ile yeniden başlatır (yalnız bu süreç
    için; Windows ayarı değişmez). Program kapanınca bu Ollama da kapanır.
    """
    global _igpu_started
    app = system_info.find_ollama_app()
    if app is None:
        return False
    exe = app.with_name("ollama.exe")
    if not exe.is_file():
        return False
    if sys.platform == "win32":
        # /T: modeli tutan alt süreçler (llama-server) de kapansın, RAM'de kalmasın
        for image in ("ollama app.exe", "ollama.exe"):
            subprocess.run(["taskkill", "/F", "/T", "/IM", image], capture_output=True,
                           creationflags=_NO_WINDOW)
        time.sleep(1.0)
    env = dict(os.environ, OLLAMA_IGPU_ENABLE="1")
    try:
        subprocess.Popen([str(exe), "serve"], env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    except Exception:
        return False
    _igpu_started = True
    return True


# ── Seçim ──

@dataclass
class Route:
    where: str                     # "npu" | "gpu" | "cpu" | "ollama" (Ollama karar verir)
    base_url: Optional[str]        # None → Ollama'nın adresi
    model: str
    options: Dict[str, object] = field(default_factory=dict)


class DeviceUnavailable(Exception):
    """Seçilen yer bu bilgisayarda kullanılamıyor (Türkçe sebep ile)."""


def auto_choice(npu: NpuInfo, gpu: GpuInfo) -> str:
    if npu.available:
        return NPU
    if gpu.kind == "dedicated" or (gpu.kind == "integrated" and igpu_enabled()):
        return GPU
    return CPU


def route(device: Optional[str], ollama_model: str) -> Route:
    device = device if device in DEVICES else AUTO
    if device in (AUTO, NPU):
        npu = npu_info(ollama_model)
        if npu.available and npu.model:
            return Route(NPU, FLM_HOST, npu.model)
        if device == NPU:
            raise DeviceUnavailable(npu.reason or "NPU kullanılamıyor.")
        return Route("ollama", None, ollama_model)
    if device == CPU:
        return Route(CPU, None, ollama_model, {"num_gpu": 0})
    return Route(GPU, None, ollama_model)


def stop_flm():
    """Programın başlattığı FastFlowLM sunucusunu kapatır (NPU modeli RAM'den çıkar)."""
    global _flm_proc
    with _lock:
        if _flm_proc is not None and _flm_proc.poll() is None:
            _flm_proc.terminate()
            try:
                _flm_proc.wait(timeout=10)
            except Exception:
                _flm_proc.kill()
        _flm_proc = None


def make_room(r: Route):
    """
    Aynı anda tek model RAM'de dursun: NPU modeli ~9 GB, Ollama modeli ~9 GB;
    ikisi birden 16 GB'lık bir bilgisayarı tıkar. Yer değişince öbürü boşaltılır.
    """
    from llm import ollama
    if r.where == NPU:
        ollama.unload_all()
    else:
        stop_flm()


_last_where: Optional[str] = None


def remember(r: Route):
    global _last_where
    _last_where = r.where


def placement_text(ollama_ps: Optional[List[dict]]) -> Optional[str]:
    """'Şu an: …' satırı. Ollama'nın /api/ps bilgisinden ya da NPU'nun açık olmasından."""
    if _last_where == NPU and flm_running():
        return "NPU'da"
    for m in ollama_ps or []:
        size, vram = m.get("size") or 0, m.get("size_vram") or 0
        if size <= 0:
            continue
        share = vram / size
        if share >= 0.98:
            return "ekran kartında"
        if share <= 0.02:
            return "işlemcide"
        return f"%{share * 100:.0f} ekran kartında, kalanı işlemcide"
    return None
