"""
Faz 4c-2 — Kenetleyiciler (clampers) Dalga Şekli (WAVEFORM) testleri.

Kitap orakılları (Selek, Elektronik-1):
  - p151, p152, p154, p156, p158, Q11, Q13, Q15, Q16
Diğer denetimler:
  - Hiç iletime geçmeyen diyot reddi
  - Eleman uç sırası ve diyot/DC kaynak sırası değişmezliği + polarite tersleme
  - Kitabın 3 kontrolü (salınım eşitliği, kayma yönü, 0 V seviyesi)
  - Sinüs kenetleyici (tüm aralıklar OFF, tepe tazeleme notu)
  - Topoloji reddi (iki kondansatör, fazladan seri direnç, zener diyot, yanlış waveform_output)
  - Anlık görüntü (y = V_K, diyot ON, anlatım / JSON tutarlılığı, tek '=' kuralı)
  - Faz 4c-1 regresyonları (yarım dalga Si ve altı zenerli kırpıcı)
"""

import json
import time

import pytest

from llm.assistant import build_messages, known_values
from models.request import AnalysisMode, AnalysisType
from parser.netlist_parser import parse_netlist
from solver.circuit_solver import solve_circuit

GND = "\n* GND1 - Referans toprak"


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


# ── Kitap orakılları ──────────────────────────────────────
# Her devre: (ad, netlist, beklenen_v_out_1, beklenen_v_out_2, beklenen_v_c, beklenen_v_k, rc_note_beklenir_mi)
BOOK_ORACLES = [
    (
        "p151",
        "V1 1 0 SQUARE(10 -15 1k)\nC1 1 2 100u\nD1 2 0 IDEAL\nR1 2 0 100k",
        0.0, -25.0, 10.0, 0.0, False,
    ),
    (
        "p152",
        "V1 1 0 SQUARE(10 -15 1k)\nC1 1 2 100u\nD1 0 2 IDEAL\nR1 2 0 100k",
        25.0, 0.0, -15.0, 0.0, False,
    ),
    (
        "p154",
        "V1 1 0 SQUARE(10 -15 1k)\nC1 1 2 100u\nD1 0 2 SI\nR1 2 0 100k",
        24.3, -0.7, -14.3, -0.7, False,
    ),
    (
        "p156",
        "V1 1 0 SQUARE(20 -15 1k)\nC1 1 2 100u\nD1 2 3 IDEAL\nV2 3 0 DC 5\nR1 2 0 100k",
        5.0, -30.0, 15.0, 5.0, False,
    ),
    (
        "p158",
        "V1 1 0 SQUARE(25 -10 1k)\nC1 1 2 100u\nD1 3 2 GE\nV2 0 3 DC 3\nR1 2 0 100k",
        31.7, -3.3, -6.7, -3.3, False,
    ),
    (
        "Q11",
        "V1 1 0 SQUARE(5 -15 1k)\nC1 1 2 100u\nD1 0 2 GE\nR1 2 0 100k",
        19.7, -0.3, -14.7, -0.3, False,
    ),
    (
        "Q13",
        "V1 1 0 SQUARE(10 -5 1k)\nC1 1 2 100u\nD1 2 3 SI\nV2 3 0 DC 3\nR1 2 0 100k",
        3.7, -11.3, 6.3, 3.7, False,
    ),
    (
        "Q15",
        "V1 1 0 SQUARE(15 -5 1k)\nC1 1 2 100u\nD1 2 3 IDEAL\nV2 0 3 DC 3\nR1 2 0 100k",
        -3.0, -23.0, 18.0, -3.0, False,
    ),
    (
        "Q16",
        "V1 1 0 SQUARE(-6 15 250)\nC1 1 2 1u\nD1 3 2 IDEAL\nV2 3 0 DC 4\nR1 2 0 1k",
        4.0, 25.0, -10.0, 4.0, True,
    ),
]


@pytest.mark.parametrize(
    "name,netlist,exp_vo1,exp_vo2,exp_vc,exp_vk,expect_rc_note",
    BOOK_ORACLES,
    ids=[x[0] for x in BOOK_ORACLES],
)
def test_book_clamper_oracles(client, name, netlist, exp_vo1, exp_vo2, exp_vc, exp_vk, expect_rc_note):
    d = analyze(client, netlist)
    wf = d["waveform"]
    assert wf is not None
    assert wf["book_formula"] is None
    assert wf["conduction_angle_deg"] is None
    assert wf["levels"] is not None and len(wf["levels"]) == 2
    assert wf["levels"][0]["v_out"] == pytest.approx(exp_vo1, abs=1e-6)
    assert wf["levels"][1]["v_out"] == pytest.approx(exp_vo2, abs=1e-6)
    assert wf["v_out_max"] == pytest.approx(max(exp_vo1, exp_vo2), abs=1e-6)
    assert wf["v_out_min"] == pytest.approx(min(exp_vo1, exp_vo2), abs=1e-6)
    assert wf["v_dc_numeric"] == pytest.approx(0.5 * (exp_vo1 + exp_vo2), abs=1e-6)

    cl = wf["clamper"]
    assert cl is not None
    assert cl["v_c"] == pytest.approx(exp_vc, abs=1e-6)
    assert abs(cl["v_c"]) == pytest.approx(abs(exp_vc), abs=1e-6)
    assert cl["v_c_plus_side"] == ("INPUT" if exp_vc > 0 else "OUTPUT")
    assert cl["v_k"] == pytest.approx(exp_vk, abs=1e-6)
    assert cl["pinned"] == ("TOP" if exp_vc > 0 else "BOTTOM")
    assert cl["shift"] == ("DOWN" if exp_vc > 0 else "UP")
    assert cl["input_swing"] == pytest.approx(cl["output_swing"], abs=1e-6)
    assert [c["name"] for c in cl["checks"]] == [
        "Salınım eşitliği",
        "Kayma yönü",
        "0 V seviyesi",
    ]
    assert cl["checks"][0]["ok"] is True
    assert cl["checks"][1]["ok"] is True
    if expect_rc_note:
        assert cl["rc_note"] is not None
        assert "τ = RC = 1 ms" in cl["rc_note"]
        assert "T = 4 ms" in cl["rc_note"]
    else:
        assert cl["rc_note"] is None

    # Anlık görüntü: düğüm y = V_K, diyot ON ve I_D = 0, JSON/anlatım sağlam
    assert d["results"]["node_voltages"]["2"]["value"] == pytest.approx(exp_vk, abs=1e-6)
    assert len(d["diodes"]) == 1
    assert d["diodes"][0]["state"] == "ON"
    assert d["diodes"][0]["i"] == pytest.approx(0.0, abs=1e-12)

    # Anlatım 6 bölüm ve her "result" bloğu tek " = " içerir
    secs = d["results"]["explanation"]
    assert [s["title"] for s in secs] == [
        "Devreyi Tanıyalım",
        "İletim Koşulu",
        "İletim Alternansı",
        "Yalıtım Alternansı",
        "Kontroller (kitabın 3 kriteri)",
        "Çıkış Dalga Şekli",
    ]
    for s in secs:
        for b in s["blocks"]:
            if b["kind"] == "result":
                # Adım özeti ilk ve son parçayı birleştirir: birden fazla " = " olmamalı
                # (kontrol sayımı satırında hiç olmayabilir).
                assert b["text"].count(" = ") <= 1, f"{name}: {b['text']}"
    json.dumps(d, allow_nan=False)


def test_clamper_never_conducts_refused(client):
    # İdeal y→gnd, +30 V ön gerilim; giriş 10/−15 → v_i,max = 10 ≤ V_K = 30
    net = "V1 1 0 SQUARE(10 -15 1k)\nC1 1 2 100u\nD1 2 3 IDEAL\nV2 3 0 DC 30\nR1 2 0 100k"
    d = analyze(client, net, status=422)
    assert "hiç iletime geçmez" in d["detail"]
    assert "kenetleme olmaz" in d["detail"]

    # Alt kenetleme tarafı: gnd→y, −20 V ön gerilim; giriş 10/−15 → v_i,min = −15 ≥ V_K = −20
    net2 = "V1 1 0 SQUARE(10 -15 1k)\nC1 1 2 100u\nD1 3 2 IDEAL\nV2 0 3 DC 20\nR1 2 0 100k"
    d2 = analyze(client, net2, status=422)
    assert "hiç iletime geçmez" in d2["detail"]


def test_clamper_orientation_invariance_and_bias_flip(client):
    base = analyze(
        client,
        "V1 1 0 SQUARE(20 -15 1k)\nC1 1 2 100u\nD1 2 3 IDEAL\nV2 3 0 DC 5\nR1 2 0 100k",
    )["waveform"]

    # C1 uç sırası ters: C1 2 1
    c_rev = analyze(
        client,
        "V1 1 0 SQUARE(20 -15 1k)\nC1 2 1 100u\nD1 2 3 IDEAL\nV2 3 0 DC 5\nR1 2 0 100k",
    )["waveform"]
    assert c_rev["v_out"] == pytest.approx(base["v_out"], abs=1e-6)
    assert c_rev["clamper"]["v_c"] == pytest.approx(base["clamper"]["v_c"], abs=1e-6)

    # R1 uç sırası ters: R1 0 2
    r_rev = analyze(
        client,
        "V1 1 0 SQUARE(20 -15 1k)\nC1 1 2 100u\nD1 2 3 IDEAL\nV2 3 0 DC 5\nR1 0 2 100k",
    )["waveform"]
    assert r_rev["v_out"] == pytest.approx(base["v_out"], abs=1e-6)

    # Seri DC kaynak y tarafında, diyot toprak tarafında (y — V2 — 3 — D1 — 0)
    swapped = analyze(
        client,
        "V1 1 0 SQUARE(20 -15 1k)\nC1 1 2 100u\nV2 2 3 DC 5\nD1 3 0 IDEAL\nR1 2 0 100k",
    )
    assert swapped["waveform"]["v_out"] == pytest.approx(base["v_out"], abs=1e-6)
    assert swapped["waveform"]["clamper"]["v_k"] == pytest.approx(5.0, abs=1e-6)
    # Ara düğüm tutarlılığı: D1(3→0) ideal iletimde → V(3) = 0, V(2) = 5
    assert swapped["results"]["node_voltages"]["3"]["value"] == pytest.approx(0.0, abs=1e-6)
    assert swapped["results"]["node_voltages"]["2"]["value"] == pytest.approx(5.0, abs=1e-6)

    # Ön gerilim polaritesi ters çevrilince V_K = −5 V olur
    flipped = analyze(
        client,
        "V1 1 0 SQUARE(20 -15 1k)\nC1 1 2 100u\nD1 2 3 IDEAL\nV2 0 3 DC 5\nR1 2 0 100k",
    )["waveform"]
    assert flipped["clamper"]["v_k"] == pytest.approx(-5.0, abs=1e-6)
    assert flipped["clamper"]["v_c"] == pytest.approx(25.0, abs=1e-6)
    assert flipped["levels"][0]["v_out"] == pytest.approx(-5.0, abs=1e-6)
    assert flipped["levels"][1]["v_out"] == pytest.approx(-40.0, abs=1e-6)


def test_clamper_checks_p151_and_p154(client):
    d151 = analyze(
        client,
        "V1 1 0 SQUARE(10 -15 1k)\nC1 1 2 100u\nD1 2 0 IDEAL\nR1 2 0 100k",
    )
    checks_151 = d151["waveform"]["clamper"]["checks"]
    assert [c["ok"] for c in checks_151] == [True, True, True]

    d154 = analyze(
        client,
        "V1 1 0 SQUARE(10 -15 1k)\nC1 1 2 100u\nD1 0 2 SI\nR1 2 0 100k",
    )
    checks_154 = d154["waveform"]["clamper"]["checks"]
    assert [c["ok"] for c in checks_154] == [True, True, None]
    assert "ideal değil" in checks_154[2]["text"].lower()

    # Seri kaynaklı ideal diyotta da 3. kontrol null (uygulanmaz)
    d156 = analyze(
        client,
        "V1 1 0 SQUARE(20 -15 1k)\nC1 1 2 100u\nD1 2 3 IDEAL\nV2 3 0 DC 5\nR1 2 0 100k",
    )
    checks_156 = d156["waveform"]["clamper"]["checks"]
    assert [c["ok"] for c in checks_156] == [True, True, None]
    assert "seri kaynak" in checks_156[2]["text"].lower()


def test_sine_clamper_oracle(client):
    net = "V1 1 0 SINE(0 10 1k)\nC1 1 2 100u\nD1 2 0 IDEAL\nR1 2 0 100k"
    d = analyze(client, net)
    wf = d["waveform"]
    assert wf["shape"] == "SINE"
    assert wf["levels"] is None
    assert wf["book_formula"] is None
    assert wf["conduction_angle_deg"] is None
    assert wf["v_out_max"] == pytest.approx(0.0, abs=1e-6)
    assert wf["v_out_min"] == pytest.approx(-20.0, abs=1e-6)
    assert wf["v_dc_numeric"] == pytest.approx(-10.0, abs=1e-4)
    assert wf["clamper"]["v_c"] == pytest.approx(10.0, abs=1e-6)
    assert wf["clamper"]["v_k"] == pytest.approx(0.0, abs=1e-6)
    # Tüm diyot aralıkları OFF olmalı
    assert len(wf["diodes"]) == 1
    assert all(iv["state"] == "OFF" for iv in wf["diodes"][0]["intervals"])
    # Anlatımda tepe tazeleme cümlesi geçmeli
    assert "yalnızca tepe anında sınırda iletime geçer ve kondansatörü tazeler" in expl_text(d)


@pytest.mark.parametrize(
    "net,extra",
    [
        # İki kondansatör
        ("V1 1 0 SQUARE(10 -15 1k)\nC1 1 2 100u\nC2 2 0 10u\nD1 2 0 IDEAL\nR1 2 0 100k", {}),
        # C + fazladan seri direnç
        ("V1 1 0 SQUARE(10 -15 1k)\nR0 1 3 1k\nC1 3 2 100u\nD1 2 0 IDEAL\nR1 2 0 100k", {}),
        # Diyot kolunda zener
        ("V1 1 0 SQUARE(10 -15 1k)\nC1 1 2 100u\nD1 2 0 ZENER VZ=5\nR1 2 0 100k", {}),
        # waveform_output başka elemanı gösteriyor
        ("V1 1 0 SQUARE(10 -15 1k)\nC1 1 2 100u\nD1 2 0 IDEAL\nR1 2 0 100k", {"waveform_output": "C1"}),
    ],
    ids=["two_caps", "extra_resistor", "zener_in_branch", "wrong_waveform_output"],
)
def test_clamper_topology_refusals(client, net, extra):
    d = analyze(client, net, status=422, **extra)
    assert d["detail"]


def test_clamper_snapshot_kcl_and_probes(client):
    net = (
        "V1 1 0 SQUARE(10 -5 1k)\n"
        "C1 1 2 100u\n"
        "D1 2 3 SI\n"
        "V2 3 0 DC 3\n"
        "R1 2 0 1k\n"
        "* PROBE VP1 V(2)\n"
        "* PROBE IP1 I(R1)"
    )
    d = analyze(client, net)
    nv = d["results"]["node_voltages"]
    ec = d["results"]["element_currents"]
    assert nv["0"]["value"] == pytest.approx(0.0)
    assert nv["1"]["value"] == pytest.approx(10.0)
    assert nv["2"]["value"] == pytest.approx(3.7)
    assert nv["3"]["value"] == pytest.approx(3.0)
    # I_R = 3.7 / 1k = 3.7 mA; I_C = 3.7 mA; I_V1 = −3.7 mA (PSC); I_D = I_V2 = 0
    assert ec["R1"]["value"] == pytest.approx(3.7e-3, abs=1e-9)
    assert ec["C1"]["value"] == pytest.approx(3.7e-3, abs=1e-9)
    assert ec["V1"]["value"] == pytest.approx(-3.7e-3, abs=1e-9)
    assert ec["D1"]["value"] == pytest.approx(0.0, abs=1e-12)
    assert ec["V2"]["value"] == pytest.approx(0.0, abs=1e-12)
    assert d["diodes"][0]["state"] == "ON"
    assert d["diodes"][0]["v_ak"] == pytest.approx(0.7, abs=1e-6)
    probes = {p["probe_id"]: p for p in d["results"]["probe_results"]}
    assert probes["VP1"]["value"] == pytest.approx(3.7, abs=1e-6)
    assert probes["IP1"]["value"] == pytest.approx(3.7e-3, abs=1e-9)


def test_clamper_assistant_known_values():
    net = "V1 1 0 SQUARE(10 -15 1k)\nC1 1 2 100u\nD1 2 0 IDEAL\nR1 2 0 100k"
    parsed = parse_netlist(net + GND)
    results, _, errs = solve_circuit(
        parsed, AnalysisMode.AC_TIME, None, AnalysisType.WAVEFORM, None, None, [],
    )
    assert not errs
    assert results.waveform is not None and results.waveform.clamper is not None
    msgs = build_messages(
        parsed, results, AnalysisType.WAVEFORM, False, 1000.0, None,
        "V_C nasıl bulundu?", [], False, [],
    )
    kv = known_values(parsed, results, 1000.0, [msgs[0]["content"]])
    assert kv is not None


def test_clamper_reversed_input_source(client):
    # V1 0 1 SQUARE(-10 15 1k), düğüm 1 gerilimi +10 / −15 → p154 (V1 1 0 SQUARE(10 -15 1k)) ile eşdeğer
    normal = analyze(
        client,
        "V1 1 0 SQUARE(10 -15 1k)\nC1 1 2 100u\nD1 0 2 SI\nR1 2 0 100k",
    )
    rev = analyze(
        client,
        "V1 0 1 SQUARE(-10 15 1k)\nC1 1 2 100u\nD1 0 2 SI\nR1 2 0 100k",
    )
    wf_n, wf_r = normal["waveform"], rev["waveform"]
    assert wf_r["v_out_max"] == pytest.approx(24.3, abs=1e-6)
    assert wf_r["v_out_min"] == pytest.approx(-0.7, abs=1e-6)
    assert wf_r["v_out_max"] == pytest.approx(wf_n["v_out_max"], abs=1e-6)
    assert wf_r["v_out_min"] == pytest.approx(wf_n["v_out_min"], abs=1e-6)
    assert abs(wf_r["clamper"]["v_c"]) == pytest.approx(14.3, abs=1e-6)
    assert wf_r["clamper"]["v_c"] == pytest.approx(wf_n["clamper"]["v_c"], abs=1e-6)
    assert wf_r["clamper"]["checks"] == wf_n["clamper"]["checks"]
    assert [lv["v_in"] for lv in wf_r["levels"]] == pytest.approx([10.0, -15.0], abs=1e-6)
    # Anlık görüntü: iletim alternansında düğüm 1 = v_i_min = −15 V; V1 (0→1) akımı = I_C = I_R
    assert rev["results"]["node_voltages"]["1"]["value"] == pytest.approx(-15.0, abs=1e-6)
    assert rev["results"]["node_voltages"]["2"]["value"] == pytest.approx(-0.7, abs=1e-6)
    assert rev["results"]["element_currents"]["V1"]["value"] == pytest.approx(-7e-6, abs=1e-12)
    assert "V1 ters bağlı" in expl_text(rev)
    for s in rev["results"]["explanation"]:
        for b in s["blocks"]:
            if b["kind"] == "result":
                assert b["text"].count(" = ") <= 1

    # V1 0 1 SQUARE(10 -15 1k), D1 2 0 IDEAL: düğüm −10/+15 görür, üst tepe (+15) 0 V'a kenetlenir
    top_pinned = analyze(
        client,
        "V1 0 1 SQUARE(10 -15 1k)\nC1 1 2 100u\nD1 2 0 IDEAL\nR1 2 0 100k",
    )
    wf_tp = top_pinned["waveform"]
    assert wf_tp["v_out_max"] == pytest.approx(0.0, abs=1e-6)
    assert wf_tp["v_out_min"] == pytest.approx(-25.0, abs=1e-6)
    assert [lv["v_out"] for lv in wf_tp["levels"]] == pytest.approx([-25.0, 0.0], abs=1e-6)
    assert wf_tp["clamper"]["v_c"] == pytest.approx(15.0, abs=1e-6)
    assert top_pinned["results"]["node_voltages"]["1"]["value"] == pytest.approx(15.0, abs=1e-6)
    assert top_pinned["results"]["node_voltages"]["2"]["value"] == pytest.approx(0.0, abs=1e-6)
    assert "V1 ters bağlı" in expl_text(top_pinned)

    # Ters bağlı SINE: V1 0 1 SINE(0 10 1k), D1 2 0 IDEAL → max 0, min −20
    sine_rev = analyze(
        client,
        "V1 0 1 SINE(0 10 1k)\nC1 1 2 100u\nD1 2 0 IDEAL\nR1 2 0 100k",
    )
    wf_sr = sine_rev["waveform"]
    assert wf_sr["shape"] == "SINE"
    assert wf_sr["v_out_max"] == pytest.approx(0.0, abs=1e-6)
    assert wf_sr["v_out_min"] == pytest.approx(-20.0, abs=1e-6)
    assert wf_sr["clamper"]["v_c"] == pytest.approx(10.0, abs=1e-6)
    assert sine_rev["results"]["node_voltages"]["1"]["value"] == pytest.approx(10.0, abs=1e-6)
    assert "V1 ters bağlı" in expl_text(sine_rev)


# ── Faz 4c-1 regresyonları ───────────────────────────────

def test_regression_half_wave_si_and_six_zener(client):
    d = analyze(client, "V1 1 0 SINE(0 10 50)\nD1 1 2 SI\nR1 2 0 1k")
    wf = d["waveform"]
    assert wf["clamper"] is None
    assert wf["v_out_max"] == pytest.approx(9.3, abs=1e-6)
    assert wf["v_dc_numeric"] == pytest.approx(2.841, abs=0.01)
    assert wf["book_formula"]["value"] == pytest.approx(2.957, abs=0.002)

    zener_net = (
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
    parsed = parse_netlist(zener_net + GND)
    solve_circuit(parsed, AnalysisMode.AC_TIME, 50.0, AnalysisType.WAVEFORM, None, None, [])
    t0 = time.perf_counter()
    res, _, errs = solve_circuit(
        parsed, AnalysisMode.AC_TIME, 50.0, AnalysisType.WAVEFORM, None, None, [],
    )
    elapsed = time.perf_counter() - t0
    assert not errs
    assert res.waveform is not None and res.waveform.clamper is None
    assert elapsed < 1.0, f"Altı zenerli kırpıcı 1 sn sınırını aştı: {elapsed:.3f} s"
