"""RMS eki yalnızca AC kaynaklarda: yanlış satır reddedilir, uzun boşluklu satır ayrıştırıcıyı yavaşlatmaz."""

import time

import pytest

from parser.netlist_parser import parse_netlist


@pytest.mark.parametrize("line", ["R1 1 0 10 RMS", "R1 1 0 10 rms", "L1 1 0 1m\tRMS"])
def test_rms_suffix_rejected_on_non_ac_lines(line):
    parsed = parse_netlist(line)
    assert not parsed.elements
    assert "yalnızca AC kaynaklarda" in parsed.errors[0]


def test_rms_inside_an_id_is_not_a_suffix():
    assert not parse_netlist("R1 1 0 10").errors
    assert not any("RMS" in e for e in parse_netlist("XRMS").errors)


def test_long_whitespace_line_parses_quickly():
    # Eski düzenli ifade bu satırda 7 saniye sürüyordu (CodeQL: polynomial regex)
    line = "X1" + " " * 40000 + "y"
    start = time.perf_counter()
    parse_netlist(line)
    assert time.perf_counter() - start < 1.0
