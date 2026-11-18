"""
Bağımlı kaynaklı Thevenin: Rth = Vth / Isc yolunda bağımsız kaynaklar SIFIRLANMAZ.

Fable denetimi (7. tur): metin önce "bağımsız kaynakları sıfırlayıp bakarız (V1 → kısa
devre)" diyor, sonra kaynaklar yerindeyken bulunan Isc ile Rth = Vth / Isc hesaplıyordu.
"""

from fastapi.testclient import TestClient

from main import app

GND = "* GND1 — Referans toprak (Node 0)"
client = TestClient(app)


def _rth_section(netlist, terminals=("3", "0")):
    r = client.post("/analyze", json={
        "netlist": f"{netlist}\n{GND}", "mode": "DC", "analysis_type": "THEVENIN",
        "thevenin_terminals": {"node_positive": terminals[0], "node_negative": terminals[1]}})
    assert r.status_code == 200
    secs = {s["title"]: [b["text"] for b in s["blocks"]] for s in r.json()["results"]["explanation"]}
    return next(v for k, v in secs.items() if k.startswith("2. Adım"))


def test_isc_route_keeps_independent_sources():
    # Vth = 240 V, Isc = 12 mA → Rth = 20 kΩ (çözücü)
    sec = _rth_section("V1 1 0 DC 10\nR1 1 2 1000\nR2 2 0 2000\nG1 0 3 V(R2) 0.002\n"
                       "R3 2 3 1000\nR4 3 0 4000")
    assert not any("sıfırlanır → kısa devre" in t for t in sec)
    assert not any(t.startswith("Bağımsız kaynakları sıfırlayıp") for t in sec)
    assert any("bağımsız kaynaklar da sıfırlanmaz" in t for t in sec)
    assert "In = Isc = 12 mA" in sec
    assert "Rth = 20 kΩ" in sec


def test_test_source_route_still_zeroes_independent_sources():
    # Ölü port (bağımsız kaynak yok): 1 V test kaynağı, I_test = 80 mA → Rth = 12,5 Ω
    sec = _rth_section("R1 1 0 20\nG1 0 1 V(R1) -0.03", ("1", "0"))
    assert any(t.startswith("Bağımsız kaynakları sıfırlayıp") for t in sec)
    assert any("test kaynağı" in t for t in sec)
    assert "Rth = 12,5 Ω" in sec
