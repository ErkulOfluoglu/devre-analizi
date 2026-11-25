"""
Üç fazlı/wattmetreli devre ve geçici durum (RC/RL anahtarlı) üst düzey çözüm akışları.
"""

import copy
import math
from typing import List, Optional, Tuple

from explainer.transient_narrative import build_transient_explanation
from models.request import AnalysisMode, AnalysisType, ProbeTarget
from models.response import (
    AnalysisResults, ExplanationBlock, ExplanationSection, SolutionStep,
    ThreePhaseAron, ThreePhaseCompensation, ThreePhaseSummary,
    TransientQuantityResult, TransientResult, WattmeterReading,
)
from parser.netlist_parser import ParsedCircuit, circuit_at_time, element_nodes
from practice.transient_questions import build_transient_questions
from solver.error_text import turkish_error
from solver.gates import UNSOLVABLE_PREFIX
from solver.numeric import make_complex_number, sig_round
from solver.power import _add_wattmeter_section, _group_powers_by_owner
from solver.three_phase import (
    analyze_three_phase, expand_three_phase, has_three_phase, wattmeter_readings,
)
from solver.transient import TransientNotApplicable, analyze_transient


def _solve_three_phase(
    parsed: ParsedCircuit, mode: AnalysisMode, frequency: Optional[float],
    analysis_type: AnalysisType, thevenin_terminals, target_probes, warnings,
    power_factor_target: Optional[float],
) -> Tuple[AnalysisResults, List[SolutionStep], List[str]]:
    """
    Üç fazlı kaynak/yük ve wattmetre içeren devre: elemanlar sıradan elemanlara açılır
    (solver.three_phase), açılmış devre mevcut çözücüyle çözülür; üç faz büyüklükleri,
    anlatım ve alıştırma soruları çözülmüş devreden kurulur.
    """
    from solver.circuit_solver import solve_circuit
    is_dc = mode == AnalysisMode.DC
    three = has_three_phase(parsed)
    if three and is_dc:
        return AnalysisResults(), [], [
            "⚠ Üç fazlı kaynak ve yük yalnızca AC devrelerde çalışır: DC'de sargılar arasında "
            "faz farkı oluşmaz. Lütfen AC (fazör) modunu seçin."]
    if power_factor_target is not None and (
            isinstance(power_factor_target, bool) or not math.isfinite(power_factor_target)
            or power_factor_target <= 0.0 or power_factor_target > 1.0):
        return AnalysisResults(), [], [
            "⚠ Hedef güç katsayısı (power_factor_target) 0 ile 1 arasında olmalıdır (0 < cos φ ≤ 1)."]

    exp = expand_three_phase(parsed, is_dc, frequency)
    freq = exp.frequency or frequency
    core_type = (AnalysisType.NODAL if three or analysis_type in (
        AnalysisType.THREE_PHASE, AnalysisType.TRANSFORMER, AnalysisType.RECIPROCITY,
        AnalysisType.ZENER_RANGE, AnalysisType.WAVEFORM)
        else analysis_type)
    results, steps, errors = solve_circuit(
        exp.flat, mode, freq, core_type, None if three else thevenin_terminals, target_probes,
        warnings, power_factor_target=None if three else power_factor_target)
    if analysis_type == AnalysisType.RECIPROCITY:
        errors.append("ℹ Karşıtlık teoremi uygulanamadı: devrede üç fazlı eleman ya da wattmetre "
                      "var; sonuçlar Düğüm Gerilimleri yöntemiyle verildi.")
    elif analysis_type == AnalysisType.ZENER_RANGE:
        from explainer.zener_range_narrative import fallback_note
        errors.append(fallback_note("devrede üç fazlı eleman ya da wattmetre var"))
    elif analysis_type == AnalysisType.WAVEFORM:
        from explainer.waveform_narrative import fallback_note as wf_fallback_note
        from solver.waveform import WAVEFORM_NO_DIODE_REASON
        errors.append(wf_fallback_note(WAVEFORM_NO_DIODE_REASON))
    if any(m.startswith(UNSOLVABLE_PREFIX) for m in errors) or not results.node_voltages:
        return results, steps, errors

    is_rms = getattr(parsed, "value_basis", "PEAK") == "RMS"
    readings = wattmeter_readings(results, exp, is_rms, is_dc)
    results.wattmeters = [WattmeterReading(id=i, p=sig_round(p)) for i, p, _, _ in readings]
    if not three:
        _add_wattmeter_section(results, exp, readings, is_rms, is_dc)
        _hide_expansion_ids(results, parsed, exp)
        return results, steps, errors

    def verify(extra):
        flat2 = copy.copy(exp.flat)
        flat2.elements = list(exp.flat.elements) + list(extra)
        flat2.node_count = len({n for e in flat2.elements for n in element_nodes(e)})
        try:
            r2, _, _ = solve_circuit(flat2, mode, freq, AnalysisType.NODAL, None, None, [])
        except Exception:
            return None
        return r2 if r2.node_voltages else None

    try:
        an = analyze_three_phase(parsed, exp, results, freq, power_factor_target, verify)
    except Exception as e:      # beklenmeyen hata: yanlış sonuç yerine dürüst yedek
        errors.append(f"ℹ Üç faz büyüklükleri hesaplanamadı: {turkish_error(e, 'üç faz')}")
        _hide_expansion_ids(results, parsed, exp)
        return results, [], errors
    if an is None:
        errors.append("ℹ Üç fazlı kaynağın hat akımları okunamadı; üç faz özeti verilemedi.")
        _hide_expansion_ids(results, parsed, exp)
        return results, [], errors
    results.three_phase = _three_phase_summary(an)
    from explainer.three_phase_narrative import build_three_phase_sections
    try:
        results.explanation = [s.build() for s in build_three_phase_sections(
            an, analysis_type, transformer=bool(results.transformer)) if s.blocks]
    except Exception as e:
        errors.append(f"ℹ Anlatım oluşturulamadı: {turkish_error(e, 'anlatım')}")
    try:
        from practice.questions import build_three_phase_questions
        results.practice = build_three_phase_questions(an, make_complex_number)
    except Exception as e:
        errors.append(f"ℹ Alıştırma soruları oluşturulamadı: {turkish_error(e, 'alıştırma')}")
    _hide_expansion_ids(results, parsed, exp)
    # Genel çözüm adımları açılmış devreyi anlatır (V_U1_R, Y1_R_m …); üç faz anlatımı onların yerini tutar
    return results, [], errors


def _hide_expansion_ids(results, parsed: ParsedCircuit, exp) -> None:
    """
    Açılımın iç elemanlarını ve düğümlerini sonuçlardan çıkarır: öğrencinin devresinde yoklar.

    • Eleman akımları ve düğüm gerilimleri: iç kimlikler/düğümler (V_U1_R, Y1_R_m, U1_n) silinir.
    • Güç tablosu: iç elemanların güçleri çizilen elemanda (U1, Y1) toplanır; wattmetrenin 0 V'luk
      ölçüm kaynağı (güç 0) tablodan çıkar.
    • Seri/paralel indirgemeler: iç eleman ya da düğüm geçen adımlar gösterilmez (öğrencinin
      çizdiği devrede böyle bir bağlantı yok).
    • Üç fazlı elemanların uçlarındaki düğümlere faz adı verilir (label: "R fazı (U1)"), sayısal
      gürültü (dengeli yükte yıldız noktası ≈ 2·10⁻¹⁴ V) sıfır gösterilir.
    """
    from solver.three_phase import node_display_labels, snap_zero

    real_ids = {e.id for e in parsed.elements}
    hidden_ids = {e.id for e in exp.flat.elements} - real_ids
    results.element_currents = {k: v for k, v in results.element_currents.items() if k not in hidden_ids}

    real_nodes = {n for e in parsed.elements for n in element_nodes(e)}
    hidden_nodes = {n for e in exp.flat.elements for n in element_nodes(e)} - real_nodes - {"0"}
    results.node_voltages = {k: v for k, v in results.node_voltages.items() if k not in hidden_nodes}

    if exp.sources or exp.loads:
        def mag(nv) -> float:
            v = nv.value
            return abs(v) if isinstance(v, (int, float)) else float(v.magnitude)

        ref = max((mag(nv) for nv in results.node_voltages.values()), default=0.0)
        labels = node_display_labels(parsed, exp)
        for k, nv in results.node_voltages.items():
            if k != "0" and ref > 0 and snap_zero(mag(nv), ref) == 0:
                nv.value = 0.0
            if k in labels:
                nv.label = labels[k]

    if results.power is not None:
        results.power.elements = _group_powers_by_owner(results.power.elements, exp.owner, exp.meter_ids)

    hidden_all = hidden_ids | hidden_nodes
    results.reductions = [r for r in results.reductions
                          if not (set(r.elements) | set(r.original_elements) | set(r.nodes)) & hidden_all]


def _three_phase_summary(an) -> ThreePhaseSummary:
    comp = None
    if an.comp is not None:
        c = an.comp
        comp = ThreePhaseCompensation(
            target_pf=c.target, applied=c.applied, reason=c.reason,
            q_c=sig_round(c.q_c) if c.applied else None,
            c_y=sig_round(c.c_y) if c.applied else None,
            c_delta=sig_round(c.c_delta) if c.applied else None)
    return ThreePhaseSummary(
        source=an.conn_s, load=an.conn_l, wires=an.wires, balanced=an.balanced,
        u_line=sig_round(an.uh), u_phase=sig_round(an.uf),
        line_currents={k: make_complex_number(v) for k, v in an.i_line.items()},
        neutral_current=make_complex_number(an.i_n) if an.i_n is not None else None,
        load_phase_currents=({k: make_complex_number(v) for k, v in an.i_phase.items()}
                             if an.i_phase else None),
        p=sig_round(an.p), q=sig_round(an.q), s=sig_round(an.s), pf=sig_round(an.pf),
        pf_type=an.pf_type,
        aron=(ThreePhaseAron(p_a=sig_round(an.aron[0]), p_b=sig_round(an.aron[1]))
              if an.aron is not None else None),
        compensation=comp,
        phase_voltages=({k: make_complex_number(v) for k, v in an.v_ph.items()}
                        if an.conn_s == "Y" else None),
        line_voltages={k: make_complex_number(v) for k, v in an.v_line.items()},
        load_voltages=({k: make_complex_number(v) for k, v in an.v_load.items()}
                       if an.v_load else None),
        # 4 iletkenli devrede N′ ile N aynı düğümdür (V_N′N = 0 kendiliğinden); yalnız 3 iletkende anlamlı
        load_neutral_voltage=(make_complex_number(an.v_star_shift)
                              if an.v_star_shift is not None and an.wires == 3 else None))


def _solve_transient(
    parsed: ParsedCircuit,
    mode: AnalysisMode,
    frequency: Optional[float],
    target_probes: Optional[List[ProbeTarget]],
    warnings: Optional[List[str]],
) -> Tuple[AnalysisResults, List[SolutionStep], List[str]]:
    """
    Geçici durum: devre t > 0 konumunda sıradan DC (ya da verilen mod) analiziyle çözülür
    (düğüm gerilimleri, akımlar, güç = t → ∞ kararlı hâl); geçici durum uygulanabilirse
    anlatım, alıştırma soruları ve `transient` sonucu bunların yerine/üstüne yazılır.
    Uygulanamaz ya da lcapy doğrulaması tutmazsa anlatımın başına Türkçe gerekçe eklenir.
    """
    from solver.circuit_solver import _solve_core
    after = circuit_at_time(parsed, "after")
    results, steps, errors = _solve_core(
        after, mode, frequency, AnalysisType.NODAL, None, target_probes, warnings)
    if parsed.errors:
        return results, steps, errors

    analysis = None
    try:
        analysis = analyze_transient(parsed, mode == AnalysisMode.DC)
    except TransientNotApplicable as e:
        reason = turkish_error(e, "geçici durum")
    except Exception as e:      # beklenmeyen hata: yanlış sonuç yerine dürüst yedek
        turkish_error(e, "geçici durum")    # ham hata stderr'e yazılır
        reason = "Geçici durum hesaplanırken beklenmeyen bir hata oluştu."

    if analysis is None:
        # Yeşil "Çözüm başarılı" yanıltır: öğrenci geçici durum sonucunu görmüyor
        errors.append(f"⚠ Geçici durum uygulanamadı: {reason} Gösterilen sonuçlar "
                      "anahtarların t > 0 konumundaki kararlı hâldir.")
        fb = ExplanationSection(title="Geçici Durum (Anahtar)", blocks=[ExplanationBlock(
            kind="note",
            text=(f"Bu devrede geçici durum analizi uygulanamadı: {reason} "
                  "Devreyi anahtarların t > 0 konumunda “Düğüm Gerilimleri” yöntemiyle "
                  "çözüyoruz."))])
        results.explanation.insert(0, fb)
        return results, steps, errors

    # Geçici durum çözüldü. t > 0 devresinin sıradan çözümü tekil çıktıysa (ör: C'nin
    # bağlı olduğu kol yüzer) o hata geçerli değildir: geçici durumun kendi çözücüsü kullanıldı.
    errors = [m for m in errors if not m.startswith(UNSOLVABLE_PREFIX)]
    results.explanation = build_transient_explanation(analysis)
    results.practice = build_transient_questions(analysis, make_complex_number)
    results.transient = TransientResult(
        element=analysis.storage.id,
        kind=analysis.kind,
        tau=sig_round(analysis.tau),
        r_th=sig_round(analysis.r_th),
        quantities=[
            TransientQuantityResult(
                id=q.id, label=q.label, unit=q.unit,
                before=sig_round(q.before), start=sig_round(q.start), final=sig_round(q.final))
            for q in analysis.quantities
        ],
    )
    return results, steps, errors
