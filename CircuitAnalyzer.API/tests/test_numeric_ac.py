"""
Sayısal AC çözücü (solver/numeric_ac.py) — beklenen değerler temel devre formülleriyle ELLE hesaplanır.

İşaret kuralları lcapy ile aynıdır: iki uçlu elemanın akımı n+ → n−, gerilim kaynağı güç verirken
akımı negatif; bağımsız akım kaynağında cct[id].I = −(kaynak değeri).
"""

import cmath
import math

import pytest

from parser.netlist_parser import parse_netlist
from solver.numeric_ac import NumericAcUnsupported, NumericCircuit, prefers_numeric

F = 50.0
W = 2 * math.pi * F


def _cct(netlist: str, frequency=F) -> NumericCircuit:
    return NumericCircuit(parse_netlist(netlist), frequency)


def _rect(mag: float, deg: float) -> complex:
    return cmath.rect(mag, math.radians(deg))


def _close(a: complex, b: complex, rel: float = 1e-9) -> bool:
    return abs(a - b) <= rel * max(abs(b), 1e-12)


def test_voltage_divider_with_complex_impedances():
    # V2 = V1·Z2/(Z1+Z2),  I = V1/(Z1+Z2)
    z1, z2 = complex(10, 5), complex(20, -10)
    v1 = _rect(10, 30)
    cct = _cct("V1 1 0 AC_PHASOR(10, 30)\nZ1 1 2 COMPLEX(10, 5)\nZ2 2 0 COMPLEX(20, -10)")
    assert _close(cct["1"].V, v1)
    assert _close(cct["2"].V, v1 * z2 / (z1 + z2))
    assert _close(cct["Z1"].I, v1 / (z1 + z2))
    assert _close(cct["V1"].I, -v1 / (z1 + z2))        # kaynak güç verir → pasif işarette negatif


def test_series_rl_uses_frequency():
    # I = V/(R + jωL),  V_L = I·jωL
    cct = _cct("V1 1 0 AC_PHASOR(100, 0)\nR1 1 2 100\nL1 2 0 0.5")
    i = 100 / complex(100, W * 0.5)
    assert _close(cct["R1"].I, i)
    assert _close(cct["2"].V, i * 1j * W * 0.5)


def test_capacitor_and_current_source_signs():
    # SPICE: I1 0 1 → akım kaynak içinden 0 → 1, devreye 1. düğümden verilir: V1 = I·Z
    # Z = R ∥ (1/jωC);  cct[id].I = −(kaynak değeri)
    cct = _cct("I1 0 1 AC_PHASOR(2, 90)\nR1 1 0 10\nC1 1 0 100u")
    y = 1 / 10 + 1j * W * 100e-6
    v1 = _rect(2, 90) / y
    assert _close(cct["1"].V, v1)
    assert _close(cct["I1"].I, -_rect(2, 90))
    assert _close(cct["C1"].I, v1 * 1j * W * 100e-6)


def test_ideal_transformer_reflected_impedance():
    # a = N2/N1 = 2: Z_giriş = Z/a² (primerden bakılan), V2 = a·V1, I1 = a·I2
    a, z, rs = 2.0, complex(10, 5), 4.0
    cct = _cct("V1 1 0 AC_PHASOR(100, 0)\nR1 1 2 4\nT1 2 0 3 0 IDEAL 2\nZ2 3 0 COMPLEX(10, 5)")
    z_in = z / a ** 2
    i1 = 100 / (rs + z_in)
    v_primary = i1 * z_in
    assert _close(cct["2"].V, v_primary)
    assert _close(cct["3"].V, a * v_primary)
    assert _close(cct["Z2"].I, a * v_primary / z)
    # Transformatör ölçüm kaynakları uca GİREN akımı verir; ideal: I1 = a·(sekondere ÇIKAN akım)
    assert _close(cct["Vsense_T1_p"].I, i1)
    assert _close(cct["Vsense_T1_s"].I, -i1 / a)


def test_coupled_inductors_equations():
    # V1 = jωL1·I1 + jωM·I2,  V2 = jωM·I1 + jωL2·I2 = −R·I2  (R yük, I2 sargıya girer)
    l1, l2, k, r, vs = 0.1, 0.2, 0.8, 10.0, 100.0
    m = k * math.sqrt(l1 * l2)
    cct = _cct("V1 1 0 AC_PHASOR(100, 0)\nT1 1 0 2 0 COUPLED 0.1 0.2 0.8\nR1 2 0 10")
    # I2 = −jωM·I1 / (R + jωL2),  V1 = vs → I1 = vs / (jωL1 + (ωM)²/(R + jωL2))
    i1 = vs / (1j * W * l1 + (W * m) ** 2 / (r + 1j * W * l2))
    i2 = -1j * W * m * i1 / (r + 1j * W * l2)
    assert _close(cct["Vsense_T1_p"].I, i1)
    assert _close(cct["Vsense_T1_s"].I, i2)
    assert _close(cct["2"].V, -r * i2)


def test_dependent_sources():
    # E1: V(3) = 3·V_R2.   G1: yük R4'e 0,01·V_R2 akımı basar (n− ucundan). H1: V(5) = 5·I_R1
    cct = _cct(
        "V1 1 0 AC_PHASOR(12, 0)\nR1 1 2 10\nR2 2 0 20\n"
        "E1 3 0 V(R2) 3\nR3 3 0 50\n"
        "G1 4 0 V(R2) 0.01\nR4 4 0 100\n"
        "H1 5 0 I(R1) 5\nR5 5 0 40")
    i = 12 / 30
    v_r2 = i * 20
    assert _close(cct["2"].V, v_r2)
    assert _close(cct["3"].V, 3 * v_r2)
    # G1 4 0: akım kaynak içinden 4 → 0, devreye 0 düğümünden verilir → R4 üzerinde V(4) = −0,01·V_R2·100
    assert _close(cct["4"].V, -0.01 * v_r2 * 100)
    assert _close(cct["5"].V, 5 * i)


def test_current_controlled_current_source_and_sense_currents():
    # F1: kaynak akımı 2·I_V1 (I_V1 = lcapy işareti, güç verirken negatif)
    cct = _cct("V1 1 0 AC_PHASOR(10, 0)\nR1 1 0 20\nF1 2 0 I(V1) 2\nR2 2 0 50")
    i_v1 = -10 / 20
    i_f = 2 * i_v1
    # F1 n+=2 → n−=0: akım kaynak içinden 2 → 0, yani devreye 0'dan girer; V(2) = −i_f·R2
    assert _close(cct["2"].V, -i_f * 50)
    assert _close(cct["Vsense_F1"].I, i_f)


def test_thevenin_and_norton_of_complex_circuit():
    # 100∠0 – Z1 – düğüm 2 – Z2 – toprak; port 2–0'da Z2 var:
    # Vth = V·Z2/(Z1+Z2), Zth = Z1 ∥ Z2, In = V/Z1
    z1, z2 = complex(10, 5), complex(20, -10)
    cct = _cct("V1 1 0 AC_PHASOR(100, 0)\nZ1 1 2 COMPLEX(10, 5)\nZ2 2 0 COMPLEX(20, -10)")
    th = cct.thevenin("2", "0")
    assert _close(th.V, 100 * z2 / (z1 + z2))
    assert _close(th.Z, z1 * z2 / (z1 + z2))
    no = cct.norton("2", "0")
    assert _close(no.Isc, 100 / z1)
    assert _close(no.Y, 1 / th.Z)


def test_singular_circuit_raises_not_invertible():
    # İki gerilim kaynağı doğrudan paralel (farklı değer): tekil
    cct = _cct("V1 1 0 AC_PHASOR(10, 0)\nV2 1 0 AC_PHASOR(5, 0)\nZ1 1 0 COMPLEX(1, 1)")
    with pytest.raises(ValueError, match="not invertible"):
        cct["1"].V


def test_unsupported_circuits_are_reported():
    with pytest.raises(NumericAcUnsupported):
        _cct("V1 1 0 DC 12\nZ1 1 0 COMPLEX(1, 1)")            # sıfırdan farklı DC kaynak
    with pytest.raises(NumericAcUnsupported):
        _cct("V1 1 0 AC_PHASOR(10, 0)\nL1 1 0 1m", frequency=None)   # frekanssız bobin


def test_prefers_numeric_only_for_complex_impedance_ac():
    with_z = parse_netlist("V1 1 0 AC_PHASOR(10, 0)\nZ1 1 0 COMPLEX(1, 1)")
    without_z = parse_netlist("V1 1 0 AC_PHASOR(10, 0)\nR1 1 0 10\nC1 1 0 1u")
    assert prefers_numeric(with_z, False, F)
    assert not prefers_numeric(with_z, True, F)           # DC
    assert not prefers_numeric(without_z, False, F)       # Z yok → lcapy yolu değişmez
