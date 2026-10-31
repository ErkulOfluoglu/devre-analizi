"""
CircuitAnalyzer API — Sayısal AC (fazör) devre çözücüsü

lcapy'nin yerine, karmaşık sayılarla doğrudan düğüm denklemleri (MNA) kurup çözen küçük çözücü.
lcapy, farklı fazlı kaynak + karmaşık empedans (Z) içeren devrelerde yanlış sonuç veriyor ve
sembolik sadeleştirmede dakikalarca takılıyor; burada sonuç milisaniyede ve sayısal olarak çıkar.

Arayüz lcapy devresine benzer (circuit_solver bu nesneyi `cct` yerine kullanır):
    cct[düğüm].V          düğüm gerilimi (karmaşık)
    cct[eleman].I         eleman akımı (lcapy işaret kuralıyla; aşağıya bakın)
    cct.thevenin(a, b)    .V (açık devre gerilimi), .Z (Thevenin empedansı)
    cct.norton(a, b)      .Isc, .Voc, .Y

İşaret kuralları lcapy ile aynıdır (to_lcapy_netlist ile uyumlu):
    • Her iki uçlu elemanın akımı n+ → n− (pasif işaret kuralı); gerilim kaynağı güç verirken
      akımı negatiftir.
    • Bağımsız akım kaynağı: SPICE'ta kaynak İÇİNDEN n+ → n− akar, devreye n− ucundan verir.
      lcapy'ye uçlar ters yazıldığı için cct[id].I = −(kaynak değeri) döner; lcapy_element_current
      işareti çevirir. Burada da aynı değer döner.
    • Gizli ölçüm kaynakları (Vsense_…): akım = o elemanın içinden n+ → n− akım.
    • Transformatör: ölçüm kaynakları uca GİREN akımı verir (I₁ p+ ucundan, I₂ s+ ucundan girer).

Desteklenmeyen bir eleman ya da durum varsa NumericAcUnsupported fırlatılır; çağıran eski (lcapy)
yola döner.
"""

import copy
import cmath
import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from parser.netlist_parser import (
    ParsedCircuit, ParsedElement, ElementType,
    CURRENT_SOURCES, VOLTAGE_SOURCES,
    circuit_at_time, has_switches, element_nodes,
    lcapy_sense_map, lcapy_transformer_map, transformer_floating_ties, transformers,
)


class NumericAcUnsupported(Exception):
    """Devre bu çözücüyle çözülemez (bilinmeyen eleman, DC kaynak, frekans yok …)."""


_SUPPORTED = (
    ElementType.RESISTOR, ElementType.CAPACITOR, ElementType.INDUCTOR, ElementType.IMPEDANCE,
    ElementType.DC_SOURCE, ElementType.AC_SOURCE_SINE, ElementType.AC_SOURCE_PHASOR,
    ElementType.CURRENT_DC, ElementType.CURRENT_AC_SINE, ElementType.CURRENT_AC_PHASOR,
    ElementType.VCVS, ElementType.VCCS, ElementType.CCVS, ElementType.CCCS,
    ElementType.TRANSFORMER,
)
# Tekil sayılacak koşul sayısı (çözülemeyen sistem lcapy'deki gibi "not invertible" hatası verir)
_MAX_CONDITION = 1e15
# Gürültü temizliği: en büyük değere göre bu orandan küçük gerçek/sanal kısımlar sıfırlanır
_NOISE = 1e-13


def unsupported_reason(parsed: ParsedCircuit, frequency: Optional[float]) -> Optional[str]:
    """Çözücü bu devreyi çözemiyorsa nedeni (kısa İngilizce/Türkçe teknik not), çözebiliyorsa None."""
    has_frequency = frequency is not None and math.isfinite(frequency) and frequency > 0
    for e in parsed.elements:
        reactive = e.element_type in (ElementType.CAPACITOR, ElementType.INDUCTOR) or (
            e.element_type == ElementType.TRANSFORMER and e.params.get("kind") != "IDEAL")
        if reactive and not has_frequency:
            return "frekans yok (bobin/kondansatör var)"
        if e.element_type not in _SUPPORTED and e.element_type != ElementType.SWITCH:
            return f"{e.id}: desteklenmeyen eleman ({e.element_type.value})"
        if e.element_type in (ElementType.DC_SOURCE, ElementType.CURRENT_DC) and e.value != 0:
            return f"{e.id}: AC çözümde sıfırdan farklı DC kaynak"
        if e.element_type == ElementType.RESISTOR and e.value == 0:
            return f"{e.id}: sıfır direnç"
    return None


def _unit_phasor(degrees: float) -> complex:
    """e^{jθ}; 90°'nin katlarında tam değer (cos 90° = 6e-17 gürültüsü olmasın)."""
    r = degrees % 360.0
    exact = {0.0: 1 + 0j, 90.0: 1j, 180.0: -1 + 0j, 270.0: -1j}
    return exact.get(r) or cmath.exp(1j * math.radians(degrees))


def source_phasor(elem: ParsedElement) -> complex:
    """Bağımsız kaynağın fazörü (to_lcapy_netlist ile aynı büyüklük ve açı, açı yuvarlaması olmadan)."""
    if elem.element_type in (ElementType.DC_SOURCE, ElementType.CURRENT_DC):
        return complex(elem.value)
    if "exact_rect" in elem.params:
        return complex(elem.params["exact_rect"])
    amp = elem.params.get("amplitude", elem.value)
    return amp * _unit_phasor(elem.params.get("phase", 0))


def prefers_numeric(parsed: ParsedCircuit, is_dc: bool, frequency: Optional[float]) -> bool:
    """
    AC devre bu çözücüyle mi çözülsün? Karmaşık empedans (Z) içeren AC devrelerde lcapy yavaş
    (saniyeler–dakikalar; sembolik sadeleştirme) ve farklı fazlı kaynaklarla birlikte yanlış
    sonuç verebiliyor; Z içermeyen devrelerde lcapy hızlı ve doğru olduğundan o yol aynen kalır.
    """
    if is_dc or not any(e.element_type == ElementType.IMPEDANCE for e in parsed.elements):
        return False
    return unsupported_reason(parsed, frequency) is None


def make_circuit(parsed: ParsedCircuit, is_dc: bool, frequency: Optional[float], lcapy_text: str):
    """Uygunsa sayısal AC devresi, değilse lcapy devresi (lcapy_text ile) döndürür."""
    if prefers_numeric(parsed, is_dc, frequency):
        return NumericCircuit(parsed, frequency)
    from lcapy import Circuit
    return Circuit(lcapy_text)


class _Solution:
    """Çözülmüş devre: düğüm gerilimleri ve eleman/ölçüm akımları (karmaşık)."""

    def __init__(self, volts: Dict[str, complex], currents: Dict[str, complex]):
        self.volts = volts
        self.currents = currents


def _clean(z: complex, scale: float) -> complex:
    re, im = z.real, z.imag
    limit = _NOISE * max(abs(z), scale)
    return complex(0.0 if abs(re) < limit else re, 0.0 if abs(im) < limit else im)


def _solve(parsed: ParsedCircuit, frequency: float) -> _Solution:
    """Devrenin tüm düğüm gerilimlerini ve eleman akımlarını (n+ → n−) çözer."""
    if has_switches(parsed):
        parsed = circuit_at_time(parsed, "after")
    reason = unsupported_reason(parsed, frequency)
    if reason:
        raise NumericAcUnsupported(reason)

    w = 2.0 * math.pi * frequency if frequency else 0.0
    elems = list(parsed.elements)
    by_id = {e.id: e for e in elems}
    ties = transformer_floating_ties(parsed)

    nodes: List[str] = []
    for e in elems:
        for n in element_nodes(e):
            if n != "0" and n not in nodes:
                nodes.append(n)
    for n in ties:
        if n != "0" and n not in nodes:
            nodes.append(n)
    index = {n: i for i, n in enumerate(nodes)}
    n_nodes = len(nodes)

    # Bilinmeyenler: düğüm gerilimleri + (gerilim benzeri elemanların) kol akımları
    branch_of: Dict[str, int] = {}          # eleman -> kol akımı sütunu (n+ → n−)
    branch_count = 0
    for e in elems:
        t = e.element_type
        if t in VOLTAGE_SOURCES or t in (ElementType.VCVS, ElementType.CCVS):
            branch_of[e.id] = n_nodes + branch_count
            branch_count += 1
        elif t == ElementType.TRANSFORMER:
            branch_of[e.id + "#p"] = n_nodes + branch_count
            branch_of[e.id + "#s"] = n_nodes + branch_count + 1
            branch_count += 2
        elif ((t == ElementType.INDUCTOR and e.value == 0)
              or (t == ElementType.IMPEDANCE and e.params.get("impedance", e.value) == 0)):
            branch_of[e.id] = n_nodes + branch_count        # sıfır empedans = tel
            branch_count += 1
    tie_cols = []
    for _ in ties:
        tie_cols.append(n_nodes + branch_count)
        branch_count += 1

    size = n_nodes + branch_count
    A = np.zeros((size, size), dtype=complex)
    b = np.zeros(size, dtype=complex)
    row_counter = [n_nodes]

    def col(n: str) -> Optional[int]:
        return None if n == "0" else index[n]

    def add(r: Optional[int], c: Optional[int], v: complex) -> None:
        if r is not None and c is not None:
            A[r, c] += v

    def admittance(na: str, nb: str, y: complex) -> None:
        ra, rb = col(na), col(nb)
        add(ra, ra, y)
        add(rb, rb, y)
        add(ra, rb, -y)
        add(rb, ra, -y)

    def kcl_branch(na: str, nb: str, c: int) -> None:
        """Kol akımı na'dan nb'ye elemanın içinden akar: na'dan çıkar, nb'ye girer."""
        add(col(na), c, 1)
        add(col(nb), c, -1)

    def new_row() -> int:
        r = row_counter[0]
        row_counter[0] += 1
        return r

    def voltage_row(r: int, na: str, nb: str, scale: complex = 1.0) -> None:
        """r. satıra scale·(V_na − V_nb) ekler."""
        add(r, col(na), scale)
        add(r, col(nb), -scale)

    def current_terms(e: ParsedElement, depth: int = 0) -> Tuple[List[Tuple[int, complex]], complex]:
        """Elemanın n+ → n− akımı = Σ katsayı·bilinmeyen + sabit."""
        if depth > 20:
            raise NumericAcUnsupported("kontrol zinciri çok uzun")
        t = e.element_type
        np_, nn = e.node_positive, e.node_negative
        if t in (ElementType.RESISTOR, ElementType.CAPACITOR, ElementType.INDUCTOR,
                 ElementType.IMPEDANCE) and e.id not in branch_of:
            y = _admittance_of(e, w)
            terms = []
            if col(np_) is not None:
                terms.append((col(np_), y))
            if col(nn) is not None:
                terms.append((col(nn), -y))
            return terms, 0j
        if e.id in branch_of:
            return [(branch_of[e.id], 1.0 + 0j)], 0j
        if t in CURRENT_SOURCES:
            return [], source_phasor(e)
        if t == ElementType.VCCS:
            g = e.params["gain"] * e.params["control_sign"]
            c = by_id[e.params["control_id"]]
            terms = []
            if col(c.node_positive) is not None:
                terms.append((col(c.node_positive), complex(g)))
            if col(c.node_negative) is not None:
                terms.append((col(c.node_negative), complex(-g)))
            return terms, 0j
        if t == ElementType.CCCS:
            g = e.params["gain"] * e.params["control_sign"]
            terms, const = current_terms(by_id[e.params["control_id"]], depth + 1)
            return [(c, g * v) for c, v in terms], g * const
        raise NumericAcUnsupported(f"{e.id}: akım ifadesi kurulamadı")

    def stamp_current(np_: str, nn: str, terms, const: complex) -> None:
        """İçinden n+ → n− akan akım kaynağı: n+'dan çıkar, n−'ye girer."""
        for c, v in terms:
            add(col(np_), c, v)
            add(col(nn), c, -v)
        if col(np_) is not None:
            b[col(np_)] -= const
        if col(nn) is not None:
            b[col(nn)] += const

    for e in elems:
        t = e.element_type
        np_, nn = e.node_positive, e.node_negative
        if t in (ElementType.RESISTOR, ElementType.CAPACITOR, ElementType.INDUCTOR,
                 ElementType.IMPEDANCE) and e.id not in branch_of:
            admittance(np_, nn, _admittance_of(e, w))
        elif e.id in branch_of and t in (ElementType.INDUCTOR, ElementType.IMPEDANCE):
            c = branch_of[e.id]
            kcl_branch(np_, nn, c)
            voltage_row(new_row(), np_, nn)
        elif t in VOLTAGE_SOURCES:
            c = branch_of[e.id]
            kcl_branch(np_, nn, c)
            r = new_row()
            voltage_row(r, np_, nn)
            b[r] += source_phasor(e)
        elif t in CURRENT_SOURCES:
            stamp_current(np_, nn, [], source_phasor(e))
        elif t == ElementType.VCVS:
            c = branch_of[e.id]
            kcl_branch(np_, nn, c)
            r = new_row()
            ctrl = by_id[e.params["control_id"]]
            voltage_row(r, np_, nn)
            voltage_row(r, ctrl.node_positive, ctrl.node_negative,
                        -e.params["gain"] * e.params["control_sign"])
        elif t == ElementType.CCVS:
            c = branch_of[e.id]
            kcl_branch(np_, nn, c)
            r = new_row()
            voltage_row(r, np_, nn)
            g = e.params["gain"] * e.params["control_sign"]
            terms, const = current_terms(by_id[e.params["control_id"]])
            for cc, v in terms:
                add(r, cc, -g * v)
            b[r] += g * const
        elif t in (ElementType.VCCS, ElementType.CCCS):
            terms, const = current_terms(e)
            stamp_current(np_, nn, terms, const)
        elif t == ElementType.TRANSFORMER:
            p = e.params
            c1, c2 = branch_of[e.id + "#p"], branch_of[e.id + "#s"]
            sp, sn = p["s_pos"], p["s_neg"]
            kcl_branch(np_, nn, c1)
            kcl_branch(sp, sn, c2)
            r1, r2 = new_row(), new_row()
            if p["kind"] == "IDEAL":
                a = p["a"]
                voltage_row(r1, sp, sn)
                voltage_row(r1, np_, nn, -a)
                A[r2, c1] += 1
                A[r2, c2] += a
            else:
                m = p["k"] * math.sqrt(p["l1"] * p["l2"])
                voltage_row(r1, np_, nn)
                A[r1, c1] -= 1j * w * p["l1"]
                A[r1, c2] -= 1j * w * m
                voltage_row(r2, sp, sn)
                A[r2, c1] -= 1j * w * m
                A[r2, c2] -= 1j * w * p["l2"]
    for node, c in zip(ties, tie_cols):
        kcl_branch(node, "0", c)
        voltage_row(new_row(), node, "0")

    if size:
        try:
            cond = np.linalg.cond(A)
        except np.linalg.LinAlgError:
            cond = math.inf
        if not math.isfinite(cond) or cond > _MAX_CONDITION:
            raise ValueError("MNA A matrix is not invertible")
        try:
            x = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            raise ValueError("MNA A matrix is not invertible")
        if not np.all(np.isfinite(x)):
            raise ValueError("MNA A matrix is not invertible")
    else:
        x = np.zeros(0, dtype=complex)

    v_scale = max([abs(x[i]) for i in range(n_nodes)] + [0.0])
    volts = {"0": 0j}
    for n, i in index.items():
        volts[n] = _clean(complex(x[i]), v_scale)

    currents: Dict[str, complex] = {}
    raw: Dict[str, complex] = {}
    for e in elems:
        if e.element_type == ElementType.TRANSFORMER:
            continue
        terms, const = current_terms(e)
        raw[e.id] = sum((v * x[c] for c, v in terms), 0j) + const
    i_scale = max([abs(v) for v in raw.values()] + [0.0])
    for eid, value in raw.items():
        currents[eid] = _clean(complex(value), i_scale)
    tmap = lcapy_transformer_map(parsed)
    for e in transformers(parsed):
        currents[tmap[e.id]["vp"]] = _clean(complex(x[branch_of[e.id + "#p"]]), i_scale)
        currents[tmap[e.id]["vs"]] = _clean(complex(x[branch_of[e.id + "#s"]]), i_scale)
    # Gizli ölçüm kaynakları: akım = elemanın içinden n+ → n− akım
    for eid, (sense_name, _) in lcapy_sense_map(parsed).items():
        currents[sense_name] = currents[eid]
    # lcapy'ye bağımsız akım kaynağı uçları ters yazılır: cct[id].I = −(kaynak değeri)
    for e in elems:
        if e.element_type in CURRENT_SOURCES:
            currents[e.id] = -currents[e.id]
    return _Solution(volts, currents)


def _admittance_of(e: ParsedElement, w: float) -> complex:
    t = e.element_type
    if t == ElementType.RESISTOR:
        return 1.0 / e.value
    if t == ElementType.CAPACITOR:
        return 1j * w * e.value
    if t == ElementType.INDUCTOR:
        return 1.0 / (1j * w * e.value)
    return 1.0 / complex(e.params.get("impedance", complex(e.value, 0)))


class _Handle:
    """cct[anahtar]: düğüm ya da eleman; `.V` ve `.I` lcapy gibi okunur."""

    def __init__(self, solution: _Solution, key: str):
        self._s = solution
        self._key = key

    @property
    def V(self) -> complex:
        if self._key in self._s.volts:
            return self._s.volts[self._key]
        raise KeyError(f"'{self._key}' düğümü bulunamadı")

    @property
    def I(self) -> complex:
        if self._key in self._s.currents:
            return self._s.currents[self._key]
        raise KeyError(f"'{self._key}' elemanı bulunamadı")


class PortEquivalent:
    """Thevenin / Norton sonucu: lcapy nesnesinin kullanılan alanları (karmaşık sayılar)."""

    def __init__(self, voc: complex, zth: Optional[complex], isc: Optional[complex],
                 y: Optional[complex]):
        self.V = voc
        self.Voc = voc
        self.Z = zth
        self.Isc = isc
        self.Y = y


class NumericCircuit:
    """lcapy Circuit yerine geçen sayısal AC devresi (bkz. modül açıklaması)."""

    def __init__(self, parsed: ParsedCircuit, frequency: Optional[float]):
        if has_switches(parsed):
            parsed = circuit_at_time(parsed, "after")
        reason = unsupported_reason(parsed, frequency)
        if reason:
            raise NumericAcUnsupported(reason)
        self.parsed = parsed
        self.frequency = frequency
        self._solution: Optional[_Solution] = None
        self._error: Optional[Exception] = None

    def solution(self) -> _Solution:
        if self._error is not None:
            raise self._error
        if self._solution is None:
            try:
                self._solution = _solve(self.parsed, self.frequency)
            except ValueError as e:
                self._error = e
                raise
        return self._solution

    def __getitem__(self, key: str) -> _Handle:
        return _Handle(self.solution(), key)

    # ── Port eşdeğerleri ──
    def _fresh(self, base: str) -> str:
        used = {e.id.upper() for e in self.parsed.elements}
        name = base
        while name.upper() in used:
            name += "_"
        return name

    def _with(self, zero_sources: bool, extra: ParsedElement) -> "NumericCircuit":
        sub = copy.deepcopy(self.parsed)
        sub.probes = []
        if zero_sources:
            for e in sub.elements:
                if e.element_type in VOLTAGE_SOURCES:
                    e.element_type, e.value, e.params = ElementType.DC_SOURCE, 0.0, {}
                elif e.element_type in CURRENT_SOURCES:
                    e.element_type, e.value, e.params = ElementType.CURRENT_DC, 0.0, {}
        sub.elements.append(extra)
        return NumericCircuit(sub, self.frequency)

    def _port_voltage(self, a: str, b: str) -> complex:
        sol = self.solution()
        if a not in sol.volts or b not in sol.volts:
            raise KeyError("Düğüm devrede bulunamadı (not found)")
        return sol.volts[a] - sol.volts[b]

    def short_circuit_current(self, a: str, b: str) -> complex:
        """a ve b arası 0 V'luk telle bağlanır; telden a → b akan akım."""
        self._port_voltage(a, b)
        wire = ParsedElement(id=self._fresh("Vsc_port"), element_type=ElementType.DC_SOURCE,
                             node_positive=a, node_negative=b, value=0.0)
        return self._with(False, wire).solution().currents[wire.id]

    def thevenin_impedance(self, a: str, b: str) -> complex:
        """Bağımsız kaynaklar sıfırlanıp a'ya 1 A girilir (b'den çıkar): Zth = V_ab / 1 A."""
        self._port_voltage(a, b)
        test = ParsedElement(id=self._fresh("Itest_port"), element_type=ElementType.CURRENT_AC_PHASOR,
                             node_positive=b, node_negative=a, value=1.0,
                             params={"amplitude": 1.0, "phase": 0.0})
        try:
            sol = self._with(True, test).solution()
        except ValueError as e:
            # Test akımı bir yere akamıyor: terminallerden bakılan empedans sonsuz
            from solver.circuit_solver import InfiniteImpedanceError
            if "invertible" in str(e):
                raise InfiniteImpedanceError("Empedans sonsuz (açık devre).") from e
            raise
        return sol.volts[a] - sol.volts[b]

    def thevenin(self, a: str, b: str) -> PortEquivalent:
        voc = self._port_voltage(a, b)
        return PortEquivalent(voc, self.thevenin_impedance(a, b), None, None)

    def norton(self, a: str, b: str) -> PortEquivalent:
        voc = self._port_voltage(a, b)
        isc = self.short_circuit_current(a, b)
        # Yn: kaynaklar sıfırlanıp a–b uçlarına 1 V uygulanır; devreye giren akım
        src = ParsedElement(id=self._fresh("Vtest_port"), element_type=ElementType.AC_SOURCE_PHASOR,
                            node_positive=a, node_negative=b, value=1.0,
                            params={"amplitude": 1.0, "phase": 0.0})
        y = -self._with(True, src).solution().currents[src.id]
        return PortEquivalent(voc, None, isc, y)
