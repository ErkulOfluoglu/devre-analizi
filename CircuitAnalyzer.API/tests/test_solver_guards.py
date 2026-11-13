"""
Sessizce yanlış sonuç veren durumlar (Fable denetimi, 2. ve 6. tur).

- Aynı adlı iki eleman: ikinci satır yok sayılıyor, V2 = 0 V çıkıyordu.
- Tanınmayan satır atlanıyor, devre eksik çözülüyordu ("2,2k", "n-1").
- Thevenin uçları aynı düğüm: sahte "Rth = 0 Ω".
- Geçici durum uygulanamayınca yeşil "Çözüm başarılı" görünüyordu.
- Anahtar açılınca yalnız kalan kondansatörün gerilimi söylenmiyordu.
"""

import pytest

from parser.netlist_parser import parse_netlist

GND = "\n* GND1 — Referans toprak (Node 0)"


def _analyze(client, netlist, analysis_type="NODAL", **extra):
    return client.post("/analyze", json={"netlist": netlist + GND, "mode": "DC",
                                         "analysis_type": analysis_type, **extra})


def test_duplicate_element_name_is_refused(client):
    r = _analyze(client, "V1 1 0 DC 12\nR1 1 2 1k\nR1 2 0 2k")
    assert r.status_code == 400
    assert "“R1” adı 2. satırda da kullanılmış" in r.json()["detail"]


def test_duplicate_name_ignores_case():
    p = parse_netlist("V1 1 0 DC 12\nR1 1 2 1k\nr1 2 0 2k")
    assert any("adı 2. satırda da kullanılmış" in e for e in p.errors)
    assert [e.id for e in p.elements] == ["V1", "R1"]


@pytest.mark.parametrize("line", ["Q7 1 2 3", "R3 2 0 2,2k", "R4 n-1 0 1k"])
def test_unrecognised_line_is_refused_not_skipped(client, line):
    r = _analyze(client, f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{line}")
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "Satır 4 anlaşılamadı" in detail
    assert line in detail


def test_comments_and_end_are_still_fine(client):
    r = _analyze(client, "* başlık\nV1 1 0 DC 12\nR1 1 2 1k\n\nR2 2 0 2k\n.end")
    assert r.status_code == 200


@pytest.mark.parametrize("analysis_type", ["THEVENIN", "NORTON"])
def test_thevenin_terminals_on_the_same_node_are_refused(client, analysis_type):
    r = _analyze(client, "V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k", analysis_type,
                 thevenin_terminals={"node_positive": "2", "node_negative": "2"})
    assert r.status_code == 400
    assert "aynı düğüm olamaz" in r.json()["detail"]


def test_thevenin_terminals_on_different_nodes_still_work(client):
    r = _analyze(client, "V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k", "THEVENIN",
                 thevenin_terminals={"node_positive": "2", "node_negative": "0"})
    assert r.status_code == 200


def test_transient_fallback_is_a_warning_not_success(client):
    # İkinci dereceden (RLC) devre: geçici durum yöntemi uygulanamaz
    r = _analyze(client, "V1 1 0 DC 10\nS1 1 2 NO\nR1 2 3 100\nL1 3 4 10m\nC1 4 0 1u", "TRANSIENT")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "warning"
    assert any("Geçici durum uygulanamadı" in e for e in body["errors"])


def test_isolated_capacitor_keeps_its_voltage_in_the_message(client):
    # NC anahtar t = 0'da açılır; C1 hiçbir yola bağlı kalmaz ve 9 V'ta kalır
    r = _analyze(client, "V1 1 0 DC 9\nR1 1 2 1k\nS1 2 3 NC\nC1 3 0 1u", "TRANSIENT")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "warning"
    msg = next(e for e in body["errors"] if "Geçici durum uygulanamadı" in e)
    assert "gerilimini korur" in msg
    assert "9 V" in msg
