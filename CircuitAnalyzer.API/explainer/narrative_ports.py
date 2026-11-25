"""
Thevenin ve Norton eşdeğeri anlatım bölümleri, port indirgeme ve bağımlı kaynaklı port denklemleri.
"""

import copy
from typing import List, Optional, Tuple

from explainer.formatting import (
    MINUS, eng, node_ek, node_name, node_v, num, paren, polar, rect, shown_digits,
)
from explainer.narrative_core import (
    _SOURCES, _Ctx, _Section, _close, port_is_dead,
)
from explainer.narrative_dependent import _dependent_check
from explainer.narrative_nodal import (
    EXTRA_DIGITS_NOTE, _currents, _flow_text, _join_terms, _known_nodes,
)
from explainer.step_generator import _node_groups, _source_value
from explainer.topology import reduce_port_impedance
from models.request import AnalysisType
from models.response import AnalysisResults, ExplanationBlock
from parser.netlist_parser import (
    CURRENT_SOURCES, DEPENDENT_CURRENT_OUTPUT, DEPENDENT_VOLTAGE_OUTPUT,
    VOLTAGE_SOURCES, ElementType, ParsedElement,
)


# ═══════════════════════════════════════════════════════
#  7. THEVENIN / NORTON
# ═══════════════════════════════════════════════════════

def _port(ctx: _Ctx):
    if not ctx.terminals:
        return None
    return ctx.terminals.node_positive, ctx.terminals.node_negative


def _imp_text(ctx: _Ctx, z: complex) -> str:
    return eng(z.real, 'Ω') if ctx.is_dc else rect(z, 'Ω')


# Yeniden çözülen (kısa devreli / test kaynaklı) devrenin anlatımından atlanan genel
# açıklamalar: ilk çözümde zaten söylendi
_PORT_SKIP = ("Kirchhoff", "Her elemanı", "Bağımlı kaynağın çıkışı bir kontrol",
              "Bağımlı kaynağın kazancı sabittir", "Bağımlı akım kaynağı (",
              "Bağımlı gerilim kaynağının (", "Bağımlı kaynağın kontrol büyüklüğü artık")


def _and_list(items: List[str]) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} ve {items[-1]}"


def _port_cut(sc: _Ctx, start: str, stop: str, helper_id: str) -> Optional[List[str]]:
    """
    KCL yazılacak düğüm kümesi: start düğümü + ona akımı bilinmeyen elemanlarla (gerilim
    kaynağı, bağımlı gerilim kaynağı, DC'de bobin) bağlı düğümler. Küme diğer terminale
    (stop) ulaşırsa None.
    """
    def unknown_current(e: ParsedElement) -> bool:
        return (e.element_type in VOLTAGE_SOURCES or e.element_type in DEPENDENT_VOLTAGE_OUTPUT
                or (sc.is_dc and e.element_type == ElementType.INDUCTOR))

    cut = {start}
    changed = True
    while changed:
        changed = False
        for e in sc.elements:
            if e.id == helper_id or not unknown_current(e):
                continue
            p, n = e.node_positive, e.node_negative
            if (p in cut) != (n in cut):
                cut.add(n if p in cut else p)
                changed = True
    return None if stop in cut else sorted(cut, key=lambda n: (len(n), n))


def _crossing_current(sc: _Ctx, e: ParsedElement) -> Tuple[Optional[complex], str]:
    """
    Kümeyi kesen elemanın akımı (n+ → n−), düğüm gerilimlerinden YENİDEN hesaplanır
    (çözücünün akımı yalnızca karşılaştırma için). (değer, terim adı); hesaplanamazsa None.
    """
    t = e.element_type

    def passive_current(x: ParsedElement) -> Optional[complex]:
        if x.element_type not in (ElementType.RESISTOR, ElementType.IMPEDANCE,
                                  ElementType.CAPACITOR, ElementType.INDUCTOR):
            return None
        if sc.is_dc and x.element_type == ElementType.CAPACITOR:
            return 0j
        z = sc.impedance(x)
        if z is None or abs(z) < 1e-15:
            return None
        return (sc.node_value(x.node_positive) - sc.node_value(x.node_negative)) / z

    if t in (ElementType.RESISTOR, ElementType.IMPEDANCE, ElementType.CAPACITOR,
             ElementType.INDUCTOR):
        return passive_current(e), f"I_{e.id}"
    if t in CURRENT_SOURCES:
        return complex(_source_value(e, sc.is_dc)), e.id
    if t in DEPENDENT_CURRENT_OUTPUT:
        p = e.params
        ctrl = next((x for x in sc.elements if x.id == p["control_id"]), None)
        if ctrl is None:
            return None, ""
        if p["control_kind"] == "V":
            cv = sc.node_value(ctrl.node_positive) - sc.node_value(ctrl.node_negative)
        elif ctrl.element_type in CURRENT_SOURCES:
            cv = complex(_source_value(ctrl, sc.is_dc))
        else:
            cv = passive_current(ctrl)
            if cv is None:
                return None, ""
        return p["gain"] * p["control_sign"] * cv, e.id
    return None, ""


def _port_equations(ctx: _Ctx, role: str) -> Optional[List[ExplanationBlock]]:
    """
    Kısa devre (role='short') ya da test kaynağı (role='test') devresinin denklemleri ve
    terminal düğümünde KCL ile Isc / I_test. Türetilen değer çözücünün sayısıyla
    uyuşmazsa ya da herhangi bir adım kurulamazsa None (çağıran eski metni yazar).
    """
    try:
        return _port_equations_unsafe(ctx, role)
    except Exception:
        return None


def _port_equations_unsafe(ctx: _Ctx, role: str) -> Optional[List[ExplanationBlock]]:
    ex = ctx.port
    if ex is None or _port(ctx) is None:
        return None
    pc = ex.sc_circuit if role == "short" else ex.test_circuit
    target = ex.isc if role == "short" else ex.i_test
    if pc is None or target is None:
        return None
    a, b = _port(ctx)

    sub = copy.deepcopy(pc.parsed)
    helper = next((e for e in sub.elements if e.id == pc.source_id), None)
    if helper is None or (helper.node_positive, helper.node_negative) != (a, b):
        return None
    helper.params = {**(helper.params or {}), "port_role": role}
    if role == "test":
        for e in sub.elements:
            if e is not helper and e.element_type in _SOURCES:
                e.params = {**(e.params or {}), "port_role": "zeroed"}

    sc = _Ctx(parsed=sub, is_dc=ctx.is_dc, frequency=ctx.frequency, omega=ctx.omega,
              analysis_type=AnalysisType.NODAL, terminals=None,
              v={str(k): complex(x) for k, x in pc.node_voltages.items()},
              i={k: complex(x) for k, x in pc.element_currents.items()},
              results=AnalysisResults())
    sc.known, sc.groups, sc.constraints = _node_groups(sub, ctx.is_dc)
    if not all(_close(val, sc.node_value(n), 1e-6) for n, val in sc.known.items()):
        return None

    # ── Düğüm denklemleri (bilinmeyen kalmadıysa yalnızca bilinen düğümler) ──
    from explainer import dependent_nodal as dn
    all_nodes = {n for e in sub.elements for n in (e.node_positive, e.node_negative)}
    secs = list(_known_nodes(sc))
    if all_nodes - set(sc.known) - {"0"}:
        built = dn.build_system(sc)
        if isinstance(built, str):
            return None
        sc.dep_system = built
        secs += dn.control_section(sc) + dn.kcl_section(sc) + dn.solve_section(sc)

    # ── KCL kümesi: + terminal ve ona gerilim kaynaklarıyla bağlı düğümler (bağlantı
    # simetrik olduğundan − terminalden denemek bir şey kazandırmaz) ──
    cut = _port_cut(sc, a, b, helper.id)
    if cut is None:
        return None
    cset = set(cut)
    # Isc (tel a → b) = kümeye GİREN akımlar; I_test (kaynaktan a'ya) = kümeden ÇIKAN akımlar
    k = 1 if role == "short" else -1
    terms = []       # (işaret, ad, değer, eleman)
    for e in sc.elements:
        if e.id == helper.id:
            continue
        p, n = e.node_positive, e.node_negative
        if (p in cset) == (n in cset):
            continue
        val, name = _crossing_current(sc, e)
        if val is None:
            return None
        if e.id not in sc.i or not _close(val, sc.i[e.id], 1e-5):
            return None
        if abs(val) < 1e-15 and (e.element_type in CURRENT_SOURCES or (
                sc.is_dc and e.element_type == ElementType.CAPACITOR)):
            continue          # açık devre: akım terimi yok
        sign = k * (1 if n in cset else -1)
        terms.append((sign, name, val, e))
    if not terms:
        return None
    total = sum(sg * v for sg, _, v, _ in terms)
    if not _close(total, target, 1e-4):
        return None

    # Toplamın tüm terimleri aynı önekle (mA gibi); AC'de elle toplanabilsin diye
    # dikdörtgensel biçimde. Sıfır olan akımlar da (Ohm yasası satırı dahil) aynı birimi alır.
    from explainer.formatting import _prefix_for
    scale, prefix = _prefix_for(max(abs(v) for _, _, v, _ in terms) or abs(target) or 1.0)
    unit = f"{prefix}A"

    # ── Akımların gösterimi: kesen pasif elemanlar + bağımlı kaynakların kontrol elemanı ──
    shown_ids = {e.id for _, _, _, e in terms
                 if e.element_type not in CURRENT_SOURCES + DEPENDENT_CURRENT_OUTPUT}
    deps = [e for _, _, _, e in terms if e.element_type in DEPENDENT_CURRENT_OUTPUT]
    for d in deps:
        ctrl = next((x for x in sc.elements if x.id == d.params["control_id"]), None)
        if (d.params["control_kind"] == "I" and ctrl is not None
                and ctrl.element_type not in CURRENT_SOURCES):
            shown_ids.add(ctrl.id)
    cur_ctx = _Ctx(parsed=sub, is_dc=sc.is_dc, frequency=sc.frequency, omega=sc.omega,
                   analysis_type=AnalysisType.NODAL, terminals=None, v=sc.v,
                   i={x: c for x, c in sc.i.items() if x in shown_ids},
                   results=AnalysisResults())
    cur_blocks = _currents(cur_ctx, passive_only=True, zero_unit=unit)[0].blocks[1:] if shown_ids else []
    chk = _dependent_check(sc, zero_i_unit=unit) if deps else []
    chk_blocks = chk[0].blocks if chk else []
    for d in deps:
        if not any(bl.kind == "math" and bl.text.startswith(f"{d.id} = ") for bl in chk_blocks):
            return None

    out = _Section("")
    if role == "short":
        out.text(f"Terminaller kısa devre edilince {node_name(a)} ile {node_name(b)} aynı gerilimde olur "
                 f"({node_v(a)} = {node_v(b)}). Bağımlı kaynak aktif kalır; bu yeni devrenin "
                 "düğüm denklemlerini kurup telden geçen akımı bulalım. Aşağıdaki düğüm "
                 "gerilimleri ve akımlar kısa devreli devreye aittir (ilk çözümdeki "
                 "değerlerden farklıdır).")
    else:
        out.text(f"Test kaynağı bağlı devrenin (V_test: {node_name(a)} (+), {node_name(b)} (−); bağımlı "
                 "kaynak aktif, bağımsız kaynaklar sıfır) düğüm denklemlerini kurup test "
                 "kaynağının akımını bulalım. Aşağıdaki düğüm gerilimleri ve akımlar bu test "
                 "devresine aittir (ilk çözümdeki değerlerden farklıdır).")
    for sec in secs:
        kept = [bl for bl in sec.blocks
                if not (bl.kind in ("text", "note") and bl.text.startswith(_PORT_SKIP))]
        if not kept:
            continue
        out.text(f"{sec.title}:")
        out.blocks.extend(kept)
    if cur_blocks:
        out.text("Bu devredeki eleman akımları (Ohm yasası):")
        out.blocks.extend(cur_blocks)
    if chk_blocks:
        out.blocks.extend(chk_blocks)

    cut_nodes_txt = (_and_list([node_name(c) for c in cut]) if "0" in cut
                     else f"Düğüm {_and_list(cut)}")
    where = (node_ek(a, "de") if len(cut) == 1 else
             f"{cut_nodes_txt} birlikte ele alınarak (aralarındaki gerilim kaynağının "
             "akımı bilinmediği için süperdüğüm)")
    if role == "short":
        lead = (f"Telden geçen akımı {where} KCL ile buluruz: elemanlardan gelen akımların "
                f"toplamı tel üzerinden {_flow_text(a, b)} akar.")
    else:
        lead = (f"Test kaynağının + ucundan ({node_name(a)}) devreye verdiği akımı {where} KCL ile "
                "buluruz: bu akım, elemanlara çıkan akımların toplamıdır.")
    place = "düğüm" if len(cut) == 1 else "süperdüğüm"
    # k = 1: gelen akımlar toplanır; k = −1: çıkan akımlar toplanır
    signs = (f"akım yönü {place}e doğru olan terim +, {place}den dışarı olan terim {MINUS}"
             if k == 1 else
             f"akım yönü {place}den dışarı olan terim +, {place}e doğru olan terim {MINUS}")
    out.text(f"{lead} Her elemanın akımı yukarıdaki yönüyle yazılır; {signs} işaretlidir"
             + (":" if ctx.is_dc else " (fazörler dikdörtgensel biçimde toplanır):"))
    sym = _join_terms([(MINUS if sg < 0 else "") + name for sg, name, _, _ in terms])

    # Birbirine yakın terimlerin farkında 4 basamak elle hesabı tutturmayabilir
    # (333,3 − 330 = 3,3 ama sonuç 3,333) → terimler gerektiği kadar basamakla
    digits = 4
    if ctx.is_dc:
        sgs = [sg for sg, _, _, _ in terms]
        digits = shown_digits([v.real / scale for _, _, v, _ in terms],
                              lambda xs: sum(g * x for g, x in zip(sgs, xs)),
                              complex(target).real / scale)

    def term_num(v: complex) -> str:
        if ctx.is_dc:
            return paren(f"{num(v.real / scale, digits)} {unit}")
        return f"({rect(v / scale, unit)})"

    # İlk terim sıfırsa "−0 A" diye başlamasın
    nums = _join_terms([(MINUS if sg < 0 and (j or abs(v) >= 1e-15) else "") + term_num(v)
                        for j, (sg, _, v, _) in enumerate(terms)])
    lhs = "Isc" if role == "short" else "I_test"
    final = ctx.val(target, "A")
    if not ctx.is_dc and abs(total) >= 1e-15:
        final = f"{rect(total / scale, unit)} = {final}"
    if len(terms) == 1 and terms[0][0] > 0:
        out.math(f"{lhs} = {sym} = {final}")
    else:
        out.math(f"{lhs} = {sym} = {nums} = {final}")
    if digits > 4 and not any(bl.text == EXTRA_DIGITS_NOTE for bl in out.blocks):
        out.note(EXTRA_DIGITS_NOTE)

    if any(pc.source_id in (bl.text or "") for bl in out.blocks):
        return None           # iç ad öğrenciye gösterilmez
    return out.blocks


def _dependent_rth(ctx: _Ctx, s: _Section, symbol: str, expected: complex,
                   zeroing_intro=None) -> bool:
    """
    Bağımlı kaynaklı devrede eşdeğer direnç (ders kitabı yöntemi): bağımlı kaynak
    SIFIRLANMAZ; Rth = Vth / In (In gerçekten kısa devre edilerek bulunmuş), bağımsız
    kaynak yoksa (Vth = In = 0) 1 V'luk test kaynağıyla Rth = V_test / I_test.
    Sayılar çözücünün Rth'siyle karşılaşmadan yazılmaz; uyuşmazsa False döner.
    """
    ex = ctx.port
    if ex is None:
        return False
    a, b = _port(ctx)
    vth = ctx.node_value(a) - ctx.node_value(b)
    dead = port_is_dead(vth, ex.isc, ctx.v, ctx.i)

    if not dead:
        if ex.isc is None or abs(ex.isc) <= 1e-15:
            return False
        if not _close(vth / ex.isc, expected, 1e-4):
            return False
        s.text(
            "Devrede bağımlı kaynak var. Bağımlı kaynak SIFIRLANMAZ: kontrol büyüklüğüne bağlı "
            "olarak devrede aktif kalır ve çıkışı terminallerden uygulanan kaynağa tepki verir; "
            "bu yüzden eşdeğer direnç seri/paralel indirgemeyle bulunamaz. Bunun yerine "
            f"{symbol} = Vth / In kullanılır: Vth açık devre gerilimi, In terminaller kısa devre "
            "edildiğinde telden geçen akımdır.")
        shown = None if ctx.isc_derived else _port_equations(ctx, "short")
        lead = ("Bu yöntemde bağımsız kaynaklar da sıfırlanmaz: Vth'yi bulduğumuz devrenin aynısında "
                f"yalnızca terminaller ({node_name(a)} ve {node_name(b)}) bir tel ile kısa devre edilir.")
        if ctx.isc_derived:
            s.text(f"{lead} Telden {_flow_text(a, b)} yönünde geçen akım, In adımında bu "
                   "devrenin denklemleriyle bulundu:")
        elif shown is not None:
            s.text(lead)
            s.blocks.extend(shown)
        else:
            s.text(f"{lead} Devre böyle yeniden çözüldüğünde telden {_flow_text(a, b)} yönünde "
                   "geçen akım:")
        s.math(f"In = Isc = {ctx.val(ex.isc, 'A')}")
        s.math(f"{symbol} = Vth / In = {ctx.val(vth, 'V')} / {paren(ctx.val(ex.isc, 'A'))}")
        s.result(f"{symbol} = {_imp_text(ctx, expected)}")
        return True

    if ex.i_test is None or abs(ex.i_test) <= 1e-15:
        return False
    if not _close(ex.v_test / ex.i_test, expected, 1e-4):
        return False
    if zeroing_intro is not None:
        zeroing_intro()
    th_sym = "Rth" if ctx.is_dc else "Zth"
    s.text(
        "Devrede bağımlı kaynak var ve bağımsız kaynak sıfırlandığında (ya da hiç yokken) "
        f"Vth = 0 ve In = 0 olur; {th_sym} = Vth / In = 0/0 belirsizdir. Bu durumda test kaynağı "
        "yöntemi kullanılır: bağımlı kaynak SIFIRLANMAZ (aktif kalır), bağımsız kaynaklar "
        "sıfırlanır ve terminallere 1 V'luk bir test kaynağı bağlanır. Kaynağın devreye "
        f"verdiği akım I_test bulunur ve {th_sym} = V_test / I_test olur.")
    s.math(f"V_test = {ctx.val(ex.v_test, 'V')}  ({node_name(a)} (+), {node_name(b)} (−))")
    shown = _port_equations(ctx, "test")
    if shown is not None:
        s.blocks.extend(shown)       # son satırı I_test = … ; aşağıdaki satır sonucu yineler
    else:
        s.text("Devre bu test kaynağıyla (bağımlı kaynak aktifken) çözüldüğünde test kaynağının + "
               f"ucundan ({node_name(a)}) devreye verdiği akım:")
    s.math(f"I_test = {ctx.val(ex.i_test, 'A')}")
    s.math(f"{symbol} = V_test / I_test = {ctx.val(ex.v_test, 'V')} / "
           f"{paren(ctx.val(ex.i_test, 'A'))}")
    s.result(f"{symbol} = {_imp_text(ctx, expected)}")
    return True


def _port_reduction_section(ctx: _Ctx, title: str, symbol: str,
                            expected: Optional[complex]) -> Tuple[_Section, bool]:
    a, b = _port(ctx)
    s = _Section(title)
    red = reduce_port_impedance(ctx.parsed, a, b, ctx.is_dc, ctx.frequency)

    def zeroing_intro() -> None:
        s.text(
            "Bağımsız kaynakları sıfırlayıp terminallerden devreye bakarız "
            "(gerilim kaynağı → kısa devre, akım kaynağı → açık devre):")
        for note_text in red.zeroing_notes:
            s.math(f"• {note_text}")

    ok = (red.complete and red.impedance is not None and expected is not None
          and _close(red.impedance, expected, 1e-4))
    # Bağımlı kaynaklıda Vth/Isc yönteminde bağımsız kaynaklar SIFIRLANMAZ: giriş
    # cümlesini kullanılan yöntem yazar (_dependent_rth)
    if ok or not (expected is not None and ctx.has_dependent):
        zeroing_intro()
    if ok:
        for step in red.steps:
            if step.kind == "series":
                s.text(f"{step.elements[0]} ve {step.elements[1]} seri bağlı "
                       "(aralarındaki düğüme başka eleman bağlı değil):")
                s.math(step.formula.replace("-", MINUS))
            elif step.kind == "parallel":
                s.text(f"{step.elements[0]} ve {step.elements[1]} aynı iki düğüm arasında, paralel:")
                s.math(step.formula.replace("-", MINUS))
            elif step.kind == "delta_y":
                tri_nodes = (", ".join(node_name(x) for x in step.nodes)
                             if "0" in step.nodes else f"Düğüm {', '.join(step.nodes)}")
                s.text(
                    f"Seri/paralel birleştirme kalmadı; {', '.join(step.elements)} "
                    f"üçgen (Δ) bağlı ({tri_nodes} arası) → "
                    "yıldıza (Y) dönüştürelim:"
                )
                for line in step.formula.splitlines():
                    s.math(line.replace("-", MINUS))
            elif step.kind == "y_delta":
                tri_nodes = (", ".join(node_name(x) for x in step.nodes)
                             if "0" in step.nodes else f"Düğüm {', '.join(step.nodes)}")
                s.text(
                    f"Seri/paralel birleştirme kalmadı; {', '.join(step.elements)} "
                    "yıldız (Y) bağlı → üçgene (Δ, "
                    f"{tri_nodes} arası) dönüştürelim:"
                )
                for line in step.formula.splitlines():
                    s.math(line.replace("-", MINUS))
            else:
                s.math(f"• {step.formula}")
        s.result(f"{symbol} = {rect(expected, 'Ω') if not ctx.is_dc else eng(expected.real, 'Ω')}")
    elif expected is not None and ctx.has_dependent:
        if not _dependent_rth(ctx, s, symbol, expected, zeroing_intro):
            zeroing_intro()
            s.text(
                "Devrede bağımlı kaynak var. Bağımlı kaynak sıfırlanmaz (devrede aktif kalır) ve "
                "çıkışı terminallerden uygulanan kaynağa tepki verir; bu yüzden eşdeğer "
                "direnç seri/paralel indirgemeyle bulunamaz. Bağımsız kaynaklar sıfırlanıp "
                "terminallere bir test kaynağı bağlanır ve Z = V_test / I_test hesaplanır "
                "(ya da Z = Voc / Isc). Çözücünün bu yöntemle bulduğu sonuç:")
            s.result(f"{symbol} = {rect(expected, 'Ω') if not ctx.is_dc else eng(expected.real, 'Ω')}")
        if expected.real < -1e-12:
            s.note("Eşdeğer direnç negatif çıktı: bağımlı kaynak terminallere enerji verir; "
                   "pasif bir devrede bu olmaz, aktif (bağımlı kaynaklı) devrede olabilir.")
    elif expected is not None:
        s.text(
            "Bu devre terminallerden bakıldığında basit seri/paralel adımlarla "
            "indirgenemiyor (ör: köprü yapısı). Bu durumda terminallere bir test "
            "kaynağı bağlanır ve Z = V_test / I_test oranı hesaplanır. Çözücünün "
            "bu yöntemle bulduğu sonuç:")
        s.result(f"{symbol} = {rect(expected, 'Ω') if not ctx.is_dc else eng(expected.real, 'Ω')}")
    return s, ok


def _thevenin(ctx: _Ctx) -> List[_Section]:
    th = ctx.results.thevenin
    if ctx.analysis_type != AnalysisType.THEVENIN or th is None or _port(ctx) is None:
        return []
    a, b = _port(ctx)
    vth = complex(th.vth.real, th.vth.imaginary)
    zth = complex(th.zth.real, th.zth.imaginary)
    sym_r = "Rth" if ctx.is_dc else "Zth"

    s1 = _Section("1. Adım — Vth (Açık Devre Gerilimi)")
    caps = [e.id for e in ctx.elements if ctx.is_dc and e.element_type == ElementType.CAPACITOR]
    if caps:
        s1.text(f"DC'de kondansatör{'ler' if len(caps) > 1 else ''} ({', '.join(caps)}) açık "
                "devredir: üzerinden akım geçmez, bu yüzden düğüm gerilimleri kondansatör "
                "devreden çıkarılmış gibi bulunur.")
    s1.text(f"Terminaller arasına hiçbir yük bağlı değilken {node_name(a)} ile {node_name(b)} "
            "arasındaki gerilim Vth'dir. Bulduğumuz düğüm gerilimlerinden:")
    derived = ctx.node_value(a) - ctx.node_value(b)
    if _close(derived, vth, 1e-4):
        s1.math(f"Vth = {node_v(a)} {MINUS} {node_v(b)} = {ctx.val(ctx.node_value(a), 'V')} "
                f"{MINUS} {paren(ctx.val(ctx.node_value(b), 'V'))}")
    s1.result(f"Vth = {ctx.val(vth, 'V')}")

    s2, _ = _port_reduction_section(ctx, f"2. Adım — {sym_r} (Eşdeğer {'Direnç' if ctx.is_dc else 'Empedans'})",
                                    sym_r, zth)

    s3 = _Section("Thevenin Eşdeğer Devresi")
    s3.result(f"Vth = {ctx.val(vth, 'V')} kaynağına seri {sym_r} = "
              f"{eng(zth.real, 'Ω') if ctx.is_dc else rect(zth, 'Ω')}")
    sections = [s1, s2, s3]

    v_scale = max((abs(x) for x in ctx.v.values()), default=0.0)
    if zth.real > 1e-12 and abs(vth) <= 1e-9 * v_scale + 1e-12:
        s4 = _Section("Maksimum Güç Transferi")
        s4.text("Vth = 0 olduğu için bu terminallere hangi yük bağlanırsa bağlansın yüke güç "
                "aktarılmaz (Pmax = 0 W); en uygun yük seçimi burada anlamsızdır.")
        sections.append(s4)
    elif zth.real > 1e-12:
        s4 = _Section("Maksimum Güç Transferi")
        if ctx.is_dc:
            pmax = abs(vth) ** 2 / (4 * zth.real)
            s4.text(f"Bu terminallere bağlanacak yük direnci RL = Rth = {eng(zth.real, 'Ω')} "
                    "seçilirse yüke en fazla güç aktarılır:")
            s4.math(f"Pmax = Vth² / (4·Rth) = ({eng(vth.real, 'V')})² / (4 · {eng(zth.real, 'Ω')}) "
                    f"= {eng(pmax, 'W')}")
        elif ctx.is_rms:
            pmax = abs(vth) ** 2 / (4 * zth.real)
            s4.text(f"Yük empedansı Zth'nin eşleniği seçilirse (ZL = Zth* = "
                    f"{rect(zth.conjugate(), 'Ω')}) yüke en fazla ortalama güç aktarılır:")
            s4.math(f"Pmax = |Vth|² / (4·Rth) = ({eng(abs(vth), 'V')})² / (4 · {eng(zth.real, 'Ω')}) "
                    f"= {eng(pmax, 'W')}")
            s4.note("Fazörler etkin (RMS) değer olduğu için payda 4·Rth'dir (tepe değerlerle 8·Rth).")
        else:
            pmax = abs(vth) ** 2 / (8 * zth.real)
            s4.text(f"Yük empedansı Zth'nin eşleniği seçilirse (ZL = Zth* = "
                    f"{rect(zth.conjugate(), 'Ω')}) yüke en fazla ortalama güç aktarılır:")
            s4.math(f"Pmax = |Vth|² / (8·Rth) = ({eng(abs(vth), 'V')})² / (8 · {eng(zth.real, 'Ω')}) "
                    f"= {eng(pmax, 'W')}")
            s4.note("Fazörler tepe değer olduğu için payda 8·Rth'dir (etkin değerlerle 4·Rth).")
        sections.append(s4)
    return sections


def _norton(ctx: _Ctx) -> List[_Section]:
    no = ctx.results.norton
    if ctx.analysis_type != AnalysisType.NORTON or no is None or _port(ctx) is None:
        return []
    a, b = _port(ctx)
    i_n = complex(no.i_n.real, no.i_n.imaginary)
    zn = complex(no.z_n.real, no.z_n.imaginary) if no.z_n is not None else None
    sym_r = "Rn" if ctx.is_dc else "Zn"
    vth = ctx.node_value(a) - ctx.node_value(b)

    conversion = (not ctx.has_dependent and zn is not None and abs(zn) > 1e-15
                  and _close(vth / zn, i_n, 1e-4))
    # Dönüşümle bulunuyorsa önce Rn, sonra In = Vth / Rn: Rn bulunmadan kullanılmasın
    n_in, n_rn = (2, 1) if conversion else (1, 2)
    s1 = _Section(f"{n_in}. Adım — In (Kısa Devre Akımı)")
    s1.text(f"Terminaller ({node_name(a)} ve {node_name(b)}) bir tel ile kısa devre edildiğinde "
            "telden akan akım In'dir.")
    if ctx.has_dependent:
        # Bağımlı kaynak aktif kalır; In = Vth/Rn dönüşümü burada döngüsel olurdu
        # (Rn de In'den bulunur). Kısa devre akımı gerçekten kısa devre edilerek bulundu.
        if ctx.port is not None and ctx.port.isc is not None and _close(ctx.port.isc, i_n, 1e-4):
            s1.text("Devrede bağımlı kaynak var; bağımlı kaynak aktif kalır. Terminaller "
                    "kısa devre edilip devre bu hâliyle yeniden çözüldüğünde telden "
                    f"{_flow_text(a, b)} yönünde geçen akım In'dir.")
            # Ölü portta (Vth = In = 0) sıfırların uzun türetmesi gösterilmez
            dead = port_is_dead(vth, ctx.port.isc, ctx.v, ctx.i)
            shown = None if dead else _port_equations(ctx, "short")
            if shown is not None:
                s1.blocks.extend(shown)
                ctx.isc_derived = True
    elif conversion:
        s1.text(f"{sym_r} bir önceki adımda bulundu. Thevenin–Norton dönüşümüyle: önce açık devre "
                f"gerilimi Vth = {node_v(a)} {MINUS} {node_v(b)} = {ctx.val(vth, 'V')}, sonra:")
        if ctx.is_dc:
            s1.math(f"In = Vth / {sym_r} = {eng(vth.real, 'V')} / {eng(zn.real, 'Ω')}")
        else:
            s1.math(f"In = Vth / {sym_r} = {polar(vth, 'V')} / {polar(zn, 'Ω')}")
    s1.result(f"In = {ctx.val(i_n, 'A')}")

    sections = [s1]
    if zn is not None:
        s2, _ = _port_reduction_section(ctx, f"{n_rn}. Adım — {sym_r} (Norton {'Direnci' if ctx.is_dc else 'Empedansı'})",
                                        sym_r, zn)
        s2.note(f"Norton empedansı Thevenin empedansıyla aynıdır: {sym_r} = Rth.")
        if conversion:
            sections.insert(0, s2)
        else:
            sections.append(s2)

    s3 = _Section("Norton Eşdeğer Devresi")
    if zn is None:
        s3.result(f"In = {ctx.val(i_n, 'A')} değerinde ideal akım kaynağı ({sym_r} = ∞)")
    else:
        s3.result(f"In = {ctx.val(i_n, 'A')} akım kaynağına paralel {sym_r} = "
                  f"{eng(zn.real, 'Ω') if ctx.is_dc else rect(zn, 'Ω')}")
    sections.append(s3)
    return sections
