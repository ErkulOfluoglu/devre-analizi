"""
Bağımlı (kontrollü) kaynaklar: E (GKGK), G (GKAK), H (AKGK), F (AKAK).

Sözleşme (CircuitAnalyzer.WPF ile ortak):
    E1 n+ n- V(ctrl) k   V(n+) − V(n−) = k · Vctrl
    G1 n+ n- V(ctrl) k   kaynak içinden n+ → n− akım = k · Vctrl   (n− ucundan dışarı çıkar)
    H1 n+ n- I(ctrl) k   V(n+) − V(n−) = k · Ictrl
    F1 n+ n- I(ctrl) k   kaynak içinden n+ → n− akım = k · Ictrl
    Vctrl = V(ctrl.n+) − V(ctrl.n−),  Ictrl = ctrl içinden n+ → n− akım
    V(-R2) / I(-R2): kontrol büyüklüğünün işareti çevrilir.

Her beklenen değer elle hesaplanmıştır (yorumlarda); çözücüden alınan sayı
beklenti olarak KULLANILMAZ.

Ortak temel devre (BASE):
    V1 = 10 V (1–0), R1 = 2 Ω (1–2), R2 = 4 Ω (2–0)
    I = 10 / (2+4) = 5/3 A,  V(2) = 5/3 · 4 = 20/3 = 6.6667 V,  V(R2) = 6.6667 V
    Eleman akımları (n+ → n−):  I_R1 = I_R2 = 1.6667 A,  I_V1 = −1.6667 A (güç verir)
"""

import json

import pytest

from llm.assistant import circuit_text, describe_element
from explainer.topology import reduce_port_impedance, reduce_series_parallel
from models.request import AnalysisMode
from parser.netlist_parser import (
    DEPENDENT_SOURCES, ElementType, parse_netlist, to_lcapy_netlist,
)
from solver.frequency_check import check_source_frequencies
from tests.conftest import as_complex

GND = "\n* GND1 — Referans toprak (Node 0)"
BASE = "V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 4\n"

APPROX = dict(rel=1e-6, abs=1e-9)


def volt(res, node):
    return as_complex(res.node_voltages[node].value)


def cur(res, elem):
    return as_complex(res.element_currents[elem].value)


def solve_ok(solve, netlist, **kw):
    res, steps, errors = solve(netlist, **kw)
    assert not any("⚠" in e for e in errors), errors
    return res, steps, errors


# ═══════════════════════════════════════════════════════
#  DC — dört tür
# ═══════════════════════════════════════════════════════

def test_vcvs_dc(solve):
    """
    E1 3 0 V(R2) 3, R3 = 6 Ω (3–0).
      V(R2) = 20/3 V  →  V(3) = 3 · 20/3 = 20 V
      I_R3 = 20/6 = 3.3333 A (3 → 0);  KCL (3): E1 devreye 3.3333 A verir → I_E1 (n+→n−) = −3.3333 A
    """
    res, _, _ = solve_ok(solve, BASE + "E1 3 0 V(R2) 3\nR3 3 0 6" + GND)
    assert volt(res, "2").real == pytest.approx(20 / 3, **APPROX)
    assert volt(res, "3").real == pytest.approx(20.0, **APPROX)
    assert cur(res, "R3").real == pytest.approx(10 / 3, **APPROX)
    assert cur(res, "E1").real == pytest.approx(-10 / 3, **APPROX)
    assert cur(res, "V1").real == pytest.approx(-5 / 3, **APPROX)


def test_vccs_dc(solve):
    """
    G1 3 0 V(R2) 0.5, R3 = 6 Ω (3–0).
      Kaynak akımı = 0.5 · 20/3 = 10/3 A, kaynak İÇİNDEN n+(3) → n−(0): düğüm 3'ten çeker,
      GND'ye bırakır (SPICE/I-kaynağı kuralı) → V(3) = −(10/3)·6 = −20 V
      I_G1 (n+→n−) = +3.3333 A;  I_R3 (3→0) = −20/6 = −3.3333 A
    """
    res, _, _ = solve_ok(solve, BASE + "G1 3 0 V(R2) 0.5\nR3 3 0 6" + GND)
    assert volt(res, "3").real == pytest.approx(-20.0, **APPROX)
    assert cur(res, "G1").real == pytest.approx(10 / 3, **APPROX)
    assert cur(res, "R3").real == pytest.approx(-10 / 3, **APPROX)


def test_ccvs_dc(solve):
    """
    H1 3 0 I(R2) 3, R3 = 6 Ω.
      I_R2 = 5/3 A (2→0)  →  V(3) = 3 · 5/3 = 5 V
      I_R3 = 5/6 = 0.8333 A (3→0);  I_H1 (n+→n−) = −0.8333 A (devreye verir)
    """
    res, _, _ = solve_ok(solve, BASE + "H1 3 0 I(R2) 3\nR3 3 0 6" + GND)
    assert volt(res, "3").real == pytest.approx(5.0, **APPROX)
    assert cur(res, "R3").real == pytest.approx(5 / 6, **APPROX)
    assert cur(res, "H1").real == pytest.approx(-5 / 6, **APPROX)
    # Kontrol elemanının kendi akımı ölçüm kaynağı yüzünden değişmez
    assert cur(res, "R2").real == pytest.approx(5 / 3, **APPROX)


def test_cccs_dc(solve):
    """
    F1 3 0 I(R2) 2, R3 = 6 Ω.
      Kaynak akımı = 2 · 5/3 = 10/3 A, kaynak içinden 3 → 0 (G ile aynı yön kuralı)
      → V(3) = −(10/3)·6 = −20 V;  I_F1 = +3.3333 A;  I_R3 = −3.3333 A
    """
    res, _, _ = solve_ok(solve, BASE + "F1 3 0 I(R2) 2\nR3 3 0 6" + GND)
    assert volt(res, "3").real == pytest.approx(-20.0, **APPROX)
    assert cur(res, "F1").real == pytest.approx(10 / 3, **APPROX)
    assert cur(res, "R3").real == pytest.approx(-10 / 3, **APPROX)


# ═══════════════════════════════════════════════════════
#  Ters kontrol: V(-R2) / I(-R2)
# ═══════════════════════════════════════════════════════

def test_reversed_voltage_control(solve):
    """
    E1 3 0 V(-R2) 3: Vctrl = −20/3 → V(3) = 3 · (−20/3) = −20 V
      I_R3 (3→0) = −20/6 = −3.3333 A; E1 R3'ten akım çeker → I_E1 (n+→n−) = +3.3333 A
    G1 3 0 V(-R2) 0.5: akım = 0.5 · (−20/3) = −10/3 A (kaynak içinden 3→0)
      → düğüm 3'e +10/3 A basar → V(3) = +20 V
    """
    res, _, _ = solve_ok(solve, BASE + "E1 3 0 V(-R2) 3\nR3 3 0 6" + GND)
    assert volt(res, "3").real == pytest.approx(-20.0, **APPROX)
    assert cur(res, "E1").real == pytest.approx(10 / 3, **APPROX)

    res, _, _ = solve_ok(solve, BASE + "G1 3 0 V(-R2) 0.5\nR3 3 0 6" + GND)
    assert volt(res, "3").real == pytest.approx(20.0, **APPROX)
    assert cur(res, "G1").real == pytest.approx(-10 / 3, **APPROX)


def test_reversed_current_control(solve):
    """
    F1 3 0 I(-R2) 2: Ictrl = −5/3 → akım = −10/3 A (3→0) → V(3) = +20 V, I_F1 = −3.3333 A
    H1 3 0 I(-R2) 3: V(3) = 3 · (−5/3) = −5 V
    """
    res, _, _ = solve_ok(solve, BASE + "F1 3 0 I(-R2) 2\nR3 3 0 6" + GND)
    assert volt(res, "3").real == pytest.approx(20.0, **APPROX)
    assert cur(res, "F1").real == pytest.approx(-10 / 3, **APPROX)

    res, _, _ = solve_ok(solve, BASE + "H1 3 0 I(-R2) 3\nR3 3 0 6" + GND)
    assert volt(res, "3").real == pytest.approx(-5.0, **APPROX)


# ═══════════════════════════════════════════════════════
#  Kontrol elemanı türleri: direnç, gerilim kaynağı, akım kaynağı, bağımlı kaynak
# ═══════════════════════════════════════════════════════

def test_current_control_through_voltage_source(solve):
    """
    Kontrol bağımsız GERİLİM kaynağı: I(V1) = element_currents['V1'] = −5/3 A (güç verir).
      F1 3 0 I(V1) 2: akım = 2 · (−5/3) = −10/3 A (3→0) → V(3) = +20 V, I_F1 = −3.3333 A
      H1 3 0 I(V1) 3: V(3) = 3 · (−5/3) = −5 V,  I_R3 = −5/6 A, I_H1 = +0.8333 A
    """
    res, _, _ = solve_ok(solve, BASE + "F1 3 0 I(V1) 2\nR3 3 0 6" + GND)
    assert cur(res, "V1").real == pytest.approx(-5 / 3, **APPROX)
    assert volt(res, "3").real == pytest.approx(20.0, **APPROX)
    assert cur(res, "F1").real == pytest.approx(-10 / 3, **APPROX)

    res, _, _ = solve_ok(solve, BASE + "H1 3 0 I(V1) 3\nR3 3 0 6" + GND)
    assert volt(res, "3").real == pytest.approx(-5.0, **APPROX)
    assert cur(res, "R3").real == pytest.approx(-5 / 6, **APPROX)
    assert cur(res, "H1").real == pytest.approx(5 / 6, **APPROX)


def test_control_through_current_source(solve):
    """
    I1 0 1 DC 1 (kaynak içinden 0→1: düğüm 1'e 1 A basar), R1 = 5 Ω (1–0) → V(1) = 5 V
      I(I1) = +1 A (n+→n−);  V(I1) = V(0) − V(1) = −5 V
      F1 2 0 I(I1) 3, R2 = 4 Ω: akım 3 A (2→0) → V(2) = −12 V, I_F1 = 3 A
      E1 2 0 V(I1) 2: V(2) = 2 · (−5) = −10 V
    """
    res, _, _ = solve_ok(solve, "I1 0 1 DC 1\nR1 1 0 5\nF1 2 0 I(I1) 3\nR2 2 0 4" + GND)
    assert volt(res, "1").real == pytest.approx(5.0, **APPROX)
    assert cur(res, "I1").real == pytest.approx(1.0, **APPROX)
    assert volt(res, "2").real == pytest.approx(-12.0, **APPROX)
    assert cur(res, "F1").real == pytest.approx(3.0, **APPROX)

    res, _, _ = solve_ok(solve, "I1 0 1 DC 1\nR1 1 0 5\nE1 2 0 V(I1) 2\nR2 2 0 4" + GND)
    assert volt(res, "2").real == pytest.approx(-10.0, **APPROX)


def test_control_by_another_dependent_source(solve):
    """
    E1 3 0 V(R2) 3 (V3 = 20 V, I_E1 = −10/3 A), R3 = 6 Ω.
      E2 4 0 V(E1) 0.5: V(E1) = V3 − V0 = 20 → V4 = 10 V        (R4 = 1 kΩ)
      H2 5 0 I(E1) 2:  I(E1) = −10/3 → V5 = −20/3 = −6.6667 V   (R5 = 1 kΩ)
    """
    net = (BASE + "E1 3 0 V(R2) 3\nR3 3 0 6\n"
           "E2 4 0 V(E1) 0.5\nR4 4 0 1k\nH2 5 0 I(E1) 2\nR5 5 0 1k" + GND)
    res, _, _ = solve_ok(solve, net)
    assert volt(res, "3").real == pytest.approx(20.0, **APPROX)
    assert volt(res, "4").real == pytest.approx(10.0, **APPROX)
    assert volt(res, "5").real == pytest.approx(-20 / 3, **APPROX)


# ═══════════════════════════════════════════════════════
#  AC_PHASOR
# ═══════════════════════════════════════════════════════

def test_ac_phasor_vcvs_and_ccvs(solve):
    """
    VAC1 = 10∠0° V, R1 = 100 Ω (1–2), C1 = 10 µF (2–0), f = 50 Hz
      ω = 2π·50 = 314.159 rad/s,  Z_C = 1/(jωC) = −j318.31 Ω
      V2 = 10 · Z_C/(R1 + Z_C) = 10·(−j318.31)/(100 − j318.31) = 9.1017 − j2.8594 V
      E1 3 0 V(C1) 2, R2 = 50 Ω: V3 = 2·V2 = 18.2034 − j5.7188 V
      I_C1 (2→0) = V2/Z_C = 0.008983 + j0.02859 A
      H1 4 0 I(C1) 2, R3 = 50 Ω: V4 = 2·I_C1 = 0.017966 + j0.05719 V
    """
    import math
    w = 2 * math.pi * 50
    zc = 1 / (1j * w * 10e-6)
    v2 = 10 * zc / (100 + zc)
    ic = v2 / zc

    net = ("VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nC1 2 0 10u\n"
           "E1 3 0 V(C1) 2\nR2 3 0 50\nH1 4 0 I(C1) 2\nR3 4 0 50" + GND)
    res, _, _ = solve_ok(solve, net, mode="AC_PHASOR", frequency=50.0)
    assert volt(res, "2") == pytest.approx(v2, rel=1e-6)
    assert volt(res, "3") == pytest.approx(2 * v2, rel=1e-6)
    assert cur(res, "C1") == pytest.approx(ic, rel=1e-6)
    assert volt(res, "4") == pytest.approx(2 * ic, rel=1e-6)
    # sayısal kontrol (elle): 9.1017 − j2.8594
    assert volt(res, "2").real == pytest.approx(9.1017, abs=1e-3)
    assert volt(res, "2").imag == pytest.approx(-2.8594, abs=1e-3)


def test_ac_phasor_vccs_cccs_reversed(solve):
    """
    Aynı RC devresi. G1 3 0 V(-C1) 0.01, R2 = 50 Ω:
      akım (3→0) = 0.01 · (−V2) → düğüm 3'e +0.01·V2 basılır → V3 = +0.01·V2·50 = 0.5·V2
    F1 4 0 I(-C1) 4, R3 = 50 Ω: akım (4→0) = 4·(−I_C1) → V4 = +4·I_C1·50 = 200·I_C1
    """
    import math
    w = 2 * math.pi * 50
    zc = 1 / (1j * w * 10e-6)
    v2 = 10 * zc / (100 + zc)
    ic = v2 / zc

    net = ("VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nC1 2 0 10u\n"
           "G1 3 0 V(-C1) 0.01\nR2 3 0 50\nF1 4 0 I(-C1) 4\nR3 4 0 50" + GND)
    res, _, _ = solve_ok(solve, net, mode="AC_PHASOR", frequency=50.0)
    assert volt(res, "3") == pytest.approx(0.5 * v2, rel=1e-6)
    assert volt(res, "4") == pytest.approx(200 * ic, rel=1e-6)


# ═══════════════════════════════════════════════════════
#  Thevenin / Norton
# ═══════════════════════════════════════════════════════

THEV = "V1 1 0 DC 10\nR1 1 2 2\nG1 2 0 V(R1) {g}" + GND


def test_thevenin_norton_with_dependent_source(solve):
    """
    V1 = 10 V, R1 = 2 Ω (1–2), G1 2 0 V(R1) g=0.25 S  (düğüm 2'den GND'ye akım çeker). Port: 2–0.
      Açık devre: V(R1) = 10 − V2; KCL: (10−V2)/2 = 0.25·(10−V2) → (10−V2)·0.25 = 0 → V2 = 10  ⇒ Vth = 10 V
      Rth: V1 sıfırlanır (düğüm 1 = GND), uca test kaynağı: akım Is içeri,
           Is = V2/2 − 0.25·V2·(−1)... (V(R1) = 0 − V2 = −V2; G akımı = 0.25·(−V2))
           KCL: Is + (0 − V2)/2 = −0.25·V2 → Is = V2·(0.5 − 0.25) = 0.25·V2 ⇒ Rth = 4 Ω
           (Bağımlı kaynak yok sayılsaydı / seri-paralelle Rth = R1 = 2 Ω çıkardı — yanlış.)
      Norton: kısa devre V2 = 0 → I(R1) = 10/2 = 5 A, G1 = 0.25·10 = 2.5 A → In = 5 − 2.5 = 2.5 A = Vth/Rth ✓
    """
    res, _, _ = solve_ok(solve, THEV.format(g="0.25"), analysis_type="THEVENIN",
                         terminals=("2", "0"))
    assert as_complex(res.thevenin.vth).real == pytest.approx(10.0, **APPROX)
    assert as_complex(res.thevenin.zth).real == pytest.approx(4.0, **APPROX)

    res, _, _ = solve_ok(solve, THEV.format(g="0.25"), analysis_type="NORTON",
                         terminals=("2", "0"))
    assert as_complex(res.norton.i_n).real == pytest.approx(2.5, **APPROX)
    assert as_complex(res.norton.z_n).real == pytest.approx(4.0, **APPROX)


def test_thevenin_negative_resistance(solve):
    """
    Aynı devre, g = 1 S:  Rth: Is = V2·(0.5 − 1) = −0.5·V2 ⇒ Rth = −2 Ω (negatif direnç)
    Açık devre yine V2 = 10 V ⇒ Vth = 10 V.   Norton: In = 5 − 1·10 = −5 A = Vth/Rth ✓
    """
    res, _, _ = solve_ok(solve, THEV.format(g="1"), analysis_type="THEVENIN",
                         terminals=("2", "0"))
    assert as_complex(res.thevenin.vth).real == pytest.approx(10.0, **APPROX)
    assert as_complex(res.thevenin.zth).real == pytest.approx(-2.0, **APPROX)
    # Anlatım negatif dirençten kaçmaz ve seri/paralel iddiası yapmaz
    text = " ".join(b.text for s in res.explanation for b in s.blocks)
    assert "negatif" in text
    assert "seri bağlı" not in text and "paralel:" not in text

    res, _, _ = solve_ok(solve, THEV.format(g="1"), analysis_type="NORTON",
                         terminals=("2", "0"))
    assert as_complex(res.norton.i_n).real == pytest.approx(-5.0, **APPROX)


def test_port_reduction_makes_no_claim_with_dependent_source():
    """Bağımlı kaynak varken Rth seri/paralel indirgemeyle bulunmuş gibi gösterilmez."""
    parsed = parse_netlist(THEV.format(g="0.25"))
    red = reduce_port_impedance(parsed, "2", "0", True, None)
    assert red.complete is False
    assert red.impedance is None
    assert red.steps == []
    assert any("SIFIRLANMAZ" in n for n in red.zeroing_notes)


def test_series_parallel_never_merges_dependent_sources_or_controls():
    """
    BASE'te R1–R2 normalde seridir (düğüm 2 yalnızca iki kol). R2, E1'in kontrol
    elemanı olduğu için birleştirilmez. R3 ∥ R4 (3–0) ise geçerli bir paralel
    indirgemedir ve yapılır; E1 hiçbir indirgemeye girmez.
    """
    parsed = parse_netlist(BASE + "E1 3 0 V(R2) 3\nR3 3 0 6\nR4 3 0 12" + GND)
    reductions, remaining, _, _ = reduce_series_parallel(parsed, True, None)
    assert [(r.kind, set(r.elements)) for r in reductions] == [("parallel", {"R3", "R4"})]
    names = {b.name for b in remaining}
    assert {"R1", "R2"} <= names                       # R1+R2 seri birleştirilmedi
    assert all("E1" not in r.members for r in reductions)


# ═══════════════════════════════════════════════════════
#  Süperpozisyon
# ═══════════════════════════════════════════════════════

def test_superposition_keeps_dependent_source_active(solve):
    """
    V1 = 10 V, I1 (0→1 değil; "I1 0 2 DC 1": düğüm 2'ye 1 A basar), R1 = 2 (1–2), R2 = 4 (2–0),
    E1 3 0 V(R2) 3, R3 = 6.
      Yalnız V1 (I1 açık): V2' = 20/3, V3' = 3·20/3 = 20 V
      Yalnız I1 (V1 kısa → düğüm 1 = GND): R1 ∥ R2 = 8/6 = 4/3 Ω → V2'' = 4/3 V,
           E1 AKTİF KALIR: V3'' = 3·4/3 = 4 V   (E1 sıfırlansaydı 0 olurdu)
      Toplam: V2 = 20/3 + 4/3 = 8 V,  V3 = 24 V   (tam çözüm: KCL (10−V2)/2 + 1 = V2/4 → V2 = 8 ✓)
    """
    net = "V1 1 0 DC 10\nI1 0 2 DC 1\nR1 1 2 2\nR2 2 0 4\nE1 3 0 V(R2) 3\nR3 3 0 6" + GND
    res, _, _ = solve_ok(solve, net, analysis_type="SUPERPOSITION")
    contribs = {c.source_id: c for c in res.superposition}
    assert set(contribs) == {"V1", "I1"}          # yalnız bağımsız kaynaklar tek tek açılır
    assert as_complex(contribs["V1"].node_voltages["3"]).real == pytest.approx(20.0, **APPROX)
    assert as_complex(contribs["I1"].node_voltages["2"]).real == pytest.approx(4 / 3, **APPROX)
    assert as_complex(contribs["I1"].node_voltages["3"]).real == pytest.approx(4.0, **APPROX)
    assert all("E1" not in z for c in res.superposition for z in c.zeroed_sources)
    assert volt(res, "2").real == pytest.approx(8.0, **APPROX)
    assert volt(res, "3").real == pytest.approx(24.0, **APPROX)
    text = " ".join(b.text for s in res.explanation for b in s.blocks)
    assert "SIFIRLANMAZ" in text and "Katkıların toplamı" in text


def test_superposition_without_independent_sources_is_all_zero(solve):
    """
    Bağımsız kaynak yok: R1 = 2 (1–2), R2 = 4 (2–0), E1 1 0 V(R2) 3 (tek başına enerji vermez)
    Çözüm: V2 = 0 → E1 = 0 → tüm gerilim ve akımlar 0; Türkçe açıklama verilir.
    """
    net = "R1 1 2 2\nR2 2 0 4\nE1 1 0 V(R2) 3" + GND
    res, _, errors = solve(net, analysis_type="SUPERPOSITION")
    assert res.superposition == []
    assert all(abs(volt(res, n)) < 1e-12 for n in ("1", "2"))
    assert any("etkin bağımsız kaynak yok" in e for e in errors)
    text = " ".join(b.text for s in res.explanation for b in s.blocks)
    assert "bağımsız kaynak yok" in text and "sıfırdır" in text


# ═══════════════════════════════════════════════════════
#  Güç dengesi
# ═══════════════════════════════════════════════════════

@pytest.mark.parametrize("dep", [
    "E1 3 0 V(R2) 3", "G1 3 0 V(R2) 0.5", "H1 3 0 I(R2) 3", "F1 3 0 I(R2) 2",
    "E1 3 0 V(-R2) 3", "F1 3 0 I(V1) 2",
])
def test_power_balance_sums_to_zero(solve, dep):
    """
    Tellegen: tüm elemanların (bağımlı kaynaklar dahil) emilen gücü toplamı 0.
    Elle (E1 3 0 V(R2) 3): R1 5.556 + R2 11.11 + R3 66.67 = 83.33 W emilir;
    V1 16.67 W + E1 66.67 W verir = 83.33 W.
    """
    res, _, errors = solve_ok(solve, BASE + dep + "\nR3 3 0 6" + GND)
    assert not any("Güç dengesi" in e for e in errors)
    pw = res.power
    assert pw is not None
    assert dep.split()[0] in pw.elements
    total = sum(ep.active_power for ep in pw.elements.values())
    biggest = max(abs(ep.active_power) for ep in pw.elements.values())
    assert abs(total) < 1e-8 * biggest
    assert pw.balance_error < 1e-8 * biggest


def test_power_balance_dependent_example_numbers(solve):
    res, _, _ = solve_ok(solve, BASE + "E1 3 0 V(R2) 3\nR3 3 0 6" + GND)
    pw = res.power.elements
    assert pw["R1"].active_power == pytest.approx(50 / 9, **APPROX)       # (5/3)²·2
    assert pw["R2"].active_power == pytest.approx(100 / 9, **APPROX)      # (5/3)²·4
    assert pw["R3"].active_power == pytest.approx(600 / 9, **APPROX)      # (10/3)²·6
    assert pw["V1"].active_power == pytest.approx(-150 / 9, **APPROX)     # 10·(−5/3)
    assert pw["E1"].active_power == pytest.approx(-600 / 9, **APPROX)     # 20·(−10/3)


def test_power_balance_ac(solve):
    net = ("VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nC1 2 0 10u\n"
           "E1 3 0 V(C1) 2\nR2 3 0 50" + GND)
    res, _, errors = solve_ok(solve, net, mode="AC_PHASOR", frequency=50.0)
    assert not any("Güç dengesi" in e for e in errors)
    total = sum(as_complex(ep.complex_power) for ep in res.power.elements.values())
    assert abs(total) < 1e-8


# ═══════════════════════════════════════════════════════
#  Gizli ölçüm düğümleri/kaynakları hiçbir sonuçta görünmez
# ═══════════════════════════════════════════════════════

HIDDEN_MARKERS = ("_s_", "Vsense", "Vs_")


def _assert_no_hidden(res):
    for table in (res.node_voltages, res.element_currents):
        assert not [k for k in table if any(m in k for m in HIDDEN_MARKERS)], list(table)
    if res.power:
        assert not [k for k in res.power.elements if any(m in k for m in HIDDEN_MARKERS)]
    dump = res.model_dump_json()
    for m in HIDDEN_MARKERS:
        assert m not in dump, f"'{m}' sonuçlara sızdı"


@pytest.mark.parametrize("analysis_type", ["NODAL", "MESH", "THEVENIN", "NORTON", "SUPERPOSITION"])
def test_hidden_sense_elements_absent_from_every_result(solve, analysis_type):
    net = ("V1 1 0 DC 10\nI1 0 2 DC 1\nR1 1 2 2\nR2 2 0 4\n"
           "E1 3 0 V(R2) 3\nR3 3 0 6\n"
           "G1 4 0 V(R2) 0.5\nR4 4 0 6\n"
           "H1 5 0 I(R2) 3\nR5 5 0 6\n"
           "F1 6 0 I(I1) 2\nR6 6 0 6\n"
           "* PROBE VP1 V(5)\n* PROBE IP1 I(G1)" + GND)
    terminals = ("3", "0") if analysis_type in ("THEVENIN", "NORTON") else None
    res, steps, _ = solve(net, analysis_type=analysis_type, terminals=terminals)
    assert res.node_voltages and res.element_currents
    _assert_no_hidden(res)
    assert set(res.element_currents) == {
        "V1", "I1", "R1", "R2", "E1", "R3", "G1", "R4", "H1", "R5", "F1", "R6"}
    assert res.practice == []
    for c in res.superposition:
        assert not [k for k in list(c.node_voltages) + list(c.element_currents)
                    if any(m in k for m in HIDDEN_MARKERS)]
    # Çözüm adımlarında yalnızca "Devre Modeli" adımı iç modeli gösterir ve bunu açıklar
    for st in steps:
        if st.title != "Devre Modeli Oluşturma":
            assert not any(m in st.model_dump_json() for m in HIDDEN_MARKERS), st.title


# ═══════════════════════════════════════════════════════
#  lcapy satır biçimleri (parser → lcapy sözleşmesi)
# ═══════════════════════════════════════════════════════

def test_lcapy_line_forms():
    net = BASE + "E1 3 0 V(R2) 3\nG1 4 0 V(-R2) 0.5\nH1 5 0 I(R2) 3\nF1 6 0 I(V1) 2" + GND
    lines = to_lcapy_netlist(parse_netlist(net)).split("\n")
    assert "E1 3 0 2 0 {3.0}" in lines                        # E: V(n+)-V(n-) = k·(V(c+)-V(c-))
    assert "G1 _s_G1 4 2 0 {-0.5}" in lines                   # G: uçlar ters (akım İLK düğümden çıkar), işaret kazanca
    assert "Vsense_G1 _s_G1 0 {0}" in lines                   # G akımını okumak için gizli ölçüm
    assert "R2 2 _s_R2 4.0" in lines                          # R2'nin n− ucu gizli düğüme
    assert "Vsense_R2 _s_R2 0 {0}" in lines
    assert "H1 5 0 Vsense_R2 {3.0}" in lines                  # H: kontrol = ölçüm kaynağı
    assert "F1 6 _s_F1 V1 {2.0}" in lines                     # F: bağımsız V kaynağı doğrudan kontrol
    assert "Vsense_F1 _s_F1 0 {0}" in lines


def test_sense_names_do_not_collide_with_user_elements():
    net = BASE + "Vsense_G1 7 0 DC 1\nG1 4 0 V(R2) 0.5\nR4 4 0 1" + GND
    text = to_lcapy_netlist(parse_netlist(net))
    sense_lines = [ln for ln in text.split("\n") if ln.startswith("Vsense_G1")]
    assert len(sense_lines) == 2 and sense_lines[1].startswith("Vsense_G1_ ")


# ═══════════════════════════════════════════════════════
#  Ayrıştırıcı
# ═══════════════════════════════════════════════════════

def test_parser_fills_params_and_types():
    p = parse_netlist(BASE + "E1 3 0 V(R2) 3\nG1 3 0 V(-R2) 1m\nH1 4 0 I(R2) 2k\n"
                      "f1 4 0 i(-V1) -0.5" + GND)
    by_id = {e.id: e for e in p.elements}
    assert p.errors == []
    assert by_id["E1"].element_type == ElementType.VCVS
    assert by_id["E1"].params == {"control_id": "R2", "control_kind": "V",
                                  "control_sign": 1, "gain": 3.0}
    assert by_id["E1"].value == 3.0
    assert by_id["G1"].element_type == ElementType.VCCS
    assert by_id["G1"].params["control_sign"] == -1 and by_id["G1"].value == pytest.approx(1e-3)
    assert by_id["H1"].element_type == ElementType.CCVS and by_id["H1"].value == 2000.0
    assert by_id["f1"].element_type == ElementType.CCCS
    assert by_id["f1"].params["control_id"] == "V1"
    assert by_id["f1"].params["control_sign"] == -1 and by_id["f1"].value == -0.5
    assert set(DEPENDENT_SOURCES) == {ElementType.VCVS, ElementType.VCCS,
                                      ElementType.CCVS, ElementType.CCCS}


@pytest.mark.parametrize("line, fragment", [
    ("E1 3 0 V(R9) 3", "R9"),                      # bilinmeyen kontrol elemanı
    ("E1 3 0 V(E1) 3", "kendi kendini"),           # kendi kendini kontrol
    ("F1 3 0 I(F1) 2", "kendi kendini"),
    ("E1 3 0 I(R2) 3", "V(...)"),                  # E için yanlış harf
    ("G1 3 0 I(R2) 3", "V(...)"),
    ("H1 3 0 V(R2) 3", "I(...)"),                  # H için yanlış harf
    ("F1 3 0 V(R2) 3", "I(...)"),
    ("E1 3 0 V(R2)", "anlaşılamadı"),              # kazanç yok
    ("E1 3 0 V(R2) abc", "okunamadı"),             # kazanç sayı değil
])
def test_parser_rejects_invalid_controls_with_turkish_message(line, fragment):
    p = parse_netlist(BASE + line + "\nR3 3 0 6" + GND)
    assert p.errors, "hata beklenirdi"
    assert fragment in " ".join(p.errors)
    assert p.errors == [m for m in p.warnings if m in p.errors]   # uyarılarda da görünür
    assert line.split()[0] not in {e.id for e in p.elements}      # kaynak reddedildi


def test_dependent_may_reference_element_defined_later():
    p = parse_netlist("E1 3 0 V(R2) 3\nR3 3 0 6\nV1 1 0 DC 10\nR1 1 2 2\nR2 2 0 4" + GND)
    assert p.errors == []
    assert len(p.elements) == 5


def test_invalid_control_gives_error_not_wrong_answer(solve):
    res, _, errors = solve(BASE + "E1 3 0 V(R9) 3\nR3 3 0 6" + GND)
    assert any("R9" in e and "bulunamadı" in e and "⚠" in e for e in errors)
    assert res.node_voltages == {}


# ═══════════════════════════════════════════════════════
#  Frekans denetimi
# ═══════════════════════════════════════════════════════

def test_frequency_check_ignores_dependent_sources():
    dc_net = parse_netlist(BASE + "E1 3 0 V(R2) 3\nR3 3 0 6" + GND)
    chk = check_source_frequencies(dc_net, AnalysisMode.DC, None)
    assert chk.warnings == [] and chk.errors == []

    ac_net = parse_netlist("VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 2\nR2 2 0 4\n"
                           "H1 3 0 I(R2) 3\nR3 3 0 6" + GND)
    chk = check_source_frequencies(ac_net, AnalysisMode.AC_PHASOR, None)
    assert chk.errors == []          # reaktif eleman yok → frekans gerekmez
    assert chk.source_frequencies == {}


# ═══════════════════════════════════════════════════════
#  Anlatım, alıştırma, asistan: çökmez, yanlış denklem göstermez
# ═══════════════════════════════════════════════════════

@pytest.mark.parametrize("analysis_type", ["NODAL", "MESH"])
def test_explanation_has_single_note_and_no_equations(solve, analysis_type):
    res, steps, errors = solve(BASE + "E1 3 0 V(R2) 3\nR3 3 0 6" + GND,
                               analysis_type=analysis_type)
    titles = [s.title for s in res.explanation]
    assert "Devreyi Tanıyalım" in titles
    assert "Düğüm Denklemleri (KCL)" not in titles and "Denklemlerin Çözümü" not in titles
    blocks = [b for s in res.explanation for b in s.blocks]
    notes = [b.text for b in blocks if "bağımlı kaynak var" in b.text]
    assert len(notes) == 1 and "bir sonraki sürümde eklenecek" in notes[0]
    assert "Sonuçlar doğrudur" in notes[0]
    text = "\n".join(b.text for b in blocks)
    assert "E1: Gerilim kontrollü gerilim kaynağı, E1 = 3·V_R2" in text
    assert res.practice == []
    assert res.meshes == []
    kcl_steps = [s for s in steps if s.title.startswith("KCL")]
    assert all(s.equations == [] for s in kcl_steps)          # sahte KCL denklemi yok
    if analysis_type == "MESH":
        assert any("çevre akımları" in e for e in errors)


@pytest.mark.parametrize("dep, name", [
    ("E1 3 0 V(R2) 3", "Gerilim kontrollü gerilim kaynağı"),
    ("G1 3 0 V(R2) 0.5", "Gerilim kontrollü akım kaynağı"),
    ("H1 3 0 I(R2) 3", "Akım kontrollü gerilim kaynağı"),
    ("F1 3 0 I(-R2) 2", "Akım kontrollü akım kaynağı"),
])
def test_intro_names_every_dependent_type(solve, dep, name):
    res, _, _ = solve(BASE + dep + "\nR3 3 0 6" + GND)
    text = "\n".join(b.text for s in res.explanation for b in s.blocks)
    assert f"{dep.split()[0]}: {name}" in text


def test_gain_that_cancels_the_loop_resistance_is_reported_once_in_turkish(client):
    """
    Kullanıcının denediği devre: V1 12 V, R1 2 Ω, R2 4 Ω, R3 6 Ω, E1 (+ ucu GND'de) = k·V_R2.
    KVL: 12 + k·4I = (2 + 4 + 6)·I → k = 3'te 12 = 0 (tekil), k = 2'de I = 3 A.
    Tekil durumda her düğüm için ayrı İngilizce lcapy hatası yerine tek Türkçe açıklama (HTTP 422).
    """
    net = "V1 1 0 DC 12\nR1 1 2 2\nR2 2 3 4\nR3 3 4 6\nE1 0 4 V(R2) {k}" + GND

    r = client.post("/analyze", json={"netlist": net.format(k=3), "mode": "DC"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "tek bir çözümü yok" in detail and "Bağımlı kaynağın kazancı" in detail
    assert "invertible" not in detail

    r = client.post("/analyze", json={"netlist": net.format(k=2), "mode": "DC"})
    assert r.status_code == 200
    nv = r.json()["results"]["node_voltages"]
    assert nv["2"]["value"] == pytest.approx(6.0) and nv["4"]["value"] == pytest.approx(-24.0)


def test_reversed_control_is_defined_by_the_drawn_polarity(solve):
    """
    V(-R2): ekranda R2'nin + işareti n− ucunda çizilir. Anlatım eksi yazmaz,
    V_R2'yi ters düğüm sırasıyla tanımlar (R2 2 0 → V_R2 = V₀ − V₂).
    """
    res, _, _ = solve(BASE + "E1 3 0 V(-R2) 3\nR3 3 0 6" + GND)
    text = "\n".join(b.text for s in res.explanation for b in s.blocks)
    assert "E1 = 3·V_R2" in text and "V_R2 = V₀ − V₂" in text
    assert "(−V_R2)" not in text


def test_assistant_describes_dependent_sources():
    p = parse_netlist(BASE + "E1 3 0 V(-R2) 3\nF1 4 0 I(R2) 2\nR3 3 0 6\nR4 4 0 6" + GND)
    by_id = {e.id: e for e in p.elements}
    e1 = describe_element(by_id["E1"])
    assert "gerilim kontrollü gerilim kaynağı" in e1 and "3·V_R2 (ölçüm yönü" in e1
    assert "(−V_R2)" not in e1
    f1 = describe_element(by_id["F1"])
    assert "akım kontrollü akım kaynağı" in f1 and "Düğüm 4 → GND" in f1
    assert "E1" in circuit_text(p, True, None)


# ═══════════════════════════════════════════════════════
#  API (FastAPI TestClient)
# ═══════════════════════════════════════════════════════

def _post(client, netlist, **extra):
    body = {"netlist": netlist, "mode": "DC", "analysis_type": "NODAL", **extra}
    return client.post("/analyze", json=body)


def test_api_contract_example(client):
    """Sözleşmedeki örnek: V(2) = 10·4/6 = 6.667 V, V(3) = 3·6.667 = 20 V."""
    net = ("V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 4\nE1 3 0 V(R2) 3\nR3 3 0 6\n"
           "* GND1 — Referans toprak (Node 0)\n.end")
    r = _post(client, net)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    nv = data["results"]["node_voltages"]
    assert nv["2"]["value"] == pytest.approx(20 / 3, rel=1e-6)
    assert nv["3"]["value"] == pytest.approx(20.0, rel=1e-6)
    assert data["results"]["element_currents"]["E1"]["value"] == pytest.approx(-10 / 3, rel=1e-6)
    assert data["results"]["element_currents"]["E1"]["direction"] == "3→0"
    assert data["results"]["practice"] == []
    assert not any(m in json.dumps(data["results"]) for m in HIDDEN_MARKERS)


@pytest.mark.parametrize("analysis_type", ["MESH", "SUPERPOSITION"])
def test_api_other_methods_do_not_crash(client, analysis_type):
    net = ("V1 1 0 DC 10\nI1 0 2 DC 1\nR1 1 2 2\nR2 2 0 4\nE1 3 0 V(R2) 3\nR3 3 0 6\n"
           "* GND1 — Referans toprak (Node 0)")
    r = _post(client, net, analysis_type=analysis_type)
    assert r.status_code == 200
    res = r.json()["results"]
    assert res["node_voltages"]["3"]["value"] == pytest.approx(24.0, rel=1e-6)
    assert res["explanation"]


def test_api_thevenin_with_dependent_source(client):
    r = _post(client, THEV.format(g="0.25"), analysis_type="THEVENIN",
              thevenin_terminals={"node_positive": "2", "node_negative": "0"})
    assert r.status_code == 200
    th = r.json()["results"]["thevenin"]
    assert th["vth"]["real"] == pytest.approx(10.0, rel=1e-6)
    assert th["zth"]["real"] == pytest.approx(4.0, rel=1e-6)


@pytest.mark.parametrize("line, fragment", [
    ("E1 3 0 V(R9) 3", "R9"),
    ("E1 3 0 V(E1) 3", "kendi kendini"),
    ("H1 3 0 V(R2) 3", "I(...)"),
])
def test_api_invalid_control_is_http_400_in_turkish(client, line, fragment):
    r = _post(client, BASE + line + "\nR3 3 0 6" + GND)
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail.startswith("Netlist hatası:") and fragment in detail


def test_api_parse_only_shows_lcapy_lines(client):
    r = client.post("/parse-only", json={
        "netlist": BASE + "E1 3 0 V(R2) 3\nR3 3 0 6" + GND, "mode": "DC"})
    assert r.status_code == 200
    data = r.json()
    e1 = next(e for e in data["elements"] if e["id"] == "E1")
    assert e1["type"] == "E" and e1["params"]["control_id"] == "R2"
    assert "E1 3 0 2 0 {3.0}" in data["lcapy_netlist"]
    assert data["errors"] == []
