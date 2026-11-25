"""
Transformatör çözüm yardımcıları (uç akımları, güç görünümü, özet, yedek çözüm) ve rezonans özeti.
"""

import copy
from typing import List, Optional

from models.request import AnalysisMode, AnalysisType
from models.response import (
    ElementCurrent, ExplanationBlock, ExplanationSection,
    ResonanceCurve, ResonanceSummary, TransformerSummary,
)
from parser.netlist_parser import (
    PHASOR_SOURCES, SINE_SOURCES, ElementType, ParsedCircuit, ParsedElement,
    lcapy_transformer_map, transformers, without_transformers,
)
from solver.error_text import turkish_error
from solver.numeric import _extract_numeric, make_complex_number, sig_round


# ═══════════════════════════════════════════════════════
#  TRANSFORMATÖR (TRANSFORMER yöntemi)
# ═══════════════════════════════════════════════════════

def _transformer_unavailable_reason(parsed: ParsedCircuit, mode: AnalysisMode) -> Optional[str]:
    """Transformatörlü çözüm uygulanamıyorsa Türkçe sebep, uygulanabiliyorsa None."""
    if mode == AnalysisMode.DC:
        return ("Transformatör yalnızca AC devrelerde çalışır: DC'de akı değişmediğinden sargılar "
                "arasında gerilim ya da akım aktarılmaz.")
    if not any(e.element_type in SINE_SOURCES + PHASOR_SOURCES for e in parsed.elements):
        return ("Devrede bağımsız bir AC kaynak yok; kaynaksız devrede transformatörün "
                "aktaracağı bir gerilim ya da akım bulunmaz.")
    return None


def _solve_transformer_fallback(
    parsed: ParsedCircuit, mode: AnalysisMode, frequency: Optional[float],
    requested_type: AnalysisType, thevenin_terminals, target_probes, warnings,
    power_factor_target, why_not: str,
):
    """
    Transformatör çözümü uygulanamıyor (DC ya da kaynak yok): sebebi söylenir; transformatör
    sargıları açık devre sayılıp kalan devre istenen yöntemle (yoksa düğüm gerilimleriyle) çözülür.
    """
    from solver.circuit_solver import _solve_core
    reduced = without_transformers(parsed)
    fb_type = (AnalysisType.NODAL
               if requested_type in (AnalysisType.TRANSFORMER, AnalysisType.TRANSIENT,
                                     AnalysisType.RECIPROCITY)
               else requested_type)
    results, steps, errors = _solve_core(
        reduced, mode, frequency, fb_type, thevenin_terminals, target_probes, warnings,
        power_factor_target=power_factor_target)
    ids = ", ".join(t.id for t in transformers(parsed))
    note = (f"Bu devrede transformatör ({ids}) var ama Transformatör yöntemi uygulanamadı: {why_not} "
            "Transformatörün sargıları açık devre sayılarak kalan devre çözüldü.")
    results.explanation.insert(0, ExplanationSection(
        title="Transformatör", blocks=[ExplanationBlock(kind="note", text=note)]))
    errors.append(f"ℹ Transformatör yöntemi uygulanamadı: {why_not}")
    return results, steps, errors


def _solve_transformer_ports(
    cct, parsed: ParsedCircuit, is_dc: bool, frequency: Optional[float],
    raw_nodes: dict, raw_currents: dict, element_currents: dict, errors: List[str],
) -> list:
    """
    Her transformatörün uç akımlarını (0 V'luk ölçüm kaynaklarından) bulur.
    raw_currents / element_currents'a iki kayıt yazılır (ikisi de uca GİREN akım, pasif işaret
    kuralı): "T1" = primer sargı (p+ → p−), "T1_s" = sekonder sargı (s+ → s−).

    Dönüş: [(t, V₁, V₂, I₁, I₂)] — kitap gösterimi: I₁ p+ ucundan girer; ideal transformatörde
    I₂ s+ ucundan ÇIKAR (= −sekonder uca giren akım), kuplajlıda GİRER.
    """
    tmap = lcapy_transformer_map(parsed)
    ports = []
    for t in transformers(parsed):
        names = tmap[t.id]
        s_pos, s_neg = t.params["s_pos"], t.params["s_neg"]
        try:
            i_p = complex(_extract_numeric(cct[names["vp"]].I, is_dc, frequency))
            i_s = complex(_extract_numeric(cct[names["vs"]].I, is_dc, frequency))
        except Exception as e:
            errors.append(f"ℹ {t.id} akımları hesaplanamadı: {turkish_error(e, 'transformatör akımları')}")
            continue
        vals = [raw_nodes.get(n) for n in (t.node_positive, t.node_negative, s_pos, s_neg)]
        if any(v is None for v in vals):
            continue
        v1 = complex(vals[0]) - complex(vals[1])
        v2 = complex(vals[2]) - complex(vals[3])

        raw_currents[t.id] = i_p
        raw_currents[f"{t.id}_s"] = i_s
        element_currents[t.id] = ElementCurrent(
            value=make_complex_number(i_p), unit="A",
            direction=f"{t.node_positive}→{t.node_negative}")
        element_currents[f"{t.id}_s"] = ElementCurrent(
            value=make_complex_number(i_s), unit="A", direction=f"{s_pos}→{s_neg}")

        i2 = -i_s if t.params["kind"] == "IDEAL" else i_s
        ports.append((t, v1, v2, i_p, i2))
    return ports


def _power_view(parsed: ParsedCircuit) -> ParsedCircuit:
    """
    Güç hesabı için görünüm: her transformatörün sekonder sargısı ayrı bir (yük gibi) iki uçlu
    eleman olarak eklenir ("T1_s": s+ → s−); primer sargı "T1" olarak kalır. İdeal
    transformatörde S₁ + S₂ = 0, kuplajlıda sargıların depoladığı reaktif güç kalır.
    """
    view = copy.copy(parsed)
    view.elements = list(parsed.elements)
    for t in transformers(parsed):
        view.elements.append(ParsedElement(
            id=f"{t.id}_s", element_type=ElementType.INDUCTOR,
            node_positive=t.params["s_pos"], node_negative=t.params["s_neg"], value=0.0))
    return view


def _transformer_summary(t: ParsedElement, v1, v2, i1, i2, floating: bool) -> TransformerSummary:
    """Çözücü sonuçları → API yanıtındaki `transformer` alanı (seçili gösterimde)."""
    p = t.params
    ideal = p["kind"] == "IDEAL"
    return TransformerSummary(
        kind="ideal" if ideal else "coupled", id=t.id,
        a=sig_round(float(p["a"])) if ideal else None,
        k=None if ideal else sig_round(float(p["k"])),
        m=None if ideal else sig_round(float(p["m"])),
        v1=make_complex_number(complex(v1)), v2=make_complex_number(complex(v2)),
        i1=make_complex_number(complex(i1)), i2=make_complex_number(complex(i2)),
        floating_secondary=floating,
    )


def _resonance_summary(a) -> ResonanceSummary:
    """Doğrulanmış rezonans analizi → API yanıtındaki `resonance` alanı."""
    return ResonanceSummary(
        kind=a.kind,
        f0=sig_round(a.f0), w0=sig_round(a.w0), x=sig_round(a.x), q=sig_round(a.q),
        bw=sig_round(a.bw), f1=sig_round(a.f1), f2=sig_round(a.f2),
        f1_exact=sig_round(a.f1_exact), f2_exact=sig_round(a.f2_exact),
        z0=sig_round(a.z0), i0=sig_round(a.i0), v0=sig_round(a.v0),
        via_source_transform=a.via_source_transform,
        curve=ResonanceCurve(
            quantity=a.curve_quantity, unit=a.curve_unit,
            f=[sig_round(v) for v in a.curve_f],
            y=[sig_round(v) for v in a.curve_y],
        ),
    )
