"""
CircuitAnalyzer API — Kalıp Tabanlı Türkçe Anlatım

Çözücünün (lcapy) bulduğu kesin sonuçları, bir öğretmenin tahtada
anlattığı sırayla Türkçe bir anlatıma dönüştürür.

★ Kurallar:
    • Yapay zekâ YOK — her cümle bir kalıptır, sayılar devreden gelir.
    • Anlatımda yapılan her cebirsel türetme (denklem çözümü, Ohm yasası,
      seri/paralel indirgeme) çözücünün sonucuyla karşılaştırılır.
      Uyuşmazsa o türetme gösterilmez, yalnızca çözücünün sonucu verilir.
      Böylece öğrenci asla yanlış bir ara adım görmez.

★ Bölüm sırası (Düğüm Gerilimi yöntemi):
    Devreyi Tanıyalım → (AC) Empedanslar → Bilinen Düğümler →
    Düğüm Denklemleri (KCL) → Denklemlerin Çözümü → Eleman Akımları →
    (Thevenin/Norton) → Güç → Kontrol → (AC) Zaman Domeni → Sonuç

★ Bağımlı kaynaklı devrelerde "Düğüm Denklemleri" öncesine "Kontrol Büyüklüğünü
  Bilinmeyenlerle Yazalım" eklenir ve KCL/çözüm bölümlerini explainer.dependent_nodal
  kurar (kısıt denklemi, süperdüğüm, A·x = b); doğrulanamazsa dürüst yedek anlatım verilir.
"""

import cmath
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from explainer.formatting import (
    MINUS, eng, node_v, num, paren, polar, rect,
)
from explainer.cramer import cramer3, exact_fmt, integer_rows, is_integral_row
from explainer.step_generator import _node_groups, _source_value
from explainer.topology import reduce_port_impedance
from models.request import AnalysisType, TheveninTerminals
from models.response import (
    AnalysisResults, ExplanationBlock, ExplanationSection,
)
from parser.netlist_parser import (
    ALL_SOURCES, CURRENT_SOURCES, DC_SOURCES, SINE_SOURCES,
    DEPENDENT_CURRENT_CONTROLLED, DEPENDENT_CURRENT_OUTPUT, DEPENDENT_NAMES,
    DEPENDENT_SOURCES,
    ElementType, ParsedCircuit, ParsedElement,
)

_SOURCES = ALL_SOURCES
_UNITS = {
    ElementType.RESISTOR: "Ω",
    ElementType.CAPACITOR: "F",
    ElementType.INDUCTOR: "H",
}

# Türetme ile çözücü sonucu arasında izin verilen bağıl fark
_REL_TOL = 1e-6


@dataclass
class PortExtras:
    """
    Bağımlı kaynaklı devrede Thevenin/Norton için çözücünün ek sayıları
    (circuit_solver._solve_port_extras): bağımlı kaynak SIFIRLANMAZ.

    isc:    terminaller kısa devre edilince (+ → −) telden geçen akım
    i_test: bağımsız kaynaklar sıfırlanıp terminallere v_test = 1 (V) test kaynağı
            bağlanınca kaynağın devreye (+ uçtan) verdiği akım
    """
    isc: Optional[complex] = None
    i_test: Optional[complex] = None
    v_test: complex = 1 + 0j


def port_is_dead(vth: complex, isc: Optional[complex], nodes, currents) -> bool:
    """
    Açık devre gerilimi ve kısa devre akımı (bağıl olarak) sıfır mı? Öyleyse
    Rth = Vth/In = 0/0 belirsizdir ve test kaynağı yöntemi gerekir.
    """
    v_scale = max((abs(complex(v)) for v in nodes.values()), default=0.0)
    i_scale = max((abs(complex(i)) for i in currents.values()), default=0.0)
    return (abs(vth) <= 1e-9 * v_scale + 1e-12
            and (isc is None or abs(isc) <= 1e-9 * i_scale + 1e-15))


# ═══════════════════════════════════════════════════════
#  YARDIMCI YAPILAR
# ═══════════════════════════════════════════════════════

class _Section:
    def __init__(self, title: str):
        self.title = title
        self.blocks: List[ExplanationBlock] = []

    def text(self, t: str):
        self.blocks.append(ExplanationBlock(kind="text", text=t))

    def math(self, t: str):
        self.blocks.append(ExplanationBlock(kind="math", text=t))

    def result(self, t: str):
        self.blocks.append(ExplanationBlock(kind="result", text=t))

    def note(self, t: str):
        self.blocks.append(ExplanationBlock(kind="note", text=t))

    def check(self, t: str):
        self.blocks.append(ExplanationBlock(kind="check", text=t))

    def build(self) -> ExplanationSection:
        return ExplanationSection(title=self.title, blocks=self.blocks)


def _close(a: complex, b: complex, rel: float = _REL_TOL) -> bool:
    return abs(complex(a) - complex(b)) <= rel * max(abs(a), abs(b), 1e-9) + 1e-12


@dataclass
class _Ctx:
    parsed: ParsedCircuit
    is_dc: bool
    frequency: Optional[float]
    omega: Optional[float]
    analysis_type: AnalysisType
    terminals: Optional[TheveninTerminals]
    v: Dict[str, complex]            # çözülmüş düğüm gerilimleri (ham)
    i: Dict[str, complex]            # eleman akımları (ham, pasif işaret kuralı)
    results: AnalysisResults
    mesh: Optional[object] = None    # doğrulanmış MeshAnalysis (MESH yönteminde)
    known: Dict[str, complex] = field(default_factory=dict)
    groups: List[List[str]] = field(default_factory=list)
    constraints: list = field(default_factory=list)
    # Bağımlı kaynaklı devrede düğüm denklem sistemi (explainer.dependent_nodal) ya da
    # kurulamadıysa sebebi; Thevenin/Norton için kısa devre/test kaynağı sayıları
    dep_system: Optional[object] = None
    dep_reason: str = ""
    port: Optional["PortExtras"] = None

    # ── Eleman bilgileri ──

    @property
    def elements(self) -> List[ParsedElement]:
        return self.parsed.elements

    def passive(self) -> List[ParsedElement]:
        return [e for e in self.elements
                if e.element_type not in _SOURCES and e.element_type not in DEPENDENT_SOURCES]

    def sources(self) -> List[ParsedElement]:
        """Bağımsız kaynaklar (bağımlı kaynaklar için dependents())."""
        return [e for e in self.elements if e.element_type in _SOURCES]

    def dependents(self) -> List[ParsedElement]:
        return [e for e in self.elements if e.element_type in DEPENDENT_SOURCES]

    @property
    def has_dependent(self) -> bool:
        return any(e.element_type in DEPENDENT_SOURCES for e in self.elements)

    def label(self, e: ParsedElement) -> str:
        """Denklemdeki adı: direnç R1, empedans Z1, C/L için Z_C1."""
        if e.element_type in (ElementType.RESISTOR, ElementType.IMPEDANCE):
            return e.id
        return f"Z_{e.id}"

    def impedance(self, e: ParsedElement) -> Optional[complex]:
        """
        Akım hesabında kullanılan empedans.
        DC: C → None (açık devre), L → 0 (kısa devre).
        """
        t = e.element_type
        if t == ElementType.RESISTOR:
            return complex(e.value)
        if t == ElementType.IMPEDANCE:
            return complex(e.params.get("impedance", complex(e.value)))
        if self.is_dc:
            return None if t == ElementType.CAPACITOR else 0j
        if self.omega is None:
            return None
        if t == ElementType.CAPACITOR:
            return 1 / (1j * self.omega * e.value)
        return 1j * self.omega * e.value

    def conducts(self, e: ParsedElement) -> bool:
        """KCL terimi oluşturan pasif eleman mı? (DC'de C açık, L kısıt)"""
        if e.element_type in _SOURCES or e.element_type in DEPENDENT_SOURCES:
            return False
        if self.is_dc and e.element_type in (ElementType.CAPACITOR, ElementType.INDUCTOR):
            return False
        return self.impedance(e) is not None

    # ── Biçimlendirme ──

    def z_num(self, z: complex) -> str:
        """Denklem içinde empedans: 1000, (−j31.83), (50 + j30)."""
        return num(z.real) if abs(z.imag) < 1e-12 * max(abs(z), 1e-15) else paren(rect(z))

    def v_num(self, vv: complex) -> str:
        """Denklem içinde bilinen gerilim (birimsiz): 12, (14.14 + j14.14)."""
        return num(vv.real) if self.is_dc or abs(complex(vv).imag) < 1e-12 else paren(rect(vv))

    def val(self, z: complex, unit: str) -> str:
        """Sonuç değeri: DC '8 V', AC '3.033∠−72.34° V'."""
        return eng(complex(z).real, unit) if self.is_dc else polar(z, unit)

    def node_value(self, node: str) -> complex:
        return complex(self.v.get(node, 0))

    def element_value_text(self, e: ParsedElement) -> str:
        t = e.element_type
        if t == ElementType.IMPEDANCE:
            return f"{e.id} = {rect(e.params.get('impedance', complex(e.value)), 'Ω')}"
        return f"{e.id} = {eng(e.value, _UNITS[t])}"


# ═══════════════════════════════════════════════════════
#  ANA GİRİŞ
# ═══════════════════════════════════════════════════════

def build_explanation(
    parsed: ParsedCircuit,
    is_dc: bool,
    frequency: Optional[float],
    analysis_type: AnalysisType,
    terminals: Optional[TheveninTerminals],
    raw_nodes: Dict[str, complex],
    raw_currents: Dict[str, complex],
    results: AnalysisResults,
    mesh_analysis=None,
    superposition=None,
    port_extras: Optional[PortExtras] = None,
) -> List[ExplanationSection]:
    """
    Çözümün Türkçe anlatımını üretir. Çözüm başarısızsa boş liste döner.

    analysis_type == MESH ise düğüm denklemleri yerine çevre akımları
    anlatılır (mesh_analysis: solver.mesh.MeshAnalysis). Çevre türetmesi
    çözücüyle doğrulanamazsa sebebi söylenip düğüm yöntemine dönülür.

    Bağımlı kaynaklı devrelerde düğüm denklemleri kontrol büyüklüğü düğüm
    gerilimleriyle yazılarak kurulur (explainer.dependent_nodal); kurulamayan ya da
    çözücüyle doğrulanamayan durumda dürüst yedek anlatım (çözücü sonuçları + sebep)
    verilir. port_extras: Thevenin/Norton'da kısa devre akımı ve test kaynağı sayıları.
    """
    nodes = {str(k): complex(v) for k, v in raw_nodes.items()}
    if len(nodes) <= 1:
        return []

    omega = None if is_dc or not frequency else 2 * math.pi * frequency
    ctx = _Ctx(
        parsed=parsed, is_dc=is_dc, frequency=frequency, omega=omega,
        analysis_type=analysis_type, terminals=terminals,
        v=nodes, i={k: complex(v) for k, v in raw_currents.items()},
        results=results, port=port_extras,
    )
    if ctx.has_dependent and analysis_type == AnalysisType.SUPERPOSITION:
        # Toplam sonuçlar süperpozisyon bölümündedir; bağımlı kaynaklar her adımda aktif
        return _build_dependent_explanation(ctx, superposition)
    ctx.known, ctx.groups, ctx.constraints = _node_groups(parsed, is_dc)

    if ctx.has_dependent:
        # Kontrol büyüklüğü düğüm gerilimleriyle yazılıp A·x = b kurulur ve çözücüyle
        # doğrulanır; olmazsa sebebiyle birlikte yedek anlatım
        from explainer import dependent_nodal as dn
        built = dn.build_system(ctx)
        if isinstance(built, str):
            ctx.dep_reason = built
            method_builders = (_dependent_solution, _currents)
        else:
            ctx.dep_system = built
            method_builders = (_known_nodes, dn.control_section, dn.kcl_section,
                               dn.solve_section, _dependent_check, _currents)
    else:
        method_builders = (_known_nodes, _kcl, _solve, _currents)
    if analysis_type == AnalysisType.MESH:
        # Döngüsel içe aktarmayı önlemek için yerel import
        from explainer.mesh_narrative import build_mesh_sections, verify
        if mesh_analysis is not None and verify(ctx, mesh_analysis):
            ctx.mesh = mesh_analysis
            mesh_sections = build_mesh_sections(ctx, mesh_analysis)
            method_builders = (lambda c: mesh_sections,)
        else:
            reason = (mesh_analysis.reason if mesh_analysis is not None and mesh_analysis.reason
                      else "çevre akımlarından bulunan sonuçlar çözücüyle doğrulanamadı.")
            fallback = _Section("Çevre Akımları Yöntemi")
            fallback.note(f"Bu devrede çevre akımları yöntemi uygulanamadı: {reason} "
                          "Aynı sonuçları veren düğüm gerilimi yöntemiyle anlatıyoruz.")
            method_builders = (lambda c: [fallback],) + method_builders

    if analysis_type == AnalysisType.SUPERPOSITION and superposition:
        # Toplam sonuçlar süperpozisyon bölümündedir; tam çözümün güç/kontrol
        # bölümleri (farklı frekanslarda geçersiz olabilir) eklenmez
        from explainer.superposition_narrative import build_superposition_sections
        sup_sections = build_superposition_sections(ctx, superposition)
        return [s.build() for s in _intro(ctx) + sup_sections if s.blocks]

    sections: List[_Section] = []
    for builder in (
        _intro,
        _impedances,
        *method_builders,
        _thevenin,
        _norton,
        _power,
        _kcl_check,
        _time_domain,
        _summary,
    ):
        sections.extend(builder(ctx))
    return [s.build() for s in sections if s.blocks]


def _build_dependent_explanation(ctx: _Ctx, superposition) -> List[ExplanationSection]:
    """
    Bağımlı kaynaklı devrenin SÜPERPOZİSYON anlatımı: tanıtım + her bağımsız kaynağın
    katkısı (bağımlı kaynaklar sıfırlanmaz, her alt devrede aktif kalır).
    """
    from explainer.superposition_narrative import build_superposition_sections
    if superposition:
        tail = build_superposition_sections(ctx, superposition)
    else:
        s = _Section("Süperpozisyon")
        s.text("Süperpozisyonda yalnızca BAĞIMSIZ kaynaklar tek tek devre dışı bırakılır; "
               "bağımlı kaynaklar her adımda aktif kalır.")
        s.note("Bu devrede etkin (sıfırdan farklı) bağımsız kaynak yok. Bağımlı kaynaklar "
               "tek başına enerji sağlayamaz: tüm gerilim ve akımlar sıfırdır.")
        tail = [s]
    return [s.build() for s in _intro(ctx) + tail if s.blocks]


def _control_text(ctx: _Ctx, e: ParsedElement) -> str:
    """
    Bağımlı kaynağın kontrol büyüklüğü: 'V_R2' / 'I_R2'.
    Ters çevrilmiş kontrolde (V(-R2)) eksi yazılmaz: ekrandaki +/− işaretleri ve
    ok da ters çizilir, V_R2'nin tanımı (_dependent_lines) o yöne göre yapılır.
    """
    p = e.params
    return f"{p['control_kind']}_{p['control_id']}"


def _dependent_lines(ctx: _Ctx) -> List[str]:
    """
    Her bağımlı kaynak için bir satır: adı + neyle kontrol edildiği.
        E1: Gerilim kontrollü gerilim kaynağı, E1 = 3·V_R2 (V_R2 = V₂ − V₀)
    """
    by_id = {e.id: e for e in ctx.elements}
    lines = []
    for e in ctx.dependents():
        gain = e.params["gain"]
        t = e.element_type
        unit = {ElementType.VCCS: "S", ElementType.CCVS: "Ω"}.get(t)
        gain_txt = eng(gain, unit) if unit else num(gain)
        ctrl = by_id.get(e.params["control_id"])
        if ctrl:
            # Ters kontrolde (+) ucu elemanın n− ucudur — ekrandaki işaretlerle aynı
            plus, minus = ctrl.node_positive, ctrl.node_negative
            if e.params["control_sign"] < 0:
                plus, minus = minus, plus
        if e.params["control_kind"] == "V":
            c_desc = (f"V_{ctrl.id} = {node_v(plus)} {MINUS} {node_v(minus)}"
                      if ctrl else "")
        else:
            c_desc = (f"I_{ctrl.id} = {ctrl.id} elemanından Düğüm {plus} → "
                      f"Düğüm {minus} yönünde geçen akım" if ctrl else "")
        out_desc = ""
        if t in DEPENDENT_CURRENT_OUTPUT:
            out_desc = (f"; akımı kaynak içinde Düğüm {e.node_positive} → "
                        f"Düğüm {e.node_negative} yönünde")
        lines.append(
            f"{e.id}: {DEPENDENT_NAMES[t]}, {e.id} = {num(gain)}·{_control_text(ctx, e)}"
            f" (kazanç {gain_txt}; {c_desc}){out_desc}")
    return lines


# ═══════════════════════════════════════════════════════
#  1. DEVREYİ TANIYALIM
# ═══════════════════════════════════════════════════════

def _intro(ctx: _Ctx) -> List[_Section]:
    s = _Section("Devreyi Tanıyalım")

    src_texts = []
    for e in ctx.sources():
        unit = "A" if e.element_type in CURRENT_SOURCES else "V"
        what = ("akım kaynağı, akımı kaynak içinde "
                f"Düğüm {e.node_positive} → Düğüm {e.node_negative} yönünde"
                if e.element_type in CURRENT_SOURCES else "")
        if e.element_type in DC_SOURCES:
            src_texts.append(f"{e.id} = {eng(e.value, unit)} (DC{', ' + what if what else ''})")
        elif e.element_type in SINE_SOURCES:
            src_texts.append(
                f"{e.id}: genlik {eng(e.params.get('amplitude', e.value), unit)}, "
                f"f = {num(e.params.get('frequency', 0))} Hz, "
                f"faz {num(e.params.get('phase', 0))}°" + (f" ({what})" if what else ""))
        else:
            src_texts.append(
                f"{e.id} = {num(e.params.get('amplitude', e.value))}∠"
                f"{num(e.params.get('phase', 0))}° {unit} (fazör{', ' + what if what else ''})")
    passives = [ctx.element_value_text(e) for e in ctx.passive()]

    if src_texts:
        s.text(f"Kaynaklar: {', '.join(src_texts)}.")
    if passives:
        s.text(f"Pasif elemanlar: {', '.join(passives)}.")
    if ctx.has_dependent:
        s.text("Bağımlı (kontrollü) kaynaklar: çıkışları başka bir elemanın gerilimi veya "
               "akımıyla orantılıdır (çıkış = kazanç · kontrol büyüklüğü).")
        for line in _dependent_lines(ctx):
            s.math(f"• {line}")

    nodes = sorted(ctx.v, key=lambda n: (len(n), n))
    s.text(
        f"Devrede {len(nodes)} düğüm var: "
        + ", ".join("0 (GND)" if n == "0" else n for n in nodes)
        + ". Toprak düğümü referans alınır: V₀ = 0 V."
    )

    if not ctx.is_dc and ctx.omega is not None:
        s.math(f"ω = 2πf = 2π · {num(ctx.frequency)} Hz = {num(ctx.omega)} rad/s")
        s.note("Fazör gösteriminde V = Vm∠θ; Vm tepe (maksimum) değerdir, etkin değer değil.")

    if ctx.analysis_type == AnalysisType.THEVENIN and ctx.terminals:
        a, b = ctx.terminals.node_positive, ctx.terminals.node_negative
        s.text(
            f"Amaç: Düğüm {a} (+) ile Düğüm {b} (−) arasındaki Thevenin "
            "eşdeğerini bulmak. Thevenin teoremine göre bu iki uçtan bakıldığında "
            "devre, tek bir gerilim kaynağı (Vth) ve ona seri bir "
            + ("direnç (Rth)" if ctx.is_dc else "empedans (Zth)")
            + " gibi davranır. Vth'yi bulmak için önce düğüm gerilimlerini çözeceğiz."
        )
    elif ctx.analysis_type == AnalysisType.NORTON and ctx.terminals:
        a, b = ctx.terminals.node_positive, ctx.terminals.node_negative
        s.text(
            f"Amaç: Düğüm {a} (+) ile Düğüm {b} (−) arasındaki Norton "
            "eşdeğerini bulmak: bir akım kaynağı (In) ve ona paralel bir "
            + ("direnç (Rn)" if ctx.is_dc else "empedans (Zn)")
            + ". Önce düğüm gerilimlerini çözeceğiz."
        )
    elif ctx.analysis_type == AnalysisType.SUPERPOSITION:
        s.text(
            "Süperpozisyon yöntemiyle çözeceğiz: her kaynağın etkisini, diğer "
            "kaynaklar sıfırlanmışken ayrı ayrı bulup sonuçları toplayacağız."
        )
    elif ctx.has_dependent and not (ctx.analysis_type == AnalysisType.MESH
                                    and ctx.mesh is not None):
        if ctx.dep_system is not None:
            s.text(
                "Düğüm gerilimi yöntemiyle çözeceğiz: önce bağımlı kaynağın kontrol büyüklüğünü "
                "bilinmeyen düğüm gerilimleriyle yazacağız, sonra KCL denklemlerini kurup "
                "bilinmeyen düğüm gerilimlerini bulacağız (bağımlı kaynak denkleme bilinmeyen "
                "bir terim getirir) ve Ohm yasasıyla her elemanın akımını hesaplayacağız."
            )
        else:
            s.text(
                "Düğüm gerilimleri ve eleman akımları çözücü tarafından bulundu; aşağıda "
                "sonuçları Ohm yasası ve KCL ile birlikte inceleyeceğiz."
            )
    elif ctx.analysis_type == AnalysisType.MESH:
        s.text(
            "Çevre akımları yöntemiyle çözeceğiz: her bağımsız çevreye (göze) bir "
            "çevre akımı atayıp KVL denklemlerini yazacağız; eleman akımlarını "
            "çevre akımlarından bulacağız."
        )
    else:
        s.text(
            "Düğüm gerilimi yöntemiyle çözeceğiz: önce bilinmeyen düğüm "
            "gerilimlerini KCL ile bulacağız, sonra Ohm yasasıyla her elemanın "
            "akımını hesaplayacağız."
        )
    return [s]


# ═══════════════════════════════════════════════════════
#  2. EMPEDANSLAR (AC)
# ═══════════════════════════════════════════════════════

def _impedances(ctx: _Ctx) -> List[_Section]:
    if ctx.is_dc or ctx.omega is None:
        return []
    s = _Section("Empedanslar ve Fazörler")
    s.text(f"Her elemanı ω = {num(ctx.omega)} rad/s'deki empedansıyla gösteririz:")
    w = num(ctx.omega)
    for e in ctx.passive():
        z = ctx.impedance(e)
        t = e.element_type
        if t == ElementType.CAPACITOR:
            s.math(f"Z_{e.id} = 1/(jωC) = 1/(j · {w} · {eng(e.value, 'F')}) = {rect(z, 'Ω')}")
        elif t == ElementType.INDUCTOR:
            s.math(f"Z_{e.id} = jωL = j · {w} · {eng(e.value, 'H')} = {rect(z, 'Ω')}")
        elif t == ElementType.RESISTOR:
            s.math(f"{e.id} = {eng(e.value, 'Ω')} (direncin empedansı gerçektir, frekanstan bağımsızdır)")
        else:
            s.math(f"{e.id} = {rect(z, 'Ω')} = {polar(z, 'Ω', scaled=False)}")
    for e in ctx.sources():
        vs = _source_value(e, False)
        unit = "A" if e.element_type in CURRENT_SOURCES else "V"
        if abs(vs) > 0:
            s.math(f"{e.id} = {polar(vs, unit, scaled=False)} = {rect(vs, unit)}")
    s.note("Kondansatörün empedansı −j yönünde (kapasitif), bobininki +j yönündedir (endüktif).")
    return [s]


# ═══════════════════════════════════════════════════════
#  3. BİLİNEN DÜĞÜMLER
# ═══════════════════════════════════════════════════════

def _known_nodes(ctx: _Ctx) -> List[_Section]:
    known = [n for n in ctx.known if n != "0"]
    if not known:
        return []
    s = _Section("Bilinen Düğüm Gerilimleri")

    # Kısıt elemanları üzerinden GND'den yayılarak açıkla (BFS)
    reached = {"0"}
    queue = ["0"]
    while queue:
        node = queue.pop(0)
        for elem, value in ctx.constraints:
            p, n = elem.node_positive, elem.node_negative
            if node not in (p, n):
                continue
            other = n if node == p else p
            if other in reached:
                continue
            reached.add(other)
            queue.append(other)
            vo = ctx.known.get(other, 0)
            if elem.params.get("superposition_zeroed"):
                s.text(f"{elem.id} bu adımda sıfırlandı (kısa devre), bu yüzden uçları "
                       "arasında gerilim farkı yoktur:")
                s.math(f"{node_v(other)} = {node_v(node)} = {ctx.val(vo, 'V')}")
            elif elem.element_type in _SOURCES and abs(value) < 1e-15:
                # Bu analizde sıfırlanan kaynak (AC'de DC kaynak / DC'de AC kaynak)
                kind = "DC" if elem.element_type in DC_SOURCES else "AC"
                mode = "AC" if kind == "DC" else "DC"
                s.text(f"{elem.id} bir {kind} kaynağıdır; {mode} analizde sıfırlanır "
                       "(kısa devre gibi davranır), bu yüzden uçları arasında gerilim farkı yoktur:")
                s.math(f"{node_v(other)} = {node_v(node)} = {ctx.val(vo, 'V')}")
            elif elem.element_type in _SOURCES:
                if node == "0":
                    s.text(
                        f"{elem.id} kaynağı Düğüm {other} ile GND arasına bağlı "
                        f"olduğundan bu düğümün gerilimi doğrudan bilinir:")
                else:
                    s.text(f"{elem.id} kaynağı Düğüm {node} ile Düğüm {other} arasında:")
                sign = "+" if other == p else MINUS
                if node == "0":
                    s.math(f"{node_v(other)} = {ctx.val(vo, 'V')}")
                else:
                    s.math(f"{node_v(other)} = {node_v(node)} {sign} {elem.id} = {ctx.val(vo, 'V')}")
            else:
                s.text(f"{elem.id} DC'de kısa devre olduğundan:")
                s.math(f"{node_v(other)} = {node_v(node)} = {ctx.val(vo, 'V')}")
    return [s]


# ═══════════════════════════════════════════════════════
#  4. DÜĞÜM DENKLEMLERİ (KCL)
# ═══════════════════════════════════════════════════════

def _group_terms(ctx: _Ctx, members: List[str]) -> Tuple[List[str], List[str]]:
    """Bir düğüm/süperdüğüm için (sembolik, sayısal) KCL terimleri."""
    mset = set(members)
    sym, numeric = [], []
    for e in ctx.elements:
        if not ctx.conducts(e):
            continue
        p, n = e.node_positive, e.node_negative
        if (p in mset) == (n in mset):
            continue
        node, other = (p, n) if p in mset else (n, p)
        lbl, z = ctx.label(e), ctx.impedance(e)
        if other == "0":
            sym.append(f"{node_v(node)}/{lbl}")
        else:
            sym.append(f"({node_v(node)} {MINUS} {node_v(other)})/{lbl}")
        if other in ctx.known:
            vo = ctx.known[other]
            top = node_v(node) if abs(vo) < 1e-15 else f"({node_v(node)} {MINUS} {ctx.v_num(vo)})"
        else:
            top = f"({node_v(node)} {MINUS} {node_v(other)})"
        numeric.append(f"{top}/{ctx.z_num(z)}")

    # Akım kaynakları: akımı bilinir. Kaynak içinden n+ → n− aktığı için
    # n+ düğümünden ÇIKAN akım +Is, n− düğümünden çıkan akım −Is'dir.
    for e in ctx.elements:
        if e.element_type not in CURRENT_SOURCES:
            continue
        p, n = e.node_positive, e.node_negative
        if (p in mset) == (n in mset):
            continue
        i_s = _source_value(e, ctx.is_dc)
        if abs(i_s) < 1e-15:
            continue   # Bu analizde sıfırlanmış (açık devre)
        leaving = p in mset
        sym.append(e.id if leaving else f"{MINUS}{e.id}")
        numeric.append(_cnum(i_s if leaving else -i_s))
    return sym, numeric


def _join_terms(terms: List[str]) -> str:
    """'a', '−b', 'c' → 'a − b + c' (eksi ile başlayan terimler çıkarma olur)."""
    out = ""
    for t in terms:
        if not out:
            out = t
        elif t.startswith(MINUS):
            out += f" {MINUS} {t[1:]}"
        else:
            out += f" + {t}"
    return out


def _kcl(ctx: _Ctx) -> List[_Section]:
    if not ctx.groups:
        return []
    s = _Section("Düğüm Denklemleri (KCL)")
    s.text(
        "Kirchhoff Akım Yasası: Bir düğümden çıkan akımların toplamı sıfırdır. "
        "Bir elemandan çıkan akım (V_düğüm − V_komşu)/Z şeklinde yazılır."
    )
    for members in ctx.groups:
        sym, numeric = _group_terms(ctx, members)
        if len(members) == 1:
            title = f"Düğüm {members[0]}"
        else:
            title = "Süperdüğüm {" + ", ".join(members) + "}"
            inner = [elem for elem, _ in ctx.constraints
                     if elem.node_positive in members and elem.node_negative in members]
            if inner and all(elem.element_type == ElementType.INDUCTOR for elem in inner):
                s.text(
                    f"{', '.join(elem.id for elem in inner)} DC'de kısa devredir; Düğüm "
                    f"{' ve '.join(members)} aynı gerilimdedir ve birlikte ele alınır "
                    "(bobinin akımı bilinmediği için tek tek KCL yazılamaz)."
                )
            else:
                s.text(
                    f"Düğüm {' ve '.join(members)} arasında bir gerilim kaynağı var; bu "
                    "düğümler süperdüğüm olarak birlikte ele alınır (kaynağın akımı "
                    "bilinmediği için tek tek KCL yazılamaz)."
                )
        s.math(f"{title}: {_join_terms(sym) or '0'} = 0")
        s.math(f"⇒ {_join_terms(numeric) or '0'} = 0")
        if len(members) > 1:
            for elem, value in ctx.constraints:
                p, n = elem.node_positive, elem.node_negative
                if p in members and n in members:
                    s.math(f"Kısıt ({elem.id}): {node_v(p)} {MINUS} {node_v(n)} = {ctx.v_num(value)}")

    isrc = [e.id for e in ctx.elements
            if e.element_type in CURRENT_SOURCES and abs(_source_value(e, ctx.is_dc)) > 1e-15]
    if isrc:
        s.note(f"Akım kaynaklarının ({', '.join(isrc)}) akımı bellidir: kaynak akımı "
               "düğümden dışarı çıkıyorsa +, düğüme giriyorsa − işaretiyle yazılır.")
    caps = [e.id for e in ctx.elements if ctx.is_dc and e.element_type == ElementType.CAPACITOR]
    if caps:
        s.note(f"DC analizde kondansatörler ({', '.join(caps)}) açık devredir, akım terimi oluşturmaz.")
    return [s]


# ═══════════════════════════════════════════════════════
#  5. DENKLEMLERİN ÇÖZÜMÜ
# ═══════════════════════════════════════════════════════

def _nodal_system(ctx: _Ctx):
    """
    Tüm bilinmeyenler tek düğümse Y·V = I sistemini kurar.
    Returns (bilinmeyenler, A, b, terim bilgileri) veya None (süperdüğüm varsa).
    """
    if not ctx.groups or any(len(g) != 1 for g in ctx.groups):
        return None
    unknown = [g[0] for g in ctx.groups]
    idx = {n: k for k, n in enumerate(unknown)}
    size = len(unknown)
    A = np.zeros((size, size), dtype=complex)
    b = np.zeros(size, dtype=complex)
    # Tek bilinmeyenli anlatım için terimler
    coef_sym = [[] for _ in unknown]
    coef_num = [[] for _ in unknown]
    rhs_sym = [[] for _ in unknown]
    rhs_num = [[] for _ in unknown]

    for e in ctx.elements:
        if not ctx.conducts(e):
            continue
        z = ctx.impedance(e)
        y = 1 / z
        lbl = ctx.label(e)
        for node, other in ((e.node_positive, e.node_negative), (e.node_negative, e.node_positive)):
            if node not in idx:
                continue
            k = idx[node]
            A[k, k] += y
            coef_sym[k].append(f"1/{lbl}")
            coef_num[k].append(f"1/{ctx.z_num(z)}")
            if other in idx:
                A[k, idx[other]] -= y
            elif other in ctx.known:
                vo = ctx.known[other]
                b[k] += vo * y
                if abs(vo) > 1e-15:
                    rhs_sym[k].append(f"{node_v(other)}/{lbl}")
                    rhs_num[k].append(f"{ctx.v_num(vo)}/{ctx.z_num(z)}")

    # Akım kaynakları sağ tarafa geçer: n+'dan çıkan Is → sağda −Is,
    # n−'ye giren Is → sağda +Is
    for e in ctx.elements:
        if e.element_type not in CURRENT_SOURCES:
            continue
        i_s = _source_value(e, ctx.is_dc)
        if abs(i_s) < 1e-15:
            continue
        for node, sign in ((e.node_positive, -1), (e.node_negative, +1)):
            if node not in idx:
                continue
            k = idx[node]
            b[k] += sign * i_s
            rhs_sym[k].append(e.id if sign > 0 else f"{MINUS}{e.id}")
            rhs_num[k].append(_cnum(sign * i_s))
    return unknown, A, b, (coef_sym, coef_num, rhs_sym, rhs_num)


def _scale_for(values) -> Tuple[float, str]:
    """Katsayıları okunur yapan 1000'in kuvveti: S → mS ise (1e3, 'm')."""
    mags = [abs(x) for x in values if abs(x) > 1e-15]
    if not mags:
        return 1.0, ""
    m = max(mags)
    for scale, prefix in ((1e-3, "k"), (1.0, ""), (1e3, "m"), (1e6, "µ"), (1e9, "n")):
        if 1 <= m * scale < 1000 or (scale == 1e9):
            return scale, prefix
    return 1.0, ""


def _is_real(z: complex) -> bool:
    z = complex(z)
    return abs(z.imag) < 1e-12 * max(abs(z), 1e-15)


def _cnum(z: complex) -> str:
    z = complex(z)
    return num(z.real) if _is_real(z) else paren(rect(z))


def _pnum(z: complex) -> str:
    """Çarpım içinde sayı: negatif gerçek sayılar da parantezli: (−10)."""
    t = _cnum(z)
    return f"({t})" if t.startswith(MINUS) else t


def _linear_term(a: complex, var: str, first: bool) -> str:
    """Doğrusal denklem terimi: '2.5·V₂', '− V₃', '+ (0.01 + j0.03)·V₂'."""
    a = complex(a)
    if _is_real(a):
        mag = abs(a.real)
        coef = "" if abs(mag - 1) < 1e-12 else f"{num(mag)}·"
        if a.real < 0:
            return f"{MINUS}{coef}{var}" if first else f"{MINUS} {coef}{var}"
        return f"{coef}{var}" if first else f"+ {coef}{var}"
    return f"{_cnum(a)}·{var}" if first else f"+ {_cnum(a)}·{var}"


def _equation_text(coeffs, rhs, names: List[str], fmt) -> str:
    """'−3·V₂ + 5·V₃ = 0': katsayılar fmt ile (tam sayılar yuvarlanmadan) yazılır."""
    parts: List[str] = []
    for a, var in zip(coeffs, names):
        a = complex(a)
        if abs(a) < 1e-15:
            continue
        mag = fmt(abs(a.real))
        coef = "" if mag == "1" else f"{mag}·"
        if a.real < 0:
            parts.append(f"{MINUS}{coef}{var}" if not parts else f"{MINUS} {coef}{var}")
        else:
            parts.append(f"{coef}{var}" if not parts else f"+ {coef}{var}")
    return f"{' '.join(parts) or '0'} = {fmt(rhs)}"


def _integer_step(s: _Section, labels: List[str], names: List[str], A2, b2, mult) -> None:
    """
    'Kesirlerden Kurtulalım' adımı: yalnızca çarpılan satırlar, ders kitabı biçiminde
    ('Düğüm 3 denklemini 12 ile çarpalım:  −3·V₂ + 5·V₃ − 2·V₄ = 0').
    """
    fmt = exact_fmt(_cnum)
    s.text("Kesirlerden Kurtulalım: katsayıları tam sayı yapmak için aşağıdaki denklemleri "
           "uygun bir sayıyla çarpalım (iki taraf birden çarpıldığı için çözüm değişmez); "
           "böylece Δ değerlerini tam sayılarla hesaplayabiliriz:")
    for r, m in enumerate(mult):
        if m > 1:
            s.math(f"{labels[r]} denklemini {m} ile çarpalım:  "
                   f"{_equation_text(A2[r], b2[r], names, fmt)}")


def _system_blocks(ctx: _Ctx, s: _Section, unknown: List[str], A, b, x,
                   kcl_mask: Optional[List[bool]] = None,
                   row_labels: Optional[List[str]] = None) -> None:
    """
    A·x = b sistemini düzenlenmiş denklemler olarak yazar ve çözer:
    1 bilinmeyen → bölme, 2 → Cramer, 3 → Cramer (Sarrus), >3 → Gauss.

    kcl_mask[r] = r. denklem KCL mi (katsayılar S, sağ taraf A cinsinden; mS/mA ölçeği
    yalnız bunlara uygulanır) yoksa gerilim kısıtı mı (volt cinsinden, ölçeksiz).
    """
    size = len(unknown)
    mask = kcl_mask if kcl_mask is not None else [True] * size
    all_kcl = all(mask)
    kcl_rows = [r for r in range(size) if mask[r]]
    labels = row_labels or [f"{r + 1}. denklem" for r in range(size)]
    int_plan = None     # (A2, b2, çarpanlar): kesirlerden kurtulmuş sistem
    if ctx.is_dc and size in (2, 3):
        # Önce ham birimlerde (S, A) dene: 5/12 S → ×12 ders kitabındaki gibi olur.
        # Her KCL satırı çarpılabiliyor (veya zaten tam sayı) ise mS/mA ölçeği gereksizdir.
        A2, b2, mult = integer_rows(A, b)
        if (any(mult[r] > 1 for r in kcl_rows)
                and all(mult[r] > 1 or is_integral_row(A[r], b[r]) for r in kcl_rows)):
            int_plan = (A2, b2, mult)
            scale, prefix = 1.0, ""
    if int_plan is None:
        scale, prefix = _scale_for([A[r, j] for r in kcl_rows for j in range(size)]
                                   + [b[r] for r in kcl_rows])
    As, bs = A.copy(), b.copy()
    for r in kcl_rows:
        As[r, :] = A[r, :] * scale
        bs[r] = b[r] * scale
    if int_plan is None and ctx.is_dc and size in (2, 3):
        # Görünen (ölçeklenmiş) sayılarla dene: ör. 2.5 mS · V₂ gibi satırlar
        A2, b2, mult = integer_rows(As, bs)
        if any(m > 1 for m in mult):
            int_plan = (A2, b2, mult)
    Vs = [node_v(n) for n in unknown]
    if all_kcl:
        s.text(
            "Denklemleri düzenleyip bilinmeyenlerin katsayılarını toplayalım "
            f"(katsayılar {prefix}S, sağ taraf {prefix}A cinsinden):")
    else:
        s.text(
            "Denklemleri düzenleyip bilinmeyenleri sol tarafta, bilinen sayıları sağ tarafta "
            f"toplayalım (KCL denklemlerinde katsayılar {prefix}S, sağ taraf {prefix}A "
            "cinsindendir; kısıt denklemleri volt cinsindendir):")
    for k in range(size):
        terms_txt = []
        for j in range(size):
            a = As[k, j]
            if abs(a) < 1e-15:
                continue
            terms_txt.append(_linear_term(a, Vs[j], first=not terms_txt))
        s.math(f"{' '.join(terms_txt)} = {_cnum(bs[k])}")

    if int_plan is not None:
        A2, b2, mult = int_plan
        _integer_step(s, labels, Vs, A2, b2, mult)
        As, bs = A2, b2
    cn = exact_fmt(_cnum)

    def P(z) -> str:
        t = cn(z)
        return f"({t})" if t.startswith(MINUS) else t

    if size == 1:
        s.result(f"{Vs[0]} = {_cnum(bs[0])} / {_pnum(As[0, 0])} = {ctx.val(x[0], 'V')}")
    elif size == 2:
        a11, a12, a21, a22 = As[0, 0], As[0, 1], As[1, 0], As[1, 1]
        b1, b2 = bs
        det = a11 * a22 - a12 * a21
        d1 = b1 * a22 - a12 * b2
        d2 = a11 * b2 - b1 * a21
        s.text("İki bilinmeyenli sistemi Cramer kuralıyla çözelim:")
        s.math(f"Δ = a₁₁·a₂₂ {MINUS} a₁₂·a₂₁ = {P(a11)}·{P(a22)} {MINUS} "
               f"{P(a12)}·{P(a21)} = {cn(det)}")
        s.math(f"Δ₁ = b₁·a₂₂ {MINUS} a₁₂·b₂ = {P(b1)}·{P(a22)} {MINUS} "
               f"{P(a12)}·{P(b2)} = {cn(d1)}")
        s.math(f"Δ₂ = a₁₁·b₂ {MINUS} b₁·a₂₁ = {P(a11)}·{P(b2)} {MINUS} "
               f"{P(b1)}·{P(a21)} = {cn(d2)}")
        s.result(f"{Vs[0]} = Δ₁/Δ = {cn(d1)} / {cn(det)} = {ctx.val(x[0], 'V')}")
        s.result(f"{Vs[1]} = Δ₂/Δ = {cn(d2)} / {cn(det)} = {ctx.val(x[1], 'V')}")
    elif size == 3:
        s.text("Üç bilinmeyenli sistemi Cramer kuralıyla çözelim. Determinantları Sarrus "
               "yöntemiyle hesaplayalım: ilk iki sütun sağa tekrar yazılır, soldan sağa inen "
               "köşegenlerin çarpımları toplanır, sağdan sola inenlerinkiler çıkarılır. "
               "Δₖ için k. sütunun yerine sağ taraf yazılır.")
        dets = cramer3(As, bs, cn)
        for _, text, _ in dets:
            s.math(text)
        det = dets[0][2]
        for k in range(3):
            symbol, _, dk = dets[k + 1]
            s.result(f"{Vs[k]} = {symbol}/Δ = {cn(dk)} / {cn(det)} = {ctx.val(x[k], 'V')}")
    else:
        s.text(
            f"{size} bilinmeyenli bu sistem Gauss eliminasyonu (veya "
            "matris tersi) ile çözülünce:")
        for k, n in enumerate(unknown):
            s.result(f"{node_v(n)} = {ctx.val(x[k], 'V')}")


def _solve(ctx: _Ctx) -> List[_Section]:
    if not ctx.groups:
        return []
    s = _Section("Denklemlerin Çözümü")
    unknown_all = [n for g in ctx.groups for n in g]
    system = _nodal_system(ctx)

    solved_ok = False
    if system is not None:
        unknown, A, b, terms = system
        try:
            x = np.linalg.solve(A, b)
            solved_ok = all(_close(x[k], ctx.node_value(n)) for k, n in enumerate(unknown))
        except np.linalg.LinAlgError:
            solved_ok = False

    if solved_ok and len(unknown) == 1:
        n = unknown[0]
        coef_sym, coef_num, rhs_sym, rhs_num = (t[0] for t in terms)
        y, i_ = A[0, 0], b[0]
        V = node_v(n)
        s.text(f"{V} içeren terimleri bir tarafta, bilinen değerleri diğer tarafta toplayalım:")
        s.math(f"{V} · ({' + '.join(coef_sym)}) = {_join_terms(rhs_sym) or '0'}")
        s.math(f"{V} · ({' + '.join(coef_num)}) = {_join_terms(rhs_num) or '0'}")
        if ctx.is_dc:
            s.math(f"{V} · {eng(y.real, 'S')} = {eng(i_.real, 'A')}")
            s.result(f"{V} = {eng(i_.real, 'A')} / {eng(y.real, 'S')} = {ctx.val(x[0], 'V')}")
        else:
            s.math(f"{V} · ({rect(y, 'S')}) = {rect(i_, 'A')}")
            s.result(f"{V} = ({rect(i_, 'A')}) / ({rect(y, 'S')}) = {polar(x[0], 'V')}  (= {rect(x[0], 'V')})")

    elif solved_ok and len(unknown) >= 2:
        _system_blocks(ctx, s, unknown, A, b, x,
                       row_labels=[f"Düğüm {n}" for n in unknown])

    else:
        s.text("Denklemler (ve varsa kaynak kısıtları) birlikte çözülünce:")
        for n in unknown_all:
            s.result(f"{node_v(n)} = {ctx.val(ctx.node_value(n), 'V')}")

    if not ctx.is_dc:
        for n in unknown_all:
            z = ctx.node_value(n)
            s.note(f"{node_v(n)} = {polar(z, 'V')} = {rect(z, 'V')} (kutupsal ↔ dikdörtgensel)")
    return [s]


# ═══════════════════════════════════════════════════════
#  6. ELEMAN AKIMLARI
# ═══════════════════════════════════════════════════════

def _flow_text(p: str, n: str) -> str:
    return f"Düğüm {p} → Düğüm {n}"


def _currents(ctx: _Ctx) -> List[_Section]:
    s = _Section("Eleman Akımları (Ohm Yasası)")
    s.text("Her elemanın akımı, uçlarındaki gerilim farkının empedansına bölümüdür: I = (V₊ − V₋)/Z.")

    for e in ctx.passive():
        if e.id not in ctx.i:
            continue
        p, n = e.node_positive, e.node_negative
        cur = ctx.i[e.id]
        t = e.element_type
        lbl = ctx.label(e)
        name = f"I_{e.id}"

        if ctx.is_dc and t == ElementType.CAPACITOR:
            s.math(f"{name} = 0 (DC'de kondansatör açık devredir)")
            continue
        if ctx.is_dc and t == ElementType.INDUCTOR:
            s.math(f"{name} = {eng(abs(cur.real), 'A')} (DC'de bobin kısa devredir; "
                   f"akımı bağlı olduğu koldan gelir, {_flow_text(*((p, n) if cur.real >= 0 else (n, p)))})")
            continue

        z = ctx.impedance(e)
        vp, vn = ctx.node_value(p), ctx.node_value(n)
        derived = (vp - vn) / z
        if not _close(derived, cur, 1e-5):
            # Tutarsızlık — türetmeyi göstermeden çözücü değerini ver
            s.math(f"{name} = {ctx.val(cur, 'A')}")
            continue

        diff_sym = node_v(p) if n == "0" else f"({node_v(p)} {MINUS} {node_v(n)})"
        if ctx.is_dc:
            diff_num = (eng(vp.real, 'V') if n == "0"
                        else f"({eng(vp.real, 'V')} {MINUS} {paren(eng(vn.real, 'V'))})")
            line = f"{name} = {diff_sym}/{lbl} = {diff_num} / {eng(z.real, 'Ω')} = {eng(cur.real, 'A')}"
            if cur.real >= 0:
                s.math(f"{line}  ({_flow_text(p, n)})")
            else:
                s.math(line)
                s.note(f"Eksi işaret, akımın ters yönde aktığını gösterir: "
                       f"{eng(-cur.real, 'A')}, {_flow_text(n, p)}.")
        else:
            vd = vp - vn
            s.math(f"{name} = {diff_sym}/{lbl} = {polar(vd, 'V')} / {polar(z, 'Ω')} = {polar(cur, 'A')}")

    for e in ctx.sources():
        if e.id not in ctx.i:
            continue
        cur = ctx.i[e.id]
        p, n = e.node_positive, e.node_negative
        if e.element_type in CURRENT_SOURCES:
            # Akımı bilinir; bilinmeyen uçlarındaki gerilimdir
            vd = ctx.node_value(p) - ctx.node_value(n)
            s.math(f"{e.id} akım kaynağı: I = {ctx.val(cur, 'A')} (kaynak içinde "
                   f"{_flow_text(p, n)}); uçlarındaki gerilim "
                   f"{node_v(p)} {MINUS} {node_v(n)} = {ctx.val(vd, 'V')}")
            continue
        if ctx.is_dc:
            if abs(cur.real) < 1e-15:
                s.math(f"I_{e.id} = 0 (kaynaktan akım çekilmiyor)")
            elif cur.real < 0:
                s.math(f"{e.id} kaynağı devreye {eng(-cur.real, 'A')} verir "
                       f"(kaynak içinde {_flow_text(n, p)}, + ucundan dışarı)")
            else:
                s.math(f"{e.id} kaynağından {eng(cur.real, 'A')} akım içeri girer "
                       f"({_flow_text(p, n)}) — bu kaynak güç çekiyor")
        else:
            s.math(f"{e.id} kaynağının verdiği akım: {polar(-cur, 'A')} "
                   f"(kaynak içinde {_flow_text(n, p)} yönü referans)")
    for e in ctx.dependents():
        if e.id not in ctx.i:
            continue
        cur = ctx.i[e.id]
        p, n = e.node_positive, e.node_negative
        vd = ctx.node_value(p) - ctx.node_value(n)
        if e.element_type in DEPENDENT_CURRENT_OUTPUT:
            s.math(f"{e.id} bağımlı akım kaynağı: I = {ctx.val(cur, 'A')} (kaynak içinde "
                   f"{_flow_text(p, n)}); uçlarındaki gerilim "
                   f"{node_v(p)} {MINUS} {node_v(n)} = {ctx.val(vd, 'V')}")
        elif not ctx.is_dc:
            s.math(f"{e.id} kaynağının verdiği akım: {polar(-cur, 'A')} "
                   f"(kaynak içinde {_flow_text(n, p)} yönü referans)")
        elif abs(cur.real) < 1e-15:
            s.math(f"I_{e.id} = 0 ({e.id} bağımlı kaynağından akım çekilmiyor)")
        elif cur.real < 0:
            s.math(f"{e.id} bağımlı kaynağı devreye {eng(-cur.real, 'A')} verir "
                   f"(kaynak içinde {_flow_text(n, p)}, + ucundan dışarı)")
        else:
            s.math(f"{e.id} bağımlı kaynağından {eng(cur.real, 'A')} akım içeri girer "
                   f"({_flow_text(p, n)}) — bu kaynak güç çekiyor")
    if any(e.id in ctx.i and e.element_type not in CURRENT_SOURCES for e in ctx.sources()) or any(
            e.id in ctx.i and e.element_type not in DEPENDENT_CURRENT_OUTPUT for e in ctx.dependents()):
        s.note("Gerilim kaynağının akımı, kaynağa bağlı elemanların akımlarından KCL ile bulunur.")
    return [s] if len(s.blocks) > 1 else []


# ═══════════════════════════════════════════════════════
#  6b. BAĞIMLI KAYNAKLI DEVRE: ÇÖZÜCÜ SONUCU VE KONTROL
# ═══════════════════════════════════════════════════════

def _dependent_solution(ctx: _Ctx) -> List[_Section]:
    """
    YEDEK anlatım: düğüm denklemleri adım adım kurulamadığında (ya da çözücüyle
    doğrulanamadığında) çözücünün düğüm gerilimleri + sebep notu + kontrol.
    """
    s = _Section("Düğüm Gerilimleri (Çözücü Sonucu)")
    if ctx.dep_reason:
        s.note(f"Bu devrede düğüm denklemleri adım adım gösterilemiyor: {ctx.dep_reason} "
               "Aşağıdaki sonuçlar çözücüden alınmıştır ve doğrudur.")
    s.text("Bağımlı kaynağın çıkışı devredeki bir gerilime/akıma bağlı olduğundan denklemler "
           "birlikte çözülür; çözücünün bulduğu düğüm gerilimleri:")
    for n in sorted((n for n in ctx.v if n != "0"), key=lambda n: (len(n), n)):
        s.result(f"{node_v(n)} = {ctx.val(ctx.node_value(n), 'V')}")
    return [s] + _dependent_check(ctx)


def _dependent_check(ctx: _Ctx) -> List[_Section]:
    """Bulunan değerlerle her bağımlı kaynağın çıkışını kontrol büyüklüğünden yeniden hesaplar."""
    by_id = {e.id: e for e in ctx.elements}
    chk = _Section("Bağımlı Kaynakların Kontrolü")
    chk.text("Bulunan değerlerle her bağımlı kaynağın çıkışı, kontrol büyüklüğünden yeniden hesaplanır:")
    for e in ctx.dependents():
        p = e.params
        ctrl = by_id.get(p["control_id"])
        if ctrl is None:
            continue
        if p["control_kind"] == "V":
            cv, cu = ctx.node_value(ctrl.node_positive) - ctx.node_value(ctrl.node_negative), "V"
        elif ctrl.id in ctx.i:
            cv, cu = ctx.i[ctrl.id], "A"
        else:
            continue
        cv = cv * p["control_sign"]
        out = p["gain"] * cv
        if e.element_type in DEPENDENT_CURRENT_OUTPUT:
            actual, ou = ctx.i.get(e.id), "A"
        else:
            actual, ou = ctx.node_value(e.node_positive) - ctx.node_value(e.node_negative), "V"
        if actual is None or not _close(out, actual, 1e-5):
            continue   # tutarsızsa yanlış bir türetme göstermeyiz
        chk.math(f"{e.id} = {num(p['gain'])}·{_control_text(ctx, e)} = {num(p['gain'])} · "
                 f"{paren(ctx.val(cv, cu))} = {ctx.val(out, ou)}")
    if len(chk.blocks) > 1:
        chk.check("Bağımlı kaynak çıkışları, kontrol büyüklükleriyle tutarlı ✓")
        return [chk]
    return []


# ═══════════════════════════════════════════════════════
#  7. THEVENIN / NORTON
# ═══════════════════════════════════════════════════════

def _port(ctx: _Ctx):
    if not ctx.terminals:
        return None
    return ctx.terminals.node_positive, ctx.terminals.node_negative


def _imp_text(ctx: _Ctx, z: complex) -> str:
    return eng(z.real, 'Ω') if ctx.is_dc else rect(z, 'Ω')


def _dependent_rth(ctx: _Ctx, s: _Section, symbol: str, expected: complex) -> bool:
    """
    Bağımlı kaynaklı devrede eşdeğer direnç (ders kitabı yöntemi): bağımlı kaynak
    SIFIRLANMAZ; Rth = Vth / In (In gerçekten kısa devre edilerek bulunmuş), bağımsız
    kaynak yoksa (Vth = In = 0) 1 V'luk test kaynağıyla Rth = V_test / I_test.
    Sayılar çözücünün Rth'siyle karşılaşmadan yazılmaz; uyuşmazsa False döner.
    """
    ex = ctx.port
    if ex is None:
        return False
    a, b = _port(ctx)
    vth = ctx.node_value(a) - ctx.node_value(b)
    dead = port_is_dead(vth, ex.isc, ctx.v, ctx.i)

    if not dead:
        if ex.isc is None or abs(ex.isc) <= 1e-15:
            return False
        if not _close(vth / ex.isc, expected, 1e-4):
            return False
        s.text(
            "Devrede bağımlı kaynak var. Bağımlı kaynak SIFIRLANMAZ: kontrol büyüklüğüne bağlı "
            "olarak devrede aktif kalır ve çıkışı terminallerden uygulanan kaynağa tepki verir; "
            "bu yüzden eşdeğer direnç seri/paralel indirgemeyle bulunamaz (yalnızca bağımsız "
            "kaynaklar sıfırlanır). Bunun yerine Rth = Vth / In kullanılır: Vth açık devre "
            "gerilimi, In terminaller kısa devre edildiğinde telden geçen akımdır.")
        s.text(f"Terminaller (Düğüm {a} ve Düğüm {b}) bir tel ile kısa devre edilip devre bağımlı "
               f"kaynak aktifken yeniden çözüldüğünde telden {_flow_text(a, b)} yönünde geçen akım:")
        s.math(f"In = Isc = {ctx.val(ex.isc, 'A')}")
        s.math(f"{symbol} = Vth / In = {ctx.val(vth, 'V')} / {paren(ctx.val(ex.isc, 'A'))}")
        s.result(f"{symbol} = {_imp_text(ctx, expected)}")
        return True

    if ex.i_test is None or abs(ex.i_test) <= 1e-15:
        return False
    if not _close(ex.v_test / ex.i_test, expected, 1e-4):
        return False
    s.text(
        "Devrede bağımlı kaynak var ve bağımsız kaynak sıfırlandığında (ya da hiç yokken) "
        "Vth = 0 ve In = 0 olur; Rth = Vth / In = 0/0 belirsizdir. Bu durumda test kaynağı "
        "yöntemi kullanılır: bağımlı kaynak SIFIRLANMAZ (aktif kalır), bağımsız kaynaklar "
        "sıfırlanır ve terminallere 1 V'luk bir test kaynağı bağlanır. Kaynağın devreye "
        "verdiği akım I_test bulunur ve Rth = V_test / I_test olur.")
    s.math(f"V_test = {ctx.val(ex.v_test, 'V')}  (Düğüm {a} (+), Düğüm {b} (−))")
    s.text("Devre bu test kaynağıyla (bağımlı kaynak aktifken) çözüldüğünde test kaynağının + "
           f"ucundan (Düğüm {a}) devreye verdiği akım:")
    s.math(f"I_test = {ctx.val(ex.i_test, 'A')}")
    s.math(f"{symbol} = V_test / I_test = {ctx.val(ex.v_test, 'V')} / "
           f"{paren(ctx.val(ex.i_test, 'A'))}")
    s.result(f"{symbol} = {_imp_text(ctx, expected)}")
    return True


def _port_reduction_section(ctx: _Ctx, title: str, symbol: str,
                            expected: Optional[complex]) -> Tuple[_Section, bool]:
    a, b = _port(ctx)
    s = _Section(title)
    s.text(
        "Bağımsız kaynakları sıfırlayıp terminallerden devreye bakarız "
        "(gerilim kaynağı → kısa devre, akım kaynağı → açık devre):")
    red = reduce_port_impedance(ctx.parsed, a, b, ctx.is_dc, ctx.frequency)
    for note_text in red.zeroing_notes:
        s.math(f"• {note_text}")

    ok = (red.complete and red.impedance is not None and expected is not None
          and _close(red.impedance, expected, 1e-4))
    if ok:
        for step in red.steps:
            if step.kind == "series":
                s.text(f"{step.elements[0]} ve {step.elements[1]} seri bağlı "
                       "(aralarındaki düğüme başka eleman bağlı değil):")
                s.math(step.formula.replace("-", MINUS))
            elif step.kind == "parallel":
                s.text(f"{step.elements[0]} ve {step.elements[1]} aynı iki düğüm arasında, paralel:")
                s.math(step.formula.replace("-", MINUS))
            else:
                s.math(f"• {step.formula}")
        s.result(f"{symbol} = {rect(expected, 'Ω') if not ctx.is_dc else eng(expected.real, 'Ω')}")
    elif expected is not None and ctx.has_dependent:
        if not _dependent_rth(ctx, s, symbol, expected):
            s.text(
                "Devrede bağımlı kaynak var. Bağımlı kaynak sıfırlanmaz (devrede aktif kalır) ve "
                "çıkışı terminallerden uygulanan kaynağa tepki verir; bu yüzden eşdeğer "
                "direnç seri/paralel indirgemeyle bulunamaz. Bağımsız kaynaklar sıfırlanıp "
                "terminallere bir test kaynağı bağlanır ve Z = V_test / I_test hesaplanır "
                "(ya da Z = Voc / Isc). Çözücünün bu yöntemle bulduğu sonuç:")
            s.result(f"{symbol} = {rect(expected, 'Ω') if not ctx.is_dc else eng(expected.real, 'Ω')}")
        if expected.real < -1e-12:
            s.note("Eşdeğer direnç negatif çıktı: bağımlı kaynak terminallere enerji verir; "
                   "pasif bir devrede bu olmaz, aktif (bağımlı kaynaklı) devrede olabilir.")
    elif expected is not None:
        s.text(
            "Bu devre terminallerden bakıldığında basit seri/paralel adımlarla "
            "indirgenemiyor (ör: köprü yapısı). Bu durumda terminallere bir test "
            "kaynağı bağlanır ve Z = V_test / I_test oranı hesaplanır. Çözücünün "
            "bu yöntemle bulduğu sonuç:")
        s.result(f"{symbol} = {rect(expected, 'Ω') if not ctx.is_dc else eng(expected.real, 'Ω')}")
    return s, ok


def _thevenin(ctx: _Ctx) -> List[_Section]:
    th = ctx.results.thevenin
    if ctx.analysis_type != AnalysisType.THEVENIN or th is None or _port(ctx) is None:
        return []
    a, b = _port(ctx)
    vth = complex(th.vth.real, th.vth.imaginary)
    zth = complex(th.zth.real, th.zth.imaginary)
    sym_r = "Rth" if ctx.is_dc else "Zth"

    s1 = _Section("1. Adım — Vth (Açık Devre Gerilimi)")
    s1.text(f"Terminaller arasına hiçbir yük bağlı değilken Düğüm {a} ile Düğüm {b} "
            "arasındaki gerilim Vth'dir. Bulduğumuz düğüm gerilimlerinden:")
    derived = ctx.node_value(a) - ctx.node_value(b)
    if _close(derived, vth, 1e-4):
        s1.math(f"Vth = {node_v(a)} {MINUS} {node_v(b)} = {ctx.val(ctx.node_value(a), 'V')} "
                f"{MINUS} {paren(ctx.val(ctx.node_value(b), 'V'))}")
    s1.result(f"Vth = {ctx.val(vth, 'V')}")

    s2, _ = _port_reduction_section(ctx, f"2. Adım — {sym_r} (Eşdeğer {'Direnç' if ctx.is_dc else 'Empedans'})",
                                    sym_r, zth)

    s3 = _Section("Thevenin Eşdeğer Devresi")
    s3.result(f"Vth = {ctx.val(vth, 'V')} kaynağına seri {sym_r} = "
              f"{eng(zth.real, 'Ω') if ctx.is_dc else rect(zth, 'Ω')}")
    sections = [s1, s2, s3]

    if zth.real > 1e-12:
        s4 = _Section("Maksimum Güç Transferi")
        if ctx.is_dc:
            pmax = abs(vth) ** 2 / (4 * zth.real)
            s4.text(f"Bu terminallere bağlanacak yük direnci RL = Rth = {eng(zth.real, 'Ω')} "
                    "seçilirse yüke en fazla güç aktarılır:")
            s4.math(f"Pmax = Vth² / (4·Rth) = ({eng(vth.real, 'V')})² / (4 · {eng(zth.real, 'Ω')}) "
                    f"= {eng(pmax, 'W')}")
        else:
            pmax = abs(vth) ** 2 / (8 * zth.real)
            s4.text(f"Yük empedansı Zth'nin eşleniği seçilirse (ZL = Zth* = "
                    f"{rect(zth.conjugate(), 'Ω')}) yüke en fazla ortalama güç aktarılır:")
            s4.math(f"Pmax = |Vth|² / (8·Rth) = ({eng(abs(vth), 'V')})² / (8 · {eng(zth.real, 'Ω')}) "
                    f"= {eng(pmax, 'W')}")
            s4.note("Fazörler tepe değer olduğu için payda 8·Rth'dir (etkin değerlerle 4·Rth).")
        sections.append(s4)
    return sections


def _norton(ctx: _Ctx) -> List[_Section]:
    no = ctx.results.norton
    if ctx.analysis_type != AnalysisType.NORTON or no is None or _port(ctx) is None:
        return []
    a, b = _port(ctx)
    i_n = complex(no.i_n.real, no.i_n.imaginary)
    zn = complex(no.z_n.real, no.z_n.imaginary) if no.z_n is not None else None
    sym_r = "Rn" if ctx.is_dc else "Zn"
    vth = ctx.node_value(a) - ctx.node_value(b)

    s1 = _Section("1. Adım — In (Kısa Devre Akımı)")
    s1.text(f"Terminaller (Düğüm {a} ve Düğüm {b}) bir tel ile kısa devre edildiğinde "
            "telden akan akım In'dir.")
    if ctx.has_dependent:
        # Bağımlı kaynak aktif kalır; In = Vth/Rn dönüşümü burada döngüsel olurdu
        # (Rn de In'den bulunur). Kısa devre akımı gerçekten kısa devre edilerek bulundu.
        if ctx.port is not None and ctx.port.isc is not None and _close(ctx.port.isc, i_n, 1e-4):
            s1.text("Devrede bağımlı kaynak var; bağımlı kaynak aktif kalır. Terminaller "
                    "kısa devre edilip devre bu hâliyle yeniden çözüldüğünde telden "
                    f"{_flow_text(a, b)} yönünde geçen akım In'dir.")
    elif zn is not None and abs(zn) > 1e-15 and _close(vth / zn, i_n, 1e-4):
        s1.text("Thevenin–Norton dönüşümüyle kolayca bulunur: önce açık devre gerilimi "
                f"Vth = {node_v(a)} {MINUS} {node_v(b)} = {ctx.val(vth, 'V')}, sonra:")
        if ctx.is_dc:
            s1.math(f"In = Vth / {sym_r} = {eng(vth.real, 'V')} / {eng(zn.real, 'Ω')}")
        else:
            s1.math(f"In = Vth / {sym_r} = {polar(vth, 'V')} / {polar(zn, 'Ω')}")
    s1.result(f"In = {ctx.val(i_n, 'A')}")

    sections = [s1]
    if zn is not None:
        s2, _ = _port_reduction_section(ctx, f"2. Adım — {sym_r} (Norton {'Direnci' if ctx.is_dc else 'Empedansı'})",
                                        sym_r, zn)
        s2.note(f"Norton empedansı Thevenin empedansıyla aynıdır: {sym_r} = Rth.")
        sections.append(s2)

    s3 = _Section("Norton Eşdeğer Devresi")
    if zn is None:
        s3.result(f"In = {ctx.val(i_n, 'A')} değerinde ideal akım kaynağı ({sym_r} = ∞)")
    else:
        s3.result(f"In = {ctx.val(i_n, 'A')} akım kaynağına paralel {sym_r} = "
                  f"{eng(zn.real, 'Ω') if ctx.is_dc else rect(zn, 'Ω')}")
    sections.append(s3)
    return sections


# ═══════════════════════════════════════════════════════
#  8. GÜÇ
# ═══════════════════════════════════════════════════════

def _power(ctx: _Ctx) -> List[_Section]:
    pw = ctx.results.power
    if pw is None or not pw.elements:
        return []
    s = _Section("Güç Hesabı")
    if not ctx.is_dc:
        s.text("Fazörler tepe değer olduğundan ortalama (aktif) güç P = ½·|I|²·R, "
               "reaktif güç Q = ½·|I|²·X formülüyle bulunur.")

    absorbed_terms = []
    for e in ctx.passive():
        ep = pw.elements.get(e.id)
        if ep is None or e.id not in ctx.i:
            continue
        i_mag = abs(ctx.i[e.id])
        t = e.element_type
        name = e.id
        if ctx.is_dc:
            if t == ElementType.RESISTOR:
                s.math(f"P_{name} = I²·R = ({eng(i_mag, 'A')})² · {eng(e.value, 'Ω')} = {eng(ep.active_power, 'W')}")
                absorbed_terms.append(eng(ep.active_power, 'W'))
            elif t in (ElementType.CAPACITOR, ElementType.INDUCTOR):
                s.math(f"P_{name} = 0 (DC'de {'açık' if t == ElementType.CAPACITOR else 'kısa'} devre, güç harcamaz)")
            else:
                s.math(f"P_{name} = {eng(ep.active_power, 'W')}")
                absorbed_terms.append(eng(ep.active_power, 'W'))
        else:
            z = ctx.impedance(e)
            if t == ElementType.RESISTOR:
                s.math(f"P_{name} = ½·|I|²·R = ½ · ({eng(i_mag, 'A')})² · {eng(e.value, 'Ω')} = {eng(ep.active_power, 'W')}")
            elif t == ElementType.INDUCTOR:
                s.math(f"Q_{name} = ½·|I|²·X_L = ½ · ({eng(i_mag, 'A')})² · {eng(z.imag, 'Ω')} = "
                       f"{eng(ep.reactive_power, 'VAR')} (bobin reaktif güç çeker, P = 0)")
            elif t == ElementType.CAPACITOR:
                s.math(f"Q_{name} = −½·|I|²·|X_C| = −½ · ({eng(i_mag, 'A')})² · {eng(abs(z.imag), 'Ω')} = "
                       f"{eng(ep.reactive_power, 'VAR')} (kondansatör reaktif güç üretir, P = 0)")
            else:
                s.math(f"S_{name} = ½·|I|²·Z = {eng(ep.active_power, 'W')} + j{eng(ep.reactive_power, 'VAR')}")

    for e in ctx.sources():
        ep = pw.elements.get(e.id)
        if ep is None or ep.apparent_power < 1e-15:
            continue   # Bu analizde sıfırlanmış kaynak (ör: DC'de AC kaynak)
        if ctx.is_dc:
            # V = uçlar arası gerilim (akım kaynağında devreden gelir)
            v_across = (ctx.node_value(e.node_positive) - ctx.node_value(e.node_negative)).real
            s.math(f"P_{e.id} = V·I = {eng(abs(v_across), 'V')} · "
                   f"{eng(abs(ctx.i.get(e.id, 0).real), 'A')} = {eng(abs(ep.active_power), 'W')} "
                   f"({'verilen' if ep.active_power < 0 else 'çekilen'})")
        else:
            supplied = complex(-ep.active_power, -ep.reactive_power)
            s.math(f"S_{e.id} = ½·V·I* = {rect(supplied, 'VA')} → P = {eng(supplied.real, 'W')}, "
                   f"Q = {eng(supplied.imag, 'VAR')}, |S| = {eng(abs(supplied), 'VA')} (verilen)")

    for e in ctx.dependents():
        ep = pw.elements.get(e.id)
        if ep is None or ep.apparent_power < 1e-15:
            continue
        # Bağımlı kaynak güç verebilir de çekebilir de (işareti sonuç belirler)
        if ctx.is_dc:
            v_across = (ctx.node_value(e.node_positive) - ctx.node_value(e.node_negative)).real
            s.math(f"P_{e.id} = V·I = {eng(abs(v_across), 'V')} · "
                   f"{eng(abs(ctx.i.get(e.id, 0).real), 'A')} = {eng(abs(ep.active_power), 'W')} "
                   f"({'verilen' if ep.active_power < 0 else 'çekilen'}; bağımlı kaynak)")
        else:
            net = complex(-ep.active_power, -ep.reactive_power)
            s.math(f"S_{e.id} = ½·V·I* = {rect(net, 'VA')} → P = {eng(net.real, 'W')}, "
                   f"Q = {eng(net.imag, 'VAR')} (bağımlı kaynağın net verdiği)")

    sup = complex(pw.total_supplied.real, pw.total_supplied.imaginary)
    absb = complex(pw.total_absorbed.real, pw.total_absorbed.imaginary)
    if ctx.is_dc:
        terms = " + ".join(absorbed_terms) if len(absorbed_terms) > 1 else ""
        s.check(f"Güç dengesi: kaynakların (net) verdiği {eng(sup.real, 'W')} = elemanların harcadığı "
                f"{(terms + ' = ') if terms else ''}{eng(absb.real, 'W')} ✓"
                if _close(sup, absb, 1e-6) else
                f"Güç dengesi: verilen {eng(sup.real, 'W')}, harcanan {eng(absb.real, 'W')}")
    else:
        if _close(sup, absb, 1e-6):
            s.check(f"Güç dengesi: verilen S = {rect(sup, 'VA')} = çekilen S ✓")
        if pw.power_factor is not None:
            kind = {"geri": "geri — akım gerilimin gerisinde, devre endüktif",
                    "ileri": "ileri — akım gerilimin önünde, devre kapasitif",
                    "birim": "birim — devre saf dirençli gibi davranıyor"}.get(pw.power_factor_type or "", "")
            s.math(f"cos φ = P/|S| = {eng(sup.real, 'W')} / {eng(abs(sup), 'VA')} = "
                   f"{pw.power_factor:.3f}" + (f" ({kind})" if kind else ""))
    return [s]


# ═══════════════════════════════════════════════════════
#  9. KONTROL (KCL)
# ═══════════════════════════════════════════════════════

def _kcl_check(ctx: _Ctx) -> List[_Section]:
    s = _Section("Kontrol: Düğümlerde Akım Dengesi")
    check_nodes = ({n for n in ctx.v if n != "0"} if ctx.has_dependent
                   else {n for g in ctx.groups for n in g} | {n for n in ctx.known if n != "0"})
    for node in sorted(check_nodes, key=lambda n: (len(n), n)):
        flows = []   # (eleman, düğümden çıkan akım)
        for e in ctx.elements:
            if e.id not in ctx.i:
                continue
            if e.node_positive == node:
                flows.append((e.id, ctx.i[e.id]))
            elif e.node_negative == node:
                flows.append((e.id, -ctx.i[e.id]))
        if len(flows) < 2:
            continue
        total = sum(f for _, f in flows)
        scale = max(abs(f) for _, f in flows)
        if scale < 1e-15 or abs(total) > 1e-6 * scale:
            continue
        if ctx.is_dc:
            ins = [(n_, -f.real) for n_, f in flows if f.real < -1e-15]
            outs = [(n_, f.real) for n_, f in flows if f.real > 1e-15]
            if not ins or not outs:
                continue
            in_txt = " + ".join(f"{eng(v, 'A')} ({n_})" for n_, v in ins)
            out_txt = " + ".join(f"{eng(v, 'A')} ({n_})" for n_, v in outs)
            s.check(f"Düğüm {node}: giren {in_txt} = çıkan {out_txt} ✓")
        else:
            terms = " + ".join(f"{polar(f, 'A')} ({n_})" for n_, f in flows)
            s.check(f"Düğüm {node}: çıkan akımların fazörel toplamı {terms} ≈ 0 ✓")
    if s.blocks:
        s.blocks.insert(0, ExplanationBlock(
            kind="text",
            text="Bulduğumuz akımlar KCL'yi sağlamalı: her düğüme giren akım, çıkan akıma eşittir."))
        return [s]
    return []


# ═══════════════════════════════════════════════════════
#  10. ZAMAN DOMENİ (AC)
# ═══════════════════════════════════════════════════════

def _time_domain(ctx: _Ctx) -> List[_Section]:
    if ctx.is_dc or ctx.omega is None:
        return []
    has_sine = any(e.element_type in SINE_SOURCES for e in ctx.elements)
    fn = "sin" if has_sine else "cos"
    s = _Section("Zaman Domenine Dönüş")
    s.text(f"Fazör V = Vm∠θ, zamanda v(t) = Vm·{fn}(ωt + θ) demektir"
           + (" (kaynak sinüs olarak verildiği için referans sin)." if has_sine
              else " (kosinüs referansı kullanıldı)."))
    w = num(ctx.omega)

    def expr(z: complex) -> str:
        mag, ph = abs(z), math.degrees(cmath.phase(z))
        sign = "+" if ph >= 0 else MINUS
        return f"{num(mag)}·{fn}({w}t {sign} {num(abs(ph))}°)"

    for n in sorted((n for n in ctx.v if n != "0"), key=lambda n: (len(n), n)):
        z = ctx.node_value(n)
        if abs(z) > 1e-15:
            s.math(f"v{n.translate(str.maketrans('0123456789', '₀₁₂₃₄₅₆₇₈₉'))}(t) = {expr(z)} V")
    for e in ctx.passive():
        if e.id in ctx.i and abs(ctx.i[e.id]) > 1e-15:
            s.math(f"i_{e.id}(t) = {expr(ctx.i[e.id])} A")
    return [s]


# ═══════════════════════════════════════════════════════
#  11. SONUÇ
# ═══════════════════════════════════════════════════════

def _summary(ctx: _Ctx) -> List[_Section]:
    s = _Section("Sonuç")
    if ctx.mesh is not None:
        for k, current in enumerate(ctx.mesh.mesh_currents, 1):
            s.result(f"I{str(k).translate(str.maketrans('0123456789', '₀₁₂₃₄₅₆₇₈₉'))} "
                     f"(çevre akımı) = {ctx.val(current, 'A')}")
    for n in sorted((n for n in ctx.v if n != "0"), key=lambda n: (len(n), n)):
        s.result(f"{node_v(n)} = {ctx.val(ctx.node_value(n), 'V')}")
    for pr in ctx.results.probe_results:
        value = pr.value
        z = complex(value) if isinstance(value, (int, float)) else complex(value.real, value.imaginary)
        s.result(f"{pr.probe_id} ({'gerilim' if pr.type == 'V' else 'akım'} probu) = {ctx.val(z, pr.unit)}")
    def cz(c) -> complex:
        return complex(c.real, c.imaginary)

    def imp(z: complex) -> str:
        return eng(z.real, 'Ω') if ctx.is_dc else rect(z, 'Ω')

    th, no = ctx.results.thevenin, ctx.results.norton
    if th is not None and ctx.analysis_type == AnalysisType.THEVENIN:
        s.result(f"Thevenin: Vth = {ctx.val(cz(th.vth), 'V')}, "
                 f"{'Rth' if ctx.is_dc else 'Zth'} = {imp(cz(th.zth))}")
    if no is not None and ctx.analysis_type == AnalysisType.NORTON:
        zn = "∞" if no.z_n is None else imp(cz(no.z_n))
        s.result(f"Norton: In = {ctx.val(cz(no.i_n), 'A')}, "
                 f"{'Rn' if ctx.is_dc else 'Zn'} = {zn}")
    return [s]
