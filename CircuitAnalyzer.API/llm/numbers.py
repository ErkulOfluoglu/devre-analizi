"""
CircuitAnalyzer API — Yapay zekâ cevabındaki sayıların denetimi

Yerel dil modeli (Ollama) yanlış sayı uydurabilir. Bu modül cevaptaki her
sayıyı (birim/önek ile) bulur ve çözücünün bildiği değerlerle karşılaştırır:

    verified    → çözümde/devrede geçen bir değerle uyuşuyor (±%1)
    unverified  → hiçbir bilinen değerle uyuşmuyor (öğrenci uyarılır)
    redacted    → alıştırma modunda bir sorunun cevabını veriyor → gizlenir

Sayım için kullanılan küçük tam sayılar ("2 düğüm", "1. adım") ve eleman
adlarındaki rakamlar (R1, V2, I_R1, V₂) denetlenmez.
"""

import cmath
import math
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Set

REL_MATCH = 0.01          # doğrulama toleransı
REL_REDACT = 0.02         # alıştırmada cevabı gizleme toleransı
REDACTED = "■■"

_PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3,
           "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}

# Önce uzun birimler; "rad/s" "rad"dan, "VAR" "VA"dan, "VA" "V"den önce gelmeli
_UNIT_ALT = r"rad/s|rad|Hz|VAR|var|VA|V|A|Ω|ohm|W|F|H|°"

# Sayı: işaret (ASCII veya Unicode eksi), sanal birim j (önde/arkada),
# ondalık nokta ya da virgül, üs. Solunda harf/alt çizgi/alt simge varsa
# (R1, I_R1, V₂) eleman adıdır.
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z_₀-₉\d.,])"
    r"(?P<sign>[-−+]\s?)?"
    r"(?:j\s?)?"
    r"(?P<num>\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?)"
    r"j?"
    r"(?:\s?(?P<prefix>[pnuµμmkKMG])?(?P<unit>" + _UNIT_ALT + r"))?"
    r"(?![A-Za-z\d])"
)


@dataclass
class FoundNumber:
    text: str            # metindeki hâli: "4 mA"
    start: int
    end: int
    raw: float           # yazılan sayı (önek uygulanmadan): 4
    value: float         # temel birimde: 0.004
    unit: Optional[str]  # "A", "V", "Ω", "°", ...


def find_numbers(text: str) -> List[FoundNumber]:
    """Metindeki sayıları (birim/önek ile) bulur."""
    out = []
    for m in _NUMBER_RE.finditer(text or ""):
        num = m.group("num").replace(",", ".")
        try:
            raw = float(num)
        except ValueError:
            continue
        if m.group("sign") and m.group("sign").strip() in ("-", "−"):
            raw = -raw
        unit = m.group("unit")
        prefix = m.group("prefix")
        if unit == "ohm":
            unit = "Ω"
        if unit and unit.lower() == "var":
            unit = "VAR"
        scale = _PREFIX.get(prefix, 1.0) if prefix else 1.0
        # "5 m" gibi birimsiz önek yakalanmaz (regex birim ister); "°"de önek olmaz
        if unit == "°":
            scale = 1.0
        out.append(FoundNumber(m.group(0), m.start(), m.end(), raw, raw * scale, unit))
    return out


def _is_counting(n: FoundNumber) -> bool:
    """Birimsiz küçük tam sayılar (sayım, adım no) denetlenmez."""
    return n.unit is None and float(n.raw).is_integer() and abs(n.raw) <= 10


def _close(a: float, b: float, rel: float) -> bool:
    if b == 0:
        return abs(a) < 1e-12
    return abs(abs(a) - abs(b)) <= rel * abs(b)


class KnownValues:
    """Çözümde ve devrede geçen tüm sayılar (işaretsiz karşılaştırılır)."""

    def __init__(self):
        self._values: Set[float] = set()

    def add(self, x: complex):
        z = complex(x)
        for v in (z.real, z.imag, abs(z)):
            if abs(v) > 1e-15:
                self._values.add(abs(v))
        if abs(z) > 1e-15 and abs(z.imag) > 1e-12 * abs(z):
            ph = math.degrees(cmath.phase(z))
            self._values.add(abs(ph))
            self._values.add(abs(180 - abs(ph)))   # −z için açı

    def add_text(self, text: str):
        """Metindeki sayıları hem yazıldığı hâliyle hem temel birimde ekler."""
        for n in find_numbers(text):
            self.add(n.value)
            self.add(n.raw)

    def contains(self, n: FoundNumber, rel: float = REL_MATCH) -> bool:
        candidates = {abs(n.value), abs(n.raw)}
        return any(_close(c, v, rel) for c in candidates for v in self._values)

    def __len__(self):
        return len(self._values)


@dataclass
class NumberCheck:
    text: str
    status: str   # "verified" | "unverified" | "redacted"


def check_answer_numbers(
    answer: str,
    known: KnownValues,
    forbidden: Sequence[complex] = (),
    given: Optional[KnownValues] = None,
) -> (str, List[NumberCheck]):
    """
    Cevaptaki sayıları denetler.

    forbidden: alıştırma sorularının cevapları — eşleşen sayılar gizlenir
               (ama devrede zaten verilen bir değere eşitse gizlenmez: 'given').
    Dönüş: (gerekirse gizlenmiş cevap, sayı denetimleri)
    """
    forbidden_parts: List[float] = []
    for f in forbidden:
        z = complex(f)
        for v in (abs(z), z.real, z.imag):
            if abs(v) > 1e-12:
                forbidden_parts.append(abs(v))
        if abs(z) > 1e-12 and abs(z.imag) > 1e-9 * abs(z):
            forbidden_parts.append(abs(math.degrees(cmath.phase(z))))

    checks: List[NumberCheck] = []
    pieces: List[str] = []
    pos = 0
    for n in find_numbers(answer):
        if _is_counting(n):
            continue
        is_given = given is not None and given.contains(n, REL_MATCH)
        hit = (not is_given) and any(
            _close(c, f, REL_REDACT) for c in (abs(n.value), abs(n.raw)) for f in forbidden_parts)
        if hit:
            pieces.append(answer[pos:n.start])
            pieces.append(REDACTED)
            pos = n.end
            checks.append(NumberCheck(n.text, "redacted"))
        elif known.contains(n):
            checks.append(NumberCheck(n.text, "verified"))
        else:
            checks.append(NumberCheck(n.text, "unverified"))
    pieces.append(answer[pos:])
    return "".join(pieces), checks


def known_from(values: Iterable[complex] = (), texts: Iterable[str] = ()) -> KnownValues:
    k = KnownValues()
    for v in values:
        k.add(v)
    for t in texts:
        k.add_text(t)
    return k
