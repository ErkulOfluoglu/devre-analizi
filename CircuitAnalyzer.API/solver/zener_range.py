"""
CircuitAnalyzer API — Zener Aralığı (ZENER_RANGE) çözücüsü (Faz 4b-2)

Kitaptaki temel zener regülatör topolojisi (yapısal olarak tanınır, eleman adına bağlı değildir):
    • Tek DC gerilim kaynağı V_İ: (+) düğüm a, (−) GND (0)
    • Seri direnç R_X: düğüm a ↔ düğüm y
    • Tek zener diyot D: anot GND (0), katot düğüm y (ters polarma yönü)
    • Yük direnci R_Y: düğüm y ↔ GND (0)

İki durum:
    • LOAD  (hedef R_Y, varsayılan): V_İ sabit, zenerin ters iletimde kalıp I_ZM'yi aşmayacağı
      R_Y ∈ [R_Y,min, R_Y,max] aralığı.
    • INPUT (hedef V_İ): R_Y sabit, V_İ ∈ [V_İ,min, V_İ,max] aralığı.

Sağlama (3 değer kontrolü) el formülüyle değil, devreyi doğrudan mevcut diyot/zener çözücüsüyle
(solver.diode.solve_with_diodes) yeniden çözerek yapılır.
"""

import copy
import dataclasses
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from explainer.formatting import MINUS, eng
from models.request import AnalysisMode, AnalysisType
from models.response import (
    ZenerRangeCheck, ZenerRangeCurve, ZenerRangeStep, ZenerRangeSummary,
)
from parser.netlist_parser import (
    DIODE_TYPES, PHASOR_SOURCES, SINE_SOURCES, ElementType, ParsedCircuit, ParsedElement,
)

# Zener akım sınırı karşılaştırma toleransı (solver.diode.I_TOL ile uyumlu)
_I_TOL = 1e-9
_ZERO_TOL = 1e-15


@dataclass
class ZenerRegulator:
    """Yapısal olarak tanınmış temel zener regülatör devresi."""
    vs: ParsedElement
    rx: ParsedElement
    ry: ParsedElement
    dz: ParsedElement
    node_a: str
    node_y: str
    kind: str                 # "LOAD" | "INPUT"
    target: ParsedElement     # ry (LOAD) veya vs (INPUT)
    v_i: float
    r_x: float
    r_y: float
    v_z: float
    i_zm: Optional[float]


@dataclass
class ZenerRangeAnalysis:
    """Zener Aralığı hesabının tüm ara büyüklükleri ve yanıt özeti."""
    reg: ZenerRegulator
    summary: ZenerRangeSummary
    unbounded_reason: Optional[str] = None
    # LOAD ara değerleri
    v_x: Optional[float] = None
    i_x: Optional[float] = None
    i_y_max: Optional[float] = None
    i_y_min: Optional[float] = None
    # INPUT ara değerleri
    i_y: Optional[float] = None
    i_x_min: Optional[float] = None
    i_x_max: Optional[float] = None
    v_x_min: Optional[float] = None
    v_x_max: Optional[float] = None


def _sig_round(x: float, digits: int = 10) -> float:
    if not math.isfinite(x):
        return x
    if abs(x) < _ZERO_TOL:
        return 0.0
    return float(f"{x:.{digits}g}")


# ═══════════════════════════════════════════════════════
#  YAPISAL UYGUNLUK DENETİMİ
# ═══════════════════════════════════════════════════════

def detect_zener_regulator(
    parsed: ParsedCircuit,
    mode: AnalysisMode,
    target_id: Optional[str] = None,
) -> Tuple[Optional[ZenerRegulator], str]:
    """
    Devrenin kitap topolojisine uyup uymadığını düğüm kümeleriyle denetler.
    Dönüş: (ZenerRegulator, "") veya (None, Türkçe uygulanamama nedeni).
    """
    if mode != AnalysisMode.DC or any(
        e.element_type in SINE_SOURCES + PHASOR_SOURCES
        or e.element_type == ElementType.THREE_PHASE_SOURCE
        for e in parsed.elements
    ):
        return None, "Zener Aralığı yalnızca DC gerilim kaynaklı devrelerde uygulanır"

    for e in parsed.elements:
        if e.element_type == ElementType.SWITCH:
            return None, (f"devrede anahtar var ({e.id}); Zener Aralığı yalnızca temel zener "
                          "regülatör devresinde (DC kaynak, R_X, zener diyot ve R_Y) uygulanır")

    allowed = (ElementType.DC_SOURCE, ElementType.RESISTOR, ElementType.DIODE)
    for e in parsed.elements:
        if e.element_type not in allowed:
            return None, (f"devrede {e.id} elemanı var; Zener Aralığı yalnızca bir DC gerilim "
                          "kaynağı, iki direnç (R_X, R_Y) ve bir zener diyottan oluşan regülatör "
                          "devresinde uygulanır")

    diodes = [e for e in parsed.elements if e.element_type in DIODE_TYPES]
    if not diodes:
        return None, "devrede zener diyot yok; Zener Aralığı bir zener regülatör devresi gerektirir"
    if len(diodes) > 1:
        return None, "devrede birden fazla diyot var; Zener Aralığı yalnızca tek zener diyotlu regülatör devresinde uygulanır"
    dz = diodes[0]
    if dz.params.get("model") != "ZENER":
        model_lbl = dz.params.get("model", "diyot")
        return None, (f"devredeki {dz.id} elemanı zener diyot değil ({model_lbl}); "
                      "Zener Aralığı yalnızca zener diyotlu regülatör devresinde uygulanır")

    sources = [e for e in parsed.elements if e.element_type == ElementType.DC_SOURCE]
    if not sources:
        return None, "devrede DC gerilim kaynağı yok; Zener Aralığı tek DC gerilim kaynaklı regülatör devresinde uygulanır"
    if len(sources) > 1:
        return None, "devrede birden fazla DC gerilim kaynağı var; Zener Aralığı tek DC gerilim kaynaklı regülatör devresinde uygulanır"
    vs = sources[0]

    resistors = [e for e in parsed.elements if e.element_type == ElementType.RESISTOR]
    if len(resistors) < 2:
        return None, "devrede seri direnç (R_X) ve yük direnci (R_Y) olmak üzere tam iki direnç bulunmalıdır"
    if len(resistors) > 2:
        return None, (f"devrede {len(resistors)} direnç var; Zener Aralığı yalnızca bir seri direnç (R_X) "
                      "ve bir yük direncinden (R_Y) oluşan temel regülatör topolojisinde uygulanır")

    # Zener bağlantısı: anot GND'de (0), katot çıkış düğümünde (y) olmalı
    if dz.node_positive != "0":
        if dz.node_negative == "0":
            return None, "zener diyotun katodu çıkış düğümünde, anodu GND'de olmalıdır (ters polarma yönü)"
        return None, "zener diyotun anodu referans düğüme (GND) bağlı olmalıdır"
    node_y = dz.node_negative
    if node_y == "0":
        return None, "zener diyotun katodu GND'den farklı bir çıkış düğümünde olmalıdır"

    # Kaynak bağlantısı: (+) giriş düğümünde (a), (−) GND'de (0)
    if "0" not in (vs.node_positive, vs.node_negative):
        return None, "DC gerilim kaynağı bir ucuyla referans düğüme (GND) bağlı olmalıdır"
    if vs.node_negative != "0":
        return None, "DC gerilim kaynağının (−) ucu GND'ye, (+) ucu giriş düğümüne bağlı olmalıdır"
    node_a = vs.node_positive
    if node_a == node_y:
        return None, "DC gerilim kaynağı ile zener diyot arasında bir seri direnç (R_X) bulunmalıdır"

    # İki direnci yapısal olarak (düğüm kümeleriyle) ayır: {a, y} → R_X, {y, 0} → R_Y
    rx: Optional[ParsedElement] = None
    ry: Optional[ParsedElement] = None
    pair_x = {node_a, node_y}
    pair_y = {node_y, "0"}
    for r in resistors:
        nodes = {r.node_positive, r.node_negative}
        if nodes == pair_x and rx is None:
            rx = r
        elif nodes == pair_y and ry is None:
            ry = r
    if rx is None or ry is None:
        return None, ("iki dirençten biri kaynak ile zener arasında (seri direnç R_X), diğeri zener "
                      "ile paralel yük olarak (R_Y, çıkış düğümü–GND) bağlı olmalıdır")

    if rx.value <= 0 or ry.value <= 0:
        return None, "seri ve yük dirençleri pozitif olmalıdır"

    v_z = float(dz.params["v_z"])
    i_zm = dz.params.get("i_zm")
    i_zm_f = float(i_zm) if i_zm is not None else None
    v_i = float(vs.value)

    # Hedef seçimi: boşsa yük direnci (LOAD), R_Y → LOAD, V_İ → INPUT, başka eleman → neden
    wanted = (target_id or "").strip()
    if not wanted:
        kind, target = "LOAD", ry
    else:
        matched = next((e for e in parsed.elements if e.id.upper() == wanted.upper()), None)
        if matched is None:
            return None, (f"“{wanted}” adlı bir eleman devrede yok; hedef olarak yük direnci "
                          f"({ry.id}) veya giriş gerilim kaynağı ({vs.id}) seçilmelidir")
        if matched.id == ry.id:
            kind, target = "LOAD", ry
        elif matched.id == vs.id:
            kind, target = "INPUT", vs
        elif matched.id == rx.id:
            return None, (f"hedef olarak seri direnç ({rx.id}) seçilmiş; Zener Aralığı yük direnci "
                          f"({ry.id}) veya giriş gerilim kaynağı ({vs.id}) için hesaplanır")
        else:
            return None, (f"hedef olarak zener diyot ({dz.id}) seçilmiş; Zener Aralığı yük direnci "
                          f"({ry.id}) veya giriş gerilim kaynağı ({vs.id}) için hesaplanır")

    if kind == "LOAD" and v_i <= v_z:
        return None, "giriş gerilimi V_Z'den büyük olmadıkça zener ters iletime geçemez"

    return ZenerRegulator(
        vs=vs, rx=rx, ry=ry, dz=dz,
        node_a=node_a, node_y=node_y,
        kind=kind, target=target,
        v_i=v_i, r_x=float(rx.value), r_y=float(ry.value),
        v_z=v_z, i_zm=i_zm_f,
    ), ""


# ═══════════════════════════════════════════════════════
#  YUVARLANMIŞ SAĞLAMA DEĞERLERİ VE TAM DEVRE ÇÖZÜMÜ
# ═══════════════════════════════════════════════════════

def _pick_nice(target: float, lo: float, hi: float) -> float:
    """
    Açık aralık (lo, hi) içinde kalan en sade yuvarlanmış (1 → 2 → 3 anlamlı basamak) değeri seçer.
    Sınırda kayan nokta eşitliği durum değiştirmesin diye küçük bir güvenlik payı bırakılır.
    """
    lo_lim = lo * (1.0 + 1e-6) if lo > 0 else 1e-12
    hi_lim = hi * (1.0 - 1e-6) if math.isfinite(hi) else math.inf
    for digits in (1, 2, 3):
        cand = float(f"{target:.{digits}g}")
        if lo_lim < cand < hi_lim:
            return cand
    return _sig_round(target, 4)


def _select_check_values(
    x_min: float, x_max: Optional[float], current_value: float,
) -> List[float]:
    """Sağlama için 3 (üst sınır sonsuzsa 2) yuvarlanmış test değeri seçer."""
    below = _pick_nice(0.8 * x_min, 0.0, x_min)

    # Mevcut değer sınırların kesinlikle içindeyse kendi değerini kullan; sınırda eşitlik OFF verir
    lo_strict = x_min * (1.0 + 1e-6)
    hi_strict = math.inf if x_max is None else x_max * (1.0 - 1e-6)
    if lo_strict < current_value < hi_strict:
        inside = current_value
    elif x_max is not None:
        inside = _pick_nice(0.5 * (x_min + x_max), x_min, x_max)
    else:
        inside = _pick_nice(1.5 * x_min, x_min, math.inf)

    values = [below, inside]
    if x_max is not None:
        above = _pick_nice(1.25 * x_max, x_max, 2.0 * x_max)
        values.append(above)
    return values


def _solve_check(circuit: ParsedCircuit, reg: ZenerRegulator, x_val: float) -> ZenerRangeCheck:
    """
    Hedef elemanı x_val değerine ayarlayıp devreyi mevcut zener çözücüsüyle tam olarak çözer.
    El formülü kullanılmaz; state, V_Y ve I_Z doğrudan çözücü çıktısından okunur.
    """
    from solver.diode import solve_with_diodes

    mod = copy.copy(circuit)
    mod.elements = [
        dataclasses.replace(e, value=float(x_val)) if e.id == reg.target.id else e
        for e in circuit.elements
    ]
    res, _, _ = solve_with_diodes(mod, AnalysisMode.DC, None, AnalysisType.NODAL, None, None, [])
    d_res = next(d for d in res.diodes if d.id == reg.dz.id)
    state = d_res.state
    nv_y = res.node_voltages[reg.node_y].value
    v_y = float(nv_y) if isinstance(nv_y, (int, float)) else float(nv_y.real)
    i_z = float(d_res.i) if state == "ZENER" else 0.0

    sym = "R_Y" if reg.kind == "LOAD" else "V_İ"
    unit = "Ω" if reg.kind == "LOAD" else "V"

    if state == "ZENER" and reg.i_zm is not None and i_z > reg.i_zm + _I_TOL:
        verdict = "ABOVE"
        verdict_txt = "⚠ aralığın üstünde: I_Z > I_ZM (zener zarar görür)"
    elif state == "ZENER":
        verdict = "OK"
        verdict_txt = "uygun"
    else:
        verdict = "BELOW"
        verdict_txt = "aralığın altında: zener yalıtımda, V_Y < V_Z"

    state_tr = {"ZENER": "ters iletimde (zener bölgesi)", "OFF": "yalıtımda", "ON": "doğru yönde iletimde"}[state]
    iz_txt = "0" if abs(i_z) < _ZERO_TOL else eng(i_z, "A")
    text = f"{sym} = {eng(x_val, unit)} → {reg.dz.id} {state_tr}, V_Y = {eng(v_y, 'V')}, I_Z = {iz_txt} → {verdict_txt}"

    return ZenerRangeCheck(
        x=_sig_round(x_val, 6),
        state=state,
        v_y=_sig_round(v_y, 6),
        i_z=_sig_round(i_z, 6),
        verdict=verdict,
        text=text,
    )


# ═══════════════════════════════════════════════════════
#  EĞRİ (~200 NOKTA)
# ═══════════════════════════════════════════════════════

def _build_curve(
    reg: ZenerRegulator, x_min: float, x_max: Optional[float], n_points: int = 200,
) -> ZenerRangeCurve:
    """V_Y ve I_Z eğrisini ~200 noktada hesaplar; diz noktası x_min tam örneklenir."""
    x_end = 2.0 * x_max if x_max is not None else 3.0 * x_min
    x_start = max(x_end * 1e-4, 1e-6) if reg.kind == "LOAD" else 0.0

    base_count = n_points - (2 if x_max is not None else 1)
    step = (x_end - x_start) / max(base_count - 1, 1)
    xs = [x_start + k * step for k in range(base_count)]
    xs.append(x_min)
    if x_max is not None:
        xs.append(x_max)
    xs.sort()

    # Çok yakın yinelemeleri ayıkla (x_min ızgara noktasıyla çakışabilir)
    dedup: List[float] = []
    for xv in xs:
        if not dedup or abs(xv - dedup[-1]) > 1e-12 * max(abs(x_end), 1.0):
            dedup.append(xv)

    out_x: List[float] = []
    out_vy: List[float] = []
    out_iz: List[float] = []
    v_z = reg.v_z
    r_x = reg.r_x
    r_y_fixed = reg.r_y
    v_i_fixed = reg.v_i

    for xv in dedup:
        if reg.kind == "LOAD":
            v_oc = v_i_fixed * xv / (r_x + xv)
            if v_oc < v_z:
                vy, iz = v_oc, 0.0
            else:
                vy = v_z
                iz = max(0.0, (v_i_fixed - v_z) / r_x - v_z / xv)
        else:
            v_oc = xv * r_y_fixed / (r_x + r_y_fixed)
            if v_oc < v_z:
                vy, iz = v_oc, 0.0
            else:
                vy = v_z
                iz = max(0.0, (xv - v_z) / r_x - v_z / r_y_fixed)
        out_x.append(_sig_round(xv, 6))
        out_vy.append(_sig_round(vy, 6))
        out_iz.append(_sig_round(iz, 6))

    return ZenerRangeCurve(x=out_x, v_y=out_vy, i_z=out_iz)


# ═══════════════════════════════════════════════════════
#  ANA ANALİZ GİRİŞİ
# ═══════════════════════════════════════════════════════

def analyze_zener_range(
    circuit: ParsedCircuit,
    mode: AnalysisMode,
    target_id: Optional[str] = None,
) -> Tuple[Optional[ZenerRangeAnalysis], str]:
    """
    Zener Aralığı analizini çalıştırır.
    Uygulanabilirse (ZenerRangeAnalysis, ""), değilse (None, Türkçe neden).
    """
    reg, reason = detect_zener_regulator(circuit, mode, target_id)
    if reg is None:
        return None, reason

    steps: List[ZenerRangeStep] = []
    unbounded_reason: Optional[str] = None

    if reg.kind == "LOAD":
        symbol, unit, x_label = "R_Y", "Ω", "R_Y (Ω)"
        current_value = reg.r_y

        v_x = reg.v_i - reg.v_z
        i_x = v_x / reg.r_x
        i_y_max = i_x
        x_min = reg.v_z / i_y_max

        steps.append(ZenerRangeStep(
            symbol="V_X", value=_sig_round(v_x), unit="V",
            text=f"V_X = V_İ {MINUS} V_Z = {eng(reg.v_i, 'V')} {MINUS} {eng(reg.v_z, 'V')} = {eng(v_x, 'V')}",
        ))
        steps.append(ZenerRangeStep(
            symbol="I_X", value=_sig_round(i_x), unit="A",
            text=f"I_X = V_X / R_X = {eng(v_x, 'V')} / {eng(reg.r_x, 'Ω')} = {eng(i_x, 'A')}",
        ))
        steps.append(ZenerRangeStep(
            symbol="I_Y,max", value=_sig_round(i_y_max), unit="A",
            text=f"I_Y,max = I_X {MINUS} I_Z,min = {eng(i_x, 'A')} {MINUS} 0 = {eng(i_y_max, 'A')}",
        ))

        if reg.i_zm is None:
            i_y_min = None
            x_max = None
            unbounded_reason = (
                f"{reg.dz.id} için en büyük zener akımı (I_ZM) belirtilmediğinden "
                "üst yük direnci sınırı yoktur (R_Y,max = ∞)."
            )
        else:
            i_y_min = i_x - reg.i_zm
            steps.append(ZenerRangeStep(
                symbol="I_Y,min", value=_sig_round(i_y_min), unit="A",
                text=f"I_Y,min = I_X {MINUS} I_ZM = {eng(i_x, 'A')} {MINUS} {eng(reg.i_zm, 'A')} = {eng(i_y_min, 'A')}",
            ))
            if i_y_min > _ZERO_TOL:
                x_max = reg.v_z / i_y_min
            else:
                x_max = None
                unbounded_reason = (
                    f"I_X = {eng(i_x, 'A')} ≤ I_ZM = {eng(reg.i_zm, 'A')} (I_Y,min ≤ 0) olduğundan "
                    "yük açık devre olsa bile zener akımı I_ZM sınırını aşmaz; R_Y,max = ∞."
                )

        steps.append(ZenerRangeStep(
            symbol="R_Y,min", value=_sig_round(x_min), unit="Ω",
            text=f"R_Y,min = V_Z / I_Y,max = {eng(reg.v_z, 'V')} / {eng(i_y_max, 'A')} = {eng(x_min, 'Ω')}",
        ))
        if x_max is not None:
            steps.append(ZenerRangeStep(
                symbol="R_Y,max", value=_sig_round(x_max), unit="Ω",
                text=f"R_Y,max = V_Z / I_Y,min = {eng(reg.v_z, 'V')} / {eng(i_y_min, 'A')} = {eng(x_max, 'Ω')}",
            ))
        else:
            steps.append(ZenerRangeStep(
                symbol="R_Y,max", value=None, unit="Ω",
                text="R_Y,max = ∞",
            ))

        analysis_extra = dict(v_x=v_x, i_x=i_x, i_y_max=i_y_max, i_y_min=i_y_min)
    else:
        symbol, unit, x_label = "V_İ", "V", "V_İ (V)"
        current_value = reg.v_i

        i_y = reg.v_z / reg.r_y
        i_x_min = i_y
        v_x_min = i_x_min * reg.r_x
        x_min = v_x_min + reg.v_z

        steps.append(ZenerRangeStep(
            symbol="I_Y", value=_sig_round(i_y), unit="A",
            text=f"I_Y = V_Z / R_Y = {eng(reg.v_z, 'V')} / {eng(reg.r_y, 'Ω')} = {eng(i_y, 'A')}",
        ))
        steps.append(ZenerRangeStep(
            symbol="I_X,min", value=_sig_round(i_x_min), unit="A",
            text=f"I_X,min = I_Y + I_Z,min = {eng(i_y, 'A')} + 0 = {eng(i_x_min, 'A')}",
        ))

        if reg.i_zm is None:
            i_x_max = None
            v_x_max = None
            x_max = None
            unbounded_reason = (
                f"{reg.dz.id} için en büyük zener akımı (I_ZM) belirtilmediğinden "
                "üst giriş gerilimi sınırı yoktur (V_İ,max = ∞)."
            )
        else:
            i_x_max = i_y + reg.i_zm
            v_x_max = i_x_max * reg.r_x
            x_max = v_x_max + reg.v_z
            steps.append(ZenerRangeStep(
                symbol="I_X,max", value=_sig_round(i_x_max), unit="A",
                text=f"I_X,max = I_Y + I_ZM = {eng(i_y, 'A')} + {eng(reg.i_zm, 'A')} = {eng(i_x_max, 'A')}",
            ))

        steps.append(ZenerRangeStep(
            symbol="V_X,min", value=_sig_round(v_x_min), unit="V",
            text=f"V_X,min = I_X,min · R_X = {eng(i_x_min, 'A')} · {eng(reg.r_x, 'Ω')} = {eng(v_x_min, 'V')}",
        ))
        if v_x_max is not None:
            steps.append(ZenerRangeStep(
                symbol="V_X,max", value=_sig_round(v_x_max), unit="V",
                text=f"V_X,max = I_X,max · R_X = {eng(i_x_max, 'A')} · {eng(reg.r_x, 'Ω')} = {eng(v_x_max, 'V')}",
            ))

        steps.append(ZenerRangeStep(
            symbol="V_İ,min", value=_sig_round(x_min), unit="V",
            text=f"V_İ,min = V_X,min + V_Z = {eng(v_x_min, 'V')} + {eng(reg.v_z, 'V')} = {eng(x_min, 'V')}",
        ))
        if x_max is not None:
            steps.append(ZenerRangeStep(
                symbol="V_İ,max", value=_sig_round(x_max), unit="V",
                text=f"V_İ,max = V_X,max + V_Z = {eng(v_x_max, 'V')} + {eng(reg.v_z, 'V')} = {eng(x_max, 'V')}",
            ))
        else:
            steps.append(ZenerRangeStep(
                symbol="V_İ,max", value=None, unit="V",
                text="V_İ,max = ∞",
            ))

        analysis_extra = dict(
            i_y=i_y, i_x_min=i_x_min, i_x_max=i_x_max, v_x_min=v_x_min, v_x_max=v_x_max,
        )

    tol_min = 1e-9 * max(abs(x_min), 1.0)
    inside_min = current_value >= x_min - tol_min
    inside_max = True if x_max is None else current_value <= x_max + 1e-9 * max(abs(x_max), 1.0)
    current_inside = inside_min and inside_max

    check_xs = _select_check_values(x_min, x_max, current_value)
    checks = [_solve_check(circuit, reg, xv) for xv in check_xs]
    curve = _build_curve(reg, x_min, x_max)

    summary = ZenerRangeSummary(
        target_id=reg.target.id,
        kind=reg.kind,
        symbol=symbol,
        unit=unit,
        min=_sig_round(x_min),
        max=None if x_max is None else _sig_round(x_max),
        current_value=_sig_round(current_value),
        current_inside=current_inside,
        steps=steps,
        checks=checks,
        curve=curve,
        x_label=x_label,
        y_label="V_Y (V)",
    )
    return ZenerRangeAnalysis(
        reg=reg,
        summary=summary,
        unbounded_reason=unbounded_reason,
        **analysis_extra,
    ), ""
