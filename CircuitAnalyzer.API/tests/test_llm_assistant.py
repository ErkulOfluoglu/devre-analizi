"""
CircuitAnalyzer API — LLM Asistanı ve API Uç Noktaları Testleri

Test edilen modül:
- llm/assistant.py (describe_element, circuit_text, explanation_text, build_messages, known_values, answer_question)
- main.py (GET /llm/status, POST /llm/ask)
"""

import pytest
from fastapi.testclient import TestClient

from llm import ollama
from llm.assistant import (
    MAX_EXPLANATION_CHARS,
    MAX_HISTORY_TURNS,
    answer_question,
    build_messages,
    circuit_text,
    describe_element,
    explanation_text,
    known_values,
)
from llm.numbers import REDACTED
from models.request import AnalysisMode, AnalysisType, TheveninTerminals
from models.response import ExplanationBlock, ExplanationSection
from parser.netlist_parser import parse_netlist

GND = "* GND1 — Referans toprak (Node 0)"
DIVIDER_NETLIST = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}"


def test_describe_element_and_circuit_text():
    """Devre elemanlarının Türkçe açıklamaları ve devre özet metninin oluşturulması."""
    parsed = parse_netlist(DIVIDER_NETLIST)
    desc_v1 = describe_element(parsed.elements[0])
    desc_r1 = describe_element(parsed.elements[1])

    assert "V1: DC gerilim kaynağı 12 V" in desc_v1
    assert "R1: direnç 1 kΩ" in desc_r1
    assert "Düğüm 1 – Düğüm 2" in desc_r1

    ctx = circuit_text(parsed, is_dc=True, frequency=None)
    assert ctx.startswith("DEVRE:")
    assert "R1: direnç 1 kΩ" in ctx
    assert "Analiz: DC" in ctx


def test_explanation_text_formatting_and_truncation():
    """Anlatım bölümlerinin metne dökülmesi ve azami karakter sınırının uygulanması."""
    sections = [
        ExplanationSection(
            title="Giriş",
            blocks=[ExplanationBlock(kind="text", text="Devre inceleniyor.")],
        ),
        ExplanationSection(
            title="Uzun Bölüm",
            blocks=[ExplanationBlock(kind="math", text="X = " + "1" * (MAX_EXPLANATION_CHARS + 500))],
        ),
    ]
    txt = explanation_text(sections)
    assert "## Giriş" in txt
    assert "Devre inceleniyor." in txt
    assert "[… anlatımın devamı kısaltıldı]" in txt


def test_build_messages_normal_mode(solve):
    """Gerilim bölücü devresi için normal modda sistem mesajı içeriği ve geçmişin sınırlandırılması."""
    parsed = parse_netlist(DIVIDER_NETLIST)
    results, _, _ = solve(DIVIDER_NETLIST, mode="DC", analysis_type="NODAL")

    # 10 turluk geçmiş oluşturuluyor (en eski 0, en yeni 9)
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"tur_{i}"}
        for i in range(10)
    ]
    question = "Düğüm 2 gerilimi nasıl hesaplanır?"

    messages = build_messages(
        parsed=parsed,
        results=results,
        analysis_type=AnalysisType.NODAL,
        is_dc=True,
        frequency=None,
        terminals=None,
        question=question,
        history=history,
        practice=False,
        practice_questions=[],
    )

    # 1 system + MAX_HISTORY_TURNS (6) + 1 user = 8 mesaj
    assert len(messages) == 1 + MAX_HISTORY_TURNS + 1

    # İlk mesaj system ve zorunlu anahtar kelimeleri içermeli
    sys_msg = messages[0]
    assert sys_msg["role"] == "system"
    content = sys_msg["content"]
    assert "DEVRE:" in content
    assert "R1: direnç 1 kΩ" in content
    assert "Düğüm gerilimleri" in content
    assert "Devreyi Tanıyalım" in content  # Çözüm anlatım başlığı

    # Son mesaj kullanıcının sorusu olmalı
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == question

    # Geçmişin yalnızca son 6 turu sırayla eklenmeli (tur_4 .. tur_9)
    history_in_messages = [m["content"] for m in messages[1:-1]]
    expected_history = [f"tur_{i}" for i in range(4, 10)]
    assert history_in_messages == expected_history


def test_build_messages_practice_mode(solve):
    """Alıştırma modunda sistem mesajının 'ALIŞTIRMA' içermesi ve çözüm sonuçlarını gizlemesi."""
    parsed = parse_netlist(DIVIDER_NETLIST)
    results, _, _ = solve(DIVIDER_NETLIST, mode="DC", analysis_type="NODAL")

    messages = build_messages(
        parsed=parsed,
        results=results,
        analysis_type=AnalysisType.NODAL,
        is_dc=True,
        frequency=None,
        terminals=None,
        question="Nereden başlamalıyım?",
        history=[],
        practice=True,
        practice_questions=results.practice,
    )

    sys_content = messages[0]["content"]

    # "ALIŞTIRMA" başlığı bulunmalı
    assert "ALIŞTIRMA" in sys_content

    # Alıştırma sorularının etiketleri sistem mesajında yer almalı
    for q in results.practice:
        assert q.label in sys_content

    # Çözüm anlatımı ve sayısal sonuçlar (8 V) modele verilmemeli
    assert "Devreyi Tanıyalım" not in sys_content
    assert "8 V" not in sys_content


def test_answer_question_normal_and_practice(solve, monkeypatch):
    """answer_question: normal modda sayı doğrulama, alıştırma modunda cevapların gizlenmesi."""
    parsed = parse_netlist(DIVIDER_NETLIST)
    results, _, _ = solve(DIVIDER_NETLIST, mode="DC", analysis_type="NODAL")

    # Modelin ürettiği varsayılan cevap
    fake_reply = "V₂ = 8 V, akım 4 mA, uydurma 7.5 V"
    monkeypatch.setattr("llm.ollama.chat", lambda model, msgs: fake_reply)

    # 1) Normal mod
    out_normal = answer_question(
        parsed=parsed,
        results=results,
        analysis_type=AnalysisType.NODAL,
        is_dc=True,
        frequency=None,
        terminals=None,
        question="Sonuç nedir?",
        history=[],
        model="test-model",
        practice=False,
        practice_questions=[],
    )

    statuses = {text: status for text, status in out_normal["numbers"]}
    assert statuses.get("8 V") == "verified"
    assert statuses.get("4 mA") == "verified"
    assert statuses.get("7.5 V") == "unverified"
    assert "7.5 V" in out_normal["note"]

    # 2) Alıştırma modu
    out_practice = answer_question(
        parsed=parsed,
        results=results,
        analysis_type=AnalysisType.NODAL,
        is_dc=True,
        frequency=None,
        terminals=None,
        question="Sonuç nedir?",
        history=[],
        model="test-model",
        practice=True,
        practice_questions=results.practice,
    )

    # Alıştırma cevabı gizlenmeli (8 V sansürlenmeli)
    assert REDACTED in out_practice["answer"]
    assert "8 V" not in out_practice["answer"]
    assert "gizlendi" in out_practice["note"]

    practice_statuses = {text: status for text, status in out_practice["numbers"]}
    assert practice_statuses.get("8 V") == "redacted"
    assert practice_statuses.get("7.5 V") == "unverified"


def test_api_status_unavailable(client, monkeypatch):
    """GET /llm/status: Ollama çalışmadığında available=False ve 'ollama.com' önerisi."""
    monkeypatch.setattr("llm.ollama.get_status", lambda: ollama.OllamaStatus(available=False))
    # Bu bilgisayarda gerçekten kurulu bir Ollama varsa "kurulu ama kapalı" denir; test kurulu olmadığını varsayar
    monkeypatch.setattr("llm.system_info.find_ollama_app", lambda: None)

    resp = client.get("/llm/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert "ollama.com adresinden" in data["message"]


def test_api_status_no_models(client, monkeypatch):
    """GET /llm/status: Ollama çalışıyor fakat hiç model yoksa 'ollama pull' önerisi."""
    monkeypatch.setattr(
        "llm.ollama.get_status",
        lambda: ollama.OllamaStatus(available=True, version="0.9.0", models=[]),
    )

    resp = client.get("/llm/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert "ollama pull" in data["message"]


def test_api_status_with_model(client, monkeypatch):
    """GET /llm/status: Model kurulu olduğunda selected_model'in seçilmesi."""
    monkeypatch.setattr(
        "llm.ollama.get_status",
        lambda: ollama.OllamaStatus(available=True, version="0.9.0", models=["gemma3:4b"]),
    )

    resp = client.get("/llm/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["selected_model"] == "gemma3:4b"


def test_api_ask_unavailable(client, monkeypatch):
    """POST /llm/ask: Ollama çalışmadığında 503 HTTP hatası dönmesi."""
    monkeypatch.setattr("llm.ollama.get_status", lambda: ollama.OllamaStatus(available=False))

    payload = {
        "netlist": DIVIDER_NETLIST,
        "mode": "DC",
        "analysis_type": "NODAL",
        "question": "Düğüm gerilimi nedir?",
    }
    resp = client.post("/llm/ask", json=payload)
    assert resp.status_code == 503


def test_api_ask_no_models(client, monkeypatch):
    """POST /llm/ask: Ollama'da model bulunmadığında 400 HTTP hatası dönmesi."""
    monkeypatch.setattr(
        "llm.ollama.get_status",
        lambda: ollama.OllamaStatus(available=True, version="0.9.0", models=[]),
    )

    payload = {
        "netlist": DIVIDER_NETLIST,
        "mode": "DC",
        "analysis_type": "NODAL",
        "question": "Düğüm gerilimi nedir?",
    }
    resp = client.post("/llm/ask", json=payload)
    assert resp.status_code == 400


def test_api_ask_success(client, monkeypatch):
    """POST /llm/ask: Başarılı istekte 200, answer, model, numbers listesi ve note dönmesi."""
    monkeypatch.setattr(
        "llm.ollama.get_status",
        lambda: ollama.OllamaStatus(available=True, version="0.9.0", models=["gemma3:4b"]),
    )
    monkeypatch.setattr("llm.ollama.chat", lambda model, msgs: "Düğüm gerilimi 8 V olarak hesaplanır.")

    payload = {
        "netlist": DIVIDER_NETLIST,
        "mode": "DC",
        "analysis_type": "NODAL",
        "question": "Düğüm 2 gerilimi nedir?",
    }
    resp = client.post("/llm/ask", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert "answer" in data
    assert "8 V" in data["answer"]
    assert data["model"] == "gemma3:4b"
    assert isinstance(data["numbers"], list)
    assert data["numbers"][0]["text"] == "8 V"
    assert data["numbers"][0]["status"] == "verified"
    assert "note" in data


def test_api_ask_chat_error(client, monkeypatch):
    """POST /llm/ask: Ollama chat sırasında OllamaError fırlatırsa 400 dönmesi ve hatayı içermesi."""
    monkeypatch.setattr(
        "llm.ollama.get_status",
        lambda: ollama.OllamaStatus(available=True, version="0.9.0", models=["gemma3:4b"]),
    )

    def _failing_chat(model, msgs):
        raise ollama.OllamaError("boom")

    monkeypatch.setattr("llm.ollama.chat", _failing_chat)

    payload = {
        "netlist": DIVIDER_NETLIST,
        "mode": "DC",
        "analysis_type": "NODAL",
        "question": "Soru?",
    }
    resp = client.post("/llm/ask", json=payload)
    assert resp.status_code == 400
    assert "boom" in resp.json()["detail"]


def test_api_ask_invalid_netlist(client, monkeypatch):
    """POST /llm/ask: Geçersiz netlist gönderildiğinde 400 HTTP hatası dönmesi."""
    monkeypatch.setattr(
        "llm.ollama.get_status",
        lambda: ollama.OllamaStatus(available=True, version="0.9.0", models=["gemma3:4b"]),
    )

    payload = {
        "netlist": "XYZ",
        "mode": "DC",
        "analysis_type": "NODAL",
        "question": "Soru?",
    }
    resp = client.post("/llm/ask", json=payload)
    assert resp.status_code == 400


def test_api_ask_ac_request_without_frequency(client, monkeypatch):
    """POST /llm/ask: AC analizde frekans null verildiğinde kaynak frekansının kullanılması ve 200 dönmesi."""
    monkeypatch.setattr(
        "llm.ollama.get_status",
        lambda: ollama.OllamaStatus(available=True, version="0.9.0", models=["gemma3:4b"]),
    )
    monkeypatch.setattr("llm.ollama.chat", lambda model, msgs: "AC gerilimi 10 V.")

    ac_netlist = (
        "VAC1 1 0 SINE(0 10 50 0 0 0)\n"
        "R1 1 2 100\n"
        "C1 2 0 100u\n"
        f"{GND}"
    )
    payload = {
        "netlist": ac_netlist,
        "mode": "AC_PHASOR",
        "frequency": None,
        "analysis_type": "NODAL",
        "question": "Devre hakkında bilgi verir misiniz?",
    }
    resp = client.post("/llm/ask", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "AC gerilimi 10 V."
    assert data["numbers"][0]["text"] == "10 V"
    assert data["numbers"][0]["status"] == "verified"
