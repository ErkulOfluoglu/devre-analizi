"""
Kesirlerden kurtulma: çözümden önce kesirli denklemlerin tam sayıya çarpılması.

explainer/cramer.py: integer_rows(A, b) -> (A2, b2, çarpanlar)
Anlatım: nodal (narrative.py), bağımlı nodal (dependent_nodal.py), mesh (mesh_narrative.py).

Kural: satır başına (katsayılar + sağ taraf), yalnız DC/gerçek; her sayı
Fraction(x).limit_denominator(1000) ile ≤1e-9 hatayla kesir olmalı; çarpan = paydaların EKOK'u,
1 < m ≤ 1000 ve çarpılmış tam sayılar |n| ≤ 100000. Aksi hâlde satır olduğu gibi kalır.
"""

import numpy as np
import pytest

from explainer.cramer import exact_fmt, integer_rows
from explainer.formatting import MINUS
from tests.conftest import as_complex

GND = "\n* GND1 — Referans toprak (Node 0)"
STEP_TITLE = "Kesirlerden Kurtulalım"


# ═══════════════════════════════════════════════════════
#  integer_rows birim testleri
# ═══════════════════════════════════════════════════════

def test_five_twelfths_row_is_multiplied_by_12():
    """Düğüm 3 satırı: (1/4 + 1/6) V₃ − 1/4 V₂ − 1/6 V₄ = 0  →  ×12  →  −3, 5, −2."""
    A = np.array([[1.0, 0.0, 0.0],
                  [-1 / 4, 1 / 4 + 1 / 6, -1 / 6],
                  [0.0, 0.0, 1.0]])
    b = np.array([2.0, 0.0, 3.0])
    A2, b2, mult = integer_rows(A, b)
    assert mult == [1, 12, 1]
    assert A2[1].tolist() == [-3, 5, -2] and b2[1] == 0
    # Diğer satırlar aynen
    assert A2[0].tolist() == A[0].tolist() and A2[2].tolist() == A[2].tolist()
    assert b2[0] == 2 and b2[2] == 3
    # Girdi değişmedi
    assert A[1, 1] == pytest.approx(5 / 12)


def test_right_hand_side_takes_part_in_the_multiplier():
    """0.5·x + y = 1/3 → paydalar 2 ve 3 → ×6 → 3x + 6y = 2."""
    A2, b2, mult = integer_rows([[0.5, 1.0]], [1 / 3])
    assert mult == [6]
    assert A2[0].tolist() == [3, 6] and b2[0] == 2


def test_scaled_rows_hold_exact_integers():
    A2, b2, _ = integer_rows([[0.75, -0.25]], [5.0])
    assert [float(v) for v in A2[0]] == [3.0, -1.0] and float(b2[0]) == 20.0


def test_already_integer_rows_untouched():
    A = np.array([[3.0, -1.0], [-1.0, 2.0]])
    b = np.array([12.0, 0.0])
    A2, b2, mult = integer_rows(A, b)
    assert mult == [1, 1]
    assert A2.tolist() == A.tolist() and b2.tolist() == b.tolist()


def test_ugly_decimal_rows_untouched():
    """1/e gibi kesre benzemeyen sayı → satır ondalık kalır; temiz satır çarpılır."""
    ugly = 1 / 2.718281828
    A = np.array([[ugly, 1.0], [0.5, 1.0]])
    b = np.array([1.0, 2.0])
    A2, b2, mult = integer_rows(A, b)
    assert mult == [1, 2]
    assert A2[0].tolist() == A[0].tolist() and b2[0] == 1.0
    assert A2[1].tolist() == [1, 2] and b2[1] == 4


def test_one_over_2_7_is_a_clean_fraction_10_over_27():
    """1/2.7 = 10/27 (payda ≤ 1000) kuralın gereği temiz kesirdir → ×27."""
    A2, b2, mult = integer_rows([[1 / 2.7, 1.0]], [0.0])
    assert mult == [27] and A2[0].tolist() == [10, 27]


def test_complex_rows_untouched():
    A = np.array([[0.5 + 0.25j, 1.0], [0.5, 0.25]], dtype=complex)
    b = np.array([1.0, 0.0], dtype=complex)
    A2, b2, mult = integer_rows(A, b)
    assert mult == [1, 4]                       # yalnız gerçek satır çarpılır
    assert A2[0].tolist() == A[0].tolist() and b2[0] == b[0]
    assert A2[1].tolist() == [2, 1]


def test_multiplier_above_1000_untouched():
    """1/37 ve 1/41 ayrı ayrı temiz kesir; EKOK = 1517 > 1000 → satır değişmez."""
    A = np.array([[1 / 37, 1 / 41]])
    A2, b2, mult = integer_rows(A, [0.0])
    assert mult == [1] and A2.tolist() == A.tolist()


def test_integers_above_100000_untouched():
    A2, _, mult = integer_rows([[0.5, 300000.0]], [0.0])
    assert mult == [1] and A2[0].tolist() == [0.5, 300000.0]


def test_zero_row_untouched():
    _, _, mult = integer_rows([[0.0, 0.0]], [0.0])
    assert mult == [1]


def test_exact_fmt_does_not_round_integers_to_four_digits():
    fmt = exact_fmt(lambda z: "FALLBACK")
    assert fmt(12345) == "12345" and fmt(-100000) == f"{MINUS}100000"
    assert fmt(196.0) == "196" and fmt(0) == "0"
    assert fmt(2.5) == "FALLBACK" and fmt(1 + 2j) == "FALLBACK"


# ═══════════════════════════════════════════════════════
#  Uçtan uca: anlatım
# ═══════════════════════════════════════════════════════

def solution_blocks(res, title="Denklemlerin Çözümü"):
    return [b for s in res.explanation if s.title == title for b in s.blocks]


def solution_texts(res, title="Denklemlerin Çözümü"):
    return [b.text for b in solution_blocks(res, title)]


def cramer_index(texts):
    return next(i for i, t in enumerate(texts) if "Üç bilinmeyenli" in t or "İki bilinmeyenli" in t)


def result_lines(res, title="Denklemlerin Çözümü"):
    """'V₂ = Δ₁/Δ = −24 / −4 = 6 V' → {'V₂': tam satır}."""
    return {b.text.split(" ", 1)[0]: b.text for b in solution_blocks(res, title) if b.kind == "result"}


def test_dependent_nodal_example_shows_scaling_step_and_integer_sarrus(solve):
    """
    V1 12 V (1–0), R1 2Ω (1–2), R2 4Ω (2–3), R3 6Ω (3–4), E1 0 4 V(R2) 2.
    Elle: V_R2 = V₂ − V₃, V₄ = −2(V₂ − V₃)  (E1: n+ = 0, n− = 4).
      Düğüm 2: (V₂−12)/2 + (V₂−V₃)/4 = 0   → 0.75V₂ − 0.25V₃ = 6    → ×4  : 3V₂ − V₃ = 24
      Düğüm 3: (V₃−V₂)/4 + (V₃−V₄)/6 = 0   → −0.25V₂+0.4167V₃−0.1667V₄ = 0 → ×12 : −3V₂ + 5V₃ − 2V₄ = 0
      Kısıt  : −2V₂ + 2V₃ − V₄ = 0 (zaten tam sayı)
      Δ = −4, Δ₁ = −24, Δ₂ = 24, Δ₃ = 96 → V₂ = 6, V₃ = −6, V₄ = −24
    """
    res, _, errors = solve("V1 1 0 DC 12\nR1 1 2 2\nR2 2 3 4\nR3 3 4 6\nE1 0 4 V(R2) 2" + GND)
    assert not any("⚠" in e for e in errors)
    texts = solution_texts(res)
    joined = "\n".join(texts)

    assert any(STEP_TITLE in t for t in texts)
    assert f"Düğüm 2 denklemini 4 ile çarpalım:  3·V₂ {MINUS} V₃ = 24" in joined
    assert f"Düğüm 3 denklemini 12 ile çarpalım:  {MINUS}3·V₂ + 5·V₃ {MINUS} 2·V₄ = 0" in joined
    # Zaten tam sayı olan kısıt satırı anılmaz
    assert "Kısıt (E1) denklemini" not in joined
    # Adım Sarrus'tan ÖNCE gelir
    step = next(i for i, t in enumerate(texts) if "denklemini 12 ile çarpalım" in t)
    assert step < cramer_index(texts)

    # Sarrus tam sayılarla: Δ = −4, ondalık yok
    sarrus = [t for t in texts if "Δ" in t and "|" in t]
    assert len(sarrus) == 4
    assert sarrus[0].rstrip().endswith(f"= {MINUS}4")
    assert "." not in "".join(sarrus)
    lines = result_lines(res)
    assert lines["V₂"].endswith(f"= {MINUS}24 / {MINUS}4 = 6 V")
    assert lines["V₃"].endswith(f"= 24 / {MINUS}4 = {MINUS}6 V")
    assert lines["V₄"].endswith(f"= 96 / {MINUS}4 = {MINUS}24 V")

    # Çözücü değerleri değişmedi
    v = {n: as_complex(res.node_voltages[n].value).real for n in ("2", "3", "4")}
    assert v == pytest.approx({"2": 6.0, "3": -6.0, "4": -24.0}, abs=1e-6)


def test_scaling_leaves_integer_systems_alone(solve):
    """Tüm katsayılar zaten tam sayı → 'Kesirlerden Kurtulalım' adımı yok."""
    res, _, _ = solve("V1 1 0 DC 12\nR1 1 2 1\nR2 2 0 1\nR3 2 3 1\nR4 3 0 1" + GND)
    texts = solution_texts(res)
    assert not any(STEP_TITLE in t or "ile çarpalım" in t for t in texts)
    # 3V₂ − V₃ = 12 ; −V₂ + 2V₃ = 0 → V₂ = 24/5, V₃ = 12/5
    assert any("İki bilinmeyenli" in t for t in texts)
    assert as_complex(res.node_voltages["2"].value).real == pytest.approx(4.8, abs=1e-6)


def test_scaling_skips_ugly_rows(solve):
    """R1 = 2.718 Ω → 1/2.718 kesre benzemez (payda > 1000): o satır ondalık kalır."""
    res, _, _ = solve("V1 1 0 DC 10\nR1 1 2 2.718\nR2 2 0 1\nR3 2 3 1\nR4 3 0 1" + GND)
    texts = solution_texts(res)
    assert not any("denklemini" in t and "ile çarpalım" in t for t in texts)
    assert any("İki bilinmeyenli" in t for t in texts)
    # Düğüm 2: (V₂−10)/2.718 + V₂ + (V₂−V₃) = 0 ; Düğüm 3: V₃ = V₂/2 → V₂(1/2.718 + 1.5) = 10/2.718
    v2 = (10 / 2.718) / (1 / 2.718 + 1.5)
    assert as_complex(res.node_voltages["2"].value).real == pytest.approx(v2, abs=1e-5)
    shown = result_lines(res)["V₂"]
    assert shown.endswith("V") and "Δ₁/Δ" in shown


def test_two_unknown_nodal_scaling_with_kilo_ohms(solve):
    """
    V1 12 V, R1 = 1k, R2 = 2k, R3 = 1k, R4 = 1k (mS/mA görünümü):
      2.5·V₂ − V₃ = 12 ; −V₂ + 2·V₃ = 0   →  Düğüm 2 × 2: 5·V₂ − 2·V₃ = 24
      Δ = 8, Δ₁ = 48, Δ₂ = 24 → V₂ = 6 V, V₃ = 3 V
    """
    res, _, _ = solve("V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\nR3 2 3 1k\nR4 3 0 1k" + GND)
    joined = "\n".join(solution_texts(res))
    assert f"Düğüm 2 denklemini 2 ile çarpalım:  5·V₂ {MINUS} 2·V₃ = 24" in joined
    assert "Düğüm 3 denklemini" not in joined
    assert f"Δ = a₁₁·a₂₂ {MINUS} a₁₂·a₂₁ = 5·2 {MINUS} ({MINUS}2)·({MINUS}1) = 8" in joined
    lines = result_lines(res)
    assert lines["V₂"].endswith("= 48 / 8 = 6 V") and lines["V₃"].endswith("= 24 / 8 = 3 V")
    assert as_complex(res.node_voltages["2"].value).real == pytest.approx(6.0, abs=1e-6)
    assert as_complex(res.node_voltages["3"].value).real == pytest.approx(3.0, abs=1e-6)


def test_ac_systems_are_never_scaled(solve):
    """AC fazör sistemleri tümüyle atlanır."""
    net = ("VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 2\nR2 2 3 4\nR3 3 0 6\nL1 2 0 0.1" + GND)
    res, _, errors = solve(net, mode="AC_PHASOR", frequency=50.0)
    assert not any("⚠" in e for e in errors)
    texts = solution_texts(res)
    assert any("İki bilinmeyenli" in t for t in texts)      # sistem yine de gösterilir
    assert not any(STEP_TITLE in t or "ile çarpalım" in t for t in texts)


def test_dependent_constraint_row_is_labelled_and_scaled(solve):
    """
    Kazanç 0.5:  E1 0 4 V(R2) 0.5 → −V₄ = 0.5(V₂ − V₃) → kısıt (sol − sağ): −0.5V₂ + 0.5V₃ − V₄ = 0
      ×2 → −V₂ + V₃ − 2V₄ = 0  (etiket: Kısıt (E1))
    Elle: Düğüm 2: 3V₂ − V₃ = 24 ; Düğüm 3: −3V₂ + 5V₃ − 2V₄ = 0 ve V₄ = −0.5(V₂ − V₃)
      → −3V₂ + 5V₃ + (V₂ − V₃) = 0 → −2V₂ + 4V₃ = 0 → V₂ = 2V₃ → 5V₃ = 24
      V₃ = 4.8, V₂ = 9.6, V₄ = −2.4
    """
    res, _, _ = solve("V1 1 0 DC 12\nR1 1 2 2\nR2 2 3 4\nR3 3 4 6\nE1 0 4 V(R2) 0.5" + GND)
    joined = "\n".join(solution_texts(res))
    assert f"Kısıt (E1) denklemini 2 ile çarpalım:  {MINUS}V₂ + V₃ {MINUS} 2·V₄ = 0" in joined
    assert "Düğüm 3 denklemini 12 ile çarpalım" in joined
    v = {n: as_complex(res.node_voltages[n].value).real for n in ("2", "3", "4")}
    assert v == pytest.approx({"2": 9.6, "3": 4.8, "4": -2.4}, abs=1e-6)
    lines = result_lines(res)
    assert lines["V₂"].endswith("= 9,6 V") and lines["V₃"].endswith("= 4,8 V")
    assert lines["V₄"].endswith(f"= {MINUS}2,4 V")


def test_mesh_kilo_ohm_system_is_scaled(solve):
    """
    V1 10 V, R1 2.2k, R2 1k, R3 3.3k, R4 1.5k (kΩ/mA görünümü):
      3.2·I₁ − I₂ = 10 ; −I₁ + 5.8·I₂ = 0  → her biri ×5 → 16·I₁ − 5·I₂ = 50 ; −5·I₁ + 29·I₂ = 0
      Δ = 464 − 25 = 439, Δ₁ = 1450, Δ₂ = 250 → I₁ = 3.303 mA, I₂ = 0.5695 mA
    """
    res, _, errors = solve("V1 1 0 DC 10\nR1 1 2 2.2k\nR2 2 0 1k\nR3 2 3 3.3k\nR4 3 0 1.5k" + GND,
                           analysis_type="MESH")
    assert not any("⚠" in e for e in errors)
    joined = "\n".join(solution_texts(res))
    assert f"Çevre 1 denklemini 5 ile çarpalım:  16·I₁ {MINUS} 5·I₂ = 50" in joined
    assert f"Çevre 2 denklemini 5 ile çarpalım:  {MINUS}5·I₁ + 29·I₂ = 0" in joined
    assert f"Δ = 16·29 {MINUS} ({MINUS}5)·({MINUS}5) = 439" in joined
    assert "I₁ = Δ₁/Δ = 1450 / 439 = 3,303 mA" in joined
    i1, i2 = (m.current.real for m in res.meshes)
    assert i1 == pytest.approx(1450 / 439e3, rel=1e-6)
    assert i2 == pytest.approx(250 / 439e3, rel=1e-6)


def test_dependent_mesh_system_is_scaled(solve):
    """
    V1 12, R1 2, R2 5, R3 3, E1 3 4 V(R2) 0.5 (E1 = 0.5·5·(I₁ − I₂)), R4 2:
      Çevre 1: 7·I₁ − 5·I₂ = 12
      Çevre 2: 5(I₂ − I₁) + 3I₂ + 2I₂ = −0.5·5·(I₁ − I₂) → −2.5·I₁ + 7.5·I₂ = 0 → ×2
      Δ = 7·15 − 25 = 80, Δ₁ = 180, Δ₂ = 60 → I₁ = 2.25 A, I₂ = 0.75 A
    """
    res, _, errors = solve("V1 1 0 DC 12\nR1 1 2 2\nR2 2 0 5\nR3 2 3 3\nE1 3 4 V(R2) 0.5\nR4 4 0 2" + GND,
                           analysis_type="MESH")
    assert not any("⚠" in e for e in errors)
    joined = "\n".join(solution_texts(res))
    assert f"Çevre 2 denklemini 2 ile çarpalım:  {MINUS}5·I₁ + 15·I₂ = 0" in joined
    assert "Çevre 1 denklemini" not in joined
    assert f"Δ = 7·15 {MINUS} ({MINUS}5)·({MINUS}5) = 80" in joined
    assert "I₁ = Δ₁/Δ = 180 / 80 = 2,25 A" in joined
    i1, i2 = (m.current.real for m in res.meshes)
    assert (i1, i2) == pytest.approx((2.25, 0.75), abs=1e-6)
