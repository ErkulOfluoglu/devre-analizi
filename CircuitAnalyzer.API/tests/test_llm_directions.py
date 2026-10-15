"""
CircuitAnalyzer API — LLM Akım Yönleri ve Güç Açıklamaları Testleri

Test edilen fonksiyonlar:
- llm/assistant.py (current_directions_text, build_messages)
"""

import pytest

from llm.assistant import build_messages, current_directions_text
from models.request import AnalysisType
from parser.netlist_parser import parse_netlist

GND = "* GND1 — Referans toprak (Node 0)"


def test_current_directions_dc_voltage_divider(solve):
    """DC gerilim bölücü devresinde eleman akım yönleri ve kaynak güç aktarımının doğrulanması."""
    netlist = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}"
    parsed = parse_netlist(netlist)
    results, _, _ = solve(netlist, mode="DC", analysis_type="NODAL")

    text = current_directions_text(parsed, results, is_dc=True)

    # V1 kaynak akımı ve güç durumu
    assert "I_V1 = \u22124 mA" in text
    assert "EKSİ" in text
    assert "GND → Düğüm 1" in text
    assert "V1 devreye güç VERİYOR" in text

    # R1 direnci akım yönü ve işareti
    r1_lines = [line for line in text.splitlines() if "I_R1" in line]
    assert len(r1_lines) == 1
    r1_line = r1_lines[0]
    assert "Düğüm 1 → Düğüm 2" in r1_line
    assert "pozitif" in r1_line


def test_current_directions_dc_current_source(solve):
    """DC akım kaynaklı devrede direnç ve akım kaynağı akış yönlerinin doğrulanması."""
    netlist = f"V1 1 0 DC 10\nR1 1 2 1k\nR2 2 0 2k\nR3 2 3 1k\nI1 0 3 DC 2m\n{GND}"
    parsed = parse_netlist(netlist)
    results, _, _ = solve(netlist, mode="DC", analysis_type="NODAL")

    text = current_directions_text(parsed, results, is_dc=True)

    # R3 direnci satırı: referansa göre eksi çıkması ve gerçek yönü
    r3_lines = [line for line in text.splitlines() if "I_R3" in line]
    assert len(r3_lines) == 1
    r3_line = r3_lines[0]
    assert "EKSİ" in r3_line
    assert "Düğüm 3 → Düğüm 2" in r3_line

    # I1 akım kaynağı satırı: akım kaynağı tanımı ve çıkış ucu
    i1_lines = [line for line in text.splitlines() if "I1 bir akım kaynağıdır" in line]
    assert len(i1_lines) == 1
    i1_line = i1_lines[0]
    assert "akım kaynağıdır" in i1_line
    assert "Düğüm 3 ucundan çıkar" in i1_line


def test_current_directions_ac_rl(solve):
    """AC RL devresinde fazör akım ifadeleri ve kaynak güç yönünün doğrulanması."""
    netlist = f"VAC1 1 0 SINE(0 20 60 0 0 45)\nR1 1 2 50\nL1 2 0 100m\n{GND}"
    parsed = parse_netlist(netlist)
    results, _, _ = solve(netlist, mode="AC_PHASOR", frequency=None, analysis_type="NODAL")

    text = current_directions_text(parsed, results, is_dc=False)

    assert "fazör" in text
    assert "180°" in text
    assert "VAC1 devreye güç VERİYOR" in text


def test_build_messages_practice_mode_directions_visibility(solve):
    """Sistem mesajında akım yönlerinin normal modda bulunması, alıştırma modunda gizlenmesi."""
    netlist = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}"
    parsed = parse_netlist(netlist)
    results, _, _ = solve(netlist, mode="DC", analysis_type="NODAL")

    # Normal modda akım yönleri ve güç bölümü sistem mesajında yer almalı
    messages_normal = build_messages(
        parsed=parsed,
        results=results,
        analysis_type=AnalysisType.NODAL,
        is_dc=True,
        frequency=None,
        terminals=None,
        question="Düğüm 2 gerilimi nedir?",
        history=[],
        practice=False,
        practice_questions=[],
    )
    assert "AKIM YÖNLERİ VE GÜÇ" in messages_normal[0]["content"]

    # Alıştırma modunda sonuçlar gizli kalmalı, akım yönleri eklenmemeli
    messages_practice = build_messages(
        parsed=parsed,
        results=results,
        analysis_type=AnalysisType.NODAL,
        is_dc=True,
        frequency=None,
        terminals=None,
        question="Düğüm 2 gerilimi nedir?",
        history=[],
        practice=True,
        practice_questions=[],
    )
    assert "AKIM YÖNLERİ" not in messages_practice[0]["content"]
