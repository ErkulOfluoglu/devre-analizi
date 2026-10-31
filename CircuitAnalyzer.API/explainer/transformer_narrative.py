"""
CircuitAnalyzer API — Transformatör anlatımı (ideal ve kuplajlı)

İdeal:
    Devreyi Tanıyalım → (AC) Empedanslar ve Fazörler → Dönüştürme Oranı → Yansıyan Empedans →
    Primere İndirgenmiş Devre → Primer Gerilimi → Sekonder Değerleri → Güç → Kontrol → Sonuç
Kuplajlı:
    Devreyi Tanıyalım → Empedanslar → Ortak Endüktans → Nokta Kuralı → Çevre Denklemleri →
    Çözüm (Cramer 2×2) → Eleman Gerilim ve Akımları → Güç → Kontrol → Sonuç

Devre bu kalıba girmiyorsa (iki transformatör, sekonderde kaynak, indirgenemeyen yapı, elle
türetme çözücüyle uyuşmuyor) kısa anlatım verilir: tanıtım + çözücü sonuçları + sebep.

Tüm sayılar çözücüden (lcapy) gelir; elle türetme solver.transformer'da çözücüyle
karşılaştırılır, uyuşmazsa yazılmaz. Gerilim sembolü V'dir; kitaplardaki U notu verilir.
"""

import math
from typing import List

from explainer.cramer import cramer2, exact_fmt
from explainer.formatting import MINUS, eng, is_real, num, paren, polar, rect
from explainer.narrative import _Section
from models.request import AnalysisType
from parser.netlist_parser import (
    ALL_SOURCES, CURRENT_SOURCES, DC_SOURCES, SINE_SOURCES, ElementType, transformers,
)
from solver.transformer import (
    TransformerAnalysis, passive_impedance, passive_label, source_phasor, z_text,
)

U_NOTE = "Kitaplarda gerilim U ile de gösterilir (U = V)."
OTHER_METHOD_NOTE = "Bu devrede transformatör var; çözüm Transformatör yöntemiyle anlatılıyor."
FLOATING_NOTE = ("Sekonder toprağa bağlı değil; sekonder gerilimleri kendi alt ucuna göre verilmiştir.")
_UNITS = {ElementType.RESISTOR: "Ω", ElementType.CAPACITOR: "F", ElementType.INDUCTOR: "H"}


def _c(z: complex, unit: str) -> str:
    """Fazör değeri: gerçekse '50 V', değilse '3,033∠−72,34° V'."""
    z = complex(z)
    return eng(z.real, unit) if is_real(z) else polar(z, unit)


def _cn(z: complex) -> str:
    """Denklem içinde birimsiz karmaşık sayı: 40, (30 + j40)."""
    z = complex(z)
    return num(z.real) if is_real(z) else paren(rect(z))


def _zeq(z: complex) -> str:
    """Empedans, denklem içinde: '40 Ω' ya da '(30 + j40) Ω'."""
    z = complex(z)
    return eng(z.real, "Ω") if is_real(z) else f"{paren(rect(z))} Ω"


def build_transformer_sections(ctx, an: TransformerAnalysis, requested_type=None) -> List[_Section]:
    """Transformatör anlatımı. `an` doğrulanamadıysa (an.reason) kısa anlatım üretilir."""
    sections = _intro(ctx, an, requested_type)
    if an.guided:
        sections += _ideal_sections(ctx, an) if an.kind == "ideal" else _coupled_sections(ctx, an)
    else:
        sections += _short_sections(ctx, an)
    return sections


# ═══════════════════════════════════════════════════════
#  ORTAK BÖLÜMLER
# ═══════════════════════════════════════════════════════

def describe_transformer(t) -> str:
    p = t.params
    ends = (f"primer Düğüm {t.node_positive} (p+, nokta) – Düğüm {t.node_negative} (p−), "
            f"sekonder Düğüm {p['s_pos']} (s+, nokta) – Düğüm {p['s_neg']} (s−)")
    if p["kind"] == "IDEAL":
        return (f"{t.id}: ideal transformatör, dönüştürme oranı a = N₂/N₁ = {num(p['a'])}; "
                f"{ends}")
    return (f"{t.id}: kuplajlı transformatör, L₁ = {eng(p['l1'], 'H')}, L₂ = {eng(p['l2'], 'H')}, "
            f"kuplaj katsayısı k = {num(p['k'])}; {ends}")


def _intro(ctx, an: TransformerAnalysis, requested_type) -> List[_Section]:
    s = _Section("Devreyi Tanıyalım")
    if requested_type not in (None, AnalysisType.TRANSFORMER):
        s.note(OTHER_METHOD_NOTE)
        if requested_type == AnalysisType.TRANSIENT:
            s.note("Geçici durum yöntemi transformatörlü devrelerde uygulanamaz.")

    srcs = []
    for e in ctx.sources():
        unit = "A" if e.element_type in CURRENT_SOURCES else "V"
        if e.element_type in DC_SOURCES:
            srcs.append(f"{e.id} = {eng(e.value, unit)} (DC; AC analizde sıfırlanır)")
        elif e.element_type in SINE_SOURCES:
            srcs.append(f"{e.id}: {'etkin değer' if ctx.is_rms else 'genlik (tepe)'} "
                        f"{eng(e.params.get('amplitude', e.value), unit)}, "
                        f"f = {num(e.params.get('frequency', 0))} Hz, faz {num(e.params.get('phase', 0))}°")
        else:
            srcs.append(f"{e.id} = {num(e.params.get('amplitude', e.value))}∠"
                        f"{num(e.params.get('phase', 0))}° {unit} (fazör)")
    if srcs:
        s.text(f"Kaynaklar: {', '.join(srcs)}.")
    s.text("Bu çözümde AC değerler etkin (RMS) olarak gösterilir." if ctx.is_rms
           else "Bu çözümde AC değerler tepe değer olarak gösterilir.")

    passives = [e for e in ctx.elements
                if e.element_type in _UNITS or e.element_type == ElementType.IMPEDANCE]
    if passives:
        texts = []
        for e in passives:
            if e.element_type == ElementType.IMPEDANCE:
                texts.append(f"{e.id} = {rect(e.params.get('impedance', complex(e.value)), 'Ω')}")
            else:
                texts.append(f"{e.id} = {eng(e.value, _UNITS[e.element_type])}")
        s.text(f"Pasif elemanlar: {', '.join(texts)}.")
    for t in transformers(ctx.parsed):
        s.text(describe_transformer(t) + ".")
    if an.kind == "ideal":
        s.text("İdeal transformatör: sargı kaybı, kaçak akı ve mıknatıslanma akımı yoktur; "
               "gerilim ve akımı yalnızca a oranıyla dönüştürür.")
    else:
        s.text("Kuplajlı transformatör: iki bobin ortak bir akıyla bağlıdır; birinin akımı "
               "diğerinde gerilim indükler (karşılıklı endüktans M).")
    if an.floating:
        s.note(FLOATING_NOTE)

    nodes = sorted(ctx.v, key=lambda n: (len(n), n))
    s.text(f"Devrede {len(nodes)} düğüm var: "
           + ", ".join("0 (GND)" if n == "0" else n for n in nodes)
           + (". Toprak düğümü referans alınır: V₀ = 0 V." if "0" in nodes else "."))
    if ctx.omega is not None:
        s.math(f"ω = 2πf = 2π · {num(ctx.frequency)} Hz = {num(ctx.omega)} rad/s")
    s.text("Amaç: primer ve sekonder gerilimlerini (V₁, V₂) ve akımlarını (I₁, I₂) bulmak; "
           "gücü hesaplamak. Gerilimler fazör olarak verilir; V₁ = V(p+) − V(p−), V₂ = V(s+) − V(s−), "
           "I₁ primerin nokta ucundan girer.")
    s.note(U_NOTE)
    return [s]


def power_factor(ctx) -> float:
    """S = V·I* (etkin) ya da ½·V·I* (tepe) çarpanı."""
    return 1.0 if ctx.is_rms else 0.5


def _short_sections(ctx, an: TransformerAnalysis) -> List[_Section]:
    t = an.t
    s = _Section("Çözücü Sonuçları")
    s.note(f"Bu devrede adım adım transformatör anlatımı verilemiyor: {an.reason}. "
           "Aşağıda çözücünün bulduğu sonuçlar gösteriliyor.")
    sym2 = "I₂ (s+ ucundan çıkar)" if an.kind == "ideal" else "I₂ (s+ ucundan girer)"
    s.math(f"V₁ = {_c(an.v1, 'V')}")
    s.math(f"V₂ = {_c(an.v2, 'V')}")
    s.math(f"I₁ (p+ ucundan girer) = {_c(an.i1, 'A')}")
    s.math(f"{sym2} = {_c(an.i2, 'A')}")
    if an.kind == "ideal":
        a = an.a
        s.text(f"İdeal transformatör kuralları: V₂ = a·V₁ ve I₁ = a·I₂ (a = {num(a)}).")
    else:
        p = t.params
        s.text(f"Karşılıklı endüktans M = k·√(L₁L₂) = {num(p['k'])} · √({eng(p['l1'], 'H')} · "
               f"{eng(p['l2'], 'H')}) = {eng(p['m'], 'H')}.")
    f = power_factor(ctx)
    s1 = f * an.v1 * an.i1.conjugate()
    s2 = f * an.v2 * (an.i2.conjugate() if an.kind == "coupled" else -an.i2.conjugate())
    s.math(f"Primer port: S₁ = {'V₁·I₁*' if ctx.is_rms else '½·V₁·I₁*'} = {rect(s1, 'VA')}  →  "
           f"P₁ = {eng(s1.real, 'W')}")
    s.math(f"Sekonder port (içeri giren): S₂ = {rect(s2, 'VA')}  →  P₂ = {eng(s2.real, 'W')}")
    sections = [s]
    r = _Section("Sonuç")
    r.result(f"V₁ = {_c(an.v1, 'V')}, V₂ = {_c(an.v2, 'V')}")
    r.result(f"I₁ = {_c(an.i1, 'A')}, I₂ = {_c(an.i2, 'A')}")
    sections.append(r)
    return sections


# ═══════════════════════════════════════════════════════
#  İDEAL / KUPLAJLI (rehberli anlatım)
# ═══════════════════════════════════════════════════════

def _impedance_section(ctx, an: TransformerAnalysis) -> List[_Section]:
    """Empedanslar ve Fazörler: yalnızca L, C ya da Z elemanı varsa (AC)."""
    if ctx.omega is None:
        return []
    elems = [e for e in ctx.elements
             if e.element_type in (ElementType.CAPACITOR, ElementType.INDUCTOR, ElementType.IMPEDANCE)]
    if not elems:
        return []
    s = _Section("Empedanslar ve Fazörler")
    s.text(f"Reaktif elemanları ω = {num(ctx.omega)} rad/s'deki empedanslarıyla gösteririz:")
    w = num(ctx.omega)
    for e in elems:
        z = passive_impedance(e, ctx.omega)
        if e.element_type == ElementType.CAPACITOR:
            s.math(f"Z_{e.id} = 1/(jωC) = 1/(j · {w} · {eng(e.value, 'F')}) = {rect(z, 'Ω')}")
        elif e.element_type == ElementType.INDUCTOR:
            s.math(f"Z_{e.id} = jωL = j · {w} · {eng(e.value, 'H')} = {rect(z, 'Ω')}")
        else:
            s.math(f"{e.id} = {rect(z, 'Ω')} = {polar(z, 'Ω', scaled=False)}")
    for e in ctx.sources():
        if e.element_type in ALL_SOURCES and e.element_type not in DC_SOURCES:
            unit = "A" if e.element_type in CURRENT_SOURCES else "V"
            vs = source_phasor(e)
            s.math(f"{e.id} = {polar(vs, unit, scaled=False)} = {rect(vs, unit)}")
    s.note("Kondansatörün empedansı −j yönünde (kapasitif), bobininki +j yönündedir (endüktif).")
    return [s]


def _source_power_line(ctx, an: TransformerAnalysis, s: _Section) -> None:
    """Ortak güç satırı: kaynağın verdiği karmaşık güç."""
    f = power_factor(ctx)
    i_src = an.sigma * an.i1            # kaynağın devreye verdiği akım
    s_src = f * an.v_s * i_src.conjugate()
    sym = "V·I*" if ctx.is_rms else "½·V·I*"
    s.text(("Fazörler etkin değer olduğundan" if ctx.is_rms else "Fazörler tepe değer olduğundan")
           + f" karmaşık güç S = {sym} ile bulunur (P = Re(S), Q = Im(S)).")
    s.math(f"Kaynak: S = {sym} = {rect(s_src, 'VA')}  →  P_kaynak = {eng(s_src.real, 'W')}")


def _ideal_sections(ctx, an: TransformerAnalysis) -> List[_Section]:
    t, a = an.t, an.a
    sections: List[_Section] = []
    sections += _impedance_section(ctx, an)

    # ── Dönüştürme Oranı ──
    s = _Section("Dönüştürme Oranı")
    s.text("İdeal transformatörde primer ve sekonder gerilimlerin oranı sarım sayıları oranına eşittir. "
           "Bu oran dönüştürme oranı a'dır:")
    s.math(f"a = N₂/N₁ = {num(a)}")
    s.math("V₂ = a·V₁")
    s.math("I₁ = a·I₂")
    kind = ("alçaltıcı (a < 1)" if a < 1 - 1e-12 else "yükseltici (a > 1)" if a > 1 + 1e-12
            else "yalıtım amaçlı (a = 1)")
    s.text(f"Bu transformatör {kind}. Nokta işaretleri p+ ve s+ uçlarında olduğundan V₁ ve V₂ aynı "
           "fazdadır; I₁ primerin nokta ucundan girer, I₂ sekonderin nokta ucundan çıkar.")
    s.text("Güç korunur: V₂·I₂ = (a·V₁)·(I₁/a) = V₁·I₁.")
    sections.append(s)

    # ── Yansıyan Empedans ──
    s = _Section("Yansıyan Empedans")
    sec_ids = ", ".join(passive_label(e) for e in an.secondary)
    s.text(f"Sekonder uçlarına (Düğüm {t.params['s_pos']} – Düğüm {t.params['s_neg']}) bağlı yük "
           f"({sec_ids}) tek bir empedans olarak görülür; buna Z₂ diyelim.")
    for step in an.z2_steps:
        s.math(step)
    s.math(f"Z₂ = {z_text(an.z2)}")
    s.text("Yük, primer taraftan bakıldığında dönüştürme oranının karesine bölünerek görünür "
           "(yansıyan empedans):")
    s.math("Z₁ = V₁/I₁ = (V₂/a) / (a·I₂) = Z₂ / a²")
    s.math(f"Z₁ = Z₂ / a² = {_zeq(an.z2)} / {num(a)}² = {z_text(an.z1)}")
    s.result(f"Z₁ = {z_text(an.z1)}")
    sections.append(s)

    # ── Primere İndirgenmiş Devre ──
    s = _Section("Primere İndirgenmiş Devre")
    s.text("Yük primere yansıtıldığında transformatör devreden çıkar; geriye kaynak, primerdeki "
           "elemanlar ve Z₁ kalır.")
    for step in an.top_steps:
        s.math(step)
    if an.top_steps:
        s.math(f"Z_top = {z_text(an.z_top)}")
    else:
        s.text("Primerde başka eleman yok: kaynak doğrudan Z₁'e bağlanır.")
        s.math(f"Z_top = Z₁ = {z_text(an.z_top)}")
    sign = "" if an.sigma == 1 else MINUS
    s.math(f"I₁ = {sign}V / Z_top = {sign}{_cn(an.v_s)} V / {_zeq(an.z_top)} = {_c(an.i1, 'A')}")
    s.result(f"I₁ = {_c(an.i1, 'A')}")
    if (abs(an.z_ser) > 1e-12 and an.z_ser.real > 0 and abs(an.z_ser.imag) < 1e-9 * abs(an.z_ser)
            and abs(an.z2.imag) < 1e-9 * abs(an.z2) and an.z2.real > 0):
        a_opt = math.sqrt(an.z2.real / an.z_ser.real)
        s.note("Maksimum güç aktarımı için yük, kaynağın seri direncine uydurulur: "
               "R_kaynak = R_yük/a² → a = √(R_yük/R_kaynak) = "
               f"√({eng(an.z2.real, 'Ω')} / {eng(an.z_ser.real, 'Ω')}) = {num(a_opt)}.")
    sections.append(s)

    # ── Primer Gerilimi ──
    s = _Section("Primer Gerilimi")
    s.text("Primer akım yansıyan empedanstan geçer; primer gerilimi bu empedansın uçlarındaki gerilimdir:")
    s.math(f"V₁ = I₁ · Z₁ = {_cn(an.i1)} A · {_zeq(an.z1)} = {_c(an.v1, 'V')}")
    if abs(an.z_ser) > 1e-12 and an.sigma == 1:
        drop = an.i1 * an.z_ser
        s.math(f"Kaynak gerilimiyle karşılaştıralım: V₁ = V {MINUS} I₁·Z_seri = {_cn(an.v_s)} V {MINUS} "
               f"{_cn(an.i1)} A · {_zeq(an.z_ser)} = {_c(an.v_s - drop, 'V')}")
    s.result(f"V₁ = {_c(an.v1, 'V')}")
    sections.append(s)

    # ── Sekonder Değerleri ──
    s = _Section("Sekonder Değerleri")
    s.text("İdeal transformatör kurallarıyla sekonder gerilimi ve akımı bulunur:")
    s.math(f"V₂ = a · V₁ = {num(a)} · {_cn(an.v1)} V = {_c(an.v2, 'V')}")
    s.math(f"I₂ = I₁ / a = {_cn(an.i1)} A / {num(a)} = {_c(an.i2, 'A')}")
    s.math(f"Yük üzerinden kontrol: I₂ = V₂ / Z₂ = {_cn(an.v2)} V / {_zeq(an.z2)} = {_c(an.v2 / an.z2, 'A')}")
    s.result(f"V₂ = {_c(an.v2, 'V')},  I₂ = {_c(an.i2, 'A')}")
    sections.append(s)

    # ── Güç ──
    s = _Section("Güç")
    _source_power_line(ctx, an, s)
    f = power_factor(ctx)
    s1 = f * an.v1 * an.i1.conjugate()
    s2 = f * an.v2 * an.i2.conjugate()
    sym = "V·I*" if ctx.is_rms else "½·V·I*"
    s.math(f"Primer: S₁ = {sym} = {rect(s1, 'VA')}  →  P₁ = {eng(s1.real, 'W')}")
    s.math(f"Sekonder (yük): S₂ = {sym} = {rect(s2, 'VA')}  →  P₂ = {eng(s2.real, 'W')}")
    s.text("İdeal transformatör güç harcamaz ve depolamaz: P₁ = P₂.")
    if abs(an.z_ser) > 1e-12:
        p_ser = f * abs(an.i1) ** 2 * an.z_ser.real
        s.math(f"Primer seri direnç kaybı: P_seri = {'' if ctx.is_rms else '½·'}|I₁|²·R_seri = "
               f"{eng(p_ser, 'W')};  P_kaynak = P_seri + P₁")
    s.result(f"P₁ = P₂ = {eng(s1.real, 'W')}")
    sections.append(s)

    # ── Kontrol ──
    s = _Section("Kontrol")
    s.check(f"Çözücüde V₁ = {_c(an.v1, 'V')} ve V₂ = {_c(an.v2, 'V')}: elle bulunanlarla aynı, "
            "V₂ = a·V₁ ✓")
    s.check(f"Çözücüde I₁ = {_c(an.i1, 'A')} ve I₂ = {_c(an.i2, 'A')}: elle bulunanlarla aynı, "
            "I₁ = a·I₂ ✓")
    pw = ctx.results.power
    if pw is not None and pw.balance_error < 1e-6 * max(abs(s1), 1e-9):
        s.check("Çözücüde kaynakların verdiği güç, elemanların çektiği güce eşit (güç dengesi) ✓")
    sections.append(s)

    # ── Sonuç ──
    s = _Section("Sonuç")
    s.result(f"a = {num(a)},  Z₂ = {z_text(an.z2)},  Z₁ = {z_text(an.z1)}")
    s.result(f"V₁ = {_c(an.v1, 'V')},  V₂ = {_c(an.v2, 'V')}")
    s.result(f"I₁ = {_c(an.i1, 'A')},  I₂ = {_c(an.i2, 'A')}")
    s.result(f"P₁ = P₂ = {eng(s1.real, 'W')}")
    sections.append(s)
    return sections


def _coupled_sections(ctx, an: TransformerAnalysis) -> List[_Section]:
    t = an.t
    p = t.params
    w = ctx.omega
    l1, l2, k, m = float(p["l1"]), float(p["l2"]), float(p["k"]), float(p["m"])
    jwl1, jwl2, jwm = 1j * w * l1, 1j * w * l2, 1j * w * m
    sections: List[_Section] = []

    # ── Empedanslar ve Fazörler ──
    s = _Section("Empedanslar ve Fazörler")
    s.text(f"Bobinleri ve diğer elemanları ω = {num(w)} rad/s'deki empedanslarıyla gösteririz:")
    ws = num(w)
    s.math(f"jωL₁ = j · {ws} · {eng(l1, 'H')} = {rect(jwl1, 'Ω')}")
    s.math(f"jωL₂ = j · {ws} · {eng(l2, 'H')} = {rect(jwl2, 'Ω')}")
    for e in ctx.elements:
        z = passive_impedance(e, w) if e.element_type in (
            ElementType.CAPACITOR, ElementType.INDUCTOR, ElementType.IMPEDANCE) else None
        if z is None:
            continue
        if e.element_type == ElementType.CAPACITOR:
            s.math(f"Z_{e.id} = 1/(jωC) = 1/(j · {ws} · {eng(e.value, 'F')}) = {rect(z, 'Ω')}")
        elif e.element_type == ElementType.INDUCTOR:
            s.math(f"Z_{e.id} = jωL = j · {ws} · {eng(e.value, 'H')} = {rect(z, 'Ω')}")
        else:
            s.math(f"{e.id} = {rect(z, 'Ω')} = {polar(z, 'Ω', scaled=False)}")
    vs = source_phasor(an.source)
    s.math(f"{an.source.id} = {polar(vs, 'V', scaled=False)} = {rect(vs, 'V')}")
    sections.append(s)

    # ── Ortak Endüktans ──
    s = _Section("Ortak Endüktans")
    s.text("İki bobin ortak akıyla bağlıdır; kuplaj katsayısı k, akının ne kadarının ortak "
           "olduğunu gösterir (0 < k ≤ 1). Ortak (karşılıklı) endüktans:")
    s.math(f"M = k · √(L₁ · L₂) = {num(k)} · √({eng(l1, 'H')} · {eng(l2, 'H')}) = {eng(m, 'H')}")
    s.math(f"X_M = ωM = {ws} rad/s · {eng(m, 'H')} = {eng(w * m, 'Ω')}")
    s.result(f"M = {eng(m, 'H')},  jωM = {rect(jwm, 'Ω')}")
    sections.append(s)

    # ── Nokta Kuralı ──
    s = _Section("Nokta Kuralı")
    s.text("Nokta işaretleri p+ ve s+ uçlarındadır. Her iki akım da nokta ucundan girerken karşılıklı "
           "terimler (jωM·I) pozitif yazılır; bu yüzden I₂ de sekonderin nokta ucundan (s+) GİRER "
           "(idealde olduğu gibi çıkmaz).")
    s.text("Sekonderdeki yüke giden akım bu nedenle −I₂'dir; yük gerilimi V₂ = −Z_yük·I₂ olur. "
           "Sekonder uçlarının yerini değiştirirseniz (s+ ↔ s−) M'nin işareti tersine döner.")
    sections.append(s)

    # ── Çevre Denklemleri ──
    s = _Section("Çevre Denklemleri")
    s.text("Primer ve sekonder için birer çevre (KVL) denklemi yazılır. Önce her çevrenin "
           "transformatör dışındaki empedansı bulunur:")
    if an.z_ser_steps:
        s.text("Primer çevre (kaynak ile primer sargı arası):")
        for step in an.z_ser_steps:
            s.math(step)
    if abs(an.z_ser) > 1e-12:
        s.math(f"Z_seri = {z_text(an.z_ser)}")
    else:
        s.text("Primerde seri eleman yok: Z_seri = 0.")
    if an.z2_steps:
        s.text("Sekonder çevre (yük):")
        for step in an.z2_steps:
            s.math(step)
    s.math(f"Z_yük = {z_text(an.z2)}")

    e_drive = an.sigma * an.v_s
    z11 = an.z_ser + jwl1
    z22 = an.z2 + jwl2
    sign = "" if an.sigma == 1 else MINUS
    s.text("Her bobinin gerilimi kendi akımından (jωL·I) ve diğer bobinin akımından (jωM·I) oluşur:")
    s.math("V₁ = jωL₁·I₁ + jωM·I₂")
    s.math("V₂ = jωM·I₁ + jωL₂·I₂")
    s.text("Primer çevre için kaynak gerilimi seri empedansın ve V₁'in toplamına eşittir; sekonder "
           "çevre için yük gerilimi V₂ = −Z_yük·I₂'dir:")
    s.math(f"{sign}V = (Z_seri + jωL₁)·I₁ + jωM·I₂")
    s.math("0 = jωM·I₁ + (Z_yük + jωL₂)·I₂")
    s.text("Sayılar yerine konunca:")
    s.math(f"{_cn(z11)} · I₁ + {_cn(jwm)} · I₂ = {_cn(e_drive)}")
    s.math(f"{_cn(jwm)} · I₁ + {_cn(z22)} · I₂ = 0")
    sections.append(s)

    # ── Çözüm (Cramer 2×2) ──
    s = _Section("Çözüm")
    s.text("İki bilinmeyenli denklem takımını Cramer kuralıyla çözeriz:")
    A = [[z11, jwm], [jwm, z22]]
    b = [e_drive, 0j]
    fmt = exact_fmt(_cn)
    parts = cramer2(A, b, fmt)
    for _, text, _ in parts:
        s.math(text)
    det, d1, d2 = parts[0][2], parts[1][2], parts[2][2]
    s.math(f"I₁ = Δ₁/Δ = {_cn(d1)} / {_cn(det)} = {_c(an.i1, 'A')}")
    s.math(f"I₂ = Δ₂/Δ = {_cn(d2)} / {_cn(det)} = {_c(an.i2, 'A')}")
    s.result(f"I₁ = {_c(an.i1, 'A')},  I₂ = {_c(an.i2, 'A')}")
    sections.append(s)

    # ── Eleman Gerilim ve Akımları ──
    s = _Section("Eleman Gerilim ve Akımları")
    s.text("Bulunan akımlarla sargı gerilimleri hesaplanır:")
    s.math(f"V₁ = jωL₁·I₁ + jωM·I₂ = {_cn(jwl1)} · {_cn(an.i1)} + {_cn(jwm)} · {_cn(an.i2)} "
           f"= {_c(an.v1, 'V')}")
    s.math(f"V₂ = jωM·I₁ + jωL₂·I₂ = {_cn(jwm)} · {_cn(an.i1)} + {_cn(jwl2)} · {_cn(an.i2)} "
           f"= {_c(an.v2, 'V')}")
    s.math(f"Yük üzerinden kontrol: V₂ = −Z_yük·I₂ = −{_zeq(an.z2)} · {_cn(an.i2)} A "
           f"= {_c(-an.z2 * an.i2, 'V')}")
    s.math(f"Yüke giden akım: −I₂ = {_c(-an.i2, 'A')}")
    if abs(an.z_ser) > 1e-12:
        s.math(f"Primer seri empedans gerilimi: I₁·Z_seri = {_c(an.i1 * an.z_ser, 'V')}")
    s.result(f"V₁ = {_c(an.v1, 'V')},  V₂ = {_c(an.v2, 'V')}")
    sections.append(s)

    # ── Güç ──
    s = _Section("Güç")
    _source_power_line(ctx, an, s)
    f = power_factor(ctx)
    sym = "V·I*" if ctx.is_rms else "½·V·I*"
    s1 = f * an.v1 * an.i1.conjugate()
    s2 = f * an.v2 * an.i2.conjugate()
    p_load = f * abs(an.i2) ** 2 * an.z2.real
    s.math(f"Primer sargı (içeri giren): S₁ = {sym} = {rect(s1, 'VA')}  →  P₁ = {eng(s1.real, 'W')}")
    s.math(f"Sekonder sargı (içeri giren): S₂ = {sym} = {rect(s2, 'VA')}  →  P₂ = {eng(s2.real, 'W')}")
    s.math(f"Yükte harcanan güç: P_yük = {'' if ctx.is_rms else '½·'}|I₂|²·R_yük = {eng(p_load, 'W')}")
    s.text("Sargılar kayıpsız olduğundan primerden giren aktif güç sekondere geçer: P₁ + P₂ = 0, "
           "yani P₁ = P_yük. Sargıların reaktif gücü ise manyetik alanda depolanır.")
    s.result(f"P₁ = {eng(s1.real, 'W')},  P_yük = {eng(p_load, 'W')}")
    sections.append(s)

    # ── Kontrol ──
    s = _Section("Kontrol")
    s.check(f"Çözücüde I₁ = {_c(an.i1, 'A')} ve I₂ = {_c(an.i2, 'A')}: Cramer çözümüyle aynı ✓")
    s.check(f"Çözücüde V₁ = {_c(an.v1, 'V')} ve V₂ = {_c(an.v2, 'V')}: sargı denklemleriyle aynı ✓")
    pw = ctx.results.power
    if pw is not None and pw.balance_error < 1e-6 * max(abs(s1), abs(s2), 1e-9):
        s.check("Çözücüde kaynakların verdiği güç, elemanların çektiği güce eşit (güç dengesi) ✓")
    sections.append(s)

    # ── Sonuç ──
    s = _Section("Sonuç")
    s.result(f"M = {eng(m, 'H')},  X_M = {eng(w * m, 'Ω')}")
    s.result(f"I₁ = {_c(an.i1, 'A')},  I₂ = {_c(an.i2, 'A')}")
    s.result(f"V₁ = {_c(an.v1, 'V')},  V₂ = {_c(an.v2, 'V')}")
    s.result(f"P₁ = {eng(s1.real, 'W')},  P_yük = {eng(p_load, 'W')}")
    sections.append(s)
    return sections
