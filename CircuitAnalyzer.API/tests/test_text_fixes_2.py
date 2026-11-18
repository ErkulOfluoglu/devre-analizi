"""
Anlatım metni düzeltmeleri — 2. grup (maddeler 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 15, 16, 17, 19, 21).
"""

import pytest
from explainer.formatting import MINUS
from llm.assistant import circuit_text, current_directions_text, describe_element
from models.request import AnalysisMode, AnalysisType
from parser.netlist_parser import parse_netlist
from solver.circuit_solver import solve_circuit

GND = "\n* GND1 — Referans toprak (Node 0)"


def _post(client, body):
    r = client.post("/analyze", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _texts(client, body):
    data = _post(client, body)
    out = []
    for sec in data["results"]["explanation"]:
        out.append(sec["title"])
        out += [b.get("text", "") for b in sec["blocks"]]
    return out


def _sec_text(client, body, title):
    data = _post(client, body)
    for sec in data["results"]["explanation"]:
        if sec["title"] == title:
            return "\n".join(b.get("text", "") for b in sec["blocks"])
    raise AssertionError(f"Section {title!r} not found")


# ─── Madde 2: Negatif sin φ (veya cos φ) çarpımında parantez ───

def test_item2_negative_sin_phi_wrapped_in_parentheses(client):
    t = _sec_text(client, {
        "netlist": "V1 1 0 SINE(0 100 50 0 0 0) RMS\nR1 1 2 10\nC1 2 0 200u" + GND,
        "mode": "AC_PHASOR",
        "analysis_type": "POWER",
        "value_display": "RMS",
    }, "Güç Üçgeni")
    assert f"· ({MINUS}" in t
    assert f"· {MINUS}" not in t


# ─── Madde 3: DC ofset uyarısı devredeki sin/cos kuralına uyar ───

def test_item3_dc_offset_warning_uses_sin_for_sine_and_cos_for_phasor(client):
    d_sine = _post(client, {
        "netlist": "V1 1 0 SINE(5 10 50 0 0 0)\nR1 1 0 100" + GND,
        "mode": "AC_PHASOR",
        "analysis_type": "NODAL",
    })
    warn_sine = " ".join(d_sine["warnings"])
    # Yalnız frekans adımı: başka adımlarda "cos φ" (güç katsayısı) geçebilir
    freq_sine = " ".join(s["description"] + " " + (s.get("latex_formula") or "")
                         for s in d_sine["solution_steps"]
                         if s["title"].startswith("Frekans Analizi"))
    assert "|V|·sin(ωt + θ)" in warn_sine
    assert "|V|·cos(ωt + θ)" not in warn_sine
    assert "\\sin" in freq_sine and "\\cos" not in freq_sine
    assert "sin(ω_k t + θ_k)" in freq_sine

    d_phasor = _post(client, {
        "netlist": "V1 1 0 DC 5\nV2 1 2 AC_PHASOR(10, 0)\nR1 2 0 100" + GND,
        "mode": "AC_PHASOR",
        "analysis_type": "NODAL",
        "frequency": 50.0,
    })
    warn_phasor = " ".join(d_phasor["warnings"])
    steps_phasor = " ".join(s["description"] + " " + (s.get("latex_formula") or "")
                            for s in d_phasor["solution_steps"])
    assert "|V|·cos(ωt + θ)" in warn_phasor
    assert "cos(" in steps_phasor and "\\cos" in steps_phasor


# ─── Madde 4: Üç faz kompanzasyonda C_Y ve C_Δ türetmesi ───

def test_item4_three_phase_compensation_shows_star_and_delta_derivation(client):
    t = _sec_text(client, {
        "netlist": "U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 0 RST RMS\n"
                   "Y1 1 2 3 0 3PH_LOAD Y Z(30,40) Z(30,40) Z(30,40)" + GND,
        "mode": "AC_PHASOR",
        "analysis_type": "THREE_PHASE",
        "value_display": "RMS",
        "power_factor_target": 0.95,
    }, "Kompanzasyon")
    assert "Q_C = 3·ω·C_Y·U_f² = ω·C_Y·U_h²  (U_h² = 3·U_f²)   →   C_Y = Q_C / (ω·U_h²)" in t
    assert "Q_C = 3·ω·C_Δ·U_h²   →   C_Δ = Q_C / (3·ω·U_h²) = C_Y / 3 =" in t


# ─── Madde 5: 3 telli üç faz sistemde nötr akımı amaçta anılmaz ───

def test_item5_three_phase_intro_mentions_neutral_current_only_with_neutral(client):
    t_3wire = _sec_text(client, {
        "netlist": "U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 0 RST RMS\n"
                   "Y1 1 2 3 4 3PH_LOAD Y Z(30,40) Z(30,40) Z(30,40)" + GND,
        "mode": "AC_PHASOR",
        "analysis_type": "THREE_PHASE",
    }, "Devreyi Tanıyalım")
    assert "nötr akımını" not in t_3wire
    assert "Amaç: faz ve hat akımlarını ve gücü" in t_3wire

    t_4wire = _sec_text(client, {
        "netlist": "U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 0 RST RMS\n"
                   "Y1 1 2 3 0 3PH_LOAD Y Z(30,40) Z(30,40) Z(30,40)" + GND,
        "mode": "AC_PHASOR",
        "analysis_type": "THREE_PHASE",
    }, "Devreyi Tanıyalım")
    assert "Amaç: faz ve hat akımlarını, nötr akımını ve gücü" in t_4wire


# ─── Madde 6: Rezonansta ω₀ = 2π·f₀ ve kaynak frekansı ayrımı ───

def test_item6_resonance_intro_distinguishes_f0_omega0_from_source_frequency(client):
    t = _sec_text(client, {
        "netlist": "V1 1 0 SINE(0 10 1000 0 0 0)\nR1 1 2 10\nL1 2 3 10m\nC1 3 0 1u" + GND,
        "mode": "AC_PHASOR",
        "analysis_type": "RESONANCE",
    }, "Devreyi Tanıyalım")
    assert "kaynak frekansı f = 1000 Hz" in t
    assert "ω₀ = 2π·f₀ = 2π · 1592 Hz = 10000 rad/s" in t
    assert "ω = 2πf =" not in t


# ─── Madde 7: Aron sağlamasında hat empedansı varken ve yokken ifade ───

def test_item7_aron_check_distinguishes_load_arms_from_line_loss_case(client):
    t_no_line = _sec_text(client, {
        "netlist": "U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 0 RST RMS\n"
                   "Y1 1 2 3 4 3PH_LOAD Y Z(30,40) Z(30,40) Z(30,40)" + GND,
        "mode": "AC_PHASOR",
        "analysis_type": "THREE_PHASE",
    }, "Aron (İki Wattmetre) Yöntemi")
    assert "yük kollarının toplam gücüne" in t_no_line
    assert "hat kayıpları dahildir" not in t_no_line

    t_with_line = _sec_text(client, {
        "netlist": "U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 0 RST RMS\n"
                   "R1 1 4 1\nR2 2 5 1\nR3 3 6 1\n"
                   "Y1 4 5 6 7 3PH_LOAD Y Z(30,40) Z(30,40) Z(30,40)" + GND,
        "mode": "AC_PHASOR",
        "analysis_type": "THREE_PHASE",
    }, "Aron (İki Wattmetre) Yöntemi")
    assert "wattmetre noktalarından giren (kaynağın verdiği) toplam güce" in t_with_line
    assert "hat kayıpları dahildir" in t_with_line


# ─── Madde 8: İç içe parantez yok ("geri, endüktif" / "birim, rezistif") ───

def test_item8_power_factor_labels_have_no_nested_parentheses(client):
    for elem, expected in [("L1 2 0 100m", "(geri, endüktif)"),
                           ("C1 2 0 100u", "(ileri, kapasitif)"),
                           ("R2 2 0 50", "(birim, rezistif)")]:
        t = " ".join(_texts(client, {
            "netlist": f"V1 1 0 SINE(0 100 50 0 0 0) RMS\nR1 1 2 50\n{elem}" + GND,
            "mode": "AC_PHASOR",
            "analysis_type": "POWER",
        }))
        assert expected in t
        assert "geri (endüktif)" not in t
        assert "ileri (kapasitif)" not in t
        assert "birim (rezistif)" not in t

    t_3ph = " ".join(_texts(client, {
        "netlist": "U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 0 RST RMS\n"
                   "Y1 1 2 3 0 3PH_LOAD Y Z(50,0) Z(50,0) Z(50,0)" + GND,
        "mode": "AC_PHASOR",
        "analysis_type": "THREE_PHASE",
    }))
    assert "(birim, rezistif)" in t_3ph
    assert "geri (endüktif)" not in t_3ph


# ─── Madde 9: Transformatörde primerde eleman yokken Z_top satırı atlanır ───

def test_item9_transformer_drops_redundant_ztop_when_no_primary_elements(client):
    t_no_prim = _sec_text(client, {
        "netlist": "V1 1 0 SINE(0 100 50 0 0 0) RMS\nT1 1 0 2 0 IDEAL 0.5\nR1 2 0 10" + GND,
        "mode": "AC_PHASOR",
        "analysis_type": "TRANSFORMER",
        "value_display": "RMS",
    }, "Primere İndirgenmiş Devre")
    assert "Z_top = Z₁" not in t_no_prim
    assert "I₁ = V / Z₁ = 100 V / 40 Ω = 2,5 A" in t_no_prim

    t_with_prim = _sec_text(client, {
        "netlist": "V1 1 0 SINE(0 100 50 0 0 0) RMS\nRs 1 3 10\nT1 3 0 2 0 IDEAL 0.5\nR1 2 0 10" + GND,
        "mode": "AC_PHASOR",
        "analysis_type": "TRANSFORMER",
        "value_display": "RMS",
    }, "Primere İndirgenmiş Devre")
    assert "Z_top =" in t_with_prim
    assert "I₁ = V / Z_top =" in t_with_prim


# ─── Madde 10 ve 12: Karma dengesiz yükte Q açıklaması ve ΣP_k / 0 V ölçüm kaynağı jargonu yok ───

def test_item10_and_12_three_phase_mixed_load_and_no_jargon(client):
    body = {
        "netlist": "U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 0 RST RMS\n"
                   "W1 1 11 1 0 WATTMETER\n"
                   "Y1 11 2 3 0 3PH_LOAD Y Z(30,20) Z(30,-40) Z(50,0)" + GND,
        "mode": "AC_PHASOR",
        "analysis_type": "THREE_PHASE",
    }
    guc = _sec_text(client, body, "Güç")
    assert "P = P_R + P_S + P_T =" in guc
    assert "Q = Q_R + Q_S + Q_T =" in guc
    assert "ΣP_k" not in guc and "ΣQ_k" not in guc
    assert "Toplam reaktif güç negatif (Q < 0) olduğundan yük bir bütün olarak kapasitif davranır" in guc
    assert "kolların karakteri ise farklıdır" in guc
    assert "Z_R endüktif, Z_S kapasitif, Z_T rezistif" in guc

    all_t = " ".join(_texts(client, body))
    assert "0 V'luk" not in all_t
    assert "ölçüm kaynağı" not in all_t


# ─── Madde 14: Kondansatör/bobin empedans notu yalnız ilgili eleman varken ───

def test_item14_impedance_notes_match_present_reactive_elements(client):
    t_only_l = _sec_text(client, {
        "netlist": "V1 1 0 SINE(0 10 50 0 0 0) RMS\nR1 1 2 10\nL1 2 0 31.83m" + GND,
        "mode": "AC_PHASOR",
        "analysis_type": "NODAL",
    }, "Empedanslar ve Fazörler")
    assert "Bobinin empedansı +j yönünde" in t_only_l
    assert "Kondansatörün empedansı" not in t_only_l

    t_only_c = _sec_text(client, {
        "netlist": "V1 1 0 SINE(0 10 50 0 0 0) RMS\nR1 1 2 10\nC1 2 0 100u" + GND,
        "mode": "AC_PHASOR",
        "analysis_type": "NODAL",
    }, "Empedanslar ve Fazörler")
    assert "Kondansatörün empedansı" in t_only_c
    assert "Bobinin empedansı" not in t_only_c


# ─── Madde 15: Kaynak dönüşümü Vth terminalleri, çözücü jargonu ve Ra kΩ birimi ───

def test_item15_source_transform_terminals_wording_and_kohm_units(client):
    t = "\n".join(_texts(client, {
        "netlist": "V1 1 0 DC 12\nR1 1 2 4k\nR2 2 0 1k\nR3 2 3 2k" + GND,
        "mode": "DC",
        "analysis_type": "SOURCE_TRANSFORM",
        "thevenin_terminals": {"node_positive": "3", "node_negative": "0"},
    }))
    assert f"Vth = V(Düğüm 3) {MINUS} V(GND)" in t
    assert "V_AB" not in t
    assert "Doğrudan Thevenin hesabıyla aynı sonuç" in t
    assert "Çözücünün" not in t
    assert "1 kΩ·4 kΩ / (1 kΩ + 4 kΩ) = 0,8 kΩ" in t
    assert "4000·1000" not in t


# ─── Madde 16: Millman ara düğüm gerilimlerinin türetilmesi ───

def test_item16_millman_derives_inner_node_voltages(client):
    sec = _sec_text(client, {
        "netlist": "V1 1 0 DC 12\nR1 1 3 1k\nR2 3 2 2k\nR3 2 4 1k\nR4 4 0 1k\nR5 2 0 4k" + GND,
        "mode": "DC",
        "analysis_type": "MILLMAN",
    }, "Ara Düğüm Gerilimleri")
    assert "V₃ =" in sec
    assert "V₄ =" in sec


# ─── Madde 17: Referans düğüm öğrenci metninde her yerde GND olarak adlandırılır ───

def test_item17_reference_node_called_gnd_everywhere(client):
    for body in [
        {"netlist": "V1 1 0 DC 10\nR1 1 2 1k\nR2 2 0 2k" + GND,
         "mode": "DC", "analysis_type": "NODAL"},
        {"netlist": "V1 1 0 DC 10\nR1 1 2 1k\nR2 2 0 2k\nR3 2 3 1k\nI1 0 3 DC 2m" + GND,
         "mode": "DC", "analysis_type": "MESH"},
        {"netlist": "V1 1 0 DC 12\nS1 1 2 NO\nR1 2 3 2k\nC1 3 0 1u" + GND,
         "mode": "DC", "analysis_type": "TRANSIENT"},
    ]:
        all_t = "\n".join(_texts(client, body))
        assert "Düğüm 0" not in all_t


# ─── Madde 19: Geçici rejim işaret değişimi (10 V → −5 V) ve negatif katsayı yazımı ───

def test_item19_transient_sign_reversal_and_negative_coefficient(client):
    # C1 başlangıçta +10 V (V1=10V, NC anahtar t=0'da açılır), t>0'da V2=−5V kaynağa bağlanır
    net_rev = (
        "V1 1 0 DC 10\n"
        "R1 1 2 1k\n"
        "S1 2 3 NC\n"
        "V2 4 0 DC -5\n"
        "R2 4 5 1k\n"
        "S2 5 3 NO\n"
        "C1 3 0 1u" + GND
    )
    t_rev = "\n".join(_texts(client, {
        "netlist": net_rev,
        "mode": "DC",
        "analysis_type": "TRANSIENT",
    }))
    assert "önce sıfıra düşer, ardından ters yönde" in t_rev
    assert "deşarj olurken" not in t_rev

    # x(0) = 2 A, x(∞) = 3 A → katsayı (x0 - xf) = −1 A: "3 A − 1 A·e^(−t/τ)" biçimi
    net_neg = (
        "V1 1 0 DC 12\n"
        "R1 1 2 4\n"
        "R2 2 3 2\n"
        "S1 2 3 NO\n"
        "L1 3 0 2" + GND
    )
    t_neg = "\n".join(_texts(client, {
        "netlist": net_neg,
        "mode": "DC",
        "analysis_type": "TRANSIENT",
    }))
    assert f"+ ({MINUS}" not in t_neg
    assert f"3 A {MINUS} 1 A · e^({MINUS}t/τ)" in t_neg


# ─── Madde 21: LLM isteminde eleman kimlikleri en çok 24 karakterle kırpılır ───

def test_item21_llm_assistant_clips_long_element_ids():
    long_id = "R_COK_UZUN_ELEMAN_ADI_1234567890"
    net = f"V1 1 0 DC 10\n{long_id} 1 0 100" + GND
    parsed = parse_netlist(net)
    results, _, _ = solve_circuit(parsed, AnalysisMode.DC, analysis_type=AnalysisType.NODAL)
    c_txt = circuit_text(parsed, is_dc=True, frequency=None)
    d_txt = current_directions_text(parsed, results, is_dc=True)
    clipped = long_id[:24] + "…"
    assert clipped in c_txt and long_id not in c_txt
    assert clipped in d_txt and long_id not in d_txt
    assert describe_element(parsed.elements[1]).startswith(clipped)
