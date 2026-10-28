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

from explainer.formatting import MINUS, num

from models.response import SolutionStep
from parser.netlist_parser import (
    ParsedCircuit, ElementType, VOLTAGE_SOURCES, CURRENT_SOURCES, DEPENDENT_SOURCES,
)


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
    """Tek bir seri/paralel veya Δ–Y/Y–Δ indirgeme adımı."""
    kind: str                # 'series' | 'parallel' | 'delta_y' | 'y_delta' | 'removed'
    elements: Tuple[str, ...]
    result_name: str
    result_kind: str
    formula: str             # düz metin: "Req1 = R1 + R2 = 1000 + 2000 = 3000 Ω"
    latex: str
    nodes: Tuple[str, ...]   # eşdeğer kolun veya dönüşümün düğümleri
    impedance: Optional[complex]
    members: List[str]


def _fmt(x: float) -> str:
    return num(x)


def _fmt_z(z: complex) -> str:
    r, i = z.real, z.imag
    if abs(i) < 1e-12 * max(abs(r), 1.0):
        return _fmt(r)
    if abs(r) < 1e-12 * max(abs(i), 1.0):
        return f"{'-' if i < 0 else ''}j{_fmt(abs(i))}"
    return f"{_fmt(r)}{'+' if i >= 0 else '-'}j{_fmt(abs(i))}"


def _paren(text: str) -> str:
    return f"({text})" if ("+" in text[1:] or "-" in text or MINUS in text) else text


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
    # Bağımlı kaynakların kontrol elemanları (V(R2) / I(R2) ölçüldüğü eleman):
    # başka bir elemanla birleştirilirse kontrol büyüklüğünün anlamı kaybolur
    controls = _control_ids(parsed)
    for e in parsed.elements:
        kind = _PASSIVE.get(e.element_type)
        if kind is None:
            # Kaynak (bağımsız veya bağımlı): düğüm derecesine sayılır ama
            # indirgenmez; bağımlı kaynak bağlı olduğu düğümde seri birleştirmeyi
            # de engeller
            branches.append(Branch(e.id, e.node_positive, e.node_negative,
                                   "SRC", reducible=False, members=[e.id]))
            continue
        if e.id in controls:
            if is_dc and kind == "C":
                open_caps.append(e.id)
                continue
            z = (e.params.get("impedance", complex(e.value)) if kind == "Z"
                 else _impedance(kind, e.value, omega))
            branches.append(Branch(e.id, e.node_positive, e.node_negative, kind,
                                   value=None if kind == "Z" else e.value, z=z,
                                   reducible=False, members=[e.id]))
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


def _control_ids(parsed: ParsedCircuit) -> Set[str]:
    """Bağımlı kaynakların kontrol elemanı olan eleman kimlikleri."""
    return {e.params["control_id"] for e in parsed.elements
            if e.element_type in DEPENDENT_SOURCES}


class _Namer:
    def __init__(self):
        self.counts = {}
        self.y_node_count = 0
        self.star_counts = {}
        self.delta_counts = {}

    def __call__(self, kind: str) -> str:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        return f"{kind}eq{self.counts[kind]}"

    def star_node(self, existing_nodes: Set[str]) -> str:
        while True:
            self.y_node_count += 1
            cand = f"Y{self.y_node_count}"
            if cand not in existing_nodes:
                return cand

    def star_branch(self, kind: str, existing_names: Set[str]) -> str:
        while True:
            self.star_counts[kind] = self.star_counts.get(kind, 0) + 1
            cand = f"{kind}y{self.star_counts[kind]}"
            if cand not in existing_names:
                return cand

    def delta_branch(self, kind: str, existing_names: Set[str]) -> str:
        while True:
            self.delta_counts[kind] = self.delta_counts.get(kind, 0) + 1
            cand = f"{kind}d{self.delta_counts[kind]}"
            if cand not in existing_names:
                return cand


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
                     members=list(dict.fromkeys(b1.members + b2.members)))
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
        new = Branch(name, a, b, "Z", z=z,
                     members=list(dict.fromkeys(b1.members + b2.members)))

    red = Reduction(
        kind=kind, elements=(n1, n2), result_name=new.name,
        result_kind=new.kind, formula=formula, latex=latex,
        nodes=(a, b), impedance=new.z, members=new.members,
    )
    return new, red


def _delta_to_y(
    b12: Branch, b13: Branch, b23: Branch,
    n1: str, n2: str, n3: str, y_node: str,
    namer: _Namer, existing_names: Set[str],
) -> Optional[Tuple[List[Branch], Reduction]]:
    """
    (n1, n2, n3) düğümleri arasındaki üçgen (Δ) bağlı (b12, b13, b23) kollarını
    ortak düğümü y_node olan yıldız (Y) bağlı üç kola dönüştürür.
    """
    na, nb, nc = b12.name, b13.name, b23.name
    members = list(dict.fromkeys(b12.members + b13.members + b23.members))
    new_branches: List[Branch] = []
    f_lines: List[str] = []
    l_lines: List[str] = []

    if b12.kind == "R" and b13.kind == "R" and b23.kind == "R":
        v12, v13, v23 = b12.value, b13.value, b23.value
        denom = v12 + v13 + v23
        if abs(denom) < 1e-15:
            return None
        sym_d = f"{na}+{nb}+{nc}"
        num_d = f"{_fmt(v12)}+{_fmt(v13)}+{_fmt(v23)}"
        lsym_d = f"{na} + {nb} + {nc}"
        lnum_d = f"{_fmt(v12)} + {_fmt(v13)} + {_fmt(v23)}"
        for node, adj1, adj2 in ((n1, b12, b13), (n2, b12, b23), (n3, b13, b23)):
            bname = namer.star_branch("R", existing_names)
            existing_names.add(bname)
            m1, m2 = adj1.name, adj2.name
            u1, u2 = adj1.value, adj2.value
            v = (u1 * u2) / denom
            f_lines.append(
                f"{bname} = {m1}·{m2}/({sym_d}) = "
                f"{_fmt(u1)}·{_fmt(u2)}/({num_d}) = {_fmt(v)} Ω (Düğüm {node}–{y_node})"
            )
            l_lines.append(
                f"{bname} = \\frac{{{m1} \\cdot {m2}}}{{{lsym_d}}} = "
                f"\\frac{{{_fmt(u1)} \\cdot {_fmt(u2)}}}{{{lnum_d}}} = {_fmt(v)} \\text{{ Ω}}"
            )
            new_branches.append(
                Branch(bname, node, y_node, "R", value=v, z=complex(v), members=members)
            )
    else:
        if b12.z is None or b13.z is None or b23.z is None:
            return None
        z12, z13, z23 = b12.z, b13.z, b23.z
        denom = z12 + z13 + z23
        if abs(denom) < 1e-15:
            return None
        lbl = lambda s: s if s[0] in "RZ" else f"Z_{s}"
        xlbl = lambda s: s if s[0] in "RZ" else f"Z_{{{s}}}"
        la, lb, lc = lbl(na), lbl(nb), lbl(nc)
        xa, xb, xc = xlbl(na), xlbl(nb), xlbl(nc)
        ta, tb, tc = _paren(_fmt_z(z12)), _paren(_fmt_z(z13)), _paren(_fmt_z(z23))
        sym_d = f"{la}+{lb}+{lc}"
        num_d = f"{ta}+{tb}+{tc}"
        lsym_d = f"{xa} + {xb} + {xc}"
        for node, adj1, adj2 in ((n1, b12, b13), (n2, b12, b23), (n3, b13, b23)):
            bname = namer.star_branch("Z", existing_names)
            existing_names.add(bname)
            l1, l2 = lbl(adj1.name), lbl(adj2.name)
            x1, x2 = xlbl(adj1.name), xlbl(adj2.name)
            t1, t2 = _paren(_fmt_z(adj1.z)), _paren(_fmt_z(adj2.z))
            z = (adj1.z * adj2.z) / denom
            f_lines.append(
                f"{bname} = {l1}·{l2}/({sym_d}) = "
                f"{t1}·{t2}/({num_d}) = {_fmt_z(z)} Ω (Düğüm {node}–{y_node})"
            )
            l_lines.append(
                f"{bname} = \\frac{{{x1} \\cdot {x2}}}{{{lsym_d}}} = {_fmt_z(z)} \\text{{ Ω}}"
            )
            new_branches.append(
                Branch(bname, node, y_node, "Z", z=z, members=members)
            )

    red = Reduction(
        kind="delta_y",
        elements=(na, nb, nc),
        result_name=", ".join(b.name for b in new_branches),
        result_kind=new_branches[0].kind,
        formula="\n".join(f_lines),
        latex=" \\\\\n".join(l_lines),
        nodes=(n1, n2, n3),
        impedance=None,
        members=members,
    )
    return new_branches, red


def _y_to_delta(
    b1: Branch, b2: Branch, b3: Branch,
    n0: str, n1: str, n2: str, n3: str,
    namer: _Namer, existing_names: Set[str],
) -> Optional[Tuple[List[Branch], Reduction]]:
    """
    n0 ortak düğümüne bağlı (b1: n0–n1, b2: n0–n2, b3: n0–n3) yıldız (Y) kollarını
    (n1, n2, n3) düğümleri arasında üçgen (Δ) bağlı üç kola dönüştürür.
    """
    na, nb, nc = b1.name, b2.name, b3.name
    members = list(dict.fromkeys(b1.members + b2.members + b3.members))
    new_branches: List[Branch] = []
    f_lines: List[str] = []
    l_lines: List[str] = []

    if b1.kind == "R" and b2.kind == "R" and b3.kind == "R":
        v1, v2, v3 = b1.value, b2.value, b3.value
        if min(abs(v1), abs(v2), abs(v3)) < 1e-15:
            return None
        prod_sum = v1 * v2 + v2 * v3 + v3 * v1
        sym_num = f"{na}·{nb} + {nb}·{nc} + {nc}·{na}"
        num_str = f"{_fmt(v1)}·{_fmt(v2)} + {_fmt(v2)}·{_fmt(v3)} + {_fmt(v3)}·{_fmt(v1)}"
        lsym_num = f"{na} \\cdot {nb} + {nb} \\cdot {nc} + {nc} \\cdot {na}"
        lnum_str = (
            f"{_fmt(v1)} \\cdot {_fmt(v2)} + {_fmt(v2)} \\cdot {_fmt(v3)} + "
            f"{_fmt(v3)} \\cdot {_fmt(v1)}"
        )
        for pa, pb, opp in ((n1, n2, b3), (n2, n3, b1), (n1, n3, b2)):
            bname = namer.delta_branch("R", existing_names)
            existing_names.add(bname)
            v = prod_sum / opp.value
            f_lines.append(
                f"{bname} = ({sym_num})/{opp.name} = "
                f"({num_str})/{_fmt(opp.value)} = {_fmt(v)} Ω (Düğüm {pa}–{pb})"
            )
            l_lines.append(
                f"{bname} = \\frac{{{lsym_num}}}{{{opp.name}}} = "
                f"\\frac{{{lnum_str}}}{{{_fmt(opp.value)}}} = {_fmt(v)} \\text{{ Ω}}"
            )
            new_branches.append(
                Branch(bname, pa, pb, "R", value=v, z=complex(v), members=members)
            )
    else:
        if b1.z is None or b2.z is None or b3.z is None:
            return None
        z1, z2, z3 = b1.z, b2.z, b3.z
        if min(abs(z1), abs(z2), abs(z3)) < 1e-15:
            return None
        prod_sum = z1 * z2 + z2 * z3 + z3 * z1
        lbl = lambda s: s if s[0] in "RZ" else f"Z_{s}"
        xlbl = lambda s: s if s[0] in "RZ" else f"Z_{{{s}}}"
        la, lb, lc = lbl(na), lbl(nb), lbl(nc)
        xa, xb, xc = xlbl(na), xlbl(nb), xlbl(nc)
        ta, tb, tc = _paren(_fmt_z(z1)), _paren(_fmt_z(z2)), _paren(_fmt_z(z3))
        sym_num = f"{la}·{lb} + {lb}·{lc} + {lc}·{la}"
        num_str = f"{ta}·{tb} + {tb}·{tc} + {tc}·{ta}"
        lsym_num = f"{xa} \\cdot {xb} + {xb} \\cdot {xc} + {xc} \\cdot {xa}"
        for pa, pb, opp in ((n1, n2, b3), (n2, n3, b1), (n1, n3, b2)):
            bname = namer.delta_branch("Z", existing_names)
            existing_names.add(bname)
            lo, xo, to = lbl(opp.name), xlbl(opp.name), _paren(_fmt_z(opp.z))
            z = prod_sum / opp.z
            f_lines.append(
                f"{bname} = ({sym_num})/{lo} = "
                f"({num_str})/{to} = {_fmt_z(z)} Ω (Düğüm {pa}–{pb})"
            )
            l_lines.append(
                f"{bname} = \\frac{{{lsym_num}}}{{{xo}}} = {_fmt_z(z)} \\text{{ Ω}}"
            )
            new_branches.append(
                Branch(bname, pa, pb, "Z", z=z, members=members)
            )

    red = Reduction(
        kind="y_delta",
        elements=(na, nb, nc),
        result_name=", ".join(b.name for b in new_branches),
        result_kind=new_branches[0].kind,
        formula="\n".join(f_lines),
        latex=" \\\\\n".join(l_lines),
        nodes=(n1, n2, n3),
        impedance=None,
        members=members,
    )
    return new_branches, red


def _node_sort_key(n: str):
    return (n == "0", len(n), n)


def _try_delta_to_y(
    branches: List[Branch],
    pinned: Set[str],
    namer: _Namer,
    forbidden_deltas: Set[frozenset],
    forbidden_stars: Set[str],
    require_helpful: bool = True,
) -> Optional[Tuple[List[Branch], Reduction]]:
    """
    Üç pasif koldan oluşan bir üçgen (Δ) arar ve yıldıza (Y) dönüştürür.
    require_helpful=True ise yalnızca dönüşüm sonrasında en az bir düğümün
    derecesini 2'ye düşürerek seri birleştirmeyi mümkün kılan üçgenleri seçer.
    """
    incident_map = {}
    for br in branches:
        if br.a == br.b:
            continue
        incident_map.setdefault(br.a, []).append(br)
        incident_map.setdefault(br.b, []).append(br)

    def eliminable_deg(n: str) -> int:
        if n in pinned:
            return 0
        inc = incident_map.get(n, [])
        if not inc or not all(b.reducible for b in inc):
            return 0
        return len(inc)

    pair_branch = {}
    for br in branches:
        if br.reducible and br.a != br.b and br.kind in ("R", "L", "C", "Z"):
            pair_branch[frozenset((br.a, br.b))] = br

    nodes = sorted(incident_map.keys(), key=_node_sort_key)
    candidates = []
    for i, n1 in enumerate(nodes):
        for j in range(i + 1, len(nodes)):
            n2 = nodes[j]
            b12 = pair_branch.get(frozenset((n1, n2)))
            if b12 is None:
                continue
            for k in range(j + 1, len(nodes)):
                n3 = nodes[k]
                b13 = pair_branch.get(frozenset((n1, n3)))
                b23 = pair_branch.get(frozenset((n2, n3)))
                if b13 is None or b23 is None:
                    continue
                if frozenset((b12.name, b13.name, b23.name)) in forbidden_deltas:
                    continue
                deg3_count = sum(1 for v in (n1, n2, n3) if eliminable_deg(v) == 3)
        
                deg4_count = sum(1 for v in (n1, n2, n3) if eliminable_deg(v) == 4)
                if require_helpful and deg3_count == 0:
                    continue
                if not require_helpful and deg3_count == 0 and deg4_count == 0:
                    continue
                candidates.append((
                    (-deg3_count, -deg4_count, _node_sort_key(n1), _node_sort_key(n2), _node_sort_key(n3)),
                    (b12, b13, b23, n1, n2, n3),
                ))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    existing_nodes = {n for br in branches for n in (br.a, br.b)}
    existing_names = {br.name for br in branches}

    for _, (b12, b13, b23, n1, n2, n3) in candidates:
        y_node = namer.star_node(existing_nodes)
        res = _delta_to_y(b12, b13, b23, n1, n2, n3, y_node, namer, set(existing_names))
        if res is None:
            continue
        new_brs, red = res
        existing_names.update(b.name for b in new_brs)
        forbidden_stars.add(y_node)
        updated = [x for x in branches if x is not b12 and x is not b13 and x is not b23]
        updated.extend(new_brs)
        return updated, red
    return None


def _try_y_to_delta(
    branches: List[Branch],
    pinned: Set[str],
    namer: _Namer,
    forbidden_deltas: Set[frozenset],
    forbidden_stars: Set[str],
) -> Optional[Tuple[List[Branch], Reduction]]:
    """
    Sabitlenmemiş, kaynak bağlı olmayan ve tam 3 indirgenebilir pasif kola sahip
    bir iç yıldız (Y) düğümünü üçgene (Δ) dönüştürür.
    """
    incident_map = {}
    pair_set = set()
    for br in branches:
        if br.a == br.b:
            continue
        incident_map.setdefault(br.a, []).append(br)
        incident_map.setdefault(br.b, []).append(br)
        if br.reducible:
            pair_set.add(frozenset((br.a, br.b)))

    candidates = []
    for n0 in sorted(incident_map.keys(), key=_node_sort_key):
        if n0 in pinned or n0 in forbidden_stars:
            continue
        inc = incident_map[n0]
        if len(inc) != 3 or not all(b.reducible for b in inc):
            continue
        neighbors = []
        for b in inc:
            other = b.b if b.a == n0 else b.a
            neighbors.append((other, b))
        if len({n0, *(n for n, _ in neighbors)}) != 4:
            continue
        neighbors.sort(key=lambda item: _node_sort_key(item[0]))
        (n1, b1), (n2, b2), (n3, b3) = neighbors
        parallel_hits = sum(
            1 for pa, pb in ((n1, n2), (n2, n3), (n1, n3))
            if frozenset((pa, pb)) in pair_set
        )
        candidates.append(((-parallel_hits, _node_sort_key(n0)), (b1, b2, b3, n0, n1, n2, n3)))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    existing_names = {br.name for br in branches}

    for _, (b1, b2, b3, n0, n1, n2, n3) in candidates:
        res = _y_to_delta(b1, b2, b3, n0, n1, n2, n3, namer, set(existing_names))
        if res is None:
            continue
        new_brs, red = res
        forbidden_deltas.add(frozenset(b.name for b in new_brs))
        updated = [x for x in branches if x is not b1 and x is not b2 and x is not b3]
        updated.extend(new_brs)
        return updated, red
    return None


def _try_star_delta_step(
    branches: List[Branch],
    pinned: Set[str],
    namer: _Namer,
    forbidden_deltas: Set[frozenset],
    forbidden_stars: Set[str],
    conversions_since_sp: int,
) -> Optional[Tuple[List[Branch], Reduction]]:
    """
    Seri/paralel adım kalmadığında sırasıyla:
      1. Doğrudan seri indirgeme açan Δ→Y
      2. İç yıldız düğümü varsa Y→Δ
      3. Yedek Δ→Y (derece 4 düğümü düşürebilecekse ve henüz dönüşüm yapılmadıysa)
    """
    res = _try_delta_to_y(
        branches, pinned, namer, forbidden_deltas, forbidden_stars, require_helpful=True
    )
    if res is not None:
        return res
    res = _try_y_to_delta(
        branches, pinned, namer, forbidden_deltas, forbidden_stars
    )
    if res is not None:
        return res
    if conversions_since_sp == 0:
        return _try_delta_to_y(
            branches, pinned, namer, forbidden_deltas, forbidden_stars, require_helpful=False
        )
    return None


_MAX_CONVERSIONS = 8
_MAX_ITERATIONS = 64


def reduce_series_parallel(
    parsed: ParsedCircuit,
    is_dc: bool = True,
    frequency: Optional[float] = None,
    pinned_nodes: Optional[Set[str]] = None,
    allow_delta_y: bool = True,
) -> Tuple[List[Reduction], List[Branch], List[str], List[str]]:
    """
    Seri/paralel (ve gerekirse Δ–Y / Y–Δ) indirgemeleri bulur.

    Returns:
        (indirgemeler, kalan kollar, DC'de açık sayılan C'ler,
         indirgenemeyen bobinler)
    """
    omega = None if is_dc or not frequency else 2 * math.pi * frequency
    branches, open_caps, blockers = _build_branches(parsed, is_dc, omega)
    pinned = {"0"} | set(pinned_nodes or ())
    namer = _Namer()
    reductions: List[Reduction] = []
    forbidden_deltas: Set[frozenset] = set()
    forbidden_stars: Set[str] = set()
    conversions = 0
    conversions_since_sp = 0
    iterations = 0

    changed = True
    while changed and iterations < _MAX_ITERATIONS:
        iterations += 1
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
                    conversions_since_sp = 0
                    changed = True
                    break
            if changed:
                break
        if changed:
            continue

        # ── Seri: ara düğüme yalnızca iki pasif kol bağlı ──
        nodes = sorted({n for b in branches for n in (b.a, b.b)}, key=_node_sort_key)
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
            conversions_since_sp = 0
            changed = True
            break
        if changed:
            continue

        # ── Δ→Y veya Y→Δ dönüşümü (seri/paralel adım kalmadıysa) ──
        if (allow_delta_y
                and conversions < _MAX_CONVERSIONS
                and conversions_since_sp < 2):
            conv = _try_star_delta_step(
                branches, pinned, namer,
                forbidden_deltas, forbidden_stars, conversions_since_sp,
            )
            if conv is not None:
                branches, red = conv
                reductions.append(red)
                conversions += 1
                conversions_since_sp += 1
                changed = True

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
        parsed, is_dc, frequency, pinned_nodes, allow_delta_y=False
    )
    if not reductions:
        return None, []

    equations = []
    for r in reductions:
        if r.kind == "series":
            a, b = r.elements
            equations.append(f"{a} ve {b} seri bağlı → {r.formula}")
        elif r.kind == "parallel":
            a, b = r.elements
            equations.append(
                f"{a} ∥ {b} (Düğüm {r.nodes[0]}–{r.nodes[1]} arası paralel) "
                f"→ {r.formula}"
            )
        elif r.kind == "delta_y":
            equations.append(
                f"Seri/paralel birleştirme kalmadı; {', '.join(r.elements)} "
                f"üçgen (Δ) bağlı → yıldıza (Y) dönüştürelim:\n{r.formula}"
            )
        elif r.kind == "y_delta":
            equations.append(
                f"Seri/paralel birleştirme kalmadı; {', '.join(r.elements)} "
                f"yıldız (Y) bağlı → üçgene (Δ) dönüştürelim:\n{r.formula}"
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
    dependents = [e.id for e in parsed.elements if e.element_type in DEPENDENT_SOURCES]
    if dependents:
        description += (
            f"\n\nBağımlı kaynaklar ({', '.join(dependents)}) ve kontrol elemanları "
            f"({', '.join(sorted(_control_ids(parsed)))}) indirgemeye katılmaz; bağımlı "
            "kaynağın bağlı olduğu düğümler üzerinden seri birleştirme yapılmaz."
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
    allow_delta_y: bool = True,
) -> PortReduction:
    """
    Thevenin direnci (Rth / Zth) için öğrencinin yaptığı işlemi taklit eder:

      1. Bağımsız gerilim kaynakları sıfırlanır → kısa devre (uç düğümleri
         birleşir). DC'de bobinler kısa devre, kondansatörler açık devredir.
      2. İki ucu aynı düğüme düşen eleman (kısa devre edilmiş) ve bir ucu
         boşta kalan eleman akım taşımaz → çıkarılır.
      3. Seri/paralel birleştirme (ve gerekirse Δ→Y / Y→Δ dönüşümü),
         terminaller arasında tek kol kalana kadar.

    Köprü gibi seri/paralel ile indirgenemeyen devrelerde Δ–Y / Y–Δ kullanılır;
    hiçbir dönüşümle indirgenemeyen devrelerde complete=False döner.
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

    # Bağımlı kaynak varsa seri/paralel indirgeme GEÇERSİZDİR: bağımlı kaynak
    # sıfırlanmaz (kontrol büyüklüğü terminallerden uygulanan test kaynağına
    # tepki verir), Rth saf pasif bir ağ gibi indirgenemez. Hiçbir indirgeme
    # iddia etmeden dön (complete=False).
    dependents = [e for e in parsed.elements if e.element_type in DEPENDENT_SOURCES]
    if dependents:
        for e in dependents:
            result.zeroing_notes.append(
                f"{e.id} bağımlı kaynak olduğu için SIFIRLANMAZ: devrede aktif kalır "
                "(çıkışı kontrol ettiği büyüklüğe bağlı olarak değişir)."
            )
        return result

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
    forbidden_deltas: Set[frozenset] = set()
    forbidden_stars: Set[str] = set()
    conversions = 0
    conversions_since_sp = 0
    iterations = 0

    changed = True
    while changed and iterations < _MAX_ITERATIONS:
        iterations += 1
        changed = False

        # Kısa devre edilmiş eleman (iki ucu aynı düğümde)
        for br in branches:
            if br.a == br.b:
                branches.remove(br)
                removed(br, f"iki ucu da aynı düğüme (Düğüm {br.a}) bağlandı "
                            "(kısa devre edildi) → üzerinden akım geçmez, çıkarılır.")
                conversions_since_sp = 0
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
                conversions_since_sp = 0
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
                    conversions_since_sp = 0
                    changed = True
                    break
            if changed:
                break
        if changed:
            continue

        # Seri
        for node in sorted({n for br in branches for n in (br.a, br.b)}, key=_node_sort_key):
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
            conversions_since_sp = 0
            changed = True
            break
        if changed:
            continue

        # Δ→Y veya Y→Δ dönüşümü (seri/paralel adım kalmadıysa ve henüz tek kol değilse)
        if (allow_delta_y
                and not (len(branches) == 1 and {branches[0].a, branches[0].b} == pinned)
                and conversions < _MAX_CONVERSIONS
                and conversions_since_sp < 2):
            conv = _try_star_delta_step(
                branches, pinned, namer,
                forbidden_deltas, forbidden_stars, conversions_since_sp,
            )
            if conv is not None:
                branches, red = conv
                result.steps.append(red)
                conversions += 1
                conversions_since_sp += 1
                changed = True

    if len(branches) == 1 and {branches[0].a, branches[0].b} == pinned:
        result.complete = True
        result.impedance = branches[0].z
        result.final_name = branches[0].name
    elif not branches:
        # Terminaller arasında hiçbir yol yok → açık devre
        result.complete = True
        result.impedance = None
    return result
