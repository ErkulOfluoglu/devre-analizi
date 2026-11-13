"""
Yapay zekâ düzeltmeleri (Fable denetimi, 4. tur).

- Sayı denetimi birime bakar: devrede 12 V varken "12 kA" ya da "12 A" doğrulanmaz.
- "2.200 Ω" binlik ayırıcıyla da okunur; s ve J birimleri tanınır.
- Ders sabitleri yalnız uygun yazımla: "45°", "%99,3", "√3 ≈ 1,732" (birimsiz "45" değil).
- Alıştırmada öğrencinin yazdığı sayı, yazıyla sayı ve kesir de gizlenir.
- Kavram notları: RC/RL notu kendi devresine, rezonansta cos φ = 1, paralel RLC, RTS, dengesiz Δ.
- Ollama'dan anlamsız cevap ya da zaman aşımı öğrenciye doğru anlatılır.
- Çözülemeyen devre için yapay zekâya sorulmaz.
"""

import io
import urllib.error

import pytest

from llm import ollama
from llm.assistant import answer_question, concept_notes
from llm.numbers import REDACTED, check_answer_numbers, known_from
from models.request import AnalysisType
from parser.netlist_parser import parse_netlist

GND = "* GND1 — Referans toprak (Node 0)"
DIVIDER = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}"


def _statuses(answer, known, forbidden=(), given=None):
    text, checks = check_answer_numbers(answer, known, forbidden, given)
    return text, {c.text: c.status for c in checks}


# ── Birim duyarlı sayı denetimi ──

def test_numbers_must_match_their_unit():
    known = known_from([(12.0, "V"), (0.004, "A")])
    _, st = _statuses("Kaynak 12 V, akım 4 mA. Akım 12 kA olur. Akım 12 A olur.", known)
    assert st["12 V"] == "verified"
    assert st["4 mA"] == "verified"
    assert st["12 kA"] == "unverified"
    assert st["12 A"] == "unverified"


def test_unitless_number_still_matches_any_known_value():
    known = known_from(texts=["Akım 40 mA."])
    _, st = _statuses("Akım 40 olur.", known)    # birimsiz "40": metinde yazıldığı hâliyle eşleşir
    assert st["40"] == "verified"


def test_thousands_separator_and_new_units():
    known = known_from([(2200.0, "Ω"), (0.002, "s"), (0.5, "J")])
    _, st = _statuses("R = 2.200 Ω, τ = 2 ms, enerji 0,5 J.", known)
    assert st["2.200 Ω"] == "verified"
    assert st["2 ms"] == "verified"
    assert st["0,5 J"] == "verified"


@pytest.mark.parametrize("text, expected", [
    ("faz farkı 45°", "verified"),
    ("faz farkı 45 derece", "verified"),
    ("akım 45 olur", "unverified"),
    ("5τ sonra %99,3 tamamlanır", "verified"),
    ("değer 99,3 olur", "unverified"),
    ("√3 ≈ 1,732", "verified"),
    ("120 V", "unverified"),
])
def test_lesson_constants_need_the_right_writing(text, expected):
    _, checks = check_answer_numbers(text, known_from([(5.0, "V")]))
    assert checks[-1].status == expected, text


# ── Alıştırma: cevap sızıntısı ──

def test_number_words_and_fractions_are_redacted():
    known = known_from(texts=["V1 12 V"])
    given = known_from(texts=["V1 12 V"])
    text, st = _statuses("Düğüm gerilimi sekiz volt olur; akım 8/3 mA.", known,
                         forbidden=[8.0, 8 / 3 * 1e-3], given=given)
    assert "sekiz volt" not in text and "8/3" not in text
    assert text.count(REDACTED) == 2
    assert st["sekiz volt"] == "redacted" and st["8/3 mA"] == "redacted"


def test_given_value_in_words_is_not_redacted():
    given = known_from(texts=["V1: DC gerilim kaynağı 12 V"])
    text, _ = _statuses("Kaynak on iki volt verir.", given, forbidden=[12.0], given=given)
    assert "on iki volt" in text


def test_student_typed_answer_is_not_confirmed(solve, monkeypatch):
    parsed = parse_netlist(DIVIDER)
    results, _, _ = solve(DIVIDER, mode="DC", analysis_type="NODAL")
    monkeypatch.setattr("llm.ollama.chat", lambda model, msgs, **kw: "Evet, V₂ = 8 V doğru.")
    out = answer_question(parsed, results, AnalysisType.NODAL, True, None, None,
                          "V2 8 V mu?", [], "m", practice=True, practice_questions=results.practice)
    assert "8 V" not in out["answer"]
    assert REDACTED in out["answer"]


# ── Kavram notları ──

def test_series_notes_follow_the_circuit():
    rc = concept_notes(AnalysisType.NODAL, False, has_c=True, has_l=False)
    rl = concept_notes(AnalysisType.NODAL, False, has_c=False, has_l=True)
    rlc = concept_notes(AnalysisType.NODAL, False, has_c=True, has_l=True)
    assert "Seri RC" in rc and "Seri RL" not in rc
    assert "Seri RL" in rl and "Seri RC" not in rl
    assert "Seri RC" not in rlc and "Seri RL" not in rlc


def test_corrected_concept_notes():
    res = concept_notes(AnalysisType.RESONANCE, False)
    assert "cos φ = 1" in res and "Paralel RLC" in res
    tp = concept_notes(AnalysisType.THREE_PHASE, False)
    assert "RTS sırasında 30° geridedir" in tp
    assert "dengesizse √3 kuralı geçerli değildir" in tp
    assert "çeyrek periyot" in tp and "yarım periyotta" not in tp


# ── Ollama hataları ──

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.parametrize("body", [b"<html>hata</html>", b"[1, 2, 3]", b"\xff\xfe"])
def test_unreadable_server_reply_is_a_turkish_error(monkeypatch, body):
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: _Resp(body))
    with pytest.raises(ollama.OllamaError) as e:
        ollama._request("/api/chat", {}, 1.0)
    assert "cevap verdi" in str(e.value)


def test_slow_model_is_a_timeout_not_missing_ollama(monkeypatch):
    def slow(req, timeout):
        raise TimeoutError("timed out")
    monkeypatch.setattr("urllib.request.urlopen", slow)
    with pytest.raises(ollama.OllamaTimeout):
        ollama._request("/api/chat", {}, 1.0)

    def slow_url(req, timeout):
        raise urllib.error.URLError(TimeoutError("timed out"))
    monkeypatch.setattr("urllib.request.urlopen", slow_url)
    with pytest.raises(ollama.OllamaTimeout):
        ollama._request("/api/chat", {}, 1.0)


def test_api_ask_timeout_message(client, monkeypatch):
    monkeypatch.setattr("llm.ollama.get_status",
                        lambda: ollama.OllamaStatus(available=True, version="1", models=["gemma4:e4b"]))

    def slow_chat(*a, **kw):
        raise ollama.OllamaTimeout("300 saniye içinde cevap gelmedi.")
    monkeypatch.setattr("llm.ollama.chat", slow_chat)
    r = client.post("/llm/ask", json={"netlist": DIVIDER, "mode": "DC", "analysis_type": "NODAL",
                                      "question": "V2 kaç?", "device": "cpu"})
    assert r.status_code == 504
    assert "zamanında cevap veremedi" in r.json()["detail"]
    assert "Ollama" not in r.json()["detail"]


def test_api_ask_refuses_unsolvable_circuit(client, monkeypatch):
    monkeypatch.setattr("llm.ollama.get_status",
                        lambda: ollama.OllamaStatus(available=True, version="1", models=["gemma4:e4b"]))
    asked = []
    monkeypatch.setattr("llm.ollama.chat", lambda *a, **kw: asked.append(1) or "cevap")
    # İki ideal gerilim kaynağı paralel (farklı değer): çözülemez
    net = f"V1 1 0 DC 12\nV2 1 0 DC 5\nR1 1 0 1k\n{GND}"
    r = client.post("/llm/ask", json={"netlist": net, "mode": "DC", "analysis_type": "NODAL",
                                      "question": "V1 akımı?", "device": "cpu"})
    assert r.status_code == 422
    assert not asked
