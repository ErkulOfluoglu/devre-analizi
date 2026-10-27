"""
CircuitAnalyzer API — Alıştırma modu soruları

Seçilen yönteme göre öğrenciye sorulacak büyüklükler:

    NODAL          asıl: bilinmeyen düğüm gerilimleri   ek: eleman akımları, toplam P
    MESH           asıl: bilinmeyen çevre akımları      ek: eleman akımları, toplam P
    THEVENIN       asıl: Vth, Rth (Zth)                 ek: Pmax
    NORTON         asıl: In, Rn (Zn)
    SUPERPOSITION  asıl: her kaynağın katkısı ve toplam (bilinmeyen düğümlerde)

Doğru değerler çözücünün sonuçlarından alınır (anlatımla aynı sayılar).
İpuçları cevabı vermez; yalnızca yöntemi hatırlatır.
"""

from typing import Callable, Dict, List, Optional

from explainer.formatting import node_v
from explainer.mesh_narrative import mesh_symbol
from explainer.step_generator import _node_groups
from explainer.superposition_narrative import mark
from models.request import AnalysisType, TheveninTerminals
from models.response import (
    AnalysisResults, ComplexNumber, PracticeAlternative, PracticeQuestion,
)
from parser.netlist_parser import (
    CURRENT_SOURCES, DEPENDENT_CURRENT_CONTROLLED, DEPENDENT_SOURCES,
    DEPENDENT_VOLTAGE_OUTPUT, ElementType, ParsedCircuit,
)

_PASSIVE = (ElementType.RESISTOR, ElementType.CAPACITOR,
            ElementType.INDUCTOR, ElementType.IMPEDANCE)

MAX_SUPERPOSITION_NODES = 3

_ZERO_SOURCES = ("Diğer kaynakları sıfırlayın (gerilim kaynağı → kısa devre, "
                 "akım kaynağı → açık devre)")

# Bağımlı kaynaklı devrede eşdeğer direnç: bağımlı kaynak sıfırlanmaz
_DEP_RTH_HINT = ("Yalnızca bağımsız kaynakları sıfırlayın; bağımlı kaynak SIFIRLANMAZ (aktif kalır), "
                 "bu yüzden seri/paralel indirgeme yetmez. Rth = Vth / In: terminalleri kısa devre "
                 "edip In'i bulun. Bağımsız kaynak yoksa (Vth = In = 0) terminallere 1 V'luk bir "
                 "test kaynağı bağlayıp Rth = 1 V / I_test hesaplayın.")
_DEP_RTH_SIGN = ("İşaret ters olabilir: bağımlı kaynaklı (aktif) devrede eşdeğer direnç negatif "
                 "çıkabilir. Rth = Vth / In oranını işaretleriyle hesaplayın.")


def _dependent_hint(parsed: ParsedCircuit, is_dc: bool) -> str:
    """
    Bağımlı kaynaklı devrelerde ipuçlarına eklenen cümle: kontrol büyüklüğü düğüm
    gerilimleriyle yazılır. Kontrol akımı düğüm gerilimleriyle yazılamıyorsa (bir
    gerilim/bağımlı kaynağın ya da DC'de bobinin akımı) bunu da söyler.
    """
    deps = [e for e in parsed.elements if e.element_type in DEPENDENT_SOURCES]
    if not deps:
        return ""
    text = (" Devrede bağımlı kaynak var: kontrol büyüklüğünü (V_X ya da I_X) önce düğüm "
            "gerilimleriyle yazın; bağımlı akım kaynağı KCL'de kazanç · kontrol büyüklüğü "
            "kadar bir akım terimi getirir.")
    by_id = {e.id: e for e in parsed.elements}
    for e in deps:
        if e.element_type not in DEPENDENT_CURRENT_CONTROLLED:
            continue
        ctrl = by_id.get(e.params.get("control_id"))
        if ctrl is None:
            continue
        no_node_form = (ctrl.element_type in DEPENDENT_SOURCES
                        or (ctrl.element_type not in CURRENT_SOURCES
                            and ctrl.element_type not in _PASSIVE)
                        or (is_dc and ctrl.element_type == ElementType.INDUCTOR))
        if no_node_form:
            return text + (" Kontrol akımı bir gerilim kaynağından (ya da DC'de bobinden) "
                           "geçiyorsa bu akım düğüm gerilimleriyle yazılamaz; kaynağa bağlı "
                           "diğer elemanların akımlarından KCL ile bulun ya da çevre akımları "
                           "yöntemini kullanın.")
    return text


def _node_key(n: str):
    return (len(n), n)


def _node_name(n: str) -> str:
    return "GND" if n == "0" else f"Düğüm {n}"


def build_questions(
    parsed: ParsedCircuit,
    is_dc: bool,
    frequency: Optional[float],
    analysis_type: AnalysisType,
    terminals: Optional[TheveninTerminals],
    raw_nodes: Dict[str, complex],
    raw_currents: Dict[str, complex],
    results: AnalysisResults,
    to_cn: Callable[[complex], ComplexNumber],
    mesh_analysis=None,
    contributions=None,
) -> List[PracticeQuestion]:
    """
    Alıştırma sorularını üretir. to_cn: complex → ComplexNumber
    (solver.circuit_solver.make_complex_number; döngüsel içe aktarmayı önler).
    """
    nodes = {str(k): complex(v) for k, v in raw_nodes.items()}
    currents = {k: complex(v) for k, v in raw_currents.items()}
    if len(nodes) <= 1:
        return []
    has_dep = any(e.element_type in DEPENDENT_SOURCES for e in parsed.elements)
    dep_hint = _dependent_hint(parsed, is_dc)
    dep_volt_nodes = {}      # düğüm → o düğüme bağlı bağımlı gerilim kaynakları (E, H)
    for e in parsed.elements:
        if e.element_type in DEPENDENT_VOLTAGE_OUTPUT:
            for n in (e.node_positive, e.node_negative):
                dep_volt_nodes.setdefault(n, []).append(e.id)

    freq = None if is_dc else frequency
    v_scale = max((abs(v) for v in nodes.values()), default=1.0) or 1.0
    i_scale = max((abs(i) for i in currents.values()), default=1.0) or 1.0
    known, _, _ = _node_groups(parsed, is_dc)
    unknown_nodes = sorted((n for n in nodes if n != "0" and n not in known), key=_node_key)

    def q(id_, label, description, unit, group, expected, scale, hint, sign_hint,
          alternatives=(), is_ac=not is_dc, frequency=freq) -> PracticeQuestion:
        exp = complex(expected)
        alts = [PracticeAlternative(value=to_cn(v), message=m) for v, m in alternatives
                if abs(complex(v) - exp) > 0.02 * max(abs(exp), 1e-3 * scale, 1e-12)]
        return PracticeQuestion(
            id=id_, label=label, description=description, unit=unit, group=group,
            is_ac=is_ac, frequency=frequency if is_ac else None, expected=to_cn(exp), scale=scale,
            hint=hint, sign_hint=sign_hint, alternatives=alts,
        )

    # ── Ortak soru üreticileri ──
    def node_hint(n: str) -> str:
        if n in dep_volt_nodes:
            ids = ", ".join(dep_volt_nodes[n])
            return (f"{_node_name(n)}, bağımlı gerilim kaynağının ({ids}) ucunda: kaynağın akımı "
                    "bilinmediği için bu düğümde KCL yerine kaynağın kısıtını yazın "
                    "(V₊ − V₋ = kazanç · kontrol büyüklüğü); iki ucu da bilinmeyen düğümse "
                    "iki düğümü süperdüğüm olarak ele alın." + dep_hint)
        return (f"{_node_name(n)} için KCL yazın: düğümden çıkan akımların toplamı sıfırdır "
                "(her kol için (V_düğüm − V_komşu)/Z). Bilinen düğüm gerilimlerini yerine koyun."
                + dep_hint)

    def node_questions(group: str) -> List[PracticeQuestion]:
        return [q(
            f"V{n}", node_v(n), f"{_node_name(n)} gerilimi (GND'ye göre)", "V", group,
            nodes[n], v_scale,
            hint=node_hint(n),
            sign_hint=("İşaret ters. Düğüm gerilimi GND'ye göre ölçülür; "
                       f"{node_v(n)} = V({n}) − V(GND)."),
        ) for n in unknown_nodes]

    def current_questions(group: str) -> List[PracticeQuestion]:
        out = []
        for e in parsed.elements:
            if e.element_type not in _PASSIVE or e.id not in currents:
                continue
            if is_dc and e.element_type == ElementType.CAPACITOR:
                continue   # DC'de kondansatör akımı her zaman 0 — soru değil
            p, n = e.node_positive, e.node_negative
            z_word = "R" if e.element_type == ElementType.RESISTOR and is_dc else "Z"
            out.append(q(
                f"I_{e.id}", f"I_{e.id}",
                f"{e.id} elemanından {_node_name(p)} → {_node_name(n)} yönünde geçen akım",
                "A", group, currents[e.id], i_scale,
                hint=(f"Ohm yasası: I_{e.id} = (V({p}) − V({n})) / {z_word}_{e.id}. "
                      "Önce elemanın iki ucundaki düğüm gerilimlerini bulun." + dep_hint),
                sign_hint=(f"İşaret ters: akım {_node_name(p)} → {_node_name(n)} yönünde pozitif "
                           "alınıyor; siz ters yönü hesaplamış olabilirsiniz."),
            ))
        return out

    def power_questions(group: str) -> List[PracticeQuestion]:
        pw = results.power
        if pw is None:
            return []
        s_abs = complex(pw.total_absorbed.real, pw.total_absorbed.imaginary)
        p_total = s_abs.real
        if p_total <= 1e-15:
            return []
        alts = []
        if not is_dc:
            alts.append((abs(s_abs), "Bu görünür güç |S| (birimi VA). Aktif güç P = |S|·cos φ "
                                     "ya da dirençlerdeki güçlerin toplamıdır."))
            alts.append((2 * p_total, "Fazörler tepe değer olduğundan P = ½·Vm·Im·cos φ; "
                                      "½ çarpanını unutmuş olabilirsiniz."))
            if abs(s_abs.imag) > 1e-15:
                alts.append((abs(s_abs.imag), "Bu reaktif güç Q (birimi VAR). Aktif güç P soruluyor."))
        return [q(
            "P_TOTAL", "P", "Dirençlerde harcanan toplam aktif güç (kaynakların verdiği güç)",
            "W", group, p_total, p_total,
            hint=("Her direncin gücünü bulup toplayın: DC'de P = I²·R; AC'de (tepe değerlerle) "
                  "P = ½·|I|²·R. Bobin ve kondansatör aktif güç harcamaz."),
            sign_hint="Harcanan güç pozitiftir.",
            alternatives=alts, is_ac=False,
        )]

    # ── Yönteme göre sorular ──
    questions: List[PracticeQuestion] = []

    if analysis_type == AnalysisType.SUPERPOSITION and contributions:
        return _superposition_questions(q, contributions, unknown_nodes, v_scale, has_dep)

    if analysis_type == AnalysisType.THEVENIN and results.thevenin is not None and terminals:
        a, b = terminals.node_positive, terminals.node_negative
        th = results.thevenin
        vth = complex(th.vth.real, th.vth.imaginary)
        zth = complex(th.zth.real, th.zth.imaginary)
        sym_r = "Rth" if is_dc else "Zth"
        questions.append(q(
            "VTH", "Vth", f"{_node_name(a)} ile {_node_name(b)} arasındaki Thevenin gerilimi",
            "V", "main", vth, max(abs(vth), v_scale),
            hint=(f"Terminaller açık devreyken {_node_name(a)} ile {_node_name(b)} arasındaki "
                  f"gerilimi bulun: Vth = V({a}) − V({b})." + dep_hint),
            sign_hint=f"İşaret ters: Vth = V({a}) − V({b}); + terminal {_node_name(a)}.",
        ))
        questions.append(q(
            sym_r.upper(), sym_r, f"Terminallerden bakıldığında eşdeğer "
                                  f"{'direnç' if is_dc else 'empedans'}",
            "Ω", "main", zth, max(abs(zth), 1.0),
            hint=(_DEP_RTH_HINT if has_dep else
                  f"{_ZERO_SOURCES.replace('Diğer k', 'Tüm bağımsız k')} ve terminallerden bakarak "
                  "seri/paralel indirgemeyle eşdeğeri bulun."),
            sign_hint=_DEP_RTH_SIGN if has_dep else "Pasif devrenin eşdeğer direnci negatif olamaz.",
        ))
        if zth.real > 1e-12:
            if is_dc:
                pmax = abs(vth) ** 2 / (4 * zth.real)
                alts = [(abs(vth) ** 2 / zth.real, "Pmax formülünde payda 4·Rth'dir: "
                                                   "Pmax = Vth² / (4·Rth).")]
                hint = "Yük direnci RL = Rth seçildiğinde güç en büyük olur: Pmax = Vth² / (4·Rth)."
            else:
                pmax = abs(vth) ** 2 / (8 * zth.real)
                alts = [(abs(vth) ** 2 / (4 * zth.real),
                         "Fazörler tepe değer olduğundan payda 8·Rth'dir (etkin değerlerle 4·Rth).")]
                hint = ("Yük empedansı ZL = Zth* (eşlenik) seçildiğinde ortalama güç en büyük olur: "
                        "Pmax = |Vth|² / (8·Rth), Rth = Zth'nin gerçel kısmı.")
            questions.append(q(
                "PMAX", "Pmax", "Bu terminallere bağlanacak yüke aktarılabilecek en büyük güç",
                "W", "extra", pmax, pmax, hint=hint,
                sign_hint="Güç pozitiftir.", alternatives=alts, is_ac=False,
            ))
        return questions

    if analysis_type == AnalysisType.NORTON and results.norton is not None and terminals:
        a, b = terminals.node_positive, terminals.node_negative
        no = results.norton
        i_n = complex(no.i_n.real, no.i_n.imaginary)
        questions.append(q(
            "IN", "In", f"{_node_name(a)} ile {_node_name(b)} kısa devre edildiğinde "
                        "kısa devreden geçen akım (Norton akımı)",
            "A", "main", i_n, max(abs(i_n), i_scale),
            hint=("Terminalleri bir telle kısa devre edip telden geçen akımı bulun "
                  + ("(bağımlı kaynak devrede aktif kalır; In'i Vth / Rth'den türetmek "
                     "döngüsel olur)." if has_dep else
                     "(ya da önce Vth ve Rth'yi bulup In = Vth / Rth).") + dep_hint),
            sign_hint=(f"İşaret ters: In, kısa devre telinde {_node_name(a)} → {_node_name(b)} "
                       "yönünde pozitif alınır (In = Vth / Rth, Vth = V(+) − V(−))."),
        ))
        if no.z_n is not None:
            zn = complex(no.z_n.real, no.z_n.imaginary)
            sym_r = "Rn" if is_dc else "Zn"
            questions.append(q(
                sym_r.upper(), sym_r, f"Norton {'direnci' if is_dc else 'empedansı'}",
                "Ω", "main", zn, max(abs(zn), 1.0),
                hint=(_DEP_RTH_HINT + " (Rn = Rth)" if has_dep else
                      f"{_ZERO_SOURCES.replace('Diğer k', 'Tüm bağımsız k')} ve terminallerden "
                      "bakarak eşdeğeri bulun (Rn = Rth)."),
                sign_hint=_DEP_RTH_SIGN if has_dep else "Pasif devrenin eşdeğer direnci negatif olamaz.",
            ))
        return questions

    mesh_ok = (analysis_type == AnalysisType.MESH and mesh_analysis is not None
               and mesh_analysis.ok and results.meshes
               and all(eid in currents and abs(ib - currents[eid]) <= 1e-6 * max(abs(currents[eid]), 1e-9)
                       for eid, ib in mesh_analysis.branch_currents.items()))
    if mesh_ok:
        from explainer.mesh_narrative import _sign_map
        signs = _sign_map(mesh_analysis)
        known_meshes = {next(iter(signs[cid])) for cid in mesh_analysis.currents_cs
                        if len(signs.get(cid, {})) == 1}
        for m in mesh_analysis.meshes:
            if m.index in known_meshes:
                continue
            k = m.index
            way = ("saat yönünde" if mesh_analysis.clockwise
                   else f"{' → '.join(m.nodes)} düğüm sırası yönünde")
            questions.append(q(
                f"MESH{k}", mesh_symbol(k), f"Çevre {k} akımı ({way})", "A", "main",
                mesh_analysis.mesh_currents[k - 1], i_scale,
                hint=(f"Çevre {k} için KVL yazın: çevre boyunca gerilimlerin toplamı sıfırdır. "
                      "Ortak kollarda iki çevre akımının farkı akar; akım kaynaklı kollarda "
                      "çevre akımı kaynaktan bilinir."
                      + (" Bağımlı kaynağın kontrol büyüklüğünü (V_X ya da I_X) çevre akımlarıyla "
                         "yazın; bağımlı kaynak KVL'de kazanç · kontrol büyüklüğü kadar bir "
                         "gerilim terimi getirir." if has_dep else "")),
                sign_hint=f"İşaret ters: {mesh_symbol(k)} akımı {way} pozitif alınıyor.",
            ))
        questions += current_questions("extra")
        questions += power_questions("extra")
        return questions

    # NODAL (ve çevre yöntemi uygulanamadığında)
    main = node_questions("main")
    if main:
        questions += main
        questions += current_questions("extra")
    else:
        questions += current_questions("main")
    questions += power_questions("extra")
    return questions


def _superposition_questions(q, contributions, unknown_nodes, v_scale,
                             has_dep: bool = False) -> List[PracticeQuestion]:
    ok = [(k, c) for k, c in enumerate(contributions, 1) if not c.error]
    if not ok:
        return []
    targets = unknown_nodes[:MAX_SUPERPOSITION_NODES]
    freqs = {c.frequency_key for _, c in ok}
    single_freq = len(freqs) == 1
    out: List[PracticeQuestion] = []
    for n in targets:
        if not all(n in c.node_voltages for _, c in ok):
            continue
        total = sum(c.node_voltages[n] for _, c in ok)
        for k, c in ok:
            src = c.source.id
            contrib = c.node_voltages[n]
            alts = []
            if single_freq:
                alts.append((total, f"Bu toplam değer. Burada yalnız {src} aktifken oluşan "
                                    "katkı soruluyor."))
            domain = "" if c.is_dc else f" ({c.frequency:g} Hz fazörü)"
            out.append(q(
                f"V{n}_{src}", f"{node_v(n)}{mark(k)}",
                f"Yalnız {src} aktifken {_node_name(n)} gerilimi{domain}", "V", "main",
                contrib, v_scale,
                hint=(f"{_ZERO_SOURCES}, yalnız {src} kalsın; bu devrede {_node_name(n)} "
                      "gerilimini bulun."
                      + (" Bağımlı kaynaklar sıfırlanmaz: her adımda aktif kalır, kontrol "
                         "büyüklükleri o alt devrede yeniden hesaplanır." if has_dep else "")),
                sign_hint=(f"İşaret ters. Kaynağın ({src}) kutuplarını ve {node_v(n)} "
                           "geriliminin GND'ye göre ölçüldüğünü kontrol edin."),
                alternatives=alts, is_ac=not c.is_dc,
                frequency=None if c.is_dc else c.frequency,
            ))
        if single_freq:
            is_dc_total = ok[0][1].is_dc
            alts = [(c.node_voltages[n], f"Bu yalnızca {c.source.id} katkısı; tüm kaynakların "
                                         "katkılarını işaretleriyle toplayın.") for _, c in ok]
            marks = " + ".join(f"{node_v(n)}{mark(k)}" for k, _ in ok)
            out.append(q(
                f"V{n}", node_v(n), f"Tüm kaynaklar birlikteyken {_node_name(n)} gerilimi",
                "V", "main", total, v_scale,
                hint=f"Katkıları işaretleriyle toplayın: {node_v(n)} = {marks}.",
                sign_hint="İşaret ters. Katkıları işaretleriyle birlikte toplayın.",
                alternatives=alts, is_ac=not is_dc_total,
                frequency=None if is_dc_total else ok[0][1].frequency,
            ))
    return out
