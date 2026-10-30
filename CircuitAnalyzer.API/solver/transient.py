"""
CircuitAnalyzer API — Birinci Dereceden DC Geçici Durum (Faz 2)

Kapsam: anahtarlı, tam olarak BİR kondansatör (RC) ya da BİR bobin (RL) içeren
DC devreler. Bütün anahtarlar t = 0 anında konum değiştirir.

Yöntem (kitaptaki sıra):
    t = 0⁻   t < 0 devresi uzun süre kaldı → DC kararlı hâl (C açık, L kısa)
    t = 0⁺   x(0⁺) = x(0⁻)  (V_C ve I_L süreklidir)
    t → ∞    t > 0 devresi DC kararlı hâl
    τ        t > 0 devresinde C/L'nin gördüğü R_th: τ = R_th·C  ya da  τ = L/R_th
    x(t)     = x(∞) + [x(0) − x(∞)]·e^(−t/τ)

Bu modül sayıları KENDİ küçük düğüm-gerilimi çözücüsüyle (numpy) bulur; çünkü
t < 0 devresi sıkça "yüzen" düğümler içerir (açık anahtar yüzünden bir kısım
GND'ye bağlı değildir) ve genel çözücü bu durumda tekil sistem hatası verir.
Sonuçlar bağımsız olarak lcapy'nin Laplace çözümüyle doğrulanır
(verify_with_lcapy); uyuşmazsa geçici durum anlatımı verilmez.
"""

import math
from copy import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from parser.netlist_parser import (
    CURRENT_SOURCES, DEPENDENT_SOURCES, PHASOR_SOURCES, SINE_SOURCES,
    ElementType, ParsedCircuit, ParsedElement,
    circuit_at_time, has_switches, to_lcapy_netlist,
)

_REL = 1e-6          # bağıl doğrulama toleransı
_TINY = 1e-12        # mutlak taban (gerilim / akım / direnç için)


class TransientNotApplicable(Exception):
    """Geçici durum bu devre için uygulanamaz; mesaj öğrenciye gösterilen Türkçe gerekçedir."""


# ═══════════════════════════════════════════════════════
#  KÜÇÜK DC ÇÖZÜCÜ (R, V, I, C, L)
# ═══════════════════════════════════════════════════════

@dataclass
class DcSolution:
    v: Dict[str, float]                      # düğüm gerilimleri (GND = 0)
    i: Dict[str, float]                      # eleman akımları (n+ → n−, eleman içinden)
    floating_refs: List[str] = field(default_factory=list)   # GND'ye bağlı olmayan kümelerin referans düğümü
    floating_nodes: set = field(default_factory=set)         # o kümelerdeki tüm düğümler (mutlak gerilimi anlamsız)

    def vd(self, n1: str, n2: str) -> float:
        return self.v.get(n1, 0.0) - self.v.get(n2, 0.0)


def _branches(elements: List[ParsedElement], overrides: Dict[str, Tuple[str, float]]):
    """
    Elemanları (id, tür, n1, n2, değer) dallarına çevirir.
    tür: 'R' direnç, 'V' gerilim kaynağı (n1 = +), 'I' akım kaynağı (kaynak içinden n1 → n2).
    DC'de C açık (dal yok), L kısa (0 V'luk 'V' dalı); overrides: {id: ('v'|'i', değer)}.
    """
    out = []
    for e in elements:
        t = e.element_type
        ov = overrides.get(e.id)
        if t == ElementType.RESISTOR:
            if e.value <= 0:
                raise TransientNotApplicable(
                    f"{e.id} direnci sıfır ya da negatif; geçici durum hesaplanamaz.")
            out.append((e.id, "R", e.node_positive, e.node_negative, e.value))
        elif t == ElementType.DC_SOURCE:
            out.append((e.id, "V", e.node_positive, e.node_negative, e.value))
        elif t == ElementType.CURRENT_DC:
            out.append((e.id, "I", e.node_positive, e.node_negative, e.value))
        elif t in (ElementType.CAPACITOR, ElementType.INDUCTOR):
            if ov is not None:
                out.append((e.id, ov[0].upper(), e.node_positive, e.node_negative, ov[1]))
            elif t == ElementType.INDUCTOR:
                out.append((e.id, "V", e.node_positive, e.node_negative, 0.0))
            # DC'de kondansatör açık devre: dal yok
        else:
            raise TransientNotApplicable("Devrede geçici durum için desteklenmeyen bir eleman var.")
    return out


def _components(branches, nodes, include_current: bool = False) -> Dict[str, str]:
    """Akım iletebilen dallarla (R, V; istenirse I) bağlı düğüm kümeleri (union-find temsilcisi)."""
    parent = {n: n for n in nodes}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for _, kind, a, b, _ in branches:
        if kind in ("R", "V") or (include_current and kind == "I"):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
    return {n: find(n) for n in nodes}


def dc_solve(elements: List[ParsedElement],
             overrides: Optional[Dict[str, Tuple[str, float]]] = None) -> DcSolution:
    """
    DC düğüm gerilimleri ve eleman akımları. GND'ye hiçbir iletken yolla bağlı
    olmayan ("yüzen") kümelerde en küçük numaralı düğüm 0 V alınır; kümenin içindeki
    gerilim farkları yine de doğrudur. Çözülemezse TransientNotApplicable.
    """
    overrides = overrides or {}
    branches = _branches(elements, overrides)
    nodes = sorted({n for e in elements for n in (e.node_positive, e.node_negative)} | {"0"},
                   key=lambda x: (x != "0", len(x), x))
    if not any(e.node_positive == "0" or e.node_negative == "0" for e in elements):
        raise TransientNotApplicable("Devrede GND (Düğüm 0) referansı yok.")

    comp = _components(branches, nodes)
    ground = comp["0"]
    refs = ["0"]
    floating: List[str] = []
    floating_all: set = set()
    for rep in sorted({c for c in comp.values() if c != ground}):
        members = sorted((n for n in nodes if comp[n] == rep), key=lambda x: (len(x), x))
        floating.append(members[0])
        floating_all.update(members)
        # Yüzen kümeye net akım basan kaynak varsa KCL sağlanamaz
        net = 0.0
        for _, kind, a, b, val in branches:
            if kind == "I":
                if comp[a] == rep and comp[b] != rep:
                    net -= val
                if comp[b] == rep and comp[a] != rep:
                    net += val
        if abs(net) > _TINY:
            raise TransientNotApplicable(
                "Bir akım kaynağı GND'ye bağlı olmayan bir kola akım basıyor; "
                "devre denklemleri çözülemiyor.")
    refs += floating

    unknown_nodes = [n for n in nodes if n not in refs]
    vbranches = [br for br in branches if br[1] == "V"]
    idx = {n: k for k, n in enumerate(unknown_nodes)}
    size = len(unknown_nodes) + len(vbranches)
    A = np.zeros((size, size))
    rhs = np.zeros(size)

    def add(row_node, col_node, val):
        if row_node in idx and col_node in idx:
            A[idx[row_node], idx[col_node]] += val

    for _, kind, a, b, val in branches:
        if kind == "R":
            g = 1.0 / val
            add(a, a, g); add(b, b, g); add(a, b, -g); add(b, a, -g)
        elif kind == "I":
            if a in idx:
                rhs[idx[a]] -= val
            if b in idx:
                rhs[idx[b]] += val
    for k, (_, _, a, b, val) in enumerate(vbranches):
        col = len(unknown_nodes) + k
        if a in idx:
            A[idx[a], col] += 1.0
            A[col, idx[a]] += 1.0
        if b in idx:
            A[idx[b], col] -= 1.0
            A[col, idx[b]] -= 1.0
        rhs[col] = val

    x = np.zeros(0)
    if size:
        try:
            if np.linalg.cond(A) > 1e13:
                raise np.linalg.LinAlgError("singular")
            x = np.linalg.solve(A, rhs)
        except np.linalg.LinAlgError:
            raise TransientNotApplicable(
                "Devre denklemleri çözülemiyor (tekil sistem): örneğin bir gerilim kaynağı "
                "kısa devre edilmiş ya da iki gerilim kaynağı doğrudan paralel kalmış olabilir.")
        if not np.all(np.isfinite(x)):
            raise TransientNotApplicable("Devre denklemleri çözülemiyor.")

    volt = {n: 0.0 for n in nodes}
    for n, k in idx.items():
        volt[n] = float(x[k])
    cur: Dict[str, float] = {}
    for bid, kind, a, b, val in branches:
        if kind == "R":
            cur[bid] = (volt[a] - volt[b]) / val
        elif kind == "I":
            cur[bid] = val
    for k, (bid, _, _, _, _) in enumerate(vbranches):
        cur[bid] = float(x[len(unknown_nodes) + k])
    return DcSolution(v=volt, i=cur, floating_refs=floating, floating_nodes=floating_all)


def dc_connected(elements: List[ParsedElement], n1: str, n2: str) -> bool:
    """n1 ile n2 arasında DC'de iletken (R, V, kısa devre L) bir yol var mı? (C açık, I açık.)"""
    branches = _branches(elements, {})
    nodes = {n for e in elements for n in (e.node_positive, e.node_negative)} | {n1, n2, "0"}
    comp = _components(branches, nodes)
    return comp[n1] == comp[n2]


# ═══════════════════════════════════════════════════════
#  ÇÖZÜM YAPISI
# ═══════════════════════════════════════════════════════

@dataclass
class TransientQuantity:
    id: str
    label: str
    unit: str
    before: float     # x(0⁻)
    start: float      # x(0⁺)
    final: float      # x(∞)


@dataclass
class TransientAnalysis:
    storage: ParsedElement           # t>0 devresindeki C / L elemanı (düğüm sırası netlistteki gibi)
    storage_before: ParsedElement    # t<0 devresindeki aynı eleman
    kind: str                        # "C" | "L"
    before_circuit: ParsedCircuit    # t < 0 devresi (anahtarlar çözülmüş)
    after_circuit: ParsedCircuit     # t > 0 devresi
    after_without_storage: ParsedCircuit   # t>0 devresi, C/L çıkarılmış (port = C/L uçları)
    port: Tuple[str, str]            # t>0 devresinde C/L'nin uç düğümleri
    port_before: Tuple[str, str]     # t<0 devresinde C/L'nin uç düğümleri
    dc_before: DcSolution
    dc_final: DcSolution
    uncharged: bool                  # t<0'da C bir kaynağa bağlı değil → boş kabul edildi
    r_th: float
    tau: float
    x_before: float                  # V_C(0⁻) ya da I_L(0⁻)
    x_start: float                   # x(0⁺) (süreklilik: = x_before)
    x_final: float                   # V_C(∞) ya da I_L(∞)
    other_start: float               # I_C(0⁺) ya da V_L(0⁺)
    quantities: List[TransientQuantity]
    switches: List[ParsedElement]
    parsed: Optional[ParsedCircuit] = None   # anahtarlı özgün devre
    verified: bool = False

    @property
    def value(self) -> float:
        return self.storage.value

    @property
    def x_label(self) -> str:
        return f"V_{self.storage.id}" if self.kind == "C" else f"I_{self.storage.id}"

    @property
    def other_label(self) -> str:
        return f"I_{self.storage.id}" if self.kind == "C" else f"V_{self.storage.id}"

    @property
    def unit(self) -> str:
        return "V" if self.kind == "C" else "A"

    def x_at(self, t: float) -> float:
        return self.x_final + (self.x_start - self.x_final) * math.exp(-t / self.tau)

    def other_at(self, t: float) -> float:
        return self.other_final + (self.other_start - self.other_final) * math.exp(-t / self.tau)

    @property
    def other_final(self) -> float:
        return 0.0     # C akımı ve L gerilimi DC kararlı hâlde sıfırdır


# ═══════════════════════════════════════════════════════
#  UYGULANABİLİRLİK DENETİMİ
# ═══════════════════════════════════════════════════════

def check_applicable(parsed: ParsedCircuit, is_dc: bool) -> Tuple[ParsedElement, str, List[ParsedElement]]:
    """
    (depolayıcı eleman, 'C'|'L', anahtarlar) döndürür; uygun değilse
    TransientNotApplicable(Türkçe gerekçe).
    """
    if not is_dc:
        raise TransientNotApplicable(
            "Geçici durum (anahtar) analizi yalnızca DC modunda yapılır; AC modunda "
            "bu yöntem kullanılamaz.")
    types = {e.element_type for e in parsed.elements}
    if types & (set(SINE_SOURCES) | set(PHASOR_SOURCES)):
        raise TransientNotApplicable(
            "Devrede AC (alternatif akım) kaynağı var; geçici durum analizi yalnızca "
            "DC kaynaklı devrelerde yapılır.")
    if types & set(DEPENDENT_SOURCES):
        raise TransientNotApplicable(
            "Devrede bağımlı kaynak var; geçici durum analizi yalnızca bağımsız DC "
            "kaynaklı devrelerde yapılır.")
    if ElementType.IMPEDANCE in types:
        raise TransientNotApplicable(
            "Devrede empedans (Z) elemanı var; geçici durum analizi yalnızca R, C, L "
            "ve DC kaynaklı devrelerde yapılır.")
    switches = [e for e in parsed.elements if e.element_type == ElementType.SWITCH]
    if not switches:
        raise TransientNotApplicable(
            "Devrede anahtar yok; geçici durum için t = 0'da konum değiştiren bir "
            "anahtar gerekir.")
    caps = [e for e in parsed.elements if e.element_type == ElementType.CAPACITOR]
    inds = [e for e in parsed.elements if e.element_type == ElementType.INDUCTOR]
    if not caps and not inds:
        raise TransientNotApplicable(
            "Devrede kondansatör ya da bobin yok; enerji depolayan eleman olmadan "
            "geçici durum oluşmaz.")
    if caps and inds:
        raise TransientNotApplicable(
            "Devrede hem kondansatör hem bobin var (ikinci dereceden devre); "
            "yalnızca tek kondansatörlü (RC) ya da tek bobinli (RL) devreler çözülür.")
    if len(caps) + len(inds) > 1:
        word = "kondansatör" if caps else "bobin"
        raise TransientNotApplicable(
            f"Devrede birden fazla {word} var; yalnızca tam olarak bir {word} içeren "
            "(birinci dereceden) devreler çözülür.")
    return (caps or inds)[0], ("C" if caps else "L"), switches


# ═══════════════════════════════════════════════════════
#  ANA ANALİZ
# ═══════════════════════════════════════════════════════

def _find(circuit: ParsedCircuit, eid: str) -> ParsedElement:
    return next(e for e in circuit.elements if e.id == eid)


def analyze_transient(parsed: ParsedCircuit, is_dc: bool = True) -> TransientAnalysis:
    """
    Geçici durum sayılarını hesaplar ve lcapy ile doğrular.
    Uygulanamazsa ya da doğrulanamazsa TransientNotApplicable (Türkçe gerekçe).
    """
    storage0, kind, switches = check_applicable(parsed, is_dc)
    before = circuit_at_time(parsed, "before")
    after = circuit_at_time(parsed, "after")
    sb = _find(before, storage0.id)
    sa = _find(after, storage0.id)
    pb = (sb.node_positive, sb.node_negative)
    pa = (sa.node_positive, sa.node_negative)

    # ── t = 0⁻ ──
    overrides: Dict[str, Tuple[str, float]] = {}
    uncharged = False
    if kind == "C":
        others = [e for e in before.elements if e.id != sb.id]
        # C'nin iki ucu DC'de (C hariç) ayrı kümelerdeyse kümelerden biri GND'ye bağlı
        # değildir: C bir kaynakla yüklenmemiştir → boş (V_C(0⁻) = 0) kabul edilir
        nodes = {n for e in before.elements for n in (e.node_positive, e.node_negative)} | {"0"}
        comp = _components(_branches(others, {}), nodes)
        if comp[pb[0]] != comp[pb[1]]:
            with_i = _components(_branches(others, {}), nodes, include_current=True)
            if with_i[pb[0]] == with_i[pb[1]]:
                raise TransientNotApplicable(
                    "t < 0 konumunda kondansatör yalnızca akım kaynağı üzerinden besleniyor; akımın "
                    "başka yolu olmadığından gerilim sürekli artar ve kararlı hâl oluşmaz.")
            uncharged = True
            overrides[sb.id] = ("v", 0.0)
    dc_before = dc_solve(before.elements, overrides)
    if kind == "C":
        x_before = dc_before.vd(*pb)
    else:
        x_before = dc_before.i[sb.id]
    if abs(x_before) < _TINY:
        x_before = 0.0

    # ── R_th (t>0, C/L çıkarılmış, bağımsız kaynaklar sıfırlanmış) ──
    rest = [e for e in after.elements if e.id != sa.id]
    if pa[0] == pa[1]:
        raise TransientNotApplicable(
            f"t > 0 konumunda {sa.id} bir tel (kapalı anahtar) ile kısa devre ediliyor; "
            "zaman sabiti sıfır olur ve değişim anında biter.")
    if not dc_connected(rest, pa[0], pa[1]):
        what = ("kondansatör hiçbir direnç yoluyla devreye bağlı değil; gerilimi değişmez"
                if kind == "C" else
                "bobinin akım yolu kesiliyor (seri açık devre); bobin akımı bir anda sıfıra "
                "düşmeye çalışır ve ideal modelde zaman sabiti tanımsız olur")
        raise TransientNotApplicable(
            f"t > 0 konumunda {sa.id} için direnç yolu yok: {what}.")
    zeroed = []
    for e in rest:
        if e.element_type == ElementType.DC_SOURCE:
            zeroed.append(_zero_source(e))
        elif e.element_type in CURRENT_SOURCES:
            continue
        else:
            zeroed.append(e)
    test = copy(sa)
    test.id = "ITEST"
    test.element_type = ElementType.CURRENT_DC
    test.node_positive, test.node_negative, test.value = pa[1], pa[0], 1.0
    test.params = {}
    sol_r = dc_solve(zeroed + [test])
    r_th = sol_r.vd(*pa)
    if r_th <= _TINY:
        raise TransientNotApplicable(
            f"t > 0 konumunda {sa.id}'nin gördüğü direnç sıfır (R_th = 0); zaman sabiti "
            "sıfır olur ve değişim anında biter.")
    tau = r_th * sa.value if kind == "C" else sa.value / r_th

    # ── t → ∞ (C açık / L kısa) ve t = 0⁺ (C → V_C0 kaynağı, L → I_L0 kaynağı) ──
    dc_final = dc_solve(after.elements)
    if kind == "C":
        x_final = dc_final.vd(*pa)
        dc_start = dc_solve(after.elements, {sa.id: ("v", x_before)})
        other_start = dc_start.i[sa.id]            # I_C(0⁺), n1 → n2
    else:
        x_final = dc_final.i[sa.id]
        dc_start = dc_solve(after.elements, {sa.id: ("i", x_before)})
        other_start = dc_start.vd(*pa)             # V_L(0⁺)
    if abs(x_final) < _TINY:
        x_final = 0.0
    if abs(other_start) < _TINY:
        other_start = 0.0

    # Thevenin tutarlılığı: C: I(0⁺) = (V∞ − V0)/R_th ;  L: V(0⁺) = (I∞ − I0)·R_th
    expect_other = (x_final - x_before) / r_th if kind == "C" else (x_final - x_before) * r_th
    scale = max(abs(x_final - x_before), abs(other_start), abs(expect_other), _TINY)
    if abs(expect_other - other_start) > _REL * scale + _TINY:
        raise TransientNotApplicable(
            "t = 0⁺ değerleri ile Thevenin sonucu birbirini doğrulamadı; bu devre için "
            "geçici durum anlatımı verilemiyor.")
    if abs(x_final - x_before) <= _REL * max(abs(x_final), abs(x_before), _TINY) + _TINY \
            and abs(other_start) <= _TINY:
        raise TransientNotApplicable(
            "Anahtar konum değiştirse de depolayıcı elemanın gerilimi/akımı değişmiyor "
            "(başlangıç ve son değer aynı); gösterilecek bir geçici durum yok.")

    sid = storage0.id
    if kind == "C":
        quantities = [
            TransientQuantity(f"V_{sid}", f"V_{sid}", "V", x_before, x_before, x_final),
            TransientQuantity(f"I_{sid}", f"I_{sid}", "A", 0.0, other_start, 0.0),
        ]
    else:
        quantities = [
            TransientQuantity(f"V_{sid}", f"V_{sid}", "V", 0.0, other_start, 0.0),
            TransientQuantity(f"I_{sid}", f"I_{sid}", "A", x_before, x_before, x_final),
        ]   # sözleşme: önce depolayıcının gerilimi (V), sonra akımı (I)

    result = TransientAnalysis(
        storage=sa, storage_before=sb,
        kind=kind, before_circuit=before, after_circuit=after,
        after_without_storage=_without(after, sa.id), port=pa, port_before=pb,
        dc_before=dc_before, dc_final=dc_final, uncharged=uncharged,
        r_th=r_th, tau=tau, x_before=x_before, x_start=x_before, x_final=x_final,
        other_start=other_start, quantities=quantities,
        switches=switches, parsed=parsed,
    )
    reason = verify_with_lcapy(result)
    if reason:
        raise TransientNotApplicable(reason)
    result.verified = True
    return result


def _zero_source(e: ParsedElement) -> ParsedElement:
    z = copy(e)
    z.value = 0.0
    z.params = dict(e.params)
    return z


def _without(circuit: ParsedCircuit, eid: str) -> ParsedCircuit:
    new = ParsedCircuit(
        elements=[e for e in circuit.elements if e.id != eid],
        probes=list(circuit.probes), has_ground=circuit.has_ground,
        raw_netlist=circuit.raw_netlist, warnings=list(circuit.warnings),
        errors=list(circuit.errors), node_positions=dict(circuit.node_positions),
    )
    new.node_count = len({n for e in new.elements for n in (e.node_positive, e.node_negative)})
    return new


# ═══════════════════════════════════════════════════════
#  BAĞIMSIZ DOĞRULAMA (lcapy)
# ═══════════════════════════════════════════════════════

def _close(a: float, b: float, scale: float) -> bool:
    return abs(a - b) <= _REL * max(abs(scale), _TINY) + 1e-12


def verify_with_lcapy(a: TransientAnalysis) -> Optional[str]:
    """
    Sayıları lcapy ile bağımsız olarak denetler; uyuşmazsa Türkçe gerekçe, uyuşuyorsa None.

    • t > 0: lcapy devreyi Laplace ile ilk koşulla (C: V_C(0), L: I_L(0)) çözer.
      x(0⁺), x(∞) ve τ (x(τ) = x∞ + (x0 − x∞)/e) karşılaştırılır; V ve I için.
    • t < 0: devre lcapy ile DC çözülebiliyorsa x(0⁻) karşılaştırılır (kondansatör
      "boş kabul edildi" ya da devre tekilse atlanır).
    """
    try:
        from lcapy import Circuit
        import sympy

        sid = a.storage.id
        lines = to_lcapy_netlist(a.after_circuit).split("\n")
        for k, line in enumerate(lines):
            if line.split(" ")[0] == sid:
                lines[k] = f"{line} {a.x_start!r}"
        cct = Circuit("\n".join(lines))
        v_expr, i_expr = cct[sid].v, cct[sid].i

        def at(expr, t):
            val = expr.subs(t)
            return float(sympy.N(getattr(val, "sympy", val)))

        e_inv = math.exp(-1.0)
        for expr, start, final in (
            (v_expr, a.x_start if a.kind == "C" else a.other_start,
             a.x_final if a.kind == "C" else 0.0),
            (i_expr, a.other_start if a.kind == "C" else a.x_start,
             0.0 if a.kind == "C" else a.x_final),
        ):
            span = max(abs(start - final), abs(start), abs(final), _TINY)
            if not _close(at(expr, 0), start, span):
                return "lcapy denetimi: t = 0⁺ değeri hesaplanan değerle uyuşmadı."
            if not _close(at(expr, 60 * a.tau), final, span):
                return "lcapy denetimi: t → ∞ değeri hesaplanan değerle uyuşmadı."
            if not _close(at(expr, a.tau), final + (start - final) * e_inv, span):
                return "lcapy denetimi: zaman sabiti τ hesaplanan değerle uyuşmadı."
    except TransientNotApplicable:
        raise
    except Exception as exc:    # lcapy çözemedi → sonucu doğrulanmamış bırakma
        return f"Sayılar bağımsız çözücüyle doğrulanamadı ({type(exc).__name__})."

    if not a.uncharged:
        try:
            from lcapy import Circuit
            from solver.circuit_solver import _extract_numeric

            cct = Circuit(to_lcapy_netlist(a.before_circuit))
            if a.kind == "C":
                n1, n2 = a.port_before
                v1 = 0.0 if n1 == "0" else _extract_numeric(cct[n1].V, True)
                v2 = 0.0 if n2 == "0" else _extract_numeric(cct[n2].V, True)
                ref = float((v1 - v2).real)
            else:
                ref = float(_extract_numeric(cct[a.storage.id].I, True).real)
        except Exception:
            return None          # t<0 devresi lcapy ile çözülemiyor (yüzen düğüm gibi) → atla
        if not _close(ref, a.x_before, max(abs(ref), abs(a.x_before), _TINY)):
            return "lcapy denetimi: t = 0⁻ değeri hesaplanan değerle uyuşmadı."
    return None
