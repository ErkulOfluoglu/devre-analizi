"""
Faz 2 — Geçici durum (anahtarlı RC / RL) testleri.

Elle hesaplar her testin yorumundadır; sayılar bunlarla karşılaştırılır.
"""

import math

import pytest

import solver.transient as transient_mod
from llm.assistant import build_messages
from models.request import AnalysisMode, AnalysisType
from parser.netlist_parser import (
    SWITCH_NOTE, ElementType, circuit_at_time, has_switches, parse_netlist,
)
from practice.answer_parser import parse_answer
from practice.checker import check_answer

GND = "* GND1 — Referans toprak (Node 0)"


def texts(results):
    return [b.text for s in results.explanation for b in s.blocks]


def titles(results):
    return [s.title for s in results.explanation]


def quantity(results, qid):
    return next(q for q in results.transient.quantities if q.id == qid)


# ═══════════════════════════════════════════════════════
#  PARSER
# ═══════════════════════════════════════════════════════

def test_parser_switch_lines_and_time_versions():
    # V1 1 0, S1 (1–2) t=0'da KAPANIR, S2 (3 ortak; t<0: 3–4, t≥0: 3–0) iki konumlu
    net = f"V1 1 0 DC 12\nS1 1 2 NO\nR1 2 3 1k\nS2 3 4 0 SPDT\nR2 4 0 1k\nS3 2 0 NC\n{GND}"
    c = parse_netlist(net)
    assert c.errors == []
    s1, s2, s3 = (e for e in c.elements if e.element_type == ElementType.SWITCH)
    assert (s1.params["kind"], s1.node_positive, s1.node_negative) == ("NO", "1", "2")
    assert s2.params == {"kind": "SPDT", "common": "3", "pos1": "4", "pos2": "0"}
    assert s3.params["kind"] == "NC"
    assert has_switches(c) and c.node_count == 5

    before = circuit_at_time(c, "before")
    after = circuit_at_time(c, "after")
    assert not has_switches(before) and not has_switches(after)
    # t<0: S1 açık (çıkar), S2: 3–4 birleşir (4 → 3), S3 kapalı: 2–0 birleşir (2 → 0)
    nodes_before = {e.id: (e.node_positive, e.node_negative) for e in before.elements}
    assert nodes_before["R1"] == ("0", "3") and nodes_before["R2"] == ("3", "0")
    # t>0: S1 kapalı: 1–2 birleşir (→ "1"), S2: 3–0 birleşir (→ "0"), S3 açık
    nodes_after = {e.id: (e.node_positive, e.node_negative) for e in after.elements}
    assert nodes_after["R1"] == ("1", "0")


@pytest.mark.parametrize("line, fragment", [
    ("S1 1 1 NO", "iki ucu da aynı düğüme"),
    ("S1 1 2", "Anahtar satırı anlaşılamadı"),
    ("S1 1 2 MAYBE", "Anahtar satırı anlaşılamadı"),
    ("S1 1 2 1 SPDT", "birbirinden farklı düğümler"),
    ("S1 1 1 1 SPDT", "birbirinden farklı düğümler"),
])
def test_parser_switch_errors(client, line, fragment):
    net = f"V1 1 0 DC 12\n{line}\nR1 1 0 1k\n{GND}"
    c = parse_netlist(net)
    assert any(fragment in m for m in c.errors)
    r = client.post("/analyze", json={"netlist": net, "mode": "DC", "analysis_type": "TRANSIENT"})
    assert r.status_code == 400
    assert fragment in r.text


def test_parse_only_with_switch_does_not_crash(client):
    net = f"V1 1 0 DC 12\nS1 1 2 NO\nR1 2 0 1k\n{GND}"
    r = client.post("/parse-only", json={"netlist": net, "mode": "DC"})
    assert r.status_code == 200
    assert "S1 " not in r.json()["lcapy_netlist"]     # lcapy anahtar bilmez; t>0 devresi yazılır
    assert "R1 1 0" in r.json()["lcapy_netlist"]


# ═══════════════════════════════════════════════════════
#  RC ŞARJ / DEŞARJ
# ═══════════════════════════════════════════════════════

RC_CHARGE = f"V1 1 0 DC 12\nS1 1 2 NO\nR1 2 3 2k\nC1 3 0 1u\n{GND}"


def test_rc_charge(solve):
    # t<0: S1 açık → C1 kaynağa bağlı değil, boş: V_C(0⁻) = 0
    # t>0: R_th = R1 = 2 kΩ, τ = R·C = 2000 · 1e-6 = 2 ms
    # V_C(∞) = 12 V, I_C(0⁺) = (12 − 0)/2000 = 6 mA
    # V_C(τ) = 12·(1 − e⁻¹) = 7.585 V
    results, _, errors = solve(RC_CHARGE, "DC", analysis_type="TRANSIENT")
    assert not errors
    tr = results.transient
    assert tr.element == "C1" and tr.kind == "C"
    assert tr.tau == pytest.approx(0.002) and tr.r_th == pytest.approx(2000.0)
    v, i = tr.quantities
    assert (v.id, v.unit) == ("V_C1", "V") and (i.id, i.unit) == ("I_C1", "A")
    assert (v.before, v.start, v.final) == pytest.approx((0.0, 0.0, 12.0))
    assert (i.before, i.start, i.final) == pytest.approx((0.0, 0.006, 0.0))

    assert titles(results) == [
        "Devreyi Tanıyalım", "t = 0⁻ Anı (Anahtar Değişmeden Önce)", "Süreklilik: t = 0⁺ Anı",
        "t → ∞ (Yeni Kararlı Hâl)", "Zaman Sabitesi τ", "Zamana Bağlı İfade", "τ Tablosu",
        "Depolanan Enerji", "Kontrol", "Sonuç",
    ]
    t = texts(results)
    assert t[0] == "Kitaplarda gerilim U ile de gösterilir (U_C = V_C)."
    assert sum("Kitaplarda gerilim U ile" in x for x in t) == 1
    assert "τ = 2 ms" in t
    assert any("V_C1(t) = U · (1 − e^(−t/τ))" in x for x in t)          # kitaptaki kısa biçim
    assert any("I_C1(0⁺) = (V_C1(∞) − V_C1(0⁺)) / R_th = (12 V − 0 V) / 2 kΩ = 6 mA" in x for x in t)
    # τ tablosu: yüzdeler ve her τ'daki değer (12·(1 − e^−n))
    for pct, volt in [("63,2", "7,585"), ("86,5", "10,38"), ("95,0", "11,4"),
                      ("98,2", "11,78"), ("99,3", "11,92")]:
        assert any(f"%{pct}" in x and f"V_C1 = {volt} V" in x for x in t), pct
    assert any("hiçbir zaman tam olarak ulaşmaz" in x and "5τ = 10 ms" in x for x in t)
    # Enerji: W = ½·C·V² = ½ · 1e-6 · 144 = 72 µJ (t=0⁺'da V=0 → W(0⁺) satırı yok)
    assert any("W(∞) = ½ · 1 µF · (12 V)² = 72 µJ" in x for x in t)
    assert not any("W(0⁺)" in x for x in t)
    assert not any("uygulanamadı" in x for x in t)


def test_rc_discharge_spdt(solve):
    # Konum 1 (t<0): C1, R1 (1k) üzerinden 12 V'a şarjlı kalır → V_C(0⁻) = 12 V
    # Konum 2 (t>0): C1, R2 = 2 kΩ üzerinden boşalır → τ = 2000 · 10e-6 = 20 ms
    # I_C(0⁺) = (0 − 12)/2000 = −6 mA (akım n1→n2 yönünün tersine)
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nS1 3 2 4 SPDT\nR2 4 0 2k\nC1 3 0 10u\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="TRANSIENT")
    assert not errors
    tr = results.transient
    assert tr.tau == pytest.approx(0.02) and tr.r_th == pytest.approx(2000.0)
    v, i = tr.quantities
    assert (v.before, v.start, v.final) == pytest.approx((12.0, 12.0, 0.0))
    assert (i.before, i.start, i.final) == pytest.approx((0.0, -0.006, 0.0))
    t = texts(results)
    assert any("V_C1(t) = V₀ · e^(−t/τ)" in x for x in t)                 # kitaptaki sönüm biçimi
    assert any("V_C1(t) = 12 V · e^(−t/τ),   τ = 20 ms" in x for x in t)
    assert any("W(0⁺) = ½ · 10 µF · (12 V)² = 720 µJ" in x for x in t)   # ½·1e-5·144
    assert any("W(∞) = ½ · 10 µF · (0 V)² = 0 J" in x for x in t)
    assert any("tamamen boşalmış" in x for x in t)
    # Kapalı anahtar tel: konum 1'de Düğüm 3 ile Düğüm 2 birleşir
    assert any("Düğüm 3 ile Düğüm 2 aynı düğümdür" in x for x in t)


def test_rc_nonzero_initial_voltage_and_reduced_rth(solve):
    # t<0 (S1 açık): R1=1k ile R2=2k bölücü, C1 R2'ye paralel → V_C(0⁻) = 12·2/3 = 8 V
    # t>0 (S1 kapalı): R3=1k, R2'ye paralel girer: R2‖R3 = 2k·1k/3k = 666.7 Ω
    #   V_C(∞) = 12 · 666.7/(1000 + 666.7) = 4.8 V
    #   R_th = R1 ‖ (R2‖R3) = 1k · 666.7/(1666.7) = 400 Ω  →  τ = 400 · 100e-6 = 40 ms
    #   I_C(0⁺) = (4.8 − 8)/400 = −8 mA
    #   V_C(t) = 4.8 + 3.2·e^(−t/τ) ; W(0⁺) = ½·1e-4·64 = 3.2 mJ, W(∞) = ½·1e-4·23.04 = 1.152 mJ
    net = (f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\nR3 2 3 1k\nS1 3 0 NO\nC1 2 0 100u\n{GND}")
    results, _, errors = solve(net, "DC", analysis_type="TRANSIENT")
    assert not errors
    tr = results.transient
    assert tr.r_th == pytest.approx(400.0) and tr.tau == pytest.approx(0.04)
    v, i = tr.quantities
    assert (v.before, v.start, v.final) == pytest.approx((8.0, 8.0, 4.8))
    assert i.start == pytest.approx(-0.008)
    t = texts(results)
    # R_th seri/paralel indirgemesi gösterilir (iki paralel adım)
    assert any("R1 ve R2 aynı iki düğüm arasında, paralel" in x for x in t)
    assert any("Req2 = R3·Req1/(R3+Req1)" in x and "= 400 Ω" in x for x in t)
    assert "R_th = 400 Ω" in t
    assert any("V_C1(0⁻) = V₂ − V₀ = 8 − 0 = 8 V" in x for x in t)
    assert any("V_C1(t) = 4,8 V + (3,2 V) · e^(−t/τ)" in x for x in t)       # genel biçim (kısa biçim yok)
    assert not any("kısa biçim" in x for x in t)
    assert any("W(0⁺) = ½ · 100 µF · (8 V)² = 3,2 mJ" in x for x in t)
    assert any("W(∞) = ½ · 100 µF · (4,8 V)² = 1,152 mJ" in x for x in t)


def test_rc_rth_needs_delta_y(solve):
    # t>0: kaynak sıfırlanınca R0 (2k) C'nin uçları 3–0 arasına girer; köprü: R1,R2,R3 = 3k üçgeni
    # (düğüm 3, 5, 6), R4 = R5 = 1k (5–0, 6–0).  Δ→Y: her kol 3k·3k/9k = 1k.
    #   köprü (C açıkken, 3 → 0): 1k + (1k+1k)‖(1k+1k) = 2k;  R_th = R0 ‖ 2k = 1 kΩ
    #   V_C(∞) = 12 · 2k/(2k+2k) = 6 V ;  τ = 1k · 100µ = 100 ms
    net = (f"V1 1 0 DC 12\nS1 1 2 NO\nR0 2 3 2k\nR1 3 5 3k\nR2 3 6 3k\nR3 5 6 3k\n"
           f"R4 5 0 1k\nR5 6 0 1k\nC1 3 0 100u\n{GND}")
    results, _, errors = solve(net, "DC", analysis_type="TRANSIENT")
    assert not errors
    tr = results.transient
    assert tr.r_th == pytest.approx(1000.0) and tr.tau == pytest.approx(0.1)
    assert quantity(results, "V_C1").final == pytest.approx(6.0)
    t = texts(results)
    assert any("üçgen (Δ)" in x for x in t)
    assert "R_th = 1 kΩ" in t


# ═══════════════════════════════════════════════════════
#  RL YÜKSELME / SÖNÜM
# ═══════════════════════════════════════════════════════

def test_rl_rise(solve):
    # t<0: S1 açık → I_L(0⁻) = 0.  t>0: R_th = R1 = 100 Ω, τ = L/R = 50e-3/100 = 0.5 ms
    # I_L(∞) = 10/100 = 0.1 A ; V_L(0⁺) = 10 − 0·R = 10 V (bobin 0⁺'da açık devre)
    net = f"V1 1 0 DC 10\nS1 1 2 NO\nR1 2 3 100\nL1 3 0 50m\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="TRANSIENT")
    assert not errors
    tr = results.transient
    assert tr.kind == "L" and tr.element == "L1"
    assert tr.tau == pytest.approx(0.0005) and tr.r_th == pytest.approx(100.0)
    v, i = tr.quantities                      # sözleşme: önce V sonra I
    assert (v.id, i.id) == ("V_L1", "I_L1")
    assert (v.before, v.start, v.final) == pytest.approx((0.0, 10.0, 0.0))
    assert (i.before, i.start, i.final) == pytest.approx((0.0, 0.0, 0.1))
    t = texts(results)
    assert any("I_L1(t) = I · (1 − e^(−t/τ))" in x for x in t)
    assert any("τ = L / R_th = 50 mH / 100 Ω" in x for x in t)
    assert any("W(∞) = ½ · 50 mH · (100 mA)² = 250 µJ" in x for x in t)     # ½·0.05·0.01
    assert "t → ∞ (Yeni Kararlı Hâl)" in titles(results)


def test_rl_decay(solve):
    # t<0: S1 açık, döngü V1–R1–L1–R2: I_L(0⁻) = 10/(100+100) = 50 mA
    # t>0: S1, R1+V1 kolunu tel yapar (düğüm 2 = GND): bobin R2 üzerinden söner.
    #   R_th = R2 = 100 Ω, τ = 0.05/100 = 0.5 ms ; I_L(∞) = 0
    #   V_L(0⁺) = (0 − 50 mA)·100 = −5 V
    net = f"V1 1 0 DC 10\nR1 1 2 100\nS1 2 0 NO\nL1 2 3 50m\nR2 3 0 100\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="TRANSIENT")
    assert not errors
    tr = results.transient
    assert tr.tau == pytest.approx(0.0005)
    v, i = tr.quantities
    assert (i.before, i.start, i.final) == pytest.approx((0.05, 0.05, 0.0))
    assert (v.before, v.start, v.final) == pytest.approx((0.0, -5.0, 0.0))
    t = texts(results)
    assert any("I_L1(t) = I₀ · e^(−t/τ)" in x for x in t)
    assert any("L1 ile R1 aynı kolda (seri)" in x for x in t)
    assert any("V_L1(0⁺) = (I_L1(∞) − I_L1(0⁺)) · R_th = (0 A − 50 mA) · 100 Ω = −5 V" in x for x in t)
    assert any("sönmüş" in x for x in t)


# ═══════════════════════════════════════════════════════
#  ANAHTARLI DEVRE, GEÇİCİ DURUM DIŞI YÖNTEM
# ═══════════════════════════════════════════════════════

@pytest.mark.parametrize("method", ["NODAL", "MESH", "THEVENIN"])
def test_switch_circuit_other_methods_use_after_state_with_note(solve, method):
    # t>0: S1 kapalı → gerilim bölücü 12 V, R1 = 1k, R2 = 2k → V₃ = 12·2/3 = 8 V
    net = f"V1 1 0 DC 12\nS1 1 2 NO\nR1 2 3 1k\nR2 3 0 2k\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type=method,
                               terminals=("3", "0") if method == "THEVENIN" else None)
    assert not errors
    assert results.explanation[0].title == "Anahtar Konumu"
    assert results.explanation[0].blocks[0].text == SWITCH_NOTE
    assert results.node_voltages["3"].value == pytest.approx(8.0)
    assert results.transient is None


def test_nc_switch_other_method_is_open_after(solve):
    # S1 NC: t>0'da açık → R1–R2 kolu kaynaktan ayrılır, V₃ = 0
    net = f"V1 1 0 DC 12\nS1 1 2 NC\nR1 2 3 1k\nR2 3 0 2k\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="NODAL")
    assert not errors
    assert results.node_voltages["3"].value == pytest.approx(0.0)
    assert results.explanation[0].blocks[0].text == SWITCH_NOTE


def test_circuit_without_switch_has_no_note(solve):
    results, _, _ = solve(f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}", "DC")
    assert "Anahtar Konumu" not in titles(results)


# ═══════════════════════════════════════════════════════
#  GERİ ÇEKİLMELER (FALLBACK)
# ═══════════════════════════════════════════════════════

FALLBACKS = [
    ("no_switch", f"V1 1 0 DC 12\nR1 1 2 1k\nC1 2 0 1u\n{GND}", "DC", "Devrede anahtar yok"),
    ("no_storage", f"V1 1 0 DC 12\nS1 1 2 NO\nR1 2 0 1k\n{GND}", "DC",
     "kondansatör ya da bobin yok"),
    ("two_caps", f"V1 1 0 DC 12\nS1 1 2 NO\nR1 2 3 1k\nC1 3 0 1u\nC2 3 0 1u\n{GND}", "DC",
     "birden fazla kondansatör"),
    ("two_coils", f"V1 1 0 DC 12\nS1 1 2 NO\nR1 2 3 1k\nL1 3 0 1m\nR2 3 4 1k\nL2 4 0 1m\n{GND}", "DC",
     "birden fazla bobin"),
    ("c_and_l", f"V1 1 0 DC 12\nS1 1 2 NO\nR1 2 3 1k\nC1 3 0 1u\nL1 3 0 1m\n{GND}", "DC",
     "hem kondansatör hem bobin"),
    ("ac_source", f"VAC1 1 0 AC_PHASOR(10, 0)\nS1 1 2 NO\nR1 2 3 1k\nC1 3 0 1u\n{GND}", "AC_PHASOR",
     "yalnızca DC modunda"),
    ("ac_source_in_dc_mode", f"VAC1 1 0 SINE(0 10 50 0 0 0)\nS1 1 2 NO\nR1 2 3 1k\nC1 3 0 1u\n{GND}",
     "DC", "AC (alternatif akım) kaynağı"),
    ("dependent", f"V1 1 0 DC 12\nS1 1 2 NO\nR1 2 3 1k\nE1 4 0 V(R1) 2\nR2 4 0 1k\nC1 3 0 1u\n{GND}",
     "DC", "bağımlı kaynak"),
    ("cap_shorted_by_switch", f"V1 1 0 DC 12\nR1 1 2 1k\nS1 2 0 NO\nC1 2 0 1u\n{GND}", "DC",
     "kısa devre ediliyor"),
    ("no_resistive_path", f"V1 1 0 DC 12\nR1 1 2 1k\nC1 2 3 1u\nS1 3 0 NC\n{GND}", "DC",
     "direnç yolu yok"),
    ("no_change", f"V1 1 0 DC 12\nR1 1 2 1k\nC1 2 0 1u\nS1 1 3 NO\nR2 3 4 1k\n{GND}", "DC",
     "değişmiyor"),
]


@pytest.mark.parametrize("name, net, mode, reason", FALLBACKS, ids=[f[0] for f in FALLBACKS])
def test_transient_fallbacks(solve, name, net, mode, reason):
    results, _, errors = solve(net, mode, frequency=None if mode == "DC" else 50.0,
                               analysis_type="TRANSIENT")
    assert not any(m.startswith("⛔") for m in errors)
    assert results.transient is None
    first = results.explanation[0]
    assert first.title == "Geçici Durum (Anahtar)"
    assert reason in first.blocks[0].text
    assert "Düğüm Gerilimleri" in first.blocks[0].text
    assert len(results.explanation) > 1                    # t>0 devresi yine de anlatılır
    assert not any(q.id == "TAU" for q in results.practice)


def test_fallback_on_lcapy_mismatch(solve, monkeypatch):
    monkeypatch.setattr(transient_mod, "verify_with_lcapy",
                        lambda a: "lcapy denetimi: zaman sabiti τ hesaplanan değerle uyuşmadı.")
    results, _, errors = solve(RC_CHARGE, "DC", analysis_type="TRANSIENT")
    assert results.transient is None
    assert "uyuşmadı" in results.explanation[0].blocks[0].text


# ═══════════════════════════════════════════════════════
#  JSON ŞEKLİ (SÖZLEŞME)
# ═══════════════════════════════════════════════════════

def test_transient_json_matches_contract(client):
    r = client.post("/analyze", json={"netlist": RC_CHARGE, "mode": "DC", "analysis_type": "TRANSIENT"})
    assert r.status_code == 200
    j = r.json()
    assert j["analysis_type"] == "TRANSIENT"
    assert "transient" not in j["results"]
    assert j["transient"] == {
        "element": "C1", "kind": "C", "tau": pytest.approx(0.002), "r_th": pytest.approx(2000.0),
        "quantities": [
            {"id": "V_C1", "label": "V_C1", "unit": "V",
             "before": 0.0, "start": 0.0, "final": pytest.approx(12.0)},
            {"id": "I_C1", "label": "I_C1", "unit": "A",
             "before": 0.0, "start": pytest.approx(0.006), "final": 0.0},
        ],
    }
    assert set(j["transient"]) == {"element", "kind", "tau", "r_th", "quantities"}
    assert all(set(q) == {"id", "label", "unit", "before", "start", "final"}
               for q in j["transient"]["quantities"])
    assert all(isinstance(q[k], float) for q in j["transient"]["quantities"]
               for k in ("before", "start", "final"))


def test_transient_json_null_when_not_transient_or_fallback(client):
    other = client.post("/analyze", json={"netlist": RC_CHARGE, "mode": "DC", "analysis_type": "NODAL"}).json()
    assert other["transient"] is None
    fb = client.post("/analyze", json={
        "netlist": f"V1 1 0 DC 12\nR1 1 2 1k\nC1 2 0 1u\n{GND}", "mode": "DC",
        "analysis_type": "TRANSIENT"}).json()
    assert fb["transient"] is None and fb["status"] in ("success", "warning")


def test_transient_unsolvable_after_circuit_is_not_http_422(client):
    # t>0 devresinde (C açık) R1 hiçbir yere bağlı değil → genel çözücü tekil der,
    # ama geçici durumun kendi çözümü geçerlidir (V_C(∞) = 0) → 422 olmamalı
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nS1 3 2 4 SPDT\nR2 4 0 2k\nC1 3 0 10u\n{GND}"
    r = client.post("/analyze", json={"netlist": net, "mode": "DC", "analysis_type": "TRANSIENT"})
    assert r.status_code == 200
    assert r.json()["transient"]["tau"] == pytest.approx(0.02)


# ═══════════════════════════════════════════════════════
#  ALIŞTIRMA
# ═══════════════════════════════════════════════════════

def test_transient_practice_questions(solve):
    results, _, _ = solve(RC_CHARGE, "DC", analysis_type="TRANSIENT")
    qs = {q.id: q for q in results.practice}
    assert list(qs) == ["TAU", "X0", "XINF", "XTAU", "TLEVEL", "XT", "O0"]
    assert qs["TAU"].unit == "s" and qs["TAU"].expected.real == pytest.approx(0.002)
    assert qs["XINF"].expected.real == pytest.approx(12.0)
    assert qs["XTAU"].expected.real == pytest.approx(12 * (1 - math.exp(-1)))      # 7.585 V
    # %90'a ulaşma: 10.8 V → t = τ·ln(12/(12−10.8)) = 2 ms · ln 10 = 4.605 ms
    assert "10,8 V" in qs["TLEVEL"].description
    assert qs["TLEVEL"].expected.real == pytest.approx(0.002 * math.log(10))
    assert "ln" in qs["TLEVEL"].hint
    # t = 2τ = 4 ms: 12·(1 − e⁻²) = 10.376 V
    assert qs["XT"].expected.real == pytest.approx(12 * (1 - math.exp(-2)))
    assert qs["O0"].expected.real == pytest.approx(0.006) and qs["O0"].unit == "A"
    assert qs["TAU"].group == "main" and qs["XT"].group == "extra"
    assert all(not q.is_ac and q.hint and q.sign_hint for q in qs.values())
    # ipucu cevabı vermez
    assert "2 ms" not in qs["TAU"].hint and "7,585" not in qs["XTAU"].hint


def test_transient_practice_answers_are_checked_with_seconds(solve):
    results, _, _ = solve(RC_CHARGE, "DC", analysis_type="TRANSIENT")
    qs = {q.id: q for q in results.practice}
    assert check_answer(qs["TAU"], "2 ms").status == "correct"
    assert check_answer(qs["TAU"], "0.002").status == "correct"
    assert check_answer(qs["TAU"], "2m").status == "correct"
    assert check_answer(qs["TLEVEL"], "4,605 ms").status == "correct"
    assert check_answer(qs["TAU"], "10 ms").status == "wrong"              # 5τ → özel mesaj
    assert "5τ" in check_answer(qs["TAU"], "10 ms").message
    wrong_unit = check_answer(qs["TAU"], "2 mV")
    assert wrong_unit.status == "partial" and "süre" in wrong_unit.message
    assert check_answer(qs["TLEVEL"], "2 ms").status == "wrong"            # log10 (= τ) hatası
    assert "10 tabanlı" in check_answer(qs["TLEVEL"], "2 ms").message or \
        "τ" in check_answer(qs["TLEVEL"], "2 ms").message


def test_rl_practice_tau_alternative(solve):
    net = f"V1 1 0 DC 10\nS1 1 2 NO\nR1 2 3 100\nL1 3 0 50m\n{GND}"
    results, _, _ = solve(net, "DC", analysis_type="TRANSIENT")
    qs = {q.id: q for q in results.practice}
    assert qs["TAU"].expected.real == pytest.approx(0.0005)
    assert qs["XINF"].unit == "A" and qs["O0"].unit == "V"
    # L·R_th = 5 yanlış yolu açıklanır
    assert "τ = L / R_th" in check_answer(qs["TAU"], "5 s").message


def test_answer_parser_seconds():
    assert parse_answer("2 ms").unit == "s"
    assert parse_answer("2 ms").value == pytest.approx(0.002)
    assert parse_answer("3.5µs").value == pytest.approx(3.5e-6)
    assert parse_answer("1,5 s").value == pytest.approx(1.5)


# ═══════════════════════════════════════════════════════
#  YAPAY ZEKÂ ASİSTANI
# ═══════════════════════════════════════════════════════

@pytest.mark.parametrize("practice", [False, True])
def test_llm_messages_with_switch_circuit(solve, practice):
    parsed = parse_netlist(RC_CHARGE)
    results, _, _ = solve(RC_CHARGE, "DC", analysis_type="TRANSIENT")
    msgs = build_messages(parsed, results, AnalysisType.TRANSIENT, True, None, None,
                          "Zaman sabitesi nedir?", [], practice, results.practice)
    system = msgs[0]["content"]
    assert "Geçici durum" in system
    assert "S1: anahtar" in system and "t = 0'da kapanır" in system
    if not practice:
        assert "τ = 2 ms" in system
