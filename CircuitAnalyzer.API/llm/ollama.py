"""
CircuitAnalyzer API — Yerel Ollama istemcisi

Ollama bilgisayarda ayrı bir program olarak çalışır (varsayılan
http://127.0.0.1:11434). Kurulu değilse uygulama yapay zekâsız aynen
çalışır; bu modül yalnızca "var mı, hangi modeller kurulu" diye bakar ve
sohbet isteği gönderir. Ek bağımlılık olmasın diye standart kütüphane
(urllib) kullanılır.

Adres OLLAMA_HOST ortam değişkeniyle değiştirilebilir (Ollama'nın kendi
kuralı: "127.0.0.1:11434" ya da "http://host:port").
"""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional

DEFAULT_HOST = "http://127.0.0.1:11434"

# Önerilen model: çok dilli; 2026-10-14'te gerçek devre sorularıyla denendi
# (Türkçe anlatım iyi, sayılar doğrulandı, işlemcide cevap 15–45 s, ~7 GB).
# Belleği az (8 GB) bilgisayarlar için daha küçüğü önerilir.
# Kurulu herhangi bir modelle de çalışır.
RECOMMENDED_MODEL = "gemma4:e4b"
SMALL_MODEL = "gemma4:e2b"

STATUS_TIMEOUT = 2.0      # s — Ollama yoksa uygulama beklemesin
CHAT_TIMEOUT = 300.0      # s — işlemcide (GPU'suz) cevap üretmek uzun sürebilir


class OllamaUnavailable(Exception):
    """Ollama'ya ulaşılamadı (kurulu değil / çalışmıyor)."""


class OllamaError(Exception):
    """Ollama isteği reddetti (ör. model kurulu değil)."""


def base_url() -> str:
    host = os.environ.get("OLLAMA_HOST", "").strip()
    if not host:
        return DEFAULT_HOST
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    # "0.0.0.0" dinleme adresidir; bağlanmak için yerel adres kullanılır
    return host.rstrip("/").replace("://0.0.0.0", "://127.0.0.1")


def _request(path: str, payload: Optional[dict], timeout: float) -> dict:
    url = base_url() + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error", "")
        except Exception:
            detail = ""
        raise OllamaError(detail or f"HTTP {e.code}") from e
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
        raise OllamaUnavailable(str(e)) from e


@dataclass
class OllamaStatus:
    available: bool
    version: Optional[str] = None
    models: List[str] = field(default_factory=list)


def get_status() -> OllamaStatus:
    """Ollama çalışıyor mu, hangi modeller kurulu? (Hata fırlatmaz.)"""
    try:
        version = _request("/api/version", None, STATUS_TIMEOUT).get("version")
        tags = _request("/api/tags", None, STATUS_TIMEOUT)
    except (OllamaUnavailable, OllamaError, ValueError):
        return OllamaStatus(available=False)
    models = sorted(m.get("name", "") for m in tags.get("models", []) if m.get("name"))
    return OllamaStatus(available=True, version=version, models=models)


def pick_model(requested: Optional[str], installed: List[str],
               preferred: Optional[str] = None) -> Optional[str]:
    """
    İstenen model kuruluysa o; değilse bu bilgisayarın belleğine göre önerilen
    (preferred); sonra genel öneri, küçük model; o da yoksa ilk kurulu model.
    """
    if requested and requested in installed:
        return requested
    if requested and f"{requested}:latest" in installed:
        return f"{requested}:latest"
    for candidate in (preferred, RECOMMENDED_MODEL, SMALL_MODEL):
        if candidate and candidate in installed:
            return candidate
    return installed[0] if installed else None


def chat(model: str, messages: List[Dict[str, str]], num_ctx: int = 8192) -> str:
    """Tek seferlik (akışsız) sohbet isteği; modelin cevap metnini döndürür."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        # Düşük sıcaklık: anlatım tutarlı olsun, sayı uydurma eğilimi azalsın.
        # num_ctx: varsayılan 2048 belirteç anlatımın tamamına yetmez.
        "options": {"temperature": 0.2, "num_ctx": num_ctx},
        # "Düşünme" kapalı: çözüm zaten programdan geliyor; açıkken cevap
        # işlemcide ~7 kat yavaş (gemma4:e4b ile ölçüm: 37 s → 5 s)
        "think": False,
    }
    try:
        data = _request("/api/chat", payload, CHAT_TIMEOUT)
    except OllamaError as e:
        # Eski Ollama sürümleri / düşünme desteği olmayan modeller bu alanı reddedebilir
        if "think" not in str(e).lower():
            raise
        payload.pop("think")
        data = _request("/api/chat", payload, CHAT_TIMEOUT)
    content = (data.get("message") or {}).get("content", "")
    if not content.strip():
        raise OllamaError("Model boş cevap döndürdü.")
    return content.strip()
