"""
Devre çözülebilirlik/kararlı hâl denetimleri, çözümsüzlük gerekçeleri ve SINE uyarıları.
"""

from typing import Dict, List, Optional

from explainer.formatting import ek, eng
from parser.netlist_parser import (
    DEPENDENT_SOURCES, SINE_SOURCES, ElementType, ParsedCircuit, element_nodes,
)
from solver.error_text import is_singular_error
from solver.numeric import _extract_numeric
from solver.topology_check import fault_reasons


# Çözülemeyen (tekil) devre hatasının işareti; main.py bu önekle başlayan hatayı
# "Devre çözülemedi" yanıtına (HTTP 422) çevirir.
UNSOLVABLE_PREFIX = "⛔ "


def _dc_no_steady_state_reason(parsed: ParsedCircuit) -> Optional[str]:
    """
    DC'de kararlı hâli olmayan iki durum: akım kaynağının akımı yalnızca kondansatörden dönebiliyor
    (gerilim sınırsız büyür) ya da gerilim kaynağı direnç görmeden yalnızca bobine bağlı (akım
    sınırsız büyür). Yalnızca R, L, C ve DC kaynaklı devrelere bakılır; yoksa None.
    """
    allowed = (ElementType.RESISTOR, ElementType.CAPACITOR, ElementType.INDUCTOR,
               ElementType.DC_SOURCE, ElementType.CURRENT_DC)
    if not parsed.elements or any(e.element_type not in allowed for e in parsed.elements):
        return None

    def components(links):
        parent: Dict[str, str] = {}

        def find(n):
            parent.setdefault(n, n)
            while parent[n] != n:
                parent[n] = parent[parent[n]]
                n = parent[n]
            return n

        for a, b in links:
            parent[find(a)] = find(b)
        return find

    def ends(*kinds):
        return [e for e in parsed.elements if e.element_type in kinds]

    # Kondansatör açık, bobin kısa devre: akım kaynağının net akımı dönemeyen parça var mı?
    find = components((e.node_positive, e.node_negative) for e in ends(
        ElementType.RESISTOR, ElementType.INDUCTOR, ElementType.DC_SOURCE))
    net: Dict[str, float] = {}
    for src in ends(ElementType.CURRENT_DC):
        net[find(src.node_negative)] = net.get(find(src.node_negative), 0.0) + src.value
        net[find(src.node_positive)] = net.get(find(src.node_positive), 0.0) - src.value
    for part, current in net.items():
        caps = [c for c in ends(ElementType.CAPACITOR)
                if (find(c.node_positive) == part) != (find(c.node_negative) == part)]
        if abs(current) <= 1e-15 or not caps:
            continue
        sources = ", ".join(s.id for s in ends(ElementType.CURRENT_DC))
        rate = ""
        if len(caps) == 1:
            rate = (f" Hızı: dV/dt = I / C = {eng(abs(current), 'A')} / {eng(caps[0].value, 'F')} = "
                    f"{eng(abs(current) / caps[0].value, 'V')}/s.")
        return ("Bu devrenin DC kararlı hâli yok. DC'de kondansatör açık devre sayılır; "
                f"{sources} akım kaynağının akımı ise dönecek başka yol bulamıyor. Bu yüzden "
                f"{', '.join(c.id for c in caps)} sürekli dolar ve gerilimi sınırsız büyür.{rate}\n\n"
                "Ne yapabilirsiniz:\n"
                "• Kondansatöre paralel bir direnç ekleyin; akım o yoldan döner ve devre çözülür.\n"
                "• Akım kaynağı yerine gerilim kaynağı kullanın.\n"
                "• Kaynağı AC yapın; AC'de kondansatörden akım geçer.")

    # Gerilim kaynağının iki ucu yalnızca bobinlerle bağlı mı?
    for v in ends(ElementType.DC_SOURCE):
        others = [e for e in ends(ElementType.DC_SOURCE) if e is not v]
        coils = ends(ElementType.INDUCTOR)
        with_coils = components([(v.node_positive, v.node_positive)]
                                + [(e.node_positive, e.node_negative) for e in others + coils])
        direct = components([(v.node_positive, v.node_positive)]
                            + [(e.node_positive, e.node_negative) for e in others])
        if (abs(v.value) <= 1e-15 or with_coils(v.node_positive) != with_coils(v.node_negative)
                or direct(v.node_positive) == direct(v.node_negative)):
            continue
        rate = ""
        if len(coils) == 1:
            rate = (f" Hızı: dI/dt = V / L = {eng(abs(v.value), 'V')} / {eng(coils[0].value, 'H')} = "
                    f"{eng(abs(v.value) / coils[0].value, 'A')}/s.")
        return ("Bu devrenin DC kararlı hâli yok. DC'de bobin kısa devre sayılır; "
                f"{v.id} gerilim kaynağı arada direnç olmadan yalnızca bobine bağlı. Bu yüzden "
                f"akım sürekli artar ve sınırsız büyür.{rate}\n\n"
                "Ne yapabilirsiniz:\n"
                "• Bobine seri bir direnç ekleyin; gerçek bobinlerin de iç direnci vardır.\n"
                "• Kaynağı AC yapın; AC'de bobinin reaktansı akımı sınırlar.")
    return None


def _unsolvable_reason(cct, parsed: ParsedCircuit, is_dc: bool,
                       frequency: Optional[float]) -> Optional[str]:
    """
    Devre denklemleri tekilse (tek bir çözüm yoksa) öğrenciye Türkçe açıklama döndürür,
    çözülebiliyorsa None. lcapy tekil sistemde "MNA A matrix is not invertible" verir.
    """
    if is_dc:
        reason = _dc_no_steady_state_reason(parsed)
        if reason:
            return reason
    nodes = sorted({n for e in parsed.elements
                    for n in element_nodes(e)} - {"0"})
    if not nodes:
        return None
    try:
        _extract_numeric(cct[nodes[0]].V, is_dc, frequency)
        return None
    except Exception as e:
        if not is_singular_error(e):
            return None   # başka tür hata: olağan akış kendi mesajını üretir

    # Hatalı elemanı adıyla söyleyebiliyorsak genel "olası nedenler" listesi yerine onu veririz
    specific = fault_reasons(parsed, is_dc)
    if specific:
        return specific

    lines = ["Bu devrenin tek bir çözümü yok: devre denklemleri birbiriyle çelişiyor "
             "ya da bilinmeyenleri bulmaya yetmiyor (tekil sistem).", "", "Olası nedenler:"]
    if any(e.element_type in DEPENDENT_SOURCES for e in parsed.elements):
        lines.append("• Bağımlı kaynağın kazancı, devredeki dirençlerin etkisini tam olarak "
                     "sıfırlıyor olabilir. Örneğin tek çevrede R1 + R2 + R3 − k·R = 0 olursa "
                     "kaynak sıfır dirençle kısa devre edilmiş gibi olur. Kazancı ya da bir "
                     "direnç değerini değiştirmeyi deneyin.")
    lines += [
        "• İki gerilim kaynağı doğrudan paralel bağlı ya da bir gerilim kaynağı kısa devre edilmiş olabilir.",
        "• İki akım kaynağı doğrudan seri bağlı olabilir.",
        "• Devrenin bir kısmı GND'ye hiçbir yolla bağlı olmayabilir (boşta kalan eleman).",
    ]
    if is_dc and any(e.element_type in (ElementType.CAPACITOR, ElementType.INDUCTOR)
                     for e in parsed.elements):
        lines.append("• DC analizde bobin kısa devre, kondansatör açık devre sayılır; "
                     "bu da yukarıdaki durumlardan birini oluşturabilir.")
    return "\n".join(lines)


def _ignored_sine_warnings(parsed: ParsedCircuit) -> List[str]:
    """SINE kaynağında gecikme ya da sönüm sıfır değilse: çözücü bunları hesaba katmaz, sessiz kalma."""
    out: List[str] = []
    for e in parsed.elements:
        if e.element_type not in SINE_SOURCES:
            continue
        if abs(e.params.get("delay", 0.0)) > 0 or abs(e.params.get("damping", 0.0)) > 0:
            out.append(f"⚠ {ek(e.id, 'in')} gecikme ve sönüm değerleri hesaba katılmadı; kaynak "
                       "t = 0'dan itibaren sönümsüz bir sinüs olarak alındı.")
    return out
