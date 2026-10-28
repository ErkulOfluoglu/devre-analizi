"""
Test suite for independent CURRENT SOURCE support (DC, AC phasor, AC sine).

Covers:
1. Netlist Parser:
   - "I1 0 2 DC 2m" -> ElementType.CURRENT_DC, value 0.002, nodes (0, 2)
   - "IAC1 0 1 AC_PHASOR(0.01, 30)" -> ElementType.CURRENT_AC_PHASOR, amplitude 0.01, phase 30
   - "IAC1 0 1 SINE(0 0.01 50 0 0 0)" -> ElementType.CURRENT_AC_SINE, frequency 50, amplitude 0.01
   - to_lcapy_netlist writes nodes SWAPPED for current sources ("I1 2 0 {0.002}")
   - voltage sources unaffected (nodes unswapped)
   - no parser warnings

2. Solver signs & passive sign convention (DC):
   - "I1 0 1 DC 1m" + "R1 1 0 1k" -> V1 = +1 V, I(I1) = +1 mA ("0→1"), I(R1) = +1 mA ("1→0"),
     P(I1) = -1 mW (supplies), power balance error ≈ 0
   - Reversed "I1 1 0 DC 1m" + "R1 1 0 1k" -> V1 = -1 V

3. Mixed circuit:
   - "V1 1 0 DC 10\nR1 1 2 1k\nR2 2 0 1k\nI1 0 2 DC 2m" -> V2 = 6 V, I(R1) = 4 mA,
     I(R2) = 6 mA, supplied power 52 mW = absorbed power

4. Two current sources + resistor network (hand-calculated / numpy nodal):
   - 2-unknown resistor network with 2 current sources
   - AC current source "IAC1 0 1 AC_PHASOR(0.01, 0)" with R1 1 0 100, C1 1 0 100u at 50 Hz -> V1 = 0.01 * (R || Zc)

5. KCL step generator:
   - Residual checks for equations of circuits 3 and 4
   - Symbolic equation for circuit 3 contains "I1" for node 2

6. Narrative explanation:
   - Exact text checks for KCL section, solve section, currents section, power section

7. Thevenin & Norton equivalence:
   - "I1 0 1 DC 2m\nR1 1 0 1k\nR2 1 2 1k\nR3 2 0 2k", port (2, 0) -> Vth = 1 V, Rth = 1 kΩ, In = 1 mA
   - narrative contains "akım kaynağı sıfırlanır → açık devre"
   - reduce_port_impedance gives 1000 Ω

8. Source frequency checks:
   - AC analysis with DC voltage source & AC current source notes DC sources zeroed
   - DC analysis with AC current source notes AC sources zeroed

9. API endpoints via client:
   - POST /analyze with mixed circuit -> 200, V2 = 6 V, explanation non-empty
   - POST /parse-only lists I1 with type "I_DC"
"""

import math
import re

import numpy as np
import pytest
import sympy

from explainer.topology import reduce_port_impedance
from models.request import AnalysisMode
from parser.netlist_parser import (
    ElementType,
    parse_netlist,
    to_lcapy_netlist,
)
from solver.frequency_check import check_source_frequencies
from tests.conftest import as_complex

GND = "* GND1 — Referans toprak (Node 0)"


# ═══════════════════════════════════════════════════════
#  YARDIMCI FONKSİYONLAR (KCL Residual Check)
# ═══════════════════════════════════════════════════════

def _to_sympy(text: str):
    """'(V_2 - 12)/1000 + V_2/(-j31.83)' -> SymPy expression."""
    text = text.replace(",", ".").replace("−", "-")
    text = re.sub(r"(?<![\w.])j(\d[\d.]*(?:e[+-]?\d+)?)", r"(\1*I)", text)
    return sympy.sympify(text)


def residual(equation: str, node_voltages: dict):
    """Denklemi çözüm gerilimleriyle değerlendir -> (|sol − sağ|, ölçek)."""
    lhs, rhs = equation.split("=")
    expr = sympy.expand(_to_sympy(lhs) - _to_sympy(rhs))
    subs = {
        sympy.Symbol(f"V_{node}"): sympy.sympify(as_complex(nv.value))
        for node, nv in node_voltages.items()
    }
    terms = [complex(t.subs(subs).evalf()) for t in sympy.Add.make_args(expr)]
    return abs(sum(terms)), max(sum(abs(t) for t in terms), 1e-12)


def _kcl_step(steps):
    return next(s for s in steps if s.title.startswith("KCL"))


# ═══════════════════════════════════════════════════════
#  1. NETLIST PARSER
# ═══════════════════════════════════════════════════════

def test_parser_current_sources():
    """DC, AC Phasor ve AC Sine akım kaynaklarının ayrıştırılmasını ve lcapy düğüm takasını doğrular."""
    net = (
        "I1 0 2 DC 2m\n"
        "IAC1 0 1 AC_PHASOR(0.01, 30)\n"
        "IAC2 0 1 SINE(0 0.01 50 0 0 0)\n"
        "V1 0 2 DC 10\n"
        f"{GND}"
    )
    parsed = parse_netlist(net)
    assert not parsed.warnings

    # 1. "I1 0 2 DC 2m" -> CURRENT_DC, value 0.002, nodes ("0", "2")
    i1 = next(e for e in parsed.elements if e.id == "I1")
    assert i1.element_type == ElementType.CURRENT_DC
    assert i1.value == pytest.approx(0.002)
    assert i1.node_positive == "0"
    assert i1.node_negative == "2"

    # 2. "IAC1 0 1 AC_PHASOR(0.01, 30)" -> CURRENT_AC_PHASOR, amplitude 0.01, phase 30
    iac1 = next(e for e in parsed.elements if e.id == "IAC1")
    assert iac1.element_type == ElementType.CURRENT_AC_PHASOR
    assert iac1.params["amplitude"] == pytest.approx(0.01)
    assert iac1.params["phase"] == pytest.approx(30.0)
    assert iac1.node_positive == "0"
    assert iac1.node_negative == "1"

    # 3. "IAC2 0 1 SINE(0 0.01 50 0 0 0)" -> CURRENT_AC_SINE, frequency 50, amplitude 0.01
    iac2 = next(e for e in parsed.elements if e.id == "IAC2")
    assert iac2.element_type == ElementType.CURRENT_AC_SINE
    assert iac2.params["frequency"] == pytest.approx(50.0)
    assert iac2.params["amplitude"] == pytest.approx(0.01)
    assert iac2.node_positive == "0"
    assert iac2.node_negative == "1"

    # 4. to_lcapy_netlist: akım kaynağında uçlar takas edilir, gerilim kaynağı etkilenmez
    lcapy_net = to_lcapy_netlist(parsed)
    assert "I1 2 0 {0.002}" in lcapy_net
    assert "V1 0 2 {10.0}" in lcapy_net


# ═══════════════════════════════════════════════════════
#  2. SOLVER SIGNS (DC)
# ═══════════════════════════════════════════════════════

def test_dc_solver_signs_forward(solve):
    """'I1 0 1 DC 1m' + 'R1 1 0 1k': akım 0'dan 1'e enjekte edilir -> V1 = +1 V."""
    net = f"I1 0 1 DC 1m\nR1 1 0 1k\n{GND}"
    results, steps, errors = solve(net, "DC")
    assert not [e for e in errors if e.startswith("⚠")]

    assert results.node_voltages["1"].value == pytest.approx(1.0)
    assert results.element_currents["I1"].value == pytest.approx(0.001)
    assert results.element_currents["I1"].direction == "0→1"
    assert results.element_currents["R1"].value == pytest.approx(0.001)
    assert results.element_currents["R1"].direction == "1→0"

    pw = results.power
    assert pw.elements["I1"].active_power == pytest.approx(-0.001)
    assert pw.elements["I1"].role == "source"
    assert pw.balance_error == pytest.approx(0.0, abs=1e-12)


def test_dc_solver_signs_reversed(solve):
    """'I1 1 0 DC 1m' + 'R1 1 0 1k': akım 1'den çekilir -> V1 = -1 V."""
    net = f"I1 1 0 DC 1m\nR1 1 0 1k\n{GND}"
    results, steps, errors = solve(net, "DC")
    assert not [e for e in errors if e.startswith("⚠")]

    assert results.node_voltages["1"].value == pytest.approx(-1.0)
    assert results.element_currents["I1"].value == pytest.approx(0.001)
    assert results.element_currents["I1"].direction == "1→0"
    assert results.element_currents["R1"].value == pytest.approx(-0.001)
    assert results.element_currents["R1"].direction == "1→0"


# ═══════════════════════════════════════════════════════
#  3. MIXED CIRCUIT (V1 + R1 + R2 + I1)
# ═══════════════════════════════════════════════════════

MIXED_NET = (
    "V1 1 0 DC 10\n"
    "R1 1 2 1k\n"
    "R2 2 0 1k\n"
    "I1 0 2 DC 2m\n"
    f"{GND}"
)


def test_mixed_circuit_dc(solve):
    """V1=10V, R1=1k, R2=1k, I1=2mA -> V2 = 6 V, I(R1)=4 mA, I(R2)=6 mA, P_sup=52 mW."""
    results, steps, errors = solve(MIXED_NET, "DC")
    assert not [e for e in errors if e.startswith("⚠")]

    assert results.node_voltages["1"].value == pytest.approx(10.0)
    assert results.node_voltages["2"].value == pytest.approx(6.0)

    # I(R1) = (10 - 6)/1k = 4 mA, direction 1->2
    assert results.element_currents["R1"].value == pytest.approx(0.004)
    assert results.element_currents["R1"].direction == "1→2"

    # I(R2) = (6 - 0)/1k = 6 mA, direction 2->0
    assert results.element_currents["R2"].value == pytest.approx(0.006)
    assert results.element_currents["R2"].direction == "2→0"

    # Power: V1 supplies 40 mW (-40 mW PSC), I1 supplies 12 mW (-12 mW PSC)
    pw = results.power
    assert pw.elements["V1"].active_power == pytest.approx(-0.040)
    assert pw.elements["I1"].active_power == pytest.approx(-0.012)
    assert pw.elements["R1"].active_power == pytest.approx(0.016)
    assert pw.elements["R2"].active_power == pytest.approx(0.036)
    assert pw.total_supplied.real == pytest.approx(0.052)
    assert pw.total_absorbed.real == pytest.approx(0.052)
    assert pw.balance_error == pytest.approx(0.0, abs=1e-12)


# ═══════════════════════════════════════════════════════
#  4. TWO CURRENT SOURCES & AC CURRENT SOURCE
# ═══════════════════════════════════════════════════════

TWO_SOURCES_NET = (
    "I1 0 1 DC 4m\n"
    "I2 2 0 DC 1m\n"
    "R1 1 0 1k\n"
    "R2 1 2 2k\n"
    "R3 2 0 1k\n"
    f"{GND}"
)


def test_two_current_sources_resistor_network(solve):
    """İki bağımsız akım kaynağı ve 3 direnç içeren ağın çözümü (numpy ile kıyaslama)."""
    # KCL denklemleri:
    # Düğüm 1: V1/1k + (V1 - V2)/2k = 4 mA
    # Düğüm 2: (V2 - V1)/2k + V2/1k = -1 mA
    G = np.array([
        [1.0 / 1000 + 1.0 / 2000, -1.0 / 2000],
        [-1.0 / 2000, 1.0 / 2000 + 1.0 / 1000],
    ])
    I = np.array([0.004, -0.001])
    expected_v = np.linalg.solve(G, I)  # V1 = 2.75 V, V2 = 0.25 V

    results, steps, errors = solve(TWO_SOURCES_NET, "DC")
    assert not [e for e in errors if e.startswith("⚠")]
    assert results.node_voltages["1"].value == pytest.approx(expected_v[0])
    assert results.node_voltages["2"].value == pytest.approx(expected_v[1])


AC_RC_NET = (
    "IAC1 0 1 AC_PHASOR(0.01, 0)\n"
    "R1 1 0 100\n"
    "C1 1 0 100u\n"
    f"{GND}"
)


def test_ac_current_source_rc(solve):
    """IAC1 = 10 mA∠0°, R1 = 100 Ω, C1 = 100 µF (50 Hz) -> V1 = IAC1 * (R1 || Zc)."""
    f = 50.0
    omega = 2 * math.pi * f
    zc = 1.0 / (1j * omega * 100e-6)
    r = 100.0
    z_par = (r * zc) / (r + zc)
    expected_v1 = 0.01 * z_par

    results, steps, errors = solve(AC_RC_NET, "AC_PHASOR", frequency=f)
    assert not [e for e in errors if e.startswith("⚠")]
    actual_v1 = as_complex(results.node_voltages["1"].value)
    assert abs(actual_v1 - expected_v1) <= 1e-4 * abs(expected_v1)


# ═══════════════════════════════════════════════════════
#  5. KCL STEP GENERATOR & RESIDUAL CHECKS
# ═══════════════════════════════════════════════════════

def test_kcl_step_residual_circuit_3(solve):
    """Devre 3 (mixed) için KCL sayısal denklemlerinin sağlanması ve sembolik satırda I1 kontrolü."""
    results, steps, errors = solve(MIXED_NET, "DC")
    step = _kcl_step(steps)

    # Düğüm 2 için sembolik satırda ASCII metin olarak I1 bulunmalı
    node2_sym = [e for e in step.equations if "Düğüm 2" in e and "(sembolik)" in e]
    assert node2_sym, "Düğüm 2 sembolik denklemi bulunamadı"
    assert "I1" in node2_sym[0]

    # Sayısal denklemlerin çözümü sağlaması (residual check)
    numeric_eqs = [
        entry["numeric"] for entry in step.result_snapshot["kcl_equations"]
    ]
    assert numeric_eqs
    for eq in numeric_eqs:
        err, scale = residual(eq, results.node_voltages)
        assert err <= 2e-3 * scale, f"{eq}: kalan={err:.3g}, ölçek={scale:.3g}"


def test_kcl_step_residual_circuit_4_two_dc_sources(solve):
    """Devre 4 (2 akım kaynağı) için KCL sayısal denklemlerinin residual kontrolü."""
    results, steps, errors = solve(TWO_SOURCES_NET, "DC")
    step = _kcl_step(steps)
    numeric_eqs = [
        entry["numeric"] for entry in step.result_snapshot["kcl_equations"]
    ]
    assert len(numeric_eqs) == 2
    for eq in numeric_eqs:
        err, scale = residual(eq, results.node_voltages)
        assert err <= 2e-3 * scale, f"{eq}: kalan={err:.3g}, ölçek={scale:.3g}"


def test_kcl_step_residual_circuit_4_ac_current_source(solve):
    """Devre 4 (AC akım kaynağı) için KCL sayısal denklemlerinin residual kontrolü."""
    results, steps, errors = solve(AC_RC_NET, "AC_PHASOR", frequency=50.0)
    step = _kcl_step(steps)
    numeric_eqs = [
        entry["numeric"] for entry in step.result_snapshot["kcl_equations"]
    ]
    assert numeric_eqs
    for eq in numeric_eqs:
        err, scale = residual(eq, results.node_voltages)
        assert err <= 2e-3 * scale, f"{eq}: kalan={err:.3g}, ölçek={scale:.3g}"


# ═══════════════════════════════════════════════════════
#  6. NARRATIVE EXPLANATION (CIRCUIT 3)
# ═══════════════════════════════════════════════════════

def test_narrative_explanation_circuit_3(solve):
    """Devre 3 için Türkçe anlatım kalıplarının birebir doğrulanması."""
    results, steps, errors = solve(MIXED_NET, "DC")
    assert results.explanation

    sec_map = {sec.title: [b.text for b in sec.blocks] for sec in results.explanation}

    # 1. KCL bölümü
    kcl_texts = sec_map.get("Düğüm Denklemleri (KCL)", [])
    assert any("Düğüm 2: (V₂ − V₁)/R1 + V₂/R2 − I1 = 0" in t for t in kcl_texts)
    assert any("⇒ (V₂ − 10)/1000 + V₂/1000 − 0,002 = 0" in t for t in kcl_texts)

    # 2. Denklemlerin Çözümü bölümü
    solve_texts = sec_map.get("Denklemlerin Çözümü", [])
    assert any("V₂ · (1/R1 + 1/R2) = V₁/R1 + I1" in t for t in solve_texts)
    assert any("V₂ = 12 mA / 2 mS = 6 V" in t for t in solve_texts)

    # 3. Eleman Akımları bölümü
    current_texts = sec_map.get("Eleman Akımları (Ohm Yasası)", [])
    assert any("I1 akım kaynağı" in t for t in current_texts)

    # 4. Güç Hesabı bölümü
    power_texts = sec_map.get("Güç Hesabı", [])
    assert any("P_I1" in t and "(verilen)" in t for t in power_texts)


# ═══════════════════════════════════════════════════════
#  7. THEVENIN & NORTON EQUIVALENCE
# ═══════════════════════════════════════════════════════

THEVENIN_NET = (
    "I1 0 1 DC 2m\n"
    "R1 1 0 1k\n"
    "R2 1 2 1k\n"
    "R3 2 0 2k\n"
    f"{GND}"
)


def test_thevenin_and_norton_with_current_source(solve):
    """Akım kaynaklı Thevenin ve Norton eşdeğeri, port indirgeme ve anlatım kontrolü."""
    # Thevenin analizi: Port (2, 0)
    results_th, steps_th, errors_th = solve(
        THEVENIN_NET, "DC", analysis_type="THEVENIN", terminals=("2", "0")
    )
    assert not [e for e in errors_th if e.startswith("⚠")]
    assert results_th.thevenin is not None
    assert results_th.thevenin.vth.real == pytest.approx(1.0)
    assert results_th.thevenin.zth.real == pytest.approx(1000.0)

    # Anlatım Rth bölümünde akım kaynağının açık devre yapıldığı belirtilmeli
    rth_sec = next(
        sec for sec in results_th.explanation if "Rth" in sec.title or "Eşdeğer Direnç" in sec.title
    )
    rth_texts = [b.text for b in rth_sec.blocks]
    assert any("akım kaynağı sıfırlanır → açık devre" in t for t in rth_texts)

    # reduce_port_impedance doğrudan çağrısı: Rth = (R1 + R2) || R3 = 2k || 2k = 1 kΩ
    parsed = parse_netlist(THEVENIN_NET)
    red = reduce_port_impedance(parsed, "2", "0", is_dc=True)
    assert red.complete is True
    assert red.impedance is not None
    assert red.impedance.real == pytest.approx(1000.0)

    # Norton analizi: In = Vth / Rth = 1 V / 1 kΩ = 1 mA
    results_no, steps_no, errors_no = solve(
        THEVENIN_NET, "DC", analysis_type="NORTON", terminals=("2", "0")
    )
    assert not [e for e in errors_no if e.startswith("⚠")]
    assert results_no.norton is not None
    assert results_no.norton.i_n.real == pytest.approx(0.001)
    assert results_no.norton.z_n.real == pytest.approx(1000.0)


# ═══════════════════════════════════════════════════════
#  8. FREQUENCY CHECK WARNINGS
# ═══════════════════════════════════════════════════════

def test_frequency_check_ac_with_dc_sources():
    """AC analizde DC kaynak bulunması 'DC bileşenler' ve 'akım kaynağı → açık devre' uyarısı verir."""
    net = (
        "IAC1 0 1 AC_PHASOR(0.01, 0)\n"
        "V1 2 0 DC 5\n"
        "R1 1 2 100\n"
        f"{GND}"
    )
    parsed = parse_netlist(net)
    fc = check_source_frequencies(parsed, AnalysisMode.AC_PHASOR, 50.0)
    assert any(
        "DC bileşenler" in w and "akım kaynağı → açık devre" in w
        for w in fc.warnings
    )


def test_frequency_check_dc_with_ac_sources():
    """DC analizde AC akım kaynağı bulunması AC kaynakların sıfırlandığı uyarısını verir."""
    net = (
        "IAC1 0 1 AC_PHASOR(0.01, 0)\n"
        "R1 1 0 100\n"
        f"{GND}"
    )
    parsed = parse_netlist(net)
    fc = check_source_frequencies(parsed, AnalysisMode.DC, None)
    assert any(
        "AC kaynaklar" in w and "sıfırlandı" in w
        for w in fc.warnings
    )


# ═══════════════════════════════════════════════════════
#  9. API ENDPOINTS VIA CLIENT
# ═══════════════════════════════════════════════════════

def test_api_endpoints_current_source(client):
    """FastAPI istemcisi üzerinden /analyze ve /parse-only uç noktalarını doğrular."""
    # POST /analyze: 200, V2 = 6.0 V, explanation boş değil
    resp_analyze = client.post("/analyze", json={"netlist": MIXED_NET, "mode": "DC"})
    assert resp_analyze.status_code == 200
    data_analyze = resp_analyze.json()
    assert data_analyze["status"] == "success"
    assert data_analyze["results"]["node_voltages"]["2"]["value"] == pytest.approx(6.0)
    assert len(data_analyze["results"]["explanation"]) > 0

    # POST /parse-only: I1 elemanının tipi "I_DC" olarak listelenir
    resp_parse = client.post("/parse-only", json={"netlist": MIXED_NET, "mode": "DC"})
    assert resp_parse.status_code == 200
    data_parse = resp_parse.json()
    assert data_parse["status"] == "parsed"
    i1_elem = next(e for e in data_parse["elements"] if e["id"] == "I1")
    assert i1_elem["type"] == "I_DC"
