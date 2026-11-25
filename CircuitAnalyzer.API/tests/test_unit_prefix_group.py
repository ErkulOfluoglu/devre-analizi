"""
Aynı satırda yan yana duran güç değerleri TEK önekle yazılır (kitaplardaki gibi):
"10,27 W + 394,7 mW" ya da "P_A = 898,6 W, P_B = 1,08 kW" gibi karışık önekler çıkmaz.
"""
import re

import pytest
from fastapi.testclient import TestClient

from explainer.formatting import eng_group
from main import app

GND = "\n* GND1 - Referans toprak"
_VAL = re.compile(r"(−?\d[\d,]*)\s?(m|k|M|µ)?(W|VAR|VA)\b")


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _lines(resp_json):
    out = []

    def walk(o):
        if isinstance(o, str):
            out.extend(o.split("\n"))
        elif isinstance(o, dict):
            for k, v in o.items():
                if k not in ("series", "points", "curve", "samples", "plot", "latex_formula"):
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(resp_json)
    return out


def _mixed_lines(lines):
    bad = []
    for ln in lines:
        prefixes = {m.group(2) or "" for m in _VAL.finditer(ln)}
        if len(prefixes) > 1:
            bad.append(ln)
    return bad


def test_eng_group_uses_prefix_of_largest_value():
    assert eng_group([1979, 194.6, 1988], ["W", "VAR", "VA"]) == ["1,979 kW", "0,1946 kVAR", "1,988 kVA"]
    assert eng_group([10.27, 0.3947, 19.74], "W") == ["10,27 W", "0,3947 W", "19,74 W"]
    assert eng_group([898.6, 1080], "W") == ["0,8986 kW", "1,08 kW"]
    assert eng_group([-450.5, 1200], ["VAR", "VA"]) == ["−0,4505 kVAR", "1,2 kVA"]


def test_eng_group_keeps_zero_and_all_zero_values():
    assert eng_group([0, 0.005], "A") == ["0 A", "5 mA"]
    assert eng_group([0, 0], "W") == ["0 W", "0 W"]


def test_dc_power_balance_line_has_one_prefix(client):
    r = client.post("/analyze", json={
        "netlist": "V1 1 0 DC 30\nR1 1 2 10\nR2 2 0 1k\nR3 2 0 20" + GND,
        "mode": "DC", "analysis_type": "NODAL"})
    assert r.status_code == 200
    lines = _lines(r.json())
    balance = [ln for ln in lines if ln.startswith("Güç dengesi")]
    assert balance, "güç dengesi satırı yok"
    assert not _mixed_lines(balance), balance
    assert "0,3947 W" in balance[0]


def test_unbalanced_three_phase_power_and_aron_lines_have_one_prefix(client):
    r = client.post("/analyze", json={
        "netlist": "U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 0 RST RMS\n"
                   "Y1 1 2 3 4 3PH_LOAD Y Z(40,30) Z(150,0) Z(60,-20)" + GND,
        "mode": "AC_PHASOR", "analysis_type": "THREE_PHASE", "value_display": "RMS"})
    assert r.status_code == 200
    lines = _lines(r.json())
    assert not _mixed_lines(lines), _mixed_lines(lines)
    assert any(ln.startswith("Aron: P_A = ") and "kW" in ln for ln in lines)
