"""
CircuitAnalyzer API — Netlist Ayrıştırıcı (Parser)

C# WPF Frontend'in ürettiği SPICE Netlist metnini satır satır okur,
her satırı regex ile eşleştirir ve ParsedCircuit veri yapısına dönüştürür.

★ İki Format Kategorisi:

    Standart SPICE:
        R1 1 2 1000           → Direnç
        C1 2 0 1e-05          → Kapasitör
        L1 1 2 0.1            → Bobin
        V1 1 0 DC 12          → DC Kaynak
        VAC1 1 0 SINE(...)    → AC Kaynak (zaman alanı)

    Özel Uzantılar (Python backend için):
        VAC1 1 0 AC_PHASOR(10, 30)    → AC Kaynak (fazör alanı)
        Z1 2 3 COMPLEX(50, 30)        → Empedans (dikdörtgensel)
        Z1 2 3 POLAR(58.31, 30.96)    → Empedans (kutupsal)
        * PROBE VP1 V(2)              → Gerilim probu
        * PROBE IP1 I(R1)             → Akım probu
        * GND1 — Referans toprak      → GND yorumu (Node 0 C#'ta atanır)
"""

import re
import math
import cmath
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from enum import Enum


# ═══════════════════════════════════════════════════════
#  VERİ YAPILARI
# ═══════════════════════════════════════════════════════

class ElementType(str, Enum):
    """Devre elemanı tipleri."""
    RESISTOR = "R"
    CAPACITOR = "C"
    INDUCTOR = "L"
    DC_SOURCE = "V_DC"
    AC_SOURCE_SINE = "V_AC_SINE"
    AC_SOURCE_PHASOR = "V_AC_PHASOR"
    IMPEDANCE = "Z"
    # Akım kaynakları — SPICE kuralı: "I1 n+ n- değer" → akım kaynağın
    # İÇİNDEN n+'dan n-'ye akar, yani dış devreye n- ucundan çıkar.
    CURRENT_DC = "I_DC"
    CURRENT_AC_SINE = "I_AC_SINE"
    CURRENT_AC_PHASOR = "I_AC_PHASOR"


# ── Kaynak grupları (tüm modüller buradan kullanır) ──
VOLTAGE_SOURCES = (
    ElementType.DC_SOURCE, ElementType.AC_SOURCE_SINE, ElementType.AC_SOURCE_PHASOR,
)
CURRENT_SOURCES = (
    ElementType.CURRENT_DC, ElementType.CURRENT_AC_SINE, ElementType.CURRENT_AC_PHASOR,
)
ALL_SOURCES = VOLTAGE_SOURCES + CURRENT_SOURCES
DC_SOURCES = (ElementType.DC_SOURCE, ElementType.CURRENT_DC)
SINE_SOURCES = (ElementType.AC_SOURCE_SINE, ElementType.CURRENT_AC_SINE)
PHASOR_SOURCES = (ElementType.AC_SOURCE_PHASOR, ElementType.CURRENT_AC_PHASOR)


@dataclass
class ParsedElement:
    """
    Ayrıştırılmış devre elemanı.

    Tüm eleman tipleri için ortak veri yapısı.
    Tip-spesifik veriler 'params' sözlüğünde tutulur.

    Örnekler:
        Direnç:     id="R1", type=RESISTOR,      nodes=("1","2"), value=1000
        AC Kaynak:  id="VAC1", type=AC_PHASOR,    nodes=("1","0"), value=10,
                    params={"amplitude": 10, "phase": 30}
        Empedans:   id="Z1", type=IMPEDANCE,       nodes=("2","3"),
                    value=complex(50, 30),
                    params={"impedance": (50+30j)}
    """
    id: str
    element_type: ElementType
    node_positive: str
    node_negative: str
    value: float = 0.0
    params: Dict = field(default_factory=dict)


@dataclass
class ParsedProbe:
    """
    Ayrıştırılmış ölçüm probu.

    Netlist'teki '* PROBE VP1 V(2)' satırından oluşturulur.
    """
    id: str
    probe_type: str  # "V" veya "I"
    target: str      # Düğüm numarası veya eleman ID


@dataclass
class ParsedCircuit:
    """
    Ayrıştırılmış devrenin tamamı.

    Parser'ın çıktısı olan bu yapı, Solver'a girdi olarak verilir.
    """
    elements: List[ParsedElement] = field(default_factory=list)
    probes: List[ParsedProbe] = field(default_factory=list)
    has_ground: bool = False
    node_count: int = 0
    raw_netlist: str = ""
    warnings: List[str] = field(default_factory=list)
    # İsteğe bağlı çizim konumları (* NODEPOS n x y) — çevre akımlarının
    # ekranda saat yönünde seçilmesi için; hesaplamayı etkilemez
    node_positions: Dict[str, Tuple[float, float]] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════
#  SPICE BİRİM ÇARPANLARI
# ═══════════════════════════════════════════════════════

# SPICE standardında birim ekleri:
#   MEG = 10⁶  (mega — DİKKAT: 'M' = milli, 'MEG' = mega!)
#   K/k = 10³  (kilo)
#   m   = 10⁻³ (milli)
#   u/µ = 10⁻⁶ (mikro)
#   n   = 10⁻⁹ (nano)
#   p   = 10⁻¹² (piko)
#   f   = 10⁻¹⁵ (femto)

# Çarpan yerine 10'un üssü tutulur: "100u" → float("100e-6") = 1e-4 tam,
# oysa 100 * 1e-6 = 9.999999999999999e-05 (float yuvarlama hatası).
_SUFFIX_EXPONENTS = {
    "T": 12,
    "G": 9,
    "MEG": 6,
    "K": 3,
    "M": -3,   # SPICE: M = milli (MEG = mega!)
    "U": -6,
    "N": -9,
    "P": -12,
    "F": -15,
}


def parse_spice_value(value_str: str) -> float:
    """
    SPICE birim ekli sayıyı float'a dönüştürür.

    Örnekler:
        "1000"   → 1000.0
        "1k"     → 1000.0
        "10u"    → 1e-05
        "100m"   → 0.1
        "4.7MEG" → 4700000.0
        "2.2e-3" → 0.0022 (bilimsel notasyon)

    Args:
        value_str: SPICE formatında sayı metni

    Returns:
        float: Çıplak sayısal değer
    """
    s = value_str.strip()

    # Direkt sayı dene (bilimsel notasyon dahil: 1e-05, 2.2E+3)
    try:
        return float(s)
    except ValueError:
        pass

    # Birim eki ayıkla: "4.7k" → ("4.7", "K"), "100MEG" → ("100", "MEG")
    # Önce uzun ekleri dene (MEG), sonra tek karakterleri
    upper = s.upper()

    for suffix in sorted(_SUFFIX_EXPONENTS.keys(), key=len, reverse=True):
        if upper.endswith(suffix):
            num_part = s[:len(s) - len(suffix)]
            exponent = _SUFFIX_EXPONENTS[suffix]
            try:
                return float(f"{num_part}e{exponent}")
            except ValueError:
                pass
            try:
                # "1e-3k" gibi zaten üslü sayılar
                return float(num_part) * 10.0 ** exponent
            except ValueError:
                continue

    raise ValueError(f"SPICE değeri ayrıştırılamadı: '{value_str}'")


# ═══════════════════════════════════════════════════════
#  REGEX KALIPLARI
# ═══════════════════════════════════════════════════════

# Her kalıp bir eleman tipini eşleştirir.
# Gruplar: (1)=ID, (2)=node+, (3)=node−, (4+)=parametreler

_PATTERNS = {
    # ── Standart SPICE ──
    "resistor": re.compile(
        r"^(R\w+)\s+(\w+)\s+(\w+)\s+([\w.eE+-]+)\s*$", re.IGNORECASE
    ),
    "capacitor": re.compile(
        r"^(C\w+)\s+(\w+)\s+(\w+)\s+([\w.eE+-]+)\s*$", re.IGNORECASE
    ),
    "inductor": re.compile(
        r"^(L\w+)\s+(\w+)\s+(\w+)\s+([\w.eE+-]+)\s*$", re.IGNORECASE
    ),
    # Gerilim (V…) ve akım (I…) kaynakları aynı biçimi paylaşır
    "dc_source": re.compile(
        r"^([VI]\w+)\s+(\w+)\s+(\w+)\s+DC\s+([\w.eE+-]+)\s*$", re.IGNORECASE
    ),

    # ── AC Kaynaklar ──
    # SINE(V_offset V_amplitude Frequency T_delay Damping Phase)
    "ac_sine": re.compile(
        r"^([VI]\w+)\s+(\w+)\s+(\w+)\s+SINE\(([^)]*)\)\s*$", re.IGNORECASE
    ),
    # AC_PHASOR(Magnitude, Phase_degrees)
    "ac_phasor": re.compile(
        r"^([VI]\w+)\s+(\w+)\s+(\w+)\s+AC_PHASOR\(([^)]*)\)\s*$", re.IGNORECASE
    ),

    # ── Empedans (Özel uzantı) ──
    # COMPLEX(real, imaginary)
    "impedance_complex": re.compile(
        r"^(Z\w+)\s+(\w+)\s+(\w+)\s+COMPLEX\(([^)]*)\)\s*$", re.IGNORECASE
    ),
    # POLAR(magnitude, angle_degrees)
    "impedance_polar": re.compile(
        r"^(Z\w+)\s+(\w+)\s+(\w+)\s+POLAR\(([^)]*)\)\s*$", re.IGNORECASE
    ),

    # ── Ölçüm Probu (Yorum satırı) ──
    "probe": re.compile(
        r"^\*\s*PROBE\s+(\w+)\s+([VI])\(([^)]+)\)\s*$"
    ),

    # ── Düğüm çizim konumu (Yorum satırı): * NODEPOS 2 340 120 ──
    "node_position": re.compile(
        r"^\*\s*NODEPOS\s+(\w+)\s+(-?[\d.]+(?:[eE][-+]?\d+)?)\s+(-?[\d.]+(?:[eE][-+]?\d+)?)\s*$",
        re.IGNORECASE
    ),

    # ── GND referansı (Yorum satırı) ──
    "ground_ref": re.compile(
        r"^\*\s*(GND\w*)\s*[—\-]\s*Referans", re.IGNORECASE
    ),
}


# ═══════════════════════════════════════════════════════
#  ANA PARSER
# ═══════════════════════════════════════════════════════

def parse_netlist(netlist_text: str) -> ParsedCircuit:
    """
    SPICE Netlist metnini ayrıştırır.

    Args:
        netlist_text: C# Frontend'ten gelen Netlist metni.
            Satırlar '\\n' ile ayrılır.
            '*' ile başlayan satırlar yorum veya ölçüm direktifidir.
            '.end' satırı dosya sonunu belirtir.

    Returns:
        ParsedCircuit: Ayrıştırılmış devre yapısı.

    Raises:
        ValueError: Hiçbir eleman ayrıştırılamazsa.

    Örnek:
        >>> result = parse_netlist("R1 1 2 1000\\nV1 1 0 DC 12\\n.end")
        >>> len(result.elements)
        2
        >>> result.elements[0].id
        'R1'
    """
    circuit = ParsedCircuit(raw_netlist=netlist_text)
    all_nodes = set()
    lines = netlist_text.strip().split("\n")

    for line_num, raw_line in enumerate(lines, 1):
        line = raw_line.strip()

        # Boş satır, başlık yorumu veya .end — atla
        if not line or line.startswith(".end"):
            continue

        # Yorum satırı — ama PROBE veya GND olabilir
        if line.startswith("*"):
            _parse_comment_line(line, circuit)
            continue

        # Eleman satırı
        element = _parse_element_line(line, line_num, circuit)
        if element:
            circuit.elements.append(element)
            all_nodes.add(element.node_positive)
            all_nodes.add(element.node_negative)

    circuit.node_count = len(all_nodes)
    return circuit


def _parse_comment_line(line: str, circuit: ParsedCircuit) -> None:
    """Yorum satırındaki PROBE ve GND direktiflerini ayrıştırır."""

    # Ölçüm probu: * PROBE VP1 V(2)
    probe_match = _PATTERNS["probe"].match(line)
    if probe_match:
        circuit.probes.append(ParsedProbe(
            id=probe_match.group(1),
            probe_type=probe_match.group(2),
            target=probe_match.group(3)
        ))
        return

    # Düğüm konumu: * NODEPOS 2 340 120
    pos_match = _PATTERNS["node_position"].match(line)
    if pos_match:
        circuit.node_positions[pos_match.group(1)] = (
            float(pos_match.group(2)), float(pos_match.group(3)))
        return

    # GND referansı: * GND1 — Referans toprak (Node 0)
    gnd_match = _PATTERNS["ground_ref"].match(line)
    if gnd_match:
        circuit.has_ground = True
        return


def _parse_element_line(
    line: str,
    line_num: int,
    circuit: ParsedCircuit
) -> Optional[ParsedElement]:
    """Tek bir eleman satırını ayrıştırır."""

    # ── Direnç: R1 1 2 1000 ──
    m = _PATTERNS["resistor"].match(line)
    if m and m.group(1)[0].upper() == "R":
        return ParsedElement(
            id=m.group(1),
            element_type=ElementType.RESISTOR,
            node_positive=m.group(2),
            node_negative=m.group(3),
            value=parse_spice_value(m.group(4))
        )

    # ── Kapasitör: C1 2 0 10u ──
    m = _PATTERNS["capacitor"].match(line)
    if m and m.group(1)[0].upper() == "C":
        return ParsedElement(
            id=m.group(1),
            element_type=ElementType.CAPACITOR,
            node_positive=m.group(2),
            node_negative=m.group(3),
            value=parse_spice_value(m.group(4))
        )

    # ── Bobin: L1 1 2 100m ──
    m = _PATTERNS["inductor"].match(line)
    if m and m.group(1)[0].upper() == "L":
        return ParsedElement(
            id=m.group(1),
            element_type=ElementType.INDUCTOR,
            node_positive=m.group(2),
            node_negative=m.group(3),
            value=parse_spice_value(m.group(4))
        )

    # ── DC Kaynak: V1 1 0 DC 12  /  I1 0 2 DC 5m ──
    m = _PATTERNS["dc_source"].match(line)
    if m:
        is_current = m.group(1)[0].upper() == "I"
        return ParsedElement(
            id=m.group(1),
            element_type=ElementType.CURRENT_DC if is_current else ElementType.DC_SOURCE,
            node_positive=m.group(2),
            node_negative=m.group(3),
            value=parse_spice_value(m.group(4))
        )

    # ── AC Kaynak (SINE): VAC1 1 0 SINE(0 10 50 0 0 30) ──
    m = _PATTERNS["ac_sine"].match(line)
    if m:
        return _parse_ac_sine(m)

    # ── AC Kaynak (Fazör): VAC1 1 0 AC_PHASOR(10, 30) ──
    m = _PATTERNS["ac_phasor"].match(line)
    if m:
        return _parse_ac_phasor(m)

    # ── Empedans (Dikdörtgensel): Z1 2 3 COMPLEX(50, 30) ──
    m = _PATTERNS["impedance_complex"].match(line)
    if m:
        return _parse_impedance_complex(m)

    # ── Empedans (Kutupsal): Z1 2 3 POLAR(58.31, 30.96) ──
    m = _PATTERNS["impedance_polar"].match(line)
    if m:
        return _parse_impedance_polar(m)

    # Tanınmayan satır → uyarı
    circuit.warnings.append(
        f"Satır {line_num}: Tanınmayan format → '{line}'"
    )
    return None


# ═══════════════════════════════════════════════════════
#  ÖZEL FORMAT PARSER'LARI
# ═══════════════════════════════════════════════════════

def _parse_ac_sine(m: re.Match) -> ParsedElement:
    """
    SINE formatını ayrıştırır.

    SINE(V_offset V_amplitude Frequency T_delay Damping Phase)
    Örnek: SINE(0 10 50 0 0 30)
      → offset=0, amplitude=10, frequency=50, phase=30°

    Parametreler boşluk veya virgülle ayrılabilir.
    """
    parts = re.split(r"[,\s]+", m.group(4).strip())
    parts = [p for p in parts if p]  # Boş elemanları temizle

    offset = float(parts[0]) if len(parts) > 0 else 0
    amplitude = float(parts[1]) if len(parts) > 1 else 0
    frequency = float(parts[2]) if len(parts) > 2 else 0
    phase = float(parts[5]) if len(parts) > 5 else 0

    return ParsedElement(
        id=m.group(1),
        element_type=(ElementType.CURRENT_AC_SINE if m.group(1)[0].upper() == "I"
                      else ElementType.AC_SOURCE_SINE),
        node_positive=m.group(2),
        node_negative=m.group(3),
        value=amplitude,
        params={
            "offset": offset,
            "amplitude": amplitude,
            "frequency": frequency,
            "phase": phase
        }
    )


def _parse_ac_phasor(m: re.Match) -> ParsedElement:
    """
    AC_PHASOR formatını ayrıştırır.

    AC_PHASOR(Magnitude, Phase_degrees)
    Örnek: AC_PHASOR(10, 30) → 10∠30° V
    """
    parts = re.split(r"[,\s]+", m.group(4).strip())
    magnitude = float(parts[0])
    phase = float(parts[1]) if len(parts) > 1 else 0

    return ParsedElement(
        id=m.group(1),
        element_type=(ElementType.CURRENT_AC_PHASOR if m.group(1)[0].upper() == "I"
                      else ElementType.AC_SOURCE_PHASOR),
        node_positive=m.group(2),
        node_negative=m.group(3),
        value=magnitude,
        params={
            "amplitude": magnitude,
            "phase": phase,
            # Kartezyen forma çevir (solver için)
            "phasor_complex": complex(
                magnitude * math.cos(math.radians(phase)),
                magnitude * math.sin(math.radians(phase))
            )
        }
    )


def _parse_impedance_complex(m: re.Match) -> ParsedElement:
    """
    COMPLEX formatını ayrıştırır.

    COMPLEX(real, imaginary)
    Örnek: COMPLEX(50, 30) → Z = 50 + j30 Ω
    """
    parts = re.split(r"[,\s]+", m.group(4).strip())
    real = float(parts[0])
    imag = float(parts[1]) if len(parts) > 1 else 0
    z = complex(real, imag)

    return ParsedElement(
        id=m.group(1),
        element_type=ElementType.IMPEDANCE,
        node_positive=m.group(2),
        node_negative=m.group(3),
        value=abs(z),
        params={
            "impedance": z,
            "resistance": real,
            "reactance": imag,
            "magnitude": abs(z),
            "phase_degrees": math.degrees(cmath.phase(z))
        }
    )


def _parse_impedance_polar(m: re.Match) -> ParsedElement:
    """
    POLAR formatını ayrıştırır.

    POLAR(magnitude, angle_degrees)
    Örnek: POLAR(58.31, 30.96) → Z = 58.31∠30.96° Ω

    Euler formülüyle kartezyen forma dönüşüm:
        a = r·cos(θ)
        b = r·sin(θ)
    """
    parts = re.split(r"[,\s]+", m.group(4).strip())
    magnitude = float(parts[0])
    angle_deg = float(parts[1]) if len(parts) > 1 else 0
    angle_rad = math.radians(angle_deg)
    z = complex(
        magnitude * math.cos(angle_rad),
        magnitude * math.sin(angle_rad)
    )

    return ParsedElement(
        id=m.group(1),
        element_type=ElementType.IMPEDANCE,
        node_positive=m.group(2),
        node_negative=m.group(3),
        value=magnitude,
        params={
            "impedance": z,
            "resistance": z.real,
            "reactance": z.imag,
            "magnitude": magnitude,
            "phase_degrees": angle_deg
        }
    )


# ═══════════════════════════════════════════════════════
#  LCAPY DÖNÜŞTÜRÜCÜ
# ═══════════════════════════════════════════════════════

def to_lcapy_netlist(circuit: ParsedCircuit, frequency: float = None) -> str:
    """
    ParsedCircuit yapısını lcapy'nin okuyabileceği Netlist formatına çevirir.

    lcapy formatı SPICE'a benzer ama bazı farklar vardır:
        - DC kaynak: 'V1 1 0 12'  (DC anahtar kelimesi yok)
        - AC kaynak: 'V1 1 0 ac {10*exp(j*pi/6)}'
        - Empedans:  'Z1 1 2 {50+30j}'  (lcapy Z elemanını destekler)

    Args:
        circuit: Ayrıştırılmış devre yapısı
        frequency: AC analiz frekansı (Hz) — opsiyonel

    Returns:
        str: lcapy-uyumlu Netlist metni
    """
    lines = []

    for elem in circuit.elements:
        if elem.element_type == ElementType.RESISTOR:
            lines.append(
                f"{elem.id} {elem.node_positive} {elem.node_negative} {elem.value}"
            )

        elif elem.element_type == ElementType.CAPACITOR:
            lines.append(
                f"{elem.id} {elem.node_positive} {elem.node_negative} {elem.value}"
            )

        elif elem.element_type == ElementType.INDUCTOR:
            lines.append(
                f"{elem.id} {elem.node_positive} {elem.node_negative} {elem.value}"
            )

        elif elem.element_type == ElementType.DC_SOURCE:
            # lcapy DC formatı: sadece değer (DC anahtar kelimesi yok)
            lines.append(
                f"{elem.id} {elem.node_positive} {elem.node_negative} "
                f"{{{elem.value}}}"
            )

        elif elem.element_type == ElementType.AC_SOURCE_SINE:
            # lcapy AC formatı: ac {Magnitude * exp(j*phase_rad)}
            amp = elem.params.get("amplitude", elem.value)
            phase_deg = elem.params.get("phase", 0)
            phase_rad = math.radians(phase_deg)

            if abs(phase_deg) < 0.001:
                lines.append(
                    f"{elem.id} {elem.node_positive} {elem.node_negative} "
                    f"ac {{{amp}}}"
                )
            else:
                lines.append(
                    f"{elem.id} {elem.node_positive} {elem.node_negative} "
                    f"ac {{{amp}*exp(j*{phase_rad:.6f})}}"
                )

        elif elem.element_type == ElementType.AC_SOURCE_PHASOR:
            amp = elem.params.get("amplitude", elem.value)
            phase_deg = elem.params.get("phase", 0)
            phase_rad = math.radians(phase_deg)

            if abs(phase_deg) < 0.001:
                lines.append(
                    f"{elem.id} {elem.node_positive} {elem.node_negative} "
                    f"ac {{{amp}}}"
                )
            else:
                lines.append(
                    f"{elem.id} {elem.node_positive} {elem.node_negative} "
                    f"ac {{{amp}*exp(j*{phase_rad:.6f})}}"
                )

        elif elem.element_type == ElementType.IMPEDANCE:
            # lcapy empedans: Z1 1 2 {50+30j}
            z = elem.params.get("impedance", complex(elem.value, 0))
            if abs(z.imag) < 1e-10:
                lines.append(
                    f"{elem.id} {elem.node_positive} {elem.node_negative} "
                    f"{{{z.real}}}"
                )
            else:
                sign = "+" if z.imag >= 0 else ""
                lines.append(
                    f"{elem.id} {elem.node_positive} {elem.node_negative} "
                    f"{{{z.real}{sign}{z.imag}j}}"
                )

        elif elem.element_type in CURRENT_SOURCES:
            # ★ YÖN KURALI: SPICE'ta "I1 n+ n- I" akımı n- ucundan dış devreye
            #   verir. lcapy'de ise "I1 a b I" akımı a (İLK) ucundan verir.
            #   Bu yüzden lcapy'ye uçlar ters sırada yazılır. (Doğrulandı:
            #   lcapy "I1 1 0 1m" + 1kΩ → V(1) = +1 V; SPICE'ta −1 V olur.)
            first, second = elem.node_negative, elem.node_positive
            if elem.element_type == ElementType.CURRENT_DC:
                lines.append(f"{elem.id} {first} {second} {{{elem.value}}}")
            else:
                amp = elem.params.get("amplitude", elem.value)
                phase_deg = elem.params.get("phase", 0)
                if abs(phase_deg) < 0.001:
                    lines.append(f"{elem.id} {first} {second} ac {{{amp}}}")
                else:
                    lines.append(
                        f"{elem.id} {first} {second} "
                        f"ac {{{amp}*exp(j*{math.radians(phase_deg):.6f})}}"
                    )

    return "\n".join(lines)
