"""
CircuitAnalyzer API — Süperpozisyon Yöntemi Anlatımı

Her kaynak için "yalnız bu kaynak aktif" alt devresinin çözümü, aynı
(doğrulanmış) düğüm anlatımı motoruyla üretilir ve ilgili adımın altına
yerleştirilir. Son bölümde katkılar toplanır:
    aynı frekans  → fazörler toplanır (tam çözümle karşılaştırılır)
    farklı frekans → her bileşen zaman domenine çevrilip toplanır
"""

import cmath
import math
from typing import Dict, List

from explainer.formatting import MINUS, eng, node_v, num, polar, rect
from explainer.narrative import _Ctx, _Section, _close, _join_terms
from models.request import AnalysisType
from models.response import AnalysisResults
from parser.netlist_parser import CURRENT_SOURCES, SINE_SOURCES, VOLTAGE_SOURCES
from solver.superposition import Contribution

_PRIMES = ["′", "″", "‴"]
_SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")

# Alt devre anlatımından alınan bölümler
_SUB_SECTIONS = ("Empedanslar ve Fazörler", "Bilinen Düğüm Gerilimleri",
                 "Düğüm Denklemleri (KCL)", "Denklemlerin Çözümü")


def mark(k: int) -> str:
    """1 → ′, 2 → ″, 3 → ‴, 4 → ⁽⁴⁾."""
    return _PRIMES[k - 1] if k <= len(_PRIMES) else f"⁽{str(k).translate(_SUPERSCRIPT)}⁾"


def _val(z: complex, unit: str, is_dc: bool) -> str:
    return eng(complex(z).real, unit) if is_dc else polar(z, unit)


def _domain(c: Contribution) -> str:
    return "DC" if c.is_dc else f"AC, f = {num(c.frequency)} Hz"


def _node_order(nodes) -> List[str]:
    return sorted((n for n in nodes if n != "0"), key=lambda n: (len(n), n))


def build_superposition_sections(ctx: _Ctx, contributions: List[Contribution]) -> List[_Section]:
    # Döngüsel içe aktarmayı önlemek için yerel import
    from explainer.narrative import build_explanation

    sections: List[_Section] = []
    s = _Section("Süperpozisyon İlkesi")
    s.text("Doğrusal bir devrede, birden fazla bağımsız kaynağın oluşturduğu gerilim ve "
           "akımlar, her kaynağın TEK BAŞINA oluşturduklarının toplamıdır. Her adımda "
           "yalnızca bir kaynak bırakılır; diğerleri sıfırlanır: gerilim kaynağı → kısa "
           "devre, akım kaynağı → açık devre.")
    if ctx.has_dependent:
        s.text("Bağımlı kaynaklar (" + ", ".join(e.id for e in ctx.dependents()) + ") bağımsız "
               "kaynak değildir: SIFIRLANMAZ, her adımda devrede aktif kalır (kontrol "
               "büyüklükleri o adımdaki devreden hesaplanır).")
    for k, c in enumerate(contributions, 1):
        s.math(f"{k}. adım: yalnız {c.source.id} ({_domain(c)}) → katkılar {mark(k)} ile "
               f"gösterilir (ör: V₂{mark(k)})")
    if len({c.frequency_key for c in contributions}) > 1:
        s.note("Kaynaklar farklı frekanslarda: her kaynak kendi frekansında çözülür, "
               "sonuçlar zaman domeninde toplanır.")
    sections.append(s)

    # ── Her kaynak için alt devre ──
    for k, c in enumerate(contributions, 1):
        sec = _Section(f"{k}. Adım — Yalnız {c.source.id} Aktif ({_domain(c)})")
        if c.zeroed:
            sec.text("Diğer kaynaklar sıfırlanır:")
            for z in c.zeroed:
                sec.math(f"• {z}")
        if c.error:
            sec.note(c.error)
            sections.append(sec)
            continue

        if ctx.has_dependent:
            # Alt devre denklemleri bağımlı kaynakları henüz bilmez; yalnızca
            # çözücü sonuçları gösterilir (tek not girişte verildi)
            sec.text("Bağımlı kaynaklar bu adımda da aktif; alt devre çözücüyle çözüldü.")
            sub = []
        else:
            sub = build_explanation(
                c.parsed, c.is_dc, c.frequency, AnalysisType.NODAL, None,
                c.node_voltages, c.element_currents, AnalysisResults(),
            )
        for sub_sec in sub:
            if sub_sec.title not in _SUB_SECTIONS:
                continue
            sec.text(f"{sub_sec.title}:")
            for b in sub_sec.blocks:
                # Genel tanım cümleleri her adımda tekrar etmesin
                if b.kind == "text" and (b.text.startswith("Kirchhoff") or
                                         b.text.startswith("Her elemanı")):
                    continue
                sec.blocks.append(b)

        sec.note(f"Bu adımda bulunan değerler {c.source.id} kaynağının katkısıdır "
                 f"({mark(k)} ile gösterilir).")
        for n in _node_order(c.node_voltages):
            sec.result(f"{node_v(n)}{mark(k)} = {_val(c.node_voltages[n], 'V', c.is_dc)}")
        sections.append(sec)

    # ── Toplam ──
    ok = [(k, c) for k, c in enumerate(contributions, 1) if not c.error]
    if not ok:
        return sections
    tot = _Section("Toplam: Katkıların Toplanması")
    freqs = sorted({c.frequency_key for _, c in ok})
    nodes = _node_order({n for _, c in ok for n in c.node_voltages})
    passives = [e for e in ctx.elements
                if e.element_type not in VOLTAGE_SOURCES + CURRENT_SOURCES]

    if len(freqs) == 1:
        is_dc = ok[0][1].is_dc
        same_as_main = (is_dc == ctx.is_dc) and (
            is_dc or (ctx.frequency is not None and _close(freqs[0], ctx.frequency, 1e-9)))
        tot.text("Tüm katkılar aynı " + ("DC" if is_dc else "frekansta") + " olduğundan doğrudan "
                 + ("toplanır:" if is_dc else "fazör olarak toplanır:"))

        def total_line(sym: str, key: str, kind: str, unit: str):
            values = [(k, (c.node_voltages if kind == "v" else c.element_currents).get(key))
                      for k, c in ok]
            values = [(k, v) for k, v in values if v is not None]
            total = sum(v for _, v in values)
            terms = _join_terms([f"{sym}{mark(k)}" for k, _ in values])
            nums = _join_terms([
                (_val(v, unit, is_dc) if not (is_dc and v.real < 0)
                 else f"({_val(v, unit, is_dc)})") if is_dc else f"({polar(v, unit)})"
                for _, v in values])
            tot.math(f"{sym} = {terms} = {nums} = {_val(total, unit, is_dc)}")
            return total

        for n in nodes:
            total = total_line(node_v(n), n, "v", "V")
            if same_as_main and n in ctx.v and not _close(total, ctx.v[n], 1e-5):
                tot.note(f"{node_v(n)} toplamı tam çözümle uyuşmuyor ({_val(ctx.v[n], 'V', is_dc)}).")
        tot.text("Eleman akımları da aynı şekilde toplanır:")
        for e in passives:
            if all(e.id in c.element_currents for _, c in ok):
                total_line(f"I_{e.id}", e.id, "i", "A")
        if same_as_main and all(n in ctx.v and _close(
                sum(c.node_voltages.get(n, 0) for _, c in ok), ctx.v[n], 1e-5) for n in nodes):
            tot.check("Katkıların toplamı, tüm kaynaklar birlikteyken bulunan tam çözümle aynı ✓")
    else:
        tot.text("Kaynaklar farklı frekanslarda olduğundan fazörler doğrudan toplanamaz. "
                 "Her frekans bileşeni zaman domenine çevrilip toplanır:")
        fn_by_freq: Dict[float, str] = {}
        for f in freqs:
            sine = any(c.source.element_type in SINE_SOURCES for _, c in ok if c.frequency_key == f)
            fn_by_freq[f] = "sin" if sine else "cos"

        def time_terms(table_kind: str, key: str) -> str:
            parts = []
            for f in freqs:
                z = sum((c.node_voltages if table_kind == "v" else c.element_currents).get(key, 0)
                        for _, c in ok if c.frequency_key == f)
                if abs(z) < 1e-15:
                    continue
                if f == 0:
                    parts.append(num(complex(z).real))
                else:
                    ph = math.degrees(cmath.phase(z))
                    sign = "+" if ph >= 0 else MINUS
                    amp = math.sqrt(2.0) * abs(z) if ctx.is_rms else abs(z)
                    parts.append(f"{num(amp)}·{fn_by_freq[f]}({num(2 * math.pi * f)}t "
                                 f"{sign} {num(abs(ph))}°)")
            return _join_terms(parts) or "0"

        sub_digits = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
        for n in nodes:
            tot.math(f"v{n.translate(sub_digits)}(t) = {time_terms('v', n)} V")
        tot.text("Eleman akımları:")
        for e in passives:
            tot.math(f"i_{e.id}(t) = {time_terms('i', e.id)} A")
        tot.note("Farklı frekanslı bileşenlerin etkin değeri ve gücü ayrı ayrı hesaplanıp "
                 "toplanır (güçler süperpoze edilebilir, fazörler edilemez).")
    sections.append(tot)
    return sections
