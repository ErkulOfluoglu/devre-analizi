"""
CircuitAnalyzer API — Karşıtlık (reciprocity) teoremi anlatımı

Tek bağımsız kaynaklı, yalnızca R/L/C içeren devrede kaynak ile bir pasif eleman (hedef) yer
değiştirir:

    gerilim kaynağı:  1. durum I₁ = hedefin akımı,  2. durum I₂ = eski kaynak kolundaki akım,  I₁ = I₂
    akım kaynağı:     1. durum U₁ = hedefin gerilimi, 2. durum U₂ = eski kaynak uçlarındaki gerilim, U₁ = U₂

İkinci durumun sayısı çözücüden gelir (circuit_solver._solve_reciprocity: devre gerçekten
yeniden çözülür). Burada yalnızca özgün devrenin çözümüyle ve iki durumun birbiriyle
uyuştuğu bir kez daha denetlenir; uyuşmazsa (None, sebep) döner ve narrative.py düğüm
gerilimi anlatımına döner. Gizli düğüm ve yardımcı kaynak adları hiçbir cümlede geçmez.
"""

from typing import List, Optional, Tuple

from explainer.formatting import MINUS, eng, node_ek, node_name, node_v, polar, paren
from parser.netlist_parser import ElementType

_PASSIVE_KINDS = {ElementType.RESISTOR: "R", ElementType.INDUCTOR: "L", ElementType.CAPACITOR: "C"}
_TINY = 1e-15


def build_reciprocity(ctx, a) -> Tuple[Optional[list], str]:
    """(bölümler, '') ya da (None, uygulanamama sebebi)."""
    from explainer.narrative import _Section, _close

    src, tgt = a.source, a.target
    current = a.form == "current"
    c, d = tgt.node_positive, tgt.node_negative
    na, nb = src.node_positive, src.node_negative

    # ── Doğrulama: 1. durum özgün çözümle, iki durum birbiriyle ──
    if current:
        if tgt.id not in ctx.i:
            return None, f"{tgt.id} elemanının akımı çözücü sonuçlarında yok."
        solved1 = complex(ctx.i[tgt.id])
    else:
        solved1 = ctx.node_value(c) - ctx.node_value(d)
    if not _close(a.case1, solved1, 1e-6):
        return None, "ilk durumdaki değer çözücünün sonucuyla uyuşmadı."
    if not _close(a.case1, a.case2, 1e-6):
        return None, "kaynak taşınınca bulunan değer ilk durumla uyuşmadı."

    unit_q = "A" if current else "V"             # ölçülen büyüklüğün birimi
    unit_s = "V" if current else "A"             # kaynağın birimi
    q1, q2 = ("I₁", "I₂") if current else ("U₁", "U₂")
    val = ctx.val
    src_txt = val(a.source_value, unit_s)
    r_name = "aktarım direnci" if ctx.is_dc else "aktarım empedansı"
    r_sym = "R_t" if ctx.is_dc else "Z_t"

    def ohm(z: complex) -> str:
        return val(z, "Ω") if ctx.is_dc else polar(z, "Ω")

    def side(x: str) -> str:
        """İşlenen ifade: DC'de negatif değer, AC'de her fazör parantezlenir."""
        return paren(x) if ctx.is_dc else f"({x})"

    # ── 1. Teoremin ifadesi ve koşulları ──
    s1 = _Section("Karşıtlık Teoremi")
    s1.text("Karşıtlık teoremi: doğrusal ve tek kaynaklı bir devrede, kaynağı A koluna koyup B "
            "kolunda ölçülen akım, aynı kaynağı B koluna koyup A kolunda ölçülen akıma eşittir. "
            "Yani kaynak ile ölçü aleti yer değiştirirse ölçülen değer değişmez.")
    if current:
        s1.text(f"Bu devrede kaynak {src.id}, ikinci kol {tgt.id}: {src.id} kendi yerindeyken "
                f"{tgt.id} üzerinden geçen akım (I₁), {src.id} kaynağı {tgt.id} koluna "
                "taşınınca eski kaynak kolunda akan akıma (I₂) eşit olur: I₁ = I₂.")
        s1.note("Teoremin eşi: tek bir akım kaynağı bir koldan başka bir kola taşınırsa, ilk "
                "koldaki gerilim ile ikinci koldaki gerilim de birbirine eşit olur.")
    else:
        s1.text(f"Bu devrede kaynak {src.id}, ikinci kol {tgt.id}: {src.id} kendi yerindeyken "
                f"{tgt.id} elemanının uçlarındaki gerilim (U₁), {src.id} kaynağı {tgt.id} koluna "
                "taşınınca eski kaynak uçlarında oluşan gerilime (U₂) eşit olur: U₁ = U₂. "
                "(Düğüm gerilimleriyle karışmasın diye bu iki gerilime V yerine U diyoruz.)")
        s1.note("Teoremin eşi: tek bir gerilim kaynağı bir koldan başka bir kola taşınırsa, ilk "
                "koldaki akım ile ikinci koldaki akım da birbirine eşit olur.")
    passives = [e for e in ctx.elements if e.element_type in _PASSIVE_KINDS]
    s1.text("Teoremin koşulları bu devrede sağlanıyor:")
    s1.check(f"Devrede tek bağımsız kaynak var ({src.id}) ✓")
    s1.check("Bağımlı kaynak yok ✓")
    s1.check(f"Yalnızca doğrusal R, L, C elemanları var ({', '.join(e.id for e in passives)}) ✓")

    # ── 2. Birinci durum ──
    s2 = _Section("1. Durum: Kaynak Kendi Yerinde")
    if current:
        s2.text(f"{src.id} kaynağı ({src_txt}) kendi yerinde: + ucu {node_ek(na, 'e')}, − ucu "
                f"{node_ek(nb, 'e')} bağlı. Ölçeceğimiz akım, {tgt.id} elemanından "
                f"{node_name(c)} → {node_name(d)} yönünde geçen I₁'dir.")
        s2.math(f"I₁ = I_{tgt.id} = {val(a.case1, 'A')}")
        s2.result(f"I₁ = {val(a.case1, 'A')}")
        if ctx.is_dc and a.case1.real < -_TINY:
            s2.note(f"Eksi işaret, akımın gerçekte {node_name(d)} → {node_name(c)} yönünde "
                    "aktığını gösterir.")
    else:
        s2.text(f"{src.id} akım kaynağı ({src_txt}) kendi yerinde: akımı kaynak içinde "
                f"{node_name(na)} → {node_name(nb)} yönünde akar, devreye {node_name(nb)} "
                f"ucundan verilir. Ölçeceğimiz gerilim, {tgt.id} elemanının uçları arasındaki "
                f"U₁ = {node_v(c)} {MINUS} {node_v(d)} değeridir.")
        vc, vd = ctx.node_value(c), ctx.node_value(d)
        s2.math(f"U₁ = {node_v(c)} {MINUS} {node_v(d)} = {val(vc, 'V')} {MINUS} "
                f"{side(val(vd, 'V'))} = {val(a.case1, 'V')}")
        s2.result(f"U₁ = {val(a.case1, 'V')}")
        if ctx.is_dc and a.case1.real < -_TINY:
            s2.note(f"Eksi işaret, {node_name(d)} düğümünün {node_name(c)} düğümünden daha "
                    "yüksek gerilimde olduğunu gösterir.")

    # ── 3. İkinci durum ──
    s3 = _Section(f"2. Durum: Kaynak {tgt.id} Koluna Taşındı")
    if current:
        s3.text(f"{src.id} kaynağını eski yerinden çıkarıp {tgt.id} elemanıyla seri bağlıyoruz. "
                "Eski kaynak kolunda kaynak yerine kısa devre (tel) kalır.")
        s3.text(f"Kaynağın − ucu {node_ek(c, 'e')}, + ucu {tgt.id} elemanının bu düğüme bakan "
                f"ucuna bağlanır; böylece {src.id} kaynağı {tgt.id} koluna seri girer ve akımı "
                f"{node_name(c)} → {node_name(d)} yönünde sürer. Kaynağın değeri aynıdır: {src_txt}.")
        s3.text(f"Şimdi eski kaynak kolundaki akımı ölçüyoruz: kısa devre telinden "
                f"{node_name(nb)} → {node_name(na)} yönünde, yani devreye {node_name(na)} "
                "ucundan giren akım I₂'dir.")
        s3.math(f"I₂ = {val(a.case2, 'A')}")
        s3.result(f"I₂ = {val(a.case2, 'A')}")
        if ctx.is_dc and a.case2.real < -_TINY:
            s3.note(f"Eksi işaret, akımın gerçekte {node_name(na)} düğümünden devreden dışarı, "
                    f"yani {node_name(na)} → {node_name(nb)} yönünde aktığını gösterir.")
    else:
        s3.text(f"{src.id} akım kaynağını eski yerinden çıkarıyoruz: yerinde açık devre kalır, "
                "yani o kola akım gitmez.")
        s3.text(f"Aynı kaynağı {tgt.id} elemanının uçlarına, aynı yönle ({src.id} akımı kaynak "
                f"içinde {node_name(c)} → {node_name(d)}) bağlıyoruz; değeri aynıdır: {src_txt}.")
        s3.text(f"Şimdi eski kaynak uçları arasındaki gerilimi ölçüyoruz: "
                f"U₂ = {node_v(na)} {MINUS} {node_v(nb)}.")
        s3.result(f"U₂ = {val(a.case2, 'V')}")
        if ctx.is_dc and a.case2.real < -_TINY:
            s3.note(f"Eksi işaret, {node_name(nb)} düğümünün {node_name(na)} düğümünden daha "
                    "yüksek gerilimde olduğunu gösterir.")

    # ── 4. Sonuç ──
    s4 = _Section("Sonuç: Karşıtlık Kontrolü")
    s4.check(f"{q1} = {val(a.case1, unit_q)}  ve  {q2} = {val(a.case2, unit_q)}: {q1} = {q2} ✓")
    s4.text(f"Kaynak {tgt.id} koluna taşınınca ölçülen {'akım' if current else 'gerilim'} "
            "değişmedi: karşıtlık teoremi bu devrede doğrulandı.")
    # Aktarım oranı: kaynak ile ölçülen büyüklüğün oranı iki durumda da aynıdır
    # (akım kaynağında V/I sıfır olabilir; gerilim kaynağında akım sıfırsa E/I tanımsızdır)
    defined = abs(a.source_value) > _TINY and (not current or abs(a.case1) > _TINY)
    if defined:
        if current:
            ratio1 = a.source_value / a.case1
            ratio2 = a.source_value / a.case2
            f1 = f"{src.id}/I₁ = {val(a.source_value, 'V')} / {side(val(a.case1, 'A'))}"
            f2 = f"{src.id}/I₂ = {val(a.source_value, 'V')} / {side(val(a.case2, 'A'))}"
            formula = f"{r_sym} = {src.id}/I"
        else:
            ratio1 = a.case1 / a.source_value
            ratio2 = a.case2 / a.source_value
            f1 = f"U₁/{src.id} = {val(a.case1, 'V')} / {side(val(a.source_value, 'A'))}"
            f2 = f"U₂/{src.id} = {val(a.case2, 'V')} / {side(val(a.source_value, 'A'))}"
            formula = f"{r_sym} = V/{src.id}"
        is_are = "aktarım direncidir" if ctx.is_dc else "aktarım empedansıdır"
        s4.text(f"Karşıtlığın bir göstergesi de {is_are} ({formula}): kaynak ile ölçülen "
                f"büyüklüğün oranı iki durumda da aynı çıkar.")
        s4.math(f"{r_sym} = {f1} = {ohm(ratio1)}")
        s4.math(f"{r_sym} = {f2} = {ohm(ratio2)}")
        s4.result(f"{r_name.capitalize()} {r_sym} = {ohm(ratio1)}")
    else:
        s4.note(f"Akım sıfır olduğundan {r_name} (kaynak/akım oranı) bu devrede tanımlı "
                "değildir (sonsuz); yine de iki durumda da sonuç aynıdır.")
    return [s1, s2, s3, s4], ""
