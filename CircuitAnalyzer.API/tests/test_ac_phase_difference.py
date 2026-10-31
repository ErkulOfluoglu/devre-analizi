"""
Farklı fazlı AC kaynaklı devreler, beklenen değerler elle hesaplı.

Yalnız dirençli devrede lcapy çözümü zaman bölgesinde verir; sanal kısım kaybolmamalı.
"""

import cmath
import math

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

GND = "\n* GND1 — Referans toprak"


def _analyze(netlist: str, analysis_type: str = "NODAL") -> dict:
    resp = client.post("/analyze", json={"netlist": netlist, "mode": "AC_PHASOR",
                                         "analysis_type": analysis_type, "value_display": "PEAK"})
    assert resp.status_code == 200, resp.text
    return resp.json()["results"]


def _value(entry) -> complex:
    v = entry["value"]
    return complex(v) if isinstance(v, (int, float)) else complex(v["real"], v["imaginary"])


def _rect(mag: float, deg: float) -> complex:
    return cmath.rect(mag, math.radians(deg))


@pytest.mark.parametrize("analysis_type", ["NODAL", "MESH"])
@pytest.mark.parametrize("source", [
    "V1 1 0 AC_PHASOR(100, 0)\nV2 2 0 AC_PHASOR(100, 90)\n",
    "V1 1 0 SINE(0 100 50 0 0 0)\nV2 2 0 SINE(0 100 50 0 0 90)\n",
])
def test_resistive_circuit_keeps_imaginary_part(source, analysis_type):
    # V3 = (V1 + V2) / 3 (eşit dirençler); I_R3 = V3 / 10, I_R1 = (V1 - V3) / 10
    r = _analyze(f"{source}R1 1 3 10\nR2 2 3 10\nR3 3 0 10\n{GND}", analysis_type)
    v1, v2 = 100 + 0j, 100j
    v3 = (v1 + v2) / 3
    assert abs(_value(r["node_voltages"]["2"]) - v2) < 1e-3
    assert abs(_value(r["node_voltages"]["3"]) - v3) < 1e-3
    assert abs(_value(r["element_currents"]["R3"]) - v3 / 10) < 1e-3
    assert abs(_value(r["element_currents"]["R1"]) - (v1 - v3) / 10) < 1e-3


def test_resistive_single_source_with_phase():
    # I = 100∠30° / (10 + 10)
    r = _analyze(f"V1 1 0 AC_PHASOR(100, 30)\nR1 1 2 10\nR2 2 0 10\n{GND}")
    assert abs(_value(r["element_currents"]["R1"]) - _rect(5, 30)) < 1e-3
    assert abs(_value(r["node_voltages"]["2"]) - _rect(50, 30)) < 1e-3
