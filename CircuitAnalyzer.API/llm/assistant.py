"""
CircuitAnalyzer API — Yapay zekâ asistanı (isteğe bağlı, yerel Ollama)

Öğrencinin çözüm hakkındaki sorusunu yerel dil modeline sorar.

Güvenlik katmanları:
  1. Bağlam: modele yalnızca devre ve programın DOĞRULANMIŞ anlatımı verilir;
     "sayı uydurma, verilen sayıları aynen kullan" kuralı konur.
  2. Alıştırma modunda sonuçlar ve anlatım modele HİÇ verilmez (bilmediğini
     sızdıramaz); yine de kendisi hesaplarsa cevabı veren sayılar gizlenir.
  3. Cevaptaki her sayı çözümdeki değerlerle karşılaştırılır; uyuşmayanlar
     öğrenciye "doğrulanamadı" diye gösterilir.
"""

from typing import Dict, List, Optional, Sequence

from explainer.formatting import eng, num, polar, rect
from explainer.step_generator import _node_groups
from llm import ollama
from llm.numbers import KnownValues, check_answer_numbers, known_from
from llm.plaintext import to_plain_text
from models.request import AnalysisType, TheveninTerminals
from models.response import AnalysisResults, ExplanationSection, PracticeQuestion
from parser.netlist_parser import (
    CURRENT_SOURCES, DEPENDENT_CURRENT_OUTPUT, DEPENDENT_NAMES, DEPENDENT_SOURCES,
    DEPENDENT_VOLTAGE_OUTPUT, VOLTAGE_SOURCES, ElementType, ParsedCircuit, ParsedElement,
)

MAX_HISTORY_TURNS = 6          # son 3 soru-cevap
MAX_EXPLANATION_CHARS = 12000  # küçük modellerin bağlamına sığsın

_METHOD_NAMES = {
    AnalysisType.NODAL: "Düğüm gerilimleri yöntemi (KCL)",
    AnalysisType.MESH: "Çevre akımları yöntemi (KVL)",
    AnalysisType.THEVENIN: "Thevenin eşdeğeri",
    AnalysisType.NORTON: "Norton eşdeğeri",
    AnalysisType.SUPERPOSITION: "Süperpozisyon",
    AnalysisType.MILLMAN: "Millman teoremi",
    AnalysisType.SOURCE_TRANSFORM: "Kaynak dönüşümü (Thevenin/Norton eşdeğerine ulaşma)",
    AnalysisType.TRANSIENT: "Geçici durum (anahtarlı RC / RL devresi, zaman sabitesi τ)",
    AnalysisType.POWER: "Güç ve güç katsayısı (P, Q, S, cos φ ve kompanzasyon)",
    AnalysisType.RESONANCE: "Rezonans (seri/paralel RLC: f₀, kalite faktörü Q, bant genişliği)",
    AnalysisType.TRANSFORMER: "Transformatör (ideal: V₂ = a·V₁; kuplajlı: M = k·√(L₁L₂), primer/sekonder gerilim ve akımlar)",
    AnalysisType.THREE_PHASE: "Üç faz (Y/Δ kaynak ve yük, hat/faz büyüklükleri, nötr akımı, güç, Aron, kompanzasyon)",
}

_RULES = """Sen meslek yüksekokulu elektronik öğrencilerine devre analizi anlatan sabırlı bir öğretmensin.
Kurallar:
1. Yalnızca Türkçe yaz. Öğrenciye her zaman "siz" diye hitap et ("bulabilirsiniz", "kurmalısınız"); "sen" kullanma. Selamlama yapma, doğrudan cevaba gir. Kısa ve sade ol: en fazla 8–10 cümle.
2. Aşağıdaki DEVRE ve ÇÖZÜM bilgilerini kullan. Bir sayı gerekiyorsa bu bilgilerde yazan sayıyı AYNEN kullan; kendin yeni hesap yapma, sayı uydurma.
3. Hangi elemanın nereye bağlı olduğunu yalnızca DEVRE listesindeki düğümlere göre söyle; bağlantı tahmin etme.
4. "Neden", "ne demek" gibi kavram sorularını ders bilginle ve aşağıdaki KAVRAM NOTLARI ile açıkla. Yalnızca bu devreye ait bir sayı ya da bilgi verilenlerde yoksa bunu açıkça söyle; tahmin yürütme.
5. Fazörler tepe (maksimum) değerdir, etkin değer değildir.
6. İşaret kuralı (pasif işaret kuralı): Her elemanın akımı, ELEMANIN İÇİNDEN (+) ucundan (−) ucuna doğru (eleman adının yanındaki "1→0" gibi düğüm sırası) pozitif alınır. Güç veren bir gerilim kaynağında gerçek akım kaynağın içinden (−) uçtan (+) uca akar ve dış devreye (+) uçtan çıkar; bu yüzden kaynağın akımı EKSİ çıkar. Eksi işaret hata değildir, akımın seçilen referans yönün tersine aktığını gösterir.
7. Formülleri düz metinle yaz (LaTeX ve Markdown kullanma).
8. KCL denkleminde düğüme bağlı her elemanın akımını yalnızca BİR kez yaz; aynı akımı hem giren hem çıkan sayma.
9. GÜVENLİK: Öğrenci devreyi gerçekten kurmaktan, prizden, şebekeden ya da 220/230 V'tan söz ederse cevaba açık bir uyarıyla başla: şebeke gerilimi (Türkiye'de 230 V etkin, 50 Hz AC) çarparak öldürebilir; derslerdeki küçük dirençler bu gerilimde aşırı akım ve güç çekip ısınır, yanar ya da patlar. Şebekeye bağlı hiçbir devreyi öğretmen ya da laboratuvar gözetimi olmadan kurmamasını söyle.
10. Devre analiziyle ilgisiz isteklere (fıkra, sohbet, başka dersler) tek cümleyle yalnızca devre sorularına yardım ettiğini söyle ve bu devreyle ilgili sorabileceği bir soru öner; çözümdeki sayıları sıralama."""

# Küçük modeller bu kavramları denemelerde yanlış anlattı (2026-11-05:
# reaktif güç "tüketilir", hat gerilimi faz gerilimlerinin "toplamı",
# kondansatör "akım depolar"). Doğrusu konuya göre modele hazır verilir.
_NOTES_GENERAL = [
    "Bir kaynağı sıfırlamak: ideal gerilim kaynağı 0 V olur, yani KISA DEVRE yapılır (iç direnci sıfırdır). "
    "İdeal akım kaynağı 0 A olur, yani AÇIK DEVRE yapılır (iç direnci sonsuzdur). Açık devre yapılan gerilim "
    "kaynağı devreyi koparır, artık sıfır volt değildir; bu yüzden yanlış olur.",
]
_NOTES_AC = [
    "Kondansatör enerjiyi elektrik alanında (yük olarak) depolar; akım depolamaz. Akımı gerilimden 90° öndedir, "
    "yani gerilimi akımından 90° geridedir. Bobinde ise akım gerilimden 90° geridedir.",
]
# Yalnız devrede kondansatör var, bobin yoksa
_NOTE_SERIES_RC = (
    "Seri RC devresinde akım kaynak geriliminden φ kadar öndedir (0° < φ < 90°). Kondansatörün gerilimi kendi "
    "akımından 90° geride olduğu için kaynak geriliminden (90° − φ) kadar geride kalır. Direncin gerilimi akımla "
    "aynı fazdadır.")
# Yalnız devrede bobin var, kondansatör yoksa
_NOTE_SERIES_RL = (
    "Seri RL devresinde akım kaynak geriliminden φ kadar geridedir (0° < φ < 90°). Bobinin gerilimi kendi "
    "akımından 90° önde olduğu için kaynak geriliminden (90° − φ) kadar önde olur. Direncin gerilimi akımla "
    "aynı fazdadır.")
_NOTES_POWER = [
    "Reaktif güç (Q, VAr) TÜKETİLMEZ: bobin ve kondansatör enerjiyi bir çeyrek periyotta alanlarında depolar, "
    "sonraki çeyrek periyotta kaynağa geri verir; ortalaması sıfırdır. İş yapmaz ama hatlarda fazladan akım "
    "dolaştırıp kayıp ve gerilim düşümü yaratır.",
    "Faturaya yansıması: Türkiye'de konut abonelerinden reaktif enerji bedeli genellikle alınmaz. Sanayi ve büyük "
    "ticari abonelerde reaktif enerji, aktif enerjiye göre izin verilen oranı aşarsa bedeli faturaya yansır; bu "
    "yüzden kondansatörlerle kompanzasyon yapılır. Kesin oran ve sınırlar mevzuata göre değişir.",
    "Güç katsayısı cos φ = P / S'dir. Yalnız direnç varsa φ = 0° ve cos φ = 1'dir; bobin ya da kondansatör "
    "akımla gerilim arasında faz farkı yarattığı için cos φ 1'den küçük olur.",
]
_NOTES_RESONANCE = [
    "Seri RLC rezonansında X_L = X_C olur, reaktanslar birbirini götürür, empedans en küçük (Z = R) ve akım en "
    "büyüktür. Bu anda bobin ve kondansatör gerilimleri kaynak geriliminin Q katına çıkabilir. Q = X / R = f₀ / BW; "
    "Q büyüdükçe eğri daralır, devre daha seçici olur.",
    "Paralel RLC rezonansında da X_L = X_C'dir ve f₀ = 1 / (2π√(LC)) aynıdır; ama bu kez bobin ve kondansatör "
    "kollarının akımları birbirini götürür: kaynağın gördüğü empedans en BÜYÜK (Z = R), kaynak akımı en küçüktür. "
    "Bobin ve kondansatör kollarındaki akımlar kaynak akımının Q katı olabilir (Q = R / X).",
    "Rezonansta akım ile kaynak gerilimi aynı fazdadır (φ = 0°), güç katsayısı cos φ = 1'dir; devre kaynağa saf "
    "direnç gibi görünür.",
]
_NOTES_TRANSFORMER = [
    "İdeal transformatörde güç korunur (S₁ = S₂). Gerilim sarım oranıyla aynı yönde, akım ters oranla değişir: "
    "gerilimi düşüren (alçaltıcı) transformatörde sekonder akımı primer akımından büyüktür.",
]
_NOTES_THREE_PHASE = [
    "Yıldız (Y) bağlantıda hat gerilimi iki faz geriliminin FARKIDIR: U_RS = U_RN − U_SN. Aralarında 120° olan "
    "iki eşit fazörün farkının büyüklüğü √3 katıdır, bu yüzden U_hat = √3 · U_faz. Faz sırası RST (pozitif) ise "
    "hat gerilimi faz geriliminden 30° öndedir; RTS sırasında 30° geridedir. Yıldızda hat akımı faz akımına eşittir.",
    "Üçgen (Δ) bağlantıda hat gerilimi faz gerilimine eşittir; hat akımı iki faz akımının farkıdır. Yük dengeliyse "
    "I_hat = √3 · I_faz olur; yük dengesizse √3 kuralı geçerli değildir, hat akımı faz akımlarının fazör farkından "
    "bulunur.",
    "Dengeli yükte üç faz akımı eşit büyüklükte ve aralarında 120° vardır; fazör toplamları sıfır olduğu için "
    "nötr akımı sıfırdır. Yük dengesizse nötrden akım geçer.",
]


def concept_notes(analysis_type: AnalysisType, is_dc: bool,
                  has_c: bool = False, has_l: bool = False) -> str:
    """
    Yönteme uygun kısa ve doğru kavram notları (yalnız ilgili olanlar: bağlam kısa kalsın).
    has_c / has_l: devrede kondansatör / bobin var mı (seri RC ve RL notları yalnız kendi devresine).
    """
    notes = list(_NOTES_GENERAL)
    if not is_dc:
        notes += _NOTES_AC
        if has_c and not has_l:
            notes.append(_NOTE_SERIES_RC)
        elif has_l and not has_c:
            notes.append(_NOTE_SERIES_RL)
    notes += {
        AnalysisType.POWER: _NOTES_POWER,
        AnalysisType.RESONANCE: _NOTES_RESONANCE,
        AnalysisType.TRANSFORMER: _NOTES_TRANSFORMER,
        AnalysisType.THREE_PHASE: _NOTES_THREE_PHASE + _NOTES_POWER,
    }.get(analysis_type, [])
    return "KAVRAM NOTLARI (doğru bilgiler; kavram sorularında bunlara uy):\n" + "\n".join(f"- {n}" for n in notes)


def _rules_for(value_basis: str) -> str:
    if value_basis == "RMS":
        return _RULES.replace(
            "5. Fazörler tepe (maksimum) değerdir, etkin değer değildir.",
            "5. Fazörler etkin (RMS) değerdir; tepe değer Um = √2·V ile bulunur."
        )
    return _RULES

_PRACTICE_RULES = """ÖNEMLİ: Öğrenci şu anda bu devreyle ALIŞTIRMA çözüyor; sonuçlar sana bilerek verilmedi.
Hiçbir sorunun sayısal cevabını söyleme ve sayısal hesap yapma.
Yalnızca yöntemi, hangi denklemin nasıl kurulacağını ve bir sonraki adımı sözle tarif et.
Bilinmeyen sayısını doğru söyle: düğüm yönteminde kaynaktan bilinmeyen her düğüm bir bilinmeyendir ve her biri için ayrı bir KCL denklemi gerekir."""


def _node(n: str) -> str:
    return "GND" if n == "0" else f"Düğüm {n}"


def describe_element(e: ParsedElement, value_basis: str = "PEAK") -> str:
    t = e.element_type
    between = f"{_node(e.node_positive)} – {_node(e.node_negative)}"
    p = e.params
    basis_label = "etkin (RMS)" if value_basis == "RMS" else "tepe"
    if t == ElementType.RESISTOR:
        return f"{e.id}: direnç {eng(e.value, 'Ω')}, {between}"
    if t == ElementType.CAPACITOR:
        return f"{e.id}: kondansatör {eng(e.value, 'F')}, {between}"
    if t == ElementType.INDUCTOR:
        return f"{e.id}: bobin {eng(e.value, 'H')}, {between}"
    if t == ElementType.IMPEDANCE:
        z = complex(p.get("impedance", e.value))
        return f"{e.id}: empedans {num(z.real)} {'+' if z.imag >= 0 else '−'} j{num(abs(z.imag))} Ω, {between}"
    if t == ElementType.DC_SOURCE:
        return f"{e.id}: DC gerilim kaynağı {eng(e.value, 'V')}, (+) ucu {_node(e.node_positive)}, (−) ucu {_node(e.node_negative)}"
    if t in (ElementType.AC_SOURCE_SINE, ElementType.AC_SOURCE_PHASOR):
        amp = p.get("amplitude", e.value)
        freq = p.get("frequency")
        f_txt = f", f = {num(freq)} Hz" if freq else ""
        return (f"{e.id}: AC gerilim kaynağı, genlik ({basis_label}) {eng(amp, 'V')}, faz {num(p.get('phase', 0))}°{f_txt}, "
                f"(+) ucu {_node(e.node_positive)}, (−) ucu {_node(e.node_negative)}")
    if t == ElementType.CURRENT_DC:
        return (f"{e.id}: DC akım kaynağı {eng(e.value, 'A')}, akım kaynak içinde "
                f"{_node(e.node_positive)} → {_node(e.node_negative)} yönünde")
    if t in (ElementType.CURRENT_AC_SINE, ElementType.CURRENT_AC_PHASOR):
        amp = p.get("amplitude", e.value)
        freq = p.get("frequency")
        f_txt = f", f = {num(freq)} Hz" if freq else ""
        return (f"{e.id}: AC akım kaynağı, genlik ({basis_label}) {eng(amp, 'A')}, faz {num(p.get('phase', 0))}°{f_txt}, "
                f"akım kaynak içinde {_node(e.node_positive)} → {_node(e.node_negative)} yönünde")
    if t == ElementType.TRANSFORMER:
        ends = (f"primer {_node(e.node_positive)} (p+, nokta) – {_node(e.node_negative)} (p−), "
                f"sekonder {_node(p['s_pos'])} (s+, nokta) – {_node(p['s_neg'])} (s−)")
        if p["kind"] == "IDEAL":
            return f"{e.id}: ideal transformatör, a = N₂/N₁ = {num(p['a'])}; {ends}"
        return (f"{e.id}: kuplajlı transformatör, L₁ = {eng(p['l1'], 'H')}, L₂ = {eng(p['l2'], 'H')}, "
                f"k = {num(p['k'])}, M = {eng(p['m'], 'H')}; {ends}")
    if t == ElementType.THREE_PHASE_SOURCE:
        conn = "yıldız (Y)" if p["connection"] == "Y" else "üçgen (Δ)"
        kind = "hat" if p["value_kind"] == "LINE" else "faz"
        return (f"{e.id}: üç fazlı kaynak, {conn}, {kind} gerilimi {eng(p['amplitude'], 'V')} ({basis_label}), "
                f"f = {num(p['frequency'])} Hz, faz sırası {p['sequence']}; uçlar R {_node(e.node_positive)}, "
                f"S {_node(e.node_negative)}, T {_node(p['t_node'])}, N {_node(p['n_node'])}")
    if t == ElementType.THREE_PHASE_LOAD:
        conn = "yıldız (Y)" if p["connection"] == "Y" else "üçgen (Δ)"
        zs = ", ".join(f"{k} = {rect(z, 'Ω')}" for k, z in zip(
            ("Z_R", "Z_S", "Z_T") if p["connection"] == "Y" else ("Z_RS", "Z_ST", "Z_TR"), p["z"]))
        return (f"{e.id}: üç fazlı yük, {conn}, {zs}; uçlar R {_node(e.node_positive)}, "
                f"S {_node(e.node_negative)}, T {_node(p['t_node'])}, N {_node(p['n_node'])}")
    if t == ElementType.WATTMETER:
        return (f"{e.id}: wattmetre, akım bobini {_node(e.node_positive)} → {_node(e.node_negative)}, "
                f"gerilim bobini {_node(p['v_pos'])} – {_node(p['v_neg'])}")
    if t == ElementType.SWITCH:
        kind = p.get("kind")
        if kind == "SPDT":
            return (f"{e.id}: iki konumlu anahtar, ortak uç {_node(p['common'])}; t < 0'da "
                    f"{_node(p['pos1'])} ile, t = 0'da {_node(p['pos2'])} ile bağlanır")
        what = "t < 0'da açık, t = 0'da kapanır" if kind == "NO" else "t < 0'da kapalı, t = 0'da açılır"
        return f"{e.id}: anahtar, {between}; {what}"
    if t in DEPENDENT_SOURCES:
        # Ters kontrolde eksi yazılmaz; V_R2 / I_R2 ekrandaki işaretlere göre tanımlanır
        ctrl = f"{p['control_kind']}_{p['control_id']}"
        if p["control_sign"] < 0:
            ctrl += (" (ölçüm yönü kontrol elemanının ters yönünde: + ucu onun n− ucu)"
                     if p["control_kind"] == "V" else
                     " (akım yönü kontrol elemanının ters yönünde)")
        what = ("gerilim kaynağı, "
                f"(+) ucu {_node(e.node_positive)}, (−) ucu {_node(e.node_negative)}"
                if t in DEPENDENT_VOLTAGE_OUTPUT else
                f"akım kaynağı, akım kaynak içinde {_node(e.node_positive)} → "
                f"{_node(e.node_negative)} yönünde")
        return (f"{e.id}: {DEPENDENT_NAMES[t].lower()} ({what}); {e.id} = {num(p['gain'])}·{ctrl}, "
                f"kontrol elemanı {p['control_id']}")
    return f"{e.id}: {between}"


def circuit_text(parsed: ParsedCircuit, is_dc: bool, frequency: Optional[float]) -> str:
    basis = getattr(parsed, "value_basis", "PEAK")
    lines = ["DEVRE:"]
    lines += [f"- {describe_element(e, basis)}" for e in parsed.elements]
    ac_label = f"AC (fazör, {'etkin/RMS' if basis == 'RMS' else 'tepe'})"
    lines.append(f"Analiz: {'DC' if is_dc else f'{ac_label}, f = {num(frequency)} Hz' if frequency else ac_label}")
    return "\n".join(lines)


def explanation_text(sections: Sequence[ExplanationSection]) -> str:
    parts = []
    for s in sections:
        parts.append(f"## {s.title}")
        for b in s.blocks:
            parts.append(("    " if b.kind == "math" else "") + b.text)
    text = "\n".join(parts)
    if len(text) > MAX_EXPLANATION_CHARS:
        text = text[:MAX_EXPLANATION_CHARS] + "\n[… anlatımın devamı kısaltıldı]"
    return text


def known_nodes_text(parsed: ParsedCircuit, is_dc: bool) -> str:
    """
    Alıştırmada modele verilen tek "çözüm" bilgisi: gerilim kaynaklarından
    doğrudan bilinen düğümler. Bunlar sorulan cevaplar değil, sorunun
    verisidir; verilmezse model "V1 de bilinmeyen" gibi yanlış yol gösteriyor.
    """
    known, _, _ = _node_groups(parsed, is_dc)
    items = [(n, v) for n, v in known.items() if n != "0"]
    if not items:
        return ""
    vals = ", ".join(
        f"{_node(n)} = {eng(complex(v).real, 'V') if is_dc else polar(complex(v), 'V')}"
        for n, v in sorted(items, key=lambda kv: (len(kv[0]), kv[0])))
    return ("Kaynaklardan doğrudan bilinen düğüm gerilimleri (sorunun verisi; öğrenci bunları "
            f"hesaplamaz, bilinmeyen değildir): {vals}")


def current_directions_text(parsed: ParsedCircuit, results: AnalysisResults, is_dc: bool) -> str:
    """
    Her elemanın akım yönü ve kaynakların güç verip vermediği — programın
    hesapladığı kesin cümleler. Küçük modeller işaret kuralında kendi başına
    akıl yürütünce yönü karıştırabiliyor (gerçek denemede görüldü); hazır
    cümle verilince yalnızca aktarmaları yeterli olur.
    """
    powers = results.power.elements if results.power else {}
    lines = ["AKIM YÖNLERİ VE GÜÇ (program hesapladı; yön ve işaret sorularında bunları aynen kullan):"]
    for e in parsed.elements:
        ec = results.element_currents.get(e.id)
        if ec is None:
            continue
        p, n = _node(e.node_positive), _node(e.node_negative)
        v = ec.value
        if is_dc or isinstance(v, (int, float)):
            i = v if isinstance(v, (int, float)) else v.real
            if abs(i) < 1e-15:
                lines.append(f"- I_{e.id} = 0: bu elemandan akım geçmiyor.")
            elif i > 0:
                lines.append(f"- I_{e.id} = {eng(i, 'A')} (referans {p} → {n}): pozitif, akım eleman "
                             f"içinden {p} → {n} yönünde akar.")
            else:
                lines.append(f"- I_{e.id} = {eng(i, 'A')} (referans {p} → {n}): EKSİ, yani akım gerçekte "
                             f"eleman içinden {n} → {p} yönünde {eng(-i, 'A')} olarak akar.")
        else:
            lines.append(f"- I_{e.id} = {polar(complex(v.real, v.imaginary), 'A')} "
                         f"(fazör, referans {p} → {n}).")

        if (e.element_type in VOLTAGE_SOURCES
                or e.element_type in DEPENDENT_VOLTAGE_OUTPUT) and e.id in powers:
            ap = powers[e.id].active_power
            if ap < -1e-15:
                sign_text = ("akımı eksi çıkar" if is_dc else
                             "akım fazörü ile kaynak gerilimi arasındaki açı 90°'den büyüktür "
                             "(cos φ < 0, P < 0)")
                lines.append(f"  {e.id} devreye güç VERİYOR (P = {eng(-ap, 'W')}): gerçek akım kaynağın "
                             f"içinden (−) uçtan (+) uca akar ve dış devreye (+) ucundan ({p}) çıkar. "
                             f"Referans yön (+) → (−) olduğu için {sign_text}.")
            elif ap > 1e-15:
                lines.append(f"  {e.id} güç ALIYOR (P = {eng(ap, 'W')}): akım kaynağa (+) ucundan girer.")
        elif e.element_type in CURRENT_SOURCES or e.element_type in DEPENDENT_CURRENT_OUTPUT:
            lines.append(f"  {e.id} bir akım kaynağıdır: tanımı gereği akımı kaynak içinden {p} → {n} "
                         f"yönündedir, dış devreye {n} ucundan çıkar.")
    return "\n".join(lines)


def build_messages(
    parsed: ParsedCircuit, results: AnalysisResults, analysis_type: AnalysisType,
    is_dc: bool, frequency: Optional[float], terminals: Optional[TheveninTerminals],
    question: str, history: Sequence[Dict[str, str]], practice: bool,
    practice_questions: Sequence[PracticeQuestion],
) -> List[Dict[str, str]]:
    method = _METHOD_NAMES.get(analysis_type, analysis_type.value)
    if terminals is not None and analysis_type in (AnalysisType.THEVENIN, AnalysisType.NORTON,
                                                  AnalysisType.SOURCE_TRANSFORM):
        method += f" ({_node(terminals.node_positive)} – {_node(terminals.node_negative)} terminalleri)"
    basis = getattr(parsed, "value_basis", "PEAK")
    kinds = {e.element_type for e in parsed.elements}
    notes = concept_notes(analysis_type, is_dc,
                          has_c=ElementType.CAPACITOR in kinds, has_l=ElementType.INDUCTOR in kinds)
    ctx = [_rules_for(basis), "", notes, "",
           circuit_text(parsed, is_dc, frequency), f"Yöntem: {method}", ""]
    if practice:
        ctx.append(_PRACTICE_RULES)
        known_text = known_nodes_text(parsed, is_dc)
        if known_text:
            ctx.append(known_text)
        if practice_questions:
            ctx.append("Öğrencinin çözmeye çalıştığı sorular:")
            ctx += [f"- {q.label}: {q.description}" for q in practice_questions]
    else:
        ctx.append("ÇÖZÜM (programın ürettiği ve doğrulanmış adım adım anlatım):")
        ctx.append(explanation_text(results.explanation))
        ctx.append("")
        ctx.append(current_directions_text(parsed, results, is_dc))

    messages = [{"role": "system", "content": "\n".join(ctx)}]
    for turn in list(history)[-MAX_HISTORY_TURNS:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": question})
    return messages


def known_values(parsed: ParsedCircuit, results: AnalysisResults, frequency: Optional[float],
                 texts: Sequence[str]) -> KnownValues:
    """
    Çözümde/devrede geçen tüm değerler, birimleriyle (cevap doğrulaması için).
    Birimi belirsiz olanlar (kazanç, cos φ, Q, karmaşık güç toplamları) birimsiz eklenir.
    """
    values = []

    def put(v, unit=None):
        if v is not None:
            values.append((v, unit))

    def source_unit(e):
        if e.element_type in VOLTAGE_SOURCES:
            return "V"
        if e.element_type in CURRENT_SOURCES:
            return "A"
        return None

    element_unit = {ElementType.RESISTOR: "Ω", ElementType.CAPACITOR: "F",
                    ElementType.INDUCTOR: "H", ElementType.IMPEDANCE: "Ω"}
    for e in parsed.elements:
        if e.element_type == ElementType.IMPEDANCE:
            put(complex(e.params.get("impedance", e.value)), "Ω")
        else:
            put(e.value, element_unit.get(e.element_type) or source_unit(e))
        put(e.params.get("amplitude"), source_unit(e))
        put(e.params.get("input_value"))
        put(e.params.get("frequency"), "Hz")
        put(e.params.get("phase"), "°")
        if e.element_type == ElementType.THREE_PHASE_LOAD:
            for z in e.params["z"]:
                put(z, "Ω")
    if frequency:
        put(frequency, "Hz")
        put(2 * 3.141592653589793 * frequency, "rad/s")

    def cn(c):
        return complex(c.real, c.imaginary)

    def rv(v):
        return v if isinstance(v, (int, float)) else cn(v)

    node_v = {k: complex(rv(nv.value)) for k, nv in results.node_voltages.items()}
    node_v.setdefault("0", 0j)
    for v in node_v.values():
        put(v, "V")
    # Eleman uçlarındaki gerilim (ör. R5: V₂ − V₃ = 3,211 V); model bunu sık hesaplıyor
    for e in parsed.elements:
        if e.node_positive in node_v and e.node_negative in node_v:
            put(node_v[e.node_positive] - node_v[e.node_negative], "V")
    for ec in results.element_currents.values():
        put(rv(ec.value), "A")
    if results.thevenin:
        put(cn(results.thevenin.vth), "V")
        put(cn(results.thevenin.zth), "Ω")
    if results.norton:
        put(cn(results.norton.i_n), "A")
        put(cn(results.norton.y_n), "S")
        if results.norton.z_n:
            put(cn(results.norton.z_n), "Ω")
    for m in results.meshes:
        put(cn(m.current), "A")
    tr = getattr(results, "transient", None)
    if tr is not None:
        put(tr.tau, "s")
        put(tr.r_th, "Ω")
        for q in tr.quantities:
            for v in (q.before, q.start, q.final):
                put(v, q.unit)
    for c in results.superposition:
        for v in c.node_voltages.values():
            put(cn(v), "V")
        for v in c.element_currents.values():
            put(cn(v), "A")
    if results.power:
        for ep in results.power.elements.values():
            put(cn(ep.complex_power))
            put(ep.active_power, "W")
            put(ep.reactive_power, "VAR")
            put(ep.apparent_power, "VA")
            put(ep.power_factor)
        put(cn(results.power.total_supplied))
        put(cn(results.power.total_absorbed))
    ps = getattr(results, "power_summary", None)
    if ps is not None:
        put(ps.p, "W")
        put(ps.q, "VAR")
        put(ps.s, "VA")
        put(ps.pf)
        put(ps.phi_deg, "°")
        if ps.compensation is not None:
            put(ps.compensation.target_pf)
            put(ps.compensation.q_c, "VAR")
            put(ps.compensation.c, "F")
            put(ps.compensation.i_before, "A")
            put(ps.compensation.i_after, "A")
    rs = getattr(results, "resonance", None)
    if rs is not None:
        for v in (rs.f0, rs.bw, rs.f1, rs.f2, rs.f1_exact, rs.f2_exact):
            put(v, "Hz")
        put(rs.w0, "rad/s")
        put(rs.x, "Ω")
        put(rs.z0, "Ω")
        put(rs.q)
        put(rs.i0, "A")
        put(rs.v0, "V")
    tp = getattr(results, "three_phase", None)
    if tp is not None:
        put(tp.u_line, "V")
        put(tp.u_phase, "V")
        put(tp.p, "W")
        put(tp.q, "VAR")
        put(tp.s, "VA")
        put(tp.pf)
        for v in tp.line_currents.values():
            put(cn(v), "A")
        if tp.neutral_current is not None:
            put(cn(tp.neutral_current), "A")
        if tp.load_phase_currents:
            for v in tp.load_phase_currents.values():
                put(cn(v), "A")
        if tp.aron is not None:
            put(tp.aron.p_a, "W")
            put(tp.aron.p_b, "W")
        if tp.compensation is not None:
            put(tp.compensation.target_pf)
            put(tp.compensation.q_c, "VAR")
            put(tp.compensation.c_y, "F")
            put(tp.compensation.c_delta, "F")
    for w in getattr(results, "wattmeters", []):
        put(w.p, "W")
    tr = getattr(results, "transformer", None)
    if tr is not None:
        put(cn(tr.v1), "V")
        put(cn(tr.v2), "V")
        put(cn(tr.i1), "A")
        put(cn(tr.i2), "A")
        put(tr.a)
        put(tr.k)
        put(tr.m, "H")
    return known_from(values, texts)


def answer_question(
    parsed: ParsedCircuit, results: AnalysisResults, analysis_type: AnalysisType,
    is_dc: bool, frequency: Optional[float], terminals: Optional[TheveninTerminals],
    question: str, history: Sequence[Dict[str, str]], model: str,
    practice: bool = False, practice_questions: Sequence[PracticeQuestion] = (),
    base: Optional[str] = None, options: Optional[Dict[str, object]] = None,
) -> dict:
    """
    Soruyu modele sorar, cevaptaki sayıları denetler.
    base / options: çalıştığı yer (NPU sunucusu, işlemci için num_gpu = 0); bkz. llm/devices.py
    Dönüş: {answer, numbers: [(text, status)], note}
    Ollama hataları (OllamaUnavailable / OllamaError) çağırana iletilir.
    """
    messages = build_messages(parsed, results, analysis_type, is_dc, frequency, terminals,
                              question, history, practice, practice_questions)
    # LaTeX/Markdown → düz metin (sayı denetiminden ÖNCE: "$12$" de yakalansın)
    extra = {k: v for k, v in (("base", base), ("options", options)) if v}
    raw = to_plain_text(ollama.chat(model, messages, **extra))

    user_texts = [question] + [t.get("content", "") for t in history if t.get("role") == "user"]
    circuit_texts = [circuit_text(parsed, is_dc, frequency), known_nodes_text(parsed, is_dc)]
    # Gizlemeden muaf olan yalnız devrede verilen değerlerdir. Öğrencinin soruda yazdığı
    # sayı ("V2 8 V mu?") muaf değildir; yoksa model "evet, 8 V" diyerek cevabı onaylar.
    given = known_from(texts=circuit_texts)
    if practice:
        # Sonuçlar bilinmiyor sayılır: yalnız devrede verilen değerler doğrulanır
        known = known_from(texts=circuit_texts + user_texts)
        forbidden = [complex(q.expected.real, q.expected.imaginary) for q in practice_questions]
    else:
        known = known_values(parsed, results, frequency,
                             [messages[0]["content"]] + user_texts)
        forbidden = []

    answer, checks = check_answer_numbers(raw, known, forbidden, given if practice else None)
    unverified = [c.text for c in checks if c.status == "unverified"]
    redacted = [c for c in checks if c.status == "redacted"]

    notes = []
    if redacted:
        notes.append("Alıştırma sürdüğü için cevabı veren sayılar gizlendi (■■).")
    if unverified:
        notes.append("Şu sayılar programın çözümüyle doğrulanamadı, dikkatli olun: "
                     + ", ".join(unverified) + "."
                     + ("" if practice else " Doğru değerler için Anlatım ve Sonuçlar sekmelerine bakın."))
    return {
        "answer": answer,
        "numbers": [(c.text, c.status) for c in checks],
        "note": " ".join(notes) if notes else None,
    }
