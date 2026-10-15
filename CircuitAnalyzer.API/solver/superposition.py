"""
CircuitAnalyzer API — Süperpozisyon Yöntemi

Doğrusal bir devrede her bağımsız kaynağın etkisi ayrı ayrı bulunup
toplanır. Her alt devrede yalnızca bir kaynak aktiftir; diğerleri sıfırlanır:
    gerilim kaynağı → kısa devre (0 V),   akım kaynağı → açık devre (çıkarılır)

★ Her kaynak KENDİ frekansında çözülür:
    DC kaynak → DC analiz,  SINE kaynak → kendi frekansı,
    AC_PHASOR kaynak → istekteki (global) frekans.
  Böylece farklı frekanslı kaynaklar içeren devreler de doğru çözülür:
  aynı frekanstaki katkılar fazör olarak, farklı olanlar zaman domeninde
  toplanır.
"""

import copy
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from parser.netlist_parser import (
    CURRENT_SOURCES, DC_SOURCES, SINE_SOURCES, VOLTAGE_SOURCES,
    ParsedCircuit, ParsedElement,
)


@dataclass
class Contribution:
    source: ParsedElement
    is_dc: bool
    frequency: Optional[float]           # Hz (DC için None)
    zeroed: List[str]                    # "V2 → kısa devre" gibi açıklamalar
    parsed: ParsedCircuit                # alt devre (anlatım için)
    node_voltages: Dict[str, complex] = field(default_factory=dict)
    element_currents: Dict[str, complex] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def frequency_key(self) -> float:
        return 0.0 if self.is_dc else float(self.frequency or 0.0)


def _source_frequency(e: ParsedElement, global_frequency: Optional[float]) -> Optional[float]:
    if e.element_type in DC_SOURCES:
        return None
    if e.element_type in SINE_SOURCES and e.params.get("frequency", 0) > 0:
        return float(e.params["frequency"])
    return global_frequency


def build_subcircuits(
    parsed: ParsedCircuit, global_frequency: Optional[float]
) -> List[Contribution]:
    """Her bağımsız kaynak için 'yalnız o kaynak aktif' alt devresini kurar."""
    sources = [e for e in parsed.elements
               if e.element_type in VOLTAGE_SOURCES + CURRENT_SOURCES
               and abs(e.params.get("amplitude", e.value)) > 0]
    contributions = []
    for active in sources:
        sub = copy.deepcopy(parsed)
        sub.probes = []
        zeroed = []
        kept = []
        for e in sub.elements:
            if e.id == active.id or e.element_type not in VOLTAGE_SOURCES + CURRENT_SOURCES:
                kept.append(e)
            elif e.element_type in VOLTAGE_SOURCES:
                # Kısa devre: 0 V'luk DC kaynak (tel gibi davranır, akımı ölçülebilir)
                e.value = 0.0
                e.params = {"superposition_zeroed": True}   # anlatım için işaret
                e.element_type = DC_SOURCES[0]
                kept.append(e)
                zeroed.append(f"{e.id} gerilim kaynağı → kısa devre")
            else:
                zeroed.append(f"{e.id} akım kaynağı → açık devre (çıkarıldı)")
        sub.elements = kept
        freq = _source_frequency(active, global_frequency)
        contributions.append(Contribution(
            source=active,
            is_dc=active.element_type in DC_SOURCES,
            frequency=freq,
            zeroed=zeroed,
            parsed=sub,
        ))
    return contributions


def solve_contributions(
    parsed: ParsedCircuit, global_frequency: Optional[float]
) -> List[Contribution]:
    """Her alt devreyi lcapy ile çözer (ham sayılar)."""
    # Döngüsel içe aktarmayı önlemek için yerel import
    from lcapy import Circuit
    from parser.netlist_parser import to_lcapy_netlist
    from solver.circuit_solver import _extract_numeric

    contributions = build_subcircuits(parsed, global_frequency)
    for c in contributions:
        if not c.is_dc and c.frequency is None:
            c.error = f"{c.source.id} için frekans bilinmiyor."
            continue
        try:
            cct = Circuit(to_lcapy_netlist(c.parsed, c.frequency))
            nodes = {n for e in c.parsed.elements for n in (e.node_positive, e.node_negative)}
            c.node_voltages["0"] = 0j
            for n in nodes - {"0"}:
                c.node_voltages[n] = complex(_extract_numeric(cct[n].V, c.is_dc, c.frequency))
            for e in c.parsed.elements:
                i = complex(_extract_numeric(cct[e.id].I, c.is_dc, c.frequency))
                if e.element_type in CURRENT_SOURCES:
                    i = -i   # bkz. circuit_solver: lcapy'ye uçlar ters yazılır
                c.element_currents[e.id] = i
        except Exception as ex:   # pragma: no cover - lcapy hata ayrıntısı
            c.error = f"{c.source.id} alt devresi çözülemedi: {ex}"
    return contributions


def phasor_sum(contributions: List[Contribution], key: str, kind: str) -> Dict[float, complex]:
    """
    Bir düğüm/elemanın katkılarını frekansa göre toplar.
    kind: 'v' (düğüm gerilimi) veya 'i' (eleman akımı).
    Dönen sözlük: {frekans (DC=0): toplam fazör}
    """
    totals: Dict[float, complex] = {}
    for c in contributions:
        if c.error:
            continue
        table = c.node_voltages if kind == "v" else c.element_currents
        if key in table:
            totals[c.frequency_key] = totals.get(c.frequency_key, 0j) + table[key]
    return totals


def omega_of(frequency_key: float) -> float:
    return 2 * math.pi * frequency_key
