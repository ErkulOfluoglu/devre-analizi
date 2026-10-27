"""
CircuitAnalyzer API — 3×3 Cramer kuralı (Sarrus yöntemiyle)

Ders kitabındaki (Yağımlı-Akar) gösterim: ilk iki sütun sağa tekrar yazılır,
sol üstten sağ alta inen üç köşegenin çarpımları toplanır, sağ üstten sol alta
inen üç köşegenin çarpımları çıkarılır.

           |  5   2   0 |  5   2
      Δ =  |  2   8  −2 |  2   8
           |  0  −2   6 |  0  −2
         = (240 + 0 + 0) − (0 + 20 + 24) = 196

Δₖ, k. sütunun yerine sağ taraf (b) yazılarak aynı yolla bulunur; xₖ = Δₖ / Δ.
Anlatım bu satırları "math" bloğunda gösterir (eş aralıklı yazı tipi, hizalı sütunlar).
"""

from typing import Callable, List, Sequence, Tuple

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
