"""
CircuitAnalyzer API — Diyotlu DC devreler (Faz 4a)

Diyot doğrusal olmayan bir elemandır; kitaptaki (Selek, Elektronik-1) sabit gerilim düşümlü model
kullanılır: iletimde (ON) diyot yerine anot (+) → katot (−) yönünde V_T değerinde bir gerilim
kaynağı (ideal 0 V, Si 0,7 V, Ge 0,3 V), yalıtımda (OFF) açık devre konur.

★ Genel cihaz–durum katmanı: her cihaz bir durum listesidir; her durum bir yerine koyma (eşdeğer
  eleman) ve bir tutarlılık denetimidir. Şimdilik yalnızca diyot (2 durum: OFF, ON); zener ve BJT
  aynı katmana 3 durumla eklenecek.

★ Durum araması (deterministik):
  1. Özdeş paralel diyotlar (aynı model, aynı iki düğüm, aynı yön) tek diyot sayılır.
  2. Birleşimler "etkin durum sayısı" artan sırada (önce hepsi OFF, sonra tek ON …), aynı sayıda
     netlist sırasıyla denenir: en fazla 2⁶ = 64 doğrusal çözüm (sayısal DC düğüm çözücüsü, ms).
  3. Aramada OFF diyot R_OFF = 10¹² Ω'luk sızıntı direncidir; böylece iki yalıtımdaki diyot
     arasında kalan düğümler de tanımlı olur. Tutarlılık: ON → I_AK ≥ −10⁻⁹ A; OFF → V_AK ≤ V_T
     (+10⁻⁹ V; eşitlikte OFF: kitapta iletim için V_T AŞILMALIDIR). Tekil birleşim (ör. Ge ∥ Si
     ikisi de ON: paralel iki farklı gerilim kaynağı) tutarsızdır.
  4. İlk tutarlı birleşim seçilir; fiziksel olarak farklı (akımları farklı) başka tutarlı birleşim
     de varsa ℹ notu. Hiçbiri tutarlı değilse ⛔ Türkçe sebep.
  En fazla 6 diyot (64 birleşim).

★ Son çözüm: seçilen durumda OFF = AÇIK DEVRE (sızıntısız). Yalıtımdaki diyotlar yüzünden GND'ye
  yolu kalmayan kaynaksız bölümler "boşta" sayılır: elemanları eşdeğer devreden çıkarılır (akımları
  0), düğümleri düğüm gerilimlerinde yer almaz. Eşdeğer devre mevcut çözücüyle (_solve_core)
  NODAL ya da MESH yöntemiyle çözülür; diğer yöntemler doğrusal devre ister ve gerekçeyle NODAL'a
  döner. İletimdeki diyotun eşdeğer kaynağının kimliği diyotun kendi adıdır ("D1"); lcapy'de gizli
  bir V… adıyla yazılır (params["lcapy_name"]) ve bu ad yanıtta hiçbir yerde görünmez.
"""

import copy
import dataclasses
import itertools
import math
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from models.request import AnalysisMode, AnalysisType
from models.response import (
    DiodeResult, ElementCurrent, ElementPower, ExplanationBlock, ExplanationSection, ProbeResult,
)
from parser.netlist_parser import (
    CURRENT_SOURCES, DEPENDENT_CURRENT_OUTPUT, DEPENDENT_SOURCES, DIODE_TYPES, PHASOR_SOURCES,
    SINE_SOURCES, SWITCH_NOTE, VOLTAGE_SOURCES, WAVEFORM_ONLY_SOURCES, ElementType,
    ParsedCircuit, ParsedElement, ParsedProbe, circuit_at_time, element_nodes, has_switches,
)

# Aramadaki yalıtım (sızıntı) direnci ve tutarlılık toleransları (sözleşme)
R_OFF = 1e12
I_TOL = 1e-9
V_TOL = 1e-9
MAX_DIODES = 6

MODEL_LABELS = {"IDEAL": "ideal", "SI": "Si", "GE": "Ge", "ZENER": "Zener"}

AC_REASON = "Diyotlu devrelerde AC/kare/üçgen kaynak için 'Dalga Şekli' yöntemini seçin."

# Diyotlu devrede uygulanamayan yöntemler: (bölüm başlığı, cümle içindeki adı)
_REFUSED = {
    AnalysisType.SUPERPOSITION: ("Süperpozisyon", "süperpozisyon yöntemi"),
    AnalysisType.THEVENIN: ("Thevenin Eşdeğeri", "Thevenin teoremi"),
    AnalysisType.NORTON: ("Norton Eşdeğeri", "Norton teoremi"),
    AnalysisType.MILLMAN: ("Millman Teoremi", "Millman teoremi"),
    AnalysisType.SOURCE_TRANSFORM: ("Kaynak Dönüşümü", "kaynak dönüşümü yöntemi"),
    AnalysisType.RECIPROCITY: ("Karşıtlık Teoremi", "karşıtlık teoremi"),
    AnalysisType.TRANSIENT: ("Geçici Durum", "geçici durum analizi"),
    AnalysisType.RESONANCE: ("Rezonans", "rezonans yöntemi"),
    AnalysisType.POWER: ("Güç ve Güç Katsayısı", "güç ve güç katsayısı yöntemi"),
    AnalysisType.TRANSFORMER: ("Transformatör", "transformatör yöntemi"),
    AnalysisType.THREE_PHASE: ("Üç Faz", "üç faz yöntemi"),
}


class DiodeUnsolvable(Exception):
    """Diyotlu devre çözülemiyor; mesaj öğrenciye gidecek Türkçe sebeptir."""


# ═══════════════════════════════════════════════════════
#  RAPOR (anlatım ve sonuçlar için)
# ═══════════════════════════════════════════════════════

@dataclass
class DiodeInfo:
    id: str
    model: str
    v_t: float
    anode: str
    cathode: str
    v_z: Optional[float] = None           # zener kırılma gerilimi V_Z (V)
    i_zm: Optional[float] = None          # en büyük zener akımı I_ZM (A)
    state: str = "OFF"                    # "ON" | "ZENER" | "OFF"
    group: List[str] = field(default_factory=list)   # özdeş paralel grup (kendisi dahil)
    rep: str = ""                         # grubun temsilcisi (eşdeğer kaynağın kimliği)
    i: float = 0.0                        # raporlanan akım: ON'da I_AK, ZENER'de pozitif I_Z (katot → anot)
    i_ak: float = 0.0                     # her zaman anot → katot yönünde akım (KCL ve element_currents için)
    i_total: float = 0.0                  # grubun toplam akımı
    v_ak: Optional[float] = None          # son çözümde V_AK (uçlardan biri boştaysa None)
    v_ak_search: float = 0.0              # aramadaki (sızıntılı) V_AK — yalnızca yön için
    kind: str = ""                        # on | on_cut | zener | zener_cut | reverse | zero | forward_low
    over_izm: bool = False                # ZENER durumunda I_Z > I_ZM aşıldı mı
    dropped: bool = False                 # boşta kalan bölümde (eşdeğer devreden çıkarıldı)

    @property
    def label(self) -> str:
        return MODEL_LABELS.get(self.model, self.model)

    @property
    def is_ideal(self) -> bool:
        return self.v_t == 0.0

    @property
    def is_zener(self) -> bool:
        return self.model == "ZENER"


@dataclass
class DiodeReport:
    diodes: List[DiodeInfo]
    combos_tried: int = 0
    floating_nodes: List[str] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)     # boşta kalan diyot dışı elemanlar
    notes: List[str] = field(default_factory=list)       # ℹ notları (anlatım + hatalar)
    refused: Optional[Tuple[str, str]] = None            # (başlık, ad) — NODAL'a dönüldüyse
    circuit: Optional[ParsedCircuit] = None              # anahtarlar konumunda, diyotlu devre
    equivalent: Optional[ParsedCircuit] = None           # çözülen eşdeğer devre

    def by_id(self) -> Dict[str, DiodeInfo]:
        return {d.id: d for d in self.diodes}


# ═══════════════════════════════════════════════════════
#  GENEL CİHAZ–DURUM KATMANI
# ═══════════════════════════════════════════════════════

@dataclass
class DeviceState:
    """Bir cihaz durumu: aramadaki eleman, son çözümdeki eşdeğer (None = açık devre), denetim."""
    name: str
    search_element: Callable[[ParsedElement], ParsedElement]
    final_element: Callable[[ParsedElement], Optional[ParsedElement]]
    consistent: Callable[[ParsedElement, float, float], bool]      # (eleman, V_AK, I_AK)


def _diode_on_element(d: ParsedElement) -> ParsedElement:
    return ParsedElement(
        id=d.id, element_type=ElementType.DC_SOURCE,
        node_positive=d.node_positive, node_negative=d.node_negative, value=d.params["v_t"],
        params={"diode_of": d.id, "model": d.params["model"], "v_t": d.params["v_t"]})


def _diode_off_search(d: ParsedElement) -> ParsedElement:
    return ParsedElement(id=d.id, element_type=ElementType.RESISTOR,
                         node_positive=d.node_positive, node_negative=d.node_negative, value=R_OFF)


def _zener_breakdown_element(d: ParsedElement) -> ParsedElement:
    # Ters iletim (zener bölgesi): + ucu katotta, − ucu anotta V_Z kaynağı (V_KA = V_Z)
    return ParsedElement(
        id=d.id, element_type=ElementType.DC_SOURCE,
        node_positive=d.node_negative, node_negative=d.node_positive, value=d.params["v_z"],
        params={"diode_of": d.id, "model": d.params["model"], "v_t": d.params["v_t"],
                "v_z": d.params["v_z"], "zener_state": "ZENER"})


# Diyot: durum 0 = OFF (yalıtım), durum 1 = ON (iletim). Sıra önemlidir: arama düşük indeksten başlar.
DIODE_STATES: List[DeviceState] = [
    DeviceState("OFF", _diode_off_search, lambda d: None,
                lambda d, v_ak, i_ak: v_ak <= d.params["v_t"] + V_TOL),
    DeviceState("ON", _diode_on_element, _diode_on_element,
                lambda d, v_ak, i_ak: i_ak >= -I_TOL),
]

# Zener (sabit V_Z, V_F = 0,7 V): 0 = OFF (−V_Z ≤ V_AK ≤ V_F; sınırda OFF), 1 = ON, 2 = ZENER (I_KA ≥ 0).
ZENER_STATES: List[DeviceState] = [
    DeviceState("OFF", _diode_off_search, lambda d: None,
                lambda d, v_ak, i_ak: -d.params["v_z"] - V_TOL <= v_ak <= d.params["v_t"] + V_TOL),
    DeviceState("ON", _diode_on_element, _diode_on_element,
                lambda d, v_ak, i_ak: i_ak >= -I_TOL),
    DeviceState("ZENER", _zener_breakdown_element, _zener_breakdown_element,
                lambda d, v_ak, i_ak: -i_ak >= -I_TOL),
]


def device_states(elem: ParsedElement) -> List[DeviceState]:
    if elem.element_type in DIODE_TYPES:
        return ZENER_STATES if elem.params.get("model") == "ZENER" else DIODE_STATES
    raise ValueError(f"{elem.id}: durum katmanı bu eleman türünü bilmiyor")


# ═══════════════════════════════════════════════════════
#  SAYISAL DC DÜĞÜM ÇÖZÜCÜSÜ (arama için, gerçek sayılar)
# ═══════════════════════════════════════════════════════

class _Singular(Exception):
    pass


class _Unsupported(Exception):
    pass


_V_BRANCH = (ElementType.DC_SOURCE, ElementType.INDUCTOR, ElementType.VCVS, ElementType.CCVS)


def _dc_solve(elements: List[ParsedElement]) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    DC düğüm denklemleri (MNA). R: iletkenlik; C: açık devre yerine 10¹² Ω (aramada düğüm tanımlı
    kalsın); L: 0 V'luk kol; bağımsız ve bağımlı kaynaklar netlist kurallarıyla (akım kaynağında
    akım kaynak İÇİNDEN n+ → n−). Dönüş: (düğüm gerilimleri, eleman akımları n+ → n−).
    Tekil sistemde _Singular, bilinmeyen elemanda _Unsupported.
    """
    by_id = {e.id: e for e in elements}
    nodes: List[str] = []
    for e in elements:
        for n in (e.node_positive, e.node_negative):
            if n != "0" and n not in nodes:
                nodes.append(n)
    idx = {n: k for k, n in enumerate(nodes)}
    nn = len(nodes)
    branch: Dict[str, int] = {}
    for e in elements:
        if e.element_type in _V_BRANCH:
            branch[e.id] = nn + len(branch)
    size = nn + len(branch)
    A = np.zeros((size, size))
    b = np.zeros(size)

    def col(n):
        return idx.get(n) if n != "0" else None

    def add(r, c, v):
        if r is not None and c is not None:
            A[r, c] += v

    def conductance(e) -> Optional[float]:
        t = e.element_type
        if t == ElementType.RESISTOR:
            return 1.0 / e.value
        if t == ElementType.CAPACITOR:
            return 1.0 / R_OFF
        if t == ElementType.IMPEDANCE:
            z = complex(e.params.get("impedance", e.value))
            if abs(z.imag) > 1e-12 * max(abs(z), 1e-300) or z.real == 0:
                raise _Unsupported(e.id)
            return 1.0 / z.real
        return None

    def current_terms(e, depth=0) -> Tuple[List[Tuple[int, float]], float]:
        """Elemanın n+ → n− akımı = Σ katsayı·bilinmeyen + sabit."""
        if depth > 20:
            raise _Unsupported(e.id)
        g = conductance(e)
        if g is not None:
            terms = []
            if col(e.node_positive) is not None:
                terms.append((col(e.node_positive), g))
            if col(e.node_negative) is not None:
                terms.append((col(e.node_negative), -g))
            return terms, 0.0
        if e.id in branch:
            return [(branch[e.id], 1.0)], 0.0
        t = e.element_type
        if t == ElementType.CURRENT_DC:
            return [], float(e.value)
        if t == ElementType.VCCS:
            k = e.params["gain"] * e.params["control_sign"]
            c = by_id[e.params["control_id"]]
            terms = []
            if col(c.node_positive) is not None:
                terms.append((col(c.node_positive), k))
            if col(c.node_negative) is not None:
                terms.append((col(c.node_negative), -k))
            return terms, 0.0
        if t == ElementType.CCCS:
            k = e.params["gain"] * e.params["control_sign"]
            terms, const = current_terms(by_id[e.params["control_id"]], depth + 1)
            return [(c, k * v) for c, v in terms], k * const
        raise _Unsupported(e.id)

    row = [nn]

    def new_row():
        r = row[0]
        row[0] += 1
        return r

    for e in elements:
        t = e.element_type
        p, n = e.node_positive, e.node_negative
        if t in _V_BRANCH:
            c = branch[e.id]
            add(col(p), c, 1.0)
            add(col(n), c, -1.0)
            r = new_row()
            add(r, col(p), 1.0)
            add(r, col(n), -1.0)
            if t == ElementType.DC_SOURCE:
                b[r] += e.value
            elif t == ElementType.VCVS:
                k = e.params["gain"] * e.params["control_sign"]
                ctrl = by_id[e.params["control_id"]]
                add(r, col(ctrl.node_positive), -k)
                add(r, col(ctrl.node_negative), k)
            elif t == ElementType.CCVS:
                k = e.params["gain"] * e.params["control_sign"]
                terms, const = current_terms(by_id[e.params["control_id"]])
                for cc, v in terms:
                    add(r, cc, -k * v)
                b[r] += k * const
            continue
        terms, const = current_terms(e)
        if conductance(e) is not None:
            for node, sign in ((p, 1.0), (n, -1.0)):
                for cc, v in terms:
                    add(col(node), cc, sign * v)
            continue
        # Akım çıkışlı eleman: n+ düğümünden çıkar, n− düğümüne girer
        for cc, v in terms:
            add(col(p), cc, v)
            add(col(n), cc, -v)
        if col(p) is not None:
            b[col(p)] -= const
        if col(n) is not None:
            b[col(n)] += const

    if size:
        try:
            x = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            raise _Singular()
        if not np.all(np.isfinite(x)):
            raise _Singular()
        resid = np.abs(A @ x - b).max()
        scale = max(np.abs(b).max(), np.abs(A).max() * np.abs(x).max(), 1e-300)
        if resid > 1e-8 * scale:
            raise _Singular()
    else:
        x = np.zeros(0)

    volts = {"0": 0.0}
    for nd, k in idx.items():
        volts[nd] = float(x[k])
    currents: Dict[str, float] = {}
    for e in elements:
        terms, const = current_terms(e)
        currents[e.id] = float(sum(v * x[c] for c, v in terms) + const)
    return volts, currents


def _voltage_loop(elements: List[ParsedElement]) -> bool:
    """Yalnızca gerilim tipi kollardan (kaynak, DC'de bobin, iletimdeki diyot) oluşan halka var mı?"""
    parent: Dict[str, str] = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for e in elements:
        if e.element_type in (ElementType.DC_SOURCE, ElementType.INDUCTOR):
            ra, rb = find(e.node_positive), find(e.node_negative)
            if ra == rb:
                return True
            parent[ra] = rb
    return False


def _search_base(circuit: ParsedCircuit) -> List[ParsedElement]:
    """Diyot dışı elemanlar, DC arama çözücüsünün anlayacağı biçimde."""
    out = []
    for e in circuit.elements:
        if e.element_type in DIODE_TYPES:
            continue
        out.append(e)
    return out


# ═══════════════════════════════════════════════════════
#  DURUM ARAMASI
# ═══════════════════════════════════════════════════════

@dataclass
class _Candidate:
    states: Tuple[int, ...]
    volts: Dict[str, float]
    currents: Dict[str, float]


def _same_physics(a: _Candidate, b: _Candidate) -> bool:
    """İki tutarlı birleşimin akımları (tüm elemanlarda) aynı mı? Yalnızca sızıntı farkı aynı sayılır."""
    keys = set(a.currents) | set(b.currents)
    scale = max([abs(v) for v in a.currents.values()] + [abs(v) for v in b.currents.values()] + [0.0])
    tol = I_TOL + 1e-6 * scale
    return all(abs(a.currents.get(k, 0.0) - b.currents.get(k, 0.0)) <= tol for k in keys)


def _combos(n: int, sizes: List[int]):
    """Durum birleşimleri: önce en az etkin (OFF dışı) cihaz, eşitlikte netlist sırası."""
    allc = list(itertools.product(*[range(s) for s in sizes]))
    allc.sort(key=lambda st: (sum(1 for x in st if x != 0), [0 if x else 1 for x in st], list(st)))
    return allc


def _group_identical(diodes: List[ParsedElement]) -> List[List[ParsedElement]]:
    groups: Dict[Tuple[str, str, str], List[ParsedElement]] = {}
    order: List[Tuple[str, str, str]] = []
    for d in diodes:
        # Zenerler birleştirilmez (farklı V_Z / I_ZM ve ters iletim olasılığı yüzünden tek tek çözülür)
        key = ("ZENER", d.id, "") if d.params["model"] == "ZENER" else (
            d.params["model"], d.node_positive, d.node_negative)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(d)
    return [groups[k] for k in order]


def resolve_states(circuit: ParsedCircuit):
    """
    Diyotların durumunu bulur. Dönüş: (gruplar, seçilen aday, çoklu_tutarlı_mı, denenen_sayısı).
    Tutarlı birleşim yoksa DiodeUnsolvable.
    """
    diodes = [e for e in circuit.elements if e.element_type in DIODE_TYPES]
    groups = _group_identical(diodes)
    reps = [g[0] for g in groups]
    base = _search_base(circuit)
    sizes = [len(device_states(r)) for r in reps]
    consistent: List[_Candidate] = []
    tried = 0
    unsupported = None
    for st in _combos(len(reps), sizes):
        tried += 1
        subs = [device_states(r)[s].search_element(r) for r, s in zip(reps, st)]
        elems = base + subs
        if _voltage_loop(elems):
            continue
        try:
            volts, currents = _dc_solve(elems)
        except _Singular:
            continue
        except _Unsupported as e:
            unsupported = str(e)
            break
        # Eşdeğer yönü ters olan durumlarda (ZENER: + katotta) akımı anot → katot (I_AK) yönüne çevir
        currents_ak = dict(currents)
        ok = True
        for r, s, sub in zip(reps, st, subs):
            v_ak = volts.get(r.node_positive, 0.0) - volts.get(r.node_negative, 0.0)
            i_raw = currents[r.id]
            i_ak = i_raw if sub.node_positive == r.node_positive else -i_raw
            currents_ak[r.id] = i_ak
            if not device_states(r)[s].consistent(r, v_ak, i_ak):
                ok = False
                break
        if ok:
            consistent.append(_Candidate(st, volts, currents_ak))
    if unsupported is not None:
        raise DiodeUnsolvable(
            f"{unsupported} elemanı diyotlu devrelerde şimdilik kullanılamıyor (diyotlu devrede "
            "direnç, DC kaynak, bobin, kondansatör ve bağımlı kaynak kullanılabilir).")
    if not consistent:
        raise DiodeUnsolvable(
            "Diyotların iletim/yalıtım durumu belirlenemedi: denenen hiçbir birleşim kitaptaki "
            "koşulları (iletimde akım anottan katoda akar; yalıtımda V_AK eşik gerilimini aşmaz) "
            "birlikte sağlamadı.\n\n"
            "Olası nedenler:\n"
            "• Bir diyot arada direnç olmadan doğrudan bir gerilim kaynağına (ya da başka bir diyota) "
            "paralel bağlı olabilir; iletimde akımı sınırlayan bir şey yoktur.\n"
            "• Bir akım kaynağı yalıtımdaki bir diyotla seri kalıyor olabilir.\n\n"
            "Ne yapabilirsiniz:\n"
            "• Diyota seri bir direnç ekleyin.")
    chosen = consistent[0]
    multiple = any(not _same_physics(chosen, c) for c in consistent[1:])
    return groups, chosen, multiple, tried


# ═══════════════════════════════════════════════════════
#  EŞDEĞER DEVRE
# ═══════════════════════════════════════════════════════

def _components(elements: List[ParsedElement]):
    parent: Dict[str, str] = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for e in elements:
        for n in element_nodes(e):
            find(n)
        if e.element_type in CURRENT_SOURCES or e.element_type in DEPENDENT_CURRENT_OUTPUT:
            continue        # akım kaynağı gerilim belirlemez: düğümleri bağlamaz
        ns = element_nodes(e)
        for n in ns[1:]:
            parent[find(ns[0])] = find(n)
    return find, parent


def build_equivalent(circuit: ParsedCircuit, groups, chosen: _Candidate, report: DiodeReport):
    """Seçilen durumda eşdeğer devre (OFF = açık); boşta kalan kaynaksız bölümler çıkarılır."""
    state_of: Dict[str, str] = {}
    rep_of: Dict[str, str] = {}
    for g, s in zip(groups, chosen.states):
        for d in g:
            state_of[d.id] = device_states(g[0])[s].name
            rep_of[d.id] = g[0].id
    used = {e.id.upper() for e in circuit.elements}
    elements: List[ParsedElement] = []
    for e in circuit.elements:
        if e.element_type not in DIODE_TYPES:
            elements.append(e)
            continue
        if rep_of[e.id] != e.id:
            continue
        idx = next(k for k, g in enumerate(groups) if g[0].id == e.id)
        sub = device_states(e)[chosen.states[idx]].final_element(e)
        if sub is None:
            continue
        name = f"Vdiode_{e.id}"
        while name.upper() in used:
            name += "_"
        used.add(name.upper())
        sub.params["lcapy_name"] = name
        elements.append(sub)

    # Boşta kalan bölümler: GND'ye yolu olmayan düğüm kümeleri
    find, parent = _components(elements)
    ground = find("0")
    keep: List[ParsedElement] = []
    for e in elements:
        roots = {find(n) for n in element_nodes(e)}
        if ground in roots:
            keep.append(e)
            continue
        # Bölümde kaynak varsa (bağımsız/bağımlı) ya da akım taşıyorsa çıkarılamaz
        is_source = (e.element_type in VOLTAGE_SOURCES + CURRENT_SOURCES
                     or e.element_type in DEPENDENT_SOURCES) and not e.params.get("diode_of")
        attached_cs = any(
            x.element_type in CURRENT_SOURCES + DEPENDENT_CURRENT_OUTPUT
            and roots & {find(n) for n in element_nodes(x)} for x in elements if x is not e)
        if is_source or attached_cs or abs(chosen.currents.get(e.id, 0.0)) > I_TOL:
            nodes = sorted({n for n in parent if find(n) in roots}, key=lambda x: (len(x), x))
            raise DiodeUnsolvable(
                "Yalıtımdaki diyotlar devrenin bir bölümünü ("
                + ", ".join(f"Düğüm {n}" for n in nodes)
                + ") GND'den ayırıyor ve bu bölümde bir kaynak var; bölümün gerilimleri "
                "belirlenemiyor.\n\nNe yapabilirsiniz:\n"
                "• Bu bölümü bir direnç ya da telle GND'ye bağlayın.")
        if e.params.get("diode_of"):
            report.by_id()[e.id].dropped = True
        else:
            report.dropped.append(e.id)

    raw_nodes = {n for e in circuit.elements for n in element_nodes(e)}
    kept_nodes = {n for e in keep for n in element_nodes(e)}
    report.floating_nodes = sorted(raw_nodes - kept_nodes - {"0"}, key=lambda x: (len(x), x))

    floating = set(report.floating_nodes)
    probes = [p for p in circuit.probes
              if not (p.probe_type == "I" and _is_diode_id(circuit, p.target))
              and not (p.probe_type == "V" and p.target in floating)]
    equiv = ParsedCircuit(
        elements=keep, probes=probes, has_ground=circuit.has_ground,
        raw_netlist=circuit.raw_netlist, warnings=list(circuit.warnings),
        errors=list(circuit.errors), node_positions=dict(circuit.node_positions),
        value_basis=circuit.value_basis, diode_report=report)
    equiv.node_count = len(kept_nodes)
    report.equivalent = equiv
    return equiv, state_of, rep_of


def _is_diode_id(circuit: ParsedCircuit, eid: str) -> bool:
    return any(e.id == eid and e.element_type in DIODE_TYPES for e in circuit.elements)


# ═══════════════════════════════════════════════════════
#  ANA GİRİŞ
# ═══════════════════════════════════════════════════════

def _unsolvable(reason: str):
    from solver.circuit_solver import UNSOLVABLE_PREFIX
    from models.response import AnalysisResults
    return AnalysisResults(), [], [UNSOLVABLE_PREFIX + reason]


def gate_reason(parsed: ParsedCircuit, mode: AnalysisMode) -> Optional[str]:
    """Diyotlu devre DC çözümüyle çözülemiyorsa (AC, çok diyot, desteklenmeyen eleman) Türkçe sebep."""
    if mode != AnalysisMode.DC or any(
            e.element_type in SINE_SOURCES + PHASOR_SOURCES + WAVEFORM_ONLY_SOURCES
            or e.element_type == ElementType.THREE_PHASE_SOURCE for e in parsed.elements):
        return AC_REASON
    count = sum(1 for e in parsed.elements if e.element_type in DIODE_TYPES)
    if count > MAX_DIODES:
        return (f"Bu devrede {count} diyot var; şimdilik en fazla {MAX_DIODES} diyotlu devreler "
                "çözülebilir (her diyotun iletim/yalıtım durumu tek tek denenir). Diyot sayısını "
                "azaltın.")
    odd = [e.id for e in parsed.elements if e.element_type in (
        ElementType.TRANSFORMER, ElementType.THREE_PHASE_LOAD, ElementType.WATTMETER)]
    if odd:
        return (f"Diyotlu devrelerde transformatör, üç fazlı yük ve wattmetre şimdilik "
                f"kullanılamaz ({', '.join(odd)}).")
    return None


def solve_with_diodes(parsed: ParsedCircuit, mode: AnalysisMode, frequency, analysis_type,
                      thevenin_terminals, target_probes, warnings,
                      zener_range_target: Optional[str] = None,
                      zener_range_given_min: Optional[float] = None,
                      zener_range_given_max: Optional[float] = None,
                      waveform_output: Optional[str] = None):
    """Diyotlu devre: durum araması → eşdeğer devre → mevcut çözücü → sonuçların tamamlanması."""
    from solver.circuit_solver import UNSOLVABLE_PREFIX, _solve_core

    if analysis_type == AnalysisType.WAVEFORM:
        # Dalga Şekli kendi AC/kare/üçgen uygunluk denetimini yapar; DC kapısından önce ayrılır
        from solver.waveform import solve_waveform
        return solve_waveform(
            parsed, mode, frequency, target_probes, warnings,
            waveform_output=waveform_output,
        )

    why = gate_reason(parsed, mode)
    if why:
        return _unsolvable(why)
    switched = has_switches(parsed)
    circuit = circuit_at_time(parsed, "after") if switched else parsed

    try:
        groups, chosen, multiple, tried = resolve_states(circuit)
    except DiodeUnsolvable as e:
        return _unsolvable(str(e))

    infos = []
    for e in circuit.elements:
        if e.element_type in DIODE_TYPES:
            infos.append(DiodeInfo(id=e.id, model=e.params["model"], v_t=e.params["v_t"],
                                   anode=e.node_positive, cathode=e.node_negative,
                                   v_z=e.params.get("v_z"), i_zm=e.params.get("i_zm")))
    report = DiodeReport(diodes=infos, combos_tried=tried, circuit=circuit)
    try:
        equiv, state_of, rep_of = build_equivalent(circuit, groups, chosen, report)
    except DiodeUnsolvable as e:
        return _unsolvable(str(e))
    if not equiv.elements:
        return _unsolvable("Diyotlar yalıtımda kalınca devrede hiçbir akım yolu kalmıyor.")

    by_id = report.by_id()
    for g in groups:
        for d in g:
            info = by_id[d.id]
            info.state = state_of[d.id]
            info.rep = g[0].id
            info.group = [x.id for x in g]
            info.v_ak_search = (chosen.volts.get(d.node_positive, 0.0)
                                - chosen.volts.get(d.node_negative, 0.0))
        if len(g) > 1:
            report.notes.append(
                f"{_and([x.id for x in g])} özdeş (aynı model, aynı uçlar, aynı yön) ve paralel "
                "bağlı: tek bir diyot gibi davranır, akım aralarında eşit bölünür.")
    if multiple:
        report.notes.append(
            "Diyotların birden fazla tutarlı iletim/yalıtım birleşimi bulundu; ilk bulunan "
            "(en az diyotun iletimde olduğu) birleşim kullanıldı.")

    core_type = analysis_type
    is_zener_range = analysis_type == AnalysisType.ZENER_RANGE
    if is_zener_range:
        # Zener Aralığı: çizilen devrenin normal düğüm çözümü yapılır, reddedilmez
        core_type = AnalysisType.NODAL
    elif analysis_type not in (AnalysisType.NODAL, AnalysisType.MESH):
        report.refused = _REFUSED.get(analysis_type, (analysis_type.value, analysis_type.value))
        core_type = AnalysisType.NODAL

    diode_ids = {d.id for d in infos}
    floating = set(report.floating_nodes)

    def keep_probe(p) -> bool:
        kind = str(getattr(p, "type", "")).upper()
        return not ((kind == "I" and p.target in diode_ids) or (kind == "V" and p.target in floating))

    probes = [p for p in (target_probes or []) if keep_probe(p)]

    results, steps, errors = _solve_core(
        equiv, mode, frequency, core_type, None, probes or None, warnings)
    names = {e.params["lcapy_name"]: e.id for e in equiv.elements if e.params.get("lcapy_name")}
    _scrub_steps(steps, names)
    errors = [_scrub_text(m, names) for m in errors]
    if any(m.startswith(UNSOLVABLE_PREFIX) for m in errors) or not results.node_voltages:
        off = [d.id for d in infos if d.state == "OFF"]
        if off:
            # Eşdeğer devredeki engel, kullanıcının çizdiği devrede görünmeyebilir: bağlamı söyle
            ctx = (f"Diyot durumları belirlendikten sonra {_and(off)} yalıtımda kaldı ve açık "
                   "devre sayıldı; bu elektriksel eşdeğer devre çözülemiyor. ")
            errors = [UNSOLVABLE_PREFIX + ctx + m[len(UNSOLVABLE_PREFIX):]
                      if m.startswith(UNSOLVABLE_PREFIX) else m for m in errors]
        return results, steps, errors

    _complete_results(results, report, equiv, circuit, target_probes, errors)

    zr_applied = False
    zr_reason = ""
    if is_zener_range:
        from explainer.zener_range_narrative import (
            build_zener_range_sections, fallback_note, fallback_section,
        )
        from solver.zener_range import analyze_zener_range
        zr_analysis, zr_reason = analyze_zener_range(
            parsed, mode, zener_range_target,
            given_min=zener_range_given_min,
            given_max=zener_range_given_max,
        )
        if zr_analysis is not None:
            results.zener_range = zr_analysis.summary
            results.explanation = build_zener_range_sections(zr_analysis)
            zr_applied = True
        else:
            errors.append(fallback_note(zr_reason))

    if not zr_applied:
        from explainer.diode_narrative import build_diode_sections
        try:
            head = build_diode_sections(report, results)
        except Exception as e:      # beklenmeyen hata: yanlış anlatım yerine dürüst yedek
            from solver.error_text import turkish_error
            errors.append(f"ℹ Diyot anlatımı oluşturulamadı: {turkish_error(e, 'diyot anlatımı')}")
            head = []
        if is_zener_range and zr_reason:
            from explainer.zener_range_narrative import fallback_section
            head.insert(0, fallback_section(zr_reason))
        # Önce devre tanıtılır ("Devreyi Tanıyalım"), sonra diyot durumları ve eşdeğer devre gelir
        rest = list(results.explanation)
        at = next((k + 1 for k, sec in enumerate(rest) if sec.title == "Devreyi Tanıyalım"), 0)
        results.explanation = rest[:at] + head + rest[at:]
        if switched:
            results.explanation.insert(0, ExplanationSection(
                title="Anahtar Konumu", blocks=[ExplanationBlock(kind="note", text=SWITCH_NOTE)]))

    for note in report.notes:
        errors.append(f"ℹ {note}")
    if report.refused is not None:
        title, what = report.refused
        errors.append(f"ℹ {title} uygulanamadı: diyot doğrusal olmayan bir elemandır; {what} "
                      "yalnızca doğrusal devrelerde geçerlidir. Sonuçlar Düğüm Gerilimleri "
                      "yöntemiyle verildi.")

    # Alıştırma: diyot soruları 4a kapsamında yok (eşdeğer kaynağı soran sorular çıkarılır).
    # Toplam güç sorusu "dirençlerdeki güç = kaynakların verdiği güç" der; iletimdeki eşikli
    # diyot da güç harcadığından bu eşitlik bozulur, soru çıkarılır.
    pat = re.compile(r"(?<![\w])(" + "|".join(re.escape(i) for i in sorted(diode_ids, key=len,
                                                                          reverse=True)) + r")(?![\w])")
    lossy = any(((d.state == "ON" and d.v_t > 0) or d.state == "ZENER") and not d.dropped
                for d in infos)
    results.practice = [q for q in results.practice
                        if not (pat.search(q.id) or pat.search(q.label) or pat.search(q.description)
                                or (lossy and q.id == "P_TOTAL"))]
    return results, steps, errors


def _and(items: List[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " ve " + items[-1]


def _scrub_text(text: str, names: Dict[str, str]) -> str:
    for hidden, shown in sorted(names.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(hidden, shown)
    return text


def _scrub(value, names):
    if isinstance(value, str):
        return _scrub_text(value, names)
    if isinstance(value, dict):
        return {(_scrub_text(k, names) if isinstance(k, str) else k): _scrub(v, names)
                for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, names) for v in value]
    return value


def _scrub_steps(steps, names: Dict[str, str]) -> None:
    """Gizli lcapy adları (Vdiode_…) çözüm adımlarında diyotun adıyla değiştirilir."""
    if not names:
        return
    for st in steps:
        st.description = _scrub_text(st.description, names)
        st.equations = [_scrub_text(x, names) for x in st.equations]
        if st.latex_formula:
            st.latex_formula = _scrub_text(st.latex_formula, names)
        if st.result_snapshot:
            st.result_snapshot = _scrub(st.result_snapshot, names)


def _complete_results(results, report: DiodeReport, equiv: ParsedCircuit, circuit: ParsedCircuit,
                      target_probes, errors: List[str]) -> None:
    """Diyot akımları (gruplar bölünür, yalıtımdakiler 0), boşta kalan elemanlar, güç ve `diodes`."""
    from explainer.formatting import eng
    from solver.circuit_solver import make_complex_number, sig_round

    def num_value(v) -> float:
        return float(v) if isinstance(v, (int, float)) else float(v.real)

    nv = results.node_voltages
    ec = results.element_currents
    totals: Dict[str, float] = {}
    for d in report.diodes:
        if d.id == d.rep and d.state in ("ON", "ZENER") and not d.dropped and d.id in ec:
            totals[d.id] = num_value(ec[d.id].value)
    for d in report.diodes:
        total = totals.get(d.rep, 0.0) if d.state in ("ON", "ZENER") else 0.0
        d.i_total = total
        if d.anode in nv and d.cathode in nv:
            d.v_ak = num_value(nv[d.anode].value) - num_value(nv[d.cathode].value)
        if d.state == "ON":
            d.i = total / len(d.group) if d.group else total
            d.i_ak = d.i
            d.kind = "on" if abs(total) > I_TOL else "on_cut"
        elif d.state == "ZENER":
            # Eşdeğer kaynak (+ katot, − anot) akımı katot → anot yönünde pozitiftir (I_Z = I_KA)
            d.i = total
            d.i_ak = -d.i
            d.kind = "zener" if abs(total) > I_TOL else "zener_cut"
            if d.i_zm is not None and d.i > d.i_zm + I_TOL:
                d.over_izm = True
                errors.append(
                    f"⚠ {d.id}: I_Z = {eng(d.i, 'A')}, I_ZM = {eng(d.i_zm, 'A')} sınırını aşıyor; "
                    "gerçekte zener aşırı akımdan zarar görür. Not: bazı ders kitapları bu durumu "
                    "“zener yalıtımdadır” diye yorumlar.")
        else:
            d.i = 0.0
            d.i_ak = 0.0
            v = d.v_ak if d.v_ak is not None else d.v_ak_search
            d.kind = "reverse" if v < -1e-12 else ("zero" if abs(v) <= 1e-12 else "forward_low")

    # Eleman akımları: netlist sırasıyla (diyotlar her zaman anot → katot yönünde; KCL tutarlı kalır)
    info = report.by_id()
    new_ec = {}
    for e in circuit.elements:
        if e.id in info:
            d = info[e.id]
            new_ec[e.id] = ElementCurrent(value=sig_round(d.i_ak), unit="A",
                                          direction=f"{d.anode}→{d.cathode}")
        elif e.id in ec:
            new_ec[e.id] = ec[e.id]
        elif e.id in report.dropped:
            new_ec[e.id] = ElementCurrent(value=0.0, unit="A",
                                          direction=f"{e.node_positive}→{e.node_negative}")
    for k, v in ec.items():
        new_ec.setdefault(k, v)
    results.element_currents = new_ec

    # Güç: diyot (yük) ON'da V_T·I, ZENER'de V_Z·I_Z; yalıtımdakiler ve boştakiler 0
    if results.power is not None:
        pe = results.power.elements
        new_pe = {}

        def power_entry(eid: str, p: float) -> ElementPower:
            return ElementPower(
                element_id=eid, role="load", complex_power=make_complex_number(p),
                active_power=sig_round(p), reactive_power=0.0, apparent_power=sig_round(abs(p)),
                power_factor=1.0 if abs(p) > 1e-15 else None,
                power_factor_type="birim" if abs(p) > 1e-15 else None)

        for e in circuit.elements:
            if e.id in info:
                d = info[e.id]
                if d.state == "ON":
                    p = d.v_t * d.i
                elif d.state == "ZENER":
                    p = d.v_z * d.i
                else:
                    p = 0.0
                new_pe[e.id] = power_entry(e.id, p)
            elif e.id in pe:
                new_pe[e.id] = pe[e.id]
            elif e.id in report.dropped:
                new_pe[e.id] = power_entry(e.id, 0.0)
        for k, v in pe.items():
            new_pe.setdefault(k, v)
        results.power.elements = new_pe

    # Diyot ve boştaki düğüm probları
    floating = set(report.floating_nodes)
    all_probes = list(target_probes or [])
    seen = {p.id for p in all_probes}
    all_probes += [p for p in circuit.probes if p.id not in seen]
    for p in all_probes:
        kind = str(getattr(p, "type", None) or getattr(p, "probe_type", "")).upper()
        if kind == "I" and p.target in info:
            results.probe_results.append(ProbeResult(
                probe_id=p.id, type="I", value=sig_round(info[p.target].i_ak), unit="A"))
        elif kind == "V" and p.target in floating:
            errors.append(f"ℹ {p.id}: Düğüm {p.target} boşta kalır (akım yolu yok); gerilimi "
                          "belirsizdir.")

    results.diodes = [
        DiodeResult(id=d.id, model=d.model, v_t=d.v_t, vz=d.v_z, izm=d.i_zm, state=d.state,
                    v_ak=None if d.v_ak is None else sig_round(d.v_ak), i=sig_round(d.i))
        for d in report.diodes
    ]


def with_diode_states(parsed: ParsedCircuit, diodes) -> ParsedCircuit:
    """Asistan için: diyotların çözümdeki durumu ve akımı eleman parametrelerine yazılmış kopya."""
    by_id = {d.id: d for d in diodes}
    new = copy.copy(parsed)
    new.elements = []
    for e in parsed.elements:
        if e.element_type in DIODE_TYPES and e.id in by_id:
            params = dict(e.params)
            params["state"] = by_id[e.id].state
            params["i"] = by_id[e.id].i
            e = dataclasses.replace(e, params=params)
        new.elements.append(e)
    return new
