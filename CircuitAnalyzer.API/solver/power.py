"""
Aktif/reaktif/görünür güç hesabı, süperpozisyon gücü, güç katsayısı düzeltme (kompanzasyon) ve wattmetre yardımcıları.
"""

import copy
import math
from typing import Dict, List, Optional, Tuple

from explainer.formatting import eng, num
from models.response import (
    AnalysisResults, ElementPower, PowerAnalysis, PowerCompensation,
    PowerSummary, SolutionStep,
)
from parser.netlist_parser import (
    ALL_SOURCES, DC_SOURCES, DEPENDENT_SOURCES, PHASOR_SOURCES, SINE_SOURCES,
    ElementType, ParsedCircuit, ParsedElement, lcapy_sense_map, to_lcapy_netlist,
)
from solver.numeric import (
    _extract_numeric, lcapy_element_current, make_complex_number, sig_round,
)
from solver.numeric_ac import make_circuit
from solver.ports import _fresh_id


# ═══════════════════════════════════════════════════════
#  GÜÇ ANALİZİ (P, Q, S, cos φ)
# ═══════════════════════════════════════════════════════

# Bağımlı kaynaklar da "kaynak" rolündedir: güç verebilir de alabilir de
# (emilen güç P > 0 olabilir); Tellegen gereği toplam yine sıfırdır.
_SOURCE_TYPES = ALL_SOURCES + DEPENDENT_SOURCES


def _power_factor(p: float, q: float, s_mag: float, q_delivered: float):
    """
    cos φ ve tipini döndürür.

    q_delivered: yük için emilen Q, kaynak için verilen Q.
        > 0 → 'geri' (endüktif, akım gerilimin gerisinde)
        < 0 → 'ileri' (kapasitif)
    """
    if s_mag < 1e-15:
        return None, None
    pf = min(abs(p) / s_mag, 1.0)
    if abs(q_delivered) <= 1e-9 * s_mag:
        return round(pf, 6), "birim"
    return round(pf, 6), ("geri" if q_delivered > 0 else "ileri")


def _compute_power(
    parsed: ParsedCircuit,
    raw_nodes: dict,
    raw_currents: dict,
    is_dc: bool,
    steps: List[SolutionStep],
    errors: List[str]
) -> Optional[PowerAnalysis]:
    """
    Her eleman için karmaşık gücü hesaplar (pasif işaret kuralı).

        V = V(+) − V(−),  I = lcapy eleman akımı (+ → −, eleman içinden)
        AC (tepe):  S = ½ · V · I*
        AC (etkin): S = V · I*
        DC:         S = V · I

    Kaynaklar için emilen güç negatiftir (güç verir). Tellegen
    teoremi gereği tüm elemanların S toplamı sıfır olmalıdır.
    """
    is_rms = getattr(parsed, "value_basis", "PEAK") == "RMS"
    factor = 1.0 if (is_dc or is_rms) else 0.5
    s_expr = "V·I*" if is_rms else "½·V·I*"
    elements = {}
    supplied = 0j
    absorbed = 0j
    equations = []
    latex_parts = []

    for elem in parsed.elements:
        if elem.id not in raw_currents:
            continue
        vp = raw_nodes.get(elem.node_positive)
        vn = raw_nodes.get(elem.node_negative)
        if vp is None or vn is None:
            continue

        v = complex(vp) - complex(vn)
        i = complex(raw_currents[elem.id])
        s = factor * v * i.conjugate()
        # Float gürültüsünü temizle: R'de Q ≈ 5e-17 gibi artıklar → 0
        tiny = 1e-12 * abs(s)
        s = complex(
            0.0 if abs(s.real) < tiny else s.real,
            0.0 if abs(s.imag) < tiny else s.imag
        )
        p, q, s_mag = s.real, s.imag, abs(s)

        # İletimdeki diyotun eşdeğer kaynağı (V_T) güç VERMEZ, çeker: P = V_T·I (yük)
        is_source = elem.element_type in _SOURCE_TYPES and not elem.params.get("diode_of")
        if is_source:
            supplied -= s
        else:
            absorbed += s

        pf, pf_type = _power_factor(p, q, s_mag, -q if is_source else q)
        elements[elem.id] = ElementPower(
            element_id=elem.id,
            role="source" if is_source else "load",
            complex_power=make_complex_number(s),
            active_power=sig_round(p),
            reactive_power=sig_round(q),
            apparent_power=sig_round(s_mag),
            power_factor=pf,
            power_factor_type=pf_type,
        )

        if is_dc:
            def _q(x: float, unit: str) -> str:
                t = eng(x, unit)
                return f"({t})" if x < 0 else t
            equations.append(
                f"P_{elem.id} = V·I = {_q(v.real, 'V')} · {_q(i.real, 'A')} "
                f"= {eng(p, 'W')}"
                + ("  (güç verir)" if is_source and p < 0 else "")
            )
        else:
            equations.append(
                f"S_{elem.id} = {s_expr} = {num(s.real)} {'+' if q >= 0 else '-'} "
                f"j{num(abs(q))} VA  →  P = {num(p)} W, Q = {num(q)} VAR, "
                f"|S| = {num(s_mag)} VA"
                + (f", cos φ = {num(pf, 4)} ({pf_type})" if pf is not None else "")
            )

    if not elements:
        return None

    balance = abs(supplied - absorbed)
    # Güç ≈ 0 iken (ör: rezonansta kaynak akımı 0, LC kolunda yine de VA dolaşır) kayan nokta
    # artığı uyarı üretmesin: ölçek, elemanların görünür güçleri toplamını da içerir
    circulating = sum(ep.apparent_power for ep in elements.values())
    scale = max(abs(supplied), abs(absorbed), circulating, 1e-12)
    if balance > 1e-6 * scale:
        errors.append(
            f"ℹ Güç dengesi tam sağlanmadı: verilen {num(supplied.real, 6)} VA, "
            f"çekilen {num(absorbed.real, 6)} VA."
        )

    pf, pf_type = _power_factor(
        supplied.real, supplied.imag, abs(supplied), supplied.imag
    )

    if is_dc:
        convention = "DC: P = V·I (pasif işaret kuralı, emilen güç)"
        equations.append(
            f"Denge: ΣP_kaynak = {eng(supplied.real, 'W')} = "
            f"ΣP_yük = {eng(absorbed.real, 'W')}"
        )
        latex_parts.append(
            "P = V \\cdot I \\quad , \\quad "
            f"\\sum P_{{\\text{{kaynak}}}} = {num(supplied.real)} \\text{{ W}} = "
            f"\\sum P_{{\\text{{yük}}}}"
        )
    else:
        if is_rms:
            convention = (
                "AC: S = V·I* (etkin fazör), P = Re(S), Q = Im(S), "
                "cos φ = P/|S| (pasif işaret kuralı, emilen güç)"
            )
            s_latex = "S = V I^{*}"
        else:
            convention = (
                "AC: S = ½·V·I* (tepe fazör), P = Re(S), Q = Im(S), "
                "cos φ = P/|S| (pasif işaret kuralı, emilen güç)"
            )
            s_latex = "S = \\tfrac{1}{2} V I^{*}"
        equations.append(
            f"Denge: S_verilen = {num(supplied.real)} {'+' if supplied.imag >= 0 else '-'} "
            f"j{num(abs(supplied.imag))} VA = S_çekilen"
        )
        if pf is not None:
            equations.append(
                f"Devre güç faktörü: cos φ = P/|S| = {num(supplied.real)} / "
                f"{num(abs(supplied))} = {num(pf, 4)} ({pf_type})"
            )
        latex_parts.append(
            f"{s_latex} = P + jQ \\quad , \\quad "
            "|S| = \\sqrt{P^2 + Q^2} \\quad , \\quad "
            "\\cos\\varphi = \\frac{P}{|S|}"
        )

    steps.append(SolutionStep(
        step_number=len(steps) + 1,
        title="Güç Analizi (P, Q, S, cos φ)",
        description=(
            "Her elemanın emdiği güç pasif işaret kuralıyla hesaplandı "
            "(akım elemanın + ucundan girer). Kaynaklarda negatif güç, "
            "kaynağın devreye güç verdiği anlamına gelir.\n"
            + ("DC devrede reaktif güç yoktur: P = V·I."
               if is_dc else
               ("Fazörler etkin (RMS) değer olduğundan S = V·I* kullanılır "
                "(tepe değerlerle S = ½·V_m·I_m*). Dirençler yalnızca P, "
                "bobinler Q > 0, kapasitörler Q < 0 çeker."
                if is_rms else
                "Fazörler tepe değer olduğundan S = ½·V·I* kullanılır "
                "(etkin değerlerle S = V_rms·I_rms*). Dirençler yalnızca P, "
                "bobinler Q > 0, kapasitörler Q < 0 çeker."))
        ),
        equations=equations,
        latex_formula=" \\\\ ".join(latex_parts),
        result_snapshot={
            "S_supplied": make_complex_number(supplied).rectangular_str,
            "S_absorbed": make_complex_number(absorbed).rectangular_str,
            "power_factor": pf,
            "power_factor_type": pf_type,
        }
    ))

    return PowerAnalysis(
        convention=convention,
        elements=elements,
        total_supplied=make_complex_number(supplied),
        total_absorbed=make_complex_number(absorbed),
        power_factor=pf,
        power_factor_type=pf_type,
        balance_error=round(balance, 12),
    )


def _compute_superposition_power(
    parsed: ParsedCircuit,
    ok_contribs: list,
    steps: List[SolutionStep],
    errors: List[str],
) -> Optional[PowerAnalysis]:
    """
    Süperpozisyonda farklı frekanslı (ör. DC + AC ya da f₁ ≠ f₂) kaynaklar varken
    toplam gücü hesaplar.

    Aynı frekanstaki kaynakların gerilim ve akım fazörleri önce kendi frekans
    grubunda toplanır; farklı frekanslı bileşenler birbirine dikgen (ortogonal)
    olduğundan ortalama güçler frekans grupları üzerinden toplanır:
        S_eleman = Σ_f S_eleman(f)
        • f = 0 (DC):   S(0) = V_dc · I_dc
        • f > 0 (AC):   S(f) = V(f) · I(f)* (RMS) veya ½ · V_m(f) · I_m(f)* (PEAK)
    """
    is_rms = getattr(parsed, "value_basis", "PEAK") == "RMS"
    by_freq = {}
    for c in ok_contribs:
        by_freq.setdefault(c.frequency_key, []).append(c)

    v_by_freq = {}
    i_by_freq = {}
    for f_key, grp in by_freq.items():
        v_map = {"0": 0j}
        i_map = {}
        for c in grp:
            for n, val in c.node_voltages.items():
                v_map[str(n)] = v_map.get(str(n), 0j) + complex(val)
            for eid, val in c.element_currents.items():
                i_map[eid] = i_map.get(eid, 0j) + complex(val)
        v_by_freq[f_key] = v_map
        i_by_freq[f_key] = i_map

    elements = {}
    supplied = 0j
    absorbed = 0j
    equations = []

    for elem in parsed.elements:
        if not any(elem.id in i_by_freq[fk] for fk in by_freq):
            continue
        s = 0j
        for f_key in by_freq:
            vp = v_by_freq[f_key].get(elem.node_positive, 0j)
            vn = v_by_freq[f_key].get(elem.node_negative, 0j)
            i_val = i_by_freq[f_key].get(elem.id, 0j)
            factor_f = 1.0 if (f_key == 0.0 or is_rms) else 0.5
            s += factor_f * (vp - vn) * i_val.conjugate()

        tiny = 1e-12 * abs(s)
        s = complex(
            0.0 if abs(s.real) < tiny else s.real,
            0.0 if abs(s.imag) < tiny else s.imag,
        )
        p, q, s_mag = s.real, s.imag, abs(s)

        is_source = elem.element_type in _SOURCE_TYPES and not elem.params.get("diode_of")
        if is_source:
            supplied -= s
        else:
            absorbed += s

        pf, pf_type = _power_factor(p, q, s_mag, -q if is_source else q)
        elements[elem.id] = ElementPower(
            element_id=elem.id,
            role="source" if is_source else "load",
            complex_power=make_complex_number(s),
            active_power=sig_round(p),
            reactive_power=sig_round(q),
            apparent_power=sig_round(s_mag),
            power_factor=pf,
            power_factor_type=pf_type,
        )
        equations.append(
            f"S_{elem.id} = Σ_f S(f) = {num(s.real)} {'+' if q >= 0 else '-'} "
            f"j{num(abs(q))} VA  →  P = {num(p)} W, Q = {num(q)} VAR"
        )

    if not elements:
        return None

    balance = abs(supplied - absorbed)
    pf, pf_type = _power_factor(
        supplied.real, supplied.imag, abs(supplied), supplied.imag
    )
    s_ac_expr = "V·I* (etkin)" if is_rms else "½·V·I* (tepe)"
    convention = (
        f"Süperpozisyon (çok frekanslı): P = Σ P_f (DC: V·I, AC: {s_ac_expr}; "
        "farklı frekanslı bileşenlerin güçleri toplanır)"
    )
    equations.append(
        f"Denge: ΣP_verilen = {num(supplied.real)} W = ΣP_çekilen = {num(absorbed.real)} W"
    )

    for st in steps:
        if st.title == "Güç Analizi (P, Q, S, cos φ)":
            st.equations = equations
            st.result_snapshot = {
                "S_supplied": make_complex_number(supplied).rectangular_str,
                "S_absorbed": make_complex_number(absorbed).rectangular_str,
                "power_factor": pf,
                "power_factor_type": pf_type,
            }
            break

    return PowerAnalysis(
        convention=convention,
        elements=elements,
        total_supplied=make_complex_number(supplied),
        total_absorbed=make_complex_number(absorbed),
        power_factor=pf,
        power_factor_type=pf_type,
        balance_error=round(balance, 12),
    )


# ═══════════════════════════════════════════════════════
#  GÜÇ VE GÜÇ KATSAYISI YÖNTEMİ (POWER + KOMPANZASYON)
# ═══════════════════════════════════════════════════════

def _solve_power_method(
    parsed: ParsedCircuit,
    is_dc: bool,
    frequency: Optional[float],
    raw_nodes: dict,
    raw_currents: dict,
    results: AnalysisResults,
    power_factor_target: Optional[float],
) -> Tuple[Optional[PowerSummary], Optional[str]]:
    """
    POWER yöntemi için PowerSummary (ve varsa kompanzasyon hesabı + çözücü doğrulaması)
    üretir. Yöntem bu devrede uygulanamıyorsa (None, Türkçe_sebep) döndürür.
    """
    if is_dc:
        return None, (
            "Güç ve güç katsayısı (cos φ, güç üçgeni, kompanzasyon) yöntemi yalnızca AC "
            "devreler için uygulanır; DC devrede reaktif güç yoktur (Q = 0 ve cos φ = 1)."
        )

    dc_srcs = [e for e in parsed.elements
               if e.element_type in DC_SOURCES and abs(e.value) > 1e-15]
    ac_srcs = [e for e in parsed.elements
               if e.element_type in (SINE_SOURCES + PHASOR_SOURCES)
               and abs(e.params.get("amplitude", e.value)) > 1e-15]
    sine_freqs = {
        round(float(e.params["frequency"]), 9)
        for e in ac_srcs
        if e.element_type in SINE_SOURCES and e.params.get("frequency") is not None
    }
    if (dc_srcs and ac_srcs) or len(sine_freqs) > 1:
        return None, (
            "Devrede farklı frekanslı kaynaklar bulunduğu için tek bir fazör güç üçgeni "
            "ve cos φ tanımlanamaz (farklı frekanslı kaynaklar için Süperpozisyon yöntemi gerekir)."
        )
    if dc_srcs and not ac_srcs:
        return None, (
            "Devrede etkin bir AC kaynağı yok (yalnızca DC kaynak var); AC analizde "
            "DC kaynaklar sıfırlandığından AC güç analizi uygulanamaz."
        )

    pw = results.power
    if pw is None:
        return None, "Güç analizi hesaplanamadı."

    sup = complex(pw.total_supplied.real, pw.total_supplied.imaginary)
    p = sup.real
    q = sup.imag
    s_mag = abs(sup)

    if s_mag < 1e-15:
        pf_val = 1.0
        pf_type_en = "unity"
        phi_deg = 0.0
    elif abs(q) <= 1e-9 * s_mag:
        pf_val = 1.0
        pf_type_en = "unity"
        phi_deg = 0.0
    else:
        pf_val = min(abs(p) / s_mag, 1.0)
        pf_type_en = "lagging" if q > 0 else "leading"
        phi_deg = math.degrees(math.atan2(q, p))

    comp_result: Optional[PowerCompensation] = None
    if power_factor_target is not None:
        comp_result = _compute_compensation(
            parsed=parsed,
            frequency=frequency,
            raw_nodes=raw_nodes,
            raw_currents=raw_currents,
            p=p,
            q=q,
            pf_val=pf_val,
            pf_type_en=pf_type_en,
            target_pf=power_factor_target,
        )

    summary = PowerSummary(
        p=sig_round(p),
        q=sig_round(q),
        s=sig_round(s_mag),
        pf=round(pf_val, 6),
        pf_type=pf_type_en,
        phi_deg=round(phi_deg, 4),
        compensation=comp_result,
    )
    return summary, None


def _compute_compensation(
    parsed: ParsedCircuit,
    frequency: Optional[float],
    raw_nodes: dict,
    raw_currents: dict,
    p: float,
    q: float,
    pf_val: float,
    pf_type_en: str,
    target_pf: float,
) -> PowerCompensation:
    """
    Hedef cos φ₂ için kompanzasyon kondansatörünü hesaplar ve kondansatörü
    devreye kaynağa paralel ekleyip lcapy ile yeniden çözerek doğrular.
    """
    v_ac_srcs = [
        e for e in parsed.elements
        if e.element_type in (ElementType.AC_SOURCE_SINE, ElementType.AC_SOURCE_PHASOR)
        and abs(e.params.get("amplitude", e.value)) > 1e-15
    ]
    i_ac_srcs = [
        e for e in parsed.elements
        if e.element_type in (ElementType.CURRENT_AC_SINE, ElementType.CURRENT_AC_PHASOR)
        and abs(e.params.get("amplitude", e.value)) > 1e-15
    ]

    if i_ac_srcs and not v_ac_srcs:
        return PowerCompensation(
            target_pf=target_pf,
            applied=False,
            reason=(
                "Devrede AC gerilim kaynağı yerine akım kaynağı var; akım kaynağına paralel "
                "kondansatör bağlamak kaynak gerilimini değiştirdiğinden standart kompanzasyon "
                "formülü uygulanamaz."
            ),
        )
    if len(v_ac_srcs) != 1 or i_ac_srcs:
        return PowerCompensation(
            target_pf=target_pf,
            applied=False,
            reason=(
                "Kompanzasyon hesabı için devrede tam olarak bir bağımsız AC gerilim kaynağı "
                "bulunmalıdır (birden çok kaynakta tek bir kaynak gerilimi tanımlanamaz)."
            ),
        )

    if pf_type_en == "leading":
        return PowerCompensation(
            target_pf=target_pf,
            applied=False,
            reason=(
                "Devre ileri (kapasitif) güç katsayılıdır (Q < 0); paralel kondansatör "
                "eklemek kapasitif reaktif gücü daha da artırır, güç katsayısını düzeltmez."
            ),
        )
    if pf_type_en == "unity" or p <= 1e-15:
        return PowerCompensation(
            target_pf=target_pf,
            applied=False,
            reason=(
                "Devre zaten birim güç katsayılıdır (Q = 0, cos φ = 1); kondansatör "
                "eklemeye gerek yoktur."
            ),
        )

    if pf_val >= target_pf - 1e-9:
        return PowerCompensation(
            target_pf=target_pf,
            applied=False,
            reason=(
                f"Mevcut güç katsayısı (cos φ = {num(pf_val, 4)}) zaten hedef değere "
                f"({num(target_pf, 4)}) eşit veya daha büyüktür; kompanzasyona gerek yoktur."
            ),
        )

    if frequency is None or frequency <= 0:
        return PowerCompensation(
            target_pf=target_pf,
            applied=False,
            reason=(
                "Devre frekansı (f) belirtilmediği için açısal frekans ω = 2πf ve "
                "kondansatör sığası C = Q_C / (ω·V²) hesaplanamaz."
            ),
        )

    v_src = v_ac_srcs[0]
    vp = complex(raw_nodes.get(v_src.node_positive, 0.0))
    vn = complex(raw_nodes.get(v_src.node_negative, 0.0))
    v_shown = abs(vp - vn)
    if v_shown <= 1e-15:
        return PowerCompensation(
            target_pf=target_pf,
            applied=False,
            reason="Kaynak gerilimi sıfır olduğundan kompanzasyon hesaplanamaz.",
        )

    is_rms = getattr(parsed, "value_basis", "PEAK") == "RMS"
    v_rms = v_shown if is_rms else (v_shown / math.sqrt(2.0))
    i_before = abs(complex(raw_currents.get(v_src.id, 0.0)))

    tan_phi1 = q / p
    phi2_rad = math.acos(min(max(target_pf, 0.0), 1.0))
    tan_phi2 = math.tan(phi2_rad)
    q_c = p * (tan_phi1 - tan_phi2)
    omega = 2.0 * math.pi * frequency
    c_val = q_c / (omega * (v_rms ** 2))
    i_after_rms = p / (v_rms * target_pf)
    i_after = i_after_rms if is_rms else (i_after_rms * math.sqrt(2.0))

    # ── Çözücüyle doğrulama: C kaynağa paralel eklenip devre yeniden çözülür ──
    verified = False
    try:
        comp_circuit = copy.deepcopy(parsed)
        comp_circuit.probes = []
        c_elem = ParsedElement(
            id=_fresh_id(parsed, "Ckomp"),
            element_type=ElementType.CAPACITOR,
            node_positive=v_src.node_positive,
            node_negative=v_src.node_negative,
            value=c_val,
        )
        comp_circuit.elements.append(c_elem)
        cct_comp = make_circuit(comp_circuit, False, frequency,
                                to_lcapy_netlist(comp_circuit, frequency))
        sense_comp = lcapy_sense_map(comp_circuit)
        i_src_new = complex(lcapy_element_current(cct_comp, v_src, sense_comp, False, frequency))
        vp_new = (0j if v_src.node_positive == "0"
                  else complex(_extract_numeric(cct_comp[v_src.node_positive].V, False, frequency)))
        vn_new = (0j if v_src.node_negative == "0"
                  else complex(_extract_numeric(cct_comp[v_src.node_negative].V, False, frequency)))
        v_new = vp_new - vn_new
        factor = 1.0 if is_rms else 0.5
        s_new = -factor * v_new * i_src_new.conjugate()
        p_new, q_new, s_new_mag = s_new.real, s_new.imag, abs(s_new)
        pf_new = min(abs(p_new) / s_new_mag, 1.0) if s_new_mag > 1e-15 else 1.0
        i_new_mag = abs(i_src_new)

        i_ok = abs(i_new_mag - i_after) <= 1e-4 * max(i_after, 1e-9)
        pf_ok = abs(pf_new - target_pf) <= 1e-4
        q_ok = q_new >= -1e-5 * max(abs(q), 1e-9)
        verified = bool(i_ok and pf_ok and q_ok)
    except Exception:
        verified = False

    if not verified:
        return PowerCompensation(
            target_pf=target_pf,
            applied=False,
            reason=(
                "Bulunan kompanzasyon kondansatörü devreye eklendiğinde çözücü doğrulaması "
                "hedef güç katsayısı ve yeni akımla uyuşmadı."
            ),
        )

    return PowerCompensation(
        target_pf=target_pf,
        q_c=sig_round(q_c),
        c=sig_round(c_val),
        i_before=sig_round(i_before),
        i_after=sig_round(i_after),
        applied=True,
        reason=None,
    )


def _group_powers_by_owner(elements: Dict[str, ElementPower], owner: Dict[str, str],
                           meter_ids: Dict[str, str]) -> Dict[str, ElementPower]:
    """İç elemanların (V_U1_R, R_Y1_R, L_Y1_R …) güçlerini çizilen elemanda (U1, Y1) toplar."""
    meter_internal = set(meter_ids.values())
    grouped: Dict[str, Tuple[str, complex]] = {}
    out: Dict[str, ElementPower] = {}
    for eid, ep in elements.items():
        if eid in meter_internal:
            continue                                    # ölçü aleti: güç çekmez, tabloda yer almaz
        if eid not in owner:
            out[eid] = ep
            continue
        oid = owner[eid]
        s = complex(ep.complex_power.real, ep.complex_power.imaginary)
        role, acc = grouped.get(oid, (ep.role, 0j))
        grouped[oid] = (role, acc + s)
        out.setdefault(oid, ep)                         # sıra korunur; değer aşağıda yazılır
    for oid, (role, s) in grouped.items():
        tiny = 1e-12 * abs(s)
        s = complex(0.0 if abs(s.real) < tiny else s.real, 0.0 if abs(s.imag) < tiny else s.imag)
        p, q, s_mag = s.real, s.imag, abs(s)
        pf, pf_type = _power_factor(p, q, s_mag, -q if role == "source" else q)
        out[oid] = ElementPower(
            element_id=oid, role=role, complex_power=make_complex_number(s),
            active_power=sig_round(p), reactive_power=sig_round(q), apparent_power=sig_round(s_mag),
            power_factor=pf, power_factor_type=pf_type)
    return out


def _add_wattmeter_section(results, exp, readings, is_rms: bool, is_dc: bool) -> None:
    """Üç fazsız devrede (tek fazlı AC ya da DC) wattmetre okumalarını anlatımın sonuna ekler."""
    if not readings:
        return
    from explainer.three_phase_narrative import wattmeter_section
    results.explanation.append(wattmeter_section(readings, is_rms, is_dc).build())
