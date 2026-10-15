"""
CircuitAnalyzer API — LLM Sayı Bulma ve Doğrulama Testleri

Test edilen modül:
- llm/numbers.py (find_numbers, KnownValues, known_from, check_answer_numbers, REDACTED)
"""

import cmath
import math
import pytest

from llm.numbers import (
    REDACTED,
    KnownValues,
    check_answer_numbers,
    find_numbers,
    known_from,
)


def test_find_numbers_values_and_units():
    """Farklı biçimlerdeki sayıların, birimlerin ve öneklerin doğru ayrıştırılması."""
    text = (
        "Gerilim 8 V, akım 4 mA, direnç 1 kΩ, sığa 100 µF, "
        "açısal frekans 314.2 rad/s, frekans 50 Hz, faz −72.34°, "
        "ondalık virgüllü 3,5 V, karmaşık 0.92 − j2.89 V, "
        "sanal 2.89j ve bilimsel 1e-3 A."
    )
    numbers = find_numbers(text)
    lookup = {n.text.strip(): n for n in numbers}

    # "8 V" → value 8, unit "V"
    assert "8 V" in lookup
    assert lookup["8 V"].raw == 8.0
    assert lookup["8 V"].value == 8.0
    assert lookup["8 V"].unit == "V"

    # "4 mA" → raw 4, value 0.004, unit "A"
    assert "4 mA" in lookup
    assert lookup["4 mA"].raw == 4.0
    assert lookup["4 mA"].value == pytest.approx(0.004)
    assert lookup["4 mA"].unit == "A"

    # "1 kΩ" → 1000 "Ω"
    assert "1 kΩ" in lookup
    assert lookup["1 kΩ"].raw == 1.0
    assert lookup["1 kΩ"].value == 1000.0
    assert lookup["1 kΩ"].unit == "Ω"

    # "100 µF" → 1e-4 "F"
    assert "100 µF" in lookup
    assert lookup["100 µF"].raw == 100.0
    assert lookup["100 µF"].value == pytest.approx(1e-4)
    assert lookup["100 µF"].unit == "F"

    # "314.2 rad/s" → unit "rad/s"
    assert "314.2 rad/s" in lookup
    assert lookup["314.2 rad/s"].raw == 314.2
    assert lookup["314.2 rad/s"].value == 314.2
    assert lookup["314.2 rad/s"].unit == "rad/s"

    # "50 Hz"
    assert "50 Hz" in lookup
    assert lookup["50 Hz"].raw == 50.0
    assert lookup["50 Hz"].value == 50.0
    assert lookup["50 Hz"].unit == "Hz"

    # "−72.34°" (Unicode eksi) → -72.34 unit "°"
    assert "−72.34°" in lookup
    assert lookup["−72.34°"].raw == pytest.approx(-72.34)
    assert lookup["−72.34°"].value == pytest.approx(-72.34)
    assert lookup["−72.34°"].unit == "°"

    # "3,5 V" → 3.5 (ondalık virgül)
    assert "3,5 V" in lookup
    assert lookup["3,5 V"].raw == 3.5
    assert lookup["3,5 V"].value == 3.5
    assert lookup["3,5 V"].unit == "V"

    # "0.92 − j2.89 V" finds 0.92 and -2.89
    assert "0.92" in lookup
    assert lookup["0.92"].value == pytest.approx(0.92)
    # Sanal kısım eksi işaretli ve V birimli
    found_neg = [n for n in numbers if "2.89" in n.text and n.raw < 0]
    assert len(found_neg) == 1
    assert found_neg[0].raw == pytest.approx(-2.89)
    assert found_neg[0].unit == "V"

    # "2.89j" → 2.89
    assert "2.89j" in lookup
    assert lookup["2.89j"].raw == pytest.approx(2.89)

    # "1e-3 A" → 0.001
    assert "1e-3 A" in lookup
    assert lookup["1e-3 A"].value == pytest.approx(0.001)
    assert lookup["1e-3 A"].unit == "A"


def test_find_numbers_ignores_circuit_identifiers():
    """Eleman adlarındaki rakamların (R1, V2, I_R1, VAC1, V₂) sayı olarak bulunmaması."""
    assert find_numbers("R1") == []
    assert find_numbers("V2") == []
    assert find_numbers("I_R1") == []
    assert find_numbers("VAC1") == []
    assert find_numbers("V₂") == []

    # Cümle içinde geçtiklerinde de rakamlar ayrıştırılmamalı
    sentence = "Devrede R1 direnci, V2 gerilim kaynağı, I_R1 akımı, VAC1 kaynağı ve V₂ düğümü bulunmaktadır."
    assert find_numbers(sentence) == []


def test_check_answer_numbers_verification_and_counting():
    """Bilinen değerlerin doğrulanması ve küçük sayma sayılarının denetim dışı bırakılması."""
    known = known_from(values=[8, 0.004, 1000, complex(0.92, -2.89)])
    answer = (
        "Düğüm gerilimi 8 V, akım 4 mA, faz açısı −72.34° ve uydurma değer 7.5 V. "
        "Devrede 2 düğüm vardır ve bu 1. adım olarak çözülmüştür."
    )

    cleaned, checks = check_answer_numbers(answer, known)
    status_by_text = {c.text: c.status for c in checks}

    # "8 V" verified
    assert status_by_text.get("8 V") == "verified"
    # "4 mA" verified
    assert status_by_text.get("4 mA") == "verified"
    # "−72.34°" verified (0.92 − j2.89 sayısının fazı)
    assert status_by_text.get("−72.34°") == "verified"
    # "7.5 V" unverified
    assert status_by_text.get("7.5 V") == "unverified"

    # "2 düğüm" ve "1. adım" sayma sayısı olduğundan denetim listesinde yer almaz
    check_texts = [c.text for c in checks]
    assert "2" not in check_texts
    assert "1" not in check_texts
    assert set(check_texts) == {"8 V", "4 mA", "−72.34°", "7.5 V"}
    assert len(checks) == 4


def test_check_answer_numbers_redaction_dc():
    """Alıştırma modunda yasaklı cevap değerinin ■■ ile gizlenmesi."""
    known = known_from([8])
    answer = "Cevap 8 V."
    cleaned, checks = check_answer_numbers(answer, known, forbidden=[8])

    assert cleaned == f"Cevap {REDACTED}."
    assert len(checks) == 1
    assert checks[0].text == "8 V"
    assert checks[0].status == "redacted"


def test_check_answer_numbers_given_value_not_redacted():
    """Devrede önceden verilen (given) değerlerin yasaklı listesinde olsa dahi gizlenmemesi."""
    given = known_from([12])
    known = known_from([8, 12])
    # 12 devrede verilen kaynak gerilimi, 8 ise bulunması istenen yanıt
    forbidden = [8, 12]
    answer = "Kaynak gerilimi 12 V olup düğüm gerilimi 8 V bulunur."

    cleaned, checks = check_answer_numbers(answer, known, forbidden=forbidden, given=given)

    # 12 V gizlenmemeli, 8 V gizlenmeli
    assert "12 V" in cleaned
    assert "8 V" not in cleaned
    assert REDACTED in cleaned

    status_map = {c.text: c.status for c in checks}
    assert status_map.get("12 V") == "verified"
    assert status_map.get("8 V") == "redacted"


def test_check_answer_numbers_redaction_ac_phasor():
    """AC fazör alıştırmasında hem genlik hem açının gizlenmesi."""
    z = cmath.rect(3.033, math.radians(-72.34))
    known = known_from([z])
    forbidden = [z]

    answer = "Hesaplanan fazör gerilimi 3.033∠−72.34° V olarak bulunur."
    cleaned, checks = check_answer_numbers(answer, known, forbidden=forbidden)

    # Hem 3.033 hem -72.34° gizlenmelidir
    assert "3.033" not in cleaned
    assert "72.34" not in cleaned
    assert cleaned.count(REDACTED) == 2

    assert len(checks) == 2
    assert all(c.status == "redacted" for c in checks)


def test_check_answer_numbers_tolerance():
    """Doğrulama toleransı: %1 farka kadar verified, %1 üstünde unverified."""
    known = known_from([8])

    # 8.05 vs known 8: fark |8.05 - 8| / 8 = 0.00625 (< %1) → verified
    _, checks_close = check_answer_numbers("Gerilim 8.05 V.", known)
    assert len(checks_close) == 1
    assert checks_close[0].status == "verified"

    # 8.2 vs known 8: fark |8.2 - 8| / 8 = 0.025 (> %1) → unverified
    _, checks_far = check_answer_numbers("Gerilim 8.2 V.", known)
    assert len(checks_far) == 1
    assert checks_far[0].status == "unverified"
