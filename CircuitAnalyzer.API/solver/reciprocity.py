"""
CircuitAnalyzer API — Karşıtlık (reciprocity) teoremi: uygunluk denetimi ve sonuç yapısı

Tek bağımsız kaynaklı, yalnızca R/L/C içeren doğrusal devrede kaynak ile bir pasif eleman
(hedef) yer değiştirirse ölçülen büyüklük aynı kalır:

    gerilim kaynağı E (a+, b−), hedef Y (c, d):   I₁ = Y'nin c → d akımı  (E kendi yerinde)
                                                  I₂ = eski kaynak kolunda devreye a'dan giren akım
                                                       (E, Y ile seri bağlanınca)       I₁ = I₂
    akım kaynağı I (a, b), hedef Y (c, d):        V₁ = V_c − V_d  (I kendi yerinde)
                                                  V₂ = V_a − V_b  (I, Y'nin uçlarına taşınınca)  V₁ = V₂

İkinci çözüm circuit_solver._solve_reciprocity'de yapılır; burada yalnızca çözümsüz
(saf Python) kısımlar bulunur: uygunluk denetimi ve sonuç veri yapısı.
"""

import cmath
import math
from dataclasses import dataclass
from typing import Optional, Tuple

from models.request import AnalysisMode
from parser.netlist_parser import (
    ALL_SOURCES, CURRENT_SOURCES, DEPENDENT_SOURCES, ElementType, ParsedCircuit, ParsedElement,
)

_PASSIVE = (ElementType.RESISTOR, ElementType.INDUCTOR, ElementType.CAPACITOR)
_COUNT_WORDS = {2: "iki", 3: "üç", 4: "dört", 5: "beş"}


@dataclass
class ReciprocityAnalysis:
    """
    form:   "current" → gerilim kaynağı, ölçülen büyüklük akım (I₁, I₂)
            "voltage" → akım kaynağı, ölçülen büyüklük gerilim (V₁, V₂)
    source_value: kaynağın değeri (DC: gerçel; AC: fazör)
    case1 / case2: 1. durumdaki (kaynak yerinde) ve 2. durumdaki (kaynak hedef kolda) ölçüm
    """
    form: str
    source: ParsedElement
    target: ParsedElement
    source_value: complex
    case1: complex
    case2: complex


def source_phasor(e: ParsedElement) -> complex:
    """Bağımsız kaynağın değeri: DC gerçel, AC genlik∠faz (gösterim tabanında)."""
    if e.element_type in (ElementType.DC_SOURCE, ElementType.CURRENT_DC):
        return complex(e.value)
    amp = float(e.params.get("amplitude", e.value))
    return amp * cmath.exp(1j * math.radians(float(e.params.get("phase", 0.0))))


def reciprocity_pair(
    parsed: ParsedCircuit, mode: AnalysisMode, target_id: Optional[str],
) -> Tuple[Optional[Tuple[ParsedElement, ParsedElement]], str]:
    """
    ((kaynak, hedef), '') ya da (None, Türkçe uygulanamama sebebi).

    Koşullar: DC ya da tek frekanslı AC (fazör); tam bir bağımsız kaynak; diğer her eleman
    R, L veya C. Hedef boşsa netlist sırasındaki son R/L/C alınır.
    """
    if mode not in (AnalysisMode.DC, AnalysisMode.AC_PHASOR):
        return None, ("karşıtlık teoremi yalnızca DC ya da tek frekanslı AC (fazör) çözümünde "
                      "uygulanır.")
    for e in parsed.elements:
        if e.element_type in DEPENDENT_SOURCES:
            return None, (f"devrede bağımlı (kontrollü) kaynak var ({e.id}); karşıtlık teoremi "
                          "yalnızca bağımsız kaynaklı, R/L/C elemanlı devrelerde geçerlidir.")
        if e.element_type == ElementType.SWITCH:
            return None, f"devrede anahtar var ({e.id}); karşıtlık teoremi anahtarsız devrelerde uygulanır."
        if e.element_type == ElementType.TRANSFORMER:
            return None, f"devrede transformatör var ({e.id}); karşıtlık teoremi bu devreye uygulanmaz."
    sources = [e for e in parsed.elements if e.element_type in ALL_SOURCES]
    if not sources:
        return None, "devrede bağımsız kaynak yok; karşıtlık teoremi tek kaynaklı devrelerde uygulanır."
    if len(sources) > 1:
        names = ", ".join(s.id for s in sources)
        count = _COUNT_WORDS.get(len(sources), str(len(sources)))
        return None, (f"devrede {count} bağımsız kaynak var ({names}); karşıtlık teoremi "
                      "tek kaynaklı devrelerde uygulanır.")
    for e in parsed.elements:
        if e.element_type not in _PASSIVE and e.element_type not in ALL_SOURCES:
            return None, (f"{e.id} elemanı direnç, bobin ya da kondansatör değil; karşıtlık "
                          "teoremi yalnızca R, L ve C elemanlı devrelerde anlatılır.")
    src = sources[0]
    passives = [e for e in parsed.elements if e.element_type in _PASSIVE]
    if not passives:
        return None, "devrede direnç, bobin ya da kondansatör yok; kaynağın taşınacağı bir kol bulunamadı."

    wanted = (target_id or "").strip()
    if not wanted:
        return (src, passives[-1]), ""
    target = next((e for e in parsed.elements if e.id.upper() == wanted.upper()), None)
    if target is None:
        return None, f"“{wanted}” adlı bir eleman devrede yok; ikinci kol olarak devredeki bir R, L ya da C seçilmelidir."
    if target.id == src.id:
        return None, (f"ikinci kol olarak kaynağın kendisi ({src.id}) seçilmiş; kaynağın "
                      "taşınacağı kol bir R, L ya da C olmalıdır.")
    if target.element_type not in _PASSIVE:
        return None, f"{target.id} bir direnç, bobin ya da kondansatör değil; ikinci kol bir R, L ya da C olmalıdır."
    return (src, target), ""


def is_current_source(e: ParsedElement) -> bool:
    return e.element_type in CURRENT_SOURCES
