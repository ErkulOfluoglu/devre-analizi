"""
CircuitAnalyzer API — Anlatım Biçimlendirme Birim Testleri

Test edilen modül: explainer/formatting.py
- num: anlamlı basamak, bilimsel gösterim yok, Unicode eksi
- eng: mühendislik notasyonu, birim ekleri (k, m, µ, ...), sınır yuvarlama
- rect: karmaşık sayılar (dikdörtgensel form)
- polar: kutupsal gösterim (açı, büyüklük, ölçekleme)
- paren: parantezleme kuralları
- node_v: düğüm indisleri (alt simge)
- value: DC (eng) ve AC (kutupsal + dikdörtgensel)
"""

import cmath
import math

import pytest

from explainer.formatting import (
    MINUS,
    eng,
    is_real,
    node_v,
    num,
    paren,
    polar,
    rect,
    sub,
    value,
)


# ═══════════════════════════════════════════════════════
#  NUM
# ═══════════════════════════════════════════════════════

def test_num_four_significant_digits():
    assert num(12.3456) == "12,35"
    assert num(1.234) == "1,234"
    assert num(1234.0) == "1234"
    # 4 anlamlı basamak, bilimsel gösterim yok, yarımda yukarı yuvarlama
    assert num(12345.0) == "12350"
    assert num(19774.648293) == "19770"
    assert num(-46704.23) == "−46700"


def test_num_zero_and_near_zero():
    assert num(0) == "0"
    assert num(0.0) == "0"
    assert num(1e-16) == "0"
    assert num(-1e-16) == "0"


def test_num_uses_comma():
    assert num(6.087) == "6,087"
    assert num(0.4167) == "0,4167"
    assert num(1.909) == "1,909"
    assert num(7.5) == "7,5"


def test_num_unicode_minus():
    res = num(-5)
    assert res == f"{MINUS}5"
    assert "-" not in res
    assert num(-0.005) == f"{MINUS}0,005"


def test_num_no_scientific_exponent():
    # Çok küçük ve çok büyük sayılarda 'e' gösterilmemeli
    small = num(1e-5)
    assert "e" not in small and "E" not in small
    assert small == "0,00001"

    large = num(1e7)
    assert "e" not in large and "E" not in large
    assert large == "10000000"


# ═══════════════════════════════════════════════════════
#  ENG (Mühendislik Notasyonu)
# ═══════════════════════════════════════════════════════

def test_eng_standard_values():
    assert eng(0.004, "A") == "4 mA"
    assert eng(666.666, "Ω") == "666,7 Ω"
    assert eng(0, "V") == "0 V"
    assert eng(0.0, "V") == "0 V"


def test_eng_prefix_threshold_rounding():
    # 0.9995 eşiği: 999.96 m yerine 1 A yazılır
    assert eng(0.99996, "A") == "1 A"


def test_eng_negative_values():
    res = eng(-0.004, "A")
    assert res == f"{MINUS}4 mA"
    assert "-" not in res
    assert eng(-666.666, "Ω") == f"{MINUS}666,7 Ω"


def test_eng_various_prefixes():
    assert eng(1.5e6, "Ω") == "1,5 MΩ"
    assert eng(2.2e3, "Ω") == "2,2 kΩ"
    assert eng(100e-6, "F") == "100 µF"
    assert eng(47e-9, "F") == "47 nF"
    assert eng(10e-12, "F") == "10 pF"


def test_eng_invalid_and_special_values():
    assert eng(None, "V") == "— V"
    assert eng(float("nan"), "V") == "— V"
    assert eng(float("inf"), "V") == "— V"
    assert eng(float("-inf"), "V") == "— V"


# ═══════════════════════════════════════════════════════
#  RECT (Dikdörtgensel Karmaşık Sayı)
# ═══════════════════════════════════════════════════════

def test_rect_complex_values():
    # 0.92 - 2.89j V → "0.92 − j2.89 V"
    z = complex(0.92, -2.89)
    assert rect(z, "V") == f"0,92 {MINUS} j2,89 V"

    # Pozitif sanal kısım
    z_pos = complex(50, 30)
    assert rect(z_pos, "Ω") == "50 + j30 Ω"


def test_rect_purely_imaginary():
    assert rect(-31.83j) == f"{MINUS}j31,83"
    assert rect(-31.83j, "Ω") == f"{MINUS}j31,83 Ω"
    assert rect(31.83j, "Ω") == "j31,83 Ω"


def test_rect_real_numbers():
    assert rect(12, "V") == "12 V"
    assert rect(-12, "V") == f"{MINUS}12 V"
    assert rect(0, "V") == "0 V"


def test_is_real_helper():
    assert is_real(12)
    assert is_real(12 + 0j)
    assert is_real(12 + 1e-14j)
    assert not is_real(12 + 1j)


# ═══════════════════════════════════════════════════════
#  POLAR (Kutupsal Karmaşık Sayı)
# ═══════════════════════════════════════════════════════

def test_polar_scaled_milliamperes():
    # 95.29∠17.66° mA beklenen değer:
    # mag = 0.09529, phase = 17.66°
    z = cmath.rect(0.09529, math.radians(17.66))
    assert pytest.approx(z.real, abs=1e-4) == 0.0907
    assert pytest.approx(z.imag, abs=1e-4) == 0.0289
    formatted = polar(z, "A", scaled=True)
    assert formatted == "95,29∠17,66° mA"


def test_polar_negative_phase():
    z = complex(0.92, -2.89)
    res = polar(z, "V", scaled=True)
    assert res == f"3,033∠{MINUS}72,34° V"


def test_polar_unscaled():
    z = complex(3, 4)
    res = polar(z, scaled=False)
    assert res == "5∠53,13°"
    res_unit = polar(z, "V", scaled=False)
    assert res_unit == "5∠53,13° V"


def test_polar_zero():
    assert polar(0, "V") == "0 V"
    assert polar(0j, "A") == "0 A"


# ═══════════════════════════════════════════════════════
#  PAREN (Parantezleme)
# ═══════════════════════════════════════════════════════

def test_paren_negative_and_sum_expressions():
    assert paren(f"{MINUS}j31,83 Ω") == f"({MINUS}j31,83 Ω)"
    assert paren("50 + j30 Ω") == "(50 + j30 Ω)"
    assert paren(f"0,92 {MINUS} j2,89 V") == f"(0,92 {MINUS} j2,89 V)"


def test_paren_plain_expressions():
    assert paren("12 V") == "12 V"
    assert paren("1000") == "1000"
    assert paren("V₂") == "V₂"


# ═══════════════════════════════════════════════════════
#  NODE_V & SUB
# ═══════════════════════════════════════════════════════

def test_node_v_subscripts():
    assert node_v("2") == "V₂"
    assert node_v("12") == "V₁₂"
    assert node_v("0") == "V₀"
    assert node_v("out") == "V_out"


def test_sub_digits():
    assert sub("0123456789") == "₀₁₂₃₄₅₆₇₈₉"
    assert sub("12") == "₁₂"


# ═══════════════════════════════════════════════════════
#  VALUE (DC vs AC Gösterim)
# ═══════════════════════════════════════════════════════

def test_value_dc():
    assert value(8, "V", is_dc=True) == "8 V"
    assert value(0.004, "A", is_dc=True) == "4 mA"
    assert value(-0.004, "A", is_dc=True) == f"{MINUS}4 mA"


def test_value_ac():
    z = complex(0.92, -2.89)
    val_str = value(z, "V", is_dc=False)
    expected_polar = f"3,033∠{MINUS}72,34° V"
    expected_rect = f"0,92 {MINUS} j2,89 V"
    assert val_str == f"{expected_polar}  (= {expected_rect})"
