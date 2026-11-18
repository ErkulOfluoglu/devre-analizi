"""
CircuitAnalyzer API — Millman teoremi anlatımı (yalnızca DC)

Devre, seri elemanlar tek kolda birleştirildikten sonra TAM İKİ ana düğüm
arasındaki paralel kollardan oluşuyorsa uygulanır. Her kol ya
    • dirençler (+ seri bağımsız DC gerilim kaynakları)  → (E_k, R_k), ya da
    • bir bağımsız akım kaynağı (seri dirençler/kaynaklar akımı değiştirmez)
olmalıdır.

    V_AB = (Σ E_k/R_k + Σ I_k) / (Σ 1/R_k)        I_k = (E_k − V_AB)/R_k

Her türetme çözücünün düğüm gerilimleri ve eleman akımlarıyla karşılaştırılır;
uygulanamayan ya da doğrulanamayan durumda sebebi söylenir (build_millman → (None, sebep))
ve narrative.py düğüm gerilimi anlatımına döner.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from explainer.formatting import MINUS, ek, eng, node_ek, node_name, node_v, num, paren, shown_digits
from parser.netlist_parser import ElementType, ParsedElement

_ALLOWED = (ElementType.RESISTOR, ElementType.DC_SOURCE, ElementType.CURRENT_DC)


@dataclass
class _Branch:
    index: int
    elements: List[ParsedElement]          # B → A yönünde sıralı
    path: List[Tuple[ParsedElement, str, str]] = field(default_factory=list)
    resistors: List[ParsedElement] = field(default_factory=list)
    volt_terms: List[Tuple[ParsedElement, int]] = field(default_factory=list)  # (kaynak, ±1)
    cur_source: Optional[ParsedElement] = None
    cur_sign: int = 1
    # (eleman, B→A yönünde gidilirken p ucundan mı girildi) — akım doğrulaması için
    entered_at_p: Dict[str, bool] = field(default_factory=dict)
    e: float = 0.0
    r: float = 0.0
    i_src: float = 0.0

    @property
    def is_current(self) -> bool:
        return self.cur_source is not None


def _is_single_loop(adj: Dict[str, List[ParsedElement]]) -> bool:
    """Her düğümde tam iki eleman ve toprak çevrenin üzerinde: devre tek bir çevre."""
    return "0" in adj and all(len(lst) == 2 for lst in adj.values())


def _single_loop_top(adj: Dict[str, List[ParsedElement]], n_elements: int) -> Optional[str]:
    """
    Tek çevrede A düğümü: B = 0'dan A'ya giden iki yolun (kolun) ikisinde de direnç ya da
    akım kaynağı bulunmalı (1/R tanımlı olsun). Uygun birden çok düğüm varsa en büyük numaralı.
    """
    seq: List[Tuple[ParsedElement, str]] = []      # (eleman, ulaşılan düğüm), 0'dan başlayarak
    prev, e = "0", adj["0"][0]
    for _ in range(n_elements + 1):
        nxt = e.node_negative if e.node_positive == prev else e.node_positive
        seq.append((e, nxt))
        if nxt == "0":
            break
        e = next(x for x in adj[nxt] if x is not e)
        prev = nxt
    else:
        return None

    def usable(elems: List[ParsedElement]) -> bool:
        return any(x.element_type != ElementType.DC_SOURCE for x in elems)

    tops = [node for i, (_, node) in enumerate(seq[:-1])
            if usable([x for x, _ in seq[:i + 1]]) and usable([x for x, _ in seq[i + 1:]])]
    return max(tops, key=lambda n: (len(n), n)) if tops else None


def _walk_branches(ctx) -> Tuple[Optional[Tuple[str, str, List[_Branch]]], str]:
    """(A, B, kollar) ya da (None, sebep)."""
    adj: Dict[str, List[ParsedElement]] = {}
    for e in ctx.elements:
        if e.node_positive == e.node_negative:
            return None, f"{e.id} elemanının iki ucu aynı düğüme bağlı."
        adj.setdefault(e.node_positive, []).append(e)
        adj.setdefault(e.node_negative, []).append(e)

    essential = [n for n, lst in adj.items() if len(lst) >= 3]
    dangling = [n for n, lst in adj.items() if len(lst) == 1]
    if dangling:
        return None, (f"{node_ek(dangling[0], 'de')} bir eleman açıkta kalıyor (akım taşımaz); "
                      "Millman formülü kapalı paralel kollar ister.")
    if not essential and _is_single_loop(adj):
        # Tek çevre (ör. paralel bağlı iki akü): bir düğüm A seçilip devre B = 0 ile
        # A arasında iki paralel kol olarak ele alınır.
        top = _single_loop_top(adj, len(ctx.elements))
        if top is None:
            return None, ("Devre tek bir çevreden oluşuyor ama hiçbir düğüm onu, iki kolunda da "
                          "direnç (ya da akım kaynağı) kalacak şekilde ikiye ayırmıyor; Millman "
                          "formülü uygulanamaz.")
        essential = ["0", top]
    if len(essential) != 2:
        return None, (f"Seri elemanları birleştirdikten sonra {len(essential)} ana düğüm "
                      "(üç veya daha fazla elemanın birleştiği düğüm) kalıyor; Millman teoremi "
                      "tam olarak iki ana düğüm arasındaki paralel kollar için kullanılır.")
    key = lambda n: (len(n), n)
    if "0" in essential:
        b = "0"
        a = next(n for n in essential if n != "0")
    else:
        a, b = sorted(essential, key=key)

    branches: List[_Branch] = []
    for first in adj[b]:
        path = []
        prev, e = b, first
        for _ in range(len(ctx.elements) + 1):
            nxt = e.node_negative if e.node_positive == prev else e.node_positive
            path.append((e, prev, nxt))
            if nxt in essential:
                break
            others = [x for x in adj[nxt] if x is not e]
            if len(others) != 1:
                return None, "Bir kol içinde beklenmeyen bir dallanma var."
            prev, e = nxt, others[0]
        else:
            return None, "Kollar izlenirken döngüye girildi."
        if path[-1][2] != a:
            return None, "Bir kol aynı ana düğüme geri dönüyor; paralel kol yapısı değil."
        br = _Branch(index=len(branches) + 1, elements=[p[0] for p in path], path=list(path))
        for el, frm, to in path:
            br.entered_at_p[el.id] = (frm == el.node_positive)
            if el.element_type == ElementType.RESISTOR:
                br.resistors.append(el)
                br.r += el.value
            elif el.element_type == ElementType.DC_SOURCE:
                # + uca doğru geçiliyorsa (− uçtan girip + uçtan çıkıyorsak) kol gerilimi A tarafını yükseltir
                sign = 1 if (frm == el.node_negative and to == el.node_positive) else -1
                br.volt_terms.append((el, sign))
                br.e += sign * el.value
            else:
                if br.cur_source is not None:
                    return None, f"Kol {br.index} içinde iki akım kaynağı seri bağlı."
                br.cur_source = el
                br.cur_sign = 1 if frm == el.node_positive else -1
                br.i_src = br.cur_sign * el.value
        branches.append(br)
    return (a, b, branches), ""


def _check(ctx, a: str, b: str, branches: List[_Branch]) -> str:
    """Millman sonucunu çözücüyle karşılaştır. Sorun varsa sebebi, yoksa ''."""
    from explainer.narrative import _close
    for br in branches:
        if not br.is_current:
            if br.r <= 0:
                return (f"Kol {br.index} yalnızca gerilim kaynağından oluşuyor (direnci yok); "
                        "bu kolun R değeri 0 olduğundan 1/R tanımsızdır.")
    g = sum(1 / br.r for br in branches if not br.is_current)
    if g <= 0:
        return "Tüm kollar akım kaynağı; paralel dirençsiz bu devrede V_AB Millman formülüyle bulunamaz."
    v_ab = (sum(br.e / br.r for br in branches if not br.is_current)
            + sum(br.i_src for br in branches if br.is_current)) / g
    solved = ctx.node_value(a) - ctx.node_value(b)
    if not _close(v_ab, solved, 1e-4):
        return "Millman formülüyle bulunan gerilim çözücünün sonucuyla uyuşmadı."
    for br in branches:
        i_k = br.i_src if br.is_current else (br.e - v_ab) / br.r
        for r in br.resistors:
            if r.id not in ctx.i:
                continue
            expect = i_k if br.entered_at_p[r.id] else -i_k
            if not _close(expect, complex(ctx.i[r.id]), 1e-4):
                return f"{r.id} akımı çözücünün sonucuyla uyuşmadı."
    return ""


def build_millman(ctx) -> Tuple[Optional[list], str]:
    """(bölümler, '') ya da (None, uygulanamama sebebi)."""
    from explainer.narrative import _Section

    if not ctx.is_dc:
        return None, "Millman teoremi bu programda yalnızca DC devreler için anlatılıyor."
    if ctx.has_dependent:
        return None, ("Devrede bağımlı (kontrollü) kaynak var; Millman formülü yalnızca "
                      "bağımsız kaynaklı paralel kollar için geçerlidir.")
    for e in ctx.elements:
        if e.element_type not in _ALLOWED:
            return None, (f"{e.id} elemanı direnç ya da bağımsız DC kaynak değil; Millman "
                          "formülü bu elemanlarla yazılır.")
    walked, reason = _walk_branches(ctx)
    if walked is None:
        return None, reason
    a, b, branches = walked
    reason = _check(ctx, a, b, branches)
    if reason:
        return None, reason

    g = sum(1 / br.r for br in branches if not br.is_current)
    v_ab = (sum(br.e / br.r for br in branches if not br.is_current)
            + sum(br.i_src for br in branches if br.is_current)) / g
    ki = lambda br: str(br.index).translate(str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉"))
    b_txt = "GND (referans)" if b == "0" else f"Düğüm {b} (referans olarak alıyoruz)"

    # ── 1. Kolları çıkaralım ──
    s1 = _Section("Millman Teoremi — Kolları Belirleyelim")
    adj: Dict[str, List[ParsedElement]] = {}
    for e in ctx.elements:
        adj.setdefault(e.node_positive, []).append(e)
        adj.setdefault(e.node_negative, []).append(e)
    merge = ("Bir koldaki seri elemanlar tek elemanmış gibi birleştirilir: seri dirençler toplanır, "
             "seri gerilim kaynakları işaretlerine göre toplanır.")
    sign_rule = ("Bir koldaki gerilim kaynağının + ucu A düğümüne bakıyorsa E pozitif, B düğümüne "
                 "bakıyorsa negatif yazılır.")
    if _is_single_loop(adj):
        s1.text("Devre tek bir çevreden oluşuyor: üç ya da daha fazla elemanın birleştiği bir ana "
                f"düğüm yok. Çevre üzerinde iki düğüm seçip (A = {node_name(a)}, B = {b_txt}) bu iki "
                "düğüm arasındaki iki yolu, paralel bağlı iki kol gibi ele alacağız. " + merge)
        s1.text(f"A düğümü, iki kolda da direnç (ya da akım kaynağı) kalacak şekilde seçildi; "
                f"aksi hâlde o kolun 1/R değeri tanımsız olurdu. {sign_rule}")
    else:
        s1.text(f"Devre, iki ana düğüm arasına paralel bağlı {len(branches)} koldan oluşuyor. "
                + merge)
        s1.text(f"Ana düğümler: A = {node_name(a)}, B = {b_txt}. {sign_rule}")
    for br in branches:
        names = ", ".join(e.id for e in br.elements)
        if br.is_current:
            src = br.cur_source
            sgn = "+" if br.cur_sign > 0 else MINUS
            s1.math(f"Kol {br.index} ({names}): akım kaynağı kolu, I{ki(br)} = {sgn}{src.id} = "
                    f"{eng(br.i_src, 'A')}  (B → A yönünde)")
            others = [e.id for e in br.elements if e is not src]
            if others:
                s1.note(f"Akım kaynağıyla seri bağlı {', '.join(others)} kolun akımını değiştirmez "
                        "(akımı kaynak belirler); yalnızca uçlarındaki gerilimi etkiler. Bu yüzden "
                        f"Kol {br.index} formülde yalnızca I{ki(br)} ile yer alır.")
            continue
        # E_k
        if not br.volt_terms:
            e_txt = f"E{ki(br)} = 0  (kolda gerilim kaynağı yok)"
        else:
            sym = (MINUS if br.volt_terms[0][1] < 0 else "") + br.volt_terms[0][0].id
            for el, s in br.volt_terms[1:]:
                sym += f" {MINUS if s < 0 else '+'} {el.id}"
            if len(br.volt_terms) == 1:
                e_txt = f"E{ki(br)} = {sym} = {eng(br.e, 'V')}"
            else:
                vals = f"{eng(br.volt_terms[0][0].value * br.volt_terms[0][1], 'V')}"
                for el, s in br.volt_terms[1:]:
                    vals += f" {MINUS if s < 0 else '+'} {eng(el.value, 'V')}"
                e_txt = f"E{ki(br)} = {sym} = {vals} = {eng(br.e, 'V')}"
        if len(br.resistors) == 1:
            r_txt = f"R{ki(br)} = {br.resistors[0].id} = {eng(br.r, 'Ω')}"
        else:
            r_txt = (f"R{ki(br)} = {' + '.join(r.id for r in br.resistors)} = "
                     f"{' + '.join(eng(r.value, 'Ω') for r in br.resistors)} = {eng(br.r, 'Ω')}")
        s1.math(f"Kol {br.index} ({names}): {e_txt};  {r_txt}")

    # ── 2. Millman formülü ──
    s2 = _Section("Millman Formülü — V_AB")
    s2.text("Her kolun A düğümüne giren akımı I = (E − V_AB)/R'dir. A düğümünde bu akımların toplamı "
            "sıfır olduğundan (KCL) V_AB için tek bir formül çıkar; kollar paralel olduğu için "
            "denklemi çözmeye gerek kalmaz:")
    sym_num, sym_den, val_num, val_den = [], [], [], []
    for br in branches:
        if br.is_current:
            sym_num.append(f"I{ki(br)}")
            val_num.append(paren(num(br.i_src)))
        else:
            sym_num.append(f"E{ki(br)}/R{ki(br)}")
            sym_den.append(f"1/R{ki(br)}")
            val_num.append(f"{paren(num(br.e))}/{num(br.r)}")
            val_den.append(f"1/{num(br.r)}")
    s2.math(f"V_AB = ({' + '.join(sym_num)}) / ({' + '.join(sym_den)})")
    s2.math(f"V_AB = ({' + '.join(val_num)}) / ({' + '.join(val_den)})")
    numerator = v_ab * g
    s2.math(f"V_AB = {eng(numerator, 'A')} / {eng(g, 'S')}")
    ref = f"{node_v(a)} {MINUS} {node_v(b)}"
    s2.result(f"V_AB = {ref} = {eng(v_ab, 'V')}")
    if b == "0":
        s2.text(f"B düğümü referans (V₀ = 0) olduğu için {node_v(a)} = {eng(v_ab, 'V')}.")

    # ── 3. Kol akımları ──
    s3 = _Section("Kol Akımları")
    s3.text("Her kolun akımı, kolun uçlarına düşen gerilimin direnç toplamına bölümüdür. Akım, kolun "
            "içinde B → A yönünde (kaynağın − ucundan + ucuna) pozitif alınır:")
    currents = []
    for br in branches:
        if br.is_current:
            i_k = br.i_src
            s3.math(f"I{ki(br)} = {br.cur_source.id} akım kaynağının akımı = {eng(i_k, 'A')}")
        else:
            i_k = (br.e - v_ab) / br.r
            s3.math(f"I{ki(br)} = (E{ki(br)} {MINUS} V_AB) / R{ki(br)} = "
                    f"({eng(br.e, 'V')} {MINUS} {paren(eng(v_ab, 'V'))}) / {eng(br.r, 'Ω')} = {eng(i_k, 'A')}")
        currents.append(i_k)
    if any(i < -1e-12 for i in currents):
        s3.note("Eksi çıkan akım, gerçekte A → B yönünde akar.")
    total = sum(currents)
    scale = max((abs(i) for i in currents), default=0.0)
    terms = " + ".join(paren(eng(i, 'A')) for i in currents)
    if abs(total) <= 1e-9 * max(scale, 1e-12):
        s3.check(f"KCL, A düğümü: I toplamı = {terms} = 0 ✓")

    sections = [s1, s2, s3]
    s4 = _inner_node_section(ctx, a, b, branches, currents)
    if s4 is not None:
        sections.append(s4)
    return sections, ""


def _inner_node_section(ctx, a: str, b: str, branches: List[_Branch], currents: List[float]):
    """Kolların içindeki ara düğüm gerilimlerini ana düğüm gerilimi ve kol akımından türetir."""
    from explainer.narrative import EXTRA_DIGITS_NOTE, _Section, _close

    ki = lambda br: str(br.index).translate(str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉"))
    lines = []
    results_lines = []
    extra_digits = False

    def derive_segment(br: _Branch, i_k: float, seg: List[Tuple[ParsedElement, str, str]],
                       start_node: str, dir_sign: int) -> None:
        nonlocal extra_digits
        v_cur = ctx.node_value(start_node).real
        cur_node = start_node
        for el, frm, to in seg[:-1]:
            if to in ("0", a, b):
                cur_node = to
                v_cur = ctx.node_value(to).real
                continue
            target = ctx.node_value(to).real
            if el.element_type == ElementType.DC_SOURCE:
                s_v = 1 if (frm == el.node_negative and to == el.node_positive) else -1
                v_next = v_cur + s_v * el.value
                if not _close(v_next, target, 1e-4):
                    return
                if cur_node == "0":
                    lines.append(f"{node_v(to)} = {'' if s_v > 0 else MINUS}{el.id} = {eng(v_next, 'V')}")
                else:
                    op = "+" if s_v > 0 else MINUS
                    d = shown_digits([v_cur, el.value], lambda xs: xs[0] + s_v * xs[1], v_next)
                    extra_digits = extra_digits or d > 4
                    lines.append(f"{node_v(to)} = {node_v(cur_node)} {op} {el.id} = "
                                 f"{eng(v_cur, 'V', d)} {op} {eng(el.value, 'V', d)} = {eng(v_next, 'V')}")
            elif el.element_type == ElementType.RESISTOR:
                i_flow = dir_sign * i_k
                v_next = v_cur - i_flow * el.value
                if not _close(v_next, target, 1e-4):
                    return
                if cur_node == "0":
                    d = shown_digits([abs(i_k)], lambda xs: xs[0] * el.value, abs(v_next))
                    extra_digits = extra_digits or d > 4
                    i_sym = f"{MINUS}I{ki(br)}" if dir_sign > 0 else f"I{ki(br)}"
                    # Kol akımını işaretiyle yerine koy: −I₃ = −(−2,182 mA) adımı görünsün
                    i_val = paren(eng(i_k, 'A', d))
                    i_txt = f"{MINUS}{i_val}" if dir_sign > 0 and abs(i_k) > 1e-15 else i_val
                    lines.append(f"{node_v(to)} = {i_sym} · {el.id} = "
                                 f"{i_txt} · {eng(el.value, 'Ω')} = {eng(v_next, 'V')}")
                else:
                    d = shown_digits([v_cur, i_k], lambda xs: xs[0] - dir_sign * xs[1] * el.value, v_next)
                    extra_digits = extra_digits or d > 4
                    op = MINUS if dir_sign > 0 else "+"
                    lines.append(f"{node_v(to)} = {node_v(cur_node)} {op} I{ki(br)} · {el.id} = "
                                 f"{eng(v_cur, 'V', d)} {op} {paren(eng(i_k, 'A', d))} · {eng(el.value, 'Ω')} = "
                                 f"{eng(v_next, 'V')}")
            else:
                return
            if to != "0":
                results_lines.append((to, f"{node_v(to)} = {eng(v_next, 'V')}"))
            cur_node = to
            v_cur = v_next

    for br, i_k in zip(branches, currents):
        if len(br.path) < 2:
            continue
        if not br.is_current:
            derive_segment(br, i_k, br.path, b, +1)
        else:
            cs_idx = next(idx for idx, (el, _, _) in enumerate(br.path) if el is br.cur_source)
            if cs_idx >= 1:
                derive_segment(br, i_k, br.path[:cs_idx + 1], b, +1)
            if cs_idx < len(br.path) - 1:
                rev = [(el, to, frm) for el, frm, to in reversed(br.path[cs_idx:])]
                derive_segment(br, i_k, rev, a, -1)

    if not lines:
        return None
    s4 = _Section("Ara Düğüm Gerilimleri")
    s4.text("Kolların içindeki ara düğümlerin gerilimleri, ana düğüm gerilimi ve kol akımından "
            "(dirençlerdeki gerilim düşümü ya da seri kaynak gerilimi eklenerek) bulunur:")
    for ln in lines:
        s4.math(ln)
    if extra_digits:
        s4.note(EXTRA_DIGITS_NOTE)
    for _, rln in sorted(results_lines, key=lambda kv: (len(kv[0]), kv[0])):
        s4.result(rln)
    return s4
