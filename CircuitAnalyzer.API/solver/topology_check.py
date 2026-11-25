"""
Devre topolojisi denetimi — çözümden önce, saf (lcapy kullanmayan) ve hızlı.

Üç "çözümsüz devre" hatası ve bir uyarı bulur; hepsini ilgili elemanların adıyla söyler:

  a) Kısa devre edilmiş gerilim kaynağı: iki ucu aynı düğümde.
  b) Yalnızca gerilim kaynaklarından oluşan halka (iki kaynağın doğrudan paralel bağlanması
     dahil). DC'de bobin tel sayılır, o yüzden halkaya girebilir.
  c) GND'ye (düğüm 0) hiçbir yolla bağlı olmayan bölüm: akım kaynakları ve (varsa) hiçbir şey
     gerilim belirlemez. Seri bağlı iki akım kaynağının ortasındaki düğüm tipik örnektir.
  Uyarı) Bir ucu hiçbir yere bağlı olmayan eleman: akım taşımaz, bir tel eksik olabilir.

Kondansatör hem DC'de hem AC'de iki düğümü BAĞLI sayılır (c için): DC'de açık devredir ama
çözücü, kondansatörün yalnız bağladığı bölümü "akım yok, gerilim aynı" kararlı hâliyle çözer ve
bu sonuç öğrenciye gösterilen doğru sonuçtur; bu devreleri engellemek çalışan devreyi reddetmek olurdu.

ÇÖZÜMDEN ÖNCE ENGELLEME yalnızca hata KESİN olduğunda yapılır (bkz. can_block): devrede yalnızca
R, L, C, bağımsız DC ya da AC kaynaklar (ve anahtarlar) varsa. Bağımlı kaynak, transformatör,
üç faz, wattmetre gibi kuralların modellemediği bir eleman varsa engellenmez; çözücü kendisi tekil
çıkarsa aynı tanı yalnızca daha özel bir açıklama için kullanılır.
"""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from explainer.formatting import ek
from parser.netlist_parser import (
    ElementType, ParsedCircuit, ParsedElement, VOLTAGE_SOURCES, CURRENT_SOURCES,
    DEPENDENT_SOURCES, DEPENDENT_CURRENT_OUTPUT, circuit_at_time, element_nodes, has_switches,
)

# Hata kesin olduğunda engellenebilen eleman kümeleri (anahtar önce t > 0 konumuna çevrilir)
_BLOCK_DC = (ElementType.RESISTOR, ElementType.CAPACITOR, ElementType.INDUCTOR,
             ElementType.DC_SOURCE, ElementType.CURRENT_DC)
_BLOCK_AC = (ElementType.RESISTOR, ElementType.CAPACITOR, ElementType.INDUCTOR,
             ElementType.AC_SOURCE_SINE, ElementType.AC_SOURCE_PHASOR,
             ElementType.CURRENT_AC_SINE, ElementType.CURRENT_AC_PHASOR)

_HINT_VLOOP = "Kaynaklardan birini devreden çıkarın ya da halkaya bir direnç ekleyin."
_HINT_VLOOP_REAL = ("Gerçek kaynakların iç direnci vardır; kaynağa seri küçük bir direnç "
                    "koymak sorunu çözer.")
_HINT_VLOOP_AC = "Kaynağı AC yapın; AC'de bobin tel gibi davranmaz."
_HINT_SHORT = "Kaynağın uçlarından birini doğru düğüme bağlayın."
_HINT_SHORT_WIRE = "Bu bir tel olacaksa kaynağı devreden çıkarın."
_HINT_FLOAT_WIRE = ("Eksik teli çizin: bu bölümü bir elemanla GND'ye (ya da devrenin geri "
                    "kalanına) bağlayın.")
_HINT_FLOAT_CS = ("Akım kaynağına paralel bir direnç ekleyin; akım o yoldan döner ve gerilim "
                  "belirlenir.")
_HINT_SERIES_CS = "Seri bağlı akım kaynaklarından birini kaldırın ya da ortadaki düğümü bir elemanla GND'ye bağlayın."


@dataclass
class Fault:
    kind: str                       # "short" | "vloop" | "floating"
    elements: List[str]             # ilgili eleman adları
    problem: str                    # ne oluyor (tek cümle/paragraf)
    hints: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════
#  YARDIMCILAR
# ═══════════════════════════════════════════════════════

def _names(ids: List[str]) -> str:
    """['R1'] → 'R1'; ['R1','R2'] → 'R1 ve R2'; üç ve fazlası 'R1, R2 ve R3'."""
    if len(ids) <= 1:
        return "".join(ids)
    return ", ".join(ids[:-1]) + " ve " + ids[-1]


def _node(n: str) -> str:
    return "GND" if n == "0" else f"Düğüm {n}"


class _Dsu:
    def __init__(self):
        self.parent: Dict[str, str] = {}

    def find(self, n: str) -> str:
        self.parent.setdefault(n, n)
        root = n
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[n] != root:          # yol sıkıştırma
            self.parent[n], n = root, self.parent[n]
        return root

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


def _at_after(parsed: ParsedCircuit) -> ParsedCircuit:
    """Anahtarlı devre t > 0 konumunda (çözücü de böyle çözer); anahtarsızsa aynı nesne."""
    return circuit_at_time(parsed, "after") if has_switches(parsed) else parsed


def can_block(parsed: ParsedCircuit, is_dc: bool) -> bool:
    """
    Hata KESİN mi sayılır? Yalnızca R, L, C ve moda uygun bağımsız kaynaklar (DC modda DC,
    AC modda AC kaynaklar) varsa, en az bir kaynak sıfırdan farklıysa ve iki ucu aynı düğümde
    olan pasif eleman yoksa. (Çağıran anahtarları önce konumuna çevirir.) Başka her şeyde False.
    Bu sınırlar rastgele devre taramasıyla (engel çıkan her devreyi çözücü de çözememeli) seçildi.
    """
    allowed = _BLOCK_DC if is_dc else _BLOCK_AC
    if not all(e.element_type in allowed or e.element_type == ElementType.SWITCH
               for e in parsed.elements):
        return False
    # İki ucu aynı düğümde olan R/L/C (kısa devre edilmiş pasif eleman): çözücü bu yapay durumu
    # bazen "çözer", bu yüzden kesin hükmetmeyiz (gerilim kaynağı için (a) kuralı geçerlidir).
    if any(e.element_type not in VOLTAGE_SOURCES and e.node_positive == e.node_negative
           for e in parsed.elements if e.element_type != ElementType.SWITCH):
        return False
    # Hiç sıfırdan farklı bağımsız kaynak yoksa çözücü her şeyi 0 bulur (uyarısız çözülür);
    # bunu da reddetmeyiz.
    return any(e.element_type in VOLTAGE_SOURCES + CURRENT_SOURCES and abs(e.value) > 0
               for e in parsed.elements)


# ═══════════════════════════════════════════════════════
#  HATALAR
# ═══════════════════════════════════════════════════════

def _voltage_faults(circuit: ParsedCircuit, is_dc: bool) -> List[Fault]:
    """(a) kısa devre edilmiş gerilim kaynağı ve (b) yalnızca kaynak (DC'de bobin) halkaları."""
    faults: List[Fault] = []
    vs = [e for e in circuit.elements if e.element_type in VOLTAGE_SOURCES]
    for v in vs:
        if v.node_positive == v.node_negative:
            faults.append(Fault(
                "short", [v.id],
                f"{ek(v.id, 'in')} iki ucu aynı düğüme ({_node(v.node_positive)}) bağlı (kısa devre "
                "edilmiş). Gerilim kaynağı uçları arasında gerilim üretmek zorundadır; iki ucu "
                "birleşince bu sağlanamaz.",
                [_HINT_SHORT, _HINT_SHORT_WIRE]))

    # Halka: kaynaklar (+ DC'de bobinler) kenar olarak eklenir; ağacı kapatan kenar bir halkadır
    edges: List[ParsedElement] = [v for v in vs if v.node_positive != v.node_negative]
    if is_dc:
        edges += [e for e in circuit.elements
                  if e.element_type == ElementType.INDUCTOR and e.node_positive != e.node_negative]
    dsu = _Dsu()
    adj: Dict[str, List[Tuple[str, ParsedElement]]] = {}
    for e in edges:
        a, b = e.node_positive, e.node_negative
        if dsu.find(a) == dsu.find(b):
            path = _tree_path(adj, a, b)
            loop = sorted(path + [e], key=circuit.elements.index)     # netlistteki sırayla
            sources = [x for x in loop if x.element_type in VOLTAGE_SOURCES]
            coils = [x for x in loop if x.element_type == ElementType.INDUCTOR]
            if sources:
                faults.append(_loop_fault(sources, coils))
            continue
        dsu.union(a, b)
        adj.setdefault(a, []).append((b, e))
        adj.setdefault(b, []).append((a, e))
    return faults


def _tree_path(adj, a: str, b: str) -> List[ParsedElement]:
    """Orman içinde a'dan b'ye giden kenarlar (BFS)."""
    prev: Dict[str, Tuple[str, ParsedElement]] = {}
    seen = {a}
    queue = [a]
    while queue and b not in seen:
        cur = queue.pop(0)
        for nxt, e in adj.get(cur, []):
            if nxt not in seen:
                seen.add(nxt)
                prev[nxt] = (cur, e)
                queue.append(nxt)
    path: List[ParsedElement] = []
    node = b
    while node != a:
        node, e = prev[node][0], prev[node][1]
        path.append(e)
    path.reverse()
    return path


def _loop_fault(sources: List[ParsedElement], coils: List[ParsedElement]) -> Fault:
    src_ids = [s.id for s in sources]
    coil_ids = [c.id for c in coils]
    if len(sources) == 2 and not coils:
        problem = (f"{_names(src_ids)} gerilim kaynakları doğrudan paralel bağlı (uçları aynı iki "
                   "düğüme bağlı). İki ideal gerilim kaynağı aynı iki nokta arasında olamaz: "
                   "değerleri farklıysa gerilim yasası çelişir, aynıysa aralarından geçen akım "
                   "belirlenemez.")
    elif coils:
        src_word = "gerilim kaynağı" if len(src_ids) == 1 else "gerilim kaynakları"
        coil_word = "bobini" if len(coil_ids) == 1 else "bobinleri"
        problem = (f"{_names(src_ids)} {src_word} ile DC'de tel sayılan {_names(coil_ids)} "
                   f"{coil_word}, arada direnç olmadan kapalı bir halka oluşturuyor. Halkadaki "
                   "gerilimler birbirini tutmaz ya da halkadaki akım belirlenemez.")
    else:
        problem = (f"{_names(src_ids)} gerilim kaynakları, arada direnç olmadan kapalı bir halka "
                   "oluşturuyor. Halkadaki gerilimler birbirini tutmaz ya da halkadaki akım "
                   "belirlenemez.")
    hints = [_HINT_VLOOP, _HINT_VLOOP_REAL]
    if coils:
        hints.append(_HINT_VLOOP_AC)
    return Fault("vloop", src_ids + coil_ids, problem, hints)


def _floating_faults(circuit: ParsedCircuit) -> List[Fault]:
    """(c) GND'ye (düğüm 0) hiçbir yolla bağlı olmayan bölümler."""
    conducting = [e for e in circuit.elements
                  if e.element_type not in CURRENT_SOURCES
                  and e.element_type not in DEPENDENT_CURRENT_OUTPUT
                  and e.element_type != ElementType.SWITCH]
    dsu = _Dsu()
    for e in circuit.elements:
        for n in element_nodes(e):
            dsu.find(n)
    for e in conducting:
        nodes = element_nodes(e)
        for n in nodes[1:]:
            dsu.union(nodes[0], n)
    ground = dsu.find("0")

    parts: Dict[str, List[str]] = {}
    for n in list(dsu.parent):
        r = dsu.find(n)
        if r != ground:
            parts.setdefault(r, []).append(n)

    faults: List[Fault] = []
    for root, nodes in sorted(parts.items(), key=lambda kv: sorted(kv[1])[0]):
        inside = [e for e in conducting if dsu.find(e.node_positive) == root]
        sources_in = [e for e in circuit.elements
                      if (e.element_type in CURRENT_SOURCES or e.element_type in DEPENDENT_CURRENT_OUTPUT)
                      and all(dsu.find(n) == root for n in element_nodes(e))]
        attached = [e for e in circuit.elements
                    if (e.element_type in CURRENT_SOURCES or e.element_type in DEPENDENT_CURRENT_OUTPUT)
                    and any(dsu.find(n) == root for n in element_nodes(e))
                    and not all(dsu.find(n) == root for n in element_nodes(e))]
        inner = [e.id for e in inside + sources_in]
        attach_ids = [e.id for e in attached]
        node_text = ", ".join(sorted(nodes, key=lambda x: (len(x), x)))
        if inner:
            what = (f"{_names(inner)} {'elemanı' if len(inner) == 1 else 'elemanları'} "
                    f"({_node(sorted(nodes)[0]) if len(nodes) == 1 else 'Düğüm ' + node_text})")
        else:
            what = _node(sorted(nodes)[0])
        if attach_ids:
            kind_word = "akım kaynağı" if len(attach_ids) == 1 else "akım kaynakları"
            if inner:
                problem = (f"{what} GND'ye yalnızca {_names(attach_ids)} {kind_word} üzerinden "
                           "bağlı. Akım kaynağı gerilim belirlemez; bu yüzden bölümün gerilimleri "
                           "tanımsız kalır.")
                hints = [_HINT_FLOAT_WIRE, _HINT_FLOAT_CS]
            else:
                problem = (f"{what}, yalnızca {_names(attach_ids)} {kind_word} arasında kalmış "
                           "(akım kaynakları seri bağlı); bu düğümü GND'ye bağlayan başka bir eleman "
                           "yok. Akım kaynağı gerilim belirlemez, bu yüzden düğümün gerilimi "
                           "tanımsız kalır.")
                hints = [_HINT_SERIES_CS, _HINT_FLOAT_WIRE]
        else:
            problem = (f"{what} devrenin geri kalanına hiçbir yoldan bağlı değil; GND'ye yolu "
                       "olmadığı için bu bölümün gerilimleri belirlenemez.")
            hints = [_HINT_FLOAT_WIRE]
        faults.append(Fault("floating", inner + attach_ids, problem, hints))
    return faults


def find_faults(parsed: ParsedCircuit, is_dc: bool, include_floating: bool = True) -> List[Fault]:
    """
    Devrenin tek çözümünü engelleyen yapısal hataların hepsi (a, b ve istenirse c).
    Düğüm 0 yoksa (GND eksik; ayrı bir uyarı verilir) hiçbir şey söylenmez.
    """
    circuit = _at_after(parsed)
    nodes = {n for e in circuit.elements for n in element_nodes(e)}
    if "0" not in nodes:
        return []
    faults = _voltage_faults(circuit, is_dc)
    if include_floating:
        faults += _floating_faults(circuit)
    return faults


def describe(faults: List[Fault]) -> Optional[str]:
    """Hataları öğrenciye gidecek tek metne çevirir ("Ne yapabilirsiniz" önerileriyle)."""
    if not faults:
        return None
    if len(faults) == 1:
        head = f"Bu devrenin tek bir çözümü yok. {faults[0].problem}"
    else:
        head = "Bu devrenin tek bir çözümü yok:\n" + "\n".join(f"• {f.problem}" for f in faults)
    hints: List[str] = []
    for f in faults:
        for h in f.hints:
            if h not in hints:
                hints.append(h)
    return head + "\n\nNe yapabilirsiniz:\n" + "\n".join(f"• {h}" for h in hints)


def blocking_reason(parsed: ParsedCircuit, is_dc: bool) -> Optional[str]:
    """Çözümden önce engelleyen KESİN hata metni; hata yoksa ya da kesin değilse None."""
    circuit = _at_after(parsed)
    if not can_block(circuit, is_dc):
        return None
    return describe(find_faults(circuit, is_dc))


def fault_reasons(parsed: ParsedCircuit, is_dc: bool) -> Optional[str]:
    """
    Çözücü devreyi tekil bulduktan SONRA daha özel bir açıklama için tanı. Her devrede
    çalışır ama yalnızca bağımsız kaynaklar için konuşur: çözücünün iç (açılmış) devresinde
    ve transformatörlü devrede GND'ye bağlantı kuralı (c) uygulanmaz.
    """
    if getattr(parsed, "internal_names", False):
        return None      # açılmış üç faz devresi: eleman adları öğrencinin devresinde yok
    include_floating = not any(e.element_type == ElementType.TRANSFORMER for e in parsed.elements)
    return describe(find_faults(parsed, is_dc, include_floating))


# ═══════════════════════════════════════════════════════
#  UYARI: BİR UCU BOŞTA KALAN ELEMAN
# ═══════════════════════════════════════════════════════

_DANGLING_TYPES = (
    ElementType.RESISTOR, ElementType.CAPACITOR, ElementType.INDUCTOR, ElementType.IMPEDANCE,
) + VOLTAGE_SOURCES + CURRENT_SOURCES + DEPENDENT_SOURCES + (ElementType.DIODE,)


def dangling_warnings(parsed: ParsedCircuit, ignore_nodes: Iterable[str] = ()) -> List[str]:
    """
    Tek bir elemanın tek bir ucunun değdiği (GND dışı) düğüm: o eleman akım taşımaz, bir tel
    eksik olabilir. ⚠ ile başlar (durum "warning" olur). Uyarı verilmeyenler: seçili
    Thevenin/Norton uçları ve gerilim probu düğümleri (`ignore_nodes`), transformatör sargıları,
    anahtarlar, üç faz elemanları, wattmetreler. Çözümü engellemez.
    """
    if getattr(parsed, "internal_names", False):
        return []
    skip = set(ignore_nodes)
    touches: Dict[str, List[ParsedElement]] = {}
    for e in parsed.elements:
        for n in element_nodes(e):
            touches.setdefault(n, []).append(e)
    if "0" not in touches:
        return []
    out: List[str] = []
    done: Set[str] = set()
    for e in parsed.elements:
        if e.element_type not in _DANGLING_TYPES or e.id in done:
            continue
        loose = [n for n in element_nodes(e)
                 if n != "0" and n not in skip and len(touches[n]) == 1]
        if not loose:
            continue
        done.add(e.id)
        if len(loose) == len(set(element_nodes(e))) and len(loose) >= 2:
            out.append(f"⚠ {e.id} hiçbir yere bağlı değil (iki ucu da boşta); bu eleman devreye "
                       "katılmıyor. Teller eksik olabilir.")
        else:
            out.append(f"⚠ {ek(e.id, 'in')} bir ucu hiçbir yere bağlı değil ({_node(loose[0])}); "
                       "bu eleman akım taşımaz. Bir tel eksik olabilir.")
    return out
