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

from explainer.formatting import eng, num, polar
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
}

_RULES = """Sen meslek yüksekokulu elektronik öğrencilerine devre analizi anlatan sabırlı bir öğretmensin.
Kurallar:
1. Yalnızca Türkçe yaz. Selamlama yapma, doğrudan cevaba gir. Kısa ve sade ol: en fazla 8–10 cümle.
2. Aşağıdaki DEVRE ve ÇÖZÜM bilgilerini kullan. Bir sayı gerekiyorsa bu bilgilerde yazan sayıyı AYNEN kullan; kendin yeni hesap yapma, sayı uydurma.
3. Hangi elemanın nereye bağlı olduğunu yalnızca DEVRE listesindeki düğümlere göre söyle; bağlantı tahmin etme.
4. Sorunun cevabı verilen bilgilerde yoksa bunu açıkça söyle; tahmin yürütme.
5. Fazörler tepe (maksimum) değerdir, etkin değer değildir.
6. İşaret kuralı (pasif işaret kuralı): Her elemanın akımı, ELEMANIN İÇİNDEN (+) ucundan (−) ucuna doğru (eleman adının yanındaki "1→0" gibi düğüm sırası) pozitif alınır. Güç veren bir gerilim kaynağında gerçek akım kaynağın içinden (−) uçtan (+) uca akar ve dış devreye (+) uçtan çıkar; bu yüzden kaynağın akımı EKSİ çıkar. Eksi işaret hata değildir, akımın seçilen referans yönün tersine aktığını gösterir.
7. Formülleri düz metinle yaz (LaTeX ve Markdown kullanma)."""

_PRACTICE_RULES = """ÖNEMLİ: Öğrenci şu anda bu devreyle ALIŞTIRMA çözüyor; sonuçlar sana bilerek verilmedi.
Hiçbir sorunun sayısal cevabını söyleme ve sayısal hesap yapma.
Yalnızca yöntemi, hangi denklemin nasıl kurulacağını ve bir sonraki adımı sözle tarif et."""


def _node(n: str) -> str:
    return "GND" if n == "0" else f"Düğüm {n}"


def describe_element(e: ParsedElement) -> str:
    t = e.element_type
    between = f"{_node(e.node_positive)} – {_node(e.node_negative)}"
    p = e.params
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
        return (f"{e.id}: AC gerilim kaynağı, genlik (tepe) {eng(amp, 'V')}, faz {num(p.get('phase', 0))}°{f_txt}, "
                f"(+) ucu {_node(e.node_positive)}, (−) ucu {_node(e.node_negative)}")
    if t == ElementType.CURRENT_DC:
        return (f"{e.id}: DC akım kaynağı {eng(e.value, 'A')}, akım kaynak içinde "
                f"{_node(e.node_positive)} → {_node(e.node_negative)} yönünde")
    if t in (ElementType.CURRENT_AC_SINE, ElementType.CURRENT_AC_PHASOR):
        amp = p.get("amplitude", e.value)
        freq = p.get("frequency")
        f_txt = f", f = {num(freq)} Hz" if freq else ""
        return (f"{e.id}: AC akım kaynağı, genlik (tepe) {eng(amp, 'A')}, faz {num(p.get('phase', 0))}°{f_txt}, "
                f"akım kaynak içinde {_node(e.node_positive)} → {_node(e.node_negative)} yönünde")
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
    lines = ["DEVRE:"]
    lines += [f"- {describe_element(e)}" for e in parsed.elements]
    lines.append(f"Analiz: {'DC' if is_dc else f'AC (fazör), f = {num(frequency)} Hz' if frequency else 'AC (fazör)'}")
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
                             "akım fazörü referansa göre yaklaşık 180° ters fazlıdır (eksi işaretli)")
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
    ctx = [_RULES, "", circuit_text(parsed, is_dc, frequency), f"Yöntem: {method}", ""]
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
    """Çözümde/devrede geçen tüm değerler (cevap doğrulaması için)."""
    values = []
    for e in parsed.elements:
        values.append(complex(e.params.get("impedance", e.value)) if e.element_type == ElementType.IMPEDANCE
                      else e.value)
        for key in ("amplitude", "frequency", "phase"):
            if e.params.get(key) is not None:
                values.append(e.params[key])
    if frequency:
        values += [frequency, 2 * 3.141592653589793 * frequency]

    def cn(c):
        return complex(c.real, c.imaginary)

    def rv(v):
        return v if isinstance(v, (int, float)) else cn(v)

    values += [rv(nv.value) for nv in results.node_voltages.values()]
    values += [rv(ec.value) for ec in results.element_currents.values()]
    if results.thevenin:
        values += [cn(results.thevenin.vth), cn(results.thevenin.zth)]
    if results.norton:
        values += [cn(results.norton.i_n), cn(results.norton.y_n)]
        if results.norton.z_n:
            values.append(cn(results.norton.z_n))
    values += [cn(m.current) for m in results.meshes]
    tr = getattr(results, "transient", None)
    if tr is not None:
        values += [tr.tau, tr.r_th]
        for q in tr.quantities:
            values += [q.before, q.start, q.final]
    for c in results.superposition:
        values += [cn(v) for v in c.node_voltages.values()]
        values += [cn(v) for v in c.element_currents.values()]
    if results.power:
        for ep in results.power.elements.values():
            values += [cn(ep.complex_power), ep.active_power, ep.reactive_power, ep.apparent_power]
            if ep.power_factor is not None:
                values.append(ep.power_factor)
        values += [cn(results.power.total_supplied), cn(results.power.total_absorbed)]
    return known_from(values, texts)


def answer_question(
    parsed: ParsedCircuit, results: AnalysisResults, analysis_type: AnalysisType,
    is_dc: bool, frequency: Optional[float], terminals: Optional[TheveninTerminals],
    question: str, history: Sequence[Dict[str, str]], model: str,
    practice: bool = False, practice_questions: Sequence[PracticeQuestion] = (),
) -> dict:
    """
    Soruyu modele sorar, cevaptaki sayıları denetler.
    Dönüş: {answer, numbers: [(text, status)], note}
    Ollama hataları (OllamaUnavailable / OllamaError) çağırana iletilir.
    """
    messages = build_messages(parsed, results, analysis_type, is_dc, frequency, terminals,
                              question, history, practice, practice_questions)
    # LaTeX/Markdown → düz metin (sayı denetiminden ÖNCE: "$12$" de yakalansın)
    raw = to_plain_text(ollama.chat(model, messages))

    user_texts = [question] + [t.get("content", "") for t in history if t.get("role") == "user"]
    given = known_from(texts=[circuit_text(parsed, is_dc, frequency),
                              known_nodes_text(parsed, is_dc)] + user_texts)
    if practice:
        # Sonuçlar bilinmiyor sayılır: yalnız devrede verilen değerler doğrulanır
        known = given
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
