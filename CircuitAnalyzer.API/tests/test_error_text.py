"""
Öğrenciye İngilizce hata metni gitmemeli (lcapy / SymPy / NumPy / Python iletileri).

- solver.error_text.turkish_error: kendi Türkçe hatalarımız aynen geçer, bilinen İngilizce iletiler
  özel Türkçe cümleye, gerisi genel bir cümleye çevrilir; ham hata stderr'e yazılır.
- Gerçek bozuk girdilerle /analyze: errors / warnings / detail içinde İngilizce söz kalmaz.
- Devre modeli kurulamazsa yanıt "başarılı" değil, HTTP 422 olur.
"""

import pytest

from solver.error_text import (
    GENERIC_TEXT, english_leak, is_singular_error, turkish_error,
)
from solver.resonance import ResonanceNotApplicable

GND = "\n* GND1 — Referans toprak (Node 0)"


def _texts(response) -> str:
    """Yanıttaki öğrenciye görünen tüm metinler."""
    body = response.json()
    if response.status_code != 200:
        return str(body.get("detail", ""))
    return "\n".join(body["errors"] + body["warnings"])


def _post(client, netlist, mode="DC", analysis_type="NODAL", **extra):
    return client.post("/analyze", json={"netlist": netlist + GND, "mode": mode,
                                         "analysis_type": analysis_type, **extra})


# ───────────── yardımcının kendisi ─────────────

def test_own_turkish_exception_passes_through_unchanged(capsys):
    text = turkish_error(ResonanceNotApplicable("Devrede bobin yok; rezonans oluşmaz."))
    assert text == "Devrede bobin yok; rezonans oluşmaz."
    # ham hata yine de geliştirici kaydına (stderr) yazılır
    assert "ResonanceNotApplicable" in capsys.readouterr().err


def test_plain_exception_raised_in_our_code_with_turkish_text_passes_through():
    try:
        raise ValueError("AC empedans için frekans gerekli.")
    except ValueError as e:
        assert turkish_error(e) == "AC empedans için frekans gerekli."


@pytest.mark.parametrize("exc, expected", [
    (ValueError("MNA A matrix is not invertible"), "tek bir çözüme varmıyor"),
    (RuntimeError("Matrix is singular to working precision"), "tek bir çözüme varmıyor"),
    (ValueError("Unknown component 'X1'"), "tanımadığı bir eleman"),
    (FileNotFoundError("Could not open R1 1 0 100.0"), "devre tanımı okunamadı"),
    (ValueError("could not convert string to float: '2x'"), "sayı olarak okunamadı"),
    (ValueError("invalid literal for int() with base 10: 'a'"), "sayı olarak okunamadı"),
    (ZeroDivisionError("division by zero"), "sıfıra bölme"),
    (OverflowError("math range error overflow"), "sonsuz ya da tanımsız"),
])
def test_known_english_messages_get_specific_turkish_text(exc, expected, capsys):
    text = turkish_error(exc, "deneme")
    assert expected in text
    assert english_leak(text) is None
    err = capsys.readouterr().err
    assert str(exc) in err and "deneme" in err        # ham hata kaybolmaz


def test_english_text_with_turkish_letters_is_not_mistaken_for_ours():
    # Düğüm adlarında Türkçe harf olabilir; lcapy iletisi yine İngilizcedir
    text = turkish_error(RuntimeError("Unknown component 'Ü1' in netlist"))
    assert english_leak(text) is None
    assert "Unknown" not in text


def test_unknown_exception_becomes_generic_sentence(capsys):
    text = turkish_error(KeyError("weird_internal_key"))
    assert text == GENERIC_TEXT
    assert "weird_internal_key" in capsys.readouterr().err


def test_singular_detection():
    assert is_singular_error(ValueError("MNA A matrix is not invertible"))
    assert not is_singular_error(ValueError("başka"))


# ───────────── uçtan uca: gerçek bozuk girdiler ─────────────

@pytest.mark.parametrize("netlist", [
    "V1 1 0 DC 12\nR1 1 2 abc\nR2 2 0 1k",                     # bozuk direnç değeri
    "V1 1 0 DC xyz\nR1 1 0 1k",                                 # bozuk kaynak değeri
    "VAC1 1 0 AC_PHASOR(2x, 30)\nR1 1 0 100",                   # bozuk fazör alanı
    "VAC1 1 0 AC_PHASOR()\nR1 1 0 100",                         # boş fazör
    "VAC1 1 0 SINE(0 5q 50 0 0 0)\nR1 1 0 100",                 # bozuk sinüs alanı
    "Z1 1 0 COMPLEX(a, b)\nV1 1 0 DC 1",                        # bozuk empedans
    "V1 1 0 DC 12\nQ7 1 2 3\nR1 1 0 100",                       # bilinmeyen eleman
    "V1 1 0 DC 12\nR1 1 0 nan",                                 # sayı değil (nan)
])
def test_bad_input_gives_turkish_error_without_english(client, netlist):
    r = _post(client, netlist, mode="AC_PHASOR" if "AC_" in netlist or "SINE" in netlist else "DC",
              frequency=50)
    assert r.status_code == 400
    detail = _texts(r)
    assert detail
    assert english_leak(detail) is None, detail
    assert "ValueError" not in detail and "float" not in detail


def test_unreadable_value_names_the_line(client):
    r = _post(client, "V1 1 0 DC 12\nR1 1 2 abc\nR2 2 0 1k")
    assert "Satır 2" in r.json()["detail"]


def test_single_line_circuit_is_a_real_failure_not_success(client, capsys):
    """Tek satırlık devre: model kurulamıyordu ama yanıt 'başarılı' + sonuçsuz geliyordu."""
    r = _post(client, "R1 1 0 100")
    assert r.status_code == 422
    detail = _texts(r)
    assert "Devre modeli oluşturulamadı" in detail
    assert english_leak(detail) is None, detail
    assert "Could not open" in capsys.readouterr().err     # ham hata geliştirici kaydında


def test_singular_circuit_message_is_turkish(client):
    r = _post(client, "V1 1 0 DC 5\nR1 1 0 100\nE1 2 0 V(R1) 1\nR2 2 3 100\nV2 3 2 DC 0")
    # hangi yoldan geçerse geçsin: İngilizce sızmamalı
    assert english_leak(_texts(r)) is None


# ───────────── çözücünün içinden sızan ham hatalar ─────────────

@pytest.mark.parametrize("target, raised", [
    ("build_explanation", ValueError("could not convert string to float: 'x'")),
    ("build_questions", RuntimeError("MNA A matrix is not invertible")),
    ("generate_topology_step", KeyError("Unknown component")),
    ("generate_solution_steps", AttributeError("'NoneType' object has no attribute 'foo'")),
])
def test_exceptions_inside_solver_stages_are_turkish(client, monkeypatch, capsys, target, raised):
    import solver.circuit_solver as cs

    def boom(*a, **k):
        raise raised
    monkeypatch.setattr(cs, target, boom)
    r = _post(client, "V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k")
    assert r.status_code == 200
    text = _texts(r)
    assert text, "aşama hatası kullanıcıya bildirilmeli"
    assert english_leak(text) is None, text
    assert "NoneType" not in text and "KeyError" not in text
    assert str(raised).strip("'") .split(":")[0].split("'")[0] in capsys.readouterr().err   # ham hata stderr'de


def test_model_build_failure_is_unsolvable_with_turkish_text(client, monkeypatch):
    import solver.circuit_solver as cs

    def boom(*a, **k):
        raise ValueError("Unknown component 'X9'")
    monkeypatch.setattr(cs, "make_circuit", boom)
    r = _post(client, "V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k")
    assert r.status_code == 422
    assert "tanımadığı bir eleman" in r.json()["detail"]
    assert english_leak(r.json()["detail"]) is None
