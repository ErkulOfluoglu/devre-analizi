"""
CircuitAnalyzer API — AC Etkin (RMS) / Tepe (Peak) Değer Desteği Testleri

Tüm beklenen değerler devre teorisi formülleriyle elle hesaplanmıştır:
- Netlist ayrıştırma: SINE(...) RMS, AC_PHASOR(...) RMS, akım kaynağı, küçük harf,
  DC ve pasif satırlarda RMS eki hatası
- Doğrusal ölçekleme: aynı fiziksel kaynakla PEAK ve RMS gösterimlerinde
  V ve I büyüklüklerinin √2 oranı, faz açılarının eşitliği
- Güç değişmezliği: R = 100 Ω ve Z = 10 + j10 Ω yüklerinde P ve Q'nun
  PEAK ve RMS gösterimlerde birebir aynı çıkması
- Thevenin: Vth √2 oranı, Zth eşitliği, Pmax eşitliği (4·Rth vs 8·Rth)
- Süperpozisyon: DC + AC ve iki farklı frekans (DC bileşen sabit, zaman ifadesinde tepe genlik)
- Bağımlı kaynaklı AC devrede √2 oranı ve güç eşitliği
- Alıştırma soruları: gerilim/akım beklentilerinin tabanı izlemesi, P ve Pmax'ın aynı kalması
- Anlatım: "Devreyi Tanıyalım" taban cümlesi, dönüşüm satırı (Um ↔ V),
  "Zaman Domenine Dönüş" içinde Um = √2·V hesabı
- API sözleşmesi: AnalysisRequest.value_display, AnalysisResponse.value_display,
  LlmAskRequest kalıtımı ve varsayılan PEAK davranışı
"""

import math
import pytest

from llm.assistant import build_messages, describe_element
from models.request import AnalysisMode, AnalysisType, LlmAskRequest, TheveninTerminals, ValueDisplay
from parser.netlist_parser import ElementType, parse_netlist
from practice.checker import check_answer
from solver.circuit_solver import solve_circuit

SQRT2 = math.sqrt(2.0)
GND = "* GND1 — Referans toprak (Node 0)\n"


def _all_texts(explanation) -> list[str]:
    return [b.text for sec in explanation for b in sec.blocks]


def _section(explanation, title_prefix: str):
    for sec in explanation:
        if sec.title.startswith(title_prefix):
            return sec
    return None


# ═══════════════════════════════════════════════════════
#  1. NETLIST AYRIŞTIRMA (RMS EKİ VE HATA DENETİMİ)
# ═══════════════════════════════════════════════════════

def test_parse_sine_voltage_rms_and_peak_scaling():
    net = f"V1 1 0 SINE(0 220 50 0 0 30) RMS\nR1 1 0 100\n{GND}"

    # Gösterim RMS: 220 V RMS girdi -> 220 V
    parsed_rms = parse_netlist(net, value_basis="RMS")
    assert not parsed_rms.errors
    assert parsed_rms.value_basis == "RMS"
    v1_rms = parsed_rms.elements[0]
    assert v1_rms.element_type == ElementType.AC_SOURCE_SINE
    assert v1_rms.params["input_basis"] == "RMS"
    assert v1_rms.params["input_value"] == pytest.approx(220.0)
    assert v1_rms.value == pytest.approx(220.0)
    assert v1_rms.params["amplitude"] == pytest.approx(220.0)

    # Gösterim PEAK (varsayılan): 220 V RMS girdi -> 220·√2 V tepe
    parsed_peak = parse_netlist(net)
    assert parsed_peak.value_basis == "PEAK"
    v1_peak = parsed_peak.elements[0]
    assert v1_peak.params["input_basis"] == "RMS"
    assert v1_peak.params["input_value"] == pytest.approx(220.0)
    assert v1_peak.value == pytest.approx(220.0 * SQRT2)
    assert v1_peak.params["amplitude"] == pytest.approx(220.0 * SQRT2)


def test_parse_ac_phasor_and_current_source_rms_case_insensitive():
    net = (
        "V1 1 0 AC_PHASOR(220, 30) rms\n"
        "I1 0 2 SINE(0 2 50 0 0 0) Rms\n"
        "I2 0 2 AC_PHASOR(4, -45) RMS\n"
        f"R1 1 2 50\n{GND}"
    )
    parsed_rms = parse_netlist(net, value_basis="RMS")
    assert not parsed_rms.errors
    v1, i1, i2 = parsed_rms.elements[0], parsed_rms.elements[1], parsed_rms.elements[2]
    assert v1.params["input_basis"] == "RMS"
    assert v1.value == pytest.approx(220.0)
    assert abs(v1.params["phasor_complex"]) == pytest.approx(220.0)
    assert i1.element_type == ElementType.CURRENT_AC_SINE
    assert i1.params["input_basis"] == "RMS"
    assert i1.value == pytest.approx(2.0)
    assert i2.element_type == ElementType.CURRENT_AC_PHASOR
    assert i2.params["input_basis"] == "RMS"
    assert i2.value == pytest.approx(4.0)

    # Aynı devre PEAK gösterimde √2 ile çarpılmalı
    parsed_peak = parse_netlist(net, value_basis="PEAK")
    assert parsed_peak.elements[0].value == pytest.approx(220.0 * SQRT2)
    assert abs(parsed_peak.elements[0].params["phasor_complex"]) == pytest.approx(220.0 * SQRT2)
    assert parsed_peak.elements[1].value == pytest.approx(2.0 * SQRT2)
    assert parsed_peak.elements[2].value == pytest.approx(4.0 * SQRT2)


def test_parse_default_without_rms_is_peak_and_scales_down_in_rms_mode():
    net = f"V1 1 0 AC_PHASOR(100, 0)\nR1 1 0 50\n{GND}"
    p_peak = parse_netlist(net, value_basis="PEAK")
    assert p_peak.elements[0].params["input_basis"] == "PEAK"
    assert p_peak.elements[0].value == pytest.approx(100.0)

    p_rms = parse_netlist(net, value_basis="RMS")
    assert p_rms.elements[0].params["input_basis"] == "PEAK"
    assert p_rms.elements[0].params["input_value"] == pytest.approx(100.0)
    assert p_rms.elements[0].value == pytest.approx(100.0 / SQRT2)


@pytest.mark.parametrize(
    "bad_line",
    [
        "V1 1 0 DC 12 RMS",
        "I1 0 1 DC 2 rms",
        "R1 1 0 100 RMS",
    ],
)
def test_rms_suffix_on_non_ac_line_produces_turkish_error(client, bad_line):
    net = f"{bad_line}\nR2 1 0 100\n{GND}"
    parsed = parse_netlist(net)
    assert len(parsed.errors) >= 1
    assert any("RMS" in err and "AC" in err for err in parsed.errors)

    resp = client.post("/analyze", json={"netlist": net, "mode": "DC"})
    assert resp.status_code == 400
    assert "RMS" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════
#  2. AYNI FİZİKSEL KAYNAKLA PEAK VE RMS ÇÖZÜM ORANI (√2)
# ═══════════════════════════════════════════════════════

def test_same_physical_circuit_peak_vs_rms_voltages_and_currents_ratio():
    # Fiziksel kaynak: 220∠30° V (etkin) = 220√2∠30° V (tepe)
    # Seri R1 = 60 Ω ve Z1 = 20 + j80 Ω -> Z_top = 80 + j80 = 80√2∠45° Ω
    # Elle hesap (RMS):
    #   I_rms = 220∠30° / (80√2∠45°) = (2.75/√2)∠-15° A ≈ 1.9445436∠-15° A
    #   V2_rms = I_rms * (20 + j80)
    net = (
        "V1 1 0 SINE(0 220 50 0 0 30) RMS\n"
        "R1 1 2 60\n"
        "Z1 2 0 COMPLEX(20, 80)\n"
        f"{GND}"
    )
    res_peak, _, err_p = solve_circuit(
        parse_netlist(net, value_basis="PEAK"), AnalysisMode.AC_PHASOR, frequency=50.0
    )
    res_rms, _, err_r = solve_circuit(
        parse_netlist(net, value_basis="RMS"), AnalysisMode.AC_PHASOR, frequency=50.0
    )
    assert not err_p and not err_r

    i_expected_rms = 220.0 / (80.0 * SQRT2)
    i_expected_peak = 220.0 / 80.0  # 2.75 A
    assert res_rms.element_currents["R1"].value.magnitude == pytest.approx(i_expected_rms, rel=1e-6)
    assert res_peak.element_currents["R1"].value.magnitude == pytest.approx(i_expected_peak, rel=1e-6)
    assert res_rms.element_currents["R1"].value.phase_degrees == pytest.approx(-15.0, abs=1e-4)
    assert res_peak.element_currents["R1"].value.phase_degrees == pytest.approx(-15.0, abs=1e-4)

    for node in ("1", "2"):
        vp = res_peak.node_voltages[node].value
        vr = res_rms.node_voltages[node].value
        assert vp.magnitude == pytest.approx(vr.magnitude * SQRT2, rel=1e-6)
        assert vp.phase_degrees == pytest.approx(vr.phase_degrees, abs=1e-4)

    for eid in ("V1", "R1", "Z1"):
        ip = res_peak.element_currents[eid].value
        ir = res_rms.element_currents[eid].value
        assert ip.magnitude == pytest.approx(ir.magnitude * SQRT2, rel=1e-6)
        assert ip.phase_degrees == pytest.approx(ir.phase_degrees, abs=1e-4)


# ═══════════════════════════════════════════════════════
#  3. GÜÇ DEĞİŞMEZLİĞİ (P, Q, |S|, cos φ)
# ═══════════════════════════════════════════════════════

def test_power_identical_in_peak_and_rms_for_100_ohm_resistor():
    # V = 200 V (RMS) = 200√2 V (tepe), R = 100 Ω
    # Elle hesap: I_rms = 2 A, P = I_rms² · R = 4 · 100 = 400 W, Q = 0 VAR
    net = f"V1 1 0 SINE(0 200 50 0 0 0) RMS\nR1 1 0 100\n{GND}"
    res_peak, steps_peak, _ = solve_circuit(
        parse_netlist(net, value_basis="PEAK"), AnalysisMode.AC_PHASOR, frequency=50.0
    )
    res_rms, steps_rms, _ = solve_circuit(
        parse_netlist(net, value_basis="RMS"), AnalysisMode.AC_PHASOR, frequency=50.0
    )

    assert res_peak.power.elements["R1"].active_power == pytest.approx(400.0, rel=1e-6)
    assert res_rms.power.elements["R1"].active_power == pytest.approx(400.0, rel=1e-6)
    assert res_peak.power.elements["R1"].reactive_power == pytest.approx(0.0, abs=1e-9)
    assert res_rms.power.elements["R1"].reactive_power == pytest.approx(0.0, abs=1e-9)
    assert res_peak.power.total_supplied.real == pytest.approx(400.0, rel=1e-6)
    assert res_rms.power.total_supplied.real == pytest.approx(400.0, rel=1e-6)

    # Convention ve adım formülleri tabana uymalı
    assert "½·V·I*" in res_peak.power.convention
    assert "S = V·I*" in res_rms.power.convention
    assert "½" not in res_rms.power.convention

    pw_sec_rms = _section(res_rms.explanation, "Güç Hesabı")
    pw_rms_texts = [b.text for b in pw_sec_rms.blocks]
    assert any("P_R1 = |I|²·R" in t for t in pw_rms_texts)
    assert not any("½" in t for t in pw_rms_texts)


def test_power_identical_in_peak_and_rms_for_10_plus_j10_load():
    # Kaynak: 100 V (RMS) = 100√2 V (tepe), yük: R1 = 10 Ω seri Z1 = j10 Ω -> Z = 10 + j10 Ω
    # Elle hesap:
    #   I_rms = 100 / (10 + j10) = 5 - j5 A  (|I_rms| = 5√2 A, |I_rms|² = 50 A²)
    #   P = |I_rms|² · 10 = 500 W
    #   Q = |I_rms|² · 10 = 500 VAR
    #   |S| = 500√2 ≈ 707.10678 VA, cos φ = 1/√2 ≈ 0.70710678 (geri)
    net = (
        "V1 1 0 AC_PHASOR(100, 0) RMS\n"
        "R1 1 2 10\n"
        "Z1 2 0 COMPLEX(0, 10)\n"
        f"{GND}"
    )
    res_peak, _, _ = solve_circuit(
        parse_netlist(net, value_basis="PEAK"), AnalysisMode.AC_PHASOR, frequency=50.0
    )
    res_rms, _, _ = solve_circuit(
        parse_netlist(net, value_basis="RMS"), AnalysisMode.AC_PHASOR, frequency=50.0
    )

    for res in (res_peak, res_rms):
        assert res.power.elements["R1"].active_power == pytest.approx(500.0, rel=1e-6)
        assert res.power.elements["R1"].reactive_power == pytest.approx(0.0, abs=1e-9)
        assert res.power.elements["Z1"].active_power == pytest.approx(0.0, abs=1e-9)
        assert res.power.elements["Z1"].reactive_power == pytest.approx(500.0, rel=1e-6)
        assert res.power.total_absorbed.real == pytest.approx(500.0, rel=1e-6)
        assert res.power.total_absorbed.imaginary == pytest.approx(500.0, rel=1e-6)
        assert res.power.total_absorbed.magnitude == pytest.approx(500.0 * SQRT2, rel=1e-6)
        assert res.power.power_factor == pytest.approx(1.0 / SQRT2, rel=1e-5)
        assert res.power.power_factor_type == "geri"


# ═══════════════════════════════════════════════════════
#  4. THEVENIN (Vth √2 ORANI, Zth VE Pmax EŞİTLİĞİ)
# ═══════════════════════════════════════════════════════

def test_thevenin_vth_ratio_zth_same_and_pmax_same():
    # V1 = 100∠25° V (RMS) = 100√2∠25° V (tepe), R1 = 20 Ω (1-2), Z1 = j20 Ω (2-0), port (2, 0)
    # Elle hesap:
    #   j20 / (20 + j20) = (1/√2)∠45°
    #   Vth_rms = 100∠25° · (1/√2)∠45° = (100/√2)∠70° V
    #   Vth_peak = 100∠70° V  (= Vth_rms · √2)
    #   Zth = 20 || j20 = (400j) / (20 + 20j) = 10 + j10 Ω  (Rth = 10 Ω)
    #   Pmax = |Vth_rms|² / (4·Rth) = 5000 / 40 = 125 W = |Vth_peak|² / (8·Rth) = 10000 / 80 = 125 W
    net = (
        "V1 1 0 AC_PHASOR(100, 25) RMS\n"
        "R1 1 2 20\n"
        "Z1 2 0 COMPLEX(0, 20)\n"
        f"{GND}"
    )
    terms = TheveninTerminals(node_positive="2", node_negative="0")
    res_peak, _, _ = solve_circuit(
        parse_netlist(net, value_basis="PEAK"),
        AnalysisMode.AC_PHASOR,
        frequency=50.0,
        analysis_type=AnalysisType.THEVENIN,
        thevenin_terminals=terms,
    )
    res_rms, _, _ = solve_circuit(
        parse_netlist(net, value_basis="RMS"),
        AnalysisMode.AC_PHASOR,
        frequency=50.0,
        analysis_type=AnalysisType.THEVENIN,
        thevenin_terminals=terms,
    )

    assert res_rms.thevenin.vth.magnitude == pytest.approx(100.0 / SQRT2, rel=1e-6)
    assert res_peak.thevenin.vth.magnitude == pytest.approx(100.0, rel=1e-6)
    assert res_rms.thevenin.vth.phase_degrees == pytest.approx(70.0, abs=1e-4)
    assert res_peak.thevenin.vth.phase_degrees == pytest.approx(70.0, abs=1e-4)

    assert res_rms.thevenin.zth.real == pytest.approx(10.0, rel=1e-6)
    assert res_peak.thevenin.zth.real == pytest.approx(10.0, rel=1e-6)
    assert res_rms.thevenin.zth.imaginary == pytest.approx(10.0, rel=1e-6)
    assert res_peak.thevenin.zth.imaginary == pytest.approx(10.0, rel=1e-6)

    pmax_sec_rms = _section(res_rms.explanation, "Maksimum Güç Transferi")
    pmax_sec_peak = _section(res_peak.explanation, "Maksimum Güç Transferi")
    rms_texts = [b.text for b in pmax_sec_rms.blocks]
    peak_texts = [b.text for b in pmax_sec_peak.blocks]
    assert any("4·Rth" in t and "125 W" in t for t in rms_texts)
    assert any("8·Rth" in t and "125 W" in t for t in peak_texts)


# ═══════════════════════════════════════════════════════
#  5. SÜPERPOZİSYON (DC + AC VE İKİ FARKLI FREKANS)
# ═══════════════════════════════════════════════════════

def test_superposition_dc_plus_ac_dc_unchanged_and_time_domain_amplitude():
    # V1 = 12 V DC (1-0), V2 = 10 V RMS SINE 50 Hz (2-0), R1 = 100 Ω (1-3), R2 = 100 Ω (2-3)
    # Elle hesap (Düğüm 3):
    #   V1 (DC) katkısı: V3' = 12 * 100 / 200 = 6 V (DC kaynak ASLA ölçeklenmez)
    #   V2 (AC) katkısı: RMS gösterimde 5∠0° V, PEAK gösterimde 5√2∠0° V (≈ 7.071 V)
    #   Zaman ifadesi v₃(t): her iki gösterimde de "6 + 7,071·sin(314,2t + 0°) V"
    net = (
        "V1 1 0 DC 12\n"
        "V2 2 0 SINE(0 10 50 0 0 0) RMS\n"
        "R1 1 3 100\n"
        "R2 2 3 100\n"
        f"{GND}"
    )
    res_rms, _, _ = solve_circuit(
        parse_netlist(net, value_basis="RMS"),
        AnalysisMode.AC_TIME,
        frequency=50.0,
        analysis_type=AnalysisType.SUPERPOSITION,
    )
    res_peak, _, _ = solve_circuit(
        parse_netlist(net, value_basis="PEAK"),
        AnalysisMode.AC_TIME,
        frequency=50.0,
        analysis_type=AnalysisType.SUPERPOSITION,
    )

    c_v1_rms = next(c for c in res_rms.superposition if c.source_id == "V1")
    c_v1_peak = next(c for c in res_peak.superposition if c.source_id == "V1")
    assert c_v1_rms.node_voltages["3"].real == pytest.approx(6.0, rel=1e-6)
    assert c_v1_peak.node_voltages["3"].real == pytest.approx(6.0, rel=1e-6)

    c_v2_rms = next(c for c in res_rms.superposition if c.source_id == "V2")
    c_v2_peak = next(c for c in res_peak.superposition if c.source_id == "V2")
    assert c_v2_rms.node_voltages["3"].magnitude == pytest.approx(5.0, rel=1e-6)
    assert c_v2_peak.node_voltages["3"].magnitude == pytest.approx(5.0 * SQRT2, rel=1e-6)

    tot_rms = _section(res_rms.explanation, "Toplam")
    tot_peak = _section(res_peak.explanation, "Toplam")
    assert any("v₃(t) = 6 + 7,071·sin(314,2t + 0°) V" in b.text for b in tot_rms.blocks)
    assert any("v₃(t) = 6 + 7,071·sin(314,2t + 0°) V" in b.text for b in tot_peak.blocks)


def test_superposition_two_frequencies_time_expression_in_rms():
    # V1: 50 Hz, 10 V RMS (tepe 10√2 ≈ 14.142 V) -> Düğüm 3'te yarısı: 5 V RMS, tepe 5√2 ≈ 7.071 V
    # V2: 100 Hz, 20 V PEAK (etkin 20/√2 ≈ 14.142 V) -> Düğüm 3'te yarısı: tepe 10 V, etkin 10/√2 V
    net = (
        "V1 1 0 SINE(0 10 50 0 0 0) RMS\n"
        "V2 2 0 SINE(0 20 100 0 0 0)\n"
        "R1 1 3 100\n"
        "R2 2 3 100\n"
        f"{GND}"
    )
    res_rms, _, _ = solve_circuit(
        parse_netlist(net, value_basis="RMS"),
        AnalysisMode.AC_TIME,
        frequency=50.0,
        analysis_type=AnalysisType.SUPERPOSITION,
    )
    tot_rms = _section(res_rms.explanation, "Toplam")
    tot_texts = [b.text for b in tot_rms.blocks]
    assert any("7,071·sin(314,2t + 0°)" in t and "10·sin(628,3t + 0°)" in t for t in tot_texts)


# ═══════════════════════════════════════════════════════
#  6. BAĞIMLI KAYNAKLI AC DEVRE
# ═══════════════════════════════════════════════════════

def test_dependent_source_ac_peak_vs_rms():
    # V1 = 10 V RMS (1-0), R1 = 100 Ω (1-2), E1 (VCVS, 2-0, kazanç 2 * V(R1)):
    # V(R1) = V(1) - V(2) => V(2) = 2 * (V(1) - V(2)) => 3 * V(2) = 2 * V(1) => V(2) = (2/3) * V1
    # Elle hesap:
    #   RMS: V(2) = 20/3 ≈ 6.666667 V, I(R1) = (10 - 20/3)/100 = 1/30 A
    #   PEAK: V(2) = (20/3)·√2 V, I(R1) = (1/30)·√2 A
    #   P(R1) = I_rms² · R1 = (1/900) · 100 = 1/9 W ≈ 0.111111 W (her iki gösterimde eşit)
    net = (
        "V1 1 0 AC_PHASOR(10, 0) RMS\n"
        "R1 1 2 100\n"
        "E1 2 0 V(R1) 2\n"
        f"{GND}"
    )
    res_rms, _, err_r = solve_circuit(
        parse_netlist(net, value_basis="RMS"), AnalysisMode.AC_PHASOR, frequency=50.0
    )
    res_peak, _, err_p = solve_circuit(
        parse_netlist(net, value_basis="PEAK"), AnalysisMode.AC_PHASOR, frequency=50.0
    )
    assert not err_r and not err_p
    v2_rms = res_rms.node_voltages["2"].value
    v2_peak = res_peak.node_voltages["2"].value
    v2_rms_mag = v2_rms if isinstance(v2_rms, (int, float)) else v2_rms.magnitude
    v2_peak_mag = v2_peak if isinstance(v2_peak, (int, float)) else v2_peak.magnitude
    assert v2_rms_mag == pytest.approx(20.0 / 3.0, rel=1e-6)
    assert v2_peak_mag == pytest.approx(20.0 * SQRT2 / 3.0, rel=1e-6)
    assert res_rms.power.elements["R1"].active_power == pytest.approx(1.0 / 9.0, rel=1e-6)
    assert res_peak.power.elements["R1"].active_power == pytest.approx(1.0 / 9.0, rel=1e-6)


# ═══════════════════════════════════════════════════════
#  7. ALIŞTIRMA SORULARI VE CEVAP DENETİMİ
# ═══════════════════════════════════════════════════════

def test_practice_questions_follow_basis_while_ac_power_stays_same():
    net = (
        "V1 1 0 AC_PHASOR(100, 0) RMS\n"
        "R1 1 2 20\n"
        "R2 2 0 20\n"
        f"{GND}"
    )
    res_rms, _, _ = solve_circuit(
        parse_netlist(net, value_basis="RMS"), AnalysisMode.AC_PHASOR, frequency=50.0
    )
    res_peak, _, _ = solve_circuit(
        parse_netlist(net, value_basis="PEAK"), AnalysisMode.AC_PHASOR, frequency=50.0
    )

    q_rms = {q.id: q for q in res_rms.practice}
    q_peak = {q.id: q for q in res_peak.practice}

    # Düğüm 2 gerilimi: RMS'te 50 V, PEAK'te 50√2 V
    assert q_rms["V2"].expected.magnitude == pytest.approx(50.0, rel=1e-6)
    assert q_peak["V2"].expected.magnitude == pytest.approx(50.0 * SQRT2, rel=1e-6)

    # Toplam aktif güç P_TOTAL: I_rms = 100 / 40 = 2.5 A -> P = 2.5² * 40 = 250 W (her ikisinde aynı!)
    assert q_rms["P_TOTAL"].expected.real == pytest.approx(250.0, rel=1e-6)
    assert q_peak["P_TOTAL"].expected.real == pytest.approx(250.0, rel=1e-6)
    assert "P = |I|²·R" in q_rms["P_TOTAL"].hint

    # RMS güç sorusunda öğrenci yanlışlıkla ½ ile çarpıp 125 W yazarsa özel teşhis döner
    verdict_half = check_answer(q_rms["P_TOTAL"], "125 W")
    assert verdict_half.status == "wrong"
    assert "etkin (RMS)" in verdict_half.message

    # √2 kat fark teşhisi tabandan bağımsız uyarı verir
    verdict_sqrt2 = check_answer(q_rms["V2"], f"{50.0 * SQRT2:.4f}∠0")
    assert verdict_sqrt2.status == "wrong"
    assert "√2" in verdict_sqrt2.message
    assert "Etkin değer = tepe/√2" in verdict_sqrt2.message

    # Thevenin PMAX sorusu da iki gösterimde aynı (62.5 W) olmalı
    terms = TheveninTerminals(node_positive="2", node_negative="0")
    th_rms, _, _ = solve_circuit(
        parse_netlist(net, value_basis="RMS"),
        AnalysisMode.AC_PHASOR,
        frequency=50.0,
        analysis_type=AnalysisType.THEVENIN,
        thevenin_terminals=terms,
    )
    th_peak, _, _ = solve_circuit(
        parse_netlist(net, value_basis="PEAK"),
        AnalysisMode.AC_PHASOR,
        frequency=50.0,
        analysis_type=AnalysisType.THEVENIN,
        thevenin_terminals=terms,
    )
    q_th_rms = {q.id: q for q in th_rms.practice}
    q_th_peak = {q.id: q for q in th_peak.practice}
    assert q_th_rms["VTH"].expected.magnitude == pytest.approx(50.0, rel=1e-6)
    assert q_th_peak["VTH"].expected.magnitude == pytest.approx(50.0 * SQRT2, rel=1e-6)
    assert q_th_rms["PMAX"].expected.real == pytest.approx(62.5, rel=1e-6)
    assert q_th_peak["PMAX"].expected.real == pytest.approx(62.5, rel=1e-6)
    assert "4·Rth" in q_th_rms["PMAX"].hint
    assert "8·Rth" in q_th_peak["PMAX"].hint


# ═══════════════════════════════════════════════════════
#  8. ANLATIM: TABAN CÜMLESİ, DÖNÜŞÜM SATIRI VE ZAMAN DOMENİ Um
# ═══════════════════════════════════════════════════════

def test_narrative_intro_basis_sentence_conversion_lines_and_time_domain_um():
    # 1) Kaynak PEAK (311.127 V), gösterim RMS -> Um = 311,1 V (tepe) → V = Um/√2 = 220 V (etkin)
    peak_val = 220.0 * SQRT2
    net_peak_in = f"V1 1 0 SINE(0 {peak_val:.6f} 50 0 0 0)\nR1 1 0 100\n{GND}"
    res_rms, _, _ = solve_circuit(
        parse_netlist(net_peak_in, value_basis="RMS"), AnalysisMode.AC_TIME, frequency=50.0
    )
    intro_rms = _section(res_rms.explanation, "Devreyi Tanıyalım")
    intro_rms_texts = [b.text for b in intro_rms.blocks]
    assert sum(1 for t in intro_rms_texts if "Bu çözümde AC değerler etkin (RMS) olarak gösterilir." == t) == 1
    assert any("V1: Um = 311,1 V (tepe) → V = Um/√2 = 220 V (etkin)" in t for t in intro_rms_texts)

    # Zaman domeninde Um = √2·V = 311,1 V açıkça yazılmalı
    td_rms = _section(res_rms.explanation, "Zaman Domenine Dönüş")
    td_rms_texts = [b.text for b in td_rms.blocks]
    assert any("v(t) = √2·|V|·sin(ωt + θ)" in t for t in td_rms_texts)
    assert any("Um = √2·V = √2·220 = 311,1 V" in t for t in td_rms_texts)

    # 2) Kaynak RMS (220 V), gösterim PEAK -> V1: V = 220 V (etkin) → Um = √2·V = 311,1 V (tepe)
    net_rms_in = f"V1 1 0 SINE(0 220 50 0 0 0) RMS\nR1 1 0 100\n{GND}"
    res_peak, _, _ = solve_circuit(
        parse_netlist(net_rms_in, value_basis="PEAK"), AnalysisMode.AC_TIME, frequency=50.0
    )
    intro_peak = _section(res_peak.explanation, "Devreyi Tanıyalım")
    intro_peak_texts = [b.text for b in intro_peak.blocks]
    assert sum(1 for t in intro_peak_texts if "Bu çözümde AC değerler tepe değer olarak gösterilir." == t) == 1
    assert any("V1: V = 220 V (etkin) → Um = √2·V = 311,1 V (tepe)" in t for t in intro_peak_texts)

    # 3) Kaynak tabanı ile gösterim tabanı aynıysa dönüşüm satırı yazılmaz
    res_same, _, _ = solve_circuit(
        parse_netlist(net_rms_in, value_basis="RMS"), AnalysisMode.AC_TIME, frequency=50.0
    )
    intro_same = _section(res_same.explanation, "Devreyi Tanıyalım")
    assert not any("→" in b.text and "√2" in b.text for b in intro_same.blocks)


# ═══════════════════════════════════════════════════════
#  9. API UÇ NOKTASI (value_display) VE LLM ASİSTAN KALITIMI
# ═══════════════════════════════════════════════════════

def test_api_analyze_value_display_rms_and_default_peak(client):
    net = f"V1 1 0 AC_PHASOR(220, 0) RMS\nR1 1 0 110\n{GND}"

    # 1) value_display verilmediğinde varsayılan PEAK
    resp_default = client.post("/analyze", json={"netlist": net, "mode": "AC_PHASOR", "frequency": 50})
    assert resp_default.status_code == 200
    body_def = resp_default.json()
    assert body_def["value_display"] == "PEAK"
    v1_def = body_def["results"]["node_voltages"]["1"]["value"]
    v1_def_mag = v1_def if isinstance(v1_def, (int, float)) else v1_def["magnitude"]
    assert v1_def_mag == pytest.approx(220.0 * SQRT2, rel=1e-6)
    assert body_def["results"]["power"]["total_absorbed"]["real"] == pytest.approx(440.0, rel=1e-6)

    # 2) value_display = "RMS"
    resp_rms = client.post(
        "/analyze",
        json={"netlist": net, "mode": "AC_PHASOR", "frequency": 50, "value_display": "RMS"},
    )
    assert resp_rms.status_code == 200
    body_rms = resp_rms.json()
    assert body_rms["value_display"] == "RMS"
    v1_rms = body_rms["results"]["node_voltages"]["1"]["value"]
    v1_rms_mag = v1_rms if isinstance(v1_rms, (int, float)) else v1_rms["magnitude"]
    assert v1_rms_mag == pytest.approx(220.0, rel=1e-6)
    assert body_rms["results"]["power"]["total_absorbed"]["real"] == pytest.approx(440.0, rel=1e-6)


def test_llm_ask_request_inherits_value_display_and_assistant_adapts():
    req_default = LlmAskRequest(netlist="V1 1 0 DC 10\nR1 1 0 10", mode=AnalysisMode.DC, question="Nedir?")
    assert req_default.value_display == ValueDisplay.PEAK

    req_rms = LlmAskRequest(
        netlist="V1 1 0 AC_PHASOR(220, 0) RMS\nR1 1 0 10",
        mode=AnalysisMode.AC_PHASOR,
        frequency=50.0,
        value_display=ValueDisplay.RMS,
        question="V1 kaç volttur?",
    )
    assert req_rms.value_display == ValueDisplay.RMS

    parsed_rms = parse_netlist(req_rms.netlist, value_basis=req_rms.value_display.value)
    res_rms, _, _ = solve_circuit(parsed_rms, AnalysisMode.AC_PHASOR, frequency=50.0)
    desc = describe_element(parsed_rms.elements[0], parsed_rms.value_basis)
    assert "etkin (RMS)" in desc
    assert "220 V" in desc

    msgs = build_messages(
        parsed_rms, res_rms, AnalysisType.NODAL, False, 50.0, None,
        req_rms.question, [], False, []
    )
    assert "Fazörler etkin (RMS) değerdir" in msgs[0]["content"]
