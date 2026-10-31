"""
CircuitAnalyzer API — 3×3 Cramer kuralı (Sarrus yöntemiyle)

Ders kitabındaki (Yağımlı-Akar) gösterim: ilk iki sütun sağa tekrar yazılır,
sol üstten sağ alta inen üç köşegenin çarpımları toplanır, sağ üstten sol alta
inen üç köşegenin çarpımları çıkarılır.

           |  4  −1   0 |  4  −1
      Δ =  | −1   6  −2 | −1   6
           |  0  −2   5 |  0  −2
         = (120 + 0 + 0) − (0 + 16 + 5) = 99

Δₖ, k. sütunun yerine sağ taraf (b) yazılarak aynı yolla bulunur; xₖ = Δₖ / Δ.
Anlatım bu satırları "math" bloğunda gösterir (eş aralıklı yazı tipi, hizalı sütunlar).
"""

from fractions import Fraction
from math import lcm
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

from explainer.formatting import MINUS

_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def _signed_sum(values: Sequence[complex], fmt: Callable[[complex], str]) -> str:
    """'240 + 0 − 20': ilk terim olduğu gibi, sonrakiler işaretiyle."""
    parts = []
    for k, v in enumerate(values):
        t = fmt(v)
        if k == 0:
            parts.append(t)
        elif t.startswith(MINUS):
            parts.append(f"{MINUS} {t[len(MINUS):]}")
        else:
            parts.append(f"+ {t}")
    return " ".join(parts)


def sarrus(symbol: str, M, fmt: Callable[[complex], str]) -> Tuple[str, complex]:
    """
    3×3 determinantın Sarrus açılımı: (çok satırlı metin, değer).
    fmt: sayı biçimlendirici (anlatımdaki _cnum).
    """
    m = [[complex(M[r][c]) for c in range(3)] for r in range(3)]
    cells = [[fmt(m[r][c]) for c in (0, 1, 2, 0, 1)] for r in range(3)]
    widths = [max(len(cells[r][c]) for r in range(3)) for c in range(5)]

    prefix = f"{symbol} = "
    pad = " " * len(prefix)
    lines = []
    for r in range(3):
        left = " ".join(cells[r][c].rjust(widths[c]) for c in range(3))
        right = " ".join(cells[r][c].rjust(widths[c]) for c in range(3, 5))
        lines.append(f"{prefix if r == 1 else pad}| {left} | {right}")

    plus = [m[0][0] * m[1][1] * m[2][2], m[0][1] * m[1][2] * m[2][0], m[0][2] * m[1][0] * m[2][1]]
    minus = [m[0][2] * m[1][1] * m[2][0], m[0][0] * m[1][2] * m[2][1], m[0][1] * m[1][0] * m[2][2]]
    det = sum(plus) - sum(minus)
    lines.append(f"{pad}= ({_signed_sum(plus, fmt)}) {MINUS} ({_signed_sum(minus, fmt)}) = {fmt(det)}")
    return "\n".join(lines), det


def cramer3(A, b, fmt: Callable[[complex], str]) -> List[Tuple[str, str, complex]]:
    """
    Üç bilinmeyenli A·x = b sistemi için [(sembol, Sarrus metni, değer)]:
    önce Δ, sonra Δ₁, Δ₂, Δ₃ (k. sütun yerine b). xₖ = Δₖ / Δ.
    """
    out = []
    text, det = sarrus("Δ", A, fmt)
    out.append(("Δ", text, det))
    for k in range(3):
        Mk = [[complex(b[r]) if c == k else complex(A[r][c]) for c in range(3)] for r in range(3)]
        symbol = "Δ" + str(k + 1).translate(_SUB)
        text, dk = sarrus(symbol, Mk, fmt)
        out.append((symbol, text, dk))
    return out


# ═══════════════════════════════════════════════════════
#  Kesirlerden kurtulma: her denklemi tam sayı yapan çarpan
# ═══════════════════════════════════════════════════════

_MAX_DENOMINATOR = 1000     # bir sayıyı kesir sayabilmek için en büyük payda
_MAX_MULTIPLIER = 1000      # denklemi çarpabileceğimiz en büyük sayı
_MAX_INTEGER = 100000       # çarpımdan sonra katsayıların en büyük mutlak değeri
_FRACTION_TOL = 1e-9        # |x − kesir| ≤ tol·max(1, |x|)


def _row_fractions(values) -> Optional[List[Fraction]]:
    """Satırdaki her sayıyı güvenilir bir kesre çevirir; gerçek olmayan/çirkin sayı varsa None."""
    out: List[Fraction] = []
    for v in values:
        z = complex(v)
        if abs(z.imag) > 1e-12 * max(abs(z), 1e-15):
            return None                      # karmaşık: dokunma
        x = z.real
        f = Fraction(x).limit_denominator(_MAX_DENOMINATOR)
        if abs(x - float(f)) > _FRACTION_TOL * max(1.0, abs(x)):
            return None                      # 1/2.7 gibi çirkin değer: ondalık kalsın
        out.append(f)
    return out


def is_integral_row(A_row, b_r) -> bool:
    """Satırın tüm sayıları (katsayılar ve sağ taraf) zaten tam sayı mı?"""
    fr = _row_fractions(list(A_row) + [b_r])
    return fr is not None and all(f.denominator == 1 for f in fr)


def integer_rows(A, b) -> Tuple[np.ndarray, np.ndarray, List[int]]:
    """
    Her denklemi (katsayılar VE sağ taraf) kesirlerden kurtaracak en küçük pozitif
    tam sayıyla çarpar: 5/12 türü satırlar ×12. (A2, b2, çarpanlar) döner;
    çarpan 1 → satır değişmedi.

    Bir satır yalnızca şu koşullarla çarpılır (çözüm değişmez, yalnız görünüm):
      - tüm sayıları gerçek ve kesir olarak güvenilir (payda ≤ 1000, hata ≤ 1e-9);
      - paydaların EKOK'u (çarpan) 1 < m ≤ 1000;
      - çarpılmış tam sayıların hepsi |n| ≤ 100000.
    Karmaşık satırlar, zaten tam sayı olan satırlar ve çirkin (ör. 1/2.7) satırlar
    olduğu gibi kalır. Çarpılan satırlar tam sayı değerlidir (yuvarlanmış).
    """
    A2 = np.array(A)
    b2 = np.array(b)
    if A2.dtype.kind not in "fc":
        A2 = A2.astype(float)
    if b2.dtype.kind not in "fc":
        b2 = b2.astype(float)
    n = len(b2)
    mult = [1] * n
    for r in range(n):
        fr = _row_fractions(list(A2[r]) + [b2[r]])
        if fr is None:
            continue
        m = lcm(*(f.denominator for f in fr))
        if m <= 1 or m > _MAX_MULTIPLIER:
            continue
        ints = [int(f * m) for f in fr]
        if any(abs(v) > _MAX_INTEGER for v in ints):
            continue
        A2[r, :] = ints[:-1]
        b2[r] = ints[-1]
        mult[r] = m
    return A2, b2, mult


def exact_fmt(fmt: Callable[[complex], str]) -> Callable[[complex], str]:
    """
    Tam sayı değerli gerçek sayıları 4 anlamlı basamağa yuvarlamadan yazar
    (12345 → '12345', −196 → '−196'); diğer sayılar için fmt kullanılır.
    """
    def f(z) -> str:
        z = complex(z)
        r = round(z.real)
        if abs(z.imag) <= 1e-12 * max(abs(z), 1e-15) and abs(z.real - r) <= 1e-9 and abs(r) < 10 ** 15:
            return f"{MINUS}{-r}" if r < 0 else str(int(r))
        return fmt(z)
    return f


# ═══════════════════════════════════════════════════════
#  2×2 Cramer (iki çevreli devreler, ör. kuplajlı transformatör)
# ═══════════════════════════════════════════════════════

def det2(symbol: str, M, fmt: Callable[[complex], str]) -> Tuple[str, complex]:
    """
    2×2 determinantın açılımı: (çok satırlı metin, değer).

          | a  b |
      Δ = | c  d | = a·d − b·c
    """
    m = [[complex(M[r][c]) for c in range(2)] for r in range(2)]
    cells = [[fmt(m[r][c]) for c in range(2)] for r in range(2)]
    widths = [max(len(cells[r][c]) for r in range(2)) for c in range(2)]
    prefix = f"{symbol} = "
    pad = " " * len(prefix)
    lines = []
    for r in range(2):
        row = " ".join(cells[r][c].rjust(widths[c]) for c in range(2))
        lines.append(f"{prefix if r == 0 else pad}| {row} |")
    p1, p2 = m[0][0] * m[1][1], m[0][1] * m[1][0]
    det = p1 - p2
    def wrap(z) -> str:
        t = fmt(z)
        return t if (t.startswith("(") and t.endswith(")") and t.count("(") == 1) else f"({t})"

    lines.append(f"{pad}= {wrap(m[0][0])} · {wrap(m[1][1])} {MINUS} {wrap(m[0][1])} · {wrap(m[1][0])}"
                 f" = {fmt(det)}")
    return "\n".join(lines), det


def cramer2(A, b, fmt: Callable[[complex], str]) -> List[Tuple[str, str, complex]]:
    """
    İki bilinmeyenli A·x = b sistemi için [(sembol, açılım metni, değer)]:
    önce Δ, sonra Δ₁ ve Δ₂ (k. sütun yerine b). xₖ = Δₖ / Δ.
    """
    out = []
    text, det = det2("Δ", A, fmt)
    out.append(("Δ", text, det))
    for k in range(2):
        Mk = [[complex(b[r]) if c == k else complex(A[r][c]) for c in range(2)] for r in range(2)]
        symbol = "Δ" + str(k + 1).translate(_SUB)
        text, dk = det2(symbol, Mk, fmt)
        out.append((symbol, text, dk))
    return out
