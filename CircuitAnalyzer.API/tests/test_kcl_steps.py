"""
KCL adım üreticisi testleri — sembolik + sayısal yerine koyma.

Ana kontrol: üretilen her sayısal denklem (ve süperdüğüm kısıtı),
lcapy'nin çözdüğü düğüm gerilimleri yerine konduğunda sağlanmalıdır.
"""

import re

import pytest
import sympy

from tests.conftest import as_complex
from tests.test_thevenin import BRIDGE, GND


def kcl_step(steps):
    return next(s for s in steps if s.title.startswith("KCL"))


def _to_sympy(text):
    """'(V_2 - 12)/1000 + V_2/(-j31.83)' → SymPy ifadesi."""
    text = re.sub(r"(?<![\w.])j(\d[\d.]*(?:e[+-]?\d+)?)", r"(\1*I)", text)
    return sympy.sympify(text)


def residual(equation, node_voltages):
    """Denklemi çözüm gerilimleriyle değerlendir → (|sol − sağ|, ölçek)."""
    lhs, rhs = equation.split("=")
    expr = sympy.expand(_to_sympy(lhs) - _to_sympy(rhs))
    subs = {
        sympy.Symbol(f"V_{node}"): sympy.sympify(as_complex(nv.value))
        for node, nv in node_voltages.items()
    }
    terms = [complex(t.subs(subs).evalf()) for t in sympy.Add.make_args(expr)]
    return abs(sum(terms)), max(sum(abs(t) for t in terms), 1e-12)


def numeric_equations(step):
    eqs = []
    for entry in step.result_snapshot["kcl_equations"]:
        eqs.append(entry["numeric"])
        eqs.extend(entry.get("constraints", []))
    return eqs


CASES = {
    "dc_divider": (f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}", "DC", None),
    "ac_rc": (f"VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nC1 2 0 100u\n{GND}",
              "AC_PHASOR", 50),
    "ac_rl_phase": (f"VAC1 1 0 AC_PHASOR(20, 45)\nR1 1 2 50\nL1 2 0 100m\n{GND}",
                    "AC_PHASOR", 60),
    "ac_bridge_z": (BRIDGE, "AC_PHASOR", 1000),
    "dc_supernode_lc": (
        "V1 1 0 DC 12\nR1 1 2 1k\nV2 2 3 DC 5\nR2 3 0 2k\nR3 2 0 4k\n"
        f"C1 3 0 1u\nL1 1 4 1m\nR4 4 5 100\nR5 5 0 50\n{GND}", "DC", None),
    "ac_supernode": (
        "VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nVAC2 2 3 AC_PHASOR(5, 90)\n"
        f"C1 3 0 10u\nL1 2 0 50m\n{GND}", "AC_PHASOR", 100),
}


@pytest.mark.parametrize("name", list(CASES))
def test_numeric_kcl_satisfied_by_solution(solve, name):
    net, mode, f = CASES[name]
    results, steps, errors = solve(net, mode, f)
    assert not [e for e in errors if e.startswith("⚠")], errors
    step = kcl_step(steps)
    eqs = numeric_equations(step)
    assert eqs
    for eq in eqs:
        err, scale = residual(eq, results.node_voltages)
        # 4 anlamlı basamaklı katsayılar → ~1e-3 bağıl hata payı
        assert err <= 2e-3 * scale, f"{eq}: kalan={err:.3g}, ölçek={scale:.3g}"


def test_dc_divider_exact_text(solve):
    net, mode, f = CASES["dc_divider"]
    step = kcl_step(solve(net, mode, f)[1])
    assert step.equations == [
        "V_1 = 12 V (gerilim kaynağı zinciriyle GND'ye bağlı — bilinen düğüm)",
        "Düğüm 2 (sembolik): (V_2 - V_1)/R1 + V_2/R2 = 0",
        "Düğüm 2 (sayısal):  (V_2 - 12)/1000 + V_2/2000 = 0",
    ]
    assert "\\frac{V_{2} - 12}{1000} + \\frac{V_{2}}{2000} = 0" in step.latex_formula


def test_symbolic_line_precedes_numeric_line(solve):
    net, mode, f = CASES["ac_rc"]
    eqs = kcl_step(solve(net, mode, f)[1]).equations
    sym = next(i for i, e in enumerate(eqs) if "(sembolik)" in e)
    assert "(sayısal)" in eqs[sym + 1]
    assert "Z_C1" in eqs[sym]
    assert "(-j31.83)" in eqs[sym + 1]


def test_source_node_has_no_kcl_equation(solve):
    # Eski üretici "Düğüm 1: (V_1-V_2)/R1 = 0" gibi yanlış denklem yazıyordu
    net, mode, f = CASES["dc_divider"]
    step = kcl_step(solve(net, mode, f)[1])
    assert not any(e.startswith("Düğüm 1") for e in step.equations)
    assert step.result_snapshot["known_nodes"]["1"] == "12"


def test_supernode_constraint_and_dc_notes(solve):
    net, mode, f = CASES["dc_supernode_lc"]
    step = kcl_step(solve(net, mode, f)[1])
    assert "Süperdüğüm {2, 3} kısıtı (V2): V_2 - V_3 = 5" in step.equations
    assert step.result_snapshot["unknown_groups"] == [["2", "3"], ["5"]]
    assert "kapasitörler (C1) açık devredir" in step.description
    assert "bobinler (L1) kısa devredir" in step.description
    # L1 kısa devre → düğüm 4 bilinen (= V1)
    assert step.result_snapshot["known_nodes"]["4"] == "12"


def test_ac_known_node_is_phasor(solve):
    net, mode, f = CASES["ac_rl_phase"]
    step = kcl_step(solve(net, mode, f)[1])
    # 20∠45° = 14.14 + j14.14
    assert step.result_snapshot["known_nodes"]["1"] == "14.14+j14.14"
    assert "(V_2 - (14.14+j14.14))/50" in step.result_snapshot["kcl_equations"][0]["numeric"]


def test_latex_has_no_malformed_imaginary(solve):
    for name in ("ac_rc", "ac_bridge_z", "ac_supernode"):
        net, mode, f = CASES[name]
        for step in solve(net, mode, f)[1]:
            assert "j-" not in (step.latex_formula or ""), (name, step.title)


def test_ac_without_frequency_skips_numeric_line(solve):
    from explainer.step_generator import generate_kcl_steps
    from parser.netlist_parser import parse_netlist

    net, _, _ = CASES["ac_rc"]
    step = generate_kcl_steps(parse_netlist(net), frequency=None, is_dc=False)[0]
    assert not any("(sayısal)" in e for e in step.equations)
    assert "Frekans belirtilmediği" in step.description
