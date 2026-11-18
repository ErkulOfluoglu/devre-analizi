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
Ekran kartı ayarı için kapatılan Ollama, program kapanırken (release_igpu) ya da
program bunu başaramazsa programın kendisi tarafından eski hâliyle yeniden açılır.
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
_lock = threading.Lock()          # yalnız FastFlowLM süreci (_flm_proc) için; denetim bunu tutmaz
_probe_lock = threading.Lock()    # denetim durumunu (önbellek + süren denetim) korur; kısa tutulur
_probe_event: Optional[threading.Event] = None   # bir denetim sürerken var; bitince set edilir
PROBE_WAIT_SECONDS = 45.0         # flm validate + flm list: en çok 2 × 20 sn zaman aşımı


def _start_probe_locked() -> threading.Event:
    """Süren denetim yoksa arka planda başlatır; varsa onunkini verir (aynı anda tek denetim)."""
    global _probe_event
    if _probe_event is not None:
        return _probe_event
    done = threading.Event()
    _probe_event = done

    def run():
        global _npu_cached, _npu_cached_at, _probe_event
        try:
            info = _probe_npu()
        except Exception:
            info = NpuInfo(False, None, "NPU denetimi yapılamadı.")
        with _probe_lock:
            _npu_cached, _npu_cached_at = info, time.time()
            _probe_event = None
        done.set()

    threading.Thread(target=run, daemon=True, name="npu-probe").start()
    return done


def npu_info(ollama_model: Optional[str] = None, refresh: bool = False) -> NpuInfo:
    """
    NPU kullanılabilir mi? (FastFlowLM kurulu + NPU hazır + uygun model var)

    Denetim ~4 sn (donarsa 40 sn) sürer; bu yüzden hiçbir kilit altında yapılmaz:
    - önbellek tazeyse hemen döner;
    - önbellek eskidiyse eski değer hemen döner, yenileme arka planda (en çok bir tane) yapılır;
    - önbellek boşsa (açılışta) süren denetimin sonucu beklenir ("NPU yok" diye yanlış
      cevap verilip model sonradan NPU'ya geçmesin);
    - refresh=True taze denetim ister ve sonucunu bekler.
    Aynı anda gelen çağrılar tek denetimi paylaşır.
    """
    wait_for: Optional[threading.Event] = None
    with _probe_lock:
        base = _npu_cached
        fresh = base is not None and time.time() - _npu_cached_at < CACHE_SECONDS
        if refresh or base is None:
            wait_for = _start_probe_locked()
        elif not fresh:
            _start_probe_locked()          # eski değer şimdilik geçerli; arkada yenilenir
    if wait_for is not None:
        wait_for.wait(PROBE_WAIT_SECONDS)
        with _probe_lock:
            base = _npu_cached
        if base is None:
            base = NpuInfo(False, None, "NPU denetimi henüz bitmedi.")
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
    alive = _igpu_proc is not None and _igpu_proc.poll() is None
    return alive or os.environ.get("OLLAMA_IGPU_ENABLE", "").strip() == "1"


# Bizim başlattığımız ekran kartı ayarlı Ollama (yoksa None) ve onu başlatmadan önce
# çalışan Ollama'yı geri açacak komut (hiçbiri çalışmıyorduysa None).
_igpu_proc: Optional[subprocess.Popen] = None
_igpu_restore: Optional[List[str]] = None
_igpu_lock = threading.Lock()     # yeniden başlatma / bırakma aynı anda tek iş yapsın
TRAY_IMAGE, SERVE_IMAGE = "ollama app.exe", "ollama.exe"
RELEASE_WAIT_SECONDS = 5.0


def parse_tasklist(text: str) -> set:
    """
    `tasklist /FO CSV /NH` çıktısındaki işlem adları (küçük harfle). Dil fark etmez:
    işlem satırları '"ad.exe","PID",...' biçimindedir; "görev yok" gibi bilgi satırları
    virgüllü CSV olmadığı için atlanır.
    """
    import csv
    names = set()
    for row in csv.reader(text.splitlines()):
        if len(row) >= 2 and row[0].strip():
            names.add(row[0].strip().lower())
    return names


def ollama_state(running_images: set) -> str:
    """'tray' (Ollama uygulaması açık), 'serve' (yalnız ollama.exe) ya da 'none'."""
    if TRAY_IMAGE in running_images:
        return "tray"
    if SERVE_IMAGE in running_images:
        return "serve"
    return "none"


def restore_command_for(state: str, app: Path) -> Optional[List[str]]:
    """Kapatmadan önceki Ollama'yı yeniden açacak komut (tepsi uygulaması yoksa 'serve')."""
    exe = app.with_name(SERVE_IMAGE)
    if state == "tray":
        tray = app.with_name(TRAY_IMAGE)
        return [str(tray)] if tray.is_file() else [str(exe), "serve"]
    if state == "serve":
        return [str(exe), "serve"]
    return None


def _tasklist() -> str:
    if sys.platform != "win32":
        return ""
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                             errors="replace", timeout=15, creationflags=_NO_WINDOW)
        return out.stdout
    except Exception:
        return ""


def _kill_image(image: str):
    # /T: modeli tutan alt süreçler (llama-server) de kapansın, RAM'de kalmasın
    subprocess.run(["taskkill", "/F", "/T", "/IM", image], capture_output=True, creationflags=_NO_WINDOW)


def _kill_tree(pid: int):
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, creationflags=_NO_WINDOW)


def _start_igpu_ollama(exe: Path) -> subprocess.Popen:
    # Bilerek iş nesnesinin içinde kalır (ayrılma bayrağı yok): program kapanınca kapanır.
    env = dict(os.environ, OLLAMA_IGPU_ENABLE="1")
    return subprocess.Popen([str(exe), "serve"], env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)


def _pause(seconds: float):
    time.sleep(seconds)


def _ollama_answers() -> bool:
    from llm import ollama
    try:
        return bool(ollama.get_status().available)
    except Exception:
        return False


def igpu_restore_command() -> Optional[List[str]]:
    """Ekran kartı ayarlı Ollama kapanınca eski Ollama'yı açacak komut (yoksa None)."""
    return list(_igpu_restore) if _igpu_restore else None


def restart_ollama_with_igpu() -> bool:
    """
    Ollama'yı kapatıp OLLAMA_IGPU_ENABLE=1 ile yeniden başlatır (yalnız bu süreç
    için; Windows ayarı değişmez). Önceki durum (tepsi uygulaması / yalnız sunucu /
    kapalı) kaydedilir; release_igpu() onu geri getirir. Program kapanınca bu Ollama
    da kapanır. Zaten bizim ayarlı Ollama'mız çalışıyorsa hiçbir şey kapatılmaz.
    """
    global _igpu_proc, _igpu_restore
    with _igpu_lock:
        if _igpu_proc is not None and _igpu_proc.poll() is None:
            return True
        app = system_info.find_ollama_app()
        if app is None:
            return False
        exe = app.with_name(SERVE_IMAGE)
        if not exe.is_file():
            return False
        restore = None
        if sys.platform == "win32":
            restore = restore_command_for(ollama_state(parse_tasklist(_tasklist())), app)
            for image in (TRAY_IMAGE, SERVE_IMAGE):
                _kill_image(image)
            _pause(1.0)
        try:
            proc = _start_igpu_ollama(exe)
        except Exception:
            if restore:                       # kapattığımızı geri aç; kullanıcı Ollama'sız kalmasın
                system_info.spawn_surviving(restore)
            return False
        _igpu_proc, _igpu_restore = proc, restore
        return True


def release_igpu() -> tuple:
    """
    Bizim başlattığımız ekran kartı ayarlı Ollama'yı kapatır (en çok ~5 sn bekler, 11434
    portu boşalsın) ve ayardan önce çalışan Ollama'yı aynen geri açar. Bizim Ollama'mız
    yoksa hemen döner (tekrar çağrılabilir). Geri açılan süreç programdan bağımsızdır.
    Döner: (başarılı mı, Türkçe mesaj)
    """
    global _igpu_proc, _igpu_restore
    with _igpu_lock:
        proc, restore = _igpu_proc, _igpu_restore
        if proc is None:
            return True, "Ekran kartı ayarlı Ollama zaten açık değil."
        was_running = proc.poll() is None
        if was_running:
            try:
                _kill_tree(proc.pid)
                proc.wait(timeout=RELEASE_WAIT_SECONDS)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except Exception:
                    pass
        _igpu_proc, _igpu_restore = None, None
        if not restore:
            return True, "Ekran kartı ayarlı Ollama kapatıldı."
        if not was_running and _ollama_answers():
            return True, "Ollama zaten açık."          # kullanıcı kendisi yeniden açmış
        if system_info.spawn_surviving(restore):
            return True, "Ollama eski hâliyle yeniden açılıyor."
        return False, "Ollama eski hâliyle açılamadı. Elle açabilirsiniz."


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
