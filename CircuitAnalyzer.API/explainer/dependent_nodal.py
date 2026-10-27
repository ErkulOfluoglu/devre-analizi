"""
CircuitAnalyzer API — Bağımlı Kaynaklı Devrede Düğüm Gerilimi Anlatımı

Ders kitabı yöntemi (adım adım):
    1. Kontrol büyüklüğünü bilinmeyen düğüm gerilimleriyle yazarız
         V_R2 = V₂ − V₃,   I_R2 = (V₂ − V₃)/R2
    2. Bağımlı AKIM kaynakları (G, F) KCL'ye bağımsız akım kaynağı gibi girer;
         önce "0.5·V_R2" diye yazılır, sonra düğüm gerilimleriyle değiştirilir.
    3. Bağımlı GERİLİM kaynakları (E, H) akımı bilinmeyen kaynaklardır:
         • bir ucu GND (ya da gerilimi bilinen düğüm) ise o düğüm için KCL yerine
           kısıt denklemi yazılır:   V₃ = 3·V_R2   (içinde bilinmeyen var!)
         • iki ucu da bilinmeyen düğümse süperdüğüm: süperdüğümün KCL'si + kısıt.
    4. A·x = b kurulur, mevcut Cramer/Sarrus/Gauss akışıyla çözülür.

★ Doğruluk kuralı: kurulan sistemin çözümü çözücünün (lcapy) düğüm gerilimleriyle
  karşılaştırılır. Uyuşmazsa ya da durum desteklenmiyorsa build_system bir Türkçe
  SEBEP metni döndürür; çağıran yanlış matematik yerine dürüst yedek anlatımı verir.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

import numpy as np

from explainer.formatting import MINUS, node_v, num, paren
from explainer.narrative import (
    _Ctx, _Section, _close, _cnum, _control_text, _group_terms, _join_terms,
    _linear_term, _pnum, _system_blocks, _flow_text,
)
from explainer.step_generator import _source_value
from parser.netlist_parser import (
    CURRENT_SOURCES, DEPENDENT_CURRENT_OUTPUT, DEPENDENT_VOLTAGE_OUTPUT,
    ElementType, ParsedElement,
)

_TINY = 1e-15


def _node_key(n: str):
    return (len(n), n)


# ═══════════════════════════════════════════════════════
#  DOĞRUSAL İFADE: Σ katsayı·V_düğüm + sabit
# ═══════════════════════════════════════════════════════

class LinExpr:
    """Bilinmeyen düğüm gerilimlerinin doğrusal ifadesi (bilinen düğümler sabite girer)."""

    __slots__ = ("c", "k")

    def __init__(self, c: Optional[Dict[str, complex]] = None, k: complex = 0j):
        self.c: Dict[str, complex] = {n: complex(v) for n, v in (c or {}).items()
                                      if abs(v) > 1e-18}
        self.k = complex(k)

    def __add__(self, o: "LinExpr") -> "LinExpr":
        c = dict(self.c)
        for n, v in o.c.items():
            c[n] = c.get(n, 0j) + v
        return LinExpr(c, self.k + o.k)

    def __neg__(self) -> "LinExpr":
        return self.scale(-1)

    def __sub__(self, o: "LinExpr") -> "LinExpr":
        return self + (-o)

    def scale(self, f: complex) -> "LinExpr":
        return LinExpr({n: v * f for n, v in self.c.items()}, self.k * f)

    @property
    def is_zero(self) -> bool:
        return not self.c and abs(self.k) < _TINY


def _node_expr(ctx: _Ctx, n: str) -> LinExpr:
    if n == "0":
        return LinExpr()
    if n in ctx.known:
        return LinExpr(k=ctx.known[n])
    return LinExpr({n: 1})


def _expr_text(e: LinExpr) -> str:
    """'V₂ − V₃', '−V₃ + 12', '0.25·V₂', '12'."""
    parts: List[str] = []
    for n in sorted(e.c, key=_node_key):
        parts.append(_linear_term(e.c[n], node_v(n), first=not parts))
    if abs(e.k) > _TINY:
        t = _cnum(e.k)
        if not parts:
            parts.append(t)
        elif t.startswith(MINUS):
            parts.append(f"{MINUS} {t[len(MINUS):]}")
        else:
            parts.append(f"+ {t}")
    return " ".join(parts) or "0"


def _coef_times(g: float, x: str) -> str:
    """Katsayı·metin: 1 → 'x', −1 → '−x', 2.5 → '2.5·x', −3 → '−3·x'."""
    g = float(g)
    if abs(g - 1) < 1e-12:
        return x
    if abs(g + 1) < 1e-12:
        return f"{MINUS}{x}"
    if g < 0:
        return f"{MINUS}{num(-g)}·{x}"
    return f"{num(g)}·{x}"


def _diff_sym(p: str, n: str) -> str:
    """Sembolik V_p − V_n (GND düğümü yazılmaz: V₀ = 0)."""
    if n == "0":
        return node_v(p)
    if p == "0":
        return f"{MINUS}{node_v(n)}"
    return f"{node_v(p)} {MINUS} {node_v(n)}"


# ═══════════════════════════════════════════════════════
#  VERİ YAPILARI
# ═══════════════════════════════════════════════════════

@dataclass
class Control:
    elem: ParsedElement          # bağımlı kaynak
    label: str                   # V_R2 / I_R2
    expr: LinExpr                # kontrol büyüklüğü, düğüm gerilimleriyle
    num: str                     # sayısal denklemde yerine konan metin
    lines: List[str]             # "Kontrol büyüklüğünü yazalım" bölümü satırları


@dataclass
class Row:
    kind: str                    # "kcl" | "constraint"
    title: str                   # KCL: 'Düğüm 3' / kısıt: 'Kısıt (E1)'
    sym: str                     # sembolik denklem (KCL'de '= 0' hariç)
    num: str                     # sayısal denklem
    expr: LinExpr                # sol taraf − sağ taraf = 0
    lead: str = ""               # denklemden önce söylenecek açıklama


@dataclass
class DepSystem:
    controls: Dict[str, Control]
    rows: List[Row]
    unknown: List[str]
    A: np.ndarray
    b: np.ndarray
    x: np.ndarray
    kcl_mask: List[bool]
    notes: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════
#  1. KONTROL BÜYÜKLÜKLERİ
# ═══════════════════════════════════════════════════════

def _make_control(ctx: _Ctx, e: ParsedElement) -> Union[Control, str]:
    """Bağımlı kaynağın kontrol büyüklüğü ya da desteklenmeme SEBEBİ (str)."""
    by_id = {x.id: x for x in ctx.elements}
    p = e.params
    ctrl = by_id.get(p["control_id"])
    if ctrl is None:
        return f"{e.id} bağımlı kaynağının kontrol elemanı bulunamadı."
    label = _control_text(ctx, e)
    plus, minus = ctrl.node_positive, ctrl.node_negative
    if p["control_sign"] < 0:
        plus, minus = minus, plus          # çizilen +/− işaretleri ters uçta
    diff = _node_expr(ctx, plus) - _node_expr(ctx, minus)
    diff_sym = f"{node_v(plus)} {MINUS} {node_v(minus)}"

    if p["control_kind"] == "V":
        simp = _expr_text(diff)
        line = f"{label} = {diff_sym}" + ("" if simp == diff_sym else f" = {simp}")
        return Control(e, label, diff, paren(simp), [line])

    # ── Akım kontrolü ──
    t = ctrl.element_type
    if t in CURRENT_SOURCES:
        val = p["control_sign"] * _source_value(ctrl, ctx.is_dc)
        line = (f"{label} = {ctx.val(val, 'A')}  ({ctrl.id} akım kaynağının kendi akımı; "
                f"yön: {_flow_text(plus, minus)})")
        return Control(e, label, LinExpr(k=val), _pnum(val), [line])
    if t in (ElementType.RESISTOR, ElementType.IMPEDANCE, ElementType.CAPACITOR,
             ElementType.INDUCTOR):
        if ctx.is_dc and t == ElementType.CAPACITOR:
            return Control(e, label, LinExpr(), "0",
                           [f"{label} = 0  (DC'de {ctrl.id} kondansatörü açık devredir)"])
        if ctx.is_dc and t == ElementType.INDUCTOR:
            return (f"{e.id} bağımlı kaynağının kontrol akımı DC'de bir bobinin akımıdır; bobin "
                    "kısa devre olduğundan bu akım düğüm gerilimlerinden yazılamaz. Bu devre "
                    "çevre akımları yöntemiyle daha kolay çözülür.")
        z = ctx.impedance(ctrl)
        if z is None or abs(z) < _TINY:
            return f"{ctrl.id} elemanının empedansı bilinmediği için {label} yazılamıyor."
        expr = diff.scale(1 / z)
        top_sym = node_v(plus) if minus == "0" else f"({diff_sym})"
        num_txt = f"{paren(_expr_text(diff))}/{ctx.z_num(z)}"
        lines = [f"{label} = {top_sym}/{ctx.label(ctrl)}", f"= {num_txt}"]
        expanded = _expr_text(expr)
        if expr.c and expanded != num_txt:
            lines.append(f"= {expanded}")
        return Control(e, label, expr, num_txt, lines)
    # Gerilim kaynağının (bağımsız/bağımlı) ya da bağımlı akım kaynağının akımı
    return (f"{e.id} bağımlı kaynağının kontrol akımı bir kaynağın ({ctrl.id}) akımıdır; kaynak "
            "akımı düğüm gerilimleriyle yazılamadığı için bu devre çevre akımları yöntemiyle "
            "daha kolay çözülür.")


# ═══════════════════════════════════════════════════════
#  2. DENKLEM SİSTEMİ
# ═══════════════════════════════════════════════════════

def _dep_term(e: ParsedElement, ctrl: Control, leaving: bool) -> Tuple[str, str, LinExpr]:
    """Bağımlı akım kaynağının KCL terimi: (sembolik, sayısal, ifade)."""
    g = e.params["gain"] * (1 if leaving else -1)
    return (_coef_times(g, ctrl.label), _coef_times(g, ctrl.num), ctrl.expr.scale(g))


def _kcl_row(ctx: _Ctx, members: List[str], controls: Dict[str, Control],
             inner: list) -> Row:
    mset = set(members)
    sym, numeric = _group_terms(ctx, members)
    tot = LinExpr()
    for e in ctx.elements:
        p, n = e.node_positive, e.node_negative
        if (p in mset) == (n in mset):
            continue
        node, other = (p, n) if p in mset else (n, p)
        if ctx.conducts(e):
            tot = tot + (_node_expr(ctx, node) - _node_expr(ctx, other)).scale(1 / ctx.impedance(e))
        elif e.element_type in CURRENT_SOURCES:
            i_s = _source_value(e, ctx.is_dc)
            tot = tot + LinExpr(k=i_s if p in mset else -i_s)
        elif e.element_type in DEPENDENT_CURRENT_OUTPUT:
            ts, tn, te = _dep_term(e, controls[e.id], p in mset)
            sym.append(ts)
            numeric.append(tn)
            tot = tot + te

    if len(members) == 1:
        title = f"Düğüm {members[0]}"
        lead = ""
    else:
        title = "Süperdüğüm {" + ", ".join(members) + "}"
        if inner and all(el.element_type == ElementType.INDUCTOR for el, *_ in inner):
            lead = (f"{', '.join(el.id for el, *_ in inner)} DC'de kısa devredir; Düğüm "
                    f"{' ve '.join(members)} aynı gerilimdedir ve birlikte ele alınır "
                    "(bobinin akımı bilinmediği için tek tek KCL yazılamaz).")
        else:
            lead = (f"Düğüm {' ve '.join(members)} arasında gerilim kaynağı var "
                    f"({', '.join(el.id for el, *_ in inner)}); kaynağın akımı bilinmediği için bu "
                    "düğümler süperdüğüm olarak birlikte ele alınır: önce süperdüğümün KCL'si, "
                    "sonra kaynağın kısıt denklemi yazılır.")
    return Row("kcl", title, _join_terms(sym) or "0", _join_terms(numeric) or "0", tot, lead)


def _constraint_row(ctx: _Ctx, edge, controls: Dict[str, Control], lead: str = "") -> Row:
    elem, p, n, value = edge
    lhs = _node_expr(ctx, p) - _node_expr(ctx, n)
    if elem.element_type in DEPENDENT_VOLTAGE_OUTPUT:
        ctrl = controls[elem.id]
        g = elem.params["gain"]
        sym = f"{_diff_sym(p, n)} = {_coef_times(g, ctrl.label)}"
        numeric = f"{_expr_text(lhs)} = {_coef_times(g, ctrl.num)}"
        return Row("constraint", f"Kısıt ({elem.id})", sym, numeric,
                   lhs - ctrl.expr.scale(g), lead)
    numeric = f"{node_v(p)} {MINUS} {node_v(n)} = {ctx.v_num(value)}"
    return Row("constraint", f"Kısıt ({elem.id})", "", numeric,
               lhs - LinExpr(k=value), lead)


def build_system(ctx: _Ctx) -> Union[DepSystem, str]:
    """
    Bağımlı kaynaklı devrenin düğüm denklem sistemini kurar ve çözücüyle doğrular.
    Başarısızsa/desteklenmiyorsa Türkçe SEBEP (str) döner.
    """
    try:
        return _build_system(ctx)
    except np.linalg.LinAlgError:
        return "Denklem sistemi tekil çıktı; sonuçlar çözücüden alındı."


def _build_system(ctx: _Ctx) -> Union[DepSystem, str]:
    # ── Kontrol büyüklükleri ──
    controls: Dict[str, Control] = {}
    for e in ctx.dependents():
        c = _make_control(ctx, e)
        if isinstance(c, str):
            return c
        controls[e.id] = c

    # ── Bilinmeyenler ve kısıt kenarları ──
    all_nodes = {n for e in ctx.elements for n in (e.node_positive, e.node_negative)}
    unknown = sorted(all_nodes - set(ctx.known) - {"0"}, key=_node_key)
    if not unknown:
        return "Bilinmeyen düğüm kalmadı."
    uset = set(unknown)

    edges = []     # (eleman, p, n, değer)  değer: bağımsız kaynak için sayı
    for elem, value in ctx.constraints:
        p, n = elem.node_positive, elem.node_negative
        if p in uset and n in uset:
            edges.append((elem, p, n, value))
        elif p in uset or n in uset:
            return f"{elem.id} kısıtı beklenmeyen biçimde bağlı; denklemler kurulamadı."
    for e in ctx.dependents():
        if e.element_type not in DEPENDENT_VOLTAGE_OUTPUT:
            continue
        p, n = e.node_positive, e.node_negative
        if p not in uset and n not in uset:
            return (f"{e.id} bağımlı gerilim kaynağı gerilimi zaten bilinen iki düğüm arasında; "
                    "bu kaynak yeni bir denklem getirmediği için adım adım gösterilemiyor.")
        edges.append((e, p, n, None))

    # ── Bağlı bileşenler (kısıtlarla birbirine bağlı düğümler) ──
    parent = {n: n for n in unknown}

    def find(a: str) -> str:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for elem, p, n, _ in edges:
        if p in uset and n in uset:
            parent[find(p)] = find(n)
    comps: Dict[str, List[str]] = {}
    for n in unknown:
        comps.setdefault(find(n), []).append(n)

    rows: List[Row] = []
    kcl_mask: List[bool] = []
    for members in sorted(comps.values(), key=lambda m: _node_key(m[0])):
        mset = set(members)
        inner = [ed for ed in edges if ed[1] in mset and ed[2] in mset]
        anchors = [ed for ed in edges if (ed[1] in mset) != (ed[2] in mset)]
        if len(anchors) > 1 or len(inner) != len(members) - 1:
            return ("Gerilim kaynaklarının oluşturduğu kısıtlar bir döngü oluşturuyor "
                    "(fazla/çelişen denklem); bu devre adım adım gösterilemiyor.")
        if not anchors:
            rows.append(_kcl_row(ctx, members, controls, inner))
            kcl_mask.append(True)
            for ed in inner:
                rows.append(_constraint_row(ctx, ed, controls))
                kcl_mask.append(False)
            continue
        # Bir ucu GND/bilinen düğüme bağlı: KCL yerine yalnızca kısıtlar
        anc = anchors[0]
        other = anc[2] if anc[1] in mset else anc[1]
        node = anc[1] if anc[1] in mset else anc[2]
        where = "GND" if other == "0" else f"Düğüm {other} (gerilimi bilinen düğüm)"
        lead = (f"{anc[0].id} bağımlı gerilim kaynağı Düğüm {node} ile {where} arasına bağlı; "
                "kaynağın akımı bilinmediği için "
                + (f"Düğüm {' ve '.join(members)} için KCL yazılmaz" if len(members) > 1
                   else f"Düğüm {node} için KCL yazılmaz")
                + ", bunun yerine kaynağın kısıt denklemi kullanılır "
                  "(kısıtta bilinmeyen düğüm gerilimi de bulunur):")
        for k, ed in enumerate(inner + [anc]):
            rows.append(_constraint_row(ctx, ed, controls, lead if k == 0 else ""))
            kcl_mask.append(False)

    if len(rows) != len(unknown):
        return "Denklem sayısı bilinmeyen sayısına eşit değil; adım adım gösterilemiyor."

    idx = {n: k for k, n in enumerate(unknown)}
    A = np.zeros((len(rows), len(unknown)), dtype=complex)
    b = np.zeros(len(rows), dtype=complex)
    for r, row in enumerate(rows):
        for n, v in row.expr.c.items():
            A[r, idx[n]] = v
        b[r] = -row.expr.k

    x = np.linalg.solve(A, b)
    if not all(_close(x[k], ctx.node_value(n)) for k, n in enumerate(unknown)):
        return ("Kurulan denklemlerin çözümü çözücünün sonuçlarıyla uyuşmadı; yanlış bir ara "
                "adım göstermemek için denklemler yazılmadı.")
    return DepSystem(controls, rows, unknown, A, b, x, kcl_mask)


# ═══════════════════════════════════════════════════════
#  3. BÖLÜMLER
# ═══════════════════════════════════════════════════════

def control_section(ctx: _Ctx) -> List[_Section]:
    sysm: DepSystem = ctx.dep_system
    s = _Section("Kontrol Büyüklüğünü Bilinmeyenlerle Yazalım")
    s.text("Bağımlı kaynağın çıkışı bir kontrol büyüklüğüne (başka bir elemanın gerilimi ya da "
           "akımı) bağlıdır. Denklemleri düğüm gerilimleriyle kurabilmek için önce bu "
           "büyüklüğü bilinmeyen düğüm gerilimleri cinsinden yazarız. V_X ve I_X, X elemanı "
           "üzerinde çizili +/− işaretine ve oka göre tanımlıdır; V₀ = 0 V alınır:")
    for e in ctx.dependents():
        c = sysm.controls[e.id]
        s.text(f"{e.id} için kontrol büyüklüğü {c.label}:")
        for line in c.lines:
            s.math(line)
    s.note("Bağımlı kaynağın kazancı sabittir; kontrol büyüklüğü ise bilinmeyen düğüm "
           "gerilimlerine bağlı olduğundan bağımlı kaynak denkleme bilinmeyen terim getirir.")
    return [s]


def kcl_section(ctx: _Ctx) -> List[_Section]:
    sysm: DepSystem = ctx.dep_system
    s = _Section("Düğüm Denklemleri (KCL)")
    s.text("Kirchhoff Akım Yasası: Bir düğümden çıkan akımların toplamı sıfırdır. "
           "Bir elemandan çıkan akım (V_düğüm − V_komşu)/Z şeklinde yazılır.")
    cur_deps = [e for e in ctx.dependents() if e.element_type in DEPENDENT_CURRENT_OUTPUT]
    volt_deps = [e for e in ctx.dependents() if e.element_type in DEPENDENT_VOLTAGE_OUTPUT]
    if cur_deps:
        d0 = cur_deps[0]
        example = f"{d0.id} = {_coef_times(d0.params['gain'], sysm.controls[d0.id].label)}"
        s.text(f"Bağımlı akım kaynağı ({', '.join(e.id for e in cur_deps)}) KCL'ye bağımsız akım "
               "kaynağı gibi girer: kaynak düğümden dışarı çıkıyorsa +, düğüme giriyorsa − "
               "işaretiyle. Değeri kazanç · kontrol büyüklüğüdür; önce kontrol büyüklüğünün adıyla "
               f"(ör: {example}), sonra düğüm gerilimleriyle yazılır.")
    if volt_deps:
        s.text(f"Bağımlı gerilim kaynağının ({', '.join(e.id for e in volt_deps)}) akımı bilinmez; "
               "bu yüzden ucundaki düğümde KCL yerine kaynağın kısıt denklemi "
               "(V₊ − V₋ = kazanç · kontrol büyüklüğü) yazılır. İki ucu da bilinmeyen düğümse iki "
               "düğüm süperdüğüm olarak birlikte ele alınır.")
    for row in sysm.rows:
        if row.lead:
            s.text(row.lead)
        if row.kind == "kcl":
            s.math(f"{row.title}: {row.sym} = 0")
            s.math(f"⇒ {row.num} = 0")
        else:
            if row.sym:
                s.math(f"{row.title}: {row.sym}")
                s.math(f"⇒ {row.num}")
            else:
                s.math(f"{row.title}: {row.num}")
    isrc = [e.id for e in ctx.elements
            if e.element_type in CURRENT_SOURCES and abs(_source_value(e, ctx.is_dc)) > _TINY]
    if isrc:
        s.note(f"Akım kaynaklarının ({', '.join(isrc)}) akımı bellidir: kaynak akımı "
               "düğümden dışarı çıkıyorsa +, düğüme giriyorsa − işaretiyle yazılır.")
    caps = [e.id for e in ctx.elements if ctx.is_dc and e.element_type == ElementType.CAPACITOR]
    if caps:
        s.note(f"DC analizde kondansatörler ({', '.join(caps)}) açık devredir, akım terimi oluşturmaz.")
    return [s]


def solve_section(ctx: _Ctx) -> List[_Section]:
    from explainer.formatting import polar, rect
    sysm: DepSystem = ctx.dep_system
    s = _Section("Denklemlerin Çözümü")
    s.text("Bağımlı kaynağın kontrol büyüklüğü artık düğüm gerilimleriyle yazıldığı için denklemler "
           "bilinmeyen terimleri sol, bilinen sayıları sağ tarafta toplanarak A·x = b biçimine gelir.")
    _system_blocks(ctx, s, sysm.unknown, sysm.A, sysm.b, sysm.x, sysm.kcl_mask)
    if not ctx.is_dc:
        for n in sysm.unknown:
            z = ctx.node_value(n)
            s.note(f"{node_v(n)} = {polar(z, 'V')} = {rect(z, 'V')} (kutupsal ↔ dikdörtgensel)")
    return [s]
