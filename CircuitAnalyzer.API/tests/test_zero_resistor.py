"""
R = 0 direnç: iletkenlik sonsuz olur ve yanıt JSON'a çevrilemezdi (HTTP 500).
Parser şimdi bu satırı Türkçe hatayla reddeder (HTTP 400); yanıtta sonsuz/NaN kalırsa
da 500 yerine Türkçe açıklama (HTTP 422) döner.
"""

import pytest
from fastapi.testclient import TestClient

from main import app
from parser.netlist_parser import parse_netlist

client = TestClient(app)

GND = "\n\n* GND1 — Referans toprak"


@pytest.mark.parametrize("netlist, rid, line", [
    ("V1 1 0 DC 10\nR1 1 2 0\nR2 2 0 10", "R1", 2),
    ("V1 1 0 DC 10\nR1 1 0 0", "R1", 2),
    ("V1 1 0 DC 10\nR1 1 2 10\nR2 2 0 0", "R2", 3),
])
@pytest.mark.parametrize("mode", ["DC", "AC_PHASOR"])
def test_zero_resistor_is_rejected_with_400(netlist, rid, line, mode):
    body = {"netlist": netlist + GND, "mode": mode, "analysis_type": "NODAL"}
    if mode == "AC_PHASOR":
        body["netlist"] = body["netlist"].replace("V1 1 0 DC 10", "V1 1 0 AC_PHASOR(10, 0)")
    resp = client.post("/analyze", json=body)
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert f"Satır {line}: {rid} direncinin değeri 0 olamaz; kısa devre için tel kullanın." in detail


def test_parser_records_error_and_skips_the_element():
    parsed = parse_netlist("V1 1 0 DC 10\nR1 1 2 0\nR2 2 0 10")
    assert parsed.errors == ["Satır 2: R1 direncinin değeri 0 olamaz; kısa devre için tel kullanın."]
    assert [e.id for e in parsed.elements] == ["V1", "R2"]


def test_small_nonzero_resistor_still_works():
    resp = client.post("/analyze", json={
        "netlist": "V1 1 0 DC 10\nR1 1 2 1m\nR2 2 0 10" + GND, "mode": "DC", "analysis_type": "NODAL"})
    assert resp.status_code == 200, resp.text


def test_non_finite_result_gives_turkish_error_not_500(monkeypatch):
    import main
    from models.response import AnalysisResults, NodeVoltage

    def fake_solve(**kwargs):
        res = AnalysisResults()
        res.node_voltages = {"1": NodeVoltage(value=float("inf"))}
        return res, [], []

    monkeypatch.setattr(main, "solve_circuit", fake_solve)
    resp = client.post("/analyze", json={
        "netlist": "V1 1 0 DC 10\nR1 1 0 10" + GND, "mode": "DC", "analysis_type": "NODAL"})
    assert resp.status_code == 422, resp.text
    assert "Devre çözülemedi" in resp.json()["detail"]
