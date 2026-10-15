"""
Thevenin eşdeğeri testleri — DC ve AC (karmaşık Vth / Zth).

Beklenen değerler kapalı-form devre formüllerinden (elle hesap)
türetilir; lcapy çıktısı bunlarla karşılaştırılır.
"""

import cmath
import math

import pytest

from tests.conftest import as_complex

GND = "* GND1 — Referans toprak (Node 0)"


def phasor(mag, deg):
    return cmath.rect(mag, math.radians(deg))


def par(a, b):
    return a * b / (a + b)


def assert_close(actual, expected, rel=1e-4):
    assert abs(actual - expected) <= rel * max(abs(expected), 1e-9), (
        f"{actual} != {expected}"
    )


# ═══════════════════════════════════════════════════════
#  DC
# ═══════════════════════════════════════════════════════

def test_dc_thevenin_voltage_divider(solve):
    # Vth = 12·2k/(1k+2k) = 8 V,  Zth = 1k ∥ 2k = 666.67 Ω
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="THEVENIN",
                               terminals=("2", "0"))
    th = results.thevenin
    assert th is not None, errors
    assert_close(as_complex(th.vth), 8.0)
    assert_close(as_complex(th.zth), 2000 / 3)


def test_dc_thevenin_capacitor_is_open(solve):
    # DC'de C açık devre: Zth = 1k ∥ 2k (C etkisiz) — eski kod s'yi
    # yerine koyamadığı için Zth=0 dönüyordu
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\nC1 2 0 1u\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="THEVENIN",
                               terminals=("2", "0"))
    th = results.thevenin
    assert th is not None, errors
    assert_close(as_complex(th.vth), 8.0)
    assert_close(as_complex(th.zth), 2000 / 3)


def test_dc_thevenin_inductor_is_short(solve):
    # DC'de L kısa devre: Zth = R1 ∥ (R2 + 0) = 1k ∥ 2k
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nL1 2 3 10m\nR2 3 0 2k\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="THEVENIN",
                               terminals=("2", "0"))
    th = results.thevenin
    assert th is not None, errors
    assert_close(as_complex(th.vth), 8.0)
    assert_close(as_complex(th.zth), 2000 / 3)


def test_dc_thevenin_infinite_impedance_reports_error(solve):
    # Port yalnızca kapasitörlerle bağlı: DC'de Zth = ∞ → Thevenin tanımsız
    net = f"V1 1 0 DC 12\nC1 1 2 1u\nC2 2 0 1u\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="THEVENIN",
                               terminals=("2", "0"))
    assert results.thevenin is None
    assert any("sonsuz" in e for e in errors), errors


# ═══════════════════════════════════════════════════════
#  AC
# ═══════════════════════════════════════════════════════

def test_ac_thevenin_rc_lowpass(solve):
    # VAC=10∠0°, f=50 Hz, R=100 Ω, C=100 µF — çıkış C üzerinde
    f, R, C = 50, 100, 100e-6
    vs = phasor(10, 0)
    zc = 1 / (1j * 2 * math.pi * f * C)        # −j31.83 Ω
    vth = vs * zc / (R + zc)                    # 0.920 − j2.890 V
    zth = par(R, zc)                            # 9.200 − j28.90 Ω

    net = f"VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nC1 2 0 100u\n{GND}"
    results, _, errors = solve(net, "AC_PHASOR", f, "THEVENIN", ("2", "0"))
    th = results.thevenin
    assert th is not None, errors
    assert_close(as_complex(th.vth), vth)
    assert_close(as_complex(th.zth), zth)
    assert th.zth.imaginary < 0          # kapasitif
    assert th.vth.phase_degrees == pytest.approx(-72.3432, abs=1e-3)


def test_ac_thevenin_rl_with_phase(solve):
    # VAC=20∠45°, f=60 Hz, R=50 Ω, L=100 mH — çıkış L üzerinde
    f, R, L = 60, 50, 0.1
    vs = phasor(20, 45)
    zl = 1j * 2 * math.pi * f * L               # j37.70 Ω
    vth = vs * zl / (R + zl)                    # −1.672 + j11.92 V
    zth = par(R, zl)

    net = f"VAC1 1 0 AC_PHASOR(20, 45)\nR1 1 2 50\nL1 2 0 100m\n{GND}"
    results, _, errors = solve(net, "AC_PHASOR", f, "THEVENIN", ("2", "0"))
    th = results.thevenin
    assert th is not None, errors
    assert_close(as_complex(th.vth), vth)
    assert_close(as_complex(th.zth), zth)
    assert th.zth.imaginary > 0          # endüktif


def _bridge_expected():
    # VAC=10∠30°, f=1 kHz; Z1=50+j30 (1–2), C1=1 µF (2–0),
    # R2=100 (2–3), R3=200 (3–0); port = düğüm 2 – düğüm 3
    f = 1000
    vs = phasor(10, 30)
    z1 = 50 + 30j
    zc = 1 / (1j * 2 * math.pi * f * 1e-6)
    r2, r3 = 100, 200

    # Açık devre gerilimi: devre olduğu gibi, V2 − V3
    zp = par(zc, r2 + r3)
    v2 = vs * zp / (z1 + zp)
    vth = v2 * r2 / (r2 + r3)

    # Kaynak kısa devre: 2–0 arası Z1 ∥ ZC, 2–3 arası R2, 3–0 arası R3
    zth = par(r2, par(z1, zc) + r3)
    return f, vth, zth


BRIDGE = (
    "VAC1 1 0 AC_PHASOR(10, 30)\nZ1 1 2 COMPLEX(50, 30)\nC1 2 0 1u\n"
    f"R2 2 3 100\nR3 3 0 200\n{GND}"
)


def test_ac_thevenin_floating_port(solve):
    # Port GND'ye bağlı değil (2–3): iki düğümlü port desteği
    f, vth, zth = _bridge_expected()
    results, _, errors = solve(BRIDGE, "AC_PHASOR", f, "THEVENIN", ("2", "3"))
    th = results.thevenin
    assert th is not None, errors
    assert_close(as_complex(th.vth), vth)
    assert_close(as_complex(th.zth), zth)
    assert (th.node_positive, th.node_negative) == ("2", "3")


def test_ac_thevenin_reversed_port_negates_vth(solve):
    # Terminaller ters çevrilince Vth işaret değiştirir, Zth aynı kalır
    f, vth, zth = _bridge_expected()
    results, _, errors = solve(BRIDGE, "AC_PHASOR", f, "THEVENIN", ("3", "2"))
    th = results.thevenin
    assert th is not None, errors
    assert_close(as_complex(th.vth), -vth)
    assert_close(as_complex(th.zth), zth)


def test_ac_thevenin_via_api(client):
    f, vth, zth = _bridge_expected()
    resp = client.post("/analyze", json={
        "netlist": BRIDGE,
        "mode": "AC_PHASOR",
        "frequency": f,
        "analysis_type": "THEVENIN",
        "thevenin_terminals": {"node_positive": "2", "node_negative": "3"},
    })
    assert resp.status_code == 200
    th = resp.json()["results"]["thevenin"]
    assert_close(complex(th["vth"]["real"], th["vth"]["imaginary"]), vth)
    assert_close(complex(th["zth"]["real"], th["zth"]["imaginary"]), zth)
