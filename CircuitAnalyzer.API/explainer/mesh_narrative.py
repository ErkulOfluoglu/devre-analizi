"""
CircuitAnalyzer API — Çevre Akımları Yöntemi Anlatımı

narrative.py'deki ortak yapıları (_Ctx, _Section, biçimlendirme) kullanır.
Sayısal çözüm solver/mesh.py'den gelir; her eleman akımı çözücünün (lcapy)
sonucuyla karşılaştırılır — uyuşmazsa çevre anlatımı hiç gösterilmez.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from explainer.cramer import cramer3, exact_fmt, integer_rows
from explainer.formatting import MINUS, eng, node_v, num, paren, polar, rect, sub
from explainer.narrative import (
    _Ctx, _Section, _close, _cnum, _flow_text, _integer_step, _join_terms, _linear_term,
    _pnum, _scale_for,
)
from parser.netlist_parser import (
    CURRENT_SOURCES, DEPENDENT_CURRENT_OUTPUT, DEPENDENT_VOLTAGE_OUTPUT, VOLTAGE_SOURCES,
)
from solver.mesh import MeshAnalysis, MeshDependent


def mesh_symbol(k: int) -> str:
    """Çevre akımı sembolü: 1 → I₁."""
    return f"I{sub(str(k))}"


def _combo(coeffs: Dict[int, int], paren_multi: bool = True) -> str:
    """{1: +1, 2: −1} → '(I₁ − I₂)'; tek terim '+1' → 'I₁'."""
    terms = []
    for k in sorted(coeffs, key=lambda k: (coeffs[k] < 0, k)):
        c = coeffs[k]
        if c == 0:
            continue
        mag = "" if abs(c) == 1 else f"{abs(c)}·"
        terms.append(f"{MINUS if c < 0 else ''}{mag}{mesh_symbol(k)}")
    text = _join_terms(terms) if terms else "0"
    return f"({text})" if paren_multi and len(terms) > 1 else text


def _sign_map(ma: MeshAnalysis) -> Dict[str, Dict[int, int]]:
    """Eleman → {çevre no: yön işareti}."""
    out: Dict[str, Dict[int, int]] = {}
    for m in ma.meshes:
        for e, sg in m.elements:
            out.setdefault(e.id, {})[m.index] = sg
    return out


def _mesh_matrices(signs, ma: MeshAnalysis, M: int):
    """Pasif elemanlardan Z (çevre empedans matrisi), kaynaklardan V."""
    Z = np.zeros((M, M), dtype=complex)
    V = np.zeros(M, dtype=complex)
    for eid, sg_map in signs.items():
        if eid in ma.impedances:
            for a, sa in sg_map.items():
                for c, sc in sg_map.items():
                    Z[a - 1, c - 1] += sa * sc * ma.impedances[eid]
        elif eid in ma.voltages:
            for a, sa in sg_map.items():
                V[a - 1] -= sa * ma.voltages[eid]
    return Z, V


def verify(ctx: _Ctx, ma: MeshAnalysis) -> bool:
    """Çevre akımlarından bulunan her eleman akımı çözücüyle aynı mı?"""
    if not ma.ok:
        return False
    for eid, ib in ma.branch_currents.items():
        if eid not in ctx.i or not _close(ib, ctx.i[eid], 1e-6):
            return False
    if ma.dependents:
        # Anlatımda gösterilecek denklem sistemi de aynı çözümü vermeli
        signs = _sign_map(ma)
        groups, cs_ids = _groups(ma, signs)
        rows = _reduced_rows(ma, signs, groups, cs_ids)
        M = len(ma.meshes)
        if len(rows) != M:
            return False
        try:
            x = np.linalg.solve(np.array([r.coeff for r in rows]), np.array([r.rhs for r in rows]))
        except np.linalg.LinAlgError:
            return False
        if not all(_close(x[k], ma.mesh_currents[k], 1e-6) for k in range(M)):
            return False
        # Bağımlı gerilim kaynağının uç gerilimi = kazanç · kontrol
        for d in ma.dependents.values():
            if d.is_current_output:
                continue
            e = d.element
            if all(n in ctx.v or n == "0" for n in (e.node_positive, e.node_negative)):
                vd = ctx.node_value(e.node_positive) - ctx.node_value(e.node_negative)
                if not _close(vd, d.value, 1e-6):
                    return False
    return True


def _cs_ids(ma: MeshAnalysis) -> List[str]:
    """Akım kaynakları: önce bağımsızlar, sonra bağımlılar (G, F)."""
    return list(ma.currents_cs) + [d.id for d in ma.dependents.values() if d.is_current_output]


def _groups(ma: MeshAnalysis, signs) -> Tuple[Dict[int, List[int]], List[str]]:
    """Ortak akım kaynağı olan çevreleri birleştirir → ({kök: [çevre no…]}, akım kaynağı kimlikleri)."""
    cs_ids = _cs_ids(ma)
    parent = {m.index: m.index for m in ma.meshes}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for cid in cs_ids:
        ks = list(signs.get(cid, {}))
        for k in ks[1:]:
            parent[find(k)] = find(ks[0])
    groups: Dict[int, List[int]] = {}
    for m in ma.meshes:
        groups.setdefault(find(m.index), []).append(m.index)
    return groups, cs_ids


def _boundary_cs(signs, cs_ids: List[str], mset) -> List[str]:
    """Grubun sınırında (tek çevresinde) kalan akım kaynakları: kaynak gerilimi bilinmez."""
    return [cid for cid in cs_ids
            if sum(signs.get(cid, {}).get(k, 0) for k in mset) != 0
            and set(signs.get(cid, {})) & mset]


@dataclass
class _Row:
    """Bağımlı kaynaklı sistemin bir denklemi (bilinmeyenler: I₁…I_M)."""
    kind: str                  # "kvl" | "cs"
    members: List[int]         # kvl: grubun çevreleri
    cid: str                   # cs: kaynak kimliği
    coeff: np.ndarray          # çevre akımı katsayıları (sol taraf)
    rhs: complex


def _reduced_rows(ma: MeshAnalysis, signs, groups, cs_ids) -> List[_Row]:
    """
    Anlatımdaki M denklem: sınırında akım kaynağı olmayan her (süper)çevre için
    bir KVL, her akım kaynağı için bir kısıt. Bağımlı terimlerin katsayıları sol
    tarafa taşınmıştır.
    """
    M = len(ma.meshes)
    rows: List[_Row] = []
    for root, members in sorted(groups.items()):
        mset = set(members)
        if _boundary_cs(signs, cs_ids, mset):
            continue
        coeff = np.zeros(M, dtype=complex)
        rhs = 0j
        for eid, sg_map in signs.items():
            sigma = sum(sg_map.get(k, 0) for k in mset)
            if sigma == 0:
                continue
            if eid in ma.impedances:
                for k, sg in sg_map.items():
                    coeff[k - 1] += sigma * sg * ma.impedances[eid]
            elif eid in ma.voltages:
                rhs -= sigma * ma.voltages[eid]
            elif eid in ma.dependents and not ma.dependents[eid].is_current_output:
                d = ma.dependents[eid]
                for k, c in d.coefficients().items():
                    coeff[k - 1] += sigma * d.gain * c
                rhs -= sigma * d.gain * d.ctrl_const
        rows.append(_Row("kvl", list(members), "", coeff, rhs))
    for cid in cs_ids:
        coeff = np.zeros(M, dtype=complex)
        for k, sg in signs.get(cid, {}).items():
            coeff[k - 1] += sg
        if cid in ma.currents_cs:
            rhs = ma.currents_cs[cid]
        else:
            d = ma.dependents[cid]
            for k, c in d.coefficients().items():
                coeff[k - 1] -= d.gain * c
            rhs = d.gain * d.ctrl_const
        rows.append(_Row("cs", [], cid, coeff, complex(rhs)))
    return rows


# ── Bağımlı kaynak metin yardımcıları ──

def _ctrl_sym(d: MeshDependent) -> str:
    """Kontrol büyüklüğünün adı: V_R2 / I_R3 (ters kontrolde de eksi yazılmaz)."""
    return f"{d.control_kind}_{d.control_id}"


def _gain_term(gain: float, factor: str) -> str:
    """3·V_R2, V_R2 (kazanç 1), −2·I_R3 (kazanç −2): eksi ile başlayabilir."""
    mag = abs(gain)
    body = factor if abs(mag - 1) < 1e-12 else f"{num(mag)}·{factor}"
    return f"{MINUS}{body}" if gain < 0 else body


def _times(factor: str, expr: str) -> str:
    """'4' ve '−I₂' → '4·(−I₂)'; sade ifadelerde parantez yok."""
    return f"{factor}·({expr})" if expr.startswith(MINUS) else f"{factor}·{expr}"


def _ctrl_numeric(ctx: _Ctx, d: MeshDependent) -> str:
    """Kontrol büyüklüğü, çevre akımları cinsinden sayısal: 4·(I₁ − I₂), I₂, 12."""
    if d.ctrl_z is None and not d.ctrl_signs:
        return _pnum(d.ctrl_const)    # bağımsız gerilim kaynağının gerilimi (veya 0)
    expr = _combo(d.ctrl_signs) if d.ctrl_signs else "0"
    if d.ctrl_z is None:
        return expr
    return _times(ctx.z_num(d.ctrl_z), expr)


def _dep_term(ctx: _Ctx, d: MeshDependent, net_gain: float, numeric: bool) -> str:
    """Bağımlı kaynak terimi: sembolik 3·V_R2 ya da sayısal 3·4·(I₁ − I₂)."""
    if not numeric:
        return _gain_term(net_gain, _ctrl_sym(d))
    mag = abs(net_gain)
    expr = _ctrl_numeric(ctx, d)
    body = expr if abs(mag - 1) < 1e-12 else _times(num(mag), expr)
    return f"{MINUS}{body}" if net_gain < 0 else body


def _solve_square(s: _Section, ctx: _Ctx, M: int, Zs, V, I, Is, unit_i: str,
                  labels: Optional[List[str]] = None) -> None:
    """
    M ≥ 2 bilinmeyenli Zs·I = V sistemi: 2×2 Cramer, 3×3 Sarrus, daha büyük → Gauss.
    DC'de 2-3 bilinmeyende kesirli (görünen) satırlar önce tam sayıya çarpılır.
    """
    labels = labels or [f"Çevre {k + 1}" for k in range(M)]
    if ctx.is_dc and M in (2, 3):
        Z2, V2, mult = integer_rows(Zs, V)
        if any(m > 1 for m in mult):
            _integer_step(s, labels, [mesh_symbol(c + 1) for c in range(M)], Z2, V2, mult)
            Zs, V = Z2, V2
    cn = exact_fmt(_cnum)

    def P(z) -> str:
        t = cn(z)
        return f"({t})" if t.startswith(MINUS) else t

    if M == 2:
        a11, a12, a21, a22 = Zs[0, 0], Zs[0, 1], Zs[1, 0], Zs[1, 1]
        b1, b2 = V
        det = a11 * a22 - a12 * a21
        d1 = b1 * a22 - a12 * b2
        d2 = a11 * b2 - b1 * a21
        s.text("İki bilinmeyenli sistemi Cramer kuralıyla çözelim:")
        s.math(f"Δ = {P(a11)}·{P(a22)} {MINUS} {P(a12)}·{P(a21)} = {cn(det)}")
        s.math(f"Δ₁ = {P(b1)}·{P(a22)} {MINUS} {P(a12)}·{P(b2)} = {cn(d1)}")
        s.math(f"Δ₂ = {P(a11)}·{P(b2)} {MINUS} {P(b1)}·{P(a21)} = {cn(d2)}")
        for k, d in ((0, d1), (1, d2)):
            if ctx.is_dc:
                scaled = f"{num(Is[k].real)} {unit_i}"
                final = eng(I[k].real, "A")
                s.result(f"{mesh_symbol(k + 1)} = Δ{sub(str(k + 1))}/Δ = {cn(d)} / {cn(det)} "
                         f"= {scaled}" + ("" if scaled == final else f" = {final}"))
            else:
                s.result(f"{mesh_symbol(k + 1)} = Δ{sub(str(k + 1))}/Δ = {polar(I[k], 'A')}")
    elif M == 3:
        s.text("Üç bilinmeyenli sistemi Cramer kuralıyla çözelim. Determinantları Sarrus "
               "yöntemiyle hesaplayalım: ilk iki sütun sağa tekrar yazılır, soldan sağa inen "
               "köşegenlerin çarpımları toplanır, sağdan sola inenlerinkiler çıkarılır. "
               "Δₖ için k. sütunun yerine sağ taraf yazılır.")
        dets = cramer3(Zs, V, cn)
        for _, text, _ in dets:
            s.math(text)
        det = dets[0][2]
        for k in range(3):
            symbol, _, d = dets[k + 1]
            if ctx.is_dc:
                scaled = f"{num(Is[k].real)} {unit_i}"
                final = eng(I[k].real, "A")
                s.result(f"{mesh_symbol(k + 1)} = {symbol}/Δ = {cn(d)} / {cn(det)} "
                         f"= {scaled}" + ("" if scaled == final else f" = {final}"))
            else:
                s.result(f"{mesh_symbol(k + 1)} = {symbol}/Δ = {polar(I[k], 'A')}")
    else:
        s.text(f"{M} bilinmeyenli bu sistem Gauss eliminasyonu ile çözülünce:")
        for k in range(M):
            s.result(f"{mesh_symbol(k + 1)} = {ctx.val(I[k], 'A')}")


def _element_currents_section(ctx: _Ctx, ma: MeshAnalysis, signs, elements) -> _Section:
    """Eleman akımları (çevre akımlarından); bağımlı kaynaklarda değer kontrolü de verilir."""
    I = ma.mesh_currents
    s = _Section("Eleman Akımları (Çevre Akımlarından)")
    s.text("Bir elemandan geçen akım, o elemandan geçen çevre akımlarının cebirsel "
           "toplamıdır (aynı yönde olan +, ters yönde olan − alınır).")
    # Önce pasif elemanlar (devre sırasıyla), sonra kaynaklar
    order = [e.id for e in ctx.elements if e.id in signs]
    cs_types = CURRENT_SOURCES + DEPENDENT_CURRENT_OUTPUT
    vs_types = VOLTAGE_SOURCES + DEPENDENT_VOLTAGE_OUTPUT
    order.sort(key=lambda eid: elements[eid].element_type in vs_types + cs_types)
    for eid in order:
        sg_map = signs[eid]
        e = elements[eid]
        ib = ma.branch_currents[eid]
        p, n = e.node_positive, e.node_negative
        if e.element_type in cs_types:
            kind = ("bağımlı akım kaynağı — değeri kontrol büyüklüğünden"
                    if eid in ma.dependents else "akım kaynağı — bilinen")
            s.math(f"I_{eid} = {ctx.val(ib, 'A')} ({kind}, {_flow_text(p, n)} kaynak içinden)")
            continue
        if e.element_type in vs_types:
            # Kaynağın VERDİĞİ akım: içinden − uçtan + uca (pasif kuralın tersi)
            delivered = {k: -sg for k, sg in sg_map.items()}
            s.math(f"{eid} kaynağının verdiği akım = {_combo(delivered, paren_multi=False)} = "
                   f"{ctx.val(-ib, 'A')}  (kaynak içinde {_flow_text(n, p)}"
                   f"{', + ucundan dışarı' if ctx.is_dc and (-ib).real >= 0 else ''})")
            continue
        expr = _combo(sg_map, paren_multi=False)

        def value_term(v: complex, sg: int) -> str:
            # DC: '6 mA', negatifse '(−3 mA)'; AC: her zaman parantezli kutupsal
            if ctx.is_dc:
                t = eng(v.real, "A")
                t = f"({t})" if v.real < 0 else t
            else:
                t = f"({polar(v, 'A')})"
            return f"{MINUS}{t}" if sg < 0 else t

        ordered = sorted(sg_map.items(), key=lambda kv: (kv[1] < 0, kv[0]))
        values = (_join_terms([value_term(I[k - 1], sg) for k, sg in ordered])
                  if len(sg_map) > 1 else None)
        line = f"I_{eid} = {expr}"
        if values:
            line += f" = {values}"
        if ctx.is_dc:
            line += f" = {eng(ib.real, 'A')}"
            if ib.real >= 0:
                s.math(f"{line}  ({_flow_text(p, n)})")
            else:
                s.math(line)
                s.note(f"Eksi işaret: {eid} akımı ters yönde, {eng(-ib.real, 'A')}, {_flow_text(n, p)}.")
        else:
            s.math(f"{line} = {polar(ib, 'A')}  ({_flow_text(p, n)} referans)")
    if ma.dependents:
        for d in ma.dependents.values():
            unit_c = "V" if d.control_kind == "V" else "A"
            unit_o = "A" if d.is_current_output else "V"
            sym = _ctrl_sym(d)
            if abs(d.gain - 1) < 1e-12:
                calc = f"{sym} = {ctx.val(d.value, unit_o)}"
            else:
                calc = (f"{num(d.gain)}·{sym} = {num(d.gain)} · "
                        f"{paren(ctx.val(d.ctrl_value, unit_c))} = {ctx.val(d.value, unit_o)}")
            s.math(f"Bağımlı kaynağın değeri: {d.id} = {calc}")
        s.check("Bağımlı kaynak çıkışları, kontrol büyüklükleriyle tutarlı ✓")
    return s


# ═══════════════════════════════════════════════════════
#  BAĞIMLI KAYNAKLI DEVRELER
# ═══════════════════════════════════════════════════════

def _drawn_description(ctx: _Ctx, d: MeshDependent) -> str:
    """Kontrol büyüklüğünün çizilen yönü: V_R2 = V₃ − V₂ / R3 içinden Düğüm 2 → Düğüm 3."""
    ctrl = next((e for e in ctx.elements if e.id == d.control_id), None)
    if ctrl is None:
        return ""
    plus, minus = ctrl.node_positive, ctrl.node_negative
    if d.control_sign < 0:
        plus, minus = minus, plus   # ters kontrol: (+) uç elemanın n− ucudur
    if d.control_kind == "V":
        return f"V_{ctrl.id} = {node_v(plus)} {MINUS} {node_v(minus)}"
    return f"I_{ctrl.id}: {ctrl.id} elemanından {_flow_text(plus, minus)} yönünde geçen akım"


def _control_line(ctx: _Ctx, d: MeshDependent) -> str:
    """Kontrol büyüklüğünün çevre akımlarıyla yazılışı: V_R2 = R2·(I₁ − I₂) = 4·(I₁ − I₂)."""
    sym = _ctrl_sym(d)
    ctrl = next(e for e in ctx.elements if e.id == d.control_id)
    if d.control_kind == "I":
        return f"{sym} = {_combo(d.ctrl_signs, paren_multi=False) if d.ctrl_signs else '0'}"
    if d.ctrl_z is None:
        # Bağımsız gerilim kaynağının gerilimi: kaynağın kendi değeri
        sign = MINUS if d.control_sign < 0 else ""
        return f"{sym} = {sign}{ctrl.id} = {ctx.val(d.ctrl_const, 'V')}"
    if not d.ctrl_signs:
        return f"{sym} = 0"
    combo = _combo(d.ctrl_signs)
    return (f"{sym} = {_times(ctx.label(ctrl), combo)} = "
            f"{_times(ctx.z_num(d.ctrl_z), combo)}")


def _kvl_terms(ctx: _Ctx, ma: MeshAnalysis, signs, elements, mset, dep_numeric: bool):
    """
    Bir (süper)çevrenin KVL terimleri: (sol sembolik, sol sayısal, sağ sembolik, sağ sayısal).
    Bağımlı gerilim kaynağı sağ tarafta bağımsız kaynakla aynı işaretle yazılır
    (−σ·E); sembolik hâlde 3·V_R2, dep_numeric ise 3·4·(I₁ − I₂).
    """
    sym_terms, num_terms, rhs_sym, rhs_num = [], [], [], []
    for eid, sg_map in signs.items():
        sigma = sum(sg_map.get(k, 0) for k in mset)
        if sigma == 0:
            continue
        e = elements[eid]
        if eid in ma.impedances:
            z = ma.impedances[eid]
            if abs(z) < 1e-15:
                continue   # DC'de bobin: Z = 0
            coeffs = {k: sigma * sg for k, sg in sg_map.items()}
            sym_terms.append(f"{ctx.label(e)}·{_combo(coeffs)}")
            num_terms.append(f"{ctx.z_num(z)}·{_combo(coeffs)}")
        elif eid in ma.voltages and abs(ma.voltages[eid]) > 1e-15:
            vs = ma.voltages[eid]
            rhs_sym.append(e.id if -sigma > 0 else f"{MINUS}{e.id}")
            rhs_num.append(_cnum(-sigma * vs))
        elif eid in ma.dependents and not ma.dependents[eid].is_current_output:
            d = ma.dependents[eid]
            rhs_sym.append(_dep_term(ctx, d, -sigma * d.gain, numeric=False))
            rhs_num.append(_dep_term(ctx, d, -sigma * d.gain, numeric=dep_numeric))
    return sym_terms, num_terms, rhs_sym, rhs_num


def _dependent_sections(ctx: _Ctx, ma: MeshAnalysis, signs, elements, groups,
                        cs_ids: List[str]) -> List[_Section]:
    """KVL → kontrol büyüklükleri → yerine koy/topla/çöz → eleman akımları."""
    M = len(ma.meshes)
    I = ma.mesh_currents
    deps = ma.dependents
    out: List[_Section] = []

    # ── (a) KVL denklemleri ──
    s = _Section("Çevre Denklemleri (KVL)")
    s.text("Kirchhoff Gerilim Yasası: Bir çevre boyunca dolaşıldığında elemanlardaki "
           "gerilim düşümlerinin toplamı, kaynak gerilimlerinin toplamına eşittir. "
           "Bir elemandaki düşüm Z × (o elemandan geçen akım) şeklinde yazılır; "
           "gerilim kaynağı − uçtan + uca geçiliyorsa sağ tarafa + işaretiyle yazılır.")
    first = next(iter(deps.values()))
    s.text("Bağımlı kaynaklar da KVL'ye normal bir kaynak gibi girer; yalnızca değeri sabit "
           f"değil, bir kontrol büyüklüğünün kazançla çarpımıdır (örneğin {first.id} = "
           f"{_dep_term(ctx, first, first.gain, numeric=False)}). Bu terim bilinmeyen çevre "
           "akımlarına bağlı olduğundan sonra sol tarafa geçecektir.")

    for root, members in sorted(groups.items()):
        mset = set(members)
        if _boundary_cs(signs, cs_ids, mset):
            continue   # Kaynak gerilimi bilinmiyor → KVL yerine kısıt kullanılır
        sym_terms, num_terms, rhs_sym, rhs_num = _kvl_terms(ctx, ma, signs, elements, mset, False)
        if len(members) == 1:
            title = f"Çevre {members[0]}"
        else:
            title = "Süperçevre {" + ", ".join(str(k) for k in members) + "}"
            shared = [cid for cid in cs_ids if set(signs.get(cid, {})) <= mset]
            s.text(f"{', '.join(shared)} akım kaynağı Çevre {' ve '.join(str(k) for k in members)} "
                   "arasında ortak. Kaynağın uçlarındaki gerilim bilinmediği için bu "
                   "çevrelerin KVL denklemleri toplanır (süperçevre); kaynak dışarıda kalır.")
        s.math(f"{title}: {_join_terms(sym_terms) or '0'} = {_join_terms(rhs_sym) or '0'}")
        s.math(f"⇒ {_join_terms(num_terms) or '0'} = {_join_terms(rhs_num) or '0'}")

    for cid in cs_ids:
        sg_map = signs.get(cid, {})
        lhs = _combo(sg_map, paren_multi=False)
        if cid in deps:
            d = deps[cid]
            rhs = _dep_term(ctx, d, d.gain, numeric=False)
            if len(sg_map) == 1:
                (k, _), = sg_map.items()
                s.text(f"{cid} bağımlı akım kaynağı yalnızca Çevre {k} üzerinde: bu çevrenin "
                       "akımı kaynağın akımına eşittir; ancak kaynağın akımı kontrol "
                       "büyüklüğüne bağlı olduğundan bilinmeyendir, bu bir denklem olarak "
                       "yazılır:")
            else:
                s.text(f"{cid} bağımlı akım kaynağının akımı, ondan geçen çevre akımlarının "
                       "farkına eşittir (kısıt); kaynağın akımı kontrol büyüklüğüne "
                       "bağlı olduğundan bu bir denklemdir:")
            s.math(f"{lhs} = {rhs}")
            continue
        i_s = ma.currents_cs[cid]
        if len(sg_map) == 1:
            (k, sg), = sg_map.items()
            s.text(f"{cid} akım kaynağı yalnızca Çevre {k} üzerinde: bu çevrenin akımı "
                   "doğrudan kaynağın akımıdır (KVL yazmaya gerek yok).")
            s.math(f"{mesh_symbol(k)} = {_cnum(sg * i_s)} A")
        else:
            s.text(f"{cid} akım kaynağının akımı, ondan geçen çevre akımlarının farkına eşittir (kısıt):")
            s.math(f"{lhs} = {_cnum(i_s)} A")
    out.append(s)

    # ── (b) Kontrol büyüklükleri ──
    s = _Section("Kontrol Büyüklüğünü Çevre Akımlarıyla Yazalım")
    s.text("Bağımlı kaynağın değeri devredeki bir gerilime ya da akıma bağlıdır; bu "
           "kontrol büyüklüğünü de bilinmeyen çevre akımlarıyla ifade etmeliyiz. Direncin "
           "gerilimi Ohm yasasıyla (V = Z·I), bir elemandan geçen akım ise o elemandan "
           "geçen çevre akımlarının cebirsel toplamıyla bulunur:")
    for d in deps.values():
        desc = _drawn_description(ctx, d)
        s.text(f"{d.id} = {_dep_term(ctx, d, d.gain, numeric=False)}"
               + (f" — {desc}" if desc else "") + ":")
        s.math(_control_line(ctx, d))
    out.append(s)

    # ── (c) Yerine koy, topla, çöz ──
    s = _Section("Denklemlerin Çözümü")
    rows = _reduced_rows(ma, signs, groups, cs_ids)
    A = np.array([r.coeff for r in rows], dtype=complex)
    V = np.array([r.rhs for r in rows], dtype=complex)
    s.text("Kontrol büyüklüklerini denklemlerde yerine koyalım:")
    for r in rows:
        if r.kind == "kvl":
            _, num_terms, _, rhs_num = _kvl_terms(ctx, ma, signs, elements, set(r.members), True)
            s.math(f"{_join_terms(num_terms) or '0'} = {_join_terms(rhs_num) or '0'}")
        else:
            lhs = _combo(signs.get(r.cid, {}), paren_multi=False)
            if r.cid in deps:
                rhs = _dep_term(ctx, deps[r.cid], deps[r.cid].gain, numeric=True)
            else:
                rhs = _cnum(ma.currents_cs[r.cid])
            s.math(f"{lhs} = {rhs}")

    has_cs_rows = any(r.kind == "cs" for r in rows)
    if has_cs_rows or M == 1:
        scale, prefix = 1.0, ""
    else:
        scale, prefix = _scale_for(list(A.flatten()))
    As = A * scale
    unit_r = {"k": "kΩ", "": "Ω", "m": "mΩ"}.get(prefix, f"{prefix}Ω")
    unit_i = {"k": "mA", "": "A", "m": "kA"}.get(prefix, "A")
    Is = [x / scale for x in I]
    if has_cs_rows:
        s.text("Bağımlı kaynak terimlerini sol tarafa geçirip çevre akımlarının "
               "katsayılarını toplayalım:")
    else:
        s.text("Bağımlı kaynak terimlerini sol tarafa geçirip çevre akımlarının "
               f"katsayılarını toplayalım (empedans {unit_r}, gerilim V, akım {unit_i} cinsinden):")
    for a in range(M):
        terms = [_linear_term(As[a, c], mesh_symbol(c + 1), first=(k == 0))
                 for k, c in enumerate(c for c in range(M) if abs(As[a, c]) > 1e-15)]
        s.math(f"{' '.join(terms) or '0'} = {_cnum(V[a])}")
    if M == 1:
        s.text("Tek bilinmeyenli denklemden çevre akımı:")
        s.result(f"{mesh_symbol(1)} = {_cnum(V[0])} / {_pnum(A[0, 0])} = {ctx.val(I[0], 'A')}")
    else:
        labels = [f"Çevre {r.members[0]}" if r.kind == "kvl" and len(r.members) == 1
                  else "Süperçevre {" + ", ".join(str(k) for k in r.members) + "}"
                  if r.kind == "kvl" else f"Kısıt ({r.cid})" for r in rows]
        _solve_square(s, ctx, M, As, V, I, Is, unit_i, labels)
    out.append(s)

    # ── (d, e) Eleman akımları ve bağımlı kaynak kontrolü ──
    out.append(_element_currents_section(ctx, ma, signs, elements))
    return out


def build_mesh_sections(ctx: _Ctx, ma: MeshAnalysis) -> List[_Section]:
    signs = _sign_map(ma)
    elements = {e.id: e for m in ma.meshes for e, _ in m.elements}
    sections: List[_Section] = []

    # ── 1. Çevreler ──
    s = _Section("Çevreler (Gözler)")
    s.text("Çevre akımları yönteminde her bağımsız çevreye (göze) bir çevre akımı "
           "atanır. Bağımsız çevre sayısı:")
    s.math(f"çevre sayısı = eleman sayısı {MINUS} düğüm sayısı + 1 = "
           f"{ma.element_count} {MINUS} {ma.node_count} + 1 = {len(ma.meshes)}")
    for note in ma.removed_notes:
        s.note(note)
    for m in ma.meshes:
        names = ", ".join(e.id for e, _ in m.elements)
        path = " → ".join(m.nodes)
        s.math(f"Çevre {m.index} ({mesh_symbol(m.index)}): Düğüm {path}  —  {names}")
    if ma.clockwise:
        s.note("Tüm çevre akımları saat yönünde seçildi. İki çevrenin ortak "
               "elemanından iki çevre akımı ters yönde geçer.")
    else:
        s.note("Tüm çevre akımları aynı dönüş yönünde (yukarıdaki düğüm sırasıyla) "
               "seçildi. İki çevrenin ortak elemanından iki çevre akımı ters yönde geçer.")
    sections.append(s)

    # ── 2. Akım kaynakları ve gruplar (süperçevre) ──
    groups, cs_ids = _groups(ma, signs)
    if ma.dependents:
        sections.extend(_dependent_sections(ctx, ma, signs, elements, groups, cs_ids))
        return sections

    # ── 3. KVL denklemleri ──
    s = _Section("Çevre Denklemleri (KVL)")
    s.text("Kirchhoff Gerilim Yasası: Bir çevre boyunca dolaşıldığında elemanlardaki "
           "gerilim düşümlerinin toplamı, kaynak gerilimlerinin toplamına eşittir. "
           "Bir elemandaki düşüm Z × (o elemandan geçen akım) şeklinde yazılır; "
           "gerilim kaynağı − uçtan + uca geçiliyorsa sağ tarafa + işaretiyle yazılır.")

    for root, members in sorted(groups.items()):
        mset = set(members)
        # Bu gruptaki akım kaynaklarından grup dışına "taşan" var mı?
        boundary_cs = [cid for cid in ma.currents_cs
                       if sum(signs.get(cid, {}).get(k, 0) for k in mset) != 0
                       and set(signs.get(cid, {})) & mset]
        if boundary_cs:
            continue   # Kaynak gerilimi bilinmiyor → KVL yerine kısıt kullanılır
        sym_terms, num_terms, rhs_sym, rhs_num = [], [], [], []
        for eid, sg_map in signs.items():
            sigma = sum(sg_map.get(k, 0) for k in mset)
            if sigma == 0:
                continue
            e = elements[eid]
            if eid in ma.impedances:
                z = ma.impedances[eid]
                if abs(z) < 1e-15:
                    continue   # DC'de bobin: Z = 0
                coeffs = {k: sigma * sg for k, sg in sg_map.items()}
                sym_terms.append(f"{ctx.label(e)}·{_combo(coeffs)}")
                num_terms.append(f"{ctx.z_num(z)}·{_combo(coeffs)}")
            elif eid in ma.voltages and abs(ma.voltages[eid]) > 1e-15:
                vs = ma.voltages[eid]
                rhs_sym.append(e.id if -sigma > 0 else f"{MINUS}{e.id}")
                rhs_num.append(_cnum(-sigma * vs))
        if len(members) == 1:
            title = f"Çevre {members[0]}"
        else:
            title = "Süperçevre {" + ", ".join(str(k) for k in members) + "}"
            shared = [cid for cid in ma.currents_cs if set(signs.get(cid, {})) <= mset]
            s.text(f"{', '.join(shared)} akım kaynağı Çevre {' ve '.join(str(k) for k in members)} "
                   "arasında ortak. Kaynağın uçlarındaki gerilim bilinmediği için bu "
                   "çevrelerin KVL denklemleri toplanır (süperçevre); kaynak dışarıda kalır.")
        s.math(f"{title}: {_join_terms(sym_terms) or '0'} = {_join_terms(rhs_sym) or '0'}")
        s.math(f"⇒ {_join_terms(num_terms) or '0'} = {_join_terms(rhs_num) or '0'}")

    for cid, i_s in ma.currents_cs.items():
        sg_map = signs.get(cid, {})
        if len(sg_map) == 1:
            (k, sg), = sg_map.items()
            s.text(f"{cid} akım kaynağı yalnızca Çevre {k} üzerinde: bu çevrenin akımı "
                   "doğrudan kaynağın akımıdır (KVL yazmaya gerek yok).")
            s.math(f"{mesh_symbol(k)} = {_cnum(sg * i_s)} A")
        else:
            s.text(f"{cid} akım kaynağının akımı, ondan geçen çevre akımlarının farkına eşittir (kısıt):")
            s.math(f"{_combo(sg_map, paren_multi=False)} = {_cnum(i_s)} A")
    sections.append(s)

    # ── 4. Çözüm ──
    s = _Section("Denklemlerin Çözümü")
    M = len(ma.meshes)
    I = ma.mesh_currents
    if not ma.currents_cs and M == 1:
        e_terms = [(eid, sg_map) for eid, sg_map in signs.items() if eid in ma.impedances
                   and abs(ma.impedances[eid]) > 1e-15]
        ztot = sum(ma.impedances[eid] for eid, _ in e_terms)
        vs_tot = sum(-sg_map[1] * ma.voltages[eid] for eid, sg_map in signs.items()
                     if eid in ma.voltages)
        rhs_sym = [eid if -sg_map[1] > 0 else f"{MINUS}{eid}"
                   for eid, sg_map in signs.items()
                   if eid in ma.voltages and abs(ma.voltages[eid]) > 1e-15]
        lbls = " + ".join(ctx.label(elements[eid]) for eid, _ in e_terms)
        nums = " + ".join(ctx.z_num(ma.impedances[eid]) for eid, _ in e_terms)
        s.text("Tek çevre olduğu için çevre akımı, toplam kaynak geriliminin toplam "
               "empedansa bölümüdür:")
        s.math(f"{mesh_symbol(1)} · ({lbls}) = {_join_terms(rhs_sym) or '0'}")
        s.math(f"{mesh_symbol(1)} · ({nums}) = {_cnum(vs_tot)}")
        if ctx.is_dc:
            s.result(f"{mesh_symbol(1)} = {eng(vs_tot.real, 'V')} / {eng(ztot.real, 'Ω')} = "
                     f"{eng(I[0].real, 'A')}")
        else:
            s.result(f"{mesh_symbol(1)} = {polar(vs_tot, 'V')} / {polar(ztot, 'Ω')} = "
                     f"{polar(I[0], 'A')}")
    elif not ma.currents_cs and M >= 2:
        Z, V = _mesh_matrices(signs, ma, M)
        scale, prefix = _scale_for(list(Z.flatten()))
        # Z'yi k ile, I'yı 1/k ile ölçekle: kΩ ↔ mA
        Zs = Z * scale
        unit_r = {"k": "kΩ", "": "Ω", "m": "mΩ"}.get(prefix, f"{prefix}Ω")
        unit_i = {"k": "mA", "": "A", "m": "kA"}.get(prefix, "A")
        Is = [x / scale for x in I]
        s.text(f"Denklemleri düzenleyip çevre akımlarının katsayılarını toplayalım "
               f"(empedans {unit_r}, gerilim V, akım {unit_i} cinsinden):")
        for a in range(M):
            terms = [_linear_term(Zs[a, c], mesh_symbol(c + 1), first=(k == 0))
                     for k, c in enumerate(c for c in range(M) if abs(Zs[a, c]) > 1e-15)]
            s.math(f"{' '.join(terms)} = {_cnum(V[a])}")
        _solve_square(s, ctx, M, Zs, V, I, Is, unit_i)
    elif all(len(signs.get(cid, {})) == 1 for cid in ma.currents_cs):
        # Akım kaynakları yalnız dış kollarda: o çevrelerin akımı bilinir,
        # diğer KVL denklemlerinde yerine konur
        Z, V = _mesh_matrices(signs, ma, M)
        known = {}
        for cid, i_s in ma.currents_cs.items():
            (k, sg), = signs[cid].items()
            known[k] = sg * i_s
        unknown = [k for k in range(1, M + 1) if k not in known]
        s.text("Akım kaynaklarından bilinen çevre akımları: "
               + ", ".join(f"{mesh_symbol(k)} = {ctx.val(v, 'A')}" for k, v in sorted(known.items())))
        if len(unknown) == 1:
            u = unknown[0]
            zuu = Z[u - 1, u - 1]
            vred = V[u - 1] - sum(Z[u - 1, k - 1] * known[k] for k in known)
            terms = [_linear_term(zuu, mesh_symbol(u), first=True)]
            terms += [f"+ {_pnum(Z[u - 1, k - 1])}·({_cnum(known[k])})"
                      for k in sorted(known) if abs(Z[u - 1, k - 1]) > 1e-15]
            s.text(f"Çevre {u} denkleminde bilinen akımları yerine koyalım:")
            s.math(f"{' '.join(terms)} = {_cnum(V[u - 1])}")
            s.math(f"{_pnum(zuu)}·{mesh_symbol(u)} = {_cnum(vred)}")
            s.result(f"{mesh_symbol(u)} = {_cnum(vred)} / {_pnum(zuu)} = {ctx.val(I[u - 1], 'A')}")
        else:
            if unknown:
                s.text("Bilinen akımlar yerine konduktan sonra kalan denklemler birlikte çözülünce:")
            for k in unknown:
                s.result(f"{mesh_symbol(k)} = {ctx.val(I[k - 1], 'A')}")
    else:
        s.text("Denklemler (KVL ve akım kaynağı kısıtları) birlikte çözülünce:")
        for k in range(M):
            s.result(f"{mesh_symbol(k + 1)} = {ctx.val(I[k], 'A')}")
    sections.append(s)

    sections.append(_element_currents_section(ctx, ma, signs, elements))
    return sections
