"""
Sonuçlar sekmesindeki "Adım adım çözüm" listesi (solution_steps).

Fable denetimi (7. tur): liste hangi yöntem seçilirse seçilsin düğüm yönteminin
KVL/KCL tarifini gösteriyordu, çözücünün ham satırlarını ("V1 1 0 {12.0}") ve
birimsiz güç değerlerini yazıyordu. Asıl adım adım anlatım “Anlatım” sekmesindedir.
"""

import pytest
from fastapi.testclient import TestClient

from main import app

GND = "* GND1 — Referans toprak (Node 0)"
client = TestClient(app)
EX5 = "V1 1 0 DC 10\nR1 1 2 1000\nR2 2 0 2000\nR3 2 3 1000\nI1 0 3 DC 0.002"


def _steps(netlist, method="NODAL", mode="DC", freq=None, terminals=None):
    body = {"netlist": f"{netlist}\n{GND}", "mode": mode, "analysis_type": method,
            "frequency": freq}
    if terminals:
        body["thevenin_terminals"] = {"node_positive": terminals[0],
                                      "node_negative": terminals[1]}
    r = client.post("/analyze", json=body)
    assert r.status_code == 200
    return r.json()["solution_steps"]


def _titles(steps):
    return [s["title"] for s in steps]


@pytest.mark.parametrize("method", ["MESH", "SUPERPOSITION", "MILLMAN"])
def test_other_methods_do_not_show_the_nodal_recipe(method):
    steps = _steps(EX5, method)
    titles = _titles(steps)
    assert "KCL — Düğüm Denklemleri" not in titles
    assert "KVL — Gerilim Kaynak Kısıtları" not in titles
    node_step = next(s for s in steps if s["title"] == "Düğüm Gerilimleri (Çözüm)")
    assert "KCL" not in node_step["description"]
    assert "“Anlatım” sekmesindedir" in node_step["description"]


@pytest.mark.parametrize("method,terminals", [("NODAL", None), ("THEVENIN", ("3", "0"))])
def test_nodal_methods_keep_the_nodal_recipe(method, terminals):
    steps = _steps(EX5, method, terminals=terminals)
    assert "KCL — Düğüm Denklemleri" in _titles(steps)
    node_step = next(s for s in steps if s["title"] == "Düğüm Gerilimleri (Çözüm)")
    assert "KCL" in node_step["description"]


def test_model_step_hides_solver_lines():
    steps = _steps(EX5)
    model = next(s for s in steps if s["title"] == "Devre Modeli Oluşturma")
    assert model["equations"] == []
    assert "lcapy" not in model["description"]
    topo = next(s for s in steps if s["title"] == "Devre Topolojisi Belirleme")
    assert "Düğüm 0 (GND)" in topo["description"] and "Node" not in topo["description"]


def test_dc_power_lines_carry_units():
    steps = _steps(EX5)
    power = next(s for s in steps if s["title"].startswith("Güç Analizi"))
    assert "P_V1 = V·I = 10 V · (−2 mA) = −20 mW  (güç verir)" in power["equations"]
    assert "P_R2 = V·I = 8 V · 4 mA = 32 mW" in power["equations"]
    assert "Denge: ΣP_kaynak = 40 mW = ΣP_yük = 40 mW" in power["equations"]


def test_dc_thevenin_titles_in_turkish_without_phasors():
    steps = _steps("V1 1 0 DC 12\nR1 1 2 1000\nR2 2 0 2000\nR3 2 3 1000\nR4 3 0 1000",
                   "THEVENIN", terminals=("3", "0"))
    assert "Thevenin Eşdeğeri (Düğüm 3 – GND)" in _titles(steps)
    res = next(s for s in steps if s["title"] == "Thevenin Sonuçları")
    assert "∠" not in res["description"]
    assert res["description"].startswith("Vth = ") and "Rth = " in res["description"]


def test_capacitor_rule_only_in_ac_with_a_capacitor():
    dc = _steps("V1 1 0 DC 12\nR1 1 2 1000\nR2 2 3 1000\nR3 3 0 1000")
    for s in dc:
        assert "Kondansatörlerde" not in s["description"]
    ac = _steps("VAC1 1 0 SINE(0 10 50 0 0 0)\nR1 1 2 100\nC1 2 3 0.0001\nC2 3 0 0.0001",
                "NODAL", "AC_TIME", 50)
    topo = [s for s in ac if s["title"].startswith("Seri/Paralel")]
    assert topo and "Kondansatörlerde kurallar terstir" in topo[0]["description"]
