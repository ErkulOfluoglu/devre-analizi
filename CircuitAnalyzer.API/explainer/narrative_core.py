"""
Türkçe anlatımın ortak veri yapıları (_Ctx, _Section, PortCircuit, PortExtras) ve temel yardımcıları.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from explainer.formatting import eng, num, paren, polar, rect
from models.request import AnalysisType, TheveninTerminals
from models.response import AnalysisResults, ExplanationBlock, ExplanationSection
from parser.netlist_parser import (
    ALL_SOURCES, DEPENDENT_SOURCES, ElementType, ParsedCircuit, ParsedElement,
)


_SOURCES = ALL_SOURCES
_UNITS = {
    ElementType.RESISTOR: "Ω",
    ElementType.CAPACITOR: "F",
    ElementType.INDUCTOR: "H",
}

# Türetme ile çözücü sonucu arasında izin verilen bağıl fark
_REL_TOL = 1e-6


@dataclass
class PortCircuit:
    """
    Kısa devre / test kaynağı için yeniden çözülen devre (anlatımda denklemleri
    gösterilir). source_id: eklenen yardımcı kaynağın İÇ adı — öğrenciye gösterilmez.
    """
    parsed: ParsedCircuit
    source_id: str
    node_voltages: Dict[str, complex]
    element_currents: Dict[str, complex]


@dataclass
class PortExtras:
    """
    Bağımlı kaynaklı devrede Thevenin/Norton için çözücünün ek sayıları
    (circuit_solver._solve_port_extras): bağımlı kaynak SIFIRLANMAZ.

    isc:    terminaller kısa devre edilince (+ → −) telden geçen akım
    i_test: bağımsız kaynaklar sıfırlanıp terminallere v_test = 1 (V) test kaynağı
            bağlanınca kaynağın devreye (+ uçtan) verdiği akım
    sc_circuit / test_circuit: bu sayıların bulunduğu devre (denklemleri anlatmak için)
    """
    isc: Optional[complex] = None
    i_test: Optional[complex] = None
    v_test: complex = 1 + 0j
    sc_circuit: Optional[PortCircuit] = None
    test_circuit: Optional[PortCircuit] = None


def port_is_dead(vth: complex, isc: Optional[complex], nodes, currents) -> bool:
    """
    Açık devre gerilimi ve kısa devre akımı (bağıl olarak) sıfır mı? Öyleyse
    Rth = Vth/In = 0/0 belirsizdir ve test kaynağı yöntemi gerekir.
    """
    v_scale = max((abs(complex(v)) for v in nodes.values()), default=0.0)
    i_scale = max((abs(complex(i)) for i in currents.values()), default=0.0)
    return (abs(vth) <= 1e-9 * v_scale + 1e-12
            and (isc is None or abs(isc) <= 1e-9 * i_scale + 1e-15))


# ═══════════════════════════════════════════════════════
#  YARDIMCI YAPILAR
# ═══════════════════════════════════════════════════════

class _Section:
    def __init__(self, title: str):
        self.title = title
        self.blocks: List[ExplanationBlock] = []

    def text(self, t: str):
        self.blocks.append(ExplanationBlock(kind="text", text=t))

    def math(self, t: str):
        self.blocks.append(ExplanationBlock(kind="math", text=t))

    def result(self, t: str):
        self.blocks.append(ExplanationBlock(kind="result", text=t))

    def note(self, t: str):
        self.blocks.append(ExplanationBlock(kind="note", text=t))

    def check(self, t: str):
        self.blocks.append(ExplanationBlock(kind="check", text=t))

    def build(self) -> ExplanationSection:
        return ExplanationSection(title=self.title, blocks=self.blocks)


def elem_name(e: ParsedElement) -> str:
    """
    Anlatımdaki adı. Thevenin/Norton'da eklenen yardımcı kaynakların iç adı
    (Vsc_port…, Vtest_port…) öğrenciye gösterilmez: 'kısa devre teli' / 'V_test'.
    """
    role = e.params.get("port_role") if e.params else None
    if role == "short":
        return "kısa devre teli"
    if role == "test":
        return "V_test"
    return e.id


def _close(a: complex, b: complex, rel: float = _REL_TOL) -> bool:
    return abs(complex(a) - complex(b)) <= rel * max(abs(a), abs(b), 1e-9) + 1e-12


@dataclass
class _Ctx:
    parsed: ParsedCircuit
    is_dc: bool
    frequency: Optional[float]
    omega: Optional[float]
    analysis_type: AnalysisType
    terminals: Optional[TheveninTerminals]
    v: Dict[str, complex]            # çözülmüş düğüm gerilimleri (ham)
    i: Dict[str, complex]            # eleman akımları (ham, pasif işaret kuralı)
    results: AnalysisResults
    mesh: Optional[object] = None    # doğrulanmış MeshAnalysis (MESH yönteminde)
    known: Dict[str, complex] = field(default_factory=dict)
    groups: List[List[str]] = field(default_factory=list)
    constraints: list = field(default_factory=list)
    # Bağımlı kaynaklı devrede düğüm denklem sistemi (explainer.dependent_nodal) ya da
    # kurulamadıysa sebebi; Thevenin/Norton için kısa devre/test kaynağı sayıları
    dep_system: Optional[object] = None
    dep_reason: str = ""
    port: Optional["PortExtras"] = None
    # Norton: kısa devre akımının türetmesi In adımında gösterildi (Rn adımı tekrar etmez)
    isc_derived: bool = False
    # Karşıtlık teoremi: çözücünün ikinci çözümünden gelen ReciprocityAnalysis (tanıtımda kullanılır)
    reciprocity: Optional[object] = None

    # ── Eleman bilgileri ──

    @property
    def is_rms(self) -> bool:
        return getattr(self.parsed, "value_basis", "PEAK") == "RMS"

    @property
    def elements(self) -> List[ParsedElement]:
        return self.parsed.elements

    def passive(self) -> List[ParsedElement]:
        return [e for e in self.elements
                if e.element_type not in _SOURCES and e.element_type not in DEPENDENT_SOURCES]

    def sources(self) -> List[ParsedElement]:
        """
        Bağımsız kaynaklar (bağımlı kaynaklar için dependents()). İletimdeki diyotun eşdeğer
        kaynağı (params["diode_of"]) kaynak sayılmaz: güç verMEZ, diyot olarak ayrıca anlatılır.
        """
        return [e for e in self.elements
                if e.element_type in _SOURCES and not e.params.get("diode_of")]

    @property
    def diodes(self):
        """Diyotlu devrenin eşdeğerinde diyot raporu (solver.diode.DiodeReport), yoksa None."""
        return getattr(self.parsed, "diode_report", None)

    def dependents(self) -> List[ParsedElement]:
        return [e for e in self.elements if e.element_type in DEPENDENT_SOURCES]

    @property
    def has_dependent(self) -> bool:
        return any(e.element_type in DEPENDENT_SOURCES for e in self.elements)

    def label(self, e: ParsedElement) -> str:
        """Denklemdeki adı: direnç R1, empedans Z1, C/L için Z_C1."""
        if e.element_type in (ElementType.RESISTOR, ElementType.IMPEDANCE):
            return e.id
        return f"Z_{e.id}"

    def impedance(self, e: ParsedElement) -> Optional[complex]:
        """
        Akım hesabında kullanılan empedans.
        DC: C → None (açık devre), L → 0 (kısa devre).
        """
        t = e.element_type
        if t == ElementType.RESISTOR:
            return complex(e.value)
        if t == ElementType.IMPEDANCE:
            return complex(e.params.get("impedance", complex(e.value)))
        if self.is_dc:
            return None if t == ElementType.CAPACITOR else 0j
        if self.omega is None:
            return None
        if t == ElementType.CAPACITOR:
            return 1 / (1j * self.omega * e.value)
        return 1j * self.omega * e.value

    def conducts(self, e: ParsedElement) -> bool:
        """KCL terimi oluşturan pasif eleman mı? (DC'de C açık, L kısıt)"""
        if e.element_type in _SOURCES or e.element_type in DEPENDENT_SOURCES:
            return False
        if self.is_dc and e.element_type in (ElementType.CAPACITOR, ElementType.INDUCTOR):
            return False
        return self.impedance(e) is not None

    # ── Biçimlendirme ──

    def z_num(self, z: complex) -> str:
        """Denklem içinde empedans: 1000, (−j31.83), (50 + j30)."""
        return num(z.real) if abs(z.imag) < 1e-12 * max(abs(z), 1e-15) else paren(rect(z))

    def v_num(self, vv: complex) -> str:
        """Denklem içinde bilinen gerilim (birimsiz): 12, (14.14 + j14.14)."""
        return num(vv.real) if self.is_dc or abs(complex(vv).imag) < 1e-12 else paren(rect(vv))

    def val(self, z: complex, unit: str) -> str:
        """Sonuç değeri: DC '8 V', AC '3.033∠−72.34° V'."""
        return eng(complex(z).real, unit) if self.is_dc else polar(z, unit)

    def node_value(self, node: str) -> complex:
        return complex(self.v.get(node, 0))

    def element_value_text(self, e: ParsedElement) -> str:
        t = e.element_type
        if t == ElementType.IMPEDANCE:
            return f"{e.id} = {rect(e.params.get('impedance', complex(e.value)), 'Ω')}"
        return f"{e.id} = {eng(e.value, _UNITS[t])}"
