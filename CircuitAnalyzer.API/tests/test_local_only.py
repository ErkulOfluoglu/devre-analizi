"""
Çözücüye yalnızca bu bilgisayardaki program erişebilir (Fable denetimi, 4. tur).

Bilgisayarda açık bir web sayfası 127.0.0.1'e istek gönderebilir. Tarayıcı başka
siteden gelen her POST'ta Origin başlığı ekler; DNS rebinding ise Host başlığında
saldırganın alan adını taşır. İkisi de 403 ile reddedilir. Ayrıca ağır çözümler
sunucuyu dondurmaz ve aşırı büyük istekler kabul edilmez.
"""

import inspect

import pytest

import main
from models.request import MAX_CHAT_TURNS, MAX_NETLIST_CHARS

NETLIST = "V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n* GND1 — Referans toprak (Node 0)"
ANALYZE = {"netlist": NETLIST, "mode": "DC", "analysis_type": "NODAL"}


@pytest.mark.parametrize("path", ["/llm/gpu/enable", "/llm/start", "/llm/pull", "/llm/pull/cancel"])
def test_web_page_cannot_trigger_ai_actions(client, path):
    r = client.post(path, headers={"Origin": "https://kotu-site.example"})
    assert r.status_code == 403
    assert "yalnızca Devre Analizi" in r.json()["detail"]


def test_web_page_cannot_read_status(client):
    r = client.get("/llm/status", headers={"Origin": "https://kotu-site.example"})
    assert r.status_code == 403


@pytest.mark.parametrize("origin", ["null", "http://127.0.0.1:9999", "file://"])
def test_other_origins_are_refused(client, origin):
    r = client.post("/analyze", json=ANALYZE, headers={"Origin": origin})
    assert r.status_code == 403


def test_dns_rebinding_host_is_refused(client):
    r = client.post("/analyze", json=ANALYZE, headers={"Host": "kotu-site.example:8000"})
    assert r.status_code == 403
    r = client.get("/health", headers={"Host": "kotu-site.example"})
    assert r.status_code == 403


def test_no_cors_permission_is_given(client):
    r = client.options("/analyze", headers={
        "Origin": "https://kotu-site.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


@pytest.mark.parametrize("host", ["127.0.0.1:8123", "localhost:8123", "[::1]:8123", "127.0.0.1"])
def test_the_program_itself_is_accepted(client, host):
    # WPF HttpClient: Host = 127.0.0.1:<port>, Origin yok
    r = client.post("/analyze", json=ANALYZE, headers={"Host": host})
    assert r.status_code == 200


def test_same_address_docs_page_is_accepted(client):
    # Geliştirici /docs sayfasından denerken tarayıcı kendi adresini Origin olarak yollar
    r = client.post("/analyze", json=ANALYZE,
                    headers={"Host": "127.0.0.1:8123", "Origin": "http://127.0.0.1:8123"})
    assert r.status_code == 200


@pytest.mark.parametrize("header, expected", [
    ("127.0.0.1:8123", "127.0.0.1"),
    ("LOCALHOST", "localhost"),
    ("[::1]:80", "[::1]"),
    ("[::1]", "[::1]"),
    ("kotu.example:80", "kotu.example"),
])
def test_host_name(header, expected):
    assert main._host_name(header) == expected


def test_heavy_endpoints_do_not_block_the_server():
    # async def + ağır CPU işi = tüm sunucu donar; düz def iş parçacığı havuzunda çalışır
    for fn in (main.analyze_circuit, main.parse_only, main.practice_check, main.llm_ask):
        assert not inspect.iscoroutinefunction(fn), fn.__name__


def test_oversized_netlist_is_refused(client):
    big = "R1 1 0 1k\n" + "* " + "x" * MAX_NETLIST_CHARS
    r = client.post("/analyze", json={"netlist": big, "mode": "DC", "analysis_type": "NODAL"})
    assert r.status_code == 422


def test_long_chat_history_is_refused(client):
    turns = [{"role": "user", "content": "soru"}] * (MAX_CHAT_TURNS + 1)
    r = client.post("/llm/ask", json={**ANALYZE, "question": "V2 kaç?", "history": turns})
    assert r.status_code == 422
