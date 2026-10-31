"""
CircuitAnalyzer API — Üç faz (Faz 3 / v1.6)

Üç fazlı kaynak (U), üç fazlı yük (Y) ve wattmetre (W) elemanları ORTAK netlistte tek elemandır;
çözücü (lcapy) için burada sıradan elemanlara açılır:

    Kaynak Y : üç AC gerilim kaynağı  R–N, S–N, T–N          (V_U1_R, V_U1_S, V_U1_T)
    Kaynak D : eşdeğer yıldız, yüzer sanal nötr düğümü (ideal üçgen gerilim çevrimi tekildir)
    Yük Y/D  : üç empedans (Z_Y1_R … / Z_Y1_RS …)
    Wattmetre: akım bobini 0 V'luk ölçüm kaynağı (V_W1), gerilim bobini açık devre

Sayılar lcapy'den gelir. Bu modül (1) açma işini, (2) çözülmüş devreden üç faz büyüklüklerini
(hat/faz akımı, nötr, güç, Aron, wattmetre, kompanzasyon) ve (3) anlatım için ELLE türetmeyi
hazırlar; elle türetme çözücüyle karşılaştırılır, uyuşmazsa anlatım kısa kalır.

Varsayımlar: D kaynakta θ eşdeğer yıldızın R fazının açısıdır (V_RN = U_f∠θ, U_f = U_h/√3);
u_phase her zaman hat–nötr gerilimi U_h/√3'tür.
"""

import cmath
import copy
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from parser.netlist_parser import (
    ElementType, ParsedCircuit, ParsedElement, element_nodes,
)

SQRT3 = math.sqrt(3.0)
PHASES = ("R", "S", "T")
DELTA_ARMS = (("RS", "R", "S"), ("ST", "S", "T"), ("TR", "T", "R"))
_TOL = 1e-5

THREE_PHASE_TYPES = (ElementType.THREE_PHASE_SOURCE, ElementType.THREE_PHASE_LOAD)


def three_phase_sources(parsed: ParsedCircuit) -> List[ParsedElement]:
    return [e for e in parsed.elements if e.element_type == ElementType.THREE_PHASE_SOURCE]


def three_phase_loads(parsed: ParsedCircuit) -> List[ParsedElement]:
    return [e for e in parsed.elements if e.element_type == ElementType.THREE_PHASE_LOAD]


def wattmeters(parsed: ParsedCircuit) -> List[ParsedElement]:
    return [e for e in parsed.elements if e.element_type == ElementType.WATTMETER]


def has_three_phase(parsed: ParsedCircuit) -> bool:
    return any(e.element_type in THREE_PHASE_TYPES for e in parsed.elements)


def has_wattmeters(parsed: ParsedCircuit) -> bool:
    return any(e.element_type == ElementType.WATTMETER for e in parsed.elements)


def cx(v) -> complex:
    """API değeri (float ya da ComplexNumber) → complex."""
    if isinstance(v, (int, float)):
        return complex(v)
    return complex(v.real, v.imaginary)


# ═══════════════════════════════════════════════════════
#  KAYNAK DEĞERLERİ
# ═══════════════════════════════════════════════════════

def source_levels(src: ParsedElement) -> Tuple[float, float]:
    """(U_h, U_f) — seçili gösterimde. Üçgen kaynakta girilen değer hat gerilimidir."""
    v = float(src.params["amplitude"])
    if src.params["connection"] == "D" or src.params["value_kind"] == "LINE":
        return v, v / SQRT3
    return v * SQRT3, v


def phase_voltages(src: ParsedElement) -> Dict[str, complex]:
    """Faz gerilimleri (eşdeğer yıldız): V_RN = U_f∠θ; S ve T faz sırasına göre ∓120°."""
    _, uf = source_levels(src)
    th = float(src.params["phase"])
    if src.params["sequence"] == "RST":
        s_ang, t_ang = th - 120.0, th + 120.0
    else:
        s_ang, t_ang = th + 120.0, th - 120.0
    return {"R": cmath.rect(uf, math.radians(th)),
            "S": cmath.rect(uf, math.radians(s_ang)),
            "T": cmath.rect(uf, math.radians(t_ang))}


def line_voltages(v: Dict[str, complex]) -> Dict[str, complex]:
    return {"RS": v["R"] - v["S"], "ST": v["S"] - v["T"], "TR": v["T"] - v["R"]}


def load_arms(load: ParsedElement) -> Dict[str, complex]:
    keys = PHASES if load.params["connection"] == "Y" else tuple(k for k, _, _ in DELTA_ARMS)
    return dict(zip(keys, load.params["z"]))


# ═══════════════════════════════════════════════════════
#  AÇMA (ortak netlist → sıradan elemanlar)
# ═══════════════════════════════════════════════════════

@dataclass
class Expansion:
    flat: ParsedCircuit
    sources: List[ParsedElement]
    loads: List[ParsedElement]
    meters: List[ParsedElement]
    src_arms: Dict[str, Dict[str, str]] = field(default_factory=dict)    # kaynak → faz → akım kaynağı kimliği
    src_neutral: Dict[str, str] = field(default_factory=dict)            # kaynak → (eşdeğer) nötr düğüm
    meter_ids: Dict[str, str] = field(default_factory=dict)              # wattmetre → 0 V kaynak kimliği
    rename: Dict[str, str] = field(default_factory=dict)                 # birleştirilen düğümler → "0"
    notes: List[str] = field(default_factory=list)
    frequency: Optional[float] = None

    def node(self, n: str) -> str:
        return self.rename.get(n, n)


def _effective_nodes(e: ParsedElement) -> Tuple[str, ...]:
    """Elemanın gerçekten kullandığı düğümler (üçgen bağlantıda N ucu kullanılmaz)."""
    if e.element_type in THREE_PHASE_TYPES:
        nodes = [e.node_positive, e.node_negative, e.params["t_node"]]
        if e.params["connection"] == "Y":
            nodes.append(e.params["n_node"])
        return tuple(nodes)
    if e.element_type == ElementType.WATTMETER:
        return (e.node_positive, e.node_negative)
    return element_nodes(e)


def _arm_elements(load_id: str, key: str, z: complex, a: str, b: str, freq: Optional[float],
                  uniq_id, uniq_node) -> List[ParsedElement]:
    """
    Kol empedansı Z = R + jX → seri R ve L (X > 0) ya da C (X < 0). lcapy karmaşık değerli
    tek bir Z elemanını, doğrudan kaynaklara bağlı üçgen kolda sayısal olarak bozar; R, L, C
    ile açılan kol ise doğru ve hızlı çözülür.
    """
    r, x = z.real, z.imag
    if abs(x) <= 1e-12 * abs(z) or not freq or freq <= 0:
        # Gerçek empedans Z elemanı olarak kalır: yalnızca dirençli bir lcapy devresinde farklı
        # fazlı AC kaynakların akımları doğru ayrışmaz (denendi); Z elemanıyla doğru çıkar.
        return [ParsedElement(id=uniq_id(f"Z_{load_id}_{key}"), element_type=ElementType.IMPEDANCE,
                              node_positive=a, node_negative=b, value=abs(z), params={"impedance": z})]
    w = 2 * math.pi * freq
    if x > 0:
        reactive = ParsedElement(id=uniq_id(f"L_{load_id}_{key}"), element_type=ElementType.INDUCTOR,
                                 node_positive=a, node_negative=b, value=x / w)
    else:
        reactive = ParsedElement(id=uniq_id(f"C_{load_id}_{key}"), element_type=ElementType.CAPACITOR,
                                 node_positive=a, node_negative=b, value=-1.0 / (w * x))
    if abs(r) <= 1e-12 * abs(z):
        return [reactive]
    mid = uniq_node(f"{load_id}_{key}_m")
    reactive.node_positive = mid
    return [ParsedElement(id=uniq_id(f"R_{load_id}_{key}"), element_type=ElementType.RESISTOR,
                          node_positive=a, node_negative=mid, value=r), reactive]


def expand_three_phase(parsed: ParsedCircuit, is_dc: bool = False,
                       frequency: Optional[float] = None) -> Expansion:
    """Üç fazlı kaynak/yük ve wattmetreleri sıradan elemanlara açar (parsed değişmez)."""
    used_ids = {e.id.upper() for e in parsed.elements}
    used_nodes = {n for e in parsed.elements for n in element_nodes(e)}

    def uniq_id(name: str) -> str:
        while name.upper() in used_ids:
            name += "_"
        used_ids.add(name.upper())
        return name

    def uniq_node(name: str) -> str:
        while name in used_nodes:
            name += "_"
        used_nodes.add(name)
        return name

    freq = next((float(s.params["frequency"]) for s in three_phase_sources(parsed)), frequency)
    basis = getattr(parsed, "value_basis", "PEAK")
    exp = Expansion(flat=ParsedCircuit(), sources=three_phase_sources(parsed),
                    loads=three_phase_loads(parsed), meters=wattmeters(parsed), frequency=freq)
    elems: List[ParsedElement] = []
    for e in parsed.elements:
        t = e.element_type
        if t == ElementType.THREE_PHASE_SOURCE:
            p = e.params
            nodes = {"R": e.node_positive, "S": e.node_negative, "T": p["t_node"]}
            neutral = p["n_node"] if p["connection"] == "Y" else uniq_node(f"{e.id}_n")
            exp.src_neutral[e.id] = neutral
            exp.src_arms[e.id] = {}
            for ph, v in phase_voltages(e).items():
                aid = uniq_id(f"V_{e.id}_{ph}")
                exp.src_arms[e.id][ph] = aid
                amp = abs(v)
                elems.append(ParsedElement(
                    id=aid, element_type=ElementType.AC_SOURCE_SINE,
                    node_positive=nodes[ph], node_negative=neutral, value=amp,
                    params={"offset": 0.0, "amplitude": amp, "frequency": float(p["frequency"]),
                            "phase": math.degrees(cmath.phase(v)), "exact_rect": v,
                            "input_value": amp, "input_basis": basis}))
        elif t == ElementType.THREE_PHASE_LOAD:
            p = e.params
            nodes = {"R": e.node_positive, "S": e.node_negative, "T": p["t_node"]}
            for key, z in load_arms(e).items():
                if p["connection"] == "Y":
                    a, b = nodes[key], p["n_node"]
                else:
                    a, b = nodes[key[0]], nodes[key[1]]
                elems.extend(_arm_elements(e.id, key, z, a, b, freq, uniq_id, uniq_node))
        elif t == ElementType.WATTMETER:
            mid = uniq_id(f"V_{e.id}")
            exp.meter_ids[e.id] = mid
            if is_dc:
                elems.append(ParsedElement(id=mid, element_type=ElementType.DC_SOURCE,
                                           node_positive=e.node_positive,
                                           node_negative=e.node_negative, value=0.0))
            else:
                elems.append(ParsedElement(
                    id=mid, element_type=ElementType.AC_SOURCE_PHASOR,
                    node_positive=e.node_positive, node_negative=e.node_negative, value=0.0,
                    params={"amplitude": 0.0, "phase": 0.0, "input_value": 0.0, "input_basis": basis,
                            "phasor_complex": 0j}))
        else:
            elems.append(copy.copy(e))

    # Toprağa (düğüm 0) bağlı olmayan küme kalırsa lcapy çözemez: kümenin bir düğümü 0 sayılır
    parent: Dict[str, str] = {}

    def find(n: str) -> str:
        parent.setdefault(n, n)
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    find("0")
    for e in elems:
        ns = element_nodes(e)
        for n in ns[1:]:
            parent[find(ns[0])] = find(n)
    preferred = list(exp.src_neutral.values())
    clusters: Dict[str, List[str]] = {}
    for n in sorted({n for e in elems for n in element_nodes(e)}):
        clusters.setdefault(find(n), []).append(n)
    for root, members in clusters.items():
        if root == find("0"):
            continue
        pick = next((n for n in preferred if n in members), members[0])
        exp.rename[pick] = "0"
    if exp.rename:
        names = ", ".join(("Düğüm " + n) for n in exp.rename)
        exp.notes.append(
            f"Devre toprağa (GND) bağlı değil; çözüm için {names} referans (0 V) alındı. "
            "Gerilimler bu referansa göre verilir, akımlar ve güçler etkilenmez.")
        for e in elems:
            e.node_positive = exp.node(e.node_positive)
            e.node_negative = exp.node(e.node_negative)
            for key in ("t_node", "n_node", "v_pos", "v_neg", "s_pos", "s_neg", "pos2"):
                if key in e.params:
                    e.params[key] = exp.node(e.params[key])

    flat = ParsedCircuit(
        elements=elems, probes=list(parsed.probes),
        has_ground=parsed.has_ground or bool(exp.rename), raw_netlist=parsed.raw_netlist,
        warnings=list(parsed.warnings), errors=list(parsed.errors),
        node_positions=dict(parsed.node_positions), value_basis=basis)
    flat.node_count = len({n for e in elems for n in element_nodes(e)})
    exp.flat = flat
    return exp


# ═══════════════════════════════════════════════════════
#  ÇÖZÜLMÜŞ DEVREDEN OKUMA
# ═══════════════════════════════════════════════════════

def node_voltage(results, exp: Expansion, node: str) -> Optional[complex]:
    name = exp.node(node)
    if name == "0":
        return 0j
    nv = results.node_voltages.get(name)
    return None if nv is None else cx(nv.value)


def element_current(results, elem_id: str) -> Optional[complex]:
    ec = results.element_currents.get(elem_id)
    return None if ec is None else cx(ec.value)


def source_line_currents(results, exp: Expansion, src: ParsedElement) -> Optional[Dict[str, complex]]:
    """Kaynağın hatlara verdiği akımlar (kaynak içinden n+→n− akımın negatifi)."""
    out = {}
    for ph, aid in exp.src_arms[src.id].items():
        i = element_current(results, aid)
        if i is None:
            return None
        out[ph] = -i
    return out


def wattmeter_readings(results, exp: Expansion, is_rms: bool, is_dc: bool) -> List[Tuple[str, float, complex, complex]]:
    """[(id, P, V, I)] — I akım bobininde I+ → I−, V = V(V+) − V(V−)."""
    out = []
    for w in exp.meters:
        i = element_current(results, exp.meter_ids[w.id])
        vp = node_voltage(results, exp, w.params["v_pos"])
        vm = node_voltage(results, exp, w.params["v_neg"])
        if i is None or vp is None or vm is None:
            continue
        v = vp - vm
        if is_dc:
            p = (v * i).real
        else:
            p = (1.0 if is_rms else 0.5) * (v * i.conjugate()).real
        out.append((w.id, p, v, i))
    return out


# ═══════════════════════════════════════════════════════
#  ÜÇ FAZ ANALİZİ
# ═══════════════════════════════════════════════════════

@dataclass
class CompAnalysis:
    target: float
    applied: bool
    reason: Optional[str] = None
    phi1: float = 0.0
    phi2: float = 0.0
    q_c: float = 0.0
    q_per_arm: float = 0.0
    c_y: float = 0.0
    c_delta: float = 0.0
    i_before: float = 0.0           # hat akımı büyüklüğü (seçili gösterimde)
    i_after: float = 0.0
    pf_check: Optional[float] = None


@dataclass
class ThreePhaseAnalysis:
    src: ParsedElement
    load: Optional[ParsedElement]
    conn_s: str
    conn_l: Optional[str]
    sequence: str
    wires: int
    is_rms: bool
    f: float                                   # S = f·V·I*   (etkin: 1, tepe: ½)
    omega: float
    frequency: float
    uh: float
    uf: float
    v_ph: Dict[str, complex]
    v_line: Dict[str, complex]                 # kaynak uçlarında çözücünün gerilimleri R−S, S−T, T−R
    z: Optional[Dict[str, complex]]
    balanced: bool
    i_line: Dict[str, complex]
    i_n: Optional[complex]
    i_phase: Optional[Dict[str, complex]]
    s_arms: Dict[str, complex]
    p: float
    q: float
    s: float
    pf: float
    pf_type: str
    aron: Optional[Tuple[float, float, complex, complex]]      # P_A, P_B, V_RS, V_TS
    guided: bool
    reason: str = ""
    hand: Optional[dict] = None
    comp: Optional[CompAnalysis] = None
    meters: List[Tuple[str, float, complex, complex]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    others: List[str] = field(default_factory=list)
    v_nn: Optional[complex] = None

    @property
    def uh_rms(self) -> float:
        return self.uh if self.is_rms else self.uh / math.sqrt(2.0)

    def to_rms(self, x: float) -> float:
        return x if self.is_rms else x / math.sqrt(2.0)


def _close(a: complex, b: complex, tol: float = _TOL) -> bool:
    return abs(complex(a) - complex(b)) <= tol * max(abs(a), abs(b), 1e-12) + 1e-9


def _pf_type(p: float, q: float, s: float) -> str:
    if s <= 0 or abs(q) <= 1e-7 * s:
        return "unity"
    return "lagging" if q > 0 else "leading"


def derive_by_hand(v: Dict[str, complex], z: Dict[str, complex], conn_l: str, wires: int) -> dict:
    """Elle türetme (ders kitabı sırası): kol gerilimi → kol akımı → hat akımı."""
    if conn_l == "Y":
        if wires == 4:
            vnn = 0j
        else:
            ysum = sum(1 / z[k] for k in PHASES)
            vnn = sum(v[k] / z[k] for k in PHASES) / ysum
        arm_v = {k: v[k] - vnn for k in PHASES}
        i_line = {k: arm_v[k] / z[k] for k in PHASES}
        return {"vnn": vnn, "arm_v": arm_v, "i_line": i_line, "i_phase": None}
    vl = line_voltages(v)
    i_ph = {k: vl[k] / z[k] for k in vl}
    i_line = {"R": i_ph["RS"] - i_ph["TR"], "S": i_ph["ST"] - i_ph["RS"], "T": i_ph["TR"] - i_ph["ST"]}
    return {"vnn": None, "arm_v": vl, "i_line": i_line, "i_phase": i_ph}


def _wires(parsed: ParsedCircuit, src: ParsedElement, load: Optional[ParsedElement]) -> int:
    """4: yıldız kaynağın nötr ucu, yıldız yükün nötr ucuna (ya da devrenin başka yerine) bağlı."""
    if src.params["connection"] != "Y":
        return 3
    n_s = src.params["n_node"]
    others = [e for e in parsed.elements if e is not src and e is not load]
    if load is not None and load.params["connection"] == "Y":
        n_l = load.params["n_node"]
        parent: Dict[str, str] = {}

        def find(n: str) -> str:
            parent.setdefault(n, n)
            while parent[n] != n:
                parent[n] = parent[parent[n]]
                n = parent[n]
            return n

        for e in others:
            if e.element_type == ElementType.THREE_PHASE_SOURCE or e.element_type == ElementType.THREE_PHASE_LOAD:
                continue
            ns = _effective_nodes(e)
            for n in ns[1:]:
                parent[find(ns[0])] = find(n)
        return 4 if find(n_s) == find(n_l) else 3
    return 4 if any(n_s in _effective_nodes(e) for e in others) else 3


def analyze_three_phase(
    parsed: ParsedCircuit, exp: Expansion, results, frequency: float,
    power_factor_target: Optional[float] = None,
    verify: Optional[Callable[[List[ParsedElement]], Optional[object]]] = None,
) -> Optional[ThreePhaseAnalysis]:
    """
    Çözülmüş (açılmış) devreden üç faz büyüklükleri. İlk üç fazlı kaynak esas alınır.
    Kaynak yoksa ya da akımlar okunamadıysa None.
    `verify(ek_elemanlar)` kompanzasyonu çözücüyle doğrulamak için kondansatörlü çözümü döndürür.
    """
    if not exp.sources:
        return None
    src = exp.sources[0]
    load = exp.loads[0] if len(exp.loads) == 1 else None
    is_rms = getattr(parsed, "value_basis", "PEAK") == "RMS"
    i_line = source_line_currents(results, exp, src)
    if i_line is None:
        return None
    uh, uf = source_levels(src)
    v_ph = phase_voltages(src)
    omega = 2 * math.pi * frequency
    f = 1.0 if is_rms else 0.5
    wires = _wires(parsed, src, load)
    conn_l = load.params["connection"] if load is not None else None
    z = load_arms(load) if load is not None else None

    # Çözücünün kaynak uçlarındaki gerilimleri (hat gerilimleri)
    nv = {ph: node_voltage(results, exp, n)
          for ph, n in (("R", src.node_positive), ("S", src.node_negative), ("T", src.params["t_node"]))}
    v_line = ({"RS": nv["R"] - nv["S"], "ST": nv["S"] - nv["T"], "TR": nv["T"] - nv["R"]}
              if all(x is not None for x in nv.values()) else line_voltages(v_ph))

    s_arms = {ph: f * v_ph[ph] * i_line[ph].conjugate() for ph in PHASES}
    s_tot = sum(s_arms.values())
    p, q = s_tot.real, s_tot.imag
    s = abs(s_tot)
    if abs(q) <= 1e-9 * s:
        q = 0.0                     # sayısal gürültü
    if abs(p) <= 1e-9 * s:
        p = 0.0
    pf = p / s if s > 0 else 1.0

    i_n = sum(i_line.values()) if wires == 4 else None
    if i_n is not None and abs(i_n) <= 1e-6 * max(abs(x) for x in i_line.values()):
        i_n = 0j
    i_phase = None
    if load is not None and conn_l == "D":
        i_phase = {}
        for key, a, b in DELTA_ARMS:
            va, vb = node_voltage(results, exp, _node_of(load, a)), node_voltage(results, exp, _node_of(load, b))
            if va is None or vb is None:
                i_phase = None
                break
            i_phase[key] = (va - vb) / z[key]

    aron = None
    if wires == 3:
        v_rs = v_line["RS"]
        v_ts = -v_line["ST"]
        pa = f * (v_rs * i_line["R"].conjugate()).real
        pb = f * (v_ts * i_line["T"].conjugate()).real
        if abs(pa) <= 1e-9 * s:
            pa = 0.0
        if abs(pb) <= 1e-9 * s:
            pb = 0.0
        aron = (pa, pb, v_rs, v_ts)

    balanced = False
    if z is not None:
        zs = list(z.values())
        balanced = all(abs(zs[0] - x) <= 1e-9 * max(abs(zs[0]), 1e-300) for x in zs[1:])

    an = ThreePhaseAnalysis(
        src=src, load=load, conn_s=src.params["connection"], conn_l=conn_l,
        sequence=src.params["sequence"], wires=wires, is_rms=is_rms, f=f, omega=omega,
        frequency=frequency, uh=uh, uf=uf, v_ph=v_ph, v_line=v_line, z=z, balanced=balanced,
        i_line=i_line, i_n=i_n, i_phase=i_phase, s_arms=s_arms, p=p, q=q, s=s, pf=pf,
        pf_type=_pf_type(p, q, s), aron=aron, guided=False, notes=list(exp.notes))
    an.meters = wattmeter_readings(results, exp, is_rms, False)

    # ── Anlatım kalıbına uyuyor mu? (tek kaynak, tek yük, başka eleman yok) ──
    reason = ""
    others = [e for e in parsed.elements
              if e.element_type not in (ElementType.THREE_PHASE_SOURCE, ElementType.THREE_PHASE_LOAD,
                                        ElementType.WATTMETER)]
    an.others = [e.id for e in others]
    if len(exp.sources) > 1:
        reason = "Devrede birden fazla üç fazlı kaynak var"
    elif load is None:
        reason = ("Devrede üç fazlı yük yok" if not exp.loads
                  else "Devrede birden fazla üç fazlı yük var")
    elif others:
        reason = ("Devrede kaynak ve yükün dışında başka elemanlar da var "
                  f"({', '.join(an.others)}), örneğin hat empedansı")
    else:
        hand = derive_by_hand(v_ph, z, conn_l, wires)
        an.hand = hand
        an.v_nn = hand["vnn"]
        ok = all(_close(hand["i_line"][k], i_line[k]) for k in PHASES)
        if ok and conn_l == "D" and i_phase is not None:
            ok = all(_close(hand["i_phase"][k], i_phase[k]) for k in i_phase)
        if ok:
            an.guided = True
        else:
            reason = "Elle türetilen akımlar çözücünün sonuçlarıyla uyuşmadı"
    an.reason = reason

    if power_factor_target is not None:
        an.comp = _compensation(an, power_factor_target, verify, exp, results)
    return an


def _node_of(load: ParsedElement, ph: str) -> str:
    return {"R": load.node_positive, "S": load.node_negative, "T": load.params["t_node"]}[ph]


def _compensation(an: ThreePhaseAnalysis, target: float, verify, exp: Expansion, results) -> CompAnalysis:
    comp = CompAnalysis(target=target, applied=False)
    if not an.guided or not an.balanced:
        comp.reason = ("Kompanzasyon yalnızca dengeli yükte uygulanır; dengesiz ya da çözümü "
                       "adım adım gösterilemeyen devrede kondansatör hesabı yapılmaz.")
        return comp
    if an.pf_type == "leading":
        comp.reason = "Yük ileri (kapasitif) güç katsayılı; kondansatör eklemek güç katsayısını daha da bozar."
        return comp
    if an.pf >= target - 1e-12:
        comp.reason = (f"Mevcut güç katsayısı (cos φ = {an.pf:.4g}) zaten hedefe ({target:.4g}) eşit "
                       "ya da hedeften büyük; kompanzasyon gerekmez.")
        return comp
    comp.phi1 = math.acos(max(min(an.pf, 1.0), -1.0))
    comp.phi2 = math.acos(target)
    comp.q_c = an.p * (math.tan(comp.phi1) - math.tan(comp.phi2))
    comp.q_per_arm = comp.q_c / 3.0
    uh = an.uh_rms
    comp.c_y = comp.q_c / (an.omega * uh * uh)
    comp.c_delta = comp.c_y / 3.0
    comp.i_before = abs(an.i_line["R"])
    scale = 1.0 if an.is_rms else math.sqrt(2.0)
    comp.i_after = an.p / (SQRT3 * uh * target) * scale
    if verify is None:
        comp.reason = "Çözücüyle doğrulama yapılamadı."
        return comp

    r, s_, t_ = (an.load.node_positive, an.load.node_negative, an.load.params["t_node"])
    r, s_, t_ = exp.node(r), exp.node(s_), exp.node(t_)
    star = "Cy_n"
    caps_y = [ParsedElement(id=f"C_comp_{ph}", element_type=ElementType.CAPACITOR, node_positive=n,
                            node_negative=star, value=comp.c_y) for ph, n in zip(PHASES, (r, s_, t_))]
    caps_d = [ParsedElement(id=f"C_comp_{k}", element_type=ElementType.CAPACITOR, node_positive=a,
                            node_negative=b, value=comp.c_delta)
              for k, a, b in ((k, {"R": r, "S": s_, "T": t_}[x], {"R": r, "S": s_, "T": t_}[y])
                              for k, x, y in DELTA_ARMS)]
    checks = []
    for caps in (caps_y, caps_d):
        r2 = verify(caps)
        cur = source_line_currents(r2, exp, an.src) if r2 is not None else None
        if cur is None:
            comp.reason = "Çözücüyle doğrulama yapılamadı."
            return comp
        tot = sum(an.f * an.v_ph[ph] * cur[ph].conjugate() for ph in PHASES)
        checks.append((tot.real / abs(tot) if abs(tot) > 0 else 1.0, abs(cur["R"])))
    comp.pf_check = checks[0][0]
    if all(abs(c[0] - target) <= 1e-6 for c in checks) and abs(checks[0][1] - comp.i_after) <= 1e-6 * comp.i_after:
        comp.applied = True
    else:
        comp.reason = "Kondansatörlü devre çözücüyle doğrulanamadı; hesaplanan değerler gösterilmiyor."
    return comp
