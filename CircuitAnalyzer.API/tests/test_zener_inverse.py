"""
Faz 4b-3 — Zener Aralığı TERS problemleri (INVERSE mode) testleri.

Sözleşmedeki tüm kitap oraklları (LOAD_FROM_INPUT, INPUT_FROM_LOAD),
aralık cevabı (unique=False), çözümsüz (feasible=False), hatalı giriş
(tek sınır, min >= max, V_İ,min <= V_Z → NODAL yedeği), anlatım ve asistan testleri.
"""

import pytest

from llm.assistant import build_messages, known_values
from models.request import AnalysisMode, AnalysisType
from parser.netlist_parser import parse_netlist
from solver.circuit_solver import solve_circuit

GND = "\n* GND1 - Referans toprak"


def reg_net(vi, rx, vz, ry, izm=None) -> str:
    z_spec = f"ZENER VZ={vz}" + (f" IZM={izm}" if izm is not None else "")
    return f"V1 1 0 DC {vi}\nRX 1 2 {rx}\nD1 0 2 {z_spec}\nRY 2 0 {ry}"


def post_inv(client, netlist, target=None, given_min=None, given_max=None):
    body = {"netlist": netlist + GND, "mode": "DC", "analysis_type": "ZENER_RANGE"}
    if target is not None:
        body["zener_range_target"] = target
    if given_min is not None:
        body["zener_range_given_min"] = given_min
    if given_max is not None:
        body["zener_range_given_max"] = given_max
    r = client.post("/analyze", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def exp_text(d) -> str:
    parts = []
    for s in d["results"]["explanation"]:
        parts.append(s["title"])
        parts += [b["text"] for b in s["blocks"]]
    return "\n".join(parts)


def exp_titles(d):
    return [s["title"] for s in d["results"]["explanation"]]


# ── LOAD_FROM_INPUT (verilen V_İ aralığı → R_Y) ──────────

def test_p178_oracle_load_from_input(client):
    # Kitap s. 178: VZ=40, IZM=40m, RX=2k, 120..200 V → R_Y = 1 kΩ (tek değer)
    d = post_inv(client, reg_net(150, "2k", 40, "1k", "40m"), target="V1", given_min=120, given_max=200)
    assert d["status"] == "success"
    assert d["analysis_type"] == "ZENER_RANGE"
    assert not any("uygulanamadı" in m for m in d["errors"])

    zr = d["zener_range"]
    assert zr is not None
    assert zr["mode"] == "INVERSE"
    assert zr["kind"] == "LOAD_FROM_INPUT"
    assert zr["target_id"] == "V1"
    assert zr["answer_id"] == "RY"
    assert zr["symbol"] == "R_Y"
    assert zr["unit"] == "Ω"
    assert zr["min"] == pytest.approx(1000.0)
    assert zr["max"] == pytest.approx(1000.0)
    assert zr["unique"] is True
    assert zr["feasible"] is True
    assert zr["given"] == {"symbol": "V_İ", "unit": "V", "min": 120.0, "max": 200.0}
    assert zr["plot_min"] == pytest.approx(120.0)
    assert zr["plot_max"] == pytest.approx(200.0)
    assert zr["current_value"] == pytest.approx(1000.0)
    assert zr["current_inside"] is True
    assert zr["x_label"] == "V_İ (V)"
    assert zr["y_label"] == "V_Y (V)"

    steps = {s["symbol"]: s for s in zr["steps"]}
    assert steps["V_X,min"]["value"] == pytest.approx(80.0)
    assert steps["V_X,max"]["value"] == pytest.approx(160.0)
    assert steps["I_X,min"]["value"] == pytest.approx(0.04)
    assert steps["I_X,max"]["value"] == pytest.approx(0.08)
    assert steps["R_Y,min"]["value"] == pytest.approx(1000.0)
    assert steps["R_Y,max"]["value"] == pytest.approx(1000.0)

    # 3 değerli sağlama (verilen V_İ aralığının altı, ortası, üstü)
    assert [c["verdict"] for c in zr["checks"]] == ["BELOW", "OK", "ABOVE"]
    assert zr["checks"][0]["x"] < 120.0 and zr["checks"][0]["state"] == "OFF"
    assert 120.0 < zr["checks"][1]["x"] < 200.0 and zr["checks"][1]["state"] == "ZENER"
    assert zr["checks"][2]["x"] > 200.0 and zr["checks"][2]["state"] == "ZENER"
    assert zr["checks"][2]["i_z"] > 0.04

    # Eğri: V_İ üzerinden, R_Y = 1 kΩ uygulanmış
    curve = zr["curve"]
    assert 195 <= len(curve["x"]) <= 205
    assert curve["x"][0] == 0.0
    assert curve["x"][-1] == pytest.approx(400.0)
    assert curve["v_y"][-1] == pytest.approx(40.0)

    # Anlatım kontrolü
    titles = exp_titles(d)
    assert titles[0] == "Devreyi Tanıyalım"
    assert "Sonuç" in titles
    assert "Sağlama" in titles
    txt = exp_text(d)
    assert "Verilen: 120 V ≤ V_İ ≤ 200 V; aranan: R_Y." in txt
    assert "80 V ≤ V_X ≤ 160 V" in txt
    assert "40 mA" in txt and "80 mA" in txt
    assert "R_Y = 1 kΩ" in txt
    assert "iki koşul aynı değeri veriyor" in txt

    # Sağlama özet satırında " = " olmamalı
    chk_sec = next(s for s in d["results"]["explanation"] if s["title"] == "Sağlama")
    res_block = next(b for b in chk_sec["blocks"] if b["kind"] == "result")
    assert " = " not in res_block["text"]


@pytest.mark.parametrize("vz,izm,rx,gmin,gmax,expected_ry", [
    (30, "30m", "4k", 90, 210, 2000.0),
    (40, "50m", "1k", 120, 170, 500.0),
])
def test_load_from_input_more_oracles(client, vz, izm, rx, gmin, gmax, expected_ry):
    d = post_inv(client, reg_net(100, rx, vz, 750, izm), target="V1", given_min=gmin, given_max=gmax)
    zr = d["zener_range"]
    assert zr["mode"] == "INVERSE"
    assert zr["kind"] == "LOAD_FROM_INPUT"
    assert zr["unique"] is True
    assert zr["feasible"] is True
    assert zr["min"] == pytest.approx(expected_ry)
    assert zr["max"] == pytest.approx(expected_ry)
    assert [c["verdict"] for c in zr["checks"]] == ["BELOW", "OK", "ABOVE"]


# ── INPUT_FROM_LOAD (verilen R_Y aralığı → V_İ) ──────────

@pytest.mark.parametrize("vz,izm,rx,gmin,gmax,expected_vi", [
    (40, "40m", "2k", 500, 1000, 200.0),
    (30, "50m", "1k", 500, 3000, 90.0),
    (60, "30m", "3k", 1200, 3000, 210.0),
])
def test_input_from_load_oracles(client, vz, izm, rx, gmin, gmax, expected_vi):
    # Çizilen V1 keyfi (hatta V_Z'den küçük olsa bile çalışmalı)
    d = post_inv(client, reg_net(10, rx, vz, 1000, izm), target="RY", given_min=gmin, given_max=gmax)
    zr = d["zener_range"]
    assert zr["mode"] == "INVERSE"
    assert zr["kind"] == "INPUT_FROM_LOAD"
    assert zr["target_id"] == "RY"
    assert zr["answer_id"] == "V1"
    assert zr["symbol"] == "V_İ"
    assert zr["unit"] == "V"
    assert zr["x_label"] == "R_Y (Ω)"
    assert zr["unique"] is True
    assert zr["feasible"] is True
    assert zr["min"] == pytest.approx(expected_vi)
    assert zr["max"] == pytest.approx(expected_vi)
    assert zr["given"] == {"symbol": "R_Y", "unit": "Ω", "min": float(gmin), "max": float(gmax)}
    assert zr["plot_min"] == pytest.approx(float(gmin))
    assert zr["plot_max"] == pytest.approx(float(gmax))
    assert zr["current_value"] == pytest.approx(10.0)
    assert zr["current_inside"] is False
    assert [c["verdict"] for c in zr["checks"]] == ["BELOW", "OK", "ABOVE"]
    assert "iki koşul aynı değeri veriyor" in exp_text(d)


def test_input_from_load_rounded_textbook_oracle(client):
    # Kitap yuvarlaması: 4000/11 ≈ 363.636 Ω → ≈205 V (0.01 V içinde ve unique=True)
    d = post_inv(client, reg_net(205, "1.5k", 40, 450, "30m"), target="RY", given_min=363.636, given_max=500)
    zr = d["zener_range"]
    assert zr["kind"] == "INPUT_FROM_LOAD"
    assert zr["feasible"] is True
    assert zr["unique"] is True
    assert zr["min"] == pytest.approx(205.0, abs=0.01)
    assert zr["max"] == pytest.approx(205.0, abs=0.01)
    assert zr["min"] == zr["max"]
    assert zr["current_inside"] is True
    assert [c["verdict"] for c in zr["checks"]] == ["BELOW", "OK", "ABOVE"]


# ── Aralık cevabı (unique = False) ────────────────────────

def test_inverse_range_answer(client):
    # VZ=20, IZM=30m, RX=1k, V_İ 60..80 V → R_Y ∈ [500, 666.67] Ω
    d = post_inv(client, reg_net(70, "1k", 20, 600, "30m"), target="V1", given_min=60, given_max=80)
    zr = d["zener_range"]
    assert zr["mode"] == "INVERSE"
    assert zr["kind"] == "LOAD_FROM_INPUT"
    assert zr["feasible"] is True
    assert zr["unique"] is False
    assert zr["min"] == pytest.approx(500.0)
    assert zr["max"] == pytest.approx(2000.0 / 3.0, rel=1e-4)
    assert zr["current_inside"] is True
    assert [c["verdict"] for c in zr["checks"]] == ["BELOW", "OK", "ABOVE"]
    txt = exp_text(d)
    assert "500 Ω ≤ R_Y ≤ 666,7 Ω olmalıdır." in txt


def test_inverse_unbounded_without_izm(client):
    # I_ZM eksik → üst sınır yok (max=None), feasible=True, unique=False
    d = post_inv(client, reg_net(150, "2k", 40, "1.5k", izm=None), target="V1", given_min=120, given_max=200)
    zr = d["zener_range"]
    assert zr["feasible"] is True
    assert zr["unique"] is False
    assert zr["min"] == pytest.approx(1000.0)
    assert zr["max"] is None
    assert zr["current_inside"] is True
    assert "∞" in exp_text(d)


# ── Çözümsüz (feasible = False) ───────────────────────────

def test_inverse_infeasible(client):
    # VZ=20, IZM=10m, RX=1k, V_İ 40..100 V → lo=1 kΩ, hi=285.7 Ω → feasible=False
    d = post_inv(client, reg_net(60, "1k", 20, 500, "10m"), target="V1", given_min=40, given_max=100)
    assert d["status"] == "success"
    assert d["results"]["node_voltages"]  # Çizilen devrenin NODAL sonuçları hâlâ var
    zr = d["zener_range"]
    assert zr is not None
    assert zr["mode"] == "INVERSE"
    assert zr["feasible"] is False
    assert zr["unique"] is False
    assert zr["min"] == pytest.approx(1000.0)
    assert zr["max"] == pytest.approx(20.0 / 0.07, rel=1e-4)
    assert zr["current_inside"] is False
    assert zr["checks"] == []
    assert "Sağlama" not in exp_titles(d)
    txt = exp_text(d)
    assert "çelişiyor" in txt
    assert "iki koşulu aynı anda sağlayan" in txt


# ── Hatalı giriş → NODAL yedeği + ℹ notu ─────────────────

def _assert_nodal_fallback(d, needle):
    assert d["status"] != "error"
    assert d["zener_range"] is None
    assert d["results"]["node_voltages"]
    notes = [m for m in d["errors"] if m.startswith("ℹ Zener Aralığı uygulanamadı:")]
    assert notes, f"Geri dönüş notu eksik: {d['errors']}"
    assert needle in notes[0]
    assert "Sonuçlar Düğüm Gerilimleri yöntemiyle verildi." in notes[0]


def test_bad_input_only_given_min(client):
    d = post_inv(client, reg_net(150, "2k", 40, "1k", "40m"), target="V1", given_min=120)
    _assert_nodal_fallback(d, "hem alt sınır hem üst sınır")


def test_bad_input_min_ge_max(client):
    d_eq = post_inv(client, reg_net(150, "2k", 40, "1k", "40m"), target="V1", given_min=150, given_max=150)
    _assert_nodal_fallback(d_eq, "alt sınırı üst sınırından küçük")

    d_gt = post_inv(client, reg_net(150, "2k", 40, "1k", "40m"), target="V1", given_min=200, given_max=120)
    _assert_nodal_fallback(d_gt, "alt sınırı üst sınırından küçük")


@pytest.mark.parametrize("gmin", [30, 40])
def test_bad_input_vi_min_le_vz(client, gmin):
    d = post_inv(client, reg_net(150, "2k", 40, "1k", "40m"), target="V1", given_min=gmin, given_max=200)
    _assert_nodal_fallback(d, "zener V_İ,min'de iletime geçemez")


def test_assistant_known_values_inverse():
    parsed = parse_netlist(reg_net(150, "2k", 40, "1k", "40m") + GND)
    results, _, _ = solve_circuit(
        parsed=parsed, mode=AnalysisMode.DC, frequency=None,
        analysis_type=AnalysisType.ZENER_RANGE, thevenin_terminals=None,
        zener_range_target="V1", zener_range_given_min=120.0, zener_range_given_max=200.0,
    )
    assert results.zener_range is not None
    kv = known_values(parsed, results, None, [])
    assert any(abs(v - 1000.0) < 1e-9 for v in kv._typed.get("Ω", ()))
    assert any(abs(v - 120.0) < 1e-9 for v in kv._typed.get("V", ()))
    assert any(abs(v - 200.0) < 1e-9 for v in kv._typed.get("V", ()))
    msgs = build_messages(parsed, results, AnalysisType.ZENER_RANGE, True, None, None,
                          "R_Y neden 1 kΩ çıktı?", [], False, [])
    assert "Zener aralığı" in msgs[0]["content"]
