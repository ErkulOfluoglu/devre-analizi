"""
Faz 2 kapsamlı köşe durumu testleri:
- Anahtar ayrıştırma ve geçici durum (NO, NC, SPDT; RC ve RL şarj/deşarj/kısmi geçiş/kutup değişimi;
  t<0'da kaynaksız durum; akım kaynaklı devre; R_th'nin Δ–Y gerektirdiği devre; birden çok anahtar;
  reddedilen tüm durumlar ve fallback; x(0⁻), x(0⁺), x(∞), τ ve enerji değerleri)
- Alıştırma soruları ve cevap denetimi (transient_questions.py, checker.py, answer_parser.py:
  virgül, M/m, kutupsal, dikdörtgen, birim/ölçek/işaret ipuçları, bozuk girişler)
- Ondalık virgül biçimlendirmesi (formatting.py; netlist ve JSON'da nokta kalması)

Tüm beklenen değerler elle/analitik olarak hesaplanmış ve her testin yorumunda açıklanmıştır.
"""

import cmath
import math
import pytest

from explainer.formatting import (
    MINUS, eng, fmt, node_v, num, paren, polar, rect, sub, value,
)
from models.response import ComplexNumber, PracticeQuestion
from parser.netlist_parser import circuit_at_time, parse_netlist, to_lcapy_netlist
from practice.answer_parser import AnswerParseError, parse_answer
from practice.checker import check_answer
from solver.transient import TransientNotApplicable, analyze_transient

GND = "* GND1 — Referans toprak (Node 0)"


def all_text(results) -> str:
    return "\n".join(b.text for s in results.explanation for b in s.blocks)


def get_quantity(results, qid: str):
    return next(q for q in results.transient.quantities if q.id == qid)


# ═══════════════════════════════════════════════════════════════════════════
#  1. GEÇİCİ DURUM (ANAHTARLI RC / RL)
# ═══════════════════════════════════════════════════════════════════════════

def test_transient_rc_spdt_polarity_reversal_and_energy(solve):
    """
    SPDT anahtarlı RC devresinde kutup değiştiren geçiş (V_C(0⁻) > 0 → V_C(∞) < 0):
    V1 1 0 DC 10 (+10 V), V2 0 2 DC 6 (-6 V Düğüm 2'de),
    S1 3 1 2 SPDT (ortak uç 3: t<0'da 1'e bağlı, t≥0'da 2'ye bağlı),
    R1 3 4 2000 (2 kΩ), C1 4 0 5u (5 µF).
    Analitik hesap:
      t < 0 (S1: 3–1 bağlı):
        C1 açık devre → I_R1 = 0 → V_C1(0⁻) = V1 = +10 V.
      Süreklilik:
        V_C1(0⁺) = +10 V.
      t → ∞ (S1: 3–2 bağlı):
        C1 açık devre → I_R1 = 0 → V_C1(∞) = V2_düğüm = -6 V.
      Zaman sabiti:
        R_th = R1 = 2000 Ω,  τ = R_th · C1 = 2000 · 5e-6 = 0.01 s = 10 ms.
      t = 0⁺ kondansatör akımı (4 → 0 yönünde):
        I_C1(0⁺) = (V_C1(∞) - V_C1(0⁺)) / R_th = (-6 - 10) / 2000 = -16 / 2000 = -0.008 A = -8 mA.
      Depolanan enerji:
        W(0⁺) = 0.5 · C · V(0⁺)² = 0.5 · 5e-6 · 10² = 2.5e-4 J = 250 µJ.
        W(∞)  = 0.5 · C · V(∞)²  = 0.5 · 5e-6 · (-6)² = 9.0e-5 J = 90 µJ.
    """
    net = f"V1 1 0 DC 10\nV2 0 2 DC 6\nS1 3 1 2 SPDT\nR1 3 4 2000\nC1 4 0 5u\n{GND}"
    res, _, err = solve(net, analysis_type="TRANSIENT")
    assert err == [] and res.transient is not None
    assert res.transient.r_th == pytest.approx(2000.0, rel=1e-6)
    assert res.transient.tau == pytest.approx(0.01, rel=1e-6)

    vc = get_quantity(res, "V_C1")
    ic = get_quantity(res, "I_C1")
    assert (vc.before, vc.start, vc.final) == pytest.approx((10.0, 10.0, -6.0), rel=1e-6)
    assert (ic.before, ic.start, ic.final) == pytest.approx((0.0, -0.008, 0.0), rel=1e-6)

    txt = all_text(res)
    assert "250 µJ" in txt and "90 µJ" in txt
    assert "−8 mA" in txt


def test_transient_rl_current_source_and_multiple_switches(solve):
    """
    Akım kaynaklı ve çift anahtarlı (NO + NC) RL geçici durum devresi:
    I1 0 1 DC 0.06 (60 mA, 0 → 1), R1 1 0 100 Ω,
    S1 1 2 NC (t<0 kapalı, t=0 açılır), R2 2 0 150 Ω,
    S2 2 3 NO (t<0 açık, t=0 kapanır), R3 3 0 300 Ω,
    L1 2 0 0.3 (300 mH).
    Analitik hesap:
      t < 0 (S1 kapalı → Düğüm 1 ve 2 birleşir; S2 açık → R3 devrede değil):
        L1 kısa devre (Düğüm 2 → 0 doğrudan tel!).
        Paralel R1 (100 Ω) ve R2 (150 Ω) kısa devre olan L1'e paralel olduğundan
        uçlarındaki gerilim 0 V olur ve I1 = 60 mA akımının tamamı L1 üzerinden (2 → 0) geçer:
        I_L1(0⁻) = 0.06 A = 60 mA!
      Süreklilik:
        I_L1(0⁺) = 0.06 A = 60 mA.
      t > 0 (S1 açık → I1+R1 kolu ayrılır; S2 kapalı → Düğüm 2 ve 3 birleşir):
        L1 uçlarında R2 = 150 Ω ve R3 = 300 Ω paralel bağlıdır, kaynak yoktur:
        I_L1(∞) = 0 A.
        R_th = R2 || R3 = (150 · 300) / (150 + 300) = 100 Ω.
        τ = L1 / R_th = 0.3 / 100 = 0.003 s = 3 ms.
        V_L1(0⁺) = (I_L1(∞) - I_L1(0⁺)) · R_th = (0 - 0.06) · 100 = -6.0 V.
      Enerji:
        W(0⁺) = 0.5 · L · I(0⁺)² = 0.5 · 0.3 · (0.06)² = 5.4e-4 J = 540 µJ,  W(∞) = 0 J.
    """
    net = (
        f"I1 0 1 DC 0.06\nR1 1 0 100\nS1 1 2 NC\nR2 2 0 150\n"
        f"S2 2 3 NO\nR3 3 0 300\nL1 2 0 0.3\n{GND}"
    )
    res, _, err = solve(net, analysis_type="TRANSIENT")
    assert err == [] and res.transient is not None
    assert res.transient.r_th == pytest.approx(100.0, rel=1e-6)
    assert res.transient.tau == pytest.approx(0.003, rel=1e-6)

    vl = get_quantity(res, "V_L1")
    il = get_quantity(res, "I_L1")
    assert (il.before, il.start, il.final) == pytest.approx((0.06, 0.06, 0.0), rel=1e-6)
    assert (vl.before, vl.start, vl.final) == pytest.approx((0.0, -6.0, 0.0), rel=1e-6)
    assert "540 µJ" in all_text(res)


def test_transient_rth_requires_delta_y_bridge_reduction(solve):
    """
    t > 0 konumunda R_th hesabının Δ–Y dönüşümü gerektirdiği gerçek köprü devresi:
    V1 1 0 DC 12, S1 1 5 NO (t<0 açık, t=0 kapanır), R0 5 2 3 Ω,
    Köprü (Düğüm 2, 3, 4, 0):
      R1 2 3 6, R2 2 4 6, R3 3 4 6 (Δ(2,3,4) üçgeni: her kenar 6 Ω),
      R4 3 0 4, R5 4 0 4,
    Kondansatör C1 4 0 60u (Düğüm 4 ile 0 arasında).
    Analitik hesap:
      t < 0 (S1 açık, devrede kaynak bağlı değil):
        V_C1(0⁻) = 0 V,  V_C1(0⁺) = 0 V.
      t > 0 (S1 kapalı → V1=12 V R0=3 Ω üzerinden Düğüm 2'yi besler):
        1) t → ∞ (C1 açık devre):
           Simetriden V3 = V4 ⇒ R3 (3–4) üzerinden akım geçmez!
           R1 || R2 = 6 || 6 = 3 Ω,  R4 || R5 = 4 || 4 = 2 Ω.
           Toplam direnç: R0 (3 Ω) + 3 Ω + 2 Ω = 8 Ω  ⇒  I_toplam = 12 / 8 = 1.5 A.
           V_C1(∞) = V4(∞) = 1.5 · 2 = 3.0 V!
        2) R_th (Düğüm 4 ile 0 arasından, V1 = 0 ⇒ R0 = 3 Ω Düğüm 2–0 arasında):
           Δ(2,3,4) [6,6,6 Ω] → Y(Y1): her kol 2 Ω.
           Düğüm 2 kolu: R0 + 2 = 5 Ω; Düğüm 3 kolu: R4 + 2 = 6 Ω.
           5 || 6 = 30/11 Ω; seri 2 Ω (Y1–4) ile: 30/11 + 2 = 52/11 Ω.
           Paralel R5 (4 Ω) ile: R_th = (52/11 · 4) / (52/11 + 4) = 208 / 96 = 13 / 6 ≈ 2.166667 Ω!
        3) Zaman sabiti ve başlangıç akımı:
           τ = R_th · C1 = (13/6) · 60e-6 = 130 µs = 1.3e-4 s.
           I_C1(0⁺) = V_C1(∞) / R_th = 3.0 / (13/6) = 18 / 13 ≈ 1.384615 A.
    """
    net = (
        f"V1 1 0 DC 12\nS1 1 5 NO\nR0 5 2 3\nR1 2 3 6\nR2 2 4 6\nR3 3 4 6\n"
        f"R4 3 0 4\nR5 4 0 4\nC1 4 0 60u\n{GND}"
    )
    res, _, err = solve(net, analysis_type="TRANSIENT")
    assert err == [] and res.transient is not None
    assert res.transient.r_th == pytest.approx(13.0 / 6.0, rel=1e-4)
    assert res.transient.tau == pytest.approx(1.3e-4, rel=1e-4)

    vc = get_quantity(res, "V_C1")
    ic = get_quantity(res, "I_C1")
    assert (vc.before, vc.start, vc.final) == pytest.approx((0.0, 0.0, 3.0), rel=1e-5)
    assert ic.start == pytest.approx(18.0 / 13.0, rel=1e-4)
    assert "üçgen (Δ)" in all_text(res)


def test_transient_t_before_isolated_capacitor_uncharged(solve):
    """
    t < 0 konumunda kondansatörün gerçekten hiçbir kaynağa bağlı olmadığı (yalıtılmış) durum:
    V1 1 0 DC 15, R1 1 2 500, S1 2 3 NO, C1 3 0 10u, R2 1 0 1000.
    t < 0'da S1 açık olduğundan C1 yalnızca Düğüm 3 ve 0 arasındadır, Düğüm 3'e başka eleman bağlı değildir.
    Analitik hesap:
      V_C1(0⁻) = 0 V (yalıtılmış, başlangıçta boş kabul edilir),
      V_C1(∞) = 15 V,  R_th = R1 = 500 Ω,  τ = 500 · 10e-6 = 5 ms,
      I_C1(0⁺) = 15 / 500 = 30 mA.
    """
    net = f"V1 1 0 DC 15\nR1 1 2 500\nS1 2 3 NO\nC1 3 0 10u\nR2 1 0 1000\n{GND}"
    res, _, err = solve(net, analysis_type="TRANSIENT")
    assert err == [] and res.transient is not None
    vc = get_quantity(res, "V_C1")
    assert (vc.before, vc.start, vc.final) == pytest.approx((0.0, 0.0, 15.0), rel=1e-6)
    assert res.transient.tau == pytest.approx(0.005, rel=1e-6)
    assert "yalıtılmış" in all_text(res)


@pytest.mark.parametrize(
    "net,mode,freq,expected_msg",
    [
        # 1) AC modunda geçici durum desteklenmez
        (f"V1 1 0 DC 12\nS1 1 2 NO\nR1 2 3 1k\nC1 3 0 10u\n{GND}", "AC_PHASOR", 50.0, "DC modunda"),
        # 2) Anahtarsız devre
        (f"V1 1 0 DC 12\nR1 1 2 1k\nC1 2 0 10u\n{GND}", "DC", None, "anahtar"),
        # 3) Depolayıcı eleman (C veya L) yok
        (f"V1 1 0 DC 12\nS1 1 2 NO\nR1 2 0 1k\n{GND}", "DC", None, "kondansatör"),
        # 4) Birden fazla depolayıcı eleman (2 kondansatör)
        (f"V1 1 0 DC 12\nS1 1 2 NO\nR1 2 3 1k\nC1 3 0 10u\nC2 2 0 5u\n{GND}", "DC", None, "birinci dereceden"),
        # 5) Bağımlı kaynak içeren devre
        (f"V1 1 0 DC 12\nS1 1 2 NO\nR1 2 3 1k\nC1 3 0 10u\nG1 3 0 V(R1) 1m\n{GND}", "DC", None, "bağımlı"),
        # 6) t > 0 konumunda depolayıcı elemanın iki ucu kısa devre (S1 kapalıyken C1 kısa devre)
        (f"V1 1 0 DC 12\nR1 1 2 1k\nC1 2 0 10u\nS1 2 0 NO\n{GND}", "DC", None, "kısa devre"),
        # 7) t > 0 konumunda R_th = 0 (C1 doğrudan gerilim kaynağına paralel bağlanıyor)
        (f"V1 1 0 DC 12\nS1 1 2 NO\nC1 2 0 10u\nR1 2 0 1k\n{GND}", "DC", None, "R_th = 0"),
        # 8) Başlangıç ve son değer aynı (geçici değişim yok)
        (f"V1 1 0 DC 12\nR1 1 2 1k\nC1 2 0 10u\nS1 1 3 NO\nR2 3 0 2k\n{GND}", "DC", None, "değişmiyor"),
    ],
)
def test_transient_rejected_cases_and_fallback_explanation(solve, net, mode, freq, expected_msg):
    """Reddedilen tüm durumlarda res.transient None olmalı ve anlatım başına Türkçe gerekçe eklenmelidir."""
    res, _, _ = solve(net, mode=mode, frequency=freq, analysis_type="TRANSIENT")
    assert res.transient is None
    assert len(res.explanation) >= 1
    first_sec = res.explanation[0]
    assert first_sec.title == "Geçici Durum (Anahtar)"
    assert expected_msg.lower() in first_sec.blocks[0].text.lower()


def test_transient_current_source_across_capacitor_at_t_before_bug():
    """
    BULGU-2:
    I1 0 1 DC 2m, C1 1 0 10u, S1 1 2 NO, R1 2 0 1000.
    t < 0'da S1 açıktır; 2 mA'lik DC akım kaynağı I1 doğrudan C1 kondansatörüne paraleldir ve
    paralel direnç yoktur. DC kararlı hâlde C1 açık devre olacağından I1 akımının gideceği yol yoktur
    (V_C(t) = (1/C)·∫I1·dt → ∞, Düğüm 1'de KCL çelişir).
    Dolayısıyla analyze_transient TransientNotApplicable fırlatmalıdır; C1'i 'yalıtılmış / boş (0 V)'
    kabul etmemelidir.
    """
    net = f"I1 0 1 DC 2m\nC1 1 0 10u\nS1 1 2 NO\nR1 2 0 1000\n{GND}"
    with pytest.raises(TransientNotApplicable):
        analyze_transient(parse_netlist(net))


def test_transient_narrative_negative_charging_capacitor_not_discharging_bug(solve):
    """
    BULGU-5:
    V1 0 1 DC 12, S1 1 2 NO, R1 2 3 1000, C1 3 0 10u.
    C1 başlangıçta boştur (V_C1(0⁺) = 0 V, W(0⁺) = 0 J) ve t → ∞'da V_C1(∞) = -12 V'a (W(∞) = 720 µJ)
    DOLMAKTADIR (şarj olmaktadır).
    Anlatım "Kondansatör boştan doluyor" dediği hâlde aynı bölümde "kondansatör deşarj olurken"
    dememelidir.
    """
    net = f"V1 0 1 DC 12\nS1 1 2 NO\nR1 2 3 1000\nC1 3 0 10u\n{GND}"
    res, _, err = solve(net, analysis_type="TRANSIENT")
    assert err == [] and res.transient is not None
    txt = all_text(res)
    assert "Kondansatör boştan doluyor" in txt
    assert "deşarj olurken" not in txt


# ═══════════════════════════════════════════════════════════════════════════
#  2. ALIŞTIRMA SORULARI, CEVAP AYRIŞTIRICI VE DENETLEYİCİ
# ═══════════════════════════════════════════════════════════════════════════

def test_transient_practice_questions_rc_and_rl_values(solve):
    """
    Geçici durum alıştırma sorularının (6 soru: x(0⁻), x(0⁺), x(∞), R_th, τ, x(τ))
    RC ve RL devreleri için analitik değerlerle bire bir uyumu:
    RL devresi:
      V1 1 0 DC 24, R1 1 2 4, S1 2 3 NO, R2 3 0 8, L1 2 0 0.24.
      t < 0 (S1 açık): L1 kısa devre → V2 = 0 → I_L1(0⁻) = 24 / 4 = 6 A, I_L1(0⁺) = 6 A.
      t > 0 (S1 kapalı): L1 kısa devre → V2 = 0 → R2 uçları 0 V → I_L1(∞) = 24 / 4 = 6 A?
      Dikkat: değişim olması için S1'i R1'in yanına veya L1'in seri koluna koyalım:
      V1 1 0 DC 24, R1 1 2 6, S1 1 2 NO, R2 2 3 4, L1 3 0 0.2.
      t < 0 (S1 açık): R_toplam = R1 + R2 = 10 Ω → I_L1(0⁻) = 24 / 10 = 2.4 A = I_L1(0⁺).
      t > 0 (S1 kapalı → R1 kısa devre): R_th = R2 = 4 Ω → I_L1(∞) = 24 / 4 = 6.0 A.
      τ = L1 / R_th = 0.2 / 4 = 0.05 s = 50 ms.
      I_L1(τ) = 6.0 + (2.4 - 6.0)·e⁻¹ = 6.0 - 3.6 / e ≈ 4.675632 A.
    """
    net = f"V1 1 0 DC 24\nR1 1 2 6\nS1 1 2 NO\nR2 2 3 4\nL1 3 0 0.2\n{GND}"
    res, _, err = solve(net, analysis_type="TRANSIENT")
    assert err == [] and len(res.practice) == 7
    by_id = {q.id: q for q in res.practice}
    assert by_id["TAU"].expected.real == pytest.approx(0.05, rel=1e-4)
    assert by_id["X0"].expected.real == pytest.approx(2.4, rel=1e-4)
    assert by_id["XINF"].expected.real == pytest.approx(6.0, rel=1e-4)
    expected_at_tau = 6.0 + (2.4 - 6.0) * math.exp(-1.0)
    assert by_id["XTAU"].expected.real == pytest.approx(expected_at_tau, rel=1e-3)
    assert by_id["O0"].expected.real == pytest.approx((6.0 - 2.4) * 4.0, rel=1e-4)


def test_answer_parser_and_checker_edge_cases():
    """
    answer_parser ve checker köşe durumları:
    - Büyük 'M' (10⁶) vs küçük 'm' (10⁻³) ayrımı
    - Virgüllü kutupsal ('10∠-36,87°', radyan '2∠0,5 rad') ve dikdörtgen ('-3,5-j2,5 kΩ', '-j4 mA')
    - Yanlış birim reddi, 1000 kat ölçek hatası ipucu, işaret hatası ipucu, açı işareti ipucu
    - Bozuk girişlerin ('', '1.000,5', '3..5', '2meg', '10∠30∠10') AnswerParseError fırlatması
    """
    assert parse_answer("2,5M").value == pytest.approx(2.5e6)
    assert parse_answer("2,5m").value == pytest.approx(2.5e-3)
    assert parse_answer("2,5 MΩ").unit == "Ω" and parse_answer("2,5 MΩ").value == pytest.approx(2.5e6)
    assert parse_answer("2,5 mA").unit == "A" and parse_answer("2,5 mA").value == pytest.approx(2.5e-3)

    p_rect = parse_answer("-3,5 - j2,5 kΩ")
    assert p_rect.form == "rect" and p_rect.unit == "Ω"
    assert p_rect.value == pytest.approx(complex(-3500.0, -2500.0))

    p_polar = parse_answer("5∠-53,13° mA")
    assert p_polar.form == "polar" and p_polar.unit == "A"
    assert abs(p_polar.value) == pytest.approx(0.005)
    assert p_polar.angle_input == pytest.approx(-53.13)

    p_rad = parse_answer("4∠0,5 rad V")
    assert p_rad.angle_unit == "rad" and p_rad.unit == "V"
    assert p_rad.value == pytest.approx(cmath.rect(4.0, 0.5))

    for bad in ["", "   ", "1.000,5", "3..5", "2meg", "10∠30∠10", "abc", "3++j4"]:
        with pytest.raises(AnswerParseError):
            parse_answer(bad)

    # Checker: doğru cevap, yanlış birim, 10³ ölçek hatası, işaret hatası, faz açısı işareti hatası
    exp_dc = ComplexNumber(
        real=0.004, imaginary=0.0, magnitude=0.004, phase_degrees=0.0,
        rectangular_str="0,004", polar_str="0,004∠0°",
    )
    q_dc = PracticeQuestion(
        id="Q_DC", label="I_R1", description="R1 akımı", unit="A", group="main",
        is_ac=False, expected=exp_dc, scale=0.004,
        hint="Ohm yasası uygulayın.", sign_hint="İşaret ters.", alternatives=[],
    )
    assert check_answer(q_dc, "4 mA").status == "correct"
    wrong_unit = check_answer(q_dc, "4 mV")
    assert wrong_unit.status != "correct" and "birim" in wrong_unit.message.lower()
    scale_err = check_answer(q_dc, "4 A")
    assert scale_err.status != "correct" and "1000" in scale_err.message
    sign_err = check_answer(q_dc, "-4 mA")
    assert sign_err.status != "correct" and "İşaret ters" in sign_err.message

    exp_ac = ComplexNumber(
        real=6.0, imaginary=-8.0, magnitude=10.0, phase_degrees=-53.1301,
        rectangular_str="6−j8", polar_str="10∠−53,13°",
    )
    q_ac = PracticeQuestion(
        id="Q_AC", label="V_1", description="Düğüm 1 gerilimi", unit="V", group="main",
        is_ac=True, expected=exp_ac, scale=10.0,
        hint="Fazör hesabı yapın.", sign_hint="Açı/işaret kontrol edin.", alternatives=[],
    )
    assert check_answer(q_ac, "10∠-53,13° V").status == "correct"
    assert check_answer(q_ac, "6 - j8 V").status == "correct"
    phase_flip = check_answer(q_ac, "10∠53,13° V")
    assert phase_flip.status != "correct" and "açı" in phase_flip.message.lower()


# ═══════════════════════════════════════════════════════════════════════════
#  3. ONDALIK VİRGÜL (ANLATIMDA VİRGÜL, NETLIST VE JSON'DA NOKTA)
# ═══════════════════════════════════════════════════════════════════════════

def test_formatting_turkish_comma_in_text_and_dot_in_netlist_and_json(client):
    """
    - formatting.py fonksiyonları Türkçe anlatımda ondalık virgül (',') ve Unicode eksi ('−') kullanmalı.
    - to_lcapy_netlist ve /api/analyze JSON çıktısındaki sayısal alanlar nokta ('.') / float kalmalı.
    """
    assert num(2.5) == "2,5"
    assert num(-0.125) == f"{MINUS}0,125"
    assert fmt(2.5, ".2f") == "2,50"
    assert eng(0.0025, "A") == "2,5 mA"
    assert eng(1500.0, "Ω") == "1,5 kΩ"
    assert paren(num(-3.5)) == f"({MINUS}3,5)"
    assert node_v("2") == "V₂"
    assert sub("12") == "₁₂"
    assert rect(complex(2.5, -1.5), "Ω") == f"2,5 {MINUS} j1,5 Ω"
    assert "," in polar(complex(2.5, -1.5), "V")
    assert "," in value(complex(2.5, -1.5), "V", is_dc=False)

    net = f"V1 1 0 DC 7.5\nS1 1 2 NO\nR1 2 3 1500\nC1 3 0 2.5u\n{GND}"
    after = circuit_at_time(parse_netlist(net), "after")
    lcapy_str = to_lcapy_netlist(after)
    assert "7.5" in lcapy_str and "," not in lcapy_str

    resp = client.post(
        "/analyze",
        json={"netlist": net, "mode": "DC", "analysis_type": "TRANSIENT"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["transient"]["tau"], float)
    assert data["transient"]["tau"] == pytest.approx(0.00375, rel=1e-6)
    expl_text = "\n".join(
        b["text"] for s in data["results"]["explanation"] for b in s["blocks"]
    )
    assert "7,5 V" in expl_text and "1,5 kΩ" in expl_text and "3,75 ms" in expl_text
