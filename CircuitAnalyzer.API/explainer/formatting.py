"""
CircuitAnalyzer API — Anlatım için sayı biçimlendirme

Öğrencinin defterine yazacağı biçim (Türkçe ondalık virgül):
    0.004 A        → "4 mA"
    666.666 Ω      → "666,7 Ω"
    0.92-2.89j V   → "0,92 − j2,89 V"
    polar          → "3,033∠−72,34° V"
    düğüm "2"      → "V₂"

Eksi işareti olarak Unicode "−" kullanılır (tire ile karışmasın).
"""

import cmath
import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Union

Number = Union[int, float, complex]

_PREFIXES = [
    (1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""),
    (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"), (1e-12, "p"),
]

_SUBSCRIPTS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")

MINUS = "−"


def num(x: float, digits: int = 4) -> str:
    """Sade sayı: 4 anlamlı basamak, bilimsel gösterim yok, Unicode eksi, ondalık virgül."""
    if abs(x) < 1e-15:
        return "0"
    s = f"{x:.{digits}g}"
    if "e" in s:
        # Bilimsel gösterim yerine sabit nokta, yine 4 anlamlı basamak:
        # 19774.65 → "19770", 0.00012345 → "0.0001235"
        exponent = math.floor(math.log10(abs(x)))
        if exponent >= digits:
            # Okuldaki gibi yarımda yukarı yuvarla (12345 → 12350); Python'un
            # round()'u yarımda çifte yuvarlar (12340 verirdi)
            step = Decimal(1).scaleb(exponent - digits + 1)
            rounded = Decimal(str(x)).quantize(step, rounding=ROUND_HALF_UP)
            s = format(rounded, "f")
        else:
            s = f"{x:.{digits - 1 - exponent}f}".rstrip("0").rstrip(".")
    return s.replace("-", MINUS).replace(".", ",")


def fmt(x: float, spec: str = "g") -> str:
    """Belirtilen format ile Türkçe virgüllü gösterim (ör. spec='.3f', '.1f')."""
    if abs(x) < 1e-15:
        return "0"
    s = format(x, spec)
    return s.replace("-", MINUS).replace(".", ",")


def _prefix_for(magnitude: float):
    for scale, prefix in _PREFIXES:
        # 0.9995: 999.96 m yerine 1 yazılsın
        if magnitude >= scale * 0.9995:
            return scale, prefix
    return 1e-12, "p"


def eng(value: float, unit: str, digits: int = 4) -> str:
    """Mühendislik notasyonu: eng(0.004, 'A') → '4 mA'."""
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return f"— {unit}".strip()
    if abs(value) < 1e-15:
        return f"0 {unit}".strip()
    scale, prefix = _prefix_for(abs(value))
    return f"{num(value / scale, digits)} {prefix}{unit}".strip()


def shown_digits(operands, combine, exact: float, max_digits: int = 8) -> int:
    """
    İşlenenler kaç anlamlı basamakla yazılırsa, öğrencinin elle yaptığı hesap
    gösterilen 4 basamaklı sonuca (exact) son basamakta en fazla ~1 birim farkla ulaşır?
    4'ten başlar, gerekirse artırır. Yakın iki sayının farkında gerekir:
    (9,065 − 8,633)/600 = 720 µA ama sonuç 719,4 µA → 5 basamak: 9,0648 − 8,6331.
    """
    if abs(exact) < 1e-15:
        return 4
    ulp = 10.0 ** (math.floor(math.log10(abs(exact))) - 3)   # 4. anlamlı basamağın birimi
    for d in range(4, max_digits + 1):
        rounded = [float(f"{x:.{d}g}") for x in operands]
        try:
            if abs(combine(rounded) - exact) <= 1.5 * ulp:
                return d
        except ZeroDivisionError:
            return 4
    return max_digits


def is_real(z: Number, rel: float = 1e-9) -> bool:
    z = complex(z)
    return abs(z.imag) <= rel * max(abs(z.real), 1e-15) or abs(z.imag) < 1e-15


def rect(z: Number, unit: str = "", digits: int = 4) -> str:
    """Dikdörtgensel: '0,92 − j2,89 V', saf sanal '−j31,83 Ω', gerçek '12 V'."""
    z = complex(z)
    unit_s = f" {unit}" if unit else ""
    re_, im = z.real, z.imag
    scale = max(abs(re_), abs(im), 1e-300)
    if abs(im) <= 1e-9 * scale:
        return f"{num(re_, digits)}{unit_s}"
    if abs(re_) <= 1e-9 * scale:
        sign = MINUS if im < 0 else ""
        return f"{sign}j{num(abs(im), digits)}{unit_s}"
    sign = MINUS if im < 0 else "+"
    return f"{num(re_, digits)} {sign} j{num(abs(im), digits)}{unit_s}"


def polar(z: Number, unit: str = "", digits: int = 4, scaled: bool = True) -> str:
    """Kutupsal: '3,033∠−72,34° V'. scaled=True → '95,29∠17,66° mA'."""
    z = complex(z)
    mag = abs(z)
    if mag < 1e-15:
        return f"0 {unit}".strip()
    phase = math.degrees(cmath.phase(z))
    if scaled and unit:
        scale, prefix = _prefix_for(mag)
        return f"{num(mag / scale, digits)}∠{num(phase, digits)}° {prefix}{unit}"
    return f"{num(mag, digits)}∠{num(phase, digits)}°" + (f" {unit}" if unit else "")


def value(z: Number, unit: str, is_dc: bool, digits: int = 4) -> str:
    """
    Sonuç değeri:
        DC  → eng gösterimi: '8 V'
        AC  → kutupsal (+ dikdörtgensel): '3,033∠−72,34° V  (= 0,92 − j2,89 V)'
    """
    z = complex(z)
    if is_dc:
        return eng(z.real, unit, digits)
    return f"{polar(z, unit, digits)}  (= {rect(z, unit, digits)})"


def paren(text: str) -> str:
    """Toplam/negatif ifadeleri paranteze al: '−j31,83 Ω' → '(−j31,83 Ω)'."""
    t = text.strip()
    if t.startswith(MINUS) or " + " in t or f" {MINUS} " in t:
        return f"({t})"
    return t


def node_v(node: str) -> str:
    """Düğüm gerilimi sembolü: '2' → 'V₂', '0' → 'V₀'."""
    return f"V{node.translate(_SUBSCRIPTS)}" if node.isdigit() else f"V_{node}"


def node_name(node: str) -> str:
    """Öğrenci metninde düğüm adı: '0' → 'GND', diğerleri → 'Düğüm N'."""
    return "GND" if str(node) == "0" else f"Düğüm {node}"


def node_ek(node: str, kind: str) -> str:
    """Düğüm adına Türkçe hâl eki: '0', 'e' → 'GND'ye'; '3', 'e' → 'Düğüm 3'e'."""
    return ek(node_name(node), kind)


def node_pair(a: str, b: str) -> str:
    """İki düğüm arası: '2', '3' → 'Düğüm 2–3'; '2', '0' → 'Düğüm 2–GND'; '0', 'Y1' → 'GND–Y1'."""
    a, b = str(a), str(b)
    if a == "0":
        # Sayı tek başına anlaşılmaz ("GND–2"), Y1 / x1 gibi adlar anlaşılır
        return f"GND–{node_name(b) if b.isdigit() else b}"
    if b == "0":
        return f"{node_name(a)}–GND"
    return f"Düğüm {a}–{b}"


def sub(text: str) -> str:
    """Rakamları alt simgeye çevirir: '12' → '₁₂'."""
    return text.translate(_SUBSCRIPTS)


# ── Türkçe ek: "Düğüm 4'te", "Düğüm 3'e", "C2'nin" ──
# Ek, adın SON OKUNAN sözcüğüne göre seçilir: 4 → "dört" → 'te; 6 → "altı" → 'da.
_DIGIT_WORDS = ["sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TEN_WORDS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
_LETTER_WORDS = {"a": "a", "e": "e", "ı": "ı", "i": "i", "o": "o", "ö": "ö", "u": "u", "ü": "ü",
                 "x": "iks", "w": "dabılyu", "q": "kü"}
_VOWELS = "aeıioöuü"
_FRONT = "eiöü"
_VOICELESS = "çfhkpsşt"
_FOUR_WAY = {"a": "ı", "ı": "ı", "o": "u", "u": "u", "e": "i", "i": "i", "ö": "ü", "ü": "ü"}


def _spoken_tail(name: str) -> str:
    """Adın sesli okunuşundaki son sözcük: '40' → 'kırk', 'x12' → 'iki', 'b' → 'be'."""
    s = str(name).strip()
    digits = len(s) - len(s.rstrip("0123456789"))
    if digits:
        n = int(s[-digits:])
        if n == 0:
            return "sıfır"
        if n % 10:
            return _DIGIT_WORDS[n % 10]
        if n % 100:
            return _TEN_WORDS[(n // 10) % 10]
        if n % 1000:
            return "yüz"
        return "bin" if n % 1_000_000 else "milyon"
    ch = s[-1:].lower()
    if ch in _LETTER_WORDS:
        return _LETTER_WORDS[ch]
    return ch + "e" if ch.isalpha() else "e"   # be, ce, de … (harf adları)


def ek(name: str, kind: str) -> str:
    """
    Ada Türkçe hâl ekini kesme işaretiyle ekler.
    kind: 'de' (bulunma: 4'te), 'e' (yönelme: 3'e, 2'ye), 'den' (ayrılma: 6'dan),
          'in' (ilgi: C1'in, C2'nin), 'i' (belirtme: C1'i, C2'yi).
    """
    word = _spoken_tail(name)
    last = word[-1]
    vowel = next((c for c in reversed(word) if c in _VOWELS), "e")
    front = vowel in _FRONT
    after_vowel = last in _VOWELS
    d = "t" if last in _VOICELESS else "d"
    e_a = "e" if front else "a"
    four = _FOUR_WAY[vowel]
    suffix = {
        "de": d + e_a,
        "den": d + e_a + "n",
        "e": ("y" if after_vowel else "") + e_a,
        "in": ("n" if after_vowel else "") + four + "n",
        "i": ("y" if after_vowel else "") + four,
    }[kind]
    return f"{name}'{suffix}"
