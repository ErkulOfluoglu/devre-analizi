"""
CircuitAnalyzer API — Öğrenci cevabını değerlendirme

Cevap doğru sonuçla karşılaştırılır; yanlışsa sık yapılan hatalar sırayla
denenir ve öğrenciye cevabı vermeden ne yanlış gitmiş olabileceği söylenir:

    işaret ters (akım yönü)          → oran ≈ −1
    birim öneki (mA ↔ A, kΩ ↔ Ω)     → oran ≈ 10^±3, 10^±6, 10^±9
    tepe / etkin değer karışması      → oran ≈ √2 (AC)
    ω yerine f                        → oran ≈ 2π (AC)
    açı radyan yazılmış               → yazılan açı ≈ doğru açının radyanı
    açının işareti ters (eşlenik)     → cevap ≈ doğru cevabın eşleniği
    soruya özel hatalar               → PracticeQuestion.alternatives

Toleranslar: ±%1 doğru, ±%5 "çok yakın" (ara sonuçların yuvarlanması).
"""

import cmath
import math
from typing import List, Optional

from explainer.formatting import eng, polar, rect
from models.response import AnswerVerdict, PracticeQuestion
from practice.answer_parser import AnswerParseError, EXAMPLES, ParsedAnswer, parse_answer

REL_OK = 0.01       # doğru
REL_CLOSE = 0.05    # çok yakın
REL_DIAG = 0.03     # hata teşhisinde oranların toleransı

_QUANTITY = {"V": "gerilim", "A": "akım", "Ω": "direnç/empedans", "W": "aktif güç", "s": "süre"}
_UNIT_NAME = {"V": "volt (V)", "A": "amper (A)", "Ω": "ohm (Ω)", "W": "watt (W)", "s": "saniye (s)"}
_PREFIX_EXAMPLE = {
    "A": "4 mA için “4m” ya da “4 mA”",
    "V": "50 mV için “50m” ya da “50 mV”",
    "Ω": "2.2 kΩ için “2.2k” ya da “2.2 kΩ”",
    "W": "3.6 mW için “3.6m” ya da “3.6 mW”",
    "s": "2 ms için “2m” ya da “2 ms”",
}


def _expected(q: PracticeQuestion) -> complex:
    return complex(q.expected.real, q.expected.imaginary)


def _floor(q: PracticeQuestion) -> float:
    """Beklenen ≈ 0 iken kabul edilecek mutlak hata."""
    return max(1e-3 * abs(q.scale), 1e-12)


def _rel_err(ans: complex, ref: complex, floor: float) -> float:
    """
    Göreli hata. Referans ≈ 0 ise (|ref| ≤ floor) mutlak hata floor'a göre
    ölçeklenir: |ans − ref| = floor ↔ REL_OK (doğru sınırı), 5·floor ↔ REL_CLOSE.
    """
    if abs(ref) <= floor:
        return REL_OK * abs(ans - ref) / floor
    return abs(ans - ref) / abs(ref)


def _near(x: float, target: float, rel: float = REL_DIAG) -> bool:
    return abs(x - target) <= rel * abs(target)


def _angle_diff(a_deg: float, b_deg: float) -> float:
    """İki açı arasındaki en küçük fark (derece, 0–180)."""
    d = (a_deg - b_deg + 180.0) % 360.0 - 180.0
    return abs(d)


def _understood(p: ParsedAnswer, unit: str, is_ac: bool) -> str:
    z = p.value
    shown_unit = p.unit or unit
    if p.form == "real" or (not is_ac and abs(z.imag) <= 1e-12 * max(abs(z), 1e-300)):
        return eng(z.real, shown_unit)
    if p.form == "rect":
        return rect(z, shown_unit)
    return polar(z, shown_unit)


def _unit_problem(p: ParsedAnswer, q: PracticeQuestion) -> Optional[str]:
    if p.unit is None or p.unit == q.unit:
        return None
    if q.unit == "W" and p.unit in ("VA", "VAR"):
        return (f"Birim olarak {p.unit} yazdınız; aktif güç P'nin birimi watt (W)'tır "
                "(VA görünür güç, VAR reaktif güç birimidir).")
    return (f"Birim olarak {p.unit} yazdınız; burada {_QUANTITY[q.unit]} soruluyor, "
            f"birimi {_UNIT_NAME[q.unit]}.")


def _verdict(q: PracticeQuestion, status: str, message: str,
             understood: Optional[str] = None) -> AnswerVerdict:
    return AnswerVerdict(question_id=q.id, status=status, message=message,
                         understood_as=understood)


def _diagnose(q: PracticeQuestion, p: ParsedAnswer, exp: complex) -> Optional[str]:
    """Yanlış cevabın olası nedeni; bulunamazsa None."""
    ans = p.value
    if abs(exp) <= _floor(q) or abs(ans) < 1e-300:
        return None
    r = ans / exp
    r_mag = abs(r)
    r_ang = math.degrees(cmath.phase(r))

    # İşaret ters (AC'de 180° kaymış)
    if abs(r + 1) <= REL_DIAG:
        return q.sign_hint

    # Birim öneki: 1000, 10⁶, 10⁹ kat
    for k in (3, 6, 9):
        for direction in (1, -1):
            if _near(r_mag, 10.0 ** (direction * k)):
                factor = f"{10 ** k:,}".replace(",", ".")
                bigger = "büyük" if direction > 0 else "küçük"
                msg = (f"Cevabınız doğru sonucun {factor} katı {bigger}. Birim önekini kontrol edin "
                       "(mA ile A, kΩ ile Ω arasında 1000 kat fark var). Değeri önekle bulduysanız "
                       f"öneki de yazın: {_PREFIX_EXAMPLE[q.unit]}.")
                if r.real < 0 and _angle_diff(r_ang, 180.0) < 2.0:
                    msg += " Ayrıca işaret de ters: " + q.sign_hint
                return msg

    if q.is_ac:
        same_phase = _angle_diff(r_ang, 0.0) < 2.0
        if same_phase and (_near(r_mag, math.sqrt(2)) or _near(r_mag, 1 / math.sqrt(2))):
            return ("Büyüklük √2 kat farklı: tepe değer ile etkin (RMS) değer karışmış olabilir. "
                    "Bu uygulamada fazörler tepe değerdir (Vm); etkin değer Vm/√2'dir.")
        if same_phase and (_near(r_mag, 2 * math.pi) or _near(r_mag, 1 / (2 * math.pi))):
            return ("Büyüklük 2π kat farklı: reaktansta ω = 2πf kullanılmalı; f'yi doğrudan "
                    "kullanmış olabilirsiniz (X_L = ωL, X_C = 1/(ωC)).")
        if _near(r_mag, 1.0):
            exp_deg = math.degrees(cmath.phase(exp))
            if (p.form == "polar" and p.angle_unit == "deg" and p.angle_input is not None
                    and abs(p.angle_input - math.radians(exp_deg)) <= max(0.02, 0.02 * abs(math.radians(exp_deg)))
                    and abs(exp_deg) > 3.0):
                return ("Büyüklük doğru ama açıyı radyan olarak yazmışsınız; açıyı derece "
                        "yazın (π rad = 180°).")
            if _rel_err(ans, exp.conjugate(), _floor(q)) <= REL_DIAG:
                return ("Büyüklük doğru ama açının işareti ters. Empedans işaretlerini kontrol "
                        "edin: Z_L = +jωL, Z_C = −j/(ωC). Bölmede açılar çıkarılır, çarpmada toplanır.")
            if _angle_diff(r_ang, 90.0) < 2.0 or _angle_diff(r_ang, -90.0) < 2.0:
                return ("Büyüklük doğru ama açı 90° kaymış: bir j çarpanı eksik ya da fazla "
                        "olabilir (Z_L = jωL, Z_C = −j/(ωC)).")
            return ("Büyüklük doğru, açı yanlış. Fazör işlemlerinde açıları kontrol edin: "
                    "bölmede açılar çıkarılır, çarpmada toplanır.")
    return None


def check_answer(q: PracticeQuestion, answer: str) -> AnswerVerdict:
    """Tek bir cevabı değerlendirir."""
    if not (answer or "").strip():
        return _verdict(q, "empty", "Cevap girilmedi.")
    try:
        p = parse_answer(answer)
    except AnswerParseError as e:
        return _verdict(q, "invalid", str(e))

    exp = _expected(q)
    ans = p.value
    floor = _floor(q)
    understood = _understood(p, q.unit, q.is_ac)
    unit_msg = _unit_problem(p, q)
    err = _rel_err(ans, exp, floor)

    if err <= REL_OK:
        if unit_msg:
            return _verdict(q, "partial", "Sayı doğru ama birim yanlış. " + unit_msg, understood)
        return _verdict(q, "correct", "Doğru! ✓", understood)

    # AC sorusunda yalnız büyüklük yazılmışsa
    if q.is_ac and p.form == "real" and abs(abs(ans) - abs(exp)) <= REL_OK * max(abs(exp), floor):
        return _verdict(q, "partial",
                        "Büyüklük doğru. AC'de cevabı fazör olarak açısıyla birlikte yazın "
                        "(ör. 5∠30 ya da 4.33+j2.5).", understood)

    if err <= REL_CLOSE:
        pct = f"{100 * err:.1f}".replace(".", ",")
        msg = (f"Çok yakın! Fark yaklaşık %{pct}. Ara sonuçları erken yuvarlamış olabilirsiniz; "
               "hesapta en az 4 anlamlı basamak kullanın.")
        if unit_msg:
            msg += " " + unit_msg
        return _verdict(q, "close", msg, understood)

    for alt in q.alternatives:
        alt_v = complex(alt.value.real, alt.value.imaginary)
        if _rel_err(ans, alt_v, floor) <= REL_OK:
            return _verdict(q, "wrong", alt.message, understood)

    reason = _diagnose(q, p, exp)
    msg = reason if reason else f"Doğru değil. İpucu: {q.hint}"
    if unit_msg:
        msg += " " + unit_msg
    return _verdict(q, "wrong", msg, understood)


def check_answers(items) -> List[AnswerVerdict]:
    """[(soru, cevap)] → değerlendirmeler (aynı sırayla)."""
    return [check_answer(q, a) for q, a in items]


__all__ = ["check_answer", "check_answers", "EXAMPLES", "REL_OK", "REL_CLOSE"]
