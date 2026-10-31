"""
Kaynak dönüşümü (Thevenin/Norton eşdeğerine adım adım ulaşma) testleri — yalnızca DC.

Elle hesaplar yorumlarda; bulunan Vth/Rth çözücünün Thevenin sonucuyla karşılaştırılır.
"""

import pytest

from explainer.formatting import MINUS
from tests.conftest import as_complex

GND = "* GND1 — Referans toprak (Node 0)"


def texts(results):
    return [b.text for s in results.explanation for b in s.blocks]


def titles(results):
    return [s.title for s in results.explanation]


def assert_close(actual, expected, rel=1e-4):
    assert abs(actual - expected) <= rel * max(abs(expected), 1e-9), f"{actual} != {expected}"


def test_ladder_two_voltage_sources(solve):
    # Terminaller 4–0. V1 (12 V) + R1 (1k) ve V2 (6 V) + R3 (3k) kolları Düğüm 2'de buluşur,
    # R2 = 2k Düğüm 2 ile GND arasında, R4 = 500 Ω Düğüm 2 ile terminal 4 arasında.
    # Kaynak dönüşümü: Ia = 12/1k = 12 mA, Ib = 6/3k = 2 mA (ikisi de GND → 2)
    # Paralel dirençler: 1k ∥ 2k ∥ 3k = 545.45 Ω;  Ic = 14 mA
    # Ea = 14 mA · 545.45 Ω = 7.636 V;  Rth = 500 + 545.45 = 1045.45 Ω
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\nR3 2 3 3k\nV2 3 0 DC 6\nR4 2 4 500\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="SOURCE_TRANSFORM", terminals=("4", "0"))
    assert not errors
    th = results.thevenin
    assert_close(as_complex(th.vth).real, 7.636364)
    assert_close(as_complex(th.zth).real, 1045.4545)
    t = texts(results)
    assert "Kaynak Dönüşümü — Adım Adım" in titles(results)
    assert any("Ia = V1 / R1 = 12 V / 1 kΩ = 12 mA" in x for x in t)
    assert any("Ib = V2 / R3 = 6 V / 3 kΩ = 2 mA" in x for x in t)
    assert any("= 14 mA" in x for x in t)
    assert any("Vth = V_AB = V₄ " + MINUS + " V₀ = 7,636 V" in x for x in t)
    assert any(x.startswith("Rth = 1,045 kΩ") for x in t)
    assert any("Çözücünün Thevenin sonucuyla aynı" in x for x in t)
    assert not any("uygulanamadı" in x for x in t)


def test_current_source_case(solve):
    # Terminaller 2–0. V1 (12 V) + R1 (1k) → 12 mA; R2 = 2k; I1 = 3 mA (GND → 2).
    # Akımlar toplanır: 15 mA; R = 1k ∥ 2k = 666.67 Ω → E = 15 mA · 666.67 = 10 V
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\nI1 0 2 DC 3m\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="SOURCE_TRANSFORM", terminals=("2", "0"))
    assert not errors
    th = results.thevenin
    assert_close(as_complex(th.vth).real, 10.0)
    assert_close(as_complex(th.zth).real, 2000 / 3)
    t = texts(results)
    assert any("Ib = I1 + Ia = 3 mA + 12 mA = 15 mA" in x for x in t)
    assert any("Vth = V_AB = V₂ " + MINUS + " V₀ = 10 V" in x for x in t)


def test_opposing_series_voltage_sources_subtract(solve):
    # V1 = 10 V ve V2 = 4 V zıt kutuplu seri (0 → V1 → V2 → R1): Ea = V1 − V2 = 6 V.
    # Terminaller 3–0: Ia = 6 V / 1k = 6 mA, Rb = 1k ∥ 2k = 666.7 Ω → Vth = 6 mA · 666.7 = 4 V
    net = f"V1 1 0 DC 10\nV2 1 2 DC 4\nR1 2 3 1k\nR2 3 0 2k\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="SOURCE_TRANSFORM", terminals=("3", "0"))
    assert not errors
    th = results.thevenin
    assert_close(as_complex(th.vth).real, 4.0)
    assert_close(as_complex(th.zth).real, 2000 / 3)
    t = texts(results)
    assert any("Ea = V1 " + MINUS + " V2 = 10 V " + MINUS + " 4 V = 6 V" in x for x in t)
    assert any("Vth = V_AB = V₃ " + MINUS + " V₀ = 4 V" in x for x in t)


def test_unbalanced_bridge_uses_delta_wye(solve):
    # V1 = 20 V + Rs = 100 Ω besler; köprü: R1 = 200 (2–3), R2 = 300 (2–4), R3 = 400 (3–4), R5 = 500 (4–0).
    # Terminaller 3–0 (yük yeri). Ia = 20/100 = 200 mA (GND → 2).
    # R1, R2, R3 kaynaksız üçgen → Y:  Ry1 = 200·300/900 = 66.67,  Ry2 = 200·400/900 = 88.89,
    #   Ry3 = 300·400/900 = 133.3 Ω.  R5 + Ry3 = 633.3 Ω;  Rs + Ry1 = 166.7 Ω → Ib = 20/166.7 = 120 mA
    #   Rc = 633.3 ∥ 166.7 = 131.9 Ω;  Eb = 120 mA · 131.9 = 15.83 V;  Rth = 88.89 + 131.9 = 220.8 Ω
    net = (f"V1 1 0 DC 20\nRs 1 2 100\nR1 2 3 200\nR2 2 4 300\nR3 3 4 400\nR5 4 0 500\n{GND}")
    results, _, errors = solve(net, "DC", analysis_type="SOURCE_TRANSFORM", terminals=("3", "0"))
    assert not errors
    th = results.thevenin
    assert_close(as_complex(th.vth).real, 15.8333)
    assert_close(as_complex(th.zth).real, 220.8333)
    t = texts(results)
    assert any("üçgen (Δ) bağlı (Düğüm 2, 3, 4 arası) → yıldıza (Y) dönüştürelim" in x for x in t)
    assert any("Ry1 = R1·R2/(R1+R2+R3) = 200·300/(200+300+400) = 66,67 Ω (Düğüm 2–Y1)" in x for x in t)
    assert any("Vth = V_AB = V₃ " + MINUS + " V₀ = 15,83 V" in x for x in t)
    assert any(x.startswith("Rth = 220,8 Ω") for x in t)
    assert any("Çözücünün Thevenin sonucuyla aynı" in x for x in t)
    assert not any("uygulanamadı" in x for x in t)


def test_bridge_with_ideal_source_node_outside_triangle(solve):
    # Eski köprü örneği: V1 doğrudan Düğüm 1'de; üçgenler kaynaksız dirençli → Δ→Y ile çözülür.
    # Vth = 8.757 V, Rth = 567.6 Ω (çözücüyle aynı)
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 1 3 2k\nR3 2 3 1k\nR4 2 0 3k\nR5 3 0 4k\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="SOURCE_TRANSFORM", terminals=("2", "0"))
    assert not errors
    th = results.thevenin
    assert_close(as_complex(th.vth).real, 8.756757)
    assert_close(as_complex(th.zth).real, 567.5676)
    t = texts(results)
    assert any("yıldıza (Y) dönüştürelim" in x for x in t)
    assert not any("uygulanamadı" in x for x in t)


def test_bridge_with_source_inside_triangle_uses_source_shifting(solve):
    # Köprünün orta kolunda V2 + R3 var: kolu I ∥ R'ye çevrilir, üçgen dirençleri yıldıza dönerken
    # akım kaynağı yıldız düğümü üzerinden kaydırılır. Beklenen değerler ayrı düğüm denklemiyle bulundu.
    net = ("V1 1 0 DC 20\nRs 1 2 100\nR1 2 3 200\nR2 2 4 300\nV2 3 5 DC 5\nR3 5 4 400\n"
           f"R4 3 0 600\nR5 4 0 500\n{GND}")
    results, _, errors = solve(net, "DC", analysis_type="SOURCE_TRANSFORM", terminals=("2", "0"))
    assert not errors
    assert as_complex(results.thevenin.vth).real == pytest.approx(16.040609, rel=1e-5)
    assert as_complex(results.thevenin.zth).real == pytest.approx(79.864636, rel=1e-5)
    assert "Kaynak Dönüşümü — Adım Adım" in titles(results)
    assert any("akım kaynağı kaydırma" in x for x in texts(results))


def test_ideal_source_with_no_series_resistor(solve):
    # V2 Düğüm 2'yi 5 V'ta tutar; soldaki V1, R1, R2 onun yanında etkisizdir.
    # R3 ve R4 gerilim bölücü: V3 = 5·50/60 = 4,1667 V; Rth = 50 ∥ 10 = 8,3333 Ω
    net = f"V1 1 0 DC 10\nR1 1 2 40\nR2 1 0 40\nR3 0 3 50\nR4 3 2 10\nV2 2 0 DC 5\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="SOURCE_TRANSFORM", terminals=("3", "0"))
    assert not errors
    assert as_complex(results.thevenin.vth).real == pytest.approx(25 / 6, rel=1e-5)
    assert as_complex(results.thevenin.zth).real == pytest.approx(25 / 3, rel=1e-5)
    assert "Kaynak Dönüşümü — Adım Adım" in titles(results)


def test_resistor_parallel_to_ideal_source_is_removed(solve):
    # Rp, V1'e paralel: etkisiz. Vth = 12·3/9 = 4 V, Rth = 6 ∥ 3 = 2 Ω
    net = f"V1 1 0 DC 12\nRp 1 0 100\nR1 1 2 6\nR2 2 0 3\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="SOURCE_TRANSFORM", terminals=("2", "0"))
    assert not errors
    assert as_complex(results.thevenin.vth).real == pytest.approx(4.0, rel=1e-5)
    assert as_complex(results.thevenin.zth).real == pytest.approx(2.0, rel=1e-5)
    t = texts(results)
    assert "Kaynak Dönüşümü — Adım Adım" in titles(results)
    assert any("Rp, V1 ideal gerilim kaynağına paralel" in x for x in t)


def test_ideal_source_across_terminals(solve):
    # Terminal gerilimini V1 belirler: Vth = 12 V, Rth = 0
    net = f"V1 1 0 DC 12\nR1 1 0 5\nR2 1 2 7\nR3 2 0 3\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="SOURCE_TRANSFORM", terminals=("1", "0"))
    assert not errors
    assert as_complex(results.thevenin.vth).real == pytest.approx(12.0, rel=1e-5)
    assert abs(as_complex(results.thevenin.zth)) < 1e-6
    assert "Kaynak Dönüşümü — Adım Adım" in titles(results)


def test_part_hanging_on_one_node_is_removed(solve):
    # V2, R3, R4 halkası devreye yalnızca toprak üzerinden bağlı: akım göndermez.
    # Vth = 10·30/40 = 7,5 V, Rth = 10 ∥ 30 = 7,5 Ω
    net = (f"V1 1 0 DC 10\nR1 1 2 10\nR2 2 0 30\nV2 3 5 DC 6\nR3 5 4 2\nR4 4 3 2\nR5 3 0 8\n{GND}")
    results, _, errors = solve(net, "DC", analysis_type="SOURCE_TRANSFORM", terminals=("2", "0"))
    assert not errors
    assert as_complex(results.thevenin.vth).real == pytest.approx(7.5, rel=1e-5)
    assert as_complex(results.thevenin.zth).real == pytest.approx(7.5, rel=1e-5)
    assert "Kaynak Dönüşümü — Adım Adım" in titles(results)


def test_fallback_when_nodes_have_four_branches(solve):
    # Beş düğümün hepsi birbirine bağlı: Δ–Y ile indirgenemez → Thevenin anlatımı
    net = ("V1 5 0 DC 10\nR0 5 1 1\nR1 0 1 3\nR2 0 2 4\nR3 0 3 5\nR4 0 4 6\nR5 1 2 7\nR6 1 3 8\n"
           f"R7 1 4 9\nR8 2 3 10\nR9 2 4 11\nR10 3 4 12\n{GND}")
    results, _, errors = solve(net, "DC", analysis_type="SOURCE_TRANSFORM", terminals=("4", "0"))
    assert not errors
    assert results.thevenin is not None
    t = texts(results)
    note = next(x for x in t if "kaynak dönüşümü yöntemi uygulanamadı" in x)
    assert "köprü" in note and "Thevenin Eşdeğeri" in note
    assert "Kaynak Dönüşümü — Adım Adım" not in titles(results)
    assert "Thevenin Eşdeğer Devresi" in titles(results)


def test_fallback_dependent_source(solve):
    net = f"V1 1 0 DC 10\nR1 1 2 1k\nR2 2 0 2k\nG1 0 2 V(R2) 1m\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="SOURCE_TRANSFORM", terminals=("2", "0"))
    assert not errors
    t = texts(results)
    note = next(x for x in t if "kaynak dönüşümü yöntemi uygulanamadı" in x)
    assert "bağımlı" in note and "Thevenin Eşdeğeri" in note
