"""
CircuitAnalyzer API — Çevre Akımları Yöntemi Anlatımı

narrative.py'deki ortak yapıları (_Ctx, _Section, biçimlendirme) kullanır.
Sayısal çözüm solver/mesh.py'den gelir; her eleman akımı çözücünün (lcapy)
sonucuyla karşılaştırılır — uyuşmazsa çevre anlatımı hiç gösterilmez.
"""

from typing import Dict, List

import numpy as np

from explainer.formatting import MINUS, eng, num, polar, rect, sub
from explainer.narrative import (
    _Ctx, _Section, _close, _cnum, _flow_text, _join_terms, _linear_term,
    _pnum, _scale_for,
)
from parser.netlist_parser import CURRENT_SOURCES, VOLTAGE_SOURCES
from solver.mesh import MeshAnalysis


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
    return True


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
    parent = {m.index: m.index for m in ma.meshes}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for cid in ma.currents_cs:
        ks = list(signs.get(cid, {}))
        for k in ks[1:]:
            parent[find(k)] = find(ks[0])
    groups: Dict[int, List[int]] = {}
    for m in ma.meshes:
        groups.setdefault(find(m.index), []).append(m.index)

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
        if M == 2:
            a11, a12, a21, a22 = Zs[0, 0], Zs[0, 1], Zs[1, 0], Zs[1, 1]
            b1, b2 = V
            det = a11 * a22 - a12 * a21
            d1 = b1 * a22 - a12 * b2
            d2 = a11 * b2 - b1 * a21
            s.text("İki bilinmeyenli sistemi Cramer kuralıyla çözelim:")
            s.math(f"Δ = {_pnum(a11)}·{_pnum(a22)} {MINUS} {_pnum(a12)}·{_pnum(a21)} = {_cnum(det)}")
            s.math(f"Δ₁ = {_pnum(b1)}·{_pnum(a22)} {MINUS} {_pnum(a12)}·{_pnum(b2)} = {_cnum(d1)}")
            s.math(f"Δ₂ = {_pnum(a11)}·{_pnum(b2)} {MINUS} {_pnum(b1)}·{_pnum(a21)} = {_cnum(d2)}")
            for k, d in ((0, d1), (1, d2)):
                if ctx.is_dc:
                    scaled = f"{num(Is[k].real)} {unit_i}"
                    final = eng(I[k].real, "A")
                    s.result(f"{mesh_symbol(k + 1)} = Δ{sub(str(k + 1))}/Δ = {_cnum(d)} / {_cnum(det)} "
                             f"= {scaled}" + ("" if scaled == final else f" = {final}"))
                else:
                    s.result(f"{mesh_symbol(k + 1)} = Δ{sub(str(k + 1))}/Δ = {polar(I[k], 'A')}")
        else:
            s.text(f"{M} bilinmeyenli bu sistem Gauss eliminasyonu ile çözülünce:")
            for k in range(M):
                s.result(f"{mesh_symbol(k + 1)} = {ctx.val(I[k], 'A')}")
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

    # ── 5. Eleman akımları ──
    s = _Section("Eleman Akımları (Çevre Akımlarından)")
    s.text("Bir elemandan geçen akım, o elemandan geçen çevre akımlarının cebirsel "
           "toplamıdır (aynı yönde olan +, ters yönde olan − alınır).")
    # Önce pasif elemanlar (devre sırasıyla), sonra kaynaklar
    order = [e.id for e in ctx.elements if e.id in signs]
    order.sort(key=lambda eid: elements[eid].element_type in VOLTAGE_SOURCES + CURRENT_SOURCES)
    for eid in order:
        sg_map = signs[eid]
        e = elements[eid]
        ib = ma.branch_currents[eid]
        p, n = e.node_positive, e.node_negative
        if e.element_type in CURRENT_SOURCES:
            s.math(f"I_{eid} = {ctx.val(ib, 'A')} (akım kaynağı — bilinen, {_flow_text(p, n)} kaynak içinden)")
            continue
        if e.element_type in VOLTAGE_SOURCES:
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
    sections.append(s)
    return sections
