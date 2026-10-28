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
        S1 1 2 NO / S1 1 2 NC         → Anahtar: t=0'da kapanır / açılır
        S1 3 1 2 SPDT                 → İki konumlu anahtar (ortak 3; t<0: 3–1, t≥0: 3–2)
        E1 3 0 V(R2) 3                → Gerilim kontrollü gerilim kaynağı (GKGK)
        G1 3 0 V(-R2) 1m              → Gerilim kontrollü akım kaynağı    (GKAK)
        H1 3 0 I(R2) 100              → Akım kontrollü gerilim kaynağı    (AKGK)
        F1 3 0 I(V1) 2                → Akım kontrollü akım kaynağı       (AKAK)
        * PROBE VP1 V(2)              → Gerilim probu
        * PROBE IP1 I(R1)             → Akım probu
        * GND1 — Referans toprak      → GND yorumu (Node 0 C#'ta atanır)
"""

import re
import math
import cmath
import dataclasses
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
    # Bağımlı (kontrollü) kaynaklar — çıkışları başka bir elemanın gerilimi
    # veya akımıyla orantılıdır: çıkış = kazanç · kontrol büyüklüğü.
    #   E: gerilim kontrollü gerilim kaynağı (GKGK)   E1 n+ n- V(ctrl) k
    #   G: gerilim kontrollü akım kaynağı    (GKAK)   G1 n+ n- V(ctrl) k
    #   H: akım kontrollü gerilim kaynağı    (AKGK)   H1 n+ n- I(ctrl) k
    #   F: akım kontrollü akım kaynağı       (AKAK)   F1 n+ n- I(ctrl) k
    # Akım çıkışlı olanlarda (G, F) yön kuralı bağımsız akım kaynaklarıyla
    # aynıdır: akım kaynak İÇİNDEN n+ → n−; dış devreye n− ucundan çıkar.
    VCVS = "E"
    VCCS = "G"
    CCVS = "H"
    CCCS = "F"
    # Anahtar (Faz 2 — geçici durum). Tüm anahtarlar t = 0 anında konum değiştirir:
    #   S1 a b NO          t < 0 açık, t ≥ 0 kapalı
    #   S1 a b NC          t < 0 kapalı, t ≥ 0 açık
    #   S1 c a b SPDT      t < 0 c–a bağlı (konum 1), t ≥ 0 c–b bağlı (konum 2)
    # Kapalı anahtar ideal kısa devre, açık anahtar ideal açık devredir.
    SWITCH = "S"


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
# Bağımlı kaynaklar ALL_SOURCES'a DAHİL DEĞİLDİR: bağımsız kaynak değildirler
# (frekansı/değeri yoktur, süperpozisyonda sıfırlanmazlar, KCL'de sabit terim
# olamazlar). Bunları tanımak için bu grubu kullanın.
DEPENDENT_SOURCES = (
    ElementType.VCVS, ElementType.VCCS, ElementType.CCVS, ElementType.CCCS,
)
# Çıkışı gerilim / akım olanlar ve kontrol büyüklüğü akım olanlar
DEPENDENT_VOLTAGE_OUTPUT = (ElementType.VCVS, ElementType.CCVS)
DEPENDENT_CURRENT_OUTPUT = (ElementType.VCCS, ElementType.CCCS)
DEPENDENT_CURRENT_CONTROLLED = (ElementType.CCVS, ElementType.CCCS)

# Bağımlı kaynakların Türkçe adı ve kontrol cümlesi (anlatım / asistan için)
DEPENDENT_NAMES = {
    ElementType.VCVS: "Gerilim kontrollü gerilim kaynağı",
    ElementType.VCCS: "Gerilim kontrollü akım kaynağı",
    ElementType.CCVS: "Akım kontrollü gerilim kaynağı",
    ElementType.CCCS: "Akım kontrollü akım kaynağı",
}


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
    # Devreyi çözülemez kılan Türkçe hatalar (ör: bağımlı kaynağın kontrol
    # elemanı yok). API bunları HTTP 400 olarak döndürür; yanlış sonuç vermez.
    errors: List[str] = field(default_factory=list)
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

    # ── Bağımlı kaynaklar ──
    # E1 3 0 V(R2) 3   G1 3 0 V(-R2) 0.5m   H1 3 0 I(R2) 100   F1 3 0 I(V1) 2
    # Gruplar: (1)=ID, (2)=n+, (3)=n−, (4)=V|I, (5)='-' (ters çevirme) veya '',
    #          (6)=kontrol elemanı, (7)=kazanç
    "dependent": re.compile(
        r"^([EFGH]\w*)\s+(\w+)\s+(\w+)\s+([VI])\(\s*(?:(-)\s*)?(\w+)\s*\)\s+([\w.eE+-]+)\s*$",
        re.IGNORECASE
    ),

    # ── Anahtar (Faz 2) ──
    # S1 a b NO   /   S1 a b NC
    "switch_two": re.compile(
        r"^(S\w*)\s+(\w+)\s+(\w+)\s+(NO|NC)\s*$", re.IGNORECASE
    ),
    # S1 c a b SPDT   (c = ortak uç, a = konum 1, b = konum 2)
    "switch_spdt": re.compile(
        r"^(S\w*)\s+(\w+)\s+(\w+)\s+(\w+)\s+SPDT\s*$", re.IGNORECASE
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

    # Bağımlı kaynakların kontrol elemanları (satır sırasından bağımsız denetlenir)
    _validate_dependents(circuit)

    for element in circuit.elements:
        all_nodes.add(element.node_positive)
        all_nodes.add(element.node_negative)
        if element.element_type == ElementType.SWITCH and element.params.get("pos2"):
            all_nodes.add(element.params["pos2"])
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

    # ── Bağımlı kaynak: E1 3 0 V(R2) 3 ──
    m = _PATTERNS["dependent"].match(line)
    if m:
        return _parse_dependent(m, line_num, circuit)

    # ── Anahtar: S1 1 2 NO  /  S1 1 2 NC  /  S1 1 2 3 SPDT ──
    if line[0].upper() == "S":
        return _parse_switch(line, line_num, circuit)

    # E/F/G/H ile başlayan ama biçimi bozuk satır: sessizce atlanırsa devre
    # kaynaksız çözülür ve yanlış sonuç çıkar → hata olarak bildir.
    if line[0].upper() in "EFGH":
        _reject(circuit,
                f"Satır {line_num}: Bağımlı kaynak satırı anlaşılamadı → '{line}'. "
                "Beklenen biçim: E1 <n+> <n-> V(<kontrol>) <kazanç> "
                "(H ve F için I(<kontrol>)).")
        return None

    # Tanınmayan satır → uyarı
    circuit.warnings.append(
        f"Satır {line_num}: Tanınmayan format → '{line}'"
    )
    return None


# ═══════════════════════════════════════════════════════
#  ÖZEL FORMAT PARSER'LARI
# ═══════════════════════════════════════════════════════

def _reject(circuit: ParsedCircuit, message: str) -> None:
    """Çözümü engelleyen Türkçe hata: hem uyarılara hem hatalara yazılır."""
    circuit.warnings.append(message)
    circuit.errors.append(message)


def _parse_switch(
    line: str, line_num: int, circuit: ParsedCircuit
) -> Optional[ParsedElement]:
    """
    Anahtar satırını ayrıştırır (Faz 2 sözleşmesi).

    S1 a b NO       → params: kind="NO"   (t<0 açık,  t≥0 kapalı)
    S1 a b NC       → params: kind="NC"   (t<0 kapalı, t≥0 açık)
    S1 c a b SPDT   → params: kind="SPDT", common=c, pos1=a, pos2=b
                      (t<0 c–a bağlı, t≥0 c–b bağlı)

    node_positive / node_negative: NO/NC'de (a, b); SPDT'de (c, a). SPDT'nin
    ikinci konumu params["pos2"]'dedir. Geçersiz satırlar Türkçe hatayla reddedilir.
    """
    expected = ("Beklenen biçim: S1 <a> <b> NO (t = 0'da kapanır), S1 <a> <b> NC "
                "(t = 0'da açılır) ya da S1 <ortak> <konum 1> <konum 2> SPDT.")
    m = _PATTERNS["switch_two"].match(line)
    if m:
        sid, a, b, kind = m.group(1), m.group(2), m.group(3), m.group(4).upper()
        if a == b:
            _reject(circuit,
                    f"Satır {line_num}: {sid} anahtarının iki ucu da aynı düğüme (Düğüm {a}) "
                    "bağlı; böyle bir anahtar devreyi değiştirmez. Uçlarını farklı düğümlere bağlayın.")
            return None
        return ParsedElement(
            id=sid, element_type=ElementType.SWITCH,
            node_positive=a, node_negative=b, value=0.0,
            params={"kind": kind},
        )
    m = _PATTERNS["switch_spdt"].match(line)
    if m:
        sid, c, a, b = m.group(1), m.group(2), m.group(3), m.group(4)
        if len({c, a, b}) < 3:
            _reject(circuit,
                    f"Satır {line_num}: {sid} iki konumlu anahtarının ortak ucu (Düğüm {c}) ile "
                    f"iki konumu (Düğüm {a} ve Düğüm {b}) birbirinden farklı düğümler olmalı.")
            return None
        return ParsedElement(
            id=sid, element_type=ElementType.SWITCH,
            node_positive=c, node_negative=a, value=0.0,
            params={"kind": "SPDT", "common": c, "pos1": a, "pos2": b},
        )
    _reject(circuit, f"Satır {line_num}: Anahtar satırı anlaşılamadı → '{line}'. {expected}")
    return None


def _parse_dependent(
    m: re.Match, line_num: int, circuit: ParsedCircuit
) -> Optional[ParsedElement]:
    """
    Bağımlı kaynak satırını ayrıştırır.

    E1 3 0 V(R2) 3     → V(3) − V(0) = 3 · V_R2          (V_R2 = V(R2.n+) − V(R2.n−))
    G1 3 0 V(-R2) 1m   → kaynak akımı = 1m · (−V_R2)      (n+ → n−, kaynak içinden)
    H1 3 0 I(R2) 100   → V(3) − V(0) = 100 · I_R2         (I_R2: R2'nin n+ → n− akımı)
    F1 3 0 I(V1) 2     → kaynak akımı = 2 · I_V1          (n+ → n−, kaynak içinden)

    params: control_id, control_kind ("V"|"I"), control_sign (±1), gain.
    Kontrol elemanının varlığı burada denetlenmez (satır sırası serbest);
    bunu parse_netlist sonunda _validate_dependents yapar.
    """
    elem_id = m.group(1)
    kind = ElementType(elem_id[0].upper())
    letter = m.group(4).upper()
    expected = "I" if kind in DEPENDENT_CURRENT_CONTROLLED else "V"
    if letter != expected:
        what = "akım" if expected == "I" else "gerilim"
        _reject(circuit,
                f"Satır {line_num}: {elem_id} bir {DEPENDENT_NAMES[kind].lower()}dır; "
                f"kontrol büyüklüğü {what} olduğundan {expected}(...) yazılmalı, "
                f"{letter}(...) yazılmış.")
        return None
    try:
        gain = parse_spice_value(m.group(7))
    except ValueError:
        _reject(circuit,
                f"Satır {line_num}: {elem_id} kazancı sayı olarak okunamadı → '{m.group(7)}'.")
        return None
    return ParsedElement(
        id=elem_id,
        element_type=kind,
        node_positive=m.group(2),
        node_negative=m.group(3),
        value=gain,
        params={
            "control_id": m.group(6),
            "control_kind": letter,
            "control_sign": -1 if m.group(5) else 1,
            "gain": gain,
        },
    )


def _validate_dependents(circuit: ParsedCircuit) -> None:
    """
    Bağımlı kaynakların kontrol elemanlarını denetler. Geçersiz olanlar
    (bilinmeyen eleman, kendi kendini kontrol, kontrol edilemeyen eleman)
    devreden çıkarılır ve Türkçe hata üretilir; böylece çözücü eksik bir
    devreyi yanlış sonuçla çözmez.
    """
    while True:
        by_id = {e.id.upper(): e for e in circuit.elements}
        bad = None
        for e in circuit.elements:
            if e.element_type not in DEPENDENT_SOURCES:
                continue
            ref = e.params["control_id"]
            ctrl = by_id.get(ref.upper())
            if ctrl is e or ref.upper() == e.id.upper():
                bad = (e, f"{e.id} kendi kendini kontrol edemez (kontrol elemanı olarak "
                          "başka bir elemanı seçin).")
            elif ctrl is None:
                bad = (e, f"{e.id} bağımlı kaynağının kontrol elemanı '{ref}' devrede "
                          "bulunamadı. Kontrol elemanının numarasını (Id) kontrol edin.")
            else:
                e.params["control_id"] = ctrl.id    # büyük/küçük harfi eleman kimliğine uydur
            if bad:
                break
        if bad is None:
            return
        elem, message = bad
        circuit.elements.remove(elem)
        _reject(circuit, message)


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
#  ANAHTARLAR — t < 0 ve t > 0 devreleri (Faz 2)
# ═══════════════════════════════════════════════════════

# Anahtarlı devre başka bir yöntemle çözülürken anlatımın başına eklenen not
SWITCH_NOTE = ("Anahtarlar t > 0 konumunda alındı; anahtarın etkisini görmek için "
               "Geçici Durum yöntemini seçin.")


def has_switches(circuit: ParsedCircuit) -> bool:
    """Devrede en az bir anahtar var mı?"""
    return any(e.element_type == ElementType.SWITCH for e in circuit.elements)


def switch_closed_pair(switch: ParsedElement, when: str) -> Optional[Tuple[str, str]]:
    """
    Anahtarın o anda kısa devre ettiği düğüm çifti; açıksa None.

    when: "before" (t < 0) ya da "after" (t ≥ 0).
        NO:   before açık,  after kapalı (a–b)
        NC:   before kapalı (a–b), after açık
        SPDT: before c–a,   after c–b (her zaman biri kapalıdır)
    """
    if when not in ("before", "after"):
        raise ValueError("when 'before' ya da 'after' olmalı.")
    kind = switch.params.get("kind")
    if kind == "SPDT":
        target = switch.params["pos1"] if when == "before" else switch.params["pos2"]
        return switch.params["common"], target
    closed = (kind == "NC") if when == "before" else (kind == "NO")
    return (switch.node_positive, switch.node_negative) if closed else None


def circuit_at_time(circuit: ParsedCircuit, when: str) -> ParsedCircuit:
    """
    Anahtarlar o zamanki konumuna getirilmiş devre kopyası.

    when="before" → t < 0 konumu, when="after" → t > 0 konumu.
    Kapalı anahtar ideal kısa devredir: iki ucu TEK düğümde birleşir (GND "0" varsa
    o kalır, yoksa küçük numara). Açık anahtar devreden çıkarılır. Anahtarsız
    devre için aynı nesne döner. Çıktıda hiç anahtar kalmaz; çözücü ve anlatım
    bu kopyayı sıradan bir devre gibi kullanır.
    """
    if not has_switches(circuit):
        return circuit

    parent: Dict[str, str] = {}

    def find(n: str) -> str:
        parent.setdefault(n, n)
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for sw in circuit.elements:
        if sw.element_type != ElementType.SWITCH:
            continue
        pair = switch_closed_pair(sw, when)
        if pair is None:
            continue
        ra, rb = find(pair[0]), find(pair[1])
        if ra != rb:
            keep, drop = sorted((ra, rb), key=lambda x: (x != "0", len(x), x))
            parent[drop] = keep

    def rename(n: str) -> str:
        return find(n) if n in parent else n

    new = ParsedCircuit(
        probes=[], has_ground=circuit.has_ground, raw_netlist=circuit.raw_netlist,
        warnings=list(circuit.warnings), errors=list(circuit.errors),
    )
    for e in circuit.elements:
        if e.element_type == ElementType.SWITCH:
            continue
        new.elements.append(dataclasses.replace(
            e, node_positive=rename(e.node_positive), node_negative=rename(e.node_negative),
            params=dict(e.params)))
    for p in circuit.probes:
        new.probes.append(ParsedProbe(
            id=p.id, probe_type=p.probe_type,
            target=rename(p.target) if p.probe_type == "V" else p.target))
    for n, xy in circuit.node_positions.items():
        new.node_positions.setdefault(rename(n), xy)
    new.node_count = len({n for e in new.elements for n in (e.node_positive, e.node_negative)})
    return new


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

    Bağımlı kaynaklar (ölçüldü, lcapy davranışı):
        E1 n+ n- c+ c- {k}       V(n+)−V(n−) = k·(V(c+)−V(c−))
        G1 n- n+ c+ c- {k}       akım İLK düğümden çıkar → uçlar ters yazılır
        H1 n+ n- Vsrc {k}        V(n+)−V(n−) = k·I(Vsrc)
        F1 n+ n- Vsrc {k}        akım İKİNCİ düğümden çıkar (SPICE düzeni)
      lcapy H/F için kontrol olarak bir GERİLİM KAYNAĞI adı ister. Kontrol
      bağımsız gerilim kaynağı değilse (R, C, L, Z, I, E, F, G, H) elemanın
      n− ucuyla arasına 0 V'luk gizli bir ölçüm kaynağı konur (bkz.
      lcapy_sense_map). G ve F elemanlarının akımını lcapy doğrudan vermediği
      için onlara da konur. Gizli düğüm/kaynak adları sonuçlara ÇIKMAZ.

    Args:
        circuit: Ayrıştırılmış devre yapısı
        frequency: AC analiz frekansı (Hz) — opsiyonel

    Returns:
        str: lcapy-uyumlu Netlist metni
    """
    if has_switches(circuit):
        # lcapy anahtar bilmez: anahtarlar t > 0 konumunda (kapalı = tel) alınır
        circuit = circuit_at_time(circuit, "after")
    lines = []
    sense = lcapy_sense_map(circuit)
    by_id = {e.id: e for e in circuit.elements}

    for orig in circuit.elements:
        elem = orig
        if orig.id in sense:
            # n− ucu gizli düğüme taşınır; 0 V'luk ölçüm kaynağı gizli düğümle
            # gerçek n− arasına girer: I(ölçüm) = eleman içinden n+ → n− akım
            elem = dataclasses.replace(orig, node_negative=sense[orig.id][1])

        if elem.element_type in DEPENDENT_SOURCES:
            lines.append(_dependent_lcapy_line(elem, by_id, sense))

        elif elem.element_type == ElementType.RESISTOR:
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

        if orig.id in sense:
            sense_name, hidden = sense[orig.id]
            lines.append(f"{sense_name} {hidden} {orig.node_negative} {{0}}")

    return "\n".join(lines)


def lcapy_sense_map(circuit: ParsedCircuit) -> Dict[str, Tuple[str, str]]:
    """
    0 V'luk gizli ölçüm kaynağı gereken elemanlar: {eleman: (kaynak adı, gizli düğüm)}.

    Gereken elemanlar:
      • akım kontrollü bir kaynağın (H, F) kontrol elemanı — bağımsız gerilim
        kaynağı DEĞİLSE (lcapy kontrol olarak gerilim kaynağı adı ister;
        bağımsız gerilim kaynağının akımı zaten uygulamanın raporladığı
        element_currents ile aynı işaretlidir, doğrudan kullanılır),
      • akım çıkışlı her bağımlı kaynak (G, F): lcapy bunların akımını
        vermez; gizli kaynağın akımı = eleman içinden n+ → n− akım.

    Adlar elemanlarla/düğümlerle çakışmayacak şekilde seçilir.
    """
    by_id = {e.id: e for e in circuit.elements}
    wanted: List[str] = []
    for e in circuit.elements:
        if e.element_type in DEPENDENT_CURRENT_OUTPUT and e.id not in wanted:
            wanted.append(e.id)
        if e.element_type in DEPENDENT_CURRENT_CONTROLLED:
            ctrl = by_id.get(e.params.get("control_id"))
            if (ctrl is not None and ctrl.element_type not in VOLTAGE_SOURCES
                    and ctrl.id not in wanted):
                wanted.append(ctrl.id)

    used_ids = {e.id.upper() for e in circuit.elements}
    used_nodes = {n for e in circuit.elements for n in (e.node_positive, e.node_negative)}
    result: Dict[str, Tuple[str, str]] = {}
    for eid in wanted:
        name, node = f"Vsense_{eid}", f"_s_{eid}"
        while name.upper() in used_ids:
            name += "_"
        while node in used_nodes:
            node += "_"
        used_ids.add(name.upper())
        used_nodes.add(node)
        result[eid] = (name, node)
    return result


def _dependent_lcapy_line(
    elem: ParsedElement,
    by_id: Dict[str, ParsedElement],
    sense: Dict[str, Tuple[str, str]],
) -> str:
    """
    Bağımlı kaynağın lcapy satırı. elem.node_negative, ölçüm kaynağı varsa
    zaten gizli düğümle değiştirilmiş olarak gelir (bkz. to_lcapy_netlist).

    Kontrol işareti kazanca katılır: E1 … V(-R2) 3 → kazanç −3.
    """
    p = elem.params
    gain = p["gain"] * p["control_sign"]
    ctrl = by_id[p["control_id"]]
    t = elem.element_type

    if t in (ElementType.VCVS, ElementType.VCCS):
        # Kontrol gerilimi = V(ctrl.n+) − V(ctrl.n−) (gerçek düğümler; gizli
        # düğüm ölçüm kaynağından dolayı n− ile aynı gerilimdedir)
        c_pos, c_neg = ctrl.node_positive, ctrl.node_negative
        if t == ElementType.VCVS:
            return (f"{elem.id} {elem.node_positive} {elem.node_negative} "
                    f"{c_pos} {c_neg} {{{gain}}}")
        # G: lcapy akımı İLK düğümden çıkarır → sözleşmedeki (n− ucundan çıkar)
        # davranış için uçlar ters yazılır
        return (f"{elem.id} {elem.node_negative} {elem.node_positive} "
                f"{c_pos} {c_neg} {{{gain}}}")

    # H / F: kontrol akımı bir gerilim kaynağından okunur
    ctrl_name = sense[ctrl.id][0] if ctrl.id in sense else ctrl.id
    return (f"{elem.id} {elem.node_positive} {elem.node_negative} "
            f"{ctrl_name} {{{gain}}}")
