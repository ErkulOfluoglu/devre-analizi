"""
CircuitAnalyzer API — Anlatım için sayı biçimlendirme

Öğrencinin defterine yazacağı biçim:
    0.004 A        → "4 mA"
    666.666 Ω      → "666.7 Ω"
    0.92-2.89j V   → "0.92 − j2.89 V"
    polar          → "3.033∠−72.34° V"
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
    """Sade sayı: 4 anlamlı basamak, bilimsel gösterim yok, Unicode eksi."""
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
    return s.replace("-", MINUS)


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


def is_real(z: Number, rel: float = 1e-9) -> bool:
    z = complex(z)
    return abs(z.imag) <= rel * max(abs(z.real), 1e-15) or abs(z.imag) < 1e-15


def rect(z: Number, unit: str = "", digits: int = 4) -> str:
    """Dikdörtgensel: '0.92 − j2.89 V', saf sanal '−j31.83 Ω', gerçek '12 V'."""
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
    """Kutupsal: '3.033∠−72.34° V'. scaled=True → '95.29∠17.66° mA'."""
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
        AC  → kutupsal (+ dikdörtgensel): '3.033∠−72.34° V  (= 0.92 − j2.89 V)'
    """
    z = complex(z)
    if is_dc:
        return eng(z.real, unit, digits)
    return f"{polar(z, unit, digits)}  (= {rect(z, unit, digits)})"


def paren(text: str) -> str:
    """Toplam/negatif ifadeleri paranteze al: '−j31.83 Ω' → '(−j31.83 Ω)'."""
    t = text.strip()
    if t.startswith(MINUS) or " + " in t or f" {MINUS} " in t:
        return f"({t})"
    return t


def node_v(node: str) -> str:
    """Düğüm gerilimi sembolü: '2' → 'V₂', '0' → 'V₀'."""
    return f"V{node.translate(_SUBSCRIPTS)}" if node.isdigit() else f"V_{node}"


def sub(text: str) -> str:
    """Rakamları alt simgeye çevirir: '12' → '₁₂'."""
    return text.translate(_SUBSCRIPTS)
