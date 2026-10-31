"""
Farklı fazlı AC kaynaklı devreler, beklenen değerler elle hesaplı.

Yalnız dirençli devrede lcapy çözümü zaman bölgesinde verir; sanal kısım kaybolmamalı.
"""

import cmath
import math
import time

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


# ═══════════════════════════════════════════════════════
#  Karmaşık empedans (Z) + farklı fazlı kaynaklar
#  lcapy bu devrelerde yanlış sonuç veriyor ve dakikalarca takılıyordu → sayısal çözücü.
# ═══════════════════════════════════════════════════════

# Üçgen: üç kaynak doğrudan empedansların uçlarında
Z1, Z2, Z3 = complex(10, 5), complex(20, -10), complex(5, 8)
DELTA = ("V1 1 0 AC_PHASOR(100, 0)\nV2 2 0 AC_PHASOR(100, -120)\nV3 3 0 AC_PHASOR(100, 120)\n"
         "Z1 1 2 COMPLEX(10, 5)\nZ2 2 3 COMPLEX(20, -10)\nZ3 3 1 COMPLEX(5, 8)\n")
# Ara düğümlü: V1 ve V2 kaynak, Z1–Z2 düğüm 3'e, Z3 düğüm 3'ten toprağa
STAR = ("V1 1 0 AC_PHASOR(100, 0)\nV2 2 0 AC_PHASOR(100, 90)\n"
        "Z1 1 3 COMPLEX(10, 5)\nZ2 2 3 COMPLEX(20, -10)\nZ3 3 0 COMPLEX(5, 8)\n")
TIME_LIMIT = 10.0    # lcapy bu devrelerde 30 sn ... dakikalar sürüyordu (ilk çağrı lcapy içe aktarımını da kapsar)


def _timed_analyze(netlist: str, analysis_type: str = "NODAL", terminals=None):
    body = {"netlist": netlist + GND, "mode": "AC_PHASOR", "analysis_type": analysis_type,
            "value_display": "PEAK", "frequency": 50}
    if terminals:
        body["thevenin_terminals"] = {"node_positive": terminals[0], "node_negative": terminals[1]}
    start = time.perf_counter()
    resp = client.post("/analyze", json=body)
    elapsed = time.perf_counter() - start
    assert resp.status_code == 200, resp.text
    assert elapsed < TIME_LIMIT, f"{analysis_type} {elapsed:.1f} sn sürdü"
    return resp.json()["results"]


def _close(a: complex, b: complex, rel: float = 1e-6) -> bool:
    return abs(a - b) <= rel * max(abs(b), 1e-9)


@pytest.mark.parametrize("analysis_type", ["NODAL", "MESH", "SUPERPOSITION", "MILLMAN", "POWER"])
def test_delta_complex_impedances_branch_currents(analysis_type):
    # Kollar doğrudan kaynak gerilimlerinin farkıyla: I_Z1 = (V1 − V2)/Z1, I_Z2 = (V2 − V3)/Z2, ...
    v1, v2, v3 = _rect(100, 0), _rect(100, -120), _rect(100, 120)
    r = _timed_analyze(DELTA, analysis_type)
    for name, v_from, v_to, z in (("Z1", v1, v2, Z1), ("Z2", v2, v3, Z2), ("Z3", v3, v1, Z3)):
        assert _close(_value(r["element_currents"][name]), (v_from - v_to) / z), name
    assert _close(_value(r["node_voltages"]["2"]), v2)


def test_delta_expected_values_by_hand():
    # (150 + j86,603)/(10 + j5) = 15,464 + j0,928 (elle bölünmüş değer)
    r = _timed_analyze(DELTA)
    i_z1 = _value(r["element_currents"]["Z1"])
    assert abs(i_z1 - complex(15.4641, 0.9282)) < 1e-3


@pytest.mark.parametrize("analysis_type", ["NODAL", "MESH", "SUPERPOSITION", "MILLMAN", "POWER"])
def test_star_complex_impedances_intermediate_node(analysis_type):
    v1, v2 = _rect(100, 0), _rect(100, 90)
    v3 = (v1 / Z1 + v2 / Z2) / (1 / Z1 + 1 / Z2 + 1 / Z3)
    r = _timed_analyze(STAR, analysis_type)
    assert _close(_value(r["node_voltages"]["3"]), v3)
    assert _close(_value(r["element_currents"]["Z1"]), (v1 - v3) / Z1)
    assert _close(_value(r["element_currents"]["Z2"]), (v2 - v3) / Z2)
    assert _close(_value(r["element_currents"]["Z3"]), v3 / Z3)


def test_star_thevenin_and_norton():
    # Düğüm 3 – toprak: Zth = Z1 ∥ Z2 ∥ Z3, Vth = V3, In = V1/Z1 + V2/Z2 (Z3 portta kalır)
    v1, v2 = _rect(100, 0), _rect(100, 90)
    zth = 1 / (1 / Z1 + 1 / Z2 + 1 / Z3)
    vth = (v1 / Z1 + v2 / Z2) * zth
    th = _timed_analyze(STAR, "THEVENIN", ("3", "0"))["thevenin"]
    assert _close(complex(th["vth"]["real"], th["vth"]["imaginary"]), vth)
    assert _close(complex(th["zth"]["real"], th["zth"]["imaginary"]), zth)
    no = _timed_analyze(STAR, "NORTON", ("3", "0"))["norton"]
    assert _close(complex(no["i_n"]["real"], no["i_n"]["imaginary"]), v1 / Z1 + v2 / Z2)
    assert _close(complex(no["z_n"]["real"], no["z_n"]["imaginary"]), zth)


def test_complex_impedance_with_equal_phases_is_also_fast():
    net = STAR.replace("AC_PHASOR(100, 90)", "AC_PHASOR(100, 0)")
    v3 = (100 / Z1 + 100 / Z2) / (1 / Z1 + 1 / Z2 + 1 / Z3)
    r = _timed_analyze(net)
    assert _close(_value(r["node_voltages"]["3"]), v3)
