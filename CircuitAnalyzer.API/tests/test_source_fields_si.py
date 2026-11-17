"""
SINE / AC_PHASOR / COMPLEX / POLAR alanları SI önekli değer kabul eder ("2m", "1k", "1meg").
Okunamayan alan Python hatası değil, Türkçe satır hatası verir.
SINE'daki gecikme ve sönüm çözücüde yoktur: sıfır değilse öğrenci uyarılır.
"""

import pytest

from parser.netlist_parser import ElementType, parse_netlist
from solver.error_text import english_leak

GND = "\n* GND1 — Referans toprak (Node 0)"


def _one(line):
    p = parse_netlist(line)
    assert not p.errors, p.errors
    return p.elements[0]


def test_phasor_magnitude_with_milli_prefix():
    e = _one("VAC1 1 0 AC_PHASOR(2m, 30)")
    assert e.element_type == ElementType.AC_SOURCE_PHASOR
    assert e.params["amplitude"] == pytest.approx(0.002)
    assert e.params["phase"] == 30                          # açı derece olarak kalır
    assert e.params["phasor_complex"].real == pytest.approx(0.002 * 0.8660254)


def test_phasor_with_space_separated_prefixed_fields():
    e = _one("IAC1 1 0 AC_PHASOR(5m 45)")
    assert e.element_type == ElementType.CURRENT_AC_PHASOR
    assert e.params["amplitude"] == pytest.approx(0.005)


def test_sine_fields_accept_prefixes():
    e = _one("VAC1 1 0 SINE(0 5m 1k 0 0 0)")
    assert e.params["amplitude"] == pytest.approx(0.005)
    assert e.params["frequency"] == pytest.approx(1000.0)


def test_m_in_a_frequency_is_milli_and_meg_is_mega():
    assert _one("VAC1 1 0 SINE(0 1 1m 0 0 0)").params["frequency"] == pytest.approx(0.001)
    assert _one("VAC1 1 0 SINE(0 1 1M 0 0 0)").params["frequency"] == pytest.approx(0.001)
    assert _one("VAC1 1 0 SINE(0 1 2meg 0 0 0)").params["frequency"] == pytest.approx(2e6)


def test_plain_numbers_are_unchanged():
    e = _one("VAC1 1 0 SINE(0 10 50 0 0 30)")
    assert (e.params["offset"], e.params["amplitude"], e.params["frequency"], e.params["phase"]) == (0, 10, 50, 30)
    e = _one("VAC1 1 0 AC_PHASOR(10, -30)")
    assert (e.params["amplitude"], e.params["phase"]) == (10, -30)


def test_impedance_fields_accept_prefixes():
    z = _one("Z1 1 0 COMPLEX(1k, 2m)").params["impedance"]
    assert z == complex(1000.0, 0.002)
    p = _one("Z1 1 0 POLAR(1k, 90)").params["impedance"]
    assert p.imag == pytest.approx(1000.0) and abs(p.real) < 1e-9


@pytest.mark.parametrize("line, field", [
    ("VAC1 1 0 AC_PHASOR(2x, 30)", "büyüklük"),
    ("VAC1 1 0 AC_PHASOR(2, abc)", "faz (derece)"),
    ("VAC1 1 0 SINE(0 5q 50 0 0 0)", "genlik"),
    ("VAC1 1 0 SINE(0 5 fifty 0 0 0)", "frekans"),
    ("Z1 1 0 COMPLEX(a, 2)", "gerçek kısım"),
    ("Z1 1 0 POLAR(5, deg)", "açı (derece)"),
])
def test_unreadable_field_is_a_turkish_line_error(line, field):
    p = parse_netlist("V9 8 0 DC 1\n" + line)         # hata 2. satırda
    assert len(p.errors) == 1
    msg = p.errors[0]
    assert msg.startswith("Satır 2:") and field in msg and "sayı olarak okunamadı" in msg
    assert english_leak(msg) is None and "float" not in msg


def test_empty_or_missing_required_field_is_refused():
    for line in ("VAC1 1 0 AC_PHASOR()", "VAC1 1 0 AC_PHASOR(, 30)", "Z1 1 0 POLAR( )"):
        p = parse_netlist(line)
        assert p.errors and p.errors[0].startswith("Satır 1:"), line


def test_nan_and_inf_fields_are_refused():
    for line in ("VAC1 1 0 AC_PHASOR(nan, 0)", "VAC1 1 0 SINE(0 inf 50 0 0 0)", "R1 1 0 nan"):
        assert parse_netlist(line).errors, line


def test_unreadable_value_on_ordinary_element_is_a_line_error_not_an_exception():
    p = parse_netlist("V1 1 0 DC 5\nR1 1 2 abc")
    assert p.errors and p.errors[0].startswith("Satır 2:")


# ───────────── SINE: gecikme / sönüm uyarısı ─────────────

def _analyze(client, sine_fields):
    return client.post("/analyze", json={
        "netlist": f"VAC1 1 0 SINE({sine_fields})\nR1 1 2 100\nR2 2 0 100" + GND,
        "mode": "AC_TIME", "analysis_type": "NODAL", "frequency": 50})


def test_sine_delay_or_damping_is_warned_about(client):
    for fields in ("0 5 50 0.002 0 0", "0 5 50 0 10 0", "0 5 50 2m 1 30"):
        r = _analyze(client, fields)
        assert r.status_code == 200, fields
        body = r.json()
        assert body["status"] == "warning"
        msg = next(w for w in body["warnings"] if "gecikme ve sönüm" in w)
        assert msg.startswith("⚠ VAC1'in gecikme ve sönüm değerleri hesaba katılmadı")


def test_sine_without_delay_and_damping_has_no_warning(client):
    r = _analyze(client, "0 5 50 0 0 0")
    assert r.status_code == 200
    assert r.json()["status"] == "success"
    assert not any("gecikme" in w for w in r.json()["warnings"])
    r = _analyze(client, "0 5m 50")       # SI önekli, eksik alanlar sıfır
    assert r.status_code == 200
    assert not any("gecikme" in w for w in r.json()["warnings"])


def test_phasor_with_prefix_solves_end_to_end(client):
    r = client.post("/analyze", json={
        "netlist": "VAC1 1 0 AC_PHASOR(2m, 30)\nR1 1 2 100\nR2 2 0 100" + GND,
        "mode": "AC_PHASOR", "analysis_type": "NODAL", "frequency": 50})
    assert r.status_code == 200
    v1 = r.json()["results"]["node_voltages"]["1"]["value"]
    assert v1["magnitude"] == pytest.approx(0.002, rel=1e-3)
    assert v1["phase_degrees"] == pytest.approx(30.0, abs=0.01)
