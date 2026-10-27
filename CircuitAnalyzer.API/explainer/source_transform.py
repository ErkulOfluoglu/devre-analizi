"""
CircuitAnalyzer API — Kaynak dönüşümü anlatımı (yalnızca DC)

Öğrencinin seçtiği iki terminalden (A +, B −) bakıldığında Thevenin/Norton eşdeğerine,
ders kitabındaki dönüşümlerle adım adım ulaşılır:

    (a) gerilim kaynağı E + seri R   →  akım kaynağı I = E/R + paralel R
    (b) paralel dirençler birleşir; paralel akım kaynakları toplanır (yönlere dikkat)
    (c) akım kaynağı I + paralel R   →  gerilim kaynağı E = I·R + seri R
    (d) seri dirençler toplanır; seri gerilim kaynakları toplanır (kutuplara dikkat)
    (e) akım kaynağına seri bağlı eleman akımı değiştirmez → çıkarılır
        (boşta kalan ya da iki ucu aynı düğümde olan eleman da akım taşımaz)

Terminaller arasında "tek gerilim kaynağı + seri direnç" (ya da "akım kaynağı + paralel
direnç") kalınca durulur. Bulunan Vth/Rth çözücünün Thevenin sonucuyla karşılaştırılır;
uygulanamayan (köprü, bağımlı kaynak, AC, tıkanma) ya da doğrulanamayan durumda
build_source_transform → (None, sebep) döner ve narrative.py Thevenin anlatımına döner.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from explainer.formatting import MINUS, eng, node_v, num
from parser.netlist_parser import ElementType

_ALLOWED = (ElementType.RESISTOR, ElementType.DC_SOURCE, ElementType.CURRENT_DC)
_MAX_ITER = 80
_LETTERS = "abcdefghijklmnopqrstuvwxyz"
_STUCK = ("Bu devre, seri/paralel birleştirme ve kaynak dönüşümleriyle terminallere kadar "
          "sadeleştirilemiyor (örneğin köprü yapısı ya da gerilim kaynağının doğrudan paralel "
          "bağlandığı bir düğüm var).")


class _Fail(Exception):
    pass


@dataclass
class _El:
    kind: str       # 'R', 'V', 'I'
    name: str
    p: str          # V: + uç; I: akımın kaynak içinde çıktığı uç; R: serbest
    n: str          # V: − uç; I: akımın kaynak içinde gittiği (devreye verdiği) uç
    val: float      # R > 0; V, I ≥ 0 (türetilenler normalize) ya da netlistteki işaretli değer


def _key(node: str):
    return (len(node), node)


def _emf_toward(v: _El, node: str) -> float:
    """V kaynağının, `node` ucunu diğer uca göre yükselttiği gerilim (işaretli)."""
    return v.val if v.p == node else -v.val


def _inj_toward(i: _El, node: str) -> float:
    """I kaynağının `node` düğümüne verdiği akım (işaretli)."""
    return i.val if i.n == node else -i.val


def _mk_v(name: str, toward: str, other: str, emf: float) -> _El:
    """`toward` ucunu `other` ucuna göre emf kadar yükselten kaynak (emf < 0 ise ters)."""
    return _El("V", name, toward, other, emf) if emf >= 0 else _El("V", name, other, toward, -emf)


def _mk_i(name: str, toward: str, other: str, amount: float) -> _El:
    """Devreye `toward` düğümünden `amount` akım veren kaynak (amount < 0 ise ters)."""
    return _El("I", name, other, toward, amount) if amount >= 0 else _El("I", name, toward, other, -amount)


def _signed_sum(names: List[str], values: List[float], signs: List[int], unit: str) -> Tuple[str, str]:
    """('V1 − V2', '6 V − 3 V'): ilk terim her zaman pozitif yazılır (signs[0] > 0 olmalı)."""
    sym, val = names[0], eng(values[0], unit)
    for nm, v, s in zip(names[1:], values[1:], signs[1:]):
        op = "+" if s > 0 else MINUS
        sym += f" {op} {nm}"
        val += f" {op} {eng(v, unit)}"
    return sym, val


class _Net:
    def __init__(self, els: List[_El], a: str, b: str):
        self.els = els
        self.a, self.b = a, b
        self.count = {"R": 0, "V": 0, "I": 0, "node": 0}
        self.steps: List[List[Tuple[str, str]]] = []   # her adım: [(tür, metin), …]
        self.cur: List[Tuple[str, str]] = []
        self.used_new_node = False

    def new_name(self, kind: str) -> str:
        i = self.count[kind]
        self.count[kind] += 1
        suffix = _LETTERS[i] if i < len(_LETTERS) else str(i + 1)
        return {"R": "R", "V": "E", "I": "I"}[kind] + suffix

    def new_node(self) -> str:
        self.count["node"] += 1
        self.used_new_node = True
        return f"x{self.count['node']}"

    def incidence(self) -> Dict[str, List[_El]]:
        inc: Dict[str, List[_El]] = {}
        for e in self.els:
            inc.setdefault(e.p, []).append(e)
            if e.n != e.p:
                inc.setdefault(e.n, []).append(e)
        return inc

    def signature(self):
        return frozenset(
            (e.kind, tuple(sorted((e.p, e.n))) if e.kind == "R" else (e.p, e.n), round(e.val, 9))
            for e in self.els)

    def remove(self, *items: _El):
        for it in items:
            self.els = [e for e in self.els if e is not it]

    def text(self, t: str):
        self.cur.append(("text", t))

    def math(self, t: str):
        self.cur.append(("math", t))

    def recap(self):
        def one(e: _El) -> str:
            if e.kind == "R":
                return f"{e.name} ({e.p}–{e.n})"
            if e.kind == "V":
                return f"{e.name} (+ {e.p}, − {e.n})".replace("−", MINUS)
            return f"{e.name} ({e.p} → {e.n})"
        self.cur.append(("note", "Devrenin şimdiki hali: " + ", ".join(one(e) for e in self.els) + "."))
        self.steps.append(self.cur)      # adım tamam
        self.cur = []


def _trace(inc, net: _Net, start: str, via: _El):
    """`start`tan `via` elemanı üzerinden iç düğümler bitene kadar yürür: [(eleman, nereden, nereye)]."""
    path = []
    prev, e = start, via
    for _ in range(len(net.els) + 1):
        nxt = e.n if e.p == prev else e.p
        path.append((e, prev, nxt))
        if nxt in (net.a, net.b) or len(inc.get(nxt, [])) != 2:
            return path
        others = [x for x in inc[nxt] if x is not e]
        if len(others) != 1:
            return path
        prev, e = nxt, others[0]
    return None


def _chains(net: _Net) -> List[list]:
    """Seri kollar: iç düğümlerle (terminal olmayan, tam 2 elemanlı) bağlı eleman dizileri."""
    inc = net.incidence()
    internal = sorted((m for m in inc if m not in (net.a, net.b) and len(inc[m]) == 2), key=_key)
    seen = set()
    out = []
    for m in internal:
        if m in seen:
            continue
        e1, e2 = inc[m]
        if e1 is e2:
            continue
        left, right = _trace(inc, net, m, e1), _trace(inc, net, m, e2)
        if left is None or right is None:
            continue
        path = [(e, t, f) for e, f, t in reversed(left)] + right
        for (_, f, t) in path:
            seen.add(f)
            seen.add(t)
        if path[0][1] == path[-1][2]:
            continue
        out.append(path)
    return out


# ═══════════════════════════════════════════════════════
#  ADIMLAR — her biri bir değişiklik yapıp True döner
# ═══════════════════════════════════════════════════════

def _step_cleanup(net: _Net) -> bool:
    for e in net.els:
        if e.p == e.n:
            if e.kind == "V":
                raise _Fail(f"{e.name} gerilim kaynağının iki ucu aynı düğüme bağlı.")
            net.remove(e)
            net.text(f"{e.name} elemanının iki ucu aynı düğüme bağlı; uçları arasında gerilim olmadığı "
                     "için akım taşımaz, devreden çıkarılır.")
            net.recap()
            return True
    inc = net.incidence()
    for node in sorted(inc, key=_key):
        if node in (net.a, net.b) or len(inc[node]) != 1:
            continue
        e = inc[node][0]
        if e.kind == "I":
            raise _Fail(f"{e.name} akım kaynağının bir ucu açıkta (Düğüm {node}).")
        net.remove(e)
        net.text(f"Düğüm {node}'ye yalnızca {e.name} bağlı; bir ucu boşta kalan eleman akım taşımaz, "
                 "devreden çıkarılır.")
        net.recap()
        return True
    return False


def _step_chain(net: _Net) -> bool:
    """(d) ve (e): seri kolları sadeleştir."""
    for path in _chains(net):
        elems = [p[0] for p in path]
        n0, nk = path[0][1], path[-1][2]
        sources_i = [e for e in elems if e.kind == "I"]
        if len(sources_i) > 1:
            raise _Fail("Aynı kolda seri bağlı iki akım kaynağı var.")
        if sources_i:
            src = sources_i[0]
            frm = next(f for e, f, _t in path if e is src)
            new = _El("I", src.name, n0, nk, src.val) if frm == src.p else _El("I", src.name, nk, n0, src.val)
            others = [e.name for e in elems if e is not src]
            net.remove(*elems)
            net.els.append(new)
            net.text(f"{src.name} akım kaynağına seri bağlı {', '.join(others)} kolun akımını değiştirmez "
                     "(akımı akım kaynağı belirler); bu elemanlar çıkarılır, kolda yalnızca "
                     f"{src.name} kalır.")
            net.recap()
            return True
        res = [e for e in elems if e.kind == "R"]
        vol = [(e, f, t) for e, f, t in path if e.kind == "V"]
        if len(res) < 2 and len(vol) < 2:
            continue

        r_new_name = net.new_name("R") if len(res) >= 2 else (res[0].name if res else "")
        r_tot = sum(e.val for e in res)
        if len(res) >= 2:
            names = [e.name for e in res]
            net.text(f"{' ve '.join(names) if len(names) == 2 else ', '.join(names)} dirençleri seri "
                     "bağlı; seri dirençler toplanır.")
            net.math(f"{r_new_name} = {' + '.join(names)} = "
                     f"{' + '.join(eng(e.val, 'Ω') for e in res)} = {eng(r_tot, 'Ω')}")

        terms = [(e, 1 if (f == e.n and t == e.p) else -1) for e, f, t in vol]   # nk yönünde +
        e_signed = sum(s * e.val for e, s in terms)
        v_name = vol[0][0].name if vol else ""
        if len(vol) >= 2:
            v_name = net.new_name("V")
            sigma = terms[0][1]
            sym, val = _signed_sum([e.name for e, _ in terms], [e.val for e, _ in terms],
                                   [s * sigma for _, s in terms], "V")
            total = sigma * e_signed
            clause = ""
            if total < 0:
                clause = (f" Eksi çıktığı için {v_name} kaynağının + ucu ilk kaynağın tersi yöndedir "
                          "(kutuplar zıt olduğundan fark alındı).")
            net.text(f"{' ve '.join(e.name for e, _ in terms) if len(terms) == 2 else ', '.join(e.name for e, _ in terms)} "
                     "gerilim kaynakları seri bağlı; aynı yönlü (+ ucu aynı tarafa bakan) kaynaklar "
                     f"toplanır, zıt yönlüler birbirinden çıkarılır.{clause}")
            net.math(f"{v_name} = {sym} = {val} = {eng(total, 'V')}")

        net.remove(*elems)
        if vol and abs(e_signed) > 1e-15 and res:
            kn = net.new_node()
            net.els.append(_El("R", r_new_name, n0, kn, r_tot))
            net.els.append(_mk_v(v_name, nk, kn, e_signed))
        elif vol and abs(e_signed) > 1e-15:
            net.els.append(_mk_v(v_name, nk, n0, e_signed))
        elif res:
            net.els.append(_El("R", r_new_name, n0, nk, r_tot))
        else:
            net.text("Seri kaynakların toplamı sıfır olduğu için kol kısa devre olur.")
            raise _Fail("Seri gerilim kaynakları birbirini götürüyor (kol kısa devre).")
        net.recap()
        return True
    return False


def _step_parallel(net: _Net) -> bool:
    """(b): aynı iki düğüm arasındaki paralel dirençler / akım kaynakları."""
    groups: Dict[tuple, List[_El]] = {}
    for e in net.els:
        if e.kind in ("R", "I"):
            groups.setdefault((e.kind, tuple(sorted((e.p, e.n), key=_key))), []).append(e)
    for key in sorted(groups, key=lambda k: (k[0] != "R", [_key(x) for x in k[1]])):
        grp = groups[key]
        if len(grp) < 2:
            continue
        kind, (u, w) = key
        names = [e.name for e in grp]
        listing = f"{' ve '.join(names)}" if len(names) == 2 else ", ".join(names)
        if kind == "R":
            new_name = net.new_name("R")
            r_eq = 1 / sum(1 / e.val for e in grp)
            net.remove(*grp)
            net.els.append(_El("R", new_name, u, w, r_eq))
            net.text(f"{listing} dirençleri Düğüm {u} ile Düğüm {w} arasında paralel bağlı; "
                     "paralel dirençler tek dirençle gösterilir.")
            if len(grp) == 2:
                net.math(f"{new_name} = {names[0]}·{names[1]} / ({names[0]} + {names[1]}) = "
                         f"{num(grp[0].val)}·{num(grp[1].val)} / ({num(grp[0].val)} + {num(grp[1].val)}) "
                         f"= {eng(r_eq, 'Ω')}")
            else:
                net.math(f"{new_name} = 1 / ({' + '.join('1/' + n for n in names)}) = "
                         f"1 / ({' + '.join('1/' + num(e.val) for e in grp)}) = {eng(r_eq, 'Ω')}")
        else:
            new_name = net.new_name("I")
            ref = grp[0]
            toward, other = ref.n, ref.p
            signs = [1 if e.n == toward else -1 for e in grp]
            total = sum(s * e.val for s, e in zip(signs, grp))
            sym, val = _signed_sum(names, [e.val for e in grp], signs, "A")
            net.remove(*grp)
            net.text(f"{listing} akım kaynakları Düğüm {u} ile Düğüm {w} arasında paralel bağlı; "
                     f"akımlar {ref.name} yönünde (Düğüm {other} → Düğüm {toward}) alınarak toplanır, "
                     "ters yöne bakan kaynağın akımı çıkarılır.")
            if abs(total) > 1e-15:
                new = _mk_i(new_name, toward, other, total)
                net.els.append(new)
                net.math(f"{new_name} = {sym} = {val} = {eng(total, 'A')}")
                net.text(f"{new_name} kaynağı içinde Düğüm {new.p} → Düğüm {new.n} yönündedir"
                         + (" (sonuç eksi çıktığı için yön ters döndü)." if total < 0 else "."))
            else:
                net.math(f"{new_name} = {sym} = {val} = 0")
                net.text("Akımlar birbirini götürdü; bu iki düğüm arasında kaynak akımı kalmadı.")
        net.recap()
        return True
    return False


def _step_vr(net: _Net) -> bool:
    """(a): gerilim kaynağı + seri direnç → akım kaynağı + paralel direnç."""
    for path in _chains(net):
        if len(path) != 2:
            continue
        kinds = sorted(p[0].kind for p in path)
        if kinds != ["R", "V"]:
            continue
        (e1, f1, m), (e2, _f2, t2) = path
        n0 = f1
        v, r = (e1, e2) if e1.kind == "V" else (e2, e1)
        x = n0 if e1.kind == "V" else t2           # gerilim kaynağının dış ucu
        y = t2 if e1.kind == "V" else n0           # direncin dış ucu
        emf_m = _emf_toward(v, m)                  # m ucunu x'e göre yükselten gerilim
        i_name = net.new_name("I")
        amount = emf_m / r.val                     # y düğümüne verilen akım
        new = _mk_i(i_name, y, x, amount)
        net.remove(v, r)
        net.els.append(new)
        net.els.append(_El("R", r.name, x, y, r.val))
        net.text(f"{v.name} gerilim kaynağı ile {r.name} direnci seri bağlı (Düğüm {m}'de başka eleman yok). "
                 f"Kaynak dönüşümü: {v.name}, {r.name} direncine paralel bir akım kaynağına dönüşür; "
                 f"akım okunun yönü, {v.name} kaynağının + ucu tarafına bakar.")
        net.math(f"{i_name} = {v.name} / {r.name} = {eng(abs(emf_m), 'V')} / {eng(r.val, 'Ω')} = "
                 f"{eng(abs(amount), 'A')}  (kaynak içinde Düğüm {new.p} → Düğüm {new.n} yönünde)")
        net.recap()
        return True
    return False


def _step_ir(net: _Net) -> bool:
    """(c): akım kaynağı + paralel direnç → gerilim kaynağı + seri direnç."""
    inc = net.incidence()
    pairs: Dict[tuple, List[_El]] = {}
    for e in net.els:
        pairs.setdefault(tuple(sorted((e.p, e.n), key=_key)), []).append(e)
    for pair in sorted(pairs, key=lambda k: [_key(x) for x in k]):
        grp = pairs[pair]
        if sorted(e.kind for e in grp) != ["I", "R"]:
            continue
        src = next(e for e in grp if e.kind == "I")
        res = next(e for e in grp if e.kind == "R")
        x = next((nd for nd in pair if nd not in (net.a, net.b) and len(inc[nd]) == 3), None)
        if x is None:
            continue
        z = pair[0] if pair[1] == x else pair[1]
        e_name = net.new_name("V")
        emf_z = _inj_toward(src, z) * res.val        # z ucunu x'e göre yükselten gerilim
        kn = net.new_node()
        net.remove(src, res)
        net.els.append(_El("R", res.name, x, kn, res.val))
        new_v = _mk_v(e_name, z, kn, emf_z)
        net.els.append(new_v)
        net.text(f"{src.name} akım kaynağı ile {res.name} direnci paralel bağlı. Kaynak dönüşümü: "
                 f"{src.name}, {res.name} direncine seri bir gerilim kaynağına dönüşür; gerilim "
                 f"kaynağının + ucu, akım okunun gösterdiği Düğüm {z if emf_z >= 0 else x} tarafındadır.")
        net.math(f"{e_name} = {src.name}·{res.name} = {eng(src.val, 'A')} · {eng(res.val, 'Ω')} = "
                 f"{eng(src.val * res.val, 'V')}")
        net.recap()
        return True
    return False


# ═══════════════════════════════════════════════════════
#  SON DURUM
# ═══════════════════════════════════════════════════════

@dataclass
class _Final:
    form: str          # 'R', 'VR', 'IR'
    e_th: float        # V_AB
    r_th: float
    elems: List[_El]


def _final(net: _Net) -> Optional[_Final]:
    a, b = net.a, net.b
    ends = {a, b}
    els = net.els
    if len(els) == 1 and els[0].kind == "R" and {els[0].p, els[0].n} == ends:
        return _Final("R", 0.0, els[0].val, els)
    if len(els) != 2:
        return None
    kinds = sorted(e.kind for e in els)
    if kinds == ["I", "R"] and all({e.p, e.n} == ends for e in els):
        src = next(e for e in els if e.kind == "I")
        res = next(e for e in els if e.kind == "R")
        return _Final("IR", _inj_toward(src, a) * res.val, res.val, els)
    if kinds == ["R", "V"]:
        v = next(e for e in els if e.kind == "V")
        r = next(e for e in els if e.kind == "R")
        common = {v.p, v.n} & {r.p, r.n}
        if len(common) != 1:
            return None
        kn = next(iter(common))
        v_out = v.n if v.p == kn else v.p
        r_out = r.n if r.p == kn else r.p
        if kn in ends or {v_out, r_out} != ends:
            return None
        emf = _emf_toward(v, v_out)                 # v_out ucu, kn'ye göre bu kadar yüksek
        return _Final("VR", emf if v_out == a else -emf, r.val, els)
    return None


def _reduce(net: _Net) -> _Final:
    seen = set()
    for _ in range(_MAX_ITER):
        fin = _final(net)
        if fin is not None:
            return fin
        sig = net.signature()
        if sig in seen:
            raise _Fail(_STUCK)
        seen.add(sig)
        if (_step_cleanup(net) or _step_chain(net) or _step_parallel(net)
                or _step_vr(net) or _step_ir(net)):
            continue
        raise _Fail(_STUCK)
    raise _Fail(_STUCK)


def build_source_transform(ctx) -> Tuple[Optional[list], str]:
    """(bölümler, '') ya da (None, uygulanamama sebebi)."""
    from explainer.narrative import _Section, _close

    if not ctx.is_dc:
        return None, "Kaynak dönüşümü bu programda yalnızca DC devreler için anlatılıyor."
    if ctx.has_dependent:
        return None, ("Devrede bağımlı (kontrollü) kaynak var; bağımlı kaynaklar bu dönüşümlerle "
                      "sadeleştirilemez.")
    if not ctx.terminals or ctx.results.thevenin is None:
        return None, "Terminal çifti (A ve B düğümleri) belirtilmemiş ya da eşdeğer hesaplanamadı."
    for e in ctx.elements:
        if e.element_type not in _ALLOWED:
            return None, (f"{e.id} elemanı direnç ya da bağımsız DC kaynak değil; bu anlatım yalnızca "
                          "dirençli, bağımsız DC kaynaklı devreleri sadeleştirir.")
    a, b = ctx.terminals.node_positive, ctx.terminals.node_negative
    if a == b:
        return None, "İki terminal aynı düğüm."

    els = []
    for e in ctx.elements:
        if e.element_type == ElementType.RESISTOR:
            els.append(_El("R", e.id, e.node_positive, e.node_negative, float(e.value)))
        elif e.element_type == ElementType.DC_SOURCE:
            els.append(_El("V", e.id, e.node_positive, e.node_negative, float(e.value)))
        else:
            els.append(_El("I", e.id, e.node_positive, e.node_negative, float(e.value)))
    net = _Net(els, a, b)
    try:
        fin = _reduce(net)
    except _Fail as exc:
        return None, str(exc)

    th = ctx.results.thevenin
    vth, zth = complex(th.vth.real, th.vth.imaginary), complex(th.zth.real, th.zth.imaginary)
    if not _close(fin.e_th, vth.real, 1e-4) or not _close(fin.r_th, zth.real, 1e-4):
        return None, "Dönüşümlerle bulunan eşdeğer çözücünün Thevenin sonucuyla uyuşmadı."

    # ── Bölüm 1: yöntem ──
    s1 = _Section("Kaynak Dönüşümü — Yöntem")
    s1.text(f"Düğüm {a} (+) ile Düğüm {b} (−) terminallerinden bakıldığında devreyi, kaynak dönüşümleriyle "
            "adım adım sadeleştirip tek bir kaynak ve tek bir dirence indireceğiz. Kullanacağımız kurallar:")
    s1.math("• Gerilim kaynağı E ile seri R  ⇄  akım kaynağı I = E/R ile paralel R "
            "(akım oku, gerilim kaynağının + ucu tarafına bakar)")
    s1.math("• Paralel dirençler: R = R1·R2 / (R1 + R2); paralel akım kaynaklarının akımları toplanır "
            "(zıt yönlü olan çıkarılır)")
    s1.math("• Seri dirençler toplanır; seri gerilim kaynakları toplanır (kutupları zıt olan çıkarılır)")
    s1.math("• Akım kaynağına seri bağlı eleman, kolun akımını değiştirmez")
    s1.note("Yeni elemanlara Ra, Ia, Ea gibi adlar, dönüşümle oluşan ara düğümlere x1, x2, … adı verilir. "
            "Terminaller (Düğüm " + a + " ve Düğüm " + b + ") hiçbir adımda ortadan kaldırılmaz.")

    # ── Bölüm 2: adımlar ──
    s2 = _Section("Kaynak Dönüşümü — Adım Adım")
    for number, entries in enumerate(net.steps, 1):
        for idx, (kind, text) in enumerate(entries):
            if kind == "text":
                s2.text(f"{number}. adım: {text}" if idx == 0 else text)
            elif kind == "math":
                s2.math(text)
            else:
                s2.note(text)
    if fin.form == "R":
        s2.text("Kalan tek eleman bir dirençtir: devrede terminalleri besleyen etkin kaynak kalmadı, "
                "bu yüzden açık devre gerilimi sıfırdır.")
    elif fin.form == "IR":
        src = next(e for e in fin.elems if e.kind == "I")
        res = next(e for e in fin.elems if e.kind == "R")
        toward = a if src.n == a else b
        s2.text(f"Terminaller arasında artık bir akım kaynağı ve ona paralel bir direnç (Norton biçimi) var. "
                f"Gerilim kaynağına dönüştürürsek: E = {src.name}·{res.name}.")
        s2.math(f"E = {src.name}·{res.name} = {eng(src.val, 'A')} · {eng(res.val, 'Ω')} = "
                f"{eng(src.val * res.val, 'V')}  (+ ucu Düğüm {toward} tarafında)")
    else:
        s2.text("Terminaller arasında tek bir gerilim kaynağı ve ona seri tek bir direnç kaldı "
                "(Thevenin biçimi); sadeleştirme tamamdır.")

    # ── Bölüm 3: sonuç ──
    s3 = _Section("Kaynak Dönüşümü — Sonuç")
    sign_note = ""
    if fin.e_th < 0:
        sign_note = f" (eksi: Düğüm {b}, Düğüm {a}'dan daha yüksek potansiyelde)"
    s3.result(f"Vth = V_AB = {node_v(a)} {MINUS} {node_v(b)} = {eng(fin.e_th, 'V')}{sign_note}")
    s3.result(f"Rth = {eng(fin.r_th, 'Ω')}")
    if fin.r_th > 1e-12:
        i_n = fin.e_th / fin.r_th
        s3.math(f"In = Vth / Rth = {eng(fin.e_th, 'V')} / {eng(fin.r_th, 'Ω')} = {eng(i_n, 'A')}")
        s3.text("Thevenin eşdeğeri: Vth kaynağı ile seri Rth. Norton eşdeğeri: In akım kaynağı ile "
                "paralel Rth (In = Vth / Rth).")
    s3.check(f"Çözücünün Thevenin sonucuyla aynı: Vth = {eng(vth.real, 'V')}, Rth = {eng(zth.real, 'Ω')} ✓")
    return [s1, s2, s3], ""
