"""
CircuitAnalyzer API — Rezonans (Faz 3 / v1.4)

Kapsam: tam olarak BİR bobin (L), BİR kondansatör (C) ve BİR AC kaynak içeren,
ideal elemanlı iki devre biçimi:

    Seri RLC:     gerilim kaynağı, R'ler (toplanır), L ve C tek gözde seri.
    Paralel RLC:  tam olarak bir R; R, L, C ve kaynak (gerilim ya da akım)
                  aynı iki düğüm arasında.

Formüller (kitaptaki sıra):
    ω₀ = 1/√(LC),  f₀ = ω₀/2π,  X = ω₀L = 1/(ω₀C)
    Seri:    Z₀ = R, I_max = V/R, Q = X/R, V_L = V_C = Q·V
    Paralel: Z₀ = R, Q = R/X, I_L = I_C = Q·I_R
    BW = f₀/Q;  kitap biçimi f₁,₂ = f₀ ∓ BW/2 (yüksek Q için yaklaşık);
    tam yarım güç frekansları f₁,₂ = √(f₀² + (BW/2)²) ∓ BW/2.

Kaynağın frekansı rezonans hesabına GİRMEZ; devre f₀'da çözülür. Sayılar
lcapy ile bağımsız olarak denetlenir (verify_with_lcapy); uyuşmazsa rezonans
anlatımı verilmez, yedek (normal AC) anlatıma dönülür.
"""

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from parser.netlist_parser import (
    ALL_SOURCES, CURRENT_SOURCES, DC_SOURCES, DEPENDENT_SOURCES, SINE_SOURCES,
    ElementType, ParsedCircuit, ParsedElement,
)

CURVE_POINTS = 400
Q_BOOK_LIMIT = 10.0          # Q bunun altındaysa f₀ ∓ BW/2 kaba bir yaklaşıktır
FREQ_NOTE_REL = 0.01         # kaynak frekansı f₀'dan bu orandan fazla farklıysa anlatımda söylenir
_TOL = 1e-6                  # lcapy denetimi bağıl toleransı

_PREFIX = "Rezonans yöntemi yalnızca seri ve paralel RLC devreleri için anlatılır"


class ResonanceNotApplicable(Exception):
    """Rezonans bu devre için uygulanamaz; mesaj öğrenciye gösterilen Türkçe gerekçedir."""


def _na(detail: str):
    raise ResonanceNotApplicable(f"{_PREFIX}; {detail}.")


@dataclass
class ResonanceCheck:
    """lcapy denetiminde ölçülen değerler (anlatımın Kontrol bölümü kullanır)."""
    z_f0: complex = 0j           # f₀'da kaynaktan görülen Z
    main_f0: float = 0.0         # seri/paralel-gerilim kaynağı: |I|; paralel-akım kaynağı: |V|
    elem_f0: float = 0.0         # seri: |V_L| ( = |V_C|); paralel: |I_L| ( = |I_C|)
    main_f1: float = 0.0         # seri: |I|(f₁ tam); paralel: |Z|(f₁ tam)
    main_f2: float = 0.0


@dataclass
class ResonanceAnalysis:
    kind: str                            # "series" | "parallel"
    source: ParsedElement
    source_is_current: bool
    resistors: List[ParsedElement]
    inductor: ParsedElement
    capacitor: ParsedElement
    r: float                             # toplam direnç (seri) ya da tek direnç (paralel)
    l: float
    c: float
    amp: float                           # kaynak genliği (seçili gösterimde)
    w0: float
    f0: float
    x: float
    q: float
    bw: float
    f1: float                            # kitap biçimi
    f2: float
    f1_exact: float
    f2_exact: float
    z0: float
    i0: float
    v0: float
    source_freq: Optional[float] = None  # kaynağın / isteğin frekansı (bilgi; hesaba girmez)
    curve_quantity: str = "I"
    curve_unit: str = "A"
    curve_f: List[float] = field(default_factory=list)
    curve_y: List[float] = field(default_factory=list)
    check: Optional[ResonanceCheck] = None

    @property
    def low_q(self) -> bool:
        return self.q < Q_BOOK_LIMIT

    @property
    def source_freq_differs(self) -> bool:
        return (self.source_freq is not None
                and abs(self.source_freq - self.f0) > FREQ_NOTE_REL * self.f0)


# ═══════════════════════════════════════════════════════
#  UYGULANABİLİRLİK VE TOPOLOJİ
# ═══════════════════════════════════════════════════════

def _is_single_loop(elems: List[ParsedElement]) -> bool:
    """Her düğümde tam iki eleman buluşuyor ve devre tek parça mı? (tek göz)"""
    deg = Counter()
    for e in elems:
        deg[e.node_positive] += 1
        deg[e.node_negative] += 1
    if any(d != 2 for d in deg.values()) or len(deg) != len(elems):
        return False
    parent = {n: n for n in deg}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for e in elems:
        parent[find(e.node_positive)] = find(e.node_negative)
    return len({find(n) for n in deg}) == 1


def analyze_resonance(parsed: ParsedCircuit,
                      request_frequency: Optional[float] = None) -> ResonanceAnalysis:
    """
    Devreyi sınıflandırır ve rezonans büyüklüklerini hesaplar. Uygun değilse
    ResonanceNotApplicable (Türkçe somut gerekçeyle) fırlatır.
    """
    elems = parsed.elements
    types = [e.element_type for e in elems]

    if ElementType.SWITCH in types:
        _na("devrede anahtar var")
    z_ids = [e.id for e in elems if e.element_type == ElementType.IMPEDANCE]
    if z_ids:
        _na(f"devrede empedans (Z) elemanı var ({', '.join(z_ids)})")
    dep_ids = [e.id for e in elems if e.element_type in DEPENDENT_SOURCES]
    if dep_ids:
        _na(f"devrede bağımlı kaynak var ({', '.join(dep_ids)})")

    sources = [e for e in elems if e.element_type in ALL_SOURCES]
    if any(e.element_type in DC_SOURCES for e in sources):
        _na("devrede DC kaynak var; rezonans AC kaynakla çalışan devrede anlatılır")
    if len(sources) != 1:
        _na("devrede tam olarak bir AC kaynak olmalı "
            f"({'hiç kaynak yok' if not sources else f'{len(sources)} kaynak var'})")
    src = sources[0]
    amp = float(src.params.get("amplitude", src.value))
    if not math.isfinite(amp) or abs(amp) <= 1e-15:
        _na(f"{src.id} kaynağının değeri sıfır; sıfır kaynakla rezonans eğrisi çıkmaz")
    amp = abs(amp)

    inductors = [e for e in elems if e.element_type == ElementType.INDUCTOR]
    capacitors = [e for e in elems if e.element_type == ElementType.CAPACITOR]
    resistors = [e for e in elems if e.element_type == ElementType.RESISTOR]
    if len(inductors) != 1:
        _na("devrede tam olarak bir bobin olmalı "
            f"({'bobin yok' if not inductors else f'{len(inductors)} bobin var'})")
    if len(capacitors) != 1:
        _na("devrede tam olarak bir kondansatör olmalı "
            f"({'kondansatör yok' if not capacitors else f'{len(capacitors)} kondansatör var'})")
    if not resistors:
        _na("devrede direnç yok; rezonansta Z₀ = R ve Q = X/R (ya da R/X) direnç olmadan tanımsızdır")
    for e in resistors:
        if not (math.isfinite(e.value) and e.value > 0):
            _na(f"{e.id} direnci sıfır ya da negatif; Z₀ = R > 0 olmalıdır")
    ind, cap = inductors[0], capacitors[0]
    for e in (ind, cap):
        if not (math.isfinite(e.value) and e.value > 0):
            _na(f"{e.id} elemanının değeri sıfır ya da negatif")

    # ── Topoloji ──
    if any(e.node_positive == e.node_negative for e in elems):
        _na("bir elemanın iki ucu aynı düğüme bağlı (kısa devre edilmiş)")
    pairs = {frozenset((e.node_positive, e.node_negative)) for e in elems}
    source_is_current = src.element_type in CURRENT_SOURCES
    if len(pairs) == 1:
        kind = "parallel"
        if len(resistors) != 1:
            _na(f"paralel biçimde tam olarak bir direnç olmalı ({len(resistors)} direnç var)")
    elif _is_single_loop(elems):
        kind = "series"
        if source_is_current:
            _na("seri devrede akım kaynağı akımı kendisi belirler; seri rezonans için "
                "gerilim kaynağı gerekir")
    else:
        _na("elemanlar ne tek gözde seri ne de aynı iki düğüm arasında paralel bağlı "
            "(ör. bobinin iç direnci gibi karma bağlantılar bu yöntemle anlatılmaz)")

    # ── Hesap ──
    r = sum(e.value for e in resistors)
    l, c = ind.value, cap.value
    w0 = 1.0 / math.sqrt(l * c)
    f0 = w0 / (2.0 * math.pi)
    x = w0 * l
    q = x / r if kind == "series" else r / x
    bw = f0 / q
    root = math.sqrt(f0 * f0 + (bw / 2.0) ** 2)
    if kind == "series":
        i0, v0 = amp / r, q * amp
    elif source_is_current:
        i0, v0 = amp, amp * r
    else:
        i0, v0 = amp / r, amp

    src_freq = None
    if src.element_type in SINE_SOURCES and src.params.get("frequency"):
        src_freq = float(src.params["frequency"])
    elif request_frequency:
        src_freq = float(request_frequency)

    a = ResonanceAnalysis(
        kind=kind, source=src, source_is_current=source_is_current,
        resistors=resistors, inductor=ind, capacitor=cap,
        r=r, l=l, c=c, amp=amp, w0=w0, f0=f0, x=x, q=q, bw=bw,
        f1=f0 - bw / 2.0, f2=f0 + bw / 2.0,
        f1_exact=root - bw / 2.0, f2_exact=root + bw / 2.0,
        z0=r, i0=i0, v0=v0, source_freq=src_freq,
    )
    a.curve_quantity, a.curve_unit = ("I", "A") if kind == "series" else ("Z", "Ω")
    a.curve_f, a.curve_y = resonance_curve(a)
    return a


# ═══════════════════════════════════════════════════════
#  EĞRİ (analitik, lcapy'siz)
# ═══════════════════════════════════════════════════════

def impedance_at(a: ResonanceAnalysis, f):
    """Kaynaktan görülen Z(f) (numpy dizisi ya da sayı)."""
    w = 2.0 * math.pi * np.asarray(f, dtype=float)
    if a.kind == "series":
        return a.r + 1j * (w * a.l - 1.0 / (w * a.c))
    y = 1.0 / a.r + 1j * (w * a.c - 1.0 / (w * a.l))
    return 1.0 / y


def resonance_curve(a: ResonanceAnalysis):
    """
    400 noktalı doğrusal frekans ekseni: alt = max(0,1·f₀, f₀ − 5·BW), üst = f₀ + 5·BW.
    f₀ eğride tam bir noktadır. Seride y = V/|Z(f)|, paralelde y = |Z(f)|.
    """
    lo = max(0.1 * a.f0, a.f0 - 5.0 * a.bw)
    hi = a.f0 + 5.0 * a.bw
    f = np.linspace(lo, hi, CURVE_POINTS)
    f[int(np.argmin(np.abs(f - a.f0)))] = a.f0
    z = np.abs(impedance_at(a, f))
    y = a.amp / z if a.kind == "series" else z
    return [float(v) for v in f], [float(v) for v in y]


# ═══════════════════════════════════════════════════════
#  lcapy İLE BAĞIMSIZ DENETİM
# ═══════════════════════════════════════════════════════

def _close(a: float, b: float) -> bool:
    return abs(a - b) <= _TOL * max(abs(a), abs(b), 1e-300)


def verify_with_lcapy(a: ResonanceAnalysis, cct) -> Optional[str]:
    """
    Sayıları çözücünün (lcapy) devresiyle denetler; uyuşmazsa Türkçe gerekçe,
    uyuşuyorsa None (ölçülen değerler a.check'e yazılır).

        f₀'da: kaynaktan görülen Z'nin sanal kısmı ≈ 0 ve Z = R; seride |I| = V/R,
               paralel-gerilim kaynağında |I| = V/R, paralel-akım kaynağında |V| = I·R;
               seride |V_L| = |V_C| = Q·V, paralelde |I_L| = |I_C| = Q·I_R
        tam f₁ ve f₂'de: seride |I| = I_max/√2, paralelde |Z| = R/√2
    """
    try:
        from solver.circuit_solver import _extract_numeric, lcapy_element_current

        src = a.source

        def volt(n: str, f: float) -> complex:
            return 0j if n == "0" else complex(_extract_numeric(cct[n].V, False, f))

        def port(f: float):
            """(kaynaktan görülen Z, devreye verilen akım, uçlardaki gerilim düşümü)"""
            ib = complex(lcapy_element_current(cct, src, {}, False, f))
            vp, vn = volt(src.node_positive, f), volt(src.node_negative, f)
            if a.source_is_current:        # akım n− ucundan devreye girer, n+ ucuna döner
                i_in, v = ib, vn - vp
            else:                          # gerilim kaynağı + ucundan akım verir
                i_in, v = -ib, vp - vn
            return v / i_in, i_in, v

        def across(e: ParsedElement, f: float) -> float:
            return abs(volt(e.node_positive, f) - volt(e.node_negative, f))

        sqrt2 = math.sqrt(2.0)
        chk = ResonanceCheck()

        z, i_in, v = port(a.f0)
        chk.z_f0 = z
        if abs(z.imag) > _TOL * abs(z) or not _close(z.real, a.r):
            return "lcapy denetimi: f₀'da kaynaktan görülen empedans Z = R (sanal kısım sıfır) çıkmadı."
        if a.kind == "parallel" and a.source_is_current:
            chk.main_f0 = abs(v)
            if not _close(chk.main_f0, a.v0):
                return "lcapy denetimi: f₀'daki gerilim V = I·R ile uyuşmadı."
        else:
            chk.main_f0 = abs(i_in)
            if not _close(chk.main_f0, a.i0):
                return "lcapy denetimi: f₀'daki akım hesaplanan değerle uyuşmadı."

        if a.kind == "series":
            chk.elem_f0 = across(a.inductor, a.f0)
            if not (_close(chk.elem_f0, a.v0) and _close(across(a.capacitor, a.f0), a.v0)):
                return "lcapy denetimi: bobin ve kondansatör gerilimleri Q·V ile uyuşmadı."
        else:
            i_l = abs(complex(_extract_numeric(cct[a.inductor.id].I, False, a.f0)))
            i_c = abs(complex(_extract_numeric(cct[a.capacitor.id].I, False, a.f0)))
            chk.elem_f0 = i_l
            if not (_close(i_l, a.v0 / a.x) and _close(i_c, a.v0 / a.x)):
                return "lcapy denetimi: bobin ve kondansatör akımları Q·I ile uyuşmadı."

        for attr, f in (("main_f1", a.f1_exact), ("main_f2", a.f2_exact)):
            z, i_in, _ = port(f)
            if a.kind == "series":
                val, want = abs(i_in), a.i0 / sqrt2
            else:
                val, want = abs(z), a.r / sqrt2
            setattr(chk, attr, val)
            if not _close(val, want):
                return "lcapy denetimi: tam yarım güç frekanslarında 1/√2 oranı sağlanmadı."

        a.check = chk
    except Exception as exc:        # lcapy çözemedi → sonucu doğrulanmamış bırakma
        return f"Sayılar bağımsız çözücüyle doğrulanamadı ({type(exc).__name__})."
    return None
