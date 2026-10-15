"""
CircuitAnalyzer API — Ollama İstemcisi Testleri

Test edilen modül:
- llm/ollama.py (base_url, pick_model, get_status, chat, OllamaUnavailable, OllamaError, RECOMMENDED_MODEL)
"""

import http.server
import json
import socket
import threading
from typing import List
import pytest

from llm.ollama import (
    DEFAULT_HOST,
    RECOMMENDED_MODEL,
    OllamaError,
    OllamaStatus,
    OllamaUnavailable,
    base_url,
    chat,
    get_status,
    pick_model,
)


class _FakeOllamaHandler(http.server.BaseHTTPRequestHandler):
    """Test için Ollama API taklidi yapan HTTP istek yöneticisi."""

    def log_message(self, format, *args):
        # Test çıktılarını kirletmemek için loglama yapma
        pass

    def do_GET(self):
        if self.path == "/api/version":
            body = json.dumps({"version": "0.9.0"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/tags":
            body = json.dumps({"models": [{"name": "b"}, {"name": "a"}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        self.server.received_posts.append(body)

        if self.path == "/api/chat":
            model = body.get("model")
            if model == "x":
                err = json.dumps({"error": "model 'x' not found"}).encode("utf-8")
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
            elif model == "empty":
                resp = json.dumps({"message": {"role": "assistant", "content": "   "}}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            else:
                resp = json.dumps({"message": {"role": "assistant", "content": " Merhaba "}}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def fake_ollama_server(monkeypatch):
    """Arka planda çalışan ve OLLAMA_HOST'a bağlanan sahte Ollama sunucusu."""
    class Server(http.server.ThreadingHTTPServer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.received_posts: List[dict] = []

    server = Server(("127.0.0.1", 0), _FakeOllamaHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    monkeypatch.setenv("OLLAMA_HOST", f"127.0.0.1:{port}")
    yield server

    server.shutdown()
    server.server_close()


def test_base_url(monkeypatch):
    """OLLAMA_HOST ortam değişkeni mantığı ve varsayılan URL."""
    # Tanımlı değilken varsayılan
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert base_url() == "http://127.0.0.1:11434"

    # Portlu yerel IP verildiğinde http:// öneki eklenmesi
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:5555")
    assert base_url() == "http://127.0.0.1:5555"

    # 0.0.0.0 dinleme adresi yerel 127.0.0.1'e çevrilmeli
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")
    assert base_url() == "http://127.0.0.1:11434"

    # Sonundaki eğik çizgi kırpılmalı
    monkeypatch.setenv("OLLAMA_HOST", "http://myhost:1/")
    assert base_url() == "http://myhost:1"


def test_pick_model():
    """Model seçimi kuralları: istenen, latest eki, önerilen model veya ilk model."""
    # İstenen model kuruluysa o seçilir
    assert pick_model("llama3", ["llama3", "mistral"]) == "llama3"

    # "gemma3" istendiğinde "gemma3:latest" kuruluysa eşleşir
    assert pick_model("gemma3", ["gemma3:latest"]) == "gemma3:latest"

    # İstenen model kurulu değilse, RECOMMENDED_MODEL kuruluysa o seçilir
    assert pick_model("yok", ["baska_model", RECOMMENDED_MODEL]) == RECOMMENDED_MODEL

    # Önerilen model de yoksa kurulu ilk model seçilir
    assert pick_model("yok", ["model_a", "model_b"]) == "model_a"

    # Hiç model kurulu değilse None döner
    assert pick_model("herhangi", []) is None
    assert pick_model(None, []) is None


def test_get_status_fake_server(fake_ollama_server):
    """Sahte sunucu üzerinden sürüm ve sıralı model listesinin alınması."""
    st = get_status()
    assert st.available is True
    assert st.version == "0.9.0"
    assert st.models == ["a", "b"]  # sorted: ['b', 'a'] → ['a', 'b']


def test_get_status_closed_port(monkeypatch):
    """Kapalı bir porta bağlanmaya çalışıldığında hata fırlatılmayıp available=False dönmesi."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    closed_port = s.getsockname()[1]
    s.close()

    monkeypatch.setenv("OLLAMA_HOST", f"127.0.0.1:{closed_port}")
    st = get_status()
    assert st.available is False
    assert st.version is None
    assert st.models == []


def test_chat_against_fake_server(fake_ollama_server):
    """POST /api/chat isteği parametreleri ve dönen cevabın kırpılması."""
    result = chat("gemma3:4b", [{"role": "user", "content": "Selam"}], num_ctx=4096)

    # Sunucu " Merhaba " döndürdü, chat() kenar boşluklarını kırparak "Merhaba" vermeli
    assert result == "Merhaba"

    # Gönderilen payload'u doğrula
    assert len(fake_ollama_server.received_posts) >= 1
    post = fake_ollama_server.received_posts[-1]
    assert post["model"] == "gemma3:4b"
    assert post["messages"] == [{"role": "user", "content": "Selam"}]
    assert post["stream"] is False
    assert post["options"]["temperature"] == 0.2
    assert post["options"]["num_ctx"] == 4096


def test_chat_model_not_found_error(fake_ollama_server):
    """Model bulunamadığında HTTP 404 dönüp 'not found' içeren OllamaError fırlatılması."""
    with pytest.raises(OllamaError) as exc_info:
        chat("x", [{"role": "user", "content": "Test"}])

    assert "not found" in str(exc_info.value)


def test_chat_empty_content_error(fake_ollama_server):
    """Model boş içerik döndürdüğünde OllamaError fırlatılması."""
    with pytest.raises(OllamaError) as exc_info:
        chat("empty", [{"role": "user", "content": "Test"}])

    assert "boş" in str(exc_info.value).lower()
