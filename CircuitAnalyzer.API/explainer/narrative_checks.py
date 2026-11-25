"""
KCL doğrulama kontrolü ve AC zaman domeni anlatım bölümleri.
"""

import cmath
import math
from typing import List

from explainer.formatting import MINUS, eng, num, polar
from explainer.narrative_core import _Ctx, _Section
from models.response import ExplanationBlock
from parser.netlist_parser import SINE_SOURCES


# ═══════════════════════════════════════════════════════
#  9. KONTROL (KCL)
# ═══════════════════════════════════════════════════════

def _kcl_check(ctx: _Ctx) -> List[_Section]:
    s = _Section("Kontrol: Düğümlerde Akım Dengesi")
    check_nodes = ({n for n in ctx.v if n != "0"} if ctx.has_dependent
                   else {n for g in ctx.groups for n in g} | {n for n in ctx.known if n != "0"})
    for node in sorted(check_nodes, key=lambda n: (len(n), n)):
        flows = []   # (eleman, düğümden çıkan akım)
        for e in ctx.elements:
            if e.id not in ctx.i:
                continue
            name = e.id
            if ctx.diodes is not None and e.params.get("diode_of"):
                from explainer.diode_narrative import kcl_label
                name = kcl_label(ctx.diodes, e.id)
            if e.node_positive == node:
                flows.append((name, ctx.i[e.id]))
            elif e.node_negative == node:
                flows.append((name, -ctx.i[e.id]))
        if len(flows) < 2:
            continue
        total = sum(f for _, f in flows)
        scale = max(abs(f) for _, f in flows)
        if scale < 1e-15 or abs(total) > 1e-6 * scale:
            continue
        if ctx.is_dc:
            ins = [(n_, -f.real) for n_, f in flows if f.real < -1e-15]
            outs = [(n_, f.real) for n_, f in flows if f.real > 1e-15]
            if not ins or not outs:
                continue
            in_txt = " + ".join(f"{eng(v, 'A')} ({n_})" for n_, v in ins)
            out_txt = " + ".join(f"{eng(v, 'A')} ({n_})" for n_, v in outs)
            s.check(f"Düğüm {node}: giren {in_txt} = çıkan {out_txt} ✓")
        else:
            terms = " + ".join(f"{polar(f, 'A')} ({n_})" for n_, f in flows)
            s.check(f"Düğüm {node}: çıkan akımların fazörel toplamı {terms} ≈ 0 ✓")
    if s.blocks:
        s.blocks.insert(0, ExplanationBlock(
            kind="text",
            text="Bulduğumuz akımlar KCL'yi sağlamalı: her düğüme giren akım, çıkan akıma eşittir."))
        if ctx.diodes is not None:
            from explainer.diode_narrative import kcl_note
            note = kcl_note(ctx.diodes)
            if note:
                s.note(note)
        return [s]
    return []


# ═══════════════════════════════════════════════════════
#  10. ZAMAN DOMENİ (AC)
# ═══════════════════════════════════════════════════════

def _time_domain(ctx: _Ctx) -> List[_Section]:
    if ctx.is_dc or ctx.omega is None:
        return []
    has_sine = any(e.element_type in SINE_SOURCES for e in ctx.elements)
    fn = "sin" if has_sine else "cos"
    s = _Section("Zaman Domenine Dönüş")
    if ctx.is_rms:
        s.text(f"Fazör V etkin (RMS) değer olduğundan zamanda v(t) = √2·|V|·{fn}(ωt + θ) "
               f"(Um = √2·V) demektir"
               + (" (kaynak sinüs olarak verildiği için referans sin)." if has_sine
                  else " (kosinüs referansı kullanıldı)."))
    else:
        s.text(f"Fazör V = Vm∠θ, zamanda v(t) = Vm·{fn}(ωt + θ) demektir"
               + (" (kaynak sinüs olarak verildiği için referans sin)." if has_sine
                  else " (kosinüs referansı kullanıldı)."))
    w = num(ctx.omega)

    def expr(z: complex, unit: str = "V") -> str:
        mag, ph = abs(z), math.degrees(cmath.phase(z))
        sign = "+" if ph >= 0 else MINUS
        if ctx.is_rms:
            peak = math.sqrt(2.0) * mag
            p_sym = "Um" if unit == "V" else "Im"
            r_sym = "V" if unit == "V" else "I"
            return (f"{num(peak)}·{fn}({w}t {sign} {num(abs(ph))}°) {unit}  "
                    f"({p_sym} = √2·{r_sym} = √2·{num(mag)} = {num(peak)} {unit})")
        return f"{num(mag)}·{fn}({w}t {sign} {num(abs(ph))}°) {unit}"

    for n in sorted((n for n in ctx.v if n != "0"), key=lambda n: (len(n), n)):
        z = ctx.node_value(n)
        if abs(z) > 1e-15:
            s.math(f"v{n.translate(str.maketrans('0123456789', '₀₁₂₃₄₅₆₇₈₉'))}(t) = {expr(z, 'V')}")
    for e in ctx.passive():
        if e.id in ctx.i and abs(ctx.i[e.id]) > 1e-15:
            s.math(f"i_{e.id}(t) = {expr(ctx.i[e.id], 'A')}")
    return [s]
