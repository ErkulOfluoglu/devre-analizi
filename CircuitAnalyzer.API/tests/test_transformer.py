"""
Transformatör (analysis_type = "TRANSFORMER") yöntemi testleri — ideal ve kuplajlı.

Tüm beklenen değerler test içinde temel devre formülleriyle ELLE hesaplanır;
çözücü çıktısı kopyalanmaz.

Gösterim (kitap): V₁ = V(p+) − V(p−), V₂ = V(s+) − V(s−), I₁ p+ ucundan GİRER.
İdeal:    V₂ = a·V₁, I₂ s+ ucundan ÇIKAR, I₁ = a·I₂, yansıyan empedans Z₁ = Z₂/a².
Kuplajlı: I₁ ve I₂ nokta uçlarından GİRER;
          V₁ = jωL₁·I₁ + jωM·I₂,  V₂ = jωM·I₁ + jωL₂·I₂,  M = k·√(L₁L₂).

Ana ideal örnek: V = 100 V (etkin), a = 0,5, R_L = 10 Ω (ortak toprak)
    V₂ = 0,5 · 100 = 50 V,  I₂ = 50/10 = 5 A,  I₁ = 0,5 · 5 = 2,5 A,
    Z₁ = 10/0,25 = 40 Ω (= V₁/I₁ = 100/2,5),  P = 100 · 2,5 = 250 W (= 50 · 5)
Primer seri 10 Ω:  Z_top = 10 + 40 = 50 Ω, I₁ = 100/50 = 2 A, V₁ = 2 · 40 = 80 V,
                   V₂ = 0,5 · 80 = 40 V, I₂ = 2/0,5 = 4 A
"""

import cmath
import math

import pytest
from fastapi.testclient import TestClient

from main import app
from models.response import PracticeQuestion
from parser.netlist_parser import ElementType, parse_netlist
from practice.checker import check_answer

client = TestClient(app)

GND = "\n* GND1 — Referans toprak"
SRC = "VAC1 1 0 AC_PHASOR(100, 0) RMS\n"
OTHER_METHOD_NOTE = "Bu devrede transformatör var; çözüm Transformatör yöntemiyle anlatılıyor."
FLOATING_NOTE = "Sekonder toprağa bağlı değil; sekonder gerilimleri kendi alt ucuna göre verilmiştir."

IDEAL = SRC + "T1 1 0 2 0 IDEAL 0.5\nR1 2 0 10" + GND
IDEAL_SERIES = SRC + "Rs 1 2 10\nT1 2 0 3 0 IDEAL 0.5\nR1 3 0 10" + GND
IDEAL_STEPUP = SRC + "T1 1 0 2 0 IDEAL 2\nR1 2 0 10" + GND
IDEAL_RL = SRC + "T1 1 0 2 0 IDEAL 0.5\nZ2 2 0 COMPLEX(30, 40)" + GND
IDEAL_FLOAT = SRC + "T1 1 0 2 3 IDEAL 0.5\nR1 2 3 10" + GND

W = 2.0 * math.pi * 50.0


def _post(netlist: str, analysis_type: str = "TRANSFORMER", mode: str = "AC_PHASOR",
          value_display: str = "RMS", frequency=50, **extra):
    body = {"netlist": netlist, "mode": mode, "analysis_type": analysis_type,
            "value_display": value_display}
    if frequency is not None:
        body["frequency"] = frequency
    body.update(extra)
    return client.post("/analyze", json=body)


def _ok(netlist: str, **kw) -> dict:
    resp = _post(netlist, **kw)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _z(c) -> complex:
    """API değeri → complex (gerçek sonuçlar düz sayı, karmaşık olanlar real/imaginary nesnesi)."""
    if isinstance(c, (int, float)):
        return complex(c)
    return complex(c["real"], c["imaginary"])


def _close(a: complex, b: complex, rel: float = 1e-6) -> bool:
    return abs(complex(a) - complex(b)) <= rel * max(abs(a), abs(b), 1e-9) + 1e-9


def _titles(data: dict) -> list:
    return [s["title"] for s in data["results"]["explanation"]]


def _text(data: dict, title: str = None) -> str:
    out = []
    for s in data["results"]["explanation"]:
        if title is None or s["title"] == title:
            out.append("\n".join(b["text"] for b in s["blocks"]))
    return "\n".join(out)


def _tr(data: dict) -> dict:
    assert data["transformer"] is not None, data["errors"]
    return data["transformer"]


def _solve2(z11, z12, z21, z22, e):
    """İki çevre denklemini elle (Cramer) çöz: z11·I1 + z12·I2 = e ; z21·I1 + z22·I2 = 0."""
    det = z11 * z22 - z12 * z21
    return e * z22 / det, -e * z21 / det


# ═══════════════════════════════════════════════════════
#  1. AYRIŞTIRMA
# ═══════════════════════════════════════════════════════

def test_parse_ideal_transformer():
    p = parse_netlist(IDEAL)
    assert not p.errors
    t = next(e for e in p.elements if e.element_type == ElementType.TRANSFORMER)
    assert (t.id, t.node_positive, t.node_negative) == ("T1", "1", "0")
    assert (t.params["s_pos"], t.params["s_neg"]) == ("2", "0")
    assert t.params["kind"] == "IDEAL" and t.params["a"] == 0.5


def test_parse_coupled_transformer():
    p = parse_netlist("T1 1 0 2 0 COUPLED 100m 100m 0.5" + GND)
    assert not p.errors
    t = p.elements[0]
    assert t.params["kind"] == "COUPLED"
    assert t.params["l1"] == pytest.approx(0.1) and t.params["l2"] == pytest.approx(0.1)
    assert t.params["k"] == 0.5
    assert t.params["m"] == pytest.approx(0.5 * math.sqrt(0.1 * 0.1))      # M = k·√(L₁L₂) = 0,05 H


def test_node_count_sees_all_four_terminals():
    p = parse_netlist("T1 1 0 2 3 IDEAL 0.5\nR1 2 3 10" + GND)
    assert p.node_count == 4          # 0, 1, 2, 3 (ikinci çiftin düğümleri de sayılır)


@pytest.mark.parametrize("line, fragment", [
    ("T1 1 0 2 0 IDEAL 0", "dönüştürme oranı"),
    ("T1 1 0 2 0 IDEAL -2", "dönüştürme oranı"),
    ("T1 1 0 2 0 IDEAL abc", "okunamadı"),
    ("T1 1 0 2 0 COUPLED 100m 100m 0", "kuplaj katsayısı"),
    ("T1 1 0 2 0 COUPLED 100m 100m 1.5", "kuplaj katsayısı"),
    ("T1 1 0 2 0 COUPLED 0 100m 0.5", "endüktans"),
    ("T1 1 1 2 0 IDEAL 0.5", "primer uçları"),
    ("T1 1 0 2 2 IDEAL 0.5", "sekonder uçları"),
    ("T1 1 0 2 0 IDEAL", "anlaşılamadı"),
])
def test_invalid_transformer_lines_are_rejected_in_turkish(line, fragment):
    p = parse_netlist(SRC + line + "\nR1 2 0 10" + GND)
    assert p.errors and fragment in p.errors[0]
    resp = _post(SRC + line + "\nR1 2 0 10" + GND)
    assert resp.status_code == 400
    assert fragment in resp.json()["detail"]


def test_coupled_k_equal_one_is_valid():
    p = parse_netlist("T1 1 0 2 0 COUPLED 100m 400m 1" + GND)
    assert not p.errors
    assert p.elements[0].params["m"] == pytest.approx(math.sqrt(0.1 * 0.4))     # 0,2 H


# ═══════════════════════════════════════════════════════
#  2. İDEAL TRANSFORMATÖR — SAYILAR
# ═══════════════════════════════════════════════════════

def test_ideal_basic_numbers():
    d = _ok(IDEAL)
    tr = _tr(d)
    assert tr["kind"] == "ideal" and tr["id"] == "T1"
    assert tr["a"] == 0.5 and tr["k"] is None and tr["m"] is None
    assert _close(_z(tr["v1"]), 100)                    # V₁ = kaynak
    assert _close(_z(tr["v2"]), 50)                     # V₂ = a·V₁ = 0,5 · 100
    assert _close(_z(tr["i2"]), 5)                      # I₂ = V₂/R = 50/10
    assert _close(_z(tr["i1"]), 2.5)                    # I₁ = a·I₂ = 0,5 · 5
    assert tr["floating_secondary"] is False
    assert d["analysis_type"] == "TRANSFORMER"
    # Düğüm gerilimleri ve eleman akımları da dolu
    assert _close(_z(d["results"]["node_voltages"]["2"]["value"]), 50)
    assert _close(_z(d["results"]["element_currents"]["R1"]["value"]), 5)


def test_ideal_power_is_conserved_and_balanced():
    d = _ok(IDEAL)
    tr = _tr(d)
    p1 = (_z(tr["v1"]) * _z(tr["i1"]).conjugate()).real          # 100 · 2,5 = 250 W (etkin)
    p2 = (_z(tr["v2"]) * _z(tr["i2"]).conjugate()).real          # 50 · 5 = 250 W
    assert p1 == pytest.approx(250) and p2 == pytest.approx(250)
    assert d["results"]["power"]["balance_error"] < 1e-9


def test_ideal_with_primary_series_resistor():
    tr = _tr(_ok(IDEAL_SERIES))
    assert _close(_z(tr["i1"]), 2)                      # 100 / (10 + 40)
    assert _close(_z(tr["v1"]), 80)                     # 2 · 40
    assert _close(_z(tr["v2"]), 40)                     # 0,5 · 80
    assert _close(_z(tr["i2"]), 4)                      # 2 / 0,5


def test_ideal_step_up():
    tr = _tr(_ok(IDEAL_STEPUP))
    assert tr["a"] == 2
    assert _close(_z(tr["v2"]), 200)                    # 2 · 100
    assert _close(_z(tr["i2"]), 20)                     # 200 / 10
    assert _close(_z(tr["i1"]), 40)                     # a·I₂ = 2 · 20
    assert _close(_z(tr["v1"]) / _z(tr["i1"]), 2.5)     # Z₁ = Z₂/a² = 10/4


def test_ideal_with_inductive_load():
    tr = _tr(_ok(IDEAL_RL))
    # Z₂ = 30 + j40 Ω, Z₁ = Z₂/a² = 120 + j160 Ω → I₁ = 100/(120 + j160) = 0,3 − j0,4 A
    assert _close(_z(tr["i1"]), 0.3 - 0.4j)
    assert _close(_z(tr["v2"]), 50)
    assert _close(_z(tr["i2"]), 0.6 - 0.8j)             # = V₂/Z₂ = 50/(30 + j40)


def test_ideal_floating_secondary_gives_same_numbers():
    d = _ok(IDEAL_FLOAT)
    tr = _tr(d)
    assert tr["floating_secondary"] is True
    assert _close(_z(tr["v2"]), 50) and _close(_z(tr["i2"]), 5) and _close(_z(tr["i1"]), 2.5)
    assert FLOATING_NOTE in _text(d)
    # Alt uç yalnızca hesap için 0'a bağlandı: s− düğümü 0 V
    assert _close(_z(d["results"]["node_voltages"]["3"]["value"]), 0)
    assert _close(_z(d["results"]["node_voltages"]["2"]["value"]), 50)


def test_grounded_secondary_has_no_floating_note():
    d = _ok(IDEAL)
    assert FLOATING_NOTE not in _text(d)


def test_ideal_rms_vs_peak_display():
    rms = _tr(_ok(IDEAL_RL, value_display="RMS"))
    peak = _tr(_ok(IDEAL_RL, value_display="PEAK"))
    for key in ("v1", "v2", "i1", "i2"):
        assert abs(_z(peak[key])) == pytest.approx(math.sqrt(2) * abs(_z(rms[key])))
    # Güç tabana göre aynı: etkin P = V·I·cosφ, tepe P = ½·Vm·Im·cosφ
    p_rms = (_z(rms["v1"]) * _z(rms["i1"]).conjugate()).real
    p_peak = 0.5 * (_z(peak["v1"]) * _z(peak["i1"]).conjugate()).real
    assert p_rms == pytest.approx(p_peak)
    assert p_rms == pytest.approx(100 * 0.3)            # V·Re(I₁) = 100 · 0,3 = 30 W


def test_ideal_needs_no_frequency_without_reactive_elements():
    d = _ok(IDEAL, frequency=None)
    assert _close(_z(_tr(d)["v2"]), 50)


# ═══════════════════════════════════════════════════════
#  3. KUPLAJLI TRANSFORMATÖR — SAYILAR (iki denklem elle çözülür)
# ═══════════════════════════════════════════════════════

# f = 50 Hz, L₁ = L₂ = 0,1 H, k = 0,5 → M = 0,05 H; primer seri R₁ = 5 Ω, yük R₂ = 10 Ω
L1 = L2 = 0.1
K = 0.5
M = K * math.sqrt(L1 * L2)
COUPLED = SRC + "Rs 1 2 5\nT1 2 0 3 0 COUPLED 100m 100m 0.5\nR1 3 0 10" + GND
COUPLED_SWAPPED = SRC + "Rs 1 2 5\nT1 2 0 0 3 COUPLED 100m 100m 0.5\nR1 3 0 10" + GND


def _coupled_expected(m_signed: float):
    # Primer çevre : (5 + jωL₁)·I₁ + jωM·I₂ = 100
    # Sekonder    : jωM·I₁ + (10 + jωL₂)·I₂ = 0
    return _solve2(5 + 1j * W * L1, 1j * W * m_signed, 1j * W * m_signed, 10 + 1j * W * L2, 100)


def test_coupled_matches_hand_solution():
    d = _ok(COUPLED)
    tr = _tr(d)
    i1, i2 = _coupled_expected(M)
    assert tr["kind"] == "coupled" and tr["a"] is None
    assert tr["k"] == pytest.approx(0.5) and tr["m"] == pytest.approx(0.05)
    assert _close(_z(tr["i1"]), i1)
    assert _close(_z(tr["i2"]), i2)
    # V₁ ve V₂ kuplaj denklemlerinden
    assert _close(_z(tr["v1"]), 1j * W * L1 * i1 + 1j * W * M * i2)
    assert _close(_z(tr["v2"]), 1j * W * M * i1 + 1j * W * L2 * i2)
    # Yük direnci: V₂ = −R·I₂ (I₂ s+ ucundan GİRER, yük akımı −I₂)
    assert _close(_z(tr["v2"]), -10 * i2)


def test_coupled_reversed_dot_flips_sign_of_m():
    """
    s+ ve s− yer değişince nokta ucu yükün öbür ucuna geçer: devredeki bir yük akımına göre
    M'nin işareti ters döner. I₁ aynı kalır (M² değişmez); R üzerindeki akım ve V(3) ters döner.
    """
    d_normal, d_swapped = _ok(COUPLED), _ok(COUPLED_SWAPPED)
    tr_n, tr_s = _tr(d_normal), _tr(d_swapped)
    i1, i2 = _coupled_expected(M)
    # Her iki netlistte de nokta ucu s+ olduğundan, s+'ya giren akım I₂ ve I₁ aynıdır
    assert _close(_z(tr_n["i1"]), i1) and _close(_z(tr_s["i1"]), i1)
    assert _close(_z(tr_n["i2"]), i2) and _close(_z(tr_s["i2"]), i2)
    # Yükten (3 → 0) geçen akım: normalde −I₂ (I₂ düğüm 3'e girer), ters bağlıda +I₂
    ir_n = _z(d_normal["results"]["element_currents"]["R1"]["value"])
    ir_s = _z(d_swapped["results"]["element_currents"]["R1"]["value"])
    assert _close(ir_n, -i2)
    assert _close(ir_s, i2)
    assert _close(ir_s, -ir_n)
    # Düğüm 3'ün gerilimi de ters döner: V(3) = R · (3 → 0 akımı)
    v3_n = _z(d_normal["results"]["node_voltages"]["3"]["value"])
    v3_s = _z(d_swapped["results"]["node_voltages"]["3"]["value"])
    assert _close(v3_n, 10 * (-i2)) and _close(v3_s, 10 * i2)


def test_coupled_floating_secondary_same_numbers():
    net = SRC + "Rs 1 2 5\nT1 2 0 3 4 COUPLED 100m 100m 0.5\nR1 3 4 10" + GND
    d = _ok(net)
    tr = _tr(d)
    i1, i2 = _coupled_expected(M)
    assert tr["floating_secondary"] is True
    assert _close(_z(tr["i1"]), i1) and _close(_z(tr["i2"]), i2)


def test_coupled_needs_frequency():
    resp = _post(COUPLED, frequency=None)
    assert resp.status_code == 200
    d = resp.json()
    assert d["transformer"] is None
    assert any("frekans" in e.lower() for e in d["errors"])


def test_coupled_rms_peak_ratio_and_equal_power():
    rms = _tr(_ok(COUPLED, value_display="RMS"))
    peak = _tr(_ok(COUPLED, value_display="PEAK"))
    assert abs(_z(peak["i1"])) == pytest.approx(math.sqrt(2) * abs(_z(rms["i1"])))
    p_rms = (_z(rms["v1"]) * _z(rms["i1"]).conjugate()).real
    p_peak = 0.5 * (_z(peak["v1"]) * _z(peak["i1"]).conjugate()).real
    assert p_rms == pytest.approx(p_peak)


# ═══════════════════════════════════════════════════════
#  4. YÖNTEM KURALLARI
# ═══════════════════════════════════════════════════════

def test_dc_mode_gives_reason_and_falls_back():
    net = "V1 1 0 DC 10\nR1 1 2 100\nR2 2 0 100\nT1 2 0 3 0 IDEAL 0.5\nR3 3 0 10" + GND
    d = _ok(net, mode="DC", frequency=None)
    assert d["transformer"] is None
    assert any("yalnızca AC" in e for e in d["errors"])
    assert "yalnızca AC" in _text(d)
    # Transformatör açık devre sayılarak kalan devre çözüldü: V(2) = 10 · 100/(100 + 100) = 5 V
    assert d["results"]["node_voltages"]["2"]["value"] == pytest.approx(5)


def test_no_ac_source_gives_reason_and_falls_back():
    net = "V1 1 0 DC 10\nR1 1 2 100\nT1 2 0 3 0 IDEAL 0.5\nR3 3 0 10" + GND
    d = _ok(net, mode="AC_PHASOR")
    assert d["transformer"] is None
    assert any("AC kaynak" in e for e in d["errors"])


def test_transient_rejects_transformer():
    d = _ok(IDEAL, analysis_type="TRANSIENT")
    assert d["transient"] is None
    assert _tr(d)["kind"] == "ideal"
    assert "Geçici durum" in _text(d)


@pytest.mark.parametrize("method", ["NODAL", "MESH", "THEVENIN", "NORTON", "SUPERPOSITION",
                                    "MILLMAN", "POWER", "RESONANCE"])
def test_other_methods_get_note_and_correct_numbers(method):
    extra = {}
    if method in ("THEVENIN", "NORTON"):
        extra["thevenin_terminals"] = {"node_positive": "2", "node_negative": "0"}
    d = _ok(IDEAL, analysis_type=method, **extra)
    assert OTHER_METHOD_NOTE in _text(d)
    tr = _tr(d)
    assert _close(_z(tr["v2"]), 50) and _close(_z(tr["i1"]), 2.5)


def test_transformer_method_has_no_other_method_note():
    assert OTHER_METHOD_NOTE not in _text(_ok(IDEAL))


def test_two_transformers_numbers_correct_and_short_explanation():
    net = (SRC + "T1 1 0 2 0 IDEAL 2\nT2 2 0 3 0 IDEAL 3\nR1 3 0 10" + GND)
    d = _ok(net)
    # V₂ = 2·100 = 200, V₃ = 3·200 = 600, I(R) = 60 A; T2'nin I₁ = 3·60 = 180 A; T1'in I₁ = 2·180 = 360 A
    nv = d["results"]["node_voltages"]
    assert _close(_z(nv["2"]["value"]), 200) and _close(_z(nv["3"]["value"]), 600)
    assert _close(_z(d["results"]["element_currents"]["R1"]["value"]), 60)
    tr = _tr(d)
    assert tr["id"] == "T1" and _close(_z(tr["i1"]), 360)
    assert _close(_z(d["results"]["element_currents"]["T2"]["value"]), 180)
    text = _text(d)
    assert "2 transformatör" in text            # kısa anlatımın sebebi
    assert "Çözücü Sonuçları" in _titles(d)


def test_json_fields_and_results_copy():
    d = _ok(IDEAL)
    tr = d["transformer"]
    assert set(tr) == {"kind", "id", "a", "k", "m", "v1", "v2", "i1", "i2", "floating_secondary"}
    for key in ("v1", "v2", "i1", "i2"):
        assert {"real", "imaginary", "magnitude", "phase_degrees"} <= set(tr[key])
    assert d["results"]["transformer"] == tr
    # Transformatörsüz çözümde alan null
    plain = _ok("V1 1 0 DC 10\nR1 1 0 100" + GND, mode="DC", analysis_type="NODAL", frequency=None)
    assert plain["transformer"] is None


def test_openapi_hides_transformer_method_like_resonance():
    schema = client.get("/openapi.json").json()
    enum = schema["components"]["schemas"]["AnalysisType"]["enum"]
    assert "TRANSFORMER" not in enum


def test_probe_on_transformer_current():
    d = _ok(IDEAL + "\n* PROBE IP1 I(T1)")
    probe = next(p for p in d["results"]["probe_results"] if p["probe_id"] == "IP1")
    assert _close(_z(probe["value"]), 2.5)             # primer akımı I₁


# ═══════════════════════════════════════════════════════
#  5. İDEAL ANLATIM
# ═══════════════════════════════════════════════════════

IDEAL_TITLES = ["Devreyi Tanıyalım", "Dönüştürme Oranı", "Yansıyan Empedans",
                "Primere İndirgenmiş Devre", "Primer Gerilimi", "Sekonder Değerleri",
                "Güç", "Kontrol", "Sonuç"]


def test_ideal_narrative_section_order():
    assert _titles(_ok(IDEAL)) == IDEAL_TITLES


def test_ideal_narrative_adds_impedance_section_only_with_reactive_elements():
    titles = _titles(_ok(IDEAL_RL))
    assert titles[:2] == ["Devreyi Tanıyalım", "Empedanslar ve Fazörler"]
    assert "Empedanslar ve Fazörler" not in _titles(_ok(IDEAL))


def test_ideal_narrative_numbers_match_hand_calculation():
    d = _ok(IDEAL)
    assert "Z₁ = Z₂ / a² = 10 Ω / 0,5² = 40 Ω" in _text(d, "Yansıyan Empedans")
    assert "I₁ = V / Z_top = 100 V / 40 Ω = 2,5 A" in _text(d, "Primere İndirgenmiş Devre")
    assert "V₂ = a · V₁ = 0,5 · 100 V = 50 V" in _text(d, "Sekonder Değerleri")
    assert "I₂ = I₁ / a = 2,5 A / 0,5 = 5 A" in _text(d, "Sekonder Değerleri")
    assert "P₁ = P₂ = 250 W" in _text(d, "Güç")
    assert "V₂ = a·V₁" in _text(d, "Dönüştürme Oranı") and "I₁ = a·I₂" in _text(d, "Dönüştürme Oranı")


def test_ideal_narrative_with_primary_series_resistor():
    d = _ok(IDEAL_SERIES)
    reduced = _text(d, "Primere İndirgenmiş Devre")
    assert "Rs + Z₁ = 50 Ω" in reduced                      # 10 + 40
    assert "I₁ = V / Z_top = 100 V / 50 Ω = 2 A" in reduced
    assert "V₁ = I₁ · Z₁ = 2 A · 40 Ω = 80 V" in _text(d, "Primer Gerilimi")
    # Maksimum güç için a: R_kaynak = R_yük/a² → a = √(10/10) = 1
    assert "a = √(R_yük/R_kaynak)" in reduced and "= 1." in reduced
    assert "P_seri" in _text(d, "Güç") and "40 W" in _text(d, "Güç")


def test_ideal_narrative_no_max_power_note_without_series_resistor():
    assert "R_yük/R_kaynak" not in _text(_ok(IDEAL), "Primere İndirgenmiş Devre")


def test_ideal_narrative_reduces_parallel_load():
    net = SRC + "T1 1 0 2 0 IDEAL 0.5\nR1 2 0 20\nR2 2 0 20" + GND
    d = _ok(net)
    assert "(R1 · R2) / (R1 + R2) = 10 Ω" in _text(d, "Yansıyan Empedans")
    assert _close(_z(_tr(d)["i1"]), 2.5)


def test_ideal_narrative_inductive_load_uses_complex_numbers():
    d = _ok(IDEAL_RL)
    assert "Z₁ = Z₂ / a² = (30 + j40) Ω / 0,5² = 120 + j160 Ω" in _text(d, "Yansıyan Empedans")
    assert "Z₂ = 30 + j40 Ω" in _text(d, "Yansıyan Empedans")


def test_ideal_narrative_peak_display_uses_half_factor():
    d = _ok(IDEAL, value_display="PEAK")
    assert "Bu çözümde AC değerler tepe değer olarak gösterilir." in _text(d, "Devreyi Tanıyalım")
    assert "½·V·I*" in _text(d, "Güç")
    # V tepe = 100·√2 = 141,4 V; P aynı: ½ · 141,4 · 1,768 = 125?  (I₁ = 141,4/40 = 3,536 A → ½·141,4·3,536 = 250 W)
    assert "P₁ = P₂ = 250 W" in _text(d, "Güç")


def test_ideal_narrative_u_note_and_decimal_comma():
    text = _text(_ok(IDEAL))
    assert "Kitaplarda gerilim U ile de gösterilir (U = V)." in text
    assert "0,5" in text and "0.5" not in text


def test_ideal_narrative_floating_secondary_note_and_same_sections():
    d = _ok(IDEAL_FLOAT)
    assert _titles(d) == IDEAL_TITLES
    assert FLOATING_NOTE in _text(d, "Devreyi Tanıyalım")


def test_ideal_narrative_other_method_note_first():
    d = _ok(IDEAL, analysis_type="NODAL")
    first = d["results"]["explanation"][0]["blocks"][0]
    assert first["kind"] == "note" and first["text"] == OTHER_METHOD_NOTE
    assert _titles(d) == IDEAL_TITLES


def test_ideal_narrative_short_when_source_is_on_secondary_side():
    net = "VAC1 2 0 AC_PHASOR(100, 0) RMS\nT1 1 0 2 0 IDEAL 0.5\nR1 1 0 10" + GND
    d = _ok(net)
    tr = _tr(d)
    # Kaynak sekonderde: V₂ = 100 → V₁ = V₂/a = 200 V, I₁ çıkış yönünde
    assert _close(_z(tr["v2"]), 100) and _close(_z(tr["v1"]), 200)
    assert "Çözücü Sonuçları" in _titles(d) and "Yansıyan Empedans" not in _titles(d)
    assert "sekonderde kaynak" in _text(d, "Çözücü Sonuçları")


def test_ideal_narrative_short_when_primary_has_shunt_branch():
    net = SRC + "Rs 1 2 10\nRp 2 0 100\nT1 2 0 3 0 IDEAL 0.5\nR1 3 0 10" + GND
    d = _ok(net)
    # Elle: Z₁ = 40, Rp ‖ Z₁ = 100·40/140 = 28,571 Ω, Z_top = 38,571 Ω, I_kaynak = 100/38,571 = 2,5926 A
    #       V₁ = V − I·Rs = 100 − 25,926 = 74,074 V; V₂ = 37,037 V
    tr = _tr(d)
    assert _close(_z(tr["v1"]), 100 - 10 * 100 / (10 + 100 * 40 / 140), 1e-4)
    assert _close(_z(tr["v2"]), 0.5 * _z(tr["v1"]))
    assert "Çözücü Sonuçları" in _titles(d) and "paralel" in _text(d, "Çözücü Sonuçları")


def test_ideal_narrative_never_contradicts_solver():
    """Anlatımdaki her sonuç satırı çözücünün verdiği sayıyla aynıdır."""
    d = _ok(IDEAL_SERIES)
    tr = _tr(d)
    result_text = _text(d, "Sonuç")
    assert "V₁ = 80 V" in result_text and "V₂ = 40 V" in result_text
    assert "I₁ = 2 A" in result_text and "I₂ = 4 A" in result_text
    assert _close(_z(tr["v1"]), 80)


# ═══════════════════════════════════════════════════════
#  6. KUPLAJLI ANLATIM
# ═══════════════════════════════════════════════════════

COUPLED_TITLES = ["Devreyi Tanıyalım", "Empedanslar ve Fazörler", "Ortak Endüktans", "Nokta Kuralı",
                  "Çevre Denklemleri", "Çözüm", "Eleman Gerilim ve Akımları", "Güç", "Kontrol", "Sonuç"]
XM = W * M                      # X_M = ωM = 314,159 · 0,05 = 15,708 Ω
XL = W * L1                     # X_L1 = X_L2 = 31,416 Ω


def _comma(x: float, fmt: str = ".4g") -> str:
    return format(x, fmt).replace(".", ",")


def test_coupled_narrative_section_order():
    assert _titles(_ok(COUPLED)) == COUPLED_TITLES


def test_coupled_narrative_mutual_inductance():
    d = _ok(COUPLED)
    text = _text(d, "Ortak Endüktans")
    assert "M = k · √(L₁ · L₂) = 0,5 · √(100 mH · 100 mH) = 50 mH" in text      # 0,5 · 0,1 = 0,05 H
    assert f"X_M = ωM = 314,2 rad/s · 50 mH = {_comma(XM)}" in text              # 15,71 Ω


def test_coupled_narrative_loop_equations_show_signs_and_numbers():
    text = _text(_ok(COUPLED), "Çevre Denklemleri")
    assert "Z_seri = 5 Ω" in text and "Z_yük = 10 Ω" in text
    assert "V = (Z_seri + jωL₁)·I₁ + jωM·I₂" in text
    assert "0 = jωM·I₁ + (Z_yük + jωL₂)·I₂" in text
    # (5 + j31,42)·I₁ + j15,71·I₂ = 100  ve  j15,71·I₁ + (10 + j31,42)·I₂ = 0
    assert f"(5 + j{_comma(XL)}) · I₁ + j{_comma(XM)} · I₂ = 100" in text
    assert f"j{_comma(XM)} · I₁ + (10 + j{_comma(XL)}) · I₂ = 0" in text


def test_coupled_narrative_cramer_matches_hand_determinant():
    d = _ok(COUPLED)
    text = _text(d, "Çözüm")
    det = (5 + 1j * XL) * (10 + 1j * XL) - (1j * XM) ** 2           # −690,2 + j471,2
    assert det == pytest.approx(complex(-690.2, 471.2), abs=0.1)
    assert "Δ = |" in text and "Δ₁ = |" in text and "Δ₂ = |" in text
    assert "(−690,2 + j471,2)" in text
    i1, i2 = _coupled_expected(M)
    tr = _tr(d)
    # Anlatımdaki I₁, I₂ büyüklükleri ve çözücü aynı sayılar
    assert "I₁ = Δ₁/Δ" in text and _comma(abs(i1)) in text
    assert _comma(abs(i2)) in text
    assert _close(_z(tr["i1"]), i1) and _close(_z(tr["i2"]), i2)


def test_coupled_narrative_dot_rule_and_current_directions():
    text = _text(_ok(COUPLED), "Nokta Kuralı")
    assert "s+" in text and "GİRER" in text and "−I₂" in text
    assert "M'nin işareti" in text


def test_coupled_narrative_element_voltages_and_power():
    d = _ok(COUPLED)
    i1, i2 = _coupled_expected(M)
    p_load = abs(i2) ** 2 * 10                                         # |I₂|²·R_yük (etkin)
    text = _text(d, "Güç")
    assert f"P_yük = |I₂|²·R_yük = {_comma(p_load)} W" in text
    assert "P₁ + P₂ = 0" in text
    volt = _text(d, "Eleman Gerilim ve Akımları")
    assert "V₂ = −Z_yük·I₂" in volt and "−I₂" in volt


def test_coupled_narrative_peak_display_uses_half_factor():
    d = _ok(COUPLED, value_display="PEAK")
    assert "½·V·I*" in _text(d, "Güç")
    i1, i2 = _coupled_expected(M)
    p_load = 0.5 * (math.sqrt(2) * abs(i2)) ** 2 * 10                  # ½·|I₂m|²·R = aynı güç
    assert f"{_comma(p_load)} W" in _text(d, "Güç")


def test_coupled_narrative_with_capacitor_in_secondary_and_decimal_comma():
    net = SRC + "Rs 1 2 5\nT1 2 0 3 0 COUPLED 100m 100m 0.5\nR1 3 4 10\nC1 4 0 100u" + GND
    d = _ok(net)
    assert _titles(d) == COUPLED_TITLES
    xc = 1.0 / (W * 100e-6)                                            # 31,83 Ω
    z_load = 10 - 1j * xc
    i1, i2 = _solve2(5 + 1j * W * L1, 1j * W * M, 1j * W * M, z_load + 1j * W * L2, 100)
    tr = _tr(d)
    assert _close(_z(tr["i1"]), i1) and _close(_z(tr["i2"]), i2)
    text = _text(d)
    assert "0.5" not in text and "R1 + Z_C1" in text


def test_coupled_floating_secondary_narrative():
    net = SRC + "Rs 1 2 5\nT1 2 0 3 4 COUPLED 100m 100m 0.5\nR1 3 4 10" + GND
    d = _ok(net)
    assert _titles(d) == COUPLED_TITLES
    assert FLOATING_NOTE in _text(d, "Devreyi Tanıyalım")


def test_coupled_narrative_other_method_note():
    d = _ok(COUPLED, analysis_type="MESH")
    assert OTHER_METHOD_NOTE in _text(d, "Devreyi Tanıyalım")
    assert _titles(d) == COUPLED_TITLES


def test_coupled_narrative_short_when_primary_has_parallel_branch():
    net = SRC + "Rs 1 2 5\nRp 2 0 50\nT1 2 0 3 0 COUPLED 100m 100m 0.5\nR1 3 0 10" + GND
    d = _ok(net)
    tr = _tr(d)
    assert "Çözücü Sonuçları" in _titles(d) and "Çevre Denklemleri" not in _titles(d)
    assert "paralel" in _text(d, "Çözücü Sonuçları")
    # Sayılar yine doğru: transformatörün uç denklemleri (V₁, V₂) ve yük (V₂ = −R·I₂) tutarlı
    assert _close(_z(tr["v1"]), 1j * W * L1 * _z(tr["i1"]) + 1j * W * M * _z(tr["i2"]))
    assert _close(_z(tr["v2"]), 1j * W * M * _z(tr["i1"]) + 1j * W * L2 * _z(tr["i2"]))
    assert _close(_z(tr["v2"]), -10 * _z(tr["i2"]))
    # Primer: kaynak 100 V → Rs üzerinden; Rp paralel. KCL: (100 − V₁)/5 = V₁/50 + I₁
    assert _close((100 - _z(tr["v1"])) / 5, _z(tr["v1"]) / 50 + _z(tr["i1"]))


def test_two_transformers_with_coupled_one_short_narrative_numbers_valid():
    net = (SRC + "T1 1 0 2 0 COUPLED 100m 100m 1\nT2 2 0 3 0 IDEAL 1\nR1 3 0 10" + GND)
    d = _ok(net)
    assert "2 transformatör" in _text(d, "Çözücü Sonuçları")
    tr = _tr(d)
    assert _close(_z(tr["v1"]), 100)
    # T2 ideal a = 1 → 10 Ω yük aynen yansır: V₂ = −10·I₂; k = 1 → V₁ = jωL(I₁ + I₂)
    assert _close(_z(tr["v2"]), -10 * _z(tr["i2"]))
    assert _close(_z(tr["v1"]), 1j * W * L1 * (_z(tr["i1"]) + _z(tr["i2"])))


# ═══════════════════════════════════════════════════════
#  7. ALIŞTIRMA SORULARI
# ═══════════════════════════════════════════════════════

def _questions(data: dict) -> dict:
    return {q["id"]: PracticeQuestion(**q) for q in data["results"]["practice"]}


def _expected(q: PracticeQuestion) -> complex:
    return complex(q.expected.real, q.expected.imaginary)


def test_practice_ideal_questions_and_expected_values():
    qs = _questions(_ok(IDEAL))
    assert list(qs) == ["V2", "I1", "I2", "Z1"]
    assert _close(_expected(qs["V2"]), 50)      # a·V₁
    assert _close(_expected(qs["I1"]), 2.5)     # a·I₂
    assert _close(_expected(qs["I2"]), 5)       # V₂/R
    assert _close(_expected(qs["Z1"]), 40)      # R/a²
    assert [qs[k].unit for k in qs] == ["V", "A", "A", "Ω"]
    assert all(q.hint and q.sign_hint for q in qs.values())


def test_practice_ideal_series_values_follow_solver():
    qs = _questions(_ok(IDEAL_SERIES))
    assert _close(_expected(qs["V2"]), 40)
    assert _close(_expected(qs["I1"]), 2)
    assert _close(_expected(qs["I2"]), 4)
    assert _close(_expected(qs["Z1"]), 40)      # yansıyan empedans seri R'yi içermez


def test_practice_ideal_answers_are_checked():
    qs = _questions(_ok(IDEAL))
    for qid, ans in (("V2", "50"), ("V2", "50 V"), ("I1", "2,5"), ("I1", "2500 mA"),
                     ("I2", "5 A"), ("Z1", "40"), ("Z1", "40 Ω")):
        assert check_answer(qs[qid], ans).status == "correct", (qid, ans)
    assert check_answer(qs["V2"], "25").status == "wrong"


def test_practice_ideal_diagnoses_common_mistakes_in_turkish():
    qs = _questions(_ok(IDEAL))
    v1_for_v2 = check_answer(qs["V2"], "100")
    assert v1_for_v2.status != "correct" and "V₁" in v1_for_v2.message
    swapped = check_answer(qs["I1"], "5")                      # I₂ yazılmış
    assert swapped.status != "correct" and "I₂" in swapped.message
    z2 = check_answer(qs["Z1"], "10")                          # Z₂ yazılmış
    assert z2.status != "correct" and "Z₂" in z2.message
    inverse = check_answer(qs["Z1"], "2.5")                    # Z₂·a²: oran ters uygulanmış
    assert inverse.status != "correct" and "a²" in inverse.message


def test_practice_coupled_questions_and_values():
    qs = _questions(_ok(COUPLED))
    assert list(qs) == ["M", "I1", "I2"]
    assert qs["M"].unit == "H" and not qs["M"].is_ac
    assert qs["M"].expected.real == pytest.approx(0.05)
    i1, i2 = _coupled_expected(M)
    assert _close(_expected(qs["I1"]), i1)
    assert _close(_expected(qs["I2"]), i2)
    assert all(q.is_ac and q.frequency == 50 for k, q in qs.items() if k != "M")


def test_practice_coupled_m_answers_in_henry_units():
    qs = _questions(_ok(COUPLED))
    for ans in ("0.05", "0,05 H", "50m", "50 mH", "50000u"):
        assert check_answer(qs["M"], ans).status == "correct", ans
    k_as_m = check_answer(qs["M"], "0.5")
    assert k_as_m.status != "correct" and "kuplaj katsayısı" in k_as_m.message


def test_practice_coupled_current_answers_polar_and_rect():
    qs = _questions(_ok(COUPLED))
    i1, i2 = _coupled_expected(M)
    ang1 = math.degrees(cmath.phase(i1))
    ok_polar = _comma(abs(i1), ".5g") + "∠" + _comma(ang1, ".4f")
    assert check_answer(qs["I1"], ok_polar).status == "correct"
    rect_txt = (_comma(i1.real, ".5g") + ("+" if i1.imag >= 0 else "-") + "j" + _comma(abs(i1.imag), ".5g"))
    assert check_answer(qs["I1"], rect_txt).status == "correct"
    other = _comma(abs(i2), ".5g") + "∠" + _comma(math.degrees(cmath.phase(i2)), ".4f")
    swapped = check_answer(qs["I1"], other)
    assert swapped.status != "correct" and "I₂" in swapped.message


def test_practice_questions_are_same_with_other_method():
    assert list(_questions(_ok(IDEAL, analysis_type="NODAL"))) == ["V2", "I1", "I2", "Z1"]
    assert list(_questions(_ok(COUPLED, analysis_type="THEVENIN",
                               thevenin_terminals={"node_positive": "3", "node_negative": "0"}))) == ["M", "I1", "I2"]


def test_practice_json_has_henry_unit_in_response():
    d = _ok(COUPLED)
    q = next(x for x in d["results"]["practice"] if x["id"] == "M")
    assert q["unit"] == "H" and q["group"] == "main" and q["hint"]


# ═══════════════════════════════════════════════════════
#  8. ÇÖKMEME: iki uç varsayan kodlar transformatörle karşılaşınca
# ═══════════════════════════════════════════════════════

ALL_METHODS = ["NODAL", "MESH", "THEVENIN", "NORTON", "SUPERPOSITION", "MILLMAN",
               "SOURCE_TRANSFORM", "TRANSIENT", "POWER", "RESONANCE", "TRANSFORMER"]
_DC_TRAFO = "V1 1 0 DC 10\nR1 1 2 100\nR2 2 0 100\nT1 2 0 3 0 IDEAL 0.5\nR3 3 0 10" + GND


@pytest.mark.parametrize("method", ALL_METHODS)
@pytest.mark.parametrize("mode", ["DC", "AC_PHASOR"])
def test_every_method_survives_a_transformer(method, mode):
    net = _DC_TRAFO if mode == "DC" else IDEAL_SERIES
    extra = {}
    if method in ("THEVENIN", "NORTON", "SOURCE_TRANSFORM"):
        extra["thevenin_terminals"] = {"node_positive": "2", "node_negative": "0"}
    resp = _post(net, analysis_type=method, mode=mode,
                 frequency=None if mode == "DC" else 50, **extra)
    assert resp.status_code == 200, (method, mode, resp.text[:300])
    d = resp.json()
    assert not any("beklenmeyen" in e for e in d["errors"]), d["errors"]
    if mode == "AC_PHASOR":
        assert _close(_z(_tr(d)["v2"]), 40)
    else:
        assert d["transformer"] is None and d["results"]["explanation"]


def test_switch_and_transformer_together():
    net = (SRC + "S1 1 2 NO\nT1 2 0 3 0 IDEAL 0.5\nR1 3 0 10" + GND)
    d = _ok(net)
    assert _close(_z(_tr(d)["v2"]), 50)          # anahtar t > 0'da kapalı: V₁ = 100 V
    assert "Anahtar Konumu" in _titles(d)
