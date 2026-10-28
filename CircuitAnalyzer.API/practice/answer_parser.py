"""
CircuitAnalyzer API — Öğrenci cevabını okuma

Öğrencinin kutuya yazdığı metni sayıya çevirir. Defterdeki yazımlar kabul
edilir; önek harflerinde büyük/küçük harf önemlidir (m = mili, M = mega):

    Gerçel     "4", "0.004", "4e-3", "4·10^-3", "4x10^(-3)", "2,5"
    Önekli     "4m", "4 mA", "2.5kΩ", "10 µA", "10uA", "1k5" (= 1.5k)
    Kutupsal   "3.033∠-72.34", "3.033∠−72.34° V", "95.29 mA ∠ 17.66°",
               "3.033<-72.34", "3.033/_-72.34", "3∠1.26rad"
    Dikdörtgen "0.92-2.89j", "0.92 − j2.89 V", "(0.92 - j2.89) mA", "-j31.83", "5+5i"

Okunamayan cevaplar için AnswerParseError, öğrenciye gösterilecek Türkçe
mesajla fırlatılır.
"""

import cmath
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, Tuple


class AnswerParseError(ValueError):
    """Cevap okunamadı; mesaj öğrenciye gösterilir."""


@dataclass
class ParsedAnswer:
    value: complex
    form: str                            # "real" | "polar" | "rect"
    unit: Optional[str] = None           # "V", "A", "Ω", "W", "s", "VA", "VAR" (yazıldıysa)
    angle_input: Optional[float] = None  # kutupsal: yazılan açı sayısı (dönüşümsüz)
    angle_unit: str = "deg"              # "deg" | "rad"


# NFKC sonrası: µ (U+00B5) → μ (U+03BC), Ω (U+2126) → Ω (U+03A9)
_PREFIXES = {
    "p": 1e-12, "n": 1e-9, "u": 1e-6, "μ": 1e-6, "m": 1e-3,
    "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9,
}

# Küçük harfe çevrilmiş birim yazımı → standart birim ("Ω".lower() == "ω")
_UNITS = {
    "v": "V", "volt": "V",
    "a": "A", "amper": "A", "amp": "A",
    "ω": "Ω", "ohm": "Ω", "ohms": "Ω",
    "w": "W", "watt": "W",
    "va": "VA",
    "var": "VAR",
    "s": "s", "sn": "s", "sec": "s", "saniye": "s",
}

_NUM = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_NUM_RE = re.compile(_NUM)

# 4·10^-3, 4*10^(-3), 4 x 10^-3, 4×10^-3 → 4e-3
_POW10_RE = re.compile(r"\s*[*x×·]\s*10\s*\^\s*\(?\s*([+-]?\d+)\s*\)?")

# "1k5" → 1.5k (direnç renk kodu / şema yazımı)
_RKM_RE = re.compile(r"^(\d+)([pnuμmkKMG])(\d+)(.*)$")

_ANGLE_UNIT_RE = re.compile(r"^(°|º|deg|derece|rad)", re.IGNORECASE)

_RECT_TERM_RE = re.compile(
    r"([+-]?)([ji])?((?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)?([ji])?"
)

EXAMPLES = "Örnek yazımlar: 4m, 4 mA, 0.004, 2.5k, 3.03∠-72.3, 0.92-j2.89"


def _normalize(text: str) -> str:
    s = unicodedata.normalize("NFKC", text).strip()
    for dash in ("−", "–", "—"):
        s = s.replace(dash, "-")
    s = s.replace(",", ".")
    s = _POW10_RE.sub(lambda m: f"e{m.group(1)}", s)
    return s


def _parse_suffix(suffix: str) -> Tuple[float, Optional[str]]:
    """
    Sayıdan sonraki önek/birim: "" → (1, None), "mA" → (1e-3, "A"),
    "k" → (1e3, None), "V" → (1, "V"). Tanınmazsa AnswerParseError.
    """
    s = suffix.replace(" ", "")
    if not s:
        return 1.0, None
    if not s.isalpha():                     # "3+", "1/3x": sayı kısmı bozuk
        raise AnswerParseError(f"Cevap bir sayı olarak okunamadı. {EXAMPLES}")
    if s.lower() in _UNITS:                 # yalnız birim (önce: "VA" önek değil)
        return 1.0, _UNITS[s.lower()]
    if s in _PREFIXES:                      # yalnız önek
        return _PREFIXES[s], None
    if s[0] in _PREFIXES and s[1:].lower() in _UNITS:
        return _PREFIXES[s[0]], _UNITS[s[1:].lower()]
    raise AnswerParseError(f"“{suffix.strip()}” birimini tanıyamadım. {EXAMPLES}")


def _parse_real(text: str) -> Tuple[float, float, Optional[str]]:
    """'4.7 kΩ' → (4.7, 1e3, 'Ω'): sayı, önek çarpanı, birim."""
    s = text.strip()
    m = _RKM_RE.match(s)
    if m:
        number = float(f"{m.group(1)}.{m.group(3)}")
        scale, unit = _parse_suffix(m.group(4))
        if scale != 1.0:
            raise AnswerParseError(f"“{text.strip()}” yazımında iki önek var. {EXAMPLES}")
        return number, _PREFIXES[m.group(2)], unit
    m = _NUM_RE.match(s)
    if not m:
        raise AnswerParseError(f"“{text.strip()}” bir sayı olarak okunamadı. {EXAMPLES}")
    number = float(m.group(0))
    rest = s[m.end():]
    # Kesir: "8/3", "8/3 mA"
    fm = re.match(r"\s*/\s*(" + _NUM + ")", rest)
    if fm:
        den = float(fm.group(1))
        if den == 0:
            raise AnswerParseError("Sıfıra bölme var.")
        number /= den
        rest = rest[fm.end():]
    scale, unit = _parse_suffix(rest)
    return number, scale, unit


def _parse_polar(text: str, sep: str) -> ParsedAnswer:
    left, right = text.split(sep, 1)
    if not left.strip():
        raise AnswerParseError(f"Açının önüne büyüklüğü yazın (ör. 3.03∠-72.3). {EXAMPLES}")
    mag, scale, unit = _parse_real(left)

    r = right.strip()
    m = _NUM_RE.match(r)
    if not m:
        raise AnswerParseError(f"“∠” işaretinden sonra açıyı derece olarak yazın. {EXAMPLES}")
    angle = float(m.group(0))
    rest = r[m.end():].strip()
    angle_unit = "deg"
    um = _ANGLE_UNIT_RE.match(rest)
    if um:
        if um.group(1).lower() == "rad":
            angle_unit = "rad"
        rest = rest[um.end():].strip()

    # Önek/birim açıdan sonra da yazılabilir: "95.29∠17.66° mA"
    tail_scale, tail_unit = _parse_suffix(rest)
    if tail_scale != 1.0 and scale != 1.0:
        raise AnswerParseError(f"Önek iki kez yazılmış. {EXAMPLES}")
    scale = scale if scale != 1.0 else tail_scale
    unit = unit or tail_unit

    radians = angle if angle_unit == "rad" else math.radians(angle)
    return ParsedAnswer(
        value=mag * scale * cmath.exp(1j * radians),
        form="polar", unit=unit, angle_input=angle, angle_unit=angle_unit,
    )


def _parse_rect(text: str) -> ParsedAnswer:
    s = text.replace(" ", "")
    suffix = ""
    if s.startswith("("):
        close = s.find(")")
        if close < 0:
            raise AnswerParseError(f"Parantez kapanmamış. {EXAMPLES}")
        s, suffix = s[1:close], s[close + 1:]
    else:
        # Sondaki önek/birim: "0.92-j2.89mA" → gövde "0.92-j2.89", ek "mA"
        m = re.search(r"[A-Za-zΩω]+$", s)
        if m and not re.fullmatch(r"[ji]", m.group(0)):
            tail = m.group(0)
            # "4j" sonundaki j gövdeye aittir: "…jmA" → gövde "…j", ek "mA"
            if tail[0] in "ji" and len(tail) > 1:
                s, suffix = s[:m.start() + 1], tail[1:]
            else:
                s, suffix = s[:m.start()], tail
    scale, unit = _parse_suffix(suffix)

    total = 0j
    pos = 0
    first = True
    while pos < len(s):
        m = _RECT_TERM_RE.match(s, pos)
        if not m or m.end() == pos:
            raise AnswerParseError(f"“{text.strip()}” karmaşık sayı olarak okunamadı. {EXAMPLES}")
        sign, pre_j, number, post_j = m.groups()
        if (pre_j and post_j) or (not number and not (pre_j or post_j)):
            raise AnswerParseError(f"“{text.strip()}” karmaşık sayı olarak okunamadı. {EXAMPLES}")
        if not first and not sign:
            raise AnswerParseError(f"“{text.strip()}” karmaşık sayı olarak okunamadı. {EXAMPLES}")
        v = float(number) if number else 1.0
        if sign == "-":
            v = -v
        total += v * 1j if (pre_j or post_j) else v
        pos = m.end()
        first = False
    if first:
        raise AnswerParseError(f"Cevap boş. {EXAMPLES}")
    return ParsedAnswer(value=total * scale, form="rect", unit=unit)


def parse_answer(text: str) -> ParsedAnswer:
    """Öğrencinin cevabını okur; okunamazsa AnswerParseError fırlatır."""
    s = _normalize(text or "")
    if not s:
        raise AnswerParseError("Cevap boş.")

    for sep in ("∠", "/_", "<"):
        if sep in s:
            return _parse_polar(s, sep)

    # j/i yalnız karmaşık sayıda geçer (birimlerde bu harfler yok)
    if re.search(r"[ji]", s.replace("(", "").replace(")", "")):
        return _parse_rect(s)

    if s.startswith("(") and ")" in s:       # "(4) mA"
        close = s.index(")")
        s = s[1:close] + s[close + 1:]
    number, scale, unit = _parse_real(s)
    return ParsedAnswer(value=complex(number * scale), form="real", unit=unit)
