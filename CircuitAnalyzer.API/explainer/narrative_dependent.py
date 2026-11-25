"""
Bağımlı kaynakların tanıtım satırları, kontrol büyüklüğü biçimlendirmesi ve çözücü kontrol bölümü.
"""

from typing import List

from explainer.formatting import MINUS, eng, node_name, node_v, num, paren
from explainer.narrative_core import _Ctx, _Section, _close
from parser.netlist_parser import (
    DEPENDENT_CURRENT_OUTPUT, DEPENDENT_NAMES, ElementType, ParsedElement,
)


def _control_text(ctx: _Ctx, e: ParsedElement) -> str:
    """
    Bağımlı kaynağın kontrol büyüklüğü: 'V_R2' / 'I_R2'.
    Ters çevrilmiş kontrolde (V(-R2)) eksi yazılmaz: ekrandaki +/− işaretleri ve
    ok da ters çizilir, V_R2'nin tanımı (_dependent_lines) o yöne göre yapılır.
    """
    p = e.params
    return f"{p['control_kind']}_{p['control_id']}"


def _dependent_lines(ctx: _Ctx) -> List[str]:
    """
    Her bağımlı kaynak için bir satır: adı + neyle kontrol edildiği.
        E1: Gerilim kontrollü gerilim kaynağı, E1 = 3·V_R2 (V_R2 = V₂ − V₀)
    """
    by_id = {e.id: e for e in ctx.elements}
    lines = []
    for e in ctx.dependents():
        gain = e.params["gain"]
        t = e.element_type
        unit = {ElementType.VCCS: "S", ElementType.CCVS: "Ω"}.get(t)
        gain_txt = eng(gain, unit) if unit else num(gain)
        ctrl = by_id.get(e.params["control_id"])
        if ctrl:
            # Ters kontrolde (+) ucu elemanın n− ucudur — ekrandaki işaretlerle aynı
            plus, minus = ctrl.node_positive, ctrl.node_negative
            if e.params["control_sign"] < 0:
                plus, minus = minus, plus
        if e.params["control_kind"] == "V":
            c_desc = (f"V_{ctrl.id} = {node_v(plus)} {MINUS} {node_v(minus)}"
                      if ctrl else "")
        else:
            c_desc = (f"I_{ctrl.id} = {ctrl.id} elemanından {node_name(plus)} → "
                      f"{node_name(minus)} yönünde geçen akım" if ctrl else "")
        out_desc = ""
        if t in DEPENDENT_CURRENT_OUTPUT:
            out_desc = (f"; akımı kaynak içinde {node_name(e.node_positive)} → "
                        f"{node_name(e.node_negative)} yönünde")
        lines.append(
            f"{e.id}: {DEPENDENT_NAMES[t]}, {e.id} = {num(gain)}·{_control_text(ctx, e)}"
            f" (kazanç {gain_txt}; {c_desc}){out_desc}")
    return lines


# ═══════════════════════════════════════════════════════
#  6b. BAĞIMLI KAYNAKLI DEVRE: ÇÖZÜCÜ SONUCU VE KONTROL
# ═══════════════════════════════════════════════════════


def _dependent_solution(ctx: _Ctx) -> List[_Section]:
    """
    YEDEK anlatım: düğüm denklemleri adım adım kurulamadığında (ya da çözücüyle
    doğrulanamadığında) çözücünün düğüm gerilimleri + sebep notu + kontrol.
    """
    s = _Section("Düğüm Gerilimleri (Çözücü Sonucu)")
    if ctx.dep_reason:
        s.note(f"Bu devrede düğüm denklemleri adım adım gösterilemiyor: {ctx.dep_reason} "
               "Aşağıdaki sonuçlar çözücüden alınmıştır ve doğrudur.")
    s.text("Bağımlı kaynağın çıkışı devredeki bir gerilime/akıma bağlı olduğundan denklemler "
           "birlikte çözülür; çözücünün bulduğu düğüm gerilimleri:")
    for n in sorted((n for n in ctx.v if n != "0"), key=lambda n: (len(n), n)):
        s.result(f"{node_v(n)} = {ctx.val(ctx.node_value(n), 'V')}")
    return [s] + _dependent_check(ctx)


def _dependent_check(ctx: _Ctx, zero_i_unit: str = "A") -> List[_Section]:
    """Bulunan değerlerle her bağımlı kaynağın çıkışını kontrol büyüklüğünden yeniden hesaplar."""
    by_id = {e.id: e for e in ctx.elements}
    chk = _Section("Bağımlı Kaynakların Kontrolü")
    chk.text("Bulunan değerlerle her bağımlı kaynağın çıkışı, kontrol büyüklüğünden yeniden hesaplanır:")
    for e in ctx.dependents():
        p = e.params
        ctrl = by_id.get(p["control_id"])
        if ctrl is None:
            continue
        if p["control_kind"] == "V":
            cv, cu = ctx.node_value(ctrl.node_positive) - ctx.node_value(ctrl.node_negative), "V"
        elif ctrl.id in ctx.i:
            cv, cu = ctx.i[ctrl.id], "A"
        else:
            continue
        cv = cv * p["control_sign"]
        out = p["gain"] * cv
        if e.element_type in DEPENDENT_CURRENT_OUTPUT:
            actual, ou = ctx.i.get(e.id), "A"
        else:
            actual, ou = ctx.node_value(e.node_positive) - ctx.node_value(e.node_negative), "V"
        if actual is None or not _close(out, actual, 1e-5):
            continue   # tutarsızsa yanlış bir türetme göstermeyiz
        cv_txt = f"0 {zero_i_unit}" if cu == "A" and abs(cv) < 1e-15 else ctx.val(cv, cu)
        out_txt = f"0 {zero_i_unit}" if ou == "A" and abs(out) < 1e-15 else ctx.val(out, ou)
        chk.math(f"{e.id} = {num(p['gain'])}·{_control_text(ctx, e)} = {num(p['gain'])} · "
                 f"{paren(cv_txt)} = {out_txt}")
    if len(chk.blocks) > 1:
        chk.check("Bağımlı kaynak çıkışları, kontrol büyüklükleriyle tutarlı ✓")
        return [chk]
    return []
