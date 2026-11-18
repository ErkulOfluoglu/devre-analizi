"""
Çevre anlatımında birim tutarlılığı ve fazladan basamak notu.

1) Bağımlı kaynaklı yol denklemleri amper cinsinden çözer: akım kaynağı satırları da A ile
   yazılmalı (aynı anlatımda "2 mA" ve "0,002" karışmasın).
   Devre: V1 10 V, R1 1k (1→2), R2 2k (2→4), E1 = 2·V_R1 (4→0), R3 1k (2→3), I1 2 mA (0→3).
   Çevre 2 kaynaktan 3 → 0 geçer, kaynak 0 → 3 → I₂ = −0,002 A.
   Çevre 1: 1000·I₁ + 2000·(I₁ − I₂) = 10 − 2·1000·I₁ → 5000·I₁ − 2000·I₂ = 10
            → 5000·I₁ + 4 = 10 → I₁ = 1,2 mA.
2) Örnek 7: I_R5 = I₃ − I₁ = 30,94 − 30,22 = 0,72 mA olurdu; sonuç 719,4 µA →
   işlenenler daha fazla basamakla yazılır ve bunu açıklayan not eklenir.
"""

from fastapi.testclient import TestClient

from main import app

GND = "* GND1 — Referans toprak (Node 0)"
client = TestClient(app)


def _texts(netlist: str):
    r = client.post("/analyze", json={"netlist": f"{netlist}\n{GND}", "mode": "DC",
                                      "analysis_type": "MESH"})
    assert r.status_code == 200
    return [b["text"] for s in r.json()["results"]["explanation"] for b in s["blocks"]]


def test_dependent_mesh_current_source_lines_stay_in_amperes():
    t = _texts("V1 1 0 DC 10\nR1 1 2 1000\nR2 2 4 2000\nE1 4 0 V(R1) 2\nR3 2 3 1000\n"
               "I1 0 3 DC 0.002\n* NODEPOS 0 300 270\n* NODEPOS 1 170 150\n"
               "* NODEPOS 2 340 140\n* NODEPOS 3 510 150\n* NODEPOS 4 340 200")
    assert "I₂ = −0,002 A" in t
    assert "I₂ = −2 mA" not in t
    assert not any("500 ile çarpalım" in x for x in t)
    assert "−I₂ = 0,002" in t
    assert any("Yönler ters" in x for x in t)
    assert any("I₁ = Δ₁/Δ" in x and x.endswith("= 1,2 mA") for x in t)


def test_close_mesh_currents_get_more_digits_and_a_note():
    t = _texts("V1 1 0 DC 20\nRs 1 2 100\nR1 2 3 200\nR2 3 0 300\nR3 2 4 400\n"
               "R4 4 0 500\nR5 3 4 600")
    line = next(x for x in t if x.startswith("I_R5 = "))
    assert "30,94 mA − 30,22 mA" not in line
    assert line.split("  (")[0].endswith("= 719,4 µA")
    assert any(x.startswith("Bazı satırlarda birbirine yakın iki değerin farkı") for x in t)
