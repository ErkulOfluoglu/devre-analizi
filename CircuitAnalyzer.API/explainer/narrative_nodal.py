"""
Düğüm gerilimleri yöntemi anlatım bölümleri: bilinen düğümler, KCL, denklem çözümü ve eleman akımları.
"""

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from explainer.cramer import cramer3, exact_fmt, integer_rows, is_integral_row
from explainer.formatting import (
    MINUS, eng, node_name, node_v, num, paren, polar, rect, shown_digits,
)
from explainer.narrative_core import _SOURCES, _Ctx, _Section, _close, elem_name
from explainer.step_generator import _source_value
from models.request import AnalysisType
from models.response import AnalysisResults
from parser.netlist_parser import (
    CURRENT_SOURCES, DC_SOURCES, DEPENDENT_CURRENT_OUTPUT, ElementType, ParsedCircuit,
)


# ═══════════════════════════════════════════════════════
#  3. BİLİNEN DÜĞÜMLER
# ═══════════════════════════════════════════════════════

def _known_nodes(ctx: _Ctx) -> List[_Section]:
    known = [n for n in ctx.known if n != "0"]
    if not known:
        return []
    s = _Section("Bilinen Düğüm Gerilimleri")

    # Kısıt elemanları üzerinden GND'den yayılarak açıkla (BFS)
    reached = {"0"}
    queue = ["0"]
    while queue:
        node = queue.pop(0)
        for elem, value in ctx.constraints:
            p, n = elem.node_positive, elem.node_negative
            if node not in (p, n):
                continue
            other = n if node == p else p
            if other in reached:
                continue
            reached.add(other)
            queue.append(other)
            vo = ctx.known.get(other, 0)
            role = elem.params.get("port_role")
            if role == "short":
                s.text("Terminaller kısa devre teliyle birleştirildi; telin iki ucu arasında "
                       "gerilim farkı yoktur:")
                s.math(f"{node_v(other)} = {node_v(node)} = {ctx.val(vo, 'V')}")
            elif role == "zeroed":
                s.text(f"{elem.id} sıfırlandı (gerilim kaynağı → kısa devre), bu yüzden uçları "
                       "arasında gerilim farkı yoktur:")
                s.math(f"{node_v(other)} = {node_v(node)} = {ctx.val(vo, 'V')}")
            elif elem.params.get("superposition_zeroed"):
                s.text(f"{elem.id} bu adımda sıfırlandı (kısa devre), bu yüzden uçları "
                       "arasında gerilim farkı yoktur:")
                s.math(f"{node_v(other)} = {node_v(node)} = {ctx.val(vo, 'V')}")
            elif elem.params.get("diode_of"):
                # İletimdeki diyot: eşik gerilimi kadar kaynak (ideal diyotta 0 V, kısa devre)
                from explainer.diode_narrative import known_node_texts
                text, eq = known_node_texts(elem, node, other, ctx.val(vo, 'V'))
                s.text(text)
                s.math(eq)
            elif elem.element_type in _SOURCES and abs(value) < 1e-15:
                # Bu analizde sıfırlanan kaynak (AC'de DC kaynak / DC'de AC kaynak)
                kind = "DC" if elem.element_type in DC_SOURCES else "AC"
                mode = "AC" if kind == "DC" else "DC"
                s.text(f"{elem.id} bir {kind} kaynağıdır; {mode} analizde sıfırlanır "
                       "(kısa devre gibi davranır), bu yüzden uçları arasında gerilim farkı yoktur:")
                s.math(f"{node_v(other)} = {node_v(node)} = {ctx.val(vo, 'V')}")
            elif elem.element_type in _SOURCES:
                name = elem_name(elem)
                if node == "0":
                    s.text(
                        f"{name} kaynağı {node_name(other)} ile GND arasına bağlı "
                        f"olduğundan bu düğümün gerilimi doğrudan bilinir:")
                else:
                    s.text(f"{name} kaynağı {node_name(node)} ile {node_name(other)} arasında:")
                sign = "+" if other == p else MINUS
                if node == "0":
                    s.math(f"{node_v(other)} = {ctx.val(vo, 'V')}")
                else:
                    s.math(f"{node_v(other)} = {node_v(node)} {sign} {name} = {ctx.val(vo, 'V')}")
            else:
                s.text(f"{elem.id} DC'de kısa devre olduğundan:")
                s.math(f"{node_v(other)} = {node_v(node)} = {ctx.val(vo, 'V')}")
    return [s]


# ═══════════════════════════════════════════════════════
#  4. DÜĞÜM DENKLEMLERİ (KCL)
# ═══════════════════════════════════════════════════════

def _group_terms(ctx: _Ctx, members: List[str]) -> Tuple[List[str], List[str]]:
    """Bir düğüm/süperdüğüm için (sembolik, sayısal) KCL terimleri."""
    mset = set(members)
    sym, numeric = [], []
    for e in ctx.elements:
        if not ctx.conducts(e):
            continue
        p, n = e.node_positive, e.node_negative
        if (p in mset) == (n in mset):
            continue
        node, other = (p, n) if p in mset else (n, p)
        lbl, z = ctx.label(e), ctx.impedance(e)
        if other == "0":
            sym.append(f"{node_v(node)}/{lbl}")
        else:
            sym.append(f"({node_v(node)} {MINUS} {node_v(other)})/{lbl}")
        if other in ctx.known:
            vo = ctx.known[other]
            top = node_v(node) if abs(vo) < 1e-15 else f"({node_v(node)} {MINUS} {ctx.v_num(vo)})"
        else:
            top = f"({node_v(node)} {MINUS} {node_v(other)})"
        numeric.append(f"{top}/{ctx.z_num(z)}")

    # Akım kaynakları: akımı bilinir. Kaynak içinden n+ → n− aktığı için
    # n+ düğümünden ÇIKAN akım +Is, n− düğümünden çıkan akım −Is'dir.
    for e in ctx.elements:
        if e.element_type not in CURRENT_SOURCES:
            continue
        p, n = e.node_positive, e.node_negative
        if (p in mset) == (n in mset):
            continue
        i_s = _source_value(e, ctx.is_dc)
        if abs(i_s) < 1e-15:
            continue   # Bu analizde sıfırlanmış (açık devre)
        leaving = p in mset
        sym.append(e.id if leaving else f"{MINUS}{e.id}")
        numeric.append(_cnum(i_s if leaving else -i_s))
    return sym, numeric


def _join_terms(terms: List[str]) -> str:
    """'a', '−b', 'c' → 'a − b + c' (eksi ile başlayan terimler çıkarma olur)."""
    out = ""
    for t in terms:
        if not out:
            out = t
        elif t.startswith(MINUS):
            out += f" {MINUS} {t[1:]}"
        else:
            out += f" + {t}"
    return out


def _kcl(ctx: _Ctx) -> List[_Section]:
    if not ctx.groups:
        return []
    s = _Section("Düğüm Denklemleri (KCL)")
    s.text(
        "Kirchhoff Akım Yasası: Bir düğümden çıkan akımların toplamı sıfırdır. "
        "Bir elemandan çıkan akım (V_düğüm − V_komşu)/Z şeklinde yazılır."
    )
    for members in ctx.groups:
        sym, numeric = _group_terms(ctx, members)
        if len(members) == 1:
            title = f"Düğüm {members[0]}"
        else:
            title = "Süperdüğüm {" + ", ".join(members) + "}"
            inner = [elem for elem, _ in ctx.constraints
                      if elem.node_positive in members and elem.node_negative in members]
            if inner and all(elem.element_type == ElementType.INDUCTOR for elem in inner):
                s.text(
                    f"{', '.join(elem.id for elem in inner)} DC'de kısa devredir; Düğüm "
                    f"{' ve '.join(members)} aynı gerilimdedir ve birlikte ele alınır "
                    "(bobinin akımı bilinmediği için tek tek KCL yazılamaz)."
                )
            else:
                s.text(
                    f"Düğüm {' ve '.join(members)} arasında bir gerilim kaynağı var; bu "
                    "düğümler süperdüğüm olarak birlikte ele alınır (kaynağın akımı "
                    "bilinmediği için tek tek KCL yazılamaz)."
                )
        s.math(f"{title}: {_join_terms(sym) or '0'} = 0")
        s.math(f"⇒ {_join_terms(numeric) or '0'} = 0")
        if len(members) > 1:
            for elem, value in ctx.constraints:
                p, n = elem.node_positive, elem.node_negative
                if p in members and n in members:
                    s.math(f"Kısıt ({elem.id}): {node_v(p)} {MINUS} {node_v(n)} = {ctx.v_num(value)}")

    isrc = [e.id for e in ctx.elements
            if e.element_type in CURRENT_SOURCES and abs(_source_value(e, ctx.is_dc)) > 1e-15]
    if isrc:
        s.note(f"Akım kaynaklarının ({', '.join(isrc)}) akımı bellidir: kaynak akımı "
               "düğümden dışarı çıkıyorsa +, düğüme giriyorsa − işaretiyle yazılır.")
    caps = [e.id for e in ctx.elements if ctx.is_dc and e.element_type == ElementType.CAPACITOR]
    if caps:
        s.note(f"DC analizde kondansatörler ({', '.join(caps)}) açık devredir, akım terimi oluşturmaz.")
    return [s]


# ═══════════════════════════════════════════════════════
#  5. DENKLEMLERİN ÇÖZÜMÜ
# ═══════════════════════════════════════════════════════

def _nodal_system(ctx: _Ctx):
    """
    Tüm bilinmeyenler tek düğümse Y·V = I sistemini kurar.
    Returns (bilinmeyenler, A, b, terim bilgileri) veya None (süperdüğüm varsa).
    """
    if not ctx.groups or any(len(g) != 1 for g in ctx.groups):
        return None
    unknown = [g[0] for g in ctx.groups]
    idx = {n: k for k, n in enumerate(unknown)}
    size = len(unknown)
    A = np.zeros((size, size), dtype=complex)
    b = np.zeros(size, dtype=complex)
    # Tek bilinmeyenli anlatım için terimler
    coef_sym = [[] for _ in unknown]
    coef_num = [[] for _ in unknown]
    rhs_sym = [[] for _ in unknown]
    rhs_num = [[] for _ in unknown]

    for e in ctx.elements:
        if not ctx.conducts(e):
            continue
        z = ctx.impedance(e)
        y = 1 / z
        lbl = ctx.label(e)
        for node, other in ((e.node_positive, e.node_negative), (e.node_negative, e.node_positive)):
            if node not in idx:
                continue
            k = idx[node]
            A[k, k] += y
            coef_sym[k].append(f"1/{lbl}")
            coef_num[k].append(f"1/{ctx.z_num(z)}")
            if other in idx:
                A[k, idx[other]] -= y
            elif other in ctx.known:
                vo = ctx.known[other]
                b[k] += vo * y
                if abs(vo) > 1e-15:
                    rhs_sym[k].append(f"{node_v(other)}/{lbl}")
                    rhs_num[k].append(f"{ctx.v_num(vo)}/{ctx.z_num(z)}")

    # Akım kaynakları sağ tarafa geçer: n+'dan çıkan Is → sağda −Is,
    # n−'ye giren Is → sağda +Is
    for e in ctx.elements:
        if e.element_type not in CURRENT_SOURCES:
            continue
        i_s = _source_value(e, ctx.is_dc)
        if abs(i_s) < 1e-15:
            continue
        for node, sign in ((e.node_positive, -1), (e.node_negative, +1)):
            if node not in idx:
                continue
            k = idx[node]
            b[k] += sign * i_s
            rhs_sym[k].append(e.id if sign > 0 else f"{MINUS}{e.id}")
            rhs_num[k].append(_cnum(sign * i_s))
    return unknown, A, b, (coef_sym, coef_num, rhs_sym, rhs_num)


def _scale_for(values) -> Tuple[float, str]:
    """Katsayıları okunur yapan 1000'in kuvveti: S → mS ise (1e3, 'm')."""
    mags = [abs(x) for x in values if abs(x) > 1e-15]
    if not mags:
        return 1.0, ""
    m = max(mags)
    for scale, prefix in ((1e-3, "k"), (1.0, ""), (1e3, "m"), (1e6, "µ"), (1e9, "n")):
        if 1 <= m * scale < 1000 or (scale == 1e9):
            return scale, prefix
    return 1.0, ""


def _is_real(z: complex) -> bool:
    z = complex(z)
    return abs(z.imag) < 1e-12 * max(abs(z), 1e-15)


def _cnum(z: complex) -> str:
    z = complex(z)
    return num(z.real) if _is_real(z) else paren(rect(z))


def _pnum(z: complex) -> str:
    """Çarpım içinde sayı: negatif gerçek sayılar da parantezli: (−10)."""
    t = _cnum(z)
    return f"({t})" if t.startswith(MINUS) else t


def _linear_term(a: complex, var: str, first: bool) -> str:
    """Doğrusal denklem terimi: '2.5·V₂', '− V₃', '+ (0.01 + j0.03)·V₂'."""
    a = complex(a)
    if _is_real(a):
        mag = abs(a.real)
        coef = "" if abs(mag - 1) < 1e-12 else f"{num(mag)}·"
        if a.real < 0:
            return f"{MINUS}{coef}{var}" if first else f"{MINUS} {coef}{var}"
        return f"{coef}{var}" if first else f"+ {coef}{var}"
    return f"{_cnum(a)}·{var}" if first else f"+ {_cnum(a)}·{var}"


def _equation_text(coeffs, rhs, names: List[str], fmt) -> str:
    """'−3·V₂ + 5·V₃ = 0': katsayılar fmt ile (tam sayılar yuvarlanmadan) yazılır."""
    parts: List[str] = []
    for a, var in zip(coeffs, names):
        a = complex(a)
        if abs(a) < 1e-15:
            continue
        mag = fmt(abs(a.real))
        coef = "" if mag == "1" else f"{mag}·"
        if a.real < 0:
            parts.append(f"{MINUS}{coef}{var}" if not parts else f"{MINUS} {coef}{var}")
        else:
            parts.append(f"{coef}{var}" if not parts else f"+ {coef}{var}")
    return f"{' '.join(parts) or '0'} = {fmt(rhs)}"


def _integer_step(s: _Section, labels: List[str], names: List[str], A2, b2, mult) -> None:
    """
    'Kesirlerden Kurtulalım' adımı: yalnızca çarpılan satırlar, ders kitabı biçiminde
    ('Düğüm 3 denklemini 12 ile çarpalım:  −3·V₂ + 5·V₃ − 2·V₄ = 0').
    """
    fmt = exact_fmt(_cnum)
    s.text("Kesirlerden kurtulalım: katsayıları tam sayı yapmak için aşağıdaki denklemleri "
           "uygun bir sayıyla çarpalım (iki taraf birden çarpıldığı için çözüm değişmez); "
           "böylece Δ değerlerini tam sayılarla hesaplayabiliriz:")
    for r, m in enumerate(mult):
        if m > 1:
            s.math(f"{labels[r]} denklemini {m} ile çarpalım:  "
                   f"{_equation_text(A2[r], b2[r], names, fmt)}")


def _display_scale(ctx: _Ctx, A, b, mask: List[bool]):
    """
    Görünen birimler: (ölçek, önek, tam sayı planı). KCL satırları mS/mA gibi
    ölçeklenir; kısıt satırları volt cinsinden kalır.
    """
    size = len(mask)
    kcl_rows = [r for r in range(size) if mask[r]]
    int_plan = None     # (A2, b2, çarpanlar): kesirlerden kurtulmuş sistem
    if ctx.is_dc and size in (2, 3):
        # Önce ham birimlerde (S, A) dene: 5/12 S → ×12 ders kitabındaki gibi olur.
        # Her KCL satırı çarpılabiliyor (veya zaten tam sayı) ise mS/mA ölçeği gereksizdir.
        A2, b2, mult = integer_rows(A, b)
        if (any(mult[r] > 1 for r in kcl_rows)
                and all(mult[r] > 1 or is_integral_row(A[r], b[r]) for r in kcl_rows)):
            return 1.0, "", (A2, b2, mult)
    scale, prefix = _scale_for([A[r, j] for r in kcl_rows for j in range(size)]
                               + [b[r] for r in kcl_rows])
    if ctx.is_dc and size in (2, 3):
        # Görünen (ölçeklenmiş) sayılarla dene: ör. 2.5 mS · V₂ gibi satırlar
        As, bs = A.copy(), b.copy()
        for r in kcl_rows:
            As[r, :] = A[r, :] * scale
            bs[r] = b[r] * scale
        A2, b2, mult = integer_rows(As, bs)
        if any(m > 1 for m in mult):
            int_plan = (A2, b2, mult)
    return scale, prefix, int_plan


def _substitution_blocks(ctx: _Ctx, s: _Section, unknown: List[str], A, b, x,
                         mask: List[bool], labels: List[str]) -> bool:
    """
    Süperdüğüm kısıtı (V_p − V_n = c) ile yerine koyma: bilinmeyen sayısını azaltıp
    kalan sistemi çözer, sonra geri yerine koyar. Sonuç tam çözümü vermezse False.
    """
    from explainer.elimination import affine_text, plan_substitution, substituted_row_text
    plan = plan_substitution(A, b, x, [not m for m in mask])
    if plan is None or not plan.keep:
        return False
    names = [node_v(n) for n in unknown]
    red_mask = [mask[r] for r in plan.rows]
    scale, prefix, _ = _display_scale(ctx, plan.A, plan.b, red_mask)
    finals = {sub.var: sub.final for sub in plan.subs}

    if len(plan.subs) == 1:
        s.text("Kısıt denklemi iki düğüm gerilimi arasındaki farkı verir; bu denklemden bir "
               "bilinmeyeni diğerinin cinsinden yazıp KCL denkleminde yerine koyarak bilinmeyen "
               "sayısını azaltalım:")
    else:
        s.text("Kısıt denklemleri düğüm gerilimleri arasındaki farkları verir; bu denklemlerden "
               "bazı bilinmeyenleri diğerlerinin cinsinden yazıp KCL denklemlerinde yerine koyarak "
               "bilinmeyen sayısını azaltalım:")
    for sub in plan.subs:
        direct = ({sub.other: 1} if sub.other is not None else {}, sub.const)
        line = f"{labels[sub.row]}  ⇒  {names[sub.var]} = {affine_text(*direct, names, _linear_term, _cnum)}"
        final = affine_text(*sub.final, names, _linear_term, _cnum)
        if final != affine_text(*direct, names, _linear_term, _cnum):
            line += f" = {final}"
        s.math(line)
    s.text(("Bunu" if len(plan.subs) == 1 else "Bunları") + " kalan denklemlerde yerine koyalım"
           + (f" (KCL denklemlerinde katsayılar {prefix}S, sağ taraf {prefix}A cinsinden):"
              if any(red_mask) else ":"))
    for r in plan.rows:
        k = scale if mask[r] else 1.0
        s.math(f"{labels[r]}: "
               + substituted_row_text(A[r] * k, b[r] * k, names, finals, num, _linear_term, _cnum))
    _system_blocks(ctx, s, [unknown[j] for j in plan.keep], plan.A, plan.b, plan.x,
                   red_mask, [labels[r] for r in plan.rows])

    back = [sb for sb in plan.subs if sb.final[0]]     # sabit olanlar baştan biliniyor
    if back:
        s.text("Bulduğumuz değeri kısıt denklemlerinde yerine koyarak diğer düğüm gerilimlerini bulalım:"
               if len(plan.keep) == 1 else
               "Bulduğumuz değerleri kısıt denklemlerinde yerine koyarak diğer düğüm gerilimlerini bulalım:")
    full = {j: plan.x[k] for k, j in enumerate(plan.keep)}
    for sub in back:
        ce, kc = sub.final
        expr = affine_text(ce, kc, names, _linear_term, _cnum)
        if ctx.is_dc:
            vals = {j: complex(full[j]) for j in ce}
            terms = []
            for j in sorted(ce):
                t = num(abs(vals[j].real))
                t = f"({MINUS}{t})" if vals[j].real < 0 else t
                coef = "" if abs(abs(ce[j].real) - 1) < 1e-12 else f"{num(abs(ce[j].real))}·"
                sign = (MINUS if ce[j].real < 0 else "") if not terms else (
                    f"{MINUS} " if ce[j].real < 0 else "+ ")
                terms.append(f"{sign}{coef}{t}")
            if abs(kc) > 1e-15:
                c = _cnum(kc)
                terms.append(c if not terms else (f"{MINUS} {c[len(MINUS):]}" if c.startswith(MINUS)
                                                  else f"+ {c}"))
            plugged = " ".join(terms)
            line = f"{names[sub.var]} = {expr}"
            trivial = len(ce) == 1 and abs(kc) < 1e-15 and all(
                abs(c - 1) < 1e-12 for c in ce.values())     # V₂ = V₃: sayı tekrar yazılmaz
            if plugged and plugged != expr and ce and not trivial:
                line += f" = {plugged}"
            s.result(f"{line} = {ctx.val(x[sub.var], 'V')}")
        else:
            s.result(f"{names[sub.var]} = {expr} = {ctx.val(x[sub.var], 'V')}")
    return True


def _system_blocks(ctx: _Ctx, s: _Section, unknown: List[str], A, b, x,
                   kcl_mask: Optional[List[bool]] = None,
                   row_labels: Optional[List[str]] = None,
                   substitute: bool = False) -> None:
    """
    A·x = b sistemini düzenlenmiş denklemler olarak yazar ve çözer:
    1 bilinmeyen → bölme, 2 → Cramer, 3 → Cramer (Sarrus), >3 → Gauss.

    kcl_mask[r] = r. denklem KCL mi (katsayılar S, sağ taraf A cinsinden; mS/mA ölçeği
    yalnız bunlara uygulanır) yoksa gerilim kısıtı mı (volt cinsinden, ölçeksiz).
    substitute: V_p − V_n = c biçimindeki kısıtlar önce yerine konur (süperdüğüm).
    """
    size = len(unknown)
    mask = kcl_mask if kcl_mask is not None else [True] * size
    labels = row_labels or [f"{r + 1}. denklem" for r in range(size)]
    if substitute and not all(mask) and _substitution_blocks(ctx, s, unknown, A, b, x, mask, labels):
        return
    all_kcl = all(mask)
    kcl_rows = [r for r in range(size) if mask[r]]
    scale, prefix, int_plan = _display_scale(ctx, A, b, mask)
    As, bs = A.copy(), b.copy()
    for r in kcl_rows:
        As[r, :] = A[r, :] * scale
        bs[r] = b[r] * scale
    Vs = [node_v(n) for n in unknown]
    if all_kcl:
        s.text(
            "Denklemleri düzenleyip bilinmeyenlerin katsayılarını toplayalım "
            f"(katsayılar {prefix}S, sağ taraf {prefix}A cinsinden):")
    else:
        s.text(
            "Denklemleri düzenleyip bilinmeyenleri sol tarafta, bilinen sayıları sağ tarafta "
            f"toplayalım (KCL denklemlerinde katsayılar {prefix}S, sağ taraf {prefix}A "
            "cinsindendir; kısıt denklemleri volt cinsindendir):")
    for k in range(size):
        terms_txt = []
        for j in range(size):
            a = As[k, j]
            if abs(a) < 1e-15:
                continue
            terms_txt.append(_linear_term(a, Vs[j], first=not terms_txt))
        s.math(f"{' '.join(terms_txt)} = {_cnum(bs[k])}")

    if int_plan is not None:
        A2, b2, mult = int_plan
        _integer_step(s, labels, Vs, A2, b2, mult)
        As, bs = A2, b2
    cn = exact_fmt(_cnum)

    def P(z) -> str:
        t = cn(z)
        return f"({t})" if t.startswith(MINUS) else t

    nz_cols = [[c for c in range(size) if abs(As[r, c]) > 1e-15] for r in range(size)]
    single = size >= 2 and all(len(cols) == 1 for cols in nz_cols)
    if size == 1:
        s.result(f"{Vs[0]} = {_cnum(bs[0])} / {_pnum(As[0, 0])} = {ctx.val(x[0], 'V')}")
    elif single:
        s.text("Her denklemde tek bilinmeyen kaldı; Cramer kuralına gerek yok, her birini "
               "doğrudan bölerek buluruz:")
        for r in range(size):
            c = nz_cols[r][0]
            s.result(f"{Vs[c]} = {cn(bs[r])} / {P(As[r, c])} = {ctx.val(x[c], 'V')}")
    elif size == 2:
        a11, a12, a21, a22 = As[0, 0], As[0, 1], As[1, 0], As[1, 1]
        b1, b2 = bs
        det = a11 * a22 - a12 * a21
        d1 = b1 * a22 - a12 * b2
        d2 = a11 * b2 - b1 * a21
        s.text("İki bilinmeyenli sistemi Cramer kuralıyla çözelim:")
        s.math(f"Δ = a₁₁·a₂₂ {MINUS} a₁₂·a₂₁ = {P(a11)}·{P(a22)} {MINUS} "
               f"{P(a12)}·{P(a21)} = {cn(det)}")
        s.math(f"Δ₁ = b₁·a₂₂ {MINUS} a₁₂·b₂ = {P(b1)}·{P(a22)} {MINUS} "
               f"{P(a12)}·{P(b2)} = {cn(d1)}")
        s.math(f"Δ₂ = a₁₁·b₂ {MINUS} b₁·a₂₁ = {P(a11)}·{P(b2)} {MINUS} "
               f"{P(b1)}·{P(a21)} = {cn(d2)}")
        s.result(f"{Vs[0]} = Δ₁/Δ = {cn(d1)} / {cn(det)} = {ctx.val(x[0], 'V')}")
        s.result(f"{Vs[1]} = Δ₂/Δ = {cn(d2)} / {cn(det)} = {ctx.val(x[1], 'V')}")
    elif size == 3:
        s.text("Üç bilinmeyenli sistemi Cramer kuralıyla çözelim. Determinantları Sarrus "
               "yöntemiyle hesaplayalım: ilk iki sütun sağa tekrar yazılır, soldan sağa inen "
               "köşegenlerin çarpımları toplanır, sağdan sola inenlerinkiler çıkarılır. "
               "Δₖ için k. sütunun yerine sağ taraf yazılır.")
        dets = cramer3(As, bs, cn)
        for _, text, _ in dets:
            s.math(text)
        det = dets[0][2]
        for k in range(3):
            symbol, _, dk = dets[k + 1]
            s.result(f"{Vs[k]} = {symbol}/Δ = {cn(dk)} / {cn(det)} = {ctx.val(x[k], 'V')}")
    else:
        s.text(
            f"{size} bilinmeyenli bu sistem Gauss eliminasyonu (veya "
            "matris tersi) ile çözülünce:")
        for k, n in enumerate(unknown):
            s.result(f"{node_v(n)} = {ctx.val(x[k], 'V')}")


def _solve(ctx: _Ctx) -> List[_Section]:
    if not ctx.groups:
        return []
    s = _Section("Denklemlerin Çözümü")
    unknown_all = [n for g in ctx.groups for n in g]
    system = _nodal_system(ctx)

    solved_ok = False
    if system is not None:
        unknown, A, b, terms = system
        try:
            x = np.linalg.solve(A, b)
            solved_ok = all(_close(x[k], ctx.node_value(n)) for k, n in enumerate(unknown))
        except np.linalg.LinAlgError:
            solved_ok = False

    if solved_ok and len(unknown) == 1:
        n = unknown[0]
        coef_sym, coef_num, rhs_sym, rhs_num = (t[0] for t in terms)
        y, i_ = A[0, 0], b[0]
        V = node_v(n)
        s.text(f"{V} içeren terimleri bir tarafta, bilinen değerleri diğer tarafta toplayalım:")
        s.math(f"{V} · ({' + '.join(coef_sym)}) = {_join_terms(rhs_sym) or '0'}")
        s.math(f"{V} · ({' + '.join(coef_num)}) = {_join_terms(rhs_num) or '0'}")
        if ctx.is_dc:
            s.math(f"{V} · {eng(y.real, 'S')} = {eng(i_.real, 'A')}")
            s.result(f"{V} = {eng(i_.real, 'A')} / {eng(y.real, 'S')} = {ctx.val(x[0], 'V')}")
        else:
            s.math(f"{V} · ({rect(y, 'S')}) = {rect(i_, 'A')}")
            s.result(f"{V} = ({rect(i_, 'A')}) / ({rect(y, 'S')}) = {polar(x[0], 'V')}  (= {rect(x[0], 'V')})")

    elif solved_ok and len(unknown) >= 2:
        _system_blocks(ctx, s, unknown, A, b, x,
                       row_labels=[f"Düğüm {n}" for n in unknown])

    else:
        s.text("Denklemler (ve varsa kaynak kısıtları) birlikte çözülünce:")
        for n in unknown_all:
            s.result(f"{node_v(n)} = {ctx.val(ctx.node_value(n), 'V')}")

    if not ctx.is_dc:
        for n in unknown_all:
            z = ctx.node_value(n)
            s.note(f"{node_v(n)} = {polar(z, 'V')} = {rect(z, 'V')} (kutupsal ↔ dikdörtgensel)")
    return [s]


# ═══════════════════════════════════════════════════════
#  6. ELEMAN AKIMLARI
# ═══════════════════════════════════════════════════════

_node_v = node_v


EXTRA_DIGITS_NOTE = ("Bazı satırlarda birbirine yakın iki değerin farkı alındığı için değerler "
                     "4'ten fazla basamakla yazıldı: 4 basamağa yuvarlanmış değerlerin farkı, "
                     "sonucu son basamaklarda kaydırırdı.")


def _flow_text(p: str, n: str) -> str:
    return f"{node_name(p)} → {node_name(n)}"


def _currents(ctx: _Ctx, mark: str = "", passive_only: bool = False,
              zero_unit: str = "A") -> List[_Section]:
    """
    Eleman akımları (Ohm yasası). mark: süperpozisyon adımının işareti (′, ″…) —
    akım ve düğüm gerilimi adlarına eklenir; passive_only: kaynak satırları yazılmaz;
    zero_unit: sıfır çıkan akımın gösterileceği birim (ör. KCL toplamındaki 'mA').
    """
    s = _Section("Eleman Akımları (Ohm Yasası)")
    s.text("Her elemanın akımı, uçlarındaki gerilim farkının empedansına bölümüdür: I = (V₊ − V₋)/Z.")

    def node_v(n: str) -> str:          # işaretli düğüm adı: V₂′
        return _node_v(n) + mark

    extra_digits = False                # bir satırda 4'ten fazla basamak gerekti mi?
    for e in ctx.passive():
        if e.id not in ctx.i:
            continue
        p, n = e.node_positive, e.node_negative
        cur = ctx.i[e.id]
        t = e.element_type
        lbl = ctx.label(e)
        name = f"I_{e.id}{mark}"

        if ctx.is_dc and t == ElementType.CAPACITOR:
            s.math(f"{name} = 0 (DC'de kondansatör açık devredir)")
            continue
        if ctx.is_dc and t == ElementType.INDUCTOR:
            s.math(f"{name} = {eng(abs(cur.real), 'A')} (DC'de bobin kısa devredir; "
                   f"akımı bağlı olduğu koldan gelir, {_flow_text(*((p, n) if cur.real >= 0 else (n, p)))})")
            continue

        z = ctx.impedance(e)
        vp, vn = ctx.node_value(p), ctx.node_value(n)
        derived = (vp - vn) / z
        if not _close(derived, cur, 1e-5):
            # Tutarsızlık — türetmeyi göstermeden çözücü değerini ver
            s.math(f"{name} = {ctx.val(cur, 'A')}")
            continue

        diff_sym = node_v(p) if n == "0" else f"({node_v(p)} {MINUS} {node_v(n)})"
        if ctx.is_dc:
            # Yakın iki gerilimin farkında 4 basamak yetmeyebilir: (9,065 − 8,633)/600
            # elle 720 µA verir, sonuç 719,4 µA'dir → işlenenler gerektiği kadar basamakla
            d = shown_digits([vp.real, vn.real], lambda a: (a[0] - a[1]) / z.real, cur.real)
            extra_digits = extra_digits or d > 4
            diff_num = (eng(vp.real, 'V', d) if n == "0"
                        else f"({eng(vp.real, 'V', d)} {MINUS} {paren(eng(vn.real, 'V', d))})")
            cur_txt = f"0 {zero_unit}" if abs(cur.real) < 1e-15 else eng(cur.real, 'A')
            line = f"{name} = {diff_sym}/{lbl} = {diff_num} / {eng(z.real, 'Ω')} = {cur_txt}"
            if cur.real >= 0:
                s.math(f"{line}  ({_flow_text(p, n)})")
            else:
                s.math(line)
                s.note(f"Eksi işaret, akımın ters yönde aktığını gösterir: "
                       f"{eng(-cur.real, 'A')}, {_flow_text(n, p)}.")
        else:
            vd = vp - vn
            cur_txt = f"0 {zero_unit}" if abs(cur) < 1e-15 else polar(cur, 'A')
            s.math(f"{name} = {diff_sym}/{lbl} = {polar(vd, 'V')} / {polar(z, 'Ω')} = {cur_txt}")

    if extra_digits:
        s.note(EXTRA_DIGITS_NOTE)
    if passive_only:
        return [s]
    for e in ctx.sources():
        if e.id not in ctx.i:
            continue
        cur = ctx.i[e.id]
        p, n = e.node_positive, e.node_negative
        if e.element_type in CURRENT_SOURCES:
            # Akımı bilinir; bilinmeyen uçlarındaki gerilimdir
            vd = ctx.node_value(p) - ctx.node_value(n)
            s.math(f"{e.id} akım kaynağı: I = {ctx.val(cur, 'A')} (kaynak içinde "
                   f"{_flow_text(p, n)}); uçlarındaki gerilim "
                   f"{node_v(p)} {MINUS} {node_v(n)} = {ctx.val(vd, 'V')}")
            continue
        if ctx.is_dc:
            if abs(cur.real) < 1e-15:
                s.math(f"I_{e.id} = 0 (kaynaktan akım çekilmiyor)")
            elif cur.real < 0:
                s.math(f"{e.id} kaynağı devreye {eng(-cur.real, 'A')} verir "
                       f"(kaynak içinde {_flow_text(n, p)}, + ucundan dışarı)")
            else:
                s.math(f"{e.id} kaynağından {eng(cur.real, 'A')} akım içeri girer "
                       f"({_flow_text(p, n)}) — bu kaynak güç çekiyor")
        else:
            s.math(f"{e.id} kaynağının verdiği akım: {polar(-cur, 'A')} "
                   f"(kaynak içinde {_flow_text(n, p)} yönü referans)")
    for e in ctx.dependents():
        if e.id not in ctx.i:
            continue
        cur = ctx.i[e.id]
        p, n = e.node_positive, e.node_negative
        vd = ctx.node_value(p) - ctx.node_value(n)
        if e.element_type in DEPENDENT_CURRENT_OUTPUT:
            s.math(f"{e.id} bağımlı akım kaynağı: I = {ctx.val(cur, 'A')} (kaynak içinde "
                   f"{_flow_text(p, n)}); uçlarındaki gerilim "
                   f"{node_v(p)} {MINUS} {node_v(n)} = {ctx.val(vd, 'V')}")
        elif not ctx.is_dc:
            s.math(f"{e.id} kaynağının verdiği akım: {polar(-cur, 'A')} "
                   f"(kaynak içinde {_flow_text(n, p)} yönü referans)")
        elif abs(cur.real) < 1e-15:
            s.math(f"I_{e.id} = 0 ({e.id} bağımlı kaynağından akım çekilmiyor)")
        elif cur.real < 0:
            s.math(f"{e.id} bağımlı kaynağı devreye {eng(-cur.real, 'A')} verir "
                   f"(kaynak içinde {_flow_text(n, p)}, + ucundan dışarı)")
        else:
            s.math(f"{e.id} bağımlı kaynağından {eng(cur.real, 'A')} akım içeri girer "
                   f"({_flow_text(p, n)}) — bu kaynak güç çekiyor")
    if any(e.id in ctx.i and e.element_type not in CURRENT_SOURCES for e in ctx.sources()) or any(
            e.id in ctx.i and e.element_type not in DEPENDENT_CURRENT_OUTPUT for e in ctx.dependents()):
        s.note("Gerilim kaynağının akımı, kaynağa bağlı elemanların akımlarından KCL ile bulunur.")
    if ctx.diodes is not None:
        from explainer.diode_narrative import current_lines
        for line in current_lines(ctx.diodes, ctx.i):
            s.math(line)
        if any(d.state in ("ON", "ZENER") for d in ctx.diodes.diodes):
            if any(d.state == "ZENER" for d in ctx.diodes.diodes):
                s.note("İletimdeki diyotun akımı, eşdeğer kaynağa bağlı elemanların akımlarından KCL "
                       "ile bulunur (doğru iletimde anot → katot, zener bölgesinde katot → anot).")
            else:
                s.note("İletimdeki diyotun akımı, eşdeğer kaynağa bağlı elemanların akımlarından KCL "
                       "ile bulunur; akım anottan katoda doğru pozitiftir.")
    return [s] if len(s.blocks) > 1 else []


def contribution_currents(parsed: ParsedCircuit, is_dc: bool, frequency: Optional[float],
                          v: Dict[str, complex], i: Dict[str, complex], mark: str):
    """Süperpozisyon adımının pasif eleman akımları (I_R1′ = (V₁′ − V₂′)/R1 = …) blokları."""
    omega = None if is_dc or not frequency else 2 * math.pi * frequency
    ctx = _Ctx(parsed=parsed, is_dc=is_dc, frequency=frequency, omega=omega,
               analysis_type=AnalysisType.NODAL, terminals=None,
               v={str(k): complex(x) for k, x in v.items()},
               i={k: complex(x) for k, x in i.items()}, results=AnalysisResults())
    return _currents(ctx, mark, passive_only=True)[0].blocks[1:]
