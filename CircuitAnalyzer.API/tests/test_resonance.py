"""
Rezonans (analysis_type = "RESONANCE") yöntemi testleri — seri ve paralel RLC.

Tüm beklenen değerler test içinde temel devre formülleriyle ELLE hesaplanır;
çözücü çıktısı kopyalanmaz.

Ana örnek: L = 10 mH, C = 1 µF
    ω₀ = 1/√(LC) = 1/√(1e-8) = 10000 rad/s
    f₀ = ω₀/(2π) = 1591,549 Hz
    X  = ω₀L = 10000 · 0,01 = 100 Ω  ( = 1/(ω₀C) = 1/(10000 · 1e-6) = 100 Ω )
Seri  (V = 10 V, R = 10 Ω):  Q = X/R = 10, BW = f₀/Q = 159,155 Hz, I_max = V/R = 1 A, V_L = V_C = Q·V = 100 V
Paralel (R = 1 kΩ):          Q = R/X = 10, Z₀ = R = 1000 Ω
Tam yarım güç: f₁,₂ = √(f₀² + (BW/2)²) ∓ BW/2
"""

import math

import pytest
from fastapi.testclient import TestClient

from main import app
from models.response import PracticeQuestion
from parser.netlist_parser import parse_netlist
from practice.answer_parser import parse_answer
from practice.checker import check_answer
from solver.resonance import ResonanceNotApplicable, analyze_resonance

client = TestClient(app)

L_VAL = 10e-3
C_VAL = 1e-6
W0 = 1.0 / math.sqrt(L_VAL * C_VAL)          # 10000 rad/s
F0 = W0 / (2.0 * math.pi)                     # 1591,549 Hz
X0 = W0 * L_VAL                               # 100 Ω
GND = "\n* GND1 - Referans toprak"

SERIES = "V1 1 0 SINE(0 10 50 0 0 0)\nR1 1 2 10\nL1 2 3 10m\nC1 3 0 1u" + GND
SERIES_PHASOR = "V1 1 0 AC_PHASOR(10, 0)\nR1 1 2 10\nL1 2 3 10m\nC1 3 0 1u" + GND
PARALLEL_V = "V1 1 0 AC_PHASOR(10, 0)\nR1 1 0 1k\nL1 1 0 10m\nC1 1 0 1u" + GND
PARALLEL_I = "I1 0 1 AC_PHASOR(0.01, 0)\nR1 1 0 1k\nL1 1 0 10m\nC1 1 0 1u" + GND


def _post(netlist: str, mode: str = "AC_PHASOR", **extra):
    body = {"netlist": netlist, "mode": mode, "analysis_type": "RESONANCE"}
    body.update(extra)
    return client.post("/analyze", json=body)


def _ok(netlist: str, **extra) -> dict:
    resp = _post(netlist, **extra)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _titles(data: dict) -> list:
    return [s["title"] for s in data["results"]["explanation"]]


def _text(data: dict, title: str) -> str:
    for s in data["results"]["explanation"]:
        if s["title"] == title:
            return "\n".join(b["text"] for b in s["blocks"])
    return ""


def _half_power(f0: float, bw: float):
    root = math.sqrt(f0 ** 2 + (bw / 2.0) ** 2)
    return root - bw / 2.0, root + bw / 2.0


def _z_series(f: float, r: float) -> complex:
    w = 2.0 * math.pi * f
    return complex(r, w * L_VAL - 1.0 / (w * C_VAL))


def _z_parallel(f: float, r: float) -> complex:
    w = 2.0 * math.pi * f
    return 1.0 / complex(1.0 / r, w * C_VAL - 1.0 / (w * L_VAL))


# ═══════════════════════════════════════════════════════
#  1. SERİ RLC
# ═══════════════════════════════════════════════════════

def test_series_rlc_hand_values_and_section_order():
    data = _ok(SERIES, frequency=50.0)
    assert data["status"] == "success"
    assert data["errors"] == [] and data["warnings"] == []
    assert data["analysis_type"] == "RESONANCE"
    rs = data["resonance"]
    assert rs["kind"] == "series"

    bw = F0 / 10.0
    f1e, f2e = _half_power(F0, bw)
    assert rs["w0"] == pytest.approx(10000.0, rel=1e-9)
    assert rs["f0"] == pytest.approx(1591.549431, rel=1e-8)
    assert rs["x"] == pytest.approx(100.0, rel=1e-9)
    assert rs["q"] == pytest.approx(10.0, rel=1e-9)
    assert rs["bw"] == pytest.approx(159.1549431, rel=1e-8)
    assert rs["f1"] == pytest.approx(F0 - bw / 2.0, rel=1e-9)
    assert rs["f2"] == pytest.approx(F0 + bw / 2.0, rel=1e-9)
    assert rs["f1_exact"] == pytest.approx(f1e, rel=1e-9)
    assert rs["f2_exact"] == pytest.approx(f2e, rel=1e-9)
    assert rs["f2_exact"] - rs["f1_exact"] == pytest.approx(rs["bw"], rel=1e-8)
    assert rs["z0"] == pytest.approx(10.0, rel=1e-9)
    assert rs["i0"] == pytest.approx(1.0, rel=1e-9)          # V/R = 10/10
    assert rs["v0"] == pytest.approx(100.0, rel=1e-9)        # Q·V = 10 · 10

    titles = _titles(data)
    expected = ["Devreyi Tanıyalım", "Rezonans Koşulu", "Rezonans Frekansı", "Reaktanslar",
                "Rezonansta Empedans ve Akım", "Kalite Faktörü Q", "Bant Genişliği",
                "Eleman Gerilimleri", "Kontrol", "Sonuç"]
    assert titles == expected

    # sayılar anlatımda ondalık virgülle
    assert "f₀ = ω₀/(2π)" in _text(data, "Rezonans Frekansı")
    assert "10000 rad/s" in _text(data, "Rezonans Frekansı")
    assert "1,592 kHz" in _text(data, "Rezonans Frekansı")
    assert "159,2 Hz" in _text(data, "Bant Genişliği")
    assert "Q = X / R = 100 Ω / 10 Ω = 10" in _text(data, "Kalite Faktörü Q")
    assert "I_max = V / Z₀ = V / R = 10 V / 10 Ω = 1 A" in _text(data, "Rezonansta Empedans ve Akım")
    assert "U ile de gösterilir" in _text(data, "Rezonansta Empedans ve Akım")
    assert "V_L = V_C = Q · V = 10 · 10 V = 100 V" in _text(data, "Eleman Gerilimleri")
    kontrol = _text(data, "Kontrol")
    assert kontrol.count("✓") >= 4
    assert "f₂ − f₁" in kontrol


def test_series_results_are_solved_at_f0():
    """Düğüm gerilimleri kaynak frekansında (50 Hz) değil f₀'da çözülür."""
    data = _ok(SERIES, frequency=50.0)
    nv = data["results"]["node_voltages"]
    # I = 1∠0° A ; V_C (düğüm 3) = I · (−j100) = 100∠−90° V ; V_2 = 10 − 1·10 = 0 V
    v3 = nv["3"]["value"]
    assert v3["magnitude"] == pytest.approx(100.0, rel=1e-6)
    assert v3["phase_degrees"] == pytest.approx(-90.0, abs=1e-3)
    assert nv["2"]["value"] == pytest.approx(0.0, abs=1e-9)          # gerçel sonuç düz sayı döner
    assert nv["1"]["value"] == pytest.approx(10.0, rel=1e-6)
    # akım kaynakla aynı fazda (gerçel): I_R1 = 1 A
    assert data["results"]["element_currents"]["R1"]["value"] == pytest.approx(1.0, rel=1e-6)


def test_series_two_resistors_are_added_and_low_q_note():
    net = ("V1 1 0 SINE(0 10 50 0 0 0)\nR1 1 2 10\nR2 2 3 5\nL1 3 4 10m\nC1 4 0 1u" + GND)
    data = _ok(net, frequency=50.0)
    rs = data["resonance"]
    r = 15.0
    q = X0 / r                               # 6,6667
    bw = F0 / q
    f1e, f2e = _half_power(F0, bw)
    assert rs["z0"] == pytest.approx(15.0, rel=1e-9)
    assert rs["q"] == pytest.approx(q, rel=1e-9)
    assert rs["bw"] == pytest.approx(bw, rel=1e-9)
    assert rs["i0"] == pytest.approx(10.0 / 15.0, rel=1e-9)
    assert rs["v0"] == pytest.approx(q * 10.0, rel=1e-9)
    assert rs["f0"] == pytest.approx(F0, rel=1e-8)          # R f₀'ı değiştirmez
    assert rs["f1_exact"] == pytest.approx(f1e, rel=1e-9)
    assert "R = R1 + R2 = 10 Ω + 5 Ω = 15 Ω" in _text(data, "Rezonans Koşulu")
    bw_txt = _text(data, "Bant Genişliği")
    assert "Q küçük olduğundan kitaptaki f₀ ∓ BW/2 yaklaşıktır; tam değerler f₁ = " in bw_txt


def test_series_low_q_exact_vs_book_half_power():
    """R = 100 Ω → Q = 1, BW = f₀: kitap f₁,₂ = 0,5·f₀ ve 1,5·f₀; tam değerler altın oran."""
    net = "V1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nL1 2 3 10m\nC1 3 0 1u" + GND
    data = _ok(net)
    rs = data["resonance"]
    assert rs["q"] == pytest.approx(1.0, rel=1e-9)
    assert rs["bw"] == pytest.approx(F0, rel=1e-8)
    assert rs["f1"] == pytest.approx(0.5 * F0, rel=1e-8)
    assert rs["f2"] == pytest.approx(1.5 * F0, rel=1e-8)
    golden = math.sqrt(1.25)
    assert rs["f1_exact"] == pytest.approx((golden - 0.5) * F0, rel=1e-8)
    assert rs["f2_exact"] == pytest.approx((golden + 0.5) * F0, rel=1e-8)
    assert rs["f2_exact"] - rs["f1_exact"] == pytest.approx(rs["bw"], rel=1e-8)
    # Q küçük olduğu için Kontrol tam değerlerde yapılır: |I| = I_max/√2
    i_half = 0.1 / math.sqrt(2.0)
    assert abs(_z_series(rs["f1_exact"], 100.0)) == pytest.approx(100.0 * math.sqrt(2.0), rel=1e-8)
    assert 10.0 / abs(_z_series(rs["f2_exact"], 100.0)) == pytest.approx(i_half, rel=1e-8)
    assert "tam değerler f₁ = 983,6 Hz, f₂ = 2,575 kHz" in _text(data, "Bant Genişliği")


def test_high_q_has_no_low_q_note():
    net = "V1 1 0 AC_PHASOR(10, 0)\nR1 1 2 1\nL1 2 3 10m\nC1 3 0 1u" + GND
    data = _ok(net)
    assert data["resonance"]["q"] == pytest.approx(100.0, rel=1e-9)
    assert "Q küçük olduğundan" not in _text(data, "Bant Genişliği")


# ═══════════════════════════════════════════════════════
#  2. PARALEL RLC
# ═══════════════════════════════════════════════════════

def test_parallel_rlc_voltage_source():
    data = _ok(PARALLEL_V)
    assert data["status"] == "success"
    rs = data["resonance"]
    assert rs["kind"] == "parallel"
    assert rs["f0"] == pytest.approx(F0, rel=1e-8)
    assert rs["x"] == pytest.approx(100.0, rel=1e-9)
    assert rs["q"] == pytest.approx(10.0, rel=1e-9)           # R/X = 1000/100
    assert rs["z0"] == pytest.approx(1000.0, rel=1e-9)
    assert rs["bw"] == pytest.approx(F0 / 10.0, rel=1e-8)
    assert rs["i0"] == pytest.approx(0.01, rel=1e-9)          # I_min = V/R = 10/1000
    assert rs["v0"] == pytest.approx(10.0, rel=1e-9)          # L ve C üzerindeki gerilim = V
    assert _titles(data) == [
        "Devreyi Tanıyalım", "Rezonans Koşulu", "Rezonans Frekansı", "Reaktanslar",
        "Rezonansta Empedans ve Akım", "Kalite Faktörü Q", "Bant Genişliği",
        "Eleman Akımları", "Kontrol", "Sonuç"]
    assert "Q = R / X = 1 kΩ / 100 Ω = 10" in _text(data, "Kalite Faktörü Q")
    assert "I_min = V / Z₀ = V / R = 10 V / 1 kΩ = 10 mA" in _text(data, "Rezonansta Empedans ve Akım")
    # I_L = I_C = Q·I_R = 10 · 10 mA = 100 mA
    assert "I_L = I_C = Q · I_R = 10 · 10 mA = 100 mA" in _text(data, "Eleman Akımları")
    # R/√2 = 707,1 Ω tam yarım güç frekanslarında doğrulanır
    assert "R/√2 = 707,1 Ω ✓" in _text(data, "Kontrol")
    # f₀'da çözülen sonuçlar: bobin akımı = V/(jX) = 0,1∠−90° A
    il = data["results"]["element_currents"]["L1"]["value"]
    assert il["magnitude"] == pytest.approx(0.1, rel=1e-6)
    assert il["phase_degrees"] == pytest.approx(-90.0, abs=1e-3)


def test_parallel_rlc_current_source():
    data = _ok(PARALLEL_I)
    rs = data["resonance"]
    assert rs["kind"] == "parallel"
    assert rs["z0"] == pytest.approx(1000.0, rel=1e-9)
    assert rs["q"] == pytest.approx(10.0, rel=1e-9)
    assert rs["i0"] == pytest.approx(0.01, rel=1e-9)          # kaynak akımı
    assert rs["v0"] == pytest.approx(10.0, rel=1e-9)          # V_max = I·R = 0,01 · 1000
    assert "Rezonansta Empedans ve Gerilim" in _titles(data)
    assert "V_max = I · Z₀ = I · R = 10 mA · 1 kΩ = 10 V" in _text(data, "Rezonansta Empedans ve Gerilim")
    # düğüm 1 gerilimi 10∠0° V (akım kaynağı 0 → 1 yönünde besler)
    assert data["results"]["node_voltages"]["1"]["value"] == pytest.approx(10.0, rel=1e-6)


def test_parallel_with_sine_source_and_other_value_set():
    """L = 4 mH, C = 25 µF, R = 20 Ω: ω₀ = 1/√(1e-7) = 3162,2777 rad/s, X = 12,649 Ω, Q = R/X."""
    net = "V1 1 0 SINE(0 5 60 0 0 0)\nR1 1 0 20\nL1 1 0 4m\nC1 1 0 25u" + GND
    data = _ok(net, frequency=60.0)
    rs = data["resonance"]
    w0 = 1.0 / math.sqrt(4e-3 * 25e-6)
    x = w0 * 4e-3
    q = 20.0 / x
    assert rs["w0"] == pytest.approx(w0, rel=1e-9)
    assert rs["x"] == pytest.approx(x, rel=1e-9)
    assert rs["q"] == pytest.approx(q, rel=1e-9)
    assert rs["bw"] == pytest.approx(w0 / (2 * math.pi) / q, rel=1e-8)
    assert rs["i0"] == pytest.approx(5.0 / 20.0, rel=1e-9)


# ═══════════════════════════════════════════════════════
#  3. ETKİN / TEPE
# ═══════════════════════════════════════════════════════

def test_rms_and_peak_give_same_f0_q_bw_and_sqrt2_current_ratio():
    net_rms = "V1 1 0 SINE(0 10 50 0 0 0) RMS\nR1 1 2 10\nL1 2 3 10m\nC1 3 0 1u" + GND
    peak = _ok(net_rms, value_display="PEAK")["resonance"]
    rms_data = _ok(net_rms, value_display="RMS")
    rms = rms_data["resonance"]
    for key in ("f0", "w0", "x", "q", "bw", "f1", "f2", "f1_exact", "f2_exact", "z0"):
        assert peak[key] == pytest.approx(rms[key], rel=1e-9), key
    assert rms["i0"] == pytest.approx(1.0, rel=1e-9)                       # 10 V etkin / 10 Ω
    assert peak["i0"] == pytest.approx(math.sqrt(2.0), rel=1e-9)           # tepe: 10·√2 / 10
    assert peak["i0"] / rms["i0"] == pytest.approx(math.sqrt(2.0), rel=1e-9)
    assert peak["v0"] / rms["v0"] == pytest.approx(math.sqrt(2.0), rel=1e-9)
    assert "etkin (RMS)" in _text(rms_data, "Devreyi Tanıyalım")


def test_peak_input_displayed_as_rms():
    """10 V tepe girildi, etkin gösteriliyor: V = 10/√2 → I_max = 10/(√2·10) A."""
    data = _ok(SERIES, value_display="RMS", frequency=50.0)
    assert data["resonance"]["i0"] == pytest.approx(1.0 / math.sqrt(2.0), rel=1e-9)
    assert data["resonance"]["q"] == pytest.approx(10.0, rel=1e-9)


def test_rms_curve_scaled_by_sqrt2():
    net = "V1 1 0 AC_PHASOR(10, 0) RMS\nR1 1 2 10\nL1 2 3 10m\nC1 3 0 1u" + GND
    c_peak = _ok(net, value_display="PEAK")["resonance"]["curve"]
    c_rms = _ok(net, value_display="RMS")["resonance"]["curve"]
    assert c_peak["f"] == c_rms["f"]
    assert max(c_peak["y"]) / max(c_rms["y"]) == pytest.approx(math.sqrt(2.0), rel=1e-8)


# ═══════════════════════════════════════════════════════
#  4. KAYNAK FREKANSI
# ═══════════════════════════════════════════════════════

def test_works_without_frequency():
    for net in (SERIES, SERIES_PHASOR, PARALLEL_V, PARALLEL_I):
        data = _ok(net)                    # frequency gönderilmedi
        assert data["status"] == "success"
        assert data["errors"] == [] and data["warnings"] == []
        assert data["resonance"]["f0"] == pytest.approx(F0, rel=1e-8)
        assert data["results"]["node_voltages"]


def test_source_frequency_does_not_change_f0_and_note_appears():
    base = _ok(SERIES_PHASOR)["resonance"]
    with_req = _ok(SERIES_PHASOR, frequency=60.0)
    assert with_req["resonance"]["f0"] == pytest.approx(base["f0"], rel=1e-12)
    assert with_req["resonance"]["q"] == base["q"]
    assert with_req["warnings"] == [] and with_req["errors"] == []
    note = _text(with_req, "Devreyi Tanıyalım")
    assert "Kaynağın frekansı f = 60 Hz;" in note
    assert "f₀'da çalışsaydı geçerlidir" in note

    # SINE kaynağın kendi frekansı (50 Hz), istekteki 1000 Hz'den önce gelir
    sine = _ok(SERIES, frequency=1000.0)
    assert sine["resonance"]["f0"] == pytest.approx(F0, rel=1e-8)
    assert "Kaynağın frekansı f = 50 Hz;" in _text(sine, "Devreyi Tanıyalım")
    # çözülen sonuçlar yine f₀'dadır
    assert sine["results"]["node_voltages"]["3"]["value"]["magnitude"] == pytest.approx(100.0, rel=1e-6)


def test_no_note_when_source_frequency_equals_f0():
    net = f"V1 1 0 SINE(0 10 {F0!r} 0 0 0)\nR1 1 2 10\nL1 2 3 10m\nC1 3 0 1u" + GND
    data = _ok(net)
    assert "Kaynağın frekansı" not in _text(data, "Devreyi Tanıyalım")
    assert data["resonance"]["f0"] == pytest.approx(F0, rel=1e-8)


# ═══════════════════════════════════════════════════════
#  5. EĞRİ
# ═══════════════════════════════════════════════════════

def test_series_curve_shape_and_values():
    rs = _ok(SERIES_PHASOR)["resonance"]
    cv = rs["curve"]
    assert cv["quantity"] == "I" and cv["unit"] == "A"
    f, y = cv["f"], cv["y"]
    assert len(f) == 400 and len(y) == 400
    assert all(b > a for a, b in zip(f, f[1:]))                       # artan, doğrusal ızgara
    bw = F0 / 10.0
    assert f[0] == pytest.approx(max(0.1 * F0, F0 - 5 * bw), rel=1e-9)
    assert f[-1] == pytest.approx(F0 + 5 * bw, rel=1e-9)
    # f₀ eğride tam bir nokta ve tepe noktası: I_max = V/R = 1 A
    k0 = f.index(rs["f0"])
    assert y[k0] == pytest.approx(1.0, rel=1e-9)
    assert y[k0] == max(y)
    # eğrideki rastgele noktalar elle hesaplanan V/|Z(f)| ile aynı
    for k in (0, 57, 199, 301, 399):
        assert y[k] == pytest.approx(10.0 / abs(_z_series(f[k], 10.0)), rel=1e-8)
    # tam yarım güç frekansında I_max/√2
    assert 10.0 / abs(_z_series(rs["f1_exact"], 10.0)) == pytest.approx(1.0 / math.sqrt(2.0), rel=1e-8)
    assert 10.0 / abs(_z_series(rs["f2_exact"], 10.0)) == pytest.approx(1.0 / math.sqrt(2.0), rel=1e-8)


def test_parallel_curve_is_impedance_magnitude():
    rs = _ok(PARALLEL_V)["resonance"]
    cv = rs["curve"]
    assert cv["quantity"] == "Z" and cv["unit"] == "Ω"
    f, y = cv["f"], cv["y"]
    assert len(f) == 400 and len(y) == 400
    k0 = f.index(rs["f0"])
    assert y[k0] == pytest.approx(1000.0, rel=1e-9)
    assert y[k0] == max(y)
    for k in (0, 100, 250, 399):
        assert y[k] == pytest.approx(abs(_z_parallel(f[k], 1000.0)), rel=1e-8)
    assert abs(_z_parallel(rs["f1_exact"], 1000.0)) == pytest.approx(1000.0 / math.sqrt(2.0), rel=1e-8)
    assert abs(_z_parallel(rs["f2_exact"], 1000.0)) == pytest.approx(1000.0 / math.sqrt(2.0), rel=1e-8)


def test_curve_lower_bound_for_low_q_is_tenth_of_f0():
    net = "V1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nL1 2 3 10m\nC1 3 0 1u" + GND   # Q = 1, BW = f₀
    cv = _ok(net)["resonance"]["curve"]
    assert cv["f"][0] == pytest.approx(0.1 * F0, rel=1e-8)             # f₀ − 5·BW < 0 → 0,1·f₀
    assert cv["f"][-1] == pytest.approx(6.0 * F0, rel=1e-8)
    assert 0.0 not in cv["f"]


# ═══════════════════════════════════════════════════════
#  6. UYGULANAMAYAN DEVRELER → TÜRKÇE SEBEP + NORMAL AC ANLATIM
# ═══════════════════════════════════════════════════════

PREFIX = "Rezonans yöntemi yalnızca seri ve paralel RLC devreleri için anlatılır"

INAPPLICABLE = {
    "two_inductors": (
        "V1 1 0 SINE(0 10 50 0 0 0)\nR1 1 2 10\nL1 2 3 10m\nL2 3 4 5m\nC1 4 0 1u" + GND,
        "tam olarak bir bobin olmalı"),
    "no_capacitor": (
        "V1 1 0 SINE(0 10 50 0 0 0)\nR1 1 2 10\nL1 2 0 10m" + GND,
        "tam olarak bir kondansatör olmalı"),
    "impedance_element": (
        "V1 1 0 SINE(0 10 50 0 0 0)\nR1 1 2 10\nL1 2 3 10m\nC1 3 4 1u\nZ1 4 0 COMPLEX(5, 5)" + GND,
        "empedans (Z) elemanı var"),
    "dependent_source": (
        "V1 1 0 SINE(0 10 50 0 0 0)\nR1 1 2 10\nL1 2 3 10m\nC1 3 0 1u\n"
        "E1 5 0 V(R1) 2\nR3 5 0 50" + GND,
        "bağımlı kaynak var"),
    "series_with_current_source": (
        "I1 0 1 AC_PHASOR(1, 0)\nR1 1 2 10\nL1 2 3 10m\nC1 3 0 1u" + GND,
        "seri devrede akım kaynağı"),
    "parallel_two_resistors": (
        "V1 1 0 AC_PHASOR(10, 0)\nR1 1 0 1k\nR2 1 0 2k\nL1 1 0 10m\nC1 1 0 1u" + GND,
        "paralel biçimde tam olarak bir direnç olmalı"),
    "real_inductor": (
        "V1 1 0 AC_PHASOR(10, 0)\nC1 1 0 1u\nR1 1 2 5\nL1 2 0 10m" + GND,
        "ne tek gözde seri ne de aynı iki düğüm arasında paralel"),
    "two_sources": (
        "V1 1 0 AC_PHASOR(10, 0)\nI1 0 1 AC_PHASOR(0.01, 0)\nR1 1 0 1k\nL1 1 0 10m\nC1 1 0 1u" + GND,
        "tam olarak bir AC kaynak olmalı"),
    "tank_extra_element_on_x": (
        "V1 1 0 AC_PHASOR(10, 0)\nR1 1 2 1k\nL1 2 0 100m\nC1 2 0 10u\nR3 2 0 5k" + GND,
        "ne tek gözde seri ne de aynı iki düğüm arasında paralel bağlı"),
    "tank_with_current_source": (
        "I1 0 1 AC_PHASOR(0.01, 0)\nR1 1 2 1k\nL1 2 0 100m\nC1 2 0 10u" + GND,
        "kaynağa seri R ile bağlı paralel LC"),
    "tank_lc_not_on_source_terminal": (
        "V1 1 0 AC_PHASOR(10, 0)\nR1 1 2 1k\nR2 2 3 1k\nL1 3 4 100m\nC1 3 4 10u\nR3 4 0 1k" + GND,
        "ne tek gözde seri ne de aynı iki düğüm arasında paralel bağlı"),
    "no_resistor": (
        "V1 1 0 AC_PHASOR(10, 0)\nL1 1 2 10m\nC1 2 0 1u" + GND,
        "devrede direnç yok"),
}


@pytest.mark.parametrize("name", list(INAPPLICABLE))
def test_inapplicable_circuits_fall_back_with_turkish_reason(name):
    net, detail = INAPPLICABLE[name]
    resp = _post(net, frequency=1000.0)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["resonance"] is None
    assert data["analysis_type"] == "RESONANCE"
    titles = _titles(data)
    assert "Rezonans" in titles                      # sebep notunu taşıyan bölüm
    note = _text(data, "Rezonans")
    assert "Bu devrede Rezonans yöntemi uygulanamadı" in note
    assert PREFIX in note
    assert detail in note
    assert "Düğüm Gerilimleri" in note
    # normal AC anlatımı sürer ve kaynak frekansı (istekteki 1000 Hz) kullanılır
    assert "Devreyi Tanıyalım" in titles
    assert "Rezonans Koşulu" not in titles
    assert "ω = 2πf = 2π · 1000 Hz = 6283 rad/s" in _text(data, "Devreyi Tanıyalım")


def test_zero_resistor_is_not_applicable():
    parsed = parse_netlist("V1 1 0 AC_PHASOR(10, 0)\nR1 1 2 0\nL1 2 3 10m\nC1 3 0 1u" + GND)
    with pytest.raises(ResonanceNotApplicable) as exc:
        analyze_resonance(parsed)
    assert PREFIX in str(exc.value)
    assert "sıfır ya da negatif" in str(exc.value)


def test_fallback_without_frequency_keeps_existing_frequency_error():
    """Uygulanamayan devrede frekans yoksa mevcut davranış (frekans hatası) aynen sürer."""
    net = "V1 1 0 AC_PHASOR(10, 0)\nR1 1 0 1k\nR2 1 0 2k\nL1 1 0 10m\nC1 1 0 1u" + GND
    plain = client.post("/analyze", json={
        "netlist": net, "mode": "AC_PHASOR", "analysis_type": "NODAL"})
    res = _post(net)
    assert res.status_code == plain.status_code
    assert res.json()["errors"] == plain.json()["errors"]
    assert res.json()["errors"], "frekans hatası bekleniyordu"
    assert res.json()["resonance"] is None


def test_inapplicable_circuit_with_sine_source_uses_source_frequency():
    net, _ = INAPPLICABLE["parallel_two_resistors"]
    net = net.replace("V1 1 0 AC_PHASOR(10, 0)", "V1 1 0 SINE(0 10 50 0 0 0)")
    data = _ok(net)                                 # istekte frekans yok; kaynaktan 50 Hz alınır
    assert data["resonance"] is None
    assert "ω = 2πf = 2π · 50 Hz = 314,2 rad/s" in _text(data, "Devreyi Tanıyalım")


# ═══════════════════════════════════════════════════════
#  7. DC
# ═══════════════════════════════════════════════════════

def test_dc_mode_falls_back_with_reason():
    net = "V1 1 0 DC 10\nR1 1 2 10\nL1 2 3 10m\nC1 3 0 1u" + GND
    data = _ok(net, mode="DC")
    assert data["resonance"] is None
    note = _text(data, "Rezonans")
    assert "yalnızca AC devreler için uygulanır" in note
    assert "Bu devrede Rezonans yöntemi uygulanamadı" in note
    assert "Devreyi Tanıyalım" in _titles(data)


# ═══════════════════════════════════════════════════════
#  8. ALIŞTIRMA
# ═══════════════════════════════════════════════════════

def _questions(data: dict) -> dict:
    return {q["id"]: PracticeQuestion.model_validate(q) for q in data["results"]["practice"]}


def test_practice_questions_series():
    data = _ok(SERIES_PHASOR)
    qs = _questions(data)
    assert list(qs) == ["F0", "Q_FACTOR", "BW", "I_MAX", "F1", "F2"]
    bw = F0 / 10.0
    assert qs["F0"].unit == "Hz" and qs["F0"].expected.real == pytest.approx(F0, rel=1e-8)
    assert qs["Q_FACTOR"].unit == "" and qs["Q_FACTOR"].expected.real == pytest.approx(10.0)
    assert qs["BW"].unit == "Hz" and qs["BW"].expected.real == pytest.approx(bw, rel=1e-8)
    assert qs["I_MAX"].unit == "A" and qs["I_MAX"].expected.real == pytest.approx(1.0)
    assert qs["F1"].expected.real == pytest.approx(F0 - bw / 2, rel=1e-8)     # kitap biçimi
    assert qs["F2"].expected.real == pytest.approx(F0 + bw / 2, rel=1e-8)
    assert all(not q.is_ac for q in qs.values())
    assert [q.group for q in qs.values()] == ["main", "main", "main", "main", "extra", "extra"]


def test_practice_questions_parallel_ask_impedance():
    qs = _questions(_ok(PARALLEL_V))
    assert list(qs) == ["F0", "Q_FACTOR", "BW", "Z0", "F1", "F2"]
    assert qs["Z0"].unit == "Ω" and qs["Z0"].expected.real == pytest.approx(1000.0)


def test_practice_answers_hz_khz_and_units():
    qs = _questions(_ok(SERIES_PHASOR))
    f0 = qs["F0"]
    for ans in ("1591.55", "1591,55 Hz", "1591.55hz", "1,59155 kHz", "1.59155k", "0.00159155 MHz",
                "1.59155 kHz"):
        assert check_answer(f0, ans).status == "correct", ans
    # birim: Hz yerine A yazılırsa sayı doğru ama birim yanlış
    wrong_unit = check_answer(f0, "1591.55 A")
    assert wrong_unit.status == "partial"
    assert "frekans" in wrong_unit.message and "hertz (Hz)" in wrong_unit.message
    # önek unutuldu: 1,59155 yazıldı (1000 kat küçük) → önek uyarısı, örnek kHz ile
    pref = check_answer(f0, "1.59155")
    assert pref.status == "wrong"
    assert "kHz" in pref.message and "1.000 katı küçük" in pref.message
    # ω₀ yazıldı
    omega = check_answer(f0, "10000")
    assert omega.status == "wrong" and "açısal frekans" in omega.message

    q_f = qs["Q_FACTOR"]
    assert check_answer(q_f, "10").status == "correct"
    unit_msg = check_answer(q_f, "10 Hz")
    assert unit_msg.status == "partial" and "kalite faktörü Q birimsiz" in unit_msg.message
    inverse = check_answer(q_f, "0.1")
    assert inverse.status == "wrong" and "ters" in inverse.message

    assert check_answer(qs["BW"], "159.155 Hz").status == "correct"
    assert check_answer(qs["BW"], "0.159155k").status == "correct"
    assert check_answer(qs["I_MAX"], "1 A").status == "correct"
    assert check_answer(qs["I_MAX"], "1000 mA").status == "correct"
    sqrt2 = check_answer(qs["I_MAX"], "1.41421")
    assert sqrt2.status == "wrong" and "√2" in sqrt2.message


def test_practice_f1_f2_accept_book_and_exact_values():
    """Q = 1: kitap f₁ = 0,5·f₀ ve tam değer 0,618·f₀ farklıdır; ikisi de doğru sayılır."""
    net = "V1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nL1 2 3 10m\nC1 3 0 1u" + GND
    data = _ok(net)
    qs = _questions(data)
    rs = data["resonance"]
    f1_book, f2_book = 0.5 * F0, 1.5 * F0
    f1_exact, f2_exact = (math.sqrt(1.25) - 0.5) * F0, (math.sqrt(1.25) + 0.5) * F0
    assert check_answer(qs["F1"], f"{f1_book} Hz").status == "correct"
    assert check_answer(qs["F2"], f"{f2_book} Hz").status == "correct"
    ex1 = check_answer(qs["F1"], f"{f1_exact} Hz")
    ex2 = check_answer(qs["F2"], f"{f2_exact:.6g} Hz")
    assert ex1.status == "correct" and "tam yarım güç" in ex1.message
    assert ex2.status == "correct" and "tam yarım güç" in ex2.message
    assert rs["f1_exact"] == pytest.approx(f1_exact, rel=1e-8)
    # hepsinden uzak bir değer yanlıştır; BW yazmak ayrıca açıklanır
    assert check_answer(qs["F1"], "1200 Hz").status == "wrong"
    bw_msg = check_answer(qs["F1"], f"{F0} Hz")
    assert bw_msg.status == "wrong" and "bant genişliği" in bw_msg.message


def test_practice_f1_high_q_exact_is_inside_tolerance():
    qs = _questions(_ok(SERIES_PHASOR))
    f1e, f2e = _half_power(F0, F0 / 10.0)
    assert check_answer(qs["F1"], f"{f1e} Hz").status == "correct"
    assert check_answer(qs["F2"], f"{f2e} Hz").status == "correct"


@pytest.mark.parametrize("text, value", [
    ("2 MHz", 2e6), ("2 mHz", 2e-3), ("5 kHz", 5e3), ("7 Hz", 7.0), ("7 hz", 7.0),
    ("2,5kHz", 2500.0), ("1k5Hz", 1500.0), ("3 MHZ", 3e6), ("40 KHz", 4e4),
])
def test_answer_parser_reads_hertz(text, value):
    parsed = parse_answer(text)
    assert parsed.unit == "Hz"
    assert parsed.value.real == pytest.approx(value, rel=1e-12)


# ═══════════════════════════════════════════════════════
#  9. YANIT JSON
# ═══════════════════════════════════════════════════════

def test_response_json_fields():
    data = _ok(SERIES_PHASOR)
    rs = data["resonance"]
    assert set(rs) == {"kind", "f0", "w0", "x", "q", "bw", "f1", "f2", "f1_exact", "f2_exact",
                       "z0", "i0", "v0", "curve", "via_source_transform"}
    assert set(rs["curve"]) == {"quantity", "unit", "f", "y"}
    for net in (SERIES, PARALLEL_V, PARALLEL_I):             # öteki biçimlerde false
        assert _ok(net, frequency=50.0)["resonance"]["via_source_transform"] is False
    assert "resonance" not in data["results"]                  # yalnızca üst düzey alan
    assert data["value_display"] == "PEAK"


def test_resonance_is_null_for_other_methods():
    for analysis in ("NODAL", "MESH", "POWER"):
        resp = client.post("/analyze", json={
            "netlist": SERIES_PHASOR, "mode": "AC_PHASOR", "frequency": 1000.0,
            "analysis_type": analysis})
        assert resp.status_code == 200
        assert resp.json()["resonance"] is None


def test_resonance_hidden_from_openapi_enum_like_power():
    schema = client.get("/openapi.json").json()
    enum = schema["components"]["schemas"]["AnalysisType"]["enum"]
    assert "RESONANCE" not in enum and "POWER" not in enum


def test_assistant_knows_resonance_method_and_numbers():
    from llm.assistant import _METHOD_NAMES
    from models.request import AnalysisType
    assert "Rezonans" in _METHOD_NAMES[AnalysisType.RESONANCE]


# ═══════════════════════════════════════════════════════
#  10. SERİ R + PARALEL LC ("TANK", kaynak dönüşümüyle paralel RLC)
# ═══════════════════════════════════════════════════════
#
# L = 100 mH, C = 10 µF:  ω₀ = 1/√(0,1 · 1e-5) = 1000 rad/s, f₀ = 159,155 Hz, X = ω₀L = 100 Ω
# R = 1 kΩ:  Q = R/X = 10, BW = f₀/Q = 15,9155 Hz
# Rezonansta LC kolu açık devre: kaynak akımı 0, V_x = V, I_L = I_C = V/X = Q·V/R

TW0 = 1.0 / math.sqrt(0.1 * 10e-6)
TF0 = TW0 / (2.0 * math.pi)
TANK = ("V1 1 0 AC_PHASOR(10, 0) RMS\nR1 1 2 1k\nL1 2 0 100m\nC1 2 0 10u" + GND)


def _z_tank(f: float, r: float) -> complex:
    """Dönüştürülmüş devrenin empedansı R‖Z_L‖Z_C."""
    w = 2.0 * math.pi * f
    return 1.0 / complex(1.0 / r, w * 10e-6 - 1.0 / (w * 0.1))


def test_tank_rms_hand_values_and_flags():
    data = _ok(TANK, value_display="RMS")
    assert data["status"] == "success"
    assert data["errors"] == [] and data["warnings"] == []
    rs = data["resonance"]
    assert rs["kind"] == "parallel" and rs["via_source_transform"] is True
    assert rs["w0"] == pytest.approx(1000.0, rel=1e-9)
    assert rs["f0"] == pytest.approx(159.1549431, rel=1e-8)
    assert rs["x"] == pytest.approx(100.0, rel=1e-9)
    assert rs["q"] == pytest.approx(10.0, rel=1e-9)
    assert rs["bw"] == pytest.approx(15.91549431, rel=1e-8)
    assert rs["z0"] == pytest.approx(1000.0, rel=1e-9)
    assert rs["i0"] == pytest.approx(0.0, abs=1e-12)              # gerçek kaynak akımı
    assert rs["v0"] == pytest.approx(10.0, rel=1e-9)              # V_x = V
    f1e, f2e = _half_power(TF0, TF0 / 10.0)
    assert rs["f1_exact"] == pytest.approx(f1e, rel=1e-9)
    assert rs["f2_exact"] == pytest.approx(f2e, rel=1e-9)
    assert rs["f1"] == pytest.approx(TF0 - TF0 / 20.0, rel=1e-9)
    assert _titles(data) == [
        "Devreyi Tanıyalım", "Rezonans Koşulu", "Rezonans Frekansı", "Reaktanslar",
        "Kaynak Dönüşümü", "Rezonansta Empedans ve Akım", "Kalite Faktörü Q", "Bant Genişliği",
        "Eleman Akımları", "Kontrol", "Sonuç"]


def test_tank_narrative_text():
    data = _ok(TANK, value_display="RMS")
    assert "I = V / R = 10 V / 1 kΩ = 10 mA" in _text(data, "Kaynak Dönüşümü")
    emp = _text(data, "Rezonansta Empedans ve Akım")
    assert "Kaynak akımı: I = 0" in emp
    assert "V_x = V" in emp
    assert "kaynaktan görülen empedans sonsuza gider" in emp
    assert "|R‖Z_L‖Z_C|" in emp
    assert "I_L = V_x / X_L = 10 V / 100 Ω = 100 mA" in _text(data, "Eleman Akımları")
    assert "I_L = I_C = Q · V / R = 10 · 10 mA = 100 mA" in _text(data, "Eleman Akımları")
    kontrol = _text(data, "Kontrol")
    assert "akım ≈ 0 ✓" in kontrol and "|V_x| = 10 V = V ✓" in kontrol
    assert "|I_L| = |I_C| = 100 mA = V/X ✓" in kontrol
    assert "V/√2 = 7,071 V ✓" in kontrol
    assert "Z = R" not in kontrol                                   # Z'nin sanal kısmı denetimi yok


def test_tank_results_solved_at_f0_on_real_circuit():
    data = _ok(TANK, value_display="RMS", frequency=50.0)           # istek frekansı kullanılmaz
    assert data["resonance"]["f0"] == pytest.approx(TF0, rel=1e-8)
    nv = data["results"]["node_voltages"]
    assert nv["1"]["value"] == pytest.approx(10.0, rel=1e-6)
    assert nv["2"]["value"] == pytest.approx(10.0, rel=1e-6)         # V_x = V
    il = data["results"]["element_currents"]["L1"]["value"]
    assert il["magnitude"] == pytest.approx(0.1, rel=1e-6)           # V/X = 10/100
    assert il["phase_degrees"] == pytest.approx(-90.0, abs=1e-3)
    ic = data["results"]["element_currents"]["C1"]["value"]
    assert ic["magnitude"] == pytest.approx(0.1, rel=1e-6)
    assert ic["phase_degrees"] == pytest.approx(90.0, abs=1e-3)
    assert abs(data["results"]["element_currents"]["R1"]["value"]) < 1e-9
    assert "Kaynağın frekansı f = 50 Hz;" in _text(data, "Devreyi Tanıyalım")


def test_tank_peak_display_scales_by_sqrt2_and_keeps_f0_q_bw():
    rms = _ok(TANK, value_display="RMS")["resonance"]
    peak_data = _ok(TANK, value_display="PEAK")
    peak = peak_data["resonance"]
    for key in ("f0", "w0", "x", "q", "bw", "f1", "f2", "f1_exact", "f2_exact", "z0"):
        assert peak[key] == pytest.approx(rms[key], rel=1e-9), key
    assert peak["v0"] == pytest.approx(10.0 * math.sqrt(2.0), rel=1e-9)
    assert peak["i0"] == pytest.approx(0.0, abs=1e-12)
    assert peak["curve"]["y"] == rms["curve"]["y"]                   # |Z| eğrisi tabandan bağımsız
    assert "I_L = V_x / X_L = 14,14 V / 100 Ω = 141,4 mA" in _text(peak_data, "Eleman Akımları")


def test_tank_without_frequency_works():
    data = _ok(TANK)
    assert data["status"] == "success"
    assert data["resonance"]["f0"] == pytest.approx(TF0, rel=1e-8)


def test_tank_curve_peak_is_r_and_cuts_half_power_at_exact_frequencies():
    rs = _ok(TANK, value_display="RMS")["resonance"]
    cv = rs["curve"]
    assert cv["quantity"] == "Z" and cv["unit"] == "Ω"
    f, y = cv["f"], cv["y"]
    assert len(f) == 400 and all(b > a for a, b in zip(f, f[1:]))
    bw = TF0 / 10.0
    assert f[0] == pytest.approx(max(0.1 * TF0, TF0 - 5 * bw), rel=1e-9)
    assert f[-1] == pytest.approx(TF0 + 5 * bw, rel=1e-9)
    k0 = f.index(rs["f0"])
    assert y[k0] == pytest.approx(1000.0, rel=1e-9)                  # tepe = R
    assert y[k0] == max(y)
    for k in (0, 80, 250, 399):
        assert y[k] == pytest.approx(abs(_z_tank(f[k], 1000.0)), rel=1e-8)
    for fe in (rs["f1_exact"], rs["f2_exact"]):
        assert abs(_z_tank(fe, 1000.0)) == pytest.approx(1000.0 / math.sqrt(2.0), rel=1e-8)


def test_tank_two_series_resistors_are_added():
    net = ("V1 1 0 AC_PHASOR(10, 0) RMS\nR1 1 2 300\nR2 2 3 200\nL1 3 0 100m\nC1 3 0 10u" + GND)
    data = _ok(net, value_display="RMS")
    rs = data["resonance"]
    assert rs["via_source_transform"] is True
    assert rs["z0"] == pytest.approx(500.0, rel=1e-9)
    assert rs["q"] == pytest.approx(5.0, rel=1e-9)                   # R/X = 500/100
    assert rs["bw"] == pytest.approx(TF0 / 5.0, rel=1e-8)
    assert rs["v0"] == pytest.approx(10.0, rel=1e-9)
    assert rs["f0"] == pytest.approx(TF0, rel=1e-8)                  # R f₀'ı değiştirmez
    assert rs["curve"]["y"][rs["curve"]["f"].index(rs["f0"])] == pytest.approx(500.0, rel=1e-9)
    assert "R = R1 + R2 = 300 Ω + 200 Ω = 500 Ω" in _text(data, "Rezonans Koşulu")
    # I_L = V/X = 100 mA = Q·V/R = 5 · 10 / 500
    assert "I_L = I_C = Q · V / R = 5 · 20 mA = 100 mA" in _text(data, "Eleman Akımları")
    # fazladan (ikinci) kaynak varsa biçim uygun değildir
    flipped = ("V1 1 0 AC_PHASOR(10, 0) RMS\nL1 1 0 100m\nC1 1 0 10u\nR1 1 2 500\n"
               "V2 2 0 AC_PHASOR(0, 0)" + GND)
    assert _ok(flipped, value_display="RMS")["resonance"] is None    # fazladan kaynak: uygun değil


def test_tank_low_q_exact_half_power_and_note():
    net = "V1 1 0 AC_PHASOR(10, 0) RMS\nR1 1 2 100\nL1 2 0 100m\nC1 2 0 10u" + GND   # Q = 1
    data = _ok(net, value_display="RMS")
    rs = data["resonance"]
    assert rs["via_source_transform"] is True
    assert rs["q"] == pytest.approx(1.0, rel=1e-9)
    assert rs["bw"] == pytest.approx(TF0, rel=1e-8)
    assert rs["f1"] == pytest.approx(0.5 * TF0, rel=1e-8)
    assert rs["f2"] == pytest.approx(1.5 * TF0, rel=1e-8)
    golden = math.sqrt(1.25)
    assert rs["f1_exact"] == pytest.approx((golden - 0.5) * TF0, rel=1e-8)
    assert rs["f2_exact"] == pytest.approx((golden + 0.5) * TF0, rel=1e-8)
    assert abs(_z_tank(rs["f1_exact"], 100.0)) == pytest.approx(100.0 / math.sqrt(2.0), rel=1e-8)
    assert "Q küçük olduğundan kitaptaki f₀ ∓ BW/2 yaklaşıktır; tam değerler" in _text(data, "Bant Genişliği")
    # Q = 1: I_L = I_C = Q·V/R = 1 · 10/100 = 0,1 A = V/X
    assert "I_L = I_C = Q · V / R = 1 · 100 mA = 100 mA" in _text(data, "Eleman Akımları")


def test_tank_practice_questions():
    data = _ok(TANK, value_display="RMS")
    qs = _questions(data)
    assert list(qs) == ["F0", "Q_FACTOR", "BW", "VX", "F1", "F2"]          # I_MAX ve Z0 sorulmaz
    assert qs["VX"].unit == "V" and qs["VX"].expected.real == pytest.approx(10.0, rel=1e-9)
    assert qs["F0"].expected.real == pytest.approx(TF0, rel=1e-8)
    assert qs["Q_FACTOR"].expected.real == pytest.approx(10.0)
    assert qs["BW"].expected.real == pytest.approx(TF0 / 10.0, rel=1e-8)
    assert qs["F1"].expected.real == pytest.approx(TF0 - TF0 / 20.0, rel=1e-8)
    assert check_answer(qs["VX"], "10 V").status == "correct"
    assert check_answer(qs["VX"], "10000 mV").status == "correct"
    assert check_answer(qs["F0"], "159,155 Hz").status == "correct"
    assert check_answer(qs["BW"], "15.9155").status == "correct"
    assert check_answer(qs["Q_FACTOR"], "10").status == "correct"
    over = check_answer(qs["VX"], "100")
    assert over.status == "wrong" and "Q·V" in over.message
    half = check_answer(qs["VX"], "7.0711")
    assert half.status == "wrong" and "V/√2" in half.message
    zero = check_answer(qs["VX"], "0")
    assert zero.status == "wrong" and "V_x sıfır değildir" in zero.message
    # peak gösterimde beklenen V_x = 10·√2
    peak_qs = _questions(_ok(TANK, value_display="PEAK"))
    assert peak_qs["VX"].expected.real == pytest.approx(10.0 * math.sqrt(2.0), rel=1e-9)


def test_tank_low_q_practice_accepts_exact_f1():
    net = "V1 1 0 AC_PHASOR(10, 0) RMS\nR1 1 2 100\nL1 2 0 100m\nC1 2 0 10u" + GND
    qs = _questions(_ok(net, value_display="RMS"))
    f1_exact = (math.sqrt(1.25) - 0.5) * TF0
    assert check_answer(qs["F1"], f"{0.5 * TF0} Hz").status == "correct"
    ex = check_answer(qs["F1"], f"{f1_exact} Hz")
    assert ex.status == "correct" and "tam yarım güç" in ex.message
