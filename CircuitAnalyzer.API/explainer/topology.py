"""
CircuitAnalyzer API — Seri/Paralel Tanıma (Topoloji Analizi)

Devredeki pasif elemanları yinelemeli olarak seri ve paralel
kombinasyonlara indirger ve her indirgemeyi öğrencinin sınavda
yazacağı formülle (ör: Req = R1·R2/(R1+R2)) açıklar.

★ Kurallar:
    Paralel: Aynı iki düğüm arasındaki iki pasif kol.
    Seri:    Ara düğüme yalnızca iki pasif kol bağlıysa (başka eleman,
             kaynak veya terminal yoksa) bu iki kol seridir.

    Sabit (elenmeyen) düğümler: GND, kaynak uçları ve Thevenin/Norton
    terminalleri — bu düğümler ölçüm/port noktası olduğundan korunur.

★ Mod farkları:
    DC: Kapasitörler açık devredir → graftan çıkarılır.
        Bobinler kısa devredir → indirgenmez (düğüm birleştirme
        iddiasında bulunmamak için kol olarak bırakılır).
    AC: Tüm pasif elemanlar empedanslarıyla birleştirilir
        (frekans yoksa sadece aynı tip elemanlar).

★ NOT: Bu modül çözüm YAPMAZ — sadece eğitici açıklama üretir.
  Sayısal çözüm her zaman lcapy'den gelir.
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

from models.response import SolutionStep
from parser.netlist_parser import ParsedCircuit, ElementType, VOLTAGE_SOURCES, CURRENT_SOURCES


_UNIT = {"R": "Ω", "L": "H", "C": "F", "Z": "Ω"}
_PASSIVE = {
    ElementType.RESISTOR: "R",
    ElementType.INDUCTOR: "L",
    ElementType.CAPACITOR: "C",
    ElementType.IMPEDANCE: "Z",
}


@dataclass
class Branch:
    """İndirgeme grafındaki bir kol (orijinal eleman veya eşdeğer)."""
    name: str
    a: str
    b: str
    kind: str                      # 'R', 'L', 'C' veya 'Z' (karışık/empedans)
    value: Optional[float] = None  # R/L/C için doğal büyüklük (Ω, H, F)
    z: Optional[complex] = None    # Empedans (ω biliniyorsa)
    members: List[str] = field(default_factory=list)
    reducible: bool = True


@dataclass
class Reduction:
    """Tek bir seri/paralel indirgeme adımı."""
    kind: str                # 'series' | 'parallel'
    elements: Tuple[str, str]
    result_name: str
    result_kind: str
    formula: str             # düz metin: "Req1 = R1 + R2 = 1000 + 2000 = 3000 Ω"
    latex: str
    nodes: Tuple[str, str]   # eşdeğer kolun uçları
    impedance: Optional[complex]
    members: List[str]


def _fmt(x: float) -> str:
    return f"{x:.4g}"


def _fmt_z(z: complex) -> str:
    r, i = z.real, z.imag
    if abs(i) < 1e-12 * max(abs(r), 1.0):
        return _fmt(r)
    if abs(r) < 1e-12 * max(abs(i), 1.0):
        return f"{'-' if i < 0 else ''}j{_fmt(abs(i))}"
    return f"{_fmt(r)}{'+' if i >= 0 else '-'}j{_fmt(abs(i))}"


def _paren(text: str) -> str:
    return f"({text})" if ("+" in text[1:] or "-" in text) else text


def _impedance(kind: str, value: float, omega: Optional[float]) -> Optional[complex]:
    if kind == "R":
        return complex(value)
    if omega is None:
        return None
    if kind == "L":
        return 1j * omega * value
    return 1 / (1j * omega * value)          # C


def _build_branches(
    parsed: ParsedCircuit, is_dc: bool, omega: Optional[float]
) -> Tuple[List[Branch], List[str], List[str]]:
    """
    Returns:
        (kollar, DC'de açık devre sayılan C'ler, indirgenemeyen elemanlar)
    """
    branches, open_caps, blockers = [], [], []
    for e in parsed.elements:
        kind = _PASSIVE.get(e.element_type)
        if kind is None:
            # Kaynak: düğüm derecesine sayılır ama indirgenmez
            branches.append(Branch(e.id, e.node_positive, e.node_negative,
                                   "SRC", reducible=False, members=[e.id]))
            continue
        if is_dc and kind == "C":
            open_caps.append(e.id)
            continue
        if kind == "Z":
            z = e.params.get("impedance", complex(e.value))
            branches.append(Branch(e.id, e.node_positive, e.node_negative,
                                   "Z", z=z, members=[e.id]))
            continue
        if is_dc and kind == "L":
            blockers.append(e.id)
            branches.append(Branch(e.id, e.node_positive, e.node_negative,
                                   "L", value=e.value, reducible=False,
                                   members=[e.id]))
            continue
        branches.append(Branch(e.id, e.node_positive, e.node_negative, kind,
                               value=e.value,
                               z=_impedance(kind, e.value, omega),
                               members=[e.id]))
    return branches, open_caps, blockers


class _Namer:
    def __init__(self):
        self.counts = {}

    def __call__(self, kind: str) -> str:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        return f"{kind}eq{self.counts[kind]}"


def _combine(
    kind: str, b1: Branch, b2: Branch, a: str, b: str, namer: _Namer
) -> Optional[Tuple[Branch, Reduction]]:
    """İki kolu seri ('series') veya paralel ('parallel') birleştirir."""
    n1, n2 = b1.name, b2.name
    series = kind == "series"

    if b1.kind == b2.kind and b1.kind in ("R", "L", "C"):
        k = b1.kind
        v1, v2 = b1.value, b2.value
        unit = _UNIT[k]
        # R, L: seri toplam / paralel çarpım-bölü-toplam; C tam tersi
        additive = series != (k == "C")
        name = namer(k)
        if additive:
            v = v1 + v2
            formula = (f"{name} = {n1} + {n2} = {_fmt(v1)} + {_fmt(v2)} "
                       f"= {_fmt(v)} {unit}")
            latex = (f"{name} = {n1} + {n2} = {_fmt(v1)} + {_fmt(v2)} "
                     f"= {_fmt(v)} \\text{{ {unit}}}")
        else:
            v = v1 * v2 / (v1 + v2)
            formula = (f"{name} = {n1}·{n2}/({n1}+{n2}) = "
                       f"{_fmt(v1)}·{_fmt(v2)}/({_fmt(v1)}+{_fmt(v2)}) "
                       f"= {_fmt(v)} {unit}")
            latex = (f"{name} = \\frac{{{n1} \\cdot {n2}}}{{{n1} + {n2}}} = "
                     f"\\frac{{{_fmt(v1)} \\cdot {_fmt(v2)}}}"
                     f"{{{_fmt(v1)} + {_fmt(v2)}}} = {_fmt(v)} "
                     f"\\text{{ {unit}}}")
        z = None
        if b1.z is not None and b2.z is not None:
            z = b1.z + b2.z if series else b1.z * b2.z / (b1.z + b2.z)
        new = Branch(name, a, b, k, value=v, z=z,
                     members=b1.members + b2.members)
    else:
        if b1.z is None or b2.z is None:
            return None                    # AC frekansı yok → karışık birleşmez
        z1, z2 = b1.z, b2.z
        name = namer("Z")
        t1, t2 = _paren(_fmt_z(z1)), _paren(_fmt_z(z2))
        # Direnç ve Z kolları zaten empedanstır (R1, Z1, Zeq1); C/L için Z_C1
        l1 = n1 if n1[0] in "RZ" else f"Z_{n1}"
        l2 = n2 if n2[0] in "RZ" else f"Z_{n2}"
        x1 = n1 if n1[0] in "RZ" else f"Z_{{{n1}}}"
        x2 = n2 if n2[0] in "RZ" else f"Z_{{{n2}}}"
        if series:
            z = z1 + z2
            formula = (f"{name} = {l1} + {l2} = {t1} + {t2} "
                       f"= {_fmt_z(z)} Ω")
            latex = (f"{name} = {x1} + {x2} = {t1} + {t2} "
                     f"= {_fmt_z(z)} \\text{{ Ω}}")
        else:
            if abs(z1 + z2) < 1e-15:
                return None                # LC rezonansı: paralel sonsuz
            z = z1 * z2 / (z1 + z2)
            formula = (f"{name} = {l1}·{l2}/({l1}+{l2}) = "
                       f"{t1}·{t2}/({t1}+{t2}) = {_fmt_z(z)} Ω")
            latex = (f"{name} = \\frac{{{x1} {x2}}}"
                     f"{{{x1} + {x2}}} = {_fmt_z(z)} \\text{{ Ω}}")
        new = Branch(name, a, b, "Z", z=z, members=b1.members + b2.members)

    red = Reduction(
        kind=kind, elements=(n1, n2), result_name=new.name,
        result_kind=new.kind, formula=formula, latex=latex,
        nodes=(a, b), impedance=new.z, members=new.members,
    )
    return new, red


def reduce_series_parallel(
    parsed: ParsedCircuit,
    is_dc: bool = True,
    frequency: Optional[float] = None,
    pinned_nodes: Optional[Set[str]] = None,
) -> Tuple[List[Reduction], List[Branch], List[str], List[str]]:
    """
    Seri/paralel indirgemeleri bulur.

    Returns:
        (indirgemeler, kalan kollar, DC'de açık sayılan C'ler,
         indirgenemeyen bobinler)
    """
    omega = None if is_dc or not frequency else 2 * math.pi * frequency
    branches, open_caps, blockers = _build_branches(parsed, is_dc, omega)
    pinned = {"0"} | set(pinned_nodes or ())
    namer = _Namer()
    reductions: List[Reduction] = []

    changed = True
    while changed:
        changed = False

        # ── Paralel: aynı düğüm çifti arasındaki iki pasif kol ──
        for i, b1 in enumerate(branches):
            if not b1.reducible or b1.a == b1.b:
                continue
            for b2 in branches[i + 1:]:
                if b2.reducible and {b2.a, b2.b} == {b1.a, b1.b}:
                    res = _combine("parallel", b1, b2, b1.a, b1.b, namer)
                    if res is None:
                        continue
                    new, red = res
                    branches = [x for x in branches if x is not b1 and x is not b2]
                    branches.append(new)
                    reductions.append(red)
                    changed = True
                    break
            if changed:
                break
        if changed:
            continue

        # ── Seri: ara düğüme yalnızca iki pasif kol bağlı ──
        nodes = sorted({n for b in branches for n in (b.a, b.b)})
        for node in nodes:
            if node in pinned:
                continue
            incident = [b for b in branches if node in (b.a, b.b)]
            if len(incident) != 2:
                continue
            b1, b2 = incident
            if not (b1.reducible and b2.reducible):
                continue
            end1 = b1.b if b1.a == node else b1.a
            end2 = b2.b if b2.a == node else b2.a
            if end1 == node or end2 == node or end1 == end2:
                continue                   # öz-döngü / sarkan çevrim
            res = _combine("series", b1, b2, end1, end2, namer)
            if res is None:
                continue
            new, red = res
            branches = [x for x in branches if x is not b1 and x is not b2]
            branches.append(new)
            reductions.append(red)
            changed = True
            break

    remaining = [b for b in branches if b.kind != "SRC"]
    return reductions, remaining, open_caps, blockers


def generate_topology_step(
    parsed: ParsedCircuit,
    is_dc: bool = True,
    frequency: Optional[float] = None,
    pinned_nodes: Optional[Set[str]] = None,
) -> Tuple[Optional[SolutionStep], List[Reduction]]:
    """
    Seri/paralel indirgemeleri eğitici bir SolutionStep'e dönüştürür.

    İndirgeme yoksa (None, []) döner.
    """
    reductions, remaining, open_caps, blockers = reduce_series_parallel(
        parsed, is_dc, frequency, pinned_nodes
    )
    if not reductions:
        return None, []

    equations = []
    for r in reductions:
        a, b = r.elements
        if r.kind == "series":
            equations.append(f"{a} ve {b} seri bağlı → {r.formula}")
        else:
            equations.append(
                f"{a} ∥ {b} (Düğüm {r.nodes[0]}–{r.nodes[1]} arası paralel) "
                f"→ {r.formula}"
            )

    description = (
        "Seri bağlı elemanlar aynı akımı taşır (aralarındaki düğüme başka "
        "eleman bağlı değildir); paralel bağlı elemanlar aynı iki düğüm "
        "arasındadır ve aynı gerilimi görür.\n"
        "Seri: Req = R1 + R2,  Paralel: Req = R1·R2/(R1+R2).\n"
        "Kapasitörlerde kurallar terstir: seri Ceq = C1·C2/(C1+C2), "
        "paralel Ceq = C1 + C2."
    )
    if open_caps:
        description += (
            f"\n\nDC analizde kapasitörler ({', '.join(open_caps)}) açık "
            "devredir — indirgemeye katılmaz."
        )
    if blockers:
        description += (
            f"\n\nDC analizde bobinler ({', '.join(blockers)}) kısa devredir; "
            "bu adımda indirgenmemiştir."
        )
    if pinned_nodes:
        others = sorted(set(pinned_nodes) - {"0"})
        if others:
            description += (
                f"\n\nKaynak/terminal düğümleri ({', '.join(others)}) "
                "korunur, bu düğümler üzerinden seri birleştirme yapılmaz."
            )

    final = [
        f"{b.name}: Düğüm {b.a}–{b.b}"
        + (f", Z = {_fmt_z(b.z)} Ω" if b.z is not None else "")
        for b in remaining if len(b.members) > 1
    ]
    if final:
        equations.append("Kalan eşdeğer kollar: " + "; ".join(final))

    step = SolutionStep(
        step_number=0,
        title="Seri/Paralel Tanıma (Eşdeğer Empedans)",
        description=description,
        equations=equations,
        latex_formula=" \\\\\n".join(r.latex for r in reductions),
        result_snapshot={
            "reductions": [
                {
                    "type": r.kind,
                    "elements": list(r.elements),
                    "result": r.result_name,
                    "nodes": list(r.nodes),
                    "original_elements": r.members,
                }
                for r in reductions
            ]
        },
    )
    return step, reductions


# ═══════════════════════════════════════════════════════
#  PORT EMPEDANSI (Thevenin/Norton direnci) — KAYNAKLAR SIFIRLANMIŞ DEVRE
# ═══════════════════════════════════════════════════════

_SOURCE_TYPES = VOLTAGE_SOURCES   # sıfırlanınca kısa devre olanlar


@dataclass
class PortReduction:
    """
    Terminallerden bakılan eşdeğer empedansın adım adım indirgenmesi.

    zeroing_notes: kaynakların sıfırlanması (ör: "V1 kısa devre edilir…")
    steps:         sırayla indirgemeler; kind = 'series' | 'parallel' | 'removed'
    impedance:     tam indirgenebildiyse sonuç (aksi halde None)
    """
    node_positive: str
    node_negative: str
    zeroing_notes: List[str] = field(default_factory=list)
    steps: List[Reduction] = field(default_factory=list)
    impedance: Optional[complex] = None
    final_name: Optional[str] = None
    complete: bool = False


def reduce_port_impedance(
    parsed: ParsedCircuit,
    node_positive: str,
    node_negative: str,
    is_dc: bool = True,
    frequency: Optional[float] = None,
) -> PortReduction:
    """
    Thevenin direnci (Rth / Zth) için öğrencinin yaptığı işlemi taklit eder:

      1. Bağımsız gerilim kaynakları sıfırlanır → kısa devre (uç düğümleri
         birleşir). DC'de bobinler kısa devre, kondansatörler açık devredir.
      2. İki ucu aynı düğüme düşen eleman (kısa devre edilmiş) ve bir ucu
         boşta kalan eleman akım taşımaz → çıkarılır.
      3. Seri/paralel birleştirme, terminaller arasında tek kol kalana kadar.

    Köprü gibi seri/paralel ile indirgenemeyen devrelerde complete=False döner.
    """
    omega = None if is_dc or not frequency else 2 * math.pi * frequency
    result = PortReduction(node_positive, node_negative)

    # ── 1. Kısa devreler: düğüm birleştirme (Union-Find) ──
    parent = {}

    def find(n):
        parent.setdefault(n, n)
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        # Temsilci: GND her zaman "0" kalsın, yoksa küçük numara
        keep, drop = sorted((ra, rb), key=lambda x: (x != "0", len(x), x))
        parent[drop] = keep

    for e in parsed.elements:
        if e.element_type in _SOURCE_TYPES:
            union(e.node_positive, e.node_negative)
            result.zeroing_notes.append(
                f"{e.id} gerilim kaynağı sıfırlanır → kısa devre (tel) olur: "
                f"Düğüm {e.node_positive} ile Düğüm {e.node_negative} birleşir."
            )
        elif e.element_type in CURRENT_SOURCES:
            result.zeroing_notes.append(
                f"{e.id} akım kaynağı sıfırlanır → açık devre olur (devreden çıkarılır)."
            )
        elif is_dc and e.element_type == ElementType.INDUCTOR:
            union(e.node_positive, e.node_negative)
            result.zeroing_notes.append(
                f"{e.id} DC'de kısa devredir: Düğüm {e.node_positive} ile "
                f"Düğüm {e.node_negative} birleşir."
            )
        elif is_dc and e.element_type == ElementType.CAPACITOR:
            result.zeroing_notes.append(
                f"{e.id} DC'de açık devredir → çıkarılır."
            )

    pos, neg = find(node_positive), find(node_negative)
    result.node_positive, result.node_negative = pos, neg
    if pos == neg:
        result.zeroing_notes.append(
            "Terminaller kısa devre ile birleşti — terminallerden bakılan "
            "empedans sıfırdır."
        )
        result.impedance = 0j
        result.complete = True
        return result

    # ── 2. Kollar (yeniden adlandırılmış düğümlerle) ──
    branches: List[Branch] = []
    for e in parsed.elements:
        kind = _PASSIVE.get(e.element_type)
        if kind is None or (is_dc and kind in ("C", "L")):
            continue
        a, b = find(e.node_positive), find(e.node_negative)
        if kind == "Z":
            z = e.params.get("impedance", complex(e.value))
            branches.append(Branch(e.id, a, b, "Z", z=z, members=[e.id]))
        else:
            branches.append(Branch(e.id, a, b, kind, value=e.value,
                                   z=_impedance(kind, e.value, omega),
                                   members=[e.id]))

    pinned = {pos, neg}
    namer = _Namer()

    def removed(branch: Branch, reason: str):
        result.steps.append(Reduction(
            kind="removed", elements=(branch.name, ""), result_name="",
            result_kind=branch.kind, formula=f"{branch.name} {reason}",
            latex="", nodes=(branch.a, branch.b), impedance=None,
            members=branch.members,
        ))

    # ── 3. İndirgeme döngüsü ──
    changed = True
    while changed:
        changed = False

        # Kısa devre edilmiş eleman (iki ucu aynı düğümde)
        for br in branches:
            if br.a == br.b:
                branches.remove(br)
                removed(br, f"iki ucu da aynı düğüme (Düğüm {br.a}) bağlandı "
                            "(kısa devre edildi) → üzerinden akım geçmez, çıkarılır.")
                changed = True
                break
        if changed:
            continue

        # Bir ucu boşta kalan eleman
        degree = {}
        for br in branches:
            degree[br.a] = degree.get(br.a, 0) + 1
            degree[br.b] = degree.get(br.b, 0) + 1
        for br in branches:
            dangling = [n for n in (br.a, br.b) if degree[n] == 1 and n not in pinned]
            if dangling:
                branches.remove(br)
                removed(br, f"bir ucu (Düğüm {dangling[0]}) boşta kaldı → "
                            "akım taşımaz, çıkarılır.")
                changed = True
                break
        if changed:
            continue

        # Paralel
        for i, b1 in enumerate(branches):
            for b2 in branches[i + 1:]:
                if {b1.a, b1.b} == {b2.a, b2.b}:
                    res = _combine("parallel", b1, b2, b1.a, b1.b, namer)
                    if res is None:
                        continue
                    new, red = res
                    branches = [x for x in branches if x is not b1 and x is not b2]
                    branches.append(new)
                    result.steps.append(red)
                    changed = True
                    break
            if changed:
                break
        if changed:
            continue

        # Seri
        for node in sorted({n for br in branches for n in (br.a, br.b)}):
            if node in pinned:
                continue
            incident = [br for br in branches if node in (br.a, br.b)]
            if len(incident) != 2:
                continue
            b1, b2 = incident
            end1 = b1.b if b1.a == node else b1.a
            end2 = b2.b if b2.a == node else b2.a
            if end1 == node or end2 == node:
                continue
            res = _combine("series", b1, b2, end1, end2, namer)
            if res is None:
                continue
            new, red = res
            branches = [x for x in branches if x is not b1 and x is not b2]
            branches.append(new)
            result.steps.append(red)
            changed = True
            break

    if len(branches) == 1 and {branches[0].a, branches[0].b} == pinned:
        result.complete = True
        result.impedance = branches[0].z
        result.final_name = branches[0].name
    elif not branches:
        # Terminaller arasında hiçbir yol yok → açık devre
        result.complete = True
        result.impedance = None
    return result
