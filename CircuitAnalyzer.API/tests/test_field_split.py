"""
SINE / AC_PHASOR / COMPLEX / POLAR alanlarını ayıran _split_fields:
- eski düzenli ifadeyle (\\s*,\\s*|\\s+) aynı sonucu verir;
- çok uzun boşluk dizilerinde yavaşlamaz (CodeQL: "polynomial regular expression").
"""
import re
import time

import pytest

from parser.netlist_parser import _split_fields, parse_netlist


def _old_split(text):
    return re.split(r"\s*,\s*|\s+", text.strip()) if text.strip() else []


@pytest.mark.parametrize("text", [
    "", "   ", "0 10 50", "0, 10, 50", "0 ,10 , 50", "0 10 50,", "0 10 50 ,  ",
    "1,,2", "1 ,  ,2", ",1", "  2m   1k\t3 ", "1meg,2u 3n", "5, 30", "a\t,\tb",
])
def test_same_result_as_old_regex(text):
    assert _split_fields(text) == _old_split(text)


def test_long_whitespace_is_fast():
    t0 = time.perf_counter()
    _split_fields("1" + " " * 200_000 + "x")
    assert time.perf_counter() - t0 < 0.5


def test_long_whitespace_in_sine_line_is_fast():
    net = "V1 1 0 SINE(0" + " " * 50_000 + "10 50)\nR1 1 0 100\n* GND1 - Referans toprak"
    t0 = time.perf_counter()
    parse_netlist(net)
    assert time.perf_counter() - t0 < 2.0
