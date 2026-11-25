"""
Güç analizi, güç üçgeni, kompanzasyon, güç kontrolü ve güç özeti anlatım bölümleri.
"""

import math
from typing import List

from explainer.formatting import MINUS, eng, eng_group, num, paren, rect
from explainer.narrative_core import _Ctx, _Section, _close
from parser.netlist_parser import DC_SOURCES, ElementType


def _pq(p: float, q: float) -> str:
    """Karmaşık güç: '33,17 W − j57,46 VAR' (işaret j'nin önünde, '+ j−' değil)."""
    sign = MINUS if q < 0 else "+"
    return f"{eng(p, 'W')} {sign} j{eng(abs(q), 'VAR')}"


# ═══════════════════════════════════════════════════════
#  8. GÜÇ
# ═══════════════════════════════════════════════════════

def _power(ctx: _Ctx) -> List[_Section]:
    pw = ctx.results.power
    if pw is None or not pw.elements:
        return []
    s = _Section("Güç Hesabı")
    if not ctx.is_dc:
        if ctx.is_rms:
            s.text("Fazörler etkin (RMS) değer olduğundan ortalama (aktif) güç P = |I|²·R, "
                   "reaktif güç Q = |I|²·X formülüyle bulunur.")
        else:
            s.text("Fazörler tepe değer olduğundan ortalama (aktif) güç P = ½·|I|²·R, "
                   "reaktif güç Q = ½·|I|²·X formülüyle bulunur.")

    absorbed_terms = []
    for e in ctx.passive():
        ep = pw.elements.get(e.id)
        if ep is None or e.id not in ctx.i:
            continue
        i_mag = abs(ctx.i[e.id])
        t = e.element_type
        name = e.id
        if ctx.is_dc:
            if t == ElementType.RESISTOR:
                s.math(f"P_{name} = I²·R = ({eng(i_mag, 'A')})² · {eng(e.value, 'Ω')} = {eng(ep.active_power, 'W')}")
                absorbed_terms.append(ep.active_power)
            elif t in (ElementType.CAPACITOR, ElementType.INDUCTOR):
                s.math(f"P_{name} = 0 (DC'de {'açık' if t == ElementType.CAPACITOR else 'kısa'} devre, güç harcamaz)")
            else:
                s.math(f"P_{name} = {eng(ep.active_power, 'W')}")
                absorbed_terms.append(ep.active_power)
        else:
            z = ctx.impedance(e)
            if ctx.is_rms:
                if t == ElementType.RESISTOR:
                    s.math(f"P_{name} = |I|²·R = ({eng(i_mag, 'A')})² · {eng(e.value, 'Ω')} = {eng(ep.active_power, 'W')}")
                elif t == ElementType.INDUCTOR and z is not None:
                    s.math(f"Q_{name} = |I|²·X_L = ({eng(i_mag, 'A')})² · {eng(z.imag, 'Ω')} = "
                           f"{eng(ep.reactive_power, 'VAR')} (bobin reaktif güç çeker, P = 0)")
                elif t == ElementType.CAPACITOR and z is not None:
                    s.math(f"Q_{name} = −|I|²·|X_C| = −({eng(i_mag, 'A')})² · {eng(abs(z.imag), 'Ω')} = "
                           f"{eng(ep.reactive_power, 'VAR')} (kondansatör reaktif güç üretir, P = 0)")
                else:
                    s.math(f"S_{name} = |I|²·Z = {_pq(ep.active_power, ep.reactive_power)}")
            else:
                if t == ElementType.RESISTOR:
                    s.math(f"P_{name} = ½·|I|²·R = ½ · ({eng(i_mag, 'A')})² · {eng(e.value, 'Ω')} = {eng(ep.active_power, 'W')}")
                elif t == ElementType.INDUCTOR and z is not None:
                    s.math(f"Q_{name} = ½·|I|²·X_L = ½ · ({eng(i_mag, 'A')})² · {eng(z.imag, 'Ω')} = "
                           f"{eng(ep.reactive_power, 'VAR')} (bobin reaktif güç çeker, P = 0)")
                elif t == ElementType.CAPACITOR and z is not None:
                    s.math(f"Q_{name} = −½·|I|²·|X_C| = −½ · ({eng(i_mag, 'A')})² · {eng(abs(z.imag), 'Ω')} = "
                           f"{eng(ep.reactive_power, 'VAR')} (kondansatör reaktif güç üretir, P = 0)")
                else:
                    s.math(f"S_{name} = ½·|I|²·Z = {_pq(ep.active_power, ep.reactive_power)}")

    for e in ctx.sources():
        ep = pw.elements.get(e.id)
        if ep is None or ep.apparent_power < 1e-15:
            continue   # Bu analizde sıfırlanmış kaynak (ör: DC'de AC kaynak)
        if ctx.is_dc:
            # V = uçlar arası gerilim (akım kaynağında devreden gelir)
            v_across = (ctx.node_value(e.node_positive) - ctx.node_value(e.node_negative)).real
            s.math(f"P_{e.id} = V·I = {eng(abs(v_across), 'V')} · "
                   f"{eng(abs(ctx.i.get(e.id, 0).real), 'A')} = {eng(abs(ep.active_power), 'W')} "
                   f"({'verilen' if ep.active_power < 0 else 'çekilen'})")
        else:
            supplied = complex(-ep.active_power, -ep.reactive_power)
            s_form = "V·I*" if ctx.is_rms else "½·V·I*"
            s.math(f"S_{e.id} = {s_form} = {rect(supplied, 'VA')} → P = {eng(supplied.real, 'W')}, "
                   f"Q = {eng(supplied.imag, 'VAR')}, |S| = {eng(abs(supplied), 'VA')} (verilen)")

    for e in ctx.dependents():
        ep = pw.elements.get(e.id)
        if ep is None or ep.apparent_power < 1e-15:
            continue
        # Bağımlı kaynak güç verebilir de çekebilir de (işareti sonuç belirler)
        if ctx.is_dc:
            v_across = (ctx.node_value(e.node_positive) - ctx.node_value(e.node_negative)).real
            s.math(f"P_{e.id} = V·I = {eng(abs(v_across), 'V')} · "
                   f"{eng(abs(ctx.i.get(e.id, 0).real), 'A')} = {eng(abs(ep.active_power), 'W')} "
                   f"({'verilen' if ep.active_power < 0 else 'çekilen'}; bağımlı kaynak)")
        else:
            net = complex(-ep.active_power, -ep.reactive_power)
            s_form = "V·I*" if ctx.is_rms else "½·V·I*"
            s.math(f"S_{e.id} = {s_form} = {rect(net, 'VA')} → P = {eng(net.real, 'W')}, "
                   f"Q = {eng(net.imag, 'VAR')} (bağımlı kaynağın net verdiği)")

    if ctx.diodes is not None and ctx.is_dc:
        from explainer.diode_narrative import power_lines
        for line, p_d in power_lines(ctx.diodes, ctx.i):
            s.math(line)
            if abs(p_d) > 1e-15:
                absorbed_terms.append(p_d)

    sup = complex(pw.total_supplied.real, pw.total_supplied.imaginary)
    absb = complex(pw.total_absorbed.real, pw.total_absorbed.imaginary)
    if ctx.is_dc:
        # Denge satırı tek önekle yazılır ("10,27 W + 394,7 mW" yerine "10,27 W + 0,3947 W")
        sup_txt, *term_txts, absb_txt = eng_group([sup.real, *absorbed_terms, absb.real], "W")
        terms = " + ".join(term_txts) if len(term_txts) > 1 else ""
        s.check(f"Güç dengesi: kaynakların (net) verdiği {sup_txt} = elemanların harcadığı "
                f"{(terms + ' = ') if terms else ''}{absb_txt} ✓"
                if _close(sup, absb, 1e-6) else
                f"Güç dengesi: verilen {eng(sup.real, 'W')}, harcanan {eng(absb.real, 'W')}")
    else:
        if _close(sup, absb, 1e-6):
            s.check(f"Güç dengesi: verilen S = {rect(sup, 'VA')} = çekilen S ✓")
        if pw.power_factor is not None:
            kind = {"geri": "geri — akım gerilimin gerisinde, devre endüktif",
                    "ileri": "ileri — akım gerilimin önünde, devre kapasitif",
                    "birim": "birim — devre saf dirençli gibi davranıyor"}.get(pw.power_factor_type or "", "")
            s.math(f"cos φ = P/|S| = {eng(sup.real, 'W')} / {eng(abs(sup), 'VA')} = "
                   f"{pw.power_factor:.3f}".replace(".", ",") + (f" ({kind})" if kind else ""))
    return [s]


# ═══════════════════════════════════════════════════════
#  8b. GÜÇ VE GÜÇ KATSAYISI YÖNTEMİ BÖLÜMLERİ (POWER)
# ═══════════════════════════════════════════════════════

_PF_TYPE_LABELS = {
    "lagging": "geri, endüktif",
    "leading": "ileri, kapasitif",
    "unity": "birim, rezistif",
}


def _power_triangle(ctx: _Ctx) -> List[_Section]:
    ps = ctx.results.power_summary
    if ps is None:
        return []
    s = _Section("Güç Üçgeni")
    type_tr = _PF_TYPE_LABELS.get(ps.pf_type, ps.pf_type)
    s.text("Kaynakların devreye verdiği toplam aktif güç P (yatay dik kenar), reaktif güç Q "
           "(düşey dik kenar) ve görünür güç S (hipotenüs) bir dik üçgen oluşturur:")
    s.math(f"P = {eng(ps.p, 'W')},  Q = {eng(ps.q, 'VAR')},  S = P + jQ = {rect(complex(ps.p, ps.q), 'VA')}")
    s.math(f"S = √(P² + Q²) = √(({num(ps.p)})² + ({num(ps.q)})²) = {eng(ps.s, 'VA')}")
    s.math(f"φ = arctan(Q / P) = arctan({num(ps.q)} / {num(ps.p)}) = {num(ps.phi_deg)}°")
    s.math(f"cos φ = P / S = {eng(ps.p, 'W')} / {eng(ps.s, 'VA')} = {num(ps.pf, 4)} ({type_tr})")

    ac_srcs = [
        e for e in ctx.sources()
        if e.element_type not in DC_SOURCES and abs(e.params.get("amplitude", e.value)) > 1e-15
    ]
    if ctx.is_rms and len(ac_srcs) == 1 and not ctx.has_dependent:
        src = ac_srcs[0]
        v_mag = abs(ctx.node_value(src.node_positive) - ctx.node_value(src.node_negative))
        i_mag = abs(ctx.i.get(src.id, 0.0))
        sin_phi = math.sin(math.radians(ps.phi_deg))
        s.text(f"Etkin (RMS) gösterimde {src.id} kaynağının V = {eng(v_mag, 'V')} ve "
               f"I = {eng(i_mag, 'A')} değerleriyle:")
        s.math(f"S = V·I = {eng(v_mag, 'V')} · {eng(i_mag, 'A')} = {eng(ps.s, 'VA')}")
        s.math(f"P = V·I·cos φ = {eng(v_mag, 'V')} · {eng(i_mag, 'A')} · {paren(num(ps.pf, 4))} = {eng(ps.p, 'W')}")
        s.math(f"Q = V·I·sin φ = {eng(v_mag, 'V')} · {eng(i_mag, 'A')} · {paren(num(sin_phi, 4))} = {eng(ps.q, 'VAR')}")

    s.result(f"P = {eng(ps.p, 'W')}, Q = {eng(ps.q, 'VAR')}, S = {eng(ps.s, 'VA')}, "
             f"cos φ = {num(ps.pf, 4)} ({type_tr})")
    return [s]


def _compensation_section(ctx: _Ctx) -> List[_Section]:
    ps = ctx.results.power_summary
    if ps is None or ps.compensation is None:
        return []
    comp = ps.compensation
    s = _Section("Kompanzasyon")
    if not comp.applied:
        s.note(comp.reason or "Bu devrede kompanzasyon uygulanamadı.")
        return [s]

    v_srcs = [
        e for e in ctx.sources()
        if e.element_type in (ElementType.AC_SOURCE_SINE, ElementType.AC_SOURCE_PHASOR)
        and abs(e.params.get("amplitude", e.value)) > 1e-15
    ]
    v_src = v_srcs[0]
    v_shown = abs(ctx.node_value(v_src.node_positive) - ctx.node_value(v_src.node_negative))
    v_rms = v_shown if ctx.is_rms else (v_shown / math.sqrt(2.0))
    tan_phi1 = ps.q / ps.p
    phi2_rad = math.acos(min(max(comp.target_pf, 0.0), 1.0))
    phi2_deg = math.degrees(phi2_rad)
    tan_phi2 = math.tan(phi2_rad)
    i_after_rms = ps.p / (v_rms * comp.target_pf)

    s.text(f"Güç katsayısını cos φ₁ = {num(ps.pf, 4)} değerinden hedef cos φ₂ = {num(comp.target_pf, 4)} "
           f"değerine yükseltmek için {v_src.id} kaynağına paralel bir C kondansatörü bağlanır.")
    if not ctx.is_rms:
        s.text("Kompanzasyon formülünde kaynağın etkin (RMS) gerilimi V kullanılır; önce tepe "
               "gerilimden etkin gerilimi bulalım:")
        s.math(f"V = Vm/√2 = {eng(v_shown, 'V')} / √2 = {eng(v_rms, 'V')}")

    s.math(f"φ₁ = {num(ps.phi_deg)}° → tan φ₁ = {num(tan_phi1, 4)},  "
           f"φ₂ = arccos({num(comp.target_pf, 4)}) = {num(phi2_deg)}° → tan φ₂ = {num(tan_phi2, 4)}")
    s.math(f"Q_C = P·(tan φ₁ {MINUS} tan φ₂) = {eng(ps.p, 'W')} · "
           f"({num(tan_phi1, 4)} {MINUS} {num(tan_phi2, 4)}) = {eng(comp.q_c, 'VAR')}")
    s.math(f"C = Q_C / (ω·V²) = {eng(comp.q_c, 'VAR')} / "
           f"({num(ctx.omega)} rad/s · ({num(v_rms)} V)²) = {eng(comp.c, 'F')}  (kaynağa paralel)")
    s.math(f"I' = P / (V·cos φ₂) = {eng(ps.p, 'W')} / "
           f"({eng(v_rms, 'V')} · {num(comp.target_pf, 4)}) = {eng(i_after_rms, 'A')}")
    if not ctx.is_rms:
        s.math(f"Im' = √2·I' = √2 · {eng(i_after_rms, 'A')} = {eng(comp.i_after, 'A')} (tepe)")
        s.result(f"Q_C = {eng(comp.q_c, 'VAR')}, C = {eng(comp.c, 'F')}, "
                 f"yeni kaynak akımı Im' = {eng(comp.i_after, 'A')} (önceki: {eng(comp.i_before, 'A')})")
    else:
        s.result(f"Q_C = {eng(comp.q_c, 'VAR')}, C = {eng(comp.c, 'F')}, "
                 f"yeni kaynak akımı I' = {eng(comp.i_after, 'A')} (önceki: {eng(comp.i_before, 'A')})")

    s.text("Açıklama: Kaynağa paralel bağlanan kondansatör reaktif gücün Q_C kısmını yerel "
           "olarak karşılar; böylece aktif güç P değişmez, yalnız reaktif güç kondansatörden "
           "karşılanır ve hat akımı azalır.")
    return [s]


def _power_check(ctx: _Ctx) -> List[_Section]:
    s = _Section("Kontrol")
    pw = ctx.results.power
    ps = ctx.results.power_summary
    if pw is not None:
        sup = complex(pw.total_supplied.real, pw.total_supplied.imaginary)
        absb = complex(pw.total_absorbed.real, pw.total_absorbed.imaginary)
        if _close(sup, absb, 1e-6):
            s.check(f"Güç dengesi: kaynakların verdiği S = {rect(sup, 'VA')} = "
                    f"elemanların çektiği S = {rect(absb, 'VA')} ✓")
    if ps is not None and ps.compensation is not None:
        comp = ps.compensation
        if comp.applied:
            i_sym = "I'" if ctx.is_rms else "Im'"
            s.check(
                f"Kompanzasyon doğrulaması: C = {eng(comp.c, 'F')} kondansatörü kaynağa paralel "
                f"eklenip devre çözücüyle yeniden çözüldüğünde cos φ₂ = {num(comp.target_pf, 4)} ve "
                f"yeni kaynak akımı {i_sym} = {eng(comp.i_after, 'A')} "
                f"(önceki: {eng(comp.i_before, 'A')}) doğrulandı ✓"
            )
        elif comp.reason:
            s.note(comp.reason)
    return [s] if s.blocks else []


def _power_summary_section(ctx: _Ctx) -> List[_Section]:
    ps = ctx.results.power_summary
    if ps is None:
        return []
    s = _Section("Sonuç")
    type_tr = _PF_TYPE_LABELS.get(ps.pf_type, ps.pf_type)
    s.result(f"P = {eng(ps.p, 'W')}, Q = {eng(ps.q, 'VAR')}, S = {eng(ps.s, 'VA')}")
    s.result(f"cos φ = {num(ps.pf, 4)} ({type_tr}, φ = {num(ps.phi_deg)}°)")
    if ps.compensation is not None and ps.compensation.applied:
        comp = ps.compensation
        i_sym = "I'" if ctx.is_rms else "Im'"
        s.result(f"Q_C = {eng(comp.q_c, 'VAR')}, C = {eng(comp.c, 'F')}, "
                 f"yeni akım {i_sym} = {eng(comp.i_after, 'A')}")
    return [s]
