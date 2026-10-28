"""
Millman teoremi anlatımı testleri (yalnızca DC).

Elle hesaplar yorumlarda; anlatımdaki sayılar bunlarla karşılaştırılır.
"""

from explainer.formatting import MINUS

GND = "* GND1 — Referans toprak (Node 0)"


def texts(results):
    return [b.text for s in results.explanation for b in s.blocks]


def titles(results):
    return [s.title for s in results.explanation]


def test_millman_three_source_branches(solve):
    # A = Düğüm 2, B = GND. Kollar (B → A yönünde):
    #   Kol 1: V1 = 12 V (+ ucu A tarafında), R1 = 1k   → E1 = +12, R1 = 1000
    #   Kol 2: V2 = 6 V  (+ ucu A tarafında), R2 = 3k   → E2 = +6,  R2 = 3000
    #   Kol 3: V3 = 9 V  (+ ucu B tarafında), R3 = 2k   → E3 = −9,  R3 = 2000
    # Σ E/R = 12/1000 + 6/3000 − 9/2000 = 12 mA + 2 mA − 4.5 mA = 9.5 mA
    # Σ 1/R = 1/1000 + 1/3000 + 1/2000 = 11/6000 S = 1.833 mS
    # V_AB = 9.5 mA / 1.833 mS = 57/11 = 5.182 V
    # I1 = (12 − 5.182)/1k = 6.818 mA, I2 = (6 − 5.182)/3k = 0.2727 mA,
    # I3 = (−9 − 5.182)/2k = −7.091 mA  → toplam 0 (KCL)
    net = ("V1 1 0 DC 12\nR1 1 2 1k\nV2 3 0 DC 6\nR2 3 2 3k\n"
           f"V3 0 4 DC 9\nR3 4 2 2k\n{GND}")
    results, _, errors = solve(net, "DC", analysis_type="MILLMAN")
    assert not errors
    assert "Millman Formülü — V_AB" in titles(results)
    t = texts(results)
    assert any("V_AB = (12/1000 + 6/3000 + (" + MINUS + "9)/2000) / (1/1000 + 1/3000 + 1/2000)" in x
               for x in t)
    assert any("V_AB = 9,5 mA / 1,833 mS" in x for x in t)
    assert any("V_AB = V₂ " + MINUS + " V₀ = 5,182 V" in x for x in t)
    assert any("= 6,818 mA" in x for x in t)
    assert any("= " + MINUS + "7,091 mA" in x for x in t)
    assert not any("uygulanamadı" in x for x in t)


def test_millman_current_source_branch(solve):
    # A = Düğüm 1. Kol 1: V1 = 10 V, R1 = 2k (E1 = +10). Kol 2: R2 = 1k (E2 = 0).
    # Kol 3: I1 (0 → 1, B → A yönünde +3 mA) ile seri R3 = 5k → yalnızca I = 3 mA sayılır.
    # V_AB = (10/2000 + 0 + 0.003) / (1/2000 + 1/1000) = 8 mA / 1.5 mS = 5.333 V
    # I1 = (10 − 5.333)/2k = 2.333 mA, I2 = −5.333 mA, I3 = +3 mA → toplam 0
    net = f"V1 2 0 DC 10\nR1 2 1 2k\nR2 1 0 1k\nI1 0 3 DC 3m\nR3 3 1 5k\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="MILLMAN")
    assert not errors
    t = texts(results)
    assert any("V_AB = 8 mA / 1,5 mS" in x for x in t)
    assert any("V_AB = V₁ " + MINUS + " V₀ = 5,333 V" in x for x in t)
    assert any("kolun akımını değiştirmez" in x for x in t)       # seri R3 etkisiz
    assert any("I₃ = I1 akım kaynağının akımı = 3 mA" in x for x in t)


def test_millman_fallback_three_essential_nodes(solve):
    # 1, 2, 3 ve 0 düğümlerinin üçü ya da fazlası ≥3 eleman birleştiriyor → ikiden fazla ana düğüm
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\nR3 2 3 1k\nR4 3 0 1k\nR5 1 3 3k\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="MILLMAN")
    assert not errors
    t = texts(results)
    assert "Millman Teoremi" in titles(results)
    note = next(x for x in t if "Millman teoremi uygulanamadı" in x)
    assert "ana düğüm" in note and "Düğüm Gerilimleri" in note
    # Yedek anlatım düğüm gerilimi yöntemidir ve sonuçlar yine verilir
    assert "Düğüm Denklemleri (KCL)" in titles(results)
    assert "Sonuç" in titles(results)
    assert "Millman Formülü — V_AB" not in titles(results)


def test_millman_fallback_dependent_source(solve):
    # Bağımlı kaynaklı devre: Millman uygulanmaz, sebep söylenir
    net = f"V1 1 0 DC 10\nR1 1 2 1k\nR2 2 0 2k\nG1 0 2 V(R2) 1m\n{GND}"
    results, _, errors = solve(net, "DC", analysis_type="MILLMAN")
    assert not errors
    t = texts(results)
    note = next(x for x in t if "Millman teoremi uygulanamadı" in x)
    assert "bağımlı" in note and "Düğüm Gerilimleri" in note
    assert "Millman Formülü — V_AB" not in titles(results)
