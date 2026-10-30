"""
CircuitAnalyzer API — Rezonans anlatımı (seri ve paralel RLC)

Bölüm sırası:
    Devreyi Tanıyalım → Rezonans Koşulu → Rezonans Frekansı → Reaktanslar →
    Rezonansta Empedans ve Akım → Kalite Faktörü Q → Bant Genişliği →
    Eleman Gerilimleri / Akımları → Kontrol → Sonuç

Tüm sayılar solver.resonance.ResonanceAnalysis'ten gelir; bu analiz lcapy ile
bağımsız olarak denetlenmeden (verify_with_lcapy) anlatım üretilmez.
Gerilim sembolü V'dir; kitaplardaki U gösterimi bir notla belirtilir.
"""

import math
from typing import List

from explainer.formatting import MINUS, eng, num
from explainer.narrative import _Section, _intro

U_NOTE = "Kitaplarda gerilim U ile de gösterilir (U = V)."


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(abs(a), abs(b), 1e-300)


def build_resonance_sections(ctx, a) -> List[_Section]:
    series = a.kind == "series"
    sections: List[_Section] = []

    # ── Devreyi Tanıyalım ──
    intro = _intro(ctx)
    if a.source_freq_differs:
        intro[0].note(
            f"Kaynağın frekansı f = {eng(a.source_freq, 'Hz')}; aşağıdaki değerler kaynak "
            "f₀'da çalışsaydı geçerlidir."
        )
    sections.extend(intro)

    r_ids = [e.id for e in a.resistors]
    l_id, c_id, src_id = a.inductor.id, a.capacitor.id, a.source.id

    # ── Rezonans Koşulu ──
    s = _Section("Rezonans Koşulu")
    if series:
        s.text(
            f"Bu devre bir seri RLC devresidir: {src_id} kaynağı, {', '.join(r_ids)}, {l_id} ve "
            f"{c_id} tek gözde seri bağlıdır."
        )
        if len(r_ids) > 1:
            s.text("Seri bağlı dirençler toplanır:")
            s.math(f"R = {' + '.join(r_ids)} = "
                   f"{' + '.join(eng(e.value, 'Ω') for e in a.resistors)} = {eng(a.r, 'Ω')}")
        s.math("Z = R + j(X_L − X_C)")
    else:
        s.text(
            f"Bu devre bir paralel RLC devresidir: {r_ids[0]}, {l_id}, {c_id} ve {src_id} kaynağı "
            "aynı iki düğüm arasında bağlıdır."
        )
        s.math("Y = 1/R + j(1/X_C − 1/X_L)")
    s.text(
        "Bobinin reaktansı X_L = ωL frekansla artar, kondansatörün reaktansı X_C = 1/(ωC) "
        "frekansla azalır. İkisinin eşit olduğu frekansta reaktif etkiler birbirini götürür ve "
        "empedansın sanal kısmı sıfır olur: devre kaynağa yalnızca bir dirençmiş gibi görünür. "
        "Buna rezonans denir."
    )
    s.math("X_L = X_C   →   ω₀L = 1/(ω₀C)   →   ω₀² = 1/(LC)")
    sections.append(s)

    # ── Rezonans Frekansı ──
    s = _Section("Rezonans Frekansı")
    s.text("Koşuldan açısal rezonans frekansı ω₀ ve rezonans frekansı f₀ bulunur:")
    s.math(f"ω₀ = 1/√(L·C) = 1/√({eng(a.l, 'H')} · {eng(a.c, 'F')}) = {num(a.w0)} rad/s")
    s.math(f"f₀ = ω₀/(2π) = {num(a.w0)} / (2π) = {eng(a.f0, 'Hz')}")
    s.result(f"f₀ = {eng(a.f0, 'Hz')}  (ω₀ = {num(a.w0)} rad/s)")
    sections.append(s)

    # ── Reaktanslar ──
    s = _Section("Reaktanslar")
    x_l = a.w0 * a.l
    x_c = 1.0 / (a.w0 * a.c)
    s.text("Rezonans frekansında bobinin ve kondansatörün reaktansları:")
    s.math(f"X_L = ω₀L = {num(a.w0)} rad/s · {eng(a.l, 'H')} = {eng(x_l, 'Ω')}")
    s.math(f"X_C = 1/(ω₀C) = 1/({num(a.w0)} rad/s · {eng(a.c, 'F')}) = {eng(x_c, 'Ω')}")
    if _same(x_l, x_c) and _same(x_l, a.x):
        s.text("İki reaktans eşit çıktı: rezonans koşulu sağlanıyor.")
    s.result(f"X = X_L = X_C = {eng(a.x, 'Ω')}")
    sections.append(s)

    # ── Rezonansta Empedans ve Akım ──
    if series:
        s = _Section("Rezonansta Empedans ve Akım")
        s.text("Rezonansta X_L − X_C = 0 olduğundan seri devrenin empedansı yalnızca dirençten "
               "ibarettir; empedans en küçük değerini, akım en büyük değerini alır:")
        s.math(f"Z₀ = R + j(X_L {MINUS} X_C) = R = {eng(a.r, 'Ω')}")
        s.math(f"I_max = V / Z₀ = V / R = {eng(a.amp, 'V')} / {eng(a.r, 'Ω')} = {eng(a.i0, 'A')}")
        s.text("Devre kaynağa dirençmiş gibi göründüğünden akım, kaynak gerilimiyle aynı fazdadır.")
    elif a.source_is_current:
        s = _Section("Rezonansta Empedans ve Gerilim")
        s.text("Rezonansta bobin ve kondansatör kollarının admitansları birbirini götürür; "
               "paralel devrenin empedansı yalnızca dirençten ibarettir ve en büyük değerini alır. "
               "Kaynak akımı bu empedans üzerinde en büyük gerilimi oluşturur:")
        s.math(f"Y₀ = 1/R + j(1/X_C {MINUS} 1/X_L) = 1/R   →   Z₀ = R = {eng(a.r, 'Ω')}")
        s.math(f"V_max = I · Z₀ = I · R = {eng(a.amp, 'A')} · {eng(a.r, 'Ω')} = {eng(a.v0, 'V')}")
    else:
        s = _Section("Rezonansta Empedans ve Akım")
        s.text("Rezonansta bobin ve kondansatör kolları eşit büyüklükte, ters yönlü akım çeker ve "
               "birbirini götürür; kaynaktan çekilen akım yalnızca direncin akımıdır. Paralel "
               "devrenin empedansı en büyük değerini, kaynak akımı en küçük değerini alır:")
        s.math(f"Y₀ = 1/R + j(1/X_C {MINUS} 1/X_L) = 1/R   →   Z₀ = R = {eng(a.r, 'Ω')}")
        s.math(f"I_min = V / Z₀ = V / R = {eng(a.amp, 'V')} / {eng(a.r, 'Ω')} = {eng(a.i0, 'A')}")
    s.note(U_NOTE)
    sections.append(s)

    # ── Kalite Faktörü Q ──
    s = _Section("Kalite Faktörü Q")
    if series:
        s.math(f"Q = X / R = {eng(a.x, 'Ω')} / {eng(a.r, 'Ω')} = {num(a.q)}")
    else:
        s.math(f"Q = R / X = {eng(a.r, 'Ω')} / {eng(a.x, 'Ω')} = {num(a.q)}")
    s.text("Q birimsizdir ve rezonans eğrisinin keskinliğini gösterir: Q büyükse eğri dar "
           "(seçici), küçükse geniştir.")
    s.result(f"Q = {num(a.q)}")
    sections.append(s)

    # ── Bant Genişliği ──
    s = _Section("Bant Genişliği")
    s.text(
        "Bant genişliği, "
        + ("akımın I_max değerinin" if series else "empedansın Z₀ değerinin")
        + " 1/√2 ≈ 0,707 katına düştüğü iki frekansın (yarım güç frekansları f₁ ve f₂) "
          "arasındaki aralıktır."
    )
    s.math(f"BW = f₀ / Q = {eng(a.f0, 'Hz')} / {num(a.q)} = {eng(a.bw, 'Hz')}")
    s.math(f"f₁ = f₀ {MINUS} BW/2 = {eng(a.f0, 'Hz')} {MINUS} {eng(a.bw / 2, 'Hz')} = {eng(a.f1, 'Hz')}")
    s.math(f"f₂ = f₀ + BW/2 = {eng(a.f0, 'Hz')} + {eng(a.bw / 2, 'Hz')} = {eng(a.f2, 'Hz')}")
    if a.low_q:
        s.note(
            "Q küçük olduğundan kitaptaki f₀ ∓ BW/2 yaklaşıktır; tam değerler "
            f"f₁ = {eng(a.f1_exact, 'Hz')}, f₂ = {eng(a.f2_exact, 'Hz')}."
        )
        if a.f1 <= 0:
            s.text("Bu Q değerinde f₀ − BW/2 sıfırın altına düşüyor; yaklaşık biçim anlamını yitirir, "
                   "tam değerleri kullanın.")
    s.result(f"BW = {eng(a.bw, 'Hz')}, f₁ = {eng(a.f1, 'Hz')}, f₂ = {eng(a.f2, 'Hz')}")
    sections.append(s)

    # ── Eleman Gerilimleri / Akımları ──
    if series:
        s = _Section("Eleman Gerilimleri")
        s.text("Rezonansta akım I_max olduğundan bobin ve kondansatör gerilimleri eşit büyüklükte "
               "ve ters yöndedir; birbirini götürdüğü için kaynak gerilimi tamamen dirençler "
               "üzerinde düşer:")
        s.math(f"V_L = I_max · X_L = {eng(a.i0, 'A')} · {eng(a.x, 'Ω')} = {eng(a.i0 * a.x, 'V')}")
        s.math(f"V_C = I_max · X_C = {eng(a.i0, 'A')} · {eng(a.x, 'Ω')} = {eng(a.i0 * a.x, 'V')}")
        s.math(f"V_L = V_C = Q · V = {num(a.q)} · {eng(a.amp, 'V')} = {eng(a.v0, 'V')}")
        if a.q > 1:
            s.note("Q > 1 olduğundan bobin ve kondansatör gerilimleri kaynak geriliminden büyüktür "
                   "(aşırı gerilim).")
        s.result(f"V_L = V_C = {eng(a.v0, 'V')}")
    else:
        i_r = a.v0 / a.r
        i_x = a.v0 / a.x
        s = _Section("Eleman Akımları")
        s.text("Rezonansta bobin ve kondansatör akımları eşit büyüklükte ve ters yöndedir; "
               "birbirini götürdüğü için kaynak akımı yalnızca dirençten geçer:")
        s.math(f"I_R = V / R = {eng(a.v0, 'V')} / {eng(a.r, 'Ω')} = {eng(i_r, 'A')}")
        s.math(f"I_L = V / X_L = {eng(a.v0, 'V')} / {eng(a.x, 'Ω')} = {eng(i_x, 'A')}")
        s.math(f"I_C = V / X_C = {eng(a.v0, 'V')} / {eng(a.x, 'Ω')} = {eng(i_x, 'A')}")
        s.math(f"I_L = I_C = Q · I_R = {num(a.q)} · {eng(i_r, 'A')} = {eng(a.q * i_r, 'A')}")
        if a.q > 1:
            s.note("Q > 1 olduğundan bobin ve kondansatör akımları dirençten (ve kaynaktan) çekilen "
                   "akımdan büyüktür (aşırı akım).")
        s.result(f"I_L = I_C = {eng(i_x, 'A')}")
    sections.append(s)

    # ── Kontrol (lcapy) ──
    chk = a.check
    s = _Section("Kontrol")
    if chk is not None:
        s.check(f"Çözücüyle f₀ = {eng(a.f0, 'Hz')} frekansında kaynaktan görülen empedans "
                f"Z = {eng(chk.z_f0.real, 'Ω')} (sanal kısım sıfır): Z = R ✓")
        if a.kind == "parallel" and a.source_is_current:
            s.check(f"Çözücüde f₀'daki gerilim |V| = {eng(chk.main_f0, 'V')} = I·R ✓")
        else:
            label = "I_max" if series else "I_min"
            s.check(f"Çözücüde f₀'daki akım |I| = {eng(chk.main_f0, 'A')} = {label} ✓")
        if series:
            s.check(f"Çözücüde |V_L| = |V_C| = {eng(chk.elem_f0, 'V')} = Q·V ✓")
        else:
            s.check(f"Çözücüde |I_L| = |I_C| = {eng(chk.elem_f0, 'A')} = Q·I_R ✓")
        if series:
            half = a.i0 / math.sqrt(2.0)
            s.check(f"Tam yarım güç frekanslarında f₁ = {eng(a.f1_exact, 'Hz')} ve "
                    f"f₂ = {eng(a.f2_exact, 'Hz')} çözücüde |I| = {eng(chk.main_f1, 'A')} ve "
                    f"{eng(chk.main_f2, 'A')}; I_max/√2 = {eng(half, 'A')} ✓")
        else:
            half = a.r / math.sqrt(2.0)
            s.check(f"Tam yarım güç frekanslarında f₁ = {eng(a.f1_exact, 'Hz')} ve "
                    f"f₂ = {eng(a.f2_exact, 'Hz')} çözücüde |Z| = {eng(chk.main_f1, 'Ω')} ve "
                    f"{eng(chk.main_f2, 'Ω')}; R/√2 = {eng(half, 'Ω')} ✓")
        s.check(f"f₂ {MINUS} f₁ = {eng(a.f2_exact - a.f1_exact, 'Hz')} = BW ✓")
    sections.append(s)

    # ── Sonuç ──
    s = _Section("Sonuç")
    s.result(f"f₀ = {eng(a.f0, 'Hz')}, ω₀ = {num(a.w0)} rad/s, X = {eng(a.x, 'Ω')}")
    s.result(f"Q = {num(a.q)}, BW = {eng(a.bw, 'Hz')}, f₁ = {eng(a.f1, 'Hz')}, f₂ = {eng(a.f2, 'Hz')}")
    if series:
        s.result(f"Z₀ = {eng(a.z0, 'Ω')}, I_max = {eng(a.i0, 'A')}, V_L = V_C = {eng(a.v0, 'V')}")
    elif a.source_is_current:
        s.result(f"Z₀ = {eng(a.z0, 'Ω')}, V_max = {eng(a.v0, 'V')}, I_L = I_C = {eng(a.v0 / a.x, 'A')}")
    else:
        s.result(f"Z₀ = {eng(a.z0, 'Ω')}, I_min = {eng(a.i0, 'A')}, I_L = I_C = {eng(a.v0 / a.x, 'A')}")
    sections.append(s)

    return sections
