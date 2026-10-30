"""
Güç ve Güç Katsayısı (analysis_type = "POWER") yöntemi ve
karışık DC + AC / çok frekanslı süperpozisyon güç toplamı testleri.

Tüm beklenen değerler test içinde temel fizik/devre formülleriyle
elle (bağımsız olarak) hesaplanır; çözücü çıktısı kopyalanmaz.
"""

import math
import pytest
from fastapi.testclient import TestClient

from main import app
from models.request import AnalysisMode, AnalysisType, ValueDisplay
from parser.netlist_parser import parse_netlist
from practice.checker import check_answer
from solver.circuit_solver import solve_circuit

client = TestClient(app)


def _section_titles(resp_json: dict) -> list[str]:
    return [s["title"] for s in resp_json["results"]["explanation"]]


def _section_text(resp_json: dict, title: str) -> str:
    for s in resp_json["results"]["explanation"]:
        if s["title"] == title:
            return "\n".join(b["text"] for b in s["blocks"])
    return ""


# ═══════════════════════════════════════════════════════
#  1. STANDART ÖRNEK: 220 V ETKİN, 50 Hz, 100 + j100 Ω
# ═══════════════════════════════════════════════════════

def test_power_220v_50hz_100_plus_j100_and_compensation_095():
    """
    220 V etkin, 50 Hz, Z = 100 + j100 Ω (R1=100 Ω ve L1 seri, X_L = 100 Ω):
        |Z|² = 100² + 100² = 20000 Ω²
        I = 220 / √20000 = 220 / 141.421356... = 1.5556349... A
        P = V²·R / |Z|² = 48400 · 100 / 20000 = 242 W
        Q = V²·X / |Z|² = 48400 · 100 / 20000 = 242 VAR
        S = √(242² + 242²) = 242·√2 ≈ 342.239682 W/VA
        cos φ₁ = P / S = 1/√2 ≈ 0.70710678 (lagging, φ₁ = 45°)
    Hedef cos φ₂ = 0.95:
        φ₂ = arccos(0.95)
        Q_C = P · (tan φ₁ − tan φ₂) = 242 · (1 − tan(arccos(0.95))) ≈ 162.458498 VAR
        C = Q_C / (2π·50·220²) ≈ 10.685269 µF
        I' = P / (220 · 0.95) ≈ 1.1578947 A
    """
    v_rms = 220.0
    freq = 50.0
    omega = 2.0 * math.pi * freq
    r_val = 100.0
    x_l = 100.0
    l_val = x_l / omega
    target_pf = 0.95

    z_sq = r_val ** 2 + x_l ** 2
    p_hand = (v_rms ** 2) * r_val / z_sq
    q_hand = (v_rms ** 2) * x_l / z_sq
    s_hand = math.hypot(p_hand, q_hand)
    pf_hand = p_hand / s_hand
    phi_hand = math.degrees(math.atan2(q_hand, p_hand))
    i_before_hand = v_rms / math.sqrt(z_sq)

    phi2_rad = math.acos(target_pf)
    qc_hand = p_hand * ((q_hand / p_hand) - math.tan(phi2_rad))
    c_hand = qc_hand / (omega * (v_rms ** 2))
    i_after_hand = p_hand / (v_rms * target_pf)

    netlist = (
        f"V1 1 0 SINE(0 {v_rms} {freq} 0 0 0) RMS\n"
        f"R1 1 2 {r_val}\n"
        f"L1 2 0 {l_val:.12g}\n"
        "* GND1 - Referans toprak"
    )
    resp = client.post("/analyze", json={
        "netlist": netlist,
        "mode": "AC_PHASOR",
        "frequency": freq,
        "analysis_type": "POWER",
        "value_display": "RMS",
        "power_factor_target": target_pf,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["analysis_type"] == "POWER"

    ps = data["power_summary"]
    assert ps is not None
    assert ps["p"] == pytest.approx(p_hand, rel=1e-6)
    assert ps["q"] == pytest.approx(q_hand, rel=1e-6)
    assert ps["s"] == pytest.approx(s_hand, rel=1e-6)
    assert ps["pf"] == pytest.approx(pf_hand, rel=1e-5)
    assert ps["pf_type"] == "lagging"
    assert ps["phi_deg"] == pytest.approx(phi_hand, rel=1e-4)

    comp = ps["compensation"]
    assert comp is not None
    assert comp["applied"] is True
    assert comp["reason"] is None
    assert comp["target_pf"] == pytest.approx(target_pf)
    assert comp["q_c"] == pytest.approx(qc_hand, rel=1e-6)
    assert comp["c"] == pytest.approx(c_hand, rel=1e-6)
    assert comp["i_before"] == pytest.approx(i_before_hand, rel=1e-6)
    assert comp["i_after"] == pytest.approx(i_after_hand, rel=1e-6)

    # Anlatım sırası kontrolü
    titles = _section_titles(data)
    assert titles[0] == "Devreyi Tanıyalım"
    assert "Empedanslar ve Fazörler" in titles
    assert "Eleman Akımları (Ohm Yasası)" in titles
    idx_guc = titles.index("Güç Hesabı")
    idx_ucgen = titles.index("Güç Üçgeni")
    idx_komp = titles.index("Kompanzasyon")
    idx_kontrol = titles.index("Kontrol")
    idx_sonuc = titles.index("Sonuç")
    assert idx_guc < idx_ucgen < idx_komp < idx_kontrol < idx_sonuc

    ucgen_txt = _section_text(data, "Güç Üçgeni")
    assert "V·I·cos φ" in ucgen_txt
    assert "V·I·sin φ" in ucgen_txt
    assert "S = V·I" in ucgen_txt
    assert "geri (endüktif)" in ucgen_txt

    kontrol_txt = _section_text(data, "Kontrol")
    assert "✓" in kontrol_txt
    assert "doğrulandı" in kontrol_txt


def test_compensated_circuit_resolved_with_solver_matches_target_pf():
    """
    Hesaplanan C kondansatörünü netlist'e kaynağa paralel olarak ekleyip
    çözücüyle ayrıca çözdüğümüzde yeni cos φ₂ = 0.95 ve kaynak akımı I' doğrulanmalı.
    """
    v_rms = 220.0
    freq = 50.0
    omega = 2.0 * math.pi * freq
    l_val = 100.0 / omega
    target_pf = 0.95

    base_netlist = (
        f"V1 1 0 SINE(0 {v_rms} {freq} 0 0 0) RMS\n"
        f"R1 1 2 100\n"
        f"L1 2 0 {l_val:.12g}\n"
        "* GND1 - Referans toprak"
    )
    parsed_base = parse_netlist(base_netlist, value_basis="RMS")
    res_base, _, errs_base = solve_circuit(
        parsed=parsed_base,
        mode=AnalysisMode.AC_PHASOR,
        frequency=freq,
        analysis_type=AnalysisType.POWER,
        power_factor_target=target_pf,
    )
    assert not errs_base
    comp = res_base.power_summary.compensation
    assert comp is not None and comp.applied is True

    # Şimdi bulunan C'yi kaynağa paralel ekleyip bağımsız olarak çözelim
    comp_netlist = base_netlist + f"\nC_PAR 1 0 {comp.c:.12g}"
    parsed_comp = parse_netlist(comp_netlist, value_basis="RMS")
    res_comp, _, errs_comp = solve_circuit(
        parsed=parsed_comp,
        mode=AnalysisMode.AC_PHASOR,
        frequency=freq,
        analysis_type=AnalysisType.POWER,
    )
    assert not errs_comp
    ps_after = res_comp.power_summary
    assert ps_after is not None
    # Aktif güç değişmemeli, cos φ = 0.95 olmalı, kaynak akımı i_after olmalı
    assert ps_after.p == pytest.approx(242.0, rel=1e-6)
    assert ps_after.pf == pytest.approx(target_pf, rel=1e-5)
    i_v1_after = res_comp.element_currents["V1"].value.magnitude
    assert i_v1_after == pytest.approx(comp.i_after, rel=1e-5)


# ═══════════════════════════════════════════════════════
#  2. LAGGING / LEADING / UNITY VE HEDEF 1.0
# ═══════════════════════════════════════════════════════

def test_power_leading_and_unity_pf_types():
    """
    Kapasitif devre → pf_type = 'leading', φ < 0.
    Saf dirençli devre → pf_type = 'unity', φ = 0, cos φ = 1.
    """
    # Kapasitif: 100 V etkin, 50 Hz, R = 60 Ω, X_C = 80 Ω (|Z| = 100 Ω)
    freq = 50.0
    omega = 2.0 * math.pi * freq
    c_val = 1.0 / (omega * 80.0)
    net_cap = f"V1 1 0 AC_PHASOR(100, 0) RMS\nR1 1 2 60\nC1 2 0 {c_val:.12g}\n* GND1 - Referans toprak"
    res_cap, _, _ = solve_circuit(
        parse_netlist(net_cap, value_basis="RMS"),
        mode=AnalysisMode.AC_PHASOR,
        frequency=freq,
        analysis_type=AnalysisType.POWER,
    )
    ps_cap = res_cap.power_summary
    assert ps_cap is not None
    # I = 100 / 100 = 1 A → P = 60 W, Q = -80 VAR, S = 100 VA, cos φ = 0.6 leading
    assert ps_cap.p == pytest.approx(60.0, rel=1e-6)
    assert ps_cap.q == pytest.approx(-80.0, rel=1e-6)
    assert ps_cap.s == pytest.approx(100.0, rel=1e-6)
    assert ps_cap.pf == pytest.approx(0.6, rel=1e-6)
    assert ps_cap.pf_type == "leading"
    assert ps_cap.phi_deg == pytest.approx(-math.degrees(math.atan2(80.0, 60.0)), rel=1e-4)
    assert ps_cap.compensation is None

    # Saf direnç: 100 V etkin, R = 50 Ω → P = 200 W, Q = 0, S = 200 VA, cos φ = 1 unity
    net_res = "V1 1 0 AC_PHASOR(100, 0) RMS\nR1 1 0 50\n* GND1 - Referans toprak"
    res_unity, _, _ = solve_circuit(
        parse_netlist(net_res, value_basis="RMS"),
        mode=AnalysisMode.AC_PHASOR,
        frequency=freq,
        analysis_type=AnalysisType.POWER,
    )
    ps_u = res_unity.power_summary
    assert ps_u is not None
    assert ps_u.p == pytest.approx(200.0, rel=1e-6)
    assert ps_u.q == pytest.approx(0.0, abs=1e-9)
    assert ps_u.s == pytest.approx(200.0, rel=1e-6)
    assert ps_u.pf == pytest.approx(1.0, rel=1e-6)
    assert ps_u.pf_type == "unity"
    assert ps_u.phi_deg == pytest.approx(0.0, abs=1e-6)


def test_power_compensation_target_unity_1_0():
    """
    Hedef cos φ₂ = 1.0 (tam kompanzasyon):
    tan φ₂ = 0 → Q_C = Q = 242 VAR, I' = P / V = 242 / 220 = 1.1 A.
    """
    v_rms = 220.0
    freq = 50.0
    omega = 2.0 * math.pi * freq
    l_val = 100.0 / omega
    netlist = f"V1 1 0 SINE(0 {v_rms} {freq} 0 0 0) RMS\nR1 1 2 100\nL1 2 0 {l_val:.12g}\n* GND1 - Referans toprak"

    res, _, _ = solve_circuit(
        parse_netlist(netlist, value_basis="RMS"),
        mode=AnalysisMode.AC_PHASOR,
        frequency=freq,
        analysis_type=AnalysisType.POWER,
        power_factor_target=1.0,
    )
    comp = res.power_summary.compensation
    assert comp is not None
    assert comp.applied is True
    assert comp.q_c == pytest.approx(242.0, rel=1e-6)
    assert comp.c == pytest.approx(242.0 / (omega * v_rms ** 2), rel=1e-6)
    assert comp.i_after == pytest.approx(242.0 / v_rms, rel=1e-6)


# ═══════════════════════════════════════════════════════
#  3. KOMPANZASYONUN UYGULANAMADIĞI DURUMLAR
# ═══════════════════════════════════════════════════════

def test_compensation_not_applied_when_target_lower_or_equal():
    """Mevcut cos φ = 0.8 iken hedef 0.75 veya 0.8 verilirse applied=False."""
    freq = 50.0
    omega = 2.0 * math.pi * freq
    # R = 80 Ω, X_L = 60 Ω → cos φ = 0.8
    l_val = 60.0 / omega
    netlist = f"V1 1 0 AC_PHASOR(100, 0) RMS\nR1 1 2 80\nL1 2 0 {l_val:.12g}\n* GND1 - Referans toprak"

    res, _, _ = solve_circuit(
        parse_netlist(netlist, value_basis="RMS"),
        mode=AnalysisMode.AC_PHASOR,
        frequency=freq,
        analysis_type=AnalysisType.POWER,
        power_factor_target=0.75,
    )
    ps = res.power_summary
    assert ps is not None
    assert ps.pf == pytest.approx(0.8, rel=1e-5)
    assert ps.compensation is not None
    assert ps.compensation.applied is False
    assert ps.compensation.c is None
    assert ps.compensation.q_c is None
    assert ps.compensation.reason and "zaten" in ps.compensation.reason.lower()


def test_compensation_not_applied_for_capacitive_or_unity_circuit():
    """İleri (kapasitif) ya da birim güç katsayılı devrede kondansatör eklenmez."""
    freq = 50.0
    omega = 2.0 * math.pi * freq
    c_val = 1.0 / (omega * 80.0)
    net_cap = f"V1 1 0 AC_PHASOR(100, 0) RMS\nR1 1 2 60\nC1 2 0 {c_val:.12g}\n* GND1 - Referans toprak"
    res_cap, _, _ = solve_circuit(
        parse_netlist(net_cap, value_basis="RMS"),
        mode=AnalysisMode.AC_PHASOR,
        frequency=freq,
        analysis_type=AnalysisType.POWER,
        power_factor_target=0.95,
    )
    comp_cap = res_cap.power_summary.compensation
    assert comp_cap is not None
    assert comp_cap.applied is False
    assert comp_cap.c is None
    assert "kapasitif" in comp_cap.reason.lower()

    net_u = "V1 1 0 AC_PHASOR(100, 0) RMS\nR1 1 0 50\n* GND1 - Referans toprak"
    res_u, _, _ = solve_circuit(
        parse_netlist(net_u, value_basis="RMS"),
        mode=AnalysisMode.AC_PHASOR,
        frequency=freq,
        analysis_type=AnalysisType.POWER,
        power_factor_target=0.95,
    )
    comp_u = res_u.power_summary.compensation
    assert comp_u is not None
    assert comp_u.applied is False
    assert "birim" in comp_u.reason.lower()


def test_compensation_not_applied_for_two_sources_or_current_source():
    """İki kaynaklı devrede veya akım kaynaklı devrede applied=False, güç hesabı yine yapılır."""
    freq = 50.0
    omega = 2.0 * math.pi * freq
    l_val = 100.0 / omega

    # İki gerilim kaynağı
    net_two = (
        f"V1 1 0 AC_PHASOR(100, 0) RMS\n"
        f"V2 3 0 AC_PHASOR(50, 0) RMS\n"
        f"R1 1 2 100\n"
        f"L1 2 3 {l_val:.12g}\n"
        "* GND1 - Referans toprak"
    )
    res_two, _, _ = solve_circuit(
        parse_netlist(net_two, value_basis="RMS"),
        mode=AnalysisMode.AC_PHASOR,
        frequency=freq,
        analysis_type=AnalysisType.POWER,
        power_factor_target=0.95,
    )
    assert res_two.power_summary is not None
    assert res_two.power_summary.p > 0
    assert res_two.power_summary.compensation.applied is False
    assert "kaynak" in res_two.power_summary.compensation.reason.lower()

    # Akım kaynağı
    net_isrc = f"I1 0 1 AC_PHASOR(2, 0) RMS\nR1 1 2 50\nL1 2 0 {l_val:.12g}\n* GND1 - Referans toprak"
    res_isrc, _, _ = solve_circuit(
        parse_netlist(net_isrc, value_basis="RMS"),
        mode=AnalysisMode.AC_PHASOR,
        frequency=freq,
        analysis_type=AnalysisType.POWER,
        power_factor_target=0.95,
    )
    assert res_isrc.power_summary is not None
    assert res_isrc.power_summary.p == pytest.approx(4.0 * 50.0, rel=1e-6)
    assert res_isrc.power_summary.compensation.applied is False
    assert "akım kaynağı" in res_isrc.power_summary.compensation.reason.lower()


def test_compensation_not_applied_when_frequency_unknown():
    """Frekanssız fazör devresinde (R + Z, frequency=None) güç bulunur ama C hesaplanamaz."""
    netlist = "V1 1 0 AC_PHASOR(100, 0) RMS\nZ1 1 0 COMPLEX(60, 80)\n* GND1 - Referans toprak"
    res, _, errs = solve_circuit(
        parse_netlist(netlist, value_basis="RMS"),
        mode=AnalysisMode.AC_PHASOR,
        frequency=None,
        analysis_type=AnalysisType.POWER,
        power_factor_target=0.95,
    )
    assert not errs
    ps = res.power_summary
    assert ps is not None
    assert ps.p == pytest.approx(60.0, rel=1e-6)
    assert ps.q == pytest.approx(80.0, rel=1e-6)
    assert ps.s == pytest.approx(100.0, rel=1e-6)
    assert ps.pf == pytest.approx(0.6, rel=1e-6)
    assert ps.compensation is not None
    assert ps.compensation.applied is False
    assert ps.compensation.c is None
    assert "frekans" in ps.compensation.reason.lower()


# ═══════════════════════════════════════════════════════
#  4. TEPE (PEAK) GÖSTERİMİ: AYNI P, Q, S, Q_C, C; AKIMLAR √2 KAT
# ═══════════════════════════════════════════════════════

def test_power_peak_display_same_c_and_p_with_vm_conversion_line():
    """
    Tepe gösterimde P, Q, S, cos φ, Q_C ve C etkin gösterimle birebir aynı çıkar;
    yalnız i_before ve i_after tepe değerdir (Im = √2·I).
    Anlatımda 'V = Vm/√2' ve 'Im' = √2·I'' satırları yer alır.
    """
    v_rms = 220.0
    freq = 50.0
    omega = 2.0 * math.pi * freq
    l_val = 100.0 / omega
    target_pf = 0.95
    netlist = f"V1 1 0 SINE(0 {v_rms} {freq} 0 0 0) RMS\nR1 1 2 100\nL1 2 0 {l_val:.12g}\n* GND1 - Referans toprak"

    resp_rms = client.post("/analyze", json={
        "netlist": netlist,
        "mode": "AC_PHASOR",
        "frequency": freq,
        "analysis_type": "POWER",
        "value_display": "RMS",
        "power_factor_target": target_pf,
    }).json()

    resp_peak = client.post("/analyze", json={
        "netlist": netlist,
        "mode": "AC_PHASOR",
        "frequency": freq,
        "analysis_type": "POWER",
        "value_display": "PEAK",
        "power_factor_target": target_pf,
    }).json()

    ps_rms = resp_rms["power_summary"]
    ps_peak = resp_peak["power_summary"]

    assert ps_peak["p"] == pytest.approx(ps_rms["p"], rel=1e-6)
    assert ps_peak["q"] == pytest.approx(ps_rms["q"], rel=1e-6)
    assert ps_peak["s"] == pytest.approx(ps_rms["s"], rel=1e-6)
    assert ps_peak["pf"] == pytest.approx(ps_rms["pf"], rel=1e-6)
    assert ps_peak["compensation"]["q_c"] == pytest.approx(ps_rms["compensation"]["q_c"], rel=1e-6)
    assert ps_peak["compensation"]["c"] == pytest.approx(ps_rms["compensation"]["c"], rel=1e-6)

    assert ps_peak["compensation"]["i_before"] == pytest.approx(
        ps_rms["compensation"]["i_before"] * math.sqrt(2.0), rel=1e-6
    )
    assert ps_peak["compensation"]["i_after"] == pytest.approx(
        ps_rms["compensation"]["i_after"] * math.sqrt(2.0), rel=1e-6
    )

    komp_txt = _section_text(resp_peak, "Kompanzasyon")
    assert "V = Vm/√2" in komp_txt
    assert "Im' = √2·I'" in komp_txt


# ═══════════════════════════════════════════════════════
#  5. DC FALLBACK, FARKLI FREKANS FALLBACK VE DOĞRULAMA HATASI
# ═══════════════════════════════════════════════════════

def test_power_dc_fallback_and_multifreq_fallback():
    """
    DC modda ve farklı frekanslı devrede POWER uygulanamaz:
    power_summary = None, Türkçe sebep notu ve normal düğüm gerilimleri anlatımı.
    """
    resp_dc = client.post("/analyze", json={
        "netlist": "V1 1 0 DC 12\nR1 1 2 4\nR2 2 0 8\n* GND1 - Referans toprak",
        "mode": "DC",
        "analysis_type": "POWER",
    })
    assert resp_dc.status_code == 200
    d_dc = resp_dc.json()
    assert d_dc["power_summary"] is None
    assert d_dc["results"]["node_voltages"]["2"]["value"] == pytest.approx(8.0, rel=1e-6)
    titles_dc = _section_titles(d_dc)
    assert "Güç ve Güç Katsayısı" in titles_dc
    assert "Düğüm Denklemleri (KCL)" in titles_dc
    note_dc = _section_text(d_dc, "Güç ve Güç Katsayısı")
    assert "uygulanamadı" in note_dc.lower()
    assert "Düğüm Gerilimleri" in note_dc

    # Farklı iki frekanslı kaynak (50 Hz ve 150 Hz)
    resp_mf = client.post("/analyze", json={
        "netlist": (
            "V1 1 0 SINE(0 100 50 0 0 0) RMS\n"
            "V2 2 1 SINE(0 20 150 0 0 0) RMS\n"
            "R1 2 0 50\n"
            "* GND1 - Referans toprak"
        ),
        "mode": "AC_TIME",
        "frequency": 50.0,
        "analysis_type": "POWER",
        "value_display": "RMS",
    })
    assert resp_mf.status_code == 200
    d_mf = resp_mf.json()
    assert d_mf["power_summary"] is None
    assert any("farklı frekans" in w.lower() for w in d_mf["warnings"])
    note_mf = _section_text(d_mf, "Güç ve Güç Katsayısı")
    assert "farklı frekans" in note_mf.lower()


@pytest.mark.parametrize("bad_target", [0.0, -0.5, 1.05, 2.0])
def test_power_factor_target_out_of_range_validation(bad_target):
    """0 < power_factor_target <= 1 dışı değerler Türkçe doğrulama hatası döndürür."""
    resp = client.post("/analyze", json={
        "netlist": "V1 1 0 AC_PHASOR(100, 0)\nR1 1 0 50\n* GND1 - Referans toprak",
        "mode": "AC_PHASOR",
        "frequency": 50.0,
        "analysis_type": "POWER",
        "power_factor_target": bad_target,
    })
    assert resp.status_code == 422
    assert "power_factor_target" in resp.text or "güç katsayısı" in resp.text.lower()


# ═══════════════════════════════════════════════════════
#  6. ALIŞTIRMA SORULARI VE BİRİM / ETKİN-TEPE TEŞHİSİ
# ═══════════════════════════════════════════════════════

def test_power_practice_questions_and_checker():
    """
    POWER yönteminde P (W), Q (VAR), S (VA), cos φ (birimsiz) ve hedef verildiyse
    Q_C (VAR), C (F) soruları üretilir; birim denetimi ve tepe/etkin teşhisi çalışır.
    """
    v_rms = 220.0
    freq = 50.0
    omega = 2.0 * math.pi * freq
    l_val = 100.0 / omega
    netlist = f"V1 1 0 SINE(0 {v_rms} {freq} 0 0 0) RMS\nR1 1 2 100\nL1 2 0 {l_val:.12g}\n* GND1 - Referans toprak"

    parsed = parse_netlist(netlist, value_basis="RMS")
    res, _, _ = solve_circuit(
        parsed=parsed,
        mode=AnalysisMode.AC_PHASOR,
        frequency=freq,
        analysis_type=AnalysisType.POWER,
        power_factor_target=0.95,
    )
    by_id = {q.id: q for q in res.practice}
    assert set(by_id.keys()) == {"P_TOTAL", "Q_TOTAL", "S_TOTAL", "COS_PHI", "Q_C", "C_COMP"}
    assert by_id["P_TOTAL"].unit == "W"
    assert by_id["Q_TOTAL"].unit == "VAR"
    assert by_id["S_TOTAL"].unit == "VA"
    assert by_id["COS_PHI"].unit == ""
    assert by_id["Q_C"].unit == "VAR"
    assert by_id["C_COMP"].unit == "F"

    # Doğru cevaplar
    assert check_answer(by_id["P_TOTAL"], "242 W").status == "correct"
    assert check_answer(by_id["Q_TOTAL"], "242 VAR").status == "correct"
    assert check_answer(by_id["S_TOTAL"], "342,24 VA").status == "correct"
    assert check_answer(by_id["COS_PHI"], "0,7071").status == "correct"
    assert check_answer(by_id["Q_C"], "162,46 VAR").status == "correct"
    assert check_answer(by_id["C_COMP"], "10,69 uF").status == "correct"

    # Birim hataları: sayı doğru ama birim yanlış → partial
    v_p_unit = check_answer(by_id["P_TOTAL"], "242 VA")
    assert v_p_unit.status == "partial"
    assert "watt" in v_p_unit.message.lower()

    v_pf_unit = check_answer(by_id["COS_PHI"], "0,7071 W")
    assert v_pf_unit.status == "partial"
    assert "birimsiz" in v_pf_unit.message.lower()

    # Etkin/tepe (½ çarpanı) hatası teşhisi
    v_half = check_answer(by_id["P_TOTAL"], "121 W")
    assert v_half.status == "wrong"
    assert "etkin" in v_half.message.lower() or "½" in v_half.message


# ═══════════════════════════════════════════════════════
#  7. KARIŞIK DC + AC VE ÇOK FREKANSLI SÜPERPOZİSYON GÜÇ DÜZELTMESESİ
# ═══════════════════════════════════════════════════════

def test_mixed_dc_ac_superposition_total_power_is_101w():
    """
    V1 1 0 DC 10, V2 2 1 SINE(0 100 50 0 0 0) RMS, R1 2 0 100,
    SUPERPOSITION, value_display RMS:
        AC 100 V etkin → P_AC = 100² / 100 = 100 W
        DC 10 V        → P_DC = 10² / 100  = 1 W
        Toplam P = 101 W (V1 1 W verir, V2 100 W verir, R1 101 W çeker).
    """
    netlist = (
        "V1 1 0 DC 10\n"
        "V2 2 1 SINE(0 100 50 0 0 0) RMS\n"
        "R1 2 0 100\n"
        "* GND1 - Referans toprak"
    )
    resp = client.post("/analyze", json={
        "netlist": netlist,
        "mode": "AC_TIME",
        "frequency": 50.0,
        "analysis_type": "SUPERPOSITION",
        "value_display": "RMS",
    })
    assert resp.status_code == 200
    pw = resp.json()["results"]["power"]
    assert pw is not None
    assert pw["total_supplied"]["real"] == pytest.approx(101.0, rel=1e-6)
    assert pw["total_absorbed"]["real"] == pytest.approx(101.0, rel=1e-6)
    assert pw["elements"]["R1"]["active_power"] == pytest.approx(101.0, rel=1e-6)
    assert pw["elements"]["V1"]["active_power"] == pytest.approx(-1.0, rel=1e-6)
    assert pw["elements"]["V2"]["active_power"] == pytest.approx(-100.0, rel=1e-6)
    assert pw["balance_error"] == pytest.approx(0.0, abs=1e-9)


def test_two_different_ac_frequencies_superposition_total_power():
    """
    Farklı iki AC frekansı (50 Hz 100 V etkin ve 150 Hz 20 V etkin) seri bağlı, R1 = 100 Ω:
        P(50 Hz)  = 100² / 100 = 100 W
        P(150 Hz) = 20² / 100  = 4 W
        Toplam P = 104 W (dikgen frekansların güçleri toplanır, fazörleri toplanmaz).
    """
    netlist = (
        "V1 1 0 SINE(0 100 50 0 0 0) RMS\n"
        "V2 2 1 SINE(0 20 150 0 0 0) RMS\n"
        "R1 2 0 100\n"
        "* GND1 - Referans toprak"
    )
    resp = client.post("/analyze", json={
        "netlist": netlist,
        "mode": "AC_TIME",
        "frequency": 50.0,
        "analysis_type": "SUPERPOSITION",
        "value_display": "RMS",
    })
    assert resp.status_code == 200
    pw = resp.json()["results"]["power"]
    assert pw is not None
    assert pw["total_supplied"]["real"] == pytest.approx(104.0, rel=1e-6)
    assert pw["total_absorbed"]["real"] == pytest.approx(104.0, rel=1e-6)
    assert pw["elements"]["R1"]["active_power"] == pytest.approx(104.0, rel=1e-6)
    assert pw["balance_error"] == pytest.approx(0.0, abs=1e-9)
