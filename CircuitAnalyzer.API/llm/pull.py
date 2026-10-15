"""
CircuitAnalyzer API — Model indirme (terminal gerekmez)

Ollama'nın POST /api/pull uç noktası indirme ilerlemesini satır satır JSON
olarak akıtır. İndirme arka planda bir iş parçacığında sürer; arayüz
GET /llm/pull ile birkaç saniyede bir durumu sorar (yüzde, GB, hız, kalan
süre) ve isterse iptal eder. Aynı anda tek indirme yapılır.

Ollama yarım kalan katmanları saklar: iptal edilen indirme yeniden
başlatılınca kaldığı yerden devam eder.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

from llm import ollama

_STATUS_TR = {
    "pulling manifest": "Model bilgisi alınıyor…",
    "verifying sha256 digest": "İndirilen dosya doğrulanıyor…",
    "writing manifest": "Kurulum tamamlanıyor…",
    "removing any unused layers": "Kurulum tamamlanıyor…",
    "success": "Model hazır.",
}


@dataclass
class PullState:
    model: Optional[str] = None
    state: str = "idle"           # idle | running | done | error | cancelled
    completed: int = 0            # bayt
    total: int = 0                # bayt (bilinmiyorsa 0)
    speed_bps: float = 0.0
    eta_seconds: Optional[float] = None
    message: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    layers: Dict[str, Tuple[int, int]] = field(default_factory=dict)

    @property
    def percent(self) -> Optional[float]:
        return 100.0 * self.completed / self.total if self.total > 0 else None


class PullManager:
    """Tek bir arka plan indirmesini yönetir (iş parçacığı güvenli)."""

    def __init__(self, opener: Optional[Callable] = None):
        self._lock = threading.Lock()
        self._state = PullState()
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._response = None
        # Testler sahte bir bağlantı verebilir
        self._open = opener or (lambda req: urllib.request.urlopen(req, timeout=60))

    def snapshot(self) -> PullState:
        with self._lock:
            s = self._state
            return PullState(s.model, s.state, s.completed, s.total, s.speed_bps,
                             s.eta_seconds, s.message, s.started_at, s.finished_at, dict(s.layers))

    @property
    def running(self) -> bool:
        with self._lock:
            return self._state.state == "running"

    def start(self, model: str) -> bool:
        """İndirmeyi başlatır; zaten bir indirme sürüyorsa False."""
        with self._lock:
            if self._state.state == "running":
                return False
            self._state = PullState(model=model, state="running", message="Başlatılıyor…",
                                    started_at=time.time())
            self._cancel.clear()
        self._thread = threading.Thread(target=self._run, args=(model,), daemon=True)
        self._thread.start()
        return True

    def cancel(self) -> bool:
        with self._lock:
            if self._state.state != "running":
                return False
        self._cancel.set()
        resp = self._response
        if resp is not None:
            try:
                resp.close()       # okuma döngüsünü hemen kırar
            except Exception:
                pass
        return True

    def wait(self, timeout: float = 10.0):
        """Testler için: iş parçacığının bitmesini bekler."""
        if self._thread is not None:
            self._thread.join(timeout)

    # ── İş parçacığı ──

    def _finish(self, state: str, message: str):
        with self._lock:
            self._state.state = state
            self._state.message = message
            self._state.eta_seconds = None
            self._state.finished_at = time.time()

    def _run(self, model: str):
        payload = json.dumps({"model": model, "stream": True}).encode("utf-8")
        req = urllib.request.Request(ollama.base_url() + "/api/pull", data=payload, method="POST",
                                     headers={"Content-Type": "application/json"})
        last_t, last_done = time.time(), 0
        try:
            resp = self._open(req)
            self._response = resp
            with resp:
                for raw in resp:
                    if self._cancel.is_set():
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if msg.get("error"):
                        self._finish("error", _error_tr(msg["error"], model))
                        return
                    status = str(msg.get("status", ""))
                    now = time.time()
                    with self._lock:
                        st = self._state
                        digest = msg.get("digest")
                        if digest and msg.get("total"):
                            st.layers[digest] = (int(msg.get("completed", 0) or 0), int(msg["total"]))
                            st.completed = sum(c for c, _ in st.layers.values())
                            st.total = sum(t for _, t in st.layers.values())
                            dt = now - last_t
                            if dt >= 0.5:
                                inst = max(0.0, (st.completed - last_done) / dt)
                                # Dalgalanmasın diye üstel ortalama
                                st.speed_bps = inst if st.speed_bps == 0 else 0.7 * st.speed_bps + 0.3 * inst
                                last_t, last_done = now, st.completed
                            if st.speed_bps > 0 and st.total > st.completed:
                                st.eta_seconds = (st.total - st.completed) / st.speed_bps
                            st.message = "İndiriliyor…"
                        elif status:
                            st.message = _STATUS_TR.get(status, st.message or status)
                    if status == "success":
                        self._finish("done", "Model hazır.")
                        return
            if self._cancel.is_set():
                self._finish("cancelled", "İndirme iptal edildi. Yeniden başlatınca kaldığı yerden devam eder.")
            else:
                self._finish("error", "İndirme yarıda kesildi. İnternet bağlantınızı kontrol edip yeniden deneyin.")
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read().decode("utf-8")).get("error", "")
            except Exception:
                detail = f"HTTP {e.code}"
            self._finish("error", _error_tr(detail, model))
        except Exception as e:
            if self._cancel.is_set():
                self._finish("cancelled", "İndirme iptal edildi. Yeniden başlatınca kaldığı yerden devam eder.")
            else:
                self._finish("error", "Ollama'ya ulaşılamadı ya da bağlantı koptu. "
                                      f"Ollama'nın açık olduğundan emin olun. ({e})")
        finally:
            self._response = None


def _error_tr(detail: str, model: str) -> str:
    d = (detail or "").lower()
    if "not found" in d or "file does not exist" in d:
        return f"“{model}” modeli bulunamadı. Ollama'yı güncellemeyi deneyin."
    if "no space" in d or "disk" in d:
        return "Diskte yer kalmadı. Yer açıp yeniden deneyin."
    if "connection" in d or "timeout" in d or "tls" in d or "dial" in d:
        return "İnternet bağlantısı sorunu. Bağlantınızı kontrol edip yeniden deneyin."
    return f"İndirme hatası: {detail}"


# Uygulama genelinde tek indirme yöneticisi
MANAGER = PullManager()
