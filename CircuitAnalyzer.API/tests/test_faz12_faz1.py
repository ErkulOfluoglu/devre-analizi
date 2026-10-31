"""
Faz 1 kapsamlı köşe durumu testleri:
- Bağımlı kaynaklar E/G/H/F (işaret kuralları, ters kontrol, negatif kazanç, kaynak kontrolü,
  süperdüğüm içinde bağımlı kaynak, AC fazör modunda bağımlı kaynak, Thevenin/Norton test kaynağı yolu)
- Cramer/Sarrus ve tam sayı ölçekleme (kesirli katsayılar, 2×2 ve 3×3, Δ=0 tekil sistem, anlatım-çözüm tutarlılığı)
- Millman teoremi (akım kaynaklı kol, ters kutuplu kaynak, seri kaynaklı kol, GND'nin ara düğüm olması, uygulanamayan devreler)
- Kaynak dönüşümü ve Δ–Y (dengeli/dengesiz köprü, farklı terminal seçimleri, Y→Δ, tıkanma/Thevenin'e dönüş, Vth/Rth doğruluğu)

Tüm beklenen değerler elle/analitik olarak hesaplanmış ve her testin yorumunda açıklanmıştır.
"""

import cmath
import math
import pytest

from explainer.cramer import cramer3, exact_fmt, integer_rows, is_integral_row, sarrus
from explainer.formatting import num
from models.request import AnalysisMode, AnalysisType, TheveninTerminals
from parser.netlist_parser import parse_netlist

GND = "* GND1 — Referans toprak (Node 0)"


def as_complex(value):
    if isinstance(value, (int, float)):
        return complex(value, 0)
    return complex(value.real, value.imaginary)


def all_text(results) -> str:
    return "\n".join(b.text for s in results.explanation for b in s.blocks)


def section_titles(results):
    return [s.title for s in results.explanation]


# ═══════════════════════════════════════════════════════════════════════════
#  1. BAĞIMLI KAYNAKLAR (E / G / H / F)
# ═══════════════════════════════════════════════════════════════════════════

def test_dependent_reversed_control_vs_negative_gain_equivalence(solve):
    """
    Analitik hesap:
    V1 = 10 V (Düğüm 1 → 0), R1 = 4 Ω (1 → 2), R2 = 6 Ω (2 → 0).
    G1 bağımlı akım kaynağı Düğüm 2 → 0 yönünde:
      Durum A: G1 2 0 V(-R1) 0.5  → kontrol V(-R1) = -(V1 - V2) = V2 - 10, kazanç +0.5
               I_G1 (2→0) = 0.5·(V2 - 10)
      Durum B: G1 2 0 V(R1) -0.5  → kontrol V(R1) = V1 - V2 = 10 - V2, kazanç -0.5
               I_G1 (2→0) = -0.5·(10 - V2) = 0.5·(V2 - 10)
    Düğüm 2 KCL:
      (V2 - 10)/4 + V2/6 + 0.5·(V2 - 10) = 0
      12 ile çarpalım: 3(V2 - 10) + 2·V2 + 6(V2 - 10) = 0
      11·V2 = 90  ⇒  V2 = 90/11 ≈ 8.181818 V
      I_R1 = (10 - 90/11)/4 = (20/11)/4 = 5/11 ≈ 0.454545 A
      I_R2 = (90/11)/6 = 15/11 ≈ 1.363636 A
      I_G1 = 0.5·(90/11 - 10) = -10/11 ≈ -0.909091 A
      KCL kontrolü: I_R2 + I_G1 = 15/11 - 10/11 = 5/11 = I_R1 ✓
    """
    net_rev = f"V1 1 0 DC 10\nR1 1 2 4\nR2 2 0 6\nG1 2 0 V(-R1) 0.5\n{GND}"
    net_neg = f"V1 1 0 DC 10\nR1 1 2 4\nR2 2 0 6\nG1 2 0 V(R1) -0.5\n{GND}"

    res_rev, _, err_rev = solve(net_rev)
    res_neg, _, err_neg = solve(net_neg)
    assert err_rev == [] and err_neg == []

    v2_expected = 90.0 / 11.0
    assert res_rev.node_voltages["2"].value == pytest.approx(v2_expected, rel=1e-5)
    assert res_neg.node_voltages["2"].value == pytest.approx(v2_expected, rel=1e-5)
    assert res_rev.element_currents["R1"].value == pytest.approx(5.0 / 11.0, rel=1e-5)
    assert res_neg.element_currents["R1"].value == pytest.approx(5.0 / 11.0, rel=1e-5)
    assert res_rev.element_currents["G1"].value == pytest.approx(-10.0 / 11.0, rel=1e-5)
    assert res_neg.element_currents["G1"].value == pytest.approx(-10.0 / 11.0, rel=1e-5)


def test_dependent_cccs_reversed_current_control(solve):
    """
    Analitik hesap (F kaynağı, ters çevrilmiş akım kontrolü I(-R1)):
    V1 = 14 V (1 → 0), R1 = 2 Ω (1 → 2), R2 = 5 Ω (2 → 0), F1 2 0 I(-R1) 3.
    I(R1) = (V1 - V2)/R1 = (14 - V2)/2.
    Ters kontrol: I(-R1) = -I(R1) = (V2 - 14)/2.
    F1 akımı (2 → 0): I_F1 = 3 · (V2 - 14)/2.
    Düğüm 2 KCL:
      (V2 - 14)/2 + V2/5 + 3·(V2 - 14)/2 = 0
      2·(V2 - 14) + 0.2·V2 = 0  ⇒  2.2·V2 = 28  ⇒  V2 = 140/11 ≈ 12.727273 V.
    Bağımsız doğrulama:
      I_R1 = (14 - 140/11)/2 = 7/11 A
      I_R2 = (140/11)/5 = 28/11 A
      I_F1 = 3 · (-7/11) = -21/11 A
      I_R2 + I_F1 = 28/11 - 21/11 = 7/11 = I_R1 ✓
    """
    net = f"V1 1 0 DC 14\nR1 1 2 2\nR2 2 0 5\nF1 2 0 I(-R1) 3\n{GND}"
    res, _, err = solve(net)
    assert err == []
    assert res.node_voltages["2"].value == pytest.approx(140.0 / 11.0, rel=1e-5)
    assert res.element_currents["R1"].value == pytest.approx(7.0 / 11.0, rel=1e-5)
    assert res.element_currents["R2"].value == pytest.approx(28.0 / 11.0, rel=1e-5)
    assert res.element_currents["F1"].value == pytest.approx(-21.0 / 11.0, rel=1e-5)


def test_dependent_controlled_by_independent_and_dependent_sources(solve):
    """
    Kontrol elemanının bağımsız kaynak (V1) ve başka bir bağımlı kaynak (E1) olması:
    V1 = 8 V (1 → 0), R1 = 4 Ω (1 → 2), E1 2 0 V(V1) 0.5, F1 0 3 I(E1) 2, R2 = 10 Ω (3 → 0).
    Analitik hesap:
      V(V1) = V1 - V0 = 8 V  ⇒  V2 = E1 = 0.5 · 8 = 4 V.
      I_R1 (1 → 2) = (V1 - V2)/R1 = (8 - 4)/4 = 1 A.
      Düğüm 2'de sadece R1 ve E1 bağlı olduğundan E1 üzerinden 2 → 0 yönünde geçen akım:
      I(E1) = I_R1 = 1 A.
      F1 kaynağı 0 → 3 yönünde (Düğüm 3'e giren) I_F1 = 2 · I(E1) = 2 A verir.
      Düğüm 3'te R2 = 10 Ω (3 → 0): V3 = I_F1 · R2 = 2 · 10 = 20 V.
    """
    net = f"V1 1 0 DC 8\nR1 1 2 4\nE1 2 0 V(V1) 0.5\nF1 0 3 I(E1) 2\nR2 3 0 10\n{GND}"
    res, _, err = solve(net)
    assert err == []
    assert res.node_voltages["1"].value == pytest.approx(8.0, rel=1e-6)
    assert res.node_voltages["2"].value == pytest.approx(4.0, rel=1e-6)
    assert res.node_voltages["3"].value == pytest.approx(20.0, rel=1e-6)
    assert res.element_currents["E1"].value == pytest.approx(1.0, rel=1e-6)
    assert res.element_currents["F1"].value == pytest.approx(2.0, rel=1e-6)


def test_dependent_voltage_source_inside_supernode_ccvs(solve):
    """
    Süperdüğüm içinde CCVS (H1):
    V1 = 20 V (1 → 0), R1 = 2 Ω (1 → 2), R2 = 4 Ω (2 → 0),
    H1 2 3 I(R1) 6 (Düğüm 2 ile 3 arasında bağımlı gerilim kaynağı: V2 - V3 = 6·I(R1)),
    R3 = 8 Ω (3 → 0).
    Analitik hesap:
      I(R1) = (20 - V2)/2 = 10 - 0.5·V2.
      Süperdüğüm kısıtı (H1): V2 - V3 = 6·(10 - 0.5·V2) = 60 - 3·V2  ⇒  V3 = 4·V2 - 60.
      Süperdüğüm {2, 3} KCL:
        (V2 - 20)/2 + V2/4 + V3/8 = 0
        8 ile çarpalım: 4(V2 - 20) + 2·V2 + (4·V2 - 60) = 0
        10·V2 = 140  ⇒  V2 = 14 V,  V3 = 4(14) - 60 = -4 V.
      Kontrol:
        I(R1) = (20 - 14)/2 = 3 A
        V2 - V3 = 14 - (-4) = 18 V = 6 · 3 A ✓
        I_R2 = 14/4 = 3.5 A,  I_R3 = -4/8 = -0.5 A  ⇒  I_R2 + I_R3 = 3.0 A = I(R1) ✓
    """
    net = f"V1 1 0 DC 20\nR1 1 2 2\nR2 2 0 4\nH1 2 3 I(R1) 6\nR3 3 0 8\n{GND}"
    res, _, err = solve(net)
    assert err == []
    assert res.node_voltages["2"].value == pytest.approx(14.0, rel=1e-5)
    assert res.node_voltages["3"].value == pytest.approx(-4.0, rel=1e-5)
    assert res.element_currents["R1"].value == pytest.approx(3.0, rel=1e-5)
    assert res.element_currents["H1"].value == pytest.approx(-0.5, rel=1e-5)
    txt = all_text(res)
    assert "H1" in txt and "14" in txt


def test_dependent_source_in_ac_phasor_mode(solve):
    """
    AC fazör modunda bağımlı kaynak (VCCS G1):
    ω = 1000 rad/s  ⇒  f = 1000 / (2π) ≈ 159.154943 Hz.
    V1 = 10∠0° V (1 → 0), R1 = 10 Ω (1 → 2), C1 = 100 µF (2 → 0), G1 2 0 V(R1) 0.1.
    Analitik hesap:
      Z_C1 = 1 / (j·ω·C1) = 1 / (j · 1000 · 1e-4) = -j10 Ω  ⇒  Y_C1 = j0.1 S.
      V(R1) = V1 - V2 = 10 - V2.
      Düğüm 2 KCL:
        (V2 - 10)/10 + V2/(-j10) + 0.1·(10 - V2) = 0
        0.1·V2 - 1 + j0.1·V2 + 1 - 0.1·V2 = 0
        j0.1·V2 = 0  ⇒  V2 = 0 V!
      Şimdi G1 kazancını 0.05 S yapalım:
        (V2 - 10)/10 + j0.1·V2 + 0.05·(10 - V2) = 0
        (0.05 + j0.1)·V2 = 0.5  ⇒  V2 = 0.5 / (0.05 + j0.1) = 10 / (1 + j2) = 2 - j4 V.
      Kontrol:
        I_R1 = (10 - (2 - j4))/10 = 0.8 + j0.4 A
        I_C1 = (2 - j4)/(-j10) = 0.4 + j0.2 A
        I_G1 = 0.05 · (8 + j4) = 0.4 + j0.2 A
        I_C1 + I_G1 = 0.8 + j0.4 A = I_R1 ✓
    """
    freq = 1000.0 / (2.0 * math.pi)
    net = f"V1 1 0 AC_PHASOR(10, 0)\nR1 1 2 10\nC1 2 0 100u\nG1 2 0 V(R1) 0.05\n{GND}"
    res, _, err = solve(net, mode="AC_PHASOR", frequency=freq)
    assert err == []
    v2 = as_complex(res.node_voltages["2"].value)
    assert v2.real == pytest.approx(2.0, rel=1e-4)
    assert v2.imag == pytest.approx(-4.0, rel=1e-4)
    ir1 = as_complex(res.element_currents["R1"].value)
    assert ir1.real == pytest.approx(0.8, rel=1e-4)
    assert ir1.imag == pytest.approx(0.4, rel=1e-4)


def test_dependent_thevenin_dead_port_test_source_dc_and_ac(solve):
    """
    Bağımsız kaynak içermeyen (ölü port: Vth = 0, Isc = 0) bağımlı kaynaklı devrede
    test kaynağı (V_test = 1 V) yoluyla Zth/Rth hesabı:
    DC:
      R1 = 20 Ω (1 → 0), G1 0 1 V(R1) -0.03 (Düğüm 1'e -0.03·V1 girer ⇒ Düğüm 1'den +0.03·V1 çıkar).
      1 V test kaynağı Düğüm 1 (+) ile 0 (−) arasına bağlandığında:
      I_test = V1/20 + 0.03·V1 = (0.05 + 0.03)·1 = 0.08 A  ⇒  Rth = 1 / 0.08 = 12.5 Ω.
    AC (ω = 1000 rad/s):
      Paralel C1 = 60 µF eklenirse Y_C1 = j·1000·60e-6 = j0.06 S.
      Y_th = 0.08 + j0.06 S  ⇒  Z_th = 1 / (0.08 + j0.06) = (0.08 - j0.06) / 0.01 = 8 - j6 Ω.
    """
    net_dc = f"R1 1 0 20\nG1 0 1 V(R1) -0.03\n{GND}"
    res_dc, _, err_dc = solve(net_dc, analysis_type="THEVENIN", terminals=("1", "0"))
    assert err_dc == []
    assert as_complex(res_dc.thevenin.vth).real == pytest.approx(0.0, abs=1e-9)
    assert as_complex(res_dc.thevenin.zth).real == pytest.approx(12.5, rel=1e-5)
    assert "test kaynağı" in all_text(res_dc).lower()

    freq = 1000.0 / (2.0 * math.pi)
    net_ac = f"R1 1 0 20\nC1 1 0 60u\nG1 0 1 V(R1) -0.03\n{GND}"
    res_ac, _, err_ac = solve(
        net_ac, mode="AC_PHASOR", frequency=freq, analysis_type="THEVENIN", terminals=("1", "0")
    )
    assert err_ac == []
    zth = as_complex(res_ac.thevenin.zth)
    assert zth.real == pytest.approx(8.0, rel=1e-4)
    assert zth.imag == pytest.approx(-6.0, rel=1e-4)
    assert "test kaynağı" in all_text(res_ac).lower()


def test_dependent_thevenin_negative_equivalent_resistance(solve):
    """
    Pozitif geri beslemeli bağımlı kaynak ile negatif Thevenin direnci (Rth < 0):
    V1 = 6 V (1 → 0), R1 = 10 Ω (1 → 2), E1 0 2 V(R1) 2 (V0 - V2 = 2·(V1 - V2) ⇒ -V2 = 2·V1 - 2·V2 ⇒ V2 = 2·V1).
    Analitik hesap:
      Açık devrede (Düğüm 2 boşta):
        V_R1 = V1 - V2 = 6 - V2,  E1 Düğüm 2'yi doğrudan belirlemez mi?
        Dikkat: E1 gerilim kaynağı yerine G1 akım kaynağı kullanalım ki Düğüm 2 gerilimi serbest olsun:
        V1 = 6 V (1 → 0), R1 = 10 Ω (1 → 2), G1 0 2 V(R1) -0.3 (0 → 2 yönünde -0.3·(V1 - V2)).
      Açık devrede (I_out = 0):
        (V2 - 6)/10 - (-0.3·(6 - V2)) = 0  ⇒  0.1(V2 - 6) + 0.3(6 - V2) = 0
        -0.2(V2 - 6) = 0  ⇒  Vth = V2 = 6 V.
      Kısa devrede (V2 = 0):
        I_R1 = 6/10 = 0.6 A,  I_G1(0→2) = -0.3·(6 - 0) = -1.8 A
        Isc = I_R1 + I_G1 = 0.6 - 1.8 = -1.2 A.
      Rth = Vth / Isc = 6 / (-1.2) = -5 Ω!
      Test kaynağıyla kontrol (V1=0, V2=1 V):
        I_test = 1/10 - (-0.3·(0 - 1)) = 0.1 - 0.3 = -0.2 A  ⇒  Rth = 1 / (-0.2) = -5 Ω ✓
    """
    net = f"V1 1 0 DC 6\nR1 1 2 10\nG1 0 2 V(R1) -0.3\n{GND}"
    res, _, err = solve(net, analysis_type="THEVENIN", terminals=("2", "0"))
    assert err == []
    assert as_complex(res.thevenin.vth).real == pytest.approx(6.0, rel=1e-5)
    assert as_complex(res.thevenin.zth).real == pytest.approx(-5.0, rel=1e-5)


# ═══════════════════════════════════════════════════════════════════════════
#  2. CRAMER / SARRUS VE TAM SAYI ÖLÇEKLEME
# ═══════════════════════════════════════════════════════════════════════════

def test_cramer_sarrus_and_integer_rows_unit_cases():
    """
    explainer/cramer.py (sarrus, cramer3, integer_rows, is_integral_row, exact_fmt) birim testi:
    1) Kesirli satırların tam sayıya ölçeklenmesi (integer_rows):
       Satır 1: (1/2 + 1/3)·V1 - (1/3)·V2 = 3  →  [5/6, -1/3 | 3]  ×6  →  [5, -2 | 18]
       Satır 2: -(1/3)·V1 + (1/3 + 1/4)·V2 = 0 →  [-1/3, 7/12 | 0] ×12 →  [-4, 7 | 0]
    2) 3×3 Sarrus ve cramer3:
       2·V1 - 1·V2 + 0·V3 = 4
      -1·V1 + 3·V2 - 1·V3 = 2
       0·V1 - 1·V2 + 2·V3 = 2
       Δ = 2·3·2 + 0 + 0 - (0 + 2·(-1)·(-1) + (-1)·(-1)·2) = 12 - (2 + 2) = 8
       Δ1 = 26,  Δ2 = 20,  Δ3 = 18
       V1 = 26/8 = 3.25 V,  V2 = 20/8 = 2.5 V,  V3 = 18/8 = 2.25 V.
    3) Tekil 3×3 matriste (Δ = 0) sarrus det = 0 döndürür; karmaşık katsayılı satırlarda integer_rows
       çarpanı 1 bırakır (dokunmaz).
    """
    A_frac = [[5.0 / 6.0, -1.0 / 3.0], [-1.0 / 3.0, 7.0 / 12.0]]
    b_frac = [3.0, 0.0]
    assert not is_integral_row(A_frac[0], b_frac[0])
    A_int, b_int, mult = integer_rows(A_frac, b_frac)
    assert mult == [6, 12]
    assert A_int.tolist() == [[5.0, -2.0], [-4.0, 7.0]]
    assert b_int.tolist() == [18.0, 0.0]
    assert is_integral_row(A_int[0], b_int[0])

    fmt_fn = exact_fmt(lambda z: num(z.real))
    assert fmt_fn(12345) == "12345"
    assert fmt_fn(-196) == "−196"

    M3 = [[2.0, -1.0, 0.0], [-1.0, 3.0, -1.0], [0.0, -1.0, 2.0]]
    b3 = [4.0, 2.0, 2.0]
    items = cramer3(M3, b3, fmt_fn)
    assert [sym for sym, _, _ in items] == ["Δ", "Δ₁", "Δ₂", "Δ₃"]
    assert [val.real for _, _, val in items] == pytest.approx([8.0, 26.0, 20.0, 18.0])
    assert "= (12 + 0 + 0) − (0 + 2 + 2) = 8" in items[0][1]

    # Tekil 3×3 matris (1. ve 2. satır orantılı → Δ = 0)
    _, det_zero = sarrus("Δ", [[1, -1, 0], [2, -2, 0], [0, 1, 3]], fmt_fn)
    assert det_zero == pytest.approx(0.0)

    # Karmaşık katsayılı satıra integer_rows dokunmaz (0. satır çarpanı 1 kalır, 1. satır gerçek olduğundan ×2)
    _, _, mult_c = integer_rows([[0.5 + 0.5j, -0.5], [-0.5, 1.0]], [1.0, 0.0])
    assert mult_c == [1, 2]


def test_integer_scaling_3x3_nodal_consistency_with_cramer(solve):
    """
    3 bilinmeyenli kesirli iletkenlikli düğüm devresi:
    I1 = 3 A (0 → 1), R1 = 2 Ω (1 → 0), R2 = 3 Ω (1 → 2), R3 = 6 Ω (2 → 0),
    R4 = 4 Ω (2 → 3), R5 = 12 Ω (3 → 0).
    Analitik hesap:
      Düğüm 1 (EKOK(2,3) = 6 ile çarpılır):
        V1/2 + (V1 - V2)/3 = 3  ⇒  5·V1 - 2·V2 = 18
      Düğüm 2 (EKOK(3,6,4) = 12 ile çarpılır):
        (V2 - V1)/3 + V2/6 + (V2 - V3)/4 = 0  ⇒  -4·V1 + 9·V2 - 3·V3 = 0
      Düğüm 3 (EKOK(4,12) = 12 ile çarpılır):
        (V3 - V2)/4 + V3/12 = 0  ⇒  -3·V2 + 4·V3 = 0  ⇒  V3 = (3/4)·V2
      Yerine koyalım:
        -4·V1 + 9·V2 - 9/4·V2 = 0  ⇒  16·V1 = 27·V2  ⇒  V2 = (16/27)·V1
        5·V1 - 32/27·V1 = 18  ⇒  (103/27)·V1 = 18  ⇒  V1 = 486/103 V ≈ 4.718447 V
        V2 = 288/103 V ≈ 2.796117 V
        V3 = 216/103 V ≈ 2.097087 V
      Cramer determinantı (tam sayı ölçekli matris [[5,-2,0],[-4,9,-3],[0,-3,4]]):
        Δ = 5(36 - 9) - (-2)(-16) = 135 - 32 = 103
        Δ1 = 18 · 27 = 486,  Δ2 = 18 · 16 = 288,  Δ3 = 18 · 12 = 216.
    """
    net = f"I1 0 1 DC 3\nR1 1 0 2\nR2 1 2 3\nR3 2 0 6\nR4 2 3 4\nR5 3 0 12\n{GND}"
    res, _, err = solve(net, analysis_type="NODAL")
    assert err == []
    assert res.node_voltages["1"].value == pytest.approx(486.0 / 103.0, rel=1e-5)
    assert res.node_voltages["2"].value == pytest.approx(288.0 / 103.0, rel=1e-5)
    assert res.node_voltages["3"].value == pytest.approx(216.0 / 103.0, rel=1e-5)
    txt = all_text(res)
    assert "103" in txt and "486" in txt and "288" in txt and "216" in txt


# ═══════════════════════════════════════════════════════════════════════════
#  3. MILLMAN TEOREMİ
# ═══════════════════════════════════════════════════════════════════════════

def test_millman_opposing_series_sources_and_current_branch(solve):
    """
    Millman teoremi — aynı kolda ters bağlı iki gerilim kaynağı + iki direnç + akım kaynaklı kol:
    Ana düğümler: A = Düğüm 3, B = Düğüm 0 (GND).
    Kol 1: V1 1 0 DC 15 (+ ucu 1'de), V2 1 2 DC 5 (+ ucu 1'de, yani 0→3 yönünde ters: E1 = 15 - 5 = 10 V),
           R1a 2 4 3 Ω, R1b 4 3 2 Ω  ⇒  R_kol1 = 3 + 2 = 5 Ω.
    Kol 2: V3 0 5 DC 8 (+ ucu 0'da, yani A=3'e göre ters: E2 = -8 V), R2 5 3 4 Ω.
    Kol 3: R3 3 0 20 Ω (E3 = 0 V, R3 = 20 Ω).
    Kol 4: I1 0 3 DC 1.5 (0 → 3 yönünde +1.5 A), I2 3 0 DC 0.5 (3 → 0 yönünde, yani -0.5 A).
    Analitik Millman hesabı:
      Pay = E1/R_kol1 + E2/R2 + E3/R3 + I1 - I2
          = 10/5 + (-8)/4 + 0/20 + 1.5 - 0.5 = 2 - 2 + 0 + 1 = 1.0 A
      Payda = 1/5 + 1/4 + 1/20 = (4 + 5 + 1)/20 = 10/20 = 0.5 S
      V_AB = V3 = 1.0 / 0.5 = 2.0 V.
    Kol akımları (B → A, yani 0 → 3 yönünde):
      I_kol1 = (10 - 2)/5 = 1.6 A
      I_kol2 = (-8 - 2)/4 = -2.5 A
      I_kol3 = (0 - 2)/20 = -0.1 A
      I_kol4 = 1.5 - 0.5 = 1.0 A
      KCL kontrolü: 1.6 - 2.5 - 0.1 + 1.0 = 0 ✓
    """
    net = (
        f"V1 1 0 DC 15\nV2 1 2 DC 5\nR1a 2 4 3\nR1b 4 3 2\n"
        f"V3 0 5 DC 8\nR2 5 3 4\nR3 3 0 20\nI1 0 3 DC 1.5\nI2 3 0 DC 0.5\n{GND}"
    )
    res, _, err = solve(net, analysis_type="MILLMAN")
    assert err == []
    assert res.node_voltages["3"].value == pytest.approx(2.0, rel=1e-5)
    assert res.element_currents["R1a"].value == pytest.approx(1.6, rel=1e-5)
    assert res.element_currents["R2"].value == pytest.approx(-2.5, rel=1e-5)
    assert res.element_currents["R3"].value == pytest.approx(0.1, rel=1e-5)
    assert "Millman Formülü — V_AB" in section_titles(res)
    assert "V_AB = V₃ − V₀ = 2 V" in all_text(res)


def test_millman_non_ground_main_nodes_when_gnd_is_internal_to_branch(solve):
    """
    GND (Düğüm 0) iki elemanlı bir ara düğüm iken ana düğümlerin Düğüm 1 ve Düğüm 2 olması:
    V1 1 0 DC 12, R1 0 2 6, R2 1 2 3, I1 2 1 DC 2.
    Analitik hesap:
      Ana düğümler: A = Düğüm 1, B = Düğüm 2.
      Kol 1 (2 → 0 → 1): R1 = 6 Ω, V1 = 12 V (+ ucu 1'de) ⇒ E1 = 12 V, R1 = 6 Ω.
      Kol 2 (2 → 1): R2 = 3 Ω, E2 = 0 V.
      Kol 3 (2 → 1): I1 = 2 A (2 → 1 yönünde).
      V_12 = V1 - V2 = (12/6 + 0/3 + 2) / (1/6 + 1/3) = 4 / 0.5 = 8 V.
      Düğüm 0 referans (V0 = 0) ve V1 - V0 = 12 V olduğundan:
      V1 = 12 V,  V2 = V1 - 8 = 4 V.
    """
    net = f"V1 1 0 DC 12\nR1 0 2 6\nR2 1 2 3\nI1 2 1 DC 2\n{GND}"
    res, _, err = solve(net, analysis_type="MILLMAN")
    assert err == []
    assert res.node_voltages["1"].value == pytest.approx(12.0, rel=1e-5)
    assert res.node_voltages["2"].value == pytest.approx(4.0, rel=1e-5)
    assert "V_AB = V₁ − V₂ = 8 V" in all_text(res)


@pytest.mark.parametrize(
    "net,expected_reason_fragment",
    [
        # 1) Dirençsiz gerilim kaynağı kolu (V1 doğrudan ana düğümler arasında)
        (f"V1 1 0 DC 12\nR1 1 0 6\nR2 1 0 3\n{GND}", "direnci yok"),
        # 2) Köprü devresi (> 2 ana düğüm)
        (f"V1 1 0 DC 12\nR1 1 2 4\nR2 1 3 4\nR3 2 3 4\nR4 2 0 4\nR5 3 0 4\n{GND}", "ana düğüm"),
        # 3) Bağımlı kaynak içeren devre
        (f"V1 1 0 DC 12\nR1 1 2 4\nR2 2 0 4\nG1 2 0 V(R1) 0.1\n{GND}", "bağımlı"),
    ],
)
def test_millman_inapplicable_circuits_fallback_to_nodal(solve, net, expected_reason_fragment):
    """Uygulanamayan devrelerde Millman Türkçe gerekçe verip Düğüm Gerilimleri anlatımına döner."""
    res, _, err = solve(net, analysis_type="MILLMAN")
    assert err == []
    txt = all_text(res)
    assert "Millman teoremi uygulanamadı" in txt
    assert expected_reason_fragment in txt.lower()


# ═══════════════════════════════════════════════════════════════════════════
#  4. KAYNAK DÖNÜŞÜMÜ VE Δ–Y
# ═══════════════════════════════════════════════════════════════════════════

def test_source_transform_unbalanced_bridge_and_non_ground_terminals(solve):
    """
    Dengesiz köprü devresinde farklı terminal seçimleri ((3,0), (2,0) ve topraksız (1,2)):
    V1 4 0 DC 12, R0 4 1 3, R1 1 2 6, R2 2 3 6, R3 1 3 6, R4 2 0 4, R5 3 0 4.
    Analitik düğüm hesabı (açık devre):
      Düğüm 1, 2, 3 için simetri: R1=R3=6 ve R4=R5=4 olduğundan devre Düğüm 2 ve 3'e göre simetriktir!
      Bu yüzden açık devrede V2 = V3 ve R2 (2–3) üzerinden akım geçmez (I_R2 = 0).
      R1 ve R3 paralel (6 || 6 = 3 Ω), R4 ve R5 paralel (4 || 4 = 2 Ω).
      Toplam kol: R0 (3 Ω) + (R1||R3 = 3 Ω) + (R4||R5 = 2 Ω) = 8 Ω.
      I_toplam = 12 / 8 = 1.5 A  ⇒  V2 = V3 = 1.5 · 2 = 3.0 V,  V1 = 12 - 1.5 · 3 = 7.5 V!
      1) Terminaller (3, 0) ve (2, 0):
         Vth = 3.0 V.
         Rth (V1=0 ⇒ R0=3 Ω Düğüm 1–0 arasında):
         Δ(1,2,3) [6,6,6 Ω] → Y(Y1): her kol 2 Ω.
         Düğüm 1 kolu: R0 + 2 = 5 Ω; Düğüm 2 kolu: R4 + 2 = 6 Ω.
         5 || 6 = 30/11 Ω; seri 2 Ω (Y1–3) ile: 30/11 + 2 = 52/11 Ω.
         Paralel R5 (4 Ω) ile: Rth = (52/11 · 4) / (52/11 + 4) = 208 / 96 = 13 / 6 ≈ 2.166667 Ω.
      2) Topraksız diferansiyel port (1, 2) (basit merdiven devrede):
         V1 3 0 DC 12, R1 3 1 4, R2 1 0 4, R3 1 2 3, R4 2 0 6.
         V1 + R1 || R2 → Vth(1,0) = 6 V, Rth(1,0) = 2 Ω.
         Düğüm 1 ve 2 kolu: R3(3 Ω) + R4(6 Ω) toplam 9 Ω üzerinden I = 6 / (2 + 3 + 6) = 6/11 A.
         Vth(1,2) = V1 - V2 = I · R3 = (6/11) · 3 = 18/11 V.
         Rth(1,2) = R3 || (Rth(1,0) + R4) = 3 || (2 + 6) = 24 / 11 Ω.
    """
    net = f"V1 4 0 DC 12\nR0 4 1 3\nR1 1 2 6\nR2 2 3 6\nR3 1 3 6\nR4 2 0 4\nR5 3 0 4\n{GND}"

    for term in [("3", "0"), ("2", "0")]:
        res_t, _, err_t = solve(net, analysis_type="SOURCE_TRANSFORM", terminals=term)
        assert err_t == []
        assert as_complex(res_t.thevenin.vth).real == pytest.approx(3.0, rel=1e-5)
        assert as_complex(res_t.thevenin.zth).real == pytest.approx(13.0 / 6.0, rel=1e-5)
        assert "Kaynak Dönüşümü — Adım Adım" in section_titles(res_t)

    net_diff = f"V1 3 0 DC 12\nR1 3 1 4\nR2 1 0 4\nR3 1 2 3\nR4 2 0 6\n{GND}"
    res_12, _, err_12 = solve(net_diff, analysis_type="SOURCE_TRANSFORM", terminals=("1", "2"))
    assert err_12 == []
    assert as_complex(res_12.thevenin.vth).real == pytest.approx(18.0 / 11.0, rel=1e-5)
    assert as_complex(res_12.thevenin.zth).real == pytest.approx(24.0 / 11.0, rel=1e-5)
    assert "Kaynak Dönüşümü — Adım Adım" in section_titles(res_12)


def test_source_transform_y_to_delta_and_stuck_fallback(solve):
    """
    1) Y → Δ gerektiren üçgensiz devre (iki paralel yıldız: Düğüm 4 ve Düğüm 5):
       Düğüm 4 yıldızı: R1(1–4)=3 Ω, R2(2–4)=3 Ω, R3(0–4)=3 Ω.
       Düğüm 5 yıldızı: R4(1–5)=3 Ω, R5(2–5)=3 Ω, R6(0–5)=3 Ω.
       Kaynak kolu: V1(3–0)=18 V, R0(3–1)=4.5 Ω.
       Üçgen hiç yoktur (iki parçalı graf); Y(4) → Δ(0,1,2) ve Y(5) → Δ(0,1,2) dönüşümüyle
       her iki yıldız 9 Ω'luk üçgenlere dönüşür; paralel birleşince Δ(0,1,2) kenarları 4.5 Ω olur!
       Ardından R0=4.5 Ω ile seri/paralel kaynak dönüşümleriyle:
       I_a = 18 / 4.5 = 4 A, R0 || R_10 = 4.5 || 4.5 = 2.25 Ω → E = 9 V + 2.25 Ω;
       R_12 = 4.5 Ω ile seri → 6.75 Ω; R_20 = 4.5 Ω ile paralel:
       Vth(2,0) = 9 · 4.5 / (6.75 + 4.5) = 3.6 V,
       Rth(2,0) = (6.75 · 4.5) / (6.75 + 4.5) = 2.7 Ω.
    2) Kaynağı köprü içinde sıkışmış devre → tıkanıp Thevenin anlatımına döner.
    """
    net_yd = (
        f"V1 3 0 DC 18\nR0 3 1 4.5\n"
        f"R1 1 4 3\nR2 2 4 3\nR3 0 4 3\n"
        f"R4 1 5 3\nR5 2 5 3\nR6 0 5 3\n{GND}"
    )
    res_yd, _, err_yd = solve(net_yd, analysis_type="SOURCE_TRANSFORM", terminals=("2", "0"))
    assert err_yd == []
    assert as_complex(res_yd.thevenin.vth).real == pytest.approx(3.6, rel=1e-5)
    assert as_complex(res_yd.thevenin.zth).real == pytest.approx(2.7, rel=1e-5)
    assert "yıldız (Y) bağlı (ortak Düğüm 4) → üçgene (Δ" in all_text(res_yd)

    # Tıkanan devre: gerilim kaynağı köprü kolunun içinde ve seri direnci yok
    net_stuck = f"V1 1 2 DC 10\nR1 1 0 4\nR2 2 0 4\nR3 1 3 4\nR4 2 3 4\n{GND}"
    res_st, _, err_st = solve(net_stuck, analysis_type="SOURCE_TRANSFORM", terminals=("3", "0"))
    assert err_st == []
    assert "kaynak dönüşümü yöntemi uygulanamadı" in all_text(res_st).lower()


@pytest.mark.xfail(
    strict=True,
    reason="Bilinen sınır (sonuç doğru, Thevenin anlatımına düşer). Üçgen SEÇİMİ sorun değil: "
           "_step_delta_y'nin göreceği tek saf dirençli üçgen (10,20,30)'dur; (10,20,100) üçgeninin "
           "20–100 kolunda paralel bir akım kaynağı (Ib) kalır ve ikisi de kaynaklı bir köprüye "
           "çıkar. Kaynaklı köprüyü indirgemek (akım kaynağı kaydırma) bu anlatımda yok.",
)
def test_source_transform_helpful_triangle_selection_bug(solve):
    """
    BULGU-3:
    V1 5 0 DC 12, R0 5 10 6, R1 10 20 6, R2 20 30 6, R3 10 30 6,
    R4 10 100 6, R5 400 100 6, R6 0 100 6, I2 400 20 DC 1, R7 20 400 6.
    I2 || R7 → 6 V + 6 Ω dönüşümünden sonra R5(6 Ω) + R7(6 Ω) = 12 Ω olur ve
    devrede iki üçgen bulunur: (10, 20, 30) ve (10, 20, 100).
    (10, 20, 100) üçgeni Düğüm 100 (derece 3) sayesinde seri kol açar (topology.py Rth = 7,2 Ω bulur);
    ancak source_transform._step_delta_y düğüm sırasına göre ('30' < '100') önce (10, 20, 30) üçgenini
    yıldıza çevirip tıkanır.
    """
    net = (
        f"V1 5 0 DC 12\nR0 5 10 6\nR1 10 20 6\nR2 20 30 6\nR3 10 30 6\n"
        f"R4 10 100 6\nR5 400 100 6\nR6 0 100 6\nI2 400 20 DC 1\nR7 20 400 6\n{GND}"
    )
    res, _, err = solve(net, analysis_type="SOURCE_TRANSFORM", terminals=("30", "0"))
    assert err == []
    assert as_complex(res.thevenin.zth).real == pytest.approx(7.2, rel=1e-5)
    assert "Kaynak Dönüşümü — Adım Adım" in section_titles(res)
