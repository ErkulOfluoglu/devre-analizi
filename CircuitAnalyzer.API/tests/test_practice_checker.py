"""
CircuitAnalyzer API — Alıştırma Modu Cevap Değerlendirici (Checker) Testleri

Test edilen modül:
- practice/checker.py (check_answer, check_answers)
- main.py (POST /practice/check endpoint'i)
"""

import cmath
import math
from typing import Optional
import pytest

from models.response import PracticeAlternative, PracticeQuestion
from practice.checker import check_answer
from solver.circuit_solver import make_complex_number


def make_q(
    expected: complex,
    unit: str = "V",
    is_ac: bool = False,
    scale: Optional[float] = None,
    alternatives=(),
    id: str = "Q1",
    label: str = "V1",
    description: str = "Test sorusu",
    group: str = "main",
    hint: str = "KCL veya düğüm gerilimi yöntemini kullanın.",
    sign_hint: str = "İşaret ters. Referans polariteyi kontrol edin.",
) -> PracticeQuestion:
    """Test için PracticeQuestion nesnesi oluşturan yardımcı fonksiyon."""
    if scale is None:
        scale = abs(expected) if abs(expected) > 1e-12 else 1.0

    alts = []
    for a in alternatives:
        if isinstance(a, PracticeAlternative):
            alts.append(a)
        else:
            val, msg = a
            alts.append(PracticeAlternative(value=make_complex_number(val), message=msg))

    return PracticeQuestion(
        id=id,
        label=label,
        description=description,
        unit=unit,
        group=group,
        is_ac=is_ac,
        expected=make_complex_number(expected),
        scale=scale,
        hint=hint,
        sign_hint=sign_hint,
        alternatives=alts,
    )


def test_check_dc_voltage():
    """DC 8 V beklenen değer için doğru, yakın, kısmi, yanlış, boş ve geçersiz durumlar."""
    q = make_q(expected=8.0, unit="V")

    # "8" doğru
    v = check_answer(q, "8")
    assert v.status == "correct"

    # "8 V" doğru
    v = check_answer(q, "8 V")
    assert v.status == "correct"

    # "8.05" doğru (< %1)
    v = check_answer(q, "8.05")
    assert v.status == "correct"

    # "7.9" çok yakın (%1.25) ve mesaj % içerir
    v = check_answer(q, "7.9")
    assert v.status == "close"
    assert "%" in v.message

    # "-8" yanlış ve mesaj == question.sign_hint
    v = check_answer(q, "-8")
    assert v.status == "wrong"
    assert v.message == q.sign_hint

    # "8000" yanlış, mesaj "1.000 katı büyük" içerir
    v = check_answer(q, "8000")
    assert v.status == "wrong"
    assert "1.000 katı büyük" in v.message

    # "8m" yanlış, "1.000 katı küçük" içerir
    v = check_answer(q, "8m")
    assert v.status == "wrong"
    assert "1.000 katı küçük" in v.message

    # "8 A" kısmi (birim yanlış), mesaj "birim" içerir
    v = check_answer(q, "8 A")
    assert v.status == "partial"
    assert "birim" in v.message.lower()

    # "" boş
    v = check_answer(q, "")
    assert v.status == "empty"

    # "abc" geçersiz (invalid)
    v = check_answer(q, "abc")
    assert v.status == "invalid"

    # "5" yanlış ve mesaj question.hint içerir
    v = check_answer(q, "5")
    assert v.status == "wrong"
    assert q.hint in v.message


def test_check_dc_current():
    """DC 0.004 A (unit 'A') beklenen değer durumları."""
    q = make_q(expected=0.004, unit="A")

    # "4m" doğru
    v = check_answer(q, "4m")
    assert v.status == "correct"

    # "0.004" doğru
    v = check_answer(q, "0.004")
    assert v.status == "correct"

    # "4" yanlış (önek, "1.000 katı büyük")
    v = check_answer(q, "4")
    assert v.status == "wrong"
    assert "1.000 katı büyük" in v.message

    # "-4" yanlış ve mesaj hem "1.000" hem sign_hint metnini içerir
    v = check_answer(q, "-4")
    assert v.status == "wrong"
    assert "1.000" in v.message
    assert q.sign_hint in v.message

    # "4 µA" yanlış ("katı küçük")
    v = check_answer(q, "4 µA")
    assert v.status == "wrong"
    assert "katı küçük" in v.message


def test_check_zero_expected():
    """Beklenen ≈ 0 iken tam 0 cevabı doğru, 1 cevabı yanlış değerlendirilir."""
    q = make_q(expected=0.0, unit="V", scale=10.0)

    v0 = check_answer(q, "0")
    assert v0.status == "correct"

    v1 = check_answer(q, "1")
    assert v1.status == "wrong"


def test_check_zero_expected_small_tolerance():
    """Beklenen ≈ 0, scale=10 (V) iken 1e-3*scale mutlak toleransındaki (0.001) cevabın doğrulanması."""
    q = make_q(expected=0.0, unit="V", scale=10.0)
    v = check_answer(q, "0.001")
    assert v.status == "correct"


def test_check_ac_phasor():
    """AC 3.033∠-72.34° beklenen değer için fazör değerlendirme ve hata teşhisi."""
    exp = cmath.rect(3.033, math.radians(-72.34))
    q = make_q(expected=exp, unit="V", is_ac=True, scale=3.033)

    # "3.033∠-72.34" doğru
    v = check_answer(q, "3.033∠-72.34")
    assert v.status == "correct"

    # "0.92-j2.89" doğru
    v = check_answer(q, "0.92-j2.89")
    assert v.status == "correct"

    # "3.03∠-72.3" doğru
    v = check_answer(q, "3.03∠-72.3")
    assert v.status == "correct"

    # "3.033" kısmi (yalnızca büyüklük, mesaj "açı" içerir)
    v = check_answer(q, "3.033")
    assert v.status == "partial"
    assert "açı" in v.message.lower()

    # "3.033∠72.34" yanlış, mesaj "işareti ters" içerir
    v = check_answer(q, "3.033∠72.34")
    assert v.status == "wrong"
    assert "işareti ters" in v.message.lower()

    # "3.033∠-1.2626" yanlış, mesaj "radyan" içerir
    v = check_answer(q, "3.033∠-1.2626")
    assert v.status == "wrong"
    assert "radyan" in v.message.lower()

    # "2.145∠-72.34" yanlış, mesaj "√2" içerir
    v = check_answer(q, "2.145∠-72.34")
    assert v.status == "wrong"
    assert "√2" in v.message

    # "19.06∠-72.34" yanlış, mesaj "2π" içerir
    v = check_answer(q, "19.06∠-72.34")
    assert v.status == "wrong"
    assert "2π" in v.message

    # "3.033∠17.66" yanlış, mesaj "90°" içerir
    v = check_answer(q, "3.033∠17.66")
    assert v.status == "wrong"
    assert "90°" in v.message

    # "-3.033∠-72.34" yanlış, mesaj == sign_hint
    v = check_answer(q, "-3.033∠-72.34")
    assert v.status == "wrong"
    assert v.message == q.sign_hint

    # "3.1∠-72" çok yakın
    v = check_answer(q, "3.1∠-72")
    assert v.status == "close"


def test_check_alternatives():
    """Özel hata alternatifleri: beklenen 4.8 iken 7.2 girildiğinde alternatif mesajı döner."""
    alt_msg = "Bu toplam değer. Burada yalnız V1 aktifken oluşan katkı soruluyor."
    q = make_q(expected=4.8, unit="V", alternatives=[(7.2, alt_msg)])

    v = check_answer(q, "7.2")
    assert v.status == "wrong"
    assert v.message == alt_msg


def test_check_understood_as():
    """understood_as alanının formatlanmış gösterimi sağlaması."""
    # "4 mA" cevabı -> understood_as == "4 mA"
    q_a = make_q(expected=0.004, unit="A")
    v_a = check_answer(q_a, "4 mA")
    assert v_a.understood_as == "4 mA"

    # DC "8" cevabı -> understood_as == "8 V"
    q_v = make_q(expected=8.0, unit="V")
    v_v = check_answer(q_v, "8")
    assert v_v.understood_as == "8 V"


def test_check_watt_unit():
    """Aktif güç sorusunda VA birimi girildiğinde kısmi doğru verilmesi ve watt uyarısı yapılması."""
    q_w = make_q(expected=3.0, unit="W")
    v = check_answer(q_w, "3 VA")
    assert v.status == "partial"
    assert "watt" in v.message.lower()


def test_check_api_endpoint(client):
    """POST /practice/check endpoint'i üzerinden değerlendirme testi."""
    q = make_q(expected=8.0, unit="V", id="Q_API")
    resp = client.post(
        "/practice/check",
        json={
            "items": [
                {"question": q.model_dump(mode="json"), "answer": "8"},
                {"question": q.model_dump(mode="json"), "answer": "-8"},
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["correct_count"] == 1
    assert data["total"] == 2
    verdicts = data["verdicts"]
    assert len(verdicts) == 2
    assert verdicts[0]["question_id"] == "Q_API"
    assert verdicts[0]["status"] == "correct"
    assert verdicts[1]["question_id"] == "Q_API"
    assert verdicts[1]["status"] == "wrong"
