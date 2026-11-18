"""
Alıştırma modu düzeltmeleri (Fable denetimi, 2. tur).

- I_C(0⁺) ipucu V_C(0⁺) cevabını söylüyordu.
- Kondansatör dolarken işaret ipucu "eksi çıkar" diyordu.
- %90 sorusunda τ yazana "log yerine ln" deniyordu (log10(10) = 1).
- "1.500" 1,5 okunup yanlış sayılıyordu; geri bildirim "1.000 katı" yazıyordu.
- Beklenen 0 iken "Çok yakın %4,2" gibi anlamsız yüzde.
- "Vp", "Vrms", "milivolt", "= 8,25" yazımları tanınmıyordu.
- DC ipuçlarında Z ve "R_R1".
"""

import pytest

from models.response import PracticeQuestion
from practice.answer_parser import parse_answer
from practice.checker import check_answer
from solver.circuit_solver import make_complex_number

GND = "* GND1 — Referans toprak (Node 0)"
RC_CHARGE = f"V1 1 0 DC 12\nS1 1 2 NO\nR1 2 3 2k\nC1 3 0 1u\n{GND}"
RC_DISCHARGE = f"V1 1 0 DC 10\nR1 1 2 2k\nR3 2 0 2k\nS1 3 2 0 SPDT\nR2 3 4 3k\nC1 4 0 2u\n{GND}"
DIVIDER = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}"


def _q(expected: float, unit: str = "V") -> PracticeQuestion:
    return PracticeQuestion(
        id="Q1", label="V2", description="Test", unit=unit, group="main", is_ac=False,
        expected=make_complex_number(complex(expected)), scale=abs(expected) or 1.0,
        hint="KCL yazın.", sign_hint="İşaret ters.")


# ── Geçici durum soruları ──

def test_capacitor_current_hint_does_not_give_the_voltage(solve):
    results, _, _ = solve(RC_DISCHARGE, "DC", analysis_type="TRANSIENT")
    qs = {q.id: q for q in results.practice}
    v0 = qs["X0"].expected.real
    assert v0 == pytest.approx(5.0)
    assert "5 V" not in qs["O0"].hint
    assert "gerilimini koruyan" in qs["O0"].hint


def test_sign_hint_follows_the_actual_current_direction(solve):
    charge = {q.id: q for q in solve(RC_CHARGE, "DC", analysis_type="TRANSIENT")[0].practice}
    assert charge["O0"].expected.real > 0
    assert "işareti artıdır" in charge["O0"].sign_hint
    assert "eksi" not in charge["O0"].sign_hint

    discharge = {q.id: q for q in solve(RC_DISCHARGE, "DC", analysis_type="TRANSIENT")[0].practice}
    assert discharge["O0"].expected.real < 0
    assert "işareti eksidir" in discharge["O0"].sign_hint


def test_tau_answer_to_the_ninety_percent_question_gets_the_tau_message(solve):
    qs = {q.id: q for q in solve(RC_CHARGE, "DC", analysis_type="TRANSIENT")[0].practice}
    v = check_answer(qs["TLEVEL"], "2m")      # τ = 2 ms, doğru cevap 4,605 ms
    assert v.status == "wrong"
    assert "bir τ'dur" in v.message
    assert "10 tabanlı" not in v.message


# ── Cevap okuma ──

@pytest.mark.parametrize("text, value", [
    ("8,25 Vp", 8.25), ("8,25 Vrms", 8.25), ("8,25Veff", 8.25),
    ("4 Arms", 4.0), ("250 milivolt", 0.25), ("2,2 kiloohm", 2200.0),
    ("10 mikrofarad", 10e-6), ("= 8,25", 8.25), ("V2 = 8,25 V", 8.25), ("≈ 8,25 V", 8.25),
])
def test_more_answer_spellings(text, value):
    assert parse_answer(text).value.real == pytest.approx(value)


# ── Değerlendirme ──

def test_thousands_separator_is_explained_not_just_wrong():
    v = check_answer(_q(1500.0, "Ω"), "1.500")
    assert v.status == "partial"
    assert "“1500” demek istediyseniz doğru" in v.message
    v = check_answer(_q(1500.0, "Ω"), "1.500 Ω")
    assert v.status == "partial"


def test_dot_decimal_still_works():
    assert check_answer(_q(3.033), "3.033").status == "correct"
    assert check_answer(_q(1.5), "1.500").status == "correct"     # 1,5 isteniyorsa doğru
    assert check_answer(_q(1500.0), "1500").status == "correct"
    assert check_answer(_q(1500.0), "1,5k").status == "correct"


def test_prefix_message_uses_words_not_dotted_numbers():
    v = check_answer(_q(8.0), "8000")
    assert "bin katı büyük" in v.message
    assert "1.000" not in v.message


def test_close_answer_to_zero_has_no_percentage():
    q = _q(0.0)
    q.scale = 10.0                       # floor = 10 mV
    v = check_answer(q, "0,04")          # 40 mV: "çok yakın" bölgesi
    assert v.status == "close"
    assert "%" not in v.message


# ── DC ipuçları ──

def test_dc_hints_use_r_not_z(solve):
    results, _, _ = solve(DIVIDER, "DC", analysis_type="NODAL")
    qs = {q.id: q for q in results.practice}
    assert "/R)" in qs["V2"].hint and "/Z" not in qs["V2"].hint
    i_r1 = qs["I_R1"].hint
    assert "/ R1." in i_r1
    assert "R_R1" not in i_r1 and "Z_" not in i_r1
