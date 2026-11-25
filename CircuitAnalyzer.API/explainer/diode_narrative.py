"""
CircuitAnalyzer API — Diyotlu devrelerin anlatımı (Faz 4a, kitap üslubu)

Kitaptaki (Selek, Elektronik-1) çözüm adımları:
    1. Polarma ve iletim/yalıtım tespiti          → "Diyotların Durumu"
    2. Elektriksel eşdeğer devrenin çizimi         → "Elektriksel Eşdeğer Devre"
    3. KVL ile V_O, V_R ve Ohm yasasıyla akım       → "Çevre Denklemi (KVL)" (tek çevreli devrede)
Sonra seçilen yöntemin (düğüm/çevre) bölümleri eşdeğer devre üzerinde gelir; iletimdeki diyot
orada "D1 (0,7 V)" gibi, eşik gerilimi kadar bir gerilim kaynağı olarak görünür.

Terimler: iletimde / yalıtımda / doğru polarma / ters polarma / eşik gerilimi V_T.
Rapor (solver.diode.DiodeReport) burada yalnızca öznitelikleriyle okunur (döngüsel içe aktarma yok).
"""

from collections import Counter
from typing import Dict, List, Optional, Tuple

from explainer.formatting import MINUS, ek, eng, node_name, node_v, num
from models.response import ExplanationBlock, ExplanationSection
from parser.netlist_parser import DIODE_TYPES, ElementType, ParsedElement


class _Sec:
    def __init__(self, title: str):
        self.title = title
        self.blocks: List[ExplanationBlock] = []

    def add(self, kind: str, text: str):
        self.blocks.append(ExplanationBlock(kind=kind, text=text))

    def build(self) -> ExplanationSection:
        return ExplanationSection(title=self.title, blocks=self.blocks)


def is_sub(e: ParsedElement) -> bool:
    """İletimdeki diyotun eşdeğer kaynağı mı?"""
    return bool(e.params.get("diode_of")) if e.params else False


def sub_label(e: ParsedElement) -> str:
    """Denklemlerdeki adı: 'D1 (0,7 V)'."""
    return f"{e.id} ({_volts(e.params.get('v_t', e.value))})"


def _and(items: List[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " ve " + items[-1]


def _volts(x: float) -> str:
    """Diyot gerilimleri kitaptaki gibi volt cinsinden: '0,7 V' (700 mV değil)."""
    return f"{num(x)} V"


def _vt(d) -> str:
    return _volts(d.v_t)


def _model_text(d) -> str:
    return f"{d.id} ({d.label}, V_T = {_vt(d)})"


def _volt_ek(text: str) -> str:
    """'0,7 V' → "0,7 V'luk" (volt)."""
    return f"{text}'luk"


def intro_line(report) -> str:
    return "Diyotlar: " + ", ".join(_model_text(d) for d in report.diodes) + "."


# ═══════════════════════════════════════════════════════
#  1. DİYOTLARIN DURUMU
# ═══════════════════════════════════════════════════════

def _vak_text(d) -> str:
    return f"V_AK = {node_v(d.anode)} {MINUS} {node_v(d.cathode)} = {_volts(d.v_ak)}"


def _state_section(report) -> _Sec:
    s = _Sec("Diyotların Durumu")
    s.add("text",
          "Diyot doğrusal olmayan bir elemandır; önce her diyotun iletimde mi yalıtımda mı "
          "olduğunu bulmalıyız. Kural: diyot doğru polarmadaysa (anot katottan daha pozitif) ve "
          "anot–katot gerilimi V_AK eşik gerilimini (V_T) aşıyorsa iletimdedir; yerine V_T "
          "değerinde bir gerilim kaynağı konur (+ ucu anotta). Ters polarmada ya da V_AK eşik "
          "gerilimini aşmıyorsa yalıtımdadır; açık devre gibi davranır (I = 0).")
    s.add("text",
          f"Diyotların olası iletim/yalıtım birleşimleri denendi ({report.combos_tried} birleşim); "
          "aşağıdaki durum, bütün koşulları birlikte sağlayan birleşimdir. Koşullar, devre çözüldükten "
          "sonra bulunan değerlerle kontrol edilir:")
    for d in report.diodes:
        s.add("math", f"{_model_text(d)}: anot {node_name(d.anode)}, katot {node_name(d.cathode)}")
        if d.state == "ON":
            if d.is_ideal:
                what = "yerine kısa devre konur (ideal diyot, V_T = 0 V)"
            else:
                what = f"yerine {_volt_ek(_vt(d))} kaynak konur (+ ucu anoda)"
            if d.kind == "on_cut":
                s.add("check",
                      f"{d.id} doğru polarmada ama akım yolu kesik, akım geçmez: I_{d.id} = 0. "
                      f"Eşdeğer devrede {what}; akım yolunu yalıtımdaki bir diyot keser ✓")
            elif len(d.group) > 1:
                s.add("check",
                      f"{d.id} iletimde: {what}. I_{d.id} = {eng(d.i_total, 'A')} / {len(d.group)} = "
                      f"{eng(d.i, 'A')} > 0 ✓")
            else:
                s.add("check", f"{d.id} iletimde: {what}. I_{d.id} = {eng(d.i, 'A')} > 0 ✓")
        else:
            if d.v_ak is None:
                rev = d.v_ak_search < 0
                s.add("check",
                      f"{d.id} {'ters' if rev else 'doğru'} polarmada; bir ucu boşta kalan düğüme bağlı, "
                      "V_AK belirsiz ve akım yolu yok → yalıtımda, açık devre (I = 0) ✓")
            elif d.kind == "reverse":
                s.add("check",
                      f"{d.id} ters polarmada: {_vak_text(d)} < 0 → yalıtımda, açık devre "
                      f"(I_{d.id} = 0) ✓")
            elif d.kind == "zero":
                s.add("check",
                      f"{d.id}: {_vak_text(d)}, diyot polarılmamış → yalıtımda, açık devre "
                      f"(I_{d.id} = 0) ✓")
            else:
                rel = "<" if d.v_ak < d.v_t - 1e-12 else "="
                s.add("check",
                      f"{d.id} doğru polarmada ama yalıtımda: {_vak_text(d)} {rel} V_T = {_vt(d)} "
                      f"(eşik gerilimi aşılmıyor) → açık devre (I_{d.id} = 0) ✓")
    for note in report.notes:
        s.add("note", note)
    for n in report.floating_nodes:
        s.add("note", f"{node_name(n)} boşta kalır (akım yolu yok); gerilimi belirsizdir.")
    return s


# ═══════════════════════════════════════════════════════
#  2. ELEKTRİKSEL EŞDEĞER DEVRE
# ═══════════════════════════════════════════════════════

def _equivalent_section(report) -> _Sec:
    s = _Sec("Elektriksel Eşdeğer Devre")
    s.add("text", "Diyotların yerine eşdeğerlerini koyalım (elektriksel eşdeğer devre):")
    for d in report.diodes:
        if d.state == "OFF":
            s.add("math", f"{d.id} → açık devre (yalıtımda; devreden çıkarılır)")
        elif d.rep != d.id:
            s.add("math", f"{d.id} → {d.rep} ile birlikte tek kaynak (özdeş paralel diyotlar)")
        elif d.is_ideal:
            s.add("math", f"{d.id} → kısa devre (ideal diyot iletimde, 0 V); "
                          f"{node_name(d.anode)} ile {node_name(d.cathode)} birleşir")
        else:
            s.add("math", f"{d.id} → {_volt_ek(_vt(d))} gerilim kaynağı: + ucu anotta "
                          f"({node_name(d.anode)}), − ucu katotta ({node_name(d.cathode)})")
    for eid in report.dropped:
        s.add("math", f"{eid} boşta kalır: bağlı olduğu bölüm yalıtımdaki diyotlar yüzünden "
                      f"GND'ye bağlantısız, akım yolu yok (I_{eid} = 0)")
    ons = [d for d in report.diodes if d.state == "ON" and d.rep == d.id and not d.is_ideal]
    if ons:
        d = ons[0]
        s.add("text",
              "Bundan sonraki adımlar bu eşdeğer devre üzerinde yapılır; denklemlerde iletimdeki "
              f"diyot “{d.id} ({_vt(d)})” olarak, yani eşik gerilimi kadar bir gerilim kaynağı "
              "olarak görünür.")
    else:
        s.add("text", "Bundan sonraki adımlar bu eşdeğer devre üzerinde yapılır.")
    return s


def _fallback_section(report) -> Optional[_Sec]:
    if report.refused is None:
        return None
    title, what = report.refused
    s = _Sec(title)
    s.add("note",
          f"Bu devrede {what} uygulanamadı: diyot doğrusal olmayan bir elemandır; {what} yalnızca "
          "doğrusal devrelerde geçerlidir. “Düğüm Gerilimleri” yöntemini seçebilirsiniz; aynı "
          "sonuçları şimdi o yöntemle (diyotların eşdeğer devresi üzerinde) anlatıyoruz.")
    return s


# ═══════════════════════════════════════════════════════
#  3. TEK ÇEVRELİ DEVREDE KVL (kitap yöntemi)
# ═══════════════════════════════════════════════════════

_LOOP_TYPES = (ElementType.RESISTOR, ElementType.DC_SOURCE, ElementType.DIODE)


def single_loop(elements) -> Optional[List[Tuple[ParsedElement, str, str]]]:
    """
    Devre tek bir seri çevre mi (yalnız R, DC gerilim kaynağı ve diyot; her düğüme tam iki eleman)?
    Öyleyse çevre sırası [(eleman, giriş düğümü, çıkış düğümü)], GND'den başlayarak; değilse None.
    """
    elems = list(elements or [])
    if not elems or any(e.element_type not in _LOOP_TYPES for e in elems):
        return None
    if not any(e.element_type == ElementType.RESISTOR for e in elems):
        return None
    deg = Counter()
    for e in elems:
        deg[e.node_positive] += 1
        deg[e.node_negative] += 1
    if any(v != 2 for v in deg.values()) or len(deg) != len(elems):
        return None
    start = "0" if "0" in deg else sorted(deg)[0]
    order: List[Tuple[ParsedElement, str, str]] = []
    used = set()
    node = start
    while True:
        cand = [e for e in elems if id(e) not in used and node in (e.node_positive, e.node_negative)]
        if not cand:
            break
        e = cand[0]
        other = e.node_negative if node == e.node_positive else e.node_positive
        order.append((e, node, other))
        used.add(id(e))
        node = other
        if node == start:
            break
    return order if len(order) == len(elems) and node == start else None


def _value(v) -> float:
    return float(v) if isinstance(v, (int, float)) else float(v.real)


def _join(terms: List[Tuple[float, str]]) -> str:
    """[(işaret, metin)] → '−5 + 0,7 + V_O' (işaret ±1)."""
    out = ""
    for sign, text in terms:
        if not out:
            out = f"{MINUS}{text}" if sign < 0 else text
        else:
            out += f" {MINUS} {text}" if sign < 0 else f" + {text}"
    return out


def _plain(x: float) -> str:
    """KVL'de birimsiz sayı (V): eng'in sayısal kısmı önek olmadan."""
    from explainer.formatting import num
    return num(abs(x))


def _kvl_section(report, results) -> Optional[_Sec]:
    """
    Kitaptaki KVL çözümü. Ham devre tek seri çevreyse ve bir diyot yalıtımdaysa: akım yok.
    Eşdeğer devre (yalıtımdakiler çıkarılmış) tek seri çevreyse: KVL ile V_R (V_O) ve I.
    """
    info = report.by_id()
    raw_order = single_loop(report.circuit.elements if report.circuit is not None else None)
    off = ([e.id for e, _, _ in raw_order
            if e.element_type in DIODE_TYPES and info[e.id].state == "OFF"] if raw_order else [])
    order = raw_order if off else single_loop(
        report.equivalent.elements if report.equivalent is not None else None)
    if order is None:
        return None
    nv = {k: _value(v.value) for k, v in results.node_voltages.items()}
    ec = {k: _value(v.value) for k, v in results.element_currents.items()}
    resistors = [e for e, _, _ in order if e.element_type == ElementType.RESISTOR]
    s = _Sec("Çevre Denklemi (KVL)")

    def out_symbol(r: ParsedElement, v_r: float) -> Optional[str]:
        """Tek dirençli devrede direncin bir ucu GND'deyse çıkış gerilimi V_O = V_R."""
        if len(resistors) != 1 or "0" not in (r.node_positive, r.node_negative):
            return None
        top = r.node_negative if r.node_positive == "0" else r.node_positive
        if top in nv and abs(nv[top] - v_r) <= 1e-6 * max(abs(v_r), 1.0):
            return top
        return None

    if off:
        s.add("text", f"Devre tek bir seri çevreden oluşuyor ve {_and(off)} yalıtımda (açık devre): "
                      "çevre kesilir, akım akmaz.")
        s.add("math", "I = 0")
        for r in resistors:
            s.add("math", f"V_{r.id} = I·{r.id} = 0 · {eng(r.value, 'Ω')} = 0 V")
        if len(resistors) == 1:
            r = resistors[0]
            top = out_symbol(r, 0.0)
            if top is not None:
                s.add("result", f"V_O = V_{r.id} = 0 V")
        s.add("note", "Yorum: Seri bağlı diyotlardan biri bile yalıtımdaysa devreden akım geçmez; "
                      "dirençler üzerinde gerilim düşümü olmaz.")
        return s

    # Çevre akımının yönü: ilk direncin akımından (dolaşma yönü akımla aynı olsun)
    r0, a0, _ = next(x for x in order if x[0].element_type == ElementType.RESISTOR)
    if r0.id not in ec:
        return None
    i_trav = ec[r0.id] if a0 == r0.node_positive else -ec[r0.id]
    if i_trav < 0:
        order = [(e, b, a) for e, a, b in reversed(order)]
        i_trav = -i_trav
    current = i_trav

    sym_terms: List[Tuple[float, str]] = []
    num_terms: List[Tuple[float, str]] = []
    known = 0.0
    src_net = 0.0
    diode_drop = 0.0
    for e, a, b in order:
        if e.element_type == ElementType.RESISTOR:
            sym_terms.append((1, f"V_{e.id}"))
            continue
        if is_sub(e):
            d = info[e.id]
            drop = d.v_t if a == d.anode else -d.v_t
            sym_terms.append((1 if drop >= 0 else -1, f"V_{e.id}"))
            diode_drop += drop
        elif e.element_type == ElementType.DC_SOURCE:
            drop = e.value if a == e.node_positive else -e.value
            sym_terms.append((1 if drop >= 0 else -1, e.id))
            src_net -= drop
        else:
            return None
        known += drop
        num_terms.append((1 if drop >= 0 else -1, _plain(drop)))
    v_r_total = -known
    r_sum = sum(r.value for r in resistors)
    if abs(v_r_total - current * r_sum) > 1e-6 * max(abs(v_r_total), 1e-9) + 1e-9:
        return None         # türetme çözücüyle uyuşmuyor: gösterilmez

    s.add("text", "Eşdeğer devre tek bir çevreden oluşuyor (seri devre). Akım yönünde dolaşarak "
                  "Kirchhoff Gerilim Yasasını (KVL) yazalım: elemanlardaki gerilim düşümleri +, "
                  "kaynağın − ucundan + ucuna geçerken − işaretiyle yazılır.")
    diodes_in = [e.id for e, _, _ in order if is_sub(e)]
    if diodes_in:
        s.add("text", "İletimdeki diyotun gerilimi eşik gerilimidir: "
              + ", ".join(f"V_{i} = {_vt(info[i])}" for i in diodes_in) + ".")
    if len(resistors) == 1:
        r = resistors[0]
        top = out_symbol(r, v_r_total)
        sym = "V_O" if top is not None else f"V_{r.id}"
        if top is not None:
            s.add("text", f"Çıkış gerilimi V_O, {ek(r.id, 'in')} üzerindeki gerilimdir "
                          f"(V_O = V_{r.id} = {node_v(top)}).")
        sym_line = _join([(sg, sym if t == f"V_{r.id}" else t) for sg, t in sym_terms])
        s.add("math", f"KVL: {sym_line} = 0")
        s.add("math", f"{_join(num_terms + [(1, sym)])} = 0 ⇒ {sym} = {eng(v_r_total, 'V')}")
        s.add("math", f"I = {sym} / {r.id} = {eng(v_r_total, 'V')} / {eng(r.value, 'Ω')} = "
                      f"{eng(current, 'A')}")
        where = f"{r.id} üzerinde"
    else:
        s.add("math", f"KVL: {_join(sym_terms)} = 0")
        s.add("text", "Dirençlerdeki gerilimler V_R = I·R olduğundan:")
        r_names = " + ".join(r.id for r in resistors)
        s.add("math", f"{_join(num_terms)} + I·({r_names}) = 0 ⇒ I = {eng(v_r_total, 'V')} / "
                      f"{eng(r_sum, 'Ω')} = {eng(current, 'A')}")
        for r in resistors:
            s.add("math", f"V_{r.id} = I·{r.id} = {eng(current, 'A')} · {eng(r.value, 'Ω')} = "
                          f"{eng(current * r.value, 'V')}")
        where = "dirençler üzerinde"
    if diodes_in and abs(diode_drop) > 1e-15:
        s.add("note", f"Yorum: Kaynakların çevredeki net gerilimi {eng(src_net, 'V')}; bunun "
                      f"{_volts(diode_drop)}'u diyotlarda (eşik gerilimi) düşer, kalan "
                      f"{eng(v_r_total, 'V')} {where}dir.")
    elif diodes_in:
        s.add("note", f"Yorum: Diyotlar ideal olduğundan üzerlerinde gerilim düşmez; kaynakların "
                      f"net gerilimi ({eng(src_net, 'V')}) tamamen {where}dir.")
    return s


# ═══════════════════════════════════════════════════════
#  GİRİŞ (solver.diode çağırır)
# ═══════════════════════════════════════════════════════

def build_diode_sections(report, results) -> List[ExplanationSection]:
    out = [_state_section(report), _equivalent_section(report)]
    fb = _fallback_section(report)
    if fb is not None:
        out.append(fb)
    kvl = _kvl_section(report, results)
    if kvl is not None:
        out.append(kvl)
    return [s.build() for s in out if s.blocks]


# ═══════════════════════════════════════════════════════
#  narrative.py KANCALARI
# ═══════════════════════════════════════════════════════

def known_node_texts(elem: ParsedElement, node: str, other: str, value_text: str) -> Tuple[str, str]:
    """Bilinen düğüm bölümünde iletimdeki diyot: (açıklama, denklem)."""
    a, k = elem.node_positive, elem.node_negative
    text = (f"{elem.id} iletimde: yerine {_volt_ek(_volts(elem.params.get('v_t', elem.value)))} "
            f"kaynak konur (anot {node_name(a)}, katot {node_name(k)}):")
    sign = "+" if other == a else MINUS
    if node == "0":
        math = f"{node_v(other)} = {sign if sign == MINUS else ''}{sub_label(elem)} = {value_text}"
    else:
        math = f"{node_v(other)} = {node_v(node)} {sign} {sub_label(elem)} = {value_text}"
    return text, math


def current_lines(report, currents: Dict[str, complex]) -> List[str]:
    """Eleman akımları bölümü: her diyot (gruplar bir kez)."""
    lines = []
    done = set()
    for d in report.diodes:
        if d.rep in done:
            continue
        flow = f"anot → katot, {node_name(d.anode)} → {node_name(d.cathode)}"
        if d.state == "OFF":
            lines.append(f"I_{d.id} = 0 (yalıtımda, açık devre)")
            continue
        total = complex(currents.get(d.rep, 0)).real if not d.dropped else 0.0
        if abs(total) <= 1e-9:
            lines.append(f"I_{d.id} = 0 (doğru polarmada ama akım yolu kesik)")
            continue
        if len(d.group) > 1:
            done.add(d.rep)
            names = " = ".join(f"I_{x}" for x in d.group)
            lines.append(f"{names} = {eng(total, 'A')} / {len(d.group)} = "
                         f"{eng(total / len(d.group), 'A')} (iletimde; {flow})")
        else:
            lines.append(f"I_{d.id} = {eng(total, 'A')} (iletimde; {flow})")
    return lines


def power_lines(report, currents: Dict[str, complex]) -> List[Tuple[str, float]]:
    """Güç bölümü: iletimdeki diyot P = V_T·I çeker (yük)."""
    out = []
    for d in report.diodes:
        if d.state == "OFF":
            continue
        total = complex(currents.get(d.rep, 0)).real if not d.dropped else 0.0
        i = total / len(d.group) if d.group else total
        if abs(i) <= 1e-15:
            continue
        p = d.v_t * i
        if d.is_ideal:
            out.append((f"P_{d.id} = V_T·I = 0 (ideal diyot güç harcamaz)", 0.0))
            continue
        out.append((f"P_{d.id} = V_T·I = {_vt(d)} · {eng(i, 'A')} = {eng(p, 'W')} "
                    "(çekilen; diyot güç harcar)", p))
    return out


def kcl_label(report, eid: str) -> str:
    """KCL kontrolünde iletimdeki eşdeğer kaynağın adı (özdeş paralel grupta 'D1 ∥ D2')."""
    d = report.by_id().get(eid)
    if d is not None and len(d.group) > 1:
        return " ∥ ".join(d.group)
    return eid


def kcl_note(report) -> Optional[str]:
    off = [d.id for d in report.diodes if d.state == "OFF"]
    if not off:
        return None
    return (f"Yalıtımdaki {'diyot' if len(off) == 1 else 'diyotlar'} ({_and(off)}) açık devredir: "
            "akımı 0'dır, KCL'ye katkısı yoktur.")


def summary_lines(report, currents: Dict[str, complex]) -> List[str]:
    out = []
    for d in report.diodes:
        state = "iletimde" if d.state == "ON" else "yalıtımda"
        total = (complex(currents.get(d.rep, 0)).real
                 if d.state == "ON" and not d.dropped else 0.0)
        i = total / len(d.group) if d.group else total
        out.append(f"{d.id}: {state}, I_{d.id} = {eng(i, 'A') if abs(i) > 1e-15 else '0'}")
    for n in report.floating_nodes:
        out.append(f"{node_v(n)}: belirsiz ({node_name(n)} boşta)")
    return out
