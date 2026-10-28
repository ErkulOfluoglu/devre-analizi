"""
CircuitAnalyzer API — Bağımlı kaynaklı çevre akımları (mesh) yöntemi

Test edilen modüller:
- solver/mesh.py (analyze_meshes, MeshDependent)
- explainer/mesh_narrative.py (build_mesh_sections, verify)

Yönlendirme (narrative / circuit_solver) başka bir işte değiştiği için burada
analyze_meshes + build_mesh_sections doğrudan çağrılır. Sayısal referans
çözücüdür (lcapy); ayrıca her devre için düğüm denklemleriyle EL HESABI
yorumlarda verilmiştir ve çevre sonuçları ona da bağlanır.

Sözleşme: V_X / I_X çizilen yöndedir (V(-R2) → V_R2 = V(R2.n−) − V(R2.n+)),
kazançla çarpımında ayrıca eksi yazılmaz.
"""

import cmath
import math

import pytest

import solver.circuit_solver as circuit_solver
from explainer.formatting import MINUS
from explainer.mesh_narrative import build_mesh_sections, verify
from explainer.narrative import _Ctx
from models.request import AnalysisMode, AnalysisType
from parser.netlist_parser import parse_netlist
from solver.mesh import analyze_meshes
from tests.conftest import as_complex

GND = "\n* GND1 — Referans toprak (Node 0)"

# Çözücüyle karşılaştırmada mutlak tolerans (çözücü 6 ondalığa yuvarlar)
TOL = 2e-6


@pytest.fixture
def mesh_case(solve, monkeypatch):
    """
    netlist → (MeshAnalysis, _Ctx, çözücü sonucu).
    Anlatım için gereken ham düğüm gerilimi / eleman akımı, çözücünün
    build_explanation çağrısından yakalanır (yönlendirme koduna bağımlı olmadan).
    """
    def _run(netlist, mode="DC", frequency=None):
        cap = {}

        def fake(parsed, is_dc, frequency, analysis_type, terminals,
                 raw_nodes, raw_currents, results, *a, **k):
            cap.update(parsed=parsed, is_dc=is_dc, nodes=raw_nodes, cur=raw_currents)
            return []

        monkeypatch.setattr(circuit_solver, "build_explanation", fake)
        res, _, errors = solve(netlist + GND, mode, frequency, "NODAL")
        assert not any("⚠" in e for e in errors), errors
        parsed, is_dc = cap["parsed"], cap["is_dc"]
        omega = None if is_dc or not frequency else 2 * math.pi * frequency
        ctx = _Ctx(
            parsed=parsed, is_dc=is_dc, frequency=frequency, omega=omega,
            analysis_type=AnalysisType.MESH, terminals=None,
            v={str(k): complex(v) for k, v in cap["nodes"].items()},
            i={k: complex(v) for k, v in cap["cur"].items()}, results=res)
        ma = analyze_meshes(parsed, is_dc, frequency)
        return ma, ctx, res
    return _run


def texts_of(sections):
    return [b.text for s in sections for b in s.blocks]


def assert_matches_solver(ma, ctx, res):
    """Her dal akımı lcapy ile aynı; çevre akımlarından yeniden kurulabiliyor; verify() geçer."""
    assert ma.ok, ma.reason
    for eid, ib in ma.branch_currents.items():
        ref = as_complex(res.element_currents[eid].value)
        assert abs(ib - ref) <= TOL, (eid, ib, ref)
    # Her çevredeki her eleman için dal akımı hesaplanmış olmalı
    for m in ma.meshes:
        for e, _ in m.elements:
            assert e.id in ma.branch_currents
    assert verify(ctx, ma)


def hand(ma, **expected):
    """El hesabı dal akımları (n+ → n−), ADIM ADIM çözücüden bağımsız."""
    for eid, val in expected.items():
        assert ma.branch_currents[eid].real == pytest.approx(val, abs=1e-9), eid
        assert abs(ma.branch_currents[eid].imag) < 1e-9


# ═══════════════════════════════════════════════════════
#  1. TEK ÇEVRE (E)
# ═══════════════════════════════════════════════════════

SINGLE = ("V1 1 0 DC 12\nR1 1 2 2\nR2 2 3 4\nR3 3 4 6\n"
          "E1 0 4 V({ctrl}) {k}")


def test_single_loop_vcvs(mesh_case):
    """
    V1 = 12 V (1-0), R1 = 2 (1-2), R2 = 4 (2-3), R3 = 6 (3-4) seri; E1 (n+ = 0, n− = 4) = 2·V_R2.
    Düğümler: V0 = 0, V1 = 12, V2 = 12 − 2I, V3 = 12 − 6I, V4 = 12 − 12I (I: V1'den R1'e akan akım)
      E1: V(0) − V(4) = 2·V_R2  →  −12 + 12I = 2·(4I)  →  4I = 12  →  I = 3 A
      (çevre KVL'si: 12·I = 12 + 2·V_R2 = 12 + 2·4I), V_R2 = 12 V, E1 = 2·12 = 24 V.
    """
    ma, ctx, res = mesh_case(SINGLE.format(ctrl="R2", k=2))
    assert_matches_solver(ma, ctx, res)
    assert len(ma.meshes) == 1
    assert abs(ma.mesh_currents[0]) == pytest.approx(3.0, abs=1e-9)
    hand(ma, R1=3, R2=3, R3=3, V1=-3, E1=-3)

    d = ma.dependents["E1"]
    assert d.gain == 2 and d.control_kind == "V" and d.control_id == "R2"
    assert d.ctrl_z == 4 and d.ctrl_const == 0
    assert d.ctrl_value.real == pytest.approx(12.0)      # V_R2
    assert d.value.real == pytest.approx(24.0)           # E1 = 2·12

    t = texts_of(build_mesh_sections(ctx, ma))
    assert any(x.endswith("= V1 + 2·V_R2") for x in t)                  # (a) KVL, bağımlı terim
    assert any(x == "V_R2 = R2·I₁ = 4·I₁" for x in t)                   # (b) kontrol
    assert any("= 12 + 2·4·I₁" in x for x in t)                         # (c) yerine koyma
    assert any(x == "4·I₁ = 12" for x in t)                             # toplanmış (12 − 8 = 4)
    assert any(x == "I₁ = 12 / 4 = 3 A" for x in t)                     # (d) çözüm
    assert any(x == "Bağımlı kaynağın değeri: E1 = 2·V_R2 = 2 · 12 V = 24 V" for x in t)  # (e)


def test_single_loop_singular_gain():
    """
    k = 3: 12·I = 12 + 3·4I → 0·I = 12 → çözüm yok (kazanç çevreyi tam dengeliyor, 12 − 4k = 0).
    Çevre yöntemi çökmeden ok=False + Türkçe sebep verir.
    """
    parsed = parse_netlist(SINGLE.format(ctrl="R2", k=3) + GND)
    ma = analyze_meshes(parsed, True, None)
    assert ma.ok is False
    assert "tekil" in ma.reason and ma.reason.strip()
    assert ma.mesh_currents == [] and ma.dependents == {}


# ═══════════════════════════════════════════════════════
#  2. İKİ ÇEVRE: E, G, H, F
# ═══════════════════════════════════════════════════════

def test_two_mesh_vcvs(mesh_case):
    """
    V1 = 10 V (1-0), R1 = 2 (1-2), R2 = 4 (2-0), E1 = 3·V_R2 (2→3: n+ = 2, n− = 3), R3 = 6 (3-0).
    Düğüm 2 = V2 = V_R2, V3 = V2 − 3·V2 = −2·V2, KCL(2):
        (10 − V2)/2 = V2/4 + V3/6 = V2/4 − V2/3  →  60 − 6V2 = −V2  →  V2 = 12 V
      I_R1 = −1 A, I_R2 = 3 A, I_R3 (3→0) = −24/6 = −4 A, I_E1 (2→3) = −4 A, I_V1 = +1 A.
    """
    ma, ctx, res = mesh_case(
        "V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 4\nE1 2 3 V(R2) 3\nR3 3 0 6")
    assert_matches_solver(ma, ctx, res)
    assert len(ma.meshes) == 2
    hand(ma, R1=-1, R2=3, R3=-4, E1=-4, V1=1)
    assert ma.dependents["E1"].value.real == pytest.approx(36.0 - 0)   # 3·V_R2 = 3·12
    t = texts_of(build_mesh_sections(ctx, ma))
    assert any("3·V_R2" in x and x.startswith("Çevre") for x in t)
    assert any(x.startswith("V_R2 = R2·") for x in t)
    assert any(x.startswith("İki bilinmeyenli sistemi Cramer") for x in t)
    assert any(x == "Bağımlı kaynağın değeri: E1 = 3·V_R2 = 3 · 12 V = 36 V" for x in t)


def test_two_mesh_vccs_single_mesh_constraint(mesh_case):
    """
    V1 = 10 (1-0), R1 = 2 (1-2), R2 = 4 (2-0), R3 = 6 (2-3), G1 (3→0) = 0.5·V_R2 (A).
    G1 dış kolda: çevre 2 akımı = ±0.5·V_R2 (bilinmeyen içeren kısıt).
    R3 ve G1 seri: i3 = 0.5·V2.  KCL(2): (10 − V2)/2 = V2/4 + 0.5·V2 → V2 = 4 V
      I_R1 = 3, I_R2 = 1, I_R3 = I_G1 = 2 A, V3 = 4 − 12 = −8 V.
    """
    ma, ctx, res = mesh_case(
        "V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 4\nR3 2 3 6\nG1 3 0 V(R2) 0.5")
    assert_matches_solver(ma, ctx, res)
    hand(ma, R1=3, R2=1, R3=2, G1=2, V1=-3)
    assert ma.dependents["G1"].is_current_output
    assert "G1" in ma.cs_voltages and "G1" not in ma.currents_cs
    assert ma.cs_voltages["G1"].real == pytest.approx(-8.0)     # V(3) − V(0)
    t = texts_of(build_mesh_sections(ctx, ma))
    assert any("G1 bağımlı akım kaynağı yalnızca Çevre" in x for x in t)
    assert any(x.endswith("= 0,5·V_R2") for x in t)             # I₂ = 0.5·V_R2 (kısıt)
    assert any(x.startswith("V_R2 = R2·") for x in t)
    assert any(x == "Bağımlı kaynağın değeri: G1 = 0,5·V_R2 = 0,5 · 4 V = 2 A" for x in t)


def test_two_mesh_ccvs(mesh_case):
    """
    V1 = 10 (1-0), R1 = 2 (1-2), R2 = 4 (2-0), R3 = 6 (2-3), H1 (3→0) = 3·I_R2 (V).
    V3 = 3·V2/4;  i3 = (V2 − V3)/6 = V2/24;  KCL(2): (10 − V2)/2 = V2/4 + V2/24
        → 120 − 12·V2 = 7·V2 → V2 = 120/19
      I_R2 = 30/19, I_R3 = I_H1 = 5/19, I_R1 = 70/38 = 35/19.
    """
    ma, ctx, res = mesh_case(
        "V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 4\nR3 2 3 6\nH1 3 0 I(R2) 3")
    assert_matches_solver(ma, ctx, res)
    hand(ma, R1=35 / 19, R2=30 / 19, R3=5 / 19, H1=5 / 19)
    d = ma.dependents["H1"]
    assert d.control_kind == "I" and d.ctrl_z is None
    assert d.ctrl_value.real == pytest.approx(30 / 19)           # I_R2
    assert d.value.real == pytest.approx(90 / 19)                # H1 = 3·I_R2 = V3
    t = texts_of(build_mesh_sections(ctx, ma))
    assert any(x.startswith("Çevre 2:") and x.endswith("= −3·I_R2") for x in t)   # KVL'de bağımlı terim
    assert any(x == "I_R2 = I₁ − I₂" for x in t)                 # kontrol büyüklüğü
    assert any(x == "6·I₁ − 4·I₂ = 10" for x in t)               # toplanmış katsayılar (el: 6I₁ − 4I₂ = 10)
    assert any(x == "−I₁ + 7·I₂ = 0" for x in t)                 # 4(I₂−I₁) + 6I₂ + 3(I₁−I₂) = 0
    assert any(x.startswith("Bağımlı kaynağın değeri: H1 = 3·I_R2 = 3 · ") for x in t)


def test_two_mesh_cccs(mesh_case):
    """
    Aynı devre, F1 (3→0) = 3·I_R2 (A):  i3 = 3·I_R2 = 3·V2/4.
    KCL(2): (10 − V2)/2 = V2/4 + 3·V2/4 = V2 → V2 = 10/3 V
      I_R1 = 10/3, I_R2 = 5/6, I_R3 = I_F1 = 5/2 A,  V3 = 10/3 − 15 = −35/3 V.
    """
    ma, ctx, res = mesh_case(
        "V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 4\nR3 2 3 6\nF1 3 0 I(R2) 3")
    assert_matches_solver(ma, ctx, res)
    hand(ma, R1=10 / 3, R2=5 / 6, R3=5 / 2, F1=5 / 2)
    assert ma.cs_voltages["F1"].real == pytest.approx(-35 / 3)
    t = texts_of(build_mesh_sections(ctx, ma))
    assert any(x == "I₂ = 3·I_R2" for x in t)                      # kısıt: bilinmeyen içerir
    assert any(x == "I_R2 = I₁ − I₂" for x in t)
    assert any(x == "I₂ = 3·(I₁ − I₂)" for x in t)                 # yerine koyma
    assert any(x == "Bağımlı kaynağın değeri: F1 = 3·I_R2 = 3 · 833,3 mA = 2,5 A" for x in t)


def test_dependent_current_source_shared_supermesh(mesh_case):
    """
    G1 iki çevre arasında ortak → süperçevre + bilinmeyen içeren kısıt.
    V1 = 12 (1-0), R1 = 2 (1-2), G1 (2→0) = 1·V_R3, R2 = 4 (2-3), R3 = 2 (3-0).
      i_R2 = i_R3 = V3/2 ve (V2 − V3)/4 = V3/2 → V2 = 3·V3
      KCL(2): (12 − V2)/2 = V3 + V3/2 → 12 − 3V3 = 3V3 → V3 = 2, V2 = 6
      I_R1 = 3, I_G1 = 2, I_R2 = I_R3 = 1 A.
    """
    ma, ctx, res = mesh_case(
        "V1 1 0 DC 12\nR1 1 2 2\nG1 2 0 V(R3) 1\nR2 2 3 4\nR3 3 0 2")
    assert_matches_solver(ma, ctx, res)
    hand(ma, R1=3, G1=2, R2=1, R3=1)
    t = texts_of(build_mesh_sections(ctx, ma))
    assert any("Süperçevre" in x for x in t)
    assert any("G1 bağımlı akım kaynağının akımı" in x for x in t)
    assert any(x.endswith("= V_R3") for x in t)       # kazanç 1 → '1·' yazılmaz
    assert any(x == "Bağımlı kaynağın değeri: G1 = V_R3 = 2 A" for x in t)


# ═══════════════════════════════════════════════════════
#  3. TERS KONTROL, I(V1), AC
# ═══════════════════════════════════════════════════════

def test_reversed_voltage_control(mesh_case):
    """
    E1 (2→3) = 3·V(-R2): çizilen V_R2 = V(0) − V(2) = −V2 (ters).
      V2 − V3 = 3·(−V2) → V3 = 4·V2;  KCL(2): (10 − V2)/2 = V2/4 + 4V2/6
        → 60 − 6V2 = 11V2 → V2 = 60/17
      I_R1 = 55/17, I_R2 = 15/17, I_R3 = V3/6 = 40/17, I_E1 = 40/17.
    Anlatımda kazanç·kontrol çarpımında eksi YOK; V_R2 = V₀ − V₂ olarak tanımlanır.
    """
    ma, ctx, res = mesh_case(
        "V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 4\nE1 2 3 V(-R2) 3\nR3 3 0 6")
    assert_matches_solver(ma, ctx, res)
    hand(ma, R1=55 / 17, R2=15 / 17, R3=40 / 17, E1=40 / 17)
    d = ma.dependents["E1"]
    assert d.control_sign == -1
    assert d.ctrl_value.real == pytest.approx(-60 / 17)          # V_R2 (çizilen) = −V2
    assert d.value.real == pytest.approx(-180 / 17)              # 3·(−60/17)
    t = texts_of(build_mesh_sections(ctx, ma))
    assert any("V_R2 = V₀ − V₂" in x for x in t)
    assert any(x.startswith("Bağımlı kaynağın değeri: E1 = 3·V_R2 = 3 · (") for x in t)
    assert not any(f"{MINUS}V_R2" in x and "E1" in x for x in t)   # E1 = −V_R2 gibi bir gösterim yok


def test_reversed_current_control(mesh_case):
    """
    F1 (3→0) = 2·I(-R2): çizilen I_R2 (0 → 2 yönü) = −V2/4.
      i_F = 2·(−V2/4) = −V2/2 = i3;  KCL(2): (10 − V2)/2 = V2/4 − V2/2 → 60 − 6V2 = −3V2 → V2 = 20
      I_R1 = −5, I_R2 = 5, I_R3 = I_F1 = −10 A.
    """
    ma, ctx, res = mesh_case(
        "V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 4\nR3 2 3 6\nF1 3 0 I(-R2) 2")
    assert_matches_solver(ma, ctx, res)
    hand(ma, R1=-5, R2=5, R3=-10, F1=-10)
    d = ma.dependents["F1"]
    assert d.ctrl_value.real == pytest.approx(-5.0)               # çizilen yönde I_R2
    t = texts_of(build_mesh_sections(ctx, ma))
    assert any("I_R2: R2 elemanından Düğüm 0 → Düğüm 2 yönünde geçen akım" in x for x in t)


def test_control_is_independent_voltage_source_current(mesh_case):
    """
    H1 (3→0) = 3·I(V1);  V1 = 10 (1-0), R1 = 2 (1-2), R2 = 4 (2-0), R3 = 6 (2-3).
    I_V1 (n+ → n−) = −i1  (i1: R1 akımı).  V3 = 3·I_V1 = −3·i1
      KCL(2): i1 = V2/4 + (V2 − V3)/6 ile V2 = 10 − 2·i1
        12·i1 = 30 − 6·i1 + 20 + 2·i1 → 16·i1 = 50 → i1 = 25/8 = 3.125
      V2 = 3.75, I_R2 = 0.9375, I_R3 = I_H1 = (3.75 + 9.375)/6 = 2.1875, I_V1 = −3.125 A.
    """
    ma, ctx, res = mesh_case(
        "V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 4\nR3 2 3 6\nH1 3 0 I(V1) 3")
    assert_matches_solver(ma, ctx, res)
    hand(ma, R1=3.125, R2=0.9375, R3=2.1875, H1=2.1875, V1=-3.125)
    d = ma.dependents["H1"]
    assert d.ctrl_value.real == pytest.approx(-3.125)             # I_V1
    assert d.value.real == pytest.approx(-9.375)                  # H1 = V3
    t = texts_of(build_mesh_sections(ctx, ma))
    assert any(x.startswith("I_V1 = ") for x in t)
    assert any(x.startswith("Bağımlı kaynağın değeri: H1 = 3·I_V1 = 3 · (") for x in t)


def test_control_is_independent_voltage_source_voltage(mesh_case):
    """
    E1 (3→0) = 0.5·V(V1): V(V1) = 10 V bilinen sabit → E1 = 5 V (kontrol sabiti sağ tarafa gider).
    V1 = 10 (1-0), R1 = 2 (1-2), R2 = 4 (2-0), R3 = 6 (2-3), E1 3 0.
      V3 = 5;  KCL(2): (10 − V2)/2 = V2/4 + (V2 − 5)/6 → 60 − 6V2 = 3V2 + 2V2 − 10 → V2 = 70/11
      I_R2 = V2/4 = 35/22, I_R1 = (10 − 70/11)/2 = 20/11,
      I_R3 = I_E1 = (V2 − V3)/6 = (70/11 − 55/11)/6 = 5/22   (35/22 + 5/22 = 20/11 ✓)
    """
    ma, ctx, res = mesh_case(
        "V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 4\nR3 2 3 6\nE1 3 0 V(V1) 0.5")
    assert_matches_solver(ma, ctx, res)
    hand(ma, R1=20 / 11, R2=35 / 22, R3=5 / 22, E1=5 / 22)
    d = ma.dependents["E1"]
    assert d.ctrl_const == 10 and d.ctrl_signs == {} and d.ctrl_z is None
    assert d.value.real == pytest.approx(5.0)
    t = texts_of(build_mesh_sections(ctx, ma))
    assert any(x == "V_V1 = V1 = 10 V" for x in t)
    assert any(x == "Bağımlı kaynağın değeri: E1 = 0,5·V_V1 = 0,5 · 10 V = 5 V" for x in t)


def test_ac_phasor_dependent(mesh_case):
    """
    AC_PHASOR, ω = 1000 rad/s:  V1 = 10∠0° (1-0), R1 = 2 (1-2), L1 = 4 mH → Z = j4 (2-0),
    R2 = 3 (2-3), E1 (3→0) = 2·V_L1.
      V3 = 2·V2;  i3 = (V2 − 2V2)/3 = −V2/3
      KCL(2): (10 − V2)/2 = V2/(j4) − V2/3 → V2·(1/2 + 1/(j4) − 1/3) = 5
        V2 = 5 / (1/6 − j/4)   (V_L1 = V2),  I_L1 = V2/(j4),  I_R2 = I_E1 = −V2/3
    """
    f = 1000 / (2 * math.pi)
    ma, ctx, res = mesh_case(
        "VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 2\nL1 2 0 4m\nR2 2 3 3\nE1 3 0 V(L1) 2",
        "AC_PHASOR", f)
    assert_matches_solver(ma, ctx, res)
    v2 = 5 / (1 / 6 - 0.25j)
    assert ma.branch_currents["L1"] == pytest.approx(v2 / 4j, abs=1e-9)
    assert ma.branch_currents["R2"] == pytest.approx(-v2 / 3, abs=1e-9)
    assert ma.branch_currents["E1"] == pytest.approx(-v2 / 3, abs=1e-9)
    assert ma.branch_currents["R1"] == pytest.approx((10 - v2) / 2, abs=1e-9)
    d = ma.dependents["E1"]
    assert d.ctrl_value == pytest.approx(v2, abs=1e-9)            # V_L1
    assert d.value == pytest.approx(2 * v2, abs=1e-9)
    t = texts_of(build_mesh_sections(ctx, ma))
    assert any(x.startswith("V_L1 = Z_L1·") for x in t)           # V = Z·I (empedanslı)
    assert any(x.startswith("Bağımlı kaynağın değeri: E1 = 2·V_L1 = 2 · ") and "∠" in x for x in t)


def test_ac_time_dependent(mesh_case):
    """
    AC_TIME (fazör çözümü): VAC1 = 10∠30° (50 Hz), R1 = 2, C1 = 1 mF (Z = −j3.183), R2 = 3,
    H1 (3→0) = 2·I_C1.  Referans: çözücü; denklem sistemi (I₁, I₂) ile aynı sonucu vermeli.
      R1·I₁ + Z_C(I₁ − I₂) = V ;  Z_C(I₂ − I₁) + R2·I₂ = −2·(I₁ − I₂)
    """
    ma, ctx, res = mesh_case(
        "VAC1 1 0 SINE(0 10 50 0 0 30)\nR1 1 2 2\nC1 2 0 1m\nR2 2 3 3\nH1 3 0 I(C1) 2",
        "AC_TIME", 50.0)
    assert_matches_solver(ma, ctx, res)
    zc = 1 / (2j * math.pi * 50 * 1e-3)
    v = cmath.rect(10, math.radians(30))
    # Çevre 1: (R1 + Zc)·I1 − Zc·I2 = V
    # Çevre 2: Zc(I2 − I1) + R2·I2 + 2·(I1 − I2) = 0  →  (2 − Zc)·I1 + (Zc + 1)·I2 = 0
    a = [[2 + zc, -zc], [2 - zc, zc + 1]]
    det = a[0][0] * a[1][1] - a[0][1] * a[1][0]
    i1 = v * a[1][1] / det
    i2 = -v * a[1][0] / det
    assert ma.branch_currents["R1"] == pytest.approx(i1, abs=1e-9)
    assert ma.branch_currents["C1"] == pytest.approx(i1 - i2, abs=1e-9)
    assert ma.branch_currents["R2"] == pytest.approx(i2, abs=1e-9)


def test_dc_inductor_current_control(mesh_case):
    """
    DC'de bobin kısa devre: F1 (3→0) = 2·I_L1.  V1 = 10, R1 = 2 (1-2), L1 (2-0) = kısa, R2 = 3 (2-3).
      V2 = 0 → I_R1 = 5 A;  R2 ve F1 seri, V2 = 0: I_R2 = I_F1 = 2·I_L1 ve I_L1 = I_R1 − I_R2
      I_F1 = 2·(5 − I_F1) → 3·I_F1 = 10 → I_F1 = I_R2 = 10/3,  I_L1 = 5/3 A.
    """
    ma, ctx, res = mesh_case(
        "V1 1 0 DC 10\nR1 1 2 2\nL1 2 0 1m\nR2 2 3 3\nF1 3 0 I(L1) 2")
    assert_matches_solver(ma, ctx, res)
    hand(ma, R1=5, L1=5 / 3, R2=10 / 3, F1=10 / 3)


# ═══════════════════════════════════════════════════════
#  4. ÜÇ ÇEVRE (Sarrus) ve KISITLAR
# ═══════════════════════════════════════════════════════

THREE = ("V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 4\nR3 2 3 6\nR4 3 0 3\n"
         "E1 3 4 V(R2) 3\nR5 4 0 5")


def test_three_mesh_sarrus(mesh_case):
    """
    V1 = 10 (1-0), R1 = 2 (1-2), R2 = 4 (2-0), R3 = 6 (2-3), R4 = 3 (3-0),
    E1 (3→4) = 3·V_R2, R5 = 5 (4-0).   3 çevre → 3×3 Cramer (Sarrus).
    Düğüm denklemleriyle:  V4 = V3 − 3·V2
      KCL(3): (V2 − V3)/6 = V3/3 + V4/5   →  23·V2 = 21·V3
      KCL(2): (10 − V2)/2 = V2/4 + (V2 − V3)/6  →  185·V2/21 = 60  →  V2 = 252/37
      V3 = 276/37, V4 = −480/37
      I_R1 = (10 − 252/37)/2 = 59/37, I_R2 = 63/37, I_R3 = (252 − 276)/(37·6) = −4/37,
      I_R4 = 92/37, I_R5 = V4/5 = −96/37 = I_E1.
    """
    ma, ctx, res = mesh_case(THREE)
    assert_matches_solver(ma, ctx, res)
    assert len(ma.meshes) == 3
    hand(ma, R1=59 / 37, R2=63 / 37, R3=-4 / 37, R4=92 / 37, R5=-96 / 37, E1=-96 / 37)
    assert ma.dependents["E1"].ctrl_value.real == pytest.approx(252 / 37)         # V_R2 = 4·63/37
    assert ma.dependents["E1"].value.real == pytest.approx(3 * 252 / 37)          # E1 = V3 − V4

    sections = build_mesh_sections(ctx, ma)
    t = texts_of(sections)
    assert any(x.startswith("Üç bilinmeyenli sistemi Cramer") for x in t)
    assert any("Δ₃ = |" in x for x in t)                             # Sarrus çizelgesi
    assert any(x.startswith("Çevre") and x.endswith("3·V_R2") for x in t)        # (a) KVL
    # Sol tarafa taşınmış katsayılar: üç satırlık denklem sistemi
    solve_sec = [s for s in sections if s.title == "Denklemlerin Çözümü"][0]
    rows = [b.text for b in solve_sec.blocks if b.kind == "math" and " = " in b.text
            and "I₁" in b.text and "Δ" not in b.text and "|" not in b.text]
    assert len(rows) >= 3


def test_three_mesh_four_meshes_use_gauss(mesh_case):
    """
    Aynı devreye R6 (1-4) ve R7 (4-3) eklenince 9 eleman − 5 düğüm + 1 = 5 çevre:
    Gauss yolu; sonuçlar çözücüyle (referans) aynı olmalı.
    """
    net = ("V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 4\nR3 2 3 6\nR4 3 0 3\n"
           "E1 3 4 V(R2) 3\nR5 4 0 5\nR6 1 4 7\nR7 4 3 9")
    ma, ctx, res = mesh_case(net)
    assert_matches_solver(ma, ctx, res)
    assert len(ma.meshes) == 5
    t = texts_of(build_mesh_sections(ctx, ma))
    assert any("Gauss eliminasyonu" in x for x in t)


def test_independent_current_source_with_dependent(mesh_case):
    """
    Bağımsız akım kaynağı (sabit kısıt satırı) ile bağımlı gerilim kaynağı birlikte.
    V1 = 10 (1-0), R1 = 2 (1-2), I1 = 2 A (2→0), R2 = 4 (2-3), R3 = 3 (3-0),
    E1 (3→4) = 2·V_R2, R4 = 5 (4-0).
      V2 = 10 − 2·i_R1, i_R1 = 2 + i_R2;  V4 = V3 − 2·4·i_R2, i_E = V4/5
      KCL(3): i_R2 = V3/3 + V4/5 → 39·i_R2 = 8·V3;  V2 − V3 = 4·i_R2 → V2 = 71·i_R2/8
      → 87·i_R2 = 48 → i_R2 = 16/29;  V3 = 78/29, V4 = −50/29
      I_R1 = 74/29, I_R2 = 16/29, I_R3 = 26/29, I_R4 = −10/29 = I_E1, I_I1 = 2.
    """
    net = ("V1 1 0 DC 10\nR1 1 2 2\nI1 2 0 DC 2\nR2 2 3 4\nR3 3 0 3\n"
           "E1 3 4 V(R2) 2\nR4 4 0 5")
    ma, ctx, res = mesh_case(net)
    assert_matches_solver(ma, ctx, res)
    hand(ma, R1=74 / 29, R2=16 / 29, R3=26 / 29, R4=-10 / 29, E1=-10 / 29, I1=2, V1=-74 / 29)
    t = texts_of(build_mesh_sections(ctx, ma))
    assert any(x == "I₁ = 2 A" for x in t)                          # bilinen çevre akımı
    assert any("Bağımlı kaynağın değeri: E1 = 2·V_R2 = 2 · " in x for x in t)


# ═══════════════════════════════════════════════════════
#  5. DESTEKLENMEYEN DURUMLAR (ok=False + Türkçe sebep)
# ═══════════════════════════════════════════════════════

@pytest.mark.parametrize("net, mode, expect", [
    # Akım kaynağının gerilimi kontrol büyüklüğü
    ("V1 1 0 DC 10\nR1 1 2 2\nI1 2 0 DC 1\nR2 2 3 4\nE1 3 0 V(I1) 2", True,
     "akım kaynağının gerilimi"),
    ("V1 1 0 DC 10\nR1 1 2 2\nG1 2 0 V(R1) 1\nR2 2 3 4\nE1 3 0 V(G1) 2", True,
     "akım kaynağının gerilimi"),
    # Bağımlı gerilim kaynağının gerilimi
    ("V1 1 0 DC 10\nR1 1 2 2\nE1 2 3 V(R1) 2\nR2 3 0 4\nE2 2 0 V(E1) 1", True,
     "bağımlı gerilim kaynağının gerilimi"),
    # DC'de kondansatör gerilimi / bobin gerilimi
    ("V1 1 0 DC 10\nR1 1 2 2\nC1 2 0 1u\nR2 2 3 4\nE1 3 0 V(C1) 2", True, "DC analizde"),
    ("V1 1 0 DC 10\nR1 1 2 2\nL1 2 3 1m\nR2 3 0 4\nE1 2 0 V(L1) 2", True, "DC analizde"),
])
def test_unsupported_controls(net, mode, expect):
    parsed = parse_netlist(net + GND)
    ma = analyze_meshes(parsed, mode, None)
    assert ma.ok is False
    assert expect in ma.reason, ma.reason
    assert ma.mesh_currents == [] and ma.dependents == {}


def test_no_dependents_unchanged_fields():
    """Bağımlı kaynaksız devrede yeni alan boş; mevcut alanlar aynı."""
    ma = analyze_meshes(parse_netlist("V1 1 0 DC 10\nR1 1 2 1k\nR2 2 0 1k" + GND), True, None)
    assert ma.ok and ma.dependents == {}
    assert ma.mesh_currents[0].real == pytest.approx(0.005)


def test_dangling_dependent_current_source_reason():
    """Bir ucu boşta kalan bağımlı akım kaynağı akıtacak yol bulamaz → sebep verilir."""
    parsed = parse_netlist(
        "V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 4\nG1 2 5 V(R2) 1" + GND)
    ma = analyze_meshes(parsed, True, None)
    assert ma.ok is False
    assert "G1" in ma.reason and "boşta" in ma.reason
