"""
CircuitAnalyzer API — Alıştırma Modu Cevap Ayrıştırıcı (Answer Parser) Testleri

Test edilen modül:
- practice/answer_parser.py (parse_answer, ParsedAnswer, AnswerParseError)
"""

import cmath
import math
import pytest

from practice.answer_parser import AnswerParseError, parse_answer


@pytest.mark.parametrize(
    "text, expected_val, expected_unit",
    [
        ("4", 4.0, None),
        ("0.004", 0.004, None),
        ("4e-3", 0.004, None),
        ("4·10^-3", 0.004, None),
        ("4x10^(-3)", 0.004, None),
        ("4*10^-3", 0.004, None),
        ("2,5", 2.5, None),
        ("-8", -8.0, None),
        ("8/3", 8.0 / 3.0, None),
        ("8/3 mA", (8.0 / 3.0) * 1e-3, "A"),
    ],
)
def test_parse_real(text, expected_val, expected_unit):
    """Gerçel sayıların (tam, ondalıklı, üslü, kesirli ve virgüllü) ayrıştırılması."""
    ans = parse_answer(text)
    assert ans.form == "real"
    assert ans.value.real == pytest.approx(expected_val, rel=1e-9)
    assert ans.value.imag == pytest.approx(0.0, abs=1e-12)
    assert ans.unit == expected_unit


@pytest.mark.parametrize(
    "text, expected_val, expected_unit",
    [
        ("4m", 4e-3, None),
        ("4 mA", 4e-3, "A"),
        ("4 M", 4e6, None),
        ("2.5kΩ", 2500.0, "Ω"),
        ("4.7 kohm", 4700.0, "Ω"),
        ("10 µA", 1e-5, "A"),   # U+00B5 mikro işareti
        ("10 μA", 1e-5, "A"),   # U+03BC yunan mu harfi
        ("10uA", 1e-5, "A"),
        ("3 n", 3e-9, None),
        ("2 kvar", 2000.0, "VAR"),
        ("3 VA", 3.0, "VA"),
        ("12 W", 12.0, "W"),
    ],
)
def test_parse_prefixes(text, expected_val, expected_unit):
    """Birim önekleri (m, M, k, u/µ/μ, n) ve birimlerin ayrıştırılması."""
    ans = parse_answer(text)
    assert ans.form == "real"
    assert ans.value.real == pytest.approx(expected_val, rel=1e-9)
    assert ans.value.imag == pytest.approx(0.0, abs=1e-12)
    assert ans.unit == expected_unit


@pytest.mark.parametrize(
    "text, expected_val, expected_unit",
    [
        ("1k5", 1500.0, None),
        ("4m7", 4.7e-3, None),
        ("1k5Ω", 1500.0, "Ω"),
    ],
)
def test_parse_rkm_notation(text, expected_val, expected_unit):
    """RKM (1k5, 4m7) şema gösteriminin ayrıştırılması."""
    ans = parse_answer(text)
    assert ans.form == "real"
    assert ans.value.real == pytest.approx(expected_val, rel=1e-9)
    assert ans.value.imag == pytest.approx(0.0, abs=1e-12)
    assert ans.unit == expected_unit


@pytest.mark.parametrize(
    "text, expected_mag, expected_phase, expected_unit, expected_ang_input, expected_ang_unit",
    [
        ("3.033∠-72.34", 3.033, -72.34, None, -72.34, "deg"),
        ("3.033∠−72.34° V", 3.033, -72.34, "V", -72.34, "deg"),  # U+2212 eksi işareti
        ("3.033<-72.34", 3.033, -72.34, None, -72.34, "deg"),
        ("3.033/_-72.34", 3.033, -72.34, None, -72.34, "deg"),
        ("95.29 mA ∠ 17.66°", 0.09529, 17.66, "A", 17.66, "deg"),
        ("95.29∠17.66° mA", 0.09529, 17.66, "A", 17.66, "deg"),
        ("3∠1.26rad", 3.0, 1.26, None, 1.26, "rad"),
    ],
)
def test_parse_polar(text, expected_mag, expected_phase, expected_unit, expected_ang_input, expected_ang_unit):
    """Kutupsal fazör yazımlarının (derece, radyan, farklı semboller) ayrıştırılması."""
    ans = parse_answer(text)
    assert ans.form == "polar"
    assert abs(ans.value) == pytest.approx(expected_mag, rel=1e-9)
    if expected_ang_unit == "deg":
        actual_phase = math.degrees(cmath.phase(ans.value))
        assert actual_phase == pytest.approx(expected_phase, rel=1e-9)
    else:
        actual_phase = cmath.phase(ans.value)
        assert actual_phase == pytest.approx(expected_phase, rel=1e-9)
    assert ans.unit == expected_unit
    assert ans.angle_input == pytest.approx(expected_ang_input, rel=1e-9)
    assert ans.angle_unit == expected_ang_unit


@pytest.mark.parametrize(
    "text, expected_complex, expected_unit",
    [
        ("0.92-2.89j", complex(0.92, -2.89), None),
        ("0.92 − j2.89 V", complex(0.92, -2.89), "V"),
        ("-j31.83", complex(0.0, -31.83), None),
        ("5+5i", complex(5.0, 5.0), None),
        ("j", complex(0.0, 1.0), None),
        ("(0.92 - j2.89) mA", complex(0.92e-3, -2.89e-3), "A"),
        ("3+4jmA", complex(3e-3, 4e-3), "A"),
        ("2e-3+j1e-3", complex(2e-3, 1e-3), None),
    ],
)
def test_parse_rect(text, expected_complex, expected_unit):
    """Dikdörtgensel karmaşık sayıların (j/i, önek, parantez) ayrıştırılması."""
    ans = parse_answer(text)
    assert ans.form == "rect"
    assert ans.value.real == pytest.approx(expected_complex.real, rel=1e-9, abs=1e-12)
    assert ans.value.imag == pytest.approx(expected_complex.imag, rel=1e-9, abs=1e-12)
    assert ans.unit == expected_unit


@pytest.mark.parametrize(
    "bad_text",
    [
        "",
        "   ",
        "abc",
        "4 xyz",
        "∠30",
        "3∠",
        "3+",
        "4/0",
        "(0.92-j2.89",
    ],
)
def test_parse_errors(bad_text):
    """Geçersiz veya eksik yazımların AnswerParseError fırlatması ve Türkçe mesaj içermesi."""
    with pytest.raises(AnswerParseError) as exc_info:
        parse_answer(bad_text)
    msg = str(exc_info.value).strip()
    assert len(msg) > 0


def test_comma_and_dot_decimal_equal():
    """Answer parser accepts '7,5' and '7.5' (as well as 4,7k, 2,2 mA, 3,03∠-72,3) equally."""
    p_dot = parse_answer("7.5")
    p_comma = parse_answer("7,5")
    assert p_dot.value == p_comma.value == pytest.approx(7.5)

    p_k_dot = parse_answer("4.7k")
    p_k_comma = parse_answer("4,7k")
    assert p_k_dot.value == p_k_comma.value == pytest.approx(4700.0)

    p_ma_dot = parse_answer("2.2 mA")
    p_ma_comma = parse_answer("2,2 mA")
    assert p_ma_dot.value == p_ma_comma.value == pytest.approx(2.2e-3)
    assert p_ma_dot.unit == p_ma_comma.unit == "A"

    p_pol_dot = parse_answer("3.03∠-72.3")
    p_pol_comma = parse_answer("3,03∠-72,3")
    assert abs(p_pol_dot.value) == pytest.approx(abs(p_pol_comma.value), rel=1e-9)
    assert p_pol_dot.angle_input == pytest.approx(p_pol_comma.angle_input, rel=1e-9)
