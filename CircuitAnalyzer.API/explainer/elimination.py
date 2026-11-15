"""
CircuitAnalyzer API — Kısıt Denklemleriyle Yerine Koyma

Süperdüğüm / süperçevre sistemlerinde ders kitabı yolu:
    kısıt:  V₁ − V₂ = 6    ⇒  V₁ = V₂ + 6
    KCL'de V₁ yerine (V₂ + 6) yazılır → bilinmeyen sayısı azalır → kalan sistem çözülür
    sonra geri yerine koyma: V₁ = V₂ + 6 = 2,18 + 6 = 8,18 V

Yalnızca "x_p − x_n = c" (iki bilinmeyen, katsayılar a ve −a) ya da "a·x = c"
(tek bilinmeyen) biçimindeki kısıt satırları kullanılır; bağımlı kaynak kısıtları
gibi başka biçimler sistemde kalır.

★ Doğruluk kuralı: indirgenmiş sistemin çözümü ve geri yerine koyma, verilen
  tam çözümü (x) vermezse plan None döner; çağıran eski anlatıma döner.
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from explainer.formatting import MINUS

Affine = Tuple[Dict[int, complex], complex]     # Σ katsayı·x_j + sabit


@dataclass
class Substitution:
    var: int                    # yok edilen bilinmeyen
    row: int                    # kullanılan kısıt satırı
    other: Optional[int]        # doğrudan ifadede kalan bilinmeyen (None: sabit değer)
    const: complex              # var = x_other + const   ya da   var = const
    final: Affine = ({}, 0j)    # zincir çözüldükten sonra: kalan bilinmeyenler cinsinden


@dataclass
class Plan:
    subs: List[Substitution]
    keep: List[int]             # kalan bilinmeyenler (orijinal sırayla)
    rows: List[int]             # indirgenmiş sistemin satırları (orijinal sırayla)
    A: np.ndarray               # indirgenmiş katsayılar
    b: np.ndarray
    x: np.ndarray               # indirgenmiş çözüm


def _substituted(row: np.ndarray, rhs: complex, exprs: Dict[int, Affine]) -> Affine:
    """Satırda yok edilmiş bilinmeyenlerin yerine ifadeleri koy: Σ c_j·x_j = sabit."""
    coef: Dict[int, complex] = {}
    const = complex(rhs)
    for j, a in enumerate(row):
        a = complex(a)
        if a == 0:
            continue
        if j in exprs:
            ce, k = exprs[j]
            for jj, cc in ce.items():
                coef[jj] = coef.get(jj, 0j) + a * cc
            const -= a * k
        else:
            coef[j] = coef.get(j, 0j) + a
    return coef, const


def plan_substitution(A, b, x, eliminable: Sequence[bool], rel_tol: float = 1e-6) -> Optional[Plan]:
    A = np.asarray(A, dtype=complex)
    b = np.asarray(b, dtype=complex)
    x = np.asarray(x, dtype=complex)
    n_rows, n = A.shape
    exprs: Dict[int, Affine] = {}
    subs: List[Substitution] = []
    used = set()
    for r in range(n_rows):
        if not eliminable[r]:
            continue
        coef, const = _substituted(A[r], b[r], exprs)
        big = max((abs(c) for c in coef.values()), default=0.0)
        nz = [j for j in sorted(coef) if abs(coef[j]) > 1e-12 * big]
        if len(nz) == 1:
            j = nz[0]
            other, d = None, const / coef[j]
            new: Affine = ({}, d)
        elif len(nz) == 2 and abs(coef[nz[0]] + coef[nz[1]]) <= 1e-12 * big:
            # a·x_j − a·x_o = c  ⇒  x_j = x_o + c/a   (artı katsayılı olan yok edilir)
            j, o = nz if coef[nz[0]].real >= 0 else (nz[1], nz[0])
            other, d = o, const / coef[j]
            new = ({o: 1 + 0j}, d)
        else:
            continue
        for v, (ce, k) in list(exprs.items()):
            if j in ce:
                f = ce.pop(j)
                for jj, cc in new[0].items():
                    ce[jj] = ce.get(jj, 0j) + f * cc
                exprs[v] = (ce, k + f * new[1])
        exprs[j] = (dict(new[0]), new[1])
        subs.append(Substitution(j, r, other, d))
        used.add(r)

    if not subs:
        return None
    keep = [j for j in range(n) if j not in exprs]
    rows = [r for r in range(n_rows) if r not in used]
    if len(rows) != len(keep):
        return None
    Ar = np.zeros((len(rows), len(keep)), dtype=complex)
    br = np.zeros(len(rows), dtype=complex)
    pos = {j: k for k, j in enumerate(keep)}
    for i, r in enumerate(rows):
        coef, const = _substituted(A[r], b[r], exprs)
        for j, c in coef.items():
            if j not in pos:
                return None
            Ar[i, pos[j]] = c
        br[i] = const
    try:
        xr = np.linalg.solve(Ar, br) if keep else np.zeros(0, dtype=complex)
    except np.linalg.LinAlgError:
        return None

    full = np.zeros(n, dtype=complex)
    for j, k in pos.items():
        full[j] = xr[k]
    for v, (ce, k) in exprs.items():
        full[v] = sum(cc * full[jj] for jj, cc in ce.items()) + k
    for j in range(n):
        if abs(full[j] - x[j]) > rel_tol * max(abs(x[j]), 1e-12) + 1e-15:
            return None
    for s in subs:
        s.final = exprs[s.var]
    return Plan(subs, keep, rows, Ar, br, xr)


def affine_text(coefs: Dict[int, complex], const: complex, names: List[str],
                term: Callable[[complex, str, bool], str], cnum: Callable[[complex], str]) -> str:
    """'V₂ + 6', 'V₃ − 2', '4' — term: _linear_term, cnum: sayı biçimi."""
    parts: List[str] = []
    for j in sorted(coefs):
        if abs(coefs[j]) < 1e-15:
            continue
        parts.append(term(coefs[j], names[j], not parts))
    if abs(const) > 1e-15 or not parts:
        t = cnum(const)
        if not parts:
            parts.append(t)
        elif t.startswith(MINUS):
            parts.append(f"{MINUS} {t[len(MINUS):]}")
        else:
            parts.append(f"+ {t}")
    return " ".join(parts)


def _needs_paren(t: str) -> bool:
    if t.startswith(MINUS):
        return True
    if " " not in t:
        return False
    return not (t.startswith("(") and t.endswith(")") and t.count("(") == 1)


def substituted_row_text(row, rhs, names: List[str], exprs: Dict[int, Affine],
                         num_fmt: Callable[[float], str], term, cnum) -> str:
    """
    Satırın yerine koyulmuş hâli: '2,5·(V₂ + 6) + 0,8333·V₂ = 10'.
    Yok edilen bilinmeyenin yerine (gerekirse parantez içinde) ifadesi yazılır.
    """
    parts: List[str] = []
    for j, a in enumerate(row):
        a = complex(a)
        if abs(a) < 1e-15:
            continue
        if j not in exprs:
            parts.append(term(a, names[j], not parts))
            continue
        ce, k = exprs[j]
        inner = affine_text(ce, k, names, term, cnum)
        body = f"({inner})" if _needs_paren(inner) else inner
        if abs(a.imag) <= 1e-12 * abs(a):
            mag = abs(a.real)
            coef = "" if abs(mag - 1) < 1e-12 and ce else f"{num_fmt(mag)}·"
            if a.real < 0:
                sign = MINUS if not parts else f"{MINUS} "
            else:
                sign = "" if not parts else "+ "
        else:
            coef, sign = f"{cnum(a)}·", ("" if not parts else "+ ")
        parts.append(f"{sign}{coef}{body}")
    return f"{' '.join(parts) or '0'} = {cnum(rhs)}"
