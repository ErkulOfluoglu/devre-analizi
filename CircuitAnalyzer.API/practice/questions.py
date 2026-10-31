"""
CircuitAnalyzer API — Alıştırma modu soruları

Seçilen yönteme göre öğrenciye sorulacak büyüklükler:

    NODAL          asıl: bilinmeyen düğüm gerilimleri   ek: eleman akımları, toplam P
    MESH           asıl: bilinmeyen çevre akımları      ek: eleman akımları, toplam P
    THEVENIN       asıl: Vth, Rth (Zth)                 ek: Pmax
    NORTON         asıl: In, Rn (Zn)
    SUPERPOSITION  asıl: her kaynağın katkısı ve toplam (bilinmeyen düğümlerde)
    POWER          asıl: toplam P, Q, S, cos φ (ve kompanzasyon varsa Q_C, C)
    RESONANCE      asıl: f₀, Q, BW, rezonanstaki akım (seri) / empedans (paralel)   ek: f₁, f₂
    TRANSFORMER    ideal: V₂, I₁, I₂, yansıyan empedans Z₁   kuplajlı: M, I₁, I₂
                   (transformatörlü devrede yöntem ne seçilirse seçilsin bu sorular sorulur)

Doğru değerler çözücünün sonuçlarından alınır (anlatımla aynı sayılar).
İpuçları cevabı vermez; yalnızca yöntemi hatırlatır.
"""

import math
from typing import Callable, Dict, List, Optional

from explainer.formatting import node_v, num
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

from solver.three_phase import PHASES

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
    # Transformatörlü devrede düğüm denklemi soruları iki uçlu eleman varsayar: atlanır
    known, _, _ = (_node_groups(parsed, is_dc) if results.transformer is None else ({}, None, None))
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

    if results.transformer is not None:
        return _transformer_questions(q, results.transformer)

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
        is_rms = getattr(parsed, "value_basis", "PEAK") == "RMS"
        alts = []
        if not is_dc:
            alts.append((abs(s_abs), "Bu görünür güç |S| (birimi VA). Aktif güç P = |S|·cos φ "
                                     "ya da dirençlerdeki güçlerin toplamıdır."))
            if is_rms:
                alts.append((0.5 * p_total, "Fazörler etkin (RMS) değer olduğundan P = V·I·cos φ = |I|²·R "
                                            "(½ çarpanı tepe değerler içindir)."))
                alts.append((2 * p_total, "Etkin değerlerle P = |I|²·R (2 çarpanı yoktur)."))
            else:
                alts.append((2 * p_total, "Fazörler tepe değer olduğundan P = ½·Vm·Im·cos φ; "
                                          "½ çarpanını unutmuş olabilirsiniz."))
            if abs(s_abs.imag) > 1e-15:
                alts.append((abs(s_abs.imag), "Bu reaktif güç Q (birimi VAR). Aktif güç P soruluyor."))
        if is_rms and not is_dc:
            p_hint = ("Her direncin gücünü bulup toplayın: etkin (RMS) değerlerle P = |I|²·R "
                      "(tepe değerlerle P = ½·|Im|²·R). Bobin ve kondansatör aktif güç harcamaz.")
        else:
            p_hint = ("Her direncin gücünü bulup toplayın: DC'de P = I²·R; AC'de (tepe değerlerle) "
                      "P = ½·|I|²·R. Bobin ve kondansatör aktif güç harcamaz.")
        return [q(
            "P_TOTAL", "P", "Dirençlerde harcanan toplam aktif güç (kaynakların verdiği güç)",
            "W", group, p_total, p_total,
            hint=p_hint,
            sign_hint="Harcanan güç pozitiftir.",
            alternatives=alts, is_ac=False,
        )]

    # ── Yönteme göre sorular ──
    questions: List[PracticeQuestion] = []

    if analysis_type == AnalysisType.POWER and results.power_summary is not None:
        return _power_method_questions(q, parsed, results.power_summary)

    if analysis_type == AnalysisType.RESONANCE and results.resonance is not None:
        return _resonance_questions(q, parsed, results.resonance, to_cn)

    if analysis_type == AnalysisType.SUPERPOSITION and contributions:
        return _superposition_questions(q, contributions, unknown_nodes, v_scale, has_dep)

    if analysis_type in (AnalysisType.THEVENIN, AnalysisType.SOURCE_TRANSFORM) and results.thevenin is not None and terminals:
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
            is_rms = getattr(parsed, "value_basis", "PEAK") == "RMS"
            if is_dc:
                pmax = abs(vth) ** 2 / (4 * zth.real)
                alts = [(abs(vth) ** 2 / zth.real, "Pmax formülünde payda 4·Rth'dir: "
                                                   "Pmax = Vth² / (4·Rth).")]
                hint = "Yük direnci RL = Rth seçildiğinde güç en büyük olur: Pmax = Vth² / (4·Rth)."
            elif is_rms:
                pmax = abs(vth) ** 2 / (4 * zth.real)
                alts = [
                    (abs(vth) ** 2 / (8 * zth.real),
                     "Fazörler etkin (RMS) değer olduğundan payda 4·Rth'dir (tepe değerlerle 8·Rth)."),
                    (abs(vth) ** 2 / zth.real,
                     "Pmax formülünde payda 4·Rth'dir: Pmax = |Vth|² / (4·Rth)."),
                ]
                hint = ("Yük empedansı ZL = Zth* (eşlenik) seçildiğinde ortalama güç en büyük olur: "
                        "Pmax = |Vth|² / (4·Rth), Rth = Zth'nin gerçel kısmı.")
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


def _power_method_questions(q, parsed: ParsedCircuit, ps) -> List[PracticeQuestion]:
    """POWER yönteminde alıştırma soruları: P, Q, S, cos φ ve varsa Q_C, C."""
    is_rms = getattr(parsed, "value_basis", "PEAK") == "RMS"
    s_scale = max(abs(ps.s), abs(ps.p), abs(ps.q), 1.0)
    out: List[PracticeQuestion] = []

    p_alts = [(ps.s, "Bu görünür güç S (birimi VA). Aktif güç P = S·cos φ ya da dirençlerdeki güçlerin toplamıdır.")]
    if abs(ps.q) > 1e-15:
        p_alts.append((abs(ps.q), "Bu reaktif güç |Q| (birimi VAR). Aktif güç P soruluyor."))
    if is_rms:
        p_alts.append((0.5 * ps.p, "Fazörler etkin (RMS) değer olduğundan P = V·I·cos φ = |I|²·R (½ çarpanı tepe değerler içindir)."))
        p_alts.append((2.0 * ps.p, "Etkin değerlerle P = |I|²·R (2 çarpanı yoktur)."))
        p_hint = "Aktif güç P = V·I·cos φ ya da dirençlerde harcanan güçlerin toplamı P = Σ(|I|²·R)."
    else:
        p_alts.append((2.0 * ps.p, "Fazörler tepe değer olduğundan P = ½·Vm·Im·cos φ; ½ çarpanını unutmuş olabilirsiniz."))
        p_alts.append((0.5 * ps.p, "½ çarpanını iki kez uygulamış olabilirsiniz; P = ½·Vm·Im·cos φ."))
        p_hint = "Fazörler tepe değer olduğundan aktif güç P = ½·Vm·Im·cos φ = Σ(½·|Im|²·R)."

    out.append(q(
        "P_TOTAL", "P", "Kaynakların verdiği toplam aktif güç",
        "W", "main", ps.p, s_scale,
        hint=p_hint,
        sign_hint="Dirençlerde harcanan (kaynakların verdiği) aktif güç pozitiftir.",
        alternatives=p_alts, is_ac=False,
    ))

    q_alts = [
        (ps.s, "Bu görünür güç S (birimi VA). Reaktif güç Q = S·sin φ soruluyor."),
        (ps.p, "Bu aktif güç P (birimi W). Reaktif güç Q soruluyor."),
    ]
    if is_rms:
        q_alts.append((0.5 * ps.q, "Fazörler etkin (RMS) değer olduğundan Q = V·I·sin φ = |I|²·X (½ çarpanı tepe değerler içindir)."))
        q_alts.append((2.0 * ps.q, "Etkin değerlerle Q = |I|²·X (2 çarpanı yoktur)."))
        q_hint = "Toplam reaktif güç Q = V·I·sin φ = Σ Q_L − Σ |Q_C| (bobinde Q > 0, kondansatörde Q < 0)."
    else:
        q_alts.append((2.0 * ps.q, "Fazörler tepe değer olduğundan Q = ½·Vm·Im·sin φ; ½ çarpanını unutmuş olabilirsiniz."))
        q_alts.append((0.5 * ps.q, "½ çarpanını iki kez uygulamış olabilirsiniz; Q = ½·Vm·Im·sin φ."))
        q_hint = "Fazörler tepe değer olduğundan toplam reaktif güç Q = ½·Vm·Im·sin φ (bobinde Q > 0, kondansatörde Q < 0)."

    out.append(q(
        "Q_TOTAL", "Q", "Kaynakların verdiği toplam reaktif güç",
        "VAR", "main", ps.q, s_scale,
        hint=q_hint,
        sign_hint="İşaret ters: endüktif (geri) devrede Q > 0, kapasitif (ileri) devrede Q < 0 alınır.",
        alternatives=q_alts, is_ac=False,
    ))

    s_alts = [(ps.p, "Bu aktif güç P (birimi W). Görünür güç S = √(P² + Q²) soruluyor.")]
    if abs(ps.q) > 1e-15:
        s_alts.append((abs(ps.q), "Bu reaktif güç |Q| (birimi VAR). Görünür güç S = √(P² + Q²) soruluyor."))
    if is_rms:
        s_alts.append((0.5 * ps.s, "Fazörler etkin (RMS) değer olduğundan S = V·I = √(P² + Q²) (½ çarpanı tepe değerler içindir)."))
        s_alts.append((2.0 * ps.s, "Etkin değerlerle S = V·I (2 çarpanı yoktur)."))
        s_hint = "Görünür güç S = √(P² + Q²) (tek kaynaklı devrede etkin değerlerle S = V·I)."
    else:
        s_alts.append((2.0 * ps.s, "Fazörler tepe değer olduğundan S = ½·Vm·Im = √(P² + Q²); ½ çarpanını unutmuş olabilirsiniz."))
        s_alts.append((0.5 * ps.s, "½ çarpanını iki kez uygulamış olabilirsiniz; S = ½·Vm·Im."))
        s_hint = "Görünür güç S = √(P² + Q²) (tek kaynaklı devrede tepe değerlerle S = ½·Vm·Im)."

    out.append(q(
        "S_TOTAL", "S", "Kaynakların verdiği toplam görünür güç",
        "VA", "main", ps.s, s_scale,
        hint=s_hint,
        sign_hint="Görünür güç S = √(P² + Q²) büyüklüktür ve her zaman pozitiftir.",
        alternatives=s_alts, is_ac=False,
    ))

    pf_alts = []
    if ps.s > 1e-15 and abs(ps.q) > 1e-15:
        pf_alts.append((abs(ps.q) / ps.s, "Bu sin φ = |Q|/S değeri; güç katsayısı cos φ = P/S soruluyor."))
    if abs(ps.p) > 1e-15 and abs(ps.q) > 1e-15:
        pf_alts.append((abs(ps.q / ps.p), "Bu tan φ = |Q|/P değeri; güç katsayısı cos φ = P/S soruluyor."))
    if abs(ps.phi_deg) > 1.0:
        pf_alts.append((abs(ps.phi_deg), "Bu faz açısı φ (derece); güç katsayısı cos φ = P/S (birimsiz oran) soruluyor."))

    out.append(q(
        "COS_PHI", "cos φ", "Devrenin güç katsayısı (cos φ = P/S, birimsiz)",
        "", "main", ps.pf, 1.0,
        hint="Güç katsayısı cos φ = P / S (aktif gücün görünür güce oranı, 0 ile 1 arasında birimsizdir).",
        sign_hint="Güç katsayısı cos φ = P / S pozitiftir.",
        alternatives=pf_alts, is_ac=False,
    ))

    if ps.compensation is not None and ps.compensation.applied:
        comp = ps.compensation
        qc_alts = [
            (ps.q, "Bu devrenin mevcut reaktif gücü Q. Kompanzasyon için Q_C = P·(tan φ₁ − tan φ₂) hesaplanmalıdır."),
        ]
        if is_rms:
            qc_alts.append((0.5 * comp.q_c, "P zaten etkin güçtür; Q_C = P·(tan φ₁ − tan φ₂) formülünde ½ çarpanı yoktur."))
        else:
            qc_alts.append((2.0 * comp.q_c, "Tepe değerlerle P hesaplanırken ½ çarpanı unutulmuş olabilir; Q_C = P·(tan φ₁ − tan φ₂)."))

        out.append(q(
            "Q_C", "Q_C", f"Güç katsayısını cos φ₂ = {num(comp.target_pf, 4)} yapmak için gerekli kapasitif reaktif güç",
            "VAR", "main", comp.q_c, max(abs(comp.q_c), abs(ps.q), 1.0),
            hint=f"Hedef cos φ₂ = {num(comp.target_pf, 4)} için φ₂ = arccos(cos φ₂) açısını bulun; Q_C = P·(tan φ₁ − tan φ₂).",
            sign_hint="Kondansatörün karşılayacağı reaktif güç büyüklüğü Q_C pozitif yazılır: Q_C = P·(tan φ₁ − tan φ₂).",
            alternatives=qc_alts, is_ac=False,
        ))

        c_alts = [
            (comp.c * 2.0 * math.pi, "Paydada ω = 2πf yerine doğrudan f kullanmış olabilirsiniz: C = Q_C / (2π·f·V²)."),
        ]
        if is_rms:
            c_alts.append((2.0 * comp.c, "Gerilim zaten etkin (RMS) değerdir; V'yi tekrar √2'ye bölmeyin: C = Q_C / (ω·V²)."))
            c_alts.append((0.5 * comp.c, "Gerilim zaten etkin (RMS) değerdir; C = Q_C / (ω·V²)."))
            c_hint = "Kaynağa paralel bağlanacak kondansatör sığası: C = Q_C / (ω·V²), ω = 2πf ve V kaynağın etkin gerilimidir."
        else:
            c_alts.append((0.5 * comp.c, "Paydada etkin gerilim V = Vm/√2 yerine tepe gerilim Vm kullanmış olabilirsiniz: C = Q_C / (ω·V²)."))
            c_alts.append((2.0 * comp.c, "C = Q_C / (ω·V²) formülünde V = Vm/√2 etkin gerilimdir."))
            c_hint = "Önce etkin gerilimi bulun (V = Vm/√2); ardından kondansatör sığası C = Q_C / (ω·V²), ω = 2πf."

        out.append(q(
            "C_COMP", "C", f"Kaynağa paralel bağlanacak kompanzasyon kondansatörünün sığası (hedef cos φ₂ = {num(comp.target_pf, 4)})",
            "F", "main", comp.c, max(abs(comp.c), 1e-12),
            hint=c_hint,
            sign_hint="Kondansatör sığası C pozitiftir.",
            alternatives=c_alts, is_ac=False,
        ))

    return out


def _resonance_questions(q, parsed: ParsedCircuit, rs, to_cn) -> List[PracticeQuestion]:
    """
    RESONANCE yönteminde alıştırma soruları: f₀, Q, BW, rezonanstaki akım (seri) ya da
    empedans (paralel) ve f₁, f₂. f₁/f₂ için beklenen kitap biçimi (f₀ ∓ BW/2) olup tam
    yarım güç değeri de doğru kabul edilir (PracticeAlternative.accepted).
    """
    series = rs.kind == "series"
    two_pi = 2.0 * math.pi
    sqrt2 = math.sqrt(2.0)
    out: List[PracticeQuestion] = []

    out.append(q(
        "F0", "f₀", "Rezonans frekansı f₀", "Hz", "main", rs.f0, rs.f0,
        hint=("Rezonansta X_L = X_C olur: ω₀ = 1/√(L·C) ve f₀ = ω₀/(2π). "
              "L'yi henri (H), C'yi farad (F) cinsinden yazmayı unutmayın."),
        sign_hint="Frekans pozitiftir.",
        alternatives=[
            (rs.w0, "Bu açısal frekans ω₀ (rad/s). Frekans f₀ = ω₀/(2π) soruluyor (birimi Hz)."),
        ],
        is_ac=False,
    ))

    q_hint = ("Seri RLC'de Q = X/R (X = ω₀L = 1/(ω₀C)); paralel RLC'de Q = R/X. "
              "Q birimsizdir.")
    out.append(q(
        "Q_FACTOR", "Q", "Kalite faktörü Q (birimsiz)", "", "main", rs.q, max(rs.q, 1.0),
        hint=q_hint,
        sign_hint="Kalite faktörü pozitiftir.",
        alternatives=[
            (1.0 / rs.q, "Oranı ters almış olabilirsiniz: seride Q = X/R, paralelde Q = R/X."),
            (rs.x, "Bu reaktans X (Ω). Kalite faktörü Q = X/R (seri) ya da R/X (paralel) birimsiz bir orandır."),
        ],
        is_ac=False,
    ))

    out.append(q(
        "BW", "BW", "Bant genişliği BW", "Hz", "main", rs.bw, rs.f0,
        hint="Bant genişliği BW = f₀ / Q (Hz).",
        sign_hint="Bant genişliği pozitiftir.",
        alternatives=[
            (rs.bw / 2.0, "Bu BW/2; bant genişliği f₂ − f₁ = f₀/Q'nun tamamıdır."),
            (rs.bw * two_pi, "Bu değer rad/s cinsinden; bant genişliği Hz olarak BW = f₀/Q soruluyor."),
        ],
        is_ac=False,
    ))

    if getattr(rs, "via_source_transform", False):
        out.append(q(
            "VX", "V_x", "Rezonansta seri R ile paralel LC kolunun birleştiği düğümdeki gerilim V_x",
            "V", "main", rs.v0, rs.v0,
            hint=("Rezonansta ideal LC kolunun empedansı sonsuz olur; kaynaktan akım çekilmez ve "
                  "seri R üzerinde gerilim düşmez. Bu yüzden V_x kaynak gerilimine eşittir."),
            sign_hint="Gerilimin büyüklüğü soruluyor; pozitif yazın.",
            alternatives=[
                (rs.v0 * rs.q, "Bu Q·V değeri; seri RLC'deki bobin/kondansatör gerilimi gibi düşünmüşsünüz. "
                               "Burada LC kolu paraleldir ve V_x kaynak gerilimine eşittir."),
                (rs.v0 / sqrt2, "Bu V/√2; yarım güç frekansındaki değerdir. Rezonansta V_x = V olur."),
                (0.0, "Rezonansta kaynak akımı sıfırdır, ama V_x sıfır değildir: R üzerinde gerilim "
                      "düşmediği için V_x = V olur."),
            ],
            is_ac=False,
        ))
    elif series:
        out.append(q(
            "I_MAX", "I_max", "Rezonansta kaynaktan çekilen akım (en büyük değer)", "A", "main",
            rs.i0, rs.i0,
            hint=("Rezonansta X_L − X_C = 0 olduğundan seri devrenin empedansı toplam dirençtir "
                  "(Z₀ = R); I_max = V / R."),
            sign_hint="Akımın büyüklüğü soruluyor; pozitif yazın.",
            alternatives=[
                (rs.i0 * sqrt2, "Tepe ile etkin değer karışmış olabilir (√2 kat fark); "
                                "programda seçili gösterimi kullanın."),
                (rs.i0 / sqrt2, "Tepe ile etkin değer karışmış olabilir (√2 kat fark); "
                                "programda seçili gösterimi kullanın."),
            ],
            is_ac=False,
        ))
    else:
        out.append(q(
            "Z0", "Z₀", "Rezonansta devrenin kaynağa göre empedansı", "Ω", "main", rs.z0, rs.z0,
            hint=("Rezonansta bobin ve kondansatör kollarının etkisi birbirini götürür; paralel "
                  "devrenin empedansı yalnızca dirençtir (Z₀ = R)."),
            sign_hint="Direnç pozitiftir.",
            alternatives=[
                (rs.x, "Bu reaktans X. Rezonansta empedans yalnızca R'dir (Z₀ = R)."),
            ],
            is_ac=False,
        ))

    # f₁, f₂: beklenen kitap biçimi; tam yarım güç değeri de kabul edilir
    for qid, label, desc, book, exact, sign in (
        ("F1", "f₁", "Alt kesim (yarım güç) frekansı f₁ = f₀ − BW/2", rs.f1, rs.f1_exact, "−"),
        ("F2", "f₂", "Üst kesim (yarım güç) frekansı f₂ = f₀ + BW/2", rs.f2, rs.f2_exact, "+"),
    ):
        question = q(
            qid, label, desc, "Hz", "extra", book, rs.f0,
            hint=(f"Önce BW = f₀/Q'yu bulun; sonra {label} = f₀ {sign} BW/2. Q küçükse tam "
                  "yarım güç değeri de kabul edilir."),
            sign_hint="Frekans pozitiftir.",
            alternatives=[
                (rs.bw, f"Bu bant genişliği BW. {label} = f₀ {sign} BW/2 soruluyor."),
                (rs.f0 + (1 if sign == "+" else -1) * rs.bw,
                 f"BW/2 yerine BW'yi eklemiş/çıkarmış olabilirsiniz: {label} = f₀ {sign} BW/2."),
            ],
            is_ac=False,
        )
        if abs(exact - book) > 0.005 * abs(book):
            question.alternatives.append(PracticeAlternative(
                value=to_cn(exact),
                message=("Bu tam yarım güç frekansı; kitaptaki yaklaşık biçim "
                         f"{label} = f₀ {sign} BW/2 de doğrudur."),
                accepted=True,
            ))
        out.append(question)
    return out


def _cplx(c: ComplexNumber) -> complex:
    return complex(c.real, c.imaginary)


def _transformer_questions(q, tr) -> List[PracticeQuestion]:
    """
    TRANSFORMER yönteminde alıştırma soruları (çözücünün seçili gösterimdeki sayıları).
    İdeal: V₂, I₁, I₂, yansıyan empedans Z₁ = V₁/I₁ (= Z₂/a²). Kuplajlı: M, I₁, I₂.
    """
    v1, v2, i1, i2 = _cplx(tr.v1), _cplx(tr.v2), _cplx(tr.i1), _cplx(tr.i2)
    v_scale = max(abs(v1), abs(v2), 1e-12)
    i_scale = max(abs(i1), abs(i2), 1e-12)
    out: List[PracticeQuestion] = []

    if tr.kind == "ideal":
        a = tr.a
        out.append(q(
            "V2", "V₂", "Sekonder gerilimi V₂ = V(s+) − V(s−)", "V", "main", v2, v_scale,
            hint=("İdeal transformatörde V₂ = a·V₁ (a = N₂/N₁). Önce primere indirgenmiş devreden "
                  "V₁'i bulun: yük empedansı primere Z₁ = Z₂/a² olarak yansır."),
            sign_hint=("İşaret ters. İdeal transformatörde V₂ = a·V₁ ve a > 0'dır: nokta uçları "
                       "(p+ ve s+) aynı fazdadır."),
            alternatives=[
                (v1, "Bu primer gerilimi V₁. Sekonder gerilimi V₂ = a·V₁ soruluyor."),
                (v1 / a, "Oranı ters uygulamış olabilirsiniz: V₂ = a·V₁ (V₁/a değil)."),
            ]))
        out.append(q(
            "I1", "I₁", "Primer akımı I₁ (p+ ucundan girer)", "A", "main", i1, i_scale,
            hint=("Sekonder yükü primere yansıtın (Z₁ = Z₂/a²), primerdeki seri empedansla toplayıp "
                  "I₁ = V / Z_toplam bulun."),
            sign_hint="İşaret ters. I₁ primerin nokta ucundan (p+) içeri girer.",
            alternatives=[
                (i2, "Bu sekonder akımı I₂. Primer akımı I₁ = a·I₂ soruluyor."),
                (i2 * a * a, "Oran karışmış olabilir: I₁ = a·I₂ (a² değil)."),
            ]))
        out.append(q(
            "I2", "I₂", "Sekonder akımı I₂ (s+ ucundan çıkar)", "A", "main", i2, i_scale,
            hint="İdeal transformatörde güç korunur: I₁ = a·I₂ → I₂ = I₁/a. Ya da I₂ = V₂/Z₂.",
            sign_hint="İşaret ters. İdeal transformatörde I₂ sekonderin nokta ucundan (s+) ÇIKAR.",
            alternatives=[
                (i1, "Bu primer akımı I₁. Sekonder akımı I₂ = I₁/a soruluyor."),
                (i1 * a, "Oranı ters uygulamış olabilirsiniz: I₂ = I₁/a (I₁·a değil)."),
            ]))
        if abs(i1) > 1e-15:
            z1 = v1 / i1
            z2 = v2 / i2 if abs(i2) > 1e-15 else z1 * a * a
            out.append(q(
                "Z1", "Z₁", "Yansıyan empedans: sekonder yükünün primere indirgenmiş değeri",
                "Ω", "extra", z1, max(abs(z1), 1.0),
                hint="Yansıyan empedans Z₁ = Z₂ / a²; Z₂ sekonderdeki toplam yük empedansıdır.",
                sign_hint="Pasif bir yükün yansıyan empedansının gerçek kısmı pozitiftir.",
                alternatives=[
                    (z2, "Bu sekonder yükü Z₂. Primere yansıyan Z₁ = Z₂/a² soruluyor."),
                    (z2 * a * a, "Oranı ters uygulamış olabilirsiniz: Z₁ = Z₂/a² (Z₂·a² değil)."),
                ]))
    else:
        out.append(q(
            "M", "M", "Ortak endüktans M = k·√(L₁·L₂)", "H", "main", tr.m, tr.m,
            hint=("M = k·√(L₁L₂). L'leri henri (H) cinsinden yazın; k birimsizdir ve 0 < k ≤ 1."),
            sign_hint="Ortak endüktansın büyüklüğü soruluyor; pozitif yazın.",
            alternatives=[(tr.k, "Bu kuplaj katsayısı k. Ortak endüktans M = k·√(L₁L₂) (H) soruluyor.")],
            is_ac=False))
        out.append(q(
            "I1", "I₁", "Primer akımı I₁ (p+ ucundan girer)", "A", "main", i1, i_scale,
            hint=("Primer ve sekonder için KVL yazın: V = (Z_seri + jωL₁)·I₁ + jωM·I₂ ve "
                  "0 = jωM·I₁ + (Z_yük + jωL₂)·I₂. İki denklemi birlikte çözün (Cramer)."),
            sign_hint="İşaret ters. I₁ primerin nokta ucundan (p+) içeri girer.",
            alternatives=[(i2, "Bu sekonder akımı I₂. Primer akımı I₁ soruluyor.")]))
        out.append(q(
            "I2", "I₂", "Sekonder akımı I₂ (s+ ucundan girer)", "A", "main", i2, i_scale,
            hint=("Kuplajlı transformatörde I₂ de sekonderin nokta ucundan (s+) GİRER: "
                  "0 = jωM·I₁ + (Z_yük + jωL₂)·I₂ → I₂ = −jωM·I₁ / (Z_yük + jωL₂)."),
            sign_hint=("İşaret ters. I₂ sekonderin nokta ucundan içeri girer; yüke giden akım "
                       "(−I₂) olduğundan I₂ genellikle I₁'e göre ters yönlüdür."),
            alternatives=[(i1, "Bu primer akımı I₁. Sekonder akımı I₂ soruluyor."),
                          (-i2, "Akım yönünü ters almış olabilirsiniz: I₂ s+ ucundan GİREN akımdır.")]))
    return out


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
            domain = "" if c.is_dc else f" ({num(c.frequency)} Hz fazörü)"
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


def build_three_phase_questions(an, to_cn: Callable[[complex], ComplexNumber]) -> List[PracticeQuestion]:
    """
    THREE_PHASE yönteminde alıştırma soruları (çözücünün seçili gösterimdeki sayıları).
    Dengeli: faz akımı, hat akımı, P, Q, S, cos φ.  Dengesiz: hat akımları, nötr akımı (4 iletken), P.
    Hedef cos φ verildiyse ve kompanzasyon uygulandıysa C_Y ve C_Δ da sorulur.
    """
    if not an.guided:
        return []
    scale_i = max(abs(v) for v in an.i_line.values()) or 1.0
    freq = an.frequency
    out: List[PracticeQuestion] = []

    def q(id_, label, description, unit, group, expected, scale, hint, sign_hint,
          alternatives=(), is_ac=False) -> PracticeQuestion:
        exp = complex(expected)
        alts = [PracticeAlternative(value=to_cn(v), message=m) for v, m in alternatives
                if abs(complex(v) - exp) > 0.02 * max(abs(exp), 1e-3 * scale, 1e-12)]
        return PracticeQuestion(
            id=id_, label=label, description=description, unit=unit, group=group,
            is_ac=is_ac, frequency=freq if is_ac else None, expected=to_cn(exp), scale=scale,
            hint=hint, sign_hint=sign_hint, alternatives=alts)

    s3 = math.sqrt(3.0)
    if an.balanced:
        i_h = an.i_line["R"]
        if an.conn_l == "Y":
            i_f = i_h
            f_hint = "Yıldız yükte faz akımı hat akımına eşittir: I_f = I_h = U_f / Z."
            f_alts = [(i_h * s3, "Faz akımı hat akımıdır; √3 ile çarpma üçgen bağlantıya özgüdür.")]
            h_alts = [(i_h / s3, "Yıldızda hat akımı faz akımına eşittir (√3 ile bölmeyin).")]
        else:
            i_f = an.i_phase["RS"]
            f_hint = "Üçgen yükte her kol hat gerilimini görür: I_f = U_h / Z."
            f_alts = [(an.i_phase["RS"] * s3, "Bu hat akımı gibi görünüyor. Faz akımı I_f = U_h / Z.")]
            h_alts = [(i_f, "Bu faz akımı. Hat akımı I_h = √3 · I_f (30° geride).")]
        out.append(q("I_F", "I_f", "Dengeli yükün faz (kol) akımı I_f (R fazı / RS kolu)", "A", "main",
                     i_f, scale_i, hint=f_hint,
                     sign_hint="İşaret ters; açıyı kontrol edin (gerilim fazörüne göre).",
                     alternatives=f_alts, is_ac=True))
        out.append(q("I_H", "I_h", "Hat akımı I_h (R hattı)", "A", "main", i_h, scale_i,
                     hint="Dengeli yükte tek faz eşdeğerini çözün; üçgende I_h = √3 · I_f.",
                     sign_hint="İşaret ters; hat akımı fazörünün açısını kontrol edin.",
                     alternatives=h_alts, is_ac=True))
        for id_, lab, desc, unit, val in (
                ("P", "P", "Toplam aktif güç P", "W", an.p),
                ("Q", "Q", "Toplam reaktif güç Q", "VAR", an.q),
                ("S", "S", "Toplam görünür güç S", "VA", an.s)):
            out.append(q(id_, lab, desc, unit, "main", val, max(abs(an.s), 1e-9),
                         hint="Dengelide P = √3·U_h·I_h·cos φ, Q = √3·U_h·I_h·sin φ, S = √3·U_h·I_h "
                              "(etkin değerlerle).",
                         sign_hint="İşaret ters; geri (endüktif) yükte Q pozitiftir.",
                         alternatives=[(val / s3, "√3 çarpanını unutmuş olabilirsiniz (üç fazlı toplam).")]
                         if val else []))
        out.append(q("PF", "cos φ", "Güç katsayısı cos φ", "", "main", an.pf, 1.0,
                     hint="cos φ = P / S = Re(Z) / |Z|.",
                     sign_hint="Güç katsayısı pozitif yazılır; geri/ileri ayrıca söylenir."))
    else:
        for ph in PHASES:
            out.append(q(f"I_{ph}", f"I_{ph}", f"{ph} hattının akımı I_{ph}", "A", "main",
                         an.i_line[ph], scale_i,
                         hint=("Her kolu ayrı çözün. 3 iletkenli yıldızda önce Millman ile V_N'N'i "
                               "bulun; üçgende kol akımlarından KCL ile hat akımına geçin."),
                         sign_hint="İşaret ters; hat akımı kaynaktan yüke doğru alınır.",
                         is_ac=True))
        if an.i_n is not None:
            out.append(q("I_N", "I_N", "Nötr akımı I_N = I_R + I_S + I_T", "A", "main", an.i_n, scale_i,
                         hint="Nötr akımı hat akımlarının FAZÖR toplamıdır (büyüklükleri toplamayın).",
                         sign_hint="İşaret ters; I_N hat akımlarının toplamıdır.", is_ac=True))
        out.append(q("P", "P", "Toplam aktif güç P (kolların toplamı)", "W", "main", an.p,
                     max(abs(an.s), 1e-9),
                     hint="Her kolun gücünü hesaplayıp toplayın: P = Σ Re(V_kol · I_kol*) (etkin).",
                     sign_hint="Aktif güç pozitiftir (yük güç çeker)."))
    if an.comp is not None and an.comp.applied:
        out.append(q("C_Y", "C_Y", "Yıldız bağlı kompanzasyon kondansatörünün her kolu C_Y", "F", "extra",
                     an.comp.c_y, an.comp.c_y,
                     hint="Q_C = P (tan φ₁ − tan φ₂); C_Y = Q_C / (ω U_h²).",
                     sign_hint="Sığa pozitiftir."))
        out.append(q("C_D", "C_Δ", "Üçgen bağlı kompanzasyon kondansatörünün her kolu C_Δ", "F", "extra",
                     an.comp.c_delta, an.comp.c_delta,
                     hint="Üçgende kol hat gerilimini görür: C_Δ = C_Y / 3.",
                     sign_hint="Sığa pozitiftir.",
                     alternatives=[(an.comp.c_y, "Bu yıldız bağlı değer C_Y; üçgende C_Δ = C_Y / 3.")]))
    return out
