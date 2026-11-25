"""
CircuitAnalyzer API — Dalga Şekli (WAVEFORM) çözücüsü (Faz 4c-1)

Diyot/zener içeren devrede tek bir zamanla değişen gerilim kaynağı (SINE, SQUARE, TRIANGLE)
için iki periyotluk (400 örnek) zaman taraması yapar. Her örnekte zaman kaynağı anlık değerinde
DC kaynakla değiştirilir ve solver.diode'daki hızlı sayısal MNA çözücüsüyle çözülür (lcapy
örnek başına asla çağrılmaz).

Düğüm gerilimleri ve eleman akımları (results) pozitif tepe anındaki DC-eşdeğer çözümdür.
"""

import copy
import dataclasses
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from explainer.formatting import MINUS, eng, num
from models.request import AnalysisMode, AnalysisType
from models.response import (
    AnalysisResults, DiodeResult, ElementCurrent, NodeVoltage, ProbeResult,
    WaveformBookFormula, WaveformClamperCheck, WaveformClamperInfo,
    WaveformDiodeInterval, WaveformDiodeTrace,
    WaveformSquareLevel, WaveformSummary,
)
from parser.netlist_parser import (
    DIODE_TYPES, WAVEFORM_ONLY_SOURCES, ElementType, ParsedCircuit, ParsedElement,
    element_nodes,
)
from solver.diode import (
    I_TOL, MAX_DIODES, V_TOL, DiodeUnsolvable, _Candidate, _Singular,
    _combos, _components, _dc_solve, _group_identical, _voltage_loop,
    device_states, resolve_states, solve_with_diodes,
)

SAMPLES_PER_PERIOD = 200
NUM_PERIODS = 2
TOTAL_SAMPLES = SAMPLES_PER_PERIOD * NUM_PERIODS  # 400

WAVEFORM_NO_DIODE_REASON = "Dalga Şekli yöntemi diyotlu devreler içindir"
WAVEFORM_ONLY_SOURCE_REASON = "Kare/üçgen dalga kaynağı yalnızca 'Dalga Şekli' yöntemiyle çözülür."

_TIME_SOURCES = (
    ElementType.AC_SOURCE_SINE,
    ElementType.AC_SOURCE_SQUARE,
    ElementType.AC_SOURCE_TRIANGLE,
)
_ALLOWED_ELEMENTS = _TIME_SOURCES + (
    ElementType.DC_SOURCE,
    ElementType.RESISTOR,
    ElementType.DIODE,
)
_CLAMPER_ALLOWED_ELEMENTS = _ALLOWED_ELEMENTS + (ElementType.CAPACITOR,)
_CLAMPER_DIODE_MODELS = ("IDEAL", "SI", "GE")


def _sig_round(x: float, digits: int = 8) -> float:
    if not math.isfinite(x):
        return x
    if abs(x) < 1e-12:
        return 0.0
    return float(f"{x:.{digits}g}")


def _output_nodes(elem: ParsedElement) -> Tuple[str, str]:
    """
    Çıkış elemanı tek uçtan toprağa ('0') bağlıysa, uç sırasından bağımsız olarak
    diğer düğümün toprağa göre gerilimini (V_diğer − V_0) kullan; aksi halde netlist yönü.
    """
    if elem.node_positive == "0" and elem.node_negative != "0":
        return elem.node_negative, "0"
    if elem.node_negative == "0" and elem.node_positive != "0":
        return elem.node_positive, "0"
    return elem.node_positive, elem.node_negative


def _volts(x: float) -> str:
    return f"{num(x)} V"


@dataclass
class ClamperSetup:
    """Doğrulanmış kitap kenetleme (clamper) devresi topolojisi."""
    input_node: str
    output_node: str
    capacitor: ParsedElement
    resistor: ParsedElement
    diode: ParsedElement
    diode_to_gnd: bool                       # True: y → 0 (üst kenetleme), False: 0 → y (alt kenetleme)
    bias_source: Optional[ParsedElement]     # diyotla seri DC kaynak (yoksa None)
    mid_node: Optional[str]                  # diyot ile seri kaynak arasındaki ara düğüm
    diode_on_y_side: bool                    # True: y—D—m—V—0, False: y—V—m—D—0 (yalnız bias varsa)
    v_bias: float                            # seri kaynağın V(y)−V(0) yönündeki işaretli katkısı
    v_t: float                               # diyot eşik gerilimi V_T (V)
    v_k: float                               # diyot kolu kenetleme gerilimi V_K = V_bias ± V_T (V)
    source_reversed: bool = False            # True: kaynak 0 → a ters bağlı, v_i(t) = −src(t)


@dataclass
class WaveformSetup:
    """Doğrulanmış Dalga Şekli devre kurulumu."""
    source: ParsedElement
    shape: str                       # "SINE" | "SQUARE" | "TRIANGLE"
    frequency: float
    period: float
    output_elem: ParsedElement
    diodes: List[ParsedElement]
    dc_sources: List[ParsedElement]
    resistors: List[ParsedElement]
    # SINE: offset, amplitude (tepe), phase_deg; SQUARE: v1, v2; TRIANGLE: amplitude (Vp)
    offset: float = 0.0
    amplitude: float = 0.0
    phase_deg: float = 0.0
    v1: float = 0.0
    v2: float = 0.0
    clamper: Optional[ClamperSetup] = None


@dataclass
class SamplePoint:
    """Tek bir zaman örneğinin çözüm özeti."""
    v_in: float
    v_out: float
    states: Dict[str, str]           # {diode_id: "ON" | "ZENER" | "OFF"}
    diode_currents: Dict[str, float] # {diode_id: I_AK}
    volts: Dict[str, float]
    currents: Dict[str, float]


@dataclass
class WaveformAnalysis:
    """Dalga Şekli analizinin tüm sonuçları (özet + anlatım verisi)."""
    setup: WaveformSetup
    summary: WaveformSummary
    pos_peak: Optional[SamplePoint] = None
    neg_peak: Optional[SamplePoint] = None
    pattern: Optional[str] = None              # "HALF_WAVE" | "BRIDGE" | None
    pattern_positive: bool = True              # True: çıkış pozitif yarım/tam dalga
    conduction_threshold_v: Optional[float] = None
    conduction_time_s: Optional[float] = None
    conduction_in_neg_half: bool = False
    path_threshold_v: Optional[float] = None   # tek yolda belirgin toplam eşik (ör. Si+Ge+3V = 4 V)
    path_threshold_expr: Optional[str] = None
    clamper_v_i_max: float = 0.0
    clamper_v_i_min: float = 0.0
    clamper_v_in_cond: float = 0.0
    clamper_v_in_off: float = 0.0


# ═══════════════════════════════════════════════════════
#  UYGUNLUK DENETİMİ
# ═══════════════════════════════════════════════════════

def _source_peak_sine(src: ParsedElement) -> float:
    """SINE kaynağının gerçek tepe genliği (RMS girişiyse √2 ile çarpılır)."""
    in_val = float(src.params.get("input_value", src.params.get("amplitude", src.value)))
    in_basis = str(src.params.get("input_basis", "PEAK")).upper()
    return in_val * math.sqrt(2.0) if in_basis == "RMS" else in_val


def _detect_clamper(
    parsed: ParsedCircuit,
    frequency: Optional[float],
    waveform_output: Optional[str],
    diodes: List[ParsedElement],
) -> Tuple[Optional[WaveformSetup], str]:
    """
    Kondansatör içeren devrede yalnızca ders kitabındaki temel kenetleme (clamper)
    topolojisini kabul eder; diğer tüm kondansatörlü devreleri Türkçe gerekçeyle reddeder.
    """
    for e in parsed.elements:
        if e.element_type == ElementType.SWITCH:
            return None, (
                f"devrede anahtar var ({e.id}); kondansatörlü Dalga Şekli çözümü yalnızca "
                "anahtarsız temel kenetleme (clamper) devresinde uygulanır"
            )
        if e.element_type not in _CLAMPER_ALLOWED_ELEMENTS:
            return None, (
                f"devrede {e.id} elemanı var; kondansatörlü Dalga Şekli çözümü yalnızca "
                "temel kenetleme (clamper) devresinde uygulanır"
            )

    caps = [e for e in parsed.elements if e.element_type == ElementType.CAPACITOR]
    if len(caps) != 1:
        return None, (
            f"devrede {len(caps)} kondansatör var; kondansatörlü Dalga Şekli çözümü yalnızca "
            "tek kondansatörlü temel kenetleme (clamper) devresinde uygulanır"
        )
    cap = caps[0]
    if not math.isfinite(cap.value) or cap.value <= 0.0:
        return None, f"{cap.id} kondansatörünün sığası sıfırdan büyük olmalıdır"

    if len(diodes) != 1:
        return None, (
            f"kondansatörlü devrede {len(diodes)} diyot var; temel kenetleme devresi "
            "yalnızca tek bir diyot içerir"
        )
    diode = diodes[0]
    model = diode.params.get("model")
    if model not in _CLAMPER_DIODE_MODELS:
        return None, (
            f"kondansatörlü devrede zener diyot ({diode.id}) var; kenetleme devresinde "
            "yalnızca normal diyot (ideal, Si veya Ge) desteklenir"
        )

    time_srcs = [e for e in parsed.elements if e.element_type in _TIME_SOURCES]
    if not time_srcs:
        return None, (
            "devrede zamanla değişen (sinüs, kare veya üçgen) gerilim kaynağı yok; "
            "Dalga Şekli yöntemi bir AC/kare/üçgen gerilim kaynağı gerektirir"
        )
    if len(time_srcs) > 1:
        return None, (
            "devrede birden fazla zamanla değişen kaynak var; "
            "Dalga Şekli yöntemi tek bir AC/kare/üçgen gerilim kaynağıyla uygulanır"
        )

    src = time_srcs[0]
    if src.node_positive == src.node_negative:
        return None, f"{src.id} giriş kaynağı kısa devre edilmiş"
    if "0" not in (src.node_positive, src.node_negative):
        return None, (
            "giriş kaynağı toprağa (GND) bağlı değil; kondansatörlü kenetleme devresinde "
            "giriş kaynağı referans toprağa (0) bağlı olmalıdır"
        )
    # Ters çizilmiş kaynak (V1 0 a ...): (+) ucu GND'de olduğundan giriş düğümü −src(t) görür.
    source_reversed = src.node_positive == "0"
    a = src.node_negative if source_reversed else src.node_positive

    freq = float(src.params.get("frequency", 0.0) or 0.0)
    if freq <= 0.0 and frequency is not None and frequency > 0.0:
        freq = float(frequency)
    if freq <= 0.0:
        return None, f"{src.id} kaynağının frekansı sıfırdan büyük olmalıdır"

    # Kondansatör giriş düğümü a ile çıkış düğümü y arasında olmalı (uç sırası fark etmez)
    c_nodes = {cap.node_positive, cap.node_negative}
    if len(c_nodes) != 2 or a not in c_nodes:
        return None, (
            f"{cap.id} kondansatörü giriş düğümü ile çıkış düğümü arasında seri bağlı değil; "
            "kondansatörlü Dalga Şekli çözümü yalnızca temel kenetleme (clamper) devresinde uygulanır"
        )
    y = cap.node_negative if cap.node_positive == a else cap.node_positive
    if y == "0":
        return None, (
            f"{cap.id} kondansatörü toprağa bağlı; kondansatörlü kenetleme devresinde "
            "kondansatör giriş ile çıkış düğümü arasında seri olmalıdır"
        )

    resistors = [e for e in parsed.elements if e.element_type == ElementType.RESISTOR]
    if not resistors:
        return None, (
            "devrede çıkış direnci yok; kondansatörlü kenetleme devresinde çıkış ile GND "
            "arasında tek bir direnç olmalıdır"
        )
    if len(resistors) > 1:
        return None, (
            f"kondansatörlü devrede {len(resistors)} direnç var; temel kenetleme devresinde "
            "çıkış ile GND arasında yalnızca tek bir direnç olabilir"
        )
    res = resistors[0]
    if not math.isfinite(res.value) or res.value <= 0.0:
        return None, f"{res.id} direncinin değeri sıfırdan büyük olmalıdır"
    if {res.node_positive, res.node_negative} != {y, "0"}:
        return None, (
            f"{res.id} direnci çıkış düğümü ile GND arasında değil; kondansatörlü kenetleme "
            "devresinde tek direnç çıkıştan toprağa bağlı olmalıdır"
        )

    wanted = (waveform_output or "").strip()
    if wanted and wanted.upper() != res.id.upper():
        return None, (
            f"kenetleme devresinde çıkış gerilimi V_O yalnızca yük direnci ({res.id}) üzerinden "
            f"alınır; “{wanted}” seçilemez"
        )

    dc_sources = [e for e in parsed.elements if e.element_type == ElementType.DC_SOURCE]
    if len(dc_sources) > 1:
        return None, (
            f"kondansatörlü devrede {len(dc_sources)} DC kaynak var; temel kenetleme "
            "devresinde diyot kolunda en fazla bir DC kaynak olabilir"
        )

    # Diyot kolu: y ile 0 arasında tek diyot (isteğe bağlı olarak tek DC kaynakla seri)
    if not dc_sources:
        if {diode.node_positive, diode.node_negative} != {y, "0"}:
            return None, (
                f"{diode.id} diyotu çıkış düğümü ile GND arasında değil; kondansatörlü "
                "kenetleme devresinde diyot kolu çıkıştan toprağa bağlı olmalıdır"
            )
        diode_to_gnd = diode.node_positive == y
        bias_source = None
        mid_node = None
        diode_on_y_side = True
        v_bias = 0.0
    else:
        dc = dc_sources[0]
        d_nodes = {diode.node_positive, diode.node_negative}
        v_nodes = {dc.node_positive, dc.node_negative}
        if len(d_nodes) != 2 or len(v_nodes) != 2:
            return None, "diyot kolundaki elemanlardan biri kısa devre edilmiş"

        # Sıra 1: y — D — m — V — 0   |   Sıra 2: y — V — m — D — 0
        if y in d_nodes and "0" in v_nodes:
            m_d = diode.node_negative if diode.node_positive == y else diode.node_positive
            m_v = dc.node_negative if dc.node_positive == "0" else dc.node_positive
            if m_d != m_v or m_d in (y, "0", a):
                return None, (
                    "diyot kolu çıkış düğümü ile GND arasında kitap kenetleme yapısında değil; "
                    "kondansatörlü devrede diyot ve seri DC kaynak çıkıştan toprağa tek kolda olmalıdır"
                )
            mid_node = m_d
            diode_on_y_side = True
            diode_to_gnd = diode.node_positive == y
            # V(m) − V(0): + ucu m'de ise +dc.value, 0'da ise −dc.value
            v_bias = float(dc.value) if dc.node_positive == mid_node else -float(dc.value)
        elif y in v_nodes and "0" in d_nodes:
            m_v = dc.node_negative if dc.node_positive == y else dc.node_positive
            m_d = diode.node_negative if diode.node_positive == "0" else diode.node_positive
            if m_d != m_v or m_d in (y, "0", a):
                return None, (
                    "diyot kolu çıkış düğümü ile GND arasında kitap kenetleme yapısında değil; "
                    "kondansatörlü devrede diyot ve seri DC kaynak çıkıştan toprağa tek kolda olmalıdır"
                )
            mid_node = m_d
            diode_on_y_side = False
            diode_to_gnd = diode.node_positive == mid_node
            # V(y) − V(m): + ucu y'de ise +dc.value, m'de ise −dc.value
            v_bias = float(dc.value) if dc.node_positive == y else -float(dc.value)
        else:
            return None, (
                "diyot kolu çıkış düğümü ile GND arasında kitap kenetleme yapısında değil; "
                "kondansatörlü devrede diyot ve seri DC kaynak çıkıştan toprağa tek kolda olmalıdır"
            )
        bias_source = dc

    v_t = float(diode.params["v_t"])
    v_k = v_bias + v_t if diode_to_gnd else v_bias - v_t
    clamper = ClamperSetup(
        input_node=a,
        output_node=y,
        capacitor=cap,
        resistor=res,
        diode=diode,
        diode_to_gnd=diode_to_gnd,
        bias_source=bias_source,
        mid_node=mid_node,
        diode_on_y_side=diode_on_y_side,
        v_bias=v_bias,
        v_t=v_t,
        v_k=v_k,
        source_reversed=source_reversed,
    )

    period = 1.0 / freq
    if src.element_type == ElementType.AC_SOURCE_SINE:
        amp = _source_peak_sine(src)
        if amp <= 0.0:
            return None, f"{src.id} sinüs kaynağının genliği sıfırdan büyük olmalıdır"
        return WaveformSetup(
            source=src, shape="SINE", frequency=freq, period=period,
            output_elem=res, diodes=diodes, dc_sources=dc_sources, resistors=resistors,
            offset=float(src.params.get("offset", 0.0) or 0.0),
            amplitude=amp,
            phase_deg=float(src.params.get("phase", 0.0) or 0.0),
            clamper=clamper,
        ), ""

    if src.element_type == ElementType.AC_SOURCE_SQUARE:
        v1 = float(src.params["v1"])
        v2 = float(src.params["v2"])
        return WaveformSetup(
            source=src, shape="SQUARE", frequency=freq, period=period,
            output_elem=res, diodes=diodes, dc_sources=dc_sources, resistors=resistors,
            amplitude=max(abs(v1), abs(v2)), v1=v1, v2=v2,
            clamper=clamper,
        ), ""

    amp = float(src.params["amplitude"])
    if amp <= 0.0:
        return None, f"{src.id} üçgen kaynağının genliği sıfırdan büyük olmalıdır"
    return WaveformSetup(
        source=src, shape="TRIANGLE", frequency=freq, period=period,
        output_elem=res, diodes=diodes, dc_sources=dc_sources, resistors=resistors,
        amplitude=amp,
        clamper=clamper,
    ), ""


def detect_waveform_circuit(
    parsed: ParsedCircuit,
    frequency: Optional[float] = None,
    waveform_output: Optional[str] = None,
) -> Tuple[Optional[WaveformSetup], str]:
    """
    Devrenin Dalga Şekli yöntemine uygunluğunu denetler.
    Dönüş: (WaveformSetup, "") veya (None, Türkçe uygulanamama nedeni).
    """
    diodes = [e for e in parsed.elements if e.element_type in DIODE_TYPES]
    if not diodes:
        return None, WAVEFORM_NO_DIODE_REASON

    # Kondansatörlü devreler yalnızca kitap kenetleme (clamper) kapısından geçer;
    # kondansatörsüz devreler Faz 4c-1 davranışını birebir korur.
    if any(e.element_type == ElementType.CAPACITOR for e in parsed.elements):
        return _detect_clamper(parsed, frequency, waveform_output, diodes)

    if len(diodes) > MAX_DIODES:
        return None, (
            f"devrede {len(diodes)} diyot var; Dalga Şekli yöntemi en fazla {MAX_DIODES} "
            "diyotlu devrelerde uygulanır"
        )

    for e in parsed.elements:
        if e.element_type == ElementType.SWITCH:
            return None, (
                f"devrede anahtar var ({e.id}); Dalga Şekli yöntemi anahtarsız, yalnızca "
                "direnç, diyot ve gerilim kaynaklı devrelerde uygulanır"
            )
        if e.element_type not in _ALLOWED_ELEMENTS:
            if e.element_type in (ElementType.CAPACITOR, ElementType.INDUCTOR):
                kind = "kondansatör" if e.element_type == ElementType.CAPACITOR else "bobin"
                return None, (
                    f"devrede {kind} var ({e.id}); Dalga Şekli yöntemi yalnızca direnç, diyot "
                    "ve gerilim kaynaklı (C/L içermeyen) devrelerde uygulanır"
                )
            return None, (
                f"devrede {e.id} elemanı var; Dalga Şekli yöntemi yalnızca direnç, diyot, "
                "DC gerilim kaynağı ve tek bir AC/kare/üçgen gerilim kaynağı içeren devrelerde uygulanır"
            )

    time_srcs = [e for e in parsed.elements if e.element_type in _TIME_SOURCES]
    if not time_srcs:
        return None, (
            "devrede zamanla değişen (sinüs, kare veya üçgen) gerilim kaynağı yok; "
            "Dalga Şekli yöntemi bir AC/kare/üçgen gerilim kaynağı gerektirir"
        )
    if len(time_srcs) > 1:
        return None, (
            "devrede birden fazla zamanla değişen kaynak var; "
            "Dalga Şekli yöntemi tek bir AC/kare/üçgen gerilim kaynağıyla uygulanır"
        )

    src = time_srcs[0]
    freq = float(src.params.get("frequency", 0.0) or 0.0)
    if freq <= 0.0 and frequency is not None and frequency > 0.0:
        freq = float(frequency)
    if freq <= 0.0:
        return None, f"{src.id} kaynağının frekansı sıfırdan büyük olmalıdır"

    resistors = [e for e in parsed.elements if e.element_type == ElementType.RESISTOR]
    dc_sources = [e for e in parsed.elements if e.element_type == ElementType.DC_SOURCE]

    wanted = (waveform_output or "").strip()
    if wanted:
        output_elem = next((e for e in parsed.elements if e.id.upper() == wanted.upper()), None)
        if output_elem is None:
            return None, f"“{wanted}” adlı bir eleman devrede yok"
    else:
        if not resistors:
            return None, "devrede çıkış geriliminin (V_O) alınacağı bir direnç yok"
        output_elem = resistors[-1]

    period = 1.0 / freq
    if src.element_type == ElementType.AC_SOURCE_SINE:
        amp = _source_peak_sine(src)
        if amp <= 0.0:
            return None, f"{src.id} sinüs kaynağının genliği sıfırdan büyük olmalıdır"
        return WaveformSetup(
            source=src, shape="SINE", frequency=freq, period=period,
            output_elem=output_elem, diodes=diodes, dc_sources=dc_sources, resistors=resistors,
            offset=float(src.params.get("offset", 0.0) or 0.0),
            amplitude=amp,
            phase_deg=float(src.params.get("phase", 0.0) or 0.0),
        ), ""

    if src.element_type == ElementType.AC_SOURCE_SQUARE:
        v1 = float(src.params["v1"])
        v2 = float(src.params["v2"])
        return WaveformSetup(
            source=src, shape="SQUARE", frequency=freq, period=period,
            output_elem=output_elem, diodes=diodes, dc_sources=dc_sources, resistors=resistors,
            amplitude=max(abs(v1), abs(v2)), v1=v1, v2=v2,
        ), ""

    amp = float(src.params["amplitude"])
    return WaveformSetup(
        source=src, shape="TRIANGLE", frequency=freq, period=period,
        output_elem=output_elem, diodes=diodes, dc_sources=dc_sources, resistors=resistors,
        amplitude=amp,
    ), ""


# ═══════════════════════════════════════════════════════
#  KAYNAK DALGA BİÇİMİ
# ═══════════════════════════════════════════════════════

def eval_source(setup: WaveformSetup, t: float) -> float:
    """t anındaki giriş gerilimi v_in(t)."""
    if setup.shape == "SINE":
        arg = 2.0 * math.pi * setup.frequency * t + math.radians(setup.phase_deg)
        return setup.offset + setup.amplitude * math.sin(arg)
    # Periyot içi normalize konum u ∈ [0, 1)
    u = (t / setup.period) % 1.0
    if abs(u - 1.0) < 1e-12:
        u = 0.0
    if setup.shape == "SQUARE":
        return setup.v1 if u < 0.5 - 1e-12 else setup.v2
    # TRIANGLE: 0 → +Vp (0..0.25), +Vp → −Vp (0.25..0.75), −Vp → 0 (0.75..1)
    if u < 0.25:
        return 4.0 * setup.amplitude * u
    if u < 0.75:
        return setup.amplitude * (2.0 - 4.0 * u)
    return setup.amplitude * (4.0 * u - 4.0)


# ═══════════════════════════════════════════════════════
#  HIZLI ÖRNEK ÇÖZÜCÜSÜ (sıcak başlangıçlı MNA)
# ═══════════════════════════════════════════════════════

class _FastSampler:
    """
    Aynı devre topolojisi üzerinde yalnızca v_in değişirken hızlı DC durum çözümleyicisi.
    Önce bir önceki örneğin durumunu dener (iç bölgedeyse tek MNA çözümü yeter);
    geçiş anlarında solver.diode.resolve_states tam aramasına düşer.
    OFF diyotların 10¹² Ω sızıntısını temizlemek için seçilen durumda açık devreyle
    GND'ye bağlı bileşende temiz çıkış gerilimi hesaplar.
    """

    def __init__(self, parsed: ParsedCircuit, setup: WaveformSetup):
        self.parsed = parsed
        self.setup = setup
        self.diodes = setup.diodes
        self.groups = _group_identical(self.diodes)
        self.reps = [g[0] for g in self.groups]
        self.rep_states = [device_states(r) for r in self.reps]
        self.sizes = [len(s) for s in self.rep_states]
        self.base_other = [
            e for e in parsed.elements
            if e.element_type not in DIODE_TYPES and e.id != setup.source.id
        ]
        self._last_state: Optional[Tuple[int, ...]] = None

    def _dc_source(self, v_in: float) -> ParsedElement:
        s = self.setup.source
        return ParsedElement(
            id=s.id, element_type=ElementType.DC_SOURCE,
            node_positive=s.node_positive, node_negative=s.node_negative,
            value=float(v_in),
        )

    def _try_state(
        self, base: List[ParsedElement], st: Tuple[int, ...],
    ) -> Optional[_Candidate]:
        subs = [sts[s].search_element(r) for r, sts, s in zip(self.reps, self.rep_states, st)]
        elems = base + subs
        if _voltage_loop(elems):
            return None
        try:
            volts, currents = _dc_solve(elems)
        except _Singular:
            return None
        currents_ak = dict(currents)
        for r, sts, s, sub in zip(self.reps, self.rep_states, st, subs):
            v_ak = volts.get(r.node_positive, 0.0) - volts.get(r.node_negative, 0.0)
            i_raw = currents[r.id]
            i_ak = i_raw if sub.node_positive == r.node_positive else -i_raw
            currents_ak[r.id] = i_ak
            # Çözücüyle (resolve_states) birebir aynı tutarlılık koşulunu uygula;
            # katı iç bölge kontrolü paralel diyotlarda (V_AK = V_T) gereksiz tam aramaya düşürüyordu.
            if not sts[s].consistent(r, v_ak, i_ak):
                return None
        return _Candidate(st, volts, currents_ak)

    def _clean_v_out(self, base: List[ParsedElement], cand: _Candidate) -> float:
        """OFF diyotlar açık devre yapılarak sızıntısız V_O hesaplanır."""
        out = self.setup.output_elem
        pos_nd, neg_nd = _output_nodes(out)
        open_elems = list(base)
        for r, sts, s in zip(self.reps, self.rep_states, cand.states):
            fin = sts[s].final_element(r)
            if fin is not None:
                open_elems.append(fin)

        # Yalnızca GND'ye bağlı bileşeni çöz; yüzen (kaynaksız) bileşendeki direncin gerilimi tam 0
        find, _ = _components(open_elems)
        ground = find("0")
        gnd_elems = [
            e for e in open_elems
            if ground in {find(n) for n in element_nodes(e)}
        ]
        if out.element_type == ElementType.RESISTOR and all(e.id != out.id for e in gnd_elems):
            return 0.0

        if gnd_elems and not _voltage_loop(gnd_elems):
            try:
                v_clean, _ = _dc_solve(gnd_elems)
                if pos_nd in v_clean and neg_nd in v_clean:
                    v_o = v_clean[pos_nd] - v_clean[neg_nd]
                    return 0.0 if abs(v_o) < 1e-12 else v_o
            except _Singular:
                pass

        v_o = cand.volts.get(pos_nd, 0.0) - cand.volts.get(neg_nd, 0.0)
        return 0.0 if abs(v_o) < 1e-9 else v_o

    def solve_at(self, v_in: float) -> SamplePoint:
        src_dc = self._dc_source(v_in)
        base = self.base_other + [src_dc]

        cand: Optional[_Candidate] = None
        if self._last_state is not None:
            cand = self._try_state(base, self._last_state)

        if cand is None:
            # Tam deterministik arama (solver.diode.resolve_states ile aynı sıra)
            dc_circuit = copy.copy(self.parsed)
            dc_circuit.elements = [
                src_dc if e.id == self.setup.source.id else e for e in self.parsed.elements
            ]
            _, cand, _, _ = resolve_states(dc_circuit)

        self._last_state = cand.states
        v_out = self._clean_v_out(base, cand)

        states: Dict[str, str] = {}
        d_currents: Dict[str, float] = {}
        for g, sts, s in zip(self.groups, self.rep_states, cand.states):
            st_name = sts[s].name
            i_rep = cand.currents.get(g[0].id, 0.0) if st_name != "OFF" else 0.0
            i_each = i_rep / len(g) if st_name == "ON" else i_rep
            for d in g:
                states[d.id] = st_name
                d_currents[d.id] = 0.0 if abs(i_each) < 1e-12 else i_each

        return SamplePoint(
            v_in=float(v_in),
            v_out=float(v_out),
            states=states,
            diode_currents=d_currents,
            volts=cand.volts,
            currents=cand.currents,
        )


# ═══════════════════════════════════════════════════════
#  TOPOLOJİ TANIMA (YARIM DALGA / KÖPRÜ DOĞRULTUCU)
# ═══════════════════════════════════════════════════════

def _recognize_rectifier(
    setup: WaveformSetup, v_out_max: float, v_out_min: float,
) -> Tuple[Optional[str], bool, Optional[WaveformBookFormula]]:
    """
    Yalnızca SINE (ofsetsiz), DC kaynaksız, tek yüklü ve tüm diyotları aynı normal modelde
    olan devrelerde kitap yarım dalga / köprü doğrultucu topolojisini tanır.
    """
    if setup.shape != "SINE" or abs(setup.offset) > 1e-12:
        return None, True, None
    if setup.dc_sources or len(setup.resistors) != 1:
        return None, True, None
    load = setup.resistors[0]
    if setup.output_elem.id != load.id:
        return None, True, None

    models = {d.params["model"] for d in setup.diodes}
    if len(models) != 1:
        return None, True, None
    model = next(iter(models))
    if model not in ("IDEAL", "SI", "GE"):
        return None, True, None

    v_t = float(setup.diodes[0].params["v_t"])
    v_m = setup.amplitude
    src = setup.source
    s_nodes = {src.node_positive, src.node_negative}
    r_nodes = {load.node_positive, load.node_negative}

    # 1. Yarım dalga doğrultucu: 1 diyot, kaynak ve yük GND'ye bağlı, diyot arada seri
    if len(setup.diodes) == 1 and "0" in s_nodes and "0" in r_nodes:
        a = src.node_negative if src.node_positive == "0" else src.node_positive
        b = load.node_negative if load.node_positive == "0" else load.node_positive
        d = setup.diodes[0]
        if a != "0" and b != "0" and a != b and {d.node_positive, d.node_negative} == {a, b}:
            if v_m <= v_t + V_TOL:
                return "HALF_WAVE", True, None
            positive = v_out_max >= abs(v_out_min)
            sign = 1.0 if positive else -1.0
            val = sign * 0.318 * (v_m - v_t)
            prefix = "" if positive else MINUS
            if v_t == 0.0:
                text = f"V_DC = {prefix}0,318·V_m = {prefix}0,318·{eng(v_m, 'V')} = {eng(val, 'V')}"
            else:
                text = (
                    f"V_DC = {prefix}0,318·(V_m {MINUS} V_T) = "
                    f"{prefix}0,318·({eng(v_m, 'V')} {MINUS} {_volts(v_t)}) = {eng(val, 'V')}"
                )
            return "HALF_WAVE", positive, WaveformBookFormula(
                name="Yarım dalga doğrultucu", text=text, value=_sig_round(val, 6),
            )

    # 2. Tam dalga (köprü) doğrultucu: 4 özdeş diyot, 4 ayrı düğüm {a, b, p, n}
    if len(setup.diodes) == 4:
        a, b = src.node_positive, src.node_negative
        p, n = load.node_positive, load.node_negative
        if len({a, b, p, n}) == 4:
            edges = [(d.node_positive, d.node_negative) for d in setup.diodes]
            pos_bridge = {(a, p), (b, p), (n, a), (n, b)}
            neg_bridge = {(p, a), (p, b), (a, n), (b, n)}
            edge_set = set(edges)
            if len(edge_set) == 4 and (edge_set == pos_bridge or edge_set == neg_bridge):
                if v_m <= 2.0 * v_t + V_TOL:
                    return "BRIDGE", edge_set == pos_bridge, None
                positive = v_out_max >= abs(v_out_min)
                sign = 1.0 if positive else -1.0
                val = sign * 0.636 * (v_m - 2.0 * v_t)
                prefix = "" if positive else MINUS
                if v_t == 0.0:
                    text = f"V_DC = {prefix}0,636·V_m = {prefix}0,636·{eng(v_m, 'V')} = {eng(val, 'V')}"
                else:
                    text = (
                        f"V_DC = {prefix}0,636·(V_m {MINUS} 2·V_T) = "
                        f"{prefix}0,636·({eng(v_m, 'V')} {MINUS} 2·{_volts(v_t)}) = {eng(val, 'V')}"
                    )
                return "BRIDGE", positive, WaveformBookFormula(
                    name="Tam dalga (köprü) doğrultucu", text=text, value=_sig_round(val, 6),
                )

    return None, True, None


# ═══════════════════════════════════════════════════════
#  İLETİM BAŞLANGICI (AÇI / ZAMAN) VE EŞİK GERİLİMİ
# ═══════════════════════════════════════════════════════

def _any_conducting(pt: SamplePoint) -> bool:
    return any(st != "OFF" for st in pt.states.values())


def _find_conduction_start(
    setup: WaveformSetup, sampler: _FastSampler,
) -> Tuple[Optional[float], Optional[float], Optional[float], bool]:
    """
    SINE veya TRIANGLE için iletimin başladığı anı ikili aramayla bulur.
    Dönüş: (açı_derece, zaman_s, eşik_v_in, negatif_yarıda_mı).
    """
    if setup.shape == "SQUARE":
        return None, None, None, False

    T = setup.period
    # Önce pozitif yarı periyodun yükselen kenarı [0, T/4], yoksa negatif yarı [T/2, 3T/4]
    for base_t, neg_half in ((0.0, False), (0.5 * T, True)):
        t_lo = base_t
        t_hi = base_t + 0.25 * T
        p_hi = sampler.solve_at(eval_source(setup, t_hi))
        if not _any_conducting(p_hi):
            continue
        p_lo = sampler.solve_at(eval_source(setup, t_lo))
        if _any_conducting(p_lo):
            return 0.0, base_t, abs(p_lo.v_in), neg_half
        # İkili arama: ~24 adım → T * 2^-24 hassasiyet (< 1e-5°)
        lo, hi = t_lo, t_hi
        for _ in range(24):
            mid = 0.5 * (lo + hi)
            if _any_conducting(sampler.solve_at(eval_source(setup, mid))):
                hi = mid
            else:
                lo = mid
        t_on = hi
        dt = t_on - base_t
        angle_deg = (dt / T) * 360.0
        v_th = abs(eval_source(setup, t_on))
        return _sig_round(angle_deg, 5), _sig_round(t_on, 6), _sig_round(v_th, 5), neg_half

    return None, None, None, False


def _path_threshold(
    setup: WaveformSetup, pattern: Optional[str], pos_peak: SamplePoint, neg_peak: SamplePoint,
) -> Tuple[Optional[float], Optional[str]]:
    """Belirgin tek iletim yolu varsa toplam eşik gerilimini ve ifadesini döndürür."""
    if pattern == "HALF_WAVE":
        d = setup.diodes[0]
        v_t = float(d.params["v_t"])
        return v_t, f"V_T = {_volts(v_t)} ({d.id})"
    if pattern == "BRIDGE":
        v_t = float(setup.diodes[0].params["v_t"])
        return 2.0 * v_t, f"2·V_T = 2·{_volts(v_t)} = {_volts(2.0 * v_t)} (her alternansta 2 diyot seri)"

    # Tek seri çevre: pozitif (ya da negatif) tepede iletimde olan diyotlar + karşı koyan DC kaynaklar
    active_pt = pos_peak if _any_conducting(pos_peak) else neg_peak
    if not _any_conducting(active_pt):
        return None, None
    # Çıkış gerilimi ve tepe giriş geriliminden etkin eşiği kontrol et (yalnız tek dirençli seri yolda)
    if len(setup.resistors) == 1 and setup.output_elem.id == setup.resistors[0].id:
        on_diodes = [d for d in setup.diodes if active_pt.states.get(d.id) == "ON"]
        if on_diodes and all(active_pt.states.get(d.id) in ("ON", "OFF") for d in setup.diodes):
            v_drop = abs(active_pt.v_in) - abs(active_pt.v_out)
            if v_drop >= -1e-6:
                d_sum = sum(float(d.params["v_t"]) for d in on_diodes)
                dc_diff = v_drop - d_sum
                parts = [f"V_{d.id} ({_volts(d.params['v_t'])})" for d in on_diodes]
                if setup.dc_sources and abs(dc_diff) > 1e-6:
                    for vdc in setup.dc_sources:
                        if abs(abs(dc_diff) - abs(vdc.value)) < 1e-6:
                            sign = "+" if dc_diff > 0 else MINUS
                            parts.append(f"{sign} {vdc.id} ({_volts(abs(vdc.value))})")
                            break
                if len(parts) == 1 and abs(dc_diff) <= 1e-6:
                    # Tek diyot, ek kaynak yok: kitaptaki gibi doğrudan V_T yazılır (sinüs çıktısıyla aynı).
                    d = on_diodes[0]
                    return _sig_round(v_drop, 6), f"V_T = {_volts(d.params['v_t'])} ({d.id})"
                expr = " + ".join(parts).replace(" + + ", " + ").replace(f" + {MINUS} ", f" {MINUS} ")
                return _sig_round(v_drop, 6), f"V_eşik = {expr} = {_volts(v_drop)}"
    return None, None


# ═══════════════════════════════════════════════════════
#  DİYOT ARALIKLARI
# ═══════════════════════════════════════════════════════

def _build_diode_intervals(
    diodes: List[ParsedElement], ts: List[float], state_rows: List[Dict[str, str]], t_total: float,
) -> List[WaveformDiodeTrace]:
    traces: List[WaveformDiodeTrace] = []
    n = len(ts)
    for d in diodes:
        intervals: List[WaveformDiodeInterval] = []
        cur_state = state_rows[0][d.id]
        start_idx = 0
        for k in range(1, n):
            st = state_rows[k][d.id]
            if st != cur_state:
                intervals.append(WaveformDiodeInterval(
                    t_start=_sig_round(ts[start_idx], 6),
                    t_end=_sig_round(ts[k], 6),
                    state=cur_state,
                ))
                cur_state = st
                start_idx = k
        intervals.append(WaveformDiodeInterval(
            t_start=_sig_round(ts[start_idx], 6),
            t_end=_sig_round(t_total, 6),
            state=cur_state,
        ))
        traces.append(WaveformDiodeTrace(id=d.id, intervals=intervals))
    return traces


# ═══════════════════════════════════════════════════════
#  ANA GİRİŞ
# ═══════════════════════════════════════════════════════

def _unsolvable(reason: str):
    from solver.circuit_solver import UNSOLVABLE_PREFIX
    return AnalysisResults(), [], [UNSOLVABLE_PREFIX + reason]


def _numeric_peak_results(
    parsed: ParsedCircuit, setup: WaveformSetup, peak: SamplePoint,
) -> AnalysisResults:
    """Pozitif tepe anı lcapy ile çözülemezse (ör. köprüde V_m < 2·V_T) sayısal yedek sonuç."""
    from solver.circuit_solver import sig_round
    res = AnalysisResults()
    res.node_voltages["0"] = NodeVoltage(value=0.0, unit="V", label="GND")
    for nd, val in sorted(peak.volts.items(), key=lambda kv: (len(kv[0]), kv[0])):
        if nd != "0":
            res.node_voltages[nd] = NodeVoltage(value=sig_round(val), unit="V")
    for e in parsed.elements:
        i_val = peak.diode_currents.get(e.id, peak.currents.get(e.id, 0.0))
        res.element_currents[e.id] = ElementCurrent(
            value=sig_round(i_val), unit="A", direction=f"{e.node_positive}→{e.node_negative}",
        )
    res.diodes = [
        DiodeResult(
            id=d.id, model=d.params["model"], v_t=d.params["v_t"],
            vz=d.params.get("v_z"), izm=d.params.get("i_zm"),
            state=peak.states[d.id],
            v_ak=sig_round(peak.volts.get(d.node_positive, 0.0) - peak.volts.get(d.node_negative, 0.0)),
            i=sig_round(abs(peak.diode_currents[d.id]) if peak.states[d.id] == "ZENER"
                        else peak.diode_currents[d.id]),
        )
        for d in setup.diodes
    ]
    return res


def _solve_clamper(
    parsed: ParsedCircuit,
    setup: WaveformSetup,
    target_probes,
):
    """
    Temel kitap kenetleme (clamper) devresi için kapalı biçimli çözüm.
    Eşik noktası asla durum çözümleyicisinden geçirilmez; V_C ve tüm örnekler
    V_O(t) = v_i(t) − V_C bağıntısıyla doğrudan hesaplanır.
    """
    from explainer.waveform_narrative import build_waveform_sections
    from solver.circuit_solver import sig_round

    cl = setup.clamper
    assert cl is not None

    # Ters bağlı kaynakta giriş düğümünün gördüğü gerilim v_i(t) = −eval_source(t) olur.
    sign = -1.0 if cl.source_reversed else 1.0

    if setup.shape == "SQUARE":
        v1 = sign * setup.v1
        v2 = sign * setup.v2
        v_i_max = max(v1, v2)
        v_i_min = min(v1, v2)
    elif setup.shape == "SINE":
        v_i_max = sign * setup.offset + setup.amplitude
        v_i_min = sign * setup.offset - setup.amplitude
    else:  # TRIANGLE
        v_i_max = setup.amplitude
        v_i_min = -setup.amplitude

    if cl.diode_to_gnd:
        v_in_cond = v_i_max
        v_in_off = v_i_min
        v_c = v_i_max - cl.v_k
        if v_c <= V_TOL:
            return _unsolvable(
                f"Diyotun iletime geçmesi için v_i > V_K ({_volts(cl.v_k)}) olmalı; "
                f"girişin en büyük değeri {_volts(v_i_max)} olduğundan diyot hiç iletime "
                "geçmez, kenetleme olmaz."
            )
        pinned = "TOP"
        shift = "DOWN"
    else:
        v_in_cond = v_i_min
        v_in_off = v_i_max
        v_c = v_i_min - cl.v_k
        if v_c >= -V_TOL:
            return _unsolvable(
                f"Diyotun iletime geçmesi için v_i < V_K ({_volts(cl.v_k)}) olmalı; "
                f"girişin en küçük değeri {_volts(v_i_min)} olduğundan diyot hiç iletime "
                "geçmez, kenetleme olmaz."
            )
        pinned = "BOTTOM"
        shift = "UP"

    v_c_plus_side = "INPUT" if v_c > 0.0 else "OUTPUT"

    T = setup.period
    t_total = NUM_PERIODS * T
    dt = T / SAMPLES_PER_PERIOD
    ts = [k * dt for k in range(TOTAL_SAMPLES)]

    v_ins: List[float] = []
    v_outs: List[float] = []
    levels: Optional[List[WaveformSquareLevel]] = None

    if setup.shape == "SQUARE":
        st1 = "ON" if abs(v1 - v_in_cond) <= V_TOL else "OFF"
        st2 = "ON" if abs(v2 - v_in_cond) <= V_TOL else "OFF"
        v_out1 = v1 - v_c
        v_out2 = v2 - v_c
        levels = [
            WaveformSquareLevel(
                v_in=_sig_round(v1, 6),
                v_out=_sig_round(v_out1, 6),
                states={cl.diode.id: st1},
            ),
            WaveformSquareLevel(
                v_in=_sig_round(v2, 6),
                v_out=_sig_round(v_out2, 6),
                states={cl.diode.id: st2},
            ),
        ]
        state_rows: List[Dict[str, str]] = []
        for k in range(TOTAL_SAMPLES):
            first_half = (k % SAMPLES_PER_PERIOD) < (SAMPLES_PER_PERIOD // 2)
            v_ins.append(_sig_round(v1 if first_half else v2, 6))
            v_outs.append(_sig_round(v_out1 if first_half else v_out2, 6))
            state_rows.append({cl.diode.id: st1 if first_half else st2})
        diode_traces = _build_diode_intervals(setup.diodes, ts, state_rows, t_total)
        v_dc_num = 0.5 * (v_out1 + v_out2)
    else:
        raw_v_outs: List[float] = []
        for t in ts:
            vin = sign * eval_source(setup, t)
            vout = vin - v_c
            v_ins.append(_sig_round(vin, 6))
            raw_v_outs.append(vout)
            v_outs.append(_sig_round(vout, 6))
        # Sinüs/üçgen girişte diyot yalnızca tepe anında sınırda iletime geçer; tüm periyot OFF raporlanır
        diode_traces = [
            WaveformDiodeTrace(
                id=cl.diode.id,
                intervals=[
                    WaveformDiodeInterval(t_start=0.0, t_end=_sig_round(t_total, 6), state="OFF")
                ],
            )
        ]
        v_dc_num = sum(raw_v_outs[:SAMPLES_PER_PERIOD]) / SAMPLES_PER_PERIOD

    v_out_max = v_i_max - v_c
    v_out_min = v_i_min - v_c
    input_swing = v_i_max - v_i_min
    output_swing = v_out_max - v_out_min

    # Kitabın 3 kontrolü (sıra sabit: salınım eşitliği, kayma yönü, 0 V seviyesi)
    swing_ok = abs(input_swing - output_swing) <= 1e-6 * max(abs(input_swing), 1.0)
    check_swing = WaveformClamperCheck(
        name="Salınım eşitliği",
        ok=swing_ok,
        text=f"Giriş salınımı {_volts(input_swing)}, çıkış salınımı {_volts(output_swing)}.",
    )

    expected_shift = "DOWN" if cl.diode_to_gnd else "UP"
    shift_ok = shift == expected_shift
    dir_word = "aşağı" if cl.diode_to_gnd else "yukarı"
    branch_dir = "çıkıştan toprağa" if cl.diode_to_gnd else "topraktan çıkışa"
    check_shift = WaveformClamperCheck(
        name="Kayma yönü",
        ok=shift_ok,
        text=(
            f"Diyot {branch_dir} ilettiğinden çıkış {dir_word} kayar "
            f"(kayma miktarı {_volts(abs(v_c))})."
        ),
    )

    is_ideal = cl.diode.params["model"] == "IDEAL"
    if is_ideal and cl.bias_source is None:
        zero_ok = abs(v_out_max) <= 1e-9 or abs(v_out_min) <= 1e-9
        pinned_lbl = "üst seviye" if cl.diode_to_gnd else "alt seviye"
        check_zero = WaveformClamperCheck(
            name="0 V seviyesi",
            ok=zero_ok,
            text=f"İdeal diyot ve seri kaynak olmadığından çıkışın bir ucu 0 V'a kenetlenir ({pinned_lbl} = 0 V).",
        )
    else:
        reasons = []
        if cl.bias_source is not None:
            reasons.append("diyota seri kaynak var")
        if not is_ideal:
            reasons.append("diyot ideal değil")
        check_zero = WaveformClamperCheck(
            name="0 V seviyesi",
            ok=None,
            text=f"Uygulanmaz: {' ve '.join(reasons)}.",
        )

    tau = cl.resistor.value * cl.capacitor.value
    if tau < 5.0 * T:
        rc_note: Optional[str] = (
            "Kitap yöntemi kondansatörün yalıtım alternansında boşalmadığını (RC ≫ T) varsayar. "
            f"Bu devrede τ = RC = {eng(tau, 's')}, T = {eng(T, 's')}; gerçek devrede çıkış seviyeleri eğimli olur."
        )
    else:
        rc_note = None

    clamper_info = WaveformClamperInfo(
        v_c=_sig_round(v_c, 6),
        v_c_plus_side=v_c_plus_side,
        v_k=_sig_round(cl.v_k, 6),
        pinned=pinned,
        shift=shift,
        input_swing=_sig_round(input_swing, 6),
        output_swing=_sig_round(output_swing, 6),
        checks=[check_swing, check_shift, check_zero],
        tau=_sig_round(tau, 6),
        period=_sig_round(T, 6),
        rc_note=rc_note,
    )

    summary = WaveformSummary(
        source_id=setup.source.id,
        shape=setup.shape,
        frequency=_sig_round(setup.frequency, 6),
        period=_sig_round(T, 6),
        output_id=cl.resistor.id,
        output_label=f"V_O ({cl.resistor.id})",
        t=[_sig_round(x, 6) for x in ts],
        v_in=v_ins,
        v_out=v_outs,
        diodes=diode_traces,
        v_out_max=_sig_round(v_out_max, 6),
        v_out_min=_sig_round(v_out_min, 6),
        v_dc_numeric=_sig_round(v_dc_num, 6),
        book_formula=None,
        conduction_angle_deg=None,
        levels=levels,
        clamper=clamper_info,
    )

    # Anlık görüntü (iletim alternansı anı): y = V_K, I_D = 0 (sınır), I_R = V_K / R, I_C = I_R
    volts: Dict[str, float] = {
        "0": 0.0,
        cl.input_node: v_in_cond,
        cl.output_node: cl.v_k,
    }
    if cl.mid_node is not None:
        if cl.diode_on_y_side:
            # y — D — m — V_bias — 0: V(m) seri kaynağın 0'a göre gerilimidir
            volts[cl.mid_node] = cl.v_bias
        else:
            # y — V_bias — m — D — 0: V(m) iletimdeki diyotun 0'a göre gerilimidir
            volts[cl.mid_node] = cl.v_t if cl.diode_to_gnd else -cl.v_t

    i_y_to_0 = cl.v_k / cl.resistor.value
    raw_currents: Dict[str, float] = {}
    for e in parsed.elements:
        if e.id == cl.resistor.id:
            raw_currents[e.id] = i_y_to_0 if e.node_positive == cl.output_node else -i_y_to_0
        elif e.id == cl.capacitor.id:
            # y düğümünde KCL: C'den y'ye giren akım = R'den 0'a akan akım (I_D = 0)
            raw_currents[e.id] = i_y_to_0 if e.node_positive == cl.input_node else -i_y_to_0
        elif e.id == setup.source.id:
            # Pasif işaret kuralı: dış devreye a'dan I_C verilir; ters kaynakta (0→a) iç akım +I_C olur
            raw_currents[e.id] = i_y_to_0 if cl.source_reversed else -i_y_to_0
        else:
            # Diyot (ve varsa seri DC kaynak): sınırda I_D = 0
            raw_currents[e.id] = 0.0

    results = AnalysisResults()
    results.node_voltages["0"] = NodeVoltage(value=0.0, unit="V", label="GND")
    for nd, val in sorted(volts.items(), key=lambda kv: (len(kv[0]), kv[0])):
        if nd != "0":
            results.node_voltages[nd] = NodeVoltage(value=sig_round(val), unit="V")

    for e in parsed.elements:
        results.element_currents[e.id] = ElementCurrent(
            value=sig_round(raw_currents.get(e.id, 0.0)),
            unit="A",
            direction=f"{e.node_positive}→{e.node_negative}",
        )

    v_ak_snap = volts[cl.diode.node_positive] - volts[cl.diode.node_negative]
    results.diodes = [
        DiodeResult(
            id=cl.diode.id,
            model=cl.diode.params["model"],
            v_t=cl.v_t,
            vz=None,
            izm=None,
            state="ON",
            v_ak=sig_round(v_ak_snap),
            i=0.0,
        )
    ]

    all_probes = list(target_probes or [])
    seen_probes = {p.id for p in all_probes}
    all_probes += [p for p in parsed.probes if p.id not in seen_probes]
    for p in all_probes:
        kind = str(getattr(p, "type", None) or getattr(p, "probe_type", "")).upper()
        if kind == "V" and p.target in volts:
            results.probe_results.append(
                ProbeResult(probe_id=p.id, type="V", value=sig_round(volts[p.target]), unit="V")
            )
        elif kind == "I" and p.target in raw_currents:
            results.probe_results.append(
                ProbeResult(probe_id=p.id, type="I", value=sig_round(raw_currents[p.target]), unit="A")
            )

    analysis = WaveformAnalysis(
        setup=setup,
        summary=summary,
        clamper_v_i_max=v_i_max,
        clamper_v_i_min=v_i_min,
        clamper_v_in_cond=v_in_cond,
        clamper_v_in_off=v_in_off,
    )
    results.waveform = summary
    results.explanation = build_waveform_sections(analysis)
    results.practice = []
    return results, [], []


def solve_waveform(
    parsed: ParsedCircuit,
    mode: AnalysisMode,
    frequency: Optional[float],
    target_probes,
    warnings: List[str],
    waveform_output: Optional[str] = None,
):
    """
    Dalga Şekli (WAVEFORM) ana giriş noktası (diyotlu devreler için solver.diode çağırır).
    Uygulanamazsa: saf DC diyotlu devrede NODAL'a düşer; AC/kare/üçgen kaynaklı diyotlu
    devrede ⛔ hatasıyla durur.
    """
    from explainer.waveform_narrative import (
        build_waveform_sections, fallback_note, fallback_section,
    )
    from solver.circuit_solver import UNSOLVABLE_PREFIX
    from solver.diode import gate_reason

    setup, reason = detect_waveform_circuit(parsed, frequency, waveform_output)
    if setup is None:
        if gate_reason(parsed, mode) is None:
            # Saf DC diyotlu devrede kullanıcı Dalga Şekli seçtiyse NODAL-DC'ye düş
            results, steps, errors = solve_with_diodes(
                parsed, mode, frequency, AnalysisType.NODAL, None, target_probes, warnings,
            )
            errors.append(fallback_note(reason))
            if results.explanation:
                results.explanation.insert(0, fallback_section(reason))
            return results, steps, errors
        return _unsolvable(f"Dalga Şekli uygulanamadı: {reason}.")

    if setup.clamper is not None:
        return _solve_clamper(parsed, setup, target_probes)

    T = setup.period
    t_total = NUM_PERIODS * T
    dt = T / SAMPLES_PER_PERIOD
    ts = [k * dt for k in range(TOTAL_SAMPLES)]

    sampler = _FastSampler(parsed, setup)
    v_ins: List[float] = []
    v_outs: List[float] = []
    state_rows: List[Dict[str, str]] = []
    levels: Optional[List[WaveformSquareLevel]] = None

    try:
        if setup.shape == "SQUARE":
            p1 = sampler.solve_at(setup.v1)
            p2 = sampler.solve_at(setup.v2)
            levels = [
                WaveformSquareLevel(
                    v_in=_sig_round(setup.v1, 6),
                    v_out=_sig_round(p1.v_out, 6),
                    states=dict(p1.states),
                ),
                WaveformSquareLevel(
                    v_in=_sig_round(setup.v2, 6),
                    v_out=_sig_round(p2.v_out, 6),
                    states=dict(p2.states),
                ),
            ]
            for k in range(TOTAL_SAMPLES):
                pt = p1 if (k % SAMPLES_PER_PERIOD) < (SAMPLES_PER_PERIOD // 2) else p2
                v_ins.append(_sig_round(pt.v_in, 6))
                v_outs.append(_sig_round(pt.v_out, 6))
                state_rows.append(pt.states)
            pos_peak = p1 if setup.v1 >= setup.v2 else p2
            neg_peak = p2 if setup.v1 >= setup.v2 else p1
        else:
            raw_v_outs: List[float] = []
            for t in ts:
                vin = eval_source(setup, t)
                pt = sampler.solve_at(vin)
                v_ins.append(_sig_round(pt.v_in, 6))
                raw_v_outs.append(pt.v_out)
                v_outs.append(_sig_round(pt.v_out, 6))
                state_rows.append(pt.states)
            v_pos_in = setup.offset + setup.amplitude
            v_neg_in = setup.offset - setup.amplitude
            pos_peak = sampler.solve_at(v_pos_in)
            neg_peak = sampler.solve_at(v_neg_in)
    except DiodeUnsolvable as e:
        return _unsolvable(str(e))

    # Bir periyot üzerinden sayısal ortalama (ilk 200 örnek = [0, T))
    if setup.shape == "SQUARE":
        v_dc_num = 0.5 * (levels[0].v_out + levels[1].v_out)
    else:
        v_dc_num = sum(raw_v_outs[:SAMPLES_PER_PERIOD]) / SAMPLES_PER_PERIOD

    v_out_max = max(v_outs)
    v_out_min = min(v_outs)

    diode_traces = _build_diode_intervals(setup.diodes, ts, state_rows, t_total)
    pattern, pattern_pos, book_formula = _recognize_rectifier(setup, v_out_max, v_out_min)
    cond_angle, cond_time, cond_v_th, cond_neg = _find_conduction_start(setup, sampler)
    path_th_v, path_th_expr = _path_threshold(setup, pattern, pos_peak, neg_peak)

    summary = WaveformSummary(
        source_id=setup.source.id,
        shape=setup.shape,
        frequency=_sig_round(setup.frequency, 6),
        period=_sig_round(setup.period, 6),
        output_id=setup.output_elem.id,
        output_label=f"V_O ({setup.output_elem.id})",
        t=[_sig_round(x, 6) for x in ts],
        v_in=v_ins,
        v_out=v_outs,
        diodes=diode_traces,
        v_out_max=_sig_round(v_out_max, 6),
        v_out_min=_sig_round(v_out_min, 6),
        v_dc_numeric=_sig_round(v_dc_num, 6),
        book_formula=book_formula,
        conduction_angle_deg=cond_angle,
        levels=levels,
    )

    # Pozitif tepe anındaki DC-eşdeğer çözüm → results.node_voltages, element_currents, diodes
    dc_peak_circuit = copy.copy(parsed)
    dc_peak_circuit.elements = [
        ParsedElement(
            id=setup.source.id, element_type=ElementType.DC_SOURCE,
            node_positive=setup.source.node_positive, node_negative=setup.source.node_negative,
            value=pos_peak.v_in,
        ) if e.id == setup.source.id else e
        for e in parsed.elements
    ]
    results, steps, errors = solve_with_diodes(
        dc_peak_circuit, AnalysisMode.DC, None, AnalysisType.NODAL,
        None, target_probes, warnings,
    )
    if any(m.startswith(UNSOLVABLE_PREFIX) for m in errors) or not results.node_voltages:
        # Örn. köprü devresinde V_m < 2·V_T iken tüm diyotlar OFF ve kaynak yüzer
        results = _numeric_peak_results(parsed, setup, pos_peak)
        steps = []
        errors = []

    analysis = WaveformAnalysis(
        setup=setup,
        summary=summary,
        pos_peak=pos_peak,
        neg_peak=neg_peak,
        pattern=pattern,
        pattern_positive=pattern_pos,
        conduction_threshold_v=cond_v_th,
        conduction_time_s=cond_time,
        conduction_in_neg_half=cond_neg,
        path_threshold_v=path_th_v,
        path_threshold_expr=path_th_expr,
    )
    results.waveform = summary
    results.explanation = build_waveform_sections(analysis)
    results.practice = []
    return results, steps, errors
