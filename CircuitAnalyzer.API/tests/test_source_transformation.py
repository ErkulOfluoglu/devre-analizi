"""
Kaynak dönüşümü (Thevenin/Norton eşdeğerine adım adım ulaşma) testleri — yalnızca DC.

Elle hesaplar yorumlarda; bulunan Vth/Rth çözücünün Thevenin sonucuyla karşılaştırılır.
"""

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
    assert any("Vth = V_AB = V₄ " + MINUS + " V₀ = 7.636 V" in x for x in t)
    assert any(x.startswith("Rth = 1.045 kΩ") for x in t)
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


def test_fallback_bridge_with_source(solve):
    # Köprü: seri/paralel/kaynak dönüşümüyle terminallere indirgenemez → Thevenin anlatımına dönülür
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 1 3 2k\nR3 2 3 1k\nR4 2 0 3k\nR5 3 0 4k\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="SOURCE_TRANSFORM", terminals=("2", "0"))
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
