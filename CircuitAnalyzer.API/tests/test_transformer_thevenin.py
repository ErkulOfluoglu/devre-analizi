"""
Transformatörlü AC devrede Thevenin / Norton eşdeğeri (terminaller verildiğinde).

Yöntem TRANSFORMER anlatımına yönlendirilse de results.thevenin / results.norton doldurulur:
    Vth = terminaller açıkken gerilim,  Zth = bağımsız kaynaklar sıfırlanıp 1 A test akımı → V/I.
Beklenen değerler elle hesaplanır (ideal: V₂ = a·V₁, primerdeki Z sekondere Z·a² yansır, a = N₂/N₁).
"""

import math

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

GND = "\n* GND1 — Referans toprak"
W = 2.0 * math.pi * 50.0


def _post(netlist: str, analysis_type: str, terminals, mode: str = "AC_PHASOR"):
    body = {"netlist": netlist + GND, "mode": mode, "analysis_type": analysis_type,
            "value_display": "PEAK", "frequency": 50}
    if terminals:
        body["thevenin_terminals"] = {"node_positive": terminals[0], "node_negative": terminals[1]}
    return client.post("/analyze", json=body)


def _cx(c) -> complex:
    return complex(c["real"], c["imaginary"])


def _close(a: complex, b: complex, rel: float = 1e-6) -> bool:
    return abs(a - b) <= rel * max(abs(b), 1e-9)


def _titles(res) -> list:
    return [s["title"] for s in res["explanation"]]


def test_ideal_transformer_thevenin_simple():
    # V2 = 2·100 = 200 V; R1–R2 bölücü: Vth = V(3) = 200·10/20 = 100 V;  Zth = R1 ∥ R2 = 5 Ω
    net = "V1 1 0 AC_PHASOR(100, 0)\nT1 1 0 2 0 IDEAL 2\nR1 2 3 10\nR2 3 0 10"
    resp = _post(net, "THEVENIN", ("3", "0"))
    assert resp.status_code == 200, resp.text
    res = resp.json()["results"]
    assert _close(_cx(res["thevenin"]["vth"]), 100)
    assert _close(_cx(res["thevenin"]["zth"]), 5)
    assert res["norton"] is None
    assert res["transformer"] is not None                    # transformatör anlatımı kalır
    assert "Thevenin Eşdeğeri" in _titles(res)
    assert "Devreyi Tanıyalım" in _titles(res)
    assert not [e for e in resp.json()["errors"] if "Thevenin" in e]


def test_ideal_transformer_thevenin_reflected_primary_impedance():
    # Primerde seri Rp = 4 Ω, a = 2.  Sekonder yük R1 + R2 = 20 Ω primere 20/a² = 5 Ω yansır:
    #   I₁ = 100/(4 + 5), V₁ = I₁·5, V₂ = a·V₁, Vth = V(3) = V₂·R2/(R1 + R2)
    # Zth: kaynak kısa → sekonderden bakınca Rp·a² = 16 Ω:  Zth = R2 ∥ (R1 + 16)
    net = "V1 1 0 AC_PHASOR(100, 0)\nRp 1 4 4\nT1 4 0 2 0 IDEAL 2\nR1 2 3 10\nR2 3 0 10"
    a, rp, r1, r2 = 2.0, 4.0, 10.0, 10.0
    v1 = (100 / (rp + (r1 + r2) / a ** 2)) * ((r1 + r2) / a ** 2)
    vth = a * v1 * r2 / (r1 + r2)
    zth = r2 * (r1 + rp * a ** 2) / (r2 + r1 + rp * a ** 2)
    resp = _post(net, "THEVENIN", ("3", "0"))
    assert resp.status_code == 200, resp.text
    th = resp.json()["results"]["thevenin"]
    assert _close(_cx(th["vth"]), vth)
    assert _close(_cx(th["zth"]), zth)


def test_ideal_transformer_thevenin_at_secondary_terminals():
    # Terminal sekonder uçları (2–0): yük R1 + R2 = 20 Ω bağlı kalır (açık devre = terminal boşta)
    # Vth = V₂ = 111,11 V;  Zth = 20 ∥ (Rp·a² = 16) = 8,889 Ω
    net = "V1 1 0 AC_PHASOR(100, 0)\nRp 1 4 4\nT1 4 0 2 0 IDEAL 2\nR1 2 3 10\nR2 3 0 10"
    resp = _post(net, "THEVENIN", ("2", "0"))
    th = resp.json()["results"]["thevenin"]
    assert _close(_cx(th["vth"]), 100 * 5 / 9 * 2)
    assert _close(_cx(th["zth"]), 20 * 16 / 36)


def test_ideal_transformer_norton():
    # Aynı devre, terminal 3–0: In = Vth/Zth,  Zn = Zth
    net = "V1 1 0 AC_PHASOR(100, 0)\nT1 1 0 2 0 IDEAL 2\nR1 2 3 10\nR2 3 0 10"
    resp = _post(net, "NORTON", ("3", "0"))
    assert resp.status_code == 200, resp.text
    res = resp.json()["results"]
    assert res["thevenin"] is None
    assert _close(_cx(res["norton"]["i_n"]), 100 / 5)
    assert _close(_cx(res["norton"]["z_n"]), 5)
    assert "Norton Eşdeğeri" in _titles(res)


def test_coupled_transformer_thevenin():
    # Yüksüz kuplajlı sargı (primer 100 V): Vth = (M/L₁)·V₁, M = k√(L₁L₂) → k√(L₂/L₁)·100
    # Zth: primer kısa devre → sekonder jωL₂(1 − k²)
    net = "V1 1 0 AC_PHASOR(100, 0)\nT1 1 0 2 0 COUPLED 0.1 0.2 0.8"
    resp = _post(net, "THEVENIN", ("2", "0"))
    assert resp.status_code == 200, resp.text
    th = resp.json()["results"]["thevenin"]
    assert _close(_cx(th["vth"]), 0.8 * math.sqrt(0.2 / 0.1) * 100)
    assert _close(_cx(th["zth"]), 1j * W * 0.2 * (1 - 0.8 ** 2))


def test_without_terminals_nothing_is_added():
    net = "V1 1 0 AC_PHASOR(100, 0)\nT1 1 0 2 0 IDEAL 2\nR1 2 0 10"
    resp = _post(net, "THEVENIN", None)
    assert resp.status_code == 200, resp.text
    res = resp.json()["results"]
    assert res["thevenin"] is None
    assert "Thevenin Eşdeğeri" not in _titles(res)


def test_transformer_method_has_no_equivalent_section():
    net = "V1 1 0 AC_PHASOR(100, 0)\nT1 1 0 2 0 IDEAL 2\nR1 2 3 10\nR2 3 0 10"
    resp = _post(net, "TRANSFORMER", ("3", "0"))
    res = resp.json()["results"]
    assert res["thevenin"] is None and res["norton"] is None
    assert "Thevenin Eşdeğeri" not in _titles(res)


def test_dc_transformer_circuit_keeps_existing_behavior():
    # DC'de transformatör çalışmaz: sargılar açık devre sayılıp kalan devre çözülür (mevcut davranış)
    net = "V1 1 0 DC 12\nR0 1 2 10\nR1 2 0 10\nT1 2 0 3 0 IDEAL 2\nR2 3 0 5"
    resp = _post(net, "THEVENIN", ("2", "0"), mode="DC")
    assert resp.status_code == 200, resp.text
    res = resp.json()["results"]
    assert res["thevenin"] is not None
    assert _close(_cx(res["thevenin"]["vth"]), 6)         # 12·10/20
    assert _close(_cx(res["thevenin"]["zth"]), 5)         # 10 ∥ 10
    assert "Thevenin Eşdeğeri" not in _titles(res)
