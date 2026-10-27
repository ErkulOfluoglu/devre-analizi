"""
CircuitAnalyzer API — Çevre Akımları (Mesh) Analizi

Devredeki bağımsız çevreleri (gözleri) bulur, her birine bir çevre akımı
atar ve KVL denklemlerini kurup çözer. Sonuç, anlatım için gereken tüm
yapıyı (çevreler, katsayılar, kısıtlar) içerir.

★ Çevreleri bulma:
    Devre bir graf olarak düzlemsel yerleşime (planar embedding) sokulur;
    her yüz bir çevredir. En dış yüz atılır → kalan yüzler bağımsız
    çevrelerdir (sayısı = eleman − düğüm + 1).
    Paralel elemanlar için her eleman ortasına sanal bir düğüm eklenir.
    C# düğüm konumlarını gönderirse ("* NODEPOS n x y"), dış yüz en büyük
    alanlı yüz seçilir ve çevre akımları ekranda saat yönüne çevrilir.

★ Akım kaynakları (değiştirilmiş çevre yöntemi):
    Bilinmeyenler = çevre akımları + akım kaynaklarının uç gerilimleri.
      • Kaynak tek çevredeyse → o çevre akımı doğrudan bilinir.
      • İki çevre paylaşıyorsa → süperçevre (iki KVL toplanır) + kısıt.

★ İşaret kuralı:
    s[e][m] = +1 → çevre m, elemanı n+ → n− yönünde geçer, −1 → tersi.
    Eleman akımı (n+ → n−):  i_e = Σ_m s[e][m] · I_m
    KVL (çevre m):  Σ_e s[e][m] · v_e = 0,   v_e = V(n+) − V(n−)

★ Bağımlı kaynaklar (E, G, H, F):
    Kontrol büyüklüğü ÇİZİLEN yönde alınır (V(-R2) → V_R2 = V(R2.n−) − V(R2.n+),
    I(-R2) → R2 içinden n− → n+ akım); kazançla çarpımında ayrıca eksi yazılmaz.
      • I_X = Σ_m σ·s[X][m]·I_m          (σ = kontrol işareti ±1)
      • V_X = Z_X · I_X                  (R, Z; AC'de L ve C); bağımsız gerilim
        kaynağının gerilimi sabittir (σ·Vs)
      • Bağımlı GERİLİM kaynağı (E, H): v = kazanç·kontrol; KVL'de bağımsız gerilim
        kaynağıyla aynı işaretle, ama bilinmeyen çevre akımlarını çarptığından
        katsayıları SOL tarafa yazılır.
      • Bağımlı AKIM kaynağı (G, F): bağımsız akım kaynağı gibi (tek çevre → kısıt,
        iki çevre → süperçevre + kısıt); kısıtın sağ tarafı bilinmeyen çevre
        akımlarını içerir: Σ s·I_m − kazanç·kontrol = 0
    Desteklenmeyenler (ok=False + Türkçe sebep): akım kaynağının veya bağımlı
    gerilim kaynağının GERİLİMİ kontrol büyüklüğüyse; DC'de kondansatör/bobin
    gerilimi (veya kondansatör akımı) kontrol büyüklüğüyse.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import networkx as nx
import numpy as np

from parser.netlist_parser import (
    CURRENT_SOURCES, DEPENDENT_CURRENT_OUTPUT, DEPENDENT_SOURCES,
    DEPENDENT_VOLTAGE_OUTPUT, VOLTAGE_SOURCES, ElementType,
    ParsedCircuit, ParsedElement,
)
from explainer.step_generator import _source_value

# Bağımlı kaynaklı sistemde "tekil" sayılan koşul sayısı eşiği
_MAX_COND = 1e12


@dataclass
class Mesh:
    index: int                                   # 1'den başlar (I₁, I₂, …)
    nodes: List[str]                             # dolaşılan düğüm sırası (kapalı)
    elements: List[Tuple[ParsedElement, int]]    # (eleman, yön işareti ±1)

    def sign(self, element_id: str) -> int:
        for e, s in self.elements:
            if e.id == element_id:
                return s
        return 0


@dataclass
class MeshDependent:
    """
    Bir bağımlı kaynağın çevre akımları cinsinden yazılmış hâli.

    Kontrol büyüklüğü (çizilen yönde):
        kontrol = ctrl_const + Σ_k katsayı_k · I_k
        katsayı_k = ctrl_z · ctrl_signs[k]   (V kontrolü, pasif eleman)
                  = ctrl_signs[k]            (I kontrolü)
    Çıkış = kazanç · kontrol  (E, H için V; G, F için A).
    """
    element: ParsedElement
    gain: float
    control_id: str
    control_kind: str                       # "V" | "I"
    control_sign: int                       # V(-R2) → −1
    ctrl_signs: Dict[int, int] = field(default_factory=dict)   # {çevre no: ±1}, çizilen yön
    ctrl_z: Optional[complex] = None        # V kontrolü, pasif eleman: Z
    ctrl_const: complex = 0j                # V kontrolü, bağımsız gerilim kaynağı: σ·Vs
    ctrl_value: complex = 0j                # çözülmüş kontrol büyüklüğü (V veya A)
    value: complex = 0j                     # çözülmüş çıkış = kazanç · kontrol

    @property
    def id(self) -> str:
        return self.element.id

    @property
    def is_current_output(self) -> bool:
        return self.element.element_type in DEPENDENT_CURRENT_OUTPUT

    def coefficients(self) -> Dict[int, complex]:
        """Kontrol büyüklüğünün çevre akımı katsayıları {çevre no: katsayı}."""
        z = self.ctrl_z if self.ctrl_z is not None else 1
        return {k: z * sg for k, sg in self.ctrl_signs.items()}


@dataclass
class MeshAnalysis:
    ok: bool
    reason: str = ""
    meshes: List[Mesh] = field(default_factory=list)
    removed_notes: List[str] = field(default_factory=list)
    impedances: Dict[str, complex] = field(default_factory=dict)   # pasif eleman Z
    voltages: Dict[str, complex] = field(default_factory=dict)     # gerilim kaynağı Vs
    currents_cs: Dict[str, complex] = field(default_factory=dict)  # akım kaynağı Is (yalnız bağımsız)
    mesh_currents: List[complex] = field(default_factory=list)     # I₁, I₂, …
    branch_currents: Dict[str, complex] = field(default_factory=dict)   # tüm elemanlar, n+ → n−
    cs_voltages: Dict[str, complex] = field(default_factory=dict)  # bağımsız + bağımlı akım kaynakları
    element_count: int = 0
    node_count: int = 0
    clockwise: bool = False                      # geometriye göre saat yönü mü
    # Bağımlı kaynaklar (eleman sırasıyla); bağımlı kaynaksız devrede boş
    dependents: Dict[str, MeshDependent] = field(default_factory=dict)


def _element_impedance(e: ParsedElement, is_dc: bool, omega: Optional[float]) -> Optional[complex]:
    t = e.element_type
    if t == ElementType.RESISTOR:
        return complex(e.value)
    if t == ElementType.IMPEDANCE:
        return complex(e.params.get("impedance", complex(e.value)))
    if is_dc:
        return None if t == ElementType.CAPACITOR else 0j   # C açık, L kısa
    if omega is None:
        return None
    if t == ElementType.CAPACITOR:
        return 1 / (1j * omega * e.value)
    return 1j * omega * e.value


def analyze_meshes(
    parsed: ParsedCircuit,
    is_dc: bool,
    frequency: Optional[float],
    node_positions: Optional[Dict[str, Tuple[float, float]]] = None,
) -> MeshAnalysis:
    """Çevre akımları analizini yapar. Uygulanamazsa ok=False ve sebep döner."""
    omega = None if is_dc or not frequency else 2 * math.pi * frequency
    result = MeshAnalysis(ok=False)

    # ── 1. Graf kenarları ──
    edges: List[ParsedElement] = []
    for e in parsed.elements:
        t = e.element_type
        if t in VOLTAGE_SOURCES:
            result.voltages[e.id] = _source_value(e, is_dc)   # 0 ise kısa devre
            edges.append(e)
        elif t in CURRENT_SOURCES:
            i_s = _source_value(e, is_dc)
            if abs(i_s) < 1e-15:
                result.removed_notes.append(
                    f"{e.id} bu analizde sıfırlanır → açık devre (çevrelere katılmaz).")
                continue
            result.currents_cs[e.id] = i_s
            edges.append(e)
        elif t in DEPENDENT_SOURCES:
            edges.append(e)   # değeri çevre akımlarına bağlı; denklemlerde işlenir
        else:
            z = _element_impedance(e, is_dc, omega)
            if z is None:
                if is_dc and t == ElementType.CAPACITOR:
                    result.removed_notes.append(f"{e.id} DC'de açık devredir → çevrelere katılmaz.")
                    continue
                result.reason = "AC analizde frekans bilinmediği için empedanslar hesaplanamıyor."
                return result
            result.impedances[e.id] = z
            edges.append(e)

    # ── 2. Uçta kalan (akım taşımayan) elemanları buda ──
    changed = True
    while changed:
        changed = False
        degree: Dict[str, int] = {}
        for e in edges:
            if e.node_positive == e.node_negative:
                continue
            degree[e.node_positive] = degree.get(e.node_positive, 0) + 1
            degree[e.node_negative] = degree.get(e.node_negative, 0) + 1
        for e in list(edges):
            if e.node_positive == e.node_negative:
                edges.remove(e)
                result.removed_notes.append(f"{e.id} iki ucu aynı düğümde → çevrelere katılmaz.")
                changed = True
                break
            if degree.get(e.node_positive, 0) == 1 or degree.get(e.node_negative, 0) == 1:
                edges.remove(e)
                if e.element_type in CURRENT_SOURCES or e.element_type in DEPENDENT_CURRENT_OUTPUT:
                    result.reason = (f"{e.id} akım kaynağının bir ucu boşta — akımı "
                                     "devreye akacak kapalı bir yol yok.")
                    return result
                result.removed_notes.append(f"{e.id} bir ucu boşta kaldığı için akım taşımaz.")
                changed = True
                break

    if not edges:
        result.reason = "Devrede kapalı bir çevre yok."
        return result

    # ── 3. Düzlemsel graf (her elemana sanal orta düğüm) ──
    G = nx.Graph()
    for e in edges:
        mid = ("e", e.id)
        G.add_edge(e.node_positive, mid)
        G.add_edge(mid, e.node_negative)
    if not nx.is_connected(G):
        result.reason = "Devre birbirine bağlı olmayan parçalardan oluşuyor."
        return result
    planar, embedding = nx.check_planarity(G)
    if not planar:
        result.reason = ("Devre düzlemsel değil (teller kesişmeden çizilemiyor); "
                         "çevre akımları yöntemi yalnızca düzlemsel devrelere uygulanır.")
        return result

    real_nodes = {n for n in G.nodes if not isinstance(n, tuple)}
    result.element_count = len(edges)
    result.node_count = len(real_nodes)
    expected = len(edges) - len(real_nodes) + 1

    # ── 4. Yüzler ──
    visited = set()
    faces: List[List] = []
    for v, w in embedding.edges():
        if (v, w) in visited:
            continue
        faces.append(embedding.traverse_face(v, w, mark_half_edges=visited))

    by_id = {e.id: e for e in edges}

    def face_elements(face) -> List[Tuple[ParsedElement, int]]:
        """Yüz sırası → (eleman, yön) listesi; aynı eleman iki kez geçerse birleşir."""
        signs: Dict[str, int] = {}
        order: List[str] = []
        k = len(face)
        for i, node in enumerate(face):
            if not isinstance(node, tuple):
                continue
            eid = node[1]
            prev_node, next_node = face[i - 1], face[(i + 1) % k]
            e = by_id[eid]
            if prev_node == e.node_positive and next_node == e.node_negative:
                s = 1
            elif prev_node == e.node_negative and next_node == e.node_positive:
                s = -1
            else:
                s = 0
            if eid not in signs:
                order.append(eid)
                signs[eid] = 0
            signs[eid] += s
        return [(by_id[eid], signs[eid]) for eid in order if signs[eid] != 0]

    def face_nodes(face) -> List[str]:
        return [n for n in face if not isinstance(n, tuple)]

    def area(face) -> Optional[float]:
        if not node_positions:
            return None
        pts = []
        for n in face:
            if isinstance(n, tuple):
                e = by_id[n[1]]
                a, b = node_positions.get(e.node_positive), node_positions.get(e.node_negative)
                if a is None or b is None:
                    return None
                pts.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
            else:
                if n not in node_positions:
                    return None
                pts.append(node_positions[n])
        return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                         for i in range(len(pts)))

    # Dış yüz: konum varsa en büyük alanlı, yoksa en çok elemanlı
    areas = [area(f) for f in faces]
    if all(a is not None for a in areas):
        outer = max(range(len(faces)), key=lambda i: abs(areas[i]))
        result.clockwise = True
    else:
        # Eşitlikte akım kaynağı içeren yüz dış yüz olsun: kaynak dış kolda
        # kalır, çevre akımı doğrudan bilinir (ders kitaplarındaki çizim gibi)
        outer = max(range(len(faces)), key=lambda i: (
            len(face_elements(faces[i])),
            sum(1 for e, _ in face_elements(faces[i]) if e.element_type in CURRENT_SOURCES)))

    # İç yüzler (yüz = sanal düğümler dahil kapalı dizi)
    seqs = []
    for i, face in enumerate(faces):
        if i == outer or not face_elements(face):
            continue
        # Ekran koordinatlarında (y aşağı) pozitif alan = saat yönü
        if result.clockwise and areas[i] < 0:
            face = list(reversed(face))
        seqs.append(face)

    if len(seqs) != expected:
        result.reason = (f"Çevre sayısı tutarsız (bulunan {len(seqs)}, beklenen {expected}).")
        return result

    # Konum yoksa saat yönü bilinemez: tüm çevreler AYNI yönde kalır, ama
    # gerilim kaynaklarından çoğunlukla − → + (yükselerek) geçilecek yön
    # seçilir; böylece çevre akımları genelde pozitif çıkar.
    if not result.clockwise:
        # "Doğal" yön: gerilim kaynağından − → + (sg < 0), akım kaynağında
        # kaynağın akımıyla aynı yön (sg > 0)
        natural = unnatural = 0
        for f in seqs:
            for e, sg in face_elements(f):
                if e.element_type in VOLTAGE_SOURCES:
                    natural += sg < 0
                    unnatural += sg > 0
                elif e.element_type in CURRENT_SOURCES:
                    natural += sg > 0
                    unnatural += sg < 0
        if unnatural > natural:
            seqs = [list(reversed(f)) for f in seqs]

    def node_key(n) -> int:
        return int(n) if isinstance(n, str) and n.isdigit() else 10**6

    # Her dizi GND'den (yoksa en küçük numaralı düğümden) başlasın; eleman
    # sırası dolaşma sırasıyla aynı olsun
    rotated = []
    for f in seqs:
        start = min((j for j, n in enumerate(f) if not isinstance(n, tuple)),
                    key=lambda j: node_key(f[j]))
        rotated.append(f[start:] + f[:start])

    # Okunabilirlik: GND'yi içeren / küçük numaralı çevre önce (deterministik)
    rotated.sort(key=lambda f: (min(node_key(n) for n in f if not isinstance(n, tuple)),
                                len(face_elements(f))))
    for idx, f in enumerate(rotated, 1):
        nodes = face_nodes(f)
        result.meshes.append(Mesh(index=idx, nodes=nodes + [nodes[0]],
                                  elements=face_elements(f)))

    # ── 5. Değiştirilmiş çevre denklemleri ──
    M = len(result.meshes)
    s = {(e.id, m.index - 1): sign for m in result.meshes for e, sign in m.elements}

    # Bağımlı kaynaklar: kontrol büyüklüğünü çevre akımlarıyla yaz
    all_by_id = {e.id: e for e in parsed.elements}
    for e in edges:
        if e.element_type not in DEPENDENT_SOURCES:
            continue
        dep = _dependent_in_meshes(e, all_by_id, s, M, result, is_dc, omega)
        if dep is None:
            result.dependents = {}
            return result   # sebep result.reason'da
        result.dependents[e.id] = dep

    cs_ids = list(result.currents_cs) + [
        e.id for e in edges if e.element_type in DEPENDENT_CURRENT_OUTPUT]
    size = M + len(cs_ids)
    A = np.zeros((size, size), dtype=complex)
    b = np.zeros(size, dtype=complex)

    for m in range(M):
        for e in edges:
            se_m = s.get((e.id, m), 0)
            if se_m == 0:
                continue
            if e.id in result.impedances:
                for k in range(M):
                    se_k = s.get((e.id, k), 0)
                    if se_k:
                        A[m, k] += se_m * se_k * result.impedances[e.id]
            elif e.id in result.voltages:
                b[m] -= se_m * result.voltages[e.id]
            elif e.id in result.dependents and not result.dependents[e.id].is_current_output:
                # Bağımlı gerilim kaynağı: v = kazanç · kontrol (sol tarafa)
                dep = result.dependents[e.id]
                for k, c in dep.coefficients().items():
                    A[m, k - 1] += se_m * dep.gain * c
                b[m] -= se_m * dep.gain * dep.ctrl_const
            elif e.id in cs_ids:
                A[m, M + cs_ids.index(e.id)] += se_m
    for c, cid in enumerate(cs_ids):
        for k in range(M):
            se_k = s.get((cid, k), 0)
            if se_k:
                A[M + c, k] = se_k
        if cid in result.currents_cs:
            b[M + c] = result.currents_cs[cid]
        else:
            # Bağımlı akım kaynağı: Σ s·I_m − kazanç·kontrol = kazanç·sabit
            dep = result.dependents[cid]
            for k, coef in dep.coefficients().items():
                A[M + c, k - 1] -= dep.gain * coef
            b[M + c] = dep.gain * dep.ctrl_const

    singular = ("Çevre denklemleri tekil (ör: seri bağlı iki akım kaynağı veya "
                "gerilim kaynaklarından oluşan bir çevre).")
    if result.dependents:
        singular = ("Çevre denklemleri tekil: bağımlı kaynağın kazancı denklemleri belirsiz "
                    "yapıyor (ör: kaynak, çevreyi tam dengeleyen bir kazançla kendi kontrol "
                    "büyüklüğünü besliyor) ya da devrede seri bağlı akım kaynakları / "
                    "yalnızca gerilim kaynaklarından oluşan bir çevre var; çevre akımları "
                    "tek türlü belirlenemiyor.")
    try:
        x = np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        result.reason = singular
        result.dependents = {}
        return result
    if result.dependents and (not np.all(np.isfinite(x)) or np.linalg.cond(A) > _MAX_COND):
        result.reason = singular
        result.dependents = {}
        return result

    result.mesh_currents = [complex(v) for v in x[:M]]
    result.cs_voltages = {cid: complex(x[M + c]) for c, cid in enumerate(cs_ids)}
    for e in edges:
        result.branch_currents[e.id] = sum(
            s.get((e.id, k), 0) * result.mesh_currents[k] for k in range(M))
    for dep in result.dependents.values():
        dep.ctrl_value = dep.ctrl_const + sum(
            c * result.mesh_currents[k - 1] for k, c in dep.coefficients().items())
        dep.value = dep.gain * dep.ctrl_value
    result.ok = True
    return result


def _dependent_in_meshes(
    e: ParsedElement,
    all_by_id: Dict[str, ParsedElement],
    s: Dict[Tuple[str, int], int],
    M: int,
    result: MeshAnalysis,
    is_dc: bool,
    omega: Optional[float],
) -> Optional[MeshDependent]:
    """
    Bağımlı kaynağın kontrol büyüklüğünü çevre akımlarıyla ifade eder.
    Desteklenmiyorsa None döner ve result.reason Türkçe sebebi taşır.
    """
    p = e.params
    ctrl = all_by_id.get(p["control_id"])
    kind, sigma = p["control_kind"], int(p["control_sign"])
    dep = MeshDependent(element=e, gain=float(p["gain"]), control_id=p["control_id"],
                        control_kind=kind, control_sign=sigma)
    if ctrl is None:
        result.reason = f"{e.id} bağımlı kaynağının kontrol elemanı '{p['control_id']}' bulunamadı."
        return None
    t = ctrl.element_type
    # Çizilen yöndeki eleman akımı: σ · Σ s[X][m]; çevreye girmeyen (budanmış,
    # sıfırlanmış) eleman 0 taşır
    signs = {m + 1: sigma * s[(ctrl.id, m)] for m in range(M) if s.get((ctrl.id, m))}

    if kind == "I":
        if is_dc and t == ElementType.CAPACITOR:
            result.reason = (f"{e.id} bağımlı kaynağının kontrol elemanı {ctrl.id} DC analizde "
                             "açık devredir (akımı 0); kontrol büyüklüğü çevre akımlarıyla "
                             "yazılamıyor.")
            return None
        dep.ctrl_signs = signs
        return dep

    # kind == "V": kontrol büyüklüğü bir gerilim
    if t in CURRENT_SOURCES or t in DEPENDENT_CURRENT_OUTPUT:
        result.reason = (f"{e.id} bağımlı kaynağının kontrol büyüklüğü {ctrl.id} akım "
                         "kaynağının gerilimi; çevre akımları yönteminde akım kaynağının "
                         "gerilimi ayrı bir bilinmeyendir, çevre akımlarıyla yazılamıyor.")
        return None
    if t in DEPENDENT_VOLTAGE_OUTPUT:
        result.reason = (f"{e.id} bağımlı kaynağının kontrol büyüklüğü {ctrl.id} bağımlı "
                         "gerilim kaynağının gerilimi; çevre akımlarıyla doğrudan "
                         "yazılamıyor.")
        return None
    if t in VOLTAGE_SOURCES:
        # Bağımsız gerilim kaynağının gerilimi bilinen sabittir (çizilen yönde)
        dep.ctrl_const = sigma * result.voltages[ctrl.id]
        return dep
    # Pasif eleman: V = Z · I
    if is_dc and t in (ElementType.CAPACITOR, ElementType.INDUCTOR):
        what = "açık devre (gerilimi çevre akımlarından bulunamaz)"             if t == ElementType.CAPACITOR else "kısa devre (gerilimi 0)"
        result.reason = (f"{e.id} bağımlı kaynağının kontrol elemanı {ctrl.id} DC analizde "
                         f"{what}; bu kontrol büyüklüğü çevre akımları yönteminde "
                         "desteklenmiyor.")
        return None
    z = result.impedances.get(ctrl.id)
    if z is None:
        z = _element_impedance(ctrl, is_dc, omega)
    if z is None:
        result.reason = "AC analizde frekans bilinmediği için empedanslar hesaplanamıyor."
        return None
    dep.ctrl_z = complex(z)
    dep.ctrl_signs = signs
    return dep
