"""
Üç faz (analysis_type = "THREE_PHASE") yöntemi testleri — Y/Δ kaynak ve yük, wattmetre, Aron,
kompanzasyon.

Tüm beklenen değerler test içinde temel devre formülleriyle ELLE hesaplanır; çözücü çıktısı
kopyalanmaz.

Ana örnek: U_h = 380 V (etkin), Y kaynak, Y yük Z = 10 Ω, 4 iletken
    U_f = 380/√3 = 219,39 V,  I = 219,39/10 = 21,94 A,  P = 3·U_f²/10 = 14,44 kW,  I_N ≈ 0
D yük aynı Z:  I_f = 380/10 = 38 A,  I_h = √3·38 = 65,82 A,  P = 3·38²·10 = 43,32 kW (Y'nin 3 katı)
Z = 8 + j6: cos φ = 8/10 = 0,8 geri.
Kompanzasyon: Q_C = P·(tan φ₁ − tan φ₂),  C_Y = Q_C/(ω·U_h²),  C_Δ = C_Y/3.
"""

import cmath
import functools
import json
import math

import pytest
from fastapi.testclient import TestClient

from main import app
from models.response import PracticeQuestion
from parser.netlist_parser import ElementType, parse_netlist
from practice.checker import check_answer

client = TestClient(app)

GND = "\n* GND1 — Referans toprak"
S3 = math.sqrt(3.0)
UH = 380.0
UF = UH / S3
W = 2.0 * math.pi * 50.0
SRC = "U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 0 RST RMS\n"


def load(conn: str, z1, z2=None, z3=None, n: str = "0") -> str:
    z2 = z1 if z2 is None else z2
    z3 = z1 if z3 is None else z3
    zs = " ".join(f"Z({z.real},{z.imag})" for z in (z1, z2, z3))
    return f"Y1 1 2 3 {n} 3PH_LOAD {conn} {zs}\n"


@functools.lru_cache(maxsize=None)
def _cached(netlist: str, body_json: str) -> tuple:
    body = {"netlist": netlist, "mode": "AC_PHASOR", "analysis_type": "THREE_PHASE",
            "value_display": "RMS"}
    body.update(json.loads(body_json))
    resp = client.post("/analyze", json=body)
    return resp.status_code, resp.text


def _post(netlist: str, **extra):
    code, text = _cached(netlist, json.dumps(extra, sort_keys=True))
    return code, json.loads(text)


def _ok(netlist: str, **extra) -> dict:
    code, data = _post(netlist, **extra)
    assert code == 200, data
    return data


def _z(c) -> complex:
    if isinstance(c, (int, float)):
        return complex(c)
    return complex(c["real"], c["imaginary"])


def _close(a, b, rel: float = 1e-4) -> bool:
    return abs(complex(a) - complex(b)) <= rel * max(abs(a), abs(b), 1e-9) + 1e-6


def _tp(data: dict) -> dict:
    assert data["three_phase"] is not None
    return data["three_phase"]


def _titles(data: dict) -> list:
    return [s["title"] for s in data["results"]["explanation"]]


def _text(data: dict, title: str = None) -> str:
    out = []
    for s in data["results"]["explanation"]:
        if title is None or s["title"] == title:
            out += [b["text"] for b in s["blocks"]]
    return "\n".join(out)


def _currents(tp: dict) -> dict:
    return {k: _z(v) for k, v in tp["line_currents"].items()}


def test_internal_names_stay_hidden():
    # Karmaşık kol R + L'ye açılır; iç kimlikler ve ara düğümler öğrenciye gösterilmez
    d = _ok("U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 0 RST RMS\nW1 1 4 1 2 WATTMETER\nR1 2 5 1\n"
            "Y1 4 5 3 0 3PH_LOAD Y Z(8,6) Z(8,6) Z(8,6)\n" + GND)
    assert set(d["results"]["element_currents"]) == {"R1"}
    assert set(d["results"]["node_voltages"]) == {"0", "1", "2", "3", "4", "5"}
    assert d["solution_steps"] == []


def test_internal_names_hidden_single_phase_wattmeter():
    d = _ok("V1 1 0 AC_PHASOR(100, 0)\nW1 1 2 1 0 WATTMETER\nR1 2 0 10\n" + GND, analysis_type="NODAL")
    assert set(d["results"]["element_currents"]) == {"V1", "R1"}
    assert d["wattmeters"][0]["p"] == pytest.approx(500.0, rel=1e-4)   # 100 V tepe: P = 100² / (2·10)


# ═══════════════════════════════════════════════════════
#  Dengeli
# ═══════════════════════════════════════════════════════

def test_balanced_star_star_four_wire():
    d = _ok(SRC + load("Y", 10 + 0j) + GND.strip("\n") if False else SRC + load("Y", 10 + 0j) + GND)
    tp = _tp(d)
    assert (tp["source"], tp["load"], tp["wires"], tp["balanced"]) == ("Y", "Y", 4, True)
    assert math.isclose(tp["u_line"], UH, rel_tol=1e-6) and math.isclose(tp["u_phase"], UF, rel_tol=1e-6)
    i = _currents(tp)
    i_f = UF / 10
    for ph, ang in (("R", 0), ("S", -120), ("T", 120)):
        assert _close(i[ph], cmath.rect(i_f, math.radians(ang)))
    assert abs(_z(tp["neutral_current"])) < 1e-4
    assert tp["load_phase_currents"] is None
    assert math.isclose(tp["p"], 3 * UF * UF / 10, rel_tol=1e-6)       # 14,44 kW
    assert abs(tp["q"]) < 1e-3 and math.isclose(tp["pf"], 1.0, rel_tol=1e-9)
    assert tp["pf_type"] == "unity" and tp["aron"] is None and tp["compensation"] is None
    assert d["results"]["three_phase"] == tp                          # results içinde de


def test_balanced_delta_load_is_three_times_the_star_power():
    d = _ok(SRC + load("D", 10 + 0j, n="4") + GND)
    tp = _tp(d)
    assert (tp["load"], tp["wires"], tp["balanced"]) == ("D", 3, True)
    i_f = UH / 10                                                       # 38 A
    ph = {k: _z(v) for k, v in tp["load_phase_currents"].items()}
    assert _close(abs(ph["RS"]), i_f) and _close(abs(ph["ST"]), i_f) and _close(abs(ph["TR"]), i_f)
    assert _close(cmath.phase(ph["RS"]), math.radians(30))              # V_RS = 380∠30° / 10
    i = _currents(tp)
    assert _close(abs(i["R"]), S3 * i_f)                                # 65,82 A
    assert _close(cmath.phase(i["R"]) - cmath.phase(ph["RS"]), math.radians(-30))   # 30° geride
    assert math.isclose(tp["p"], 3 * i_f ** 2 * 10, rel_tol=1e-6)       # 43,32 kW
    assert math.isclose(tp["p"], 3 * 14440.0, rel_tol=1e-3)
    assert tp["neutral_current"] is None


def test_balanced_rl_load_power_factor_is_lagging():
    d = _ok(SRC + load("D", 8 + 6j, n="4") + GND)
    tp = _tp(d)
    i_f = UH / 10
    assert math.isclose(tp["pf"], 0.8, rel_tol=1e-6) and tp["pf_type"] == "lagging"
    assert math.isclose(tp["p"], 3 * i_f ** 2 * 8, rel_tol=1e-6)
    assert math.isclose(tp["q"], 3 * i_f ** 2 * 6, rel_tol=1e-6)
    assert math.isclose(tp["s"], 3 * i_f ** 2 * 10, rel_tol=1e-6)
    # cos φ = 0,8: akım geriliminin gerisinde (φ = 36,87°)
    i_r = _currents(tp)["R"]
    v_rn = cmath.rect(UF, 0)
    assert _close(cmath.phase(i_r) - cmath.phase(v_rn), -math.atan2(6, 8))


def test_balanced_capacitive_load_is_leading():
    tp = _tp(_ok(SRC + load("Y", 6 - 8j) + GND))
    assert math.isclose(tp["pf"], 0.6, rel_tol=1e-6) and tp["pf_type"] == "leading"
    assert tp["q"] < 0


def test_delta_source_with_star_load_equals_star_source():
    star = _tp(_ok(SRC + load("Y", 10 + 0j, n="4") + GND))
    d = _ok("U1 1 2 3 0 3PH_SOURCE D LINE 380 50 0 RST RMS\n" + load("Y", 10 + 0j, n="4") + GND)
    delta = _tp(d)
    assert (delta["source"], delta["load"], delta["wires"]) == ("D", "Y", 3)
    for ph in "RST":
        assert _close(_currents(delta)[ph], _currents(star)[ph])
    assert math.isclose(delta["p"], star["p"], rel_tol=1e-6)
    assert "eşdeğer yıldız" in _text(d, "Devreyi Tanıyalım")


def test_delta_source_delta_load():
    tp = _tp(_ok("U1 1 2 3 0 3PH_SOURCE D LINE 380 50 0 RST RMS\n" + load("D", 10 + 0j, n="4") + GND))
    assert (tp["source"], tp["load"]) == ("D", "D")
    assert math.isclose(tp["p"], 3 * (UH / 10) ** 2 * 10, rel_tol=1e-6)


def test_phase_value_kind_sets_line_voltage():
    tp = _tp(_ok("U1 1 2 3 0 3PH_SOURCE Y PHASE 220 50 0 RST RMS\n" + load("Y", 10 + 0j) + GND))
    assert math.isclose(tp["u_phase"], 220, rel_tol=1e-6) and math.isclose(tp["u_line"], 220 * S3, rel_tol=1e-6)
    assert _close(abs(_currents(tp)["R"]), 22.0)


# ═══════════════════════════════════════════════════════
#  Dengesiz
# ═══════════════════════════════════════════════════════

def test_unbalanced_four_wire_neutral_current_is_phasor_sum():
    z = (10 + 0j, 20 + 0j, 40 + 0j)
    tp = _tp(_ok(SRC + load("Y", *z) + GND))
    assert (tp["wires"], tp["balanced"]) == (4, False)
    v = [cmath.rect(UF, math.radians(a)) for a in (0, -120, 120)]
    hand = [vi / zi for vi, zi in zip(v, z)]
    for ph, h in zip("RST", hand):
        assert _close(_currents(tp)[ph], h)
    assert _close(_z(tp["neutral_current"]), sum(hand))
    assert abs(sum(hand)) > 5                                           # gerçekten sıfır değil
    assert math.isclose(tp["p"], sum(abs(h) ** 2 * zi.real for h, zi in zip(hand, z)), rel_tol=1e-6)


def test_unbalanced_three_wire_star_uses_millman_shift():
    z = (10 + 0j, 20 + 0j, 40 + 0j)
    d = _ok(SRC + load("Y", *z, n="4") + GND)
    tp = _tp(d)
    assert (tp["wires"], tp["balanced"], tp["neutral_current"]) == (3, False, None)
    v = [cmath.rect(UF, math.radians(a)) for a in (0, -120, 120)]
    vnn = sum(vi / zi for vi, zi in zip(v, z)) / sum(1 / zi for zi in z)        # Millman
    hand = [(vi - vnn) / zi for vi, zi in zip(v, z)]
    for ph, h in zip("RST", hand):
        assert _close(_currents(tp)[ph], h)
    assert abs(sum(_currents(tp).values())) < 1e-3                      # I_R + I_S + I_T = 0
    assert "Millman" in _text(d, "Kol Kol Çözüm (Dengesiz Yük)")


def test_unbalanced_delta_kcl_line_currents():
    z = (10 + 0j, 20 + 5j, 40 - 10j)
    tp = _tp(_ok(SRC + load("D", *z, n="4") + GND))
    v = [cmath.rect(UF, math.radians(a)) for a in (0, -120, 120)]
    vrs, vst, vtr = v[0] - v[1], v[1] - v[2], v[2] - v[0]
    i_rs, i_st, i_tr = vrs / z[0], vst / z[1], vtr / z[2]
    ph = {k: _z(c) for k, c in tp["load_phase_currents"].items()}
    assert _close(ph["RS"], i_rs) and _close(ph["ST"], i_st) and _close(ph["TR"], i_tr)
    i = _currents(tp)
    assert _close(i["R"], i_rs - i_tr) and _close(i["S"], i_st - i_rs) and _close(i["T"], i_tr - i_st)
    assert abs(sum(i.values())) < 1e-3


# ═══════════════════════════════════════════════════════
#  Aron, faz sırası, etkin/tepe
# ═══════════════════════════════════════════════════════

def test_aron_readings_sum_to_total_power():
    z = 5 + 5j
    tp = _tp(_ok(SRC + load("Y", z, n="4") + GND))
    assert tp["wires"] == 3 and tp["aron"] is not None
    i_h = UF / abs(z)
    phi = math.atan2(z.imag, z.real)                                    # 45°
    assert math.isclose(tp["aron"]["p_a"], UH * i_h * math.cos(math.radians(30) + phi), rel_tol=1e-4)
    assert math.isclose(tp["aron"]["p_b"], UH * i_h * math.cos(math.radians(30) - phi), rel_tol=1e-4)
    assert math.isclose(tp["aron"]["p_a"] + tp["aron"]["p_b"], tp["p"], rel_tol=1e-6)


def test_aron_one_wattmeter_reads_zero_at_power_factor_half():
    tp = _tp(_ok(SRC + load("Y", 5 + 5 * S3 * 1j, n="4") + GND))           # cos φ = 0,5 geri
    assert math.isclose(tp["pf"], 0.5, rel_tol=1e-6) and tp["pf_type"] == "lagging"
    pa, pb = tp["aron"]["p_a"], tp["aron"]["p_b"]
    assert abs(pa) < 1e-3 * abs(pb)
    assert math.isclose(pb, tp["p"], rel_tol=1e-6)


def test_aron_explained_for_balanced_load():
    d = _ok(SRC + load("Y", 5 + 5j, n="4") + GND)
    assert "Aron (İki Wattmetre) Yöntemi" in _titles(d)
    assert "P_A + P_B" in _text(d, "Aron (İki Wattmetre) Yöntemi")


def test_rts_sequence_swaps_s_and_t():
    z = 8 + 6j
    tp = _tp(_ok("U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 0 RTS RMS\n" + load("Y", z) + GND))
    i = _currents(tp)
    assert _close(i["S"], cmath.rect(UF / abs(z), math.radians(120) - cmath.phase(z)))
    assert _close(i["T"], cmath.rect(UF / abs(z), math.radians(-120) - cmath.phase(z)))


def test_rts_sequence_swaps_aron_readings():
    z = 5 + 5j
    rst = _tp(_ok(SRC + load("Y", z, n="4") + GND))["aron"]
    rts = _tp(_ok("U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 0 RTS RMS\n" + load("Y", z, n="4") + GND))["aron"]
    assert math.isclose(rts["p_a"], rst["p_b"], rel_tol=1e-4)
    assert math.isclose(rts["p_b"], rst["p_a"], rel_tol=1e-4)


def test_source_start_angle_shifts_all_phases():
    tp = _tp(_ok("U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 30 RST RMS\n" + load("Y", 10 + 0j) + GND))
    assert _close(_currents(tp)["R"], cmath.rect(UF / 10, math.radians(30)))
    assert _close(_currents(tp)["S"], cmath.rect(UF / 10, math.radians(-90)))


def test_peak_basis_scales_voltage_and_current_but_not_power():
    rms = _tp(_ok(SRC + load("Y", 8 + 6j) + GND))
    peak = _tp(_ok(SRC + load("Y", 8 + 6j) + GND, value_display="PEAK"))
    assert math.isclose(peak["u_line"], UH * math.sqrt(2), rel_tol=1e-6)
    assert math.isclose(peak["u_phase"], UF * math.sqrt(2), rel_tol=1e-6)
    assert _close(abs(_currents(peak)["R"]), abs(_currents(rms)["R"]) * math.sqrt(2))
    assert math.isclose(peak["p"], rms["p"], rel_tol=1e-6) and math.isclose(peak["pf"], rms["pf"], rel_tol=1e-6)


def test_peak_basis_input_without_rms_suffix():
    # RMS eki yok: girilen 380 değeri tepe değerdir → etkin hat gerilimi 380/√2
    tp = _tp(_ok("U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 0 RST\n" + load("Y", 10 + 0j) + GND))
    assert math.isclose(tp["u_line"], 380 / math.sqrt(2), rel_tol=1e-6)


# ═══════════════════════════════════════════════════════
#  Kompanzasyon
# ═══════════════════════════════════════════════════════

def test_compensation_formulas_and_solver_verification():
    d = _ok(SRC + load("D", 8 + 6j, n="4") + GND, power_factor_target=0.95)
    tp = _tp(d)
    c = tp["compensation"]
    p = 3 * (UH / 10) ** 2 * 8
    qc = p * (0.75 - math.tan(math.acos(0.95)))
    cy = qc / (W * UH ** 2)
    assert c["applied"] and c["reason"] is None and c["target_pf"] == 0.95
    assert math.isclose(c["q_c"], qc, rel_tol=1e-6)
    assert math.isclose(c["c_y"], cy, rel_tol=1e-6)
    assert math.isclose(c["c_delta"], cy / 3, rel_tol=1e-6)
    # Bağımsız doğrulama: üçgen kondansatörleri netlistte ELLE ekle, yeni cos φ hedefe eşit olmalı
    net = (SRC + load("D", 8 + 6j, n="4")
           + "".join(f"C{k} {a} {b} {c['c_delta']}\n" for k, a, b in ((1, 1, 2), (2, 2, 3), (3, 3, 1))) + GND)
    after = _tp(_ok(net))
    assert math.isclose(after["pf"], 0.95, rel_tol=1e-5)
    assert math.isclose(after["p"], tp["p"], rel_tol=1e-6)
    i_after = p / (S3 * UH * 0.95)
    assert _close(abs(_currents(after)["R"]), i_after)
    assert "Kompanzasyon" in _titles(d) and "Q_C" in _text(d, "Kompanzasyon")


def test_compensation_not_applied_for_unbalanced_leading_or_met_target():
    unb = _tp(_ok(SRC + load("Y", 10 + 0j, 20 + 5j, 40 + 0j) + GND, power_factor_target=0.95))
    assert unb["compensation"]["applied"] is False and "dengeli" in unb["compensation"]["reason"]
    assert unb["compensation"]["c_y"] is None
    lead = _tp(_ok(SRC + load("Y", 6 - 8j) + GND, power_factor_target=0.95))["compensation"]
    assert lead["applied"] is False and "ileri" in lead["reason"]
    met = _tp(_ok(SRC + load("Y", 8 + 6j) + GND, power_factor_target=0.7))["compensation"]
    assert met["applied"] is False and "hedef" in met["reason"]


# ═══════════════════════════════════════════════════════
#  Wattmetre
# ═══════════════════════════════════════════════════════

def test_wattmeter_in_three_phase_circuit_reads_one_phase_power():
    net = (SRC + "W1 1 5 5 0 WATTMETER\n" + "Y1 5 2 3 0 3PH_LOAD Y Z(10,0) Z(10,0) Z(10,0)\n" + GND)
    d = _ok(net)
    assert [w["id"] for w in d["wattmeters"]] == ["W1"]
    assert math.isclose(d["wattmeters"][0]["p"], UF ** 2 / 10, rel_tol=1e-5)    # P_R = 4,813 kW
    assert "Wattmetre Okumaları" in _titles(d)
    assert math.isclose(_tp(d)["p"], 3 * UF ** 2 / 10, rel_tol=1e-5)


def test_wattmeter_in_single_phase_ac_circuit():
    net = "V1 1 0 AC_PHASOR(100, 0) RMS\nW1 1 2 1 0 WATTMETER\nZ1 2 0 COMPLEX(8, 6)" + GND
    code, d = _post(net, analysis_type="NODAL", frequency=50)
    assert code == 200, d
    assert d["three_phase"] is None
    assert math.isclose(d["wattmeters"][0]["p"], 100 * 10 * 0.8, rel_tol=1e-5)  # 800 W
    assert "Wattmetre Okumaları" in _titles(d)


def test_wattmeter_peak_basis_uses_half_rule():
    net = "V1 1 0 AC_PHASOR(100, 0)\nW1 1 2 1 0 WATTMETER\nR1 2 0 10" + GND
    code, d = _post(net, analysis_type="NODAL", frequency=50, value_display="PEAK")
    assert code == 200, d
    assert math.isclose(d["wattmeters"][0]["p"], 0.5 * 100 * 10, rel_tol=1e-5)  # ½·V·I


# ═══════════════════════════════════════════════════════
#  Anlatım
# ═══════════════════════════════════════════════════════

def test_balanced_narrative_follows_textbook_order():
    d = _ok(SRC + load("Y", 8 + 6j) + GND)
    assert _titles(d) == ["Devreyi Tanıyalım", "Faz ve Hat Büyüklükleri",
                          "Tek Faz Eşdeğeri (Dengeli Yük)", "Güç", "Kontrol", "Sonuç"]
    assert "Kitaplarda gerilim U ile de gösterilir" in _text(d, "Devreyi Tanıyalım")
    assert "√3" in _text(d, "Faz ve Hat Büyüklükleri")
    assert "cos φ" in _text(d, "Güç")


def test_peak_basis_narrative_converts_to_rms_before_power_formulas():
    d = _ok(SRC + load("Y", 8 + 6j) + GND, value_display="PEAK")
    assert "etkin = tepe / √2" in _text(d, "Güç")


def test_unbalanced_narrative_has_per_arm_section():
    d = _ok(SRC + load("Y", 10 + 0j, 20 + 0j, 40 + 0j) + GND)
    assert "Kol Kol Çözüm (Dengesiz Yük)" in _titles(d)
    assert "I_N" in _text(d, "Kol Kol Çözüm (Dengesiz Yük)")


def test_other_method_selected_adds_redirect_note():
    d = _ok(SRC + load("Y", 10 + 0j) + GND, analysis_type="NODAL")
    note = "Bu devrede üç fazlı eleman var; çözüm Üç Faz yöntemiyle anlatılıyor."
    assert note in _text(d, "Devreyi Tanıyalım")
    assert _tp(d)["balanced"] is True


def test_line_impedance_gives_short_narrative_with_correct_results():
    net = SRC + "R1 1 5 1\nY1 5 2 3 0 3PH_LOAD Y Z(9,0) Z(9,0) Z(9,0)\n" + GND
    d = _ok(net)
    assert _titles(d)[1] == "Çözücü Sonuçları" and "Kontrol" not in _titles(d)
    assert "başka elemanlar" in _text(d, "Çözücü Sonuçları")
    assert _close(abs(_currents(_tp(d))["R"]), UF / 10)                  # 1 + 9 = 10 Ω
    # yalnızca R hattında 1 Ω var: kaynak P = U_f²/10 (R: 1+9) + 2·U_f²/9 (S, T)
    assert math.isclose(_tp(d)["p"], UF ** 2 / 10 + 2 * UF ** 2 / 9, rel_tol=1e-5)


def test_transformer_in_same_circuit_gives_reason_and_results():
    net = (SRC + load("Y", 10 + 0j) + "T1 1 0 4 0 IDEAL 0.5\nR2 4 0 10" + GND)
    d = _ok(net)
    assert d["transformer"] is not None
    assert "transformatör" in _text(d, "Çözücü Sonuçları")
    i_r = _currents(_tp(d))["R"]
    # T1 R fazına bağlı: yansıyan Z₁ = R2/a² = 10/0,25 = 40 Ω → I₁ = U_f/40; R hattı = U_f/10 + U_f/40
    assert _close(abs(i_r), abs(UF / 10 + UF / 40))


# ═══════════════════════════════════════════════════════
#  Alıştırma, JSON, hatalar
# ═══════════════════════════════════════════════════════

def _questions(data: dict) -> dict:
    return {q["id"]: PracticeQuestion(**q) for q in data["results"]["practice"]}


def test_practice_balanced_questions_are_checked_against_solver():
    d = _ok(SRC + load("D", 8 + 6j, n="4") + GND, power_factor_target=0.95)
    qs = _questions(d)
    assert {"I_F", "I_H", "P", "Q", "S", "PF", "C_Y", "C_D"} <= set(qs)
    assert check_answer(qs["I_H"], "65.82∠-36.87°").status == "correct"
    assert check_answer(qs["P"], "34.66k").status == "correct"
    assert check_answer(qs["PF"], "0.8").status == "correct"
    assert check_answer(qs["P"], "11.55k").status != "correct"


def test_practice_unbalanced_questions():
    d = _ok(SRC + load("Y", 10 + 0j, 20 + 0j, 40 + 0j) + GND)
    qs = _questions(d)
    assert {"I_R", "I_S", "I_T", "I_N", "P"} <= set(qs)
    assert _close(_z(d["three_phase"]["neutral_current"]), complex(qs["I_N"].expected.real, qs["I_N"].expected.imaginary))


def test_response_json_fields():
    tp = _tp(_ok(SRC + load("D", 10 + 0j, n="4") + GND, power_factor_target=0.95))
    assert set(tp) == {"source", "load", "wires", "balanced", "u_line", "u_phase", "line_currents",
                       "neutral_current", "load_phase_currents", "p", "q", "s", "pf", "pf_type",
                       "aron", "compensation"}
    assert set(tp["line_currents"]) == {"R", "S", "T"}
    assert set(tp["line_currents"]["R"]) >= {"real", "imaginary", "magnitude", "phase_degrees"}
    assert set(tp["aron"]) == {"p_a", "p_b"}
    assert set(tp["compensation"]) == {"target_pf", "q_c", "c_y", "c_delta", "applied", "reason"}


def test_other_responses_have_no_three_phase_fields():
    code, d = _post("V1 1 0 DC 10\nR1 1 0 5" + GND, mode="DC", analysis_type="NODAL")
    assert code == 200 and d["three_phase"] is None and d["wattmeters"] == []


def test_dc_mode_is_rejected_with_turkish_reason():
    code, d = _post(SRC + load("Y", 10 + 0j) + GND, mode="DC")
    assert code == 200 and d["three_phase"] is None
    assert any("AC" in m and "Üç fazlı" in m for m in d["errors"])


@pytest.mark.parametrize("bad", [
    "U1 1 2 3 0 3PH_SOURCE Z LINE 380 50 0 RST RMS",            # bağlantı Y/D değil
    "U1 1 2 3 0 3PH_SOURCE Y LINE -380 50 0 RST RMS",           # negatif gerilim
    "U1 1 1 3 0 3PH_SOURCE Y LINE 380 50 0 RST RMS",            # R ve S aynı düğüm
    "Y1 1 2 3 0 3PH_LOAD Y Z(10,0) Z(10,0)",                    # iki empedans
    "Y1 1 2 3 0 3PH_LOAD Y Z(10,0) Z(0,0) Z(10,0)",             # sıfır empedans
    "Y1 1 2 3 0 3PH_LOAD Y Z(-10,0) Z(10,0) Z(10,0)",           # negatif direnç
    "W1 1 1 3 0 WATTMETER",                                     # akım bobini kısa
])
def test_invalid_three_phase_lines_are_rejected_in_turkish(bad):
    code, text = _cached(bad + "\nR1 1 0 5" + GND, "{}")
    assert code == 400
    assert "Netlist hatası" in json.loads(text)["detail"]


def test_parser_reads_all_three_elements():
    p = parse_netlist(SRC + load("D", 8 + 6j, 7 + 0j, 6 - 2j, n="4") + "W1 1 5 6 7 WATTMETER", "RMS")
    assert not p.errors
    u, y, w = p.elements
    assert u.element_type == ElementType.THREE_PHASE_SOURCE and u.params["connection"] == "Y"
    assert u.params["input_basis"] == "RMS" and u.params["amplitude"] == 380
    assert y.element_type == ElementType.THREE_PHASE_LOAD and y.params["z"] == [8 + 6j, 7 + 0j, 6 - 2j]
    assert w.element_type == ElementType.WATTMETER and (w.node_positive, w.node_negative) == ("1", "5")
    assert p.node_count == 8


def test_floating_circuit_gets_a_reference_note():
    # Hiçbir düğüm 0 değil: çözüm için bir düğüm referans alınır, sonuçlar değişmez
    net = ("U1 1 2 3 4 3PH_SOURCE D LINE 380 50 0 RST RMS\n"
           "Y1 1 2 3 5 3PH_LOAD D Z(10,0) Z(10,0) Z(10,0)")
    d = _ok(net)
    assert math.isclose(_tp(d)["p"], 3 * (UH / 10) ** 2 * 10, rel_tol=1e-5)
    assert "referans" in _text(d, "Devreyi Tanıyalım")
