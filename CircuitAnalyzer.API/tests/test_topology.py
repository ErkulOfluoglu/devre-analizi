"""
Seri/paralel tanıma testleri.

Ana kontrol: Tam indirgenebilen devrelerde son eşdeğer kol, kaynaktan
görülen giriş empedansına (Zin = Vs / I_kaynak, lcapy çözümünden) eşittir.
"""

import math

import pytest

from explainer.topology import reduce_series_parallel
from parser.netlist_parser import parse_netlist
from tests.conftest import as_complex
from tests.test_thevenin import GND, assert_close, par


def zin_from_solution(results, source_id, vs):
    # lcapy pasif işaret kuralı: kaynaktan çıkan akım = −I(kaynak)
    i = as_complex(results.element_currents[source_id].value)
    return vs / -i


def final_reduction(results):
    return results.reductions[-1]


def test_dc_parallel_then_series(solve):
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\nR3 2 0 2k\n{GND}"
    results, steps, _ = solve(net, "DC")
    reds = results.reductions
    assert [(r.type, r.elements) for r in reds] == [
        ("parallel", ["R2", "R3"]),
        ("series", ["R1", "Req1"]),
    ]
    assert reds[0].formula == (
        "Req1 = R2·R3/(R2+R3) = 2000·2000/(2000+2000) = 1000 Ω"
    )
    assert reds[1].formula == "Req2 = R1 + Req1 = 1000 + 1000 = 2000 Ω"
    assert sorted(reds[1].original_elements) == ["R1", "R2", "R3"]
    assert_close(as_complex(reds[1].impedance), zin_from_solution(results, "V1", 12))
    step = next(s for s in steps if s.title.startswith("Seri/Paralel"))
    assert "R2 ∥ R3" in step.equations[0]
    assert "R1 ve Req1 seri bağlı" in step.equations[1]


def test_dc_ladder(solve):
    # R3+R4 = 2k → ∥ R2 = 1k → + R1 = 2k
    net = (f"V1 1 0 DC 10\nR1 1 2 1k\nR2 2 0 2k\nR3 2 3 1k\nR4 3 0 1k\n{GND}")
    results, _, _ = solve(net, "DC")
    kinds = [r.type for r in results.reductions]
    assert kinds == ["series", "parallel", "series"]
    assert_close(as_complex(final_reduction(results).impedance), 2000)
    assert_close(as_complex(final_reduction(results).impedance),
                 zin_from_solution(results, "V1", 10))


def test_ac_series_capacitors_use_inverse_rule(solve):
    f = 1000
    net = f"VAC1 1 0 AC_PHASOR(5, 0)\nC1 1 2 10u\nC2 2 0 10u\n{GND}"
    results, _, _ = solve(net, "AC_PHASOR", f)
    red = final_reduction(results)
    assert red.result_name == "Ceq1"
    assert red.formula.startswith("Ceq1 = C1·C2/(C1+C2) = ")
    assert red.formula.endswith("0,000005 F")
    assert_close(as_complex(red.impedance), 1 / (1j * 2 * math.pi * f * 5e-6))
    assert_close(as_complex(red.impedance), zin_from_solution(results, "VAC1", 5))


def test_ac_parallel_capacitors_add(solve):
    net = f"VAC1 1 0 AC_PHASOR(5, 0)\nR1 1 2 10\nC1 2 0 1u\nC2 2 0 2u\n{GND}"
    red = solve(net, "AC_PHASOR", 50)[0].reductions[0]
    assert red.formula.startswith("Ceq1 = C1 + C2 = ")


def test_ac_mixed_rlc_matches_input_impedance(solve):
    f = 50
    w = 2 * math.pi * f
    net = (f"VAC1 1 0 AC_PHASOR(10, 30)\nR1 1 2 100\nL1 2 3 100m\n"
           f"C1 3 0 10u\nR2 3 0 200\n{GND}")
    results, _, _ = solve(net, "AC_PHASOR", f)
    expected = 100 + 1j * w * 0.1 + par(1 / (1j * w * 10e-6), 200)
    red = final_reduction(results)
    assert red.result_name.startswith("Zeq")
    assert_close(as_complex(red.impedance), expected)
    vs = 10 * complex(math.cos(math.radians(30)), math.sin(math.radians(30)))
    assert_close(as_complex(red.impedance), zin_from_solution(results, "VAC1", vs))


def test_wheatstone_bridge_has_no_reductions(solve):
    net = (f"V1 1 0 DC 10\nR1 1 2 1k\nR2 1 3 2k\nR3 2 3 3k\n"
           f"R4 2 0 4k\nR5 3 0 5k\n{GND}")
    results, steps, _ = solve(net, "DC")
    assert results.reductions == []
    assert not any(s.title.startswith("Seri/Paralel") for s in steps)


def test_thevenin_terminal_is_not_eliminated(solve):
    # Düğüm 3 port terminali → R2a ve R2b seri birleştirilmez
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nR2a 2 3 1k\nR2b 3 0 1k\n{GND}"
    no_port = solve(net, "DC")[0].reductions
    with_port = solve(net, "DC", analysis_type="THEVENIN",
                      terminals=("3", "0"))[0].reductions
    assert any({"R2a", "R2b"} <= set(r.original_elements) for r in no_port)
    assert not any({"R2a", "R2b"} <= set(r.original_elements)
                   for r in with_port)
    # Düğüm 2 korunmuyor → R1 + R2a yine seri birleşir (Düğüm 1–3 arası)
    assert [(r.elements, r.nodes) for r in with_port] == [
        (["R1", "R2a"], ["1", "3"])
    ]


def test_dc_capacitor_is_open(solve):
    # DC'de C1 açık → R1, R2, R3 seri: Req = 6k
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nC1 2 0 1u\nR2 2 3 2k\nR3 3 0 3k\n{GND}"
    results, steps, _ = solve(net, "DC")
    assert_close(as_complex(final_reduction(results).impedance), 6000)
    step = next(s for s in steps if s.title.startswith("Seri/Paralel"))
    assert "kapasitörler (C1) açık" in step.description


def test_dc_inductor_not_reduced():
    parsed = parse_netlist("V1 1 0 DC 12\nR1 1 2 1k\nL1 2 3 1m\nR2 3 0 1k")
    reds, _, _, blockers = reduce_series_parallel(parsed, is_dc=True)
    assert blockers == ["L1"]
    assert all("L1" not in r.members for r in reds)


def test_ac_without_frequency_only_same_kind():
    parsed = parse_netlist(
        "VAC1 1 0 AC_PHASOR(1, 0)\nR1 1 2 1k\nR2 2 3 1k\nC1 3 0 1u")
    reds, _, _, _ = reduce_series_parallel(parsed, is_dc=False, frequency=None)
    assert [r.result_name for r in reds] == ["Req1"]   # R+C birleşmez (ω yok)
    assert reds[0].impedance == pytest.approx(2000)
