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

import copy
import math
import cmath
import traceback
from typing import Tuple, List, Optional, Union

import sympy

from models.response import (
    AnalysisResults, SolutionStep, ComplexNumber,
    ExplanationBlock, ExplanationSection, TransientQuantityResult, TransientResult,
    NodeVoltage, ElementCurrent, ProbeResult, TheveninResult, NortonResult,
    ElementPower, PowerAnalysis, SeriesParallelReduction, MeshInfo,
    SourceContribution,
)
from models.request import (
    AnalysisMode, AnalysisType, TheveninTerminals, ProbeTarget
)
from parser.netlist_parser import (
    ParsedCircuit, ParsedElement, ParsedProbe,
    ElementType, to_lcapy_netlist, lcapy_sense_map,
    ALL_SOURCES, CURRENT_SOURCES, DEPENDENT_SOURCES, DEPENDENT_CURRENT_OUTPUT,
    VOLTAGE_SOURCES,
    SWITCH_NOTE, circuit_at_time, has_switches,
)
from explainer.step_generator import generate_solution_steps
from explainer.topology import generate_topology_step
from explainer.narrative import PortExtras, build_explanation, port_is_dead
from solver.frequency_check import check_source_frequencies
from solver.mesh import analyze_meshes
from solver.superposition import solve_contributions
from practice.questions import build_questions
from practice.transient_questions import build_transient_questions
from explainer.transient_narrative import build_transient_explanation
from solver.transient import TransientNotApplicable, analyze_transient


# ═══════════════════════════════════════════════════════
#  SYMPY ↔ PYTHON DÖNÜŞÜM ARAÇLARI
# ═══════════════════════════════════════════════════════

def sympy_to_numeric(expr) -> Union[float, complex]:
    """
    SymPy ifadesini Python float veya complex'e dönüştürür.

    Dönüşüm öncelik sırası:
        1. None / 0 → 0.0
        2. Zaten float/int/complex ise → doğrudan döndür
        3. SymPy sayısal (Integer, Float, Rational) → float()
        4. SymPy karmaşık (a + b*I) → complex()
        5. Sembolik (hâlâ değişken içeriyor) → evalf() → complex()

    Args:
        expr: SymPy ifadesi veya Python sayı

    Returns:
        float veya complex
    """
    if expr is None:
        return 0.0

    # Zaten Python sayısıysa doğrudan döndür
    if isinstance(expr, (int, float)):
        return float(expr)
    if isinstance(expr, complex):
        return expr if abs(expr.imag) > 1e-12 else expr.real

    # lcapy Expr sarmalayıcısını aç — SymPy fonksiyonlarına lcapy nesnesi
    # vermek deprecation uyarısı üretir
    expr = _to_sympy(expr)

    try:
        # SymPy → float dene
        val = float(expr)
        return val
    except (TypeError, ValueError):
        pass

    try:
        # SymPy → complex (önce evalf ile sayısala çevir)
        evaluated = expr.evalf()
        val = complex(evaluated)
        if abs(val.imag) < 1e-12:
            return val.real
        return val
    except (TypeError, ValueError, AttributeError):
        pass

    try:
        # lcapy PhasorDomainVoltage/Current — complex() doğrudan çalışmaz
        # ama .real ve .imag SymPy ifadeleri döndürür
        re_part = float(sympy.re(expr).evalf())
        im_part = float(sympy.im(expr).evalf())
        if abs(im_part) < 1e-12:
            return re_part
        return complex(re_part, im_part)
    except (TypeError, ValueError, AttributeError):
        pass

    try:
        # lcapy Expr: .expr ile alttaki SymPy ifadesine eriş
        underlying = getattr(expr, 'expr', None)
        if underlying is not None and underlying is not expr:
            return sympy_to_numeric(underlying)
    except:
        pass

    try:
        # Son çare: string'e çevirip complex() dene
        s = str(expr.evalf())
        s = s.replace("*I", "j").replace("I", "j")
        val = complex(s)
        if abs(val.imag) < 1e-12:
            return val.real
        return val
    except:
        return 0.0


def _to_sympy(expr):
    """
    lcapy Expr nesnesini alttaki SymPy ifadesine açar.

    lcapy sonuçları (ConstantDomainExpression, PhasorDomainVoltage,
    LaplaceDomainImpedance...) SymPy ifadesini '.expr' içinde taşır.
    Zaten SymPy olan veya '.expr' taşımayan nesneler aynen döner.
    """
    if isinstance(expr, sympy.Basic):
        return expr
    try:
        underlying = getattr(expr, 'expr', None)
    except Exception:
        return expr
    return underlying if isinstance(underlying, sympy.Basic) else expr


def sympy_to_latex(expr) -> Optional[str]:
    """
    SymPy ifadesini LaTeX string'e dönüştürür.

    Örnekler:
        sympy.Rational(8, 1) → "8"
        V2 / 1000 + V2 / 2000 → "\\frac{V_{2}}{1000} + \\frac{V_{2}}{2000}"

    Returns:
        LaTeX string veya None (dönüşüm başarısızsa)
    """
    if expr is None:
        return None
    try:
        return sympy.latex(expr)
    except:
        return str(expr)


def sig_round(x: float, digits: int = 10) -> float:
    """
    Anlamlı basamağa yuvarlar: 4.7e-6 → 4.7e-6.

    Eskiden round(x, 6) kullanılıyordu; mikro düzeyindeki değerleri
    bozuyordu (4.7 µA → 5 µA, 0.4 µA → 0). Femto altı gürültü 0 olur.
    """
    if not math.isfinite(x):
        return x
    if abs(x) < 1e-15:
        return 0.0
    return float(f"{x:.{digits}g}")


def make_complex_number(value: Union[float, complex]) -> ComplexNumber:
    """
    Python float/complex → Pydantic ComplexNumber modeli.

    Her iki gösterim formunu (dikdörtgensel + kutupsal) üretir:
        float(6.0)          → real=6, imag=0, mag=6, phase=0°
        complex(3+4j)       → real=3, imag=4, mag=5, phase=53.13°

    Args:
        value: Python float veya complex

    Returns:
        ComplexNumber Pydantic modeli
    """
    if isinstance(value, (int, float)):
        value = complex(value, 0)

    real = value.real
    imag = value.imag
    magnitude = abs(value)
    # Sayısal gürültüyü temizle (ör. 8+1e-17j → 8): büyüklüğe göre
    # ihmal edilebilir kısımlar ve femto altı değerler 0 sayılır
    if magnitude < 1e-15:
        real = imag = magnitude = 0.0
    else:
        if abs(imag) <= 1e-12 * magnitude:
            imag = 0.0
        if abs(real) <= 1e-12 * magnitude:
            real = 0.0
    phase_deg = math.degrees(cmath.phase(complex(real, imag))) if magnitude > 1e-15 else 0.0

    # Dikdörtgensel gösterim: "50+j30" veya "6"
    if abs(imag) < 1e-10:
        rect_str = f"{real:.4g}"
    elif abs(real) < 1e-10:
        rect_str = f"{'−' if imag < 0 else ''}j{abs(imag):.4g}"
    else:
        sign = "+" if imag >= 0 else "−"
        rect_str = f"{real:.4g}{sign}j{abs(imag):.4g}"

    # Kutupsal gösterim: "58.31∠30.96°"
    if magnitude < 1e-15:
        polar_str = "0∠0°"
    else:
        polar_str = f"{magnitude:.4g}∠{phase_deg:.4g}°"

    return ComplexNumber(
        real=sig_round(real),
        imaginary=sig_round(imag),
        magnitude=sig_round(magnitude),
        phase_degrees=round(phase_deg, 4),
        rectangular_str=rect_str,
        polar_str=polar_str
    )


def _substitute_frequency(expr, frequency: float):
    """
    SymPy ifadesindeki omega sembollerini sayısal değerle değiştirir.

    lcapy AC sonuçları 'omega_0' sembolü içerir:
        V2 = -1000*j/(omega_0 - 100*j)

    Bu fonksiyon omega_0 = 2πf yerine koyar.

    ★ NOT: lcapy v1.26 'omega_0' kullanır, 'omega' değil!
    """
    if expr is None or frequency is None:
        return expr

    try:
        omega_val = 2 * sympy.pi * frequency

        # lcapy'nin kullandığı tüm olası sembol adları
        for sym in list(expr.free_symbols):
            name = str(sym)
            if name in ('omega_0', 'omega', 'Omega', 'w'):
                expr = expr.subs(sym, omega_val)
            elif name == 'f':
                expr = expr.subs(sym, frequency)
    except (AttributeError, TypeError):
        pass

    return expr


def _extract_numeric(
    expr, is_dc: bool, frequency: float = None
) -> Union[float, complex]:
    """
    lcapy ifadesinden sayısal değer çıkarır.

    İş akışı:
        1. DC ise .dc bileşenini al, AC ise .phasor (property!) al
        2. ExprDict ise ilk değeri çıkar
        3. Frekans varsa omega_0 = 2πf yerine koy
        4. sympy_to_numeric ile Python float/complex'e çevir

    ★ NOT: lcapy .phasor property'dır (parantessiz), method değil!
    ★ NOT: lcapy .ac ExprDict döndürür {omega_0: expr} formatında
    """
    raw = None

    if is_dc:
        for getter in [lambda e: e.dc, lambda e: e]:
            try:
                raw = getter(expr)
                break
            except:
                continue
    else:
        # lcapy AC stratejisi:
        # 1. .ac: ExprDict döndürür {omega_0: expr} — ilk değeri al
        #    Debug'da doğrulandı: expr.ac → ExprDict({omega_0: -1000j/(omega_0-100j)})
        # 2. .phasor(): Method — parametresiz çağrılırsa expression dönebilir
        # 3. Doğrudan ifade
        for getter in [
            lambda e: _exprdict_first(e.ac),  # ExprDict'ten ilk değer (birincil)
            lambda e: e.phasor(),              # method call (yedek)
            lambda e: e
        ]:
            try:
                raw = getter(expr)
                if raw is not None:
                    break
            except:
                continue

    if raw is None:
        raw = expr

    # Frekans yerine koyma (AC modda omega_0 sembolünü çözer)
    if frequency is not None:
        raw = _substitute_frequency(raw, frequency)

    return sympy_to_numeric(raw)


def _exprdict_first(expr_dict):
    """
    lcapy ExprDict'ten ilk değeri çıkarır.

    lcapy .ac özelliği ExprDict({omega_0: expr}) formatında döndürür.
    Bu fonksiyon ilk (ve genellikle tek) ifadeyi çıkarır.
    """
    try:
        # ExprDict bir dict-like objedir
        values = list(expr_dict.values())
        if values:
            return values[0]
    except:
        pass
    return expr_dict


def lcapy_element_current(
    cct, elem: ParsedElement, sense: dict, is_dc: bool, frequency: float = None
) -> Union[float, complex]:
    """
    Elemanın içinden n+ → n− akan akım (uygulamanın raporladığı işaret).

    • Bağımsız akım kaynağı: lcapy'ye uçlar ters yazıldığı için (bkz.
      to_lcapy_netlist) lcapy akımı kendi ilk→ikinci ucuna göre verir →
      işaret çevrilir. Sonuç: kaynak içinden n+ → n− (= kaynak değeri).
    • Akım çıkışlı bağımlı kaynak (G, F): lcapy bunun akımını vermez; elemanla
      seri konan 0 V'luk gizli ölçüm kaynağının akımı alınır (zaten n+ → n−).
    • Diğerleri: lcapy'nin eleman akımı.
    """
    if elem.element_type in DEPENDENT_CURRENT_OUTPUT:
        return _extract_numeric(cct[sense[elem.id][0]].I, is_dc, frequency)
    i_val = _extract_numeric(cct[elem.id].I, is_dc, frequency)
    if elem.element_type in CURRENT_SOURCES:
        i_val = -i_val
    return i_val


class InfiniteImpedanceError(ValueError):
    """Empedans sonsuz (açık devre) — ör: DC'de seri kapasitör."""


def _evaluate_impedance(
    expr, is_dc: bool, frequency: float = None
) -> Union[float, complex]:
    """
    lcapy Laplace alanı empedansını/admitansını sayısala çevirir.

    lcapy thevenin().Z ve norton().Y ifadelerini 's' cinsinden verir:
        Z(s) = R / (R·C·s + 1)

    Değerlendirme noktası:
        DC  →  s = 0           (C açık devre, L kısa devre)
        AC  →  s = jω = j2πf

    ★ NOT: Eski kod sadece omega_0 yerine koyuyordu; 's' sembolü
      kaldığı için dönüşüm başarısız olup sessizce 0 dönüyordu.

    Raises:
        InfiniteImpedanceError: Sonuç sonsuzsa (ör: DC'de seri kapasitör)
        ValueError: AC modda frekans bilinmiyorsa
    """
    e = _to_sympy(expr)

    s_syms = [sym for sym in getattr(e, 'free_symbols', ()) if str(sym) == 's']
    if s_syms:
        s = s_syms[0]
        if is_dc:
            s_val = sympy.Integer(0)
        elif frequency is not None:
            s_val = sympy.I * 2 * sympy.pi * sympy.nsimplify(frequency)
        else:
            raise ValueError("AC empedans için frekans gerekli.")

        evaluated = e.subs(s, s_val)
        if evaluated.has(sympy.nan):
            # 0/0 belirsizliği → limit ile çöz
            evaluated = sympy.limit(e, s, s_val)
        e = evaluated

    if frequency is not None:
        e = _substitute_frequency(e, frequency)

    if isinstance(e, sympy.Basic) and e.has(sympy.zoo, sympy.oo, -sympy.oo):
        raise InfiniteImpedanceError("Empedans sonsuz (açık devre).")

    return sympy_to_numeric(e)


# ═══════════════════════════════════════════════════════
#  ANA ÇÖZÜCÜ
# ═══════════════════════════════════════════════════════

def solve_circuit(
    parsed: ParsedCircuit,
    mode: AnalysisMode,
    frequency: Optional[float] = None,
    analysis_type: AnalysisType = AnalysisType.NODAL,
    thevenin_terminals: Optional[TheveninTerminals] = None,
    target_probes: Optional[List[ProbeTarget]] = None,
    warnings: Optional[List[str]] = None
) -> Tuple[AnalysisResults, List[SolutionStep], List[str]]:
    """
    Devreyi çözer (anahtarlı devreler için giriş noktası).

    • TRANSIENT: geçici durum (RC / RL) çözülür; devre uygun değilse Türkçe gerekçeyle
      anahtarların t > 0 konumunda Düğüm Gerilimleri yöntemine döner.
    • Anahtar içeren devre BAŞKA bir yöntemle çözülürse anahtarlar t > 0 konumunda alınır
      ve anlatımın başına bu durumu söyleyen bir not eklenir.
    • Anahtarsız devrede doğrudan _solve_core çalışır.
    """
    if analysis_type == AnalysisType.TRANSIENT:
        return _solve_transient(parsed, mode, frequency, target_probes, warnings)
    if has_switches(parsed) and not parsed.errors:
        results, steps, errors = _solve_core(
            circuit_at_time(parsed, "after"), mode, frequency, analysis_type,
            thevenin_terminals, target_probes, warnings)
        results.explanation.insert(0, ExplanationSection(
            title="Anahtar Konumu",
            blocks=[ExplanationBlock(kind="note", text=SWITCH_NOTE)]))
        return results, steps, errors
    return _solve_core(parsed, mode, frequency, analysis_type,
                       thevenin_terminals, target_probes, warnings)


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
    after = circuit_at_time(parsed, "after")
    results, steps, errors = _solve_core(
        after, mode, frequency, AnalysisType.NODAL, None, target_probes, warnings)
    if parsed.errors:
        return results, steps, errors

    analysis = None
    try:
        analysis = analyze_transient(parsed, mode == AnalysisMode.DC)
    except TransientNotApplicable as e:
        reason = str(e)
    except Exception as e:      # beklenmeyen hata: yanlış sonuç yerine dürüst yedek
        reason = f"Geçici durum hesaplanırken beklenmeyen bir hata oluştu ({type(e).__name__})."

    if analysis is None:
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


def _solve_core(
    parsed: ParsedCircuit,
    mode: AnalysisMode,
    frequency: Optional[float] = None,
    analysis_type: AnalysisType = AnalysisType.NODAL,
    thevenin_terminals: Optional[TheveninTerminals] = None,
    target_probes: Optional[List[ProbeTarget]] = None,
    warnings: Optional[List[str]] = None
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
        analysis_type: NODAL, MESH veya THEVENIN
        thevenin_terminals: Thevenin port tanımı (iki düğüm)
        target_probes: Ölçüm probları
        warnings: Verilirse frekans/süperpozisyon uyarıları bu listeye
            eklenir (API yanıtındaki 'warnings'); verilmezse 'errors'e.

    Returns:
        (AnalysisResults, List[SolutionStep], List[str])
        Sonuçlar, çözüm adımları ve hata/uyarı mesajları
    """
    results = AnalysisResults()
    steps: List[SolutionStep] = []
    errors: List[str] = []

    # ── Ön kontroller ──
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

    # ── Adım 1: Topoloji ──
    elem_summary = ", ".join(
        f"{e.id}({e.element_type.value})" for e in parsed.elements
    )
    steps.append(SolutionStep(
        step_number=1,
        title="Devre Topolojisi Belirleme",
        description=(
            f"Devrede {len(parsed.elements)} eleman ve "
            f"{parsed.node_count} düğüm tespit edildi.\n"
            f"Elemanlar: {elem_summary}\n"
            f"Referans: {'Node 0 (GND) ✓' if parsed.has_ground else 'GND YOK ✕'}"
        ),
        equations=[],
        result_snapshot={"element_count": len(parsed.elements),
                         "node_count": parsed.node_count}
    ))

    # ── Adım 1.5: Kaynak frekansı denetimi (süperpozisyon uyarısı) ──
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
                "\nBağımlı kaynaklar için 0 V'luk iç ölçüm kaynakları (Vsense_…) ve "
                "gizli düğümler (_s_…) eklendi; bunlar yalnızca çözücünün iç modelidir "
                "ve sonuçlarda görünmez."
            )

        steps.append(SolutionStep(
            step_number=2,
            title="Devre Modeli Oluşturma",
            description=(
                "Netlist lcapy formatına dönüştürüldü ve "
                "sembolik devre modeli oluşturuldu." + model_note
            ),
            equations=lcapy_text.split("\n"),
            result_snapshot={"lcapy_netlist": lcapy_text}
        ))

        cct = Circuit(lcapy_text)

    except ImportError:
        errors.append(
            "lcapy kütüphanesi bulunamadı. "
            "Kurulum: pip install lcapy"
        )
        return results, steps, errors
    except Exception as e:
        errors.append(
            f"Devre modeli oluşturulurken hata: {str(e)}\n"
            "Olası nedenler:\n"
            "  • Netlist formatı hatalı olabilir\n"
            "  • Desteklenmeyen eleman tipi olabilir"
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
        errors.append(f"ℹ Seri/paralel analizi yapılamadı: {str(e)}")

    # ── Adım 2.5: Eğitici adımlar (Empedans / KVL / KCL) ──
    try:
        edu_steps = generate_solution_steps(
            parsed=parsed,
            frequency=frequency,
            is_dc=is_dc
        )
        if edu_steps:
            # Adım numaralarını mevcut adımların devamı olarak ata
            base_num = len(steps)
            for i, es in enumerate(edu_steps):
                es.step_number = base_num + i + 1
            steps.extend(edu_steps)
    except Exception as e:
        errors.append(f"ℹ Eğitici adımlar oluşturulamadı: {str(e)}")

    # ── Adım 3: Düğüm gerilimleri ──
    raw_nodes = {"0": 0.0}
    node_voltages = _solve_node_voltages(
        cct, parsed, is_dc, frequency, steps, errors, raw_nodes
    )
    results.node_voltages = node_voltages

    # ── Adım 4: Eleman akımları ──
    raw_currents = {}
    element_currents = _solve_element_currents(
        cct, parsed, is_dc, frequency, steps, errors, raw_currents
    )
    results.element_currents = element_currents

    # ── Adım 4.5: Güç analizi (P, Q, S, cos φ) ──
    results.power = _compute_power(
        parsed, raw_nodes, raw_currents, is_dc, steps, errors
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
            errors.append(f"ℹ Çevre akımları analizi yapılamadı: {str(e)}")

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
        except Exception as e:
            errors.append(f"ℹ Süperpozisyon analizi yapılamadı: {str(e)}")

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
            errors.append(f"ℹ Kısa devre/test kaynağı hesabı yapılamadı: {str(e)}")

    # ── Adım 7: Öğrenci için Türkçe anlatım (kalıp tabanlı) ──
    try:
        results.explanation = build_explanation(
            parsed, is_dc, frequency, analysis_type, thevenin_terminals,
            raw_nodes, raw_currents, results, mesh_analysis, contributions,
            port_extras,
        )
    except Exception as e:
        errors.append(f"ℹ Anlatım oluşturulamadı: {str(e)}")

    # ── Adım 7.5: Alıştırma modu soruları ──
    try:
        results.practice = build_questions(
            parsed, is_dc, frequency, analysis_type, thevenin_terminals,
            raw_nodes, raw_currents, results, make_complex_number,
            mesh_analysis, contributions,
        )
    except Exception as e:
        errors.append(f"ℹ Alıştırma soruları oluşturulamadı: {str(e)}")

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

# Çözülemeyen (tekil) devre hatasının işareti; main.py bu önekle başlayan hatayı
# "Devre çözülemedi" yanıtına (HTTP 422) çevirir.
UNSOLVABLE_PREFIX = "⛔ "


def _unsolvable_reason(cct, parsed: ParsedCircuit, is_dc: bool,
                       frequency: Optional[float]) -> Optional[str]:
    """
    Devre denklemleri tekilse (tek bir çözüm yoksa) öğrenciye Türkçe açıklama döndürür,
    çözülebiliyorsa None. lcapy tekil sistemde "MNA A matrix is not invertible" verir.
    """
    nodes = sorted({n for e in parsed.elements
                    for n in (e.node_positive, e.node_negative)} - {"0"})
    if not nodes:
        return None
    try:
        _extract_numeric(cct[nodes[0]].V, is_dc, frequency)
        return None
    except Exception as e:
        msg = str(e).lower()
        if "invertible" not in msg and "singular" not in msg:
            return None   # başka tür hata: olağan akış kendi mesajını üretir

    lines = ["Bu devrenin tek bir çözümü yok: devre denklemleri birbiriyle çelişiyor "
             "ya da bilinmeyenleri bulmaya yetmiyor (tekil sistem).", "", "Olası nedenler:"]
    if any(e.element_type in DEPENDENT_SOURCES for e in parsed.elements):
        lines.append("• Bağımlı kaynağın kazancı, devredeki dirençlerin etkisini tam olarak "
                     "sıfırlıyor olabilir. Örneğin tek çevrede R1 + R2 + R3 − k·R = 0 olursa "
                     "kaynak sıfır dirençle kısa devre edilmiş gibi olur. Kazancı ya da bir "
                     "direnç değerini değiştirmeyi deneyin.")
    lines += [
        "• İki gerilim kaynağı doğrudan paralel bağlı ya da bir gerilim kaynağı kısa devre edilmiş olabilir.",
        "• İki akım kaynağı doğrudan seri bağlı olabilir.",
        "• Devrenin bir kısmı GND'ye hiçbir yolla bağlı olmayabilir (boşta kalan eleman).",
    ]
    if is_dc and any(e.element_type in (ElementType.CAPACITOR, ElementType.INDUCTOR)
                     for e in parsed.elements):
        lines.append("• DC analizde bobin kısa devre, kondansatör açık devre sayılır; "
                     "bu da yukarıdaki durumlardan birini oluşturabilir.")
    return "\n".join(lines)


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
        all_nodes.add(elem.node_positive)
        all_nodes.add(elem.node_negative)

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
                    f"⚠ Düğüm {node}: Tekil matris hatası.\n"
                    "Bu genellikle devrede açık devre (floating node) "
                    "veya kısa devre olduğunu gösterir.\n"
                    "Lütfen tüm düğümlerin GND'ye bir yol ile "
                    "bağlı olduğundan emin olun."
                )
            elif "not connected" in err_msg or "floating" in err_msg:
                errors.append(
                    f"⚠ Düğüm {node}: Bu düğüm devrenin geri kalanına "
                    "bağlı değil (floating node).\n"
                    "Lütfen tüm elemanların tel ile bağlandığından emin olun."
                )
            else:
                errors.append(
                    f"⚠ Düğüm {node} gerilimi hesaplanamadı: {str(e)}"
                )

    # Çözüm adımı
    if solved_nodes:
        equations = []
        latex_parts = []
        for node, val in solved_nodes.items():
            if isinstance(val, complex):
                sign = "-" if val.imag < 0 else "+"
                eq = f"V({node}) = {val.real:.4g} {sign} j{abs(val.imag):.4g} V"
                latex_parts.append(
                    f"V_{{{node}}} = {val.real:.4g} {sign} j{abs(val.imag):.4g}"
                )
            else:
                eq = f"V({node}) = {val:.4g} V"
                latex_parts.append(f"V_{{{node}}} = {val:.4g}")
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
                f"ℹ {elem.id} akımı hesaplanamadı: {str(e)}"
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


# ═══════════════════════════════════════════════════════
#  THEVENİN EŞDEĞERİ
# ═══════════════════════════════════════════════════════

def _solve_thevenin(
    cct,
    terminals: TheveninTerminals,
    is_dc: bool,
    frequency: float,
    steps: List[SolutionStep],
    errors: List[str]
) -> Optional[TheveninResult]:
    """
    İki terminal (port) arasındaki Thevenin eşdeğerini hesaplar.

    Thevenin Teoremi:
        Vth = Açık devre gerilimi (OCV) — terminaller arasında
              yük yokken ölçülen gerilim.
        Zth = Thevenin empedansı — tüm bağımsız kaynaklar
              sıfırlanıp (V→kısa, I→açık) terminallerden
              bakılan empedans.

    ★ 2-Terminal (Port) Desteği:
        cct.thevenin(node_pos, node_neg)
        Varsayılan: node_neg = "0" (GND)
    """
    node_pos = terminals.node_positive
    node_neg = terminals.node_negative

    steps.append(SolutionStep(
        step_number=len(steps) + 1,
        title=f"Thevenin Eşdeğeri (Node {node_pos} – Node {node_neg})",
        description=(
            f"Düğüm {node_pos} ve Düğüm {node_neg} arasındaki "
            "Thevenin eşdeğer devresi hesaplanıyor.\n\n"
            "Adım A: Açık devre gerilimi (Vth) — terminaller "
            "arasında yük bağlamadan gerilimi ölç.\n"
            "Adım B: Thevenin empedansı (Zth) — tüm bağımsız "
            "kaynakları sıfırla, terminallerden bak."
        )
    ))

    try:
        # lcapy thevenin çağrısı — iki düğüm arası port
        th = cct.thevenin(node_pos, node_neg)

        # Vth — _extract_numeric omega yerine koymasını halleder
        vth_val = _extract_numeric(th.V, is_dc, frequency)

        # Zth — lcapy Laplace alanında verir (s); DC'de s=0, AC'de s=jω
        zth_val = _evaluate_impedance(th.Z, is_dc, frequency)

        vth_complex = make_complex_number(vth_val)
        zth_complex = make_complex_number(zth_val)

        thevenin_result = TheveninResult(
            vth=vth_complex,
            zth=zth_complex,
            node_positive=node_pos,
            node_negative=node_neg
        )

        # Thevenin sonuç LaTeX
        vth_latex = (
            f"V_{{th}} = {vth_complex.rectangular_str} \\text{{ V}}"
        )
        zth_latex = (
            f"Z_{{th}} = {zth_complex.rectangular_str} \\text{{ Ω}}"
        )

        steps.append(SolutionStep(
            step_number=len(steps) + 1,
            title="Thevenin Sonuçları",
            description=(
                f"Vth = {vth_complex.rectangular_str} V "
                f"({vth_complex.polar_str} V)\n"
                f"Zth = {zth_complex.rectangular_str} Ω "
                f"({zth_complex.polar_str} Ω)"
            ),
            equations=[
                f"Vth = {vth_complex.rectangular_str} V",
                f"Zth = {zth_complex.rectangular_str} Ω"
            ],
            latex_formula=f"{vth_latex} \\quad , \\quad {zth_latex}",
            result_snapshot={
                "Vth": vth_complex.rectangular_str,
                "Zth": zth_complex.rectangular_str,
                "Vth_polar": vth_complex.polar_str,
                "Zth_polar": zth_complex.polar_str
            }
        ))

        return thevenin_result

    except InfiniteImpedanceError:
        errors.append(
            f"⚠ Thevenin hesaplanamadı (Düğüm {node_pos}–{node_neg}): "
            "Zth sonsuz.\n"
            "Terminallerden bakıldığında devre açık görünüyor — ör: DC "
            "analizde seri bağlı bir kapasitör akımı keser.\n"
            "Bu port için Thevenin eşdeğeri tanımsızdır."
        )
        return None
    except Exception as e:
        err_str = str(e).lower()
        if "singular" in err_str:
            errors.append(
                f"⚠ Thevenin hesaplanamadı (Düğüm {node_pos}–{node_neg}):\n"
                "Tekil matris hatası — bu genellikle seçilen terminaller "
                "arasında geçerli bir devre yolu olmadığı anlamına gelir.\n"
                "Lütfen terminal düğümlerinin doğru seçildiğinden "
                "emin olun."
            )
        elif "not found" in err_str or "unknown" in err_str:
            errors.append(
                f"⚠ Düğüm {node_pos} veya {node_neg} devrede bulunamadı.\n"
                "Lütfen Thevenin terminal düğümlerinin devredeki "
                "geçerli düğüm numaraları olduğunu kontrol edin."
            )
        else:
            errors.append(
                f"⚠ Thevenin hesaplama hatası: {str(e)}\n"
                f"Detay: {traceback.format_exc()}"
            )
        return None


# ═══════════════════════════════════════════════════════
#  NORTON EŞDEĞERİ
# ═══════════════════════════════════════════════════════

def _solve_norton(
    cct,
    terminals: TheveninTerminals,
    is_dc: bool,
    frequency: float,
    steps: List[SolutionStep],
    errors: List[str]
) -> Optional[NortonResult]:
    """
    İki terminal (port) arasındaki Norton eşdeğerini hesaplar.

    Norton Teoremi (Thevenin'in dual'i):
        In = Kısa devre akımı (Isc) — terminaller kısa devre
             edildiğinde (+)'dan (−)'ye akan akım.
        Zn = Zth — tüm bağımsız kaynaklar sıfırlanıp
             terminallerden bakılan empedans (Yn = 1/Zn).

    ★ lcapy notu: cct.norton(n1, n2).I bu sürümde boş
      SuperpositionCurrent({}) döndürüyor. Bu yüzden In, aynı
      Norton nesnesinin .Isc alanından alınır ve In = Vth·Yn
      (= Vth/Zth) ile çapraz doğrulanır.
    """
    node_pos = terminals.node_positive
    node_neg = terminals.node_negative

    steps.append(SolutionStep(
        step_number=len(steps) + 1,
        title=f"Norton Eşdeğeri (Node {node_pos} – Node {node_neg})",
        description=(
            f"Düğüm {node_pos} ve Düğüm {node_neg} arasındaki "
            "Norton eşdeğer devresi hesaplanıyor.\n\n"
            "Adım A: Kısa devre akımı (In) — terminalleri bir tel ile "
            "kısa devre et, telden geçen akımı bul.\n"
            "Adım B: Norton empedansı (Zn) — tüm bağımsız kaynakları "
            "sıfırla (V→kısa devre), terminallerden bak. Zn = Zth.\n"
            "Kontrol: In = Vth / Zth (Thevenin ↔ Norton dönüşümü)."
        )
    ))

    try:
        no = cct.norton(node_pos, node_neg)

        in_val = _extract_numeric(no.Isc, is_dc, frequency)
        vth_val = _extract_numeric(no.Voc, is_dc, frequency)
        yn_val = _evaluate_impedance(no.Y, is_dc, frequency)

        zn_finite = abs(yn_val) > 1e-15
        zn_val = (1 / yn_val) if zn_finite else None

        # Çapraz doğrulama: In = Vth · Yn
        expected_in = vth_val * yn_val
        if abs(in_val - expected_in) > 1e-6 * max(abs(expected_in), 1e-9):
            errors.append(
                f"ℹ Norton tutarlılık uyarısı: Isc={in_val} ancak "
                f"Vth·Yn={expected_in}."
            )

        in_c = make_complex_number(in_val)
        yn_c = make_complex_number(yn_val)
        zn_c = make_complex_number(zn_val) if zn_finite else None
        vth_c = make_complex_number(vth_val)

        result = NortonResult(
            i_n=in_c,
            z_n=zn_c,
            y_n=yn_c,
            node_positive=node_pos,
            node_negative=node_neg
        )

        zn_str = f"{zn_c.rectangular_str} Ω" if zn_c else "∞ Ω"
        zn_polar = f"{zn_c.polar_str} Ω" if zn_c else "∞"
        equations = [
            f"In = Isc = {in_c.rectangular_str} A",
            f"Yn = {yn_c.rectangular_str} S",
            f"Zn = Zth = 1/Yn = {zn_str}",
        ]
        zn_latex = zn_c.rectangular_str if zn_c else "\\infty"
        latex = [
            f"I_{{N}} = {in_c.rectangular_str} \\text{{ A}}",
            f"Z_{{N}} = {zn_latex} \\text{{ Ω}}",
        ]
        if zn_c:
            equations.append(
                f"Kontrol: In = Vth / Zth = ({vth_c.rectangular_str}) / "
                f"({zn_c.rectangular_str}) = {in_c.rectangular_str} A"
            )
            latex.append(
                f"I_{{N}} = \\frac{{V_{{th}}}}{{Z_{{th}}}} = "
                f"\\frac{{{vth_c.rectangular_str}}}{{{zn_c.rectangular_str}}}"
            )
        else:
            equations.append(
                "Zn sonsuz → Norton eşdeğeri ideal bir akım kaynağıdır "
                "(Thevenin eşdeğeri tanımsız)."
            )

        steps.append(SolutionStep(
            step_number=len(steps) + 1,
            title="Norton Sonuçları",
            description=(
                f"In = {in_c.rectangular_str} A ({in_c.polar_str} A)\n"
                f"Zn = {zn_str} ({zn_polar})"
            ),
            equations=equations,
            latex_formula=" \\quad , \\quad ".join(latex),
            result_snapshot={
                "In": in_c.rectangular_str,
                "In_polar": in_c.polar_str,
                "Zn": zn_c.rectangular_str if zn_c else "∞",
                "Zn_polar": zn_polar,
                "Yn": yn_c.rectangular_str,
                "Vth": vth_c.rectangular_str,
            }
        ))

        return result

    except Exception as e:
        err_str = str(e).lower()
        if "not invertible" in err_str or "singular" in err_str:
            errors.append(
                f"⚠ Norton hesaplanamadı (Düğüm {node_pos}–{node_neg}): "
                "terminaller kısa devre edildiğinde bir gerilim kaynağı "
                "da kısa devre oluyor.\n"
                "Port doğrudan ideal bir gerilim kaynağına paralel → "
                "Zth = 0 ve In = Vth/0 sonsuz.\n"
                "Bu port için Norton eşdeğeri tanımsızdır "
                "(Thevenin eşdeğeri: yalnızca Vth)."
            )
        elif "not found" in err_str or "unknown" in err_str:
            errors.append(
                f"⚠ Düğüm {node_pos} veya {node_neg} devrede bulunamadı.\n"
                "Lütfen Norton terminal düğümlerinin devredeki "
                "geçerli düğüm numaraları olduğunu kontrol edin."
            )
        else:
            errors.append(
                f"⚠ Norton hesaplama hatası: {str(e)}\n"
                f"Detay: {traceback.format_exc()}"
            )
        return None


# ═══════════════════════════════════════════════════════
#  BAĞIMLI KAYNAKLI DEVREDE PORT: KISA DEVRE VE TEST KAYNAĞI
# ═══════════════════════════════════════════════════════

def _fresh_id(parsed: ParsedCircuit, base: str) -> str:
    used = {e.id.upper() for e in parsed.elements}
    name = base
    while name.upper() in used:
        name += "_"
    return name


def _solve_port_extras(
    parsed: ParsedCircuit, terminals: TheveninTerminals, is_dc: bool,
    frequency: Optional[float], raw_nodes: dict, raw_currents: dict,
) -> PortExtras:
    """
    Anlatımın ders kitabı yöntemi için gerçek sayılar (bağımlı kaynaklar SIFIRLANMAZ):

      • isc: terminaller 0 V'luk bir kaynakla (tel) kısa devre edilip devre yeniden
        çözülür; telden + → − akan akım (n+ → n− eleman akımı kuralı).
      • i_test: açık devre gerilimi ve kısa devre akımı 0 ise (bağımsız kaynak yok ya da
        terminallere hiçbir şey vermiyor) bağımsız kaynaklar sıfırlanır, terminallere
        1 V'luk test kaynağı (+ ucu node_positive) bağlanır; kaynağın devreye + ucundan
        verdiği akım (= −eleman akımı) bulunur. Rth = 1 V / I_test.

    Her ikisi de lcapy ile gerçekten çözülür; Rth'den türetilmez.
    """
    from lcapy import Circuit

    a, b = terminals.node_positive, terminals.node_negative
    extras = PortExtras()

    def solve_with(base: ParsedCircuit, src: ParsedElement) -> complex:
        sub = copy.deepcopy(base)
        sub.probes = []
        sub.elements.append(src)
        cct = Circuit(to_lcapy_netlist(sub, frequency))
        return complex(lcapy_element_current(
            cct, src, lcapy_sense_map(sub), is_dc, frequency))

    short = ParsedElement(id=_fresh_id(parsed, "Vsc_port"), element_type=ElementType.DC_SOURCE,
                          node_positive=a, node_negative=b, value=0.0)
    try:
        extras.isc = solve_with(parsed, short)
    except Exception:
        extras.isc = None

    vth = complex(raw_nodes.get(a, 0)) - complex(raw_nodes.get(b, 0))
    if not port_is_dead(vth, extras.isc, raw_nodes, raw_currents):
        return extras

    zeroed = copy.deepcopy(parsed)
    for e in zeroed.elements:
        if e.element_type in VOLTAGE_SOURCES:
            e.element_type, e.value, e.params = ElementType.DC_SOURCE, 0.0, {}
        elif e.element_type in CURRENT_SOURCES:
            e.element_type, e.value, e.params = ElementType.CURRENT_DC, 0.0, {}
    if is_dc:
        test = ParsedElement(id=_fresh_id(parsed, "Vtest_port"),
                             element_type=ElementType.DC_SOURCE,
                             node_positive=a, node_negative=b, value=1.0)
    else:
        test = ParsedElement(id=_fresh_id(parsed, "Vtest_port"),
                             element_type=ElementType.AC_SOURCE_PHASOR,
                             node_positive=a, node_negative=b, value=1.0,
                             params={"amplitude": 1.0, "phase": 0.0})
    try:
        extras.i_test = -solve_with(zeroed, test)
    except Exception:
        extras.i_test = None
    return extras


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
        AC:  S = ½ · V · I*      (fazör genlikleri TEPE değerdir —
                                  C# AcVoltageSource.Amplitude tepe değer)
        DC:  S = V · I

    Kaynaklar için emilen güç negatiftir (güç verir). Tellegen
    teoremi gereği tüm elemanların S toplamı sıfır olmalıdır.
    """
    factor = 1.0 if is_dc else 0.5
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

        is_source = elem.element_type in _SOURCE_TYPES
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
            equations.append(
                f"P_{elem.id} = V·I = ({v.real:.4g})·({i.real:.4g}) "
                f"= {p:.4g} W"
                + ("  (güç verir)" if is_source and p < 0 else "")
            )
        else:
            equations.append(
                f"S_{elem.id} = ½·V·I* = {s.real:.4g} {'+' if q >= 0 else '-'} "
                f"j{abs(q):.4g} VA  →  P = {p:.4g} W, Q = {q:.4g} VAR, "
                f"|S| = {s_mag:.4g} VA"
                + (f", cos φ = {pf:.4f} ({pf_type})" if pf is not None else "")
            )

    if not elements:
        return None

    balance = abs(supplied - absorbed)
    scale = max(abs(supplied), abs(absorbed), 1e-12)
    if balance > 1e-6 * scale:
        errors.append(
            f"ℹ Güç dengesi tam sağlanmadı: verilen {supplied:.6g} VA, "
            f"çekilen {absorbed:.6g} VA."
        )

    pf, pf_type = _power_factor(
        supplied.real, supplied.imag, abs(supplied), supplied.imag
    )

    if is_dc:
        convention = "DC: P = V·I (pasif işaret kuralı, emilen güç)"
        equations.append(
            f"Denge: ΣP_kaynak = {supplied.real:.4g} W = "
            f"ΣP_yük = {absorbed.real:.4g} W"
        )
        latex_parts.append(
            "P = V \\cdot I \\quad , \\quad "
            f"\\sum P_{{\\text{{kaynak}}}} = {supplied.real:.4g} \\text{{ W}} = "
            f"\\sum P_{{\\text{{yük}}}}"
        )
    else:
        convention = (
            "AC: S = ½·V·I* (tepe fazör), P = Re(S), Q = Im(S), "
            "cos φ = P/|S| (pasif işaret kuralı, emilen güç)"
        )
        equations.append(
            f"Denge: S_verilen = {supplied.real:.4g} {'+' if supplied.imag >= 0 else '-'} "
            f"j{abs(supplied.imag):.4g} VA = S_çekilen"
        )
        if pf is not None:
            equations.append(
                f"Devre güç faktörü: cos φ = P/|S| = {supplied.real:.4g} / "
                f"{abs(supplied):.4g} = {pf:.4f} ({pf_type})"
            )
        latex_parts.append(
            "S = \\tfrac{1}{2} V I^{*} = P + jQ \\quad , \\quad "
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
               "Fazörler tepe değer olduğundan S = ½·V·I* kullanılır "
               "(etkin değerlerle S = V_rms·I_rms*). Dirençler yalnızca P, "
               "bobinler Q > 0, kapasitörler Q < 0 çeker.")
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
