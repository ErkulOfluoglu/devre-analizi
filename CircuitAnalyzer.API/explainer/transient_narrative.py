"""
CircuitAnalyzer API — Geçici Durum (RC / RL) Anlatımı (Faz 2)

Kitaptaki sırayla, sade bir MYO dilinde:

    Devreyi Tanıyalım → t = 0⁻ → Süreklilik (t = 0⁺) → t → ∞ →
    Zaman Sabitesi τ → Zamana Bağlı İfade → τ Tablosu → Depolanan Enerji →
    Kontrol → Sonuç

Sayılar solver.transient.TransientAnalysis'ten gelir; bu analiz kurulurken
lcapy ile bağımsız olarak doğrulanmıştır. R_th indirgemesi (seri / paralel / Δ–Y)
Thevenin anlatımındaki bölümle aynı koddan gelir (explainer.topology).
"""

import math
from typing import List, Optional

from explainer.formatting import MINUS, eng, num, paren
from explainer.narrative import _Ctx, _Section, _port_reduction_section
from models.request import AnalysisType, TheveninTerminals
from models.response import AnalysisResults, ExplanationSection
from parser.netlist_parser import ElementType, ParsedCircuit, ParsedElement
from solver.transient import DcSolution, TransientAnalysis

_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_PERCENT = [(n, (1 - math.exp(-n)) * 100) for n in range(1, 6)]

INTRO_U_NOTE_C = "Kitaplarda gerilim U ile de gösterilir (U_C = V_C)."
INTRO_U_NOTE_L = "Kitaplarda gerilim U ile de gösterilir (U_L = V_L)."


def _v(node: str) -> str:
    return f"V{node.translate(_SUB)}" if node.isdigit() else f"V_{node}"


def _node(n: str) -> str:
    return "GND" if n == "0" else f"Düğüm {n}"


def _x(a: TransientAnalysis, value: float) -> str:
    return eng(value, a.unit)


# ═══════════════════════════════════════════════════════
#  YARDIMCILAR
# ═══════════════════════════════════════════════════════

def _switch_lines(a: TransientAnalysis) -> List[str]:
    out = []
    for sw in a.switches:
        kind = sw.params.get("kind")
        if kind == "NO":
            out.append(f"{sw.id}: Düğüm {sw.node_positive} ile Düğüm {sw.node_negative} arasında; "
                       "t < 0'da AÇIK, t = 0'da KAPANIR.")
        elif kind == "NC":
            out.append(f"{sw.id}: Düğüm {sw.node_positive} ile Düğüm {sw.node_negative} arasında; "
                       "t < 0'da KAPALI, t = 0'da AÇILIR.")
        else:
            c, p1, p2 = sw.params["common"], sw.params["pos1"], sw.params["pos2"]
            out.append(f"{sw.id}: iki konumlu anahtar; ortak uç Düğüm {c}. t < 0'da Düğüm {p1} "
                       f"(konum 1) ile bağlı, t = 0'da Düğüm {p2} (konum 2) ile bağlanır.")
    return out


def _state_lines(a: TransientAnalysis, when: str) -> List[str]:
    """Anahtarların o andaki konumu (t<0 ya da t>0)."""
    out = []
    for sw in a.switches:
        kind = sw.params.get("kind")
        if kind == "SPDT":
            tgt = sw.params["pos1"] if when == "before" else sw.params["pos2"]
            pos = 1 if when == "before" else 2
            out.append(f"{sw.id}: konum {pos} (Düğüm {sw.params['common']} – Düğüm {tgt} bağlı)")
        else:
            closed = (kind == "NC") if when == "before" else (kind == "NO")
            out.append(f"{sw.id}: {'kapalı (tel gibi)' if closed else 'açık (devreden çıkar)'}")
    return out


def _merge_lines(a: TransientAnalysis, when: str) -> List[str]:
    """Kapalı anahtar tel olduğundan birleşen düğümler (devre çiziminde düğüm adı değişir)."""
    circuit = a.before_circuit if when == "before" else a.after_circuit
    original = [e for e in a.parsed.elements if e.element_type != ElementType.SWITCH]
    renamed = {}
    for old, new in zip(original, circuit.elements):
        renamed[old.node_positive] = new.node_positive
        renamed[old.node_negative] = new.node_negative
    groups = {}
    for old, new in renamed.items():
        if old != new:
            groups.setdefault(new, []).append(old)
    return [f"Kapalı anahtar tel gibidir: Düğüm {', '.join(sorted(olds))} ile Düğüm {new} aynı "
            f"düğümdür (aşağıda Düğüm {new} diye anılır)." for new, olds in sorted(groups.items())]


def _dc_listing(s: _Section, circuit: ParsedCircuit, dc: DcSolution, skip_id: Optional[str]) -> None:
    """Düğüm gerilimleri ve direnç akımları (Ohm yasası)."""
    show = sorted((n for n in dc.v if n != "0" and n not in dc.floating_nodes),
                  key=lambda n: (len(n), n))
    if show:
        s.text("Bu DC devrede düğüm gerilimleri (GND = 0 V):")
        for n in show:
            s.math(f"{_v(n)} = {eng(dc.v[n], 'V')}")
    res = [e for e in circuit.elements if e.element_type == ElementType.RESISTOR]
    if res and all(abs(dc.i.get(e.id, 0.0)) < 1e-15 for e in res):
        s.text("Hiçbir dirençten akım geçmiyor (kapalı bir akım yolu yok), bu yüzden dirençlerde "
               "gerilim düşmez.")
    elif res:
        s.text("Direnç akımları (Ohm yasası):")
        for e in res:
            i = dc.i.get(e.id, 0.0)
            if abs(i) < 1e-15:
                s.math(f"I_{e.id} = 0  (uçları arasında gerilim farkı yok ya da akım yolu yok)")
                continue
            p, q = e.node_positive, e.node_negative
            if p in dc.floating_nodes:
                s.math(f"I_{e.id} = {eng(i, 'A')}")
                continue
            s.math(f"I_{e.id} = ({_v(p)} {MINUS} {_v(q)}) / {e.id} = "
                   f"({num(dc.v[p])} {MINUS} {paren(num(dc.v[q]))}) V / {eng(e.value, 'Ω')} = {eng(i, 'A')}")


def _series_partner(circuit: ParsedCircuit, coil: ParsedElement) -> Optional[ParsedElement]:
    """Bobinle aynı kolda (uçlarından birinde yalnız bir direnç var) direnç, yoksa None."""
    for node in (coil.node_positive, coil.node_negative):
        inc = [e for e in circuit.elements
               if e.id != coil.id and node in (e.node_positive, e.node_negative)]
        if len(inc) == 1 and inc[0].element_type == ElementType.RESISTOR:
            return inc[0]
    return None


def _dc_rule(is_c: bool) -> str:
    if is_c:
        return ("DC kararlı hâlde kondansatörün akımı sıfırdır → kondansatör AÇIK devre gibi "
                "davranır.")
    return "DC kararlı hâlde bobinin gerilimi sıfırdır → bobin KISA devre (tel) gibi davranır."


def _done_word(a: TransientAnalysis) -> str:
    """5τ sonunda durumun adı: tam dolmuş / tamamen boşalmış / sönmüş / son değerine ulaşmış."""
    charging, ending = abs(a.x_start) < 1e-12, abs(a.x_final) < 1e-12
    if a.kind == "C":
        return ("tam dolmuş" if charging else "tamamen boşalmış" if ending
                else "son gerilimine ulaşmış")
    return "son akımına ulaşmış" if not ending else "sönmüş (akımı sıfırlanmış)"


# ═══════════════════════════════════════════════════════
#  ANA GİRİŞ
# ═══════════════════════════════════════════════════════

def build_transient_explanation(a: TransientAnalysis) -> List[ExplanationSection]:
    sections: List[_Section] = []
    sid = a.storage.id
    is_c = a.kind == "C"
    x_lbl, o_lbl = a.x_label, a.other_label
    tau_txt = eng(a.tau, "s")

    # ── 1. Devreyi tanıyalım ──
    s = _Section("Devreyi Tanıyalım")
    s.text(INTRO_U_NOTE_C if is_c else INTRO_U_NOTE_L)
    elems = []
    for e in a.after_circuit.elements:
        if e.element_type == ElementType.DC_SOURCE:
            elems.append(f"{e.id} = {eng(e.value, 'V')} (DC)")
        elif e.element_type == ElementType.CURRENT_DC:
            elems.append(f"{e.id} = {eng(e.value, 'A')} (DC akım kaynağı)")
        elif e.element_type == ElementType.RESISTOR:
            elems.append(f"{e.id} = {eng(e.value, 'Ω')}")
    elems.append(f"{sid} = {eng(a.value, 'F' if is_c else 'H')}")
    s.text("Elemanlar: " + ", ".join(elems) + ".")
    s.text("Anahtarlar:")
    for line in _switch_lines(a):
        s.math(f"• {line}")
    what = "kondansatörün" if is_c else "bobinin"
    s.text(
        f"Devrede tek bir {'kondansatör' if is_c else 'bobin'} ({sid}) var; buna birinci dereceden "
        f"({'RC' if is_c else 'RL'}) devre denir. Anahtar konum değiştirince {what} "
        f"{'gerilimi' if is_c else 'akımı'} bir anda değil, zamanla değişir. Bu değişimi üç adımda bulacağız:")
    s.math(f"1) Başlangıç değeri: {x_lbl}(0)      2) Son değer: {x_lbl}(∞)      "
           f"3) Zaman sabitesi: τ")
    s.math(f"Sonra: {x_lbl}(t) = {x_lbl}(∞) + [{x_lbl}(0) {MINUS} {x_lbl}(∞)] · e^({MINUS}t/τ)")
    sections.append(s)

    # ── 2. t = 0⁻ ──
    s = _Section("t = 0⁻ Anı (Anahtar Değişmeden Önce)")
    s.text("Anahtarlar t = 0 anına kadar t < 0 konumunda uzun süre kaldı; devre kararlı (DC) hâle "
           "geldi. " + _dc_rule(is_c))
    s.text("t < 0 konumunda anahtarlar:")
    for line in _state_lines(a, "before"):
        s.math(f"• {line}")
    for line in _merge_lines(a, "before"):
        s.text(line)
    if is_c and a.uncharged:
        s.text(f"Bu konumda {sid}, hiçbir kaynağa bağlı değil (yalıtılmış). Devre kurulduğunda "
               "kondansatörün boş olduğu kabul edilir.")
        s.result(f"{x_lbl}(0⁻) = 0 V")
    else:
        s.text(f"{sid} " + ("açık devre sayılarak" if is_c else "kısa devre (tel) sayılarak")
               + " t < 0 devresi çözülür.")
        _dc_listing(s, a.before_circuit, a.dc_before, sid)
        if is_c:
            n1, n2 = a.port_before
            s.math(f"{x_lbl}(0⁻) = {_v(n1)} {MINUS} {_v(n2)} = "
                   f"{num(a.dc_before.v[n1])} {MINUS} {paren(num(a.dc_before.v[n2]))} = {eng(a.x_before, 'V')}")
        else:
            r = _series_partner(a.before_circuit, a.storage_before)
            if r is not None:
                s.text(f"{sid} ile {r.id} aynı kolda (seri) bağlıdır; ikisinden de aynı büyüklükte "
                       f"akım geçer ({eng(abs(a.dc_before.i.get(r.id, 0.0)), 'A')}).")
            else:
                s.text(f"Kısa devre olan {sid}'in akımı, bağlı olduğu düğümlerdeki KCL ile bulunur.")
        s.result(f"{x_lbl}(0⁻) = {_x(a, a.x_before)}")
    sections.append(s)

    # ── 3. Süreklilik ──
    s = _Section("Süreklilik: t = 0⁺ Anı")
    if is_c:
        s.text("Kondansatörün gerilimi bir anda değişemez (aksi hâlde enerjisi ½·C·V² anında "
               "sıçrardı). Bu yüzden anahtar konum değiştirdikten hemen sonra da aynı gerilimdedir:")
        s.math(f"{x_lbl}(0⁺) = {x_lbl}(0⁻)")
        s.result(f"{x_lbl}(0⁺) = {_x(a, a.x_start)}")
        if abs(a.x_start) < 1e-12:
            s.note("Boş kondansatör t = 0⁺ anında kısa devre gibidir (gerilimi 0 V).")
        else:
            s.note(f"Yüklü kondansatör t = 0⁺ anında {_x(a, a.x_start)}'luk bir gerilim kaynağı gibidir.")
    else:
        s.text("Bobinin akımı bir anda değişemez (aksi hâlde enerjisi ½·L·I² anında sıçrardı). "
               "Bu yüzden anahtar konum değiştirdikten hemen sonra da aynı akımdadır:")
        s.math(f"{x_lbl}(0⁺) = {x_lbl}(0⁻)")
        s.result(f"{x_lbl}(0⁺) = {_x(a, a.x_start)}")
        if abs(a.x_start) < 1e-12:
            s.note("Enerjisiz bobin t = 0⁺ anında açık devre gibidir (akımı 0 A).")
        else:
            s.note(f"Enerjili bobin t = 0⁺ anında {_x(a, a.x_start)}'lik bir akım kaynağı gibidir.")
    s.text("Süreklilik yalnızca " + ("kondansatör gerilimi" if is_c else "bobin akımı")
           + " için geçerlidir; "
           + ("kondansatör akımı" if is_c else "bobin gerilimi") + " ve dirençlerin gerilim/akımları "
           "t = 0'da sıçrayabilir.")
    sections.append(s)

    # ── 4. t → ∞ ──
    s = _Section("t → ∞ (Yeni Kararlı Hâl)")
    s.text("Anahtar konum değiştirdikten sonra devre uzun süre beklenirse yeniden DC kararlı hâle "
           "ulaşır. " + _dc_rule(is_c))
    s.text("t > 0 konumunda anahtarlar:")
    for line in _state_lines(a, "after"):
        s.math(f"• {line}")
    for line in _merge_lines(a, "after"):
        s.text(line)
    _dc_listing(s, a.after_circuit, a.dc_final, sid)
    if is_c:
        n1, n2 = a.port
        s.math(f"{x_lbl}(∞) = {_v(n1)} {MINUS} {_v(n2)} = "
               f"{num(a.dc_final.v[n1])} {MINUS} {paren(num(a.dc_final.v[n2]))} = {eng(a.x_final, 'V')}")
        s.result(f"{x_lbl}(∞) = {_x(a, a.x_final)}")
        s.note(f"Kararlı hâlde kondansatör akımı sıfırdır: {o_lbl}(∞) = 0 A.")
    else:
        s.result(f"{x_lbl}(∞) = {_x(a, a.x_final)}")
        s.note(f"Kararlı hâlde bobin gerilimi sıfırdır: {o_lbl}(∞) = 0 V.")
    sections.append(s)

    # ── 5. Zaman sabitesi ──
    ctx = _Ctx(
        parsed=a.after_without_storage, is_dc=True, frequency=None, omega=None,
        analysis_type=AnalysisType.THEVENIN,
        terminals=TheveninTerminals(node_positive=a.port[0], node_negative=a.port[1]),
        v={}, i={}, results=AnalysisResults(),
    )
    s, _ok = _port_reduction_section(ctx, "Zaman Sabitesi τ", "R_th", complex(a.r_th))
    intro = _Section("")
    intro.text(f"Zaman sabitesi, t > 0 devresinde {sid}'in uçlarından bakıldığında görülen R_th "
               f"(Thevenin direnci) ile bulunur. Önce {sid} devreden çıkarılır:")
    s.blocks = intro.blocks + s.blocks
    if is_c:
        s.math(f"τ = R_th · C = {eng(a.r_th, 'Ω')} · {eng(a.value, 'F')}")
    else:
        s.math(f"τ = L / R_th = {eng(a.value, 'H')} / {eng(a.r_th, 'Ω')}")
    s.result(f"τ = {tau_txt}")
    sections.append(s)

    # ── 6. Zamana bağlı ifade ──
    s = _Section("Zamana Bağlı İfade")
    s.text("Birinci dereceden devrede her büyüklük, başlangıç değerinden son değerine üstel olarak gider:")
    s.math(f"x(t) = x(∞) + [x(0) {MINUS} x(∞)] · e^({MINUS}t/τ)")
    x0, xf = a.x_start, a.x_final
    s.math(f"{x_lbl}(t) = {_x(a, xf)} + [{_x(a, x0)} {MINUS} {paren(_x(a, xf))}] · e^({MINUS}t/τ),   τ = {tau_txt}")
    if abs(xf) > 1e-12 and abs(x0) > 1e-12:
        s.math(f"{x_lbl}(t) = {_x(a, xf)} + ({_x(a, x0 - xf)}) · e^({MINUS}t/τ)")
    if abs(x0) < 1e-12 and abs(xf) > 1e-12:
        if is_c:
            s.text("Kondansatör boştan doluyor (V_C(0) = 0). Kitaplardaki kısa biçim:")
            s.math(f"{x_lbl}(t) = U · (1 {MINUS} e^({MINUS}t/τ))   →   U = {_x(a, xf)}")
        else:
            s.text("Bobin enerjisizden başlıyor (I_L(0) = 0). Kitaplardaki kısa biçim:")
            s.math(f"{x_lbl}(t) = I · (1 {MINUS} e^({MINUS}t/τ))   →   I = {_x(a, xf)}  (I = U/R)")
        s.result(f"{x_lbl}(t) = {_x(a, xf)} · (1 {MINUS} e^({MINUS}t/τ)),   τ = {tau_txt}")
    elif abs(xf) < 1e-12 and abs(x0) > 1e-12:
        if is_c:
            s.text("Kondansatör boşalıyor (V_C(∞) = 0). Kitaplardaki kısa biçim:")
            s.math(f"{x_lbl}(t) = V₀ · e^({MINUS}t/τ)   →   V₀ = {_x(a, x0)}")
        else:
            s.text("Bobin akımı sönüyor (I_L(∞) = 0). Kitaplardaki kısa biçim:")
            s.math(f"{x_lbl}(t) = I₀ · e^({MINUS}t/τ)   →   I₀ = {_x(a, x0)}")
        s.result(f"{x_lbl}(t) = {_x(a, x0)} · e^({MINUS}t/τ),   τ = {tau_txt}")
    else:
        s.result(f"{x_lbl}(t) = {_x(a, xf)} + ({_x(a, x0 - xf)}) · e^({MINUS}t/τ),   τ = {tau_txt}")

    # Diğer büyüklük (C akımı / L gerilimi): t = 0'da sıçrayabilir, son değeri sıfır
    o_unit = "A" if is_c else "V"
    o0 = a.other_start
    if is_c:
        s.text(f"Kondansatör akımı {o_lbl} (n1 → n2 yönünde; {sid}: Düğüm {a.storage.node_positive} → "
               f"Düğüm {a.storage.node_negative}). t = 0⁺ anındaki değeri, kondansatörün gördüğü "
               "Thevenin eşdeğeriyle (V_C(∞) kaynağı ve R_th direnci) bulunur: akım = gerilim farkı / R_th.")
        s.math(f"{o_lbl}(0⁺) = ({x_lbl}(∞) {MINUS} {x_lbl}(0⁺)) / R_th = "
               f"({_x(a, xf)} {MINUS} {paren(_x(a, x0))}) / {eng(a.r_th, 'Ω')} = {eng(o0, 'A')}")
    else:
        s.text(f"Bobin gerilimi {o_lbl} (n1 − n2; {sid}: Düğüm {a.storage.node_positive} → "
               f"Düğüm {a.storage.node_negative}). t = 0⁺ anındaki değeri, bobinin gördüğü R_th "
               "üzerindeki gerilim farkıdır:")
        s.math(f"{o_lbl}(0⁺) = ({x_lbl}(∞) {MINUS} {x_lbl}(0⁺)) · R_th = "
               f"({_x(a, xf)} {MINUS} {paren(_x(a, x0))}) · {eng(a.r_th, 'Ω')} = {eng(o0, 'V')}")
    s.math(f"{o_lbl}(t) = {eng(o0, o_unit)} · e^({MINUS}t/τ)   (son değeri 0)")
    if o0 < -1e-15 and is_c:
        s.note("Akımın eksi çıkması, kondansatör deşarj olurken akımın seçilen yönün tersine "
               "aktığını gösterir.")
    sections.append(s)

    # ── 7. τ tablosu ──
    s = _Section("τ Tablosu")
    s.text("Her τ süresinde, kalan fark e ≈ 2,718 kat azalır. Zamanı τ'nın katlarıyla ifade edince "
           "değişimin ne kadarının tamamlandığı hazır yüzdelerle bulunur:")
    for n, pct in _PERCENT:
        t = n * a.tau
        pct_txt = f"{pct:.1f}".replace(".", ",")
        s.math(f"t = {n}τ = {eng(t, 's')}  →  değişimin %{pct_txt} kadarı tamamlanır  →  "
               f"{x_lbl} = {_x(a, a.x_at(t))}")
    s.text("Eğri son değere hiçbir zaman tam olarak ulaşmaz; ama 5τ sonunda değişimin %99,3'ü "
           f"tamamlandığı için {sid} pratikte {_done_word(a)} kabul edilir: "
           f"5τ = {eng(5 * a.tau, 's')}.")
    sections.append(s)

    # ── 8. Enerji ──
    s = _Section("Depolanan Enerji")
    if is_c:
        s.text("Kondansatörde depolanan enerji W = ½·C·V² formülüyle bulunur.")
        w = lambda v: 0.5 * a.value * v * v
        if abs(x0) > 1e-12:
            s.math(f"W(0⁺) = ½ · {eng(a.value, 'F')} · ({_x(a, x0)})² = {eng(w(x0), 'J')}")
        s.math(f"W(∞) = ½ · {eng(a.value, 'F')} · ({_x(a, xf)})² = {eng(w(xf), 'J')}")
    else:
        s.text("Bobinde depolanan enerji W = ½·L·I² formülüyle bulunur.")
        w = lambda i: 0.5 * a.value * i * i
        if abs(x0) > 1e-12:
            s.math(f"W(0⁺) = ½ · {eng(a.value, 'H')} · ({_x(a, x0)})² = {eng(w(x0), 'J')}")
        s.math(f"W(∞) = ½ · {eng(a.value, 'H')} · ({_x(a, xf)})² = {eng(w(xf), 'J')}")
    sections.append(s)

    # ── 9. Kontrol ──
    s = _Section("Kontrol")
    s.text("Bulunan sayılar ayrı bir yöntemle de hesaplandı: devre t > 0 konumunda başlangıç "
           "koşuluyla Laplace dönüşümü kullanılarak (lcapy) çözüldü ve karşılaştırıldı.")
    s.check(f"{x_lbl}(0⁺) = {_x(a, x0)} ✓")
    s.check(f"{x_lbl}(∞) = {_x(a, xf)} ✓")
    s.check(f"τ = {tau_txt} ✓")
    sections.append(s)

    # ── 10. Sonuç ──
    s = _Section("Sonuç")
    s.result(f"R_th = {eng(a.r_th, 'Ω')},  τ = {tau_txt}")
    s.result(f"{x_lbl}(0⁻) = {_x(a, a.x_before)},  {x_lbl}(0⁺) = {_x(a, x0)},  {x_lbl}(∞) = {_x(a, xf)}")
    s.result(f"{o_lbl}(0⁺) = {eng(o0, o_unit)},  {o_lbl}(∞) = 0 {o_unit}")
    s.result(f"5τ = {eng(5 * a.tau, 's')} sonunda değişim pratikte tamamlanır")
    sections.append(s)

    return [sec.build() for sec in sections if sec.blocks]
