"""
CircuitAnalyzer API — Port Empedansı İndirgeme Testleri

Test edilen modül: explainer/topology.py (reduce_port_impedance)
- DC ve AC port indirgeme (Thevenin / Norton empedansı)
- Merdiven devreleri (seri/paralel zinciri)
- Gerilim bölücü portu
- AC Köprü (Bridge) devresi eşdeğer empedansı
- Kısa devre ve sarkan (boşta kalan) elemanların elenmesi (kind="removed")
- DC kondansatör (açık devre) ve bobin (kısa devre + düğüm birleşimi) notları
- Kaynak uçları arasındaki port (empedans 0)
- İndirgenemeyen Wheatstone köprüsü (complete=False)
"""

import pytest

from explainer.topology import reduce_port_impedance
from parser.netlist_parser import parse_netlist
from tests.test_thevenin import BRIDGE, _bridge_expected, assert_close


def test_ladder_port_reduction():
    net = (
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
        "R3 2 3 1k\n"
        "R4 3 0 1k"
    )
    red = reduce_port_impedance(parse_netlist(net), "3", "0", is_dc=True)

    assert red.complete is True
    assert red.impedance is not None
    assert_close(red.impedance, 625.0)

    step_kinds = [s.kind for s in red.steps]
    assert step_kinds == ["parallel", "series", "parallel"]

    # Kaynak sıfırlama notu V1 kısa devre olduğunu belirtmeli
    v1_notes = [n for n in red.zeroing_notes if "V1" in n]
    assert len(v1_notes) >= 1
    assert any("kısa devre" in n for n in v1_notes)


def test_voltage_divider_port_reduction():
    net = (
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k"
    )
    red = reduce_port_impedance(parse_netlist(net), "2", "0", is_dc=True)

    assert red.complete is True
    assert red.impedance is not None
    assert_close(red.impedance, 2000.0 / 3.0)  # 666.67 Ω
    assert len(red.steps) == 1
    assert red.steps[0].kind == "parallel"


def test_ac_bridge_port_reduction():
    f, _, zth_expected = _bridge_expected()
    red = reduce_port_impedance(
        parse_netlist(BRIDGE), "2", "3", is_dc=False, frequency=f
    )

    assert red.complete is True
    assert red.impedance is not None
    assert_close(red.impedance, zth_expected, rel=1e-4)


def test_shorted_and_dangling_elements_removed():
    # R6, V1 kaynak uçları arasında olduğundan sıfırlanınca iki ucu aynı düğümde kalır
    # R5'in bir ucu (4) boşta kalır (başka eleman bağlı değil)
    net = (
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
        "R6 1 0 1k\n"
        "R5 2 4 1k"
    )
    red = reduce_port_impedance(parse_netlist(net), "2", "0", is_dc=True)

    removed_steps = [s for s in red.steps if s.kind == "removed"]
    removed_names = {s.elements[0] for s in removed_steps}

    assert "R6" in removed_names
    assert "R5" in removed_names

    r6_step = next(s for s in removed_steps if s.elements[0] == "R6")
    assert "kısa devre edildi" in r6_step.formula or "aynı düğüme" in r6_step.formula

    r5_step = next(s for s in removed_steps if s.elements[0] == "R5")
    assert "boşta kaldı" in r5_step.formula or "akım taşımaz" in r5_step.formula


def test_dc_capacitor_and_inductor_zeroing_notes():
    net = (
        "V1 1 0 DC 12\n"
        "C1 1 2 1u\n"
        "L1 2 3 10m\n"
        "R1 3 0 1k"
    )
    red = reduce_port_impedance(parse_netlist(net), "3", "0", is_dc=True)

    # C1 DC'de açık devre
    c1_notes = [n for n in red.zeroing_notes if "C1" in n]
    assert len(c1_notes) >= 1
    assert any("açık devre" in n for n in c1_notes)

    # L1 DC'de kısa devre ve düğüm birleştirme
    l1_notes = [n for n in red.zeroing_notes if "L1" in n]
    assert len(l1_notes) >= 1
    assert any("kısa devre" in n for n in l1_notes)
    assert any("birleşir" in n for n in l1_notes)


def test_port_across_voltage_source_has_zero_impedance():
    # Kaynak uçları arasındaki port (1, 0)
    net = (
        "V1 1 0 DC 12\n"
        "R1 1 0 1k"
    )
    red = reduce_port_impedance(parse_netlist(net), "1", "0", is_dc=True)

    assert red.complete is True
    assert red.impedance == 0j
    assert any("kısa devre ile birleşti" in n for n in red.zeroing_notes)


def test_wheatstone_reduces_with_delta_y():
    # Kaynaksız Wheatstone köprüsü seri/paralel ile indirgenemez; Δ→Y dönüşümüyle biter.
    # Dengeli köprü (hepsi 1k): (1k+1k) ∥ (1k+1k) = 1k
    net = (
        "R1 1 2 1k\n"
        "R2 1 3 1k\n"
        "R3 2 3 1k\n"
        "R4 2 0 1k\n"
        "R5 3 0 1k"
    )
    red = reduce_port_impedance(parse_netlist(net), "1", "0", is_dc=True)

    assert red.complete is True
    assert red.impedance == pytest.approx(1000)
    assert any(s.kind == "delta_y" for s in red.steps)
