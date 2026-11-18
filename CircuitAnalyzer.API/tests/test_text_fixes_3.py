"""
Son üç yazı pürüzü:
- Kaynak dönüşümünde türetilen direnç ilk yazıldığı birimle kalır (Ra = 0,8 kΩ → Ea satırında da 0,8 kΩ).
- Sonuçlar sekmesindeki Thevenin/Norton başlığı ve açıklaması referans düğümü "GND" diye yazar.
- Norton hata mesajı "(Düğüm 3–GND)" der, "(Düğüm 3–0)" demez.
"""
import pytest
from fastapi.testclient import TestClient

from main import app

GND = "\n* GND1 - Referans toprak"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _texts(resp_json):
    out = []

    def walk(o):
        if isinstance(o, str):
            out.append(o)
        elif isinstance(o, dict):
            for k, v in o.items():
                if k not in ("series", "points", "curve", "samples", "plot"):
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(resp_json)
    return out


def test_source_transform_keeps_unit_of_derived_resistor(client):
    # R4 ∥ R1 → Ra = 0,8 kΩ; sonra Ia ∥ Ra → Ea = Ia·Ra satırı da kΩ ile yazılmalı
    net = ("V1 1 0 DC 12\nR1 1 2 1000\nR2 2 3 2000\nR3 3 0 3000\nR4 2 0 4000" + GND)
    r = client.post("/analyze", json={
        "netlist": net, "mode": "DC", "analysis_type": "SOURCE_TRANSFORM",
        "thevenin_terminals": {"node_positive": "3", "node_negative": "0"}})
    texts = _texts(r.json()["results"]["explanation"])
    ra_lines = [t for t in texts if t.startswith("Ra = ")]
    assert ra_lines and ra_lines[0].endswith("= 0,8 kΩ")
    ea_lines = [t for t in texts if t.startswith("Ea = ")]
    assert ea_lines, texts
    assert "0,8 kΩ" in ea_lines[0] and "800 Ω" not in ea_lines[0]


@pytest.mark.parametrize("method, title", [("THEVENIN", "Thevenin Eşdeğeri (Düğüm 3 – GND)"),
                                           ("NORTON", "Norton Eşdeğeri (Düğüm 3 – GND)")])
def test_port_step_title_calls_reference_gnd(client, method, title):
    net = "V1 1 0 DC 12\nR1 1 2 1000\nR2 2 0 2000\nR3 2 3 1000\nR4 3 0 1000" + GND
    r = client.post("/analyze", json={
        "netlist": net, "mode": "DC", "analysis_type": method,
        "thevenin_terminals": {"node_positive": "3", "node_negative": "0"}})
    steps = r.json()["solution_steps"]
    titles = [s["title"] for s in steps]
    assert title in titles
    desc = next(s["description"] for s in steps if s["title"] == title)
    assert "Düğüm 3 ve GND arasındaki" in desc
    assert "Düğüm 0" not in "\n".join(titles)


def test_norton_error_calls_reference_gnd(client):
    # Port doğrudan ideal gerilim kaynağına paralel → Norton tanımsız
    net = "V1 1 0 DC 12\nR1 1 0 1000" + GND
    r = client.post("/analyze", json={
        "netlist": net, "mode": "DC", "analysis_type": "NORTON",
        "thevenin_terminals": {"node_positive": "1", "node_negative": "0"}})
    errs = "\n".join(_texts(r.json().get("errors") or []))
    assert "Norton hesaplanamadı (Düğüm 1–GND)" in errs
    assert "Düğüm 1–0)" not in errs
