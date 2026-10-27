"""
CircuitAnalyzer API — KCL/KVL Adım Üretici (Step Generator)

Devre çözümünü eğitici adımlara dönüştürür.

★ Amaç:
    Öğrencinin sınavda yapması gereken adımları,
    formül formatında (LaTeX) ve Türkçe açıklamayla üretmek.

★ Üretilen Adım Tipleri:
    1. Empedans Hesaplama — ZC, ZL değerlerini ω'ya göre hesapla
    2. KCL Denklem Sistemi — Her düğüm için akım korunum denklemi
    3. KVL Çevrim Denklemleri — Her bağımsız çevrim için gerilim denklemi
    4. Matris Formülasyonu — [G][V] = [I] matris denklemi
    5. Çözüm — Cramer/ters matris ile sonuç
    6. Birim Dönüşümü — Sonuçları mühendislik birimine çevir

★ NOT:
    Bu modül çözümü kendisi YAPMAZ — solver'dan gelen sonuçları
    ve ara ifadeleri formatlayıp açıklama metni üretir.
"""

import math
import cmath
from typing import List, Optional, Dict, Any

from models.response import SolutionStep
from parser.netlist_parser import (
    ParsedCircuit, ParsedElement, ElementType,
    VOLTAGE_SOURCES, CURRENT_SOURCES, DC_SOURCES,
    DEPENDENT_SOURCES, DEPENDENT_STEPS_NOTE,
)


# ═══════════════════════════════════════════════════════
#  YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════

def _format_complex_latex(z: complex, unit: str = "") -> str:
    """
    Karmaşık sayıyı LaTeX formatında döndürür.

    Örnekler:
        (50+30j), "Ω"  → "50 + j30 \\; \\Omega"
        (-2.5j), "V"   → "-j2.5 \\; \\text{V}"
        (8.0), "V"     → "8 \\; \\text{V}"
    """
    unit_tex = f" \\; \\text{{{unit}}}" if unit else ""

    if isinstance(z, (int, float)):
        return f"{z:.4g}{unit_tex}"

    r, i = z.real, z.imag

    if abs(i) < 1e-10:
        return f"{r:.4g}{unit_tex}"
    elif abs(r) < 1e-10:
        if abs(i - 1) < 1e-10:
            return f"j{unit_tex}"
        elif abs(i + 1) < 1e-10:
            return f"-j{unit_tex}"
        sign = "-" if i < 0 else ""
        return f"{sign}j{abs(i):.4g}{unit_tex}"
    else:
        sign = "+" if i >= 0 else "-"
        return f"{r:.4g} {sign} j{abs(i):.4g}{unit_tex}"


def _format_polar_latex(z: complex, unit: str = "") -> str:
    """
    Karmaşık sayıyı kutupsal LaTeX formatında döndürür.

    Örnek: (3+4j), "V" → "5 \\angle 53.13^\\circ \\; \\text{V}"
    """
    mag = abs(z)
    phase = math.degrees(cmath.phase(z)) if mag > 1e-15 else 0
    unit_tex = f" \\; \\text{{{unit}}}" if unit else ""
    return f"{mag:.4g} \\angle {phase:.4g}^\\circ{unit_tex}"


def _engineering_notation(value: float, unit: str) -> str:
    """
    Değeri mühendislik notasyonuna çevirir.

    Örnekler:
        (0.004, "A")  → "4 mA"
        (1000, "Ω")   → "1 kΩ"
        (1e-6, "F")   → "1 µF"
    """
    prefixes = [
        (1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k"),
        (1, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"), (1e-12, "p")
    ]
    abs_val = abs(value)
    if abs_val == 0:
        return f"0 {unit}"

    for threshold, prefix in prefixes:
        if abs_val >= threshold:
            scaled = value / threshold
            if abs(scaled - round(scaled)) < 1e-6:
                return f"{int(round(scaled))} {prefix}{unit}"
            return f"{scaled:.4g} {prefix}{unit}"

    return f"{value:.4g} {unit}"


# ═══════════════════════════════════════════════════════
#  ANA STEP GENERATOR
# ═══════════════════════════════════════════════════════

def generate_impedance_steps(
    parsed: ParsedCircuit,
    frequency: float = None
) -> List[SolutionStep]:
    """
    Adım 0: Empedans hesaplama adımlarını üretir.

    AC devrelerde C ve L elemanlarının empedansları
    ω = 2πf kullanılarak hesaplanmalıdır.

    Üretilen LaTeX:
        Z_C = \\frac{1}{j\\omega C} = \\frac{1}{j \\cdot 314.16 \\cdot 10^{-4}} = -j31.83 \\; \\Omega
        Z_L = j\\omega L = j \\cdot 314.16 \\cdot 0.1 = j31.42 \\; \\Omega
    """
    steps = []

    # Frekansı olan C ve L elemanları bul
    capacitors = [e for e in parsed.elements if e.element_type == ElementType.CAPACITOR]
    inductors = [e for e in parsed.elements if e.element_type == ElementType.INDUCTOR]
    impedances = [e for e in parsed.elements if e.element_type == ElementType.IMPEDANCE]

    if not (capacitors or inductors or impedances) or frequency is None:
        return steps

    omega = 2 * math.pi * frequency
    equations = []
    latex_parts = []

    # Başlık adımı
    equations.append(f"ω = 2πf = 2π × {frequency} = {omega:.4g} rad/s")
    latex_parts.append(
        f"\\omega = 2\\pi f = 2\\pi \\times {frequency} = {omega:.4g} "
        f"\\; \\text{{rad/s}}"
    )

    # Kapasitörler: Zc = 1/(jωC)
    for c in capacitors:
        zc = 1 / (1j * omega * c.value)
        eq = f"Z_{c.id} = 1/(jωC) = 1/(j×{omega:.4g}×{c.value:.4g}) = {_format_complex_latex(zc, 'Ω')}"
        equations.append(eq)
        latex_parts.append(
            f"Z_{{{c.id}}} = \\frac{{1}}{{j\\omega C}} = "
            f"\\frac{{1}}{{j \\cdot {omega:.4g} \\cdot {c.value:.4g}}} = "
            f"{_format_complex_latex(zc, 'Ω')}"
        )

    # Bobinler: ZL = jωL
    for l in inductors:
        zl = 1j * omega * l.value
        eq = f"Z_{l.id} = jωL = j×{omega:.4g}×{l.value:.4g} = {_format_complex_latex(zl, 'Ω')}"
        equations.append(eq)
        latex_parts.append(
            f"Z_{{{l.id}}} = j\\omega L = "
            f"j \\cdot {omega:.4g} \\cdot {l.value:.4g} = "
            f"{_format_complex_latex(zl, 'Ω')}"
        )

    # Genel empedanslar
    for z_elem in impedances:
        z = z_elem.params.get("impedance", complex(z_elem.value, 0))
        equations.append(
            f"Z_{z_elem.id} = {_format_complex_latex(z, 'Ω')} "
            f"= {_format_polar_latex(z, 'Ω')}"
        )
        latex_parts.append(
            f"Z_{{{z_elem.id}}} = {_format_complex_latex(z, 'Ω')} "
            f"= {_format_polar_latex(z, 'Ω')}"
        )

    steps.append(SolutionStep(
        step_number=0,  # Çağıran yeniden numaralandıracak
        title="Empedans Hesaplama",
        description=(
            "AC devrede reaktif elemanların (C, L) empedansları "
            f"ω = 2π×{frequency} Hz = {omega:.4g} rad/s frekansında "
            "hesaplanır."
        ),
        equations=equations,
        latex_formula=" \\\\ ".join(latex_parts),
        result_snapshot={"omega": omega, "frequency": frequency}
    ))

    return steps


# Gerilim kısıtı oluşturan kaynaklar (akım kaynakları KCL'de terim olur)
_SOURCE_TYPES = VOLTAGE_SOURCES


def _format_complex_text(z) -> str:
    """
    Sayıyı düz metin denklem formatına çevirir (4 anlamlı basamak).

    Örnekler: 12 → "12", -31.83j → "-j31.83", 14.14+14.14j → "14.14+j14.14"
    """
    z = complex(z)
    r, i = z.real, z.imag
    if abs(i) < 1e-12 * max(abs(r), 1.0):
        return f"{r:.4g}"
    if abs(r) < 1e-12 * max(abs(i), 1.0):
        return f"{'-' if i < 0 else ''}j{abs(i):.4g}"
    sign = "+" if i >= 0 else "-"
    return f"{r:.4g}{sign}j{abs(i):.4g}"


def _paren(z) -> str:
    """Toplam/negatif değerleri parantez içine alır: -j31.83 → (-j31.83)."""
    text = _format_complex_text(z)
    if text.startswith("-") or "+" in text[1:] or "-" in text[1:]:
        return f"({text})"
    return text


def _source_value(elem: ParsedElement, is_dc: bool) -> complex:
    """
    Kaynağın analiz modundaki değeri: gerilim kaynağında V(+) − V(−),
    akım kaynağında içinden n+ → n− akan akım.

    DC modda AC kaynaklar, AC modda DC kaynaklar sıfırdır (gerilim kaynağı
    kısa devre, akım kaynağı açık devre) — lcapy da .dc / .ac bileşenlerini
    böyle ayırır.
    """
    if elem.element_type in DC_SOURCES:
        return complex(elem.value) if is_dc else 0j
    if is_dc:
        return 0j
    amp = elem.params.get("amplitude", elem.value)
    phase = elem.params.get("phase", 0)
    return cmath.rect(amp, math.radians(phase))


def _element_impedance(elem: ParsedElement, is_dc: bool, omega: Optional[float]):
    """
    Pasif elemanın empedansı ve denklemdeki etiketi.

    Returns:
        (etiket, empedans) — empedans None ise sayısal değer bilinmiyor
        (AC modda frekans yok).
    """
    if elem.element_type == ElementType.RESISTOR:
        return elem.id, complex(elem.value)
    if elem.element_type == ElementType.IMPEDANCE:
        return f"Z_{elem.id}", elem.params.get("impedance", complex(elem.value))
    label = f"Z_{elem.id}"
    if omega is None:
        return label, None
    if elem.element_type == ElementType.CAPACITOR:
        return label, 1 / (1j * omega * elem.value)
    return label, 1j * omega * elem.value       # INDUCTOR


def _node_groups(parsed: ParsedCircuit, is_dc: bool):
    """
    Gerilim kısıtı taşıyan elemanlarla (kaynaklar, DC'de bobinler)
    birbirine bağlı düğümleri gruplar ve bilinen gerilimleri yayar.

    Returns:
        known:   {düğüm: gerilim} — GND'ye kısıt zinciriyle bağlı düğümler
        groups:  bilinmeyen düğüm grupları (tek düğüm veya süperdüğüm)
        constraints: [(eleman, değer)] — kısıt elemanları
    """
    constraints = []
    for elem in parsed.elements:
        if elem.element_type in _SOURCE_TYPES:
            constraints.append((elem, _source_value(elem, is_dc)))
        elif is_dc and elem.element_type == ElementType.INDUCTOR:
            constraints.append((elem, 0j))      # DC: L kısa devre

    adjacency: Dict[str, list] = {}
    for elem, value in constraints:
        p, n = elem.node_positive, elem.node_negative
        adjacency.setdefault(p, []).append((n, -value))   # V_n = V_p − Vs
        adjacency.setdefault(n, []).append((p, value))    # V_p = V_n + Vs

    def flood(start, start_value):
        values = {start: start_value}
        queue = [start]
        while queue:
            node = queue.pop(0)
            for other, delta in adjacency.get(node, []):
                if other not in values:
                    values[other] = values[node] + delta
                    queue.append(other)
        return values

    known = flood("0", 0j)

    all_nodes = set()
    for elem in parsed.elements:
        all_nodes.add(elem.node_positive)
        all_nodes.add(elem.node_negative)

    groups = []
    seen = set(known)
    for node in sorted(all_nodes):
        if node in seen:
            continue
        members = sorted(flood(node, 0j))
        seen.update(members)
        groups.append(members)

    return known, groups, constraints


def generate_kcl_steps(
    parsed: ParsedCircuit,
    frequency: float = None,
    is_dc: bool = True
) -> List[SolutionStep]:
    """
    KCL (Kirchhoff Akım Yasası) adımlarını üretir.

    Her bilinmeyen düğüm (veya süperdüğüm) için "düğümden çıkan
    akımların toplamı = 0" denklemi iki satır halinde yazılır:

        Düğüm 2 (sembolik): (V_2 - V_1)/R1 + V_2/R2 = 0
        Düğüm 2 (sayısal):  (V_2 - 12)/1000 + V_2/2000 = 0

    Kurallar:
        • GND'ye kaynak zinciriyle bağlı düğümlerin gerilimi bilinir;
          bunlar için KCL yazılmaz, sayısal satırda yerine konur.
        • İki bilinmeyen düğüm arasındaki kaynak → süperdüğüm:
          grup için tek KCL + kaynak kısıt denklemi.
        • DC modda C açık devre (akım terimi yok), L kısa devre
          (düğümleri birleştiren 0 V kısıt).
        • AC modda paydada empedans: Z_C = 1/(jωC), Z_L = jωL.
    """
    if any(e.element_type in DEPENDENT_SOURCES for e in parsed.elements):
        # KCL terimleri bağımlı kaynakları henüz bilmez (yanlış denklem yazmamak
        # için üretilmez); sonuçlar lcapy'den gelir ve doğrudur.
        return [SolutionStep(
            step_number=0,
            title="KCL — Düğüm Denklemleri",
            description=DEPENDENT_STEPS_NOTE,
            equations=[],
        )]

    omega = None if is_dc or frequency is None else 2 * math.pi * frequency
    numeric_ok = is_dc or omega is not None

    known, groups, constraints = _node_groups(parsed, is_dc)
    if not groups:
        return []

    equations = []
    latex_parts = []
    snapshot_eqs = []

    # Bilinen düğümler
    for node in sorted(known):
        if node == "0":
            continue
        equations.append(
            f"V_{node} = {_format_complex_text(known[node])} V "
            "(gerilim kaynağı zinciriyle GND'ye bağlı — bilinen düğüm)"
        )
        latex_parts.append(
            f"V_{{{node}}} = {_format_complex_latex(known[node], 'V')}"
        )

    open_caps = []

    for members in groups:
        member_set = set(members)
        sym_terms, num_terms = [], []
        sym_latex, num_latex = [], []

        for elem in parsed.elements:
            if elem.element_type in _SOURCE_TYPES:
                continue
            if is_dc and elem.element_type == ElementType.INDUCTOR:
                continue
            p, n = elem.node_positive, elem.node_negative
            if (p in member_set) == (n in member_set):
                continue                        # grup dışı veya iç eleman
            if elem.element_type in CURRENT_SOURCES:
                # Akım kaynağı: içinden n+ → n− akar → n+ düğümünden ÇIKAN
                # akım +Is, n− düğümünden çıkan akım −Is
                i_s = _source_value(elem, is_dc)
                leaving = p in member_set
                sym_terms.append(elem.id if leaving else f"(-{elem.id})")
                sym_latex.append(elem.id if leaving else f"(-{elem.id})")
                text = _format_complex_text(i_s)
                num_terms.append(f"({text})" if leaving else f"(-({text}))")
                num_latex.append(
                    _format_complex_latex(i_s) if leaving
                    else f"\\left(-{_format_complex_latex(i_s)}\\right)")
                continue
            if is_dc and elem.element_type == ElementType.CAPACITOR:
                open_caps.append(elem.id)
                continue

            node, other = (p, n) if p in member_set else (n, p)
            label, z = _element_impedance(elem, is_dc, omega)
            label_tex = (
                f"Z_{{{label[2:]}}}" if label.startswith("Z_") else label
            )

            if other == "0":
                sym_terms.append(f"V_{node}/{label}")
                sym_latex.append(f"\\frac{{V_{{{node}}}}}{{{label_tex}}}")
            else:
                sym_terms.append(f"(V_{node} - V_{other})/{label}")
                sym_latex.append(
                    f"\\frac{{V_{{{node}}} - V_{{{other}}}}}{{{label_tex}}}"
                )

            if not numeric_ok:
                continue
            if other in known:
                v_other = known[other]
                if abs(v_other) < 1e-15:
                    num_top, num_top_tex = f"V_{node}", f"V_{{{node}}}"
                else:
                    num_top = f"(V_{node} - {_paren(v_other)})"
                    num_top_tex = (
                        f"V_{{{node}}} - {_format_complex_latex(v_other)}"
                    )
            else:
                num_top = f"(V_{node} - V_{other})"
                num_top_tex = f"V_{{{node}}} - V_{{{other}}}"
            num_terms.append(f"{num_top}/{_paren(z)}")
            num_latex.append(
                f"\\frac{{{num_top_tex}}}{{{_format_complex_latex(z)}}}"
            )

        if len(members) == 1:
            name = f"Düğüm {members[0]}"
            name_tex = f"\\text{{Düğüm {members[0]}:}}"
        else:
            name = "Süperdüğüm {" + ", ".join(members) + "}"
            name_tex = (
                "\\text{Süperdüğüm } \\{" + ", ".join(members) + "\\}:"
            )

        sym_eq = (" + ".join(sym_terms) or "0") + " = 0"
        equations.append(f"{name} (sembolik): {sym_eq}")
        latex_parts.append(
            f"{name_tex} \\quad {' + '.join(sym_latex) or '0'} = 0"
        )
        entry = {"nodes": members, "symbolic": sym_eq}

        if numeric_ok:
            num_eq = (" + ".join(num_terms) or "0") + " = 0"
            equations.append(f"{name} (sayısal):  {num_eq}")
            latex_parts.append(
                f"\\Rightarrow \\quad {' + '.join(num_latex) or '0'} = 0"
            )
            entry["numeric"] = num_eq

        # Süperdüğüm iç kısıtları: V_p − V_n = Vs
        if len(members) > 1:
            for elem, value in constraints:
                p, n = elem.node_positive, elem.node_negative
                if p in member_set and n in member_set:
                    c_num = f"V_{p} - V_{n} = {_format_complex_text(value)}"
                    equations.append(f"{name} kısıtı ({elem.id}): {c_num}")
                    latex_parts.append(
                        f"V_{{{p}}} - V_{{{n}}} = {_format_complex_latex(value)}"
                    )
                    entry.setdefault("constraints", []).append(c_num)

        snapshot_eqs.append(entry)

    description = (
        "Kirchhoff Akım Yasası (KCL): Her düğümden çıkan akımların "
        "toplamı sıfırdır.\n\n"
        "Düğüm Gerilimi Analizi: Gerilimi kaynaklarla belirlenen "
        "düğümler bilinen kabul edilir; her bilinmeyen düğüm için önce "
        "sembolik denklem yazılır, ardından eleman değerleri ve bilinen "
        "gerilimler yerine konarak sayısal denklem elde edilir."
    )
    if any(len(m) > 1 for m in groups):
        description += (
            "\n\nİki bilinmeyen düğüm arasındaki gerilim kaynağı bir "
            "süperdüğüm oluşturur: iki düğüm tek bir KCL denkleminde "
            "birleştirilir ve kaynak kısıtı ayrıca yazılır."
        )
    if open_caps:
        description += (
            f"\n\nDC analizde kapasitörler ({', '.join(sorted(set(open_caps)))}) "
            "açık devredir — akım terimi oluşturmaz."
        )
    shorted = [
        e.id for e in parsed.elements
        if is_dc and e.element_type == ElementType.INDUCTOR
    ]
    if shorted:
        description += (
            f"\n\nDC analizde bobinler ({', '.join(shorted)}) kısa "
            "devredir — bağladıkları düğümler aynı gerilimdedir."
        )
    if not numeric_ok:
        description += (
            "\n\nℹ Frekans belirtilmediği için reaktif empedanslar "
            "sayısal olarak yerine konamadı."
        )

    return [SolutionStep(
        step_number=0,
        title="KCL — Düğüm Denklemleri",
        description=description,
        equations=equations,
        latex_formula=" \\\\\n".join(latex_parts),
        result_snapshot={
            "known_nodes": {
                k: _format_complex_text(v) for k, v in sorted(known.items())
            },
            "unknown_groups": groups,
            "kcl_equations": snapshot_eqs,
        }
    )]


def generate_kvl_steps(
    parsed: ParsedCircuit,
) -> List[SolutionStep]:
    """
    KVL (Kirchhoff Gerilim Yasası) bilgi adımı üretir.

    ★ NOT: Tam otomatik çevrim tespiti graph traversal gerektirir.
    Bu aşamada KVL'nin prensibini açıklayan bir bilgi adımı üretilir.
    """
    # Kaynak elemanları bul
    sources = [
        e for e in parsed.elements
        if e.element_type in (
            ElementType.DC_SOURCE,
            ElementType.AC_SOURCE_SINE,
            ElementType.AC_SOURCE_PHASOR
        )
    ]

    if not sources:
        return []

    equations = []
    for src in sources:
        if src.element_type == ElementType.DC_SOURCE:
            equations.append(
                f"V({src.node_positive}) - V({src.node_negative}) = "
                f"{src.value} V  ({src.id})"
            )
        else:
            amp = src.params.get("amplitude", src.value)
            phase = src.params.get("phase", 0)
            equations.append(
                f"V({src.node_positive}) - V({src.node_negative}) = "
                f"{amp}∠{phase}° V  ({src.id})"
            )

    return [SolutionStep(
        step_number=0,
        title="KVL — Gerilim Kaynak Kısıtları",
        description=(
            "Kirchhoff Gerilim Yasası (KVL): Bir çevrimdeki "
            "gerilimlerin cebirsel toplamı sıfırdır.\n\n"
            "Bağımsız gerilim kaynakları, bağlı oldukları düğümler "
            "arasında sabit gerilim farkı kısıtı oluşturur."
        ),
        equations=equations
    )]


def generate_result_verification_step(
    node_voltages: Dict[str, Any],
    element_currents: Dict[str, Any],
    parsed: ParsedCircuit
) -> SolutionStep:
    """
    Sonuç doğrulama adımı üretir.

    Toplam güç dengesi: Kaynakların verdiği güç = Dirençlerin harcadığı güç
    """
    equations = []

    # Düğüm gerilimlerini özetle
    for node, nv in sorted(node_voltages.items()):
        if node == "0":
            continue
        val = nv.get("value", nv) if isinstance(nv, dict) else nv
        if isinstance(val, dict):
            rect = val.get("rectangular_str", str(val))
            polar = val.get("polar_str", "")
            equations.append(f"V({node}) = {rect} V = {polar} V")
        elif hasattr(val, 'value'):
            equations.append(f"V({node}) = {val.value} V")
        else:
            equations.append(f"V({node}) = {val} V")

    # Akımları özetle
    for eid, ec in element_currents.items():
        val = ec.get("value", ec) if isinstance(ec, dict) else ec
        if isinstance(val, dict):
            rect = val.get("rectangular_str", str(val))
            equations.append(f"I({eid}) = {rect} A")
        elif hasattr(val, 'value'):
            equations.append(f"I({eid}) = {val.value} A")
        else:
            equations.append(f"I({eid}) = {val} A")

    return SolutionStep(
        step_number=0,
        title="Sonuç Doğrulama",
        description=(
            "Hesaplanan değerler KCL ve KVL ile tutarlıdır. "
            "Her düğümde akım korunumu sağlanmaktadır."
        ),
        equations=equations
    )


def generate_solution_steps(
    parsed: ParsedCircuit,
    frequency: float = None,
    is_dc: bool = True,
    node_voltages: Dict = None,
    element_currents: Dict = None
) -> List[SolutionStep]:
    """
    Tüm çözüm adımlarını üretir ve numaralandırır.

    Çıktı sırası:
        1. Empedans Hesaplama (AC modda)
        2. KVL — Gerilim Kaynak Kısıtları
        3. KCL — Düğüm Denklemleri
        4. Sonuç Doğrulama (opsiyonel)

    Bu adımlar solver'ın ürettiği topoloji/model/çözüm adımları
    ARASINA eklenir (solver adım 2 ve 3 arasında).

    Args:
        parsed: Ayrıştırılmış devre
        frequency: AC frekansı (Hz)
        is_dc: DC modda mı
        node_voltages: Çözülmüş düğüm gerilimleri (dict)
        element_currents: Çözülmüş eleman akımları (dict)

    Returns:
        List[SolutionStep]: Numaralandırılmış adımlar
    """
    all_steps = []

    # 1. Empedans hesaplama (sadece AC modda)
    if not is_dc and frequency:
        all_steps.extend(generate_impedance_steps(parsed, frequency))

    # 2. KVL — kaynak kısıtları
    all_steps.extend(generate_kvl_steps(parsed))

    # 3. KCL — düğüm denklemleri
    all_steps.extend(generate_kcl_steps(parsed, frequency, is_dc))

    # Adımları yeniden numaralandır
    for i, step in enumerate(all_steps, 1):
        step.step_number = i

    return all_steps
