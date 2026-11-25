"""
CircuitAnalyzer API — Kalıp Tabanlı Türkçe Anlatım

Çözücünün (lcapy) bulduğu kesin sonuçları, bir öğretmenin tahtada
anlattığı sırayla Türkçe bir anlatıma dönüştürür.

★ Kurallar:
    • Yapay zekâ YOK — her cümle bir kalıptır, sayılar devreden gelir.
    • Anlatımda yapılan her cebirsel türetme (denklem çözümü, Ohm yasası,
      seri/paralel indirgeme) çözücünün sonucuyla karşılaştırılır.
      Uyuşmazsa o türetme gösterilmez, yalnızca çözücünün sonucu verilir.
      Böylece öğrenci asla yanlış bir ara adım görmez.

★ Bölüm sırası (Düğüm Gerilimi yöntemi):
    Devreyi Tanıyalım → (AC) Empedanslar → Bilinen Düğümler →
    Düğüm Denklemleri (KCL) → Denklemlerin Çözümü → Eleman Akımları →
    (Thevenin/Norton) → Güç → Kontrol → (AC) Zaman Domeni → Sonuç

★ Bağımlı kaynaklı devrelerde "Düğüm Denklemleri" öncesine "Kontrol Büyüklüğünü
  Bilinmeyenlerle Yazalım" eklenir ve KCL/çözüm bölümlerini explainer.dependent_nodal
  kurar (kısıt denklemi, süperdüğüm, A·x = b); doğrulanamazsa dürüst yedek anlatım verilir.
"""

import math
from typing import Dict, List, Optional

from explainer.formatting import eng, node_name, node_v, num, polar, rect
from explainer.step_generator import _node_groups, _source_value
from models.request import AnalysisType, TheveninTerminals
from models.response import AnalysisResults, ExplanationSection
from parser.netlist_parser import (
    CURRENT_SOURCES, DC_SOURCES, SINE_SOURCES, ElementType, ParsedCircuit,
)
from explainer.narrative_core import (
    PortCircuit, PortExtras, _Ctx, _Section, _close, elem_name, port_is_dead,
)  # noqa: F401  (geriye uyumluluk)
from explainer.narrative_dependent import (
    _control_text, _dependent_check, _dependent_lines, _dependent_solution,
)  # noqa: F401  (geriye uyumluluk)
from explainer.narrative_nodal import (
    EXTRA_DIGITS_NOTE, _cnum, _currents, _flow_text, _group_terms,
    _integer_step, _is_real, _join_terms, _kcl, _known_nodes,
    _linear_term, _pnum, _scale_for, _solve, _system_blocks,
    contribution_currents,
)  # noqa: F401  (geriye uyumluluk)
from explainer.narrative_ports import (
    _norton, _port_reduction_section, _thevenin,
)  # noqa: F401  (geriye uyumluluk)
from explainer.narrative_power import (
    _compensation_section, _power, _power_check, _power_summary_section,
    _power_triangle, _pq,
)  # noqa: F401  (geriye uyumluluk)
from explainer.narrative_checks import _kcl_check, _time_domain


# ═══════════════════════════════════════════════════════
#  ANA GİRİŞ
# ═══════════════════════════════════════════════════════

def build_explanation(
    parsed: ParsedCircuit,
    is_dc: bool,
    frequency: Optional[float],
    analysis_type: AnalysisType,
    terminals: Optional[TheveninTerminals],
    raw_nodes: Dict[str, complex],
    raw_currents: Dict[str, complex],
    results: AnalysisResults,
    mesh_analysis=None,
    superposition=None,
    port_extras: Optional[PortExtras] = None,
    power_inapplicable_reason: Optional[str] = None,
    resonance_analysis=None,
    resonance_inapplicable_reason: Optional[str] = None,
    transformer_analysis=None,
    requested_type: Optional[AnalysisType] = None,
    reciprocity_analysis=None,
    reciprocity_inapplicable_reason: Optional[str] = None,
    zener_range_inapplicable_reason: Optional[str] = None,
    waveform_inapplicable_reason: Optional[str] = None,
) -> List[ExplanationSection]:
    """
    Çözümün Türkçe anlatımını üretir. Çözüm başarısızsa boş liste döner.

    analysis_type == MESH ise düğüm denklemleri yerine çevre akımları
    anlatılır (mesh_analysis: solver.mesh.MeshAnalysis). Çevre türetmesi
    çözücüyle doğrulanamazsa sebebi söylenip düğüm yöntemine dönülür.

    Bağımlı kaynaklı devrelerde düğüm denklemleri kontrol büyüklüğü düğüm
    gerilimleriyle yazılarak kurulur (explainer.dependent_nodal); kurulamayan ya da
    çözücüyle doğrulanamayan durumda dürüst yedek anlatım (çözücü sonuçları + sebep)
    verilir. port_extras: Thevenin/Norton'da kısa devre akımı ve test kaynağı sayıları.
    """
    nodes = {str(k): complex(v) for k, v in raw_nodes.items()}
    if len(nodes) <= 1:
        return []

    omega = None if is_dc or not frequency else 2 * math.pi * frequency
    ctx = _Ctx(
        parsed=parsed, is_dc=is_dc, frequency=frequency, omega=omega,
        analysis_type=analysis_type, terminals=terminals,
        v=nodes, i={k: complex(v) for k, v in raw_currents.items()},
        results=results, port=port_extras,
    )
    if analysis_type == AnalysisType.TRANSFORMER:
        if transformer_analysis is None:
            return []
        # Transformatörlü devre: düğüm/çevre anlatımı transformatörü yazamaz (iki uçlu eleman
        # varsayar); başka yöntem seçilmiş olsa da anlatım Transformatör yöntemiyle verilir
        from explainer.transformer_narrative import build_transformer_sections
        return [s.build() for s in
                build_transformer_sections(ctx, transformer_analysis, requested_type) if s.blocks]
    if ctx.has_dependent and analysis_type == AnalysisType.SUPERPOSITION:
        # Toplam sonuçlar süperpozisyon bölümündedir; bağımlı kaynaklar her adımda aktif
        return _build_dependent_explanation(ctx, superposition)
    ctx.known, ctx.groups, ctx.constraints = _node_groups(parsed, is_dc)

    if ctx.has_dependent:
        # Kontrol büyüklüğü düğüm gerilimleriyle yazılıp A·x = b kurulur ve çözücüyle
        # doğrulanır; olmazsa sebebiyle birlikte yedek anlatım
        from explainer import dependent_nodal as dn
        built = dn.build_system(ctx)
        if isinstance(built, str):
            ctx.dep_reason = built
            method_builders = (_dependent_solution, _currents)
        else:
            ctx.dep_system = built
            method_builders = (_known_nodes, dn.control_section, dn.kcl_section,
                               dn.solve_section, _dependent_check, _currents)
    else:
        method_builders = (_known_nodes, _kcl, _solve, _currents)
        if any(len(g) > 1 for g in ctx.groups):
            # Süperdüğüm: KCL + kaynak kısıtı birlikte kurulur, çözücüyle doğrulanır ve
            # yerine koyma ile çözülür. Kurulamazsa (ör. kaynak döngüsü) eski anlatım.
            from explainer import dependent_nodal as dn
            built = dn.build_system(ctx)
            if not isinstance(built, str):
                ctx.dep_system = built
                method_builders = (_known_nodes, dn.kcl_section, dn.solve_section, _currents)

    if analysis_type == AnalysisType.POWER:
        if results.power_summary is not None:
            sections: List[_Section] = []
            for builder in (
                _intro,
                _impedances,
                *method_builders,
                _power,
                _power_triangle,
                _compensation_section,
                _power_check,
                _power_summary_section,
            ):
                sections.extend(builder(ctx))
            return [s.build() for s in sections if s.blocks]
        else:
            why = (power_inapplicable_reason
                   or "Güç ve güç katsayısı yöntemi yalnızca tek frekanslı AC devrelerde uygulanabilir.")
            fallback = _Section("Güç ve Güç Katsayısı")
            fallback.note(
                f"Bu devrede Güç ve Güç Katsayısı yöntemi uygulanamadı: {why} "
                "“Düğüm Gerilimleri” yöntemini seçebilirsiniz; aynı sonuçları şimdi o "
                "yöntemle anlatıyoruz."
            )
            analysis_type = ctx.analysis_type = AnalysisType.NODAL
            method_builders = (lambda c: [fallback],) + method_builders

    if analysis_type == AnalysisType.RESONANCE:
        if resonance_analysis is not None and results.resonance is not None:
            # Döngüsel içe aktarmayı önlemek için yerel import
            from explainer.resonance_narrative import build_resonance_sections
            return [s.build() for s in build_resonance_sections(ctx, resonance_analysis) if s.blocks]
        why = (resonance_inapplicable_reason
               or "Rezonans yöntemi yalnızca seri ve paralel RLC devreleri için anlatılır.")
        fallback = _Section("Rezonans")
        fallback.note(
            f"Bu devrede Rezonans yöntemi uygulanamadı: {why} "
            "“Düğüm Gerilimleri” yöntemini seçebilirsiniz; aynı sonuçları şimdi o "
            "yöntemle anlatıyoruz."
        )
        analysis_type = ctx.analysis_type = AnalysisType.NODAL
        method_builders = (lambda c: [fallback],) + method_builders

    if analysis_type == AnalysisType.RECIPROCITY:
        # Döngüsel içe aktarmayı önlemek için yerel import
        from explainer.reciprocity_narrative import build_reciprocity
        if reciprocity_analysis is not None:
            extra, why = build_reciprocity(ctx, reciprocity_analysis)
        else:
            extra, why = None, (reciprocity_inapplicable_reason
                                or "karşıtlık teoremi bu devreye uygulanamadı.")
        if extra is not None:
            ctx.reciprocity = reciprocity_analysis
            method_builders = (lambda c: extra,)
        else:
            fallback = _Section("Karşıtlık Teoremi")
            fallback.note(
                f"Bu devrede karşıtlık teoremi uygulanamadı: {why} "
                "“Düğüm Gerilimleri” yöntemini seçebilirsiniz; aynı sonuçları şimdi o "
                "yöntemle anlatıyoruz."
            )
            analysis_type = ctx.analysis_type = AnalysisType.NODAL
            method_builders = (lambda c: [fallback],) + method_builders

    if analysis_type == AnalysisType.ZENER_RANGE:
        why = (zener_range_inapplicable_reason
               or "devrede zener diyot yok; Zener Aralığı bir zener regülatör devresi gerektirir")
        clean = why.strip().rstrip(".")
        fallback = _Section("Zener Aralığı")
        fallback.note(
            f"Bu devrede Zener Aralığı uygulanamadı: {clean}. "
            "“Düğüm Gerilimleri” yöntemini seçebilirsiniz; aynı sonuçları şimdi o "
            "yöntemle anlatıyoruz."
        )
        analysis_type = ctx.analysis_type = AnalysisType.NODAL
        method_builders = (lambda c: [fallback],) + method_builders

    if analysis_type == AnalysisType.WAVEFORM:
        why = (waveform_inapplicable_reason
               or "Dalga Şekli yöntemi diyotlu devreler içindir")
        clean = why.strip().rstrip(".")
        fallback = _Section("Dalga Şekli")
        fallback.note(
            f"Bu devrede Dalga Şekli yöntemi uygulanamadı: {clean}. "
            "“Düğüm Gerilimleri” yöntemini seçebilirsiniz; aynı sonuçları şimdi o "
            "yöntemle anlatıyoruz."
        )
        analysis_type = ctx.analysis_type = AnalysisType.NODAL
        method_builders = (lambda c: [fallback],) + method_builders

    if analysis_type in (AnalysisType.MILLMAN, AnalysisType.SOURCE_TRANSFORM):
        # Döngüsel içe aktarmayı önlemek için yerel import
        from explainer.millman import build_millman
        from explainer.source_transform import build_source_transform
        if analysis_type == AnalysisType.MILLMAN:
            extra, why = build_millman(ctx)
            title, what, fb_type = "Millman Teoremi", "Millman teoremi", AnalysisType.NODAL
            advice = ("“Düğüm Gerilimleri” yöntemini seçebilirsiniz; aynı sonuçları şimdi o "
                      "yöntemle anlatıyoruz.")
        else:
            extra, why = build_source_transform(ctx)
            title, what, fb_type = "Kaynak Dönüşümü", "kaynak dönüşümü yöntemi", AnalysisType.THEVENIN
            advice = ("“Thevenin Eşdeğeri” yöntemini seçebilirsiniz; aynı eşdeğeri şimdi o "
                      "yöntemle anlatıyoruz.")
        if extra is not None and analysis_type == AnalysisType.SOURCE_TRANSFORM:
            # Eşdeğer, dönüşüm bölümlerinde bulunur; tam çözümün düğüm/güç bölümleri eklenmez
            return [s.build() for s in _intro(ctx) + extra if s.blocks]
        if extra is not None:
            method_builders = (lambda c: extra,)
        else:
            fallback = _Section(title)
            fallback.note(f"Bu devrede {what} uygulanamadı: {why} {advice}")
            analysis_type = ctx.analysis_type = fb_type
            method_builders = (lambda c: [fallback],) + method_builders

    if analysis_type == AnalysisType.MESH:
        # Döngüsel içe aktarmayı önlemek için yerel import
        from explainer.mesh_narrative import build_mesh_sections, verify
        if mesh_analysis is not None and verify(ctx, mesh_analysis):
            ctx.mesh = mesh_analysis
            mesh_sections = build_mesh_sections(ctx, mesh_analysis)
            method_builders = (lambda c: mesh_sections,)
        else:
            reason = (mesh_analysis.reason if mesh_analysis is not None and mesh_analysis.reason
                      else "çevre akımlarından bulunan sonuçlar çözücüyle doğrulanamadı.")
            fallback = _Section("Çevre Akımları Yöntemi")
            fallback.note(f"Bu devrede çevre akımları yöntemi uygulanamadı: {reason} "
                          "Aynı sonuçları veren düğüm gerilimi yöntemiyle anlatıyoruz.")
            method_builders = (lambda c: [fallback],) + method_builders

    if analysis_type == AnalysisType.SUPERPOSITION and superposition:
        # Toplam sonuçlar süperpozisyon bölümündedir; tam çözümün güç/kontrol
        # bölümleri (farklı frekanslarda geçersiz olabilir) eklenmez
        from explainer.superposition_narrative import build_superposition_sections
        sup_sections = build_superposition_sections(ctx, superposition)
        return [s.build() for s in _intro(ctx) + sup_sections if s.blocks]

    sections: List[_Section] = []
    for builder in (
        _intro,
        _impedances,
        *method_builders,
        _thevenin,
        _norton,
        _power,
        _kcl_check,
        _time_domain,
        _summary,
    ):
        sections.extend(builder(ctx))
    return [s.build() for s in sections if s.blocks]


def _build_dependent_explanation(ctx: _Ctx, superposition) -> List[ExplanationSection]:
    """
    Bağımlı kaynaklı devrenin SÜPERPOZİSYON anlatımı: tanıtım + her bağımsız kaynağın
    katkısı (bağımlı kaynaklar sıfırlanmaz, her alt devrede aktif kalır).
    """
    from explainer.superposition_narrative import build_superposition_sections
    if superposition:
        tail = build_superposition_sections(ctx, superposition)
    else:
        s = _Section("Süperpozisyon")
        s.text("Süperpozisyonda yalnızca BAĞIMSIZ kaynaklar tek tek devre dışı bırakılır; "
               "bağımlı kaynaklar her adımda aktif kalır.")
        s.note("Bu devrede etkin (sıfırdan farklı) bağımsız kaynak yok. Bağımlı kaynaklar "
               "tek başına enerji sağlayamaz: tüm gerilim ve akımlar sıfırdır.")
        tail = [s]
    return [s.build() for s in _intro(ctx) + tail if s.blocks]


# ═══════════════════════════════════════════════════════
#  1. DEVREYİ TANIYALIM
# ═══════════════════════════════════════════════════════

def _intro(ctx: _Ctx) -> List[_Section]:
    s = _Section("Devreyi Tanıyalım")

    src_texts = []
    for e in ctx.sources():
        unit = "A" if e.element_type in CURRENT_SOURCES else "V"
        what = ("akım kaynağı, akımı kaynak içinde "
                f"{node_name(e.node_positive)} → {node_name(e.node_negative)} yönünde"
                if e.element_type in CURRENT_SOURCES else "")
        if e.element_type in DC_SOURCES:
            src_texts.append(f"{e.id} = {eng(e.value, unit)} (DC{', ' + what if what else ''})")
        elif e.element_type in SINE_SOURCES:
            f_lbl = "kaynak frekansı f" if ctx.analysis_type == AnalysisType.RESONANCE else "f"
            src_texts.append(
                f"{e.id}: {'etkin değer' if ctx.is_rms else 'genlik (tepe)'} "
                f"{eng(e.params.get('amplitude', e.value), unit)}, "
                f"{f_lbl} = {num(e.params.get('frequency', 0))} Hz, "
                f"faz {num(e.params.get('phase', 0))}°" + (f" ({what})" if what else ""))
        else:
            src_texts.append(
                f"{e.id} = {num(e.params.get('amplitude', e.value))}∠"
                f"{num(e.params.get('phase', 0))}° {unit} (fazör{', ' + what if what else ''})")
    passives = [ctx.element_value_text(e) for e in ctx.passive()]

    if src_texts:
        s.text(f"Kaynaklar: {', '.join(src_texts)}.")
    has_ac_source = any(e.element_type not in DC_SOURCES for e in ctx.sources())
    if not ctx.is_dc or (ctx.analysis_type == AnalysisType.SUPERPOSITION and has_ac_source):
        s.text(
            "Bu çözümde AC değerler etkin (RMS) olarak gösterilir."
            if ctx.is_rms
            else "Bu çözümde AC değerler tepe değer olarak gösterilir."
        )
        disp_basis = "RMS" if ctx.is_rms else "PEAK"
        for e in ctx.sources():
            if e.element_type in DC_SOURCES:
                continue
            in_basis = e.params.get("input_basis", "PEAK")
            if in_basis != disp_basis:
                unit = "A" if e.element_type in CURRENT_SOURCES else "V"
                p_sym = "Im" if e.element_type in CURRENT_SOURCES else "Um"
                r_sym = "I" if e.element_type in CURRENT_SOURCES else "V"
                in_val = float(e.params.get("input_value", e.value))
                shown_val = float(e.params.get("amplitude", e.value))
                if in_basis == "PEAK" and disp_basis == "RMS":
                    s.math(f"{e.id}: {p_sym} = {eng(in_val, unit)} (tepe) → "
                           f"{r_sym} = {p_sym}/√2 = {eng(shown_val, unit)} (etkin)")
                else:
                    s.math(f"{e.id}: {r_sym} = {eng(in_val, unit)} (etkin) → "
                           f"{p_sym} = √2·{r_sym} = {eng(shown_val, unit)} (tepe)")
    if passives:
        s.text(f"Pasif elemanlar: {', '.join(passives)}.")
    if ctx.diodes is not None:
        from explainer.diode_narrative import intro_line
        s.text(intro_line(ctx.diodes))
    if ctx.has_dependent:
        s.text("Bağımlı (kontrollü) kaynaklar: çıkışları başka bir elemanın gerilimi veya "
               "akımıyla orantılıdır (çıkış = kazanç · kontrol büyüklüğü).")
        for line in _dependent_lines(ctx):
            s.math(f"• {line}")

    nodes = sorted(ctx.v, key=lambda n: (len(n), n))
    s.text(
        f"Devrede {len(nodes)} düğüm var: "
        + ", ".join("0 (GND)" if n == "0" else n for n in nodes)
        + ". Toprak düğümü referans alınır: V₀ = 0 V."
    )

    if not ctx.is_dc and ctx.omega is not None:
        if ctx.analysis_type == AnalysisType.RESONANCE:
            s.math(f"ω₀ = 2π·f₀ = 2π · {num(ctx.frequency)} Hz = {num(ctx.omega)} rad/s")
        else:
            s.math(f"ω = 2πf = 2π · {num(ctx.frequency)} Hz = {num(ctx.omega)} rad/s")
        if ctx.is_rms:
            s.note("Fazörün büyüklüğü etkin (RMS) değerdir; tepe değer Um = √2·V olur.")
        else:
            s.note("Fazör gösteriminde V = Vm∠θ; Vm tepe (maksimum) değerdir, etkin değer değil.")

    if ctx.analysis_type == AnalysisType.THEVENIN and ctx.terminals:
        a, b = ctx.terminals.node_positive, ctx.terminals.node_negative
        s.text(
            f"Amaç: {node_name(a)} (+) ile {node_name(b)} (−) arasındaki Thevenin "
            "eşdeğerini bulmak. Thevenin teoremine göre bu iki uçtan bakıldığında "
            "devre, tek bir gerilim kaynağı (Vth) ve ona seri bir "
            + ("direnç (Rth)" if ctx.is_dc else "empedans (Zth)")
            + " gibi davranır. Vth'yi bulmak için önce düğüm gerilimlerini çözeceğiz."
        )
    elif ctx.analysis_type == AnalysisType.NORTON and ctx.terminals:
        a, b = ctx.terminals.node_positive, ctx.terminals.node_negative
        s.text(
            f"Amaç: {node_name(a)} (+) ile {node_name(b)} (−) arasındaki Norton "
            "eşdeğerini bulmak: bir akım kaynağı (In) ve ona paralel bir "
            + ("direnç (Rn)" if ctx.is_dc else "empedans (Zn)")
            + ". Önce düğüm gerilimlerini çözeceğiz."
        )
    elif ctx.analysis_type == AnalysisType.MILLMAN:
        s.text(
            "Millman teoremiyle çözeceğiz: devre, iki düğüm arasına paralel bağlı kollar olarak "
            "ele alınır. Önce bu iki düğüm arasındaki gerilimi tek bir formülle bulacağız, sonra her "
            "kolun akımını Ohm yasasıyla hesaplayacağız."
        )
    elif ctx.analysis_type == AnalysisType.RECIPROCITY and ctx.reciprocity is not None:
        ra = ctx.reciprocity
        s.text(
            f"Karşıtlık teoremiyle çözeceğiz: {ra.source.id} kaynağını {ra.target.id} koluna "
            "taşıyıp ölçülen "
            + ("akımın" if ra.form == "current" else "gerilimin")
            + " değişmediğini göstereceğiz. Önce kaynak kendi yerindeyken, sonra "
            f"{ra.target.id} koluna taşınmışken devreyi inceleyeceğiz."
        )
    elif ctx.analysis_type == AnalysisType.SOURCE_TRANSFORM and ctx.terminals:
        a, b = ctx.terminals.node_positive, ctx.terminals.node_negative
        s.text(
            f"Amaç: {node_name(a)} (+) ile {node_name(b)} (−) arasındaki Thevenin/Norton eşdeğerini, devreyi "
            "kaynak dönüşümleriyle (gerilim kaynağı ⇄ akım kaynağı) adım adım sadeleştirerek bulmak."
        )
    elif ctx.analysis_type == AnalysisType.SUPERPOSITION:
        s.text(
            "Süperpozisyon yöntemiyle çözeceğiz: her kaynağın etkisini, diğer "
            "kaynaklar sıfırlanmışken ayrı ayrı bulup sonuçları toplayacağız."
        )
    elif ctx.analysis_type == AnalysisType.POWER:
        ps = ctx.results.power_summary
        comp_txt = (
            f" ve güç katsayısını cos φ₂ = {num(ps.compensation.target_pf, 4)} hedefine "
            "getirecek kompanzasyon kondansatörünü (C) belirlemek"
            if ps is not None and ps.compensation is not None else ""
        )
        s.text(
            "Amaç: Önce düğüm gerilimlerini ve eleman akımlarını bularak devrenin aktif (P), "
            f"reaktif (Q) ve görünür (S) güçlerini, güç üçgenini ve güç katsayısını (cos φ) hesaplamak{comp_txt}."
        )
    elif ctx.analysis_type == AnalysisType.RESONANCE:
        s.text(
            "Amaç: seri ya da paralel RLC devresinin rezonans frekansını (f₀), kalite faktörünü (Q) "
            "ve bant genişliğini (BW) bulmak; rezonansta empedansı, akımı ve bobin ile "
            "kondansatörün gerilim/akımını hesaplamak."
        )
        s.text(
            "Rezonans yönteminde kaynağın frekansı kullanılmaz: rezonans frekansı devrenin kendi "
            "L ve C değerlerinden bulunur ve devre bu f₀ frekansında çözülür."
        )
    elif ctx.has_dependent and not (ctx.analysis_type == AnalysisType.MESH
                                    and ctx.mesh is not None):
        if ctx.dep_system is not None:
            s.text(
                "Düğüm gerilimi yöntemiyle çözeceğiz: önce bağımlı kaynağın kontrol büyüklüğünü "
                "bilinmeyen düğüm gerilimleriyle yazacağız, sonra KCL denklemlerini kurup "
                "bilinmeyen düğüm gerilimlerini bulacağız (bağımlı kaynak denkleme bilinmeyen "
                "bir terim getirir) ve Ohm yasasıyla her elemanın akımını hesaplayacağız."
            )
        else:
            s.text(
                "Düğüm gerilimleri ve eleman akımları çözücü tarafından bulundu; aşağıda "
                "sonuçları Ohm yasası ve KCL ile birlikte inceleyeceğiz."
            )
    elif ctx.analysis_type == AnalysisType.MESH:
        s.text(
            "Çevre akımları yöntemiyle çözeceğiz: her bağımsız çevreye (göze) bir "
            "çevre akımı atayıp KVL denklemlerini yazacağız; eleman akımlarını "
            "çevre akımlarından bulacağız."
        )
    else:
        s.text(
            "Düğüm gerilimi yöntemiyle çözeceğiz: önce bilinmeyen düğüm "
            "gerilimlerini KCL ile bulacağız, sonra Ohm yasasıyla her elemanın "
            "akımını hesaplayacağız."
        )
    return [s]


# ═══════════════════════════════════════════════════════
#  2. EMPEDANSLAR (AC)
# ═══════════════════════════════════════════════════════

def _impedances(ctx: _Ctx) -> List[_Section]:
    if ctx.is_dc or ctx.omega is None:
        return []
    s = _Section("Empedanslar ve Fazörler")
    s.text(f"Her elemanı ω = {num(ctx.omega)} rad/s'deki empedansıyla gösteririz:")
    w = num(ctx.omega)
    for e in ctx.passive():
        z = ctx.impedance(e)
        t = e.element_type
        if t == ElementType.CAPACITOR:
            s.math(f"Z_{e.id} = 1/(jωC) = 1/(j · {w} · {eng(e.value, 'F')}) = {rect(z, 'Ω')}")
        elif t == ElementType.INDUCTOR:
            s.math(f"Z_{e.id} = jωL = j · {w} · {eng(e.value, 'H')} = {rect(z, 'Ω')}")
        elif t == ElementType.RESISTOR:
            s.math(f"{e.id} = {eng(e.value, 'Ω')} (direncin empedansı gerçektir, frekanstan bağımsızdır)")
        else:
            s.math(f"{e.id} = {rect(z, 'Ω')} = {polar(z, 'Ω', scaled=False)}")
    for e in ctx.sources():
        vs = _source_value(e, False)
        unit = "A" if e.element_type in CURRENT_SOURCES else "V"
        if abs(vs) > 0:
            s.math(f"{e.id} = {polar(vs, unit, scaled=False)} = {rect(vs, unit)}")
    has_c = any(e.element_type == ElementType.CAPACITOR for e in ctx.passive())
    has_l = any(e.element_type == ElementType.INDUCTOR for e in ctx.passive())
    if has_c and has_l:
        s.note("Kondansatörün empedansı −j yönünde (kapasitif), bobininki +j yönündedir (endüktif).")
    elif has_c:
        s.note("Kondansatörün empedansı −j yönündedir (kapasitif).")
    elif has_l:
        s.note("Bobinin empedansı +j yönündedir (endüktif).")
    return [s]


# ═══════════════════════════════════════════════════════
#  11. SONUÇ
# ═══════════════════════════════════════════════════════

def _summary(ctx: _Ctx) -> List[_Section]:
    s = _Section("Sonuç")
    if ctx.mesh is not None:
        for k, current in enumerate(ctx.mesh.mesh_currents, 1):
            s.result(f"I{str(k).translate(str.maketrans('0123456789', '₀₁₂₃₄₅₆₇₈₉'))} "
                     f"(çevre akımı) = {ctx.val(current, 'A')}")
    for n in sorted((n for n in ctx.v if n != "0"), key=lambda n: (len(n), n)):
        s.result(f"{node_v(n)} = {ctx.val(ctx.node_value(n), 'V')}")
    if ctx.diodes is not None:
        from explainer.diode_narrative import summary_lines
        for line in summary_lines(ctx.diodes, ctx.i):
            s.result(line)
    for pr in ctx.results.probe_results:
        value = pr.value
        z = complex(value) if isinstance(value, (int, float)) else complex(value.real, value.imaginary)
        s.result(f"{pr.probe_id} ({'gerilim' if pr.type == 'V' else 'akım'} probu) = {ctx.val(z, pr.unit)}")
    def cz(c) -> complex:
        return complex(c.real, c.imaginary)

    def imp(z: complex) -> str:
        return eng(z.real, 'Ω') if ctx.is_dc else rect(z, 'Ω')

    th, no = ctx.results.thevenin, ctx.results.norton
    if th is not None and ctx.analysis_type == AnalysisType.THEVENIN:
        s.result(f"Thevenin: Vth = {ctx.val(cz(th.vth), 'V')}, "
                 f"{'Rth' if ctx.is_dc else 'Zth'} = {imp(cz(th.zth))}")
    if no is not None and ctx.analysis_type == AnalysisType.NORTON:
        zn = "∞" if no.z_n is None else imp(cz(no.z_n))
        s.result(f"Norton: In = {ctx.val(cz(no.i_n), 'A')}, "
                 f"{'Rn' if ctx.is_dc else 'Zn'} = {zn}")
    return [s]
