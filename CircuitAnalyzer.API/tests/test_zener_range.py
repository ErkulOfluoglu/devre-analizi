"""
Faz 4b-2 — Zener Aralığı (analysis_type = "ZENER_RANGE") testleri.

Sözleşmedeki LOAD 1/2, INPUT 1/2, IZM eksik (∞), I_X ≤ I_ZM (∞),
uygulanamayan durumlarda NODAL yedeği, yapısal tanıma (R1/R2),
gizli kimlik sızıntısı, OpenAPI şeması ve asistan testleri.
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


def post_zr(client, netlist, target=None, mode="DC", frequency=None):
    body = {"netlist": netlist + GND, "mode": mode, "analysis_type": "ZENER_RANGE"}
    if target is not None:
        body["zener_range_target"] = target
    if frequency is not None:
        body["frequency"] = frequency
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


# ── LOAD oraklları ────────────────────────────────────────

def test_load_oracle_1(client):
    d = post_zr(client, reg_net(100, "1k", 20, 300, "30m"))
    assert d["status"] == "success"
    assert d["analysis_type"] == "ZENER_RANGE"
    assert not any("uygulanamadı" in m for m in d["errors"])

    # Çizilen devrenin NODAL sonuçları hâlâ yanıtta
    assert d["results"]["node_voltages"]["2"]["value"] == pytest.approx(20.0)
    assert d["results"]["element_currents"]["RX"]["value"] == pytest.approx(0.08)
    assert d["results"]["element_currents"]["RY"]["value"] == pytest.approx(20.0 / 300.0)

    zr = d["zener_range"]
    assert zr is not None
    assert zr["target_id"] == "RY"
    assert zr["kind"] == "LOAD"
    assert zr["symbol"] == "R_Y"
    assert zr["unit"] == "Ω"
    assert zr["min"] == pytest.approx(250.0)
    assert zr["max"] == pytest.approx(400.0)
    assert zr["current_value"] == pytest.approx(300.0)
    assert zr["current_inside"] is True
    assert zr["x_label"] == "R_Y (Ω)"
    assert zr["y_label"] == "V_Y (V)"

    steps = {s["symbol"]: s for s in zr["steps"]}
    assert steps["V_X"]["value"] == pytest.approx(80.0)
    assert steps["I_X"]["value"] == pytest.approx(0.08)
    assert steps["I_Y,max"]["value"] == pytest.approx(0.08)
    assert steps["I_Y,min"]["value"] == pytest.approx(0.05)
    assert steps["R_Y,min"]["value"] == pytest.approx(250.0)
    assert steps["R_Y,max"]["value"] == pytest.approx(400.0)

    # 3 değerli sağlama: alt (OFF), iç (300 Ω, ZENER OK), üst (⚠ ABOVE)
    assert len(zr["checks"]) == 3
    c_below, c_ok, c_above = zr["checks"]
    assert c_below["x"] < 250.0
    assert c_below["state"] == "OFF"
    assert c_below["v_y"] < 20.0
    assert c_below["i_z"] == 0.0
    assert c_below["verdict"] == "BELOW"
    assert "aralığın altında: zener yalıtımda, V_Y < V_Z" in c_below["text"]

    assert c_ok["x"] == pytest.approx(300.0)
    assert c_ok["state"] == "ZENER"
    assert c_ok["v_y"] == pytest.approx(20.0)
    assert c_ok["i_z"] == pytest.approx(40.0 / 3000.0, rel=1e-4)
    assert c_ok["verdict"] == "OK"
    assert "uygun" in c_ok["text"]

    assert c_above["x"] > 400.0
    assert c_above["state"] == "ZENER"
    assert c_above["v_y"] == pytest.approx(20.0)
    assert c_above["i_z"] > 0.03
    assert c_above["verdict"] == "ABOVE"
    assert "⚠" in c_above["text"]
    assert "aralığın üstünde: I_Z > I_ZM (zener zarar görür)" in c_above["text"]

    # Eğri (~200 nokta)
    curve = zr["curve"]
    assert 195 <= len(curve["x"]) <= 205
    assert len(curve["x"]) == len(curve["v_y"]) == len(curve["i_z"])
    assert curve["x"][0] > 0
    assert curve["x"][-1] == pytest.approx(800.0)
    assert curve["v_y"][0] < 20.0 and curve["i_z"][0] == 0.0
    assert curve["v_y"][-1] == pytest.approx(20.0)
    assert curve["i_z"][-1] == pytest.approx(0.08 - 20.0 / 800.0, rel=1e-4)

    # Anlatım: odaklanmış kitap sırası, sıradan Düğüm Denklemleri (KCL) yok
    titles = exp_titles(d)
    assert titles[0] == "Devreyi Tanıyalım"
    assert "Sonuç" in titles
    assert "Sağlama" in titles
    assert "Düğüm Denklemleri (KCL)" not in titles
    t = exp_text(d)
    assert "250 Ω ≤ R_Y ≤ 400 Ω olmalıdır." in t


def test_load_oracle_2(client):
    d = post_zr(client, reg_net(200, "2k", 40, 750, "40m"))
    zr = d["zener_range"]
    assert zr["kind"] == "LOAD"
    assert zr["min"] == pytest.approx(500.0)
    assert zr["max"] == pytest.approx(1000.0)
    assert zr["current_inside"] is True
    assert [c["verdict"] for c in zr["checks"]] == ["BELOW", "OK", "ABOVE"]


# ── INPUT oraklları ───────────────────────────────────────

def test_input_oracle_1(client):
    d = post_zr(client, reg_net(120, "2k", 30, "1k", "40m"), target="V1")
    assert d["status"] == "success"
    zr = d["zener_range"]
    assert zr["target_id"] == "V1"
    assert zr["kind"] == "INPUT"
    assert zr["symbol"] == "V_İ"
    assert zr["unit"] == "V"
    assert zr["x_label"] == "V_İ (V)"
    assert zr["min"] == pytest.approx(90.0)
    assert zr["max"] == pytest.approx(170.0)
    assert zr["current_value"] == pytest.approx(120.0)
    assert zr["current_inside"] is True

    steps = {s["symbol"]: s for s in zr["steps"]}
    assert steps["I_Y"]["value"] == pytest.approx(0.03)
    assert steps["I_X,min"]["value"] == pytest.approx(0.03)
    assert steps["I_X,max"]["value"] == pytest.approx(0.07)
    assert steps["V_İ,min"]["value"] == pytest.approx(90.0)
    assert steps["V_İ,max"]["value"] == pytest.approx(170.0)

    assert [c["verdict"] for c in zr["checks"]] == ["BELOW", "OK", "ABOVE"]
    assert zr["checks"][0]["state"] == "OFF"
    assert zr["checks"][1]["x"] == pytest.approx(120.0)
    assert zr["checks"][1]["state"] == "ZENER"
    assert zr["checks"][2]["state"] == "ZENER"
    assert zr["curve"]["x"][0] == 0.0
    assert zr["curve"]["x"][-1] == pytest.approx(340.0)
    assert "90 V ≤ V_İ ≤ 170 V olmalıdır." in exp_text(d)


def test_input_oracle_2(client):
    d = post_zr(client, reg_net(180, "3k", 20, 500, "30m"), target="V1")
    zr = d["zener_range"]
    assert zr["kind"] == "INPUT"
    assert zr["min"] == pytest.approx(140.0)
    assert zr["max"] == pytest.approx(230.0)
    assert zr["current_inside"] is True
    assert [c["verdict"] for c in zr["checks"]] == ["BELOW", "OK", "ABOVE"]


# ── Üst sınır sonsuz (I_ZM yok veya I_X ≤ I_ZM) ───────────

def test_no_izm_unbounded_load_and_input(client):
    d_load = post_zr(client, reg_net(100, "1k", 20, 300, izm=None))
    zr_l = d_load["zener_range"]
    assert zr_l["min"] == pytest.approx(250.0)
    assert zr_l["max"] is None
    assert len(zr_l["checks"]) == 2
    assert [c["verdict"] for c in zr_l["checks"]] == ["BELOW", "OK"]
    assert zr_l["curve"]["x"][-1] == pytest.approx(750.0)
    assert "I_ZM" in exp_text(d_load) and "∞" in exp_text(d_load)

    d_inp = post_zr(client, reg_net(120, "2k", 30, "1k", izm=None), target="V1")
    zr_i = d_inp["zener_range"]
    assert zr_i["min"] == pytest.approx(90.0)
    assert zr_i["max"] is None
    assert len(zr_i["checks"]) == 2
    assert [c["verdict"] for c in zr_i["checks"]] == ["BELOW", "OK"]
    assert zr_i["curve"]["x"][-1] == pytest.approx(270.0)
    assert "I_ZM" in exp_text(d_inp) and "∞" in exp_text(d_inp)


def test_load_ix_le_izm_unbounded(client):
    # Vi=30, RX=1k, VZ=20 → I_X = 10 mA ≤ I_ZM = 30 mA → I_Y,min ≤ 0 → R_Y,max = ∞
    d = post_zr(client, reg_net(30, "1k", 20, "3k", "30m"))
    zr = d["zener_range"]
    assert zr["min"] == pytest.approx(2000.0)
    assert zr["max"] is None
    assert len(zr["checks"]) == 2
    assert "I_Y,min ≤ 0" in exp_text(d)


# ── Uygulanamayan durumlar → NODAL yedeği + ℹ notu ────────

def _assert_nodal_fallback(d, needle):
    assert d["status"] != "error"
    assert d["zener_range"] is None
    assert d["results"]["node_voltages"]
    notes = [m for m in d["errors"] if m.startswith("ℹ Zener Aralığı uygulanamadı:")]
    assert notes, f"Geri dönüş notu eksik: {d['errors']}"
    assert needle in notes[0]
    assert "Sonuçlar Düğüm Gerilimleri yöntemiyle verildi." in notes[0]
    assert "Zener Aralığı" in exp_titles(d)


def test_inapplicable_extra_resistor(client):
    net = reg_net(100, "1k", 20, 300, "30m") + "\nR3 2 0 500"
    _assert_nodal_fallback(post_zr(client, net), "3 direnç")


def test_inapplicable_plain_si_diode(client):
    net = "V1 1 0 DC 100\nRX 1 2 1k\nD1 0 2 SI\nRY 2 0 300"
    _assert_nodal_fallback(post_zr(client, net), "zener diyot değil")


def test_inapplicable_target_is_rx(client):
    _assert_nodal_fallback(post_zr(client, reg_net(100, "1k", 20, 300, "30m"), target="RX"), "seri direnç")


def test_inapplicable_unknown_target(client):
    _assert_nodal_fallback(post_zr(client, reg_net(100, "1k", 20, 300, "30m"), target="R99"), "R99")


@pytest.mark.parametrize("vi", [15, 20])
def test_inapplicable_load_vi_le_vz(client, vi):
    _assert_nodal_fallback(
        post_zr(client, reg_net(vi, "1k", 20, 300, "30m")),
        "giriş gerilimi V_Z'den büyük olmadıkça zener ters iletime geçemez",
    )


def test_inapplicable_ac_source(client):
    net = "VAC1 1 0 AC_PHASOR(100, 0)\nRX 1 2 1k\nRY 2 0 300"
    _assert_nodal_fallback(
        post_zr(client, net, mode="AC_PHASOR", frequency=50.0),
        "yalnızca DC",
    )


# ── Yapısal tanıma (eleman adları önemsiz) ve gizli kimlik ─

def test_structural_detection_arbitrary_names(client):
    # Eleman adları R1/R2/VS/D9 ve direnç düğüm sıraları karışık (SPICE'ta diyot D ile başlar)
    net = "R2 0 5 300\nVS 9 0 DC 100\nD9 0 5 ZENER VZ=20 IZM=30m\nR1 5 9 1k"
    d = post_zr(client, net)
    zr = d["zener_range"]
    assert zr is not None
    assert zr["target_id"] == "R2"
    assert zr["min"] == pytest.approx(250.0)
    assert zr["max"] == pytest.approx(400.0)
    assert not [s for s in all_strings(d) if "Vdiode" in s]

    d_in = post_zr(client, net, target="VS")
    assert d_in["zener_range"]["kind"] == "INPUT"
    assert d_in["zener_range"]["target_id"] == "VS"
    assert not [s for s in all_strings(d_in) if "Vdiode" in s]


def test_openapi_hides_zener_range(client):
    schema = client.get("/openapi.json").json()
    assert "ZENER_RANGE" not in schema["components"]["schemas"]["AnalysisType"]["enum"]


def test_assistant_supports_zener_range():
    parsed = parse_netlist(reg_net(100, "1k", 20, 300, "30m") + GND)
    results, _, _ = solve_circuit(
        parsed=parsed, mode=AnalysisMode.DC, frequency=None,
        analysis_type=AnalysisType.ZENER_RANGE, thevenin_terminals=None,
    )
    assert results.zener_range is not None
    msgs = build_messages(parsed, results, AnalysisType.ZENER_RANGE, True, None, None,
                          "R_Y neden en az 250 ohm olmalı?", [], False, [])
    assert "Zener aralığı" in msgs[0]["content"]
    assert "0 ≤ I_Z ≤ I_ZM" in msgs[0]["content"]
    kv = known_values(parsed, results, None, [])
    assert any(abs(v - 250.0) < 1e-9 for v in kv._typed.get("Ω", ()))
    assert any(abs(v - 400.0) < 1e-9 for v in kv._typed.get("Ω", ()))
