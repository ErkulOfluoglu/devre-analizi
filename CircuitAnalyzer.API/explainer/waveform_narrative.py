"""
CircuitAnalyzer API — Dalga Şekli (WAVEFORM) Türkçe anlatımı (Faz 4c-1)

Kitap sırası (Selek, Elektronik-1):
    1. Devreyi Tanıyalım        (kaynak biçimi, V_m/f/T, diyotlar ve V_T, çıkış V_O, tepe notu)
    2. Eşik Gerilimi            (iletim yolundaki toplam eşik ya da diyot başına V_T)
    3. Pozitif Alternans        (durumlar, eşdeğer devre, tepede KVL / V_O)
    4. Negatif Alternans        (durumlar, eşdeğer devre, tepede KVL / V_O)
    5. İletim Aralığı           (SINE/TRIANGLE: θ ve t)  /  Kare Dalga Seviyeleri (SQUARE)
    6. Çıkış Değerleri          (V_O,max ve V_O,min)
    7. Ortalama (DC) Değer      (sayısal V_DC + varsa kitap formülü ve fark açıklaması)
    8. Çıkış Dalga Şekli        (çıkışın biçimini özetleyen cümle)
"""

from typing import List

from explainer.formatting import MINUS, ek, eng, num, paren
from models.response import ExplanationBlock, ExplanationSection


class _Sec:
    def __init__(self, title: str):
        self.title = title
        self.blocks: List[ExplanationBlock] = []

    def add(self, kind: str, text: str) -> None:
        self.blocks.append(ExplanationBlock(kind=kind, text=text))

    def build(self) -> ExplanationSection:
        return ExplanationSection(title=self.title, blocks=self.blocks)


_MODEL_LABELS = {"IDEAL": "ideal", "SI": "Si", "GE": "Ge", "ZENER": "Zener"}
_STATE_LABELS = {"ON": "iletimde", "ZENER": "ters iletimde (zener bölgesi)", "OFF": "yalıtımda"}
_SHAPE_LABELS = {"SINE": "sinüs", "SQUARE": "kare", "TRIANGLE": "üçgen"}


def _volts(x: float) -> str:
    return f"{num(x)} V"


def _diode_spec(d) -> str:
    m = d.params["model"]
    if m == "ZENER":
        return f"{d.id} (Zener, V_Z = {_volts(d.params['v_z'])}, V_F = {_volts(d.params['v_t'])})"
    return f"{d.id} ({_MODEL_LABELS.get(m, m)}, V_T = {_volts(d.params['v_t'])})"


def _and(items: List[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " ve " + items[-1]


def fallback_note(reason: str) -> str:
    """errors listesine eklenecek standart ℹ geri dönüş notu."""
    clean = reason.strip().rstrip(".")
    return f"ℹ Dalga Şekli uygulanamadı: {clean}. Sonuçlar Düğüm Gerilimleri yöntemiyle verildi."


def fallback_section(reason: str) -> ExplanationSection:
    """Anlatımın başına eklenecek geri dönüş bölümü."""
    clean = reason.strip().rstrip(".")
    return ExplanationSection(
        title="Dalga Şekli",
        blocks=[ExplanationBlock(
            kind="note",
            text=(f"Bu devrede Dalga Şekli yöntemi uygulanamadı: {clean}. "
                  "“Düğüm Gerilimleri” yöntemini seçebilirsiniz; aynı sonuçları şimdi o "
                  "yöntemle anlatıyoruz."),
        )],
    )


def _alternans_section(title: str, intro: str, setup, pt) -> _Sec:
    s = _Sec(title)
    s.add("text", intro)
    on_ids = [d.id for d in setup.diodes if pt.states.get(d.id) == "ON"]
    zener_ids = [d.id for d in setup.diodes if pt.states.get(d.id) == "ZENER"]
    off_ids = [d.id for d in setup.diodes if pt.states.get(d.id) == "OFF"]

    parts = []
    if on_ids:
        parts.append(f"{_and(on_ids)} iletimde")
    if zener_ids:
        parts.append(f"{_and(zener_ids)} ters iletimde (zener bölgesi)")
    if off_ids:
        parts.append(f"{_and(off_ids)} yalıtımda")
    s.add("text", "Diyot durumları: " + "; ".join(parts) + ".")

    # Eşdeğer devre cümlesi
    eq_parts = []
    for d in setup.diodes:
        st = pt.states.get(d.id, "OFF")
        if st == "OFF":
            eq_parts.append(f"{d.id} açık devre")
        elif st == "ZENER":
            eq_parts.append(f"{d.id} yerine V_Z = {_volts(d.params['v_z'])} kaynak")
        elif d.params["v_t"] == 0.0:
            eq_parts.append(f"{d.id} kısa devre")
        else:
            eq_parts.append(f"{d.id} yerine V_T = {_volts(d.params['v_t'])} kaynak")
    s.add("text", "Eşdeğer devrede " + ", ".join(eq_parts) + " konur.")

    # KVL / V_O sonucu
    if not on_ids and not zener_ids:
        s.add("math", f"v_in = {_volts(pt.v_in)} → akım geçmez ⇒ V_O = {_volts(pt.v_out)}")
    else:
        drop = abs(pt.v_in) - abs(pt.v_out)
        if abs(drop) > 1e-6 and len(setup.resistors) == 1 and setup.output_elem.id == setup.resistors[0].id:
            s.add("math", (
                f"v_in = {_volts(pt.v_in)} → toplam düşüm {_volts(drop)} ⇒ "
                f"V_O ({setup.output_elem.id}) = {_volts(pt.v_out)}"
            ))
        else:
            s.add("math", f"v_in = {_volts(pt.v_in)} ⇒ V_O ({setup.output_elem.id}) = {_volts(pt.v_out)}")
    # Adım özeti math satırının ilk ve son parçasını alır ("v_in = 9,3 V" gibi yanıltıcı
    # bir özet çıkıyordu); tek eşitlikli sonuç satırı özette doğru büyüklüğü gösterir.
    s.add("result", f"V_O = {_volts(pt.v_out)}")
    return s


def _build_clamper_sections(analysis) -> List[ExplanationSection]:
    """Kenetleme (clamper) devresi için kitap sırasıyla Türkçe anlatım bölümleri."""
    setup = analysis.setup
    cl = setup.clamper
    sm = analysis.summary
    info = sm.clamper
    d = cl.diode
    c = cl.capacitor
    r = cl.resistor
    bias = cl.bias_source
    sections: List[_Sec] = []

    # ── 1. Devreyi Tanıyalım ──
    s1 = _Sec("Devreyi Tanıyalım")
    s1.add(
        "text",
        "Bu devre bir kenetleme devresidir (clamper): giriş dalga şeklinin biçimini "
        "bozmadan DC seviyesini aşağı ya da yukarı kaydırır.",
    )
    shape_tr = _SHAPE_LABELS[setup.shape]
    if setup.shape == "SQUARE":
        src_desc = (
            f"Giriş kaynağı {setup.source.id}: {shape_tr} dalga, "
            f"seviyeler V₁ = {_volts(setup.v1)} ve V₂ = {_volts(setup.v2)}, "
            f"f = {eng(setup.frequency, 'Hz')}, periyot T = 1/f = {eng(setup.period, 's')}."
        )
    else:
        off_txt = f", ofset {_volts(setup.offset)}" if abs(setup.offset) > 1e-12 else ""
        src_desc = (
            f"Giriş kaynağı {setup.source.id}: {shape_tr} dalga, "
            f"tepe değeri V_m = {_volts(setup.amplitude)}{off_txt}, "
            f"f = {eng(setup.frequency, 'Hz')}, periyot T = 1/f = {eng(setup.period, 's')}."
        )
    s1.add("text", src_desc)
    if bias is not None:
        s1.add(
            "text",
            f"Diyot kolu: {_diode_spec(d)} ve seri DC kaynak {bias.id} = {_volts(bias.value)} "
            f"(çıkıştan toprağa katkısı V_bias = {_volts(cl.v_bias)}).",
        )
    else:
        s1.add("text", f"Diyot kolu: {_diode_spec(d)} (seri DC kaynak yok).")
    s1.add(
        "text",
        f"Kondansatör {c.id} = {eng(c.value, 'F')}, yük direnci {r.id} = {eng(r.value, 'Ω')} "
        f"(τ = R·C = {eng(info.tau, 's')}). Çıkış gerilimi {sm.output_label}, "
        f"{ek(sm.output_id, 'in')} uçlarından alınır.",
    )
    s1.add(
        "note",
        "Kitap yöntemi: kondansatör yalıtım alternansında gerilimini korur (RC ≫ T). "
        "Düğüm gerilimleri ve akımlar iletim alternansı anındaki değerlerdir.",
    )
    sections.append(s1)

    # ── 2. İletim Koşulu ──
    s2 = _Sec("İletim Koşulu")
    if bias is not None:
        op = "+" if cl.diode_to_gnd else MINUS
        s2.add(
            "math",
            f"V_K = V_bias {op} V_T = {_volts(cl.v_bias)} {op} {_volts(cl.v_t)} = {_volts(cl.v_k)}",
        )
    else:
        if cl.v_t == 0.0:
            s2.add("math", f"V_K = {_volts(0.0)} (ideal diyot, seri kaynak yok)")
        elif cl.diode_to_gnd:
            s2.add("math", f"V_K = +V_T = {_volts(cl.v_k)}")
        else:
            s2.add("math", f"V_K = {MINUS}V_T = {_volts(cl.v_k)}")

    if cl.diode_to_gnd:
        s2.add(
            "text",
            f"{d.id} çıkıştan toprağa doğru bağlandığından v_i > V_K = {_volts(cl.v_k)} olduğunda "
            f"(üst alternans, v_i,max = {_volts(analysis.clamper_v_i_max)}) iletime geçer.",
        )
    else:
        s2.add(
            "text",
            f"{d.id} topraktan çıkışa doğru bağlandığından v_i < V_K = {_volts(cl.v_k)} olduğunda "
            f"(alt alternans, v_i,min = {_volts(analysis.clamper_v_i_min)}) iletime geçer.",
        )
    s2.add(
        "note",
        "İncelemeye diyotu iletime götüren alternanstan başlanır, çünkü V_C önce bulunmalıdır.",
    )
    if setup.shape != "SQUARE":
        s2.add(
            "note",
            f"{shape_tr.capitalize()} girişte kararlı hâlde diyot periyot boyunca yalıtımdadır; "
            "yalnızca tepe anında sınırda iletime geçer ve kondansatörü tazeler.",
        )
    sections.append(s2)

    # ── 3. İletim Alternansı ──
    s3 = _Sec("İletim Alternansı")
    diode_eq = f"{d.id} kısa devre" if cl.v_t == 0.0 else f"{d.id} yerine V_T = {_volts(cl.v_t)} kaynak"
    if bias is not None:
        s3.add(
            "text",
            f"Eşdeğer devrede {diode_eq} konur ve seri {bias.id} ({_volts(bias.value)}) kaynağı korunur; "
            f"çıkış V_O = V_K = {_volts(cl.v_k)} değerinde sabitlenir.",
        )
    else:
        s3.add(
            "text",
            f"Eşdeğer devrede {diode_eq} konur; çıkış V_O = V_K = {_volts(cl.v_k)} değerinde sabitlenir.",
        )
    s3.add(
        "math",
        f"KVL: v_i = V_C + V_O ⇒ V_C = v_i {MINUS} V_K = "
        f"{_volts(analysis.clamper_v_in_cond)} {MINUS} {paren(_volts(cl.v_k))} = {_volts(info.v_c)}",
    )
    if info.v_c_plus_side == "INPUT":
        s3.add(
            "text",
            f"V_C = {_volts(info.v_c)} (> 0) olduğundan {ek(c.id, 'in')} + ucu giriş tarafında, "
            "− ucu çıkış tarafındadır.",
        )
    else:
        s3.add(
            "text",
            f"V_C = {_volts(info.v_c)} (büyüklük {_volts(abs(info.v_c))}) olduğundan {ek(c.id, 'in')} "
            "+ ucu çıkış tarafında, − ucu giriş tarafındadır.",
        )
    # Tek eşitlikli sonuç satırı: WPF adım özeti ilk ve son parçayı gösterir.
    s3.add("result", f"V_O = {_volts(cl.v_k)}")
    sections.append(s3)

    # ── 4. Yalıtım Alternansı ──
    s4 = _Sec("Yalıtım Alternansı")
    s4.add("text", "Diyot yalıtımda; V_C'nin polaritesi korunur.")
    if setup.shape == "SQUARE":
        v_off = analysis.clamper_v_in_off
        v_out_off = v_off - info.v_c
        s4.add(
            "math",
            f"V_O = v_i {MINUS} V_C = {_volts(v_off)} {MINUS} {paren(_volts(info.v_c))} = {_volts(v_out_off)}",
        )
        s4.add("result", f"V_O = {_volts(v_out_off)}")
    else:
        s4.add(
            "text",
            "Diyot yalnızca tepe anında sınırda iletime geçer ve kondansatörü tazeler; "
            "tüm periyot boyunca V_O(t) = v_i(t) − V_C geçerlidir.",
        )
        s4.add(
            "math",
            f"V_O,max = v_i,max {MINUS} V_C = {_volts(analysis.clamper_v_i_max)} "
            f"{MINUS} {paren(_volts(info.v_c))} = {_volts(sm.v_out_max)}",
        )
        s4.add(
            "math",
            f"V_O,min = v_i,min {MINUS} V_C = {_volts(analysis.clamper_v_i_min)} "
            f"{MINUS} {paren(_volts(info.v_c))} = {_volts(sm.v_out_min)}",
        )
        s4.add("result", f"V_O,max = {_volts(sm.v_out_max)}")
        s4.add("result", f"V_O,min = {_volts(sm.v_out_min)}")
    sections.append(s4)

    # ── 5. Kontroller (kitabın 3 kriteri) ──
    s5 = _Sec("Kontroller (kitabın 3 kriteri)")
    for ch in info.checks:
        mark = "✓ " if ch.ok is True else ("✗ " if ch.ok is False else "– ")
        s5.add("check", f"{mark}{ch.name}: {ch.text}")
    # Adım özeti tek sonuç satırını gösterir; yoksa "3 kontrol tuttu" deyip uygulanmayan
    # kriteri de tutmuş sayıyordu. Sayım ok değerine göre yapılır (tek " = " kuralı: eşittir yok).
    n_ok = sum(1 for ch in info.checks if ch.ok is True)
    n_bad = sum(1 for ch in info.checks if ch.ok is False)
    n_na = sum(1 for ch in info.checks if ch.ok is None)
    parts = [f"{n_ok} kriter uygun ✓"]
    if n_bad:
        parts.append(f"{n_bad} kriter uymuyor ✗")
    if n_na:
        parts.append(f"{n_na} kriter uygulanmaz")
    s5.add("result", ", ".join(parts))
    sections.append(s5)

    # ── 6. Çıkış Dalga Şekli ──
    s6 = _Sec("Çıkış Dalga Şekli")
    dir_word = "aşağı" if info.shift == "DOWN" else "yukarı"
    s6.add(
        "text",
        f"Çıkış, girişin {_volts(abs(info.v_c))} {dir_word} kaymış hâlidir "
        f"(V_O,max = {_volts(sm.v_out_max)}, V_O,min = {_volts(sm.v_out_min)}).",
    )
    if info.rc_note:
        s6.add("note", info.rc_note)
    s6.add("text", "Bir periyot üzerinden sayısal ortalama (DC) çıkış gerilimi:")
    s6.add("math", f"V_DC (sayısal) = {_volts(sm.v_dc_numeric)}")
    s6.add("result", f"V_DC = {_volts(sm.v_dc_numeric)}")
    sections.append(s6)

    return [s.build() for s in sections if s.blocks]


def build_waveform_sections(analysis) -> List[ExplanationSection]:
    """WaveformAnalysis → kitap sırasıyla Türkçe ExplanationSection listesi."""
    setup = analysis.setup
    if setup.clamper is not None and analysis.summary.clamper is not None:
        return _build_clamper_sections(analysis)
    sm = analysis.summary
    sections: List[_Sec] = []

    # ── 1. Devreyi Tanıyalım ──
    s1 = _Sec("Devreyi Tanıyalım")
    shape_tr = _SHAPE_LABELS[setup.shape]
    if setup.shape == "SQUARE":
        src_desc = (
            f"Giriş kaynağı {setup.source.id}: {shape_tr} dalga, "
            f"seviyeler V₁ = {_volts(setup.v1)} ve V₂ = {_volts(setup.v2)}, "
            f"f = {eng(setup.frequency, 'Hz')}, periyot T = 1/f = {eng(setup.period, 's')}."
        )
    else:
        off_txt = f", ofset {_volts(setup.offset)}" if abs(setup.offset) > 1e-12 else ""
        src_desc = (
            f"Giriş kaynağı {setup.source.id}: {shape_tr} dalga, "
            f"tepe değeri V_m = {_volts(setup.amplitude)}{off_txt}, "
            f"f = {eng(setup.frequency, 'Hz')}, periyot T = 1/f = {eng(setup.period, 's')}."
        )
    s1.add("text", src_desc)
    s1.add("text", "Diyotlar: " + ", ".join(_diode_spec(d) for d in setup.diodes) + ".")
    if setup.dc_sources:
        dcs = ", ".join(f"{v.id} = {_volts(v.value)}" for v in setup.dc_sources)
        s1.add("text", f"Sabit DC kaynaklar: {dcs}.")
    s1.add("text", f"Çıkış gerilimi {sm.output_label}, {ek(sm.output_id, 'in')} uçlarından alınır.")
    s1.add("note", "Düğüm gerilimleri pozitif tepe anındaki değerlerdir; eleman akımları da aynı an için verilmiştir.")
    sections.append(s1)

    # ── 2. Eşik Gerilimi ──
    s2 = _Sec("Eşik Gerilimi")
    if analysis.path_threshold_expr:
        s2.add("text", "İletim yolundaki toplam eşik gerilimi:")
        s2.add("math", analysis.path_threshold_expr)
    else:
        s2.add("text", "Devredeki diyotların eşik gerilimleri:")
        for d in setup.diodes:
            s2.add("math", _diode_spec(d))
    sections.append(s2)

    # ── 3. Pozitif Alternans ──
    pos_intro = (
        f"Pozitif alternansın tepe anında (v_in = {_volts(analysis.pos_peak.v_in)}):"
        if setup.shape != "SQUARE"
        else f"Üst seviyede (v_in = {_volts(analysis.pos_peak.v_in)}):"
    )
    sections.append(_alternans_section("Pozitif Alternans", pos_intro, setup, analysis.pos_peak))

    # ── 4. Negatif Alternans ──
    neg_intro = (
        f"Negatif alternansın tepe anında (v_in = {_volts(analysis.neg_peak.v_in)}):"
        if setup.shape != "SQUARE"
        else f"Alt seviyede (v_in = {_volts(analysis.neg_peak.v_in)}):"
    )
    sections.append(_alternans_section("Negatif Alternans", neg_intro, setup, analysis.neg_peak))

    # ── 5. İletim Aralığı (SINE/TRIANGLE) veya Kare Dalga Seviyeleri (SQUARE) ──
    if setup.shape == "SQUARE" and sm.levels:
        s5 = _Sec("Kare Dalga Seviyeleri")
        s5.add("text", "Kare dalga iki sabit seviyeden oluşur; her seviyedeki çıkış gerilimi V_O ve diyot durumları:")
        for idx, lv in enumerate(sm.levels, 1):
            st_txt = ", ".join(f"{did} {_STATE_LABELS[st]}" for did, st in lv.states.items())
            s5.add("math", f"{idx}. yarı periyot: v_in = {_volts(lv.v_in)} ⇒ V_O = {_volts(lv.v_out)}  ({st_txt})")
        # Özet için her seviyenin tek eşitlikli sonucu (yukarıdaki nedenle).
        for idx, lv in enumerate(sm.levels, 1):
            s5.add("result", f"{idx}. yarı periyot V_O = {_volts(lv.v_out)}")
        sections.append(s5)
    else:
        s5 = _Sec("İletim Aralığı")
        if sm.conduction_angle_deg is not None and analysis.conduction_threshold_v is not None:
            v_th = analysis.conduction_threshold_v
            t_on = analysis.conduction_time_s or 0.0
            half_txt = "negatif" if analysis.conduction_in_neg_half else "pozitif"
            s5.add("text", (
                f"Diyotlar {half_txt} alternansta |v_in| eşik gerilimini ({_volts(v_th)}) "
                "aştığında iletime geçer:"
            ))
            if setup.shape == "SINE":
                s5.add("math", (
                    f"θ = arcsin({_volts(v_th)} / {_volts(setup.amplitude)}) = "
                    f"{num(sm.conduction_angle_deg)}°   (t = {eng(t_on, 's')})"
                ))
            else:
                s5.add("math", (
                    f"|v_in| = {_volts(v_th)} ⇒ t = {eng(t_on, 's')} "
                    f"(periyodun {num(sm.conduction_angle_deg)}° konumu)"
                ))
        else:
            s5.add("text", "Giriş gerilimi eşik gerilimini aşmadığından diyotlar periyot boyunca yalıtımdadır.")
        sections.append(s5)

    # ── 6. Çıkış Değerleri ──
    s6 = _Sec("Çıkış Değerleri")
    s6.add("math", f"V_O,max = {_volts(sm.v_out_max)}")
    s6.add("math", f"V_O,min = {_volts(sm.v_out_min)}")
    s6.add("result", f"Çıkış gerilimi {sm.output_label}: en büyük {_volts(sm.v_out_max)}, en küçük {_volts(sm.v_out_min)}.")
    sections.append(s6)

    # ── 7. Ortalama (DC) Değer ──
    s7 = _Sec("Ortalama (DC) Değer")
    s7.add("text", "Bir periyot üzerinden sayısal ortalama (DC) çıkış gerilimi:")
    s7.add("math", f"V_DC (sayısal) = {_volts(sm.v_dc_numeric)}")
    if sm.book_formula is not None:
        s7.add("text", f"Kitap formülü ({sm.book_formula.name.lower()}):")
        s7.add("math", sm.book_formula.text)
        s7.add("note", (
            "Kitap formülü tüm yarım periyot boyunca iletim varsayar; sayısal ortalama değer, "
            "iletim θ açısında başladığı için biraz daha düşüktür."
        ))
    s7.add("result", f"V_DC = {_volts(sm.v_dc_numeric)}")
    sections.append(s7)

    # ── 8. Çıkış Dalga Şekli ──
    s8 = _Sec("Çıkış Dalga Şekli")
    if analysis.pattern == "HALF_WAVE":
        pol = "pozitif" if analysis.pattern_positive else "negatif"
        s8.add("text", (
            f"Çıkış, giriş sinüsünün yalnızca {pol} alternanslarını geçiren ve diğer yarı periyotta "
            f"sıfırda kalan yarım dalga doğrultulmuş bir işarettir (tepe {_volts(sm.v_out_max if analysis.pattern_positive else sm.v_out_min)})."
        ))
    elif analysis.pattern == "BRIDGE":
        pol = "pozitif" if analysis.pattern_positive else "negatif"
        s8.add("text", (
            f"Çıkış, giriş sinüsünün her iki alternansını da {pol} yöne çeviren tam dalga doğrultulmuş "
            f"bir işarettir (tepe {_volts(sm.v_out_max if analysis.pattern_positive else sm.v_out_min)})."
        ))
    elif setup.shape == "SQUARE" and sm.levels:
        s8.add("text", (
            f"Çıkış, her periyotta {_volts(sm.levels[0].v_out)} ile {_volts(sm.levels[1].v_out)} "
            "seviyeleri arasında gidip gelen kare dalga biçimindedir."
        ))
    else:
        s8.add("text", (
            f"Çıkış dalga şekli {_volts(sm.v_out_min)} ile {_volts(sm.v_out_max)} aralığında "
            "periyodik olarak değişir ve diyotların yalıtımda kaldığı aralıklarda kırpılır."
        ))
    sections.append(s8)

    return [s.build() for s in sections if s.blocks]
