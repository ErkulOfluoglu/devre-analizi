"""
Bağımlı kaynaklı devrelerde adım adım DÜĞÜM GERİLİMİ anlatımı, Thevenin/Norton ve alıştırma.

Her beklenen değer elle hesaplanmıştır (yorumlarda); çözücü sayıları yalnızca
"anlatımdaki son sayı çözücüyle aynı" denetiminde karşılaştırılır.

Ortak temel devre (BASE):
    V1 = 10 V (1–0), R1 = 2 Ω (1–2), R2 = 4 Ω (2–0)
    V2 = 10·4/6 = 20/3 = 6.667 V,  I_R2 = 5/3 A
"""

import re

import pytest

from explainer.cramer import cramer3, sarrus
from explainer.formatting import MINUS, num
from models.request import AnalysisType
from parser.netlist_parser import parse_netlist
from practice.checker import check_answer
from tests.conftest import as_complex

GND = "\n* GND1 — Referans toprak (Node 0)"
BASE = "V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 4\n"
OLD_NOTE = "bir sonraki sürümde"


# ═══════════════════════════════════════════════════════
#  Yardımcılar
# ═══════════════════════════════════════════════════════

def blocks_of(res, title=None):
    return [b for s in res.explanation if title is None or s.title == title for b in s.blocks]


def full_text(res):
    return "\n".join(b.text for b in blocks_of(res))


def section_titles(res):
    return [s.title for s in res.explanation]


_PREFIX = {"": 1.0, "k": 1e3, "m": 1e-3, "µ": 1e-6, "M": 1e6}


def _value_in(text):
    """'… = 6.667 V' ya da '… = −20 V' ya da '… = 750 mV' → float (DC, son '=' sonrası)."""
    tail = text.rsplit("=", 1)[1].strip()
    m = re.match(r"^([−-]?[\d.]+)\s*([kmµM]?)V$", tail)
    assert m, tail
    return float(m.group(1).replace(MINUS, "-")) * _PREFIX[m.group(2)]


def final_voltages(res):
    """'Denklemlerin Çözümü' bölümündeki 'V₃ = … = 20 V' sonuç satırları → {düğüm: değer}."""
    sub = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
    out = {}
    for b in blocks_of(res, "Denklemlerin Çözümü"):
        if b.kind == "result" and b.text.startswith("V"):
            node = b.text.split(" ", 1)[0][1:].translate(sub)
            out[node] = _value_in(b.text)
    return out


def assert_text_matches_solver(res):
    """Anlatımdaki her son V değeri çözücünün düğüm gerilimiyle (4 anlamlı basamak) aynı."""
    shown = final_voltages(res)
    assert shown, "Denklemlerin Çözümü bölümünde sonuç yok"
    for node, v in shown.items():
        assert v == pytest.approx(as_complex(res.node_voltages[node].value).real, rel=2e-3, abs=1e-9)


# ═══════════════════════════════════════════════════════
#  cramer.py — elle hesaplanmış 3×3 örnek
# ═══════════════════════════════════════════════════════

def fmt(z):
    return num(complex(z).real)


def test_cramer3_hand_checked_example():
    """
    A = [[4,−1,0],[−1,6,−2],[0,−2,5]], b = [12,0,10]
      Δ  = (120 + 0 + 0) − (0 + 16 + 5) = 99
      Δ₁ = 12(30−4) + 1(0+20) + 0 = 312 + 20 = 332   → x₁ = 332/99 = 3.354
    """
    A = [[4, -1, 0], [-1, 6, -2], [0, -2, 5]]
    b = [12, 0, 10]
    dets = cramer3(A, b, fmt)
    assert [d[0] for d in dets] == ["Δ", "Δ₁", "Δ₂", "Δ₃"]
    assert dets[0][2] == pytest.approx(99)
    assert dets[1][2] == pytest.approx(332)
    assert dets[1][2] / dets[0][2] == pytest.approx(3.353535, rel=1e-6)

    text = dets[0][1]
    lines = text.splitlines()
    # ilk iki sütun sağa tekrar yazılmış: | 4 −1 0 | 4 −1   (Δ = etiketi ortadaki satırda)
    assert re.sub(r"\s+", " ", lines[0]).strip() == "| 4 −1 0 | 4 −1"
    assert re.sub(r"\s+", " ", lines[1]).strip() == "Δ = | −1 6 −2 | −1 6"
    assert re.sub(r"\s+", " ", lines[2]).strip() == "| 0 −2 5 | 0 −2"
    assert " = (" in text.splitlines()[-1] and f") {MINUS} (" in text.splitlines()[-1]
    assert text.splitlines()[-1].rstrip().endswith("= 99")
    # Δ = (120 + 0 + 0) − (0 + 16 + 5)  (Sarrus: 4·6·5, (−1)·(−2)·0, 0·(−1)·(−2) | 0·6·0, 4·(−2)·(−2), (−1)·(−1)·5)
    assert "(120 + 0 + 0)" in text and "(0 + 16 + 5)" in text

    # Δ₁: ilk sütun yerine b
    assert re.sub(r"\s+", " ", dets[1][1].splitlines()[0]).strip() == "| 12 −1 0 | 12 −1"


def test_cramer3_second_example_and_solution():
    """
    A = [[7,−2,−3],[−2,9,−4],[−3,−4,10]]:
      Δ = 7(90−16) + 2(−20−12) − 3(8+27) = 518 − 64 − 105 = 349
    """
    A = [[7, -2, -3], [-2, 9, -4], [-3, -4, 10]]
    b = [50, 0, 0]
    dets = cramer3(A, b, fmt)
    assert dets[0][2] == pytest.approx(349)
    # Δ₁ = 50(90−16) = 3700 → x₁ = 3700/349 ≈ 10.60 ; Cramer çözümü numpy ile aynı
    import numpy as np
    x = np.linalg.solve(np.array(A, dtype=float), np.array(b, dtype=float))
    for k in range(3):
        assert dets[k + 1][2] / dets[0][2] == pytest.approx(x[k], rel=1e-9)
    assert dets[1][2] / dets[0][2] == pytest.approx(3700 / 349)


def test_sarrus_value_and_layout():
    text, det = sarrus("Δ", [[1, 2, 3], [4, 5, 6], [7, 8, 10]], fmt)
    # det = 1(50−48) − 2(40−42) + 3(32−35) = 2 + 4 − 9 = −3
    assert det == pytest.approx(-3)
    lines = text.splitlines()
    assert len(lines) == 4 and all("|" in ln for ln in lines[:3])
    assert lines[-1].rstrip().endswith(f"= {MINUS}3")


# ═══════════════════════════════════════════════════════
#  Düğüm anlatımı: dört tür (DC)
# ═══════════════════════════════════════════════════════

def test_vcvs_nodal_steps(solve):
    """
    E1 3 0 V(R2) 3, R3 = 6.   V_R2 = V₂.
      Düğüm 2: (V₂−10)/2 + V₂/4 = 0 → 0.75·V₂ = 5 → V₂ = 6.667
      E1: V₃ = 3·V_R2 = 3·V₂ → V₃ = 20
    """
    res, _, _ = solve(BASE + "E1 3 0 V(R2) 3\nR3 3 0 6" + GND)
    text = full_text(res)
    assert OLD_NOTE not in text
    titles = section_titles(res)
    for t in ("Kontrol Büyüklüğünü Bilinmeyenlerle Yazalım", "Düğüm Denklemleri (KCL)",
              "Denklemlerin Çözümü", "Bağımlı Kaynakların Kontrolü"):
        assert t in titles
    assert "V_R2 = V₂ − V₀ = V₂" in text
    assert "Düğüm 2: (V₂ − V₁)/R1 + V₂/R2 = 0" in text
    assert "⇒ (V₂ − 10)/2 + V₂/4 = 0" in text
    assert "Kısıt (E1): V₃ = 3·V_R2" in text and "⇒ V₃ = 3·V₂" in text
    # KCL yerine kısıt: Düğüm 3 için KCL yazılmaz
    kcl_text = "\n".join(b.text for b in blocks_of(res, "Düğüm Denklemleri (KCL)"))
    assert "Düğüm 3: " not in kcl_text
    assert "0.75·V₂ = 5" in text and f"{MINUS}3·V₂ + V₃ = 0" in text
    assert final_voltages(res) == pytest.approx({"2": 20 / 3, "3": 20.0}, rel=2e-3)
    assert_text_matches_solver(res)


def test_vccs_nodal_steps(solve):
    """
    G1 3 0 V(R2) 0.5, R3 = 6: akım 0.5·V_R2 düğüm 3'ten ÇIKAR (n+ = 3).
      Düğüm 3: V₃/6 + 0.5·V₂ = 0 → V₃ = −3·V₂ = −20 V
    """
    res, _, _ = solve(BASE + "G1 3 0 V(R2) 0.5\nR3 3 0 6" + GND)
    text = full_text(res)
    assert OLD_NOTE not in text
    assert "Düğüm 3: V₃/R3 + 0.5·V_R2 = 0" in text       # önce kontrol büyüklüğünün adıyla
    assert "⇒ V₃/6 + 0.5·V₂ = 0" in text                  # sonra düğüm gerilimiyle
    assert "0.5·V₂ + 0.1667·V₃ = 0" in text               # bilinmeyenler solda toplandı
    assert final_voltages(res) == pytest.approx({"2": 20 / 3, "3": -20.0}, rel=2e-3)
    assert_text_matches_solver(res)


def test_ccvs_nodal_steps(solve):
    """
    H1 3 0 I(R2) 3: I_R2 = V₂/R2 = V₂/4 (2→0).  V₃ = 3·I_R2 = 0.75·V₂ = 0.75·6.667 = 5 V
    """
    res, _, _ = solve(BASE + "H1 3 0 I(R2) 3\nR3 3 0 6" + GND)
    text = full_text(res)
    assert "I_R2 = V₂/R2" in text and "= 0.25·V₂" in text
    assert "Kısıt (H1): V₃ = 3·I_R2" in text and "⇒ V₃ = 3·V₂/4" in text
    assert final_voltages(res) == pytest.approx({"2": 20 / 3, "3": 5.0}, rel=2e-3)
    assert_text_matches_solver(res)


def test_cccs_nodal_steps_with_reversed_current_control(solve):
    """
    F1 3 0 I(-R2) 2: I_R2 ters (çizili ok 0→2): I_R2 = (V₀ − V₂)/R2 = −0.25·V₂ — eksik işaret
    eklenmez, tanım yönüyle yazılır.  Akım = 2·I_R2 = −3.333 A, düğüm 3'ten çıkar:
      V₃/6 + 2·I_R2 = 0 → V₃/6 − 0.5·V₂ = 0 → V₃ = 3·V₂ = +20 V
    """
    res, _, _ = solve(BASE + "F1 3 0 I(-R2) 2\nR3 3 0 6" + GND)
    text = full_text(res)
    assert "I_R2 = (V₀ − V₂)/R2" in text
    assert "Düğüm 3: V₃/R3 + 2·I_R2 = 0" in text
    assert f"{MINUS}I_R2" not in text and "(−I_R2)" not in text     # kontrol adında eksik işaret yok
    assert final_voltages(res) == pytest.approx({"2": 20 / 3, "3": 20.0}, rel=2e-3)
    assert_text_matches_solver(res)


def test_reversed_voltage_control_is_not_written_with_a_minus(solve):
    """
    E1 3 0 V(-R2) 3: V_R2 = V₀ − V₂ = −V₂ (çizili polarite). V₃ = 3·V_R2 = −3·V₂ = −20 V.
    """
    res, _, _ = solve(BASE + "E1 3 0 V(-R2) 3\nR3 3 0 6" + GND)
    text = full_text(res)
    assert "V_R2 = V₀ − V₂ = −V₂" in text
    assert "Kısıt (E1): V₃ = 3·V_R2" in text
    assert "(−V_R2)" not in text and "−3·V_R2" not in text and "3·−V_R2" not in text
    assert final_voltages(res) == pytest.approx({"2": 20 / 3, "3": -20.0}, rel=2e-3)
    assert_text_matches_solver(res)


def test_dc_capacitor_current_control_is_zero(solve):
    """
    H1 3 0 I(C1) 5: DC'de kondansatör açık → I_C1 = 0 → V₃ = 5·0 = 0 V; V₂ = 10 V.
    """
    res, _, _ = solve("V1 1 0 DC 10\nR1 1 2 2\nC1 2 0 1u\nH1 3 0 I(C1) 5\nR3 3 0 6" + GND)
    text = full_text(res)
    assert "I_C1 = 0" in text and "açık devre" in text
    assert OLD_NOTE not in text
    assert abs(as_complex(res.node_voltages["3"].value)) < 1e-12
    assert_text_matches_solver(res)


# ═══════════════════════════════════════════════════════
#  Süperdüğüm, 3 bilinmeyen (Sarrus), AC
# ═══════════════════════════════════════════════════════

def test_supernode_with_dependent_voltage_source(solve):
    """
    E1 3 4 V(R2) 2, R3 3 0 6, R4 4 0 12:  V_R2 = V₂ = 6.667.
      Süperdüğüm {3,4}: V₃/6 + V₄/12 = 0 → V₄ = −2·V₃
      Kısıt: V₃ − V₄ = 2·V₂ = 13.33 → 3·V₃ = 13.33 → V₃ = 4.444, V₄ = −8.889
    """
    res, _, _ = solve(BASE + "E1 3 4 V(R2) 2\nR3 3 0 6\nR4 4 0 12" + GND)
    text = full_text(res)
    assert "Süperdüğüm {3, 4}: V₃/R3 + V₄/R4 = 0" in text
    assert "⇒ V₃/6 + V₄/12 = 0" in text
    assert "Kısıt (E1): V₃ − V₄ = 2·V_R2" in text and "⇒ V₃ − V₄ = 2·V₂" in text
    assert final_voltages(res) == pytest.approx(
        {"2": 20 / 3, "3": 40 / 9, "4": -80 / 9}, rel=2e-3)
    assert_text_matches_solver(res)


def test_three_unknowns_use_sarrus(solve):
    """
    E1 3 0 V(R2) 3, R3 3 4 6, R4 4 0 12:
      V₂ = 6.667, V₃ = 20, Düğüm 4: (V₄−20)/6 + V₄/12 = 0 → 3·V₄ = 40 → V₄ = 13.33
      A = [[0.75,0,0],[−3,1,0],[0,−1/6,1/4]], Δ = 0.75·1·0.25 = 0.1875
      Kesirlerden kurtulma: Düğüm 2 ×4 (3·V₂ = 20), Düğüm 4 ×12 (−2·V₃ + 3·V₄ = 0) → Δ = 3·1·3 = 9
    """
    res, _, _ = solve(BASE + "E1 3 0 V(R2) 3\nR3 3 4 6\nR4 4 0 12" + GND)
    text = full_text(res)
    assert "Üç bilinmeyenli sistemi Cramer kuralıyla" in text and "Sarrus" in text
    sarrus_blocks = [b.text for b in blocks_of(res, "Denklemlerin Çözümü")
                     if b.kind == "math" and "Δ" in b.text and "|" in b.text]
    assert len(sarrus_blocks) == 4
    assert all(t.count("|") == 6 and f") {MINUS} (" in t for t in sarrus_blocks)
    solution = chr(10).join(b.text for b in blocks_of(res, "Denklemlerin Çözümü"))
    assert "Düğüm 2 denklemini 4 ile çarpalım" in solution
    assert "Düğüm 4 denklemini 12 ile çarpalım" in solution
    assert sarrus_blocks[0].rstrip().endswith("= 9")
    assert final_voltages(res) == pytest.approx({"2": 20 / 3, "3": 20.0, "4": 40 / 3}, rel=2e-3)
    assert_text_matches_solver(res)


def test_ac_phasor_nodal_steps(solve):
    """
    VAC1 10∠0°, R1 = 100, C1 = 10 µF (50 Hz: Z_C = −j318.3 Ω), E1 3 0 V(C1) 2, R2 3–4 = 50, L1 4–0 = 0.1 H (Z_L = j31.42).
      V₂ = 10·Z_C/(R1+Z_C) = 3183/333.6 = 9.542∠−17.44°,  V_C1 = V₂
      V₃ = 2·V₂ = 19.08∠−17.44°
      V₄ = V₃·Z_L/(R2+Z_L) = 19.08·0.5321 = 10.15∠40.4°
    """
    net = ("VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nC1 2 0 10u\n"
           "E1 3 0 V(C1) 2\nR2 3 4 50\nL1 4 0 0.1" + GND)
    res, _, errors = solve(net, mode="AC_PHASOR", frequency=50.0)
    assert not any("⚠" in e for e in errors)
    text = full_text(res)
    assert OLD_NOTE not in text
    assert "V_C1 = V₂ − V₀ = V₂" in text
    assert "Düğüm 2: (V₂ − V₁)/R1 + V₂/Z_C1 = 0" in text
    assert "Kısıt (E1): V₃ = 2·V_C1" in text
    assert "Sarrus" in text
    assert abs(as_complex(res.node_voltages["2"].value)) == pytest.approx(9.542, rel=2e-3)
    assert abs(as_complex(res.node_voltages["3"].value)) == pytest.approx(19.08, rel=2e-3)
    assert abs(as_complex(res.node_voltages["4"].value)) == pytest.approx(10.15, rel=2e-3)
    # Anlatımdaki kutupsal sonuçlar çözücüyle aynı (büyüklük ve açı)
    import cmath
    import math
    for b in blocks_of(res, "Denklemlerin Çözümü"):
        if b.kind == "result" and b.text.startswith("V"):
            node = {"₂": "2", "₃": "3", "₄": "4"}[b.text[1]]
            m = re.search(r"= ([\d.]+)∠([−\d.]+)° V$", b.text)
            assert m, b.text
            mag, ang = float(m.group(1)), float(m.group(2).replace(MINUS, "-"))
            z = as_complex(res.node_voltages[node].value)
            assert mag == pytest.approx(abs(z), rel=2e-3)
            assert ang == pytest.approx(math.degrees(cmath.phase(z)), abs=0.02)


# ═══════════════════════════════════════════════════════
#  Desteklenmeyen durumda dürüst yedek anlatım
# ═══════════════════════════════════════════════════════

def test_current_control_through_voltage_source_falls_back_with_reason(solve):
    """F1 3 0 I(V1) 2: kontrol akımı bir gerilim kaynağının akımı → düğüm denklemleri yazılmaz."""
    res, _, _ = solve(BASE + "F1 3 0 I(V1) 2\nR3 3 0 6" + GND)
    text = full_text(res)
    assert "Düğüm Denklemleri (KCL)" not in section_titles(res)
    assert "çevre akımları yöntemiyle daha kolay çözülür" in text
    assert "Çözücüden alınmıştır" in text.replace("çözücüden", "Çözücüden") or "çözücüden alınmıştır" in text
    assert OLD_NOTE not in text
    # Çözücü sonuçları yine verilir:  V₂ = 6.667, F1 = 2·(−5/3) = −3.333 A → V₃ = +20 V
    assert "V₃ = 20 V" in text and "V₂ = 6.667 V" in text
    assert as_complex(res.node_voltages["3"].value).real == pytest.approx(20.0, rel=1e-6)


def test_dc_inductor_current_control_falls_back(solve):
    res, _, _ = solve("V1 1 0 DC 10\nR1 1 2 2\nL1 2 0 1m\nF1 3 0 I(L1) 2\nR3 3 0 6" + GND)
    text = full_text(res)
    assert "bobin" in text and "Düğüm Denklemleri (KCL)" not in section_titles(res)
    assert OLD_NOTE not in text


# ═══════════════════════════════════════════════════════
#  Thevenin / Norton
# ═══════════════════════════════════════════════════════

THEV = "V1 1 0 DC 10\nR1 1 2 2\nG1 2 0 V(R1) {g}" + GND


def test_thevenin_uses_isc_and_vth_over_in(solve):
    """
    THEV (g = 0.25), port 2–0:  Vth = 10 V.
    Terminaller kısa: V₂ = 0 → I_R1 = 10/2 = 5 A, G1 = 0.25·10 = 2.5 A akım çeker → In = 5 − 2.5 = 2.5 A
    Rth = Vth/In = 10/2.5 = 4 Ω
    """
    res, _, _ = solve(THEV.format(g="0.25"), analysis_type="THEVENIN", terminals=("2", "0"))
    text = full_text(res)
    assert "SIFIRLANMAZ" in text
    assert "In = Isc = 2.5 A" in text
    assert "Rth = Vth / In = 10 V / 2.5 A" in text
    assert "Rth = 4 Ω" in text
    assert "test kaynağı" not in text.split("2. Adım")[0]
    assert as_complex(res.thevenin.zth).real == pytest.approx(4.0)


def test_norton_isc_is_computed_not_derived_from_rth(solve):
    res, _, _ = solve(THEV.format(g="0.25"), analysis_type="NORTON", terminals=("2", "0"))
    text = full_text(res)
    assert "Thevenin–Norton dönüşümüyle" not in text          # In = Vth/Rn döngüsel olurdu
    assert "kısa devre edilip devre bu hâliyle yeniden çözüldüğünde" in text
    assert "In = 2.5 A" in text
    assert "Rn = Vth / In = 10 V / 2.5 A" in text and "Rn = 4 Ω" in text


def test_thevenin_negative_rth_keeps_the_note(solve):
    """g = 1: Isc = 5 − 1·10 = −5 A → Rth = 10/(−5) = −2 Ω."""
    res, _, _ = solve(THEV.format(g="1"), analysis_type="THEVENIN", terminals=("2", "0"))
    text = full_text(res)
    assert "In = Isc = −5 A" in text
    assert "Rth = Vth / In = 10 V / (−5 A)" in text and "Rth = −2 Ω" in text
    assert "negatif" in text


def test_thevenin_with_only_dependent_sources_uses_test_source(solve):
    """
    R1 = 2 (1–2), R2 = 4 (2–0), E1 1 0 V(R2) 3, bağımsız kaynak YOK, port 2–0:
      Vth = 0, In = 0 → 0/0.  1 V test kaynağı: V₂ = 1, V₁ = 3·V₂ = 3,
      I_test = V₂/R2 + (V₂ − V₁)/R1 = 1/4 + (1−3)/2 = −0.75 A  →  Rth = 1/(−0.75) = −1.333 Ω
    """
    net = "R1 1 2 2\nR2 2 0 4\nE1 1 0 V(R2) 3" + GND
    res, _, _ = solve(net, analysis_type="THEVENIN", terminals=("2", "0"))
    text = full_text(res)
    assert "test kaynağı yöntemi" in text
    assert "V_test = 1 V" in text
    assert f"I_test = {MINUS}750 mA" in text
    assert f"Rth = V_test / I_test = 1 V / ({MINUS}750 mA)" in text
    assert f"Rth = {MINUS}1.333 Ω" in text
    assert "negatif" in text
    assert as_complex(res.thevenin.zth).real == pytest.approx(-4 / 3, rel=1e-6)


def test_norton_with_only_dependent_sources_uses_test_source(solve):
    """
    R1 = 2 (1–2), R2 = 4 (2–0), G1 1 0 V(R2) 0.1 (akım düğüm 1'den çıkar), port 1–0:
      1 V test: V₁ = 1, V₂ = 1·4/6 = 0.6667, V_R2 = 0.6667,  G1 = 0.0667 A
      I_test = (1 − 0.6667)/2 + 0.0667 = 0.1667 + 0.0667 = 0.2333 A → Rn = 1/0.2333 = 4.286 Ω
    """
    net = "R1 1 2 2\nR2 2 0 4\nG1 1 0 V(R2) 0.1" + GND
    res, _, _ = solve(net, analysis_type="NORTON", terminals=("1", "0"))
    text = full_text(res)
    assert "test kaynağı yöntemi" in text
    assert "I_test = 233.3 mA" in text
    assert "Rn = V_test / I_test = 1 V / 233.3 mA" in text and "Rn = 4.286 Ω" in text
    assert as_complex(res.norton.z_n).real == pytest.approx(30 / 7, rel=1e-6)


def test_thevenin_ac_with_dependent_source(solve):
    """
    VAC1 10∠0°, R1 = 100 (1–2), G1 2 0 V(R1) 0.005, C1 = 10 µF (2–0), 50 Hz, port 2–0.
      KCL: (V₂−10)/100 + 0.005·(10−V₂) + jωC·V₂ = 0 → V₂(0.01 − 0.005 + j0.0031416) = 0.05
      Vth = 0.05/(0.005+j0.0031416) = 8.467∠−32.14° V.  Kısa devre (V₂=0): 0.1 − 0.05 = 0.05 A
      Zth = Vth/In = 169.3∠−32.14° Ω
    """
    net = ("VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nG1 2 0 V(R1) 0.005\nC1 2 0 10u" + GND)
    res, _, errors = solve(net, mode="AC_PHASOR", frequency=50.0,
                           analysis_type="THEVENIN", terminals=("2", "0"))
    assert not any("⚠" in e for e in errors)
    text = full_text(res)
    assert "In = Isc = 50∠0° mA" in text
    assert "Zth = Vth / In" in text
    zth = as_complex(res.thevenin.zth)
    assert abs(zth) == pytest.approx(169.3, rel=2e-3)
    assert as_complex(res.thevenin.vth) / 0.05 == pytest.approx(zth, rel=1e-6)


# ═══════════════════════════════════════════════════════
#  MESH yönlendirmesi
# ═══════════════════════════════════════════════════════

def test_mesh_method_with_dependent_source_never_shows_the_old_note(solve):
    """
    Çevre analizi başarılıysa çevre bölümleri, olmazsa sebebiyle düğüm anlatımı verilir;
    iki durumda da sonuçlar çözücüyle aynıdır.
    """
    res, _, _ = solve(BASE + "E1 3 0 V(R2) 3\nR3 3 0 6" + GND, analysis_type="MESH")
    text = full_text(res)
    titles = section_titles(res)
    assert OLD_NOTE not in text
    assert "Sonuç" in titles
    if res.meshes:
        assert any("Çevre" in t for t in titles)
    else:
        assert "Düğüm Denklemleri (KCL)" in titles or "Çevre Akımları Yöntemi" in titles
    assert as_complex(res.node_voltages["3"].value).real == pytest.approx(20.0, rel=1e-6)


# ═══════════════════════════════════════════════════════
#  Alıştırma soruları
# ═══════════════════════════════════════════════════════

def test_practice_questions_exist_and_check_correctly(solve):
    """
    E1 3 0 V(R2) 3, R3 = 6: V₂ = 6.667 V, V₃ = 20 V, I_R3 = 20/6 = 3.333 A.
    """
    res, _, _ = solve(BASE + "E1 3 0 V(R2) 3\nR3 3 0 6" + GND)
    qs = {q.id: q for q in res.practice}
    assert {"V2", "V3", "I_R1", "I_R2", "I_R3"} <= set(qs)
    assert check_answer(qs["V3"], "20 V").status == "correct"
    assert check_answer(qs["V2"], "6.667 V").status == "correct"
    assert check_answer(qs["V3"], "-20 V").status != "correct"
    assert check_answer(qs["I_R3"], "3.333 A").status == "correct"
    # İpuçları kontrol büyüklüğünü düğüm gerilimleriyle yazmayı söyler; V₃ için kısıt hatırlatılır
    assert "düğüm gerilimleriyle yazın" in qs["V2"].hint
    assert "E1" in qs["V3"].hint and "kısıt" in qs["V3"].hint
    assert "düğüm gerilimleriyle yazın" in qs["I_R3"].hint


def test_practice_questions_for_current_sources_and_ac(solve):
    res, _, _ = solve(BASE + "G1 3 0 V(R2) 0.5\nR3 3 0 6" + GND)
    qs = {q.id: q for q in res.practice}
    assert check_answer(qs["V3"], "-20").status == "correct"          # elle: −20 V
    assert "KCL" in qs["V3"].hint and "kazanç · kontrol büyüklüğü" in qs["V3"].hint

    net = ("VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nC1 2 0 10u\nE1 3 0 V(C1) 2\nR2 3 0 50" + GND)
    res, _, _ = solve(net, mode="AC_PHASOR", frequency=50.0)
    qs = {q.id: q for q in res.practice}
    assert "V3" in qs and qs["V3"].is_ac
    assert check_answer(qs["V3"], "19.08∠-17.44").status == "correct"   # elle: 2·9.542∠−17.44°


def test_practice_hint_for_voltage_source_current_control_mentions_kcl_or_mesh(solve):
    """Kontrol akımı bir gerilim kaynağından geçiyorsa ipucu 'düğüm gerilimleriyle yaz' demekle yetinmez."""
    res, _, _ = solve(BASE + "F1 3 0 I(V1) 2\nR3 3 0 6" + GND)
    qs = {q.id: q for q in res.practice}
    assert "yazılamaz" in qs["V3"].hint and "çevre akımları" in qs["V3"].hint


def test_practice_thevenin_rth_hint_does_not_tell_to_zero_the_dependent_source(solve):
    res, _, _ = solve(THEV.format(g="1"), analysis_type="THEVENIN", terminals=("2", "0"))
    qs = {q.id: q for q in res.practice}
    assert {"VTH", "RTH"} <= set(qs)
    assert "SIFIRLANMAZ" in qs["RTH"].hint and "seri/paralel indirgemeyle eşdeğeri bulun" not in qs["RTH"].hint
    assert "negatif" in qs["RTH"].sign_hint and "olamaz" not in qs["RTH"].sign_hint
    assert check_answer(qs["RTH"], "-2 ohm").status == "correct"        # elle: 10 V / (−5 A) = −2 Ω
    assert check_answer(qs["VTH"], "10 V").status == "correct"
