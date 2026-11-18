"""
DC'de kondansatörlü Thevenin: açık devre adımı söylenir, Vth = 0 iken Pmax = 0 açıklanır.

Devre: V1 = 12 V, R1 1k (1→2), C1 (2→3), R2 2k (2→0), R3 1k (3→0); uçlar 3–0.
DC'de C1 açık → Düğüm 3'e akım gelmez: V₃ = 0 → Vth = 0, Rth = R3 = 1 kΩ, Pmax = 0.
"""

from fastapi.testclient import TestClient

from main import app

GND = "* GND1 — Referans toprak (Node 0)"
client = TestClient(app)


def test_open_capacitor_and_zero_pmax_are_explained():
    r = client.post("/analyze", json={
        "netlist": f"V1 1 0 DC 12\nR1 1 2 1000\nC1 2 3 0.0001\nR2 2 0 2000\nR3 3 0 1000\n{GND}",
        "mode": "DC", "analysis_type": "THEVENIN",
        "thevenin_terminals": {"node_positive": "3", "node_negative": "0"}})
    assert r.status_code == 200
    secs = {s["title"]: [b["text"] for b in s["blocks"]] for s in r.json()["results"]["explanation"]}
    vth = secs["1. Adım — Vth (Açık Devre Gerilimi)"]
    assert any(t.startswith("DC'de kondansatör (C1) açık devredir") for t in vth)
    assert "Vth = 0 V" in vth
    pmax = secs["Maksimum Güç Transferi"]
    assert any("Pmax = 0 W" in t for t in pmax)
    assert not any("seçilirse yüke en fazla güç aktarılır" in t for t in pmax)
