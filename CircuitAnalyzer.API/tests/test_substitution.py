"""
Süperdüğüm / süperçevre çözümünün adım adım gösterilmesi (yerine koyma).

Önceden bu devrelerde denklemler kurulup "birlikte çözülünce" denip sonuca
geçiliyordu. Artık kısıt denkleminden bir bilinmeyen diğeri cinsinden yazılır,
KCL/KVL'de yerine konur, kalan sistem çözülür ve geri yerine konur.
Sayılar elle hesaplanmıştır (yorum satırlarında).
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from explainer.elimination import plan_substitution
from main import app

GND = "* GND1 — Referans toprak (Node 0)"
client = TestClient(app)


def _texts(netlist: str, method: str = "NODAL", mode: str = "DC", freq=None):
    r = client.post("/analyze", json={"netlist": f"{netlist}\n{GND}", "mode": mode,
                                      "analysis_type": method, "frequency": freq})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "success", d["errors"]
    return [b["text"] for s in d["results"]["explanation"] for b in s["blocks"]]


def _has(texts, part):
    return any(part in t for t in texts)


def test_chain_supernode_is_solved_by_substitution():
    # I1 = 6 mA Düğüm 1'e girer; R1 = 1k, R2 = 2k, R3 = 4k toprağa; V1: V₁ − V₂ = 4, V2: V₂ − V₃ = 2
    # V₁ = V₃ + 6, V₂ = V₃ + 2 → (V₃ + 6) + 0,5·(V₃ + 2) + 0,25·V₃ = 6 (mS, mA)
    # → 1,75·V₃ = −1 → V₃ = −0,5714 V, V₁ = 5,429 V, V₂ = 1,429 V
    t = _texts("I1 0 1 DC 0.006\nR1 1 0 1000\nV1 1 2 DC 4\nR2 2 0 2000\nV2 2 3 DC 2\nR3 3 0 4000")
    assert not _has(t, "birlikte çözülünce")
    assert _has(t, "Düğüm 1, 2 ve 3 arasında gerilim kaynakları var (V1, V2)")
    assert _has(t, "Kısıt (V1)  ⇒  V₁ = V₂ + 4 = V₃ + 6")
    assert _has(t, "Kısıt (V2)  ⇒  V₂ = V₃ + 2")
    assert _has(t, "(V₃ + 6) + 0,5·(V₃ + 2) + 0,25·V₃ = 6")
    assert _has(t, "1,75·V₃ = −1")
    assert _has(t, "V₃ = −1 / 1,75 = −571,4 mV")
    assert _has(t, "V₁ = V₃ + 6 = (−0,5714) + 6 = 5,429 V")
    assert _has(t, "V₂ = V₃ + 2 = (−0,5714) + 2 = 1,429 V")


def test_dc_inductor_supernode_says_short_circuit():
    # L1 DC'de kısa devre: V₂ = V₃; (V₂ − 10)/1k + V₂/2k + V₃/2k = 0 → 2·V₃ = 10 → 5 V
    t = _texts("V1 1 0 DC 10\nR1 1 2 1000\nL1 2 3 0.01\nR2 2 0 2000\nR3 3 0 2000")
    assert _has(t, "L1 DC'de kısa devredir. Bu yüzden Düğüm 2 ve 3 aynı gerilimdedir")
    assert _has(t, "Kısıt (L1)  ⇒  V₂ = V₃")
    assert _has(t, "V₃ = 10 / 2 = 5 V")
    assert _has(t, "V₂ = V₃ = 5 V")


def test_superposition_zeroed_source_is_called_a_short():
    t = _texts("V1 1 0 DC 12\nR1 1 2 1000\nV2 2 3 DC 5\nR2 3 0 2000\nR3 2 0 3000",
               "SUPERPOSITION")
    assert _has(t, "V2 bu adımda sıfırlandı (kısa devre). Bu yüzden Düğüm 2 ve 3 aynı gerilimdedir")
    assert not _has(t, "birlikte çözülünce")


def test_ac_supernode_substitution_uses_phasor_constant():
    t = _texts("VAC1 1 0 SINE(0 10 50 0 0 0)\nR1 1 2 100\nVAC2 2 3 SINE(0 5 50 0 0 30)\n"
               "C1 2 0 0.0001\nR2 3 0 50", "NODAL", "AC_TIME", 50)
    assert _has(t, "V₂ = V₃ + (4,33 + j2,5)")
    assert _has(t, "V₃ = (135,2 − j161) / (30 + j31,42) = 4,841∠−96,3° V")
    assert _has(t, "V₂ = V₃ + (4,33 + j2,5) = 4,447∠−31,32° V")


def test_two_current_sources_supermesh_and_direct_division():
    # I2 yalnız Çevre 4'te (I₄ = 1 mA); I1 Çevre 1 ile 3 arasında (I₁ = I₃ + 2 mA).
    # Yerine koyunca denklemler ayrışır: 5·I₃ = −2, 3·I₂ = 12 → Cramer gerekmez.
    t = _texts("V1 1 0 DC 10\nR1 1 2 1000\nI1 2 3 DC 0.001\nR2 2 0 2000\nR3 3 0 1000\n"
               "R4 3 4 1000\nI2 4 0 DC 0.002\nR5 4 0 3000", "MESH")
    assert not _has(t, "birlikte çözülünce")
    assert _has(t, "I₁ = I₃ + 2")
    assert _has(t, "doğrudan bölerek")
    assert _has(t, "I₃ = −2 / 5 = −0,4 mA = −400 µA")
    assert _has(t, "I₂ = 12 / 3 = 4 mA")
    assert _has(t, "I₁ = I₃ + 2 = (−0,4) + 2 = 1,6 mA")
    assert not _has(t, "Δ = 0·0")


def test_decoupled_nodal_system_skips_cramer():
    # DC'de C1 açık devre: Düğüm 2 ve 3 birbirinden ayrılır → her denklemde tek bilinmeyen
    t = _texts("V1 1 0 DC 12\nR1 1 2 1000\nC1 2 3 0.0001\nR2 2 0 2000\nR3 3 0 1000")
    assert _has(t, "doğrudan bölerek")
    assert _has(t, "V₂ = 24 / 3 = 8 V")
    assert not _has(t, "Cramer kuralıyla çözelim")


def test_plan_refuses_when_it_does_not_reproduce_the_solution():
    A = np.array([[1e-3, 1 / 2000 + 1 / 3000], [1, -1]])
    b = np.array([0.01, 6])
    x = np.linalg.solve(A, b)
    plan = plan_substitution(A, b, x, [False, True])
    assert plan is not None and plan.keep == [1]
    assert plan.x[0] == pytest.approx(x[1])
    assert plan_substitution(A, b, x * 1.01, [False, True]) is None


def test_plan_leaves_non_difference_constraints_in_the_system():
    # 4·V₃ − 3·V₂ = 0 (bağımlı kaynak kısıtı gibi) yerine koyma için uygun değil
    A = np.array([[2.0, 1.0], [-3.0, 4.0]])
    b = np.array([5.0, 0.0])
    x = np.linalg.solve(A, b)
    assert plan_substitution(A, b, x, [False, True]) is None
