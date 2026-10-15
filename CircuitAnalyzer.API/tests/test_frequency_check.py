"""
Kaynak frekansı denetimi testleri — çoklu frekans / süperpozisyon uyarısı.
"""

import math

from tests.conftest import as_complex
from tests.test_thevenin import GND, assert_close

RC = "R1 1 2 100\nC1 2 0 100u"


def analyze(client, netlist, mode="AC_PHASOR", frequency=None):
    payload = {"netlist": f"{netlist}\n{GND}", "mode": mode}
    if frequency is not None:
        payload["frequency"] = frequency
    resp = client.post("/analyze", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def rc_v2(f, vs=10):
    zc = 1 / (1j * 2 * math.pi * f * 100e-6)
    return vs * zc / (100 + zc)


def node_v(body, node):
    v = body["results"]["node_voltages"][node]["value"]
    return complex(v) if isinstance(v, (int, float)) else complex(
        v["real"], v["imaginary"])


def test_two_sine_sources_different_frequencies(client):
    net = ("VAC1 1 0 SINE(0 10 50 0 0 0)\nR1 1 2 100\n"
           "VAC2 3 0 SINE(0 5 60 0 0 0)\nR2 3 2 100\nC1 2 0 100u")
    body = analyze(client, net)
    assert body["status"] == "warning"
    w = [m for m in body["warnings"] if "farklı frekanslarda" in m]
    assert len(w) == 1
    assert "50 Hz: VAC1" in w[0] and "60 Hz: VAC2" in w[0]
    assert "GEÇERSİZ" in w[0]
    step = next(s for s in body["solution_steps"]
                if s["title"].startswith("Frekans Analizi"))
    assert step["equations"] == ["50 Hz: VAC1", "60 Hz: VAC2"]


def test_sine_and_phasor_with_different_global_frequency(client):
    # AC_PHASOR global frekansı (60 Hz) kullanır, SINE kendi 50 Hz'ini
    net = ("VAC1 1 0 SINE(0 10 50 0 0 0)\nR1 1 2 100\n"
           "VAC2 3 0 AC_PHASOR(5, 0)\nR2 3 2 100\nC1 2 0 100u")
    body = analyze(client, net, frequency=60)
    assert any("farklı frekanslarda" in m for m in body["warnings"])
    assert body["status"] == "warning"


def test_same_frequency_sources_no_warning(client):
    net = ("VAC1 1 0 SINE(0 10 50 0 0 0)\nR1 1 2 100\n"
           "VAC2 3 0 AC_PHASOR(5, 0)\nR2 3 2 100\nC1 2 0 100u")
    body = analyze(client, net, frequency=50)
    assert body["warnings"] == []
    assert body["status"] == "success"
    assert not any(s["title"].startswith("Frekans Analizi")
                   for s in body["solution_steps"])


def test_sine_frequency_used_when_request_has_none(client):
    # Eskiden V(2) sessizce 0 dönüyordu
    body = analyze(client, f"VAC1 1 0 SINE(0 10 50 0 0 0)\n{RC}")
    assert body["status"] == "success"
    assert any("kaynak frekansı kullanıldı: f = 50 Hz" in m
               for m in body["warnings"])
    assert_close(node_v(body, "2"), rc_v2(50))


def test_sine_frequency_mismatch_warns(client):
    body = analyze(client, f"VAC1 1 0 SINE(0 10 50 0 0 0)\n{RC}", frequency=60)
    assert body["status"] == "warning"
    assert any("analiz frekansından (60 Hz) farklı" in m
               for m in body["warnings"])
    assert_close(node_v(body, "2"), rc_v2(60))     # davranış korunur: 60 Hz


def test_phasor_without_frequency_is_an_error(client):
    # Eskiden V(2) = 0 dönüyordu — artık çözülmez ve açıkça hata verilir
    body = analyze(client, f"VAC1 1 0 AC_PHASOR(10, 0)\n{RC}")
    assert body["status"] == "warning"
    assert any("frekans gerekli" in e for e in body["errors"])
    assert body["results"]["node_voltages"] == {}


def test_phasor_without_frequency_resistive_circuit_ok(client):
    body = analyze(client, "VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 1k\nR2 2 0 1k")
    assert body["errors"] == []
    assert_close(node_v(body, "2"), 5)


def test_dc_source_in_ac_mode_reports_dc_component(client):
    net = f"VAC1 1 0 AC_PHASOR(10, 0)\nV1 3 0 DC 5\nR2 3 2 1k\n{RC}"
    body = analyze(client, net, frequency=50)
    assert body["status"] == "success"
    assert any("DC bileşenler (V1)" in m for m in body["warnings"])
    step = next(s for s in body["solution_steps"]
                if s["title"].startswith("Frekans Analizi"))
    assert "DC (0 Hz): V1" in step["equations"]


def test_ac_mode_without_ac_sources(client):
    body = analyze(client, "V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k", frequency=50)
    assert body["status"] == "warning"
    assert any("devrede AC kaynak yok" in m for m in body["warnings"])


def test_dc_mode_with_ac_source_and_offset(client):
    net = "V1 1 0 DC 12\nR1 1 2 1k\nVAC1 2 3 SINE(2 10 50 0 0 0)\nR2 3 0 1k"
    body = analyze(client, net, mode="DC")
    assert any(m.startswith("ℹ DC analizde AC kaynaklar (VAC1)")
               for m in body["warnings"])
    assert any("ofseti (VAC1: 2 V)" in m for m in body["warnings"])
    assert body["status"] == "warning"


def test_solver_without_warnings_list_appends_to_errors(solve):
    # Geriye uyumluluk: warnings listesi verilmezse mesajlar errors'a gider
    net = (f"VAC1 1 0 SINE(0 10 50 0 0 0)\nR1 1 2 100\n"
           f"VAC2 3 0 SINE(0 5 60 0 0 0)\nR2 3 2 100\nC1 2 0 100u\n{GND}")
    _, _, errors = solve(net, "AC_PHASOR")
    assert any("farklı frekanslarda" in e for e in errors)
