"""
Güç analizi testleri — P, Q, S, cos φ.

Kural: Fazörler tepe değerdir → S = ½·V·I*. Pasif işaret kuralı:
güç veren kaynakta emilen P negatiftir.
"""

import math

import pytest

from tests.conftest import as_complex
from tests.test_thevenin import BRIDGE, GND, assert_close, phasor


def test_dc_divider_power(solve):
    # I = 12/3k = 4 mA; P_R1 = 4²·1k = 16 mW, P_R2 = 32 mW, kaynak 48 mW verir
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}"
    pw = solve(net, "DC")[0].power
    assert pw.elements["R1"].active_power == pytest.approx(0.016)
    assert pw.elements["R2"].active_power == pytest.approx(0.032)
    assert pw.elements["V1"].active_power == pytest.approx(-0.048)
    assert pw.elements["V1"].role == "source"
    assert pw.elements["R1"].role == "load"
    assert pw.elements["R1"].reactive_power == 0
    assert_close(as_complex(pw.total_supplied), 0.048)
    assert pw.power_factor == pytest.approx(1.0)
    assert pw.power_factor_type == "birim"
    assert pw.balance_error < 1e-12
    assert pw.convention.startswith("DC")


def test_ac_rl_power_triangle(solve):
    f, R, L = 60, 50, 0.1
    vs = phasor(20, 45)
    zl = 1j * 2 * math.pi * f * L
    i = vs / (R + zl)
    p_r = 0.5 * abs(i) ** 2 * R                 # 2.550 W
    q_l = 0.5 * abs(i) ** 2 * zl.imag           # 1.923 VAR
    s_src = 0.5 * vs * i.conjugate()            # verilen güç

    net = f"VAC1 1 0 AC_PHASOR(20, 45)\nR1 1 2 50\nL1 2 0 100m\n{GND}"
    pw = solve(net, "AC_PHASOR", f)[0].power

    r1, l1, src = pw.elements["R1"], pw.elements["L1"], pw.elements["VAC1"]
    assert r1.active_power == pytest.approx(p_r, rel=1e-5)
    assert r1.reactive_power == 0
    assert r1.power_factor_type == "birim"
    assert l1.active_power == pytest.approx(0, abs=1e-12)
    assert l1.reactive_power == pytest.approx(q_l, rel=1e-5)
    assert l1.power_factor == pytest.approx(0, abs=1e-9)
    assert l1.power_factor_type == "geri"

    # Kaynak: emilen S negatif, verilen S = ½·Vs·I*
    assert src.active_power == pytest.approx(-s_src.real, rel=1e-5)
    assert src.reactive_power == pytest.approx(-s_src.imag, rel=1e-5)
    assert src.apparent_power == pytest.approx(abs(s_src), rel=1e-5)
    assert src.power_factor_type == "geri"

    # Devre güç faktörü = R/|Z|, endüktif → geri
    assert pw.power_factor == pytest.approx(R / abs(R + zl), rel=1e-5)
    assert pw.power_factor_type == "geri"
    assert_close(as_complex(pw.total_supplied), s_src)
    # Güç üçgeni: |S|² = P² + Q²
    assert src.apparent_power ** 2 == pytest.approx(
        src.active_power ** 2 + src.reactive_power ** 2, rel=1e-9)


def test_ac_rc_leading_power_factor(solve):
    f, R, C = 50, 100, 100e-6
    zc = 1 / (1j * 2 * math.pi * f * C)
    i = 10 / (R + zc)
    net = f"VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nC1 2 0 100u\n{GND}"
    pw = solve(net, "AC_PHASOR", f)[0].power

    c1 = pw.elements["C1"]
    assert c1.reactive_power == pytest.approx(0.5 * abs(i) ** 2 * zc.imag, rel=1e-5)
    assert c1.reactive_power < 0
    assert c1.power_factor_type == "ileri"
    assert pw.power_factor == pytest.approx(R / abs(R + zc), rel=1e-5)
    assert pw.power_factor_type == "ileri"


def test_ac_complex_impedance_element(solve):
    # Z = 50 + j30 tek başına: P = ½|I|²·50, Q = ½|I|²·30
    z = 50 + 30j
    i = 10 / z
    net = f"VAC1 1 0 AC_PHASOR(10, 0)\nZ1 1 0 COMPLEX(50, 30)\n{GND}"
    pw = solve(net, "AC_PHASOR", 1000)[0].power
    z1 = pw.elements["Z1"]
    assert z1.active_power == pytest.approx(0.5 * abs(i) ** 2 * 50, rel=1e-5)
    assert z1.reactive_power == pytest.approx(0.5 * abs(i) ** 2 * 30, rel=1e-5)
    assert z1.power_factor == pytest.approx(50 / abs(z), rel=1e-5)


def test_tellegen_balance_on_bridge(solve):
    pw = solve(BRIDGE, "AC_PHASOR", 1000)[0].power
    total = sum(as_complex(e.complex_power) for e in pw.elements.values())
    assert abs(total) < 1e-5 * as_complex(pw.total_supplied).__abs__()
    assert pw.balance_error < 1e-9
    assert_close(as_complex(pw.total_supplied), as_complex(pw.total_absorbed))


def test_dc_capacitor_draws_no_power(solve):
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nC1 2 0 1u\n{GND}"
    pw = solve(net, "DC")[0].power
    c1 = pw.elements["C1"]
    assert c1.active_power == 0
    assert c1.apparent_power == 0
    assert c1.power_factor is None


def test_power_step_and_api(client):
    resp = client.post("/analyze", json={
        "netlist": f"VAC1 1 0 AC_PHASOR(20, 45)\nR1 1 2 50\nL1 2 0 100m\n{GND}",
        "mode": "AC_PHASOR",
        "frequency": 60,
    })
    assert resp.status_code == 200
    body = resp.json()
    power = body["results"]["power"]
    assert power["power_factor_type"] == "geri"
    assert set(power["elements"]) == {"VAC1", "R1", "L1"}
    step = next(s for s in body["solution_steps"]
                if s["title"].startswith("Güç Analizi"))
    assert any("cos φ" in e for e in step["equations"])
    assert "e-17" not in " ".join(step["equations"])
