"""
CircuitAnalyzer API — Δ–Y (Üçgen–Yıldız) ve Y–Δ (Yıldız–Üçgen) İndirgeme Testleri

Test edilen modüller:
- explainer/topology.py (reduce_port_impedance, reduce_series_parallel)
- explainer/narrative.py (Thevenin / Norton eşdeğer direnç anlatımı)
- FastAPI /analyze uç noktası üzerinden uçtan uca doğrulama
"""

import pytest

from explainer.topology import reduce_port_impedance, reduce_series_parallel
from parser.netlist_parser import parse_netlist
from tests.conftest import as_complex
from tests.test_narrative import all_texts, section_by_title, section_texts
from tests.test_thevenin import GND, assert_close


# ═══════════════════════════════════════════════════════
#  1. DENGESİZ WHEATSTONE KÖPRÜSÜ (Δ → Y)
# ═══════════════════════════════════════════════════════
#
# Elle kontrol edilen sayılar:
#   Üst üçgen (Düğüm 1, 2, 3):
#     R1 (1–2) = 30 Ω,  R2 (1–3) = 60 Ω,  R3 (2–3) = 90 Ω
#     Toplam: R1 + R2 + R3 = 30 + 60 + 90 = 180 Ω
#   Δ → Y dönüşümü (ortak düğüm Y1):
#     Ry1 (1–Y1) = R1·R2 / 180 = 30·60 / 180 = 10 Ω
#     Ry2 (2–Y1) = R1·R3 / 180 = 30·90 / 180 = 15 Ω
#     Ry3 (3–Y1) = R2·R3 / 180 = 60·90 / 180 = 30 Ω
#   Alt kollar (dengesiz: R1·R5 = 900 ≠ R2·R4 = 1500):
#     R4 (2–0) = 25 Ω  →  Req1 = Ry2 + R4 = 15 + 25 = 40 Ω
#     R5 (3–0) = 30 Ω  →  Req2 = Ry3 + R5 = 30 + 30 = 60 Ω
#   Paralel ve son seri:
#     Req3 = Req1 ∥ Req2 = 40·60 / (40 + 60) = 24 Ω
#     Rth  = Ry1 + Req3  = 10 + 24 = 34 Ω
#   Kaynak I1 = 0.5 A (0 → 1) iken Vth = 0.5 · 34 = 17 V.

UNBALANCED_BRIDGE = (
    "I1 0 1 DC 0.5\n"
    "R1 1 2 30\n"
    "R2 1 3 60\n"
    "R3 2 3 90\n"
    "R4 2 0 25\n"
    "R5 3 0 30\n"
    f"{GND}"
)


def test_unbalanced_wheatstone_bridge_delta_to_y(solve, client):
    parsed = parse_netlist(UNBALANCED_BRIDGE)
    red = reduce_port_impedance(parsed, "1", "0", is_dc=True)

    assert red.complete is True
    assert red.impedance is not None
    assert_close(red.impedance, 34.0)

    kinds = [s.kind for s in red.steps]
    assert kinds == ["delta_y", "series", "series", "parallel", "series"]

    dy = red.steps[0]
    assert dy.kind == "delta_y"
    assert set(dy.elements) == {"R1", "R2", "R3"}
    assert "Ry1 = R1·R2/(R1+R2+R3) = 30·60/(30+60+90) = 10 Ω" in dy.formula
    assert "Ry2 = R1·R3/(R1+R2+R3) = 30·90/(30+60+90) = 15 Ω" in dy.formula
    assert "Ry3 = R2·R3/(R1+R2+R3) = 60·90/(30+60+90) = 30 Ω" in dy.formula
    assert "\\frac{R1 \\cdot R2}{R1 + R2 + R3}" in dy.latex

    # Uçtan uca çözücü ve Türkçe anlatım kontrolü
    results, _, errors = solve(
        UNBALANCED_BRIDGE, "DC", analysis_type="THEVENIN", terminals=("1", "0")
    )
    assert not errors
    assert results.thevenin is not None
    assert_close(as_complex(results.thevenin.vth), 17.0)
    assert_close(as_complex(results.thevenin.zth), 34.0)

    rth_sec = section_by_title(results.explanation, "2. Adım — Rth")
    assert rth_sec is not None
    rth_texts = section_texts(rth_sec)
    assert any("üçgen (Δ) bağlı" in t and "yıldıza (Y) dönüştürelim" in t for t in rth_texts)
    assert any("Ry1 = R1·R2/(R1+R2+R3)" in t for t in rth_texts)
    assert any("Rth = 34 Ω" in t for t in rth_texts)

    # FastAPI /analyze uç noktası üzerinden kontrol
    resp = client.post("/analyze", json={
        "netlist": UNBALANCED_BRIDGE,
        "mode": "DC",
        "analysis_type": "THEVENIN",
        "thevenin_terminals": {"node_positive": "1", "node_negative": "0"},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert_close(body["results"]["thevenin"]["zth"]["real"], 34.0)
    assert_close(body["results"]["thevenin"]["vth"]["real"], 17.0)


def test_unbalanced_bridge_across_middle_terminals_with_voltage_source(solve):
    # Gerilim kaynağı V1 (1–0) seri R1 (1–2) üzerinden köprüye bağlanır;
    # terminaller köprünün orta uçları (3, 4).
    # V1 kısa devre olunca Düğüm 1 → 0 birleşir ve (0, 2, 3) üçgeni Δ→Y ile çözülür:
    #   R1(0–2)=30, R2(2–3)=60, R4(3–0)=90 → toplam 180 Ω
    #   Ry1(0–Y1) = 30·90/180 = 15 Ω, Ry2(2–Y1) = 30·60/180 = 10 Ω, Ry3(3–Y1) = 60·90/180 = 30 Ω
    #   Düğüm 0 üzerinden: Ry1 + R5(30) = 45 Ω
    #   Düğüm 2 üzerinden: Ry2 + R3(25) = 35 Ω
    #   Paralel: 45 ∥ 35 = 1575/80 = 19.6875 Ω
    #   Rth = Ry3 + 19.6875 = 49.6875 Ω
    net = (
        "V1 1 0 DC 18\n"
        "R1 1 2 30\n"
        "R2 2 3 60\n"
        "R3 2 4 25\n"
        "R4 3 0 90\n"
        "R5 4 0 30\n"
        f"{GND}"
    )
    results, _, errors = solve(net, "DC", analysis_type="THEVENIN", terminals=("3", "4"))
    assert not errors
    assert results.thevenin is not None
    assert_close(as_complex(results.thevenin.zth), 49.6875)

    rth_sec = section_by_title(results.explanation, "2. Adım — Rth")
    assert rth_sec is not None
    assert any("üçgen (Δ) bağlı" in t for t in section_texts(rth_sec))


# ═══════════════════════════════════════════════════════
#  2. DENGELİ WHEATSTONE KÖPRÜSÜ
# ═══════════════════════════════════════════════════════
#
# R1(1–2)=20 Ω, R2(1–3)=40 Ω, R3(2–3)=60 Ω, R4(2–0)=30 Ω, R5(3–0)=60 Ω
# Dengeli: R1·R5 = 20·60 = 1200 = R2·R4 = 40·30
# R3'ten akım geçmez → Rth = (20+30) ∥ (40+60) = 50 ∥ 100 = 100/3 ≈ 33.3333 Ω

def test_balanced_wheatstone_bridge(solve):
    net = (
        "I1 0 1 DC 0.3\n"
        "R1 1 2 20\n"
        "R2 1 3 40\n"
        "R3 2 3 60\n"
        "R4 2 0 30\n"
        "R5 3 0 60\n"
        f"{GND}"
    )
    results, _, errors = solve(net, "DC", analysis_type="NORTON", terminals=("1", "0"))
    assert not errors
    assert results.norton is not None
    assert_close(as_complex(results.norton.z_n), 100.0 / 3.0)
    assert_close(as_complex(results.norton.i_n), 0.3)

    rn_sec = section_by_title(results.explanation, "2. Adım — Rn")
    assert rn_sec is not None
    assert any("üçgen (Δ) bağlı" in t for t in section_texts(rn_sec))


# ═══════════════════════════════════════════════════════
#  3. Y → Δ (YILDIZ → ÜÇGEN) GEREKTİREN DEVRELER
# ═══════════════════════════════════════════════════════
#
# 3a) Çift kaynaklı T-ağı (Düğüm 3 iç yıldız düğümü, hiç üçgen yok):
#     Düğüm 1 ve Düğüm 2'ye kaynak bağlı, Düğüm 0 toprak; Düğüm 3'e
#     yalnızca R1(1–3)=20 Ω, R2(2–3)=30 Ω, R3(3–0)=60 Ω bağlıdır.
#     Hiç üçgen olmadığı ve seri/paralel yapılamadığı için Düğüm 3
#     Y→Δ ile üçgene dönüştürülür:
#       Pay = 20·30 + 30·60 + 60·20 = 600 + 1800 + 1200 = 3600
#       Rd1 (1–2) = 3600 / 60 = 60 Ω
#       Rd2 (2–0) = 3600 / 20 = 180 Ω
#       Rd3 (1–0) = 3600 / 30 = 120 Ω

def test_y_to_delta_star_node_conversion():
    net = (
        "V1 1 0 DC 12\n"
        "V2 2 0 DC 6\n"
        "R1 1 3 20\n"
        "R2 2 3 30\n"
        "R3 3 0 60\n"
        f"{GND}"
    )
    parsed = parse_netlist(net)
    reds, rem, _, _ = reduce_series_parallel(parsed, is_dc=True)

    assert len(reds) == 1
    yd = reds[0]
    assert yd.kind == "y_delta"
    assert set(yd.elements) == {"R1", "R2", "R3"}
    assert (
        "Rd1 = (R1·R2 + R2·R3 + R3·R1)/R3 = "
        "(20·30 + 30·60 + 60·20)/60 = 60 Ω (Düğüm 1–2)"
    ) in yd.formula
    assert (
        "Rd2 = (R1·R2 + R2·R3 + R3·R1)/R1 = "
        "(20·30 + 30·60 + 60·20)/20 = 180 Ω (Düğüm 2–0)"
    ) in yd.formula
    assert (
        "Rd3 = (R1·R2 + R2·R3 + R3·R1)/R2 = "
        "(20·30 + 30·60 + 60·20)/30 = 120 Ω (Düğüm 1–0)"
    ) in yd.formula
    assert len(rem) == 3


def test_y_to_delta_triangle_free_bipartite_network(solve):
    # Hiç üçgen içermeyen iki parçalı (bipartite) 8 dirençli ağ:
    # {1, 4, 5} ile {2, 3, 0} arasında bağlar. Hiç üçgen olmadığı için
    # indirgeme zorunlu olarak Y→Δ ile başlar.
    # Tüm dirençler 60 Ω iken simetriden:
    #   R(1 → {2,3}) = 60 ∥ 60 = 30 Ω
    #   R({2,3} → {4,5}) = 60 / 4 = 15 Ω
    #   R({4,5} → 0) = 60 ∥ 60 = 30 Ω
    #   Rth = 30 + 15 + 30 = 75 Ω.
    net = (
        "I1 0 1 DC 0.4\n"
        "R1 1 2 60\n"
        "R2 1 3 60\n"
        "R3 2 4 60\n"
        "R4 2 5 60\n"
        "R5 3 4 60\n"
        "R6 3 5 60\n"
        "R7 4 0 60\n"
        "R8 5 0 60\n"
        f"{GND}"
    )
    parsed = parse_netlist(net)
    red = reduce_port_impedance(parsed, "1", "0", is_dc=True)
    assert red.complete is True
    assert red.steps[0].kind == "y_delta"
    assert_close(red.impedance, 75.0)

    results, _, errors = solve(net, "DC", analysis_type="THEVENIN", terminals=("1", "0"))
    assert not errors
    assert_close(as_complex(results.thevenin.zth), 75.0)


# ═══════════════════════════════════════════════════════
#  4. AC EMPEDANS KÖPRÜSÜ
# ═══════════════════════════════════════════════════════
#
# Üst üçgen (1, 2, 3):
#   Z1(1–2) = 30 Ω,  Z2(1–3) = j60 Ω,  Z3(2–3) = 30 − j60 Ω
#   Toplam: Z1 + Z2 + Z3 = 60 Ω
#   Zy1(1–Y1) = 30·j60 / 60 = j30 Ω
#   Zy2(2–Y1) = 30·(30−j60) / 60 = 15 − j30 Ω
#   Zy3(3–Y1) = j60·(30−j60) / 60 = 60 + j30 Ω
# Alt kollar:
#   Z4(2–0) = 25 + j30 Ω  →  Zeq1 = Zy2 + Z4 = 40 Ω
#   Z5(3–0) = −j30 Ω      →  Zeq2 = Zy3 + Z5 = 60 Ω
#   Zeq3 = 40 ∥ 60 = 24 Ω
#   Zth  = Zy1 + Zeq3 = 24 + j30 Ω.

def test_ac_impedance_bridge_delta_to_y(solve, client):
    f = 1000
    net = (
        "IAC1 0 1 AC_PHASOR(1, 0)\n"
        "Z1 1 2 COMPLEX(30, 0)\n"
        "Z2 1 3 COMPLEX(0, 60)\n"
        "Z3 2 3 COMPLEX(30, -60)\n"
        "Z4 2 0 COMPLEX(25, 30)\n"
        "Z5 3 0 COMPLEX(0, -30)\n"
        f"{GND}"
    )
    parsed = parse_netlist(net)
    red = reduce_port_impedance(parsed, "1", "0", is_dc=False, frequency=f)
    assert red.complete is True
    assert red.steps[0].kind == "delta_y"
    assert_close(red.impedance, 24 + 30j)

    results, _, errors = solve(
        net, "AC_PHASOR", frequency=f, analysis_type="THEVENIN", terminals=("1", "0")
    )
    assert not errors
    assert results.thevenin is not None
    assert_close(as_complex(results.thevenin.zth), 24 + 30j)

    zth_sec = section_by_title(results.explanation, "2. Adım — Zth")
    assert zth_sec is not None
    assert any("üçgen (Δ) bağlı" in t for t in section_texts(zth_sec))

    # reduce_series_parallel doğrudan çağrısı da aynı eşdeğere indirgemeli
    reds, rem, _, _ = reduce_series_parallel(parsed, is_dc=False, frequency=f, pinned_nodes={"1", "0"})
    assert reds[0].kind == "delta_y"
    assert len(rem) == 1
    assert_close(rem[0].z, 24 + 30j)


# ═══════════════════════════════════════════════════════
#  5. SONSUZ DÖNGÜ KORUMASI VE İNDİRGENEMEYEN AĞ (complete=False)
# ═══════════════════════════════════════════════════════

def test_irreducible_graph_terminates_without_infinite_loop(solve):
    # K_{4,4} tam iki parçalı 4-dereceli graf ({1,2,3,4} × {0,5,6,7}) +
    # (1, 2, 3) arasında ek bir üçgen: üçgen Δ→Y ile Y1'e dönüşse bile
    # kalan düğümlerin derecesi ≥ 4 olduğundan seri/paralel adım açılamaz
    # ve Y1 geri Δ'ya dönüştürülmez (döngü koruması).
    lines = ["I1 0 1 DC 1"]
    idx = 1
    for a in ("1", "2", "3", "4"):
        for b in ("0", "5", "6", "7"):
            lines.append(f"R{idx} {a} {b} 100")
            idx += 1
    # Üçgen ekle
    lines.append("R17 1 2 100")
    lines.append("R18 2 3 100")
    lines.append("R19 1 3 100")
    lines.append(GND)
    net = "\n".join(lines)

    parsed = parse_netlist(net)
    red = reduce_port_impedance(parsed, "1", "0", is_dc=True)
    assert red.complete is False
    assert red.impedance is None

    # Çözücü yine de Rth'yi test kaynağıyla bulur ve anlatım yedek metni gösterir
    results, _, errors = solve(net, "DC", analysis_type="THEVENIN", terminals=("1", "0"))
    assert not errors
    assert results.thevenin is not None
    rth_sec = section_by_title(results.explanation, "2. Adım — Rth")
    assert rth_sec is not None
    assert any("test kaynağı" in t for t in section_texts(rth_sec))
