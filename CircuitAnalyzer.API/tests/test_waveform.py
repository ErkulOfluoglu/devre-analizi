"""
Faz 4c-1 — Dalga Şekli (analysis_type = "WAVEFORM") ve SQUARE / TRIANGLE kaynak testleri.

Kitap referansları (Selek, Elektronik-1):
  - Yarım dalga doğrultucu (Si ve ideal, pozitif ve negatif yön)
  - Tam dalga (köprü) doğrultucu (4 Si diyot, yüzen kaynak)
  - Kare dalga doğrultucu ve ön gerilimli kırpıcı (s. 134: Si + Ge + 3 V = 4 V eşik)
  - Üçgen dalga yarım dalga doğrultucu
  - Uygunluk kapıları, gizli kimlik sızıntısı, OpenAPI uyumu, yapay zekâ bağlamı
"""

import math
import time

import pytest

from llm.assistant import build_messages, known_values
from models.request import AnalysisMode, AnalysisType
from parser.netlist_parser import ElementType, parse_netlist
from solver.circuit_solver import solve_circuit

GND = "\n* GND1 - Referans toprak"

HALF_SI = "V1 1 0 SINE(0 10 50)\nD1 1 2 SI\nR1 2 0 1k"
HALF_IDEAL = "V1 1 0 SINE(0 10 50)\nD1 1 2 IDEAL\nR1 2 0 1k"
HALF_NEG_SI = "V1 1 0 SINE(0 10 50)\nD1 2 1 SI\nR1 2 0 1k"

# Tam dalga köprü doğrultucu (4 özdeş Si diyot, yüzen kaynak 1–2, yük R1: köprü+ (3) → GND (0)):
#   Pozitif alternans (V1 = +10 V): 1 → D1(1→3) → R1(3→0) → D4(0→2) → 2.
#     KVL: −10 + 0,7 + V_R1 + 0,7 = 0 ⇒ V_R1 = V(3) = +8,6 V; D2 (2→3) ve D3 (0→1) ters polarmada (OFF).
#   Negatif alternans (V1 = −10 V, V2−V1 = +10 V): 2 → D2(2→3) → R1(3→0) → D3(0→1) → 1.
#     KVL: −10 + 0,7 + V_R1 + 0,7 = 0 ⇒ V_R1 = V(3) = +8,6 V; D1 (1→3) ve D4 (0→2) ters polarmada (OFF).
#   Kitap formülü: V_DC = 0,636·(10 − 2·0,7) = 0,636·8,6 = 5,4696 ≈ 5,470 V.
BRIDGE_SI = (
    "V1 1 2 SINE(0 10 50)\n"
    "D1 1 3 SI\n"
    "D2 2 3 SI\n"
    "D3 0 1 SI\n"
    "D4 0 2 SI\n"
    "R1 3 0 1k"
)

SQUARE_SI = "V1 1 0 SQUARE(10 -15 1k)\nD1 1 2 SI\nR1 2 0 1k"

# Kitap s. 134 ön gerilimli kırpıcı: seri Si (0,7 V) + Ge (0,3 V) + iletime karşı koyan 3 V DC = 4 V eşik.
#   v_in = +10 V → KVL: −10 + 0,7 + 0,3 + 3 + V_O = 0 ⇒ V_O = +6 V.
#   v_in = −10 V → diyotlar ters polarmada (OFF) ⇒ V_O = 0 V.
BIASED_CLIPPER = (
    "V1 1 0 SQUARE(10 -10 1k)\n"
    "D1 1 2 SI\n"
    "D2 2 3 GE\n"
    "V2 3 4 DC 3\n"
    "R1 4 0 1k"
)

TRIANGLE_SI = "V1 1 0 TRIANGLE(10 1k)\nD1 1 2 SI\nR1 2 0 1k"


def analyze(client, netlist, analysis_type="WAVEFORM", mode="AC_TIME", status=200, **extra):
    body = {"netlist": netlist + GND, "mode": mode, "analysis_type": analysis_type}
    body.update(extra)
    r = client.post("/analyze", json=body)
    assert r.status_code == status, r.text
    return r.json()


def expl_text(d):
    parts = []
    for s in d["results"]["explanation"]:
        parts.append(s["title"])
        parts += [b["text"] for b in s["blocks"]]
    return "\n".join(parts)


def all_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from all_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from all_strings(v)


# ── Ayrıştırıcı ──────────────────────────────────────────

def test_parse_square_and_triangle_si_suffixes():
    p = parse_netlist("V1 1 0 SQUARE(10 -15 1k)\nV2 2 0 TRIANGLE(500m 2.5k)\nR1 1 0 1k" + GND)
    assert not p.errors
    v1 = next(e for e in p.elements if e.id == "V1")
    v2 = next(e for e in p.elements if e.id == "V2")
    assert v1.element_type == ElementType.AC_SOURCE_SQUARE
    assert v1.params["v1"] == pytest.approx(10.0)
    assert v1.params["v2"] == pytest.approx(-15.0)
    assert v1.params["frequency"] == pytest.approx(1000.0)
    assert v2.element_type == ElementType.AC_SOURCE_TRIANGLE
    assert v2.params["amplitude"] == pytest.approx(0.5)
    assert v2.params["frequency"] == pytest.approx(2500.0)


# ── Orakıllar ────────────────────────────────────────────

def test_half_wave_si_oracle(client):
    d = analyze(client, HALF_SI)
    wf = d["waveform"]
    assert wf is not None
    assert wf["source_id"] == "V1"
    assert wf["shape"] == "SINE"
    assert wf["frequency"] == pytest.approx(50.0)
    assert wf["period"] == pytest.approx(0.02)
    assert wf["output_id"] == "R1"
    assert wf["output_label"] == "V_O (R1)"
    assert len(wf["t"]) == 400
    assert len(wf["v_in"]) == 400
    assert len(wf["v_out"]) == 400

    assert wf["v_out_max"] == pytest.approx(9.3, abs=1e-6)
    assert wf["v_out_min"] == pytest.approx(0.0, abs=1e-6)

    # Kesin V_DC: (1 / 2π) [2·10·cos(θ₁) − 0.7·(π − 2θ₁)], θ₁ = arcsin(0.07)
    theta1 = math.asin(0.07)
    exact_vdc = (2.0 * 10.0 * math.cos(theta1) - 0.7 * (math.pi - 2.0 * theta1)) / (2.0 * math.pi)
    assert wf["v_dc_numeric"] == pytest.approx(exact_vdc, rel=0.01)

    bf = wf["book_formula"]
    assert bf is not None
    assert bf["name"] == "Yarım dalga doğrultucu"
    assert bf["value"] == pytest.approx(2.9574, abs=1e-3)
    assert "0,318" in bf["text"]

    assert wf["conduction_angle_deg"] == pytest.approx(math.degrees(theta1), abs=0.05)
    assert wf["levels"] is None
    assert len(wf["diodes"]) == 1 and wf["diodes"][0]["id"] == "D1"
    assert any(iv["state"] == "ON" for iv in wf["diodes"][0]["intervals"])
    assert any(iv["state"] == "OFF" for iv in wf["diodes"][0]["intervals"])

    # Pozitif tepe anı sonuçları
    assert d["results"]["node_voltages"]["2"]["value"] == pytest.approx(9.3, abs=1e-6)
    assert d["results"]["element_currents"]["R1"]["value"] == pytest.approx(9.3e-3, abs=1e-6)

    txt = expl_text(d)
    assert "Düğüm gerilimleri pozitif tepe anındaki değerlerdir" in txt
    assert "Kitap formülü" in txt
    assert "Ortalama (DC) Değer" in txt
    assert not [s for s in all_strings(d) if "Vdiode" in s]


def test_half_wave_ideal_oracle(client):
    d = analyze(client, HALF_IDEAL)
    wf = d["waveform"]
    assert wf["v_out_max"] == pytest.approx(10.0, abs=1e-6)
    assert wf["v_out_min"] == pytest.approx(0.0, abs=1e-6)
    assert wf["v_dc_numeric"] == pytest.approx(10.0 / math.pi, rel=0.01)
    assert wf["book_formula"]["value"] == pytest.approx(3.18, abs=1e-3)
    assert wf["conduction_angle_deg"] == pytest.approx(0.0, abs=0.05)


def test_negative_half_wave_si_oracle(client):
    d = analyze(client, HALF_NEG_SI)
    wf = d["waveform"]
    assert wf["v_out_min"] == pytest.approx(-9.3, abs=1e-6)
    assert wf["v_out_max"] == pytest.approx(0.0, abs=1e-6)
    assert wf["v_dc_numeric"] < -2.8


def test_bridge_si_oracle_and_performance(client):
    t0 = time.perf_counter()
    d = analyze(client, BRIDGE_SI)
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"Köprü taraması 1 sn sınırını aştı: {elapsed:.3f} s"

    wf = d["waveform"]
    assert wf["v_out_max"] == pytest.approx(8.6, abs=1e-6)
    assert wf["v_out_min"] == pytest.approx(0.0, abs=1e-6)
    bf = wf["book_formula"]
    assert bf is not None
    assert bf["name"] == "Tam dalga (köprü) doğrultucu"
    assert bf["value"] == pytest.approx(0.636 * 8.6, abs=1e-3)
    assert "0,636" in bf["text"]

    # Her iki yarım periyotta pozitif çıkış (k=50: T/4, k=150: 3T/4)
    assert wf["v_out"][50] == pytest.approx(8.6, abs=1e-6)
    assert wf["v_out"][150] == pytest.approx(8.6, abs=1e-6)
    assert not [s for s in all_strings(d) if "Vdiode" in s]


def test_square_wave_oracle(client):
    d = analyze(client, SQUARE_SI)
    wf = d["waveform"]
    assert wf["shape"] == "SQUARE"
    assert wf["book_formula"] is None
    assert wf["conduction_angle_deg"] is None
    assert wf["levels"] is not None and len(wf["levels"]) == 2
    assert wf["levels"][0]["v_in"] == pytest.approx(10.0)
    assert wf["levels"][0]["v_out"] == pytest.approx(9.3, abs=1e-6)
    assert wf["levels"][0]["states"] == {"D1": "ON"}
    assert wf["levels"][1]["v_in"] == pytest.approx(-15.0)
    assert wf["levels"][1]["v_out"] == pytest.approx(0.0, abs=1e-6)
    assert wf["levels"][1]["states"] == {"D1": "OFF"}
    # Tam yarı periyot sınırı T/2 = 0.0005 s örneklenmiş olmalı
    assert wf["t"][100] == pytest.approx(0.0005, abs=1e-9)
    assert wf["v_out"][0] == pytest.approx(9.3, abs=1e-6)
    assert wf["v_out"][100] == pytest.approx(0.0, abs=1e-6)


def test_book_p134_biased_clipper_oracle(client):
    d = analyze(client, BIASED_CLIPPER)
    wf = d["waveform"]
    assert wf["levels"] is not None
    assert wf["levels"][0]["v_out"] == pytest.approx(6.0, abs=1e-6)
    assert wf["levels"][1]["v_out"] == pytest.approx(0.0, abs=1e-6)
    assert wf["v_out_max"] == pytest.approx(6.0, abs=1e-6)
    assert wf["v_out_min"] == pytest.approx(0.0, abs=1e-6)
    assert "4 V" in expl_text(d)


def test_triangle_half_wave_si_oracle(client):
    d = analyze(client, TRIANGLE_SI)
    wf = d["waveform"]
    assert wf["shape"] == "TRIANGLE"
    assert wf["book_formula"] is None
    assert wf["v_out_max"] == pytest.approx(9.3, abs=1e-6)
    assert wf["v_out_min"] == pytest.approx(0.0, abs=1e-6)
    # Üçgen dalgada 0 → 10 V çıkışı T/4 süresinde doğrusaldır; 0,7 V → (0,7/10)·90° = 6,3°
    assert wf["conduction_angle_deg"] == pytest.approx(6.3, abs=0.1)


def test_custom_waveform_output_element(client):
    net = "V1 1 0 SINE(0 10 50)\nD1 1 2 SI\nR1 2 3 1k\nR2 3 0 2k"
    d = analyze(client, net, waveform_output="R1")
    wf = d["waveform"]
    assert wf["output_id"] == "R1"
    assert wf["output_label"] == "V_O (R1)"
    assert wf["v_out_max"] == pytest.approx(9.3 * (1.0 / 3.0), abs=1e-4)


# ── Kapılar ve geri dönüşler ─────────────────────────────

def test_waveform_without_diode_falls_back(client):
    net = "V1 1 0 DC 10\nR1 1 2 1k\nR2 2 0 1k"
    d = analyze(client, net, analysis_type="WAVEFORM", mode="DC", status=200)
    assert d["waveform"] is None
    assert any("Dalga Şekli yöntemi diyotlu devreler içindir" in m for m in d["errors"])
    assert d["results"]["node_voltages"]["2"]["value"] == pytest.approx(5.0)


def test_waveform_with_capacitor_refused(client):
    net = "V1 1 0 SINE(0 10 50)\nD1 1 2 SI\nR1 2 0 1k\nC1 2 0 100u"
    d = analyze(client, net, analysis_type="WAVEFORM", mode="AC_TIME", status=422)
    assert "kondansatör" in d["detail"]


@pytest.mark.parametrize("net", [SQUARE_SI, TRIANGLE_SI, "V1 1 0 SQUARE(5 -5 1k)\nR1 1 0 1k"])
def test_square_triangle_refused_outside_waveform(client, net):
    d = analyze(client, net, analysis_type="NODAL", mode="DC", status=422)
    assert d["detail"] == "Kare/üçgen dalga kaynağı yalnızca 'Dalga Şekli' yöntemiyle çözülür."


def test_diode_sine_with_nodal_new_refusal_text(client):
    d = analyze(client, HALF_SI, analysis_type="NODAL", mode="AC_TIME", frequency=50, status=422)
    assert d["detail"] == "Diyotlu devrelerde AC/kare/üçgen kaynak için 'Dalga Şekli' yöntemini seçin."


def test_openapi_hides_waveform(client):
    schema = client.get("/openapi.json").json()
    assert "WAVEFORM" not in schema["components"]["schemas"]["AnalysisType"]["enum"]
    assert "waveform_output" not in schema["components"]["schemas"]["AnalysisRequest"]["properties"]
    assert "waveform" not in schema["components"]["schemas"]["AnalysisResponse"]["properties"]


def test_assistant_supports_waveform():
    parsed = parse_netlist(HALF_SI + GND)
    results, _, _ = solve_circuit(
        parsed, AnalysisMode.AC_TIME, 50.0, AnalysisType.WAVEFORM, None, None, [],
    )
    assert results.waveform is not None
    msgs = build_messages(parsed, results, AnalysisType.WAVEFORM, False, 50.0, None,
                          "V_DC nasıl bulundu?", [], False, [])
    sys_msg = msgs[0]["content"]
    assert "Dalga şekli" in sys_msg
    assert "0,318" in sys_msg
    kv = known_values(parsed, results, 50.0, [sys_msg])
    assert kv is not None


# ── Polarite ve hız düzeltmeleri ─────────────────────────

def test_grounded_load_pin_order_independent(client):
    # UI'da döndürülmüş yük (R1 0 2 1k), R1 2 0 1k ile aynı pozitif çıkışı vermeli
    d_norm = analyze(client, HALF_SI)["waveform"]
    d_rot = analyze(client, "V1 1 0 SINE(0 10 50)\nD1 1 2 SI\nR1 0 2 1k")["waveform"]
    assert d_rot["output_label"] == "V_O (R1)"
    assert d_rot["v_out_max"] == pytest.approx(9.3, abs=1e-6)
    assert d_rot["v_out_min"] == pytest.approx(0.0, abs=1e-6)
    assert d_rot["v_dc_numeric"] == pytest.approx(d_norm["v_dc_numeric"], abs=1e-6)
    assert d_rot["book_formula"]["value"] == pytest.approx(2.9574, abs=1e-3)
    assert d_rot["v_out"] == pytest.approx(d_norm["v_out"], abs=1e-6)

    # Diyot ters çevrildiğinde (gerçek negatif doğrultucu) çıkış yine negatif kalmalı
    d_neg = analyze(client, "V1 1 0 SINE(0 10 50)\nD1 2 1 SI\nR1 0 2 1k")["waveform"]
    assert d_neg["v_out_min"] == pytest.approx(-9.3, abs=1e-6)
    assert d_neg["v_out_max"] == pytest.approx(0.0, abs=1e-6)
    assert d_neg["book_formula"]["value"] == pytest.approx(-2.9574, abs=1e-3)


def test_six_zener_sweep_speed_and_exact_match():
    from solver.waveform import _FastSampler, detect_waveform_circuit, eval_source

    net = (
        "V1 1 0 SINE(0 50 50)\n"
        "R0 1 2 1k\n"
        "D1 0 2 ZENER VZ=6\n"
        "D2 0 2 ZENER VZ=7\n"
        "D3 0 2 ZENER VZ=8\n"
        "D4 0 2 ZENER VZ=9\n"
        "D5 0 2 ZENER VZ=10\n"
        "D6 0 2 ZENER VZ=11\n"
        "R1 2 0 1k"
    )
    parsed = parse_netlist(net + GND)
    # Isınma (import / lcapy ilk yükleme) sonrası süreyi ölç
    solve_circuit(parsed, AnalysisMode.AC_TIME, 50.0, AnalysisType.WAVEFORM, None, None, [])
    t0 = time.perf_counter()
    results, _, errs = solve_circuit(
        parsed, AnalysisMode.AC_TIME, 50.0, AnalysisType.WAVEFORM, None, None, [],
    )
    elapsed = time.perf_counter() - t0
    assert not errs
    wf = results.waveform
    assert wf is not None
    assert elapsed < 1.0, f"Altı zenerli tarama 1 sn sınırını aştı: {elapsed:.3f} s"
    assert wf.v_out_max == pytest.approx(6.0, abs=1e-6)
    assert wf.v_out_min == pytest.approx(-0.7, abs=1e-6)

    # Önceki-durum kısayolunun 20 örnekte tam aramayla birebir aynı V_O verdiğini doğrula
    setup, _ = detect_waveform_circuit(parsed, 50.0, None)
    sampler = _FastSampler(parsed, setup)
    for k in range(0, len(wf.t), 20):
        vin = eval_source(setup, wf.t[k])
        sampler._last_state = None
        pt_full = sampler.solve_at(vin)
        assert wf.v_out[k] == pytest.approx(pt_full.v_out, abs=1e-6)

