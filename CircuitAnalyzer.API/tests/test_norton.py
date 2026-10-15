"""
Norton eşdeğeri testleri — DC ve AC.

Beklenen değerler: In = Isc (terminaller kısa devre), Zn = Zth,
ve dualite In = Vth / Zth.
"""

import math

from tests.conftest import as_complex
from tests.test_thevenin import (
    BRIDGE, GND, _bridge_expected, assert_close, par, phasor
)


def test_dc_norton_voltage_divider(solve):
    # Kısa devre 2–0: R2 devre dışı → In = 12 / 1k = 12 mA; Zn = 1k ∥ 2k
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}"
    results, steps, errors = solve(net, "DC", analysis_type="NORTON",
                                   terminals=("2", "0"))
    no = results.norton
    assert no is not None, errors
    assert results.thevenin is None
    assert_close(as_complex(no.i_n), 0.012)
    assert_close(as_complex(no.z_n), 2000 / 3)
    assert_close(as_complex(no.y_n), 1.5e-3)
    assert any(s.title == "Norton Sonuçları" for s in steps)
    assert not [e for e in errors if "tutarlılık" in e]


def test_ac_norton_rc_lowpass(solve):
    # Kısa devre C üzerinde → In = Vs / R = 0.1∠0° A; Zn = R ∥ ZC
    f, R, C = 50, 100, 100e-6
    zc = 1 / (1j * 2 * math.pi * f * C)
    net = f"VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nC1 2 0 100u\n{GND}"
    results, _, errors = solve(net, "AC_PHASOR", f, "NORTON", ("2", "0"))
    no = results.norton
    assert no is not None, errors
    assert_close(as_complex(no.i_n), 0.1)
    assert_close(as_complex(no.z_n), par(R, zc))
    assert_close(as_complex(no.y_n), 1 / R + 1 / zc)


def test_ac_norton_rl_phase(solve):
    # In = Vs / R (L kısa devre ile atlanır) = 20∠45° / 50 = 0.4∠45° A
    f, R, L = 60, 50, 0.1
    zl = 1j * 2 * math.pi * f * L
    net = f"VAC1 1 0 AC_PHASOR(20, 45)\nR1 1 2 50\nL1 2 0 100m\n{GND}"
    results, _, errors = solve(net, "AC_PHASOR", f, "NORTON", ("2", "0"))
    no = results.norton
    assert no is not None, errors
    assert_close(as_complex(no.i_n), phasor(0.4, 45))
    assert_close(as_complex(no.z_n), par(R, zl))


def test_ac_norton_floating_port_duality(solve):
    # Dualite: In = Vth / Zth, Zn = Zth
    f, vth, zth = _bridge_expected()
    results, _, errors = solve(BRIDGE, "AC_PHASOR", f, "NORTON", ("2", "3"))
    no = results.norton
    assert no is not None, errors
    assert_close(as_complex(no.i_n), vth / zth)
    assert_close(as_complex(no.z_n), zth)


def test_norton_matches_thevenin_from_solver(solve):
    # Aynı devre için solver'ın Thevenin ve Norton çıktıları tutarlı olmalı
    f, _, _ = _bridge_expected()
    th = solve(BRIDGE, "AC_PHASOR", f, "THEVENIN", ("2", "3"))[0].thevenin
    no = solve(BRIDGE, "AC_PHASOR", f, "NORTON", ("2", "3"))[0].norton
    assert_close(as_complex(no.z_n), as_complex(th.zth))
    assert_close(as_complex(no.i_n) * as_complex(no.z_n), as_complex(th.vth))


def test_norton_port_across_voltage_source_is_undefined(solve):
    # Port doğrudan ideal kaynağa paralel: Zth = 0 → In sonsuz
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="NORTON",
                               terminals=("1", "0"))
    assert results.norton is None
    assert any("Norton eşdeğeri tanımsız" in e for e in errors), errors


def test_dc_norton_infinite_impedance(solve):
    # Port sadece kapasitörlerle bağlı: DC'de Yn = 0 → Zn = ∞, In = 0
    net = f"V1 1 0 DC 12\nC1 1 2 1u\nC2 2 0 1u\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="NORTON",
                               terminals=("2", "0"))
    no = results.norton
    assert no is not None, errors
    assert no.z_n is None
    assert no.y_n.magnitude == 0
    assert no.i_n.magnitude == 0


def test_norton_without_terminals_reports_error(solve):
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="NORTON")
    assert results.norton is None
    assert any("terminal çifti" in e for e in errors), errors


def test_norton_via_api(client):
    resp = client.post("/analyze", json={
        "netlist": f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}",
        "mode": "DC",
        "analysis_type": "NORTON",
        "thevenin_terminals": {"node_positive": "2"},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis_type"] == "NORTON"
    no = body["results"]["norton"]
    assert no["i_n"]["real"] == 0.012
    assert abs(no["z_n"]["real"] - 666.666667) < 1e-5
