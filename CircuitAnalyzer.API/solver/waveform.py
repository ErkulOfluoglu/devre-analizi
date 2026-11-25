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
    AnalysisResults, DiodeResult, ElementCurrent, NodeVoltage,
    WaveformBookFormula, WaveformDiodeInterval, WaveformDiodeTrace,
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
    pos_peak: SamplePoint
    neg_peak: SamplePoint
    pattern: Optional[str] = None              # "HALF_WAVE" | "BRIDGE" | None
    pattern_positive: bool = True              # True: çıkış pozitif yarım/tam dalga
    conduction_threshold_v: Optional[float] = None
    conduction_time_s: Optional[float] = None
    conduction_in_neg_half: bool = False
    path_threshold_v: Optional[float] = None   # tek yolda belirgin toplam eşik (ör. Si+Ge+3V = 4 V)
    path_threshold_expr: Optional[str] = None


# ═══════════════════════════════════════════════════════
#  UYGUNLUK DENETİMİ
# ═══════════════════════════════════════════════════════

def _source_peak_sine(src: ParsedElement) -> float:
    """SINE kaynağının gerçek tepe genliği (RMS girişiyse √2 ile çarpılır)."""
    in_val = float(src.params.get("input_value", src.params.get("amplitude", src.value)))
    in_basis = str(src.params.get("input_basis", "PEAK")).upper()
    return in_val * math.sqrt(2.0) if in_basis == "RMS" else in_val


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
