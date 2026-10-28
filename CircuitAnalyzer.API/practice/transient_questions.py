"""
CircuitAnalyzer API — Geçici durum (TRANSIENT) alıştırma soruları

Sorular (kitaptaki tipik soru türleri):

    main   τ · x(0⁺) · x(∞) · x(τ) · "ne kadar sürede … olur?" (ln)
    extra  seçilen bir t anında x(t) · diğer büyüklüğün 0⁺ değeri (C akımı / L gerilimi)

Doğru değerler çözücünün TransientAnalysis sonucundan alınır (anlatımla aynı sayılar).
İpuçları cevabı vermez; yalnızca yöntemi hatırlatır.
"""

import math
from typing import Callable, List

from explainer.formatting import eng
from models.response import ComplexNumber, PracticeAlternative, PracticeQuestion
from solver.transient import TransientAnalysis

TIME_TO_LEVEL_FRACTION = 0.9      # değişimin %90'ı


def _nice_time(t: float) -> float:
    """t'yi tek anlamlı basamağa yuvarlar (4.37 ms → 4 ms)."""
    if t <= 0:
        return t
    exp = math.floor(math.log10(t))
    return round(t / 10 ** exp) * 10 ** exp


def build_transient_questions(
    a: TransientAnalysis, to_cn: Callable[[complex], ComplexNumber]
) -> List[PracticeQuestion]:
    is_c = a.kind == "C"
    x_lbl, o_lbl = a.x_label, a.other_label
    unit = "V" if is_c else "A"
    o_unit = "A" if is_c else "V"
    what = "kondansatör gerilimi" if is_c else "bobin akımı"
    o_what = "kondansatör akımı" if is_c else "bobin gerilimi"
    sid = a.storage.id
    x0, xf, tau = a.x_start, a.x_final, a.tau
    span = max(abs(x0), abs(xf), 1e-12)
    n1, n2 = a.storage.node_positive, a.storage.node_negative

    def q(id_, label, description, q_unit, group, expected, scale, hint, sign_hint,
          alternatives=()) -> PracticeQuestion:
        exp = complex(expected)
        alts = [PracticeAlternative(value=to_cn(complex(v)), message=m)
                for v, m in alternatives
                if abs(complex(v) - exp) > 0.02 * max(abs(exp), 1e-3 * scale, 1e-12)]
        return PracticeQuestion(
            id=id_, label=label, description=description, unit=q_unit, group=group,
            is_ac=False, frequency=None, expected=to_cn(exp), scale=scale,
            hint=hint, sign_hint=sign_hint, alternatives=alts,
        )

    out: List[PracticeQuestion] = []

    # ── τ ──
    tau_alts = [(5 * tau, "Bu 5τ (değişimin pratikte bittiği süre); sorulan bir τ'dur.")]
    if is_c:
        hint = (f"t > 0 konumunda {sid}'yi devreden çıkarın, bağımsız kaynakları sıfırlayın "
                f"(gerilim kaynağı → tel, akım kaynağı → açık devre) ve uçlarından bakıp R_th'yi "
                f"bulun. Sonra τ = R_th · C.")
    else:
        hint = (f"t > 0 konumunda {sid}'yi devreden çıkarın, bağımsız kaynakları sıfırlayın "
                f"(gerilim kaynağı → tel, akım kaynağı → açık devre) ve uçlarından bakıp R_th'yi "
                f"bulun. Sonra τ = L / R_th.")
        tau_alts.append((a.value * a.r_th, "RL devresinde τ = L / R_th'dir (bölme); L ile R_th'yi "
                                           "çarpmışsınız."))
    out.append(q("TAU", "τ", "Zaman sabitesi τ (t > 0 devresi için)", "s", "main", tau, tau,
                 hint=hint, sign_hint="Zaman sabitesi pozitiftir.", alternatives=tau_alts))

    # ── x(0⁺) ──
    out.append(q(
        "X0", f"{x_lbl}(0⁺)", f"t = 0⁺ anında (anahtar değiştikten hemen sonra) {what} {x_lbl}",
        unit, "main", x0, span,
        hint=(f"Süreklilik: {x_lbl}(0⁺) = {x_lbl}(0⁻). t < 0 devresini DC kararlı hâlde çözün "
              f"({'kondansatör açık devre' if is_c else 'bobin kısa devre'}); anahtar açıkken "
              f"{sid} kaynağa bağlı değilse boş kabul edilir."),
        sign_hint=f"İşaret ters: {x_lbl}, {sid}'nin Düğüm {n1} ucu (+) alınarak "
                  f"{'V(' + n1 + ') − V(' + n2 + ')' if is_c else 'Düğüm ' + n1 + ' → Düğüm ' + n2 + ' yönünde'} hesaplanır.",
    ))

    # ── x(∞) ──
    out.append(q(
        "XINF", f"{x_lbl}(∞)", f"t → ∞ iken (yeni kararlı hâlde) {what} {x_lbl}",
        unit, "main", xf, span,
        hint=(f"t > 0 devresini DC kararlı hâlde çözün: "
              f"{'kondansatör açık devre (akımı 0)' if is_c else 'bobin kısa devre (gerilimi 0)'}. "
              f"{x_lbl}(∞) bu devrede {sid}'nin " + ("uçları arasındaki gerilimdir." if is_c else "içinden geçen akımdır.")),
        sign_hint=f"İşaret ters: yönleri {sid}'nin Düğüm {n1} → Düğüm {n2} sırasına göre alın.",
    ))

    # ── x(τ) ──
    x_tau = a.x_at(tau)
    out.append(q(
        "XTAU", f"{x_lbl}(τ)", f"t = τ = {eng(tau, 's')} anında {what} {x_lbl}",
        unit, "main", x_tau, span,
        hint=(f"{x_lbl}(t) = {x_lbl}(∞) + [{x_lbl}(0) − {x_lbl}(∞)] · e^(−t/τ) formülünde t = τ "
              "yazın: e⁻¹ ≈ 0.368. (Değişimin %63.2'si tamamlanmış olur.)"),
        sign_hint="İşaret ters: başlangıç ve son değerin işaretlerini kontrol edin.",
        alternatives=[
            (abs(x0 - xf) * (1 - math.exp(-1)),
             "Bu, tamamlanan değişimin miktarı (%63.2'si); soru değerin kendisini soruyor "
             f"({x_lbl}(τ) = {x_lbl}(∞) + [{x_lbl}(0) − {x_lbl}(∞)]·e⁻¹)."),
            (xf, f"Bu {x_lbl}(∞): τ anında henüz son değere ulaşılmadı."),
        ],
    ))

    # ── "ne kadar sürede … olur?" ──
    target = x0 + TIME_TO_LEVEL_FRACTION * (xf - x0)
    ratio = (x0 - xf) / (target - xf)
    t_level = tau * math.log(ratio)
    out.append(q(
        "TLEVEL", "t",
        f"{x_lbl} ne kadar sürede (t = 0 anından itibaren) {eng(target, unit)} değerine ulaşır?",
        "s", "main", t_level, tau,
        hint=(f"{x_lbl}(t) = {x_lbl}(∞) + [{x_lbl}(0) − {x_lbl}(∞)] · e^(−t/τ) denkleminde "
              f"{x_lbl}(t) yerine {eng(target, unit)} yazıp e^(−t/τ) terimini yalnız bırakın, "
              "sonra iki tarafın doğal logaritmasını (ln) alın: "
              f"t = τ · ln[({x_lbl}(0) − {x_lbl}(∞)) / ({x_lbl}(t) − {x_lbl}(∞))]."),
        sign_hint="Süre pozitif çıkmalı: ln içindeki oran 1'den büyük olacak şekilde yazın.",
        alternatives=[
            (tau * math.log10(ratio), "Doğal logaritma (ln) kullanılmalı, 10 tabanlı logaritma (log) değil."),
            (5 * tau, "Bu 5τ (değişimin pratikte bittiği süre); sorulan, belirtilen değere ulaşma süresi."),
            (tau, "Bu bir τ'dur (değişimin %63.2'si); belirtilen değere ulaşma süresini ln ile bulun."),
        ],
    ))

    # ── Seçilen bir anda x(t) (ek) ──
    t_given = _nice_time(2 * tau)
    out.append(q(
        "XT", f"{x_lbl}(t)", f"t = {eng(t_given, 's')} anında {what} {x_lbl}",
        unit, "extra", a.x_at(t_given), span,
        hint=(f"{x_lbl}(t) = {x_lbl}(∞) + [{x_lbl}(0) − {x_lbl}(∞)] · e^(−t/τ) formülünde "
              f"t = {eng(t_given, 's')} ve τ = {eng(tau, 's')} yazın (aynı birimde, saniye)."),
        sign_hint="İşaret ters: başlangıç ve son değerin işaretlerini kontrol edin.",
        alternatives=[(xf, f"Bu {x_lbl}(∞): bu anda henüz son değere ulaşılmadı."),
                      (x0, f"Bu {x_lbl}(0): bu anda değer başlangıçtan farklıdır.")],
    ))

    # ── Diğer büyüklüğün 0⁺ değeri (ek) ──
    o0 = a.other_start
    o_scale = max(abs(o0), 1e-12)
    out.append(q(
        "O0", f"{o_lbl}(0⁺)",
        f"t = 0⁺ anında {o_what} {o_lbl} (Düğüm {n1} → Düğüm {n2} yönünde"
        + (")" if is_c else f"; V = V({n1}) − V({n2}))"),
        o_unit, "extra", o0, o_scale,
        hint=((f"t = 0⁺ anında {sid} değeri {eng(x0, unit)} olan bir gerilim kaynağı gibidir "
               f"(boşsa kısa devre). Devreyi bu modelle çözün; ya da {o_lbl}(0⁺) = "
               f"({x_lbl}(∞) − {x_lbl}(0⁺)) / R_th.") if is_c else
              (f"t = 0⁺ anında {sid} değeri {eng(x0, unit)} olan bir akım kaynağı gibidir "
               f"(enerjisizse açık devre). Devreyi bu modelle çözün; ya da {o_lbl}(0⁺) = "
               f"({x_lbl}(∞) − {x_lbl}(0⁺)) · R_th.")),
        sign_hint=(f"İşaret ters: {o_lbl} için yön {sid}'nin Düğüm {n1} → Düğüm {n2} sırasıdır; "
                   "deşarj olurken kondansatör akımı bu yönün tersine aktığı için eksi çıkar."
                   if is_c else
                   f"İşaret ters: V_{sid} = V({n1}) − V({n2}) alınır."),
    ))
    return out
