"""
CircuitAnalyzer API — Zener Aralığı (ZENER_RANGE) Türkçe anlatımı (Faz 4b-2)

Kitap sırası (Selek, Elektronik-1):
    1. Devreyi Tanıyalım (roller: V_İ, R_X, R_Y, zener)
    2. Zener Regülatör Modeli (ideal zener: V_Y = V_Z, 0 ≤ I_Z ≤ I_ZM, KCL)
    3. Hesap adımları (LOAD: V_X → I_X → I_Y sınırları → R_Y sınırları;
                       INPUT: I_Y → I_X sınırları → V_X → V_İ sınırları)
    4. Sonuç (aralık cümlesi ve mevcut değerin durumu)
    5. Sağlama (3 değerli tam devre çözümü kontrolü)
"""

from typing import List

from explainer.formatting import MINUS, eng, num
from models.response import ExplanationBlock, ExplanationSection


class _Sec:
    def __init__(self, title: str):
        self.title = title
        self.blocks: List[ExplanationBlock] = []

    def add(self, kind: str, text: str) -> None:
        self.blocks.append(ExplanationBlock(kind=kind, text=text))

    def build(self) -> ExplanationSection:
        return ExplanationSection(title=self.title, blocks=self.blocks)


def _volts(x: float) -> str:
    return f"{num(x)} V"


def _zener_spec(dz) -> str:
    v_z = dz.params["v_z"]
    i_zm = dz.params.get("i_zm")
    parts = [f"V_Z = {_volts(v_z)}"]
    if i_zm is not None:
        parts.append(f"I_ZM = {eng(i_zm, 'A')}")
    return f"{dz.id} ({', '.join(parts)})"


def fallback_note(reason: str) -> str:
    """errors listesine eklenecek standart ℹ geri dönüş notu."""
    clean = reason.strip().rstrip(".")
    return f"ℹ Zener Aralığı uygulanamadı: {clean}. Sonuçlar Düğüm Gerilimleri yöntemiyle verildi."


def fallback_section(reason: str) -> ExplanationSection:
    """Anlatımın başına eklenecek geri dönüş bölümü."""
    clean = reason.strip().rstrip(".")
    return ExplanationSection(
        title="Zener Aralığı",
        blocks=[ExplanationBlock(
            kind="note",
            text=(f"Bu devrede Zener Aralığı uygulanamadı: {clean}. "
                  "“Düğüm Gerilimleri” yöntemini seçebilirsiniz; aynı sonuçları şimdi o "
                  "yöntemle anlatıyoruz."),
        )],
    )


def build_zener_range_sections(analysis) -> List[ExplanationSection]:
    """ZenerRangeAnalysis → kitap sırasıyla Türkçe ExplanationSection listesi."""
    reg = analysis.reg
    sm = analysis.summary
    sections: List[_Sec] = []

    # ── 1. Devreyi Tanıyalım ──
    s1 = _Sec("Devreyi Tanıyalım")
    z_spec = _zener_spec(reg.dz)
    if reg.kind == "LOAD":
        s1.add("text", (
            f"Giriş V_İ = {reg.vs.id} = {eng(reg.v_i, 'V')}, "
            f"seri direnç R_X = {reg.rx.id} = {eng(reg.r_x, 'Ω')}, "
            f"yük R_Y = {reg.ry.id} (devrede {eng(reg.r_y, 'Ω')}), "
            f"zener {z_spec}."
        ))
        s1.add("text", (
            "Amaç: Giriş gerilimi V_İ sabitken zenerin ters iletimde (regülasyon bölgesinde) "
            "kalıp aşırı akımdan zarar görmeyeceği yük direnci (R_Y) aralığını bulmak."
        ))
    else:
        s1.add("text", (
            f"Giriş V_İ = {reg.vs.id} (devrede {eng(reg.v_i, 'V')}), "
            f"seri direnç R_X = {reg.rx.id} = {eng(reg.r_x, 'Ω')}, "
            f"yük R_Y = {reg.ry.id} = {eng(reg.r_y, 'Ω')}, "
            f"zener {z_spec}."
        ))
        s1.add("text", (
            "Amaç: Yük direnci R_Y sabitken zenerin ters iletimde (regülasyon bölgesinde) "
            "kalıp aşırı akımdan zarar görmeyeceği giriş gerilimi (V_İ) aralığını bulmak."
        ))
    sections.append(s1)

    # ── 2. Zener Regülatör Modeli ──
    s2 = _Sec("Zener Regülatör Modeli")
    if reg.i_zm is not None:
        s2.add("text", (
            f"İdeal zener modeli: ters iletimde (zener bölgesi) çıkış gerilimi V_Y = V_Z = "
            f"{_volts(reg.v_z)} sabit kalır; zener akımı I_Z,min = 0 ile "
            f"I_Z,max = I_ZM = {eng(reg.i_zm, 'A')} arasında olmalıdır."
        ))
        s2.add("math", f"V_Y = V_Z = {_volts(reg.v_z)},   0 ≤ I_Z ≤ I_ZM ({eng(reg.i_zm, 'A')})")
    else:
        s2.add("text", (
            f"İdeal zener modeli: ters iletimde (zener bölgesi) çıkış gerilimi V_Y = V_Z = "
            f"{_volts(reg.v_z)} sabit kalır; I_Z,min = 0 olmalıdır. I_ZM belirtilmediği için "
            "zener akımının üst sınırı yoktur."
        ))
        s2.add("math", f"V_Y = V_Z = {_volts(reg.v_z)},   I_Z ≥ 0")
    s2.add("math", "Çıkış düğümünde KCL:  I_X = I_Z + I_Y")
    sections.append(s2)

    # ── 3. Hesap Adımları ──
    by_sym = {st.symbol: st for st in sm.steps}
    if reg.kind == "LOAD":
        s_vx = _Sec("Seri Direnç Gerilimi ve Akımı (V_X, I_X)")
        s_vx.add("text", (
            "Zener ters iletimde iken V_Y = V_Z sabit olduğundan seri direnç R_X üzerindeki "
            "gerilim ve akım yükten bağımsız olarak sabittir:"
        ))
        s_vx.add("math", by_sym["V_X"].text)
        s_vx.add("math", by_sym["I_X"].text)
        sections.append(s_vx)

        s_iy = _Sec("Yük Akımı Sınırları (I_Y,min, I_Y,max)")
        s_iy.add("text", (
            f"Çıkış düğümünde KCL gereği I_Y = I_X {MINUS} I_Z'dir. Zener akımı en küçük (I_Z = 0) "
            "olduğunda yük akımı en büyük, zener akımı en büyük (I_Z = I_ZM) olduğunda yük akımı "
            "en küçük değerini alır:"
        ))
        s_iy.add("math", by_sym["I_Y,max"].text)
        if "I_Y,min" in by_sym:
            s_iy.add("math", by_sym["I_Y,min"].text)
        if analysis.unbounded_reason:
            s_iy.add("note", analysis.unbounded_reason)
        sections.append(s_iy)

        s_ry = _Sec("Yük Direnci Aralığı (R_Y,min, R_Y,max)")
        s_ry.add("text", (
            "Ohm yasasıyla R_Y = V_Z / I_Y'dir. Akım büyüdükçe direnç küçüldüğünden "
            "R_Y,min değeri I_Y,max'tan, R_Y,max değeri I_Y,min'den bulunur:"
        ))
        s_ry.add("math", by_sym["R_Y,min"].text)
        s_ry.add("math", by_sym["R_Y,max"].text)
        sections.append(s_ry)
    else:
        s_iy = _Sec("Yük Akımı (I_Y)")
        s_iy.add("text", (
            "Zener ters iletimde iken çıkış gerilimi V_Y = V_Z sabit olduğundan yük akımı I_Y sabittir:"
        ))
        s_iy.add("math", by_sym["I_Y"].text)
        sections.append(s_iy)

        s_ix = _Sec("Seri Direnç Akımı Sınırları (I_X,min, I_X,max)")
        s_ix.add("text", (
            "Çıkış düğümünde KCL gereği I_X = I_Y + I_Z'dir. Zener akımının alt ve üst "
            "sınırlarından seri direnç akımının sınırları bulunur:"
        ))
        s_ix.add("math", by_sym["I_X,min"].text)
        if "I_X,max" in by_sym:
            s_ix.add("math", by_sym["I_X,max"].text)
        if analysis.unbounded_reason:
            s_ix.add("note", analysis.unbounded_reason)
        sections.append(s_ix)

        s_vi = _Sec("Seri Direnç ve Giriş Gerilimi Sınırları (V_X, V_İ)")
        s_vi.add("text", "R_X üzerindeki gerilim düşümü V_X = I_X · R_X ve giriş gerilimi V_İ = V_X + V_Z'dir:")
        s_vi.add("math", by_sym["V_X,min"].text)
        s_vi.add("math", by_sym["V_İ,min"].text)
        if "V_X,max" in by_sym:
            s_vi.add("math", by_sym["V_X,max"].text)
        s_vi.add("math", by_sym["V_İ,max"].text)
        sections.append(s_vi)

    # ── 4. Sonuç ──
    s_res = _Sec("Sonuç")
    if sm.max is not None:
        s_res.add("result", f"{eng(sm.min, sm.unit)} ≤ {sm.symbol} ≤ {eng(sm.max, sm.unit)} olmalıdır.")
    else:
        s_res.add("result", f"{sm.symbol} ≥ {eng(sm.min, sm.unit)} olmalıdır ({sm.symbol},max = ∞).")
        if analysis.unbounded_reason:
            s_res.add("note", analysis.unbounded_reason)

    cur_txt = f"{sm.target_id} = {eng(sm.current_value, sm.unit)}"
    if sm.current_inside:
        s_res.add("check", f"Devredeki mevcut değer ({cur_txt}) bu aralığın içindedir ✓")
    elif sm.current_value < sm.min:
        s_res.add("note", f"Devredeki mevcut değer ({cur_txt}) alt sınırın altındadır; zener yalıtımda kalır.")
    else:
        s_res.add("note", f"⚠ Devredeki mevcut değer ({cur_txt}) üst sınırın üstündedir; zener aşırı akımdan zarar görür.")
    sections.append(s_res)

    # ── 5. Sağlama ──
    s_chk = _Sec("Sağlama")
    s_chk.add("text", (
        "Bulunan aralığı doğrulamak için aralığın altından, içinden"
        + (" ve üstünden" if sm.max is not None else "")
        + " seçilen değerlerle devre zener çözücüsüyle yeniden çözüldü:"
    ))
    for ch in sm.checks:
        if ch.verdict == "OK":
            s_chk.add("check", f"{ch.text} ✓")
        elif ch.verdict == "ABOVE":
            s_chk.add("note", ch.text)
        else:
            s_chk.add("check", ch.text)
    # Adım listesindeki kısa özet: üç sonuç birden görünsün ("2 kontrol tuttu" yanıltıcıydı,
    # çünkü aralık dışındaki değerlerin de beklendiği gibi sonuç vermesi sağlamanın parçası).
    # " = " kullanılmaz: adım özeti eşitlikleri "ilk = son" diye kısaltır ve ilk iki değer kaybolurdu.
    _verdict = {"OK": "uygun ✓", "BELOW": "yalıtımda", "ABOVE": "I_Z > I_ZM ⚠"}
    if sm.checks:
        sym = sm.checks[0].text.split(" = ")[0]
        items = [f"{ch.text.split(' → ')[0].split(' = ')[-1]} {_verdict.get(ch.verdict, ch.verdict)}"
                 for ch in sm.checks]
        s_chk.add("result", f"{sym}: " + " · ".join(items))
    sections.append(s_chk)

    return [s.build() for s in sections if s.blocks]
