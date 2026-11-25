"""
CircuitAnalyzer API — Devre Çözücü (lcapy Entegrasyonu)

lcapy kütüphanesini kullanarak devreyi sembolik olarak çözer.

★ Üç Kritik Kural:

    1. SymPy → JSON Serialization:
       lcapy SymPy nesneleri döndürür. Bunları:
       - Sayısal → yuvarlanmış float veya complex
       - Sembolik → LaTeX string
       olarak dönüştürüyoruz.

    2. Pedagojik Hata Yakalama:
       lcapy istisnaları (tekil matris, floating node, GND eksik)
       Türkçe ve öğretici mesajlara dönüştürülür.

    3. Thevenin 2-Terminal:
       Thevenin eşdeğeri iki düğüm (port) arasında hesaplanır.
"""

import math
from typing import List, Optional, Tuple, Union

from explainer.formatting import num
from models.response import (
    AnalysisResults, SolutionStep, ExplanationBlock, ExplanationSection,
    NodeVoltage, ElementCurrent, ProbeResult,
    SeriesParallelReduction, MeshInfo, SourceContribution,
)
from models.request import (
    AnalysisMode, AnalysisType, TheveninTerminals, ProbeTarget,
)
from parser.netlist_parser import (
    ParsedCircuit, ElementType, to_lcapy_netlist, lcapy_sense_map,
    has_diodes, has_waveform_sources, DEPENDENT_SOURCES, SWITCH_NOTE,
    circuit_at_time, has_switches, apply_value_basis, element_nodes,
    has_transformers, transformer_floating_ties,
)
from explainer.step_generator import generate_solution_steps
from explainer.topology import generate_topology_step
from explainer.narrative import build_explanation
from solver.frequency_check import check_source_frequencies
from solver.mesh import analyze_meshes
from solver.resonance import ResonanceNotApplicable, analyze_resonance, verify_with_lcapy
from solver.reciprocity import ReciprocityAnalysis
from solver.transformer import analyze_transformer
from solver.three_phase import has_three_phase, has_wattmeters
from solver.numeric_ac import NumericAcUnsupported, NumericCircuit, make_circuit
from solver.superposition import solve_contributions
from practice.questions import build_questions
from solver.error_text import turkish_error
from solver.topology_check import (
    blocking_reason as topology_blocking_reason, dangling_warnings,
)
from solver.numeric import (
    InfiniteImpedanceError, _evaluate_impedance, _extract_numeric, _to_sympy,
    lcapy_element_current, make_complex_number, sig_round,
    sympy_to_latex, sympy_to_numeric,
)  # noqa: F401  (geriye uyumluluk)
from solver.gates import (
    UNSOLVABLE_PREFIX, _dc_no_steady_state_reason, _ignored_sine_warnings,
    _unsolvable_reason,
)  # noqa: F401  (geriye uyumluluk)
from solver.ports import (
    _solve_norton, _solve_port_extras, _solve_reciprocity, _solve_thevenin,
)
from solver.power import (
    _compute_power, _compute_superposition_power, _solve_power_method,
)
from solver.ac_extras import (
    _power_view, _resonance_summary, _solve_transformer_fallback,
    _solve_transformer_ports, _transformer_summary, _transformer_unavailable_reason,
)
from solver.mode_runners import _solve_three_phase, _solve_transient


# ═══════════════════════════════════════════════════════
#  ANA ÇÖZÜCÜ
# ═══════════════════════════════════════════════════════

# Sonuçlar sekmesindeki KVL/KCL "düğüm tarifi" adımlarının doğru olduğu yöntemler:
# düğüm gerilimiyle çözülenler (Thevenin/Norton Vth'yi düğüm gerilimlerinden bulur)
_NODAL_RECIPE_METHODS = (AnalysisType.NODAL, AnalysisType.POWER,
                         AnalysisType.THEVENIN, AnalysisType.NORTON)


def solve_circuit(
    parsed: ParsedCircuit,
    mode: AnalysisMode,
    frequency: Optional[float] = None,
    analysis_type: AnalysisType = AnalysisType.NODAL,
    thevenin_terminals: Optional[TheveninTerminals] = None,
    target_probes: Optional[List[ProbeTarget]] = None,
    warnings: Optional[List[str]] = None,
    value_display: Optional[Union[str, object]] = None,
    power_factor_target: Optional[float] = None,
    reciprocity_target: Optional[str] = None,
    zener_range_target: Optional[str] = None,
    zener_range_given_min: Optional[float] = None,
    zener_range_given_max: Optional[float] = None,
    waveform_output: Optional[str] = None,
) -> Tuple[AnalysisResults, List[SolutionStep], List[str]]:
    """
    Devreyi çözer (anahtarlı devreler için giriş noktası).

    • TRANSIENT: geçici durum (RC / RL) çözülür; devre uygun değilse Türkçe gerekçeyle
      anahtarların t > 0 konumunda Düğüm Gerilimleri yöntemine döner.
    • Anahtar içeren devre BAŞKA bir yöntemle çözülürse anahtarlar t > 0 konumunda alınır
      ve anlatımın başına bu durumu söyleyen bir not eklenir.
    • Anahtarsız devrede doğrudan _solve_core çalışır.
    """
    if value_display is not None:
        parsed = apply_value_basis(parsed, value_display)
    if has_waveform_sources(parsed) and not parsed.errors:
        # Kare/üçgen dalga kaynakları yalnızca WAVEFORM (Dalga Şekli) yöntemiyle geçerlidir
        from solver.waveform import WAVEFORM_NO_DIODE_REASON, WAVEFORM_ONLY_SOURCE_REASON
        if analysis_type != AnalysisType.WAVEFORM:
            return AnalysisResults(), [], [UNSOLVABLE_PREFIX + WAVEFORM_ONLY_SOURCE_REASON]
        if not has_diodes(parsed):
            return AnalysisResults(), [], [
                UNSOLVABLE_PREFIX + f"{WAVEFORM_NO_DIODE_REASON}; kare/üçgen dalga kaynağı diyotsuz devrede başka bir yöntemle çözülemez."
            ]
    if has_diodes(parsed) and not parsed.errors:
        # Diyot doğrusal değildir: durumları bulunur, devre eşdeğeriyle çözülür (solver.diode).
        # Ham diyot asla _solve_core'a gitmez (lcapy netlistine yazılamaz).
        from solver.diode import solve_with_diodes
        return solve_with_diodes(
            parsed, mode, frequency, analysis_type, thevenin_terminals,
            target_probes, warnings,
            zener_range_target=zener_range_target,
            zener_range_given_min=zener_range_given_min,
            zener_range_given_max=zener_range_given_max,
            waveform_output=waveform_output,
        )
    if (has_three_phase(parsed) or has_wattmeters(parsed)) and not parsed.errors:
        return _solve_three_phase(parsed, mode, frequency, analysis_type, thevenin_terminals,
                                  target_probes, warnings, power_factor_target)
    if analysis_type == AnalysisType.TRANSIENT and not has_transformers(parsed):
        return _solve_transient(parsed, mode, frequency, target_probes, warnings)
    if has_switches(parsed) and not parsed.errors:
        # Karşıtlık teoremi anahtarsız devre ister: sebebi _solve_core'a önceden verilir
        switch_block = ("devrede anahtar var; karşıtlık teoremi anahtarsız devrelerde uygulanır."
                        if analysis_type == AnalysisType.RECIPROCITY else None)
        zr_block = ("devrede anahtar var; Zener Aralığı yalnızca temel zener regülatör devresinde "
                    "(DC kaynak, R_X, zener diyot ve R_Y) uygulanır"
                    if analysis_type == AnalysisType.ZENER_RANGE else None)
        results, steps, errors = _solve_core(
            circuit_at_time(parsed, "after"), mode, frequency, analysis_type,
            thevenin_terminals, target_probes, warnings,
            power_factor_target=power_factor_target,
            reciprocity_target=reciprocity_target, reciprocity_block=switch_block,
            zener_range_target=zener_range_target, zener_range_block=zr_block)
        results.explanation.insert(0, ExplanationSection(
            title="Anahtar Konumu",
            blocks=[ExplanationBlock(kind="note", text=SWITCH_NOTE)]))
        return results, steps, errors
    return _solve_core(parsed, mode, frequency, analysis_type,
                       thevenin_terminals, target_probes, warnings,
                       power_factor_target=power_factor_target,
                       reciprocity_target=reciprocity_target,
                       zener_range_target=zener_range_target)


def _solve_core(
    parsed: ParsedCircuit,
    mode: AnalysisMode,
    frequency: Optional[float] = None,
    analysis_type: AnalysisType = AnalysisType.NODAL,
    thevenin_terminals: Optional[TheveninTerminals] = None,
    target_probes: Optional[List[ProbeTarget]] = None,
    warnings: Optional[List[str]] = None,
    power_factor_target: Optional[float] = None,
    reciprocity_target: Optional[str] = None,
    reciprocity_block: Optional[str] = None,
    zener_range_target: Optional[str] = None,
    zener_range_block: Optional[str] = None,
) -> Tuple[AnalysisResults, List[SolutionStep], List[str]]:
    """
    Devreyi çözer ve yapılandırılmış sonuç döndürür.

    İş Akışı:
        1. ParsedCircuit → lcapy Netlist formatı
        2. lcapy Circuit nesnesi oluştur
        3. Düğüm gerilimleri + eleman akımları hesapla
        4. Prob sonuçlarını üret
        5. (Opsiyonel) Thevenin eşdeğeri hesapla
        6. Çözüm adımlarını oluştur

    Args:
        parsed: Ayrıştırılmış devre
        mode: DC, AC_TIME veya AC_PHASOR
        frequency: AC frekansı (Hz) — AC modlarında zorunlu
        analysis_type: NODAL, MESH, THEVENIN, NORTON, SUPERPOSITION, MILLMAN, SOURCE_TRANSFORM, TRANSIENT, POWER, RESONANCE, RECIPROCITY
        thevenin_terminals: Thevenin port tanımı (iki düğüm)
        target_probes: Ölçüm probları
        warnings: Verilirse frekans/süperpozisyon uyarıları bu listeye
            eklenir (API yanıtındaki 'warnings'); verilmezse 'errors'e.
        power_factor_target: POWER yönteminde hedef cos φ₂ (0 < cos φ₂ ≤ 1)
        reciprocity_target: RECIPROCITY yönteminde ikinci kolun elemanı (boşsa son R/L/C)
        reciprocity_block: RECIPROCITY'nin uygulanamama sebebi çağıran tarafça biliniyorsa (ör. anahtar)

    Returns:
        (AnalysisResults, List[SolutionStep], List[str])
        Sonuçlar, çözüm adımları ve hata/uyarı mesajları
    """
    results = AnalysisResults()
    steps: List[SolutionStep] = []
    errors: List[str] = []

    # ── Ön kontroller ──
    if power_factor_target is not None:
        if (isinstance(power_factor_target, bool)
                or not math.isfinite(power_factor_target)
                or power_factor_target <= 0.0
                or power_factor_target > 1.0):
            errors.append(
                "⚠ Hedef güç katsayısı (power_factor_target) 0 ile 1 arasında olmalıdır (0 < cos φ ≤ 1)."
            )
            return results, steps, errors

    if parsed.errors:
        # Ayrıştırıcının reddettiği satırlar (ör: bağımlı kaynağın kontrol
        # elemanı yok) — eksik devreyi çözüp yanlış sonuç vermeyiz
        errors.extend(f"⚠ {m}" for m in parsed.errors)
        return results, steps, errors

    if not parsed.elements:
        errors.append("Devrede hiç eleman bulunamadı.")
        return results, steps, errors

    if not parsed.has_ground:
        errors.append(
            "⚠ Devrede Toprak (GND / Node 0) referansı yok. "
            "SPICE analizi için bir referans düğüm gereklidir. "
            "Lütfen devreye bir GND elemanı ekleyin."
        )

    # ── Transformatör: AC değilse / AC kaynak yoksa mevcut yöntemle devam, aksi hâlde TRANSFORMER ──
    requested_type = analysis_type
    trafo = has_transformers(parsed)
    if trafo:
        why_not = _transformer_unavailable_reason(parsed, mode)
        if why_not:
            return _solve_transformer_fallback(
                parsed, mode, frequency, requested_type, thevenin_terminals,
                target_probes, warnings, power_factor_target, why_not)
        analysis_type = AnalysisType.TRANSFORMER

    # ── Adım 1: Topoloji ──
    elem_summary = ", ".join(e.id for e in parsed.elements)
    steps.append(SolutionStep(
        step_number=1,
        title="Devre Topolojisi Belirleme",
        description=(
            f"Devrede {len(parsed.elements)} eleman ve "
            f"{parsed.node_count} düğüm tespit edildi.\n"
            f"Elemanlar: {elem_summary}\n"
            f"Referans: {'Düğüm 0 (GND) ✓' if parsed.has_ground else 'GND YOK ✕'}"
        ),
        equations=[],
        result_snapshot={"element_count": len(parsed.elements),
                         "node_count": parsed.node_count}
    ))

    # ── Adım 1.4: Rezonans uygunluğu (RESONANCE yöntemi) ──
    # Uygunsa devre kaynağın değil, kendi L ve C'sinden bulunan f₀ frekansında çözülür.
    resonance_analysis = None
    resonance_inapplicable_reason: Optional[str] = None
    if analysis_type == AnalysisType.RESONANCE:
        if mode == AnalysisMode.DC:
            resonance_inapplicable_reason = (
                "Rezonans yöntemi yalnızca AC devreler için uygulanır; DC devrede bobin kısa devre, "
                "kondansatör açık devre sayıldığından rezonans oluşmaz."
            )
        else:
            try:
                resonance_analysis = analyze_resonance(parsed, frequency)
            except ResonanceNotApplicable as e:
                resonance_inapplicable_reason = turkish_error(e, "rezonans")
            except Exception as e:      # beklenmeyen hata: yanlış sonuç yerine dürüst yedek
                turkish_error(e, "rezonans")    # ham hata stderr'e yazılır
                resonance_inapplicable_reason = "Rezonans hesaplanırken beklenmeyen bir hata oluştu."

    # ── Adım 1.5: Kaynak frekansı denetimi (süperpozisyon uyarısı) ──
    if resonance_analysis is not None:
        # Kaynağın (ve isteğin) frekansı rezonans hesabına girmez; f₀ analiz frekansıdır
        frequency = resonance_analysis.f0
    else:
        freq_check = check_source_frequencies(
            parsed, mode, frequency,
            superposition=(analysis_type == AnalysisType.SUPERPOSITION))
        frequency = freq_check.frequency
        (warnings if warnings is not None else errors).extend(freq_check.warnings)
        for fs in freq_check.steps:
            fs.step_number = len(steps) + 1
            steps.append(fs)
        if freq_check.errors:
            errors.extend(freq_check.errors)
            return results, steps, errors

    # ── Adım 2: lcapy devre oluşturma ──
    try:
        from lcapy import Circuit

        lcapy_text = to_lcapy_netlist(parsed, frequency)
        model_note = ""
        if lcapy_sense_map(parsed):
            model_note = (
                "\nBağımlı kaynakların kontrol akımlarını ölçmek için çözücünün içinde 0 V'luk "
                "yardımcı ölçüm kaynakları kullanıldı; bunlar sonuçlarda görünmez."
            )
        if any(e.params.get("diode_of") for e in parsed.elements):
            model_note += (
                "\nİletimdeki diyotlar çözücüde eşik gerilimi (V_T) değerinde bir gerilim kaynağıyla "
                "modellendi; yalıtımdaki diyotlar açık devre olduğundan devreden çıkarıldı."
            )
        if trafo:
            model_note += (
                "\nTransformatör çözücüde ideal transformatör ya da kuplajlı iki bobin olarak "
                "modellendi; uçlarına sonuçlarda görünmeyen 0 V'luk ölçüm kaynakları eklendi."
            )
            if transformer_floating_ties(parsed):
                model_note += (
                    "\nSekonder (ya da primer) toprağa bağlı değil: yalnızca çözüm için o tarafın "
                    "alt ucu GND'ye bağlandı; sonuçları etkilemez, gerilimler o tarafın alt ucuna "
                    "göre verilir."
                )

        steps.append(SolutionStep(
            step_number=2,
            title="Devre Modeli Oluşturma",
            description=(
                "Devre, çözücünün okuyacağı biçime çevrildi ve sembolik devre modeli "
                "oluşturuldu." + model_note
            ),
            equations=[],
            result_snapshot={"lcapy_netlist": lcapy_text}
        ))

        # Karmaşık empedans (Z) içeren AC devrelerde lcapy yavaş/yanlış → sayısal çözücü.
        # Rezonans doğrulaması devreyi birkaç frekansta okur; sayısal çözücü tek frekanslıdır.
        cct = make_circuit(
            parsed, mode == AnalysisMode.DC or analysis_type == AnalysisType.RESONANCE,
            frequency, lcapy_text)

    except ImportError as e:
        turkish_error(e, "çözücü bileşeni")
        errors.append(
            UNSOLVABLE_PREFIX + "Devre çözücünün gerekli bir bileşeni bulunamadı. "
            "Programı yeniden kurmayı deneyin."
        )
        return results, steps, errors
    except Exception as e:
        # Devre modeli kurulamadıysa sonuç yoktur: "başarılı" görünmesin, /analyze 422 döndürsün
        errors.append(
            UNSOLVABLE_PREFIX + f"Devre modeli oluşturulamadı: {turkish_error(e, 'devre modeli')}\n\n"
            "Olası nedenler:\n"
            "• Devrede hatalı ya da eksik bir bağlantı olabilir.\n"
            "• Devrede desteklenmeyen bir eleman olabilir.\n"
            "• Bir eleman değeri okunamamış olabilir."
        )
        return results, steps, errors

    is_dc = (mode == AnalysisMode.DC)

    # ── Adım 2.2: Çözülebilirlik denetimi ──
    # Tekil sistemde her düğüm ve akım için ayrı ayrı İngilizce lcapy hatası çıkıyordu;
    # tek bir Türkçe açıklamayla dur (main.py bunu "Devre çözülemedi" yanıtına çevirir).
    reason = _unsolvable_reason(cct, parsed, is_dc, frequency)
    if reason:
        errors.append(UNSOLVABLE_PREFIX + reason)
        return results, steps, errors

    # ── Adım 2.4: Seri/Paralel tanıma (topoloji) ──
    # (Transformatörlü devrede bu eğitici adımlar atlanır: iki uçlu eleman varsayarlar;
    #  anlatımı TRANSFORMER bölümleri kurar.)
    if not trafo:
        try:
            pinned = set()
            if thevenin_terminals is not None:
                pinned = {thevenin_terminals.node_positive,
                          thevenin_terminals.node_negative}
            topo_step, reductions = generate_topology_step(
                parsed, is_dc, frequency, pinned
            )
            if topo_step:
                topo_step.step_number = len(steps) + 1
                steps.append(topo_step)
            results.reductions = [
                SeriesParallelReduction(
                    type=r.kind,
                    elements=list(r.elements),
                    result_name=r.result_name,
                    nodes=list(r.nodes),
                    formula=r.formula,
                    latex=r.latex,
                    impedance=(make_complex_number(r.impedance)
                               if r.impedance is not None else None),
                    original_elements=r.members,
                )
                for r in reductions
            ]
        except Exception as e:
            errors.append(f"ℹ Seri/paralel analizi yapılamadı: {turkish_error(e, 'seri/paralel')}")

        # ── Adım 2.5: Eğitici adımlar (Empedans / KVL / KCL) ──
        try:
            edu_steps = generate_solution_steps(
                parsed=parsed,
                frequency=frequency,
                is_dc=is_dc
            )
            if analysis_type not in _NODAL_RECIPE_METHODS:
                # Çevre, süperpozisyon, Millman, kaynak dönüşümü… kendi adımlarını
                # “Anlatım” sekmesinde verir; burada düğüm tarifi yanıltıcı olur
                edu_steps = [s for s in edu_steps if s.title == "Empedans Hesaplama"]
            if edu_steps:
                # Adım numaralarını mevcut adımların devamı olarak ata
                base_num = len(steps)
                for i, es in enumerate(edu_steps):
                    es.step_number = base_num + i + 1
                steps.extend(edu_steps)
        except Exception as e:
            errors.append(f"ℹ Eğitici adımlar oluşturulamadı: {turkish_error(e, 'eğitici adımlar')}")

    # ── Adım 3: Düğüm gerilimleri ──
    raw_nodes = {"0": 0.0}
    node_voltages = _solve_node_voltages(
        cct, parsed, is_dc, frequency, steps, errors, raw_nodes
    )
    results.node_voltages = node_voltages
    if analysis_type not in _NODAL_RECIPE_METHODS:
        for st in steps:
            if st.title == "Düğüm Gerilimleri (Çözüm)":
                st.description = ("Düğüm gerilimleri bulundu. Seçtiğiniz yöntemin adımları "
                                  "“Anlatım” sekmesindedir.")

    # ── Adım 4: Eleman akımları ──
    raw_currents = {}
    element_currents = _solve_element_currents(
        cct, parsed, is_dc, frequency, steps, errors, raw_currents
    )
    results.element_currents = element_currents

    # ── Adım 4.2: Transformatör uç akımları (I₁, I₂) ──
    trafo_ports = []
    power_parsed = parsed
    if trafo:
        trafo_ports = _solve_transformer_ports(
            cct, parsed, is_dc, frequency, raw_nodes, raw_currents, element_currents, errors)
        power_parsed = _power_view(parsed)

    # ── Adım 4.5: Güç analizi (P, Q, S, cos φ) ──
    results.power = _compute_power(
        power_parsed, raw_nodes, raw_currents, is_dc, steps, errors
    )

    # ── Adım 5: Prob sonuçları ──
    probes = target_probes or []
    # Netlist'teki probları da ekle
    if parsed.probes:
        existing_ids = {p.id for p in probes}
        for pp in parsed.probes:
            if pp.id not in existing_ids:
                probes.append(
                    ProbeTarget(id=pp.id, type=pp.probe_type, target=pp.target)
                )

    if probes:
        probe_results = _resolve_probes(
            probes, node_voltages, element_currents, steps, errors
        )
        results.probe_results = probe_results

    # ── Adım 6: Thevenin / Norton (opsiyonel) ──
    if analysis_type in (AnalysisType.THEVENIN, AnalysisType.NORTON,
                         AnalysisType.SOURCE_TRANSFORM):
        if thevenin_terminals is None:
            errors.append(
                f"⚠ {analysis_type.value} analizi için terminal çifti "
                "gerekli. Lütfen 'thevenin_terminals' alanında "
                "node_positive (ve isteğe bağlı node_negative) belirtin."
            )
        elif analysis_type in (AnalysisType.THEVENIN, AnalysisType.SOURCE_TRANSFORM):
            # Kaynak dönüşümü Thevenin eşdeğerine ulaşır; çözücünün Thevenin sonucu doğrulamada kullanılır
            results.thevenin = _solve_thevenin(
                cct, thevenin_terminals, is_dc, frequency, steps, errors
            )
        else:
            results.norton = _solve_norton(
                cct, thevenin_terminals, is_dc, frequency, steps, errors
            )

    # ── Adım 6.1: Transformatörlü devrede Thevenin/Norton (sayısal AC çözücüyle) ──
    # Yöntem TRANSFORMER'a yönlendirildiği için yukarıdaki blok çalışmaz; terminaller
    # verildiyse eşdeğer yine hesaplanır (Vth: terminaller açıkken gerilim, Zth: bağımsız
    # kaynaklar sıfırlanıp 1 A test akımı uygulanınca V/I).
    if (trafo and thevenin_terminals is not None
            and requested_type in (AnalysisType.THEVENIN, AnalysisType.NORTON)):
        try:
            port_cct = NumericCircuit(parsed, frequency)
        except NumericAcUnsupported as e:
            errors.append(f"ℹ Transformatörlü devrede {requested_type.value} eşdeğeri "
                          f"hesaplanamadı: {turkish_error(e, 'transformatör eşdeğeri')}")
        else:
            if requested_type == AnalysisType.THEVENIN:
                results.thevenin = _solve_thevenin(
                    port_cct, thevenin_terminals, is_dc, frequency, steps, errors)
            else:
                results.norton = _solve_norton(
                    port_cct, thevenin_terminals, is_dc, frequency, steps, errors)

    # ── Adım 6.5: Çevre akımları (MESH yöntemi) ──
    mesh_analysis = None
    has_dependent = any(e.element_type in DEPENDENT_SOURCES for e in parsed.elements)
    if analysis_type == AnalysisType.MESH:
        try:
            mesh_analysis = analyze_meshes(
                parsed, is_dc, frequency, getattr(parsed, "node_positions", None))
            if mesh_analysis.ok:
                results.meshes = [
                    MeshInfo(
                        index=m.index,
                        current=make_complex_number(mesh_analysis.mesh_currents[m.index - 1]),
                        nodes=m.nodes,
                        elements=[e.id for e, _ in m.elements],
                    )
                    for m in mesh_analysis.meshes
                ]
            else:
                errors.append(f"ℹ Çevre akımları yöntemi uygulanamadı: {mesh_analysis.reason}")
        except Exception as e:
            errors.append(f"ℹ Çevre akımları analizi yapılamadı: {turkish_error(e, 'çevre akımları')}")

    # ── Adım 6.6: Süperpozisyon ──
    contributions = None
    if analysis_type == AnalysisType.SUPERPOSITION:
        try:
            contributions = solve_contributions(parsed, frequency)
            results.superposition = [
                SourceContribution(
                    source_id=c.source.id,
                    frequency=None if c.is_dc else c.frequency,
                    zeroed_sources=c.zeroed,
                    node_voltages={n: make_complex_number(v) for n, v in c.node_voltages.items()},
                    element_currents={e: make_complex_number(v) for e, v in c.element_currents.items()},
                    error=c.error,
                )
                for c in contributions
            ]
            if not contributions and has_dependent:
                errors.append("ℹ Devrede etkin bağımsız kaynak yok; bağımlı kaynaklar tek "
                              "başına enerji sağlayamaz, bu yüzden tüm gerilim ve akımlar sıfırdır.")
            elif len(contributions) < 2:
                errors.append("ℹ Süperpozisyon için devrede en az iki bağımsız kaynak "
                              "olmalı; tek kaynakta sonuç tam çözümle aynıdır.")
            # Çok frekanslı veya karışık DC+AC süperpozisyonda toplam güç her frekans
            # bileşeninin güçlerinin toplamıdır (dikgen frekanslarda P = Σ P_f).
            ok_contribs = [c for c in (contributions or []) if not c.error]
            freq_keys = {c.frequency_key for c in ok_contribs}
            if ok_contribs and (len(freq_keys) > 1 or any(c.is_dc != is_dc for c in ok_contribs)):
                sup_power = _compute_superposition_power(parsed, ok_contribs, steps, errors)
                if sup_power is not None:
                    results.power = sup_power
        except Exception as e:
            errors.append(f"ℹ Süperpozisyon analizi yapılamadı: {turkish_error(e, 'süperpozisyon')}")

    # ── Adım 6.65: Güç ve Güç Katsayısı (POWER yöntemi) ──
    power_inapplicable_reason: Optional[str] = None
    if analysis_type == AnalysisType.POWER:
        results.power_summary, power_inapplicable_reason = _solve_power_method(
            parsed, is_dc, frequency, raw_nodes, raw_currents, results, power_factor_target
        )

    # ── Adım 6.66: Rezonans (RESONANCE yöntemi) — sayılar lcapy ile denetlenir ──
    if resonance_analysis is not None:
        why = verify_with_lcapy(resonance_analysis, cct)
        if why is None:
            results.resonance = _resonance_summary(resonance_analysis)
        else:
            resonance_inapplicable_reason = (
                f"{why} Devre f₀ = {num(resonance_analysis.f0)} Hz frekansında çözüldü.")
            resonance_analysis = None
    # Sebep anlatımın içinde kalmasın: panelin üstünde de görünsün
    if resonance_inapplicable_reason:
        errors.append(f"ℹ Rezonans yöntemi uygulanamadı: {resonance_inapplicable_reason}")
    if power_inapplicable_reason:
        errors.append(f"ℹ Güç ve Güç Katsayısı yöntemi uygulanamadı: {power_inapplicable_reason}")

    # ── Adım 6.67: Karşıtlık teoremi (RECIPROCITY yöntemi) — ikinci çözüm ──
    reciprocity_analysis: Optional[ReciprocityAnalysis] = None
    reciprocity_inapplicable_reason: Optional[str] = None
    if analysis_type == AnalysisType.RECIPROCITY:
        if reciprocity_block:
            reciprocity_inapplicable_reason = reciprocity_block
        else:
            try:
                reciprocity_analysis, reciprocity_inapplicable_reason = _solve_reciprocity(
                    parsed, mode, is_dc, frequency, reciprocity_target, raw_nodes, raw_currents)
            except Exception as e:      # beklenmeyen hata: yanlış sonuç yerine dürüst yedek
                turkish_error(e, "karşıtlık teoremi")   # ham hata stderr'e yazılır
                reciprocity_analysis = None
                reciprocity_inapplicable_reason = (
                    "karşıtlık teoremi hesaplanırken beklenmeyen bir hata oluştu.")
        if reciprocity_inapplicable_reason:
            errors.append(f"ℹ Karşıtlık teoremi uygulanamadı: {reciprocity_inapplicable_reason}")

    # ── Adım 6.68: Zener Aralığı (ZENER_RANGE) — diyotsuz devrede her zaman NODAL'a döner ──
    zener_range_inapplicable_reason: Optional[str] = None
    if analysis_type == AnalysisType.ZENER_RANGE:
        from explainer.zener_range_narrative import fallback_note
        from solver.zener_range import detect_zener_regulator
        if zener_range_block:
            zener_range_inapplicable_reason = zener_range_block
        else:
            _, zener_range_inapplicable_reason = detect_zener_regulator(
                parsed, mode, zener_range_target)
        if zener_range_inapplicable_reason:
            errors.append(fallback_note(zener_range_inapplicable_reason))

    # ── Adım 6.69: Dalga Şekli (WAVEFORM) — diyotsuz devrede her zaman NODAL'a döner ──
    waveform_inapplicable_reason: Optional[str] = None
    if analysis_type == AnalysisType.WAVEFORM:
        from explainer.waveform_narrative import fallback_note as wf_fallback_note
        from solver.waveform import WAVEFORM_NO_DIODE_REASON
        waveform_inapplicable_reason = WAVEFORM_NO_DIODE_REASON
        errors.append(wf_fallback_note(waveform_inapplicable_reason))

    # ── Adım 6.7: Bağımlı kaynaklı Thevenin/Norton için ek sayılar ──
    port_extras = None
    if (has_dependent and thevenin_terminals is not None
            and analysis_type in (AnalysisType.THEVENIN, AnalysisType.NORTON,
                                  AnalysisType.SOURCE_TRANSFORM)
            and (results.thevenin is not None or results.norton is not None)):
        try:
            port_extras = _solve_port_extras(
                parsed, thevenin_terminals, is_dc, frequency, raw_nodes, raw_currents)
        except Exception as e:
            errors.append(f"ℹ Kısa devre/test kaynağı hesabı yapılamadı: {turkish_error(e, 'kısa devre/test kaynağı')}")

    # ── Adım 6.8: Transformatör (TRANSFORMER yöntemi) — sonuç özeti ve elle türetme ──
    transformer_analysis = None
    if trafo and trafo_ports:
        omega = None if is_dc or not frequency else 2 * math.pi * frequency
        first = trafo_ports[0]
        results.transformer = _transformer_summary(*first, bool(transformer_floating_ties(parsed)))
        try:
            transformer_analysis = analyze_transformer(
                parsed, omega, getattr(parsed, "value_basis", "PEAK") == "RMS",
                raw_currents, *first[1:], transformer_floating_ties(parsed))
        except Exception as e:      # beklenmeyen hata: yanlış sonuç yerine dürüst yedek
            errors.append(f"ℹ Transformatör türetmesi hazırlanamadı: {turkish_error(e, 'transformatör türetmesi')}")

    # ── Adım 7: Öğrenci için Türkçe anlatım (kalıp tabanlı) ──
    try:
        results.explanation = build_explanation(
            parsed, is_dc, frequency, analysis_type, thevenin_terminals,
            raw_nodes, raw_currents, results, mesh_analysis, contributions,
            port_extras, power_inapplicable_reason=power_inapplicable_reason,
            resonance_analysis=resonance_analysis,
            resonance_inapplicable_reason=resonance_inapplicable_reason,
            transformer_analysis=transformer_analysis,
            requested_type=requested_type,
            reciprocity_analysis=reciprocity_analysis,
            reciprocity_inapplicable_reason=reciprocity_inapplicable_reason,
            zener_range_inapplicable_reason=zener_range_inapplicable_reason,
            waveform_inapplicable_reason=waveform_inapplicable_reason,
        )
    except Exception as e:
        errors.append(f"ℹ Anlatım oluşturulamadı: {turkish_error(e, 'anlatım')}")

    # ── Adım 7.5: Alıştırma modu soruları ──
    try:
        results.practice = build_questions(
            parsed, is_dc, frequency, analysis_type, thevenin_terminals,
            raw_nodes, raw_currents, results, make_complex_number,
            mesh_analysis, contributions,
        )
    except Exception as e:
        errors.append(f"ℹ Alıştırma soruları oluşturulamadı: {turkish_error(e, 'alıştırma')}")

    # ── Son adım: Doğrulama ──
    if node_voltages:
        steps.append(SolutionStep(
            step_number=len(steps) + 1,
            title="Sonuç Özeti",
            description="Tüm düğüm gerilimleri ve eleman akımları hesaplandı.",
            result_snapshot={
                "node_voltages": {
                    k: v.value if isinstance(v.value, float)
                    else v.value.rectangular_str
                    for k, v in node_voltages.items()
                },
                "element_currents": {
                    k: v.value if isinstance(v.value, float)
                    else v.value.rectangular_str
                    for k, v in element_currents.items()
                }
            }
        ))

    return results, steps, errors


# ═══════════════════════════════════════════════════════
#  DÜĞÜM GERİLİMLERİ
# ═══════════════════════════════════════════════════════


def topology_gate(
    parsed: ParsedCircuit,
    mode: AnalysisMode,
    analysis_type: AnalysisType,
    ignore_nodes=(),
) -> Tuple[Optional[str], List[str]]:
    """
    Çözümden ÖNCE hızlı yapı denetimi (main.py çağırır): (engelleyen_neden | None, uyarılar).

    • Engel: devrede yalnızca R, L, C ve bağımsız kaynaklar varken (hata kesin) kısa devre edilmiş
      gerilim kaynağı, yalnız kaynaklardan oluşan halka ya da GND'ye bağlı olmayan bölüm.
      DC'de çözücünün zaten bildiği kararlı hâli olmayan durumlar önce söylenir (daha özel).
      Geçici durumda (anahtarlı, t < 0 ve t > 0 ayrı çözülür) engellenmez.
    • Uyarı: bir ucu boşta kalan eleman; SINE kaynağında hesaba katılmayan gecikme/sönüm (⚠, engellemez).
    Ayrıştırma hatası ya da boş devrede bir şey yapmaz (onları çağıran taraf bildirir).
    """
    if parsed.errors or not parsed.elements:
        return None, []
    warns = dangling_warnings(parsed, ignore_nodes) + _ignored_sine_warnings(parsed)
    if analysis_type == AnalysisType.TRANSIENT:
        return None, warns
    is_dc = mode == AnalysisMode.DC
    after = circuit_at_time(parsed, "after")
    reason = None
    if is_dc:
        reason = _dc_no_steady_state_reason(after)
    if reason is None:
        reason = topology_blocking_reason(parsed, is_dc)
    return reason, warns


def _solve_node_voltages(
    cct, parsed: ParsedCircuit, is_dc: bool,
    frequency: float,
    steps: List[SolutionStep], errors: List[str],
    raw_out: Optional[dict] = None
) -> dict:
    """
    Tüm düğümlerdeki gerilimleri hesaplar.

    raw_out verilirse yuvarlanmamış değerler {düğüm: float|complex}
    olarak buraya yazılır (güç hesabı için).

    DC modda: float sonuç (ör: V2 = 8.0 V)
    AC modda: complex sonuç (ör: V2 = 7.07+j7.07 V)

    ★ AC modda omega = 2πf yerine koyması yapılır.
    """
    node_voltages = {}

    # Tüm düğümleri topla (0 dahil)
    all_nodes = set()
    for elem in parsed.elements:
        all_nodes.update(element_nodes(elem))

    # Node 0 = GND = 0V
    node_voltages["0"] = NodeVoltage(value=0.0, unit="V", label="GND")

    # Diğer düğümler
    solved_nodes = {}
    for node in sorted(all_nodes):
        if node == "0":
            continue

        try:
            v_expr = cct[node].V
            v_val = _extract_numeric(v_expr, is_dc, frequency)

            solved_nodes[node] = v_val
            if raw_out is not None:
                raw_out[node] = v_val

            if isinstance(v_val, complex):
                node_voltages[node] = NodeVoltage(
                    value=make_complex_number(v_val), unit="V"
                )
            else:
                node_voltages[node] = NodeVoltage(
                    value=sig_round(float(v_val)), unit="V"
                )

        except Exception as e:
            err_msg = str(e).lower()
            if "singular" in err_msg:
                errors.append(
                    f"⚠ Düğüm {node}: devre denklemleri tek bir çözüme varmıyor (tekil sistem).\n"
                    "Bu genellikle devrede boşta kalan bir düğüm (açık devre) "
                    "veya kısa devre olduğunu gösterir.\n"
                    "Lütfen tüm düğümlerin GND'ye bir yol ile "
                    "bağlı olduğundan emin olun."
                )
            elif "not connected" in err_msg or "floating" in err_msg:
                errors.append(
                    f"⚠ Düğüm {node}: Bu düğüm devrenin geri kalanına "
                    "bağlı değil (boşta kalan düğüm).\n"
                    "Lütfen tüm elemanların tel ile bağlandığından emin olun."
                )
            else:
                errors.append(
                    f"⚠ Düğüm {node} gerilimi hesaplanamadı: {turkish_error(e, 'düğüm gerilimi')}"
                )

    # Çözüm adımı
    if solved_nodes:
        equations = []
        latex_parts = []
        for node, val in solved_nodes.items():
            if isinstance(val, complex):
                sign = "-" if val.imag < 0 else "+"
                eq = f"V({node}) = {num(val.real)} {sign} j{num(abs(val.imag))} V"
                latex_parts.append(
                    f"V_{{{node}}} = {num(val.real)} {sign} j{num(abs(val.imag))}"
                )
            else:
                eq = f"V({node}) = {num(val)} V"
                latex_parts.append(f"V_{{{node}}} = {num(val)}")
            equations.append(eq)

        steps.append(SolutionStep(
            step_number=len(steps) + 1,
            title="Düğüm Gerilimleri (Çözüm)",
            description=(
                "KCL (Kirchhoff Akım Yasası) uygulanarak "
                "düğüm gerilimleri hesaplandı."
            ),
            equations=equations,
            latex_formula=" \\quad , \\quad ".join(latex_parts),
            result_snapshot=solved_nodes
        ))

    return node_voltages


# ═══════════════════════════════════════════════════════
#  ELEMAN AKIMLARI
# ═══════════════════════════════════════════════════════

def _solve_element_currents(
    cct, parsed: ParsedCircuit, is_dc: bool,
    frequency: float,
    steps: List[SolutionStep], errors: List[str],
    raw_out: Optional[dict] = None
) -> dict:
    """
    Her eleman üzerinden geçen akımı hesaplar.

    raw_out verilirse yuvarlanmamış değerler {eleman: float|complex}
    olarak buraya yazılır (güç hesabı için).

    Pasif işaret kuralı (PSC): Akım pozitif terminalden
    negatif terminale doğrudur.

    ★ AC modda omega = 2πf yerine koyması yapılır.
    """
    element_currents = {}
    sense = lcapy_sense_map(parsed)

    for elem in parsed.elements:
        if elem.element_type == ElementType.TRANSFORMER:
            continue        # akımları _solve_transformer_ports hesaplar (I₁, I₂)
        try:
            i_val = lcapy_element_current(cct, elem, sense, is_dc, frequency)
            if raw_out is not None:
                raw_out[elem.id] = i_val

            direction = f"{elem.node_positive}→{elem.node_negative}"

            if isinstance(i_val, complex):
                element_currents[elem.id] = ElementCurrent(
                    value=make_complex_number(i_val),
                    unit="A",
                    direction=direction
                )
            else:
                element_currents[elem.id] = ElementCurrent(
                    value=sig_round(float(i_val)),
                    unit="A",
                    direction=direction
                )

        except Exception as e:
            # Akım hesaplanamayan elemanlar için uyarı
            errors.append(
                f"ℹ {elem.id} akımı hesaplanamadı: {turkish_error(e, 'eleman akımı')}"
            )

    return element_currents


# ═══════════════════════════════════════════════════════
#  ÖLÇÜM PROBLARI
# ═══════════════════════════════════════════════════════

def _resolve_probes(
    probes: List[ProbeTarget],
    node_voltages: dict,
    element_currents: dict,
    steps: List[SolutionStep],
    errors: List[str]
) -> List[ProbeResult]:
    """
    Ölçüm problarının sonuçlarını düğüm gerilimleri ve
    eleman akımlarından çıkarır.
    """
    probe_results = []

    for probe in probes:
        if probe.type == "V":
            # Gerilim probu → düğüm geriliminden oku
            node_id = probe.target
            if node_id in node_voltages:
                nv = node_voltages[node_id]
                probe_results.append(ProbeResult(
                    probe_id=probe.id,
                    type="V",
                    value=nv.value,
                    unit="V"
                ))
            else:
                errors.append(
                    f"⚠ {probe.id}: Düğüm {node_id} bulunamadı. "
                    "Probu doğru düğüme bağladığınızdan emin olun."
                )

        elif probe.type == "I":
            # Akım probu → eleman akımından oku
            elem_id = probe.target
            if elem_id in element_currents:
                ec = element_currents[elem_id]
                probe_results.append(ProbeResult(
                    probe_id=probe.id,
                    type="I",
                    value=ec.value,
                    unit="A"
                ))
            else:
                errors.append(
                    f"⚠ {probe.id}: Eleman '{elem_id}' bulunamadı. "
                    "Hedef eleman ID'sini kontrol edin."
                )

    # Prob sonuçları adımı
    if probe_results:
        probe_eqs = []
        for pr in probe_results:
            val_str = (
                pr.value if isinstance(pr.value, (int, float))
                else pr.value.rectangular_str
            )
            probe_eqs.append(f"{pr.probe_id}: {pr.type}={val_str} {pr.unit}")

        steps.append(SolutionStep(
            step_number=len(steps) + 1,
            title="Ölçüm Probu Sonuçları",
            description="Kullanıcının yerleştirdiği probların ölçüm sonuçları:",
            equations=probe_eqs
        ))

    return probe_results
