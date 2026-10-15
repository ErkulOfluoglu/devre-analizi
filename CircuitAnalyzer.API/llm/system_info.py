"""
CircuitAnalyzer API — Yapay zekâ için bilgisayar bilgisi

Öğrencinin bilgisayarı yerel modeli kaldırabilir mi? Bellek (RAM) ve disk
ölçülür, belleğe uygun model önerilir; Ollama kurulu ama kapalıysa
başlatılır. Hiçbiri hata fırlatmaz: ölçülemeyen değer None olur.
"""

import ctypes
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Önerilen modeller ve yaklaşık indirme boyutları (GB). Ollama indirme
# sırasında gerçek boyutu bildirir; bunlar yalnızca önceden göstermek ve
# disk yeri kontrolü içindir.
MODEL_LARGE = "gemma4:e4b"
MODEL_SMALL = "gemma4:e2b"
APPROX_SIZE_GB = {MODEL_LARGE: 6.6, MODEL_SMALL: 4.6}

RAM_GOOD_GB = 15.0   # "16 GB" bilgisayarlar işletim sistemine göre 15.x gösterir
RAM_MIN_GB = 7.5     # "8 GB" → 7.x
DISK_MARGIN_GB = 1.0


def total_ram_gb() -> Optional[float]:
    """Toplam fiziksel bellek (GB)."""
    try:
        if sys.platform == "win32":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return stat.ullTotalPhys / 1024 ** 3
            return None
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return pages * page_size / 1024 ** 3
    except Exception:
        return None


def models_dir() -> Path:
    """Ollama'nın modelleri sakladığı klasör (OLLAMA_MODELS ile değişebilir)."""
    custom = os.environ.get("OLLAMA_MODELS", "").strip()
    return Path(custom) if custom else Path.home() / ".ollama" / "models"


def free_disk_gb(path: Optional[Path] = None) -> Optional[float]:
    """Modellerin ineceği diskteki boş yer (GB)."""
    p = path or models_dir()
    # Klasör henüz yoksa var olan ilk üst klasöre bak
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(str(p)).free / 1024 ** 3
    except Exception:
        return None


@dataclass
class ModelAdvice:
    model: str
    fit: str              # "good" | "ok" | "low" | "unknown"
    approx_size_gb: float
    message: str          # Türkçe tek cümle


def recommend(ram_gb: Optional[float]) -> ModelAdvice:
    """Belleğe göre model önerisi."""
    if ram_gb is None:
        return ModelAdvice(MODEL_SMALL, "unknown", APPROX_SIZE_GB[MODEL_SMALL],
                           "Bellek ölçülemedi; daha küçük model önerilir.")
    gb = f"{ram_gb:.0f} GB"
    if ram_gb >= RAM_GOOD_GB:
        return ModelAdvice(MODEL_LARGE, "good", APPROX_SIZE_GB[MODEL_LARGE],
                           f"Bu bilgisayar ({gb} bellek) yapay zekâyı rahat çalıştırır.")
    if ram_gb >= RAM_MIN_GB:
        return ModelAdvice(MODEL_SMALL, "ok", APPROX_SIZE_GB[MODEL_SMALL],
                           f"Bu bilgisayarda ({gb} bellek) küçük model çalışır, cevaplar biraz daha yavaş gelir.")
    return ModelAdvice(MODEL_SMALL, "low", APPROX_SIZE_GB[MODEL_SMALL],
                       f"Bu bilgisayarın belleği ({gb}) yapay zekâ için yetersiz; programı yapay zekâsız "
                       "kullanmanız önerilir.")


# ── Ollama programı ──

def find_ollama_app() -> Optional[Path]:
    """Kurulu Ollama'nın başlatılabilir dosyası (yoksa None)."""
    candidates = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            base = Path(local) / "Programs" / "Ollama"
            candidates += [base / "ollama app.exe", base / "ollama.exe"]
        program_files = os.environ.get("ProgramFiles", "")
        if program_files:
            candidates.append(Path(program_files) / "Ollama" / "ollama app.exe")
    found = shutil.which("ollama")
    if found:
        candidates.append(Path(found))
    for c in candidates:
        if c.is_file():
            return c
    return None


def start_ollama() -> bool:
    """
    Kurulu ama kapalı Ollama'yı başlatır. "ollama app.exe" tepsi uygulamasıdır
    ve sunucuyu kendisi açar; yalnız ollama.exe varsa "serve" ile başlatılır.
    Sunucunun hazır olmasını beklemez (çağıran durumu yoklar).
    """
    app = find_ollama_app()
    if app is None:
        return False
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    args = [str(app)] if app.name.lower() == "ollama app.exe" else [str(app), "serve"]
    try:
        subprocess.Popen(args, creationflags=flags, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        return True
    except Exception:
        return False
