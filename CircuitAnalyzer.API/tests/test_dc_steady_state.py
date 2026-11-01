"""
DC'de kararlı hâli olmayan devreler: sebep doğru söylenmeli, çözülebilen benzerleri bozulmamalı.

Değerler elle: 2 mA / 10 µF = 200 V/s;  10 V / 10 mH = 1000 A/s.
"""

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)
GND = "\n* GND1 — Referans toprak"


def _post(netlist: str):
    return client.post("/analyze", json={"netlist": netlist + GND, "mode": "DC", "analysis_type": "NODAL"})


def _nodes(netlist: str) -> dict:
    r = _post(netlist)
    assert r.status_code == 200, r.text
    return {k: v["value"] for k, v in r.json()["results"]["node_voltages"].items()}


@pytest.mark.parametrize("net", [
    "I2 0 1 DC 2m\nR3 1 2 2k\nC2 2 0 10u\n",        # kaynak, seri direnç, kondansatör
    "I2 0 1 DC 2m\nC2 1 0 10u\n",                   # kaynak ve kondansatör
])
def test_current_source_charging_capacitor(net):
    r = _post(net)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "kararlı hâli yok" in detail
    assert "C2 sürekli dolar" in detail
    assert "200 V/s" in detail
    assert "sıfır dirençli" not in detail


def test_two_capacitors_name_both_without_a_rate():
    r = _post("I1 0 1 DC 1m\nC1 1 0 10u\nC2 1 0 20u\n")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "C1, C2 sürekli dolar" in detail and "dV/dt" not in detail


@pytest.mark.parametrize("net", ["V1 1 0 DC 10\nL1 1 0 10m\n"])
def test_voltage_source_directly_on_inductor(net):
    r = _post(net)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "kararlı hâli yok" in detail and "dI/dt" in detail and "1 kA/s" in detail


@pytest.mark.parametrize("net", [
    "V1 1 0 DC 10\nV2 1 0 DC 5\nR1 1 0 5\n",        # iki gerilim kaynağı paralel: eski açıklama kalır
    "I1 0 1 DC 2m\nR1 1 2 2k\n",                    # akım kaynağı açık uçta: kondansatör yok
])
def test_other_unsolvable_circuits_keep_their_reason(net):
    r = _post(net)
    assert r.status_code == 422
    assert "tek bir çözümü yok" in r.json()["detail"]


def test_circuits_with_a_return_path_still_solve():
    # 2 mA R2'den döner: V2 = 2 mA·1 kΩ = 2 V, V1 = 2 + 2 mA·2 kΩ = 6 V
    v = _nodes("I1 0 1 DC 2m\nR1 1 2 2k\nC1 2 0 10u\nR2 2 0 1k\n")
    assert v["1"] == pytest.approx(6.0) and v["2"] == pytest.approx(2.0)
    # Kondansatör açık, akım yok: V2 = V1 = 10 V
    v = _nodes("V1 1 0 DC 10\nR1 1 2 2k\nC1 2 0 10u\n")
    assert v["2"] == pytest.approx(10.0)
    # Bobin kısa devre: V2 = 0
    v = _nodes("V1 1 0 DC 10\nR1 1 2 2k\nL1 2 0 10m\n")
    assert v["2"] == pytest.approx(0.0)
    # Akım kaynağının akımı bobinden döner: V1 = 0
    v = _nodes("I1 0 1 DC 2m\nL1 1 0 10m\n")
    assert v["1"] == pytest.approx(0.0)
    # Süzme: kondansatör dirençle paralel, gerilim bölücü
    v = _nodes("V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\nC1 2 0 10u\n")
    assert v["2"] == pytest.approx(8.0)


def test_opposing_current_sources_balance_on_capacitor():
    # Net akım sıfır: kondansatör dolmaz, "kararlı hâl yok" denmemeli
    r = _post("I1 0 1 DC 2m\nI2 1 0 DC 2m\nC1 1 0 10u\n")
    assert "dolar" not in r.text
