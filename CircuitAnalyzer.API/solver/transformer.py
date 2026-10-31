"""
CircuitAnalyzer API — Transformatör (Faz 3 / v1.5)

Kapsam: bir transformatör (ideal ya da kuplajlı) ve primer tarafta tek bir bağımsız AC
gerilim kaynağı içeren devre. Sayılar lcapy'den gelir (circuit_solver); bu modül yalnızca
ANLATIM için elle türetmeyi hazırlar ve çözücü sonuçlarıyla karşılaştırır:

    İdeal:    Z₂ (sekonderdeki yük) → Z₁ = Z₂/a² → primer toplam Z → I₁ = V/Z_top → V₁ = I₁·Z₁
              → V₂ = a·V₁, I₂ = I₁/a
    Kuplajlı: Z_seri (primer) ve Z_yük (sekonder) → iki çevre denklemi
              (Z_seri + jωL₁)·I₁ + jωM·I₂ = E,   jωM·I₁ + (Z_yük + jωL₂)·I₂ = 0   (Cramer 2×2)

Türetme çözücüyle uyuşmazsa ya da devre bu kalıba girmiyorsa `reason` doludur: anlatım kısa
kalır (çözücü sonuçları + sebep), sayılar yine doğrudur.

Gerilim sembolü V'dir (kitaplardaki U gösterimi anlatımda bir notla belirtilir).
"""

import cmath
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from explainer.formatting import eng, rect
from parser.netlist_parser import (
    ALL_SOURCES, CURRENT_SOURCES, DEPENDENT_SOURCES, DC_SOURCES, PHASOR_SOURCES, SINE_SOURCES,
    VOLTAGE_SOURCES, ElementType, ParsedCircuit, ParsedElement, element_nodes, transformers,
)

_TOL = 1e-6      # elle türetme ile çözücü arasında izin verilen bağıl fark


def source_phasor(e: ParsedElement) -> complex:
    """AC kaynağın fazörü (seçili gösterimde)."""
    return cmath.rect(float(e.params.get("amplitude", e.value)),
                      math.radians(float(e.params.get("phase", 0.0))))


def passive_impedance(e: ParsedElement, omega: Optional[float]) -> Optional[complex]:
    """Pasif elemanın AC empedansı; frekans yoksa ve eleman reaktifse None."""
    t = e.element_type
    if t == ElementType.RESISTOR:
        return complex(e.value)
    if t == ElementType.IMPEDANCE:
        return complex(e.params.get("impedance", complex(e.value)))
    if omega is None or omega <= 0:
        return None
    if t == ElementType.CAPACITOR:
        return 1 / (1j * omega * e.value)
    if t == ElementType.INDUCTOR:
        return 1j * omega * e.value
    return None


def passive_label(e: ParsedElement) -> str:
    """Denklemdeki adı: direnç R1, empedans Z1, C/L için Z_C1."""
    if e.element_type in (ElementType.RESISTOR, ElementType.IMPEDANCE):
        return e.id
    return f"Z_{e.id}"


def z_text(z: complex) -> str:
    """Empedans: gerçekse '40 Ω', değilse '30 + j40 Ω'."""
    z = complex(z)
    return eng(z.real, "Ω") if abs(z.imag) <= 1e-9 * max(abs(z), 1e-15) else rect(z, "Ω")


# ═══════════════════════════════════════════════════════
#  İKİ UÇLU SERİ/PARALEL İNDİRGEME
# ═══════════════════════════════════════════════════════

def reduce_two_terminal(
    branches: List[Tuple[str, str, str, complex]], pin_a: str, pin_b: str,
) -> Optional[Tuple[complex, List[str]]]:
    """
    Pasif kolları (ad, düğüm1, düğüm2, Z) pin_a–pin_b arasında tek empedansa indirger.
    Yalnızca seri ve paralel birleştirme kullanılır; olmazsa None.
    Dönüş: (Z, adım metinleri) — her metin bir seri/paralel birleştirmedir.
    """
    br = [list(b) for b in branches if b[1] != b[2]]       # iki ucu aynı düğüm: akım taşımaz
    if pin_a == pin_b:
        return 0j, []
    steps: List[str] = []
    counters = {"s": 0, "p": 0}

    def new_name(kind: str, z1: complex, z2: complex) -> str:
        counters[kind] += 1
        real = abs(z1.imag) < 1e-12 and abs(z2.imag) < 1e-12
        return f"{'R' if real else 'Z'}_{kind}{counters[kind]}"

    for _ in range(100):
        if len(br) == 1 and {br[0][1], br[0][2]} == {pin_a, pin_b}:
            return br[0][3], steps
        changed = False
        # Paralel
        for i in range(len(br)):
            for j in range(i + 1, len(br)):
                if {br[i][1], br[i][2]} == {br[j][1], br[j][2]}:
                    z1, z2 = br[i][3], br[j][3]
                    if abs(z1 + z2) < 1e-15:
                        return None
                    z = z1 * z2 / (z1 + z2)
                    name = new_name("p", z1, z2)
                    steps.append(f"{name} = ({br[i][0]} · {br[j][0]}) / ({br[i][0]} + {br[j][0]}) "
                                 f"= {z_text(z)}")
                    node_a, node_b = br[i][1], br[i][2]
                    br = [b for k, b in enumerate(br) if k not in (i, j)] + [[name, node_a, node_b, z]]
                    changed = True
                    break
            if changed:
                break
        if changed:
            continue
        # Seri: pin olmayan, tam iki koluna bağlı düğüm
        nodes = sorted({n for b in br for n in (b[1], b[2])} - {pin_a, pin_b})
        for node in nodes:
            inc = [b for b in br if node in (b[1], b[2])]
            if len(inc) != 2:
                continue
            b1, b2 = inc
            end1 = b1[2] if b1[1] == node else b1[1]
            end2 = b2[2] if b2[1] == node else b2[1]
            if end1 == node or end2 == node:
                continue
            z = b1[3] + b2[3]
            name = new_name("s", b1[3], b2[3])
            steps.append(f"{name} = {b1[0]} + {b2[0]} = {z_text(z)}")
            br = [b for b in br if b is not b1 and b is not b2] + [[name, end1, end2, z]]
            changed = True
            break
        if not changed:
            return None
    return None


# ═══════════════════════════════════════════════════════
#  ANALİZ
# ═══════════════════════════════════════════════════════

@dataclass
class TransformerAnalysis:
    t: ParsedElement
    kind: str                       # "ideal" | "coupled"
    omega: Optional[float]
    is_rms: bool
    v1: complex                     # V(p+) − V(p−)
    v2: complex                     # V(s+) − V(s−)
    i1: complex                     # p+ ucundan giren akım
    i2: complex                     # ideal: s+ ucundan ÇIKAN; kuplajlı: s+ ucundan GİREN
    floating: bool = False
    ties: List[str] = field(default_factory=list)
    reason: Optional[str] = None    # None değilse kısa anlatım (sebep)
    # ── Rehberli türetme (reason None iken dolu) ──
    source: Optional[ParsedElement] = None
    v_s: complex = 0j               # kaynak fazörü
    sigma: int = 1                  # I₁ = σ · (kaynağın verdiği akım)
    primary: List[ParsedElement] = field(default_factory=list)
    secondary: List[ParsedElement] = field(default_factory=list)
    z2: complex = 0j                # sekonderdeki yük empedansı (Z_yük)
    z2_steps: List[str] = field(default_factory=list)
    z_ser: complex = 0j             # primer seri empedans (kaynak ile primer sargı arası)
    z_ser_steps: List[str] = field(default_factory=list)
    z1: complex = 0j                # ideal: yansıyan empedans Z₂/a²
    z_top: complex = 0j             # ideal: kaynağın gördüğü toplam empedans
    top_steps: List[str] = field(default_factory=list)

    @property
    def a(self) -> float:
        return float(self.t.params["a"])

    @property
    def m(self) -> float:
        return float(self.t.params["m"])

    @property
    def guided(self) -> bool:
        return self.reason is None


def _close(a: complex, b: complex, tol: float = _TOL) -> bool:
    return abs(complex(a) - complex(b)) <= tol * max(abs(a), abs(b), 1e-9) + 1e-12


def _partition(parsed: ParsedCircuit, t: ParsedElement):
    """
    Transformatör "kırık" sayılıp GND (düğüm 0) bağlayıcı olmadan devre iki tarafa ayrılır.
    Dönüş: (primer elemanlar, sekonder elemanlar, sebep|None).
    """
    parent: Dict[str, str] = {}

    def find(n: str) -> str:
        parent.setdefault(n, n)
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    others = [e for e in parsed.elements if e.element_type != ElementType.TRANSFORMER]
    for e in others:
        ns = [n for n in element_nodes(e) if n != "0"]
        for n in ns[1:]:
            parent[find(n)] = find(ns[0])

    def root_of(nodes) -> Optional[str]:
        roots = {find(n) for n in nodes if n != "0"}
        if len(roots) == 1:
            return roots.pop()
        return None

    p_nodes = (t.node_positive, t.node_negative)
    s_nodes = (t.params["s_pos"], t.params["s_neg"])
    if len({find(n) for n in p_nodes if n != "0"}) > 1 or len({find(n) for n in s_nodes if n != "0"}) > 1:
        return [], [], ("primer (ya da sekonder) uçları devrenin farklı kısımlarına bağlı olduğundan "
                        "devre tek çevre olarak indirgenemiyor")
    p_root, s_root = root_of(p_nodes), root_of(s_nodes)
    if p_root is None or s_root is None:
        return [], [], "sargı uçlarından biri doğrudan toprağa bağlı olduğundan taraflar ayrılamıyor"
    if p_root == s_root:
        return [], [], ("primer ve sekonder taraf transformatör dışında da birbirine bağlı "
                        "(ortak düğüm ya da başka bir yol)")
    primary: List[ParsedElement] = []
    secondary: List[ParsedElement] = []
    for e in others:
        r = root_of(element_nodes(e))
        if r == p_root:
            primary.append(e)
        elif r == s_root:
            secondary.append(e)
        elif r is not None:
            return [], [], "devrede transformatörle bağlantısı olmayan başka bir kısım da var"
    return primary, secondary, None


def analyze_transformer(
    parsed: ParsedCircuit, omega: Optional[float], is_rms: bool,
    raw_currents: Dict[str, complex], v1: complex, v2: complex, i1: complex, i2: complex,
    ties: List[str],
) -> TransformerAnalysis:
    """Çözücü sonuçlarından (v1, v2, i1, i2) ve devreden anlatım türetmesini hazırlar."""
    ts = transformers(parsed)
    t = ts[0]
    an = TransformerAnalysis(
        t=t, kind="ideal" if t.params["kind"] == "IDEAL" else "coupled", omega=omega,
        is_rms=is_rms, v1=v1, v2=v2, i1=i1, i2=i2,
        floating=bool(ties), ties=list(ties),
    )

    def fail(msg: str) -> TransformerAnalysis:
        an.reason = msg
        return an

    if len(ts) > 1:
        return fail(f"devrede {len(ts)} transformatör var; adım adım anlatım tek transformatörlü "
                    "devreler için hazırlandı")
    others = [e for e in parsed.elements if e.element_type != ElementType.TRANSFORMER]
    if any(e.element_type in DEPENDENT_SOURCES for e in others):
        return fail("devrede bağımlı kaynak var")
    if any(e.element_type in CURRENT_SOURCES for e in others):
        return fail("devrede akım kaynağı var; adım adım anlatım gerilim kaynağıyla beslenen "
                    "devreler için hazırlandı")
    sources = [e for e in others if e.element_type in ALL_SOURCES]
    ac_sources = [e for e in sources if e.element_type in SINE_SOURCES + PHASOR_SOURCES]
    if len(ac_sources) != 1 or len(sources) != len(ac_sources):
        return fail("adım adım anlatım için devrede tam olarak bir bağımsız AC kaynak olmalı")
    src = ac_sources[0]

    primary, secondary, why = _partition(parsed, t)
    if why:
        return fail(why)
    if src not in primary:
        return fail("bağımsız kaynak primer tarafta değil (sekonderde kaynak var)")
    if omega is None and any(e.element_type in (ElementType.CAPACITOR, ElementType.INDUCTOR)
                             for e in primary + secondary):
        return fail("frekans bilinmediğinden empedanslar hesaplanamıyor")
    if an.kind == "coupled" and omega is None:
        return fail("frekans bilinmiyor")

    def branches(elems: List[ParsedElement]):
        out = []
        for e in elems:
            if e.element_type in ALL_SOURCES:
                continue
            z = passive_impedance(e, omega)
            if z is None:
                return None
            out.append((passive_label(e), e.node_positive, e.node_negative, z))
        return out

    sec_br = branches(secondary)
    pri_br = branches(primary)
    if sec_br is None or pri_br is None:
        return fail("devrede empedansı hesaplanamayan bir eleman var")

    s_pos, s_neg = t.params["s_pos"], t.params["s_neg"]
    red2 = reduce_two_terminal(sec_br, s_pos, s_neg) if sec_br else None
    if red2 is None:
        return fail("sekonder taraf seri/paralel birleştirmelerle tek bir yük empedansına indirgenemiyor")
    an.z2, an.z2_steps = red2

    # Primer: transformatör uçları kısa devre sayılarak kaynağın gördüğü seri empedans
    p_pos, p_neg = t.node_positive, t.node_negative
    pins = (src.node_positive, src.node_negative)

    def merge(node: str) -> str:
        return p_pos if node == p_neg else node

    short_br = [(n, merge(a), merge(b), z) for n, a, b, z in pri_br]
    red_ser = reduce_two_terminal(short_br, merge(pins[0]), merge(pins[1]))
    if red_ser is None:
        return fail("primer taraf seri/paralel birleştirmelerle tek bir seri empedansa indirgenemiyor")
    an.z_ser, an.z_ser_steps = red_ser

    an.source = src
    an.v_s = source_phasor(src)
    an.primary, an.secondary = primary, secondary
    i_deliv = -complex(raw_currents.get(src.id, 0))      # kaynağın devreye verdiği akım
    if _close(i1, i_deliv):
        an.sigma = 1
    elif _close(i1, -i_deliv):
        an.sigma = -1
    else:
        return fail("primer tarafta transformatöre paralel bir kol olduğundan kaynak akımı I₁'den farklı")
    e_drive = an.sigma * an.v_s

    if an.kind == "ideal":
        a = an.a
        an.z1 = an.z2 / (a * a)
        top_br = pri_br + [("Z₁", p_pos, p_neg, an.z1)]
        red_top = reduce_two_terminal(top_br, pins[0], pins[1])
        if red_top is None:
            return fail("primer taraf yansıyan empedansla birlikte tek empedansa indirgenemiyor")
        an.z_top, an.top_steps = red_top
        if abs(an.z_top) < 1e-15:
            return fail("kaynağın gördüğü toplam empedans sıfır")
        i1_calc = e_drive / an.z_top
        v1_calc = i1_calc * an.z1
        v2_calc = a * v1_calc
        i2_calc = i1_calc / a
        ok = (_close(i1_calc, i1) and _close(v1_calc, v1) and _close(v2_calc, v2)
              and _close(i2_calc, i2))
        if not ok:
            return fail("elle türetilen değerler çözücüyle uyuşmadı; yalnızca çözücü sonuçları gösteriliyor")
    else:
        zm = 1j * omega * an.m
        z11 = an.z_ser + 1j * omega * float(t.params["l1"])
        z22 = an.z2 + 1j * omega * float(t.params["l2"])
        det = z11 * z22 - zm * zm
        if abs(det) < 1e-15:
            return fail("çevre denklemlerinin determinantı sıfır")
        i1_calc = e_drive * z22 / det
        i2_calc = -e_drive * zm / det
        ok = _close(i1_calc, i1) and _close(i2_calc, i2)
        if not ok:
            return fail("elle türetilen değerler çözücüyle uyuşmadı; yalnızca çözücü sonuçları gösteriliyor")
    return an
