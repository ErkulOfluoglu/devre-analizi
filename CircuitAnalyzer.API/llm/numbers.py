"""
CircuitAnalyzer API — Yapay zekâ cevabındaki sayıların denetimi

Yerel dil modeli (Ollama) yanlış sayı uydurabilir. Bu modül cevaptaki her
sayıyı (birim/önek ile) bulur ve çözücünün bildiği değerlerle karşılaştırır:

    verified    → çözümde/devrede geçen bir değerle uyuşuyor (±%1)
    unverified  → hiçbir bilinen değerle uyuşmuyor (öğrenci uyarılır)
    redacted    → alıştırma modunda bir sorunun cevabını veriyor → gizlenir

Sayım için kullanılan küçük tam sayılar ("2 düğüm", "1. adım"), sıfır
(GND, başlangıç değeri), eleman adlarındaki rakamlar (R1, V2, I_R1, V₂) ve
konunun sabitleri (90°, 120°, √3, 5τ'da %99,3) denetlenmez.

Birim yazılmış sayılar yalnız aynı birimdeki (ya da birimi bilinmeyen) değerlerle
karşılaştırılır: devrede 12 V varken "12 kA" ya da "12 A" doğrulanmaz.
"""

import cmath
import math
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

REL_MATCH = 0.01          # doğrulama toleransı
REL_REDACT = 0.02         # alıştırmada cevabı gizleme toleransı
REDACTED = "■■"

# Her devrede doğru olan ders sabitleri. Açılar yalnız "°" ya da "derece" ile,
# 1τ…5τ yüzdeleri yalnız "%" ile, √2, √3, π gibi sayılar birimsiz doğrulanır
# (birimsiz "45" ya da "120" bir akım ya da gerilim iddiası olabilir).
_ANGLE_CONSTANTS = (30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 270.0, 360.0)
_PERCENT_CONSTANTS = (63.2, 86.5, 95.0, 98.2, 99.3, 36.8, 13.5, 1.8)
_MATH_CONSTANTS = (math.sqrt(2), math.sqrt(3), 1 / math.sqrt(2), 1 / math.sqrt(3), math.pi, 2 * math.pi)
REL_CONSTANT = 0.002

_PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3,
           "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}

# Önce uzun birimler; "rad/s" "rad"dan, "VAR" "VA"dan, "VA" "V"den önce gelmeli
_UNIT_ALT = r"rad/s|rad|Hz|VAR|var|VA|V|A|Ω|ohm|W|F|H|J|S|s|°"

# "2.200": Türkçede binlik ayırıcı da olabilir (2200); iki okuma da denenir
_THOUSANDS_RE = re.compile(r"^[1-9]\d{0,2}(?:\.\d{3})+$")

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
    alt_value: Optional[float] = None   # "2.200" → 2200 (nokta binlik ayırıcıysa)
    percent: bool = False                # "%99,3"
    degree_word: bool = False            # "90 derece"


def find_numbers(text: str) -> List[FoundNumber]:
    """Metindeki sayıları (birim/önek ile) bulur."""
    out = []
    for m in _NUMBER_RE.finditer(text or ""):
        num_text = m.group("num")
        num = num_text.replace(",", ".")
        try:
            raw = float(num)
        except ValueError:
            continue
        alt_raw = float(num_text.replace(".", "")) if _THOUSANDS_RE.match(num_text) else None
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
        start = m.start()
        sign = m.group("sign")
        if sign and sign != sign.strip() and m.group(0)[len(sign):].lstrip()[:1] != "j":
            # "12 V - 0 V": boşluklu eksi çıkarma işaretidir, sayının parçası
            # değil; yazılan hâlden çıkarılır (karşılaştırma zaten işaretsiz)
            start = m.start("num")
        percent = (m.start() > 0 and text[m.start() - 1] == "%") or text[m.end():m.end() + 1] == "%"
        degree_word = text[m.end():].lstrip().lower().startswith("derece")
        out.append(FoundNumber(text[start:m.end()], start, m.end(), raw, raw * scale, unit,
                               alt_raw * scale if alt_raw is not None else None, percent, degree_word))
    return out


def _is_counting(n: FoundNumber) -> bool:
    """Birimsiz küçük tam sayılar (sayım, adım no) ve sıfır denetlenmez."""
    if n.value == 0:
        return True   # GND = 0 V, V_C(0⁻) = 0 V, I_N = 0 A: gösterilecek bir uyarı yok
    return n.unit is None and float(n.raw).is_integer() and abs(n.raw) <= 10


def _is_constant(n: FoundNumber) -> bool:
    """90°, 120°, √3 = 1,732, %99,3 gibi ders sabitleri."""
    x = abs(n.raw)
    if n.unit == "°" or (n.unit is None and n.degree_word):
        return any(_close(x, c, REL_CONSTANT) for c in _ANGLE_CONSTANTS)
    if n.unit is not None:
        return False
    if n.percent:
        return any(_close(x, c, REL_CONSTANT) for c in _PERCENT_CONSTANTS)
    return any(_close(x, c, REL_CONSTANT) for c in _MATH_CONSTANTS)


def _close(a: float, b: float, rel: float) -> bool:
    if b == 0:
        return abs(a) < 1e-12
    return abs(abs(a) - abs(b)) <= rel * abs(b)


class KnownValues:
    """
    Çözümde ve devrede geçen tüm sayılar (işaretsiz karşılaştırılır), birimleriyle.

    Birim yazılmış bir sayı yalnız aynı birimdeki ya da birimi bilinmeyen değerlerle
    eşleşir ("12 kA" ≠ 12 V). Birimsiz yazılmış bir sayı her değerle eşleşir; metinde
    yazıldığı hâliyle ("4 mA" → 4) de denenir.
    """

    def __init__(self):
        self._untyped: Set[float] = set()          # birimi bilinmeyen
        self._typed: Dict[str, Set[float]] = {}    # birim → değerler (temel birimde)
        self._raw: Set[float] = set()              # metinde yazıldığı hâli (önek uygulanmadan)

    def add(self, x: complex, unit: Optional[str] = None):
        z = complex(x)
        target = self._untyped if unit is None else self._typed.setdefault(unit, set())
        for v in (z.real, z.imag, abs(z)):
            if abs(v) > 1e-15:
                target.add(abs(v))
        if abs(z) > 1e-15 and abs(z.imag) > 1e-12 * abs(z):
            ph = math.degrees(cmath.phase(z))
            angles = self._typed.setdefault("°", set())
            angles.add(abs(ph))
            angles.add(abs(180 - abs(ph)))   # −z için açı

    def add_text(self, text: str):
        """Metindeki sayıları temel birimde (birimiyle) ve yazıldığı hâliyle ekler."""
        for n in find_numbers(text):
            self.add(n.value, n.unit)
            if abs(n.raw) > 1e-15:
                self._raw.add(abs(n.raw))

    def _pool(self, unit: Optional[str]) -> Iterable[float]:
        if unit is None:
            yield from self._untyped
            yield from self._raw
            for values in self._typed.values():
                yield from values
        else:
            yield from self._untyped
            yield from self._typed.get(unit, ())

    def contains(self, n: FoundNumber, rel: float = REL_MATCH) -> bool:
        candidates = {abs(n.value)}
        if n.unit is None:
            candidates.add(abs(n.raw))
        if n.alt_value is not None:
            candidates.add(abs(n.alt_value))
        return any(_close(c, v, rel) for v in self._pool(n.unit) for c in candidates)

    def __len__(self):
        return len(self._untyped) + len(self._raw) + sum(len(v) for v in self._typed.values())


# ── Alıştırma: yazıyla sayılar ("on iki volt") ve kesirler ("8/3 A") ──
_ONES_TENS = {
    "sıfır": 0, "bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7,
    "sekiz": 8, "dokuz": 9, "on": 10, "yirmi": 20, "otuz": 30, "kırk": 40, "elli": 50,
    "altmış": 60, "yetmiş": 70, "seksen": 80, "doksan": 90,
}
_WORD_PREFIX = {"mili": 1e-3, "mikro": 1e-6, "kilo": 1e3, "mega": 1e6}
_WORD_UNIT = {"volt": "V", "amper": "A", "ohm": "Ω", "watt": "W", "hertz": "Hz", "farad": "F",
              "henri": "H", "henry": "H", "saniye": "s", "derece": "°"}
_NUMBER_WORDS = "|".join(sorted(list(_ONES_TENS) + ["yüz", "bin"], key=len, reverse=True))
_WORDS_RE = re.compile(
    r"(?<!\w)(?P<words>(?:(?:" + _NUMBER_WORDS + r")\s+)*(?:" + _NUMBER_WORDS + r"))"
    r"\s*(?P<prefix>mili|mikro|kilo|mega)?\s*(?P<unit>volt|amper|ohm|watt|hertz|farad|henri|henry|saniye|derece)"
    r"(?!\w)", re.IGNORECASE)
_FRACTION_RE = re.compile(
    r"(?<![A-Za-z_₀-₉\d.,])(?P<a>\d+(?:[.,]\d+)?)\s*/\s*(?P<b>\d+(?:[.,]\d+)?)"
    r"(?:\s?(?P<prefix>[pnuµμmkKMG])?(?P<unit>" + _UNIT_ALT + r"))?(?![A-Za-z\d])")


def _words_value(words: str) -> Optional[float]:
    """'on iki' → 12, 'iki yüz elli' → 250, 'bin' → 1000."""
    total, current = 0, 0
    for w in words.lower().split():
        if w in _ONES_TENS:
            current += _ONES_TENS[w]
        elif w == "yüz":
            current = (current or 1) * 100
        elif w == "bin":
            total += (current or 1) * 1000
            current = 0
        else:
            return None
    return float(total + current)


def find_hidden_numbers(text: str) -> List[FoundNumber]:
    """Rakamla tek sayı olarak yazılmamış değerler: yazıyla sayılar ve kesirler."""
    out: List[FoundNumber] = []
    for m in _WORDS_RE.finditer(text or ""):
        v = _words_value(m.group("words"))
        if v is None:
            continue
        unit = _WORD_UNIT[m.group("unit").lower()]
        scale = _WORD_PREFIX.get((m.group("prefix") or "").lower(), 1.0)
        out.append(FoundNumber(m.group(0), m.start(), m.end(), v, v * scale, unit))
    for m in _FRACTION_RE.finditer(text or ""):
        b = float(m.group("b").replace(",", "."))
        if b == 0:
            continue
        v = float(m.group("a").replace(",", ".")) / b
        unit = m.group("unit")
        if unit == "ohm":
            unit = "Ω"
        scale = _PREFIX.get(m.group("prefix"), 1.0) if m.group("prefix") and unit != "°" else 1.0
        out.append(FoundNumber(m.group(0), m.start(), m.end(), v, v * scale, unit))
    return out


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

    def forbidden_hit(n: FoundNumber) -> bool:
        if given is not None and given.contains(n, REL_MATCH):
            return False      # devrede zaten verilmiş bir değer (ör. kaynak gerilimi)
        return any(_close(c, f, REL_REDACT) for c in (abs(n.value), abs(n.raw)) for f in forbidden_parts)

    checks: List[NumberCheck] = []
    hidden: List[Tuple[int, int]] = []
    if forbidden_parts:
        # "sekiz volt", "8/3 A": rakamla tek sayı olarak yazılmamış cevaplar da gizlenir
        for n in find_hidden_numbers(answer):
            if forbidden_hit(n):
                hidden.append((n.start, n.end))
                checks.append(NumberCheck(n.text, "redacted"))

    def inside_hidden(n: FoundNumber) -> bool:
        return any(s <= n.start < e for s, e in hidden)

    for n in find_numbers(answer):
        if inside_hidden(n) or _is_counting(n):
            continue
        if forbidden_parts and forbidden_hit(n):
            hidden.append((n.start, n.end))
            checks.append(NumberCheck(n.text, "redacted"))
        elif known.contains(n) or _is_constant(n):
            checks.append(NumberCheck(n.text, "verified"))
        else:
            checks.append(NumberCheck(n.text, "unverified"))

    pieces: List[str] = []
    pos = 0
    for s, e in sorted(hidden):
        if s < pos:
            continue
        pieces.append(answer[pos:s])
        pieces.append(REDACTED)
        pos = e
    pieces.append(answer[pos:])
    return "".join(pieces), checks


def known_from(values: Iterable = (), texts: Iterable[str] = ()) -> KnownValues:
    """values: sayı ya da (sayı, birim) çiftleri; texts: birimleriyle okunacak metinler."""
    k = KnownValues()
    for v in values:
        if isinstance(v, tuple):
            k.add(v[0], v[1])
        else:
            k.add(v)
    for t in texts:
        k.add_text(t)
    return k
